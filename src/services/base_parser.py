from typing import List, Tuple, Optional, Dict, Any
import logging
import re
from datetime import datetime
from src.models.bill_components import (
    TrailerBill,
    DigestSection,
    BillSection,
    CodeReference,
    CodeAction,
    SectionType
)

class BaseParser:
    """
    Handles initial regex-based parsing of trailer bills to extract basic structure,
    digest sections, and bill sections.
    """

    def __init__(self):
        """Initialize the parser with regex patterns and logger."""
        self.logger = logging.getLogger(__name__)

        # Bill header pattern (e.g., "Assembly Bill 173 CHAPTER 53")
        self.bill_header_pattern = (
            r'(Assembly|Senate)\s+Bill\s+(?:No\.?\s+)?(\d+)\s+CHAPTER\s*(\d+)\s*'
        )

        # Digest section pattern (e.g., "(1) Some text (2) More text")
        self.digest_section_pattern = r'\((\d+)\)\s+([^(]+)(?=\(\d+\)|$)'

        # Bill section pattern (SEC. 1. or SECTION 1.)
        self.bill_section_pattern = (
            r'^(?:SEC(?:TION)?\.?)\s+(\d+(?:\.\d+)?)(?:\.|:)?\s+(.*?)'
            r'(?=^(?:SEC(?:TION)?\.?)\s+\d+|\Z)'
        )

        # Approval/filing dates pattern
        self.date_pattern = (
            r'Approved by Governor\s+([^.]+)\.\s+'
            r'Filed with Secretary of State\s+([^.]+)\.'
        )

    def parse_bill(self, bill_text: str) -> TrailerBill:
        """Parse the full text of a trailer bill into structured components."""
        try:
            # Normalize section markers to start on new lines
            cleaned_text = self._normalize_section_breaks(bill_text)

            # Parse bill header information
            header_info = self._parse_bill_header(cleaned_text)

            # Create initial TrailerBill object
            bill = TrailerBill(
                bill_number=header_info['bill_number'],
                title=header_info['title'],
                chapter_number=header_info['chapter_number'],
                date_approved=header_info['date_approved'],
                date_filed=header_info['date_filed'],
                raw_text=cleaned_text
            )

            # Split and parse digest and bill portions
            digest_text, bill_portion = self._split_digest_and_bill(cleaned_text)
            bill.digest_sections = self._parse_digest_sections(digest_text)
            bill.bill_sections = self._parse_bill_sections(bill_portion)

            # Match digest sections to bill sections based on code references
            self._match_sections(bill)

            return bill

        except Exception as e:
            self.logger.error(f"Error parsing bill: {str(e)}")
            raise

    def _parse_bill_header(self, text: str) -> dict:
        """Parse the header section of the bill for basic metadata."""
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
        """Split the bill text into digest portion and main bill portion."""
        lower_text = text.lower()
        digest_start = lower_text.find("legislative counsel's digest")

        if digest_start == -1:
            self.logger.info("No 'Legislative Counsel's Digest' found.")
            return "", text

        # Look for end of digest marker
        digest_end = lower_text.find(
            "the people of the state of california do enact as follows:"
        )
        if digest_end == -1:
            # Try alternate pattern
            fallback_pattern = r"the people of the state of california do enact"
            m = re.search(fallback_pattern, lower_text, re.IGNORECASE)
            digest_end = m.start() if m else len(text)

        digest_text = text[digest_start:digest_end].strip()
        bill_portion = text[digest_end:].strip()
        return digest_text, bill_portion

    def _parse_digest_sections(self, digest_text: str) -> List[DigestSection]:
        """Parse numbered sections from the Legislative Counsel's Digest."""
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
        """Parse the main portion of the bill into numbered sections."""
        sections = []
        pattern = re.compile(
            self.bill_section_pattern,
            flags=re.IGNORECASE | re.DOTALL | re.MULTILINE
        )
        matches = list(pattern.finditer(bill_portion))

        if matches:
            for match in matches:
                section_num = match.group(1).strip()
                section_body = match.group(2).strip()
                code_refs, action = self._parse_section_header(section_body)

                section = BillSection(
                    number=section_num,
                    text=section_body,
                    code_references=code_refs
                )
                sections.append(section)
        else:
            # Fallback parsing if no explicit sections found
            self.logger.info("No explicit sections found, using fallback parsing")
            fallback_refs = self._extract_code_references(bill_portion)

            if fallback_refs:
                # Create sections based on code references
                for i, ref in enumerate(fallback_refs, start=1):
                    sections.append(
                        BillSection(
                            number=str(i),
                            text=f"Reference to {ref.code_name} section {ref.section}.",
                            code_references=[ref]
                        )
                    )
            elif bill_portion.strip():
                # Create single section for remaining text
                sections.append(
                    BillSection(
                        number="1",
                        text=bill_portion.strip(),
                        code_references=[]
                    )
                )

        return sections

    def _parse_section_header(self, text: str) -> Tuple[List[CodeReference], Optional[CodeAction]]:
        """Parse the header line of a bill section for code references and action type."""
        first_line = text.split('\n', 1)[0]
        action = self._determine_action(first_line)
        refs = self._extract_code_references(first_line)
        return refs, action

    def _determine_action(self, text: str) -> CodeAction:
        """Determine the action type (add/amend/repeal) from section text."""
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

    def _extract_code_references(self, text: str) -> List[CodeReference]:
        """Extract references to California Code sections from text."""
        references = []
        pattern = (
            r'Sections?\s+([0-9\.\,\-\s&and]+)\s+'
            r'(?:of\s+(?:the\s+)?)?([A-Za-z\s]+Code)'
        )
        matches = re.finditer(pattern, text, re.IGNORECASE)

        for match in matches:
            sections_list = self._tokenize_section_numbers(match.group(1))
            code_name = match.group(2).strip()

            for section_num in sections_list:
                ref = CodeReference(section=section_num, code_name=code_name)
                references.append(ref)

        return references

    def _tokenize_section_numbers(self, text: str) -> List[str]:
        """Split a string of section numbers into individual numbers."""
        text = re.sub(r'\s*and\s*', ',', text, flags=re.IGNORECASE)
        parts = re.split(r'[,\s]+', text)
        return [p.strip() for p in parts if p.strip() and re.match(r'^[\d\.]+$', p.strip())]

    def _split_existing_and_changes(self, text: str) -> Tuple[str, str]:
        """Split digest section text into existing law and proposed changes portions."""
        if "Existing law" in text and "This bill would" in text:
            parts = text.split("This bill would", 1)
            existing = parts[0].replace("Existing law", "", 1).strip()
            changes = "This bill would" + parts[1].strip()
            return existing, changes
        return "", text

    def _match_sections(self, bill: TrailerBill) -> None:
        """Link digest sections to bill sections based on shared code references."""
        for digest_section in bill.digest_sections:
            digest_refs = {
                f"{ref.code_name}:{ref.section}"
                for ref in digest_section.code_references
            }

            for bill_section in bill.bill_sections:
                bill_refs = {
                    f"{ref.code_name}:{ref.section}"
                    for ref in bill_section.code_references
                }

                # If there's overlap in references, link them
                if digest_refs & bill_refs:
                    digest_section.bill_sections.append(bill_section.number)
                    bill_section.digest_reference = digest_section.number

    def _extract_title(self, text: str) -> str:
        """Extract the bill title from the text."""
        title_pattern = r'An act to .*?(?=\[|LEGISLATIVE COUNSEL|$)'
        match = re.search(title_pattern, text, re.DOTALL | re.IGNORECASE)
        return match.group().strip() if match else ""

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse a date string into a datetime object."""
        try:
            return datetime.strptime(date_str.strip(), '%B %d, %Y')
        except Exception as e:
            self.logger.error(f"Error parsing date '{date_str}': {str(e)}")
            return None

    def _normalize_section_breaks(self, text: str) -> str:
        """Ensure section markers start on new lines for consistent parsing."""
        return re.sub(
            r'([.:;])(?!\n)\s*(?=(SEC(?:TION)?\.))',
            r'\1\n',
            text,
            flags=re.IGNORECASE
        )