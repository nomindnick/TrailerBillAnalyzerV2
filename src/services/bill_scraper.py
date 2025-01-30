import aiohttp
import logging
import re
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from bs4 import BeautifulSoup
from datetime import datetime
from aiohttp import ClientTimeout, TCPConnector
from aiohttp.client_exceptions import ClientError
from enum import Enum

class CodeAction(Enum):
    UNKNOWN = 0
    ADDED = 1
    AMENDED = 2
    REPEALED = 3
    REPEALED_AND_ADDED = 4
    AMENDED_AND_REPEALED = 5

class SectionType(Enum):
    UNKNOWN = 0
    DIGEST = 1
    BILL = 2

class CodeReference:
    def __init__(self, section: str, code_name: str):
        self.section = section
        self.code_name = code_name

class DigestSection:
    def __init__(self, number: str, text: str, existing_law: str,
                 proposed_changes: str, code_references: List[CodeReference]):
        self.number = number
        self.text = text
        self.existing_law = existing_law
        self.proposed_changes = proposed_changes
        self.code_references = code_references
        self.bill_sections: List[str] = []  # store matching BillSection numbers

class BillSection:
    def __init__(self, number: str, text: str, code_references: List[CodeReference]):
        self.number = number
        self.text = text
        self.code_references = code_references
        self.digest_reference: Optional[str] = None

class TrailerBill:
    def __init__(self, bill_number: str, title: str, chapter_number: str,
                 date_approved: Optional[datetime], date_filed: Optional[datetime],
                 raw_text: str):
        self.bill_number = bill_number
        self.title = title
        self.chapter_number = chapter_number
        self.date_approved = date_approved
        self.date_filed = date_filed
        self.raw_text = raw_text

        self.digest_sections: List[DigestSection] = []
        self.bill_sections: List[BillSection] = []

# ---------------------------------------------------------------------
# BillScraper Class - fetches HTML from the CA Legislature site
# ---------------------------------------------------------------------

class BillScraper:
    """
    Handles retrieval and cleaning of trailer bill text from leginfo.legislature.ca.gov
    with improved error handling and retry logic.
    """

    def __init__(self, max_retries: int = 3, timeout: int = 30):
        """
        Initialize the scraper with configurable retry and timeout settings.

        Args:
            max_retries: Maximum number of retry attempts for failed requests
            timeout: Timeout in seconds for each request
        """
        self.logger = logging.getLogger(__name__)
        self.base_url = "https://leginfo.legislature.ca.gov/faces"
        self.bill_url = f"{self.base_url}/billTextClient.xhtml"
        self.max_retries = max_retries
        self.timeout = timeout

        # Common browser headers
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "DNT": "1"
        }

    def get_session_year_range(self, year: int) -> str:
        """Convert an input year to a legislative session range."""
        session_start = year if (year % 2 == 1) else (year - 1)
        return f"{session_start}{session_start + 1}"

    async def get_bill_text(self, bill_number: str, year: int) -> Dict[str, Any]:
        """Retrieves the full text for the specified bill with retry logic."""
        for attempt in range(self.max_retries):
            try:
                bill_number = bill_number.replace(" ", "").upper()
                session_str = self.get_session_year_range(year)
                url = f"{self.bill_url}?bill_id={session_str}0{bill_number}"

                self.logger.info(f"Attempt {attempt + 1}/{self.max_retries}: Fetching bill from {url}")

                timeout = aiohttp.ClientTimeout(total=self.timeout)
                connector = aiohttp.TCPConnector(ssl=False, force_close=True)
                
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.get(url, headers=self.headers, timeout=timeout, allow_redirects=True) as response:
                        self.logger.debug(f"Response status: {response.status}")
                        
                        if response.status == 200:
                            html_content = await response.text()
                            self.logger.debug(f"Response content length: {len(html_content)}")
                            
                            if not html_content:
                                raise ValueError("Empty response received")
                                
                            result = self._parse_bill_page(html_content)
                            self.logger.info(f"Successfully parsed bill text of length {len(result.get('full_text', ''))}")
                            return result
                            
                        response.raise_for_status()

            except Exception as e:
                self.logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt == self.max_retries - 1:
                    raise RuntimeError(f"Failed to fetch bill after {self.max_retries} attempts: {str(e)}")
                await asyncio.sleep(1)  # Wait before retrying

    def _parse_bill_page(self, html_content: str) -> Dict[str, Any]:
        """Parse the HTML content from the Legislature site."""
        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Log the first 500 characters of HTML for debugging
            self.logger.debug(f"Raw HTML preview: {html_content[:500]}")

            # Remove script and style elements
            self._strip_scripts_and_styles(soup)

            # Try multiple container selectors with logging
            content_div = None
            for selector in [
                {"name": "div", "class_": "bill-content"},
                {"name": "div", "class_": "contentArea"},
                {"name": "div", "id": "bill_all"},
                {"name": "article", "id": "bill_all"}
            ]:
                candidate = soup.find(**selector)
                if candidate:
                    self.logger.debug(f"Found content using selector: {selector}")
                    content_div = candidate
                    break
                else:
                    self.logger.debug(f"No match found for selector: {selector}")

            if not content_div:
                # Log available classes and IDs for debugging
                all_divs = soup.find_all('div')
                self.logger.debug("Available div classes and IDs:")
                for div in all_divs[:10]:
                    self.logger.debug(f"Class: {div.get('class')}, ID: {div.get('id')}")
                raise ValueError("Could not find valid bill content in HTML")

            # Get the full text content
            full_text = content_div.get_text("\n", strip=True)

            # Additional cleanup - remove multiple newlines and spaces
            full_text = re.sub(r'\n\s*\n', '\n\n', full_text)
            full_text = re.sub(r' +', ' ', full_text)

            # Validate content
            if not full_text or len(full_text.strip()) < 100:
                self.logger.warning(f"Retrieved text appears short: {len(full_text)} chars")
                raise ValueError("Retrieved bill content appears to be empty or invalid")

            # Log the length of extracted text
            self.logger.debug(f"Extracted text length: {len(full_text)}")

            return {
                'full_text': full_text,  # Changed from 'text' to 'full_text'
                'html': str(content_div)
            }

        except Exception as e:
            self.logger.error(f"Error parsing bill page: {str(e)}")
            self.logger.debug(f"HTML content length: {len(html_content)}")
            raise

    def _strip_scripts_and_styles(self, soup: BeautifulSoup) -> None:
        """Remove script and style elements from BeautifulSoup object."""
        for elem in soup(["script", "style"]):
            elem.decompose()

