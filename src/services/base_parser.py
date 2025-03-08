import re
import logging
import traceback
from datetime import datetime
from typing import List, Tuple, Optional, Set
from src.models.bill_components import (
    TrailerBill,
    DigestSection,
    BillSection,
    CodeReference,
    CodeAction
)

class BillParser:
    """
    Enhanced parser for handling trailer bills, including those with amendment markup.
    Properly processes bills with HTML formatting, strikethroughs, and additions.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

        # Pattern for identifying the basic bill header
        # Tweaked to allow multi-line spacing between "Assembly/Senate Bill No.X" and "CHAPTER Y"
        self.bill_header_pattern = (
            r'(Assembly|Senate)\s+Bill\s+(?:No\.?\s+)?(\d+)\s+(?:CHAPTER\s+(\d+))'
        )

        self.digest_section_pattern = r'\((\d+)\)\s+([^(]+)(?=\(\d+\)|$)'

        # Regex for capturing "SECTION 1." or "SEC. X." blocks
        # We'll handle newlines/spaces in a more robust manner
        self.bill_section_pattern = re.compile(
            r'(?:^|\n+)\s*'
            r'(?P<label>(?:SECTION|SEC)\.\s+(?P<number>\d+)\.)'
            r'\s*(?P<body>.*?)(?='
            r'(?:\n+(?:SECTION|SEC)\.\s+\d+\.|$))',
            re.DOTALL | re.IGNORECASE
        )

        self.date_pattern = (
            r'Approved by Governor\s+([^.]+)\.\s+Filed with Secretary of State\s+([^.]+)\.'
        )

    def parse_bill(self, bill_text: str) -> TrailerBill:
        """
        Parse the entire bill text and return a TrailerBill object containing:
          - Bill header info
          - List of DigestSection objects
          - List of BillSection objects
        """
        # First clean any HTML markup from amended bills
        cleaned_text = self._clean_html_markup(bill_text)

        # Then normalize section breaks for consistent parsing
        cleaned_text = self._normalize_section_breaks(cleaned_text)

        # Now parse the bill components
        header_info = self._parse_bill_header(cleaned_text)

        bill = TrailerBill(
            bill_number=header_info['bill_number'],
            title=header_info['title'],
            chapter_number=header_info['chapter_number'],
            date_approved=header_info['date_approved'],
            date_filed=header_info['date_filed'],
            raw_text=cleaned_text
        )

        # Split the bill text into digest and bill portions
        digest_text, bill_portion = self._split_digest_and_bill(cleaned_text)

        # Parse each portion
        bill.digest_sections = self._parse_digest_sections(digest_text)
        bill.bill_sections = self._parse_bill_sections(bill_portion)

        # Match digest sections to bill sections
        self._match_sections(bill)

        return bill

    def _clean_html_markup(self, text: str) -> str:
        """
        Clean HTML markup from amended bills to create plain text that's easier to parse.
        Handles strikethroughs, additions, and other HTML formatting.
        """
        # First, handle the strike-through content (removed text)
        # We simply remove it since it's not part of the final bill text
        text = re.sub(r'<font color="#B30000"><strike>.*?</strike></font>', '', text, flags=re.DOTALL)

        # Then handle blue text (added text)
        # We keep this content but remove the HTML markup
        text = re.sub(r'<font color="blue" class="blue_text"><i>(.*?)</i></font>', r'\1', text, flags=re.DOTALL)

        # Remove any remaining HTML tags
        text = re.sub(r'<[^>]*>', '', text)

        # Clean up extra whitespace
        text = re.sub(r'\s+', ' ', text)

        # Make sure section identifiers are separated by newlines
        text = re.sub(r'([^\n])(SEC\.|SECTION)', r'\1\n\2', text, flags=re.IGNORECASE)

        # Ensure consistency in section formatting
        text = re.sub(r'\n\s*(SEC\.?|SECTION)\s*(\d+)\.\s*', r'\n\1 \2.\n', text, flags=re.IGNORECASE)

        return text

    def _parse_bill_header(self, text: str) -> dict:
        header_match = re.search(self.bill_header_pattern, text, re.MULTILINE | re.IGNORECASE | re.DOTALL)
        if not header_match:
            self.logger.warning("Could not parse bill header with standard pattern")
            return {
                'bill_number': "",
                'chapter_number': "",
                'title': "",
                'date_approved': None,
                'date_filed': None
            }

        # If CHAPTER group is missing, we assign an empty string
        # (Some trailer bills might omit the word "CHAPTER X" in the text)
        chapter = header_match.group(3) if header_match.lastindex >= 3 else ""

        date_match = re.search(self.date_pattern, text)

        return {
            'bill_number': f"{header_match.group(1)} Bill {header_match.group(2)}",
            'chapter_number': chapter if chapter else "",
            'title': self._extract_title(text),
            'date_approved': self._parse_date(date_match.group(1)) if date_match else None,
            'date_filed': self._parse_date(date_match.group(2)) if date_match else None
        }

    def _split_digest_and_bill(self, text: str) -> Tuple[str, str]:
        lower_text = text.lower()
        digest_start = lower_text.find("legislative counsel's digest")
        if digest_start == -1:
            self.logger.info("No 'Legislative Counsel's Digest' found.")
            return "", text

        digest_end = lower_text.find(
            "the people of the state of california do enact as follows:"
        )
        if digest_end == -1:
            # Fallback pattern if the exact phrase wasn't found
            fallback_pattern = r"the people of the state of california do enact"
            m = re.search(fallback_pattern, lower_text, re.IGNORECASE)
            digest_end = m.start() if m else len(text)

        digest_text = text[digest_start:digest_end].strip()
        bill_portion = text[digest_end:].strip()
        return digest_text, bill_portion

    def _parse_digest_sections(self, digest_text: str) -> List[DigestSection]:
        if not digest_text:
            return []

        sections = []
        matches = re.finditer(self.digest_section_pattern, digest_text, re.DOTALL)
        for match in matches:
            number = match.group(1)
            text_chunk = match.group(2).strip()
            existing_law, changes = self._split_existing_and_changes(text_chunk)
            code_refs = self._extract_code_references(text_chunk)

            section = DigestSection(
                number=number,
                text=text_chunk,
                existing_law=existing_law,
                proposed_changes=changes,
                code_references=code_refs
            )
            sections.append(section)
        return sections

    def _parse_bill_sections(self, bill_portion: str) -> List[BillSection]:
        """
        Enhanced section parser that handles both clean bills and bills with
        amendment markup. Uses multiple strategies to find and extract sections.
        """
        sections = []
        cleaned_text = bill_portion.strip()

        # Apply aggressive normalization to the text
        normalized_text = self._aggressive_normalize(cleaned_text)

        # Try multiple section patterns with increasing flexibility
        section_patterns = [
            # Standard format with newline
            r'(?:^|\n)\s*(?P<label>(?:SECTION|SEC)\.?\s+(?P<number>\d+)\.)\s*(?P<text>(?:.+?)(?=\n\s*(?:SECTION|SEC)\.?\s+\d+\.|\Z))',

            # More flexible with optional whitespace
            r'(?:^|\n)\s*(?P<label>(?:SECTION|SEC)\.?\s*(?P<number>\d+)\.)\s*(?P<text>(?:.+?)(?=\n\s*(?:SECTION|SEC)\.?\s*\d+\.|\Z))',

            # Force matches at "SEC. X." regardless of surrounding context
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
            self.logger.warning("Standard patterns failed, attempting fallback section extraction")
            # Use fallback method
            return self._parse_bill_sections_fallback(cleaned_text)

        # Process matches
        for match in all_matches:
            section_num = match.group('number')
            section_text = match.group('text').strip()
            section_label = match.group('label').strip()

            # Skip empty sections
            if not section_text:
                self.logger.warning(f"Empty text for section {section_num}, skipping")
                continue

            # Extract code references with special handling for decimal points
            code_refs = self._extract_code_references_robust(section_text)

            bs = BillSection(
                number=section_num,
                original_label=section_label,
                text=section_text,
                code_references=code_refs
            )

            action_type = self._determine_action(section_text)
            if action_type != CodeAction.UNKNOWN:
                bs.section_type = action_type

            sections.append(bs)

        self.logger.info(f"Parsed {len(sections)} bill sections: {[s.original_label for s in sections]}")
        return sections

    def _parse_bill_sections_fallback(self, bill_portion: str) -> List[BillSection]:
        """
        Fallback section parser that uses direct extraction methods when regular patterns fail.
        This is especially useful for bills with complex formatting or amendments.
        """
        self.logger.info(f"Starting fallback parsing with text length: {len(bill_portion)}")

        sections = []

        # Method 1: Look for section headers directly
        pattern = re.compile(
            r'((?:SECTION|SEC)\.?\s+\d+\.)',
            re.IGNORECASE
        )

        # Find all section headers
        matches = list(pattern.finditer(bill_portion))
        self.logger.info(f"Found {len(matches)} section headers")

        if matches:
            # Extract sections based on the headers found
            for i, match in enumerate(matches):
                start_idx = match.start()
                label = match.group(1)

                # The next heading or end of the bill text
                if i < len(matches) - 1:
                    end_idx = matches[i+1].start()
                else:
                    end_idx = len(bill_portion)

                section_text = bill_portion[start_idx:end_idx].strip()

                # Extract the section number
                sec_num_match = re.search(r'(?:SECTION|SEC\.?)\s+(\d+)\.', label, re.IGNORECASE)
                sec_num = sec_num_match.group(1) if sec_num_match else f"Unknown_{i+1}"

                # The body is everything after the label
                body_parts = section_text.split('\n', 1)
                body = body_parts[1] if len(body_parts) > 1 else ""

                # Create the BillSection object
                code_refs = self._extract_code_references_robust(body)
                action_type = self._determine_action(body)

                bs = BillSection(
                    number=sec_num,
                    original_label=label.strip(),
                    text=body.strip(),
                    code_references=code_refs
                )

                if action_type != CodeAction.UNKNOWN:
                    bs.section_type = action_type

                sections.append(bs)
                self.logger.info(f"Fallback added section {sec_num} with label '{label}'")

        # Method 2: If no sections found yet, try a more aggressive approach
        if not sections:
            self.logger.info("Trying more aggressive section extraction")

            # Strip all HTML completely and normalize whitespace
            cleaned_text = re.sub(r'<[^>]*>', '', bill_portion)
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text)

            # Force section headers to be on new lines
            cleaned_text = re.sub(r'([^\n])(SECTION|SEC\.)', r'\1\n\2', cleaned_text, flags=re.IGNORECASE)

            # Try to find section headers more aggressively
            section_headers = re.findall(r'\n\s*((?:SECTION|SEC\.)\s+(\d+)\.)', cleaned_text, re.IGNORECASE)

            self.logger.info(f"Aggressive approach found {len(section_headers)} section headers")

            if section_headers:
                for i, (header, number) in enumerate(section_headers):
                    start_pos = cleaned_text.find(header) + len(header)

                    if i < len(section_headers) - 1:
                        next_header = section_headers[i+1][0]
                        end_pos = cleaned_text.find(next_header)
                    else:
                        end_pos = len(cleaned_text)

                    section_text = cleaned_text[start_pos:end_pos].strip()

                    # Create a BillSection object
                    bs = BillSection(
                        number=number,
                        original_label=header.strip(),
                        text=section_text,
                        code_references=self._extract_code_references_robust(section_text)
                    )

                    sections.append(bs)
                    self.logger.info(f"Aggressive fallback added section {number}")

        self.logger.info(f"Fallback parse completed with {len(sections)} sections")
        return sections


    def _aggressive_normalize(self, text: str) -> str:
        """
        Aggressively normalize text to fix common issues with bill formatting,
        especially handling decimal points in section numbers.
        """
        # Replace Windows line endings
        text = text.replace('\r\n', '\n')

        # Ensure consistent spacing around section headers
        text = re.sub(r'(\n\s*)(SEC\.?|SECTION)(\s*)(\d+)(\.\s*)', r'\n\2 \4\5', text, flags=re.IGNORECASE)

        # Fix the decimal point issue - remove line breaks between section numbers and decimal points
        text = re.sub(r'(\d+)\s*\n\s*(\.\d+)', r'\1\2', text)

        # Standardize decimal points in section headers
        text = re.sub(r'Section\s+(\d+)\s*\n\s*(\.\d+)', r'Section \1\2', text)

        # Ensure section headers are properly separated with newlines
        text = re.sub(r'([^\n])(SEC\.|SECTION)', r'\1\n\2', text)

        return text

    def _extract_code_references_robust(self, text: str) -> List[CodeReference]:
        """
        Extract code references with special handling for decimal points and other formatting issues.
        """
        references = []

        # Check first for the amended/added/repealed pattern that's common in section headers
        first_line = text.split('\n', 1)[0] if '\n' in text else text

        # Normalize the section number if it contains a decimal point
        first_line = re.sub(r'(\d+)\s*\n\s*(\.\d+)', r'\1\2', first_line)

        # Pattern for "Section X of the Y Code is amended/added/repealed"
        section_header_pattern = r'(?i)Section\s+(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        header_match = re.search(section_header_pattern, first_line)

        if header_match:
            section_num = header_match.group(1).strip()
            code_name = header_match.group(2).strip()
            references.append(CodeReference(section=section_num, code_name=code_name))
            self.logger.debug(f"Found primary code reference: {code_name} Section {section_num}")

        # Special case for Education Code sections with decimal points
        decimal_pattern = r'Section\s+(\d+\.\d+)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        for match in re.finditer(decimal_pattern, text):
            section_num = match.group(1).strip()
            code_name = match.group(2).strip()
            references.append(CodeReference(section=section_num, code_name=code_name))

        # Handle other standard reference formats
        patterns = [
            # Standard format: "Section 123 of the Education Code"
            r'(?i)Section(?:s)?\s+(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)',

            # Reverse format: "Education Code Section 123"
            r'(?i)([A-Za-z\s]+Code)\s+Section(?:s)?\s+(\d+(?:\.\d+)?)',
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text):
                if len(match.groups()) == 2:
                    if "code" in match.group(2).lower():  # Standard format
                        section_num = match.group(1).strip()
                        code_name = match.group(2).strip()
                    else:  # Reverse format
                        code_name = match.group(1).strip()
                        section_num = match.group(2).strip()

                    references.append(CodeReference(section=section_num, code_name=code_name))

        return references