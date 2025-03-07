import asyncio
import logging
import os
import sys
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('parser_test.log')
    ]
)

logger = logging.getLogger("parser_test")

# Add project root to path to enable imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the components we need to test
from src.services.bill_scraper import BillScraper
from src.services.base_parser import BaseParser

async def test_parser():
    """
    Test the BaseParser with AB114 from 2023-2024 session to validate
    parsing of digest sections and bill sections.
    """
    # Set the bill info
    bill_number = "AB114"
    session_year = 2023  # For 2023-2024 session

    logger.info(f"Starting parser test for {bill_number} from {session_year}-{session_year+1} session")

    try:
        # 1. Fetch the bill text
        logger.info("Fetching bill text...")
        scraper = BillScraper()
        bill_response = await scraper.get_bill_text(bill_number, session_year)

        if not bill_response or 'full_text' not in bill_response:
            logger.error("Failed to retrieve bill text")
            return

        bill_text = bill_response['full_text']
        logger.info(f"Successfully retrieved bill text ({len(bill_text)} characters)")

        # Save the raw bill text for reference
        with open("raw_bill_text.txt", "w", encoding="utf-8") as f:
            f.write(bill_text)
        logger.info("Saved raw bill text to 'raw_bill_text.txt'")

        # 2. Parse the bill
        logger.info("Parsing bill with BaseParser...")
        parser = BaseParser()
        parsed_bill = parser.parse_bill(bill_text)

        # 3. Report on the parsing results
        logger.info("Parsing complete. Generating report...")

        report = "=" * 80 + "\n"
        report += f"PARSER TEST REPORT: {bill_number} ({session_year}-{session_year+1})\n"
        report += f"Test run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        report += "=" * 80 + "\n\n"

        # Basic bill info
        report += "BILL INFORMATION\n"
        report += "-" * 50 + "\n"
        report += f"Bill Number: {parsed_bill.bill_number}\n"
        report += f"Chapter Number: {parsed_bill.chapter_number}\n"
        report += f"Title: {parsed_bill.title[:100]}...\n"  # First 100 chars
        report += f"Date Approved: {parsed_bill.date_approved}\n"
        report += f"Date Filed: {parsed_bill.date_filed}\n\n"

        # Digest sections
        report += "DIGEST SECTIONS\n"
        report += "-" * 50 + "\n"
        report += f"Total Digest Sections Found: {len(parsed_bill.digest_sections)}\n\n"

        for i, section in enumerate(parsed_bill.digest_sections):
            report += f"Digest Section {section.number}:\n"
            report += f"  Text Preview: {section.text[:100]}...\n"
            report += f"  Code References: {[f'{ref.code_name} {ref.section}' for ref in section.code_references]}\n"
            report += f"  Bill Sections: {section.bill_sections}\n"
            report += "\n"

        # Bill sections
        report += "BILL SECTIONS\n"
        report += "-" * 50 + "\n"
        report += f"Total Bill Sections Found: {len(parsed_bill.bill_sections)}\n\n"

        for i, section in enumerate(parsed_bill.bill_sections):
            report += f"Bill Section {section.number} (Original Label: {section.original_label}):\n"
            report += f"  Text Preview: {section.text[:100]}...\n"
            report += f"  Code References: {[f'{ref.code_name} {ref.section}' for ref in section.code_references]}\n"
            report += f"  Digest Reference: {section.digest_reference}\n"
            report += "\n"

        # Section matches
        matched_digest = sum(1 for s in parsed_bill.digest_sections if s.bill_sections)
        matched_bill = sum(1 for s in parsed_bill.bill_sections if s.digest_reference)

        report += "MATCHING SUMMARY\n"
        report += "-" * 50 + "\n"
        report += f"Digest Sections with Bill Section Matches: {matched_digest}/{len(parsed_bill.digest_sections)}\n"
        report += f"Bill Sections with Digest Reference: {matched_bill}/{len(parsed_bill.bill_sections)}\n\n"

        # Save the report
        with open("parser_test_report.txt", "w", encoding="utf-8") as f:
            f.write(report)

        logger.info("Test report saved to 'parser_test_report.txt'")

        # Print summary to console
        print("\nPARSER TEST SUMMARY")
        print("-" * 50)
        print(f"Bill: {bill_number} ({session_year}-{session_year+1})")
        print(f"Digest Sections Found: {len(parsed_bill.digest_sections)}")
        print(f"Bill Sections Found: {len(parsed_bill.bill_sections)}")
        print(f"Digest Sections Matched: {matched_digest}/{len(parsed_bill.digest_sections)}")
        print(f"Bill Sections Matched: {matched_bill}/{len(parsed_bill.bill_sections)}")
        print("\nDetailed report saved to 'parser_test_report.txt'")
        print("Raw bill text saved to 'raw_bill_text.txt'")
        print("See 'parser_test.log' for detailed logging output")

    except Exception as e:
        logger.error(f"Error during parser test: {str(e)}", exc_info=True)
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    # Set up asyncio event loop handling based on platform
    if sys.platform == 'win32':
        # Windows-specific event loop policy
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Run the async test function
    asyncio.run(test_parser())