# ---------------------------------------------------------------------
# BaseParser Class - does the regex-based parsing of the downloaded text
# ---------------------------------------------------------------------

class BaseParser:
    """
    Handles initial regex-based parsing of trailer bills to extract basic structure,
    digest sections, and bill sections.
    """

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
        self.logger = logging.getLogger(__name__)

        # Bill header pattern: e.g. "Assembly Bill 173 CHAPTER 53 ..."
        self.bill_header_pattern = (
            r'(Assembly|Senate)\s+Bill\s+(?:No\.?\s+)?(\d+)\s+CHAPTER\s*(\d+)\s*'
        )

        # Digest sections: matches "(1) some text (2) next text..."
        self.digest_section_pattern = r'\((\d+)\)\s+([^(]+)(?=\(\d+\)|$)'

        # Updated: We use a multiline pattern to capture lines that START with 
        # "SECTION X." or "SEC. X." (case-insensitive), 
        # pulling all subsequent text until the next "SECTION Y." or end of string.
        #
        # Explanation:
        #   ^ = start of line (because of re.MULTILINE)
        #   (?:SEC(?:TION)?\.?) => matches "SEC." or "SECTION" or "Sec." etc.
        #   \s+(\d+(?:\.\d+)?) => capturing group for the numeric part
        #   (?:\.|:)?\s+ => optional "." or ":" plus some whitespace
        #   (.*?) => lazy capture for the body
        #   (?=^(?:SEC(?:TION)?\.?)\s+\d+|\Z) => lookahead for next "SECTION X" or end-of-string
        #
        self.bill_section_pattern = (
            r'^(?:SEC(?:TION)?\.?)\s+(\d+(?:\.\d+)?)(?:\.|:)?\s+(.*?)'
            r'(?=^(?:SEC(?:TION)?\.?)\s+\d+|\Z)'
        )

        # Approved/Filed date pattern
        self.date_pattern = (
            r'Approved by Governor\s+([^.]+)\.\s+'
            r'Filed with Secretary of State\s+([^.]+)\.'
        )

    def parse_bill(self, bill_text: str) -> TrailerBill:
        # Normalize lines that contain "SEC." or "SECTION." so they appear at the start
        cleaned_text = self._normalize_section_breaks(bill_text)

        # Parse header
        header_info = self._parse_bill_header(cleaned_text)

        # Build our TrailerBill model
        bill = TrailerBill(
            bill_number=header_info['bill_number'],
            title=header_info['title'],
            chapter_number=header_info['chapter_number'],
            date_approved=header_info['date_approved'],
            date_filed=header_info['date_filed'],
            raw_text=cleaned_text
        )

        # Split digest from main portion (may be empty if no "Legislative Counsel's Digest" found)
        digest_text, bill_portion = self._split_digest_and_bill(cleaned_text)

        # Parse the digest sections
        bill.digest_sections = self._parse_digest_sections(digest_text)

        # Parse the actual numbered sections
        bill.bill_sections = self._parse_bill_sections(bill_portion)

        # Link digest sections to bill sections if they share code references
        self._match_sections(bill)

        return bill

    def _parse_bill_header(self, text: str) -> dict:
        header_match = re.search(self.bill_header_pattern, text, re.MULTILINE | re.IGNORECASE)
        if not header_match:
            # Not all trailer bills strictly have "Assembly Bill ___ CHAPTER ___" lines,
            # so let's just do a fallback
            self.logger.warning("Could not parse a 'bill header' with the standard pattern.")
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
        Splits out the "Legislative Counsel's Digest" portion (if any), 
        returning (digest_text, remainder).
        """
        lower_text = text.lower()
        digest_start = lower_text.find("legislative counsel's digest")

        if digest_start == -1:
            self.logger.info("No 'Legislative Counsel's Digest' found. Entire text is bill portion.")
            return "", text

        # Usually it ends around "The people of the State of California do enact as follows:"
        # or some variant. Let's look for that phrase:
        digest_end = lower_text.find("the people of the state of california do enact as follows:")
        if digest_end == -1:
            # fallback
            fallback_pattern = r"the people of the state of california do enact"
            m = re.search(fallback_pattern, lower_text, re.IGNORECASE)
            if m:
                digest_end = m.start()
            else:
                self.logger.info(
                    "Couldn't find 'The people... do enact' after the digest. "
                    "We'll treat the remainder as bill portion."
                )
                digest_end = len(text)

        digest_text = text[digest_start:digest_end].strip()
        bill_portion = text[digest_end:].strip()
        return digest_text, bill_portion

    def _parse_digest_sections(self, digest_text: str) -> List[DigestSection]:
        if not digest_text:
            return []

        sections = []
        # This pattern tries to parse chunks like "(1) ...some text... (2) ...some text..."
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
        If the digest portion includes "Existing law" and "This bill would ...", 
        try to separate them for convenience. Otherwise, keep them as one chunk.
        """
        if "Existing law" in text and "This bill would" in text:
            parts = text.split("This bill would", 1)
            existing = parts[0].replace("Existing law", "", 1).strip()
            changes = "This bill would" + parts[1].strip()
            return existing, changes
        return "", text

    def _parse_bill_sections(self, bill_portion: str) -> List[BillSection]:
        """
        Uses a multiline regex to parse each enumerated section that starts with 
        "SECTION X." or "SEC. X." on its own line, capturing all text until 
        the next "SECTION Y." or the end of the string.
        """
        sections = []

        # We'll do multiline matching
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
            # No explicit "SECTION X." lines found. We do a fallback approach:
            self.logger.info("No explicit 'SECTION X.' lines found; using fallback logic.")
            fallback_refs = self._extract_code_references(bill_portion)
            if fallback_refs:
                # If we have code references, each reference might be a 'section'
                for i, ref in enumerate(fallback_refs, start=1):
                    fallback_body = f"Reference to {ref.code_name} section {ref.section}."
                    sections.append(
                        BillSection(
                            number=str(i),
                            text=fallback_body,
                            code_references=[ref]
                        )
                    )
            else:
                # Just treat the entire leftover text as a single BillSection
                leftover = bill_portion.strip()
                if leftover:
                    sections.append(
                        BillSection(
                            number="1",
                            text=leftover,
                            code_references=[]
                        )
                    )

        return sections

    def _parse_section_header(self, text: str) -> Tuple[List[CodeReference], Optional[CodeAction]]:
        """
        Inspect the first line for hints of "added", "amended", "repealed", etc.
        Then parse code references from that line.
        """
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

    def _extract_code_references(self, text: str) -> List[CodeReference]:
        """
        Looks for references like:
          "Section 8594.14 of the Government Code"
          "Sections 123 and 125 of the Penal Code"
          "Sections 187010, 187022, and 187030 of the Public Utilities Code"
        """
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
        # Replace "and" with commas for simpler splitting
        text = re.sub(r'\s*and\s*', ',', text, flags=re.IGNORECASE)
        parts = re.split(r'[,\s]+', text)
        return [p.strip() for p in parts if p.strip() and re.match(r'^[\d\.]+$', p.strip())]

    def _match_sections(self, bill: TrailerBill) -> None:
        """
        Naive linking: if a digest section references e.g. Government Code 8594.14,
        and a bill section references Government Code 8594.14, we link them.
        """
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
                # Overlap means a match
                if digest_refs & bill_refs:
                    digest_section.bill_sections.append(bill_section.number)
                    bill_section.digest_reference = digest_section.number

    def _extract_title(self, text: str) -> str:
        """
        Try to find "An act to ..." up to "LEGISLATIVE COUNSEL'S DIGEST" or bracket
        as a rough 'title'.
        """
        title_pattern = r'An act to .*?(?=\[|LEGISLATIVE COUNSEL|$)'
        match = re.search(title_pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group().strip()
        return ""

    def _parse_date(self, date_str: str) -> datetime:
        """
        Attempt to parse "June 26, 2023" style strings into a datetime.
        """
        return datetime.strptime(date_str.strip(), '%B %d, %Y')

    def _normalize_section_breaks(self, text: str) -> str:
        """
        Insert a newline after . : ; if the next word is “SEC.” or “SECTION.” 
        to ensure they appear at the start of a line for our multiline regex.
        """
        text = re.sub(
            r'([.:;])(?!\n)\s*(?=(SEC(?:TION)?\.))',
            r'\1\n',
            text,
            flags=re.IGNORECASE
        )
        return text