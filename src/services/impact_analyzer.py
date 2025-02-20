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
    impacts_local: bool = False
    impacts_state: bool = False

class ImpactAnalyzer:
    """
    Analyzer for determining local agency impacts, deadlines, and other
    practical considerations using GPT. We instruct GPT to parse
    local agencies specifically. We also do a final check to refine practice group assignments.
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

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-2024-08-06",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a legal expert analyzing legislative changes affecting "
                            "California local public agencies (cities, counties, special districts, "
                            "school districts, JPAs, etc.) OR state agencies. "
                            "Focus on practical implications, compliance requirements, deadlines/effective dates, "
                            "and specifically name which local agencies are impacted if applicable. "
                            "Identify relevant practice groups from the provided list, if any. "
                            "Indicate only one group as 'primary' if it clearly applies, others 'secondary' if needed. "
                            "Your response MUST be valid JSON, and nothing else. "
                            "If you are not sure or it doesn't apply, return an empty JSON object like {}."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0
            )

            ai_content = response.choices[0].message.content
            ai_content = self._extract_json(ai_content)

            try:
                analysis_data = json.loads(ai_content)
            except json.JSONDecodeError:
                # fallback if GPT didn't return valid JSON
                self.logger.error("Failed to parse JSON from GPT in ImpactAnalyzer; using fallback empty JSON.")
                analysis_data = {}

        except Exception as e:
            self.logger.error(f"Error in AI call for impact analysis: {e}")
            # fallback empty
            analysis_data = {}

        summary = analysis_data.get("summary", "")
        ai_impacts = analysis_data.get("agency_impacts", [])
        practice_groups_raw = analysis_data.get("practice_groups", [])
        action_items = analysis_data.get("action_items", [])
        deadlines = analysis_data.get("deadlines", [])
        requirements = analysis_data.get("requirements", [])

        impacts = []
        for impact in ai_impacts:
            ag_type = impact.get("agency_type", "").strip()
            dl = impact.get("deadline")
            deadline_parsed = self._try_parse_date(dl) if isinstance(dl, str) else None
            impacts.append(AgencyImpact(
                agency_type=ag_type,
                impact_type=impact.get("impact_type", ""),
                description=impact.get("description", ""),
                deadline=deadline_parsed,
                requirements=impact.get("requirements", [])
            ))

        # refine practice groups
        refined_groups = self._refine_practice_groups(practice_groups_raw)

        impacts_local = False
        impacts_state = False
        for imp in impacts:
            l = imp.agency_type.lower()
            if any(x in l for x in ["city", "county", "counties", "local", "school district", "special district", "law enforcement", "jpa"]):
                impacts_local = True
            if any(x in l for x in ["state", "department", "caltrans", "dmv", "high-speed rail", "transportation agency"]):
                impacts_state = True

        analysis = ChangeAnalysis(
            summary=summary,
            impacts=impacts,
            practice_groups=refined_groups,
            action_items=action_items,
            deadlines=deadlines,
            requirements=requirements,
            impacts_local=impacts_local,
            impacts_state=impacts_state
        )
        return analysis

    def _refine_practice_groups(self, raw_groups: List[Dict[str,str]]) -> List[Dict[str,str]]:
        """
        Ensures exactly one group is 'primary' if any are indicated. 
        If multiple claim 'primary', only the first remains primary; 
        the rest are set to 'secondary'.
        If none is primary, the first group is assigned primary.
        """
        seen_primary = False
        refined = []
        known_names = self.practice_groups.group_names

        for g in raw_groups:
            name = g.get("name", "").strip()
            # Only keep if it's in known practice group names
            if name not in known_names:
                continue

            relevance = g.get("relevance", "").lower()
            justification = g.get("justification", "")

            if relevance == "primary":
                if seen_primary:
                    relevance = "secondary"
                else:
                    seen_primary = True

            refined.append({
                "name": name,
                "relevance": relevance,
                "justification": justification
            })

        # If no primary found but we do have at least one group, make the first primary
        if refined and not any(pg["relevance"] == "primary" for pg in refined):
            refined[0]["relevance"] = "primary"

        return refined

    def _extract_json(self, text: str) -> str:
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

    def _build_analysis_prompt(self, change: Dict[str, Any], sections: List[Dict[str, Any]],
                               code_mods: List[Dict[str, Any]], parsed_bill: TrailerBill) -> str:
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

        existing_law_text = change.get("existing_law", "")
        proposed_change_text = change.get("proposed_change", "")
        practice_groups_text = self.practice_groups.get_prompt_text(detail_level="brief")

        # ADDED: we specifically instruct GPT to provide (1) what the change does,
        # (2) which local agencies are affected, (3) how they're affected, etc.
        # The system prompt above also encourages focusing on local agencies if applicable.
        return f"""
