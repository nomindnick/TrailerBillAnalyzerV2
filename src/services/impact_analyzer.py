from typing import Dict, List, Any, Optional
import logging
import json
from openai import OpenAI
from src.models.practice_groups import PracticeGroups, PracticeGroupRelevance

from src.logging_config import get_module_logger

class ImpactAnalyzer:
    """
    Analyzes each change in the trailer bill for its impact on public agencies
    and determines relevant practice groups.
    """

    def __init__(self):
        """Initialize the analyzer with OpenAI client and logger."""
        self.logger = logging.getLogger(__name__)
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = "gpt-4o-2024-08-06"
        self.practice_groups = PracticeGroups()

    async def analyze_changes(self, skeleton: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze all changes in the JSON skeleton for impacts and practice groups."""
        try:
            for change in skeleton["changes"]:
                if change["bill_sections"]:
                    analyzed_change = await self._analyze_single_change(change)
                    change.update(analyzed_change)

            # Update metadata using the new impacts_local_agencies field
            skeleton["metadata"]["has_agency_impacts"] = any(
                change.get("impacts_local_agencies")  # Changed from impacts_public_agencies
                for change in skeleton["changes"]
            )

            skeleton["metadata"]["practice_groups_affected"] = sorted(list(set(
                group["name"]
                for change in skeleton["changes"]
                for group in change.get("practice_groups", [])
                if change.get("impacts_local_agencies") and group.get("relevance") == "primary"  # Added impacts_local_agencies check
            )))

            return skeleton

        except Exception as e:
            self.logger.error(f"Error analyzing changes: {str(e)}")
            raise 

    async def _analyze_single_change(self, change: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze a single change for its impact on public agencies."""
        try:
            messages = [
                {
                    "role": "system",
                    "content": """You are analyzing changes to California law that may affect public agencies.
    Focus on practical operational impacts, compliance requirements, and implementation considerations.
    Return only valid JSON with your analysis."""
                },
                {
                    "role": "user",
                    "content": self._build_analysis_prompt(change)
                }
            ]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)
            return self._validate_analysis_result(result)

        except Exception as e:
            self.logger.error(f"Error analyzing change {change.get('id', 'UNKNOWN')}: {str(e)}")
            return self._get_default_analysis()

    def _build_analysis_prompt(self, change: Dict[str, Any]) -> str:
        """Build a comprehensive prompt for the AI analysis."""
        practice_group_info = self.practice_groups.get_prompt_text(detail_level="brief")

        return f"""You are a legal analyst specializing in California law, with a focus on how legislative changes impact local public agencies. Your task is to analyze a proposed change to California law and determine its relevance to local public agencies such as school districts, cities, counties, special districts, and joint powers authorities.

    First, review the following information about the proposed law change:

    <digest_text>
    {change["digest_text"]}
    </digest_text>

    <existing_law>
    {change["existing_law"]}
    </existing_law>

    <proposed_change>
    {change["proposed_change"]}
    </proposed_change>

    <code_sections>
    {', '.join(change["code_sections"])}
    </code_sections>

    Now, carefully analyze this information to determine if the change directly impacts any local agencies. Conduct your analysis inside <detailed_analysis> tags:

    <detailed_analysis>
    1. Affected Local Agencies:
       [List out the specific types of local agencies that might be affected by this change]

    2. New Obligations:
       [Analyze whether the change creates any new obligations for local agencies]
       - What specific new responsibilities or duties are introduced?
       - Can you provide an example of how a local agency might need to adapt to meet these new obligations?

    3. Funding, Operations, or Compliance:
       [Analyze whether the change affects local agency funding, operations, or compliance requirements]
       - How might this change impact local agency budgets?
       - What operational processes might need to be modified?
       - Are there new compliance measures that local agencies will need to implement?

    4. Interaction with State Agencies:
       [Analyze whether the change alters how local agencies interact with state agencies]
       - Does this change introduce new reporting requirements to state agencies?
       - Are there changes in how local agencies might receive guidance or oversight from state agencies?

    5. Programs or Services:
       [Analyze whether the change affects programs or services that local agencies rely on]
       - What specific programs or services might be impacted?
       - How might these changes affect the delivery of services to the public?

    6. Key Points for Public Agency Clients:
       [Summarize the most important aspects of this change that attorneys should quickly understand for their public agency clients]
       - What are the top 3-5 takeaways from this change?
       - Are there any immediate actions that local agencies should consider?

    Conclusion:
    [Based on the above analysis, determine if this change directly impacts local public agencies. Provide a brief summary of why or why not.]
    </detailed_analysis>

    If you've determined that there ARE local agency impacts, consider the following practice groups and their areas of focus:

    <practice_group_info>
    {practice_group_info}
    </practice_group_info>

    Guidelines for Practice Group Assignment:

    1. Primary Relevance (requires at least one):
       - Creates direct compliance obligations for local agencies within that practice area
       - Requires significant operational changes in that practice area
       - Materially affects funding or resources in that practice area
       - Imposes new legal requirements or liabilities in that practice area

    2. Secondary Relevance (requires at least one):
       - Creates optional opportunities that local agencies may want to consider
       - May require minor procedural updates in that practice area
       - Has indirect effects on operations or resources in that practice area
       - Changes the context in which local agencies operate without imposing direct requirements

    3. No Relevance:
       - Changes that only affect state agencies
       - Changes that create theoretical possibilities for local agency involvement
       - Changes that might have very indirect or speculative effects
       - Administrative or technical changes with no operational impact

    Your analysis should:
    1. Assign practice groups conservatively - only when there's a clear connection
    2. Provide distinct analysis for each practice group rather than duplicating content
    3. Focus on concrete, specific impacts rather than speculative possibilities
    4. Distinguish clearly between mandatory requirements and optional opportunities

    Now, provide your final analysis in the following JSON format:

    {{
      "impacts_local_agencies": boolean,
      "impact_analysis": string or null,
      "practice_groups": [
        {{
          "name": string,
          "relevance": "primary" or "secondary"
        }}
      ]
    }}

    Ensure that:
    1. "impacts_local_agencies" is a boolean indicating if this DIRECTLY impacts local public agencies.
    2. "impact_analysis" is a detailed analysis of how this affects local public agencies, or null if there is no impact.
    3. "practice_groups" is an array of objects, each containing a "name" and "relevance" field. Only include practice groups if there is a genuine connection to local agency impacts.
    4. If there are no local agency impacts, mark "impacts_local_agencies" as false, set "impact_analysis" to null, and include an empty array for "practice_groups".

    Remember to focus on providing a useful analysis that allows attorneys to quickly understand if the proposed change has sections directly relevant to their public agency clients."""

    def _validate_analysis_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and clean up the AI analysis result."""
        try:
            validated = {
                "impacts_local_agencies": bool(result.get("impacts_local_agencies", False)),
                "impact_analysis": str(result["impact_analysis"]) if result.get("impact_analysis") else None,
                "practice_groups": []
            }

            # Only include practice groups if there's a local agency impact
            if validated["impacts_local_agencies"]:
                if isinstance(result.get("practice_groups"), list):
                    validated_groups = []
                    for group in result["practice_groups"]:
                        if not isinstance(group, dict):
                            continue

                        name = group.get("name")
                        relevance = group.get("relevance")

                        # Verify group exists and relevance is valid
                        if (self.practice_groups.get_group_by_name(name) and 
                            relevance in ("primary", "secondary")):
                            validated_groups.append({
                                "name": name,
                                "relevance": relevance
                            })

                    validated["practice_groups"] = validated_groups

            return validated 

        except Exception as e:
            self.logger.error(f"Error validating analysis result: {str(e)}")
            return self._get_default_analysis()

    def _get_default_analysis(self) -> Dict[str, Any]:
        """Get default analysis values for error cases."""
        return {
            "impacts_public_agencies": False,
            "impact_analysis": None,
            "practice_groups": []
        }

    def _get_default_value(self, field: str) -> Any:
        """Get default value for a specific field."""
        defaults = {
            "impacts_public_agencies": False,
            "impact_analysis": None,
            "practice_groups": []
        }
        return defaults.get(field)

    def get_analysis_stats(self, skeleton: Dict[str, Any]) -> Dict[str, Any]:
        """Get statistics about the impact analysis results."""
        total_changes = len(skeleton["changes"])
        impacting_changes = len([
            c for c in skeleton["changes"]
            if c.get("impacts_public_agencies")
        ])

        practice_group_counts = {}
        for group in self.practice_groups.groups.values():
            primary_count = len([
                c for c in skeleton["changes"]
                if any(pg.get("name") == group.name and pg.get("relevance") == "primary"
                      for pg in c.get("practice_groups", []))
            ])
            secondary_count = len([
                c for c in skeleton["changes"]
                if any(pg.get("name") == group.name and pg.get("relevance") == "secondary"
                      for pg in c.get("practice_groups", []))
            ])
            if primary_count > 0 or secondary_count > 0:
                practice_group_counts[group.name] = {
                    "primary": primary_count,
                    "secondary": secondary_count,
                    "total": primary_count + secondary_count
                }

        return {
            "total_changes": total_changes,
            "impacting_changes": impacting_changes,
            "impact_rate": impacting_changes / total_changes if total_changes > 0 else 0,
            "practice_group_distribution": practice_group_counts
        }

    def validate_analysis(self, skeleton: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Validate the impact analysis results and return any issues found."""
        issues = []

        for change in skeleton["changes"]:
            if change.get("impacts_public_agencies") and not change.get("impact_analysis"):
                issues.append({
                    "type": "missing_analysis",
                    "id": change["id"],
                    "message": "Impact marked but no analysis provided"
                })

            if not change.get("impacts_public_agencies") and change.get("impact_analysis"):
                issues.append({
                    "type": "inconsistent_analysis",
                    "id": change["id"],
                    "message": "Analysis provided but no impact marked"
                })

            if change.get("impacts_public_agencies") and not change.get("practice_groups"):
                issues.append({
                    "type": "missing_practice_groups",
                    "id": change["id"],
                    "message": "Impact marked but no practice groups assigned"
                })

        return issues