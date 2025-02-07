import os
import json
import logging
import re
import openai
from typing import Dict, List, Any, Optional
from .rate_limiter import RateLimiter

from src.logging_config import get_module_logger

class SectionMatcher:
    """
    Matches bill sections to the appropriate changes in the JSON skeleton.
    Uses both traditional matching techniques and AI assistance for accuracy.
    """

    def __init__(self):
        """Initialize the matcher with OpenAI client and logger."""
        self.logger = logging.getLogger(__name__)

        # Make sure the OpenAI API key is pulled from environment
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            self.logger.error("OPENAI_API_KEY is not set")
            raise ValueError("OPENAI_API_KEY is not set")

        # We'll store a reference to the openai module so we can easily make calls.
        openai.api_key = api_key

        # Use a currently supported model. Adjust if you have GPT-4 access.
        self.model = "gpt-4"

        # Initialize rate limiter for 50 requests per minute
        self.rate_limiter = RateLimiter(requests_per_minute=50)

    async def match_section(self, skeleton: Dict[str, Any], section_data: Dict[str, str]) -> Dict[str, Any]:
        """Match a single bill section to the appropriate change(s) in the JSON skeleton."""
        try:
            section_number = section_data.get("section_number", "")
            section_text = section_data.get("section_text", "")

            # First try exact matching by code references
            exact_matches = self._find_exact_matches(skeleton, section_text)

            if exact_matches:
                matched_changes = exact_matches
            else:
                # If no exact matches, use AI to help match
                matched_changes = await self._ai_assisted_match(skeleton, section_text)

            return self._update_skeleton(skeleton, section_number, matched_changes)

        except Exception as e:
            self.logger.error(f"Error matching section {section_data.get('section_number', 'UNKNOWN')}: {str(e)}")
            raise

    def _find_exact_matches(self, skeleton: Dict[str, Any], section_text: str) -> List[str]:
        """
        Find exact matches based on code references.

        Args:
            skeleton: Current JSON skeleton
            section_text: Text of the bill section to match

        Returns:
            List of change IDs that match
        """
        matches = []
        section_refs = self._extract_code_references(section_text)

        for change in skeleton["changes"]:
            change_refs = set(change["code_sections"])
            # If there's any overlap between section_refs and code_sections, it's a match
            if change_refs & section_refs:
                matches.append(change["id"])

        return matches

    async def _ai_assisted_match(self, skeleton: Dict[str, Any], section_text: str) -> List[str]:
        """Use AI to match the section to appropriate changes when exact matching fails."""
        try:
            # We prompt the model for a JSON list of matching IDs
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are analyzing a California trailer bill section to determine which "
                        "substantive change(s) from the Legislative Counsel's Digest it implements. "
                        "You should return only the IDs of the matching changes, in JSON."
                    )
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "changes": skeleton["changes"],
                        "section_text": section_text
                    }, indent=2)
                }
            ]

            async def make_api_call():
                return openai.ChatCompletion.create(
                    model=self.model,
                    messages=messages,
                    temperature=0
                )

            response = await self.rate_limiter.execute(make_api_call)
            content = response["choices"][0]["message"]["content"]

            # Expecting a JSON with "matching_changes": ["change_1", "change_2", ...]
            # Attempt to parse
            try:
                result = json.loads(content)
                return result.get("matching_changes", [])
            except json.JSONDecodeError:
                self.logger.warning("AI output could not be parsed as JSON.")
                return []

        except Exception as e:
            self.logger.error(f"Error in AI-assisted matching: {str(e)}")
            return []

    def _update_skeleton(self, skeleton: Dict[str, Any], section_number: str,
                         matched_changes: List[str]) -> Dict[str, Any]:
        """
        Update the JSON skeleton with the matched section.

        Args:
            skeleton: Current JSON skeleton
            section_number: Number of the matched section
            matched_changes: List of change IDs that match

        Returns:
            Updated JSON skeleton
        """
        try:
            for change in skeleton["changes"]:
                if change["id"] in matched_changes:
                    if section_number not in change["bill_sections"]:
                        change["bill_sections"].append(section_number)

            return skeleton

        except Exception as e:
            self.logger.error(f"Error updating skeleton: {str(e)}")
            raise

    def _extract_code_references(self, text: str) -> set:
        """
        Extract code references from text for exact matching.

        Return them in the same string format used in the JSON skeleton ("Government Code Section 8594.14", etc.)
        """
        references = set()

        # Pattern for "Section(s) 123, 456 of the Government Code"
        pattern_of_code = re.compile(
            r'(?:Sections?\s+([\d\.\,\-\s&and]+)\s+of\s+the\s+([A-Za-z\s]+Code))',
            flags=re.IGNORECASE
        )

        # Pattern for "Government Code Section(s) 123, 456"
        pattern_code_section = re.compile(
            r'([A-Za-z\s]+Code)\s+Sections?\s+([\d\.\,\-\s&and]+)',
            flags=re.IGNORECASE
        )

        # Grab references from pattern_of_code
        for m in pattern_of_code.finditer(text):
            raw_secs = m.group(1)
            code_name = m.group(2).strip().title() + " Code"
            # Split by comma or "and"
            splitted = re.split(r'[,\s]+(?:and\s+|\s+and\s+)?', raw_secs)
            splitted = [s for s in splitted if s.strip()]
            for sec in splitted:
                sec = sec.strip().replace(".", "")
                if sec and re.match(r'^\d+', sec):
                    references.add(f"{code_name} Section {sec}")

        # Grab references from pattern_code_section
        for m in pattern_code_section.finditer(text):
            code_name = m.group(1).strip().title() + " Code"
            raw_secs = m.group(2)
            splitted = re.split(r'[,\s]+(?:and\s+|\s+and\s+)?', raw_secs)
            splitted = [s for s in splitted if s.strip()]
            for sec in splitted:
                sec = sec.strip().replace(".", "")
                if sec and re.match(r'^\d+', sec):
                    references.add(f"{code_name} Section {sec}")

        return references

    def validate_matches(self, skeleton: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Validate the matches in the skeleton and return any issues found.
        """
        issues = []

        for change in skeleton["changes"]:
            # Check for changes with no matched sections
            if not change["bill_sections"]:
                issues.append({
                    "type": "unmatched_change",
                    "id": change["id"],
                    "message": "No bill sections matched to this change"
                })

            # Check for suspiciously large numbers of matches
            if len(change["bill_sections"]) > 3:
                issues.append({
                    "type": "multiple_matches",
                    "id": change["id"],
                    "message": f"Unusually high number of matched sections: {len(change['bill_sections'])}"
                })

        return issues

    def get_matching_stats(self, skeleton: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get statistics about the matching results.
        """
        total_changes = len(skeleton["changes"])
        matched_changes = len([c for c in skeleton["changes"] if c["bill_sections"]])
        unique_sections = len(
            set(
                section
                for change in skeleton["changes"]
                for section in change["bill_sections"]
            )
        )

        return {
            "total_changes": total_changes,
            "matched_changes": matched_changes,
            "unmatched_changes": total_changes - matched_changes,
            "unique_sections_matched": unique_sections,
            "match_rate": matched_changes / total_changes if total_changes > 0 else 0
        }
