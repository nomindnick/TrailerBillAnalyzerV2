import aiohttp
import logging
import re
import asyncio
from typing import Dict, Any, Optional, List
from bs4 import BeautifulSoup
from datetime import datetime
from aiohttp import ClientTimeout, TCPConnector
from aiohttp.client_exceptions import ClientError, ClientResponseError

class BillScraper:
    """
    Handles retrieval and cleaning of trailer bill text from leginfo.legislature.ca.gov
    with improved error handling, retry logic, and support for amended bills with markup.
    """

    def __init__(self, max_retries: int = 3, timeout: int = 30):
        self.logger = logging.getLogger(__name__)
        self.base_url = "https://leginfo.legislature.ca.gov"
        self.bill_url = f"{self.base_url}/faces/billNavClient.xhtml"
        self.max_retries = max_retries
        self.timeout = ClientTimeout(total=timeout)

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        }

    def get_session_year_range(self, year: int) -> str:
        """
        Calculate the legislative session year range based on the provided year.
        Legislative sessions in California run for 2 years, starting on odd years.
        """
        session_start = year if (year % 2 == 1) else (year - 1)
        return f"{session_start}{session_start + 1}"

    async def get_bill_text(self, bill_number: str, year: int) -> Dict[str, Any]:
        """
        Retrieves the full text for the specified bill with robust retry logic.

        Args:
            bill_number: The bill identifier (e.g., "AB123", "SB456")
            year: The year of the legislative session

        Returns:
            Dictionary containing bill text and metadata
        """
        bill_number = bill_number.replace(" ", "").upper()
        session_str = self.get_session_year_range(year)
        url = f"{self.bill_url}?bill_id={session_str}0{bill_number}"

        self.logger.info(f"Attempting to fetch bill {bill_number} from session {year}-{year+1}")
        self.logger.info(f"Request URL: {url}")

        for attempt in range(1, self.max_retries + 1):
            try:
                return await self._fetch_bill(url, bill_number, year, attempt)
            except ClientResponseError as e:
                if e.status == 404:
                    self.logger.error(f"Bill not found: {bill_number} (404 response)")
                    raise ValueError(f"Bill {bill_number} from session {year}-{year+1} not found")
                elif attempt < self.max_retries:
                    wait_time = 2 ** attempt
                    self.logger.warning(f"Request failed with status {e.status}, retrying in {wait_time}s (attempt {attempt}/{self.max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    self.logger.error(f"Failed to fetch bill after {self.max_retries} attempts: {str(e)}")
                    raise
            except Exception as e:
                if attempt < self.max_retries:
                    wait_time = 2 ** attempt
                    self.logger.warning(f"Error fetching bill: {str(e)}, retrying in {wait_time}s (attempt {attempt}/{self.max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    self.logger.error(f"Failed to fetch bill after {self.max_retries} attempts: {str(e)}")
                    raise

        raise ValueError(f"Failed to fetch bill {bill_number} after {self.max_retries} attempts")

    async def _fetch_bill(self, url: str, bill_number: str, year: int, attempt: int) -> Dict[str, Any]:
        """
        Helper method to fetch and process a bill from the legislature website.
        """
        self.logger.info(f"Fetching bill {bill_number}, attempt {attempt}/{self.max_retries}")

        connector = TCPConnector(ssl=False, limit=1, force_close=True)

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=self.timeout,
            headers=self.headers
        ) as session:
            async with session.get(url) as response:
                self.logger.info(f"Response status: {response.status}")
                response.raise_for_status()

                html_content = await response.text()
                content_length = len(html_content) if html_content else 0
                self.logger.info(f"Received HTML content of length: {content_length}")

                if not html_content or content_length < 100:
                    raise ValueError(f"Received invalid content (length: {content_length})")

                # Check for "bill not found" messages
                not_found_indicators = [
                    "bill not available",
                    "not found",
                    "content not found",
                    "no bill information available"
                ]
                if any(indicator in html_content.lower() for indicator in not_found_indicators):
                    raise ValueError(f"Bill {bill_number} from session {year}-{year+1} was not found")

                result = self._parse_bill_page(html_content)
                if not result or not result.get('full_text'):
                    self.logger.warning("Initial parsing failed, trying alternative approach")
                    result = self._parse_bill_page_alternative(html_content)
                    if not result or not result.get('full_text'):
                        raise ValueError("Failed to extract bill text from HTML")

                self.logger.info(f"Successfully parsed bill text of length {len(result.get('full_text', ''))}")
                result.update(self._extract_bill_metadata(html_content))

                return result

    def _parse_bill_page(self, html_content: str) -> Dict[str, Any]:
        """
        Parse the HTML content from the Legislature site to extract the main text.
        """
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            for elem in soup(["script", "style"]):
                elem.decompose()

            content_div = None
            selectors = [
                {"name": "div", "class_": "bill-content"},
                {"name": "div", "class_": "contentArea"},
                {"name": "div", "id": "bill_all"},
                {"name": "article", "id": "bill_all"},
                {"name": "div", "id": "bill_text"},
                {"name": "div", "class_": "bill-detail"}
            ]
            for selector in selectors:
                candidate = soup.find(**selector)
                if candidate:
                    content_div = candidate
                    self.logger.info(f"Found bill content using selector: {selector}")
                    break

            if not content_div:
                raise ValueError("Could not find valid bill content in HTML")

            html_content_div = str(content_div)
            full_text = self._clean_html_markup_enhanced(html_content_div)
            full_text = self._normalize_whitespace(full_text)
            full_text = self._normalize_section_breaks(full_text)

            if not full_text or len(full_text.strip()) < 100:
                raise ValueError("Retrieved bill content appears to be empty or invalid")

            return {
                'full_text': full_text,
                'html': html_content_div,
                'has_amendments': '<strike>' in html_content_div or '<font color="blue"' in html_content_div
            }
        except Exception as e:
            self.logger.error(f"Error parsing bill page: {str(e)}")
            raise

    def _parse_bill_page_alternative(self, html_content: str) -> Dict[str, Any]:
        """
        Alternative parsing for unusual structure.
        """
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            main_content = soup.find(id="main-content") or soup.find(id="content-area") or soup.find("main")

            if main_content:
                text_elements = main_content.find_all(['p', 'div', 'article', 'section'])
                bill_text_parts = []
                for elem in text_elements:
                    text = elem.get_text(strip=True)
                    # Quick heuristic:
                    if len(text) > 200 or ("section" in text.lower() and "chapter" in text.lower()):
                        bill_text_parts.append(elem.get_text("\n", strip=True))

                if bill_text_parts:
                    combined_text = "\n\n".join(bill_text_parts)
                    cleaned_text = self._clean_html_markup_enhanced(combined_text)
                    cleaned_text = self._normalize_whitespace(cleaned_text)
                    cleaned_text = self._normalize_section_breaks(cleaned_text)
                    return {
                        'full_text': cleaned_text,
                        'html': str(main_content),
                        'has_amendments': ('<strike>' in str(main_content) or '<font color="blue"' in str(main_content)),
                        'parse_method': 'alternative'
                    }

            all_text = soup.get_text("\n", strip=True)
            if all_text and len(all_text) > 1000:
                markers = ["CHAPTER", "SECTION", "SEC.", "Legislative Counsel", "do enact as follows"]
                if any(marker in all_text for marker in markers):
                    cleaned_text = self._clean_html_markup_enhanced(html_content)
                    cleaned_text = self._normalize_whitespace(cleaned_text)
                    cleaned_text = self._normalize_section_breaks(cleaned_text)
                    return {
                        'full_text': cleaned_text,
                        'html': html_content,
                        'has_amendments': '<strike>' in html_content or '<font color="blue"' in html_content,
                        'parse_method': 'text_extraction'
                    }

            raise ValueError("Could not extract bill text using alternative parsing")

        except Exception as e:
            self.logger.error(f"Error in alternative bill parsing: {str(e)}")
            raise

    def _extract_bill_metadata(self, html_content: str) -> Dict[str, Any]:
        """
        Extract additional metadata about the bill from the HTML.
        """
        metadata = {}
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            status_elem = soup.find(class_="bill-status") or soup.find(text=re.compile("Current Bill Status"))
            if status_elem:
                status_text = status_elem.get_text(strip=True) if hasattr(status_elem, 'get_text') else str(status_elem)
                metadata['status'] = status_text

            author_elem = soup.find(text=re.compile("Author:")) or soup.find(text=re.compile("Principal coauthors:"))
            if author_elem and author_elem.find_next():
                author_text = author_elem.find_next().get_text(strip=True)
                metadata['authors'] = author_text

            action_date = soup.find(text=re.compile("Last Action:"))
            if action_date and action_date.find_next():
                action_text = action_date.find_next().get_text(strip=True)
                metadata['last_action'] = action_text

            votes = []
            vote_rows = soup.find_all(class_="vote-row")
            for row in vote_rows:
                if hasattr(row, 'get_text'):
                    votes.append(row.get_text(strip=True))
            if votes:
                metadata['votes'] = votes

            return metadata
        except Exception as e:
            self.logger.warning(f"Error extracting bill metadata: {str(e)}")
            return metadata

    def _clean_html_markup_enhanced(self, text):
        """
        Enhanced method to clean HTML markup from amended bills,
        removing strikethrough or red text and preserving real sections.
        Specifically preserves "SECTION 1." and "SEC. N." formats that
        are the standard for bill text sections.
        """
        self.logger.info("Starting enhanced HTML markup cleaning...")
        
        # First, specifically identify and preserve bill text sections (SECTION 1., SEC. N.)
        # These are the actual bill section markers (not statute section references)
        # We want to capture both standard formats:
        # 1. SECTION 1. (first section)
        # 2. SEC. N. (all other sections)
        bill_text_section_pattern = re.compile(
            r'(?:<[^>]*>)*(?:SECTION|SEC)\.?\s+(\d+)\.?(?:<[^>]*>)*',
            re.DOTALL | re.IGNORECASE
        )
        
        # Run a first pass to identify and preserve ALL section markers
        bill_text_sections = list(bill_text_section_pattern.finditer(text))
        self.logger.info(f"Initial scan found {len(bill_text_sections)} potential section markers")
        
        section_markers = {}
        
        # First, look for SECTION 1. specifically (as it's special)
        for match in bill_text_sections:
            section_number = match.group(1)
            section_text = match.group(0)
            
            # Check if this is SECTION 1
            if section_number == "1" and "SECTION" in section_text.upper():
                # Extract the exact text with HTML stripped
                clean_section = re.sub(r'<[^>]*>', '', section_text)
                
                # Create unique marker
                marker = f"__BILL_SECTION_{section_number}__"
                section_markers[marker] = "SECTION 1."  # Ensure standard format
                
                # Replace in the text with our marker
                start, end = match.span()
                text = text[:start] + marker + text[end:]
                
                self.logger.info("Found and preserved crucial SECTION 1. marker")
                break
        
        # Now identify and preserve remaining bill sections (SEC. 2. through SEC. 124.)
        # Re-run the pattern match since we modified the text
        bill_text_sections = list(bill_text_section_pattern.finditer(text))
        
        for match in bill_text_sections:
            section_number = match.group(1)
            section_text = match.group(0)
            
            # Skip SECTION 1 (we handled it already)
            if section_number == "1" and "SECTION" in section_text.upper():
                continue
                
            # Skip section numbers > 124 (for AB114)
            try:
                if int(section_number) > 124:
                    continue
            except ValueError:
                continue
                
            # Extract the exact text with HTML stripped
            clean_section = re.sub(r'<[^>]*>', '', section_text)
            
            # For numbers > 1, ensure SEC. N. format (standard for bill)
            if int(section_number) > 1:
                # Create a unique marker
                marker = f"__BILL_SECTION_{section_number}__"
                section_markers[marker] = f"SEC. {section_number}."  # Ensure standard format
                
                # Replace in the text with our marker
                start, end = match.span()
                text = text[:start] + marker + text[end:]
        
        self.logger.info(f"Found and preserved {len(section_markers)} bill section markers")
        
        # Now continue with general HTML cleaning
        
        # Remove strike/other markup for deleted text
        text = re.sub(r'<font color="#B30000"><strike>.*?</strike></font>', '', text, flags=re.DOTALL)
        text = re.sub(r'<strike>.*?</strike>', '', text, flags=re.DOTALL)
        text = re.sub(r'<del>.*?</del>', '', text, flags=re.DOTALL)
        text = re.sub(r'<s>.*?</s>', '', text, flags=re.DOTALL)
        text = re.sub(r'<span class="strikeout">.*?</span>', '', text, flags=re.DOTALL)
        text = re.sub(r'<span style="text-decoration: ?line-through">.*?</span>', '', text, flags=re.DOTALL)
        text = re.sub(r'<font color="(?:#B30000|#FF0000|red)">(.*?)</font>', '', text, flags=re.DOTALL)

        # "blue text" is new text, retain it by flattening the markup
        text = re.sub(r'<font color="blue" class="blue_text"><i>(.*?)</i></font>', r'\1', text, flags=re.DOTALL)
        text = re.sub(r'<font color="blue">(.*?)</font>', r'\1', text, flags=re.DOTALL)
        text = re.sub(r'<span class="new_text">(.*?)</span>', r'\1', text, flags=re.DOTALL)
        text = re.sub(r'<ins>(.*?)</ins>', r'\1', text, flags=re.DOTALL)
        text = re.sub(r'<i>(.*?)</i>', r'\1', text, flags=re.DOTALL)
        
        # Remove SPAN tags with class="hidden" which often contain hidden section markers
        text = re.sub(r'<span class="hidden">.*?</span>', '', text, flags=re.DOTALL)
        
        # Remove HTML comments
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
        
        # Handle specific HTML formatting for section headers before removing all tags
        # This makes sure sections are correctly identified even if they span multiple HTML tags
        section_header_html = re.compile(
            r'<[^>]*>(SECTION|SEC)\.?\s*<[^>]*>?\s*(\d+)\.?<[^>]*>?',
            re.IGNORECASE | re.DOTALL
        )
        
        # Replace section headers that were broken across tags
        for match in section_header_html.finditer(text):
            type_text = match.group(1)
            num_text = match.group(2)
            
            # Determine correct format
            if type_text.upper() == "SECTION" and num_text == "1":
                replacement = f"SECTION {num_text}."
            else:
                replacement = f"SEC. {num_text}."
                
            # Create marker
            marker = f"__BILL_SECTION_{num_text}__"
            if marker not in section_markers:
                section_markers[marker] = replacement
                
                # Replace the original text
                start, end = match.span()
                text = text[:start] + marker + text[end:]
        
        # Now remove all remaining HTML tags
        text = re.sub(r'<[^>]*>', ' ', text)
        
        # Fix HTML entities
        entities = {
            '&nbsp;': ' ',
            '&lt;': '<',
            '&gt;': '>',
            '&amp;': '&',
            '&quot;': '"',
            '&apos;': "'",
            '&#46;': '.',
            '&#39;': "'",
            '&#34;': '"',
        }
        for entity, replacement in entities.items():
            text = text.replace(entity, replacement)
        
        # Initial whitespace normalization
        text = re.sub(r'\s+', ' ', text)
        
        # Restore our preserved bill section markers
        # Do this in numeric order to ensure proper sequence
        if section_markers:
            # Fix the section marker extraction to handle potential empty strings
            def safe_extract_section_number(marker):
                try:
                    number_part = marker.split('_')[-1].rstrip('__')
                    if number_part:
                        return int(number_part)
                    return 999  # Default high number for invalid formats
                except (ValueError, IndexError):
                    return 999  # Default high number for invalid formats
                    
            sorted_markers = sorted(section_markers.keys(), key=safe_extract_section_number)
            
            for marker in sorted_markers:
                formatted_section = section_markers[marker]
                
                # Add newlines around section headers when replacing
                text = text.replace(marker, f"\n\n{formatted_section}\n")
        
        # Ensure other section references (not at boundaries) are properly formatted
        # Some bill text sections might still need normalization if they weren't captured earlier
        # Look for remaining SECTION or SEC occurrences that look like bill section headers
        # but only at appropriate places (beginning of line)
        bill_section_pattern = re.compile(
            r'(?:^|\n)\s*((?:SECTION|SEC)\.?)\s*(\d+)\.?',
            re.MULTILINE | re.IGNORECASE
        )
        
        # Function to standardize section header format
        def normalize_section_format(match):
            type_text = match.group(1).upper()
            num_text = match.group(2)
            
            # Follow standard bill section format
            if type_text == "SECTION" and num_text == "1":
                return f"\n\nSECTION {num_text}.\n"
            elif int(num_text) > 1:
                return f"\n\nSEC. {num_text}.\n"
            else:
                return f"\n\n{type_text} {num_text}.\n"
                
        # Normalize any remaining section headers
        text = bill_section_pattern.sub(normalize_section_format, text)
        
        # Final whitespace normalization
        text = re.sub(r' +', ' ', text)
        text = re.sub(r' +\n', '\n', text)
        text = re.sub(r'\n +', '\n', text)
        text = re.sub(r'\n\n+', '\n\n', text)
        
        # Look for bill text sections specifically with bill section format
        # First pass to find actual bill section patterns
        bill_section_candidates = re.findall(
            r'(?:^|\n)\s*((?:SECTION|SEC)\.?\s+\d+\.)',
            text,
            re.IGNORECASE | re.MULTILINE
        )
        
        self.logger.info(f"Final scan found {len(bill_section_candidates)} bill section candidates")
        
        # Check if we found the expected pattern for AB114
        section1_found = any(s for s in bill_section_candidates if "SECTION 1" in s.upper())
        sec2_found = any(s for s in bill_section_candidates if "SEC" in s.upper() and "2" in s)
        
        if section1_found and sec2_found:
            self.logger.info("Found both SECTION 1. and SEC. 2. patterns - good sign for proper detection")
        elif not section1_found:
            self.logger.warning("Could not find SECTION 1. pattern after cleaning - bill sections may be missing")
        
        self.logger.info("HTML markup cleaning completed")
        return text.strip()

    def _clean_html_markup(self, text: str) -> str:
        return self._clean_html_markup_enhanced(text)

    def _normalize_whitespace(self, text: str) -> str:
        text = re.sub(r'\r\n|\r', '\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' +', ' ', text)
        text = re.sub(r'\n +', '\n', text)
        text = re.sub(r'\s*([.,;:)])\s*', r'\1 ', text)
        text = re.sub(r'\s*([(])\s*', r' \1', text)
        return text.strip()

    def _normalize_section_breaks(self, text: str) -> str:
        text = re.sub(
            r'([^\n])(\b(?:SECTION|SEC)\.?\s+\d+\.)',
            r'\1\n\2',
            text,
            flags=re.IGNORECASE
        )
        text = re.sub(
            r'(?:^|\n)\s*((?:SECTION|SEC)\.?\s+\d+\.)',
            r'\n\n\1',
            text,
            flags=re.IGNORECASE
        )
        return text

    async def get_bill_history(self, bill_number: str, year: int) -> List[Dict[str, Any]]:
        """
        Retrieve the legislative history for a bill.
        """
        bill_number = bill_number.replace(" ", "").upper()
        session_str = self.get_session_year_range(year)
        url = f"{self.bill_url}?bill_id={session_str}0{bill_number}"

        self.logger.info(f"Fetching history for bill {bill_number} from session {year}-{year+1}")
        connector = TCPConnector(ssl=False, limit=1, force_close=True)

        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=self.timeout,
                headers=self.headers
            ) as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    html_content = await response.text()
                    return self._parse_bill_history(html_content)
        except Exception as e:
            self.logger.error(f"Error fetching bill history: {str(e)}")
            raise ValueError(f"Failed to retrieve history for bill {bill_number}: {str(e)}")

    def _parse_bill_history(self, html_content: str) -> List[Dict[str, Any]]:
        """
        Parse the bill history from the HTML content.
        """
        history = []
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            history_container = soup.find(id="bill_history") or soup.find(class_="bill-history")

            if not history_container:
                history_heading = soup.find(text=re.compile("Bill History"))
                if history_heading:
                    history_container = history_heading.find_next(['table', 'ul', 'ol', 'div'])

            if history_container:
                if history_container.name == 'table':
                    rows = history_container.find_all('tr')
                    for row in rows[1:]:
                        cells = row.find_all('td')
                        if len(cells) >= 2:
                            date = cells[0].get_text(strip=True)
                            action = cells[1].get_text(strip=True)
                            history.append({'date': date, 'action': action})
                elif history_container.name in ['ul', 'ol']:
                    items = history_container.find_all('li')
                    for item in items:
                        text = item.get_text(strip=True)
                        parts = re.split(r'[-–:]', text, 1)
                        if len(parts) >= 2:
                            date = parts[0].strip()
                            action = parts[1].strip()
                            history.append({'date': date, 'action': action})
                        else:
                            history.append({'action': text})
                elif history_container.name == 'div':
                    paragraphs = history_container.find_all('p')
                    for p in paragraphs:
                        text = p.get_text(strip=True)
                        if text:
                            date_match = re.search(r'^(\d{1,2}/\d{1,2}/\d{2,4}|\w+ \d{1,2}, \d{4})', text)
                            if date_match:
                                date = date_match.group(1)
                                action = text[len(date):].strip('- :')
                                history.append({'date': date, 'action': action})
                            else:
                                history.append({'action': text})

            return history
        except Exception as e:
            self.logger.warning(f"Error parsing bill history: {str(e)}")
            return history
