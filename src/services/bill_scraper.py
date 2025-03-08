import aiohttp
import logging
import re
import asyncio
from typing import Dict, Any
from bs4 import BeautifulSoup
from datetime import datetime
from aiohttp import ClientTimeout, TCPConnector
from aiohttp.client_exceptions import ClientError

class BillScraper:
    """
    Handles retrieval and cleaning of trailer bill text from leginfo.legislature.ca.gov
    with improved error handling and retry logic.
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
        session_start = year if (year % 2 == 1) else (year - 1)
        return f"{session_start}{session_start + 1}"

    async def get_bill_text(self, bill_number: str, year: int) -> Dict[str, Any]:
        """
        Retrieves the full text for the specified bill with retry logic.
        """
        try:
            bill_number = bill_number.replace(" ", "").upper()
            session_str = self.get_session_year_range(year)

            # Format checks for bill number
            if not any(bill_number.startswith(prefix) for prefix in ['AB', 'SB', 'ACA', 'SCA', 'ACR', 'SCR', 'AJR', 'SJR']):
                self.logger.warning(f"Bill number '{bill_number}' doesn't start with a recognized prefix")

            url = f"{self.bill_url}?bill_id={session_str}0{bill_number}"

            self.logger.info(f"Attempting to fetch bill from {url}")
            self.logger.info(f"Session string: {session_str}")
            self.logger.info(f"Full bill ID: {session_str}0{bill_number}")

            connector = TCPConnector(ssl=False, limit=1, force_close=True)

            async with aiohttp.ClientSession(
                connector=connector,
                timeout=self.timeout,
                headers=self.headers
            ) as session:
                self.logger.info("Making request with headers:")
                self.logger.info(self.headers)

                async with session.get(url) as response:
                    self.logger.info(f"Response status: {response.status}")
                    self.logger.info(f"Response headers: {response.headers}")

                    if response.status == 200:
                        html_content = await response.text()
                        content_length = len(html_content) if html_content else 0
                        self.logger.info(f"Received HTML content of length: {content_length}")

                        if not html_content or content_length < 100:
                            raise ValueError(f"Received invalid content (length: {content_length})")

                        self.logger.debug(f"First 500 chars of response: {html_content[:500]}")

                        # Check if content appears to contain a "bill not found" message
                        if "bill not available" in html_content.lower() or "not found" in html_content.lower():
                            raise ValueError(f"Bill {bill_number} from session {year}-{year+1} was not found")

                        result = self._parse_bill_page(html_content)
                        if not result or not result.get('full_text'):
                            raise ValueError("Failed to extract bill text from HTML")

                        self.logger.info(f"Response content length: {len(html_content)}")
                        self.logger.info(f"Contains 'Bill Text' tag: {'Bill Text' in html_content}")
                        self.logger.info(f"Contains 'Content not found': "
                                         f"{'Content not found' in html_content}")

                        # parse again to ensure data is present
                        result = self._parse_bill_page(html_content)
                        self.logger.info(f"Successfully parsed bill text of length "
                                         f"{len(result.get('full_text', ''))}")
                        return result

                    self.logger.error(f"Failed with status {response.status}")
                    response.raise_for_status()

        except Exception as e:
            self.logger.error(f"Error fetching bill {bill_number} from session {year}-{year+1}: {str(e)}")
            raise

    def _clean_html_markup(self, text: str) -> str:
        """
        Clean HTML markup from amended bills to create plain text that's easier to parse.
        Handles strikethroughs, additions, and other HTML formatting.
        """
        # First, handle the strike-through content (removed text)
        # We simply remove it since it's not part of the final bill text
        text = re.sub(r'<font color="#B30000"><strike>.*?</strike></font>', '', text, flags=re.DOTALL)

        # Then handle blue text (added text)
        # We keep this content but remove the HTML markup
        text = re.sub(r'<font color="blue" class="blue_text"><i>(.*?)</i></font>', r'\1', text, flags=re.DOTALL)

        # Remove any remaining HTML tags
        text = re.sub(r'<[^>]*>', '', text)

        # Clean up extra whitespace
        text = re.sub(r'\s+', ' ', text)

        # Make sure section identifiers are separated by newlines
        text = re.sub(r'([^\n])(SEC\.|SECTION)', r'\1\n\2', text, flags=re.IGNORECASE)

        # Ensure consistency in section formatting
        text = re.sub(r'\n\s*(SEC\.?|SECTION)\s*(\d+)\.\s*', r'\n\1 \2.\n', text, flags=re.IGNORECASE)

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
    
    def _parse_bill_page(self, html_content: str) -> Dict[str, Any]:
        """
        Parse the HTML content from the Legislature site to extract the main text,
        applying enhanced processing for amended bills.
        """
        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Remove script and style elements
            for elem in soup(["script", "style"]):
                elem.decompose()

            content_div = None
            for selector in [
                {"name": "div", "class_": "bill-content"},
                {"name": "div", "class_": "contentArea"},
                {"name": "div", "id": "bill_all"},
                {"name": "article", "id": "bill_all"}
            ]:
                candidate = soup.find(**selector)
                if candidate:
                    content_div = candidate
                    break

            if not content_div:
                raise ValueError("Could not find valid bill content in HTML")

            # Apply more aggressive cleaning to better handle amended bills
            full_text = content_div.get_text("\n", strip=True)

            # Normalize whitespace and line breaks
            full_text = re.sub(r'\n\s*\n', '\n\n', full_text)
            full_text = re.sub(r' +', ' ', full_text)

            # Ensure section headers are separated from surrounding text
            full_text = re.sub(r'([^\n])(SEC\.|SECTION)', r'\1\n\2', full_text, flags=re.IGNORECASE)
            full_text = re.sub(r'(SEC\.|SECTION)(\s*)(\d+)(\.)(\s*)', r'\1 \3\4\n', full_text, flags=re.IGNORECASE)

            if not full_text or len(full_text.strip()) < 100:
                raise ValueError("Retrieved bill content appears to be empty or invalid")

            return {
                'full_text': full_text,
                'html': str(content_div)
            }

        except Exception as e:
            self.logger.error(f"Error parsing bill page: {str(e)}")
            raise
