import logging
import json
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from collections import defaultdict

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

class ImpactAnalyzer:
    """Enhanced analyzer for determining local agency impacts with detailed progress reporting"""

    def __init__(self, openai_client, practice_groups_data):
        self.logger = logging.getLogger(__name__)
        self.client = openai_client
        self.practice_groups = practice_groups_data

        # Expanded keywords to catch local agency references from the AI response
        self.local_agency_keywords = {
            "city", "cities",
            "county", "counties",
            "school district", "school districts",
            "special district", "special districts",
            "joint powers authority", "joint powers authorities", "jpas",
            "community college district", "community college districts",
            "law enforcement agency", "law enforcement agencies",
            "transit operator", "transit operators",
            "municipal agency", "municipal agencies"
        }

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
                    4,
                    "Starting impact analysis for local agencies",
                    total_changes // 3,
                    total_changes
                )

            for i, change in enumerate(skeleton["changes"]):
                if progress_handler:
                    progress_handler.update_substep(
                        min(total_changes // 3 + i, total_changes),
                        f"Analyzing impacts for change {i+1} of {total_changes}"
                    )

                sections = self._get_linked_sections(change, skeleton)
                code_mods = self._get_code_modifications(change, skeleton)
                change["bill_section_details"] = sections

                analysis = await self._analyze_change(change, sections, code_mods, skeleton)
                self._update_change_with_analysis(change, analysis)

                local_agencies_mentioned = self._extract_local_agencies(analysis.impacts)
                if local_agencies_mentioned:
                    change["impacts_local_agencies"] = True
                    change["local_agencies_impacted"] = list(local_agencies_mentioned)
                else:
                    change["impacts_local_agencies"] = False
                    change["local_agencies_impacted"] = []

                if progress_handler and i < total_changes - 1:
                    progress_handler.update_substep(
                        min(total_changes // 3 + i + 1, total_changes),
                        f"Completed analysis for change {i+1}"
                    )

            self._update_skeleton_metadata(skeleton)

            if progress_handler:
                progress_handler.update_substep(
                    total_changes,
                    "Impact analysis complete"
                )

            return skeleton

        except Exception as e:
            self.logger.error(f"Error analyzing changes: {str(e)}")
            raise

    async def _analyze_change(
        self,
        change: Dict[str, Any],
        sections: List[Dict[str, Any]],
        code_mods: List[Dict[str, Any]],
        skeleton: Dict[str, Any]
    ) -> ChangeAnalysis:
        """Generate comprehensive analysis of a change"""
        # Store the bill section details directly in the change object
        change["bill_section_details"] = sections
        prompt = self._build_analysis_prompt(change, sections, code_mods, skeleton)

        response = await self.client.chat.completions.create(
            model="gpt-4o-2024-08-06",
            messages=[
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
            temperature=0,
            response_format={"type": "json_object"}
        )

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
            practice_groups=self._validate_practice_groups(analysis_data["practice_groups"]),
            action_items=analysis_data["action_items"],
            deadlines=analysis_data["deadlines"],
            requirements=analysis_data["requirements"]
        )

    def _build_analysis_prompt(self, change, sections, code_mods, skeleton) -> str:
        """
        Instruct the model to produce a 'summary' that clearly identifies:
          1) The specific change the bill is making
          2) Which local public agencies are affected (and why)
          3) How those local agencies would be impacted

        Then produce the required JSON structure.
        """
        instruction_block = (
            "Your summary must begin with a short paragraph describing:\n"
            "(1) The specific change this bill is making.\n"
            "(2) Which local public agencies (e.g., cities, counties, school districts, special districts, JPAs, etc.)"
            " are affected and why.\n"
            "(3) How those local public agencies are impacted.\n"
            "If no local public agencies are impacted, state that clearly.\n\n"
            "Return the following JSON structure:\n"
            "{\n"
            "  \"summary\": \"(Include the 3-point explanation above)\",\n"
            "  \"agency_impacts\": [\n"
            "     {\n"
            "       \"agency_type\": \"type of agency\",\n"
            "       \"impact_type\": \"type of impact\",\n"
            "       \"description\": \"explanation\",\n"
            "       \"deadline\": \"YYYY-MM-DD or null\",\n"
            "       \"requirements\": [\"req1\", \"req2\"]\n"
            "     }\n"
            "  ],\n"
            "  \"practice_groups\": [\n"
            "    {\n"
            "      \"name\": \"practice group name\",\n"
            "      \"relevance\": \"primary or secondary\",\n"
            "      \"justification\": \"why relevant\"\n"
            "    }\n"
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
Analyze this legislative change and its impact on local public agencies:

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

Practice Group Information:
{self._format_practice_groups()}
"""

    def _extract_local_agencies(self, impacts: List[AgencyImpact]) -> set:
        local_agencies_found = set()
        for imp in impacts:
            lower_type = imp.agency_type.lower()
            for keyword in self.local_agency_keywords:
                if keyword in lower_type:
                    local_agencies_found.add(imp.agency_type)
                    break
        return local_agencies_found

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

    def _format_practice_groups(self) -> str:
        formatted = []
        for group in self.practice_groups.groups.values():
            text = f"{group.name}:\n{group.description}\n"
            formatted.append(text)
        return "\n".join(formatted)

    def _validate_practice_groups(self, groups: List[Dict[str, str]]) -> List[Dict[str, str]]:
        validated = []
        valid_group_names = {group.name for group in self.practice_groups.groups.values()}
        for group in groups:
            if group["name"] in valid_group_names:
                if group["relevance"] in ("primary", "secondary"):
                    validated.append({
                        "name": group["name"],
                        "relevance": group["relevance"],
                        "justification": group.get("justification", "")
                    })
        return validated

    def _update_change_with_analysis(self, change: Dict[str, Any], analysis: ChangeAnalysis) -> None:
        change.update({
            "substantive_change": analysis.summary,
            "local_agency_impact": self._format_agency_impacts(analysis.impacts),
            "practice_groups": analysis.practice_groups,
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
        """Get all bill sections that are linked to this change."""
        sections = []

        # Get the bill section numbers from the change
        section_nums = change.get("bill_sections", [])
        self.logger.info(f"Change {change.get('id')} has section numbers: {section_nums}")

        # Look up each section in the bill_sections from the skeleton
        bill_sections = skeleton.get("bill_sections", [])
        self.logger.info(f"Skeleton has {len(bill_sections)} bill sections")

        # Debug: Print all section numbers in the skeleton for comparison
        all_section_nums = [str(s.get("number")) for s in bill_sections]
        self.logger.info(f"Available section numbers in skeleton: {all_section_nums}")

        for section_num in section_nums:
            found_section = False
            for section in bill_sections:
                if str(section.get("number")) == str(section_num):
                    sections.append({
                        "number": section.get("number"),
                        "original_label": section.get("original_label", f"SECTION {section_num}."),
                        "text": section.get("text", ""),
                        "code_modifications": section.get("code_modifications", [])
                    })
                    found_section = True
                    self.logger.info(f"Found section {section_num}")
                    break

            if not found_section:
                self.logger.warning(f"Could not find section {section_num} in bill_sections")

        self.logger.info(f"Linked {len(sections)} sections to change {change.get('id')}")

        # Important: If no sections were found, add debugging info
        if not sections:
            self.logger.error(f"No sections linked to change {change.get('id')}. "
                              f"Section nums: {section_nums}, Available: {all_section_nums}")

        return sections

    def _get_code_modifications(self, change: Dict[str, Any], skeleton: Dict[str, Any]) -> List[Dict[str, Any]]:
        mods = []
        for section_num in change.get("bill_sections", []):
            for section in skeleton.get("bill_sections", []):
                if section.get("number") == section_num:
                    for mod in section.get("code_modifications", []):
                        mods.append(mod)
        return mods
