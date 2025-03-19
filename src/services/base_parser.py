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

        # Log extracted digest sections
        self.logger.info(f"Extracted {len(digest_sections)} digest sections")
        for i, section in enumerate(digest_sections):
            self.logger.debug(f"Digest section {section.number}: {len(section.text)} chars, "
                              f"{len(section.code_references)} code references")

        # Parse bill sections
        bill_sections = self._parse_bill_sections(bill_text)

        # Log extracted bill sections
        self.logger.info(f"Extracted {len(bill_sections)} bill sections")
        for i, section in enumerate(bill_sections[:5]):  # Log first 5 for brevity
            self.logger.debug(f"Bill section {section.number}: {len(section.text)} chars, "
                              f"{len(section.code_references)} code references")

        if len(bill_sections) > 5:
            self.logger.debug(f"... and {len(bill_sections) - 5} more sections")

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

        # Verify matches
        matched_digests = sum(1 for d in digest_sections if d.bill_sections)
        self.logger.info(f"Completed parsing {bill_number} - Found {len(digest_sections)} digest sections and {len(bill_sections)} bill sections")
        self.logger.info(f"Successfully matched {matched_digests} of {len(digest_sections)} digest sections to bill sections")

        return bill

    def _extract_metadata(self, soup: BeautifulSoup) -> Dict[str, str]:
        """
        Extract bill metadata from soup with improved robustness for amended bills
        """
        metadata = {}

        # Try to get bill number with multiple strategies
        bill_num_elem = soup.find(id="bill_num_title_chap")
        if bill_num_elem:
            metadata['bill_number'] = bill_num_elem.get_text(strip=True)
        else:
            # Try the regex approach for bill number
            bill_pattern = r'(Assembly|Senate)\s+Bill\s+No\.\s+(\d+)'
            bill_match = None

            # First try in the beginning of the document
            first_1000_chars = soup.get_text()[:1000]
            bill_match = re.search(bill_pattern, first_1000_chars)

            if not bill_match:
                # Try in the entire document
                bill_match = re.search(bill_pattern, soup.get_text())

            if bill_match:
                house = bill_match.group(1)
                number = bill_match.group(2)
                prefix = 'AB' if house == 'Assembly' else 'SB'
                metadata['bill_number'] = f"{prefix}{number}"
                self.logger.info(f"Extracted bill number '{metadata['bill_number']}' using regex")

        # Try to get chapter number
        chap_num_elem = soup.find(id="chap_num_title_chap")
        if chap_num_elem:
            metadata['chapter_number'] = chap_num_elem.get_text(strip=True)
        else:
            # Try regex approach for chapter number
            chapter_pattern = r'CHAPTER\s+(\d+)'
            chapter_match = re.search(chapter_pattern, soup.get_text()[:1000])
            if chapter_match:
                metadata['chapter_number'] = f"Chapter {chapter_match.group(1)}"
                self.logger.info(f"Extracted chapter number '{metadata['chapter_number']}' using regex")

        # Try to get bill title
        title_elem = soup.find(id="title")
        if title_elem:
            metadata['title'] = title_elem.get_text(strip=True)
        else:
            # Try to find title using typical patterns
            title_patterns = [
                r'An act to .*?, relating to',
                r'An act to amend.*?code.*?relating to'
            ]

            for pattern in title_patterns:
                title_match = re.search(pattern, soup.get_text(), re.DOTALL)
                if title_match:
                    title_text = title_match.group(0)
                    # Limit to a reasonable length
                    if len(title_text) > 200:
                        title_text = title_text[:197] + '...'
                    metadata['title'] = title_text
                    self.logger.info(f"Extracted bill title using regex pattern")
                    break

        # Try to get approval date
        approval_text = soup.find(string=lambda t: "Approved" in str(t) and "Governor" in str(t))
        if approval_text:
            # Try with more specific pattern matching
            date_pattern = r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}'
            parent_text = str(approval_text.find_parent())
            date_match = re.search(date_pattern, parent_text)

            if date_match:
                metadata['date_approved'] = date_match.group(0)
                self.logger.info(f"Extracted approval date '{metadata['date_approved']}' using regex")
            else:
                # Try the original approach
                date_text = approval_text.findNext(string=lambda t: any(month in str(t) for month in 
                                                ['January', 'February', 'March', 'April', 'May', 'June', 
                                                'July', 'August', 'September', 'October', 'November', 'December']))
                if date_text:
                    metadata['date_approved'] = date_text.strip()

        # Try to get file date
        file_text = soup.find(string=lambda t: "Filed with" in str(t) and "Secretary of State" in str(t))
        if file_text:
            # Try with more specific pattern matching
            date_pattern = r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}'
            parent_text = str(file_text.find_parent())
            date_match = re.search(date_pattern, parent_text)

            if date_match:
                metadata['date_filed'] = date_match.group(0)
                self.logger.info(f"Extracted filed date '{metadata['date_filed']}' using regex")
            else:
                # Try the original approach
                date_text = file_text.findNext(string=lambda t: any(month in str(t) for month in 
                                            ['January', 'February', 'March', 'April', 'May', 'June', 
                                            'July', 'August', 'September', 'October', 'November', 'December']))
                if date_text:
                    metadata['date_filed'] = date_text.strip()

        return metadata

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """
        Parse a date string into a datetime object with enhanced format handling
        """
        if not date_str:
            return None

        try:
            # Handle various date formats
            date_formats = [
                '%B %d, %Y',    # January 01, 2023
                '%B %d,%Y',     # January 01,2023 (no space after comma)
                '%b %d, %Y',    # Jan 01, 2023
                '%m/%d/%Y',     # 01/01/2023
                '%B %d %Y',     # January 01 2023 (no comma)
                '%d %B %Y',     # 01 January 2023
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

            # Try European format (day first)
            date_match = re.search(r'(\d{1,2})\s+(\w+)\s+(\d{4})', date_str)
            if date_match:
                day, month, year = date_match.groups()
                month_str = month[:3]  # First 3 chars of month name
                try:
                    return datetime.strptime(f"{day} {month_str} {year}", "%d %b %Y")
                except ValueError:
                    pass

            return None
        except Exception as e:
            self.logger.warning(f"Error parsing date '{date_str}': {str(e)}")
            return None

    def _split_digest_and_bill(self, bill_html: str) -> Tuple[str, str]:
        """
        Split the bill HTML into digest and bill text portions with enhanced robustness
        for amended bills with complex markup.
        """
        self.logger.info("Starting to split digest and bill text")

        # Fix malformed HTML before processing
        clean_html = self._fix_malformed_html(bill_html)


        soup = BeautifulSoup(clean_html, "html.parser")

        # Try multiple approaches to find the digest and bill sections
        digest_text = ""
        bill_text = ""

        # Try to find digest container
        digest_container = (
            soup.find(id="digesttext") or 
            soup.find(id="digest") or 
            soup.find(class_="digesttext")
        )

        if digest_container:
            digest_text = digest_container.get_text(separator='\n', strip=True)
            self.logger.info(f"Found digest container, extracted {len(digest_text)} characters")
        else:
            # Look for the digest heading
            digest_heading = soup.find(string=lambda text: "LEGISLATIVE COUNSEL'S DIGEST" in text)
            if digest_heading:
                self.logger.info("Found digest heading, looking for surrounding content")
                parent = digest_heading.find_parent()
                if parent and parent.name in ['h1', 'h2', 'h3', 'div', 'p']:
                    # Get all text until we reach the enactment clause
                    digest_text = ""
                    current = parent
                    while current:
                        next_elem = current.find_next_sibling()
                        if next_elem:
                            elem_text = next_elem.get_text()
                            if "The people of the State of California do enact as follows" in elem_text:
                                break
                            digest_text += "\n" + elem_text
                        current = next_elem

                    self.logger.info(f"Extracted digest by traversing siblings: {len(digest_text)} chars")

        # Find the enactment clause
        enactment_text = soup.find(string=lambda text: "The people of the State of California do enact as follows" in text)

        # Get the bill text container
        bill_container = soup.find(id="bill_all") or soup.find(class_="bill-content")

        if enactment_text and bill_container:
            # Get the full bill text and extract everything after the enactment clause
            full_text = bill_container.get_text(separator='\n', strip=True)
            enactment_pattern = r'The\s+people\s+of\s+the\s+State\s+of\s+California\s+do\s+enact\s+as\s+follows'
            matches = re.search(enactment_pattern, full_text, re.DOTALL | re.IGNORECASE)

            if matches:
                bill_text = full_text[matches.end():].strip()
                self.logger.info(f"Extracted bill text after enactment clause: {len(bill_text)} chars")

        # If approach 1 didn't work, try regex as a fallback
        if not digest_text or not bill_text:
            self.logger.warning("Using regex fallback for splitting digest and bill text")
            full_text = soup.get_text(separator='\n', strip=True)

            # Try to find the Legislative Counsel's Digest
            if not digest_text:
                digest_match = re.search(
                    r'LEGISLATIVE\s+COUNSEL[\'\']?S\s+DIGEST(.*?)(?:The\s+people\s+of\s+the\s+State\s+of\s+California\s+do\s+enact\s+as\s+follows)', 
                    full_text, 
                    re.DOTALL | re.IGNORECASE
                )

                if digest_match:
                    digest_text = digest_match.group(1).strip()
                    self.logger.info(f"Extracted digest text via regex: {len(digest_text)} chars")

            # Try to find the bill text after enactment clause
            if not bill_text:
                bill_match = re.search(
                    r'The\s+people\s+of\s+the\s+State\s+of\s+California\s+do\s+enact\s+as\s+follows(.*?)$', 
                    full_text, 
                    re.DOTALL | re.IGNORECASE
                )

                if bill_match:
                    bill_text = bill_match.group(1).strip()
                    self.logger.info(f"Extracted bill text via regex: {len(bill_text)} chars")

        # Last resort if digest text is still empty
        if not digest_text:
            self.logger.warning("Unable to extract digest, using heuristic approach")
            # Try to find any text between the bill title and enactment clause
            digest_pattern = r'(An act to .*?relating to.*?)(The people of the State of California do enact as follows)'
            match = re.search(digest_pattern, full_text, re.DOTALL | re.IGNORECASE)
            if match:
                # Extract everything between end of title and start of enactment
                title_text = match.group(1).strip()
                # The digest typically starts after the title
                title_end_pos = len(title_text)
                enactment_start_pos = full_text.find("The people of the State of California do enact as follows")
                if title_end_pos < enactment_start_pos:
                    potential_digest = full_text[title_end_pos:enactment_start_pos].strip()
                    # Check if it looks like a digest (contains digest-like keywords)
                    if "existing law" in potential_digest.lower() or "this bill would" in potential_digest.lower():
                        digest_text = potential_digest
                        self.logger.info(f"Extracted potential digest text using title/enactment bounds: {len(digest_text)} chars")

        # Log the results to verify content was properly extracted
        self.logger.info(f"Final digest text length: {len(digest_text)}")
        self.logger.info(f"Final bill text length: {len(bill_text)}")

        return digest_text, bill_text

    def _fix_malformed_html(self, html_content: str) -> str:
        """Fix common HTML issues in bill text"""
        # Fix malformed ID attributes with embedded tags
        # Example: <div id="<b><span style='background-color:yellow'>bill"</span></b>>
        pattern = r'id\s*=\s*"(.*?)"'

        def clean_id_attr(match):
            id_content = match.group(1)
            # If the ID contains HTML tags, extract just the text
            if '<' in id_content or '>' in id_content:
                # Extract just the text without tags using regex
                clean_id = re.sub(r'<.*?>', '', id_content)
                return f'id="{clean_id}"'
            return match.group(0)

        html_content = re.sub(pattern, clean_id_attr, html_content)

        # Fix unclosed tags
        html_content = re.sub(r'<([a-zA-Z]+)([^>]*?)(?<!/)>(?!</\1>)', r'<\1\2></\1>', html_content)

        # Fix missing quotes in attributes
        html_content = re.sub(r'(\w+)=([^\s"][^\s>]*)', r'\1="\2"', html_content)

        # Normalize whitespace in tags
        html_content = re.sub(r'<\s*(\w+)', r'<\1', html_content)
        html_content = re.sub(r'(\w+)\s*>', r'\1>', html_content)

        # Fix line breaks within attributes
        html_content = re.sub(r'="([^"]*?)\n([^"]*?)"', r'="\1 \2"', html_content)

        return html_content

    def _parse_digest_sections(self, digest_text: str) -> List[DigestSection]:
        """
        Parse the digest text into a list of DigestSection objects with enhanced handling
        for complex formatting and amended bills.
        """
        digest_sections = []
        if not digest_text:
            self.logger.warning("No digest text to parse")
            return digest_sections

        # First, remove the "LEGISLATIVE COUNSEL'S DIGEST" heading if present
        digest_text = re.sub(r'^LEGISLATIVE\s+COUNSEL[\'\']?S\s+DIGEST\s*', '', digest_text, flags=re.IGNORECASE)


        # Split the digest text into sections based on paragraph numbers (1), (2), etc.
        # Enhanced pattern to handle various formatting issues
        section_pattern = r'\((\d+)\)(.*?)(?=\(\d+\)|$)'
        section_matches = re.finditer(section_pattern, digest_text, re.DOTALL)

        matched_sections = False
        for match in section_matches:
            matched_sections = True
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
                # If we can't clearly separate, try alternative patterns
                alt_patterns = [
                    r'(.*?existing law.*?)(This bill|The bill)',
                    r'(.*?current law.*?)(This bill|The bill)',
                    r'(.*?The law.*?)(This bill|The bill)'
                ]

                for pattern in alt_patterns:
                    alt_match = re.search(pattern, section_text, re.DOTALL | re.IGNORECASE)
                    if alt_match:
                        existing_law = alt_match.group(1).strip()
                        proposed_changes = section_text[len(existing_law):].strip()
                        break

                # If we still can't separate, just use the whole text
                if not existing_law:
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

        # If we didn't find any numbered sections, try to parse based on paragraphs
        if not matched_sections and digest_text:
            self.logger.warning("No numbered digest sections found. Attempting to parse by paragraphs.")

            # Split by paragraphs (double newlines or periods followed by space)
            paragraphs = re.split(r'\n\s*\n|\.\s+', digest_text)

            # Filter out short paragraphs
            paragraphs = [p.strip() for p in paragraphs if len(p.strip()) > 50]

            for i, paragraph in enumerate(paragraphs):
                # Try to split into existing law and proposed changes
                existing_law = ""
                proposed_changes = ""

                existing_match = re.search(r'^(.*?)(This\s+bill\s+would|This\s+bill\s+provides|The\s+bill\s+would)', paragraph, re.DOTALL | re.IGNORECASE)

                if existing_match:
                    existing_law = existing_match.group(1).strip()
                    proposed_changes = paragraph[len(existing_law):].strip()
                else:
                    # If no clear separation, use heuristics
                    if "existing law" in paragraph.lower() and "this bill" in paragraph.lower():
                        parts = paragraph.split("this bill", 1)
                        existing_law = parts[0].strip()
                        proposed_changes = "This bill" + parts[1].strip()
                    else:
                        proposed_changes = paragraph

                # Extract code references
                code_references = self._extract_code_references(paragraph)

                digest_section = DigestSection(
                    number=str(i + 1),  # Create sequential numbers
                    text=paragraph,
                    existing_law=existing_law,
                    proposed_changes=proposed_changes,
                    code_references=code_references
                )

                digest_sections.append(digest_section)

            self.logger.info(f"Created {len(digest_sections)} digest sections from paragraphs")

        # Sort by section number
        digest_sections.sort(key=lambda x: int(x.number))

        self.logger.info(f"Parsed {len(digest_sections)} digest sections")
        return digest_sections

    def _parse_bill_sections(self, bill_text: str) -> List[BillSection]:
        """
        Parse the bill text into a list of BillSection objects with improved pattern matching
        specifically targeting the exact format of "SECTION 1." and "SEC. X."
        """
        bill_sections = []
        if not bill_text:
            self.logger.warning("No bill text to parse")
            return bill_sections

        # Pre-process the text for more reliable section detection
        normalized_text = self._aggressive_normalize_improved(bill_text)

        # Look for the first section - SECTION 1.
        first_section_pattern = r'(?:^|\n)\s*(?P<label>SECTION\s+1\.)\s*(?P<text>(?:.+?)(?=\n\s*SEC\.\s+\d+\.|\Z))'
        first_section_match = re.search(first_section_pattern, normalized_text, re.DOTALL | re.IGNORECASE)

        if first_section_match:
            section_text = first_section_match.group('text').strip()
            section_label = first_section_match.group('label').strip()

            if section_text:
                # Extract code references
                code_refs = self._extract_code_references(section_text)

                # Create first section
                bill_sections.append(BillSection(
                    number="1",
                    original_label=section_label,
                    text=section_text,
                    code_references=code_refs
                ))
                self.logger.info("Found SECTION 1.")

        # Look for all subsequent SEC. X. sections
        subsequent_pattern = r'(?:^|\n)\s*(?P<label>SEC\.\s+(?P<number>\d+)\.)\s*(?P<text>(?:.+?)(?=\n\s*SEC\.\s+\d+\.|\Z))'
        subsequent_matches = list(re.finditer(subsequent_pattern, normalized_text, re.DOTALL | re.IGNORECASE))

        self.logger.info(f"Found {len(subsequent_matches)} subsequent SEC. X. sections")

        for match in subsequent_matches:
            section_num = match.group('number')
            section_text = match.group('text').strip()
            section_label = match.group('label').strip()

            # Skip empty sections
            if not section_text:
                self.logger.warning(f"Empty text for section {section_num}, skipping")
                continue

            # Handle sections with potential amendments (e.g., [ADDED: text], [DELETED: text])
            # Replace amendment markers with cleaner text for code reference extraction
            clean_text = section_text
            clean_text = re.sub(r'\[ADDED:\s*(.*?)\]', r'\1', clean_text)
            clean_text = re.sub(r'\[DELETED:\s*(.*?)\]', r'', clean_text)

            # Extract code references from the cleaned text
            code_refs = self._extract_code_references(clean_text)

            bill_sections.append(BillSection(
                number=section_num,
                original_label=section_label,
                text=section_text,
                code_references=code_refs
            ))

            # Log detected code references for debugging
            if code_refs:
                ref_strs = [f"{ref.code_name} Section {ref.section}" for ref in code_refs]
                self.logger.debug(f"Section {section_num} references: {', '.join(ref_strs)}")

        # If we found no standard sections, try direct extraction as a last resort
        if not bill_sections:
            self.logger.warning("Standard section patterns failed, attempting direct section extraction")
            bill_sections = self._direct_section_extraction(normalized_text)

        # Sort bill sections by number
        def sort_key(section):
            try:
                return int(section.number)
            except ValueError:
                try:
                    return float(section.number)
                except ValueError:
                    return 999999  # Place invalid section numbers at the end

        bill_sections.sort(key=sort_key)


        self.logger.info(f"Successfully extracted {len(bill_sections)} bill sections")
        return bill_sections

    def _direct_section_extraction(self, normalized_text: str) -> List[BillSection]:
        """
        Fallback method to directly extract sections when regex patterns fail.
        Uses precise patterns to find sections in amended bills.
        """
        bill_sections = []

        # Find all section headers for SECTION 1. and SEC. X.
        section_markers = []

        # Look for the first section SECTION 1.
        first_section_marker = re.search(r'SECTION\s+1\.', normalized_text, re.IGNORECASE)
        if first_section_marker:
            marker_pos = first_section_marker.start()
            section_markers.append((marker_pos, "SECTION 1.", "1"))
            self.logger.info("Found SECTION 1. marker")

        # Look for subsequent SEC. X. markers
        sec_markers = re.finditer(r'SEC\.\s+(\d+)\.', normalized_text, re.IGNORECASE)
        for marker in sec_markers:
            marker_pos = marker.start()
            section_num = marker.group(1)
            section_header = marker.group(0)
            section_markers.append((marker_pos, section_header, section_num))

        # Sort markers by position in text
        section_markers.sort()

        self.logger.info(f"Found {len(section_markers)} section markers using direct extraction")

        # Extract text between markers
        for i, (pos, header, number) in enumerate(section_markers):
            start_pos = pos + len(header)

            # Find end position (next section or end of text)
            if i < len(section_markers) - 1:
                end_pos = section_markers[i+1][0]
            else:
                end_pos = len(normalized_text)

            section_text = normalized_text[start_pos:end_pos].strip()

            if section_text:
                # Extract code references
                code_refs = self._extract_code_references(section_text)

                # Create bill section
                bill_section = BillSection(
                    number=number,
                    original_label=header.strip(),
                    text=section_text,
                    code_references=code_refs
                )
                bill_sections.append(bill_section)
                self.logger.debug(f"Extracted section {number} with {len(section_text)} chars")
            else:
                self.logger.warning(f"Empty text for section {number} in direct extraction, skipping")

        return bill_sections

    def _aggressive_normalize_improved(self, text: str) -> str:
        """
        Aggressively normalize text to fix common issues with bill formatting,
        with special handling for "SECTION 1." and "SEC. X." formats.
        """
        # Replace Windows line endings
        text = text.replace('\r\n', '\n')

        # First pass: clean up added/deleted markers to standardize them
        text = re.sub(r'\[DELETED:([^\]]*)\]', r' [DELETED: \1] ', text)
        text = re.sub(r'\[ADDED:([^\]]*)\]', r' [ADDED: \1] ', text)

        # Ensure SECTION 1. is properly formatted
        # Add double newlines before SECTION 1.
        text = re.sub(r'([^\n])(SECTION\s+1\.)', r'\1\n\n\2', text, flags=re.IGNORECASE)
        # Ensure newline after SECTION 1.
        text = re.sub(r'(SECTION\s+1\.)([^\n])', r'\1\n\2', text, flags=re.IGNORECASE)

        # Ensure SEC. X. is properly formatted
        # Add double newlines before each SEC. X.
        text = re.sub(r'([^\n])(SEC\.\s+\d+\.)', r'\1\n\n\2', text, flags=re.IGNORECASE)
        # Ensure newline after each SEC. X.
        text = re.sub(r'(SEC\.\s+\d+\.)([^\n])', r'\1\n\2', text, flags=re.IGNORECASE)

        # Fix the decimal point issue - specifically for section references in amended bills
        text = re.sub(r'(\d+)\s*\n\s*(\.\d+)', r'\1\2', text)

        # Ensure "The people of the State of California do enact as follows:" is followed by double newlines
        text = re.sub(r'(The people of the State of California do enact as follows:)(?!\n)', 
                     r'\1\n\n', text, flags=re.IGNORECASE)

        # Add double newlines before each section to ensure proper separation
        text = re.sub(r'\n(\s*SECTION\s+1\.)', r'\n\n\1', text, flags=re.IGNORECASE)
        text = re.sub(r'\n(\s*SEC\.\s+\d+\.)', r'\n\n\1', text, flags=re.IGNORECASE)

        # Normalize whitespace
        text = re.sub(r'\n\s+', '\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)

        # Force a double newline after the enactment clause
        text = re.sub(
            r'(The people of the State of California do enact as follows:.*?)(\n)',
            r'\1\n\n',
            text,
            flags=re.IGNORECASE
        )

        return text

    def _extract_code_references(self, text: str) -> List[CodeReference]:
        """
        Extract code references from text with improved pattern matching for amended bills,
        e.g., "Section 123 of the Education Code"
        """
        code_references = []

        # Pattern for "Section X of the Y Code"
        pattern1 = r'Section\s+(\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        for match in re.finditer(pattern1, text, re.IGNORECASE):
            section_num = match.group(1)
            code_name = match.group(2)

            # Handle comma-separated section lists
            if ',' in section_num:
                sections = re.split(r'\s*,\s*', section_num)
                for sec in sections:
                    if sec.strip():
                        code_references.append(CodeReference(section=sec.strip(), code_name=code_name))
            else:
                code_references.append(CodeReference(section=section_num, code_name=code_name))

        # Pattern for "Y Code Section X"
        pattern2 = r'([A-Za-z\s]+Code)\s+Section\s+(\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*)'
        for match in re.finditer(pattern2, text, re.IGNORECASE):
            code_name = match.group(1)
            section_num = match.group(2)

            # Handle comma-separated section lists
            if ',' in section_num:
                sections = re.split(r'\s*,\s*', section_num)
                for sec in sections:
                    if sec.strip():
                        code_references.append(CodeReference(section=sec.strip(), code_name=code_name))
            else:
                code_references.append(CodeReference(section=section_num, code_name=code_name))

        # Pattern for "Sections X to Y of the Z Code" (ranges)
        pattern3 = r'Sections\s+(\d+(?:\.\d+)?)\s+to\s+(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        for match in re.finditer(pattern3, text, re.IGNORECASE):
            start_section = match.group(1)
            end_section = match.group(2)
            code_name = match.group(3)

            # Add both endpoints of the range
            code_references.append(CodeReference(section=start_section, code_name=code_name))
            code_references.append(CodeReference(section=end_section, code_name=code_name))

            # Try to add intermediate sections for simple integer ranges
            try:
                start = int(start_section)
                end = int(end_section)
                if end - start <= 20:  # Only expand reasonable ranges
                    for i in range(start + 1, end):
                        code_references.append(CodeReference(section=str(i), code_name=code_name))
            except ValueError:
                # Skip if we can't convert to int (e.g., decimal sections)
                pass

        return code_references

    def _match_digest_to_bill_sections(self, bill: TrailerBill) -> None:
        """
        Match digest sections to bill sections using multiple strategies
        with enhanced handling for amended bills.
        """
        # Reset any existing matches
        for digest_section in bill.digest_sections:
            digest_section.bill_sections = []

        # Create bill section map for easier lookup
        bill_section_map = {bs.number: bs for bs in bill.bill_sections}

        self.logger.info(f"Matching {len(bill.digest_sections)} digest sections to {len(bill.bill_sections)} bill sections")

        # For logging matches
        match_counts = {
            "code_reference": 0,
            "explicit_reference": 0,
            "code_name_similarity": 0,
            "content_similarity": 0,
            "fallback": 0
        }

        # For each digest section, try multiple matching strategies
        for digest_section in bill.digest_sections:
            matched_section_numbers = []
            match_type = None

            # 1. Try to match based on code references
            digest_codes = {(ref.section, ref.code_name) for ref in digest_section.code_references}

            if digest_codes:
                self.logger.debug(f"Digest section {digest_section.number} has code references: {digest_codes}")

                for bill_section in bill.bill_sections:
                    bill_codes = {(ref.section, ref.code_name) for ref in bill_section.code_references}

                    # If there's any overlap in code references, consider it a match
                    if bill_codes and digest_codes.intersection(bill_codes):
                        matched_section_numbers.append(bill_section.number)
                        match_type = "code_reference"
                        self.logger.debug(f"Matched digest {digest_section.number} to section {bill_section.number} by code references")

            if matched_section_numbers:
                match_counts["code_reference"] += len(matched_section_numbers)

            # 2. If no matches by code references, try to match by explicit section references
            if not matched_section_numbers:
                # Check for explicit reference to first section
                if re.search(r'(?:SECTION|SEC)\.\s*1\b', digest_section.text, re.IGNORECASE) and "1" in bill_section_map:
                    matched_section_numbers.append("1")
                    match_type = "explicit_reference"
                    self.logger.debug(f"Matched digest {digest_section.number} to SECTION 1 by explicit reference")

                # Check for explicit references to other sections
                for section_num in bill_section_map.keys():
                    if section_num != "1":  # Skip first section as we handled it separately
                        section_pattern = rf'SEC\.\s*{section_num}\b'
                        if re.search(section_pattern, digest_section.text, re.IGNORECASE):
                            matched_section_numbers.append(section_num)
                            match_type = "explicit_reference"
                            self.logger.debug(f"Matched digest {digest_section.number} to section {section_num} by explicit reference")

            if matched_section_numbers and match_type == "explicit_reference":
                match_counts["explicit_reference"] += len(matched_section_numbers)

            # 3. Try matching by code name similarity
            if not matched_section_numbers:
                # Extract code names from digest text
                digest_code_names = set()
                code_pattern = r'([A-Za-z\s]+Code)'
                for match in re.finditer(code_pattern, digest_section.text):
                    digest_code_names.add(match.group(1).strip())

                if digest_code_names:
                    for bill_section in bill.bill_sections:
                        bill_code_names = set()
                        for ref in bill_section.code_references:
                            bill_code_names.add(ref.code_name)

                        # If there's any overlap in code names, consider it a potential match
                        if bill_code_names and digest_code_names.intersection(bill_code_names):
                            matched_section_numbers.append(bill_section.number)
                            match_type = "code_name_similarity"
                            self.logger.debug(f"Matched digest {digest_section.number} to section {bill_section.number} by code name similarity")

            if matched_section_numbers and match_type == "code_name_similarity":
                match_counts["code_name_similarity"] += len(matched_section_numbers)

            # 4. Try matching by content similarity
            if not matched_section_numbers:
                # Look for common phrases between digest and bill sections
                digest_phrases = self._extract_key_phrases(digest_section.text)

                best_match = None
                best_score = 1  # Need at least 2 matching phrases

                for bill_section in bill.bill_sections:
                    bill_phrases = self._extract_key_phrases(bill_section.text)
                    common_phrases = digest_phrases.intersection(bill_phrases)

                    if len(common_phrases) > best_score:
                        best_score = len(common_phrases)
                        best_match = bill_section.number

                if best_match:
                    matched_section_numbers.append(best_match)
                    match_type = "content_similarity"
                    self.logger.debug(f"Matched digest {digest_section.number} to section {best_match} by content similarity")

            if matched_section_numbers and match_type == "content_similarity":
                match_counts["content_similarity"] += len(matched_section_numbers)

            # Store the matches
            digest_section.bill_sections = matched_section_numbers

        # Final pass: handle unmatched digest sections using fallback approach
        unmatched_digests = [d for d in bill.digest_sections if not d.bill_sections]
        if unmatched_digests:
            self.logger.warning(f"Found {len(unmatched_digests)} unmatched digest sections after initial matching")

            # Get all bill sections that have been matched
            matched_bill_sections = set()
            for d in bill.digest_sections:
                matched_bill_sections.update(d.bill_sections)

            # Find unmatched bill sections
            unmatched_bill_sections = [bs.number for bs in bill.bill_sections if bs.number not in matched_bill_sections]

            # Use position-based heuristic for remaining unmatched sections
            if unmatched_digests and unmatched_bill_sections:
                self.logger.info(f"Applying fallback matching for {len(unmatched_digests)} digest sections and {len(unmatched_bill_sections)} bill sections")

                # Sort both lists to match by relative position
                unmatched_bill_sections.sort(key=lambda x: int(x) if x.isdigit() else float(x))
                unmatched_digests.sort(key=lambda d: int(d.number))

                # Calculate how many bill sections to assign per digest
                sections_per_digest = max(1, len(unmatched_bill_sections) // len(unmatched_digests))

                # Distribute the sections
                for i, digest in enumerate(unmatched_digests):
                    start_idx = i * sections_per_digest
                    end_idx = min(start_idx + sections_per_digest, len(unmatched_bill_sections))

                    for j in range(start_idx, end_idx):
                        if j < len(unmatched_bill_sections):
                            digest.bill_sections.append(unmatched_bill_sections[j])
                            match_counts["fallback"] += 1
                            self.logger.debug(f"Fallback match: digest {digest.number} to bill section {unmatched_bill_sections[j]}")

        # Log matching results
        matched_digests = sum(1 for d in bill.digest_sections if d.bill_sections)
        total_matches = sum(match_counts.values())

        self.logger.info(f"Matched {matched_digests} of {len(bill.digest_sections)} digest sections")
        self.logger.info(f"Total matches: {total_matches} - By code reference: {match_counts['code_reference']}, "
                        f"By explicit reference: {match_counts['explicit_reference']}, "
                        f"By code name: {match_counts['code_name_similarity']}, "
                        f"By content similarity: {match_counts['content_similarity']}, "
                        f"By fallback: {match_counts['fallback']}")

    def _extract_key_phrases(self, text: str, min_length: int = 5) -> set:
        """Extract key phrases for matching content similarity"""
        # Normalize text
        text = text.lower()

        # Remove common words and punctuation
        words = re.findall(r'\b[a-z]{3,}\b', text)

        # Extract phrases (sequences of 3 consecutive words)
        phrases = set()
        for i in range(len(words) - 2):
            phrase = ' '.join(words[i:i+3])
            if len(phrase.split()) >= min_length:
                phrases.add(phrase)

        return phrases