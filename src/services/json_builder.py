from typing import List, Dict, Any
import logging
from src.models.bill_components import DigestSection, CodeReference

class JsonBuilder:
    """
    Creates the initial JSON skeleton structure from parsed digest sections.
    This structure serves as the foundation for further analysis steps.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def create_skeleton(self, digest_sections: List[DigestSection]) -> Dict[str, Any]:
        """
        Create initial JSON structure from parsed digest sections.
        Each digest section becomes a distinct change object in the JSON.

        Args:
            digest_sections: List of parsed DigestSection objects

        Returns:
            Dict containing the structured JSON with change objects
        """
        try:
            changes = []

            for section in digest_sections:
                # Create a unique ID for this change
                change_id = f"change_{section.number}"

                # Convert code references to string format
                code_sections = [
                    f"{ref.code_name} Section {ref.section}"
                    for ref in section.code_references
                ]

                # Determine preliminary action type from the text
                action_type = self._determine_action_type(section.proposed_changes)

                # Create the change object
                change = {
                    "id": change_id,
                    "digest_text": section.text,
                    "existing_law": section.existing_law,
                    "proposed_change": section.proposed_changes,
                    "code_sections": code_sections,
                    "action_type": action_type,
                    "bill_sections": [],  # Will be filled in by section matcher
                    "impacts_public_agencies": None,  # Will be filled in by impact analyzer
                    "impact_analysis": None,  # Will be filled in by impact analyzer
                    "practice_groups": []  # Will be filled in by impact analyzer
                }

                changes.append(change)

            # Create the full structure
            return {
                "changes": changes,
                "metadata": {
                    "total_changes": len(changes),
                    "has_agency_impacts": False,  # Will be updated during analysis
                    "practice_groups_affected": []  # Will be updated during analysis
                }
            }

        except Exception as e:
            self.logger.error(f"Error creating JSON skeleton: {str(e)}")
            raise

    def _determine_action_type(self, proposed_change: str) -> str:
        """
        Determine the preliminary action type from the proposed change text.
        This is a basic determination that may be refined in later analysis.

        Args:
            proposed_change: The text describing the proposed change

        Returns:
            String indicating the action type (ADD, AMEND, or REPEAL)
        """
        text = proposed_change.lower()

        # Look for key phrases that indicate the type of change
        if "repeal" in text:
            if "add" in text:
                return "REPEAL_AND_ADD"
            return "REPEAL"
        elif "add" in text or "establish" in text or "create" in text:
            return "ADD"
        elif "amend" in text or "revise" in text or "modify" in text or "change" in text:
            return "AMEND"

        # Default to AMEND if we can't determine specifically
        return "AMEND"

    def validate_skeleton(self, skeleton: Dict[str, Any]) -> bool:
        """
        Validate that the JSON skeleton has the required structure and fields.

        Args:
            skeleton: The JSON structure to validate

        Returns:
            bool indicating whether the structure is valid
        """
        try:
            # Check top level structure
            if not isinstance(skeleton, dict):
                return False
            if "changes" not in skeleton or "metadata" not in skeleton:
                return False

            # Check each change object
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
        """
        Update the metadata section of the JSON skeleton based on current content.
        This should be called after any modifications to the changes array.

        Args:
            skeleton: The current JSON structure

        Returns:
            Updated JSON structure with refreshed metadata
        """
        try:
            changes = skeleton["changes"]

            # Update the metadata
            skeleton["metadata"].update({
                "total_changes": len(changes),
                "has_agency_impacts": any(
                    change.get("impacts_public_agencies")
                    for change in changes
                ),
                "practice_groups_affected": sorted(list(set(
                    group
                    for change in changes
                    for group in change.get("practice_groups", [])
                )))
            })

            return skeleton

        except Exception as e:
            self.logger.error(f"Error updating JSON skeleton metadata: {str(e)}")
            raise