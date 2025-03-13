from typing import List, Dict, Any
import logging
from src.models.bill_components import DigestSection, BillSection

class JsonBuilder:
    """
    Creates the initial JSON skeleton structure from parsed digest sections.
    This structure serves as the foundation for further analysis steps.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def create_skeleton(self, digest_sections: List[DigestSection], bill_sections: List[BillSection] = None) -> Dict[str, Any]:
        """
        Create initial JSON structure from parsed digest sections and bill sections.
        Each digest section becomes a distinct change object in the JSON.
        """
        try:
            changes = []

            for section in digest_sections:
                change_id = f"change_{section.number}"

                # Convert code references to string format
                code_sections = [
                    f"{ref.code_name} Section {ref.section}"
                    for ref in section.code_references
                ]

                # Determine preliminary action type from the text
                action_type = self._determine_action_type(section.proposed_changes)

                change = {
                    "id": change_id,
                    "digest_text": section.text,
                    "existing_law": section.existing_law,
                    "proposed_change": section.proposed_changes,
                    "code_sections": code_sections,
                    "action_type": action_type,
                    "bill_sections": [],
                    "impacts_public_agencies": None,
                    "impact_analysis": None,
                    "practice_groups": []
                }

                changes.append(change)

            skeleton = {
                "changes": changes,
                "metadata": {
                    "total_changes": len(changes),
                    "has_agency_impacts": False,
                    "practice_groups_affected": []
                }
            }

            # Add bill sections to the skeleton
            if bill_sections:
                bill_sections_list = []
                for bs in bill_sections:
                    code_mods = []
                    for ref in bs.code_references:
                        code_mods.append({
                            "code_name": ref.code_name,
                            "section": ref.section,
                            "action": getattr(ref, "action", None)
                        })
                    bill_sections_list.append({
                        "number": bs.number,
                        "original_label": bs.original_label,  # Include the original label
                        "text": bs.text,
                        "code_modifications": code_mods
                    })
                skeleton["bill_sections"] = bill_sections_list

            return skeleton
        except Exception as e:
            self.logger.error(f"Error creating JSON skeleton: {str(e)}")
            raise

    def _determine_action_type(self, proposed_change: str) -> str:
        text = proposed_change.lower()
        if "repeal" in text:
            if "add" in text:
                return "REPEAL_AND_ADD"
            return "REPEAL"
        elif any(word in text for word in ["add", "establish", "create"]):
            return "ADD"
        elif any(word in text for word in ["amend", "revise", "modify", "change"]):
            return "AMEND"
        return "AMEND"

    def validate_skeleton(self, skeleton: Dict[str, Any]) -> bool:
        try:
            if not isinstance(skeleton, dict):
                return False
            if "changes" not in skeleton or "metadata" not in skeleton:
                return False

            required_fields = {
                "id", "digest_text", "existing_law", "proposed_change",
                "code_sections", "action_type", "bill_sections",
                "impacts_public_agencies", "impact_analysis", "practice_groups"
            }

            for change in skeleton["changes"]:
                if not isinstance(change, dict):
                    return False
                if not required_fields.issubset(change.keys()):
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Error validating JSON skeleton: {str(e)}")
            return False

    def update_metadata(self, skeleton: Dict[str, Any]) -> Dict[str, Any]:
        try:
            changes = skeleton["changes"]
            skeleton["metadata"].update({
                "total_changes": len(changes),
                "has_agency_impacts": any(
                    change.get("impacts_public_agencies")
                    for change in changes
                ),
                "practice_groups_affected": sorted(list(set(
                    group["name"]  # Extract just the name field from each group dictionary
                    for change in changes
                    for group in change.get("practice_groups", [])
                    if isinstance(group, dict) and "name" in group  # Ensure it's a valid group dict
                )))
            })
            return skeleton
        except Exception as e:
            self.logger.error(f"Error updating JSON skeleton metadata: {str(e)}")
            raise
