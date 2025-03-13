"""
BillScraper module for fetching and basic preparation of bill text from leginfo.legislature.ca.gov
Focused on reliable retrieval with minimal processing.
"""
import aiohttp
import logging
import asyncio
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
from datetime import datetime
from aiohttp import ClientTimeout, TCPConnector
from aiohttp.client_exceptions import ClientError, ClientResponseError

class BillScraper:
    """
    A simplified scraper for California trailer bills from leginfo.legislature.ca.gov
    that focuses on reliable fetching and minimal HTML preprocessing.
    """

    def __init__(self, max_retries: int = 3, timeout: int = 30):
        self.logger = logging.getLogger(__name__)
        self.base_url = "https://leginfo.legislature.ca.gov"
        self.bill_url = f"{self.base_url}/faces/billNavClient.xhtml"
        self.max_retries = max_retries
        self.timeout = ClientTimeout(total=timeout)

        # Standard headers for requests
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

    def get_session_year_range(self, year) -> str:
        """
        Calculate the legislative session year range based on the provided year.
        Legislative sessions in California run for 2 years, starting on odd years.

        Args:
            year: The year (as integer, string, or range like "2023-2024")

        Returns:
            Session year range string (e.g., "20232024")
        """
        # Handle different input formats
        if isinstance(year, str):
            # If it's already in "YYYY-YYYY" format, extract the first year
            if "-" in year:
                try:
                    first_year = int(year.split("-")[0].strip())
                    return f"{first_year}{first_year + 1}"
                except (ValueError, IndexError):
                    self.logger.warning(f"Could not parse year range: {year}. Using current year.")
                    import datetime
                    current_year = datetime.datetime.now().year
                    session_start = current_year if (current_year % 2 == 1) else (current_year - 1)
                    return f"{session_start}{session_start + 1}"
            else:
                # Try to convert simple string to int
                try:
                    year = int(year)
                except ValueError:
                    self.logger.warning(f"Invalid year format: {year}. Using current year.")
                    import datetime
                    current_year = datetime.datetime.now().year
                    session_start = current_year if (current_year % 2 == 1) else (current_year - 1)
                    return f"{session_start}{session_start + 1}"

        # Now year should be an integer
        session_start = year if (year % 2 == 1) else (year - 1)
        return f"{session_start}{session_start + 1}"

    async def get_bill_text(self, bill_number: str, year) -> Dict[str, Any]:
        """
        Retrieves the full text for the specified bill with retry logic.

        Args:
            bill_number: The bill identifier (e.g., "AB123", "SB456")
            year: The year of the legislative session (as integer, string, or range like "2023-2024")

        Returns:
            Dictionary containing bill text and metadata
        """
        bill_number = bill_number.replace(" ", "").upper()
        session_str = self.get_session_year_range(year)
        url = f"{self.bill_url}?bill_id={session_str}0{bill_number}"

        # For logging, handle both string and integer year formats
        if isinstance(year, str) and "-" in year:
            # If it's already in session format like "2023-2024", use it directly
            display_year = year
        else:
            # Otherwise convert to integer and create a range
            try:
                year_int = int(year) if isinstance(year, str) else year
                display_year = f"{year_int}-{year_int+1}"
            except (ValueError, TypeError):
                display_year = str(year)  # Fallback for any other format

        self.logger.info(f"Fetching bill {bill_number} from session {display_year}")
        self.logger.info(f"Request URL: {url}")

        for attempt in range(1, self.max_retries + 1):
            try:
                return await self._fetch_bill(url, bill_number, year, attempt)
            except ClientResponseError as e:
                if e.status == 404:
                    self.logger.error(f"Bill not found: {bill_number} (404 response)")
                    raise ValueError(f"Bill {bill_number} from session {display_year} not found")
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

                # Parse the bill content
                result = self._parse_bill_page(html_content)

                if not result or not result.get('full_text'):
                    self.logger.warning("Failed to extract bill text from HTML")
                    raise ValueError("Could not extract bill text from HTML")

                self.logger.info(f"Successfully parsed bill text of length {len(result.get('full_text', ''))}")

                # Add metadata
                result.update(self._extract_bill_metadata(html_content))
                return result

    def _parse_bill_page(self, html_content: str) -> Dict[str, Any]:
        """
        Parse the HTML content from the Legislature site to extract the bill text.
        """
        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Remove scripts and styles
            for elem in soup(["script", "style"]):
                elem.decompose()

            # Try to find the main content
            bill_content = soup.find(id="bill_all") or soup.find(class_="bill-content")

            if not bill_content:
                # If we couldn't find the standard containers, look for other possibilities
                bill_content = soup.find(id="content_main") or soup.find(class_="centercolumn")

            if not bill_content:
                raise ValueError("Could not find bill content container in HTML")

            # Get bill content as HTML and as text
            html_content = str(bill_content)

            # Clean the text and normalize whitespace
            full_text = self._clean_html_markup(html_content)

            # Check if we have any content
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

    def _clean_html_markup(self, html_text: str) -> str:
        """
        Basic HTML cleanup to extract text content. More advanced cleaning
        for amended bills will be added later.
        """
        # Create soup for better text extraction
        soup = BeautifulSoup(html_text, "html.parser")

        # Get text content
        text = soup.get_text(separator=' ', strip=True)

        # Normalize whitespace
        text = ' '.join(text.split())

        return text

    def _extract_bill_metadata(self, html_content: str) -> Dict[str, Any]:
        """
        Extract basic metadata about the bill from the HTML.
        """
        metadata = {}
        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Try to extract bill number
            bill_num = soup.find(id="bill_num_title_chap")
            if bill_num:
                metadata['bill_number'] = bill_num.get_text(strip=True)

            # Try to extract chapter number
            chap_num = soup.find(id="chap_num_title_chap")
            if chap_num:
                metadata['chapter_number'] = chap_num.get_text(strip=True)

            # Try to extract title
            title_elem = soup.find(id="title")
            if title_elem:
                metadata['title'] = title_elem.get_text(strip=True)

            # Extract approval date if available
            approved_date = None
            approval_text = soup.find(string=lambda t: "Approved" in str(t) and "Governor" in str(t))
            if approval_text:
                # Try to find date near approval text
                date_text = approval_text.findNext(string=lambda t: any(month in str(t) for month in 
                                                   ['January', 'February', 'March', 'April', 'May', 'June', 
                                                    'July', 'August', 'September', 'October', 'November', 'December']))
                if date_text:
                    metadata['date_approved'] = date_text.strip()

            return metadata
        except Exception as e:
            self.logger.warning(f"Error extracting bill metadata: {str(e)}")
            return metadata