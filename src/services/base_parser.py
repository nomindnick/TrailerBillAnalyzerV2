"""
BaseParser module for processing and parsing bill text from leginfo.legislature.ca.gov
"""
import re
import logging
import os
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any, Set
from bs4 import BeautifulSoup
from src.models.bill_components import (
    TrailerBill,
    DigestSection,
    BillSection,
    CodeReference
)

class BaseParser:
    """
    A simplified parser for California trailer bills that focuses on reliable
    extraction of bill components (metadata, digest sections, bill sections).
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def parse_bill(self, bill_html: str) -> TrailerBill:
        """
        Parse a bill's HTML content into structured TrailerBill object

        Args:
            bill_html: The raw HTML content of the bill

        Returns:
            TrailerBill object containing parsed bill data
        """
        self.logger.info("Starting bill parsing")

        # Create soup for easier parsing
        soup = BeautifulSoup(bill_html, "html.parser")

        # Extract metadata
        metadata = self._extract_metadata(soup)
        bill_number = metadata.get('bill_number', '')
        bill_title = metadata.get('title', '')
        chapter_number = metadata.get('chapter_number', '')

        # Extract approval and filing dates
        date_approved = self._parse_date(metadata.get('date_approved'))
        date_filed = self._parse_date(metadata.get('date_filed'))

        # Split bill into digest and sections
        digest_text, bill_text = self._split_digest_and_bill(bill_html)

        # Parse digest sections
        digest_sections = self._parse_digest_sections(digest_text)

        # Parse bill sections
        bill_sections = self._parse_bill_sections(bill_text)

        # Create TrailerBill object
        bill = TrailerBill(
            bill_number=bill_number,
            title=bill_title,
            chapter_number=chapter_number,
            date_approved=date_approved,
            date_filed=date_filed,
            raw_text=bill_html,
            digest_sections=digest_sections,
            bill_sections=bill_sections
        )

        # Match digest sections to bill sections
        self._match_digest_to_bill_sections(bill)

        self.logger.info(f"Completed parsing {bill_number} - Found {len(digest_sections)} digest sections and {len(bill_sections)} bill sections")
        return bill

    def _extract_metadata(self, soup: BeautifulSoup) -> Dict[str, str]:
        """
        Extract bill metadata from soup
        """
        metadata = {}

        # Try to get bill number
        bill_num_elem = soup.find(id="bill_num_title_chap")
        if bill_num_elem:
            metadata['bill_number'] = bill_num_elem.get_text(strip=True)

        # Try to get chapter number
        chap_num_elem = soup.find(id="chap_num_title_chap")
        if chap_num_elem:
            metadata['chapter_number'] = chap_num_elem.get_text(strip=True)

        # Try to get bill title
        title_elem = soup.find(id="title")
        if title_elem:
            metadata['title'] = title_elem.get_text(strip=True)

        # Try to get approval date
        approval_text = soup.find(string=lambda t: "Approved" in str(t) and "Governor" in str(t))
        if approval_text:
            date_text = approval_text.findNext(string=lambda t: any(month in str(t) for month in 
                                            ['January', 'February', 'March', 'April', 'May', 'June', 
                                             'July', 'August', 'September', 'October', 'November', 'December']))
            if date_text:
                metadata['date_approved'] = date_text.strip()

        # Try to get file date
        file_text = soup.find(string=lambda t: "Filed with" in str(t) and "Secretary of State" in str(t))
        if file_text:
            date_text = file_text.findNext(string=lambda t: any(month in str(t) for month in 
                                         ['January', 'February', 'March', 'April', 'May', 'June', 
                                          'July', 'August', 'September', 'October', 'November', 'December']))
            if date_text:
                metadata['date_filed'] = date_text.strip()

        return metadata

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """
        Parse a date string into a datetime object
        """
        if not date_str:
            return None

        try:
            # Handle various date formats
            date_formats = [
                '%B %d, %Y',  # January 01, 2023
                '%b %d, %Y',  # Jan 01, 2023
                '%m/%d/%Y',   # 01/01/2023
            ]

            for date_format in date_formats:
                try:
                    return datetime.strptime(date_str.strip(), date_format)
                except ValueError:
                    continue

            # If none of the formats work, try to extract a date with regex
            date_match = re.search(r'(\w+)\s+(\d{1,2}),?\s+(\d{4})', date_str)
            if date_match:
                month, day, year = date_match.groups()
                month_str = month[:3]  # First 3 chars of month name
                try:
                    return datetime.strptime(f"{month_str} {day} {year}", "%b %d %Y")
                except ValueError:
                    pass

            return None
        except Exception as e:
            self.logger.warning(f"Error parsing date '{date_str}': {str(e)}")
            return None

    def _split_digest_and_bill(self, bill_html: str) -> Tuple[str, str]:
        """
        Split the bill HTML into digest and bill text portions
        """
        soup = BeautifulSoup(bill_html, "html.parser")

        # Try to find the digest section
        digest_elem = soup.find(id="digesttext") or soup.find(string=lambda text: "LEGISLATIVE COUNSEL'S DIGEST" in text)

        digest_text = ""
        bill_text = ""

        # If digest element found, extract text
        if digest_elem:
            # Get the digest container
            if digest_elem.name:  # Is an element
                digest_container = digest_elem
            else:  # Is a string
                digest_container = digest_elem.find_parent('div')

            if digest_container:
                # Extract all text from digest container
                digest_text = digest_container.get_text(separator='\n', strip=True)

        # Find the bill text section (after "The people of the State of California do enact as follows:")
        enactment_text = soup.find(string=lambda text: "The people of the State of California do enact as follows" in text)

        if enactment_text:
            # Get the parent element
            enactment_elem = enactment_text if enactment_text.name else enactment_text.find_parent()

            # Get all siblings after the enactment clause
            bill_elements = []
            current_elem = enactment_elem.find_next()

            while current_elem:
                bill_elements.append(current_elem.get_text(separator='\n', strip=True))
                current_elem = current_elem.find_next_sibling()

            # Join all the bill section elements
            bill_text = '\n'.join(bill_elements)

        # If extraction from HTML structure failed, use regex as fallback
        if not digest_text or not bill_text:
            self.logger.warning("Using regex fallback for splitting digest and bill text")

            # Get the entire text content
            full_text = soup.get_text(separator='\n', strip=True)

            # Try to find the Legislative Counsel's Digest
            digest_match = re.search(r'LEGISLATIVE\s+COUNSEL[\'\']?S\s+DIGEST(.*?)(?:The\s+people\s+of\s+the\s+State\s+of\s+California\s+do\s+enact\s+as\s+follows)', 
                                    full_text, 
                                    re.DOTALL | re.IGNORECASE)

            if digest_match:
                digest_text = digest_match.group(1).strip()

            # Try to find the bill text after enactment clause
            bill_match = re.search(r'The\s+people\s+of\s+the\s+State\s+of\s+California\s+do\s+enact\s+as\s+follows(.*?)$', 
                                  full_text, 
                                  re.DOTALL | re.IGNORECASE)

            if bill_match:
                bill_text = bill_match.group(1).strip()

        return digest_text, bill_text

    def _parse_digest_sections(self, digest_text: str) -> List[DigestSection]:
        """
        Parse the digest text into a list of DigestSection objects
        """
        digest_sections = []
        if not digest_text:
            self.logger.warning("No digest text to parse")
            return digest_sections

        # First, remove the "LEGISLATIVE COUNSEL'S DIGEST" heading if present
        digest_text = re.sub(r'^LEGISLATIVE\s+COUNSEL[\'\']?S\s+DIGEST\s*', '', digest_text, flags=re.IGNORECASE)

        # Split the digest text into sections based on paragraph numbers (1), (2), etc.
        section_pattern = r'\((\d+)\)(.*?)(?=\(\d+\)|$)'
        section_matches = re.finditer(section_pattern, digest_text, re.DOTALL)

        for match in section_matches:
            section_number = match.group(1)
            section_text = match.group(2).strip()

            # Further split the section text into "existing law" and "proposed changes"
            existing_law = ""
            proposed_changes = ""

            # Look for patterns like "Existing law..." followed by "This bill would..."
            existing_match = re.search(r'^(.*?)(This\s+bill\s+would|This\s+bill\s+provides|The\s+bill\s+would)', section_text, re.DOTALL | re.IGNORECASE)

            if existing_match:
                existing_law = existing_match.group(1).strip()
                proposed_changes = section_text[len(existing_law):].strip()
            else:
                # If we can't clearly separate, just use the whole text
                proposed_changes = section_text

            # Extract code references
            code_references = self._extract_code_references(section_text)

            digest_section = DigestSection(
                number=section_number,
                text=section_text,
                existing_law=existing_law,
                proposed_changes=proposed_changes,
                code_references=code_references
            )

            digest_sections.append(digest_section)

        # Sort by section number
        digest_sections.sort(key=lambda x: int(x.number))

        return digest_sections

    # Add this as a fallback method in base_parser.py
    def _direct_section_extraction(self, normalized_text: str) -> List[BillSection]:
        """
        Fallback method to directly extract sections when regex patterns fail
        """
        bill_sections = []

        # Find all section headers
        section_markers = []

        # Look for both "SECTION X." and "SEC. X."
        for pattern in [r'\n\s*(SECTION\s+(\d+)\.)', r'\n\s*(SEC\.\s+(\d+)\.)']: 
            markers = re.findall(pattern, normalized_text, flags=re.IGNORECASE)
            section_markers.extend(markers)

        # Sort markers by their position in the text
        section_positions = []
        for header, number in section_markers:
            pos = normalized_text.find(header)
            if pos != -1:
                section_positions.append((pos, header, number))

        section_positions.sort()

        # Extract text between section headers
        for i, (pos, header, number) in enumerate(section_positions):
            start_pos = pos + len(header)

            # Find end position
            if i < len(section_positions) - 1:
                end_pos = section_positions[i+1][0]
            else:
                end_pos = len(normalized_text)

            section_text = normalized_text[start_pos:end_pos].strip()
            if section_text:
                bill_section = BillSection(
                    number=number,
                    original_label=header.strip(),
                    text=section_text,
                    code_references=self._extract_code_references(section_text)
                )
                bill_sections.append(bill_section)

        return bill_sections
    
    def _parse_bill_sections(self, bill_text: str) -> List[BillSection]:
        """
        Parse the bill text into a list of BillSection objects with improved pattern matching
        """
        bill_sections = []
        if not bill_text:
            self.logger.warning("No bill text to parse")
            return bill_sections

        # Write original bill text to debug file
        debug_dir = "debug_output"
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, "original_bill_text.txt"), "w", encoding="utf-8") as f:
            f.write(bill_text)

        # Pre-process the text for more reliable section detection
        normalized_text = self._aggressive_normalize_improved(bill_text)

        # Log a sample for debugging
        self.logger.debug(f"Normalized text sample: {normalized_text[:500]}...")

        # Write normalized text to debug file
        with open(os.path.join(debug_dir, "normalized_text.txt"), "w", encoding="utf-8") as f:
            f.write(normalized_text)

        # Try multiple section patterns with increasing flexibility
        section_patterns = [
            # Pattern 1: Standard format with newline
            r'(?:^|\n)\s*(?P<label>(?:SECTION|SEC)\.?\s+(?P<number>\d+)\.)\s*(?P<text>(?:.+?)(?=\n\s*(?:SECTION|SEC)\.?\s+\d+\.|\Z))',

            # Pattern 2: More flexible with optional whitespace
            r'(?:^|\n)\s*(?P<label>(?:SECTION|SEC)\.?\s*(?P<number>\d+)\.)\s*(?P<text>(?:.+?)(?=\n\s*(?:SECTION|SEC)\.?\s*\d+\.|\Z))',

            # Pattern 3: Force matches at "SEC. X." regardless of surrounding context
            r'\n\s*(?P<label>SEC\.\s+(?P<number>\d+)\.)\s*(?P<text>(?:.+?)(?=\n\s*SEC\.\s+\d+\.|\Z))',
        ]

        # Try each pattern
        all_matches = []
        successful_pattern = None

        for i, pattern in enumerate(section_patterns):
            matches = list(re.finditer(pattern, normalized_text, re.DOTALL | re.MULTILINE | re.IGNORECASE))
            self.logger.info(f"Pattern {i+1} found {len(matches)} potential sections")

            if matches:
                all_matches = matches
                successful_pattern = i+1
                break

        if not all_matches:
            self.logger.warning("Standard patterns failed, attempting direct section extraction")
            bill_sections = self._direct_section_extraction(normalized_text)
            if bill_sections:
                self.logger.info(f"Direct extraction found {len(bill_sections)} sections")
                bill_sections.sort(key=lambda x: int(x.number))
                return bill_sections

        # Process regular matches if direct extraction didn't work
        if all_matches:
            for match in all_matches:
                section_num = match.group('number')
                section_text = match.group('text').strip()
                section_label = match.group('label').strip()

                # Skip empty sections
                if not section_text:
                    self.logger.warning(f"Empty text for section {section_num}, skipping")
                    continue

                # Extract code references
                code_refs = self._extract_code_references(section_text)

                bill_section = BillSection(
                    number=section_num,
                    original_label=section_label,
                    text=section_text,
                    code_references=code_refs
                )

                bill_sections.append(bill_section)

        # Sort by section number
        bill_sections.sort(key=lambda x: int(x.number))

        self.logger.info(f"Successfully extracted {len(bill_sections)} bill sections")
        return bill_sections

    def _aggressive_normalize_improved(self, text: str) -> str:
        """
        Aggressively normalize text to fix common issues with bill formatting,
        especially handling decimal points in section numbers.
        """
        # Replace Windows line endings
        text = text.replace('\r\n', '\n')

        # Ensure consistent spacing around section headers
        text = re.sub(r'(\n\s*)(SEC\.?|SECTION)(\s*)(\d+)(\.\s*)', r'\n\2 \4\5', text)

        # Fix the decimal point issue - remove line breaks between section numbers and decimal points
        text = re.sub(r'(\d+)\s*\n\s*(\.\d+)', r'\1\2', text)

        # Standardize decimal points in section headers
        text = re.sub(r'Section\s+(\d+)\s*\n\s*(\.\d+)', r'Section \1\2', text)

        # Ensure section headers are properly separated with newlines
        text = re.sub(r'([^\n])(SEC\.|SECTION)', r'\1\n\n\2', text)

        # Handle extra whitespace
        text = re.sub(r'\n\s+', '\n', text)

        # Ensure "The people of the State of California do enact as follows:" is followed by double newlines
        text = re.sub(r'(The people of the State of California do enact as follows:)(?!\n)', 
                     r'\1\n\n', text, flags=re.IGNORECASE)

        # Add double newlines before each section to ensure they're properly separated
        text = re.sub(r'\n(\s*(?:SEC\.|SECTION)\s+\d+\.)', r'\n\n\1', text, flags=re.IGNORECASE)

        # Make sure section headers are followed by a newline
        text = re.sub(r'((?:SEC\.|SECTION)\s+\d+\.)([^\n])', r'\1\n\2', text, flags=re.IGNORECASE)

        return text

    def _extract_code_references(self, text: str) -> List[CodeReference]:
        """
        Extract code references from text, e.g., "Section 123 of the Education Code"
        """
        code_references = []

        # Pattern for "Section X of the Y Code"
        pattern1 = r'Section\s+(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        for match in re.finditer(pattern1, text, re.IGNORECASE):
            section_num = match.group(1)
            code_name = match.group(2)
            code_references.append(CodeReference(section=section_num, code_name=code_name))

        # Pattern for "Y Code Section X"
        pattern2 = r'([A-Za-z\s]+Code)\s+Section\s+(\d+(?:\.\d+)?)'
        for match in re.finditer(pattern2, text, re.IGNORECASE):
            code_name = match.group(1)
            section_num = match.group(2)
            code_references.append(CodeReference(section=section_num, code_name=code_name))

        return code_references

    def _match_digest_to_bill_sections(self, bill: TrailerBill) -> None:
        """
        Match digest sections to bill sections using various heuristics
        """
        # This is a simple first-pass matching that we can improve later
        for digest_section in bill.digest_sections:
            matched_section_numbers = []

            # 1. Try to match based on code references
            digest_codes = {(ref.section, ref.code_name) for ref in digest_section.code_references}

            for bill_section in bill.bill_sections:
                bill_codes = {(ref.section, ref.code_name) for ref in bill_section.code_references}

                # If there's any overlap in code references, consider it a match
                if digest_codes and bill_codes and digest_codes.intersection(bill_codes):
                    matched_section_numbers.append(bill_section.number)

            # 2. If nothing matched by code references, try to match by explicit section references in digest
            if not matched_section_numbers:
                for bill_section in bill.bill_sections:
                    # Look for explicit references to SEC. X or SECTION X
                    section_pattern = rf'(?:SEC|SECTION)\.\s*{bill_section.number}\b'
                    if re.search(section_pattern, digest_section.text, re.IGNORECASE):
                        matched_section_numbers.append(bill_section.number)

            # If we found matches, add them to the digest section
            digest_section.bill_sections = matched_section_numbers