# main.py

import argparse
import logging
import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime
import eventlet
eventlet.monkey_patch()

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO

# Import services
from src.services.bill_scraper import BillScraper
from src.services.base_parser import BaseParser
from src.services.json_builder import JsonBuilder
from src.services.impact_analyzer import ImpactAnalyzer
from src.services.report_generator import ReportGenerator
from src.models.practice_groups import PracticeGroups
from src.services.embeddings_matcher import EmbeddingsMatcher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log")
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='frontend/dist')
CORS(app)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_timeout=300,
    ping_interval=10,
    reconnection=True,
    reconnection_attempts=0,
    reconnection_delay=0.5,
    reconnection_delay_max=2,
    async_mode='eventlet',
    async_handlers=True,
    manage_session=False,
    max_http_buffer_size=1e8,
    transports=['websocket'],
    logger=True,
    engineio_logger=True
)

REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(exist_ok=True)

# Initialize services
bill_scraper = BillScraper()
bill_parser = BaseParser()
json_builder = JsonBuilder()

# We no longer patch openai proxies here, but you can keep your patches if needed.
# ...
try:
    import openai
    openai_client = openai.AsyncClient(api_key=os.environ.get('OPENAI_API_KEY'))
    logger.info("OpenAI client initialized")
except Exception as e:
    logger.warning(f"OpenAI client initialization failed: {str(e)}")
    openai_client = None

# Initialize Anthropic if still needed, but for embeddings we typically won't.
# ...

class ProgressHandler:
    def __init__(self, socketio, analysis_id=None):
        self.socketio = socketio
        self.logger = logging.getLogger(__name__)
        self.analysis_id = analysis_id

    def update_progress(self, step, message, current_substep=None, total_substeps=None):
        data = {
            'step': step,
            'message': message
        }
        if current_substep is not None and total_substeps is not None:
            data['current_substep'] = current_substep
            data['total_substeps'] = total_substeps
        if self.analysis_id:
            data['analysis_id'] = self.analysis_id

        self.logger.info(f"Emitting progress: step={step}, message={message}, data={data}")
        self.socketio.emit('analysis_progress', data)

    def update_substep(self, current, message=None):
        data = {'current_substep': current}
        if message:
            data['message'] = message
        if self.analysis_id:
            data['analysis_id'] = self.analysis_id
        
        self.logger.info(f"Emitting substep update: current={current}, message={message}")
        self.socketio.emit('analysis_progress', data)

@app.route('/api/analyze', methods=['POST'])
def analyze_bill():
    """API endpoint to analyze a bill"""
    data = request.json
    if not data or 'billNumber' not in data:
        return jsonify({'error': 'Bill number is required'}), 400

    bill_number = data.get('billNumber')
    session_year = data.get('sessionYear', '2023-2024')
    model = data.get('model', 'gpt-4o-2024-08-06')
    analysis_id = data.get('analysisId')

    def run_async_analysis():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(
            analyze_bill_async(
                bill_number=bill_number,
                year=session_year,
                model=model,
                analysis_id=analysis_id
            )
        )
        loop.close()

    socketio.start_background_task(run_async_analysis)

    return jsonify({'status': 'Analysis started', 'analysisId': analysis_id})

@app.route('/reports/<path:filename>')
def serve_report(filename):
    if filename.endswith('.pdf'):
        html_file = filename.replace('.pdf', '.html')
        html_path = os.path.join(REPORTS_DIR, html_file)
        if not os.path.exists(html_path):
            return 'HTML report not found', 404
        from weasyprint import HTML
        pdf_path = os.path.join(REPORTS_DIR, filename)
        try:
            HTML(html_path).write_pdf(pdf_path)
            return send_from_directory(REPORTS_DIR, filename)
        except Exception as e:
            logger.error(f"PDF generation failed: {str(e)}")
            return 'PDF generation failed', 500
    return send_from_directory(REPORTS_DIR, filename)

@app.route('/api/report-status/<bill_number>')
def check_report_status(bill_number):
    try:
        import glob
        import os
        report_pattern = os.path.join(REPORTS_DIR, f"{bill_number}_*.html")
        reports = sorted(glob.glob(report_pattern), key=os.path.getmtime, reverse=True)
        if reports:
            latest_report = os.path.basename(reports[0])
            return jsonify({
                'status': 'complete',
                'report_url': f"/reports/{latest_report}"
            })
        else:
            return jsonify({
                'status': 'pending',
                'message': 'No report found yet'
            })
    except Exception as e:
        logger.error(f"Error checking report status: {str(e)}")
        return jsonify({'status': 'error','message': str(e)}), 500

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(app.static_folder + '/' + path):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

