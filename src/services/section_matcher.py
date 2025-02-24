from typing import Dict, List, Any, Set
import re
import logging
from dataclasses import dataclass
from collections import defaultdict
import json

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

    def __init__(self, openai_client, model="gpt-4o-2024-08-06"):
        self.logger = logging.getLogger(__name__)
        self.client = openai_client
        self.model = model

    async def match_sections(self, skeleton: Dict[str, Any], bill_text: str, progress_handler=None) -> Dict[str, Any]:
        """
        Main matching function using multiple strategies

        Args:
            skeleton: The analysis skeleton structure
            bill_text: Full text of the bill
            progress_handler: Optional progress handler for reporting status

        Returns:
            Updated skeleton with matched sections
        """
        try:
            # Extract digest items and section maps
            digest_map = self._create_digest_map(skeleton)
            section_map = self._extract_bill_sections(bill_text)

            # Log the start of the matching process
            if progress_handler:
                progress_handler.update_progress(
                    4, 
                    "Starting section matching process",
                    1,
                    len(digest_map)
                )

            # Execute matching strategies in order of reliability
            matches = []
            digest_count = len(digest_map)
            current_digest = 1

            # 1. Exact code reference matching
            if progress_handler:
                progress_handler.update_progress(
                    4, 
                    "Matching sections by code references",
                    current_digest,
                    digest_count
                )

            code_matches = self._match_by_code_references(digest_map, section_map)
            matches.extend(code_matches)

            current_digest += len(code_matches) // 2  # Increment based on approximate matched items
            if progress_handler:
                progress_handler.update_substep(
                    min(current_digest, digest_count),
                    "Code reference matching complete"
                )

            # 2. Section number matching
            section_matches = self._match_by_section_numbers(digest_map, section_map)
            matches.extend(section_matches)

            current_digest += len(section_matches) // 2
            if progress_handler:
                progress_handler.update_substep(
                    min(current_digest, digest_count),
                    "Section number matching complete"
                )

            # 3. Context-based matching for remaining unmatched items
            remaining_digests = self._get_unmatched_digests(digest_map, matches)
            remaining_sections = self._get_unmatched_sections(section_map, matches)

            if remaining_digests and remaining_sections:
                if progress_handler:
                    progress_handler.update_substep(
                        min(current_digest, digest_count),
                        f"Performing contextual matching for {len(remaining_digests)} remaining sections"
                    )

                # Process remaining digests one by one with progress updates
                context_matches = []
                for i, (digest_id, digest_info) in enumerate(remaining_digests.items()):
                    if progress_handler:
                        progress_handler.update_substep(
                            min(current_digest + i, digest_count),
                            f"Analyzing context for digest item {digest_id}"
                        )

                    # Get context matches for this digest
                    digest_matches = await self._match_by_context_single(
                        digest_id,
                        digest_info, 
                        remaining_sections,
                        bill_text
                    )
                    context_matches.extend(digest_matches)

                matches.extend(context_matches)

            # Validate and update skeleton with matches
            if progress_handler:
                progress_handler.update_substep(
                    digest_count,
                    "Finalizing section matching"
                )

            validated_matches = self._validate_matches(matches)
            updated_skeleton = self._update_skeleton_with_matches(skeleton, validated_matches)

            # Verify all digest items are matched
            self._verify_complete_matching(updated_skeleton)

            # Final progress update
            if progress_handler:
                progress_handler.update_progress(
                    4, 
                    f"Section matching complete - {len(validated_matches)} matches found",
                    digest_count,
                    digest_count
                )

            return updated_skeleton

        except Exception as e:
            self.logger.error(f"Error in section matching: {str(e)}")
            raise

    async def _match_by_context_single(
        self, 
        digest_id: str,
        digest_info: Dict[str, Any],
        sections: Dict[str, Dict[str, Any]],
        bill_text: str
    ) -> List[MatchResult]:
        """Match a single digest item to sections by context analysis"""
        context_prompt = self._build_context_prompt(
            digest_info, 
            sections,
            bill_text
        )

        # Use `create(...)` as an async call
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "You are analyzing bill sections to determine which sections "
                        "implement specific digest items. Return a JSON object "
                        "with matches and confidence scores."
                    )
                },
                {"role": "user", "content": context_prompt}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )

        matches_data = self._parse_ai_matches(response.choices[0].message.content)
        results = []

        for match in matches_data:
            results.append(MatchResult(
                digest_id=digest_id,
                section_id=match["section_id"],
                confidence=match["confidence"],
                match_type="context",
                supporting_evidence=match.get("evidence", {})
            ))

        return results

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
                "action_type": self._determine_action_type(section_text),
                "code_sections": self._extract_modified_sections(section_text)
            }

        return section_map

    def _determine_action_type(self, text: str) -> str:
        """Determine the type of action being performed in the section"""
        lower_text = text.lower()
        if "amended" in lower_text and "repealed" in lower_text:
            return "AMENDED_AND_REPEALED"
        elif "repealed" in lower_text and "added" in lower_text:
            return "REPEALED_AND_ADDED"
        elif "amended" in lower_text:
            return "AMENDED"
        elif "added" in lower_text:
            return "ADDED"
        elif "repealed" in lower_text:
            return "REPEALED"
        return "UNKNOWN"

    def _extract_modified_sections(self, text: str) -> List[Dict[str, str]]:
        """Extract information about modified code sections"""
        modified_sections = []
        pattern = r'Section\s+(\d+(?:\.\d+)?)\s+of\s+the\s+([A-Za-z\s]+Code)'

        for match in re.finditer(pattern, text):
            section_num = match.group(1)
            code_name = match.group(2)

            modified_sections.append({
                "section": section_num,
                "code": code_name,
                "action": self._determine_action_type(text)
            })

        return modified_sections

    def _match_by_code_references(
        self, 
        digest_map: Dict[str, Dict[str, Any]],
        section_map: Dict[str, Dict[str, Any]]
    ) -> List[MatchResult]:
        """Match digest items to bill sections based on shared code references"""
        matches = []

        for digest_id, digest_info in digest_map.items():
            digest_refs = digest_info["code_refs"]

            if not digest_refs:
                continue

            for section_id, section_info in section_map.items():
                section_refs = section_info["code_refs"]

                # Find intersections
                common_refs = digest_refs.intersection(section_refs)

                if common_refs:
                    confidence = min(
                        0.9, 
                        0.5 + (len(common_refs) / max(len(digest_refs), 1) * 0.4)
                    )

                    matches.append(MatchResult(
                        digest_id=digest_id,
                        section_id=section_id,
                        confidence=confidence,
                        match_type="code_ref",
                        supporting_evidence={"common_refs": list(common_refs)}
                    ))

        return matches

    def _match_by_section_numbers(
        self,
        digest_map: Dict[str, Dict[str, Any]],
        section_map: Dict[str, Dict[str, Any]]
    ) -> List[MatchResult]:
        """Match based on explicit section numbers mentioned in digest items"""
        matches = []

        for digest_id, digest_info in digest_map.items():
            section_refs = digest_info["section_refs"]

            if not section_refs:
                continue

            for section_id in section_refs:
                if section_id in section_map:
                    matches.append(MatchResult(
                        digest_id=digest_id,
                        section_id=section_id,
                        confidence=0.8,
                        match_type="section_num",
                        supporting_evidence={"explicit_reference": True}
                    ))

        return matches

    def _get_unmatched_digests(
        self, 
        digest_map: Dict[str, Dict[str, Any]],
        matches: List[MatchResult]
    ) -> Dict[str, Dict[str, Any]]:
        """Get digest items that haven't been matched yet"""
        matched_digest_ids = {match.digest_id for match in matches}
        return {
            digest_id: info 
            for digest_id, info in digest_map.items() 
            if digest_id not in matched_digest_ids
        }

    def _get_unmatched_sections(
        self,
        section_map: Dict[str, Dict[str, Any]],
        matches: List[MatchResult]
    ) -> Dict[str, Dict[str, Any]]:
        """Get bill sections that haven't been matched yet"""
        matched_section_ids = {match.section_id for match in matches}
        return {
            section_id: info 
            for section_id, info in section_map.items() 
            if section_id not in matched_section_ids
        }

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
            "confidence": float,
            "evidence": {{
                "key_terms": ["matched terms"],
                "thematic_match": "explanation",
                "action_alignment": "explanation"
            }}
        }}
    ]
}}"""

    def _format_sections_for_prompt(
        self, 
        sections: Dict[str, Dict[str, Any]]
    ) -> str:
        """Format sections for inclusion in the prompt"""
        formatted = []
        for section_id, info in sections.items():
            preview = info["text"][:200] + ("..." if len(info["text"]) > 200 else "")
            formatted.append(f"Section {section_id}:\n{preview}\n")
        return "\n".join(formatted)

    def _parse_ai_matches(self, content: str) -> List[Dict[str, Any]]:
        """Parse matches from AI response"""
        try:
            data = json.loads(content)
            return data.get("matches", [])
        except Exception as e:
            self.logger.error(f"Error parsing AI matches: {str(e)}")
            return []

    def _extract_code_references(self, text: str) -> Set[str]:
        """Extract code references with improved pattern matching"""
        references = set()

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

    def _extract_section_numbers(self, text: str) -> Set[str]:
        """Extract bill section numbers from text using precise patterns"""
        numbers = set()

        # Precisely match "SECTION 1." and "SEC. X." references
        section_patterns = [
            r'SECTION\s+1\.', 
            r'SEC\.\s+(\d+)\.'
        ]

        # Match first section
        if re.search(section_patterns[0], text, re.IGNORECASE):
            numbers.add("1")

        # Match other sections
        for match in re.finditer(section_patterns[1], text, re.IGNORECASE):
            numbers.add(match.group(1))

        return numbers

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

    def _update_skeleton_with_matches(
        self, 
        skeleton: Dict[str, Any], 
        matches: List[MatchResult]
    ) -> Dict[str, Any]:
        """Update the skeleton with match information"""
        digest_matches = defaultdict(list)
        for match in matches:
            digest_matches[match.digest_id].append(match)

        for change in skeleton["changes"]:
            change_matches = digest_matches.get(change["id"], [])
            # Store the section IDs in the bill_sections field
            change["bill_sections"] = [m.section_id for m in change_matches]

            # Additional information can be stored here
            if change_matches:
                change["matching_confidence"] = max(m.confidence for m in change_matches)
                best_match = max(change_matches, key=lambda m: m.confidence)
                change["matching_evidence"] = {
                    "type": best_match.match_type,
                    "details": best_match.supporting_evidence
                }

        return skeleton

    def _verify_complete_matching(self, skeleton: Dict[str, Any]) -> None:
        """Verify all digest items have matches and log warnings for unmatched items"""
        unmatched = []
        for change in skeleton["changes"]:
            if not change.get("bill_sections"):
                unmatched.append(change["id"])

        if unmatched:
            self.logger.warning(f"Unmatched digest items: {', '.join(unmatched)}")

    def _get_linked_sections(self, change: Dict[str, Any], skeleton: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get all bill sections that are linked to this change."""
        sections = []

        # Get the bill section numbers from the change, and normalize format
        section_nums = change.get("bill_sections", [])
        normalized_nums = []

        for sec_num in section_nums:
            # Extract just the numeric part if it contains "Section" prefix
            if isinstance(sec_num, str) and "section" in sec_num.lower():
                # Extract just the number
                num_match = re.search(r'(\d+(?:\.\d+)?)', sec_num, re.IGNORECASE)
                if num_match:
                    normalized_nums.append(num_match.group(1))
            else:
                normalized_nums.append(str(sec_num))

        self.logger.info(f"Change {change.get('id')} has normalized section numbers: {normalized_nums}")

        # Look up each section in the bill_sections from the skeleton
        bill_sections = skeleton.get("bill_sections", [])

        for section_num in normalized_nums:
            found_section = False
            for section in bill_sections:
                if str(section.get("number")) == section_num:
                    sections.append({
                        "number": section.get("number"),
                        "text": section.get("text", ""),
                        "original_label": section.get("original_label", f"SECTION {section_num}."),
                        "code_modifications": section.get("code_modifications", [])
                    })
                    found_section = True
                    break

            if not found_section:
                self.logger.warning(f"Could not find section {section_num} in bill_sections")

        return sections
