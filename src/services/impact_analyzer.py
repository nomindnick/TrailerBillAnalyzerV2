import logging
import json
import asyncio
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from src.models.bill_components import TrailerBill

@dataclass
class AgencyImpact:
    agency_type: str
    impact_type: str
    description: str
    deadline: Optional[datetime] = None
    requirements: Optional[List[str]] = None

@dataclass
class ChangeAnalysis:
    summary: str
    impacts: List[AgencyImpact]
    practice_groups: List[Dict[str, str]]
    action_items: List[str]
    deadlines: List[Dict[str, Any]]
    requirements: List[str]

class ImpactAnalyzer:
    """
    Analyzer for determining local agency impacts, deadlines, and other
    practical considerations using GPT. We instruct GPT to parse
    local agencies (counties, cities, special districts, etc.) if possible.
    """

    def __init__(self, openai_client, practice_groups_data):
        self.logger = logging.getLogger(__name__)
        self.client = openai_client
        self.practice_groups = practice_groups_data

    async def analyze_changes(self, parsed_bill: TrailerBill, skeleton: Dict[str, Any]) -> Dict[str, Any]:
        try:
            for change in skeleton["changes"]:
                analysis = await self._analyze_change(change, parsed_bill)
                self._update_change_with_analysis(change, analysis)
            self._update_skeleton_metadata(skeleton)
            return skeleton
        except Exception as e:
            self.logger.error(f"Error analyzing changes: {str(e)}")
            raise

    async def _analyze_change(self, change: Dict[str, Any], parsed_bill: TrailerBill) -> ChangeAnalysis:
        sections = self._get_linked_sections(change, parsed_bill)
        code_mods = self._get_code_modifications(change, parsed_bill)
        prompt = self._build_analysis_prompt(change, sections, code_mods, parsed_bill)

        # We'll run this in an executor to avoid blocking
        # Use the ChatCompletion with the model
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self.client.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a legal expert analyzing legislative changes affecting "
                            "California local public agencies (cities, counties, special districts, "
                            "school districts, law enforcement agencies, regional transportation planning agencies, etc.). "
                            "Focus on practical implications, compliance requirements, "
                            "deadlines/effective dates, and local agency types impacted. "
                            "Identify relevant practice groups from the provided list, if any."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0
            )
        )

        ai_content = response.choices[0].message.content
        try:
            analysis_data = json.loads(ai_content)
        except json.JSONDecodeError:
            # fallback if GPT didn't return valid JSON
            analysis_data = {
                "summary": "",
                "agency_impacts": [],
                "practice_groups": [],
                "action_items": [],
                "deadlines": [],
                "requirements": []
            }

        # parse dates
        self._parse_analysis_dates(analysis_data)

        # Convert agency impacts
        impacts = []
        for impact in analysis_data.get("agency_impacts", []):
            # Some might not have all fields
            deadline = impact.get("deadline")
            if isinstance(deadline, str):
                deadline_parsed = self._try_parse_date(deadline)
            else:
                deadline_parsed = None
            impacts.append(AgencyImpact(
                agency_type=impact.get("agency_type", ""),
                impact_type=impact.get("impact_type", ""),
                description=impact.get("description", ""),
                deadline=deadline_parsed,
                requirements=impact.get("requirements", [])
            ))

        # Validate practice groups
        validated_groups = self._validate_practice_groups(analysis_data.get("practice_groups", []))

        return ChangeAnalysis(
            summary=analysis_data.get("summary", ""),
            impacts=impacts,
            practice_groups=validated_groups,
            action_items=analysis_data.get("action_items", []),
            deadlines=analysis_data.get("deadlines", []),
            requirements=analysis_data.get("requirements", [])
        )

    def _build_analysis_prompt(self, change: Dict[str, Any], sections: List[Dict[str, Any]],
                               code_mods: List[Dict[str, Any]], parsed_bill: TrailerBill) -> str:
        # We'll format sections for clarity
        sec_str = []
        for s in sections:
            sec_txt = f"SEC. {s['number']}:\n{s['text']}\n"
            if s.get("code_modifications"):
                sec_txt += "Modifies:\n"
                for cm in s["code_modifications"]:
                    sec_txt += f"- {cm['code_name']} Section {cm['section']} ({cm.get('action','')})\n"
            sec_str.append(sec_txt)

        code_mod_str = []
        for cm in code_mods:
            code_mod_str.append(
                f"{cm.get('code_name','')} Section {cm.get('section','')} Action: {cm.get('action','UNKNOWN')}"
            )
        code_mod_joined = "\n".join(code_mod_str)

        # We pass existing/proposed text from the digest
        existing_law_text = change.get("existing_law", "")
        proposed_change_text = change.get("proposed_change", "")

        practice_groups_text = self.practice_groups.get_prompt_text(detail_level="brief")

        return f"""
Analyze the following trailer bill digest change and identify:
- A concise summary
- Which local agencies (counties, cities, special districts, law enforcement, etc.) might be impacted
- Deadlines or effective dates
- Key action items
- Additional requirements
- Relevant practice groups from the list
Return valid JSON with fields:
{{
  "summary": "...",
  "agency_impacts": [
    {{
      "agency_type": "e.g. counties, cities, special districts",
      "impact_type": "compliance, operational, financial, etc.",
      "description": "Explain the nature of the impact",
      "deadline": "YYYY-MM-DD or null",
      "requirements": ["req1", "req2"]
    }}
  ],
  "practice_groups": [
    {{
      "name": "practice group name",
      "relevance": "primary or secondary",
      "justification": "why this group is relevant"
    }}
  ],
  "action_items": ["action item 1", "action item 2"],
  "deadlines": [
    {{
      "date": "YYYY-MM-DD",
      "description": "deadline detail",
      "affected_agencies": ["type of agencies"]
    }}
  ],
  "requirements": ["req1", "req2"]
}}

Digest Text:
{change['digest_text']}

Existing Law:
{existing_law_text}

Proposed Changes:
{proposed_change_text}

Bill Sections Implementing This Change:
{"".join(sec_str)}

Code Modifications:
{code_mod_joined}

Practice Group Definitions (brief):
{practice_groups_text}
"""

    def _parse_analysis_dates(self, analysis_data: Dict[str, Any]) -> None:
        for impact in analysis_data.get("agency_impacts", []):
            deadline = impact.get("deadline")
            if isinstance(deadline, str):
                impact["deadline"] = self._try_parse_date(deadline)
        for d in analysis_data.get("deadlines", []):
            ddate = d.get("date")
            if isinstance(ddate, str):
                d["date"] = self._try_parse_date(ddate)

    def _try_parse_date(self, date_str: str) -> Optional[datetime]:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return None

    def _validate_practice_groups(self, groups: List[Dict[str, str]]) -> List[Dict[str, str]]:
        # Just return them if they have a name that matches known groups or skip
        valid = []
        known_names = self.practice_groups.group_names
        for g in groups:
            gname = g.get("name", "")
            if gname in known_names:
                valid.append(g)
            else:
                # We allow them but maybe mark them as 'unrecognized' if needed
                pass
        return valid

    def _update_change_with_analysis(self, change: Dict[str, Any], analysis: ChangeAnalysis) -> None:
        # Summarize local agencies impacted
        if analysis.impacts:
            lines = []
            for imp in analysis.impacts:
                # e.g. "counties: [some text], deadline, etc."
                part = f"{imp.agency_type}: {imp.description}"
                if imp.deadline:
                    part += f" (Deadline: {imp.deadline.strftime('%Y-%m-%d')})"
                lines.append(part)
            local_agency_impact = "\n".join(lines)
        else:
            local_agency_impact = "No specific local agencies identified."

        change.update({
            "substantive_change": analysis.summary,
            "local_agency_impact": local_agency_impact,
            "practice_groups": analysis.practice_groups,
            "key_action_items": analysis.action_items,
            "deadlines": analysis.deadlines,
            "requirements": analysis.requirements,
            "impacts_local_agencies": len(analysis.impacts) > 0
        })

    def _update_skeleton_metadata(self, skeleton: Dict[str, Any]) -> None:
        impacting_changes = [c for c in skeleton["changes"] if c.get("impacts_local_agencies")]
        primary_groups = set()
        for change in impacting_changes:
            for group in change.get("practice_groups", []):
                if group.get("relevance") == "primary":
                    primary_groups.add(group["name"])
        skeleton["metadata"].update({
            "has_agency_impacts": bool(impacting_changes),
            "impacting_changes_count": len(impacting_changes),
            "practice_groups_affected": sorted(primary_groups)
        })

    def _get_linked_sections(self, change: Dict[str, Any], parsed_bill: TrailerBill) -> List[Dict[str, Any]]:
        # bill_sections is a list of dict with 'section_id'
        out = []
        for bs in change.get("bill_sections", []):
            sid = bs["section_id"]
            matched = next((x for x in parsed_bill.bill_sections if x.number == sid), None)
            if matched:
                cm = []
                for ref in matched.code_references:
                    cm.append({
                        "code_name": ref.code_name,
                        "section": ref.section,
                        "action": getattr(ref, "action", None)
                    })
                out.append({
                    "number": sid,
                    "text": matched.text,
                    "code_modifications": cm
                })
        return out

    def _get_code_modifications(self, change: Dict[str, Any], parsed_bill: TrailerBill) -> List[Dict[str, Any]]:
        # from the digest references
        mods = []
        digest_number = change.get("digest_number")
        if digest_number:
            ds = next((d for d in parsed_bill.digest_sections if d.number == digest_number), None)
            if ds:
                for ref in ds.code_references:
                    mods.append({
                        "code_name": ref.code_name,
                        "section": ref.section,
                        "action": getattr(ref, "action", None)
                    })
        return mods
