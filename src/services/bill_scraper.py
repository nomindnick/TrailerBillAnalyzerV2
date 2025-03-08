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

        Args:
            year: The year to calculate the session for

        Returns:
            A string representing the session (e.g. "20232024")
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

        Raises:
            ValueError: If the bill cannot be found or content is invalid
            ClientError: For network-related errors
        """
        bill_number = bill_number.replace(" ", "").upper()
        session_str = self.get_session_year_range(year)
        url = f"{self.bill_url}?bill_id={session_str}0{bill_number}"

        self.logger.info(f"Attempting to fetch bill {bill_number} from session {year}-{year+1}")
        self.logger.info(f"Request URL: {url}")

        # Implement retry logic
        for attempt in range(1, self.max_retries + 1):
            try:
                return await self._fetch_bill(url, bill_number, year, attempt)
            except ClientResponseError as e:
                if e.status == 404:
                    self.logger.error(f"Bill not found: {bill_number} (404 response)")
                    raise ValueError(f"Bill {bill_number} from session {year}-{year+1} not found")
                elif attempt < self.max_retries:
                    wait_time = 2 ** attempt  # Exponential backoff
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

        # This should never be reached due to the exception handling above
        raise ValueError(f"Failed to fetch bill {bill_number} after {self.max_retries} attempts")

    async def _fetch_bill(self, url: str, bill_number: str, year: int, attempt: int) -> Dict[str, Any]:
        """
        Helper method to fetch and process a bill from the legislature website.

        Args:
            url: The full URL to fetch
            bill_number: The bill identifier
            year: The year of the legislative session
            attempt: The current retry attempt number

        Returns:
            Dictionary containing bill text and metadata

        Raises:
            ValueError: If the bill content is invalid
            ClientError: For network-related errors
        """
        self.logger.info(f"Fetching bill {bill_number}, attempt {attempt}/{self.max_retries}")

        # Use a fresh connector for each request to avoid connection pool issues
        connector = TCPConnector(ssl=False, limit=1, force_close=True)

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=self.timeout,
            headers=self.headers
        ) as session:
            async with session.get(url) as response:
                self.logger.info(f"Response status: {response.status}")

                # Raise for status to trigger retry logic
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

                # Parse the bill page
                result = self._parse_bill_page(html_content)

                if not result or not result.get('full_text'):
                    # Try an alternative parsing approach if the initial one fails
                    self.logger.warning("Initial parsing failed, trying alternative approach")
                    result = self._parse_bill_page_alternative(html_content)

                    if not result or not result.get('full_text'):
                        raise ValueError("Failed to extract bill text from HTML")

                self.logger.info(f"Successfully parsed bill text of length {len(result.get('full_text', ''))}")

                # Extract additional metadata if available
                result.update(self._extract_bill_metadata(html_content))

                return result

    def _parse_bill_page(self, html_content: str) -> Dict[str, Any]:
        """
        Parse the HTML content from the Legislature site to extract the main text,
        applying enhanced processing for amended bills.

        Args:
            html_content: The HTML content to parse

        Returns:
            Dictionary with full_text and html fields

        Raises:
            ValueError: If no valid bill content could be found
        """
        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Remove script and style elements
            for elem in soup(["script", "style"]):
                elem.decompose()

            # Try multiple selectors to find the bill content
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

            # Apply more aggressive cleaning to better handle amended bills
            # First, get the full HTML of the content div
            html_content = str(content_div)

            # Then get the plain text with proper spacing
            full_text = content_div.get_text("\n", strip=True)

            # Apply enhanced HTML cleaning for amended bills
            full_text = self._clean_html_markup_enhanced(html_content)

            # Normalize whitespace and line breaks
            full_text = self._normalize_whitespace(full_text)

            # Handle amendments (strikethrough and additions)
            full_text = self._normalize_section_breaks(full_text)

            if not full_text or len(full_text.strip()) < 100:
                raise ValueError("Retrieved bill content appears to be empty or invalid")

            return {
                'full_text': full_text,
                'html': html_content,
                'has_amendments': '<strike>' in html_content or '<font color="blue"' in html_content
            }

        except Exception as e:
            self.logger.error(f"Error parsing bill page: {str(e)}")
            raise

    def _parse_bill_page_alternative(self, html_content: str) -> Dict[str, Any]:
        """
        Alternative parsing method for pages with unusual structure.
        Used as a fallback when the standard method fails.

        Args:
            html_content: The HTML content to parse

        Returns:
            Dictionary with full_text and html fields

        Raises:
            ValueError: If no valid bill content could be found
        """
        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Try a broader approach - look for any large text block that might contain bill text
            main_content = soup.find(id="main-content") or soup.find(id="content-area") or soup.find("main")

            if main_content:
                # Extract all paragraphs and text divisions
                text_elements = main_content.find_all(['p', 'div', 'article', 'section'])

                # Collect text from elements that look like they might contain bill text
                bill_text_parts = []
                for elem in text_elements:
                    text = elem.get_text(strip=True)
                    # Skip very short elements and navigation elements
                    if len(text) > 200 or ("section" in text.lower() and "chapter" in text.lower()):
                        bill_text_parts.append(elem.get_text("\n", strip=True))

                if bill_text_parts:
                    combined_text = "\n\n".join(bill_text_parts)
                    # Clean and normalize the text using enhanced cleaning
                    cleaned_text = self._clean_html_markup_enhanced(combined_text)
                    cleaned_text = self._normalize_whitespace(cleaned_text)
                    cleaned_text = self._normalize_section_breaks(cleaned_text)

                    return {
                        'full_text': cleaned_text,
                        'html': str(main_content),
                        'has_amendments': '<strike>' in str(main_content) or '<font color="blue"' in str(main_content),
                        'parse_method': 'alternative'
                    }

            # If we can't find a structured container, try a more aggressive approach
            all_text = soup.get_text("\n", strip=True)

            # Look for bill sections within all the text
            if all_text and len(all_text) > 1000:
                # Check if it contains key bill indicators
                markers = ["CHAPTER", "SECTION", "SEC.", "Legislative Counsel", "do enact as follows"]
                if any(marker in all_text for marker in markers):
                    # Apply enhanced cleaning for heavily formatted/amended bills
                    cleaned_text = self._clean_html_markup_enhanced(html_content)
                    cleaned_text = self._normalize_whitespace(cleaned_text)
                    cleaned_text = self._normalize_section_breaks(cleaned_text)

                    return {
                        'full_text': cleaned_text,
                        'html': html_content,  # Use the full HTML as we couldn't isolate a specific div
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

        Args:
            html_content: The HTML content to parse

        Returns:
            Dictionary containing bill metadata such as status, authors, etc.
        """
        metadata = {}
        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Try to extract bill status
            status_elem = soup.find(class_="bill-status") or soup.find(text=re.compile("Current Bill Status"))
            if status_elem:
                status_text = status_elem.get_text(strip=True) if hasattr(status_elem, 'get_text') else str(status_elem)
                metadata['status'] = status_text

            # Try to extract authors
            author_elem = soup.find(text=re.compile("Author:")) or soup.find(text=re.compile("Principal coauthors:"))
            if author_elem and author_elem.find_next():
                author_text = author_elem.find_next().get_text(strip=True)
                metadata['authors'] = author_text

            # Extract last action date if available
            action_date = soup.find(text=re.compile("Last Action:"))
            if action_date and action_date.find_next():
                action_text = action_date.find_next().get_text(strip=True)
                metadata['last_action'] = action_text

            # Extract voting info if available
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
            return metadata  # Return whatever we could extract

    def _clean_html_markup_enhanced(self, text):
        """
        Enhanced method to clean HTML markup from amended bills to create plain text that's easier to parse.
        Handles strikethroughs, additions, and other HTML formatting with special attention to section headers.

        Args:
            text: The HTML text to clean

        Returns:
            Plain text with HTML markup removed but sections preserved
        """
        # First, identify and protect section headers
        section_headers = re.findall(r'(?:<[^>]*>)*(?:SECTION|SEC)\.?\s+\d+\.(?:<[^>]*>)*', text, re.IGNORECASE)
        protected_text = text

        section_header_map = []
        for i, header in enumerate(section_headers):
            # Create a unique marker for this section header
            marker = f"__SECTION_MARKER_{i}__"
            # Clean the header text (remove HTML but keep the section header text)
            clean_header = re.sub(r'<[^>]*>', '', header)
            # Replace the header with the marker
            protected_text = protected_text.replace(header, marker)
            # Store the mapping for later restoration
            section_header_map.append((marker, clean_header))

        # Handle strikethroughs - remove the content
        protected_text = re.sub(r'<font color="#B30000"><strike>.*?</strike></font>', '', protected_text, flags=re.DOTALL)
        protected_text = re.sub(r'<strike>.*?</strike>', '', protected_text, flags=re.DOTALL)
        protected_text = re.sub(r'<del>.*?</del>', '', protected_text, flags=re.DOTALL)
        protected_text = re.sub(r'<s>.*?</s>', '', protected_text, flags=re.DOTALL)

        # Handle red text that might indicate deletions
        protected_text = re.sub(r'<font color="(?:#B30000|#FF0000|red)">(.*?)</font>', '', protected_text, flags=re.DOTALL)

        # Handle blue text (added text) - keep content but remove markup
        protected_text = re.sub(r'<font color="blue" class="blue_text"><i>(.*?)</i></font>', r'\1', protected_text, flags=re.DOTALL)
        protected_text = re.sub(r'<font color="blue">(.*?)</font>', r'\1', protected_text, flags=re.DOTALL)
        protected_text = re.sub(r'<span class="new_text">(.*?)</span>', r'\1', protected_text, flags=re.DOTALL)
        protected_text = re.sub(r'<ins>(.*?)</ins>', r'\1', protected_text, flags=re.DOTALL)
        protected_text = re.sub(r'<i>(.*?)</i>', r'\1', protected_text, flags=re.DOTALL)

        # Remove any remaining HTML tags
        protected_text = re.sub(r'<[^>]*>', ' ', protected_text)

        # Clean up extra whitespace
        protected_text = re.sub(r'\s+', ' ', protected_text)

        # Restore the protected section headers
        cleaned_text = protected_text
        for marker, header in section_header_map:
            cleaned_text = cleaned_text.replace(marker, header)

        # Make sure section identifiers are separated by newlines
        cleaned_text = re.sub(r'([^\n])(SEC\.|SECTION)', r'\1\n\2', cleaned_text, flags=re.IGNORECASE)

        # Ensure consistency in section formatting
        cleaned_text = re.sub(r'\n\s*(SEC\.?|SECTION)\s*(\d+)\.\s*', r'\n\1 \2.\n', cleaned_text, flags=re.IGNORECASE)

        # Normalize whitespace
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
        cleaned_text = re.sub(r' +\n', '\n', cleaned_text)
        cleaned_text = re.sub(r'\n +', '\n', cleaned_text)
        cleaned_text = re.sub(r'\n\n+', '\n\n', cleaned_text)

        return cleaned_text.strip()

    def _clean_html_markup(self, text: str) -> str:
        """
        Clean HTML markup from amended bills to create plain text that's easier to parse.
        Handles strikethroughs, additions, and other HTML formatting.

        This method is now a wrapper for the enhanced version.
        """
        return self._clean_html_markup_enhanced(text)

    def _normalize_whitespace(self, text: str) -> str:
        """
        Normalize whitespace and line breaks in the text.

        Args:
            text: The text to normalize

        Returns:
            Normalized text with consistent whitespace
        """
        # Replace various types of line breaks with \n
        text = re.sub(r'\r\n|\r', '\n', text)

        # Collapse multiple line breaks into at most two
        text = re.sub(r'\n{3,}', '\n\n', text)

        # Collapse multiple spaces into one
        text = re.sub(r' +', ' ', text)

        # Remove space at start of lines
        text = re.sub(r'\n +', '\n', text)

        # Normalize whitespace around delimiters
        text = re.sub(r'\s*([.,;:)])\s*', r'\1 ', text)
        text = re.sub(r'\s*([(])\s*', r' \1', text)

        return text.strip()

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
            r'([^\n])((?:SECTION|SEC)\.?\s+\d+(?:\.\d+)?\.)',
            r'\1\n\2',
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

        # Fix decimal points in section numbers (e.g. "Section 12 . 5" -> "Section 12.5")
        normalized = re.sub(
            r'(Section\s+\d+)\s+\.\s+(\d+)',
            r'\1.\2',
            normalized,
            flags=re.IGNORECASE
        )

        return normalized

    async def get_bill_history(self, bill_number: str, year: int) -> List[Dict[str, Any]]:
        """
        Retrieve the legislative history for a bill.

        Args:
            bill_number: The bill identifier (e.g., "AB123", "SB456")
            year: The year of the legislative session

        Returns:
            List of actions in the bill's history

        Raises:
            ValueError: If the bill history cannot be found
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

        Args:
            html_content: The HTML content to parse

        Returns:
            List of actions in the bill's history
        """
        history = []
        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Look for the history table or list
            history_container = soup.find(id="bill_history") or soup.find(class_="bill-history")
            if not history_container:
                # Try to find by heading
                history_heading = soup.find(text=re.compile("Bill History"))
                if history_heading:
                    # Look for the closest table or list
                    history_container = history_heading.find_next(['table', 'ul', 'ol', 'div'])

            if history_container:
                # For table format
                if history_container.name == 'table':
                    rows = history_container.find_all('tr')
                    for row in rows[1:]:  # Skip header row
                        cells = row.find_all('td')
                        if len(cells) >= 2:
                            date = cells[0].get_text(strip=True)
                            action = cells[1].get_text(strip=True)
                            history.append({
                                'date': date,
                                'action': action
                            })
                # For list format
                elif history_container.name in ['ul', 'ol']:
                    items = history_container.find_all('li')
                    for item in items:
                        text = item.get_text(strip=True)
                        # Try to split date and action
                        parts = re.split(r'[-–:]', text, 1)
                        if len(parts) >= 2:
                            date = parts[0].strip()
                            action = parts[1].strip()
                            history.append({
                                'date': date,
                                'action': action
                            })
                        else:
                            history.append({
                                'action': text
                            })
                # For div format with paragraphs
                elif history_container.name == 'div':
                    paragraphs = history_container.find_all('p')
                    for p in paragraphs:
                        text = p.get_text(strip=True)
                        if text:
                            # Try to extract date and action
                            date_match = re.search(r'^(\d{1,2}/\d{1,2}/\d{2,4}|\w+ \d{1,2}, \d{4})', text)
                            if date_match:
                                date = date_match.group(1)
                                action = text[len(date):].strip('- :')
                                history.append({
                                    'date': date,
                                    'action': action
                                })
                            else:
                                history.append({
                                    'action': text
                                })

            return history

        except Exception as e:
            self.logger.warning(f"Error parsing bill history: {str(e)}")
            return history  # Return whatever we could extract