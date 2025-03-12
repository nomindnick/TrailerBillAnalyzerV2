import argparse
import logging
import asyncio
import os
import sys
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO

# Import services
from src.services.bill_scraper import BillScraper
from src.services.base_parser import BaseParser
from src.services.json_builder import JsonBuilder
from src.services.section_matcher import SectionMatcher
from src.services.impact_analyzer import ImpactAnalyzer  # Assuming you have this service
from src.services.report_generator import ReportGenerator  # Assuming you have this service

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
socketio = SocketIO(app, cors_allowed_origins="*")

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
    def __init__(self, socketio):
        self.socketio = socketio

    def update_progress(self, step, message, current_substep=None, total_substeps=None):
        """Send progress update to client"""
        data = {
            'step': step,
            'message': message
        }

        if current_substep is not None and total_substeps is not None:
            data['current_substep'] = current_substep
            data['total_substeps'] = total_substeps

        self.socketio.emit('analysis_progress', data)

    def update_substep(self, current, message=None):
        """Update just the substep progress"""
        data = {'current_substep': current}
        if message:
            data['message'] = message
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

    # Start async bill analysis in the background
    socketio.start_background_task(
        analyze_bill_async, bill_number, session_year, model
    )

    return jsonify({'status': 'Analysis started'})

@app.route('/reports/<path:filename>')
def serve_report(filename):
    """Serve generated reports"""
    return send_from_directory(REPORTS_DIR, filename)

# Serve frontend static files
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(app.static_folder + '/' + path):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

async def analyze_bill_async(bill_number, session_year, model):
    """Run bill analysis asynchronously and emit progress via Socket.IO"""
    progress_handler = ProgressHandler(socketio)
    report_url = None

    try:
        # Extract year from session year (e.g., 2023 from "2023-2024")
        year = int(session_year.split('-')[0])

        # Step 1: Fetch bill text
        progress_handler.update_progress(1, f"Fetching bill {bill_number} from {year}")
        bill_data = await bill_scraper.get_bill_text(bill_number, year)

        if not bill_data or not bill_data.get('full_text'):
            raise ValueError(f"Failed to retrieve bill text for {bill_number}")

        bill_text = bill_data['full_text']
        progress_handler.update_progress(1, f"Retrieved bill text ({len(bill_text)} characters)")

        # Step 2: Parse bill
        progress_handler.update_progress(2, f"Parsing bill components")
        parsed_bill = bill_parser.parse_bill(bill_text)

        digest_count = len(parsed_bill.digest_sections)
        section_count = len(parsed_bill.bill_sections)
        progress_handler.update_progress(2, f"Identified {digest_count} digest sections and {section_count} bill sections")

        # Step 3: Build analysis skeleton
        progress_handler.update_progress(3, "Creating analysis structure")
        skeleton = json_builder.create_skeleton(parsed_bill.digest_sections, parsed_bill.bill_sections)
        progress_handler.update_progress(3, f"Created initial structure with {len(skeleton['changes'])} changes")

        # Step 4: AI Analysis - match sections
        progress_handler.update_progress(4, "Matching digest items to bill sections")

        # Determine which AI client to use based on model name
        ai_client = anthropic_client if model.startswith("claude") else openai_client

        if not ai_client:
            raise ValueError(f"AI client for model {model} is not available")

        section_matcher = SectionMatcher(openai_client, model, anthropic_client)
        updated_skeleton = await section_matcher.match_sections(
            skeleton, 
            bill_text, 
            progress_handler
        )

        # Step 4 continued: Analyze impacts
        progress_handler.update_progress(4, "Analyzing impacts on public agencies")

        impact_analyzer = ImpactAnalyzer(openai_client, model, anthropic_client)
        analysis_result = await impact_analyzer.analyze_impacts(
            updated_skeleton,
            parsed_bill,
            progress_handler
        )

        # Step 5: Generate report
        progress_handler.update_progress(5, "Generating final report")

        report_generator = ReportGenerator(REPORTS_DIR)
        report_file = report_generator.generate_report(
            analysis_result,
            parsed_bill,
            bill_number,
            model
        )

        report_url = f"/reports/{os.path.basename(report_file)}"
        progress_handler.update_progress(5, "Report generation complete")

        # Notify client of completion
        socketio.emit('analysis_complete', {
            'report_url': report_url,
            'bill_number': bill_number
        })

    except Exception as e:
        logger.error(f"Error analyzing bill: {str(e)}", exc_info=True)
        socketio.emit('analysis_error', {'error': str(e)})

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