Analyze this trailer bill digest change. Provide in your JSON:
1) A short summary describing what the law change does, focusing on practical/legal effect.
2) The type(s) of local agency (cities, counties, special districts, JPAs, etc.) affected, if any.
3) How those local agencies are affected, including new requirements or compliance steps.
4) State agency impacts if relevant.
5) Deadlines/effective dates.
6) Action items to implement or comply.
7) Additional requirements.
8) Relevant practice group(s) from the list (mark only one as 'primary' if it clearly applies).

Return JSON with fields exactly:
{{
  "summary": "...",
  "agency_impacts": [
    {{
      "agency_type": "e.g. counties, cities, special districts, state, etc.",
      "impact_type": "compliance, operational, etc.",
      "description": "Short explanation",
      "deadline": "YYYY-MM-DD or null",
      "requirements": ["req1", "req2"]
    }}
  ],
  "practice_groups": [
    {{
      "name": "practice group name",
      "relevance": "primary or secondary",
      "justification": "why"
    }}
  ],
  "action_items": ["action item 1", "action item 2"],
  "deadlines": [
    {{
      "date": "YYYY-MM-DD",
      "description": "deadline detail",
      "affected_agencies": ["type1", "type2"]
    }}
  ],
  "requirements": ["req1", "req2"]
}}

If no info is available, return: {{}}

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

    def _try_parse_date(self, date_str: str) -> Optional[datetime]:
        try:
            return datetime.strptime(date_str.strip(), "%Y-%m-%d")
        except (ValueError, TypeError):
            return None

    def _update_change_with_analysis(self, change: Dict[str, Any], analysis: ChangeAnalysis) -> None:
        if analysis.impacts:
            lines = []
            for imp in analysis.impacts:
                part = f"{imp.agency_type}: {imp.description}"
                if imp.deadline:
                    part += f" (Deadline: {imp.deadline.strftime('%Y-%m-%d')})"
                lines.append(part)
            local_agency_impact = "\n".join(lines)
        else:
            local_agency_impact = "No specific agencies identified."

        change.update({
            "substantive_change": analysis.summary,
            "local_agency_impact_summary": local_agency_impact,
            "practice_groups": analysis.practice_groups,
            "key_action_items": analysis.action_items,
            "deadlines": analysis.deadlines,
            "requirements": analysis.requirements,
            "impacts_local_agencies": analysis.impacts_local,
            "impacts_state_agencies": analysis.impacts_state
        })

    def _update_skeleton_metadata(self, skeleton: Dict[str, Any]) -> None:
        changes = skeleton["changes"]
        local_impacting_changes = [c for c in changes if c.get("impacts_local_agencies")]
        state_impacting_changes = [c for c in changes if c.get("impacts_state_agencies")]

        skeleton["metadata"].update({
            "has_local_agency_impacts": bool(local_impacting_changes),
            "local_impacts_count": len(local_impacting_changes),
            "has_state_agency_impacts": bool(state_impacting_changes),
            "state_impacts_count": len(state_impacting_changes),
        })

    def _get_linked_sections(self, change: Dict[str, Any], parsed_bill: TrailerBill) -> List[Dict[str, Any]]:
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
        # Currently returns empty or a placeholder. Could be expanded if needed.
        return []
