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
        # Create debug directory
        debug_dir = "debug_output"
        os.makedirs(debug_dir, exist_ok=True)

        # Save initial HTML
        with open(os.path.join(debug_dir, "initial_bill.html"), "w", encoding="utf-8") as f:
            f.write(bill_html)

        self.logger.info("Starting to split digest and bill text")

        # Fix malformed HTML before processing
        clean_html = self._fix_malformed_html(bill_html)

        # Save cleaned HTML
        with open(os.path.join(debug_dir, "cleaned_bill.html"), "w", encoding="utf-8") as f:
            f.write(clean_html)

        soup = BeautifulSoup(clean_html, "html.parser")

        # Try multiple approaches to find the digest and bill sections

        # Approach 1: Look for specific containers
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

        # Save extracted sections for debugging
        with open(os.path.join(debug_dir, "extracted_digest.txt"), "w", encoding="utf-8") as f:
            f.write(digest_text)
        with open(os.path.join(debug_dir, "extracted_bill.txt"), "w", encoding="utf-8") as f:
            f.write(bill_text)

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

    def _direct_section_extraction(self, normalized_text: str) -> List[BillSection]:
        """
        Fallback method to directly extract sections when regex patterns fail.
        Now with improved handling of amended bills.
        """
        bill_sections = []

        # Find all section headers
        section_markers = []

        # Look for both "SECTION X." and "SEC. X." with enhanced pattern matching
        patterns = [
            r'\n\s*(SECTION\s+(\d+(?:\.\d+)?)\.)',
            r'\n\s*(SEC\.\s+(\d+(?:\.\d+)?)\.)' 
        ]

        for pattern in patterns:
            markers = re.findall(pattern, normalized_text, flags=re.IGNORECASE)
            section_markers.extend(markers)

        # Sort markers by their position in the text
        section_positions = []
        for header, number in section_markers:
            pos = normalized_text.find(header)
            if pos != -1:
                section_positions.append((pos, header, number))

        # Sort by position to ensure correct order
        section_positions.sort()

        self.logger.info(f"Found {len(section_positions)} potential section markers")

        # Extract text between section headers
        for i, (pos, header, number) in enumerate(section_positions):
            start_pos = pos + len(header)

            # Find end position (next section or end of text)
            if i < len(section_positions) - 1:
                end_pos = section_positions[i+1][0]
            else:
                end_pos = len(normalized_text)

            section_text = normalized_text[start_pos:end_pos].strip()
            if section_text:
                # Extract code references
                code_refs = self._extract_code_references(section_text)

                bill_section = BillSection(
                    number=number,
                    original_label=header.strip(),
                    text=section_text,
                    code_references=code_refs
                )
                bill_sections.append(bill_section)
                self.logger.debug(f"Extracted section {number} with {len(section_text)} chars")

        return bill_sections

    def _parse_bill_sections(self, bill_text: str) -> List[BillSection]:
        """
        Parse the bill text into a list of BillSection objects with improved pattern matching
        and handling of amended bills.
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
            r'(?:^|\n)\s*(?P<label>(?:SECTION|SEC)\.?\s+(?P<number>\d+(?:\.\d+)?)\.)\s*(?P<text>(?:.+?)(?=\n\s*(?:SECTION|SEC)\.?\s+\d+(?:\.\d+)?\.|\Z))',

            # Pattern 2: More flexible with optional whitespace
            r'(?:^|\n)\s*(?P<label>(?:SECTION|SEC)\.?\s*(?P<number>\d+(?:\.\d+)?)\.)\s*(?P<text>(?:.+?)(?=\n\s*(?:SECTION|SEC)\.?\s*\d+(?:\.\d+)?\.|\Z))',

            # Pattern 3: Force matches at "SEC. X." regardless of surrounding context
            r'\n\s*(?P<label>SEC\.\s+(?P<number>\d+(?:\.\d+)?)\.)\s*(?P<text>(?:.+?)(?=\n\s*SEC\.\s+\d+(?:\.\d+)?\.|\Z))',

            # Pattern 4: Even more flexible pattern for problematic cases
            r'(?P<label>(?:SECTION|SEC)\.?\s+(?P<number>\d+(?:\.\d+)?)\.)[^\n]*(?P<text>(?:.+?)(?=(?:SECTION|SEC)\.?\s+\d+(?:\.\d+)?\.|\Z))',
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
                bill_sections.sort(key=lambda x: float(x.number) if '.' in x.number else int(x.number))
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

        # If we still have no sections, try one more approach - look for section headings
        if not bill_sections:
            self.logger.warning("All patterns failed, trying one last section extraction approach")

            # Simply look for text blocks that start with something that looks like a section marker
            section_blocks = re.split(r'\n\s*(?=SEC\.|SECTION)', normalized_text)

            for block in section_blocks:
                if not block.strip():
                    continue

                # Try to extract section number
                section_match = re.match(r'(?:SEC\.|SECTION)\s+(\d+(?:\.\d+)?)', block)
                if section_match:
                    section_num = section_match.group(1)
                    label_end_pos = block.find('.')

                    if label_end_pos > 0:
                        section_label = block[:label_end_pos+1].strip()
                        section_text = block[label_end_pos+1:].strip()

                        if section_text:
                            code_refs = self._extract_code_references(section_text)

                            bill_section = BillSection(
                                number=section_num,
                                original_label=section_label,
                                text=section_text,
                                code_references=code_refs
                            )

                            bill_sections.append(bill_section)

        # Sort by section number, handling both integer and decimal section numbers
        def sort_key(section):
            try:
                return float(section.number) if '.' in section.number else int(section.number)
            except ValueError:
                return 999  # Put sections with invalid numbers at the end

        bill_sections.sort(key=sort_key)

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
        text = re.sub(r'(\n\s*)(SEC\.?|SECTION)(\s*)(\d+(?:\.\d+)?)(\.\s*)', r'\n\2 \4\5', text)

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
        text = re.sub(r'\n(\s*(?:SEC\.|SECTION)\s+\d+(?:\.\d+)?\.)', r'\n\n\1', text, flags=re.IGNORECASE)

        # Make sure section headers are followed by a newline
        text = re.sub(r'((?:SEC\.|SECTION)\s+\d+(?:\.\d+)?\.)([^\n])', r'\1\n\2', text, flags=re.IGNORECASE)

        # Handle amendments by removing strikethrough markers and preserving added text
        text = re.sub(r'<strike>.*?</strike>', '', text)
        text = re.sub(r'<font color="blue"><i>(.*?)</i></font>', r'\1', text)

        # Remove HTML tags that might interfere with parsing
        text = re.sub(r'<[^>]+>', ' ', text)

        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)

        # Re-add newlines for section headers to ensure proper separation
        text = re.sub(r'(SEC\.\s+\d+(?:\.\d+)?\.)', r'\n\n\1\n', text, flags=re.IGNORECASE)
        text = re.sub(r'(SECTION\s+\d+(?:\.\d+)?\.)', r'\n\n\1\n', text, flags=re.IGNORECASE)

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
        Match digest sections to bill sections using multiple enhanced heuristics
        """
        # Reset any existing matches
        for digest_section in bill.digest_sections:
            digest_section.bill_sections = []

        # 1. Try to match based on code references
        for digest_section in bill.digest_sections:
            matched_section_numbers = []

            # Get code references from digest
            digest_codes = {(ref.section, ref.code_name) for ref in digest_section.code_references}

            if digest_codes:
                for bill_section in bill.bill_sections:
                    # Get code references from bill section
                    bill_codes = {(ref.section, ref.code_name) for ref in bill_section.code_references}

                    # If there's any overlap in code references, consider it a match
                    if bill_codes and digest_codes.intersection(bill_codes):
                        matched_section_numbers.append(bill_section.number)
                        self.logger.debug(f"Matched digest {digest_section.number} to section {bill_section.number} by code references")

            # 2. If nothing matched by code references, try to match by explicit section references in digest
            if not matched_section_numbers:
                for bill_section in bill.bill_sections:
                    # Look for explicit references to SEC. X or SECTION X
                    section_pattern = rf'(?:SEC|SECTION)\.\s*{bill_section.number}\b'
                    if re.search(section_pattern, digest_section.text, re.IGNORECASE):
                        matched_section_numbers.append(bill_section.number)
                        self.logger.debug(f"Matched digest {digest_section.number} to section {bill_section.number} by explicit reference")

            # 3. Try matching by content similarity
            if not matched_section_numbers:
                # Look for common phrases between digest and bill sections
                digest_phrases = self._extract_key_phrases(digest_section.text)

                for bill_section in bill.bill_sections:
                    bill_phrases = self._extract_key_phrases(bill_section.text)

                    # Check for overlapping phrases
                    common_phrases = digest_phrases.intersection(bill_phrases)
                    if len(common_phrases) >= 2:  # Require at least 2 common phrases
                        matched_section_numbers.append(bill_section.number)
                        self.logger.debug(f"Matched digest {digest_section.number} to section {bill_section.number} by content similarity")

            # 4. Last resort - if this is the only unmatched digest section, match to any unmatched bill sections
            if not matched_section_numbers:
                # Check if this is the only unmatched digest section
                other_unmatched = sum(1 for d in bill.digest_sections if d.number != digest_section.number and not d.bill_sections)

                if other_unmatched == 0:
                    # Find bill sections that aren't matched to any digest section
                    matched_bill_sections = set()
                    for d in bill.digest_sections:
                        matched_bill_sections.update(d.bill_sections)

                    unmatched_bill_sections = [b.number for b in bill.bill_sections if b.number not in matched_bill_sections]

                    if unmatched_bill_sections:
                        matched_section_numbers.extend(unmatched_bill_sections)
                        self.logger.debug(f"Matched digest {digest_section.number} to section(s) {', '.join(unmatched_bill_sections)} as last resort")

            # Store the matches
            digest_section.bill_sections = matched_section_numbers

        # Verify results
        matched_digests = sum(1 for d in bill.digest_sections if d.bill_sections)
        self.logger.info(f"Matched {matched_digests} of {len(bill.digest_sections)} digest sections to bill sections")

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