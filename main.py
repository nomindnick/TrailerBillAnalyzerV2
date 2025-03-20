import argparse
import logging
import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO
from openai import OpenAI
from anthropic import AsyncAnthropic

# Import services
from src.services.bill_scraper import BillScraper
from src.services.base_parser import BaseParser
from src.services.json_builder import JsonBuilder
from src.services.section_matcher import SectionMatcher
from src.services.impact_analyzer import ImpactAnalyzer  # Assuming you have this service
from src.services.report_generator import ReportGenerator  # Assuming you have this service
from src.models.practice_groups import PracticeGroups

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

# Create Flask app
app = Flask(__name__, static_folder='frontend/dist')
CORS(app)  # Enable CORS for development
socketio = SocketIO(app, 
                   cors_allowed_origins="*", 
                   ping_timeout=120,  # Increase ping timeout 
                   ping_interval=15,  # More frequent pings
                   reconnection=True, 
                   reconnection_attempts=10, 
                   reconnection_delay=1, 
                   reconnection_delay_max=5,
                   async_mode='threading')  # Use threading mode for better reliability

# Create directory for reports
REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(exist_ok=True)

# Initialize services
bill_scraper = BillScraper()
bill_parser = BaseParser()
json_builder = JsonBuilder()

# Initialize OpenAI client (if used)
try:
    import openai
    openai_client = openai.AsyncClient(api_key=os.environ.get('OPENAI_API_KEY'))
    logger.info("OpenAI client initialized")
except (ImportError, Exception) as e:
    logger.warning(f"OpenAI client initialization failed: {str(e)}")
    openai_client = None

