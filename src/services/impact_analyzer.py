from typing import Dict, Any
import logging
import json
import os
import openai
from src.models.practice_groups import PracticeGroups

from src.logging_config import get_module_logger

class ImpactAnalyzer:
    def __init__(self):
        """Initialize the analyzer with OpenAI client and logger."""
        self.logger = logging.getLogger(__name__)

        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            self.logger.error("OPENAI_API_KEY environment variable is not set")
            raise ValueError("OPENAI_API_KEY environment variable is not set")

        openai.api_key = api_key
        self.model = "gpt-4"
        self.practice_groups = PracticeGroups()

    async def analyze_changes(self, skeleton: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze all changes in the JSON skeleton for:
          - Public agency impacts
          - Practice group relevance
          - Key action items
          - Concise summary focusing on practical implications
        """
        try:
            for change in skeleton["changes"]:
                if change["bill_sections"]:
                    analyzed_change = await self._analyze_single_change(change)
                    change.update(analyzed_change)

            # After analysis, update metadata
            skeleton["metadata"]["has_agency_impacts"] = any(
                c.get("impacts_public_agencies") for c in skeleton["changes"]
            )
            skeleton["metadata"]["practice_groups_affected"] = sorted(list(set(
                gp["name"]
                for c in skeleton["changes"] for gp in c.get("practice_groups", [])
                if gp["relevance"] == "primary"
            )))

            return skeleton

        except Exception as e:
            self.logger.error(f"Error analyzing changes: {str(e)}")
            raise

    async def _analyze_single_change(self, change: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a single change for local agency impact using GPT.
        Encourages a concise, plain-English summary with practical action items.
        """
        system_instructions = (
            "You are a legal analyst specializing in California law, especially public agency impacts. "
            "Provide a concise analysis focusing on practical implications, compliance requirements, and "
            "key action items for local agencies (e.g., counties, cities, special districts). "
            "Use plain English. Limit restating statutory text. "
            "Focus on what attorneys actually need to know."
        )

        user_prompt = {
            "digest_number": change.get("digest_number"),
            "existing_law": change.get("existing_law"),
            "proposed_change": change.get("proposed_change"),
            "code_sections": change.get("code_sections"),
            "action_type": change.get("action_type"),
        }

        messages = [
            {"role": "system", "content": system_instructions},
            {
                "role": "user",
                "content": (
                    f"Analyze this legislative change:\n\n"
                    f"{json.dumps(user_prompt, indent=2)}\n\n"
                    "Return valid JSON only with the following fields:\n"
                    "{\n"
                    "  \"impacts_public_agencies\": boolean,\n"
                    "  \"substantive_change\": string,\n"
                    "  \"local_agency_impact\": string,\n"
                    "  \"analysis\": string,\n"
                    "  \"key_action_items\": [string],\n"
                    "  \"impacted_agencies\": [string],\n"
                    "  \"practice_groups\": [\n"
                    "    {\n"
                    "      \"name\": string,\n"
                    "      \"relevance\": \"primary\" or \"secondary\"\n"
                    "    }\n"
                    "  ]\n"
                    "}\n\n"
                    "Keep it concise. Focus on real-world implications for public agencies."
                ),
            }
        ]

        try:
            response = await self._call_openai_api(messages)
            # Attempt to parse the JSON response
            parsed = {}
            try:
                parsed = json.loads(response)
            except json.JSONDecodeError:
                self.logger.warning("Could not parse response as JSON; returning default.")
                return self._get_default_analysis()

            # Validate fields
            if not isinstance(parsed, dict):
                return self._get_default_analysis()

            return {
                "impacts_public_agencies": bool(parsed.get("impacts_public_agencies", False)),
                "substantive_change": str(parsed.get("substantive_change", "")),
                "local_agency_impact": str(parsed.get("local_agency_impact", "")),
                "analysis": str(parsed.get("analysis", "")),
                "key_action_items": parsed.get("key_action_items", []),
                "impacted_agencies": parsed.get("impacted_agencies", []),
                "practice_groups": [
                    pg for pg in parsed.get("practice_groups", [])
                    if isinstance(pg, dict) and pg.get("name") and pg.get("relevance") in ("primary", "secondary")
                ]
            }

        except Exception as e:
            self.logger.error(f"Error analyzing single change: {str(e)}")
            return self._get_default_analysis()

    async def _call_openai_api(self, messages):
        """
        Helper for making an async call to OpenAI's chat completion.
        """
        return openai.ChatCompletion.create(
            model=self.model,
            messages=messages,
            temperature=0
        )["choices"][0]["message"]["content"]

    def _get_default_analysis(self) -> Dict[str, Any]:
        """
        Return a default, no-impact analysis if the AI call fails.
        """
        return {
            "impacts_public_agencies": False,
            "substantive_change": "",
            "local_agency_impact": "",
            "analysis": "",
            "key_action_items": [],
            "impacted_agencies": [],
            "practice_groups": []
        }

    def get_analysis_stats(self, skeleton: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get statistics about the impact analysis results.
        """
        total_changes = len(skeleton["changes"])
        impacting_changes = len([
            c for c in skeleton["changes"]
            if c.get("impacts_public_agencies")
        ])

        practice_group_counts = {}
        for c in skeleton["changes"]:
            for pg in c.get("practice_groups", []):
                name = pg.get("name")
                if not name:
                    continue
                if name not in practice_group_counts:
                    practice_group_counts[name] = {
                        "primary": 0,
                        "secondary": 0
                    }
                if pg.get("relevance") == "primary":
                    practice_group_counts[name]["primary"] += 1
                else:
                    practice_group_counts[name]["secondary"] += 1

        return {
            "total_changes": total_changes,
            "impacting_changes": impacting_changes,
            "impact_rate": impacting_changes / total_changes if total_changes else 0,
            "practice_group_distribution": practice_group_counts
        }

    def validate_analysis(self, skeleton: Dict[str, Any]) -> list:
        """
        Validate the impact analysis results and return any issues found.
        """
        issues = []

        for change in skeleton["changes"]:
            if change.get("impacts_public_agencies") and not change.get("analysis"):
                issues.append({
                    "type": "missing_analysis",
                    "id": change["id"],
                    "message": "Impact marked but no analysis provided"
                })

            if not change.get("impacts_public_agencies") and change.get("analysis"):
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
