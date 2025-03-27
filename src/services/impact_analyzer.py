# impact_analyzer.py

import logging
import json
import re
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from collections import defaultdict

@dataclass
class AgencyImpact:
    agency_type: str
    impact_type: str
    description: str
    deadline: Optional[datetime] = None
    requirements: List[str] = None

@dataclass
class ChangeAnalysis:
    summary: str
    impacts: List[AgencyImpact]
    # We no longer rely on LLM to produce practice_groups
    practice_groups: List[Dict[str, str]]
    action_items: List[str]
    deadlines: List[Dict[str, Any]]
    requirements: List[str]

class ImpactAnalyzer:
    """
    Analyzes local agency impacts using an LLM. 
    BUT we skip the LLM if local_agency_type is None.
    """

    def __init__(self, openai_client, practice_groups_data, model="gpt-4o-2024-08-06", anthropic_client=None):
        self.logger = logging.getLogger(__name__)
        self.openai_client = openai_client
        self.anthropic_client = anthropic_client
        self.practice_groups = practice_groups_data

        if not isinstance(model, str):
            self.logger.warning(f"Model parameter is not a string, defaulting to GPT-4o.")
            self.model = "gpt-4o-2024-08-06"
        else:
            self.model = model

        self.use_anthropic = self.model.startswith("claude")
        self.logger.info(f"Initialized ImpactAnalyzer with model: {self.model}")

        # For now, we do not do embeddings in this class. 
        # The local agency check is done upstream by embeddings_matcher.

    async def analyze_changes(self, skeleton: Dict[str, Any], progress_handler=None) -> Dict[str, Any]:
        """
        For each change, if local_agency_type is None, skip LLM-based analysis. 
        Otherwise, call LLM for the final "impact analysis" (the summary, deadlines, etc.)
        """
        total_changes = len(skeleton["changes"])
        if progress_handler:
            progress_handler.update_progress(5, "Starting impact analysis for local agencies", 0, total_changes)

        for i, change in enumerate(skeleton["changes"]):
            current_change = i + 1
            if progress_handler:
                progress_handler.update_substep(
                    current_change,
                    f"Analyzing change {current_change}/{total_changes}"
                )

            # If no local agency impacted, skip LLM
            if not change.get("local_agency_type"):
                change["impacts_local_agencies"] = False
                change["substantive_change"] = "No local public agency is directly impacted by this change."
                change["local_agency_impact"] = "None"
                change["key_action_items"] = []
                change["deadlines"] = []
                change["requirements"] = []
                continue

            # Otherwise, we do call the LLM for final details
            # Build the prompt or call a function that builds the prompt
            prompt = self._build_analysis_prompt(change, skeleton)
            # We'll do a minimal approach with streaming or not
            analysis_data = {}
            if self.use_anthropic:
                analysis_data = await self._anthropic_impact_analysis(prompt)
            else:
                analysis_data = await self._openai_impact_analysis(prompt)

            # Convert analysis_data -> ChangeAnalysis
            analysis = self._parse_analysis_data(analysis_data)
            self._update_change_with_analysis(change, analysis)

            # Mark that it does impact agencies
            change["impacts_local_agencies"] = True

        # Add a final pass to label changes with no local agency as "no local public agency impact"
        # The report generator can group them separately.
        # But we do that simply by checking "impacts_local_agencies" in the final skeleton.
        if progress_handler:
            progress_handler.update_substep(total_changes, "Impact analysis complete.")

        return skeleton

    def _build_analysis_prompt(self, change: Dict[str, Any], skeleton: Dict[str, Any]) -> str:
        """
        Provide text to LLM for the final deeper impact analysis.
        We assume that "practice_groups" is already assigned.
        We also know local_agency_type is not None.
        """
        local_agency = change["local_agency_type"]
        digest_text = change.get("digest_text","")
        existing_law = change.get("existing_law","")
        proposed_change = change.get("proposed_change","")

        instruction_block = (
            "You are an LLM analyzing how this bill change impacts the specified local public agency type. "
            "Focus on compliance requirements, deadlines, and recommended action items. Return JSON:\n"
            "{\n"
            "  \"summary\": \"(a short explanation)\",\n"
            "  \"agency_impacts\": [\n"
            "     {\n"
            "       \"agency_type\": \"(the local agency_type)\",\n"
            "       \"impact_type\": \"(what type of impact - e.g., new mandate, increased cost, etc.)\",\n"
            "       \"description\": \"(explain)\",\n"
            "       \"deadline\": \"YYYY-MM-DD or null\",\n"
            "       \"requirements\": [\"req1\", \"req2\"]\n"
            "     }\n"
            "  ],\n"
            "  \"practice_groups\": [],\n"
            "  \"action_items\": [\"action1\", \"action2\"],\n"
            "  \"deadlines\": [\n"
            "    {\n"
            "      \"date\": \"YYYY-MM-DD\",\n"
            "      \"description\": \"\",\n"
            "      \"affected_agencies\": [\"...\"]\n"
            "    }\n"
            "  ],\n"
            "  \"requirements\": [\"req1\", \"req2\"]\n"
            "}\n"
        )

        # We'll embed enough context so the LLM can provide an analysis.
        # But we skip practice group identification here. It's already done.
        # We'll pass it anyway in case it's helpful for context, or we can omit it.
        pg_names = ", ".join(
            pg["name"] for pg in change.get("practice_groups", [])
        )

        text_block = f"""
Local Agency Type: {local_agency}
Digest Text: {digest_text}
Existing Law: {existing_law}
Proposed Change: {proposed_change}
Practice Groups (already identified): {pg_names}
"""

        return f"{instruction_block}\n{text_block}\n"

    async def _anthropic_impact_analysis(self, prompt: str) -> Dict[str, Any]:
        """
        Minimal example for calling Anthropic. Adapt for your code as needed.
        """
        # This is a stub. In practice you'd do something like:
        """
        response = await self.anthropic_client.messages.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            stream=False
        )
        return json.loads(response.content[0].text)
        """
        # For demonstration, return a dummy
        return {
            "summary": "Anthropic-based summary placeholder",
            "agency_impacts": [{
                "agency_type": "School District",
                "impact_type": "New Mandate",
                "description": "A short explanation of the new requirement.",
                "deadline": None,
                "requirements": []
            }],
            "practice_groups": [],
            "action_items": ["Coordinate with budget office"],
            "deadlines": [],
            "requirements": []
        }

    async def _openai_impact_analysis(self, prompt: str) -> Dict[str, Any]:
        """
        Minimal example for calling OpenAI chat completions in an async manner.
        """
        if not self.openai_client:
            self.logger.warning("OpenAI client not initialized. Returning dummy data.")
            return {
                "summary": "OpenAI-based summary placeholder",
                "agency_impacts": [{
                    "agency_type": "City",
                    "impact_type": "New Mandate",
                    "description": "A short explanation of the new requirement.",
                    "deadline": None,
                    "requirements": []
                }],
                "practice_groups": [],
                "action_items": ["Coordinate with city council"],
                "deadlines": [],
                "requirements": []
            }

        try:
            response = await self.openai_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an AI analyzing legislative changes for local public agencies."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0
            )
            content = response.choices[0].message["content"]
            # Attempt to parse as JSON
            return json.loads(content)
        except Exception as e:
            self.logger.error(f"Error calling OpenAI: {str(e)}")
            return {
                "summary": "LLM call failed. No additional impact data.",
                "agency_impacts": [],
                "practice_groups": [],
                "action_items": [],
                "deadlines": [],
                "requirements": []
            }

    def _parse_analysis_data(self, data: Dict[str, Any]) -> ChangeAnalysis:
        # Convert the raw dict from LLM into typed data
        summary = data.get("summary", "")
        raw_impacts = data.get("agency_impacts", [])
        agency_impacts = []
        for imp in raw_impacts:
            # Attempt to parse a date
            dline = imp.get("deadline")
            dt_obj = None
            if dline and isinstance(dline, str):
                try:
                    dt_obj = datetime.strptime(dline, "%Y-%m-%d")
                except:
                    dt_obj = None
            agency_impacts.append(
                AgencyImpact(
                    agency_type=imp.get("agency_type",""),
                    impact_type=imp.get("impact_type",""),
                    description=imp.get("description",""),
                    deadline=dt_obj,
                    requirements=imp.get("requirements", [])
                )
            )
        action_items = data.get("action_items", [])
        deadlines = data.get("deadlines", [])
        requirements = data.get("requirements", [])
        # We keep the old "practice_groups" only if the LLM returned something. 
        # But typically it should be empty now.
        practice_groups = data.get("practice_groups", [])
        return ChangeAnalysis(
            summary=summary,
            impacts=agency_impacts,
            practice_groups=practice_groups,
            action_items=action_items,
            deadlines=deadlines,
            requirements=requirements
        )

    def _update_change_with_analysis(self, change: Dict[str, Any], analysis: ChangeAnalysis):
        change["substantive_change"] = analysis.summary
        if analysis.impacts:
            # Combine them into a readable string
            lines = []
            for imp in analysis.impacts:
                line = f"{imp.agency_type}: {imp.description}"
                if imp.deadline:
                    line += f" (Deadline: {imp.deadline.strftime('%Y-%m-%d')})"
                lines.append(line)
            change["local_agency_impact"] = "\n".join(lines)
        else:
            change["local_agency_impact"] = "None"

        # We already assigned "practice_groups" from embeddings, so we only 
        # replace them here if the LLM returned something non-empty
        if analysis.practice_groups:
            change["practice_groups"] = analysis.practice_groups

        change["key_action_items"] = analysis.action_items
        change["deadlines"] = analysis.deadlines
        change["requirements"] = analysis.requirements
        change["impacts_local_agencies"] = bool(analysis.impacts)
