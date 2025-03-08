import re
import logging
from datetime import datetime
from typing import List, Tuple, Optional, Set, Dict, Any
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

        #
        # We'll compile the main pattern with IGNORECASE as a separate flag,
        # so we don't do inline (?i), to avoid "global flags not at the start" issues
        #
        self.bill_section_pattern = re.compile(
            r'(?:^|\n+)\s*'
            r'(?P<label>((?:SECTION|SEC)\.)\s+(?P<number>\d+)\.)'
            r'\s*(?P<body>.*?)(?=(?:\n+\s*(?:SECTION|SEC)\.\s+\d+\.)|$)',
            re.DOTALL | re.IGNORECASE
        )

        self.bill_header_pattern = r'(Assembly|Senate)\s+Bill\s+(?:No\.?\s+)?(\d+)\s+(?:CHAPTER\s+(\d+))'
        self.digest_section_pattern = r'\((\d+)\)\s+([^(]+)(?=\(\d+\)|$)'
        self.date_pattern = r'Approved by Governor\s+([^.]+)\.\s+Filed with Secretary of State\s+([^.]+)\.'

    def parse_bill(self, bill_text: str) -> TrailerBill:
        try:
            cleaned_text = self._clean_html_markup(bill_text)
            cleaned_text = self._aggressive_normalize_improved(cleaned_text)

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
            bill.bill_sections = self._parse_bill_sections_improved(bill_portion)

            self._match_sections(bill)

            self.logger.info(
                f"Successfully parsed bill with {len(bill.digest_sections)} digest sections "
                f"and {len(bill.bill_sections)} bill sections"
            )
            return bill

        except Exception as e:
            self.logger.error(f"Error parsing bill: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return TrailerBill(
                bill_number="Unknown",
                title="Parse Error",
                chapter_number="",
                raw_text=bill_text
            )

    def _split_existing_and_changes(self, text: str) -> Tuple[str, str]:
        separators = [
            "This bill would",
            "The bill would",
            "Instead, this bill",
            "This bill will"
        ]
        lower_text = text.lower()
        split_pos = -1
        for separator in separators:
            pos = text.find(separator)
            if pos != -1 and (split_pos == -1 or pos < split_pos):
                split_pos = pos

        if split_pos == -1:
            would_pos = lower_text.find("would")
            if would_pos != -1:
                sentence_start = would_pos
                while sentence_start > 0 and text[sentence_start-1] not in ".!?":
                    sentence_start -= 1
                if sentence_start > 0:
                    existing_law = text[:sentence_start].strip()
                    proposed_changes = text[sentence_start:].strip()
                else:
                    midpoint = len(text) // 2
                    existing_law = text[:midpoint].strip()
                    proposed_changes = text[midpoint:].strip()
            else:
                midpoint = len(text) // 2
                existing_law = text[:midpoint].strip()
                proposed_changes = text[midpoint:].strip()
        else:
            existing_law = text[:split_pos].strip()
            proposed_changes = text[split_pos:].strip()

        return existing_law, proposed_changes

    def _clean_html_markup(self, text: str) -> str:
        return self._clean_html_markup_enhanced(text)

    def _clean_html_markup_enhanced(self, text: str) -> str:
        text = re.sub(r'<font color="#B30000"><strike>.*?</strike></font>', '', text, flags=re.DOTALL)
        text = re.sub(r'<strike>.*?</strike>', '', text, flags=re.DOTALL)
        text = re.sub(r'<del>.*?</del>', '', text, flags=re.DOTALL)
        text = re.sub(r'<s>.*?</s>', '', text, flags=re.DOTALL)
        text = re.sub(r'<font color="(?:#B30000|#FF0000|red)">(.*?)</font>', '', text, flags=re.DOTALL)
        text = re.sub(r'<font color="blue" class="blue_text"><i>(.*?)</i></font>', r'\1', text, flags=re.DOTALL)
        text = re.sub(r'<font color="blue">(.*?)</font>', r'\1', text, flags=re.DOTALL)
        text = re.sub(r'<span class="new_text">(.*?)</span>', r'\1', text, flags=re.DOTALL)
        text = re.sub(r'<ins>(.*?)</ins>', r'\1', text, flags=re.DOTALL)
        text = re.sub(r'<i>(.*?)</i>', r'\1', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]*>', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def _parse_bill_header(self, text: str) -> Dict[str, Any]:
        header_match = re.search(self.bill_header_pattern, text, re.MULTILINE | re.IGNORECASE | re.DOTALL)
        if not header_match:
            self.logger.warning("Could not parse bill header with standard pattern")
            alt_patterns = [r'(Assembly|Senate)\s+Bill(?:\s+No\.?)?\s+(\d+)', r'CHAPTER\s+(\d+)']
            bill_type = None
            bill_num = None
            chapter = ""
            bill_match = re.search(alt_patterns[0], text, re.IGNORECASE)
            if bill_match:
                bill_type = bill_match.group(1)
                bill_num = bill_match.group(2)
            chapter_match = re.search(alt_patterns[1], text, re.IGNORECASE)
            if chapter_match:
                chapter = chapter_match.group(1)

            if bill_type and bill_num:
                header_info = {
                    'bill_number': f"{bill_type} Bill {bill_num}",
                    'chapter_number': chapter,
                    'title': self._extract_title(text),
                    'date_approved': None,
                    'date_filed': None
                }
                date_match = re.search(self.date_pattern, text)
                if date_match:
                    header_info['date_approved'] = self._parse_date(date_match.group(1)) if date_match else None
                    header_info['date_filed'] = self._parse_date(date_match.group(2)) if date_match else None
                return header_info

        if header_match:
            chapter = header_match.group(3) if header_match.lastindex >= 3 else ""
            date_match = re.search(self.date_pattern, text)
            return {
                'bill_number': f"{header_match.group(1)} Bill {header_match.group(2)}",
                'chapter_number': chapter if chapter else "",
                'title': self._extract_title(text),
                'date_approved': self._parse_date(date_match.group(1)) if date_match else None,
                'date_filed': self._parse_date(date_match.group(2)) if date_match else None
            }
        self.logger.error("Failed to parse bill header with any pattern")
        return {
            'bill_number': "",
            'chapter_number': "",
            'title': "",
            'date_approved': None,
            'date_filed': None
        }

    def _extract_title(self, text: str) -> str:
        title_patterns = [
            r'(?:Assembly|Senate)\s+Bill(?:\s+No\.?)?\s+\d+\s+(?:CHAPTER\s+\d+)?\s+\n+\s*(.+?)\s*\n+\s*(?:Approved|Legislative|The people)',
            r'(?:CHAPTER\s+\d+)\s+\n+\s*(.+?)\s*\n+\s*Legislative Counsel',
            r'(?:Assembly|Senate)\s+Bill(?:\s+No\.?)?\s+\d+.*?\n+\s*(.+?)\s*\n+\s*(?:Approved|Legislative|The people)'
        ]
        for pattern in title_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                title = match.group(1).strip()
                if len(title) > 500:
                    end = title.find("\n\n")
                    if end > 0:
                        title = title[:end].strip()
                return title
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if "Bill" in line and "CHAPTER" in line and i+1 < len(lines):
                for j in range(1, 5):
                    if i+j < len(lines) and lines[i+j].strip() and len(lines[i+j]) > 20:
                        return lines[i+j].strip()
        return ""

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        try:
            formats = ["%B %d, %Y","%B %d,%Y","%b %d, %Y","%b %d,%Y"]
            for fmt in formats:
                try:
                    return datetime.strptime(date_str.strip(), fmt)
                except ValueError:
                    continue
            self.logger.warning(f"Could not parse date: {date_str}")
            return None
        except Exception as e:
            self.logger.error(f"Error parsing date '{date_str}': {str(e)}")
            return None

    def _split_digest_and_bill(self, text: str) -> Tuple[str, str]:
        lower_text = text.lower()
        digest_patterns = ["legislative counsel's digest", "legislative counsel’s digest"]
        digest_start = -1
        for pattern in digest_patterns:
            pos = lower_text.find(pattern)
            if pos != -1:
                digest_start = pos
                break

        if digest_start == -1:
            self.logger.info("No 'Legislative Counsel's Digest' found.")
            return "", text

        bill_start_patterns = [
            "the people of the state of california do enact as follows:",
            "the people of the state of california do enact",
            "california do enact as follows"
        ]
        digest_end = -1
        for pattern in bill_start_patterns:
            pos = lower_text.find(pattern)
            if pos != -1:
                digest_end = pos
                break

        if digest_end == -1:
            section_match = re.search(r'\n\s*((?:SECTION|SEC)\.)\s+1\.', text, re.IGNORECASE)
            if section_match:
                digest_end = section_match.start()
            else:
                digest_end = len(text)

        digest_text = text[digest_start:digest_end].strip()
        bill_portion = text[digest_end:].strip()
        return digest_text, bill_portion

    def _parse_digest_sections(self, digest_text: str) -> List[DigestSection]:
        if not digest_text:
            return []
        sections = []
        digest_start = digest_text.lower().find("digest")
        if digest_start > 0:
            clean_digest = digest_text[digest_start:].strip()
            intro_end = -1
            for pattern in ["(1)", "\n(1)"]:
                pos = clean_digest.find(pattern)
                if pos > 0:
                    intro_end = pos
                    break
            if intro_end > 0:
                clean_digest = clean_digest[intro_end:].strip()
        else:
            clean_digest = digest_text

        matches = re.finditer(self.digest_section_pattern, clean_digest, re.DOTALL)
        for match in matches:
            number = match.group(1)
            text_chunk = match.group(2).strip()
            if not text_chunk:
                continue
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

        self.logger.info(f"Found {len(sections)} digest sections")
        return sections

    def _parse_bill_sections(self, bill_portion: str) -> List[BillSection]:
        return self._parse_bill_sections_improved(bill_portion)

    def _parse_bill_sections_improved(self, bill_portion: str) -> List[BillSection]:
        sections = []
        cleaned_text = bill_portion.strip()
        self.logger.info(f"Starting enhanced bill section parsing for text of length: {len(cleaned_text)}")

        # 1) Direct approach
        matches = list(self.bill_section_pattern.finditer(cleaned_text))
        if matches:
            self.logger.info(f"Found {len(matches)} potential section boundaries with direct approach")
            section_boundaries = []
            for match in matches:
                label = match.group('label').strip()
                number = match.group('number')
                start_pos = match.start()
                section_boundaries.append((start_pos, number, label))

            section_boundaries.sort()
            for i, (start_pos, number, label) in enumerate(section_boundaries):
                if i < len(section_boundaries) - 1:
                    end_pos = section_boundaries[i+1][0]
                else:
                    end_pos = len(cleaned_text)

                full_section_text = cleaned_text[start_pos:end_pos].strip()
                parts = full_section_text.split('\n', 1)
                if len(parts) > 1:
                    section_body = parts[1].strip()
                else:
                    section_body = ""

                if not section_body:
                    self.logger.warning(f"Empty text for section {number}, skipping")
                    continue

                code_refs = self._extract_code_references_robust(section_body)
                bs = BillSection(
                    number=number,
                    original_label=label,
                    text=section_body,
                    code_references=code_refs
                )
                action_type = self._determine_action(section_body)
                if action_type != CodeAction.UNKNOWN:
                    bs.section_type = action_type

                sections.append(bs)

        # 2) fallback
        if not sections:
            self.logger.warning("No sections found with direct approach, using fallback logic.")
            fallback_sections = self._parse_bill_sections_fallback(cleaned_text)
            sections.extend(fallback_sections)

        self.logger.info(f"Enhanced section parsing completed with {len(sections)} sections")
        return sections

    def _parse_bill_sections_fallback(self, bill_portion: str) -> List[BillSection]:
        """
        Fallback approach if direct pattern fails entirely.
        We'll match lines like:
            Sec. <n>.
            SECTION <n>.
        With trailing period, ignoring case, but forcing start-of-line
        so references like "Section 1240" do not match as a top-level section.
        """
        self.logger.info(f"Starting fallback parsing with text length: {len(bill_portion)}")
        sections = []

        pattern = re.compile(
            r'(^|\n)\s*((?:SECTION|SEC)\.)\s+(\d+)\.',
            re.MULTILINE | re.IGNORECASE
        )
        matches = list(pattern.finditer(bill_portion))
        self.logger.info(f"Found {len(matches)} section headers in fallback")

        for i, match in enumerate(matches):
            label_full = match.group(2) + " " + match.group(3) + "."
            number = match.group(3)
            start_idx = match.start()
            if i < len(matches) - 1:
                end_idx = matches[i+1].start()
            else:
                end_idx = len(bill_portion)

            section_text = bill_portion[start_idx:end_idx].strip()
            lines = section_text.split('\n', 1)
            if len(lines) > 1:
                body = lines[1].strip()
            else:
                body = ""

            if not body:
                self.logger.warning(f"Empty text for section {number}, skipping")
                continue

            code_refs = self._extract_code_references_robust(body)
            action_type = self._determine_action(body)

            bs = BillSection(
                number=number,
                original_label=label_full,
                text=body,
                code_references=code_refs
            )
            if action_type != CodeAction.UNKNOWN:
                bs.section_type = action_type

            sections.append(bs)

        return sections

    def _aggressive_normalize_improved(self, text):
        text = text.replace('\r\n', '\n')
        # Force newlines for top-level "SEC." or "SECTION" lines
        text = re.sub(
            r'([^\n])(\b(?:SECTION|SEC)\.?\s+\d+\.)',
            r'\1\n\2',
            text,
            flags=re.IGNORECASE
        )
        text = re.sub(
            r'\n\s*((?:SECTION|SEC)\.?)\s*(\d+)\.\s*',
            r'\n\1 \2.\n',
            text,
            flags=re.IGNORECASE
        )
        text = re.sub(
            r'(\n)((?:SECTION|SEC)\.\s+\d+\.)',
            r'\1\n\n\2',
            text,
            flags=re.IGNORECASE
        )
        text = re.sub(r'(\d+)\s*\n\s*(\.\d+)', r'\1\2', text)
        text = re.sub(r'\s{2,}', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _extract_code_references(self, text: str) -> List[CodeReference]:
        return self._extract_code_references_robust(text)

    def _extract_code_references_robust(self, text: str) -> List[CodeReference]:
        references = []
        first_line = text.split('\n', 1)[0] if '\n' in text else text
        first_line = re.sub(r'(\d+)\s*\n\s*(\.\d+)', r'\1\2', first_line)

        # We keep the same patterns for code references
        section_header_pattern = r'(?i)Section\s+(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        header_match = re.search(section_header_pattern, first_line)
        if header_match:
            section_num = header_match.group(1).strip()
            code_name = header_match.group(2).strip()
            references.append(CodeReference(section=section_num, code_name=code_name))

        decimal_pattern = r'Section\s+(\d+\.\d+)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        for match in re.finditer(decimal_pattern, text):
            section_num = match.group(1).strip()
            code_name = match.group(2).strip()
            references.append(CodeReference(section=section_num, code_name=code_name))

        patterns = [
            r'(?i)Section(?:s)?\s+(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)',
            r'(?i)([A-Za-z\s]+Code)\s+Section(?:s)?\s+(\d+(?:\.\d+)?)',
            r'(?i)Section(?:s)?\s+(\d+(?:\.\d+)?)\s*(?:to|through|-)\s*(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                if len(match.groups()) == 2:
                    if "code" in match.group(2).lower():
                        sections_str, code_name = match.groups()
                        for sect in re.split(r'[,\s]+', sections_str):
                            if sect.strip() and re.match(r'\d+(?:\.\d+)?', sect.strip()):
                                references.append(CodeReference(section=sect.strip(), code_name=code_name.strip()))
                    else:
                        code_name, sections_str = match.groups()
                        for sect in re.split(r'[,\s]+', sections_str):
                            if sect.strip() and re.match(r'\d+(?:\.\d+)?', sect.strip()):
                                references.append(CodeReference(section=sect.strip(), code_name=code_name.strip()))
                elif len(match.groups()) == 3:
                    start, end, code = match.groups()
                    try:
                        if '.' not in start and '.' not in end:
                            for num in range(int(start), int(end) + 1):
                                references.append(CodeReference(section=str(num), code_name=code.strip()))
                        else:
                            references.append(CodeReference(section=start.strip(), code_name=code.strip()))
                            references.append(CodeReference(section=end.strip(), code_name=code.strip()))
                    except (ValueError, TypeError):
                        references.append(CodeReference(section=start.strip(), code_name=code.strip()))
                        references.append(CodeReference(section=end.strip(), code_name=code.strip()))

        return references

    def _determine_action(self, text: str) -> CodeAction:
        lower_text = text.lower()
        if "amended" in lower_text and "repealed" in lower_text:
            return CodeAction.AMENDED_AND_REPEALED
        elif "repealed" in lower_text and "added" in lower_text:
            return CodeAction.REPEALED_AND_ADDED
        elif "amended" in lower_text:
            return CodeAction.AMENDED
        elif "added" in lower_text:
            return CodeAction.ADDED
        elif "repealed" in lower_text:
            return CodeAction.REPEALED
        return CodeAction.UNKNOWN

    def _match_sections(self, bill: TrailerBill) -> None:
        """
        Preliminary linking of digest sections and bill sections by naive text references.
        """
        for ds in bill.digest_sections:
            for bs in bill.bill_sections:
                if f"Section {bs.number}" in ds.text or f"SEC. {bs.number}" in ds.text:
                    ds.bill_sections.append(bs.number)
                digest_code_refs = {f"{ref.code_name} Section {ref.section}" for ref in ds.code_references}
                bill_code_refs = {f"{ref.code_name} Section {ref.section}" for ref in bs.code_references}
                if digest_code_refs and bill_code_refs and digest_code_refs.intersection(bill_code_refs):
                    if bs.number not in ds.bill_sections:
                        ds.bill_sections.append(bs.number)
