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
        try:
            # First clean any HTML markup from amended bills
            cleaned_text = self._clean_html_markup(bill_text)

            # Then normalize section breaks for consistent parsing
            cleaned_text = self._aggressive_normalize(cleaned_text)

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

            # Set relationships between digest sections and bill sections
            self._match_sections(bill)

            self.logger.info(f"Successfully parsed bill with {len(bill.digest_sections)} digest sections "
                            f"and {len(bill.bill_sections)} bill sections")
            return bill

        except Exception as e:
            self.logger.error(f"Error parsing bill: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            # Return a minimal bill object rather than completely failing
            return TrailerBill(
                bill_number="Unknown",
                title="Parse Error",
                chapter_number="",
                raw_text=bill_text
            )

    def _split_existing_and_changes(self, text: str) -> Tuple[str, str]:
        """
        Split a digest section text into existing law and proposed changes.

        Args:
            text: The text of a digest section

        Returns:
            A tuple with (existing_law, proposed_changes)
        """
        # Look for phrases that typically separate existing and proposed law
        separators = [
            "This bill would",
            "The bill would",
            "Instead, this bill",
            "This bill will"
        ]

        lower_text = text.lower()

        # Try to find the first occurrence of any separator
        split_pos = -1
        found_separator = ""

        for separator in separators:
            pos = text.find(separator)
            if pos != -1 and (split_pos == -1 or pos < split_pos):
                split_pos = pos
                found_separator = separator

        # If no separator was found, make best guess
        if split_pos == -1:
            # Default split - search for "would" which is common in proposed changes
            would_pos = lower_text.find("would")
            if would_pos != -1:
                # Look for the start of the sentence containing "would"
                sentence_start = would_pos
                while sentence_start > 0 and text[sentence_start-1] not in ".!?":
                    sentence_start -= 1

                if sentence_start > 0:
                    existing_law = text[:sentence_start].strip()
                    proposed_changes = text[sentence_start:].strip()
                else:
                    # If we can't find a good split, return half as existing and half as changes
                    midpoint = len(text) // 2
                    existing_law = text[:midpoint].strip()
                    proposed_changes = text[midpoint:].strip()
            else:
                # If we can't find "would", return half as existing and half as changes
                midpoint = len(text) // 2
                existing_law = text[:midpoint].strip()
                proposed_changes = text[midpoint:].strip()
        else:
            existing_law = text[:split_pos].strip()
            proposed_changes = text[split_pos:].strip()

        return existing_law, proposed_changes

    def _clean_html_markup(self, text: str) -> str:
        """
        Clean HTML markup from amended bills to create plain text that's easier to parse.
        Handles strikethroughs, additions, and other HTML formatting.
        """
        # First, handle the strike-through content (removed text)
        # We simply remove it since it's not part of the final bill text
        text = re.sub(r'<font color="#B30000"><strike>.*?</strike></font>', '', text, flags=re.DOTALL)
        text = re.sub(r'<strike>.*?</strike>', '', text, flags=re.DOTALL)

        # Then handle blue text (added text)
        # We keep this content but remove the HTML markup
        text = re.sub(r'<font color="blue" class="blue_text"><i>(.*?)</i></font>', r'\1', text, flags=re.DOTALL)
        text = re.sub(r'<i>(.*?)</i>', r'\1', text, flags=re.DOTALL)
        text = re.sub(r'<font color="blue">(.*?)</font>', r'\1', text, flags=re.DOTALL)

        # Remove any remaining HTML tags
        text = re.sub(r'<[^>]*>', '', text)

        # Clean up extra whitespace
        text = re.sub(r'\s+', ' ', text)

        # Make sure section identifiers are separated by newlines
        text = re.sub(r'([^\n])(SEC\.|SECTION)', r'\1\n\2', text, flags=re.IGNORECASE)

        # Ensure consistency in section formatting
        text = re.sub(r'\n\s*(SEC\.?|SECTION)\s*(\d+)\.\s*', r'\n\1 \2.\n', text, flags=re.IGNORECASE)

        return text

    def _extract_title(self, text: str) -> str:
        """
        Extract the title of the bill from the text.

        Args:
            text: The bill text

        Returns:
            The extracted title or empty string if not found
        """
        # Try different patterns to extract the title
        title_patterns = [
            # Look for title after bill header
            r'(?:Assembly|Senate)\s+Bill(?:\s+No\.?)?\s+\d+\s+(?:CHAPTER\s+\d+)?\s+\n+\s*(.+?)\s*\n+\s*(?:Approved|Legislative|The people)',

            # Look for text between header and digest
            r'(?:CHAPTER\s+\d+)\s+\n+\s*(.+?)\s*\n+\s*Legislative Counsel',

            # More general pattern
            r'(?:Assembly|Senate)\s+Bill(?:\s+No\.?)?\s+\d+.*?\n+\s*(.+?)\s*\n+\s*(?:Approved|Legislative|The people)'
        ]

        for pattern in title_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                title = match.group(1).strip()
                # If the title is too long, it may have captured too much text
                if len(title) > 500:
                    # Try to truncate at a reasonable point
                    end = title.find("\n\n")
                    if end > 0:
                        title = title[:end].strip()
                return title

        # If no pattern works, try a simple approach
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if "Bill" in line and "CHAPTER" in line and i+1 < len(lines):
                # The title is likely in the next few lines
                for j in range(1, 5):
                    if i+j < len(lines) and lines[i+j].strip() and len(lines[i+j]) > 20:
                        return lines[i+j].strip()

        # Return empty string if no title found
        return ""

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse a date string from the bill into a datetime object.

        Args:
            date_str: The date string from the bill (e.g. "July 10, 2023")

        Returns:
            A datetime object or None if parsing fails
        """
        try:
            # Try different date formats
            formats = [
                "%B %d, %Y",     # "July 10, 2023"
                "%B %d,%Y",      # "July 10,2023"
                "%b %d, %Y",     # "Jul 10, 2023"
                "%b %d,%Y"       # "Jul 10,2023"
            ]

            for fmt in formats:
                try:
                    return datetime.strptime(date_str.strip(), fmt)
                except ValueError:
                    continue

            # If we get here, no format worked
            self.logger.warning(f"Could not parse date: {date_str}")
            return None

        except Exception as e:
            self.logger.error(f"Error parsing date '{date_str}': {str(e)}")
            return None

    def _parse_bill_header(self, text: str) -> Dict[str, Any]:
        """
        Parse the bill header to extract bill number, chapter, title, and dates.

        Enhanced to handle amended bills with complex markup.

        Args:
            text: The bill text

        Returns:
            A dictionary with header information
        """
        # First, try the standard pattern
        header_match = re.search(self.bill_header_pattern, text, re.MULTILINE | re.IGNORECASE | re.DOTALL)

        # If standard pattern fails, try a more flexible pattern that can handle amended bills
        if not header_match:
            self.logger.warning("Could not parse bill header with standard pattern")

            # More flexible patterns for amended bills
            alt_patterns = [
                # Look for bill number in a more flexible way
                r'(Assembly|Senate)\s+Bill(?:\s+No\.?)?\s+(\d+)',

                # Look for chapter number separately
                r'CHAPTER\s+(\d+)',
            ]

            bill_type = None
            bill_num = None
            chapter = ""

            # Try to find bill type and number
            bill_match = re.search(alt_patterns[0], text, re.IGNORECASE)
            if bill_match:
                bill_type = bill_match.group(1)
                bill_num = bill_match.group(2)

            # Try to find chapter number
            chapter_match = re.search(alt_patterns[1], text, re.IGNORECASE)
            if chapter_match:
                chapter = chapter_match.group(1)

            if bill_type and bill_num:
                # Use the extracted information
                header_info = {
                    'bill_number': f"{bill_type} Bill {bill_num}",
                    'chapter_number': chapter,
                    'title': self._extract_title(text),
                    'date_approved': None,
                    'date_filed': None
                }

                # Try to extract dates
                date_match = re.search(self.date_pattern, text)
                if date_match:
                    header_info['date_approved'] = self._parse_date(date_match.group(1)) if date_match else None
                    header_info['date_filed'] = self._parse_date(date_match.group(2)) if date_match else None

                return header_info

        # If the standard pattern worked, use it
        if header_match:
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

        # If all else fails, return empty values
        self.logger.error("Failed to parse bill header with any pattern")
        return {
            'bill_number': "",
            'chapter_number': "",
            'title': "",
            'date_approved': None,
            'date_filed': None
        }

    def _split_digest_and_bill(self, text: str) -> Tuple[str, str]:
        """
        Split the bill text into the digest portion and the actual bill portion.

        Args:
            text: The full bill text

        Returns:
            A tuple of (digest_text, bill_portion)
        """
        lower_text = text.lower()

        # Try to find the digest start
        digest_patterns = [
            "legislative counsel's digest",
            "legislative counsel's digest"  # Alternative apostrophe
        ]

        digest_start = -1
        for pattern in digest_patterns:
            pos = lower_text.find(pattern)
            if pos != -1:
                digest_start = pos
                break

        if digest_start == -1:
            self.logger.info("No 'Legislative Counsel's Digest' found.")
            return "", text

        # Try to find where the bill text starts
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
            # If we can't find the standard separator, look for the first section
            section_match = re.search(r'\n\s*(?:SECTION|SEC)\.\s+1\.', text, re.IGNORECASE)
            if section_match:
                digest_end = section_match.start()
            else:
                # If all else fails, use entire text
                digest_end = len(text)

        digest_text = text[digest_start:digest_end].strip()
        bill_portion = text[digest_end:].strip()

        return digest_text, bill_portion

    def _parse_digest_sections(self, digest_text: str) -> List[DigestSection]:
        """
        Parse the digest text into individual digest sections.

        Args:
            digest_text: The text of the Legislative Counsel's Digest

        Returns:
            A list of DigestSection objects
        """
        if not digest_text:
            return []

        sections = []

        # Skip the header of the digest
        digest_start = digest_text.lower().find("digest")
        if digest_start > 0:
            clean_digest = digest_text[digest_start:].strip()

            # Find the end of the introduction paragraph
            intro_end = -1
            for pattern in ["(1)", "\n(1)"]:
                pos = clean_digest.find(pattern)
                if pos > 0:
                    intro_end = pos
                    break

            if intro_end > 0:
                # Remove the introduction
                clean_digest = clean_digest[intro_end:].strip()
        else:
            clean_digest = digest_text

        # Find all digest items using the pattern
        matches = re.finditer(self.digest_section_pattern, clean_digest, re.DOTALL)
        for match in matches:
            number = match.group(1)
            text_chunk = match.group(2).strip()

            # Skip empty sections
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

        self.logger.info(f"Parsed {len(sections)} bill sections using pattern {successful_pattern}")
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

        # Add space after section label if needed
        text = re.sub(r'(SEC\.|SECTION)\s*(\d+\.)', r'\1 \2', text, flags=re.IGNORECASE)

        # Enhance section visibility
        text = re.sub(r'\n\s*(SEC\.|SECTION)\s+(\d+)\.', r'\n\1 \2.\n', text, flags=re.IGNORECASE)

        # Fix double spaces
        text = re.sub(r'\s{2,}', ' ', text)

        return text

    def _normalize_section_breaks(self, text: str) -> str:
        """
        Ensure section breaks are consistently formatted to improve pattern matching.

        Args:
            text: The bill text to normalize

        Returns:
            Normalized text with consistent section breaks
        """
        # Ensure newlines before section headers
        normalized = re.sub(
            r'(?<!\n)(?:\s*)((?:SECTION|SEC)\.?\s+\d+(?:\.\d+)?\.)',
            r'\n\1',
            text,
            flags=re.IGNORECASE
        )

        # Standardize spacing in section headers
        normalized = re.sub(
            r'((?:SECTION|SEC)\.?)\s*(\d+(?:\.\d+)?)\.',
            r'\1 \2.',
            normalized,
            flags=re.IGNORECASE
        )

        # Make sure all section headers are followed by at least one newline
        normalized = re.sub(
            r'((?:SECTION|SEC)\.?\s+\d+(?:\.\d+)?\.)\s*(?!\n)',
            r'\1\n',
            normalized,
            flags=re.IGNORECASE
        )

        return normalized

    def _extract_code_references(self, text: str) -> List[CodeReference]:
        """
        Extract code references from text by delegating to the robust version.

        Args:
            text: The text to search for code references

        Returns:
            A list of CodeReference objects
        """
        # Simply delegate to the existing robust implementation
        return self._extract_code_references_robust(text)

    def _extract_code_references_robust(self, text: str) -> List[CodeReference]:
        """
        Extract code references with special handling for decimal points and other formatting issues.

        Args:
            text: The text to search for code references

        Returns:
            A list of CodeReference objects
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

            # Range format: "Sections 123-128 of the Education Code"
            r'(?i)Section(?:s)?\s+(\d+(?:\.\d+)?)\s*(?:to|through|-)\s*(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text):
                if len(match.groups()) == 2:  # Standard or reverse format
                    if "code" in match.group(2).lower():  # "Section X of Y Code" format
                        sections_str, code_name = match.groups()
                        for section in re.split(r'[,\s]+', sections_str):
                            if section.strip() and re.match(r'\d+(?:\.\d+)?', section.strip()):
                                references.append(CodeReference(section=section.strip(), code_name=code_name.strip()))
                    else:  # "Y Code Section X" format
                        code_name, sections_str = match.groups()
                        for section in re.split(r'[,\s]+', sections_str):
                            if section.strip() and re.match(r'\d+(?:\.\d+)?', section.strip()):
                                references.append(CodeReference(section=section.strip(), code_name=code_name.strip()))
                elif len(match.groups()) == 3:  # Range format
                    start, end, code = match.groups()
                    try:
                        # For integer ranges, expand them
                        if '.' not in start and '.' not in end:
                            for num in range(int(start), int(end) + 1):
                                references.append(CodeReference(section=str(num), code_name=code.strip()))
                        else:
                            # For decimal points, just add the endpoints
                            references.append(CodeReference(section=start.strip(), code_name=code.strip()))
                            references.append(CodeReference(section=end.strip(), code_name=code.strip()))
                    except (ValueError, TypeError):
                        # If we can't convert to numbers, just add the endpoints
                        references.append(CodeReference(section=start.strip(), code_name=code.strip()))
                        references.append(CodeReference(section=end.strip(), code_name=code.strip()))

        return references

    def _determine_action(self, text: str) -> CodeAction:
        """
        Determine the type of code action (added, amended, repealed, etc.) from the text.

        Args:
            text: The section text

        Returns:
            A CodeAction enum value
        """
        lower_text = text.lower()

        # Check for combined actions first
        if "amended" in lower_text and "repealed" in lower_text:
            return CodeAction.AMENDED_AND_REPEALED
        elif "repealed" in lower_text and "added" in lower_text:
            return CodeAction.REPEALED_AND_ADDED

        # Then check for individual actions
        elif "amended" in lower_text:
            return CodeAction.AMENDED
        elif "added" in lower_text:
            return CodeAction.ADDED
        elif "repealed" in lower_text:
            return CodeAction.REPEALED

        return CodeAction.UNKNOWN

    def _match_sections(self, bill: TrailerBill) -> None:
        """
        Set preliminary relationships between digest sections and bill sections.
        This is a basic implementation - more sophisticated matching will be done
        by the SectionMatcher service.

        Args:
            bill: The TrailerBill object
        """
        # This is a basic implementation that will be replaced by the SectionMatcher
        # Just set up preliminary relationships based on section numbers mentioned in digest text
        for digest_section in bill.digest_sections:
            for bill_section in bill.bill_sections:
                # Look for explicit mentions
                if f"Section {bill_section.number}" in digest_section.text or f"SEC. {bill_section.number}" in digest_section.text:
                    digest_section.bill_sections.append(bill_section.number)

                # Also try to match based on code references
                digest_code_refs = {f"{ref.code_name} Section {ref.section}" for ref in digest_section.code_references}
                bill_code_refs = {f"{ref.code_name} Section {ref.section}" for ref in bill_section.code_references}

                if digest_code_refs and bill_code_refs and digest_code_refs.intersection(bill_code_refs):
                    if bill_section.number not in digest_section.bill_sections:
                        digest_section.bill_sections.append(bill_section.number)