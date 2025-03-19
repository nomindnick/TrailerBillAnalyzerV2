"""
BillScraper module for fetching and basic preparation of bill text from leginfo.legislature.ca.gov
Focused on reliable retrieval with minimal processing.
"""
import aiohttp
import logging
import asyncio
import re
import os
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
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
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
                    self.logger.warning(
                        f"Request failed with status {e.status}, retrying in {wait_time}s "
                        f"(attempt {attempt}/{self.max_retries})"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    self.logger.error(
                        f"Failed to fetch bill after {self.max_retries} attempts: {str(e)}"
                    )
                    raise
            except Exception as e:
                if attempt < self.max_retries:
                    wait_time = 2 ** attempt
                    self.logger.warning(
                        f"Error fetching bill: {str(e)}, retrying in {wait_time}s "
                        f"(attempt {attempt}/{self.max_retries})"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    self.logger.error(
                        f"Failed to fetch bill after {self.max_retries} attempts: {str(e)}"
                    )
                    raise

        raise ValueError(
            f"Failed to fetch bill {bill_number} after {self.max_retries} attempts"
        )

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
                    raise ValueError(
                        f"Bill {bill_number} from session {year}-{year+1} was not found"
                    )

                # Parse the bill content
                result = self._parse_bill_page(html_content)

                if not result or not result.get('full_text'):
                    self.logger.warning("Failed to extract bill text from HTML")
                    raise ValueError("Could not extract bill text from HTML")

                self.logger.info(
                    f"Successfully parsed bill text of length {len(result.get('full_text', ''))}"
                )

                # Add metadata
                result.update(self._extract_bill_metadata(html_content))
                return result

    def _parse_bill_page(self, html_content: str) -> Dict[str, Any]:
        """
        Parse the HTML content from the Legislature site to extract the bill text.
        Now with enhanced handling for amended bills (with strikethrough and added text).
        """
        try:
            # Create debug directory if needed
            output_dir = "debug_output"
            os.makedirs(output_dir, exist_ok=True)

            # Save original HTML for debugging
            with open(os.path.join(output_dir, "original_bill.html"), "w", encoding="utf-8") as f:
                f.write(html_content)

            self.logger.info("Starting bill parsing")

            # Pre-clean HTML to handle malformed attributes and tags
            cleaned_html = self._pre_clean_html(html_content)

            # Save pre-cleaned HTML for debugging
            with open(os.path.join(output_dir, "pre_cleaned_bill.html"), "w", encoding="utf-8") as f:
                f.write(cleaned_html)

            # Create soup with cleaned HTML
            soup = BeautifulSoup(cleaned_html, "html.parser")

            # Remove scripts and styles that could interfere with parsing
            for tag_name in ["script", "style", "meta", "link"]:
                for tag in soup.find_all(tag_name):
                    tag.decompose()

            # Try multiple potential content containers in order of specificity
            bill_content = None
            container_id = None

            # List of possible container selectors in order of preference
            container_selectors = [
                {"type": "id", "value": "bill_all"},
                {"type": "class", "value": "bill-content"},
                {"type": "id", "value": "billtext"},
                {"type": "id", "value": "bill"},
                {"type": "id", "value": "content_main"},
                {"type": "id", "value": "centercolumn"},
                {"type": "class", "value": "centercolumn"},
                {"type": "class", "value": "centercolumntwo"},
                {"type": "tag", "value": "pre"}, # Last resort, look for preformatted text
            ]

            # Try each container selector
            for selector in container_selectors:
                if selector["type"] == "id":
                    bill_content = soup.find(id=selector["value"])
                elif selector["type"] == "class":
                    bill_content = soup.find(class_=selector["value"])
                elif selector["type"] == "tag":
                    bill_content = soup.find(selector["value"])

                if bill_content:
                    container_id = selector["value"]
                    self.logger.info(f"Found bill content in container with {selector['type']}={selector['value']}")
                    break

            # If we still don't have a container, look for the bill text more directly
            if not bill_content:
                self.logger.warning("Could not find bill content using standard containers")

                # Try to find the enactment clause and get content that way
                enactment_text = soup.find(string=lambda text: "The people of the State of California do enact as follows" in str(text))
                if enactment_text:
                    self.logger.info("Found enactment clause, extracting bill text from there")
                    parent = enactment_text.find_parent()
                    if parent:
                        bill_content = parent
                        container_id = "enactment_parent"

                # Last resort - use the entire body
                if not bill_content:
                    self.logger.warning("Using body as fallback container")
                    bill_content = soup.body
                    container_id = "body"

            if not bill_content:
                raise ValueError("Could not find any container with bill content")

            self.logger.info(f"Using container '{container_id}' for bill text extraction")

            # Detect if this is an amended bill
            strikethrough_tags = bill_content.find_all('strike')
            blue_text_tags = bill_content.find_all('font', attrs={'color': 'blue'})
            highlight_tags = bill_content.find_all('span', style=lambda s: s and 'background-color:yellow' in s)

            is_amended = bool(strikethrough_tags or blue_text_tags or highlight_tags)

            if is_amended:
                self.logger.info(f"Detected amended bill: {len(strikethrough_tags)} strikethrough sections, "
                                f"{len(blue_text_tags)} blue text sections, {len(highlight_tags)} highlighted sections")

            # Get bill content as HTML
            html_content = str(bill_content)

            # If this is an amended bill, clean the markup to preserve both added and deleted text
            if is_amended:
                html_content = self._clean_amended_bill_html(html_content)

            # Get clean text without HTML tags
            text_content = self._extract_text_with_amendments(html_content)

            # Check if we have any content
            if not text_content or len(text_content.strip()) < 100:
                self.logger.warning(f"Extracted text content is suspiciously short: {len(text_content)} chars")

                # Emergency fallback - try to get any text
                text_content = soup.get_text(separator='\n', strip=True)
                if not text_content or len(text_content.strip()) < 100:
                    raise ValueError("Retrieved bill content appears to be empty or invalid")

            self.logger.info(f"Successfully extracted bill text: {len(text_content)} characters")

            # Save extracted text for debugging
            with open(os.path.join(output_dir, "extracted_bill_text.txt"), "w", encoding="utf-8") as f:
                f.write(text_content)

            return {
                'full_text': text_content,
                'html': html_content,
                'has_amendments': is_amended,
                'container_used': container_id
            }

        except Exception as e:
            self.logger.error(f"Error parsing bill page: {str(e)}")
            raise

    def _pre_clean_html(self, html_content: str) -> str:
        """
        Pre-clean HTML to fix malformed tags and attributes that would confuse BeautifulSoup.
        This addresses issues like HTML tags embedded within ID attributes.
        """
        # First pass - fix malformed ID attributes containing HTML tags
        # Example: <div id="<b><span style='background-color:yellow'>bill"</span></b>>

        # Fix malformed IDs with embedded tags
        pattern = r'id\s*=\s*"(.*?)"'

        def clean_id_attr(match):
            id_content = match.group(1)
            # If the ID contains HTML tags, extract just the text
            if '<' in id_content or '>' in id_content:
                # Extract just the text without tags using regex
                clean_id = re.sub(r'<.*?>', '', id_content)
                return f'id="{clean_id}"'
            return match.group(0)

        html_content = re.sub(pattern, clean_id_attr, html_content)

        # Fix unclosed tags
        html_content = re.sub(r'<([a-zA-Z]+)([^>]*?)(?<!/)>(?!</\1>)', r'<\1\2></\1>', html_content)

        # Fix missing quotes in attributes
        html_content = re.sub(r'(\w+)=([^\s"][^\s>]*)', r'\1="\2"', html_content)

        # Normalize whitespace in tags
        html_content = re.sub(r'<\s*(\w+)', r'<\1', html_content)
        html_content = re.sub(r'(\w+)\s*>', r'\1>', html_content)

        # Fix line breaks within attributes
        html_content = re.sub(r'="([^"]*?)\n([^"]*?)"', r'="\1 \2"', html_content)

        return html_content

    def _extract_text_with_amendments(self, html_content: str) -> str:
        """
        Extract text from HTML with special handling for amendments.
        This preserves added text and removes strikethrough text.
        """
        soup = BeautifulSoup(html_content, "html.parser")

        # Remove strikethrough text
        for strike in soup.find_all('strike'):
            # Replace with a marker for easier debugging
            strike.replace_with('[DELETED TEXT]')

        # Mark added text for better visibility
        for blue in soup.find_all('font', attrs={'color': 'blue'}):
            # Add markers around the added text
            text = blue.get_text()
            blue.replace_with(f'[ADDED: {text}]')

        # Get text with decent formatting
        lines = []
        for element in soup.find_all(['p', 'div', 'h1', 'h2', 'h3', 'h4', 'pre']):
            text = element.get_text(strip=True)
            if text:
                lines.append(text)

        # Join with newlines
        text_with_markers = '\n'.join(lines)

        # Now remove the markers
        text_cleaned = text_with_markers.replace('[DELETED TEXT]', '')
        text_cleaned = re.sub(r'\[ADDED: (.*?)\]', r'\1', text_cleaned)

        # Normalize whitespace
        text_cleaned = re.sub(r'\s+', ' ', text_cleaned)

        # Add proper spacing around section headers
        text_cleaned = re.sub(r'(SEC\.\s+\d+\.)', r'\n\n\1\n', text_cleaned, flags=re.IGNORECASE)
        text_cleaned = re.sub(r'(SECTION\s+\d+\.)', r'\n\n\1\n', text_cleaned, flags=re.IGNORECASE)

        # Add spacing around the enactment clause
        text_cleaned = re.sub(
            r'(The people of the State of California do enact as follows:)', 
            r'\n\n\1\n\n', 
            text_cleaned, 
            flags=re.IGNORECASE
        )

        # Fix extra spaces
        text_cleaned = re.sub(r'\n\s+', '\n', text_cleaned)
        text_cleaned = re.sub(r'\n{3,}', '\n\n', text_cleaned)

        return text_cleaned

    def _clean_amended_bill_html(self, html_content: str) -> str:
        """
        Clean HTML of amended bills by normalizing strikethrough and added text.
        Returns clean HTML with amendments properly formatted.
        """
        output_dir = "debug_output"
        os.makedirs(output_dir, exist_ok=True)

        self.logger.info("Cleaning amended bill HTML to normalize strikethrough and added text")

        # Log initial state
        with open(os.path.join(output_dir, "bill_pre_clean.html"), "w", encoding="utf-8") as f:
            f.write(html_content)

        # Log counts of amendment markup
        strike_pattern = r'<strike>'
        blue_pattern = r'<font color="blue"'
        highlight_pattern = r'<span style=\'background-color:yellow\'>'

        strike_count = len(re.findall(strike_pattern, html_content))
        blue_count = len(re.findall(blue_pattern, html_content))
        highlight_count = len(re.findall(highlight_pattern, html_content))

        self.logger.info(f"Initial markup counts - strikethrough: {strike_count}, "
                        f"blue text: {blue_count}, highlights: {highlight_count}")

        # Log section markers before cleaning
        section_pattern = r'(?:SEC\.|SECTION)\s+\d+\.'
        pre_clean_sections = re.findall(section_pattern, html_content, re.IGNORECASE)
        self.logger.info(f"Section markers before cleaning: {len(pre_clean_sections)}")
        with open(os.path.join(output_dir, "pre_clean_sections.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(pre_clean_sections))

        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # KEEP strikethrough text but mark it for later removal in text extraction

            # Normalize styling on blue italicized text (added text)
            for blue_text in soup.find_all('font', attrs={'color': 'blue'}):
                # Just keep the font tag with a standard class for easier processing
                blue_text['class'] = 'added_text'
                # Remove italic tags but keep their content
                for i_tag in blue_text.find_all('i'):
                    i_tag.unwrap()

            # Remove highlight spans but keep their content
            for span in soup.find_all('span', style=lambda s: s and 'background-color:yellow' in s):
                span.unwrap()

            # Remove any custom tags that may interfere with parsing
            for tag in soup.find_all():
                if ':' in tag.name:  # XML namespaced tags like 'caml:xyz'
                    tag.unwrap()

            # Get the cleaned HTML
            html_str = str(soup)

            # Ensure proper separation of the enactment clause from the first section
            html_str = re.sub(
                r'(The people of the State of California do enact as follows:)\s*(?=(SEC\.|SECTION))',
                r'\1\n\n',
                html_str,
                flags=re.IGNORECASE
            )

            # Add significant spacing around section headers to make them stand out
            # First, make sure there are double newlines before each section header
            html_str = re.sub(
                r'([^\n])((?:SEC\.|SECTION)\s+\d+\.)',
                r'\1\n\n\2',
                html_str,
                flags=re.IGNORECASE
            )

            # Then, make sure there's a newline after each section header
            html_str = re.sub(
                r'((?:SEC\.|SECTION)\s+\d+\.)([^\n])',
                r'\1\n\2',
                html_str,
                flags=re.IGNORECASE
            )

            # Force a double newline before each section even if there's already a newline
            html_str = re.sub(
                r'\n(\s*(?:SEC\.|SECTION)\s+\d+\.)',
                r'\n\n\1',
                html_str,
                flags=re.IGNORECASE
            )

            # Normalize extra whitespace
            html_str = re.sub(r' {2,}', ' ', html_str)
            html_str = re.sub(r'\n{3,}', '\n\n', html_str)

            # Log final state after all cleaning
            post_clean_sections = re.findall(r'(?:SEC\.|SECTION)\s+\d+\.', html_str, re.IGNORECASE)
            self.logger.info(f"Section markers after cleaning: {len(post_clean_sections)}")

            with open(os.path.join(output_dir, "bill_post_clean.html"), "w", encoding="utf-8") as f:
                f.write(html_str)
            with open(os.path.join(output_dir, "post_clean_sections.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(post_clean_sections))

            # Create a "diff" of sections
            lost_sections = set(pre_clean_sections) - set(post_clean_sections)
            new_sections = set(post_clean_sections) - set(pre_clean_sections)
            if lost_sections or new_sections:
                self.logger.warning("Section marker changes detected during cleaning:")
                if lost_sections:
                    self.logger.warning(f"Lost sections: {sorted(lost_sections)}")
                if new_sections:
                    self.logger.warning(f"New sections: {sorted(new_sections)}")

            return html_str
        except Exception as e:
            self.logger.error(f"Error cleaning amended bill HTML: {str(e)}")
            return html_content  # Return original content on error

    def _extract_bill_metadata(self, html_content: str) -> Dict[str, Any]:
        """
        Extract basic metadata about the bill from the HTML.
        """
        metadata = {}
        try:
            # First pre-clean the HTML to handle malformed attributes
            cleaned_html = self._pre_clean_html(html_content)
            soup = BeautifulSoup(cleaned_html, "html.parser")

            # Try to extract bill number
            bill_num = soup.find(id="bill_num_title_chap")
            if bill_num:
                metadata['bill_number'] = bill_num.get_text(strip=True)
            else:
                # Try alternative pattern matching for bill number
                bill_pattern = r'(Assembly|Senate)\s+Bill\s+No\.\s+(\d+)'
                match = re.search(bill_pattern, soup.get_text())
                if match:
                    house = match.group(1)
                    number = match.group(2)
                    prefix = 'AB' if house == 'Assembly' else 'SB'
                    metadata['bill_number'] = f"{prefix}{number}"

            # Try to extract chapter number
            chap_num = soup.find(id="chap_num_title_chap")
            if chap_num:
                metadata['chapter_number'] = chap_num.get_text(strip=True)
            else:
                # Try alternative pattern matching for chapter number
                chapter_pattern = r'CHAPTER\s+(\d+)'
                match = re.search(chapter_pattern, soup.get_text())
                if match:
                    metadata['chapter_number'] = f"Chapter {match.group(1)}"

            # Try to extract title
            title_elem = soup.find(id="title")
            if title_elem:
                metadata['title'] = title_elem.get_text(strip=True)
            else:
                # Look for a typical bill title pattern
                title_pattern = r'An act to .*?, relating to'
                match = re.search(title_pattern, soup.get_text(), re.DOTALL)
                if match:
                    title_text = match.group(0)
                    # Limit title length
                    if len(title_text) > 200:
                        title_text = title_text[:197] + '...'
                    metadata['title'] = title_text

            # Extract approval date if available
            approval_text = soup.find(
                string=lambda t: "Approved" in str(t) and "Governor" in str(t)
            )
            if approval_text:
                # Try to find date near approval text
                date_pattern = r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}'
                match = re.search(date_pattern, str(approval_text.find_parent()))
                if match:
                    metadata['date_approved'] = match.group(0)
                else:
                    # Try to find in nearby elements
                    date_text = approval_text.find_next(
                        string=lambda t: any(
                            month in str(t)
                            for month in [
                                'January', 'February', 'March', 'April', 'May', 'June',
                                'July', 'August', 'September', 'October', 'November', 'December'
                            ]
                        )
                    )
                    if date_text:
                        metadata['date_approved'] = date_text.strip()

            return metadata
        except Exception as e:
            self.logger.warning(f"Error extracting bill metadata: {str(e)}")
            return metadata

    def _split_digest_and_bill(self, html_content: str) -> Dict[str, str]:
        """Splits bill HTML into digest and bill text."""
        try:
            # First pre-clean the HTML
            cleaned_html = self._pre_clean_html(html_content)
            soup = BeautifulSoup(cleaned_html, "html.parser")

            # Extract digest text
            digest_text = ""

            # Try different container options for digest
            digest_container = (
                soup.find(id="digest") or 
                soup.find(id="digesttext") or 
                soup.find(class_="digesttext")
            )

            # If container not found, look for the Legislative Counsel's Digest heading
            if not digest_container:
                digest_heading = soup.find(
                    string=lambda text: "LEGISLATIVE COUNSEL'S DIGEST" in text
                )
                if digest_heading:
                    # Get the parent element containing the heading
                    parent = digest_heading.find_parent()
                    if parent:
                        digest_container = parent

            # If we found a digest container, extract its text
            if digest_container:
                digest_text = digest_container.get_text(separator='\n', strip=True)

            # If still no digest text, try regex approach
            if not digest_text:
                full_text = soup.get_text(separator='\n', strip=True)
                digest_match = re.search(
                    r'LEGISLATIVE\s+COUNSEL[\'\']?S\s+DIGEST(.*?)(?=The\s+people\s+of\s+the\s+State\s+of\s+California\s+do\s+enact\s+as\s+follows)',
                    full_text,
                    re.DOTALL | re.IGNORECASE
                )
                if digest_match:
                    digest_text = digest_match.group(1).strip()

            # Extract bill text
            bill_text = ""

            # Try finding the bill text container
            bill_container = (
                soup.find(id="bill") or
                soup.find(id="billtext") or
                soup.find(class_="bill-content")
            )

            # Find the enactment clause
            enactment_text = soup.find(
                string=lambda text: "The people of the State of California do enact as follows" in text
            )

            # If we found the enactment clause, get everything after it
            if enactment_text:
                if bill_container:
                    # Get text from the container
                    bill_text = bill_container.get_text(separator='\n', strip=True)
                else:
                    # If no container, get text from the soup and extract everything after enactment
                    full_text = soup.get_text(separator='\n', strip=True)
                    bill_match = re.search(
                        r'The\s+people\s+of\s+the\s+State\s+of\s+California\s+do\s+enact\s+as\s+follows(.*?)',
                        full_text,
                        re.DOTALL | re.IGNORECASE
                    )
                    if bill_match:
                        bill_text = bill_match.group(1).strip()

            self.logger.info(f"Digest text length: {len(digest_text)}")
            self.logger.info(f"Bill text length: {len(bill_text)}")

            return {"digest": digest_text, "bill": bill_text}
        except Exception as e:
            self.logger.error(f"Error splitting digest and bill text: {str(e)}")
            raise