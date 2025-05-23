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

    def __init__(self, openai_client, model="gpt-4o-2024-08-06", anthropic_client=None):
        self.logger = logging.getLogger(__name__)
        self.openai_client = openai_client
        self.anthropic_client = anthropic_client
        self.model = model
        self.logger.info(f"Initialized SectionMatcher with model: {model}")

        # Determine which API to use based on model name
        self.use_anthropic = model.startswith("claude")
        
        # Cache variables for Anthropic API
        self.digest_cache_created = False
        self.cached_digest_formatted = None  # Will store formatted digest items
        self.cached_digest_map_key = None    # Will store a key to check if the digest map has changed

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
            total_sections = len(section_map) 
            if progress_handler:
                progress_handler.update_progress(
                    4, 
                    "Starting section matching process",
                    0,  # Start at 0
                    total_sections  # Number of sections to process
                )

            # Execute matching strategies in order of reliability
            matches = []
            current_section = 0

            # 1. Exact code reference matching
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

            # 2. Section number matching
            section_matches = self._match_by_section_numbers(digest_map, section_map)
            matches.extend(section_matches)

            current_section += len(section_matches) // 2
            if progress_handler:
                progress_handler.update_substep(
                    current_section,
                    f"Matched {len(section_matches)} section numbers ({current_section}/{total_sections})"
                )

            # 3. Context-based matching for ALL remaining bill sections
            # Get sections that haven't been matched yet
            remaining_sections = self._get_unmatched_sections(section_map, matches)

            if remaining_sections:
                if progress_handler:
                    progress_handler.update_substep(
                        current_section,
                        f"Processing {len(remaining_sections)} remaining sections ({current_section}/{total_sections})"
                    )

                # Process each bill section, matching it to a digest item
                context_matches = []

                # Set up cache tracking for Anthropic
                cache_hits = 0
                total_remainder = len(remaining_sections)

                for i, (section_id, section_info) in enumerate(remaining_sections.items()):
                    section_num = i + 1
                    overall_progress = current_section + section_num

                    if progress_handler:
                        # Update the progress message with specific section information
                        progress_msg = f"Matching bill text section {section_id} ({overall_progress}/{total_sections})"
                        progress_handler.update_substep(
                            overall_progress,
                            progress_msg
                        )

                    # Match this section to the best digest item
                    section_matches = await self._match_section_to_digest(
                        section_id,
                        section_info, 
                        digest_map,
                        bill_text
                    )

                    # Track cache hits for Claude API
                    if self.use_anthropic and self.digest_cache_created and i > 0:
                        cache_hits += 1

                    context_matches.extend(section_matches)

                # Log final cache statistics if using Claude
                if self.use_anthropic and total_remainder > 1:
                    cache_hit_rate = (cache_hits / max(1, total_remainder - 1)) * 100
                    self.logger.info(f"Claude API cache performance: {cache_hits}/{total_remainder-1} sections used cache ({cache_hit_rate:.1f}%)")

                matches.extend(context_matches)
                current_section += len(remaining_sections)

            # Validate and update skeleton with matches
            if progress_handler:
                progress_handler.update_substep(
                    total_sections,
                    f"Finalizing section matching ({total_sections}/{total_sections})"
                )

            validated_matches = self._validate_matches(matches)
            updated_skeleton = self._update_skeleton_with_matches(skeleton, validated_matches)

            # Verify all sections are matched and all digest items have at least one section
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
            self.logger.error(f"Error in section matching: {str(e)}")
            raise

    async def _match_section_to_digest(
        self,
        section_id: str,
        section_info: Dict[str, Any],
        digest_map: Dict[str, Dict[str, Any]],
        bill_text: str
    ) -> List[MatchResult]:
        """Match a single bill section to the appropriate digest item(s)"""
        # Build a prompt that provides all digest sections and the current bill section
        # Note the reversed matching approach compared to the previous implementation
        context_prompt = self._build_reverse_section_prompt(
            section_id,
            section_info,
            digest_map
        )

        # Determine which API to use
        if self.use_anthropic:
            # Using Anthropic API with prompt caching for digest items
            base_system_prompt = (
                "You are analyzing a bill section to determine which digest item it implements. "
                "Each bill section must be matched to exactly one digest item. "
                "Return a JSON object with the best matching digest item and confidence score."
            )

            # Split the context prompt into cacheable (digest items) and non-cacheable parts (bill section)
            prompt_parts = context_prompt.split("Available Digest Items:")
            bill_section_part = prompt_parts[0]  # Contains the bill section to analyze
            digest_items_part = "Available Digest Items:" + prompt_parts[1].split("IMPORTANT REQUIREMENTS:")[0]
            requirements_part = "IMPORTANT REQUIREMENTS:" + prompt_parts[1].split("IMPORTANT REQUIREMENTS:")[1]

            # Check for supported models for caching
            cache_supported = (
                "claude-3-7" in self.model or
                "claude-3-5" in self.model or
                "claude-3" in self.model
            )

            if cache_supported:
                self.logger.info(f"Using Anthropic API with model {self.model} (with prompt caching)")

                # Build system with caching enabled for the digest items
                system_messages = [
                    {
                        "type": "text",
                        "text": base_system_prompt
                    },
                    {
                        "type": "text",
                        "text": digest_items_part,
                        "cache_control": {"type": "ephemeral"}
                    }
                ]

                # Claude-specific parameters with caching
                params = {
                    "model": self.model,
                    "max_tokens": 64000,
                    "system": system_messages,
                    "messages": [
                        {
                            "role": "user", 
                            "content": bill_section_part + requirements_part
                        }
                    ],
                    "stream": True  # Use streaming for long-running operations
                }

                # Set up extended thinking for Claude 3.7 models
                if "claude-3-7" in self.model:
                    params["temperature"] = 1
                    params["thinking"] = {
                        "type": "enabled", 
                        "budget_tokens": 16000
                    }
            else:
                # Fallback to regular API without caching for unsupported models
                self.logger.info(f"Using Anthropic API with model {self.model} (without prompt caching, unsupported model)")

                # Regular parameters without caching
                params = {
                    "model": self.model,
                    "max_tokens": 64000,
                    "system": base_system_prompt,
                    "messages": [{"role": "user", "content": context_prompt}],
                    "stream": True  # Use streaming for long-running operations
                }

                # Set up extended thinking for Claude 3.7 models
                if "claude-3-7" in self.model:
                    params["temperature"] = 1
                    params["thinking"] = {
                        "type": "enabled", 
                        "budget_tokens": 16000
                    }

            # Process the streaming response with retries for Overloaded errors
            response_content = ""
            max_retries = 3
            retry_delay = 2  # Starting delay in seconds

            for retry_attempt in range(max_retries + 1):
                try:
                    # Make the API call
                    stream = await self.anthropic_client.messages.create(**params)

                    # Track cache usage if available
                    if hasattr(stream, 'usage'):
                        usage = stream.usage
                        if hasattr(usage, 'cache_creation_input_tokens') and usage.cache_creation_input_tokens > 0:
                            self.digest_cache_created = True
                            self.logger.info(f"Cache created with {usage.cache_creation_input_tokens} tokens")
                        elif hasattr(usage, 'cache_read_input_tokens') and usage.cache_read_input_tokens > 0:
                            self.logger.info(f"Cache hit: {usage.cache_read_input_tokens} tokens read from cache")

                    # Process streaming response
                    response_content = ""  # Reset for each attempt
                    async for chunk in stream:
                        if hasattr(chunk, 'delta') and hasattr(chunk.delta, 'text'):
                            response_content += chunk.delta.text

                    # If we get here, the API call succeeded
                    break

                except Exception as e:
                    error_str = str(e)
                    is_overloaded = "overloaded_error" in error_str.lower() or "overloaded" in error_str.lower()

                    if is_overloaded and retry_attempt < max_retries:
                        # Only retry on Overloaded errors
                        wait_time = retry_delay * (2 ** retry_attempt)  # Exponential backoff
                        self.logger.warning(f"Anthropic API overloaded, retrying in {wait_time}s (attempt {retry_attempt+1}/{max_retries})")
                        import asyncio
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        # Either not an overloaded error or we've exhausted retries
                        if retry_attempt == max_retries:
                            self.logger.error(f"Error during Anthropic API streaming after {max_retries} retries: {error_str}")
                        else:
                            self.logger.error(f"Error during Anthropic API streaming: {error_str}")

                        # Try falling back to non-streaming for overloaded errors
                        if is_overloaded:
                            self.logger.info("Attempting fallback to non-streaming request...")
                            try:
                                # Clone params but remove streaming
                                non_streaming_params = params.copy()
                                non_streaming_params.pop("stream", None)

                                # Make non-streaming request
                                response = await self.anthropic_client.messages.create(**non_streaming_params)
                                response_content = response.content[0].text
                                self.logger.info("Fallback to non-streaming request successful")
                                break
                            except Exception as fallback_error:
                                self.logger.error(f"Fallback request also failed: {str(fallback_error)}")
                                raise
                        else:
                            raise

            if not response_content:
                self.logger.error("No text content received in Anthropic API response")
                raise ValueError("No text received from Claude API response")

            # Parse the JSON response from the text
            matches_data = self._parse_ai_section_matches(response_content)
        else:
            # Using OpenAI API - No changes needed as OpenAI handles caching internally
            params = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system", 
                        "content": (
                            "You are analyzing a bill section to determine which digest item it implements. "
                            "Each bill section must be matched to exactly one digest item. "
                            "Return a JSON object with the best matching digest item and confidence score."
                        )
                    },
                    {"role": "user", "content": context_prompt}
                ],
                "response_format": {"type": "json_object"}
            }

            # Add model-specific parameters for OpenAI models
            if "o3-mini" in self.model or "o1" in self.model:  # Reasoning models
                self.logger.info(f"Using OpenAI API with reasoning model {self.model}")
                # Use temperature instead of reasoning_effort to avoid compatibility issues
                params["reasoning_effort"] = "high"
            else:  # gpt-4o and other models
                self.logger.info(f"Using OpenAI API with model {self.model}")
                params["temperature"] = 0

            self.logger.info(f"Using OpenAI API with model {self.model}")
            response = await self.openai_client.chat.completions.create(**params)
            matches_data = self._parse_ai_section_matches(response.choices[0].message.content)

        results = []

        for match in matches_data:
            results.append(MatchResult(
                digest_id=match["digest_id"],
                section_id=section_id,
                confidence=match["confidence"],
                match_type="context",
                supporting_evidence=match.get("evidence", {})
            ))

        return results
        
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

        # Determine which API to use
        if self.use_anthropic:
            # Using Anthropic API
            system_prompt = (
                "You are analyzing bill sections to determine which sections "
                "implement specific digest items. Return a JSON object "
                "with matches and confidence scores."
            )

            # Claude-specific parameters
            params = {
                "model": self.model,
                "max_tokens": 64000,
                "system": system_prompt,
                "messages": [{"role": "user", "content": context_prompt}],
                "stream": True  # Use streaming for long-running operations
            }

            # Set up extended thinking for Claude 3.7 models
            if "claude-3-7" in self.model:
                params["temperature"] = 1
                params["thinking"] = {
                    "type": "enabled", 
                    "budget_tokens": 16000
                }

            self.logger.info(f"Using Anthropic API with model {self.model} (streaming enabled)")

            # Process the streaming response
            response_content = ""
            try:
                stream = await self.anthropic_client.messages.create(**params)
                async for chunk in stream:
                    if hasattr(chunk, 'delta') and hasattr(chunk.delta, 'text'):
                        response_content += chunk.delta.text
            except Exception as e:
                self.logger.error(f"Error during Anthropic API streaming: {str(e)}")
                raise

            if not response_content:
                self.logger.error("No text content received in Anthropic streaming response")
                raise ValueError("No text received from Claude API in streaming response")

            # Parse the JSON response from the text
            matches_data = self._parse_ai_matches(response_content)
        else:
            # Using OpenAI API
            params = {
                "model": self.model,
                "messages": [
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
                "response_format": {"type": "json_object"}
            }

            # Add model-specific parameters for OpenAI models
            if self.model.startswith("o"):  # o3-mini or o1 reasoning models
                params["reasoning_effort"] = "high"
            else:  # gpt-4o and other models
                params["temperature"] = 0

            self.logger.info(f"Using OpenAI API with model {self.model}")
            response = await self.openai_client.chat.completions.create(**params)
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

    def _build_section_prompt(self, section_id: str, section_info: Dict[str, Any], digest_map: Dict[str, Dict[str, Any]]) -> str:
        """Build detailed prompt for section to digest matching (LEGACY)"""
        digest_items_formatted = []
        for digest_id, digest_info in digest_map.items():
            # Format each digest item
            item_text = f"Digest Item {digest_id}:\n"
            item_text += f"Text: {digest_info['text']}\n"
            if digest_info.get('existing_law'):
                item_text += f"Existing Law: {digest_info['existing_law']}\n"
            if digest_info.get('proposed_change'):
                item_text += f"Proposed Change: {digest_info['proposed_change']}\n"
            digest_items_formatted.append(item_text)
        
        # Join all digest items
        all_digest_items = "\n".join(digest_items_formatted)
        
        return f"""Determine which digest item this bill section best implements:

    Bill Section {section_id}:
    {section_info['text']}

    Available Digest Items:
    {all_digest_items}

    IMPORTANT: Select the SINGLE best matching digest item for this section. Choose only the one digest item that most directly corresponds to this bill section.

    Analyze the text carefully and return your match in this JSON format:
    {{
        "matches": [
            {{
                "digest_id": "digest item id (e.g. 'change_1')",
                "confidence": float,
                "evidence": {{
                    "key_terms": ["matched terms"],
                    "thematic_match": "explanation",
                    "action_alignment": "explanation"
                }}
            }}
        ]
    }}"""
    
    def _format_digest_items(self, digest_map: Dict[str, Dict[str, Any]]) -> str:
        """
        Format digest items into a single string for prompts
        This is separated to support caching
        """
        digest_items_formatted = []
        for digest_id, digest_info in digest_map.items():
            # Format each digest item
            item_text = f"Digest Item {digest_id}:\n"
            item_text += f"Text: {digest_info['text']}\n"
            if digest_info.get('existing_law'):
                item_text += f"Existing Law: {digest_info['existing_law']}\n"
            if digest_info.get('proposed_change'):
                item_text += f"Proposed Change: {digest_info['proposed_change']}\n"
            digest_items_formatted.append(item_text)
        
        # Join all digest items
        return "\n".join(digest_items_formatted)
        
    def _get_digest_map_key(self, digest_map: Dict[str, Dict[str, Any]]) -> str:
        """Generate a key to identify if digest map has changed"""
        # Simple key generation - hash the digest IDs and lengths of their content
        # This is a quick way to check if the digest map might have changed
        digest_keys = sorted(digest_map.keys())
        key_parts = []
        for did in digest_keys:
            info = digest_map[did]
            # Create a signature based on text lengths
            sig = f"{did}:{len(info.get('text', ''))}:{len(info.get('existing_law', ''))}"
            key_parts.append(sig)
        return "|".join(key_parts)

    def _build_reverse_section_prompt(self, section_id: str, section_info: Dict[str, Any], digest_map: Dict[str, Dict[str, Any]]) -> str:
        """
        Build prompt for the reversed matching approach - one bill section matched to all digest items
        This ensures each bill section is matched to a digest item
        """
        # Format the digest items and cache for re-use
        digest_map_key = self._get_digest_map_key(digest_map)
        if not self.cached_digest_formatted or digest_map_key != self.cached_digest_map_key:
            self.cached_digest_formatted = self._format_digest_items(digest_map)
            self.cached_digest_map_key = digest_map_key
            self.digest_cache_created = False  # Need to create a new cache with Claude
        
        all_digest_items = self.cached_digest_formatted
        
        return f"""Identify which digest item is best implemented by this bill section:

    Bill Section {section_id}:
    {section_info['text']}

    Available Digest Items:
    {all_digest_items}

    IMPORTANT REQUIREMENTS:
    1. Every bill section MUST be matched to exactly ONE digest item
    2. Choose the SINGLE digest item that best corresponds to this bill section
    3. Even if the match isn't perfect, select the best possible digest item

    This bill section is making a change to the law. Your task is to determine which digest item 
    best describes the change being made by this section.

    Analyze the text carefully and return your match in this JSON format:
    {{
        "matches": [
            {{
                "digest_id": "digest item id (e.g. 'change_1')",
                "confidence": float,
                "evidence": {{
                    "key_terms": ["matched terms"],
                    "thematic_match": "explanation",
                    "action_alignment": "explanation"
                }}
            }}
        ]
    }}"""

    def _build_context_prompt(self, digest_info: Dict[str, Any], sections: Dict[str, Dict[str, Any]], bill_text: str) -> str:
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

    IMPORTANT: When referring to sections, use just the number (e.g., "1", "7") not the full label.

    Analyze the text and return matches in this JSON format:
    {{
        "matches": [
            {{
                "section_id": "section number (just the number, e.g. '7')",
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

    def _parse_ai_section_matches(self, content: str) -> List[Dict[str, Any]]:
        """Parse section-to-digest matches from AI response"""
        try:
            # For Claude responses, we may need to extract JSON from a text response
            if self.use_anthropic:
                # First try direct JSON loading
                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    # Try to extract JSON from text
                    self.logger.warning(f"Invalid JSON from Claude, attempting to extract JSON: {content[:200]}...")
                    json_start = content.find('{')
                    json_end = content.rfind('}') + 1
                    if json_start >= 0 and json_end > json_start:
                        clean_json = content[json_start:json_end]
                        data = json.loads(clean_json)
                    else:
                        raise ValueError("Cannot extract JSON from Claude response")
            else:
                # For OpenAI, we expect clean JSON
                data = json.loads(content)

            return data.get("matches", [])
        except Exception as e:
            self.logger.error(f"Error parsing AI section matches: {str(e)}")
            return []
            
    def _parse_ai_matches(self, content: str) -> List[Dict[str, Any]]:
        """Parse matches from AI response"""
        try:
            # For Claude responses, we may need to extract JSON from a text response
            if self.use_anthropic:
                # First try direct JSON loading
                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    # Try to extract JSON from text
                    self.logger.warning(f"Invalid JSON from Claude, attempting to extract JSON: {content[:200]}...")
                    json_start = content.find('{')
                    json_end = content.rfind('}') + 1
                    if json_start >= 0 and json_end > json_start:
                        clean_json = content[json_start:json_end]
                        data = json.loads(clean_json)
                    else:
                        raise ValueError("Cannot extract JSON from Claude response")
            else:
                # For OpenAI, we expect clean JSON
                data = json.loads(content)

            return data.get("matches", [])
        except Exception as e:
            self.logger.error(f"Error parsing AI matches: {str(e)}")
            return []

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
            self.logger.error("With the reverse matching approach, all bill sections should be matched to a digest item.")
            raise ValueError(f"Failed to match {len(unmatched_sections)} bill sections")
            
        # Check for unmatched digest items - this is allowed but we'll log it
        unmatched_digests = []
        for change in skeleton["changes"]:
            if not change.get("bill_sections"):
                unmatched_digests.append(change["id"])

        if unmatched_digests:
            self.logger.warning(f"Note: {len(unmatched_digests)} digest items have no matching bill sections: {', '.join(unmatched_digests)}")

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