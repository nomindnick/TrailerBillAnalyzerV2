import logging
import json
import re
import asyncio
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Tuple, Set
from collections import defaultdict

from src.services.embeddings_service import EmbeddingsService
from src.models.practice_groups import PracticeGroups, PracticeGroupRelevance
from src.models.agency_types import AgencyTypes, AgencyImpactLevel


@dataclass
class AgencyImpact:
    """Represents specific impact on local agencies"""
    agency_type: str
    impact_type: str
    description: str
    deadline: Optional[datetime] = None
    requirements: List[str] = None


@dataclass
class ChangeAnalysis:
    """Represents analysis of a legislative change"""
    summary: str
    impacts: List[AgencyImpact]
    practice_groups: List[Dict[str, str]]
    action_items: List[str]
    deadlines: List[Dict[str, Any]]
    requirements: List[str]


class EmbeddingsImpactAnalyzer:
    """
    Enhanced analyzer for determining local agency impacts using embeddings for
    practice group and agency type identification, with LLM used only for detailed analysis.
    """

    def __init__(
        self, 
        openai_client, 
        practice_groups_data: PracticeGroups,
        embedding_model="text-embedding-3-large", 
        llm_model="gpt-4o-2024-08-06", 
        anthropic_client=None
    ):
        self.logger = logging.getLogger(__name__)
        self.openai_client = openai_client
        self.anthropic_client = anthropic_client
        self.practice_groups = practice_groups_data
        self.agency_types = AgencyTypes()

        # Set up embedding service
        self.embedding_model = embedding_model
        self.embeddings_service = EmbeddingsService(
            openai_client,
            embedding_model=embedding_model,
            embedding_dimensions=768  # Use lower dimension for these simpler classifications
        )

        # Set up LLM model for detailed analysis
        self.llm_model = llm_model
        self.use_anthropic = llm_model.startswith("claude")

        # Similarity thresholds for classification
        self.practice_group_threshold = 0.7  # Threshold for primary practice group
        self.practice_group_secondary_threshold = 0.62  # Threshold for secondary practice group
        self.agency_impact_threshold = 0.68  # Threshold for detecting agency impact

        self.logger.info(f"Initialized EmbeddingsImpactAnalyzer with embedding model: {embedding_model} and LLM model: {llm_model}")

        # Cache the practice group embeddings
        self.practice_group_embeddings = None
        self.practice_group_names = None
        self.agency_type_embeddings = None
        self.agency_type_names = None

    async def analyze_changes(
        self,
        skeleton: Dict[str, Any],
        progress_handler=None
    ) -> Dict[str, Any]:
        """
        Analyze changes with enhanced impact detection and progress reporting
        """
        try:
            total_changes = len(skeleton["changes"])

            if progress_handler:
                progress_handler.update_progress(
                    5,  # Step 5 for impact analysis
                    "Starting impact analysis for local agencies",
                    0,  # Start at 0
                    total_changes
                )

            # Initialize the embeddings for practice groups and agency types (one-time)
            await self._initialize_embeddings()

            for i, change in enumerate(skeleton["changes"]):
                current_change = i + 1  # Human-readable count (1-based)

                if progress_handler:
                    progress_handler.update_substep(
                        current_change,
                        f"Analyzing substantive change {current_change} of {total_changes}"
                    )

                # Get bill sections for this change
                sections = self._get_linked_sections(change, skeleton)
                code_mods = self._get_code_modifications(change, skeleton)
                change["bill_section_details"] = sections

                # Before starting analysis, update with more specific info
                if progress_handler:
                    # Include the digest text preview for better context
                    digest_preview = change['digest_text'][:60] + "..." if len(change['digest_text']) > 60 else change['digest_text']
                    progress_handler.update_substep(
                        current_change,
                        f"Processing change {current_change}/{total_changes}: {digest_preview}"
                    )

                # 1. Identify practice groups using embeddings
                await self._identify_practice_groups(change, sections)

                # 2. Identify impacted agency types using embeddings
                impacted_agencies = await self._identify_impacted_agencies(change, sections)

                # Store agency impact results
                if impacted_agencies:
                    change["impacts_local_agencies"] = True
                    change["local_agencies_impacted"] = impacted_agencies
                else:
                    change["impacts_local_agencies"] = False
                    change["local_agencies_impacted"] = []

                # Only perform detailed LLM analysis if there's a local agency impact
                if change["impacts_local_agencies"]:
                    # 3. Generate detailed impact analysis using LLM
                    analysis = await self._analyze_change_with_llm(change, sections, code_mods, skeleton)
                    self._update_change_with_analysis(change, analysis)
                else:
                    # For non-impacted changes, create minimal analysis
                    self._create_minimal_analysis(change)

                # After analysis completed, update progress with completion info
                if progress_handler:
                    # Get the count of affected agencies for the status message
                    agency_count = len(impacted_agencies)
                    agency_msg = f"{agency_count} agencies affected" if agency_count > 0 else "No agencies affected"

                    progress_handler.update_substep(
                        current_change,
                        f"Completed change {current_change}/{total_changes} ({agency_msg})"
                    )

            # Update overall metadata of the skeleton
            self._update_skeleton_metadata(skeleton)

            if progress_handler:
                progress_handler.update_substep(
                    total_changes,
                    f"Impact analysis complete ({total_changes}/{total_changes})"
                )

            return skeleton

        except Exception as e:
            self.logger.error(f"Error analyzing changes: {str(e)}")
            raise

    async def _initialize_embeddings(self):
        """Initialize the embeddings for practice groups and agency types"""
        if self.practice_group_embeddings is None:
            # Format practice groups for embedding
            practice_group_data = []
            practice_group_names = []

            for group_name, group in self.practice_groups.groups.items():
                practice_group_data.append(group.format_for_prompt())
                practice_group_names.append(group_name)

            # Generate embeddings for all practice groups
            self.logger.info(f"Generating embeddings for {len(practice_group_data)} practice groups")
            self.practice_group_embeddings = await self.embeddings_service.get_embeddings_batch(practice_group_data)
            self.practice_group_names = practice_group_names

        if self.agency_type_embeddings is None:
            # Format agency types for embedding
            agency_type_data = self.agency_types.get_all_formatted_for_embedding()
            agency_type_names = list(self.agency_types.agency_names)

            # Generate embeddings for all agency types
            self.logger.info(f"Generating embeddings for {len(agency_type_data)} agency types")
            self.agency_type_embeddings = await self.embeddings_service.get_embeddings_batch(agency_type_data)
            self.agency_type_names = agency_type_names

    async def _identify_practice_groups(self, change: Dict[str, Any], sections: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """
        Identify relevant practice groups using embeddings

        Args:
            change: The change object to analyze
            sections: Bill sections implementing this change

        Returns:
            List of practice group information
        """
        # Combine text from change and sections for embedding
        combined_text = f"{change['digest_text']} {change.get('existing_law', '')} {change.get('proposed_change', '')}"

        # Add section texts if available
        for section in sections:
            combined_text += f" {section.get('text', '')}"

        # Generate embedding for the combined text
        text_embedding = await self.embeddings_service.get_embedding(combined_text)

        # Calculate similarity with all practice groups
        similarities = []
        for i, pg_embedding in enumerate(self.practice_group_embeddings):
            similarity = self.embeddings_service.cosine_similarity(text_embedding, pg_embedding)
            similarities.append((self.practice_group_names[i], similarity))

        # Sort by similarity (highest first)
        similarities.sort(key=lambda x: x[1], reverse=True)

        # Determine primary and secondary practice groups
        practice_groups_result = []

        # The most similar group above threshold is primary
        if similarities and similarities[0][1] >= self.practice_group_threshold:
            primary_group = similarities[0][0]
            practice_groups_result.append({
                "name": primary_group,
                "relevance": "primary",
                "justification": f"This change most directly relates to {primary_group} practices and requirements."
            })

            # Add secondary groups that are above secondary threshold but not the primary
            for group_name, score in similarities[1:]:
                if score >= self.practice_group_secondary_threshold:
                    practice_groups_result.append({
                        "name": group_name,
                        "relevance": "secondary",
                        "justification": f"This change has secondary implications for {group_name} practices."
                    })

                    # Limit to at most 2 secondary groups
                    if len(practice_groups_result) >= 3:
                        break

        # Store the result in the change object
        change["practice_groups"] = practice_groups_result

        return practice_groups_result

    async def _identify_impacted_agencies(self, change: Dict[str, Any], sections: List[Dict[str, Any]]) -> List[str]:
        """
        Identify local agency types impacted by this change using embeddings

        Args:
            change: The change object to analyze
            sections: Bill sections implementing this change

        Returns:
            List of impacted agency type names
        """
        # Combine text from change and sections for embedding
        combined_text = f"{change['digest_text']} {change.get('existing_law', '')} {change.get('proposed_change', '')}"

        # Add section texts if available
        for section in sections:
            combined_text += f" {section.get('text', '')}"

        # Generate embedding for the combined text
        text_embedding = await self.embeddings_service.get_embedding(combined_text)

        # Calculate similarity with all agency types
        similarities = []
        for i, agency_embedding in enumerate(self.agency_type_embeddings):
            similarity = self.embeddings_service.cosine_similarity(text_embedding, agency_embedding)
            agency_name = self.agency_type_names[i]

            # Skip "No Local Agency Impact" for individual matching
            if agency_name != "No Local Agency Impact":
                similarities.append((agency_name, similarity))

        # Sort by similarity (highest first)
        similarities.sort(key=lambda x: x[1], reverse=True)

        # Check if no agency impact is the highest match
        no_impact_idx = self.agency_type_names.index("No Local Agency Impact")
        no_impact_similarity = self.embeddings_service.cosine_similarity(
            text_embedding, 
            self.agency_type_embeddings[no_impact_idx]
        )

        # If "No Local Agency Impact" has the highest similarity above threshold,
        # return empty list (no agencies impacted)
        highest_agency_similarity = similarities[0][1] if similarities else 0
        if no_impact_similarity > highest_agency_similarity and no_impact_similarity > self.agency_impact_threshold:
            return []

        # Otherwise, return all agency types with similarity above threshold
        impacted_agencies = [
            agency_name for agency_name, score in similarities 
            if score >= self.agency_impact_threshold
        ]

        # Always include at least the top match if it has reasonable similarity
        if similarities and not impacted_agencies and similarities[0][1] >= 0.65:
            impacted_agencies.append(similarities[0][0])

        return impacted_agencies

    async def _analyze_change_with_llm(
        self,
        change: Dict[str, Any],
        sections: List[Dict[str, Any]],
        code_mods: List[Dict[str, Any]],
        skeleton: Dict[str, Any]
    ) -> ChangeAnalysis:
        """
        Generate comprehensive analysis of a change using LLM for detailed narrative

        This is only called for changes that impact local agencies.
        """
        # Store the bill section details directly in the change object
        change["bill_section_details"] = sections

        # Build a simplified prompt without asking for practice groups (already done with embeddings)
        # and without asking for agency identification (already done with embeddings)
        prompt = self._build_simplified_analysis_prompt(change, sections, code_mods)

        # Determine which API to use
        if self.use_anthropic:
            # Using Anthropic API
            system_prompt = (
                "You are a legal expert analyzing legislative changes affecting local public agencies. "
                "Focus on practical implications, compliance requirements, and deadlines. "
                "Provide concise, action-oriented analysis in JSON format."
            )

            # Claude-specific parameters
            params = {
                "model": self.llm_model,
                "max_tokens": 64000,
                "system": system_prompt,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True  # Use streaming for long-running operations
            }

            # Add thinking parameter for Claude 3.7 models
            if "claude-3-7" in self.llm_model:
                params["temperature"] = 1
                params["thinking"] = {
                    "type": "enabled", 
                    "budget_tokens": 16000
                }

            self.logger.info(f"Using Anthropic API with model {self.llm_model} (streaming enabled)")

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
            try:
                # Check if response starts with a JSON object
                if response_content and not response_content.strip().startswith('{'):
                    # Try to extract JSON content
                    json_start = response_content.find('{')
                    json_end = response_content.rfind('}') + 1
                    if json_start >= 0 and json_end > json_start:
                        clean_json = response_content[json_start:json_end]
                        analysis_data = json.loads(clean_json)
                    else:
                        raise ValueError("Could not extract JSON from response")
                else:
                    analysis_data = json.loads(response_content)
            except json.JSONDecodeError:
                # Handle case where response isn't valid JSON
                self.logger.error(f"Invalid JSON response from Claude: {response_content[:200]}...")
                # Try to extract JSON from text response
                json_start = response_content.find('{')
                json_end = response_content.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    try:
                        clean_json = response_content[json_start:json_end]
                        analysis_data = json.loads(clean_json)
                    except:
                        self.logger.error("Failed to extract JSON from Claude response")
                        raise
                else:
                    raise ValueError("Failed to parse JSON response from Claude")
        else:
            # Using OpenAI API
            params = {
                "model": self.llm_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a legal expert analyzing legislative changes affecting local public agencies. "
                            "Focus on practical implications, compliance requirements, and deadlines. "
                            "Provide concise, action-oriented analysis in JSON format."
                        )
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "response_format": {"type": "json_object"}
            }

            # Add model-specific parameters for OpenAI models
            if "o3-mini" in self.llm_model or "o1" in self.llm_model:  # Reasoning models
                # Use temperature instead of reasoning_effort to avoid compatibility issues
                self.logger.info(f"Using OpenAI API with reasoning model {self.llm_model}")
                params["reasoning_effort"] = "high"
            else:  # gpt-4o and other models
                self.logger.info(f"Using OpenAI API with model {self.llm_model}")
                params["temperature"] = 0

            self.logger.info(f"Using OpenAI API with model {self.llm_model}")
            response = await self.openai_client.chat.completions.create(**params)
            analysis_data = json.loads(response.choices[0].message.content)

        impacts_list = []
        for impact_dict in analysis_data["agency_impacts"]:
            raw_deadline = impact_dict.get("deadline")
            parsed_deadline = None
            if raw_deadline and isinstance(raw_deadline, str):
                try:
                    parsed_deadline = datetime.strptime(raw_deadline, "%Y-%m-%d")
                except ValueError:
                    self.logger.warning(f"Unable to parse deadline '{raw_deadline}' as YYYY-MM-DD.")
                    parsed_deadline = None

            impacts_list.append(
                AgencyImpact(
                    agency_type=impact_dict["agency_type"],
                    impact_type=impact_dict["impact_type"],
                    description=impact_dict["description"],
                    deadline=parsed_deadline,
                    requirements=impact_dict.get("requirements", [])
                )
            )

        return ChangeAnalysis(
            summary=analysis_data["summary"],
            impacts=impacts_list,
            practice_groups=[],  # Empty since we've already identified practice groups with embeddings
            action_items=analysis_data["action_items"],
            deadlines=analysis_data["deadlines"],
            requirements=analysis_data["requirements"]
        )

    def _build_simplified_analysis_prompt(self, change, sections, code_mods) -> str:
        """
        Build a simplified prompt for LLM analysis that doesn't ask for practice groups
        or agency identification since we've already done that with embeddings.
        """
        # List the agencies that have been identified through embeddings
        agencies_str = "No agencies identified."
        if change.get("local_agencies_impacted") and len(change.get("local_agencies_impacted")) > 0:
            agencies_str = ", ".join(change.get("local_agencies_impacted"))

        instruction_block = (
            "Focus your analysis on the following pre-identified local agencies: " + agencies_str + "\n\n"
            "Your summary must:\n"
            "(1) Clearly explain the specific change this bill is making.\n"
            "(2) Explain how these specific local agencies are impacted.\n"
            "(3) Describe what actions these agencies need to take to comply.\n\n"
            "Return the following JSON structure:\n"
            "{\n"
            "  \"summary\": \"Explanation of change and impacts on specified agencies\",\n"
            "  \"agency_impacts\": [\n"
            "     {\n"
            "       \"agency_type\": \"one of the pre-identified agency types\",\n"
            "       \"impact_type\": \"type of impact\",\n"
            "       \"description\": \"detailed explanation\",\n"
            "       \"deadline\": \"YYYY-MM-DD or null\",\n"
            "       \"requirements\": [\"req1\", \"req2\"]\n"
            "     }\n"
            "  ],\n"
            "  \"action_items\": [\"action1\", \"action2\"],\n"
            "  \"deadlines\": [\n"
            "    {\n"
            "      \"date\": \"YYYY-MM-DD\",\n"
            "      \"description\": \"deadline details\",\n"
            "      \"affected_agencies\": [\"agency types\"]\n"
            "    }\n"
            "  ],\n"
            "  \"requirements\": [\"req1\", \"req2\"]\n"
            "}\n"
        )

        section_info = self._format_sections(sections)
        code_mods_text = self._format_code_mods(code_mods)

        return f"""{instruction_block}
Analyze this legislative change and its impact on the specified local public agencies:

Digest Text:
{change['digest_text']}

Bill Sections Implementing This Change:
{section_info}

Code Modifications:
{code_mods_text}

Existing Law:
{change.get('existing_law', '')}

Proposed Changes:
{change.get('proposed_change', '')}
"""

    def _create_minimal_analysis(self, change: Dict[str, Any]) -> None:
        """
        Create minimal analysis for changes with no local agency impact
        """
        change.update({
            "substantive_change": "This change does not appear to have a direct impact on local public agencies.",
            "local_agency_impact": "No direct impact on local agencies identified.",
            "key_action_items": [],
            "deadlines": [],
            "requirements": [],
            "impacts_local_agencies": False
        })

    def _format_sections(self, sections: List[Dict[str, Any]]) -> str:
        formatted = []
        for section in sections:
            text = f"Section {section['number']}:\n"
            text += f"Text: {section['text']}\n"
            if section.get('code_modifications'):
                text += "Modifies:\n"
                for mod in section['code_modifications']:
                    text += f"- {mod['code_name']} Section {mod['section']} ({mod['action']})\n"
            formatted.append(text)
        return "\n".join(formatted)

    def _format_code_mods(self, mods: List[Dict[str, Any]]) -> str:
        formatted = []
        for mod in mods:
            text = f"{mod['code_name']} Section {mod['section']}:\n"
            text += f"Action: {mod['action']}\n"
            text += f"Context: {mod.get('text','N/A')}\n"
            formatted.append(text)
        return "\n".join(formatted)

    def _update_change_with_analysis(self, change: Dict[str, Any], analysis: ChangeAnalysis) -> None:
        """Update change object with analysis results"""
        # Keep the practice groups that were identified by embeddings
        original_practice_groups = change.get("practice_groups", [])

        change.update({
            "substantive_change": analysis.summary,
            "local_agency_impact": self._format_agency_impacts(analysis.impacts),
            "practice_groups": original_practice_groups,  # Keep the embedding-identified practice groups
            "key_action_items": analysis.action_items,
            "deadlines": analysis.deadlines,
            "requirements": analysis.requirements,
            "impacts_local_agencies": bool(analysis.impacts)
        })

    def _format_agency_impacts(self, impacts: List[AgencyImpact]) -> str:
        if not impacts:
            return "No direct impact on local agencies."
        formatted = []
        for impact in impacts:
            text = f"{impact.agency_type}: {impact.description}"
            if impact.deadline:
                text += f" (Deadline: {impact.deadline.strftime('%B %d, %Y')})"
            formatted.append(text)
        return "\n".join(formatted)

    def _update_skeleton_metadata(self, skeleton: Dict[str, Any]) -> None:
        """Update skeleton metadata with analysis results"""
        impacting_changes = [
            c for c in skeleton["changes"]
            if c.get("impacts_local_agencies")
        ]

        primary_groups = set()
        for change in skeleton["changes"]:
            for group in change.get("practice_groups", []):
                if group.get("relevance") == "primary":
                    primary_groups.add(group["name"])

        skeleton["metadata"].update({
            "has_agency_impacts": bool(impacting_changes),
            "impacting_changes_count": len(impacting_changes),
            "practice_groups_affected": sorted(primary_groups)
        })

    def _get_linked_sections(self, change: Dict[str, Any], skeleton: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get bill sections linked to this change."""
        sections = []

        # Get and normalize section numbers
        section_refs = change.get("bill_sections", [])
        normalized_nums = []

        for ref in section_refs:
            # If it's a string like "Section 7", extract just the number
            if isinstance(ref, str) and "section" in ref.lower():
                match = re.search(r'(\d+)', ref, re.IGNORECASE)
                if match:
                    normalized_nums.append(match.group(1))
            else:
                # If it's already just the number or another format
                normalized_nums.append(str(ref))

        self.logger.info(f"Change {change.get('id')} has normalized section numbers: {normalized_nums}")

        # Get bill sections from skeleton
        bill_sections = skeleton.get("bill_sections", [])

        # For each normalized section number, find matching bill section
        for section_num in normalized_nums:
            found = False
            for section in bill_sections:
                if str(section.get("number")) == section_num:
                    self.logger.info(f"Found section {section_num} with label: {section.get('original_label')}")
                    sections.append({
                        "number": section.get("number"),
                        "text": section.get("text", ""),
                        "original_label": section.get("original_label"),
                        "code_modifications": section.get("code_modifications", [])
                    })
                    found = True
                    break

            if not found:
                self.logger.warning(f"Could not find section {section_num} in bill_sections")

        return sections

    def _get_code_modifications(self, change: Dict[str, Any], skeleton: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract code modifications from bill sections associated with a change
        """
        mods = []

        # Get and normalize section numbers from the change
        section_refs = change.get("bill_sections", [])
        normalized_nums = []

        for ref in section_refs:
            # If it's a string like "Section 7", extract just the number
            if isinstance(ref, str) and "section" in ref.lower():
                match = re.search(r'(\d+)', ref, re.IGNORECASE)
                if match:
                    normalized_nums.append(match.group(1))
            else:
                # If it's already just the number or another format
                normalized_nums.append(str(ref))

        # For each normalized section number, find associated code modifications
        for section_num in normalized_nums:
            for section in skeleton.get("bill_sections", []):
                if str(section.get("number")) == section_num:
                    for mod in section.get("code_modifications", []):
                        # Include section text with the modification for context
                        mod_with_context = mod.copy()
                        mod_with_context["text"] = section.get("text", "")[:200]  # First 200 chars for context
                        mods.append(mod_with_context)

        return mods