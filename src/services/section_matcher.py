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

        # We'll store a reference to the openai module so we can easily make calls.
        self.client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # Use a currently supported model. You can switch to "gpt-4" if you have access.
        self.model = "gpt-4o-mini-2024-07-18"

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

        # Extract code references from section text using regex
        section_refs = self._extract_code_references(section_text)

        # Look for matching references in changes
        for change in skeleton["changes"]:
            change_refs = set(change["code_sections"])
            # If there's any overlap between section_refs and code_sections, it's a match
            if change_refs & section_refs:  
                matches.append(change["id"])

        return matches

    async def _ai_assisted_match(self, skeleton: Dict[str, Any], section_text: str) -> List[str]:
        """Use AI to match the section to appropriate changes when exact matching fails."""
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are analyzing a California trailer bill section to determine which "
                        "substantive change(s) from the Legislative Counsel's Digest it implements. "
                        "You should return only the IDs of the matching changes. Consider both the "
                        "specific legal changes being made and the broader context."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"Here are the substantive changes identified in the digest:\n\n"
                        f"{json.dumps(skeleton['changes'], indent=2)}\n\n"
                        f"Here is the bill section text to match:\n\n"
                        f"{section_text}\n\n"
                        "Which change(s) does this section implement? Return ONLY a JSON object "
                        "with a 'matching_changes' array containing the IDs of the matching changes."
                    )
                }
            ]

            # Use rate limiter for API call
            async def make_api_call():
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0,
                    response_format={"type": "json_object"}
                )

            response = await self.rate_limiter.execute(make_api_call)

            result = json.loads(response.choices[0].message.content)
            return result.get("matching_changes", [])

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
            # Add section number to each matched change
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

        Args:
            text: Text to extract references from

        Returns:
            A set of code references in the format used in the JSON (e.g., "Education Code Section 1234").
        """
        references = set()

        # Regex pattern for "Section X of the Y Code"
        pattern = r'Section[s]?\s+([0-9\.\,\-\s&and]+)\s+(?:of\s+(?:the\s+)?)?([A-Za-z\s]+Code)'
        matches = re.finditer(pattern, text, re.IGNORECASE)

        for match in matches:
            sections = match.group(1).split(',')
            code_name = match.group(2).strip()

            for section in sections:
                section = section.strip()
                if section:
                    references.add(f"{code_name} Section {section}")

        return references

    def validate_matches(self, skeleton: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Validate the matches in the skeleton and return any issues found.

        Args:
            skeleton: JSON skeleton to validate

        Returns:
            List of dictionaries describing validation issues (if any).
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

        Args:
            skeleton: JSON skeleton to analyze

        Returns:
            Dictionary of matching statistics.
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