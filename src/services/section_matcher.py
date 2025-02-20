import re
import logging
import json
import asyncio
from typing import Dict, List, Any, Set
from dataclasses import dataclass
from collections import defaultdict

@dataclass
class MatchResult:
    digest_id: str
    section_id: str
    confidence: float
    match_type: str
    supporting_evidence: Dict[str, Any]

class SectionMatcher:
    """
    Enhanced matcher using multiple strategies to link digest items to bill sections
    based on code references, explicit section numbers, and context.
    """

    def __init__(self, openai_client, model="gpt-4"):
        self.logger = logging.getLogger(__name__)
        self.client = openai_client
        self.model = model

    async def match_sections(self, skeleton: Dict[str, Any], bill_text: str) -> Dict[str, Any]:
        try:
            digest_map = self._create_digest_map(skeleton)
            section_map = self._extract_bill_sections(bill_text)

            matches = []
            # 1) Exact code reference matching
            code_matches = self._match_by_code_references(digest_map, section_map)
            matches.extend(code_matches)

            # 2) Section number matching
            section_matches = self._match_by_section_numbers(digest_map, section_map)
            matches.extend(section_matches)

            # 3) Context-based matching
            remaining_digests = self._get_unmatched_digests(digest_map, matches)
            remaining_sections = self._get_unmatched_sections(section_map, matches)

            if remaining_digests and remaining_sections:
                context_matches = await self._match_by_context(
                    remaining_digests,
                    remaining_sections,
                    bill_text
                )
                matches.extend(context_matches)

            validated_matches = self._validate_matches(matches)
            updated_skeleton = self._update_skeleton_with_matches(skeleton, validated_matches)
            self._verify_complete_matching(updated_skeleton)

            return updated_skeleton

        except Exception as e:
            self.logger.error(f"Error in section matching: {str(e)}")
            raise

    def _create_digest_map(self, skeleton: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
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
        """
        Extract SEC. 1, SEC. 2, etc., plus code references.
        """
        section_map = {}
        pattern = r'(?:SECTION|SEC\.)\s+(?P<number>\d+(?:\.\d+)?)\.\s*(?P<text>(?:.*?)(?=(?:SECTION|SEC\.)\s+\d+|\Z))'
        for match in re.finditer(pattern, bill_text, re.DOTALL | re.MULTILINE):
            section_num = match.group('number')
            section_text = match.group('text').strip()
            code_refs = self._extract_code_references(section_text)
            action_type = self._determine_action(section_text)
            mod_sections = self._extract_modified_sections(section_text)

            section_map[section_num] = {
                "text": section_text,
                "code_refs": code_refs,
                "action_type": action_type,
                "code_sections": mod_sections
            }
        return section_map

    def _match_by_code_references(self, digest_map: Dict[str, Dict[str, Any]],
                                  section_map: Dict[str, Dict[str, Any]]) -> List[MatchResult]:
        matches = []
        for digest_id, digest_info in digest_map.items():
            digest_refs = digest_info["code_refs"]
            if not digest_refs:
                continue
            for section_id, section_info in section_map.items():
                section_refs = section_info["code_refs"]
                if not section_refs:
                    continue
                common = digest_refs & section_refs
                if common:
                    matches.append(MatchResult(
                        digest_id=digest_id,
                        section_id=section_id,
                        confidence=0.9,
                        match_type="code_ref",
                        supporting_evidence={"matching_refs": list(common)}
                    ))
        return matches

    def _match_by_section_numbers(self, digest_map: Dict[str, Dict[str, Any]],
                                  section_map: Dict[str, Dict[str, Any]]) -> List[MatchResult]:
        matches = []
        for digest_id, digest_info in digest_map.items():
            digest_secs = digest_info["section_refs"]
            for section_id in section_map.keys():
                if section_id in digest_secs:
                    matches.append(MatchResult(
                        digest_id=digest_id,
                        section_id=section_id,
                        confidence=0.8,
                        match_type="section_number",
                        supporting_evidence={"matching_section": section_id}
                    ))
        return matches

    async def _match_by_context(self, unmatched_digests, unmatched_sections, bill_text) -> List[MatchResult]:
        """
        Use GPT to do context-based matching for any leftover items.
        """
        matches = []
        for digest_id, digest_info in unmatched_digests.items():
            prompt = self._build_context_prompt(digest_info, unmatched_sections)
            try:
                completion = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.client.ChatCompletion.create(
                        model=self.model,
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "You are analyzing a California trailer bill to determine "
                                    "which SEC. # sections implement or correspond to a given digest item. "
                                    "Return a JSON object with matches and confidence scores."
                                )
                            },
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0
                    )
                )
                content = completion.choices[0].message.content
                try:
                    data = json.loads(content)
                    for m in data.get("matches", []):
                        matches.append(MatchResult(
                            digest_id=digest_id,
                            section_id=m["section_id"],
                            confidence=m["confidence"],
                            match_type="context",
                            supporting_evidence=m.get("evidence", {})
                        ))
                except Exception as e:
                    self.logger.error(f"Failed to parse JSON from GPT: {e}")

            except Exception as e:
                self.logger.error(f"Error in AI context matching: {str(e)}")
        return matches

    def _build_context_prompt(self, digest_info: Dict[str, Any], sections: Dict[str, Dict[str, Any]]) -> str:
        sec_texts = []
        for sid, sinfo in sections.items():
            sec_texts.append(f"SEC. {sid}:\n{sinfo['text']}\n")
        return (
            f"Digest Item:\n{digest_info['text']}\n\n"
            f"Existing Law:\n{digest_info['existing_law']}\n\n"
            f"Proposed Change:\n{digest_info['proposed_change']}\n\n"
            f"Here are the remaining SEC. # sections:\n{''.join(sec_texts)}\n\n"
            "Based on context, which SEC. # sections correspond to the digest item? "
            "Return JSON in the format:\n"
            "{\n"
            '   "matches": [\n'
            "       {\n"
            '           "section_id": "the SEC. number",\n'
            '           "confidence": 0.0 to 1.0,\n'
            '           "evidence": {\n'
            '               "key_terms": ["terms"],\n'
            '               "thematic_match": "explanation"\n'
            "           }\n"
            "       }\n"
            "   ]\n"
            "}"
        )

    def _validate_matches(self, matches: List[MatchResult]) -> List[MatchResult]:
        validated = []
        # We'll keep the highest confidence match for each digest->section
        # But it's possible a digest item can match multiple sections
        # We'll store them but if there's a direct conflict, we keep the highest
        combined = defaultdict(list)
        for m in matches:
            key = (m.digest_id, m.section_id)
            combined[key].append(m)

        for k, result_list in combined.items():
            # pick highest confidence
            best = max(result_list, key=lambda x: x.confidence)
            validated.append(best)

        return validated

    def _update_skeleton_with_matches(self, skeleton: Dict[str, Any], matches: List[MatchResult]) -> Dict[str, Any]:
        digest_to_sections = defaultdict(list)
        for m in matches:
            digest_to_sections[m.digest_id].append({
                "section_id": m.section_id,
                "confidence": m.confidence,
                "match_type": m.match_type
            })

        for change in skeleton["changes"]:
            change["bill_sections"] = digest_to_sections.get(change["id"], [])

        return skeleton

    def _verify_complete_matching(self, skeleton: Dict[str, Any]) -> None:
        unmatched = []
        for change in skeleton["changes"]:
            if not change.get("bill_sections"):
                unmatched.append(change["id"])
        if unmatched:
            self.logger.warning(f"Unmatched digest items: {', '.join(unmatched)}")

    def _extract_code_references(self, text: str) -> Set[str]:
        """
        Convert code references into a set of "CodeName:section" strings
        for easier matching.
        """
        # We'll do a simpler approach: look for "XXXX Code Section NNN"
        # or "Section NNN of the XXXX Code" or range forms:
        # This is already done in base_parser, but we replicate a simpler approach
        # for matching here.

        # We'll unify patterns to catch typical references
        pattern = r'(?i)([A-Za-z\s]+Code)\s+Section(?:s)?\s+([\d\.\-\,\s&and]+)|Section(?:s)?\s+([\d\.\-\,\s&and]+)\s+of\s+([A-Za-z\s]+Code)'
        result = set()

        matches = re.finditer(pattern, text)
        for match in matches:
            # match can have up to 4 groups, 2 for each side
            left_code = match.group(1)
            left_secs = match.group(2)
            right_secs = match.group(3)
            right_code = match.group(4)

            if left_code and left_secs:
                code_name = left_code.strip()
                sections_str = left_secs.strip()
                # split on commas or 'and'
                sections_list = self._split_sections(sections_str)
                for sec in sections_list:
                    result.add(f"{code_name}:{sec.strip()}")

            if right_secs and right_code:
                code_name = right_code.strip()
                sections_str = right_secs.strip()
                sections_list = self._split_sections(sections_str)
                for sec in sections_list:
                    result.add(f"{code_name}:{sec.strip()}")

        return result

    def _split_sections(self, sections_str: str) -> List[str]:
        # Replace 'and' with commas
        s = re.sub(r'\s+and\s+', ',', sections_str, flags=re.IGNORECASE)
        # Split on commas
        parts = [x.strip() for x in s.split(',')]
        return [p for p in parts if p]

    def _determine_action(self, text: str) -> str:
        lower = text.lower()
        if "repealed and added" in lower:
            return "REPEALED_AND_ADDED"
        if "amended and repealed" in lower:
            return "AMENDED_AND_REPEALED"
        if "amended" in lower:
            return "AMENDED"
        if "added" in lower:
            return "ADDED"
        if "repealed" in lower:
            return "REPEALED"
        return "UNKNOWN"

    def _extract_modified_sections(self, text: str) -> List[str]:
        # E.g. "Section 8594.14 is amended"
        # We'll do something simple for demonstration
        pattern = r'(?:amends|adds|repeals)\s+Section\s+(\d+(?:\.\d+)?)'
        return re.findall(pattern, text, flags=re.IGNORECASE)