async def analyze_bill_async(bill_number, year, model=None, analysis_id=None):
    progress_handler = ProgressHandler(socketio, analysis_id)
    try:
        progress_handler.update_progress(1, "Starting bill analysis")

        # Create default model if not provided
        if model is None:
            model = "text-embedding-3-large"

        # 1. Fetch Bill Text
        progress_handler.update_progress(1, "Fetching bill text")
        bill_data = await bill_scraper.get_bill_text(bill_number, year)
        bill_text = bill_data["full_text"]

        # 2. Parse Bill
        progress_handler.update_progress(2, "Parsing bill text")
        parsed_bill = bill_parser.parse_bill(bill_text)

        # 3. Build JSON skeleton
        progress_handler.update_progress(3, "Building analysis structure")
        skeleton = json_builder.create_skeleton(
            parsed_bill.digest_sections,
            parsed_bill.bill_sections
        )

        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        # 4. Embeddings-based matching
        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        progress_handler.update_progress(4, "Performing embeddings-based matching")
        emb_matcher = EmbeddingsMatcher()
        # We also need practice groups loaded for assignment
        practice_groups = PracticeGroups()
        # Prepare the practice group embeddings
        await emb_matcher.prepare_practice_group_embeddings([
            {"name": pg.name, "description": pg.description}
            for pg in practice_groups.groups.values()
        ])

        # First, match sections
        skeleton = await emb_matcher.match_digest_sections(skeleton, progress_handler=progress_handler)

        # Assign practice groups
        skeleton = await emb_matcher.assign_practice_groups(skeleton)

        # Identify local agency type
        skeleton = await emb_matcher.identify_local_agency_types(skeleton)

        # 5. Impact Analysis (only for changes that do have a local agency)
        progress_handler.update_progress(5, "Analyzing local agency impacts")
        impact_analyzer = ImpactAnalyzer(openai_client, practice_groups, model=model)
        # For each change, if change["local_agency_type"] is None, skip LLM
        # The ImpactAnalyzer code will handle that logic internally (we'll see below).
        skeleton = await impact_analyzer.analyze_changes(skeleton, progress_handler)

        # 6. Update metadata
        skeleton = json_builder.update_metadata(skeleton)

        # 7. Generate Report
        progress_handler.update_progress(6, "Generating final report")
        bill_info = {
            "bill_number": bill_number,
            "chapter_number": parsed_bill.chapter_number,
            "title": parsed_bill.title,
            "date_approved": parsed_bill.date_approved,
            "model": model
        }
        report_generator = ReportGenerator()
        report_html = report_generator.generate_report(skeleton, bill_info, bill_text)

        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = f"reports/{bill_number}_{timestamp}.html"
        os.makedirs("reports", exist_ok=True)
        report_generator.save_report(report_html, report_path)

        logger.info(f"Analysis complete, report saved to {report_path}")
        report_url = f"/reports/{os.path.basename(report_path)}"
        completion_data = {'report_url': report_url, 'analysis_id': analysis_id}

        import json
        completion_json_path = f"reports/{bill_number}_latest.json"
        with open(completion_json_path, 'w') as f:
            json.dump(completion_data, f)

        # Emit final event
        socketio.emit('analysis_complete', completion_data)

        return {
            "status": "success",
            "report_path": report_path,
            "bill_number": bill_number,
            "chapter_number": parsed_bill.chapter_number,
            "title": parsed_bill.title,
            "analyzed_data": skeleton
        }
    except Exception as e:
        logger.error(f"Error analyzing bill: {str(e)}", exc_info=True)
        socketio.emit('analysis_error', {'error': str(e)})
        return {"status": "error", "message": str(e)}

@socketio.on('ping')
def handle_ping(data):
    logger.debug(f"Received ping from client {request.sid}: {data}")
    socketio.emit('pong', {'timestamp': data.get('timestamp'), 'server_time': datetime.now().isoformat()}, room=request.sid)

@socketio.on('connect')
def handle_connect():
    logger.info(f"Client connected: {request.sid}")
    socketio.emit('connection_established', {'status': 'connected', 'sid': request.sid}, room=request.sid)

@socketio.on('disconnect')
def handle_disconnect():
    logger.info(f"Client disconnected: {request.sid}")

@socketio.on_error()
def handle_error(e):
    logger.error(f"Socket.IO error for {request.sid}: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Analyze California trailer bills')
    parser.add_argument('bill_number', nargs='?', help='The bill number to analyze (e.g., AB173)')
    parser.add_argument('--year', type=int, default=2023, help='Year of the legislative session')
    parser.add_argument('--output', type=str, default='output', help='Output directory')
    parser.add_argument('--server', action='store_true', help='Run as web server')

    if len(sys.argv) == 1:
        sys.argv.append('--server')

    args = parser.parse_args()
    if args.server or not args.bill_number:
        port = int(os.environ.get('PORT', 8080))
        logger.info(f"Starting web server on port {port}")
        socketio.run(app, host='0.0.0.0', port=port, debug=True)
    else:
        # CLI mode
        logger.info("CLI mode not yet updated for embeddings. Using basic parse only.")
        sys.exit(0)
