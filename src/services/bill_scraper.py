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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9," \
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
                        self.logger.debug(f"First 500 chars of response: {html_content[:500]}")

                        if not html_content:
                            raise ValueError("Empty response received")

                        self.logger.info(f"Response content length: {len(html_content)}")
                        self.logger.info(f"Contains 'Bill Text' tag: {'Bill Text' in html_content}")
                        self.logger.info(f"Contains 'Content not found': "
                                         f"{'Content not found' in html_content}")

                        result = self._parse_bill_page(html_content)
                        self.logger.info(f"Successfully parsed bill text of length "
                                         f"{len(result.get('full_text', ''))}")
                        return result

                    self.logger.error(f"Failed with status {response.status}")
                    response.raise_for_status()

        except Exception as e:
            self.logger.error(f"Error fetching bill: {str(e)}")
            raise

    def _parse_bill_page(self, html_content: str) -> Dict[str, Any]:
        """
        Parse the HTML content from the Legislature site to extract the main text.
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

            full_text = content_div.get_text("\n", strip=True)
            full_text = re.sub(r'\n\s*\n', '\n\n', full_text)
            full_text = re.sub(r' +', ' ', full_text)

            if not full_text or len(full_text.strip()) < 100:
                raise ValueError("Retrieved bill content appears to be empty or invalid")

            return {
                'full_text': full_text,
                'html': str(content_div)
            }

        except Exception as e:
            self.logger.error(f"Error parsing bill page: {str(e)}")
            raise
