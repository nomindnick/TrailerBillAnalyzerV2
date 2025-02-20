from typing import List, Tuple, Optional
import logging
import re
from datetime import datetime
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
        self.bill_section_pattern = (
            r'^(?:SEC(?:TION)?\.?)\s+(\d+(?:\.\d+)?)(?:\.|:)?\s+(.*?)'
            r'(?=^(?:SEC(?:TION)?\.?)\s+\d+|\Z)'
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
        sections = []
        pattern = re.compile(self.bill_section_pattern, flags=re.IGNORECASE | re.DOTALL | re.MULTILINE)
        matches = list(pattern.finditer(bill_portion))

        if matches:
            for match in matches:
                section_num = match.group(1).strip()
                section_body = match.group(2).strip()
                code_refs, action = self._parse_section_header(section_body)

                bs = BillSection(
                    number=section_num,
                    text=section_body,
                    code_references=code_refs
                )
                sections.append(bs)
        else:
            # Fallback if no explicit sections found
            fallback_refs = self._extract_code_references(bill_portion)
            if fallback_refs:
                for i, ref in enumerate(fallback_refs, start=1):
                    bs = BillSection(
                        number=str(i),
                        text=f"Reference to {ref.code_name} section {ref.section}.",
                        code_references=[ref]
                    )
                    sections.append(bs)
            else:
                leftover = bill_portion.strip()
                if leftover:
                    bs = BillSection(
                        number="1",
                        text=leftover,
                        code_references=[]
                    )
                    sections.append(bs)

        return sections

    def _extract_code_references(self, text: str) -> List[CodeReference]:
        """
        Extract references in the form of:
         - "Section 8594.14 of the Government Code"
         - "Sections 187010, 187022 of the Public Utilities Code"
         - "Public Utilities Code Section 187030"
         - Ranges: "Sections 103 to 105 of the Government Code"
        """
        references = []
        # Combine multiple patterns to capture different ordering:
        patterns = [
            # Format: "Sections 8594.14 and 13987 of the Government Code"
            r"(?i)Sections?\s+([\d\.\-\,\s&and]+)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)",
            # Format: "Government Code Sections 8594.14 and 13987"
            r"(?i)([A-Za-z\s]+Code)\s+Sections?\s+([\d\.\-\,\s&and]+)",
            # Ranges: "Sections 100 to 102 of the Government Code"
            r"(?i)Sections?\s+(\d+(?:\.\d+)?)(?:\s*(?:to|through|-)\s*(\d+(?:\.\d+)?))?\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)",
        ]

        # To handle single line references like: "Section 8594.14 of the Government Code" distinctly:
        single_section_pattern = r"(?i)Section\s+(\d+(?:\.\d+)?)(?:\s+of\s+(?:the\s+)?([A-Za-z\s]+Code))?"
        single_rev_pattern = r"(?i)([A-Za-z\s]+Code)\s+Section\s+(\d+(?:\.\d+)?)"

        # We'll parse using each pattern:
        # Because we may have overlap in patterns, we'll do a best effort approach
        all_matches = []

        # Multi reference patterns
        for pat in patterns:
            for match in re.finditer(pat, text):
                all_matches.append(match)

        # Single reference patterns
        for match in re.finditer(single_section_pattern, text):
            all_matches.append(match)
        for match in re.finditer(single_rev_pattern, text):
            all_matches.append(match)

        # We'll store them in a set of (code_name, section_num) to avoid duplication
        unique_refs = set()

        for match in all_matches:
            groups = match.groups()
            # We must interpret them carefully because pattern structures differ
            # We'll unify logic in a single approach:
            # If pattern is "Sections 8594.14, 13987 of Government Code"
            # groups might be ( '8594.14, 13987', 'Government Code' )
            # We'll split the sections
            # If pattern is a range: ( '100', '102', 'Government Code' )
            # If single section: ( '8594.14', 'Government Code' )
            # Or reversed: ( 'Government Code', '8594.14, 13987' )

            # We'll try a safe approach:
            # We see how many groups we have:
            if len(groups) == 2:
                # Could be (sections_str, code_name) or (code_name, sections_str)
                # We try to guess which is code name vs. sections
                # We'll do a naive check for "Code" to identify code name
                if "code" in groups[1].lower():
                    # (sections_str, code_name)
                    sections_str = groups[0]
                    code_name = groups[1].strip()
                    for sec in self._split_section_list(sections_str):
                        unique_refs.add((code_name, sec))
                elif "code" in groups[0].lower():
                    # (code_name, sections_str)
                    code_name = groups[0].strip()
                    sections_str = groups[1]
                    for sec in self._split_section_list(sections_str):
                        unique_refs.add((code_name, sec))

            elif len(groups) == 3:
                # Could be (sections_str, None, code_name) for a single range, or
                # (start, end, code_name) for a range
                # We'll see if the second group is None
                start = groups[0]
                maybe_end = groups[1]
                code_name = groups[2]
                if maybe_end:
                    # It's a range
                    start_val = int(float(start))
                    end_val = int(float(maybe_end))
                    for i in range(start_val, end_val + 1):
                        unique_refs.add((code_name.strip(), str(i)))
                else:
                    # It's probably sections_str, code_name
                    # so we do the multi-split
                    for sec in self._split_section_list(start):
                        unique_refs.add((code_name.strip(), sec))
            else:
                # If there's an unexpected group count, we just skip
                pass

        code_refs = []
        for (code, sec) in unique_refs:
            # Remove extra whitespace
            code = code.strip()
            sec = sec.strip()
            if code and sec:
                code_ref = CodeReference(section=sec, code_name=code)
                code_refs.append(code_ref)

        return code_refs

    def _split_section_list(self, sections_str: str) -> List[str]:
        # Attempt to split on commas, 'and', etc.
        # e.g. "8594.14, 13987 and 13989"
        s = re.sub(r'\s+and\s+', ',', sections_str, flags=re.IGNORECASE)
        s = re.sub(r'\s+', '', s)  # remove extra spaces
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
        Attempt to separate 'Existing law' and 'This bill would' from text
        """
        existing_text = ""
        change_text = text

        # Very simplistic approach:
        # If we see "Existing law" and "This bill would", we split
        # or we just keep them as is
        if not text:
            return "", ""
            
        pattern = r"(Existing law.*?)(This bill would.*)"
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            existing_text = match.group(1).strip()
            change_text = match.group(2).strip()
            return existing_text, change_text
            
        return text, ""  # If no match, treat entire text as existing law

    def _match_sections(self, bill: TrailerBill) -> None:
        """
        Match up digest sections to bill sections that share code references
        """
        for dsec in bill.digest_sections:
            digest_refs = {f"{ref.code_name}:{ref.section}" for ref in dsec.code_references}
            for bsec in bill.bill_sections:
                bill_refs = {f"{ref.code_name}:{ref.section}" for ref in bsec.code_references}
                if digest_refs & bill_refs:
                    dsec.bill_sections.append(bsec.number)
                    bsec.digest_reference = dsec.number

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
        return re.sub(
            r'([.:;])(?!\n)\s*(?=(SEC(?:TION)?\.))',
            r'\1\n',
            text,
            flags=re.IGNORECASE
        )
