import eventlet

eventlet.monkey_patch()

from flask import Flask, send_from_directory, request, jsonify, make_response
from flask_socketio import SocketIO, emit
import openai
from flask_cors import CORS
import os
from dotenv import load_dotenv
import logging
import asyncio
from weasyprint import HTML, CSS
from src.services.bill_scraper import BillScraper
from src.services.base_parser import BaseParser
from src.services.json_builder import JsonBuilder
from src.services.section_matcher import SectionMatcher
from src.services.impact_analyzer import ImpactAnalyzer
from src.services.report_generator import ReportGenerator
from src.models.practice_groups import PracticeGroups
from src.models.bill_components import TrailerBill
import sys

# Load environment variables
load_dotenv()

# Verify critical environment variables
if not os.getenv('OPENAI_API_KEY'):
    raise ValueError("OPENAI_API_KEY environment variable is not set")

openai.api_key = os.getenv("OPENAI_API_KEY")

# Configure logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)
logger.info("Environment variables loaded")

# Initialize Flask app and extensions
app = Flask(__name__, static_folder='frontend/dist', static_url_path='')
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://0.0.0.0:3000", "https://0.0.0.0:3000"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"],
        "expose_headers": ["Content-Type"]
    }
}, supports_credentials=True)

@app.after_request
def after_request(response):
    logger.info(f"Response headers: {dict(response.headers)}")
    return response

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

class AnalysisProgressHandler:
    def __init__(self, socket):
        self.socket = socket
        self.current_step = 0
        self.total_steps = 5
        self.current_substep = 0
        self.total_substeps = 0

    def update_progress(self, step, message, substep=None, total_substeps=None):
        self.current_step = step
        if substep is not None:
            self.current_substep = substep
            self.total_substeps = total_substeps if total_substeps else 0

        logger.info(f"Progress: Step {step} - {message}")
        self.socket.emit('analysis_progress', {
            'step': step,
            'message': message,
            'current_substep': self.current_substep,
            'total_substeps': self.total_substeps
        })

def trailer_bill_to_dict(bill: TrailerBill) -> dict:
    """
    Convert the parsed TrailerBill object into a dictionary
    that has a 'bill_sections' key for the report generator.
    """
    sections_dict = {}
    for bs in bill.bill_sections:
        code_mods = []
        for ref in bs.code_references:
            code_mods.append({
                "code_name": ref.code_name,
                "section": ref.section,
                "action": getattr(ref, "action", None)
            })
        sections_dict[bs.number] = {
            "text": bs.text,
            "code_modifications": code_mods
        }

    return {
        "bill_sections": sections_dict
    }

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/analyze', methods=['POST'])
def analyze_bill():
    try:
        logger.info(f"Received request: {request.method} {request.path}")
        logger.info(f"Request headers: {dict(request.headers)}")
        logger.info(f"Request data: {request.get_data(as_text=True)}")

        data = request.json
        logger.info(f"Parsed JSON data: {data}")

        bill_number = data.get('billNumber')
        if not bill_number:
            logger.error("Bill number is missing from request")
            return jsonify({'error': 'Bill number is required'}), 400

        logger.info(f"Starting analysis for bill {bill_number}")

        # Start async analysis in background
        socketio.start_background_task(
            target=lambda: asyncio.run(process_bill_analysis(bill_number))
        )

        return jsonify({
            'status': 'processing',
            'billNumber': bill_number
        })

    except Exception as e:
        logger.error(f"Error in analyze_bill: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/reports/<filename>')
def serve_report(filename):
    reports_dir = os.path.join(app.root_path, 'reports')
    return send_from_directory(reports_dir, filename)

@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

async def process_bill_analysis(bill_number):
    progress = AnalysisProgressHandler(socketio)
    try:
        # Step 1: Fetch bill text
        progress.update_progress(1, "Fetching bill text")
        bill_scraper = BillScraper(max_retries=3, timeout=30)
        bill_text_response = await bill_scraper.get_bill_text(bill_number, 2024)
        bill_text = bill_text_response['full_text']

        # Step 2: Initial parsing
        progress.update_progress(2, "Parsing bill components")
        parser = BaseParser()
        parsed_bill = parser.parse_bill(bill_text)

        # Step 3: Build analysis structure
        progress.update_progress(3, "Building analysis structure")
        json_builder = JsonBuilder()
        skeleton = json_builder.create_skeleton(parsed_bill.digest_sections)

        # Step 4: AI Analysis
        progress.update_progress(4, "Starting AI analysis", 0, len(parsed_bill.digest_sections))
        client = openai
        matcher = SectionMatcher(openai_client=client)
        practice_groups = PracticeGroups()
        analyzer = ImpactAnalyzer(openai_client=client, practice_groups_data=practice_groups)

        # Match sections
        skeleton = await matcher.match_sections(skeleton, bill_text)

        # Analyze changes
        analyzed_skeleton = await analyzer.analyze_changes(parsed_bill, skeleton)

        # Step 5: Generate report
        progress.update_progress(5, "Generating final report")
        report_gen = ReportGenerator()

        parsed_bill_dict = trailer_bill_to_dict(parsed_bill)

        report = report_gen.generate_report(
            analyzed_skeleton,
            {
                'bill_number': bill_number,
                'title': parsed_bill.title,
                'chapter_number': parsed_bill.chapter_number,
                'date_approved': parsed_bill.date_approved.isoformat() if parsed_bill.date_approved else None
            },
            parsed_bill_dict
        )

        report_filename = f"bill_analysis_{bill_number}.html"
        os.makedirs('reports', exist_ok=True)
        report_path = os.path.join('reports', report_filename)
        report_gen.save_report(report, report_path)

        logger.info(f"Analysis completed for bill {bill_number}")
        socketio.emit('analysis_complete', {
            'status': 'complete',
            'report_url': f'/api/reports/{report_filename}',
            'billNumber': bill_number
        })

    except Exception as e:
        logger.error(f"Error in process_bill_analysis: {str(e)}")
        socketio.emit('analysis_error', {
            'error': str(e),
            'billNumber': bill_number
        })

@app.route('/api/reports/<filename>.pdf')
def serve_pdf_report(filename):
    try:
        html_path = os.path.join(app.root_path, 'reports', f'{filename}.html')
        if not os.path.exists(html_path):
            logger.error(f"Report file not found: {html_path}")
            return jsonify({'error': 'Report not found'}), 404

        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        report_gen = ReportGenerator()
        try:
            html = HTML(string=html_content)
            css = CSS(string=report_gen.css_styles)
            pdf_content = html.write_pdf(stylesheets=[css])
        except Exception as e:
            logger.error(f"PDF generation error: {str(e)}")
            logger.exception("Full traceback:")
            return jsonify({'error': 'Failed to generate PDF'}), 500

        response = make_response(pdf_content)
        response.headers.set('Content-Type', 'application/pdf')
        response.headers.set('Content-Disposition', 'attachment', filename=f'{filename}.pdf')

        return response

    except Exception as e:
        logger.error(f"Error in PDF endpoint: {str(e)}")
        logger.exception("Full traceback:")
        return jsonify({'error': 'Failed to generate PDF'}), 500

if __name__ == '__main__':
    os.makedirs('reports', exist_ok=True)

    if not os.path.exists('frontend/dist'):
        logger.info("Building frontend...")
        os.system('cd frontend && npm install && npm run build')

    port = int(os.environ.get('PORT', 8080))

    logger.info(f"Starting server on port {port}...")
    socketio.run(app, host='0.0.0.0', port=port, debug=True)
