from typing import Dict, List, Any, Optional
import logging
import json
import os
from openai import OpenAI
from src.models.practice_groups import PracticeGroups, PracticeGroupRelevance

from src.logging_config import get_module_logger

class ImpactAnalyzer:
    def __init__(self):
        """Initialize the analyzer with OpenAI client and logger."""
        self.logger = logging.getLogger(__name__)

        # Get API key with explicit error handling
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            self.logger.error("OPENAI_API_KEY environment variable is not set")
            raise ValueError("OPENAI_API_KEY environment variable is not set")

        try:
            # Initialize with just the required api_key
            self.client = OpenAI(api_key=api_key)
            self.logger.info("Successfully initialized OpenAI client")
        except Exception as e:
            self.logger.error(f"Failed to initialize OpenAI client: {str(e)}")
            raise

        # Specify model
        self.model = "gpt-4o-2024-08-06"  # Updated to a current model
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
                change.get("impacts_local_agencies")
                for change in skeleton["changes"]
            )

            # Collect all practice groups that are marked as "primary" for changes that impact local agencies
            skeleton["metadata"]["practice_groups_affected"] = sorted(list(set(
                group["name"]
                for change in skeleton["changes"]
                if change.get("impacts_local_agencies")
                for group in change.get("practice_groups", [])
                if group.get("relevance") == "primary"
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
                    "content": """You are analyzing changes to California law that may affect local public agencies.
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

            # Validate and clean up the result
            validated_result = {
                "impacts_local_agencies": bool(result.get("impacts_local_agencies", False)),
                "substantive_change": str(result.get("substantive_change", "")),
                "local_agency_impact": str(result.get("local_agency_impact", "")),
                "analysis": str(result.get("analysis", "")),
                "key_action_items": result.get("key_action_items", []),
                "practice_groups": [],
                # New field to capture which agencies (cities, counties, districts, etc.) are impacted
                "impacted_agencies": result.get("impacted_agencies", [])
            }

            # Process practice groups if there are any
            if result.get("practice_groups"):
                validated_result["practice_groups"] = [
                    {
                        "name": pg["name"],
                        "relevance": pg["relevance"]
                    }
                    for pg in result["practice_groups"]
                    if self.practice_groups.get_group_by_name(pg.get("name"))
                    and pg.get("relevance") in ("primary", "secondary")
                ]

            # Log the result for debugging
            self.logger.debug(f"Analysis result for change: {json.dumps(validated_result, indent=2)}")

            return validated_result

        except Exception as e:
            self.logger.error(f"Error analyzing change: {str(e)}")
            self.logger.exception(e)  # Log full traceback
            return self._get_default_analysis()

    def _build_analysis_prompt(self, change: Dict[str, Any]) -> str:
        """Build a comprehensive prompt for the AI analysis."""
        practice_group_info = self.practice_groups.get_prompt_text(detail_level="brief")

        return f"""You are a legal analyst specializing in California law, with expertise in analyzing legislative changes that affect local public agencies like cities, counties, school districts, and special districts. Your task is to analyze a proposed change to California law and produce a clear, concise analysis that will help attorneys quickly understand if and how the change impacts their public agency clients.

Review the following information about the proposed law change:

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

Based on this information, provide your final analysis in the following JSON format:

{{
    "impacts_local_agencies": boolean,
    "substantive_change": string,
    "local_agency_impact": string,
    "analysis": string,
    "key_action_items": [string],  
    "impacted_agencies": [string],
    "practice_groups": [
        {{
            "name": string,
            "relevance": "primary" or "secondary"
        }}
    ]
}}

Requirements for each field:
1. "impacts_local_agencies": Indicate True if local agencies are materially impacted by the change, else False.
2. "substantive_change": Provide a concise description of what the law is changing.
3. "local_agency_impact": Provide a clear explanation if (and how) this change impacts local agencies.
4. "analysis": Offer a focused analysis of what attorneys need to know (requirements, compliance, operational changes, financial implications, etc.).
5. "key_action_items": 3-5 specific and actionable steps local agencies or their counsel should consider.
6. "impacted_agencies": List specific local agencies affected (e.g., cities, counties, school districts, special districts), or leave it empty if none are specifically singled out.
7. "practice_groups": Identify which practice groups are impacted. Use:
   - "primary" if the change directly imposes compliance obligations or significant operational changes in that practice area.
   - "secondary" if it creates optional or minor considerations.

If you determine that there are no local agency impacts, set "impacts_local_agencies" to false, provide a short statement in "local_agency_impact", leave "practice_groups" empty, and note "impacted_agencies" as empty.
"""

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
            if c.get("impacts_local_agencies")
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
            if change.get("impacts_local_agencies") and not change.get("analysis"):
                issues.append({
                    "type": "missing_analysis",
                    "id": change["id"],
                    "message": "Impact marked but no analysis provided"
                })

            if not change.get("impacts_local_agencies") and change.get("analysis"):
                issues.append({
                    "type": "inconsistent_analysis",
                    "id": change["id"],
                    "message": "Analysis provided but no impact marked"
                })

            if change.get("impacts_local_agencies") and not change.get("practice_groups"):
                issues.append({
                    "type": "missing_practice_groups",
                    "id": change["id"],
                    "message": "Impact marked but no practice groups assigned"
                })

        return issues
