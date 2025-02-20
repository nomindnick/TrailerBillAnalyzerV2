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
        # Updated pattern to better capture "SECTION X." lines:
        self.bill_section_pattern = (
            r'(?:^|\n)(SEC(?:TION)?\.?)\s+(\d+)(?:\.)?\s+(.*?)'
            r'(?=\nSEC(?:TION)?\.?\s+\d+|\Z)'
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
        pattern = re.compile(self.bill_section_pattern, flags=re.IGNORECASE | re.DOTALL)
        matches = list(pattern.finditer(bill_portion))

        if matches:
            for match in matches:
                # e.g. match for "SECTION 1. ..." or "SEC. 12 ..."
                section_label = match.group(1)  # "SEC." or "SECTION"
                section_num = match.group(2).strip()  # "1", "2", etc.
                section_body = match.group(3).strip()

                code_refs, action = self._parse_section_header(section_body)
                bs = BillSection(
                    number=section_num,
                    text=section_body,
                    code_references=code_refs
                )
                sections.append(bs)
        else:
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
        patterns = [
            r"(?i)Sections?\s+([\d\.\-\,\s&and]+)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)",
            r"(?i)([A-Za-z\s]+Code)\s+Sections?\s+([\d\.\-\,\s&and]+)",
            r"(?i)Sections?\s+(\d+(?:\.\d+)?)(?:\s*(?:to|through|-)\s*(\d+(?:\.\d+)?))?\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)",
        ]
        # Format for single section references:
        single_section_pattern = r"(?i)Section\s+(\d+(?:\.\d+)?)(?:\s+of\s+(?:the\s+)?([A-Za-z\s]+Code))?"
        single_rev_pattern = r"(?i)([A-Za-z\s]+Code)\s+Section\s+(\d+(?:\.\d+)?)"

        all_matches = []

        for pat in patterns:
            for match in re.finditer(pat, text):
                all_matches.append(match)
        for match in re.finditer(single_section_pattern, text):
            all_matches.append(match)
        for match in re.finditer(single_rev_pattern, text):
            all_matches.append(match)

        unique_refs = set()

        for match in all_matches:
            groups = match.groups()
            if len(groups) == 2:
                if groups[1] is not None and "code" in groups[1].lower():
                    sections_str = groups[0]
                    code_name = groups[1].strip()
                    for sec in self._split_section_list(sections_str):
                        unique_refs.add((code_name, sec))
                elif groups[0] is not None and "code" in groups[0].lower():
                    code_name = groups[0].strip()
                    sections_str = groups[1] if groups[1] is not None else ""
                    for sec in self._split_section_list(sections_str):
                        unique_refs.add((code_name, sec))
            elif len(groups) == 3:
                # e.g. (start, maybe_end, code_name)
                start = groups[0]
                maybe_end = groups[1]
                code_name = groups[2]
                code_name = code_name.strip() if code_name is not None else ""
                if maybe_end:
                    try:
                        start_val = int(float(start))
                        end_val = int(float(maybe_end))
                        for i in range(start_val, end_val + 1):
                            unique_refs.add((code_name, str(i)))
                    except ValueError:
                        for sec in self._split_section_list(start):
                            unique_refs.add((code_name, sec))
                else:
                    for sec in self._split_section_list(start):
                        unique_refs.add((code_name, sec))
            else:
                # handle single section patterns, etc.
                pass

        code_refs = []
        for (code, sec) in unique_refs:
            code = code.strip() if code is not None else ""
            sec = sec.strip() if sec is not None else ""
            if code and sec:
                code_ref = CodeReference(section=sec, code_name=code)
                code_refs.append(code_ref)

        return code_refs

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
        Attempt to separate 'Existing law' and 'This bill would' from text
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
        # Insert line breaks before "SEC." or "SECTION" if not already present.
        text = re.sub(
            r'(?<!\n)(SEC(?:TION)?\.?\s+\d+)',
            r'\n\1',
            text,
            flags=re.IGNORECASE
        )
        return text
