from typing import List, Tuple, Optional
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
    digest sections, and bill sections. This parser uses traditional parsing techniques
    (no AI) to create the foundational structure for further analysis.
    """

    # List of recognized California Codes for reference matching
    CA_CODES = [
        "Business and Professions",
        "Civil",
        "Code of Civil Procedure",
        "Commercial",
        "Corporations",
        "Education",
        "Elections",
        "Evidence",
        "Family",
        "Financial",
        "Fish and Game",
        "Food and Agricultural",
        "Government",
        "Harbors and Navigation",
        "Health and Safety",
        "Insurance",
        "Labor",
        "Military and Veterans",
        "Penal",
        "Probate",
        "Public Contract",
        "Public Resources",
        "Public Utilities",
        "Revenue and Taxation",
        "Streets and Highways",
        "Unemployment Insurance",
        "Vehicle",
        "Water",
        "Welfare and Institutions"
    ]

    def __init__(self):
        """Initialize the parser with regex patterns for identifying bill components."""
        self.logger = logging.getLogger(__name__)

        # Pattern for bill header (e.g., "Assembly Bill 173 CHAPTER 53")
        self.bill_header_pattern = (
            r'(Assembly|Senate)\s+Bill\s+(?:No\.?\s+)?(\d+)\s+CHAPTER\s*(\d+)\s*'
        )

        # Pattern for numbered digest sections (e.g., "(1) Some text (2) More text")
        self.digest_section_pattern = r'\((\d+)\)\s+([^(]+)(?=\(\d+\)|$)'

        # Pattern for bill sections (SEC. 1. or SECTION 1.)
        self.bill_section_pattern = (
            r'^(?:SEC(?:TION)?\.?)\s+(\d+(?:\.\d+)?)(?:\.|:)?\s+(.*?)'
            r'(?=^(?:SEC(?:TION)?\.?)\s+\d+|\Z)'
        )

        # Pattern for approval/filing dates
        self.date_pattern = (
            r'Approved by Governor\s+([^.]+)\.\s+'
            r'Filed with Secretary of State\s+([^.]+)\.'
        )

    def parse_bill(self, bill_text: str) -> TrailerBill:
        """
        Parse the full text of a trailer bill into structured components.

        Args:
            bill_text (str): Raw text of the trailer bill

        Returns:
            TrailerBill: Structured representation of the bill
        """
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

    def _parse_bill_header(self, text: str) -> dict:
        """
        Parse the header section of the bill for basic metadata.

        Args:
            text (str): Full bill text

        Returns:
            dict: Header information including bill number, chapter, title, and dates
        """
        header_match = re.search(self.bill_header_pattern, text, re.MULTILINE | re.IGNORECASE)
        if not header_match:
            self.logger.warning("Could not parse bill header with standard pattern.")
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
        """
        Split the bill text into digest portion and main bill portion.

        Args:
            text (str): Full bill text

        Returns:
            Tuple[str, str]: (digest_text, bill_portion)
        """
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
        """
        Parse numbered sections from the Legislative Counsel's Digest.

        Args:
            digest_text (str): Text of the digest portion

        Returns:
            List[DigestSection]: List of parsed digest sections
        """
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

    def _split_existing_and_changes(self, text: str) -> Tuple[str, str]:
        """
        Split digest section text into "existing law" and "proposed changes" portions.

        Args:
            text (str): Full text of a digest section

        Returns:
            Tuple[str, str]: (existing_law, proposed_changes)
        """
        if "Existing law" in text and "This bill would" in text:
            parts = text.split("This bill would", 1)
            existing = parts[0].replace("Existing law", "", 1).strip()
            changes = "This bill would" + parts[1].strip()
            return existing, changes
        return "", text

    def _parse_bill_sections(self, bill_portion: str) -> List[BillSection]:
        """
        Parse the main portion of the bill into numbered sections.

        Args:
            bill_portion (str): Text of the main bill portion

        Returns:
            List[BillSection]: List of parsed bill sections
        """
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
                    code_references=code_refs,
                    section_type=SectionType.UNKNOWN
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
        """
        Parse the header line of a bill section for code references and action type.

        Args:
            text (str): Full text of a bill section

        Returns:
            Tuple[List[CodeReference], Optional[CodeAction]]: (references, action)
        """
        first_line = text.split('\n', 1)[0]
        action = self._determine_action(first_line)
        refs = self._extract_code_references(first_line)
        return refs, action

    def _determine_action(self, text: str) -> CodeAction:
        """
        Determine the action type (add/amend/repeal) from section text.

        Args:
            text (str): Text to analyze (typically first line of section)

        Returns:
            CodeAction: The determined action type
        """
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
        """
        Extract references to California Code sections from text.
        Handles various formats and patterns of code references.

        Args:
            text (str): Text to analyze for code references

        Returns:
            List[CodeReference]: List of found code references
        """
        references = []

        # Multiple patterns to catch different reference formats
        patterns = [
            # Standard format: "Section 123 of the Education Code"
            (
                r'Sections?\s+([0-9\.\,\-\s&and]+)\s+'
                r'(?:of\s+(?:the\s+)?)?([A-Za-z\s]+Code)'
            ),
            # Reverse format: "Education Code Section 123"
            (
                r'([A-Za-z\s]+Code)\s+Sections?\s+'
                r'([0-9\.\,\-\s&and]+)'
            ),
            # Range format: "Sections 123 through 128 of the Education Code"
            (
                r'Sections?\s+(\d+)(?:\s+through\s+|\s*\-\s*)(\d+)'
                r'\s+(?:of\s+(?:the\s+)?)?([A-Za-z\s]+Code)'
            )
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)

            for match in matches:
                if len(match.groups()) == 2:
                    # Standard or reverse format
                    if any(code in match.group(2) for code in self.CA_CODES):
                        # Standard format
                        sections_list = self._tokenize_section_numbers(match.group(1))
                        code_name = match.group(2).strip()
                    else:
                        # Reverse format
                        sections_list = self._tokenize_section_numbers(match.group(2))
                        code_name = match.group(1).strip()
                else:
                    # Range format
                    start_num = int(match.group(1))
                    end_num = int(match.group(2))
                    sections_list = [str(num) for num in range(start_num, end_num + 1)]
                    code_name = match.group(3).strip()

                # Validate code name against known CA_CODES
                code_name = self._normalize_code_name(code_name)
                if code_name:
                    for section_num in sections_list:
                        ref = CodeReference(section=section_num, code_name=code_name)
                        if ref not in references:  # Avoid duplicates
                            references.append(ref)

        return references

    def _normalize_code_name(self, code_name: str) -> Optional[str]:
        """
        Normalize a code name against known California Codes.

        Args:
            code_name (str): Raw code name from text

        Returns:
            Optional[str]: Normalized code name or None if invalid
        """
        code_name = code_name.strip()

        # Direct match
        if code_name in self.CA_CODES:
            return code_name

        # Try matching without "Code" suffix
        base_name = code_name.replace(" Code", "").strip()
        for known_code in self.CA_CODES:
            if known_code.startswith(base_name):
                return known_code

        # Log warning if we can't normalize the code name
        self.logger.warning(f"Unknown code name encountered: {code_name}")
        return None

    def _tokenize_section_numbers(self, text: str) -> List[str]:
        """
        Split a string of section numbers into individual numbers.

        Args:
            text (str): String containing section numbers (e.g., "123, 124 and 125")

        Returns:
            List[str]: List of individual section numbers
        """
        text = re.sub(r'\s*and\s*', ',', text, flags=re.IGNORECASE)
        parts = re.split(r'[,\s]+', text)
        return [p.strip() for p in parts if p.strip() and re.match(r'^[\d\.]+$', p.strip())]

    def _match_sections(self, bill: TrailerBill) -> None:
        """
        Link digest sections to bill sections based on shared code references
        and contextual analysis.
        """
        try:
            # First try matching by code references
            matches_found = self._match_by_code_references(bill)

            # If no matches found by code references, try context matching
            if not matches_found:
                self._match_by_context(bill)

            # Log matching results
            self._log_matching_results(bill)

        except Exception as e:
            self.logger.error(f"Error in section matching: {str(e)}")
            self.logger.exception(e)

    def _match_by_code_references(self, bill: TrailerBill) -> bool:
        """Match sections based on shared code references."""
        matches_found = False

        for digest_section in bill.digest_sections:
            digest_refs = set(
                f"{ref.code_name}:{ref.section}"
                for ref in digest_section.code_references
            )

            for bill_section in bill.bill_sections:
                bill_refs = set(
                    f"{ref.code_name}:{ref.section}"
                    for ref in bill_section.code_references
                )

                # Check for any overlap in references
                if digest_refs & bill_refs:
                    digest_section.bill_sections.append(bill_section.number)
                    bill_section.digest_reference = digest_section.number
                    matches_found = True
                    self.logger.debug(
                        f"Matched digest section {digest_section.number} "
                        f"to bill section {bill_section.number}"
                    )

        return matches_found

    def _match_by_context(self, bill: TrailerBill) -> None:
        """Match sections based on textual similarity when code references fail."""
        from difflib import SequenceMatcher

        def similarity(a: str, b: str) -> float:
            return SequenceMatcher(None, a.lower(), b.lower()).ratio()

        for bill_section in bill.bill_sections:
            if not bill_section.digest_reference:
                best_match = None
                best_score = 0

                for digest_section in bill.digest_sections:
                    if not digest_section.bill_sections:  # Only consider unmatched digest sections
                        score = similarity(bill_section.text, digest_section.text)
                        if score > best_score and score > 0.3:  # Threshold for matching
                            best_score = score
                            best_match = digest_section

                if best_match:
                    best_match.bill_sections.append(bill_section.number)
                    bill_section.digest_reference = best_match.number
                    self.logger.debug(
                        f"Context-matched bill section {bill_section.number} "
                        f"to digest section {best_match.number} "
                        f"with score {best_score}"
                    )
                    
    def _log_matching_results(self, bill: TrailerBill) -> None:
        """Log the results of section matching."""
        unmatched_bill_sections = []
        unmatched_digest_sections = []

        for section in bill.bill_sections:
            if not section.digest_reference:
                unmatched_bill_sections.append(section.number)

        for section in bill.digest_sections:
            if not section.bill_sections:
                unmatched_digest_sections.append(section.number)

        if unmatched_bill_sections:
            self.logger.warning(
                f"Unmatched bill sections: {', '.join(unmatched_bill_sections)}"
            )

        if unmatched_digest_sections:
            self.logger.warning(
                f"Unmatched digest sections: {', '.join(unmatched_digest_sections)}"
            )

        self.logger.info(
            f"Matching complete: {len(bill.bill_sections) - len(unmatched_bill_sections)} "
            f"of {len(bill.bill_sections)} bill sections matched"
        )
        
    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate a similarity score between two text segments.
        This is a basic implementation that could be enhanced.

        Args:
            text1 (str): First text segment
            text2 (str): Second text segment

        Returns:
            float: Similarity score between 0 and 1
        """
        # Convert texts to sets of words
        words1 = set(text1.split())
        words2 = set(text2.split())

        # Calculate Jaccard similarity
        intersection = words1 & words2
        union = words1 | words2

        if not union:
            return 0.0

        return len(intersection) / len(union)

    def _validate_matches(self, bill: TrailerBill) -> None:
        """
        Validate the section matches and log any issues.

        Args:
            bill (TrailerBill): Bill object to validate
        """
        # Check for unmatched sections
        unmatched_bill_sections = [
            section.number
            for section in bill.bill_sections
            if not section.digest_reference
        ]

        unmatched_digest_sections = [
            section.number
            for section in bill.digest_sections
            if not section.bill_sections
        ]

        # Log any issues found
        if unmatched_bill_sections:
            self.logger.warning(
                f"Unmatched bill sections: {', '.join(unmatched_bill_sections)}"
            )

        if unmatched_digest_sections:
            self.logger.warning(
                f"Unmatched digest sections: {', '.join(unmatched_digest_sections)}"
            )

    def _extract_title(self, text: str) -> str:
        """
        Extract the bill title from the text.

        Args:
            text (str): Full bill text

        Returns:
            str: Extracted title or empty string
        """
        title_pattern = r'An act to .*?(?=\[|LEGISLATIVE COUNSEL|$)'
        match = re.search(title_pattern, text, re.DOTALL | re.IGNORECASE)
        return match.group().strip() if match else ""

    def _parse_date(self, date_str: str) -> datetime:
        """
        Parse a date string into a datetime object.

        Args:
            date_str (str): Date string (e.g., "June 26, 2023")

        Returns:
            datetime: Parsed datetime object
        """
        return datetime.strptime(date_str.strip(), '%B %d, %Y')

    def _normalize_section_breaks(self, text: str) -> str:
        """
        Ensure section markers start on new lines for consistent parsing.

        Args:
            text (str): Text to normalize

        Returns:
            str: Normalized text
        """
        return re.sub(
            r'([.:;])(?!\n)\s*(?=(SEC(?:TION)?\.))',
            r'\1\n',
            text,
            flags=re.IGNORECASE
        )