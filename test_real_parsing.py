# test_real_parsing.py
import asyncio
import logging
import sys
import os
import re
from typing import Dict, List, Any, Set, Optional
from dataclasses import dataclass
import json

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("bill_parser_test")

# Import the actual classes from your project
from src.services.bill_scraper import BillScraper
from src.services.base_parser import BaseParser
from src.services.section_matcher import SectionMatcher

# Create a mock OpenAI client for the SectionMatcher
class MockOpenAIClient:
    async def chat(self):
        return None

# Apply our fixes to BaseParser
# This modifies the class method directly to test our changes
def apply_fixes_to_base_parser(parser):
    """Apply our fixes to the BaseParser instance"""

    # Replace the _parse_bill_sections method with our improved version
    def new_parse_bill_sections(self, bill_portion: str) -> List:
        """
        Parse bill sections with improved pattern matching and error handling.
        """
        sections = []
        cleaned_text = bill_portion.strip()

        # Log a sample of the text we're about to parse (first 200 chars)
        self.logger.debug(f"Processing bill text (sample): {cleaned_text[:200]}...")

        # Apply aggressive normalization
        normalized_text = self._aggressive_normalize_section_breaks(cleaned_text)

        # More robust unified pattern that handles both "SECTION X." and "SEC. X." formats
        # This pattern works with any whitespace variations and captures both formats
        section_pattern = re.compile(
            r'(?:^|\n)(?P<label>(?:SECTION|SEC)\.\s+(?P<number>\d+)\.)\s*(?P<body>.*?)(?=\n(?:SECTION|SEC)\.\s+\d+\.|\Z)',
            re.DOTALL
        )

        # Find all matching sections
        section_matches = list(section_pattern.finditer(normalized_text))
        self.logger.info(f"Found {len(section_matches)} potential bill sections")

        if not section_matches:
            # If no sections found, try fallback normalization
            self.logger.warning("No sections found with primary pattern, attempting normalization")
            normalized_text = self._aggressive_normalize_section_breaks(cleaned_text)
            section_matches = list(section_pattern.finditer(normalized_text))
            self.logger.info(f"After normalization, found {len(section_matches)} potential bill sections")

        # Try more aggressive approach if still not working
        if len(section_matches) < 4:  # We know we should find at least 7 sections
            self.logger.warning("Standard pattern found too few sections, using more aggressive pattern")
            # Direct approach using simpler SEC. X. pattern
            headers = re.findall(r'\n\s*(SEC\.\s+(\d+)\.)', normalized_text)
            self.logger.info(f"Found {len(headers)} section headers directly")

            if headers:
                # Process each section by finding text between headers
                for i, (header, number) in enumerate(headers):
                    start_idx = normalized_text.find(header)
                    if start_idx == -1:
                        continue

                    start_pos = start_idx + len(header)

                    # Find end position (next header or end of text)
                    if i < len(headers) - 1:
                        next_header = headers[i+1][0]
                        end_pos = normalized_text.find(next_header)
                    else:
                        end_pos = len(normalized_text)

                    body_text = normalized_text[start_pos:end_pos].strip()

                    # Skip if the section body is empty
                    if not body_text:
                        self.logger.warning(f"Empty body found for section {number}, skipping")
                        continue

                    self.logger.info(f"Processing section {number} with label 'SEC. {number}.'")

                    # Extract code references and determine action type
                    code_refs = self._extract_code_references(body_text)
                    action_type = self._determine_action_type(body_text)

                    # Create the section object
                    from src.models.bill_components import BillSection
                    bs = BillSection(
                        number=number,
                        original_label=f"SEC. {number}.",
                        text=body_text,
                        code_references=code_refs
                    )

                    if action_type:
                        bs.section_type = action_type

                    sections.append(bs)
        else:
            # Process each section from the regex matches
            for match in section_matches:
                label = match.group('label').strip()
                number = match.group('number')
                body_text = match.group('body').strip()

                # Skip if the section body is empty
                if not body_text:
                    self.logger.warning(f"Empty body found for section {number}, skipping")
                    continue

                self.logger.info(f"Processing section {number} with label '{label}'")

                # Handle code reference extraction
                # Fix the .2 issue in section numbers like 2575.2
                body_text = re.sub(r'(\d+)\s*\n\s*(\.\d+)', r'\1\2', body_text)

                # Extract code references and determine action type
                code_refs = self._extract_code_references(body_text)
                action_type = self._determine_action_type(body_text)

                # Create the section object
                from src.models.bill_components import BillSection
                bs = BillSection(
                    number=number,
                    original_label=label,
                    text=body_text,
                    code_references=code_refs
                )

                if action_type:
                    bs.section_type = action_type

                sections.append(bs)

        # Log the overall results
        self.logger.info(f"Successfully parsed {len(sections)} bill sections: {[s.original_label for s in sections]}")

        return sections

    # Add our new aggressive section break normalization method
    def aggressive_normalize_section_breaks(self, text: str) -> str:
        """
        Enhanced normalization of section breaks with more aggressive pattern matching.
        This is a fallback when regular normalization fails.
        """
        # Replace Windows line endings
        text = text.replace('\r\n', '\n')

        # Ensure consistent spacing around section headers
        text = re.sub(
            r'(\n\s*)(SEC\.?|SECTION)(\s*)(\d+)(\.\s*)',
            r'\n\2 \4\5',
            text
        )

        # Fix the decimal point issue - remove line breaks between section numbers and decimal points
        text = re.sub(r'(\d+)\s*\n\s*(\.\d+)', r'\1\2', text)

        # Standardize decimal points in section headers
        text = re.sub(r'Section\s+(\d+)\s*\n\s*(\.\d+)', r'Section \1\2', text)

        # Ensure section headers are properly separated with newlines
        text = re.sub(r'([^\n])(SEC\.|SECTION)', r'\1\n\2', text)

        # First, ensure there's a newline before any SEC. or SECTION patterns
        text = re.sub(
            r'(?<!\n)(?:\s*)(SEC(?:TION)?\.?\s+\d+\.)',
            r'\n\1',
            text,
            flags=re.IGNORECASE
        )

        return text

    # Update the extraction method and add the new normalization method to the instance
    setattr(parser, '_parse_bill_sections', new_parse_bill_sections.__get__(parser, type(parser)))
    setattr(parser, '_aggressive_normalize_section_breaks', aggressive_normalize_section_breaks.__get__(parser, type(parser)))

    # Also improve the extract_code_references method
    def improved_extract_code_references(self, text: str):
        """
        Enhanced code reference extraction with better decimal point handling
        """
        references = []

        # Special case for Education Code sections with decimal points
        # This handles cases like "Section 2575.2 of the Education Code"
        decimal_pattern = r'Section\s+(\d+\.\d+)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        for match in re.finditer(decimal_pattern, text):
            section_num = match.group(1).strip()
            code_name = match.group(2).strip()
            from src.models.bill_components import CodeReference
            references.append(CodeReference(section=section_num, code_name=code_name))

        # Now run the original method to get more references
        original_refs = parser._extract_code_references(text)

        # Combine both reference sets
        references.extend(original_refs)

        return references

    # Replace the code reference method with our improved version
    # Only if we haven't found many references with the original
    if len(parser._extract_code_references(bill_portion[:5000])) < 3:
        setattr(parser, '_extract_code_references', improved_extract_code_references.__get__(parser, type(parser)))

    return parser

