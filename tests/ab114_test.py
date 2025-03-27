"""
Test script to verify bill parsing of AB114, focusing on section identification.
This will test if the code correctly identifies all 72 digest sections and 124 bill sections.

Usage: python ab114_test.py
"""
import asyncio
import logging
import sys
import re
import os
from datetime import datetime
from src.services.bill_scraper import BillScraper
from src.services.base_parser import BillParser

# Configure logging
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = os.path.join(LOG_DIR, f"ab114_test_{timestamp}.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("ab114_test")

async def test_ab114_parsing():
    """
    Test the bill parsing on AB114 to check if all sections are properly identified.
    """
    logger.info("="*80)
    logger.info("Starting AB114 parsing test")
    logger.info("="*80)

    # Create instances of scrapers and parsers
    bill_scraper = BillScraper(max_retries=3, timeout=60)  # Increased timeout for large bill
    bill_parser = BillParser()

    # Fetch AB114
    bill_number = "AB114"
    year = 2023  # Year of bill

    try:
        logger.info(f"Fetching bill {bill_number} from {year}")
        bill_data = await bill_scraper.get_bill_text(bill_number, year)

        if not bill_data or not bill_data.get('full_text'):
            logger.error("Failed to retrieve bill text")
            return False

        # Log the length of the bill text for reference
        bill_text = bill_data['full_text']
        logger.info(f"Successfully retrieved bill text ({len(bill_text):,} characters)")

        # Save raw bill text for analysis if needed
        output_dir = "test_output"
        os.makedirs(output_dir, exist_ok=True)

        with open(os.path.join(output_dir, "ab114_raw.txt"), "w", encoding="utf-8") as f:
            f.write(bill_text)
        logger.info(f"Saved raw bill text to {output_dir}/ab114_raw.txt")

        # Direct check for section headers in the raw text
        # This helps verify how many sections should be found
        section_pattern = re.compile(r'(?:SECTION|SEC)\.?\s+(\d+)\.')
        raw_sections = section_pattern.findall(bill_text)
        unique_raw_sections = sorted(set(raw_sections), key=int)

        logger.info(f"Raw section headers found in text: {len(raw_sections)}")
        logger.info(f"Unique section numbers found in text: {len(unique_raw_sections)}")
        logger.info(f"First 10 unique section numbers: {unique_raw_sections[:10]}")
        logger.info(f"Last 10 unique section numbers: {unique_raw_sections[-10:]}")

        # Check if HTML markup might be causing issues
        html_content = bill_data.get('html', '')
        if html_content:
            strike_pattern = r'<font color="#B30000"><strike>'
            blue_pattern = r'<font color="blue" class="blue_text"><i>'
            strike_count = len(re.findall(strike_pattern, html_content))
            blue_count = len(re.findall(blue_pattern, html_content))
            logger.info(f"HTML markup analysis - strikethrough tags: {strike_count}, blue text tags: {blue_count}")

        # Test the HTML cleaning directly
        logger.info("Testing HTML cleaning...")
        # First, use the bill_scraper's clean method directly on the HTML
        cleaned_text = bill_scraper._clean_html_markup(html_content if html_content else bill_text)

        with open(os.path.join(output_dir, "ab114_cleaned.txt"), "w", encoding="utf-8") as f:
            f.write(cleaned_text)
        logger.info(f"Saved cleaned bill text to {output_dir}/ab114_cleaned.txt")

        # Check for sections after cleaning
        cleaned_sections = section_pattern.findall(cleaned_text)
        unique_cleaned_sections = sorted(set(cleaned_sections), key=int)
        logger.info(f"Unique section numbers after cleaning: {len(unique_cleaned_sections)}")

        # Test the normalization function from the parser
        logger.info("Testing text normalization...")
        normalized_text = bill_parser._aggressive_normalize_improved(cleaned_text)

        with open(os.path.join(output_dir, "ab114_normalized.txt"), "w", encoding="utf-8") as f:
            f.write(normalized_text)
        logger.info(f"Saved normalized bill text to {output_dir}/ab114_normalized.txt")

        # Check for sections after normalization
        normalized_sections = section_pattern.findall(normalized_text)
        unique_normalized_sections = sorted(set(normalized_sections), key=int)
        logger.info(f"Unique section numbers after normalization: {len(unique_normalized_sections)}")

        # Parse the bill text
        logger.info("Parsing bill text with BillParser...")
        parsed_bill = bill_parser.parse_bill(bill_text)

        # Log the parsing results
        digest_count = len(parsed_bill.digest_sections)
        section_count = len(parsed_bill.bill_sections)

        logger.info(f"Digest sections found: {digest_count} (Expected: 72)")
        logger.info(f"Bill sections found: {section_count} (Expected: 124)")

        # Output section numbers for verification
        parsed_section_numbers = [section.number for section in parsed_bill.bill_sections]
        parsed_section_set = set(parsed_section_numbers)

        logger.info(f"First 10 parsed section numbers: {parsed_section_numbers[:10]}")
        logger.info(f"Last 10 parsed section numbers: {parsed_section_numbers[-10:] if len(parsed_section_numbers) >= 10 else parsed_section_numbers}")

        # Compare with raw sections to identify any missing
        missing_sections = set(unique_raw_sections) - parsed_section_set
        if missing_sections:
            missing_sorted = sorted(missing_sections, key=int)
            logger.warning(f"Missing sections: {missing_sorted}")
            logger.warning(f"Total missing sections: {len(missing_sections)}")

        # Write detailed section info to file
        with open(os.path.join(output_dir, "ab114_sections.txt"), "w", encoding="utf-8") as f:
            f.write(f"Digest Sections: {digest_count}\n")
            for i, section in enumerate(parsed_bill.digest_sections):
                f.write(f"Digest {section.number}: {len(section.text)} chars\n")
                f.write(f"Preview: {section.text[:100].replace(chr(10), ' ')}...\n\n")

            f.write(f"\nBill Sections: {section_count}\n")
            for i, section in enumerate(parsed_bill.bill_sections):
                f.write(f"Section {section.number}: {len(section.text)} chars\n")
                f.write(f"Label: {section.original_label}\n")
                f.write(f"Preview: {section.text[:100].replace(chr(10), ' ')}...\n\n")

        logger.info(f"Saved detailed section info to {output_dir}/ab114_sections.txt")

        # Test conclusion
        if digest_count == 72 and section_count == 124:
            logger.info("✓ SUCCESS: All expected sections were found!")
            return True
        else:
            logger.warning(f"✗ FAILURE: Expected 72 digest sections and 124 bill sections, but found {digest_count} and {section_count}")
            return False

    except Exception as e:
        logger.error(f"Error during test: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

if __name__ == "__main__":
    logger.info("Running AB114 parsing test")
    result = asyncio.run(test_ab114_parsing())

    if result:
        print("\n✓ TEST PASSED: All expected sections were found!")
        sys.exit(0)
    else:
        print("\n✗ TEST FAILED: Not all expected sections were found.")
        sys.exit(1)