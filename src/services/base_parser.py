import re
import logging
import traceback
from datetime import datetime
from typing import List, Tuple, Optional
from src.models.bill_components import (
    TrailerBill,
    DigestSection,
    BillSection,
    CodeReference,
    CodeAction
)

class BaseParser:
    """
    Handles initial regex-based parsing of trailer bills to extract basic structure,
    digest sections, and bill sections, including code references.
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
        cleaned_text = self._normalize_section_breaks(bill_text)
        header_info = self._parse_bill_header(cleaned_text)

        bill = TrailerBill(
            bill_number=header_info['bill_number'],
            title=header_info['title'],
            chapter_number=header_info['chapter_number'],
            date_approved=header_info['date_approved'],
            date_filed=header_info['date_filed'],
            raw_text=cleaned_text
        )

        digest_text, bill_portion = self._split_digest_and_bill(cleaned_text)
        bill.digest_sections = self._parse_digest_sections(digest_text)
        bill.bill_sections = self._parse_bill_sections(bill_portion)

        self._match_sections(bill)
        return bill

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
        Parses all sections from the main bill text using a robust regex pattern
        that captures both 'SECTION 1.' and 'SEC. 2.' style headings.
        """
        sections = []
        cleaned_text = bill_portion.strip()

        # Potentially normalize section breaks a bit more to ensure consistent newlines:
        normalized_text = self._normalize_section_breaks(cleaned_text)

        section_matches = list(self.bill_section_pattern.finditer(normalized_text))
        self.logger.info(f"Found {len(section_matches)} potential bill sections")

        if not section_matches:
            # Attempt a fallback approach if no sections found at all
            self.logger.warning("No sections found with primary pattern, attempting fallback.")
            return self._parse_bill_sections_debug(cleaned_text)

        for match in section_matches:
            label = match.group('label').strip()
            number = match.group('number')
            body_text = match.group('body').strip()

            if not body_text:
                self.logger.warning(f"Empty body found for section {number}, skipping")
                continue

            self.logger.info(f"Found section with label '{label}'")

            code_refs = self._extract_code_references(body_text)
            action_type = self._determine_action(body_text)

            bs = BillSection(
                number=number,
                original_label=label,
                text=body_text,
                code_references=code_refs
            )

            if action_type != CodeAction.UNKNOWN:
                bs.section_type = action_type

            sections.append(bs)

            if code_refs:
                ref_strings = [f"{ref.code_name}:{ref.section}" for ref in code_refs]
                self.logger.info(f"Found {len(code_refs)} code references in section {number}: {ref_strings}")
            else:
                self.logger.warning(f"No code references found in section {number}")

        self.logger.info(f"Parsed {len(sections)} bill sections: {[s.original_label for s in sections]}")
        return sections

    def _parse_bill_sections_debug(self, bill_portion: str) -> List[BillSection]:
        """
        A fallback debug parser that tries a simpler approach if the main regex fails.
        Logs extensive information for troubleshooting.
        """
        self.logger.info(f"Starting fallback parsing with text length: {len(bill_portion)}")

        sections = []
        # Simple pattern: look for lines that start with "SECTION N." or "SEC. N."
        # Then read until we encounter the next "SECTION/SEC." or the end of text
        pattern = re.compile(
            r'(SECTION\s+\d+\.|SEC\.\s+\d+\.)',
            re.IGNORECASE
        )

        # Collect all indexes where these headings appear
        matches = list(pattern.finditer(bill_portion))
        self.logger.info(f"FOUND HEADERS: {len(matches)}")

        for i, match in enumerate(matches):
            start_idx = match.start()
            label = match.group(1)

            # The next heading or end of the bill text
            if i < len(matches) - 1:
                end_idx = matches[i+1].start()
            else:
                end_idx = len(bill_portion)

            section_text = bill_portion[start_idx:end_idx].strip()

            # Attempt to extract the number from the label
            sec_num_match = re.search(r'(?:SECTION|SEC\.?)\s+(\d+)\.', label, re.IGNORECASE)
            sec_num = sec_num_match.group(1) if sec_num_match else f"Unknown_{i+1}"

            # The "body" is everything after the label
            body_lines = section_text.split('\n', 1)
            body = body_lines[1] if len(body_lines) > 1 else ""

            code_refs = self._extract_code_references(body)
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

        self.logger.info(f"Fallback parse completed with {len(sections)} sections")
        return sections

    def _aggressive_normalize_section_breaks(self, text: str) -> str:
        """
        Enhanced normalization of section breaks with more aggressive pattern matching.
        This is a fallback when regular normalization fails.
        """
        # First, ensure there's a newline before any SEC. or SECTION patterns
        text = re.sub(
            r'(?<!\n)(?:\s*)(SEC(?:TION)?\.?\s+\d+\.)',
            r'\n\1',
            text,
            flags=re.IGNORECASE
        )

        # Standardize spacing around section labels
        text = re.sub(
            r'(SEC(?:TION)?\.)\s*(\d+)\.',
            r'\1 \2.',
            text,
            flags=re.IGNORECASE
        )

        # Ensure there's an extra newline between sections for clarity
        text = re.sub(
            r'(\n(?:SECTION|SEC)\.\s+\d+\..*?)(\n(?:SECTION|SEC)\.\s+\d+\.)',
            r'\1\n\2',
            text,
            flags=re.IGNORECASE | re.DOTALL
        )

        return text

    def _extract_code_references(self, text: str) -> List[CodeReference]:
        """
        Enhanced code reference extraction with improved pattern matching.
        Looks for references like 'Section 123 of the Education Code', 
        'Education Code Section 123', or '... is amended in the Penal Code ...'
        """
        references = []

        # Basic patterns:
        pattern1 = r'(?i)Section\s+(\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        pattern2 = r'(?i)([A-Za-z\s]+Code)\s+Section\s+(\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*)'

        # We'll store unique references in a set (code_name, section_number)
        unique_refs = set()

        # Pattern 1: "Section X of the Y Code"
        for match in re.finditer(pattern1, text):
            sections_str = match.group(1)
            code_name = match.group(2).strip()
            for section_num in re.split(r'\s*,\s*', sections_str):
                if section_num.strip():
                    unique_refs.add((code_name, section_num.strip()))

        # Pattern 2: "Y Code Section X"
        for match in re.finditer(pattern2, text):
            code_name = match.group(1).strip()
            sections_str = match.group(2)
            for section_num in re.split(r'\s*,\s*', sections_str):
                if section_num.strip():
                    unique_refs.add((code_name, section_num.strip()))

        # Convert into CodeReference objects
        for code_name, section_num in unique_refs:
            references.append(CodeReference(section=section_num, code_name=code_name))

        return references

    def _split_section_list(self, sections_str: str) -> List[str]:
        s = re.sub(r'\s+and\s+', ',', sections_str, flags=re.IGNORECASE)
        s = re.sub(r'\s+', '', s)
        parts = re.split(r',', s)
        return [p for p in parts if p]

    def _parse_section_header(self, text: str) -> Tuple[List[CodeReference], Optional[CodeAction]]:
        first_line = text.split('\n', 1)[0]
        action = self._determine_action(first_line)
        refs = self._extract_code_references(first_line)
        return refs, action

    def _determine_action(self, text: str) -> CodeAction:
        lower = text.lower()
        if "repealed and added" in lower:
            return CodeAction.REPEALED_AND_ADDED
        if "amended and repealed" in lower:
            return CodeAction.AMENDED_AND_REPEALED
        if "amended" in lower:
            return CodeAction.AMENDED
        if "added" in lower:
            return CodeAction.ADDED
        if "repealed" in lower:
            return CodeAction.REPEALED
        return CodeAction.UNKNOWN

    def _split_existing_and_changes(self, text: str) -> Tuple[str, str]:
        """
        Attempts to split digest text into "existing law" vs. "this bill would" changes.
        """
        if not text or not isinstance(text, str):
            return "", ""

        existing_text = ""
        change_text = text

        pattern = r"(Existing law.*?)(This bill would.*)"
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            existing_text = match.group(1).strip()
            change_text = match.group(2).strip()
            return existing_text, change_text

        return text.strip(), ""

    def _match_sections(self, bill: TrailerBill) -> None:
        """
        Match up digest sections to bill sections that share code references
        (simple approach - real matching logic is done in SectionMatcher).
        """
        matches_found = 0
        for dsec in bill.digest_sections:
            digest_refs = {f"{ref.code_name}:{ref.section}" for ref in dsec.code_references}
            self.logger.info(f"Digest section {dsec.number} has refs: {digest_refs}")

            for bsec in bill.bill_sections:
                bill_refs = {f"{ref.code_name}:{ref.section}" for ref in bsec.code_references}
                overlap = digest_refs & bill_refs
                if overlap:
                    dsec.bill_sections.append(bsec.number)
                    bsec.digest_reference = dsec.number
                    matches_found += 1
                    self.logger.info(
                        f"Matched digest {dsec.number} to bill section {bsec.number} via refs: {overlap}"
                    )

        self.logger.info(f"Total section matches found: {matches_found}")

    def _extract_title(self, text: str) -> str:
        pattern = r'An act to .*?(?=\[|LEGISLATIVE COUNSEL|$)'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return match.group().strip() if match else ""

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        try:
            return datetime.strptime(date_str.strip(), '%B %d, %Y')
        except ValueError:
            return None

    def _normalize_section_breaks(self, text: str) -> str:
        """
        Insert line breaks before 'SECTION N.' or 'SEC. N.' if not already present,
        ensuring each section starts on a fresh line for easier parsing.
        """
        # Convert Windows line endings
        text = text.replace('\r\n', '\n')

        # Ensure there's a newline before 'SEC. X.' or 'SECTION X.'
        text = re.sub(
            r'(?<!\n)(?:\s*)(SECTION\s+\d+\.|SEC\.\s+\d+\.)',
            r'\n\1',
            text,
            flags=re.IGNORECASE
        )

        return text