# Initialize Anthropic client (if used)
try:
    import anthropic
    anthropic_client = anthropic.AsyncClient(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    logger.info("Anthropic client initialized")
except (ImportError, Exception) as e:
    logger.warning(f"Anthropic client initialization failed: {str(e)}")
    anthropic_client = None

# Progress handler class for tracking analysis progress
class ProgressHandler:
    def __init__(self, socketio, analysis_id=None):
        self.socketio = socketio
        self.logger = logging.getLogger(__name__)
        self.analysis_id = analysis_id

    def update_progress(self, step, message, current_substep=None, total_substeps=None):
        """Send progress update to client"""
        data = {
            'step': step,
            'message': message
        }

        if current_substep is not None and total_substeps is not None:
            data['current_substep'] = current_substep
            data['total_substeps'] = total_substeps

        # Include analysis ID if available
        if self.analysis_id:
            data['analysis_id'] = self.analysis_id

        self.logger.info(f"Emitting progress: step={step}, message={message}, data={data}")
        self.socketio.emit('analysis_progress', data)

    def update_substep(self, current, message=None):
        """Update just the substep progress"""
        data = {'current_substep': current}
        if message:
            data['message'] = message

        # Include analysis ID if available
        if self.analysis_id:
            data['analysis_id'] = self.analysis_id

        self.logger.info(f"Emitting substep update: current={current}, message={message}")
        self.socketio.emit('analysis_progress', data)

# API Routes
@app.route('/api/analyze', methods=['POST'])
def analyze_bill():
    """API endpoint to analyze a bill"""
    data = request.json
    if not data or 'billNumber' not in data:
        return jsonify({'error': 'Bill number is required'}), 400

    bill_number = data.get('billNumber')
    session_year = data.get('sessionYear', '2023-2024')
    model = data.get('model', 'gpt-4o-2024-08-06')
    analysis_id = data.get('analysisId')  # Get the analysis ID

    # Determine if we should use Anthropic based on the model name
    use_anthropic = model.startswith('claude')

    # Start async bill analysis in the background
    def run_async_analysis():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # Use named parameters to avoid order issues
        loop.run_until_complete(
            analyze_bill_async(
                bill_number=bill_number, 
                year=session_year, 
                use_anthropic=use_anthropic, 
                model=model,
                analysis_id=analysis_id  # Make sure parameter names match function definition
            )
        )
        loop.close()

    socketio.start_background_task(run_async_analysis)

    return jsonify({'status': 'Analysis started', 'analysisId': analysis_id})

@app.route('/reports/<path:filename>')
def serve_report(filename):
    """Serve generated reports"""
    if filename.endswith('.pdf'):
        # Get corresponding HTML file
        html_file = filename.replace('.pdf', '.html')
        html_path = os.path.join(REPORTS_DIR, html_file)

        if not os.path.exists(html_path):
            return 'HTML report not found', 404

        # Generate PDF from HTML using WeasyPrint
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
    """Check if a report exists for the given bill number"""
    try:
        # Find the latest report for this bill
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
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# Serve frontend static files
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(app.static_folder + '/' + path):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

async def analyze_bill_async(bill_number, year, use_anthropic=False, model=None, analysis_id=None, progress_handler=None):
    """Asynchronous bill analysis"""
    try:
        # Create progress handler if not provided
        if progress_handler is None:
            progress_handler = ProgressHandler(socketio, analysis_id)  # Pass analysis_id to handler

        # Update initial progress
        progress_handler.update_progress(1, "Starting bill analysis")

        # Set default model if not specified, but don't override a provided model
        if model is None:
            model = "claude-3-sonnet-20240229" if use_anthropic else "gpt-4o-2024-08-06"

        # Always calculate use_anthropic based on the final model name to ensure consistency
        use_anthropic = model.startswith("claude")

        # Create clients
        from openai import OpenAI
        openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        anthropic_client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

        logger.info(f"Using model: {model} for analysis (use_anthropic={use_anthropic})")

        # Create bill scraper
        bill_scraper = BillScraper()

        # Fetch bill data
        progress_handler.update_progress(1, "Fetching bill text")
        bill_data = await bill_scraper.get_bill_text(bill_number, year)
        bill_text = bill_data["full_text"]

        # Create parser
        bill_parser = BaseParser()

        # Parse bill
        progress_handler.update_progress(2, "Parsing bill text")
        parsed_bill = bill_parser.parse_bill(bill_text)

        # Load practice groups
        practice_groups = PracticeGroups()

        # Create section matcher with specified model
        section_matcher = SectionMatcher(openai_client, model=model, anthropic_client=anthropic_client)

        # Create JSON builder
        json_builder = JsonBuilder()

        # Build skeleton from parsed bill
        progress_handler.update_progress(3, "Building analysis structure")
        skeleton = json_builder.create_skeleton(parsed_bill.digest_sections, parsed_bill.bill_sections)

        # Match sections to digest items
        matched_skeleton = await section_matcher.match_sections(skeleton, bill_text, progress_handler)

        # Create impact analyzer with the SAME model as the section matcher
        impact_analyzer = ImpactAnalyzer(openai_client, practice_groups, model=model, anthropic_client=anthropic_client)

        # Analyze impacts
        analyzed_skeleton = await impact_analyzer.analyze_changes(matched_skeleton, progress_handler)

        # Update metadata
        final_skeleton = json_builder.update_metadata(analyzed_skeleton)

        # Extract bill info
        bill_info = {
            "bill_number": bill_number,
            "chapter_number": parsed_bill.chapter_number,
            "title": parsed_bill.title,
            "date_approved": parsed_bill.date_approved,
            "model": model
        }

        # Generate report
        progress_handler.update_progress(5, "Generating final report")
        report_generator = ReportGenerator()
        report_html = report_generator.generate_report(final_skeleton, bill_info, bill_text)

        # Save report
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = f"reports/{bill_number}_{timestamp}.html"
        os.makedirs("reports", exist_ok=True)
        report_generator.save_report(report_html, report_path)

        # Emit completion event with report URL - make multiple attempts
        logger.info(f"Analysis complete, report saved to {report_path}")
        report_url = f"/reports/{os.path.basename(report_path)}"
        completion_data = {
            'report_url': report_url,
            'analysis_id': analysis_id  # Include analysis ID
        }

        # Save completion data to a JSON file that can be polled by the frontend
        # as a fallback mechanism
        try:
            import json
            completion_json_path = f"reports/{bill_number}_latest.json"
            with open(completion_json_path, 'w') as f:
                json.dump(completion_data, f)
            logger.info(f"Saved completion data to {completion_json_path}")
        except Exception as json_err:
            logger.error(f"Error saving completion JSON: {str(json_err)}")

        # Make multiple attempts to emit the completion event to increase reliability
        max_emit_attempts = 3
        for attempt in range(max_emit_attempts):
            try:
                logger.info(f"Emitting analysis_complete event (attempt {attempt+1}/{max_emit_attempts})")
                socketio.emit('analysis_complete', completion_data)
                # Sleep briefly between attempts
                if attempt < max_emit_attempts - 1:
                    await asyncio.sleep(1)
            except Exception as emit_err:
                logger.error(f"Error emitting completion event (attempt {attempt+1}): {str(emit_err)}")

        # Return data for frontend
        return {
            "status": "success",
            "report_path": report_path,
            "bill_number": bill_number,
            "chapter_number": parsed_bill.chapter_number,
            "title": parsed_bill.title,
            "analyzed_data": final_skeleton
        }
    except Exception as e:
        logger.error(f"Error analyzing bill: {str(e)}", exc_info=True)
        # Emit error event
        socketio.emit('analysis_error', {
            'error': str(e)
        })
        return {"status": "error", "message": str(e)}

def run_cli(bill_number, year, output):
    """Run bill analysis from command line"""
    output_dir = Path(output)
    output_dir.mkdir(exist_ok=True)

    logger.info(f"Starting CLI analysis of bill {bill_number} from {year}")

    try:
        # Use asyncio to run the async functions
        loop = asyncio.get_event_loop()

        # Get bill text
        bill_data = loop.run_until_complete(bill_scraper.get_bill_text(bill_number, year))

        if not bill_data or not bill_data.get('full_text'):
            logger.error(f"Failed to retrieve bill text for {bill_number}")
            return 1

        bill_text = bill_data['full_text']
        logger.info(f"Retrieved bill text ({len(bill_text)} characters)")

        # Parse bill
        parsed_bill = bill_parser.parse_bill(bill_text)
        logger.info(f"Parsed bill with {len(parsed_bill.digest_sections)} digest sections")

        # Save parsed bill to file
        output_file = output_dir / f"{bill_number}_parsed.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"Bill Number: {bill_number}\n")
            f.write(f"Title: {parsed_bill.title}\n\n")

            f.write(f"Digest Sections: {len(parsed_bill.digest_sections)}\n")
            for i, section in enumerate(parsed_bill.digest_sections):
                f.write(f"\nDigest Section {section.number}:\n")
                f.write(f"{section.text}\n")

            f.write(f"\nBill Sections: {len(parsed_bill.bill_sections)}\n")
            for i, section in enumerate(parsed_bill.bill_sections):
                f.write(f"\n{section.original_label}\n")
                f.write(f"{section.text[:200]}...\n")

        logger.info(f"Analysis saved to {output_file}")
        return 0

    except Exception as e:
        logger.error(f"CLI error: {str(e)}", exc_info=True)
        return 1

@socketio.on('ping')
def handle_ping(data):
    """Handle ping from client to keep connection alive"""
    logger.debug(f"Received ping from client {request.sid}: {data}")
    # Reply directly to the client who sent the ping
    socketio.emit('pong', {'timestamp': data.get('timestamp'), 'server_time': datetime.now().isoformat()}, room=request.sid)

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info(f"Client connected: {request.sid}")
    # Send a welcome message to confirm connection
    socketio.emit('connection_established', {'status': 'connected', 'sid': request.sid}, room=request.sid)

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info(f"Client disconnected: {request.sid}")

@socketio.on_error()
def handle_error(e):
    """Handle socket errors"""
    logger.error(f"Socket.IO error for {request.sid}: {str(e)}")

if __name__ == "__main__":
    # Check if running as CLI or web server
    parser = argparse.ArgumentParser(description='Analyze California trailer bills')
    parser.add_argument('bill_number', nargs='?', help='The bill number to analyze (e.g., AB173)')
    parser.add_argument('--year', type=int, default=2023, help='Year of the legislative session')
    parser.add_argument('--output', type=str, default='output', help='Output directory')
    parser.add_argument('--server', action='store_true', help='Run as web server')

    # If no args provided, default to server mode
    if len(sys.argv) == 1:
        sys.argv.append('--server')

    args = parser.parse_args()

    # If --server flag is set or no bill_number is provided, run as web server
    if args.server or not args.bill_number:
        # Default to port 8080, but use environment variable if set
        port = int(os.environ.get('PORT', 8080))
        logger.info(f"Starting web server on port {port}")
        socketio.run(app, host='0.0.0.0', port=port, debug=True)
    else:
        # Run as CLI tool
        exit_code = run_cli(args.bill_number, args.year, args.output)
        exit(exit_code)