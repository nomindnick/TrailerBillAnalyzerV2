import logging
import json
import asyncio
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from src.models.bill_components import TrailerBill


@dataclass
class AgencyImpact:
    """Represents specific impact on local agencies"""
    agency_type: str  # e.g., "cities", "counties", "school districts"
    impact_type: str  # e.g., "compliance", "operational", "financial"
    description: str
    deadline: Optional[datetime] = None
    requirements: Optional[List[str]] = None


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
        parsed_bill: TrailerBill,
        skeleton: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze changes with enhanced impact detection"""
        try:
            for change in skeleton["changes"]:
                # Get comprehensive analysis for each "change"
                analysis = await self._analyze_change(change, parsed_bill)

                # Update change with analysis results
                self._update_change_with_analysis(change, analysis)

            # Update skeleton metadata
            self._update_skeleton_metadata(skeleton)
            return skeleton

        except Exception as e:
            self.logger.error(f"Error analyzing changes: {str(e)}")
            raise

    async def _analyze_change(
        self,
        change: Dict[str, Any],
        parsed_bill: TrailerBill
    ) -> ChangeAnalysis:
        """Generate comprehensive analysis of a change"""
        # Prepare the relevant data
        sections = self._get_linked_sections(change, parsed_bill)
        code_mods = self._get_code_modifications(change, parsed_bill)

        # Build prompt for AI analysis
        prompt = self._build_analysis_prompt(
            change,
            sections,
            code_mods,
            parsed_bill
        )

        # NOTE: Because the OpenAI call is synchronous, we run it in an executor:
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self.client.chat.completions.create(
                model="gpt-4o-2024-08-06",
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
                # Keep your custom parameter here if your library supports it
                response_format={"type": "json_object"}
            )
        )

        ai_content = response.choices[0].message.content
        analysis_data = json.loads(ai_content)

        # Convert string dates to datetime objects
        self._parse_analysis_dates(analysis_data)

        # Build ChangeAnalysis
        return ChangeAnalysis(
            summary=analysis_data.get("summary", ""),
            impacts=[
                AgencyImpact(**impact) for impact in analysis_data.get("agency_impacts", [])
            ],
            practice_groups=self._validate_practice_groups(
                analysis_data.get("practice_groups", [])
            ),
            action_items=analysis_data.get("action_items", []),
            deadlines=analysis_data.get("deadlines", []),
            requirements=analysis_data.get("requirements", [])
        )

    def _build_analysis_prompt(
        self,
        change: Dict[str, Any],
        sections: List[Dict[str, Any]],
        code_mods: List[Dict[str, Any]],
        parsed_bill: TrailerBill
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
{self.practice_groups.get_prompt_text(detail_level="brief")}

Provide analysis in this JSON format:
{{
    "summary": "Clear, concise summary of the change",
    "agency_impacts": [
        {{
            "agency_type": "type of agency affected",
            "impact_type": "type of impact",
            "description": "specific impact description",
            "deadline": "YYYY-MM-DD or null",
            "requirements": ["specific requirement 1", "requirement 2"]
        }}
    ],
    "practice_groups": [
        {{
            "name": "practice group name",
            "relevance": "primary or secondary",
            "justification": "why this practice group is relevant"
        }}
    ],
    "action_items": [
        "specific action item 1",
        "specific action item 2"
    ],
    "deadlines": [
        {{
            "date": "YYYY-MM-DD",
            "description": "what is due",
            "affected_agencies": ["agency types"]
        }}
    ],
    "requirements": [
        "specific requirement 1",
        "specific requirement 2"
    ]
}}
"""

    def _format_sections(self, sections: List[Dict[str, Any]]) -> str:
        """Format bill sections for prompt"""
        formatted = []
        for section in sections:
            text = f"Section {section['number']}:\nText: {section['text']}\n"
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
            text = f"{mod.get('code_name', '')} Section {mod.get('section', '')}:\n"
            text += f"Action: {mod.get('action', '')}\n"
            text += f"Context: {mod.get('text', '')}\n"
            formatted.append(text)
        return "\n".join(formatted)

    def _parse_analysis_dates(self, analysis_data: Dict[str, Any]) -> None:
        """Convert date strings to datetime objects where applicable"""
        # agency_impacts => "deadline"
        for impact in analysis_data.get("agency_impacts", []):
            if impact.get("deadline"):
                impact["deadline"] = self._try_parse_date(impact["deadline"])

        # deadlines => "date"
        for deadline in analysis_data.get("deadlines", []):
            if deadline.get("date"):
                deadline["date"] = self._try_parse_date(deadline["date"])

    def _try_parse_date(self, date_str: str) -> Optional[datetime]:
        """Safely parse a date string in YYYY-MM-DD format; return None on failure"""
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return None

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
        parsed_bill: TrailerBill
    ) -> List[Dict[str, Any]]:
        """Get bill sections linked to this change"""
        sections = []
        for section_num in change.get("bill_sections", []):
            # If your code in skeleton stores dicts with 'section_id' rather than the raw ID,
            # adjust accordingly. This example assumes a direct string of the section's number:
            if isinstance(section_num, dict) and "section_id" in section_num:
                section_num = section_num["section_id"]

            section = next(
                (s for s in parsed_bill.bill_sections if s.number == str(section_num)),
                None
            )
            if section:
                sections.append({
                    "number": section_num,
                    "text": section.text,
                    "code_modifications": [
                        {
                            "code_name": ref.code_name,
                            "section": ref.section,
                            "action": getattr(ref, 'action', None),
                            "text": getattr(ref, 'text', None)
                        }
                        for ref in section.code_references
                    ]
                })
        return sections

    def _get_code_modifications(
        self,
        change: Dict[str, Any],
        parsed_bill: TrailerBill
    ) -> List[Dict[str, Any]]:
        """Get code modifications related to this change"""
        mods = []
        digest_number = change.get("digest_number")
        if digest_number:
            digest_section = next(
                (d for d in parsed_bill.digest_sections if d.number == digest_number),
                None
            )
            if digest_section:
                for ref in digest_section.code_references:
                    mods.append({
                        "code_name": ref.code_name,
                        "section": ref.section,
                        "action": getattr(ref, 'action', None),
                        "text": getattr(ref, 'text', None)
                    })
        return mods

    def _validate_practice_groups(
        self,
        practice_groups: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """
        You may want to validate the practice group names or structure here.
        Returning as-is in this example.
        """
        return practice_groups
