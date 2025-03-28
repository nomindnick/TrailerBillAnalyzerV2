from typing import Dict, List, Any, Set, Tuple, Optional
import re
import logging
from dataclasses import dataclass
from collections import defaultdict
import numpy as np
import asyncio
import json

from src.services.embeddings_service import EmbeddingsService


@dataclass
class MatchResult:
    """Represents a match between digest and bill sections with confidence score"""
    digest_id: str
    section_id: str
    confidence: float
    match_type: str  # 'embedding', 'code_ref', 'section_ref', 'fallback'
    supporting_evidence: Dict[str, Any]


class EmbeddingsMatcher:
    """
    Enhanced matcher using embeddings to link digest items to bill sections
    with traditional text-based matching as a fallback.
    """

    def __init__(
        self, 
        openai_client, 
        embedding_model="text-embedding-3-large", 
        embedding_dimensions=1024
    ):
        self.logger = logging.getLogger(__name__)
        self.openai_client = openai_client
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions

        # Initialize the embedding service
        self.embeddings_service = EmbeddingsService(
            openai_client, 
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions
        )

        self.logger.info(f"Initialized EmbeddingsMatcher with model: {embedding_model}")

    async def match_sections(self, skeleton: Dict[str, Any], bill_text: str, progress_handler=None) -> Dict[str, Any]:
        """
        Main matching function using multiple strategies with embeddings as primary approach

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
            total_sections = len(section_map) 
            if progress_handler:
                progress_handler.update_progress(
                    4, 
                    "Starting section matching process using embeddings",
                    0,  # Start at 0
                    total_sections  # Number of sections to process
                )

            # Execute matching strategies in order of reliability
            matches = []
            current_section = 0

            # 1. Direct code reference matching (deterministic, no embeddings needed)
            if progress_handler:
                progress_handler.update_substep(
                    current_section,
                    f"Identifying sections by code references (0/{total_sections})"
                )

            code_matches = self._match_by_code_references(digest_map, section_map)
            matches.extend(code_matches)

            current_section += len(code_matches) // 2
            if progress_handler:
                progress_handler.update_substep(
                    current_section,
                    f"Matched {len(code_matches)} references ({current_section}/{total_sections})"
                )

            # 2. Direct section number matching (deterministic, no embeddings needed)
            section_matches = self._match_by_section_numbers(digest_map, section_map)
            matches.extend(section_matches)

            current_section += len(section_matches) // 2
            if progress_handler:
                progress_handler.update_substep(
                    current_section,
                    f"Matched {len(section_matches)} section numbers ({current_section}/{total_sections})"
                )

            # 3. Embeddings-based matching (for remaining unmatched sections)
            unmatched_sections = self._get_unmatched_sections(section_map, matches)
            unmatched_digests = self._get_unmatched_digests(digest_map, matches)

            if unmatched_sections:
                if progress_handler:
                    progress_handler.update_substep(
                        current_section,
                        f"Processing {len(unmatched_sections)} remaining sections with embeddings ({current_section}/{total_sections})"
                    )

                embedding_matches = await self._match_by_embeddings(
                    unmatched_digests, 
                    unmatched_sections,
                    progress_handler
                )
                matches.extend(embedding_matches)

                current_section += len(unmatched_sections)
                if progress_handler:
                    progress_handler.update_substep(
                        current_section,
                        f"Matched {len(embedding_matches)} sections using embeddings ({current_section}/{total_sections})"
                    )

            # Validate and update skeleton with matches
            if progress_handler:
                progress_handler.update_substep(
                    total_sections,
                    f"Finalizing section matching ({total_sections}/{total_sections})"
                )

            validated_matches = self._validate_matches(matches)
            updated_skeleton = self._update_skeleton_with_matches(skeleton, validated_matches)

            # Verify all sections are matched to at least one digest item
            self._verify_complete_matching(updated_skeleton, section_map)

            # Final progress update
            if progress_handler:
                progress_handler.update_progress(
                    4, 
                    f"Section matching complete - {len(validated_matches)} matches found",
                    total_sections,
                    total_sections
                )

            return updated_skeleton

        except Exception as e:
            self.logger.error(f"Error in embeddings-based section matching: {str(e)}")
            raise

    async def _match_by_embeddings(
        self,
        unmatched_digests: Dict[str, Dict[str, Any]],
        unmatched_sections: Dict[str, Dict[str, Any]],
        progress_handler=None
    ) -> List[MatchResult]:
        """
        Match unmatched sections to digest items using embeddings

        Args:
            unmatched_digests: Dict of unmatched digest items
            unmatched_sections: Dict of unmatched bill sections
            progress_handler: Optional progress handler

        Returns:
            List of MatchResult objects representing matches
        """
        # Early exit if nothing to match
        if not unmatched_digests or not unmatched_sections:
            return []

        matches = []

        try:
            # 1. Prepare the texts for embedding
            digest_ids = list(unmatched_digests.keys())
            digest_texts = []

            # Combine important information for each digest item
            for digest_id in digest_ids:
                digest_info = unmatched_digests[digest_id]
                combined_text = (
                    f"{digest_info['text']} "
                    f"{digest_info.get('existing_law', '')} "
                    f"{digest_info.get('proposed_change', '')}"
                )
                digest_texts.append(combined_text)

            section_ids = list(unmatched_sections.keys())
            section_texts = [unmatched_sections[sec_id]["text"] for sec_id in section_ids]

            # 2. Generate embeddings for all texts
            self.logger.info(f"Generating embeddings for {len(digest_texts)} digest items and {len(section_texts)} bill sections")

            # Get embeddings in parallel
            digest_embeddings = await self.embeddings_service.get_embeddings_batch(digest_texts)
            section_embeddings = await self.embeddings_service.get_embeddings_batch(section_texts)

            # 3. Calculate the similarity matrix between all digest items and bill sections
            self.logger.info("Calculating similarity matrix")

            # For each section, find best matching digest
            best_digest_matches = {}  # Maps section_id to (digest_id, score)

            for i, section_id in enumerate(section_ids):
                section_embedding = section_embeddings[i]

                # Find top matches for this section
                best_matches = await self.embeddings_service.find_best_matches_from_embeddings(
                    section_embedding,
                    digest_embeddings,
                    top_n=2  # Get top 2 to have a fallback
                )

                if best_matches:
                    top_match_idx, top_match_score = best_matches[0]
                    digest_id = digest_ids[top_match_idx]

                    # Only consider as a match if the score is good enough
                    if top_match_score >= 0.6:  # Minimum threshold for a good match
                        best_digest_matches[section_id] = (digest_id, top_match_score)

                        # Create a match result
                        matches.append(MatchResult(
                            digest_id=digest_id,
                            section_id=section_id,
                            confidence=min(0.95, top_match_score),  # Cap at 0.95 (not 100% certain)
                            match_type="embedding",
                            supporting_evidence={
                                "similarity_score": top_match_score,
                                "digest_text_preview": digest_texts[top_match_idx][:100] + "...",
                                "section_text_preview": section_texts[i][:100] + "..."
                            }
                        ))

                        self.logger.debug(f"Embedding match: Section {section_id} -> Digest {digest_id} (score: {top_match_score:.4f})")

            # 4. Handle sections with no good match - pick the best available digest
            for i, section_id in enumerate(section_ids):
                if section_id not in best_digest_matches:
                    # For remaining unmatched sections, find best digest even if score is low
                    section_embedding = section_embeddings[i]
                    best_matches = await self.embeddings_service.find_best_matches_from_embeddings(
                        section_embedding,
                        digest_embeddings,
                        top_n=1
                    )

                    if best_matches:
                        top_match_idx, top_match_score = best_matches[0]
                        digest_id = digest_ids[top_match_idx]

                        matches.append(MatchResult(
                            digest_id=digest_id,
                            section_id=section_id,
                            confidence=max(0.5, top_match_score),  # Minimum confidence of 0.5
                            match_type="embedding_fallback",
                            supporting_evidence={
                                "similarity_score": top_match_score,
                                "fallback": True,
                                "note": "Low confidence match"
                            }
                        ))

                        self.logger.debug(f"Fallback embedding match: Section {section_id} -> Digest {digest_id} (score: {top_match_score:.4f})")

            self.logger.info(f"Found {len(matches)} matches using embeddings")
            return matches

        except Exception as e:
            self.logger.error(f"Error in embeddings matching: {str(e)}")
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
        """
        Extract and structure bill sections with enhanced pattern matching for challenging formats.
        """
        section_map = {}
        self.logger.info(f"Extracting bill sections from text of length {len(bill_text)}")

        # Apply aggressive normalization to fix decimal point issues
        normalized_text = self._aggressive_normalize(bill_text)

        # Try multiple section patterns with increasing flexibility
        section_patterns = [
            # Pattern 1: Standard format with newline
            r'(?:^|\n)\s*(?P<label>(?:SECTION|SEC)\.?\s+(?P<number>\d+)\.)\s*(?P<text>(?:.+?)(?=\n\s*(?:SECTION|SEC)\.?\s+\d+\.|\Z))',

            # Pattern 2: More flexible with optional whitespace
            r'(?:^|\n)\s*(?P<label>(?:SECTION|SEC)\.?\s*(?P<number>\d+)\.)\s*(?P<text>(?:.+?)(?=\n\s*(?:SECTION|SEC)\.?\s*\d+\.|\Z))',

            # Pattern 3: Force matches at "SEC. X." regardless of surrounding context
            r'\n\s*(?P<label>SEC\.\s+(?P<number>\d+)\.)\s*(?P<text>(?:.+?)(?=\n\s*SEC\.\s+\d+\.|\Z))',
        ]

        # Try each pattern
        all_matches = []
        successful_pattern = None

        for i, pattern in enumerate(section_patterns):
            matches = list(re.finditer(pattern, normalized_text, re.DOTALL | re.MULTILINE | re.IGNORECASE))

            if matches:
                all_matches = matches
                successful_pattern = i+1
                break

        if not all_matches:
            self.logger.warning("Standard patterns failed, attempting direct section extraction")
            # Direct approach - find all "SEC. X." headers and extract content between them
            section_headers = re.findall(r'\n\s*(SEC\.\s+(\d+)\.)', normalized_text)
            self.logger.info(f"Found {len(section_headers)} section headers directly")

            if section_headers:
                # Manual extraction between headers
                for i, (header, number) in enumerate(section_headers):
                    start_pos = normalized_text.find(header) + len(header)

                    # Find the end by looking for the next section header or end of text
                    if i < len(section_headers) - 1:
                        next_header = section_headers[i+1][0]
                        end_pos = normalized_text.find(next_header)
                    else:
                        end_pos = len(normalized_text)

                    section_text = normalized_text[start_pos:end_pos].strip()

                    # Create a simple mock match object
                    class SimpleMatch:
                        def group(self, name):
                            if name == 'label': return header
                            if name == 'number': return number
                            if name == 'text': return section_text
                            return None

                    all_matches.append(SimpleMatch())

        # Process matches
        for match in all_matches:
            section_num = match.group('number')
            section_text = match.group('text').strip()
            section_label = match.group('label').strip()

            # Skip empty sections
            if not section_text:
                self.logger.warning(f"Empty text for section {section_num}, skipping")
                continue

            # Log the beginning of the section text
            self.logger.debug(f"Section {section_num} begins with: {section_text[:100]}...")

            # Extract code references with special handling for decimal points
            code_refs = self._extract_code_references_robust(section_text)

            section_map[section_num] = {
                "text": section_text,
                "original_label": section_label,
                "code_refs": code_refs,
                "action_type": self._determine_action_type(section_text),
                "code_sections": self._extract_modified_sections(section_text)
            }

            # Log code references found if any
            if code_refs:
                self.logger.info(f"Section {section_num} has code references: {list(code_refs)}")

        self.logger.info(f"Successfully extracted {len(section_map)} bill sections: {list(section_map.keys())}")
        return section_map

    def _aggressive_normalize(self, text: str) -> str:
        """
        Aggressively normalize text to fix common issues with bill formatting,
        especially handling decimal points in section numbers.
        """
        # Replace Windows line endings
        text = text.replace('\r\n', '\n')

        # Ensure consistent spacing around section headers
        text = re.sub(r'(\n\s*)(SEC\.?|SECTION)(\s*)(\d+)(\.\s*)', r'\n\2 \4\5', text)

        # Fix the decimal point issue - remove line breaks between section numbers and decimal points
        text = re.sub(r'(\d+)\s*\n\s*(\.\d+)', r'\1\2', text)

        # Standardize decimal points in section headers
        text = re.sub(r'Section\s+(\d+)\s*\n\s*(\.\d+)', r'Section \1\2', text)

        # Ensure section headers are properly separated with newlines
        text = re.sub(r'([^\n])(SEC\.|SECTION)', r'\1\n\2', text)

        return text

    def _extract_code_references_robust(self, text: str) -> Set[str]:
        """
        Extract code references with special handling for decimal points and other formatting issues.
        """
        references = set()

        # Check first for the amended/added/repealed pattern that's common in section headers
        first_line = text.split('\n', 1)[0] if '\n' in text else text

        # Normalize the section number if it contains a decimal point
        first_line = re.sub(r'(\d+)\s*\n\s*(\.\d+)', r'\1\2', first_line)

        # Pattern for "Section X of the Y Code is amended/added/repealed"
        section_header_pattern = r'(?i)Section\s+(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        header_match = re.search(section_header_pattern, first_line)

        if header_match:
            section_num = header_match.group(1).strip()
            code_name = header_match.group(2).strip()
            references.add(f"{code_name} Section {section_num}")
            self.logger.info(f"Found primary code reference: {code_name} Section {section_num}")

        # Special case for Education Code sections with decimal points
        # This handles cases like "Section 2575.2 of the Education Code"
        decimal_pattern = r'Section\s+(\d+\.\d+)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        for match in re.finditer(decimal_pattern, text):
            section_num = match.group(1).strip()
            code_name = match.group(2).strip()
            references.add(f"{code_name} Section {section_num}")

        # Handle other standard reference formats
        patterns = [
            # Standard format: "Section 123 of the Education Code"
            r'(?i)Section(?:s)?\s+(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)',

            # Reverse format: "Education Code Section 123"
            r'(?i)([A-Za-z\s]+Code)\s+Section(?:s)?\s+(\d+(?:\.\d+)?)',
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text):
                if len(match.groups()) == 2:
                    if "code" in match.group(2).lower():  # Standard format
                        section_num = match.group(1).strip()
                        code_name = match.group(2).strip()
                    else:  # Reverse format
                        code_name = match.group(1).strip()
                        section_num = match.group(2).strip()

                    references.add(f"{code_name} Section {section_num}")

        return references

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
                        match_type="section_ref",
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

    def _extract_code_references(self, text: str) -> Set[str]:
        """
        Extract code references with improved pattern matching for various formats.

        Args:
            text: The section text to search for code references

        Returns:
            Set of code references in standardized format
        """
        references = set()

        # First check the first line, which often contains the primary code reference
        first_line = text.split('\n')[0] if '\n' in text else text

        # Pattern for "Section X of the Y Code is amended/added/repealed"
        section_header_pattern = r'(?i)Section\s+(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)\s+(?:is|are)'
        header_match = re.search(section_header_pattern, first_line)

        if header_match:
            section_num = header_match.group(1).strip()
            code_name = header_match.group(2).strip()
            references.add(f"{code_name} Section {section_num}")
            self.logger.debug(f"Found primary code reference: {code_name} Section {section_num}")

        # Various patterns for code references
        patterns = [
            # Standard format: "Section 123 of the Education Code"
            r'(?i)Section(?:s)?\s+(\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)',

            # Reverse format: "Education Code Section 123"
            r'(?i)([A-Za-z\s]+Code)\s+Section(?:s)?\s+(\d+(?:\.\d+)?(?:\s*,\s*\d+(?:\.\d+)?)*)',

            # Range format: "Sections 123-128 of the Education Code"
            r'(?i)Section(?:s)?\s+(\d+(?:\.\d+)?)\s*(?:to|through|-)\s*(\d+(?:\.\d+)?)\s+of\s+(?:the\s+)?([A-Za-z\s]+Code)'
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                if len(match.groups()) == 2:  # Standard or reverse format
                    if "code" in match.group(2).lower():  # "Section X of Y Code" format
                        sections_str, code_name = match.groups()
                        for section in re.split(r'[,\s]+', sections_str):
                            if section.strip() and section.strip().isdigit():
                                references.add(f"{code_name.strip()} Section {section.strip()}")
                    else:  # "Y Code Section X" format
                        code_name, sections_str = match.groups()
                        for section in re.split(r'[,\s]+', sections_str):
                            if section.strip() and section.strip().isdigit():
                                references.add(f"{code_name.strip()} Section {section.strip()}")
                elif len(match.groups()) == 3:  # Range format
                    start, end, code = match.groups()
                    try:
                        for num in range(int(float(start)), int(float(end)) + 1):
                            references.add(f"{code.strip()} Section {num}")
                    except (ValueError, TypeError):
                        # If we can't convert to numbers, just add the endpoints
                        references.add(f"{code.strip()} Section {start.strip()}")
                        references.add(f"{code.strip()} Section {end.strip()}")

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
            numbers.add("1")  # Return just the number

        # Match other sections
        for match in re.finditer(section_patterns[1], text, re.IGNORECASE):
            numbers.add(match.group(1))  # Return just the number

        return numbers

    def _validate_matches(self, matches: List[MatchResult]) -> List[MatchResult]:
        """
        Validate matches and resolve conflicts
        Under the reverse matching approach, each bill section should match to exactly one digest item
        """
        validated = []
        seen_sections = defaultdict(list)

        # Group matches by section
        for match in matches:
            seen_sections[match.section_id].append(match)

        # Process each section
        for section_id, section_matches in seen_sections.items():
            if len(section_matches) == 1:
                # Only one match for this section - perfect
                validated.append(section_matches[0])
            else:
                # Multiple matches for this section - keep highest confidence
                best_match = max(section_matches, key=lambda m: m.confidence)
                self.logger.info(f"Section {section_id} had {len(section_matches)} matches - keeping highest confidence match to digest {best_match.digest_id}")
                validated.append(best_match)

        # Log sections with no matches - this shouldn't happen with the new approach
        # but we'll keep this check for robustness
        all_section_ids = {match.section_id for match in matches}
        if len(all_section_ids) < sum(1 for _ in seen_sections):
            self.logger.warning(f"Some sections have no matches after validation - this shouldn't happen")

        return validated

    def _update_skeleton_with_matches(self, skeleton: Dict[str, Any], matches: List[MatchResult]) -> Dict[str, Any]:
        """Update the skeleton with match information"""
        digest_matches = defaultdict(list)
        for match in matches:
            digest_matches[match.digest_id].append(match)

        for change in skeleton["changes"]:
            change_matches = digest_matches.get(change["id"], [])
            # Store just the section numbers in the bill_sections field
            section_ids = []
            for m in change_matches:
                # Make sure we're storing just the number, not 'Section X'
                section_ids.append(m.section_id)

            change["bill_sections"] = section_ids

            # Additional information can be stored here
            if change_matches:
                change["matching_confidence"] = max(m.confidence for m in change_matches)
                best_match = max(change_matches, key=lambda m: m.confidence)
                change["matching_evidence"] = {
                    "type": best_match.match_type,
                    "details": best_match.supporting_evidence
                }

        return skeleton

    def _verify_complete_matching(self, skeleton: Dict[str, Any], section_map: Dict[str, Dict[str, Any]]) -> None:
        """
        Verify all bill sections are matched to a digest item
        With the reverse matching approach, each bill section should be matched to exactly one digest item,
        but some digest items may not have matches.
        """
        # Check for unmatched bill sections
        all_matched_sections = set()
        for change in skeleton["changes"]:
            all_matched_sections.update(change.get("bill_sections", []))

        unmatched_sections = set(section_map.keys()) - all_matched_sections

        if unmatched_sections:
            self.logger.error(f"Unmatched bill sections: {', '.join(unmatched_sections)}")
            self.logger.error("With the embeddings matching approach, all bill sections should be matched to a digest item.")
            raise ValueError(f"Failed to match {len(unmatched_sections)} bill sections")

        # Check for unmatched digest items - this is allowed but we'll log it
        unmatched_digests = []
        for change in skeleton["changes"]:
            if not change.get("bill_sections"):
                unmatched_digests.append(change["id"])

        if unmatched_digests:
            self.logger.warning(f"Note: {len(unmatched_digests)} digest items have no matching bill sections: {', '.join(unmatched_digests)}")