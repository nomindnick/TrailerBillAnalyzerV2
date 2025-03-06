# test_bill_parsing.py

import asyncio
import logging
import re
import sys
from typing import Dict, List, Any, Set, Optional
from dataclasses import dataclass

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("bill_parser_test")

# Import necessary classes and use mock data if needed
from src.services.bill_scraper import BillScraper
from src.models.bill_components import CodeReference, BillSection

# Create a simplified test version of SectionMatcher with our improved methods
class TestSectionMatcher:
    def __init__(self):
        self.logger = logging.getLogger("test_section_matcher")

    def _extract_bill_sections(self, bill_text: str) -> Dict[str, Dict[str, Any]]:
        """
        Extract and structure bill sections with enhanced metadata and improved pattern matching.
        """
        section_map = {}
        self.logger.info(f"Extracting bill sections from text of length {len(bill_text)}")

        # Normalize section breaks to ensure consistency
        normalized_text = self._normalize_section_breaks(bill_text)

        # Enhanced section pattern with named groups
        # This captures both "SECTION X." and "SEC. X." formats with flexible whitespace
        pattern = r'(?:^|\n)(?P<label>(?:SECTION|SEC)\.?\s+(?P<number>\d+(?:\.\d+)?)\.)\s*(?P<text>(?:.*?)(?=\n(?:SECTION|SEC)\.?\s+\d+(?:\.\d+)?\.|\Z))'

        matches = list(re.finditer(pattern, normalized_text, re.DOTALL | re.MULTILINE))
        self.logger.info(f"Found {len(matches)} potential bill sections")

        # If no sections found with the primary pattern, try an alternative approach
        if not matches:
            self.logger.warning("No bill sections found with primary pattern, trying backup pattern")
            # Fallback pattern with more aggressive whitespace handling
            pattern = r'(?P<label>(?:SECTION|SEC)\.?\s*(?P<number>\d+(?:\.\d+)?)\.)\s*(?P<text>.*?)(?=(?:SECTION|SEC)\.?\s*\d+(?:\.\d+)?\.|\Z)'
            matches = list(re.finditer(pattern, normalized_text, re.DOTALL))
            self.logger.info(f"Fallback pattern found {len(matches)} bill sections")

        # Process each matched section
        for match in matches:
            section_num = match.group('number')
            section_text = match.group('text').strip()
            section_label = match.group('label').strip()

            # Log the discovery of each section
            self.logger.info(f"Found bill section {section_num} with label '{section_label}'")

            # Skip empty sections
            if not section_text:
                self.logger.warning(f"Empty text for section {section_num}, skipping")
                continue

            # Extract code references and other metadata
            code_refs = self._extract_code_references(section_text)
            code_refs_strs = list(code_refs) if code_refs else []

            section_map[section_num] = {
                "text": section_text,
                "original_label": section_label,
                "code_refs": code_refs,
                "action_type": self._determine_action_type(section_text),
                "code_sections": self._extract_modified_sections(section_text)
            }

            # Log code references for debugging
            if code_refs:
                self.logger.info(f"Section {section_num} has code references: {code_refs_strs}")
            else:
                self.logger.debug(f"No code references found in section {section_num}")

        self.logger.info(f"Successfully extracted {len(section_map)} bill sections: {list(section_map.keys())}")
        return section_map

    def _normalize_section_breaks(self, text: str) -> str:
        """
        Ensure section breaks are consistently formatted to improve pattern matching.
        """
        # Ensure newlines before section headers
        normalized = re.sub(
            r'(?<!\n)(?:\s*)((?:SECTION|SEC)\.?\s+\d+(?:\.\d+)?\.)',
            r'\n\1',
            text,
            flags=re.IGNORECASE
        )

        # Standardize spacing in section headers
        normalized = re.sub(
            r'((?:SECTION|SEC)\.?)\s*(\d+(?:\.\d+)?)\.',
            r'\1 \2.',
            normalized,
            flags=re.IGNORECASE
        )

        # Make sure all section headers are followed by at least one newline
        normalized = re.sub(
            r'((?:SECTION|SEC)\.?\s+\d+(?:\.\d+)?\.)\s*(?!\n)',
            r'\1\n',
            normalized,
            flags=re.IGNORECASE
        )

        return normalized

    def _extract_code_references(self, text: str) -> Set[str]:
        """
        Extract code references with improved pattern matching for various formats.
        """
        references = set()

        # First check the first line, which often contains the primary code reference
        first_line = text.split('\n')[0] if '\n' in text else text

        # Pattern for "Section X of the Y Code is amended/added/repealed"
        section_header_pattern = r'(?i)Section\s+(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)\s+(?:is|are)'
        header_match = re.search(section_header_pattern, first_line)

        if header_match:
            section_num = header_match.group(1).strip()
            code_name = header_match.group(2).strip()
            references.add(f"{code_name} Section {section_num}")
            self.logger.debug(f"Found primary code reference: {code_name} Section {section_num}")

        # Various patterns for code references
        patterns = [
            # Standard format: "Section 123 of the Education Code"
            r'(?i)Section(?:s)?\s+(\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)',

            # Reverse format: "Education Code Section 123"
            r'(?i)([A-Za-z\s]+Code)\s+Section(?:s)?\s+(\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*)',

            # Range format: "Sections 123-128 of the Education Code"
            r'(?i)Section(?:s)?\s+(\d+(?:\.\d+)?)\s*(?:to|through|-)\s*(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                if len(match.groups()) == 2:  # Standard or reverse format
                    if "code" in match.group(2).lower():  # "Section X of Y Code" format
                        sections_str, code_name = match.groups()
                        for section in re.split(r'[,\s]+', sections_str):
                            if section.strip() and section.strip().isdigit():
                                references.add(f"{code_name.strip()} Section {section.strip()}")
                    else:  # "Y Code Section X" format
                        code_name, sections_str = match.groups()
                        for section in re.split(r'[,\s]+', sections_str):
                            if section.strip() and section.strip().isdigit():
                                references.add(f"{code_name.strip()} Section {section.strip()}")
                elif len(match.groups()) == 3:  # Range format
                    start, end, code = match.groups()
                    try:
                        for num in range(int(float(start)), int(float(end)) + 1):
                            references.add(f"{code.strip()} Section {num}")
                    except (ValueError, TypeError):
                        # If we can't convert to numbers, just add the endpoints
                        references.add(f"{code.strip()} Section {start.strip()}")
                        references.add(f"{code.strip()} Section {end.strip()}")

        return references

    def _determine_action_type(self, text: str) -> str:
        """Determine the type of action being performed in the section"""
        lower_text = text.lower()
        if "amended" in lower_text and "repealed" in lower_text:
            return "AMENDED_AND_REPEALED"
        elif "repealed" in lower_text and "added" in lower_text:
            return "REPEALED_AND_ADDED"
        elif "amended" in lower_text:
            return "AMENDED"
        elif "added" in lower_text:
            return "ADDED"
        elif "repealed" in lower_text:
            return "REPEALED"
        return "UNKNOWN"

    def _extract_modified_sections(self, text: str) -> List[Dict[str, str]]:
        """Extract information about modified code sections"""
        modified_sections = []
        pattern = r'Section\s+(\d+(?:\.\d+)?)\s+of\s+the\s+([A-Za-z\s]+Code)'

        for match in re.finditer(pattern, text):
            section_num = match.group(1)
            code_name = match.group(2)

            modified_sections.append({
                "section": section_num,
                "code": code_name,
                "action": self._determine_action_type(text)
            })

        return modified_sections


# Create a test class to run our tests
class BillParserTest:
    def __init__(self):
        self.logger = logging.getLogger("bill_parser_test")
        self.bill_scraper = BillScraper()
        self.section_matcher = TestSectionMatcher()

    async def test_ab114_parsing(self):
        """
        Test parsing AB114 from the 2023-2024 session using our improved methods.
        This demonstrates the enhanced section extraction.
        """
        self.logger.info("Starting test of AB114 (2023-2024) parsing...")

        try:
            # Fetch the bill text
            bill_text_response = await self.bill_scraper.get_bill_text("AB114", 2023)
            bill_text = bill_text_response['full_text']
            self.logger.info(f"Retrieved bill text of length: {len(bill_text)}")

            # Test the improved section extraction
            sections = self.section_matcher._extract_bill_sections(bill_text)

            # Print summary of results
            print("\n==== BILL PARSING TEST RESULTS ====")
            print(f"Total sections found: {len(sections)}")

            # Print section numbers and their code references
            print("\nSection details:")
            for num, section_info in sections.items():
                print(f"  Section {num}:")
                print(f"    Original label: {section_info['original_label']}")
                print(f"    Action type: {section_info['action_type']}")
                print(f"    Code references: {section_info['code_refs']}")
                print(f"    Text length: {len(section_info['text'])} characters")
                print(f"    Text starts with: {section_info['text'][:100]}...")
                print()

            # Verify we're finding the sections that were previously missed
            for section_num in range(3, 8):  # Previously it found only 1-3, test 3-7
                if str(section_num) in sections:
                    print(f"✅ Successfully found Section {section_num}")
                else:
                    print(f"❌ Failed to find Section {section_num}")

            return sections

        except Exception as e:
            self.logger.error(f"Error in test: {str(e)}")
            raise


# Run the test
async def run_tests():
    test = BillParserTest()
    sections = await test.test_ab114_parsing()
    return sections

# Execute test when run directly
if __name__ == "__main__":
    sections = asyncio.run(run_tests())

    # Save the first 7 sections to a file for manual inspection
    try:
        with open("ab114_sections.txt", "w") as f:
            i = 0
            for section_num, section_info in sorted(sections.items(), key=lambda x: int(x[0]) if x[0].isdigit() else float(x[0])):
                if i < 7:  # Just save the first 7 sections
                    f.write(f"==== {section_info['original_label']} ====\n\n")
                    f.write(section_info['text'])
                    f.write("\n\n")
                    i += 1
        print(f"\nSaved first 7 sections to ab114_sections.txt for inspection")
    except Exception as e:
        print(f"Error saving sections to file: {e}")