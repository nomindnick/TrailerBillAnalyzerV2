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

        # Patterns for identifying the basic bill header
        self.bill_header_pattern = (
            r'(Assembly|Senate)\s+Bill\s+(?:No\.?\s+)?(\d+)\s+CHAPTER\s*(\d+)\s*'
        )
        self.digest_section_pattern = r'\((\d+)\)\s+([^(]+)(?=\(\d+\)|$)'

        # We capture: group(1) = "SECTION" or "SEC.", group(2) = the numeric portion, group(3) = remainder of the text
        self.bill_section_pattern = (
            r'(?:^|\r?\n)(SEC(?:TION)?\.?)\s+(\d+)(?:\.)?\s*(.*?)(?=\r?\nSEC(?:TION)?\.?\s+\d+|\Z)'
        )
        self.date_pattern = (
            r'Approved by Governor\s+([^.]+)\.\s+Filed with Secretary of State\s+([^.]+)\.'
        )

    def parse_bill(self, bill_text: str) -> TrailerBill:
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
        header_match = re.search(self.bill_header_pattern, text, re.MULTILINE | re.IGNORECASE)
        if not header_match:
            self.logger.warning("Could not parse bill header with standard pattern")
            return {
                'bill_number': "",
                'chapter_number': "",
                'title': "",
                'date_approved': None,
                'date_filed': None
            }

        date_match = re.search(self.date_pattern, text)

        return {
            'bill_number': f"{header_match.group(1)} Bill {header_match.group(2)}",
            'chapter_number': header_match.group(3),
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
        Parse bill sections with improved pattern matching and error handling.
        """
        sections = []
        cleaned_text = bill_portion.strip()

        # Log a sample of the text we're about to parse (first 200 chars)
        self.logger.debug(f"Processing bill text (sample): {cleaned_text[:200]}...")

        # More robust unified pattern that handles both "SECTION X." and "SEC. X." formats
        # This pattern works with any whitespace variations and captures both formats
        section_pattern = re.compile(
            r'(?:^|\n)(?P<label>(?:SECTION|SEC)\.\s+(?P<number>\d+)\.)\s*(?P<body>.*?)(?=\n(?:SECTION|SEC)\.\s+\d+\.|\Z)',
            re.DOTALL
        )

        # Find all matching sections
        section_matches = list(section_pattern.finditer(cleaned_text))
        self.logger.info(f"Found {len(section_matches)} potential bill sections")

        if not section_matches:
            # If no sections found, try fallback normalization
            self.logger.warning("No sections found with primary pattern, attempting normalization")
            normalized_text = self._aggressive_normalize_section_breaks(cleaned_text)
            section_matches = list(section_pattern.finditer(normalized_text))
            self.logger.info(f"After normalization, found {len(section_matches)} potential bill sections")

        # Process each section
        for match in section_matches:
            label = match.group('label').strip()
            number = match.group('number')
            body_text = match.group('body').strip()

            # Skip if the section body is empty
            if not body_text:
                self.logger.warning(f"Empty body found for section {number}, skipping")
                continue

            self.logger.info(f"Processing section {number} with label '{label}'")

            # Extract code references and determine action type
            code_refs = self._extract_code_references(body_text)
            action_type = self._determine_action(body_text)

            # Create the section object
            bs = BillSection(
                number=number,
                original_label=label,
                text=body_text,
                code_references=code_refs
            )

            if action_type != CodeAction.UNKNOWN:
                bs.section_type = action_type

            sections.append(bs)

            # Log code references found
            if code_refs:
                ref_strings = [f"{ref.code_name}:{ref.section}" for ref in code_refs]
                self.logger.info(f"Found {len(code_refs)} code references in section {number}: {ref_strings}")
            else:
                self.logger.warning(f"No code references found in section {number}")

        # Log the overall results
        self.logger.info(f"Successfully parsed {len(sections)} bill sections: {[s.original_label for s in sections]}")

        return sections

    def _parse_bill_sections_debug(self, bill_portion: str) -> List[BillSection]:
        """Debug-focused section parser to identify where the process is failing."""
        self.logger.info(f"Starting section parsing with text length: {len(bill_portion)}")

        sections = []

        # First, check for all section headers with a simple pattern
        all_headers = re.findall(r'(?:^|\n)\s*(SEC\.\s+(\d+)\.)', bill_portion, re.IGNORECASE)
        self.logger.info(f"FOUND HEADERS: {[h[1] for h in all_headers]}")

        # Process each section header one by one with extensive logging
        for i, (header, section_num) in enumerate(all_headers):
            self.logger.info(f"------ PROCESSING SECTION {section_num} (header {i+1} of {len(all_headers)}) ------")

            try:
                # Find the start position of this section
                start_idx = bill_portion.find(header)
                if start_idx == -1:
                    self.logger.error(f"ERROR: Couldn't find header '{header}' in bill text")
                    continue

                start_pos = start_idx + len(header)

                # Find the end of this section (start of next section or end of text)
                if i < len(all_headers) - 1:
                    next_header = all_headers[i+1][0]
                    end_pos = bill_portion.find(next_header, start_pos)
                    if end_pos == -1:
                        self.logger.error(f"ERROR: Couldn't find next header '{next_header}' after section {section_num}")
                        end_pos = len(bill_portion)
                else:
                    end_pos = len(bill_portion)

                # Extract the section text
                section_text = bill_portion[start_pos:end_pos].strip()
                self.logger.info(f"Section {section_num}: Extracted {len(section_text)} characters")
                self.logger.info(f"SECTION TEXT STARTS WITH: {section_text[:100]}...")

                # Check if there's anything strange in the text that might cause issues
                if '\0' in section_text:
                    self.logger.warning(f"WARNING: Section {section_num} contains null bytes")

                # Extract code references with explicit error handling
                try:
                    self.logger.info(f"Extracting code references for section {section_num}")
                    code_refs = self._extract_code_references(section_text)
                    self.logger.info(f"Found {len(code_refs)} code references: {code_refs}")
                except Exception as e:
                    self.logger.error(f"EXCEPTION in code reference extraction: {str(e)}")
                    self.logger.error(f"Stack trace: {traceback.format_exc()}")
                    code_refs = []

                # Create and add the section object
                try:
                    bs = BillSection(
                        number=section_num,
                        original_label=header.strip(),
                        text=section_text,
                        code_references=code_refs
                    )
                    sections.append(bs)
                    self.logger.info(f"Successfully added section {section_num}")
                except Exception as e:
                    self.logger.error(f"EXCEPTION creating BillSection: {str(e)}")
                    self.logger.error(f"Stack trace: {traceback.format_exc()}")

            except Exception as e:
                self.logger.error(f"GENERAL EXCEPTION processing section {section_num}: {str(e)}")
                self.logger.error(f"Stack trace: {traceback.format_exc()}")

        self.logger.info(f"PARSING COMPLETED: Found {len(sections)} sections: {[s.number for s in sections]}")
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

        # Second, standardize spacing around section labels
        text = re.sub(
            r'(SEC(?:TION)?\.)\s*(\d+)\.',
            r'\1 \2.',
            text,
            flags=re.IGNORECASE
        )

        # Third, ensure there's an extra newline between sections for clarity
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
        """
        references = []

        # Log the first 100 chars of the text we're searching for references
        self.logger.debug(f"Searching for code references in: {text[:100]}...")

        # Improved patterns for code reference detection
        # First pattern: "Section X of the Y Code"
        pattern1 = r'(?i)Section\s+(\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'

        # Second pattern: "Y Code Section X"
        pattern2 = r'(?i)([A-Za-z\s]+Code)\s+Section\s+(\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*)'

        # Third pattern: amended/added/repealed pattern that appears in section headers
        pattern3 = r'(?i)([A-Za-z\s]+Code)\s+(?:is|are)\s+(?:amended|added|repealed)'

        # Fourth pattern: Section reference in the first line (section declaration)
        first_line_pattern = r'(?i)Section\s+(\d+(?:\.\d+)?)\s+of\s+the\s+([A-Za-z\s]+Code)\s+(?:is|are)'

        # Use a set to track unique references
        unique_refs = set()

        # Check first line pattern as a high priority - usually defines what the section is about
        first_line = text.split('\n')[0] if '\n' in text else text
        first_match = re.search(first_line_pattern, first_line)
        if first_match:
            section_num = first_match.group(1).strip()
            code_name = first_match.group(2).strip()
            self.logger.info(f"Found primary code reference in section header: {code_name} Section {section_num}")
            unique_refs.add((code_name, section_num))

        # Check all other patterns
        for pattern in [pattern1, pattern2]:
            for match in re.finditer(pattern, text):
                if len(match.groups()) == 2:
                    # Extract the sections and code
                    if "code" in match.group(2).lower():  # "Section X of Y Code" format
                        sections_str = match.group(1)
                        code_name = match.group(2).strip()
                    else:  # "Y Code Section X" format
                        code_name = match.group(1).strip()
                        sections_str = match.group(2)

                    # Process comma-separated section numbers
                    for section in re.split(r'\s*,\s*', sections_str):
                        if section.strip():
                            unique_refs.add((code_name, section.strip()))

        # Create CodeReference objects from the unique references
        for code_name, section_num in unique_refs:
            references.append(CodeReference(section=section_num, code_name=code_name))

        self.logger.info(f"Found {len(references)} code references")
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
        """
        matches_found = 0
        for dsec in bill.digest_sections:
            digest_refs = {f"{ref.code_name}:{ref.section}" for ref in dsec.code_references}
            self.logger.info(f"Digest section {dsec.number} has refs: {digest_refs}")

            for bsec in bill.bill_sections:
                bill_refs = {f"{ref.code_name}:{ref.section}" for ref in bsec.code_references}
                self.logger.info(f"Bill section {bsec.number} has refs: {bill_refs}")

                overlap = digest_refs & bill_refs
                if overlap:
                    dsec.bill_sections.append(bsec.number)
                    bsec.digest_reference = dsec.number
                    matches_found += 1
                    self.logger.info(f"Matched digest {dsec.number} to bill section {bsec.number} via refs: {overlap}")

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
        # Insert line breaks before "SEC." or "SECTION" if not already present.
        text = re.sub(
            r'(?<!\n)(SEC(?:TION)?\.?\s+\d+)',
            r'\n\1',
            text,
            flags=re.IGNORECASE
        )
        return text