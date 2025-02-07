from typing import Dict, List, Any, Optional, Set, Union
import logging
import json
from datetime import datetime
from dataclasses import dataclass, field
from collections import defaultdict
import re

@dataclass
class AgencyImpact:
    """Represents specific impact on local agencies"""
    agency_type: str  # e.g., "cities", "counties", "school districts"
    impact_type: str  # e.g., "compliance", "operational", "financial"
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
    """Enhanced analyzer for determining local agency impacts"""

    def __init__(self, openai_client, practice_groups_data):
        self.logger = logging.getLogger(__name__)
        self.client = openai_client
        self.practice_groups = practice_groups_data

    async def analyze_changes(
        self,
        parsed_bill: Dict[str, Any],
        skeleton: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze changes with enhanced impact detection"""
        try:
            for change in skeleton["changes"]:
                # Get linked sections and code modifications
                sections = self._get_linked_sections(change, parsed_bill)
                code_mods = self._get_code_modifications(change, parsed_bill)

                # Generate comprehensive analysis
                analysis = await self._analyze_change(
                    change,
                    sections,
                    code_mods,
                    parsed_bill
                )

                # Update change with analysis results
                self._update_change_with_analysis(change, analysis)

            # Update metadata
            self._update_skeleton_metadata(skeleton)

            return skeleton

        except Exception as e:
            self.logger.error(f"Error analyzing changes: {str(e)}")
            raise

    async def _analyze_change(
        self,
        change: Dict[str, Any],
        sections: List[Dict[str, Any]],
        code_mods: List[Dict[str, Any]],
        parsed_bill: Dict[str, Any]
    ) -> ChangeAnalysis:
        """Generate comprehensive analysis of a change"""
        # Build detailed prompt for AI analysis
        prompt = self._build_analysis_prompt(
            change,
            sections,
            code_mods,
            parsed_bill
        )

        # Get AI analysis
        response = await self.client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": """You are a legal expert analyzing legislative changes affecting local public agencies.
                    Focus on practical implications, compliance requirements, and deadlines.
                    Provide concise, action-oriented analysis."""
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )

        # Parse and structure the analysis
        analysis_data = json.loads(response.choices[0].message.content)

        return ChangeAnalysis(
            summary=analysis_data["summary"],
            impacts=[
                AgencyImpact(**impact)
                for impact in analysis_data["agency_impacts"]
            ],
            practice_groups=self._validate_practice_groups(
                analysis_data["practice_groups"]
            ),
            action_items=analysis_data["action_items"],
            deadlines=analysis_data["deadlines"],
            requirements=analysis_data["requirements"]
        )

    def _build_analysis_prompt(
        self,
        change: Dict[str, Any],
        sections: List[Dict[str, Any]],
        code_mods: List[Dict[str, Any]],
        parsed_bill: Dict[str, Any]
    ) -> str:
        """Build comprehensive prompt for change analysis"""
        return f"""Analyze this legislative change and its impact on local public agencies:

Digest Text:
{change['digest_text']}

Bill Sections Implementing This Change:
{self._format_sections(sections)}

Code Modifications:
{self._format_code_mods(code_mods)}

Existing Law:
{change.get('existing_law', '')}

Proposed Changes:
{change.get('proposed_change', '')}

Practice Group Information:
{self._format_practice_groups()}

Provide analysis in this JSON format:
{{
    "summary": "Clear, concise summary of the change",
    "agency_impacts": [
        {
            "agency_type": "type of agency affected",
            "impact_type": "type of impact",
            "description": "specific impact description",
            "deadline": "YYYY-MM-DD or null",
            "requirements": ["specific requirement 1", "requirement 2"]
        }
    ],
    "practice_groups": [
        {
            "name": "practice group name",
            "relevance": "primary or secondary",
            "justification": "why this practice group is relevant"
        }
    ],
    "action_items": [
        "specific action item 1",
        "specific action item 2"
    ],
    "deadlines": [
        {
            "date": "YYYY-MM-DD",
            "description": "what is due",
            "affected_agencies": ["agency types"]
        }
    ],
    "requirements": [
        "specific requirement 1",
        "specific requirement 2"
    ]
}}"""

    def _format_sections(self, sections: List[Dict[str, Any]]) -> str:
        """Format bill sections for prompt"""
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
        """Format code modifications for prompt"""
        formatted = []
        for mod in mods:
            text = f"{mod['code_name']} Section {mod['section']}:\n"
            text += f"Action: {mod['action']}\n"
            text += f"Context: {mod['text']}\n"
            formatted.append(text)
        return "\n".join(formatted)

    def _format_practice_groups(self) -> str:
        """Format practice group information for prompt"""
        formatted = []
        for group in self.practice_groups:
            text = f"{group.name}:\n{group.description}\n"
            formatted.append(text)
        return "\n".join(formatted)

    def _validate_practice_groups(
        self,
        groups: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """Validate and normalize practice group assignments"""
        validated = []
        for group in groups:
            if group["name"] in self.practice_groups.groups:
                if group["relevance"] in ("primary", "secondary"):
                    validated.append({
                        "name": group["name"],
                        "relevance": group["relevance"]
                    })
        return validated

    def _update_change_with_analysis(
        self,
        change: Dict[str, Any],
        analysis: ChangeAnalysis
    ) -> None:
        """Update change dictionary with analysis results"""
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
        """Format agency impacts into readable text"""
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
        """Update skeleton metadata with impact analysis results"""
        impacting_changes = [
            c for c in skeleton["changes"]
            if c.get("impacts_local_agencies")
        ]

        primary_groups = set()
        for change in impacting_changes:
            primary_groups.update(
                group["name"]
                for group in change.get("practice_groups", [])
                if group["relevance"] == "primary"
            )

        skeleton["metadata"].update({
            "has_agency_impacts": bool(impacting_changes),
            "impacting_changes_count": len(impacting_changes),
            "practice_groups_affected": sorted(primary_groups)
        })

    def _get_linked_sections(
        self,
        change: Dict[str, Any],
        parsed_bill: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Get bill sections linked to this change"""
        sections = []
        for section_num in change.get("bill_sections", []):
            if section := parsed_bill["bill_sections"].get(section_num):
                sections.append({
                    "number": section_num,
                    **section
                })
        return sections

    def _get_code_modifications(
        self,
        change: Dict[str, Any],
        parsed_bill: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Get code modifications related to this change"""
        mods = []
        digest_item = next(
            (item for item in parsed_bill["digest_items"]
             if item.number == change.get("digest_number")),
            None
        )
        if digest_item:
            mods.extend(
                {"number": mod.section, **mod.__dict__}
                for mod in digest_item.code_modifications
            )
        return mods