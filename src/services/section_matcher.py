from typing import Dict, List, Any, Optional, Set, Tuple, Union
import re
import logging
from dataclasses import dataclass, field
from collections import defaultdict

@dataclass
class MatchResult:
    """Represents a match between digest and bill sections with confidence score"""
    digest_id: str
    section_id: str
    confidence: float
    match_type: str  # 'exact', 'code_ref', 'semantic', 'context'
    supporting_evidence: Dict[str, Any]

class SectionMatcher:
    """Enhanced matcher using multiple strategies to link digest items to bill sections"""

    def __init__(self, openai_client, model="gpt-4"):
        self.logger = logging.getLogger(__name__)
        self.client = openai_client
        self.model = model

    async def match_sections(self, skeleton: Dict[str, Any], bill_text: str) -> Dict[str, Any]:
        """Main matching function using multiple strategies"""
        try:
            # Extract digest items and section maps
            digest_map = self._create_digest_map(skeleton)
            section_map = self._extract_bill_sections(bill_text)

            # Execute matching strategies in order of reliability
            matches = []

            # 1. Exact code reference matching
            code_matches = self._match_by_code_references(digest_map, section_map)
            matches.extend(code_matches)

            # 2. Section number matching
            section_matches = self._match_by_section_numbers(digest_map, section_map)
            matches.extend(section_matches)

            # 3. Context-based matching for remaining unmatched items
            remaining_digests = self._get_unmatched_digests(digest_map, matches)
            remaining_sections = self._get_unmatched_sections(section_map, matches)

            if remaining_digests and remaining_sections:
                context_matches = await self._match_by_context(
                    remaining_digests, 
                    remaining_sections,
                    bill_text
                )
                matches.extend(context_matches)

            # Validate and update skeleton with matches
            validated_matches = self._validate_matches(matches)
            updated_skeleton = self._update_skeleton_with_matches(skeleton, validated_matches)

            # Verify all digest items are matched
            self._verify_complete_matching(updated_skeleton)

            return updated_skeleton

        except Exception as e:
            self.logger.error(f"Error in section matching: {str(e)}")
            raise

    def _create_digest_map(self, skeleton: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Create structured map of digest items with extracted information"""
        digest_map = {}
        for change in skeleton["changes"]:
            digest_map[change["id"]] = {
                "text": change["digest_text"],
                "code_refs": self._extract_code_references(change["digest_text"]),
                "section_refs": self._extract_section_numbers(change["digest_text"]),
                "existing_law": change.get("existing_law", ""),
                "proposed_change": change.get("proposed_change", "")
            }
        return digest_map

    def _extract_bill_sections(self, bill_text: str) -> Dict[str, Dict[str, Any]]:
        """Extract and structure bill sections with enhanced metadata"""
        section_map = {}

        # Enhanced section pattern with named groups
        pattern = r'(?:SECTION|SEC\.)\s+(?P<number>\d+(?:\.\d+)?)\.\s*(?P<text>(?:.*?)(?=(?:SECTION|SEC\.)\s+\d+|\Z))'

        for match in re.finditer(pattern, bill_text, re.DOTALL | re.MULTILINE):
            section_num = match.group('number')
            section_text = match.group('text').strip()

            section_map[section_num] = {
                "text": section_text,
                "code_refs": self._extract_code_references(section_text),
                "action_type": self._determine_action(section_text),
                "code_sections": self._extract_modified_sections(section_text)
            }

        return section_map

    def _extract_code_references(self, text: str) -> Set[str]:
        """Extract code references with improved pattern matching"""
        references = set()

        # Multiple patterns to catch different reference formats
        patterns = [
            # Standard format: "Section 123 of the Education Code"
            r'Section(?:s)?\s+(\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)',

            # Reverse format: "Education Code Section 123"
            r'([A-Za-z\s]+Code)\s+Section(?:s)?\s+(\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*)',

            # Range format: "Sections 123-128 of the Education Code"
            r'Section(?:s)?\s+(\d+(?:\.\d+)?)\s*(?:to|through|-)\s*(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                if len(match.groups()) == 2:
                    sections, code = match.groups()
                    for section in re.split(r'[,\s]+', sections):
                        if section.strip():
                            references.add(f"{code.strip()} Section {section.strip()}")
                elif len(match.groups()) == 3:
                    start, end, code = match.groups()
                    for num in range(int(float(start)), int(float(end)) + 1):
                        references.add(f"{code.strip()} Section {num}")

        return references

    async def _match_by_context(
        self, 
        unmatched_digests: Dict[str, Dict[str, Any]],
        unmatched_sections: Dict[str, Dict[str, Any]],
        bill_text: str
    ) -> List[MatchResult]:
        """Use AI to match remaining sections based on context"""
        matches = []

        for digest_id, digest_info in unmatched_digests.items():
            context_prompt = self._build_context_prompt(
                digest_info, 
                unmatched_sections,
                bill_text
            )

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are analyzing bill sections to determine which sections implement specific digest items. Return a JSON object with matches and confidence scores."},
                    {"role": "user", "content": context_prompt}
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )

            matches_data = self._parse_ai_matches(response.choices[0].message.content)
            for match in matches_data:
                matches.append(MatchResult(
                    digest_id=digest_id,
                    section_id=match["section_id"],
                    confidence=match["confidence"],
                    match_type="context",
                    supporting_evidence=match["evidence"]
                ))

        return matches

    def _build_context_prompt(
        self,
        digest_info: Dict[str, Any],
        sections: Dict[str, Dict[str, Any]],
        bill_text: str
    ) -> str:
        """Build detailed prompt for context matching"""
        return f"""Analyze which bill sections implement this digest item:

Digest Item:
{digest_info['text']}

Existing Law:
{digest_info['existing_law']}

Proposed Change:
{digest_info['proposed_change']}

Available Bill Sections:
{self._format_sections_for_prompt(sections)}

Analyze the text and return matches in this JSON format:
{{
    "matches": [
        {{
            "section_id": "section number",
            "confidence": float between 0-1,
            "evidence": {{
                "key_terms": [matched terms],
                "thematic_match": "explanation",
                "action_alignment": "explanation"
            }}
        }}
    ]
}}"""

    def _validate_matches(self, matches: List[MatchResult]) -> List[MatchResult]:
        """Validate matches and resolve conflicts"""
        validated = []
        seen_sections = defaultdict(list)

        # Group matches by section
        for match in matches:
            seen_sections[match.section_id].append(match)

        # Resolve conflicts
        for section_id, section_matches in seen_sections.items():
            if len(section_matches) == 1:
                validated.append(section_matches[0])
            else:
                # Keep highest confidence match
                best_match = max(section_matches, key=lambda m: m.confidence)
                validated.append(best_match)

        return validated

    def _extract_section_numbers(self, text: str) -> Set[str]:
        """Extract section numbers from text using regex patterns"""
        numbers = set()
        patterns = [
            r'Section\s+(\d+(?:\.\d+)?)',
            r'Sections\s+(\d+(?:\.\d+)?(?:\s*(?:,|and)\s*\d+(?:\.\d+)?)*)',
            r'Sections\s+(\d+(?:\.\d+)?)\s*(?:to|through|-)\s*(\d+(?:\.\d+)?)'
        ]
        
        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                if len(match.groups()) == 1:
                    # Single section or comma-separated list
                    sections = re.split(r'[,\s]+and\s+|\s*,\s*', match.group(1))
                    numbers.update(sections)
                elif len(match.groups()) == 2:
                    # Range of sections
                    start, end = match.groups()
                    start_num = float(start)
                    end_num = float(end)
                    numbers.update(str(num) for num in range(int(start_num), int(end_num) + 1))
        
        return numbers

    def _verify_complete_matching(self, skeleton: Dict[str, Any]) -> None:
        """Verify all digest items have matches and log warnings for unmatched items"""
        unmatched = []
        for change in skeleton["changes"]:
            if not change.get("bill_sections"):
                unmatched.append(change["id"])

        if unmatched:
            self.logger.warning(f"Unmatched digest items: {', '.join(unmatched)}")