# Test the actual parsers with our fixes
async def test_ab114_parsing():
    """
    Test parsing AB114 from the 2023-2024 session using the real parsers with fixes.
    """
    logger.info("Starting test of AB114 (2023-2024) parsing...")

    try:
        # Fetch bill text using BillScraper
        bill_scraper = BillScraper()
        bill_text_response = await bill_scraper.get_bill_text("AB114", 2023)
        bill_text = bill_text_response['full_text']
        logger.info(f"Retrieved bill text of length: {len(bill_text)}")

        # Prepare parsers
        parser = BaseParser()

        # Apply our fixes to the BaseParser
        apply_fixes_to_base_parser(parser)

        # Run the parsing with our fixed parser
        parsed_bill = parser.parse_bill(bill_text)

        # Test if we're getting the sections we expect
        print("\n==== BILL PARSING TEST RESULTS ====")
        print(f"Total sections found: {len(parsed_bill.bill_sections)}")

        # Print details about each section
        section_numbers = [section.number for section in parsed_bill.bill_sections]
        print(f"Section numbers found: {section_numbers}")

        print("\nSection details:")
        for section in parsed_bill.bill_sections:
            print(f"  Section {section.number}:")
            print(f"    Original label: {section.original_label}")
            print(f"    Code references: {[f'{ref.code_name}:{ref.section}' for ref in section.code_references]}")
            print(f"    Text length: {len(section.text)} characters")
            print(f"    Text starts with: {section.text[:100]}...")
            print()

        # Check if sections 3-7 were found
        for i in range(3, 8):
            section_present = str(i) in section_numbers
            status = "✅" if section_present else "❌"
            print(f"{status} Section {i}: {'Present' if section_present else 'Not found'}")

        # Return the parsed bill for further inspection
        return parsed_bill

    except Exception as e:
        logger.error(f"Error in test: {str(e)}")
        import traceback
        traceback.print_exc()
        raise

# Run the test when script is executed directly
if __name__ == "__main__":
    parsed_bill = asyncio.run(test_ab114_parsing())

    # Save the sections to a file for inspection
    try:
        with open("ab114_sections_fixed.txt", "w") as f:
            f.write(f"Total sections found: {len(parsed_bill.bill_sections)}\n\n")
            for section in parsed_bill.bill_sections:
                f.write(f"==== {section.original_label} ====\n")
                f.write(f"Text length: {len(section.text)} characters\n")
                f.write(f"Code references: {[f'{ref.code_name}:{ref.section}' for ref in section.code_references]}\n\n")
                f.write(section.text[:500])  # First 500 characters of each section
                f.write("\n...\n\n")
    except Exception as e:
        print(f"Error saving to file: {e}")