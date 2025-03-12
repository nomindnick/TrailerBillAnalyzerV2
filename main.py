"""
Main entry point for Trailer Bill Analysis application
Connects the bill retrieval, parsing, and analysis components
"""
import sys
import logging
import asyncio
import argparse
from datetime import datetime
from src.services.bill_scraper import BillScraper
from src.services.base_parser import BaseParser
from src.models.bill_components import TrailerBill

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

class BillAnalyzer:
    """
    Main coordinator class for bill retrieval, parsing and analysis.
    """

    def __init__(self):
        self.bill_scraper = BillScraper(max_retries=3, timeout=60)
        self.bill_parser = BaseParser()
        self.logger = logging.getLogger(__name__)

    async def analyze_bill(self, bill_number: str, year: int) -> TrailerBill:
        """
        Retrieve, parse and analyze the specified bill

        Args:
            bill_number: Bill identifier (e.g., "AB123", "SB456")
            year: Year of the legislative session

        Returns:
            TrailerBill object containing the parsed bill data
        """
        self.logger.info(f"Starting analysis of bill {bill_number} from {year}")

        try:
            # Step 1: Retrieve the bill HTML
            bill_data = await self.bill_scraper.get_bill_text(bill_number, year)
            if not bill_data or 'html' not in bill_data:
                raise ValueError(f"Failed to retrieve bill {bill_number}")

            self.logger.info(f"Retrieved bill HTML ({len(bill_data['html'])} characters)")

            # Step 2: Parse the bill HTML into a structured object
            bill = self.bill_parser.parse_bill(bill_data['html'])

            self.logger.info(f"Parsed bill {bill_number} successfully")
            self.logger.info(f"Found {len(bill.digest_sections)} digest sections and {len(bill.bill_sections)} bill sections")

            return bill

        except Exception as e:
            self.logger.error(f"Error analyzing bill {bill_number}: {str(e)}")
            raise

    def save_bill_to_file(self, bill: TrailerBill, output_file: str) -> None:
        """
        Save the parsed bill to a text file for inspection

        Args:
            bill: The parsed TrailerBill object
            output_file: Path to save the output to
        """
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                # Write bill metadata
                f.write(f"Bill: {bill.bill_number}\n")
                f.write(f"Title: {bill.title}\n")
                f.write(f"Chapter: {bill.chapter_number}\n")
                f.write(f"Date Approved: {bill.date_approved}\n")
                f.write(f"Date Filed: {bill.date_filed}\n\n")

                # Write digest sections
                f.write(f"DIGEST SECTIONS ({len(bill.digest_sections)}):\n")
                f.write("=" * 80 + "\n\n")

                for ds in bill.digest_sections:
                    f.write(f"DIGEST SECTION {ds.number}:\n")
                    f.write("-" * 40 + "\n")
                    f.write(f"Text: {ds.text[:200]}...\n")
                    f.write(f"Existing Law: {ds.existing_law[:200]}...\n")
                    f.write(f"Proposed Changes: {ds.proposed_changes[:200]}...\n")
                    f.write(f"Code References: {', '.join([f'{ref.code_name} {ref.section}' for ref in ds.code_references])}\n")
                    f.write(f"Linked Bill Sections: {', '.join(ds.bill_sections)}\n")
                    f.write("\n")

                # Write bill sections
                f.write(f"BILL SECTIONS ({len(bill.bill_sections)}):\n")
                f.write("=" * 80 + "\n\n")

                for bs in bill.bill_sections:
                    f.write(f"BILL SECTION {bs.number} ({bs.original_label}):\n")
                    f.write("-" * 40 + "\n")
                    f.write(f"Text: {bs.text[:200]}...\n")
                    f.write(f"Code References: {', '.join([f'{ref.code_name} {ref.section}' for ref in bs.code_references])}\n")
                    f.write("\n")

                self.logger.info(f"Saved bill analysis to {output_file}")

        except Exception as e:
            self.logger.error(f"Error saving bill to file: {str(e)}")

async def main():
    """
    Main entry point for command-line usage
    """
    parser = argparse.ArgumentParser(description='Analyze a California trailer bill')
    parser.add_argument('bill_number', help='Bill number (e.g., SB174)')
    parser.add_argument('--year', type=int, default=datetime.now().year, help='Legislative session year')
    parser.add_argument('--output', default='bill_analysis.txt', help='Output file path')

    args = parser.parse_args()

    analyzer = BillAnalyzer()
    try:
        bill = await analyzer.analyze_bill(args.bill_number, args.year)
        analyzer.save_bill_to_file(bill, args.output)
        logger.info("Analysis completed successfully")
    except Exception as e:
        logger.error(f"Analysis failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())