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

    def __init__(self, openai_client, model="gpt-4o-2024-08-06"):
        self.logger = logging.getLogger(__name__)
        self.client = openai_client
        self.model = model

    async def match_sections(self, skeleton: Dict[str, Any], bill_text: str) -> Dict[str, Any]:
        """
        Matches each digest 'change' to one or more sections in the raw bill text.
        We'll do three passes:
        1) Exact code reference matching
        2) Section number matching
        3) GPT-based context matching
        """
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
        We'll store them keyed by the numeric section_id (string).
        """
        section_map = {}
        # Updated pattern to catch "SECTION 1." lines more easily
        pattern = r'(?:^|\n)(SEC(?:TION)?\.?)\s+(\d+)(?:\.)?\s+(.*?)(?=\nSEC(?:TION)?\.?\s+\d+|\Z)'
        matches = re.finditer(pattern, bill_text, flags=re.IGNORECASE | re.DOTALL)

        for match in matches:
            label = match.group(1)  # "SEC." or "SECTION"
            sec_num = match.group(2)  # "1", "2", ...
            sec_text = match.group(3).strip()
            code_refs = self._extract_code_references(sec_text)
            action_type = self._determine_action(sec_text)
            mod_sections = self._extract_modified_sections(sec_text)

            section_map[sec_num] = {
                "text": sec_text,
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
        """
        If the digest text says 'SECTION 2' or 'SEC. 2', let's try direct matching.
        """
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
        Use GPT to do context-based matching for leftover items.
        We'll ask GPT which sections best match each digest item.
        """
        matches = []
        for digest_id, digest_info in unmatched_digests.items():
            prompt = self._build_context_prompt(digest_info, unmatched_sections)
            try:
                completion = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are analyzing a California trailer bill to determine "
                                "which SEC. # sections implement or correspond to a given digest item. "
                                "Your entire response MUST be valid JSON, and nothing else. "
                                "If uncertain, return an empty JSON object like `{}`."
                            )
                        },
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0
                )
                content = completion.choices[0].message.content
                cleaned_content = self._extract_json(content)

                try:
                    data = json.loads(cleaned_content)
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

    def _extract_json(self, text: str) -> str:
        """
        Attempt to isolate the JSON portion of the model's response.
        """
        if not text:
            return "{}"

        text = text.strip().strip("`")
        first_brace_index = text.find("{")
        if first_brace_index == -1:
            return "{}"
        text = text[first_brace_index:]
        last_brace_index = text.rfind("}")
        if last_brace_index == -1:
            return "{}"
        text = text[: last_brace_index + 1]
        if text.strip() == "{}":
            return "{}"
        return text

    def _build_context_prompt(self, digest_info: Dict[str, Any], sections: Dict[str, Dict[str, Any]]) -> str:
        sec_texts = []
        for sid, sinfo in sections.items():
            sec_texts.append(f"SEC. {sid}:\n{sinfo['text']}\n")

        return (
            "Digest Item:\n"
            f"{digest_info['text']}\n\n"
            f"Existing Law:\n{digest_info['existing_law']}\n\n"
            f"Proposed Change:\n{digest_info['proposed_change']}\n\n"
            f"Remaining Bill Sections:\n{''.join(sec_texts)}\n\n"
            "Return a JSON of the form:\n"
            "{\n"
            '  "matches": [\n'
            "    {\n"
            '      "section_id": "string",\n'
            '      "confidence": 0.0,\n'
            '      "evidence": {\n'
            '          "key_terms": ["terms"],\n'
            '          "thematic_match": "explanation"\n'
            "      }\n"
            "    }\n"
            "  ]\n"
            "}\n"
            "If no matches, return:\n"
            "{\n"
            '  "matches": []\n'
            "}\n"
        )

    def _validate_matches(self, matches: List[MatchResult]) -> List[MatchResult]:
        """
        Keep only the highest confidence match if there's a duplicate (digest_id, section_id).
        """
        from collections import defaultdict
        validated = []
        combined = defaultdict(list)
        for m in matches:
            key = (m.digest_id, m.section_id)
            combined[key].append(m)

        for k, result_list in combined.items():
            best = max(result_list, key=lambda x: x.confidence)
            validated.append(best)

        return validated

    def _update_skeleton_with_matches(self, skeleton: Dict[str, Any], matches: List[MatchResult]) -> Dict[str, Any]:
        from collections import defaultdict
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
        Convert code references into a set of "CodeName:section" strings for easier matching.
        """
        pattern = (
            r'(?i)([A-Za-z\s]+Code)\s+Section(?:s)?\s+([\d\.\-\,\s&and]+)|'
            r'Section(?:s)?\s+([\d\.\-\,\s&and]+)\s+of\s+([A-Za-z\s]+Code)'
        )
        result = set()
        matches = re.finditer(pattern, text)
        for match in matches:
            left_code = match.group(1)
            left_secs = match.group(2)
            right_secs = match.group(3)
            right_code = match.group(4)

            if left_code and left_secs:
                code_name = left_code.strip()
                sections_list = self._split_sections(left_secs.strip())
                for sec in sections_list:
                    result.add(f"{code_name}:{sec.strip()}")

            if right_secs and right_code:
                code_name = right_code.strip()
                sections_list = self._split_sections(right_secs.strip())
                for sec in sections_list:
                    result.add(f"{code_name}:{sec.strip()}")
        return result

    def _split_sections(self, sections_str: str) -> List[str]:
        import re
        s = re.sub(r'\s+and\s+', ',', sections_str, flags=re.IGNORECASE)
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
        pattern = r'(?:amends|adds|repeals)\s+Section\s+(\d+(?:\.\d+)?)'
        return re.findall(pattern, text, flags=re.IGNORECASE)

    def _extract_section_numbers(self, text: str) -> Set[str]:
        """
        Extract references to "SEC. X" or "SECTION X" from the digest text.
        We'll store them as { "1", "2", ... } to see if they match any bill section numbers.
        """
        pattern = r'\b(?:SEC\.|SECTION)\s+(\d+)'
        return set(re.findall(pattern, text, flags=re.IGNORECASE))

    def _get_unmatched_digests(self, digest_map: Dict[str, Dict[str, Any]], matches: List[MatchResult]) -> Dict[str, Dict[str, Any]]:
        matched = {m.digest_id for m in matches}
        return {k: v for k, v in digest_map.items() if k not in matched}

    def _get_unmatched_sections(self, section_map: Dict[str, Dict[str, Any]], matches: List[MatchResult]) -> Dict[str, Dict[str, Any]]:
        matched = {m.section_id for m in matches}
        return {k: v for k, v in section_map.items() if k not in matched}
