from dataclasses import dataclass
from typing import Dict, Optional, Set
from enum import Enum

class PracticeGroupRelevance(Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"

@dataclass
class PracticeGroup:
    name: str
    description: str

    def format_for_prompt(self, detail_level: str = "full") -> str:
        if detail_level == "minimal":
            return self.name
        elif detail_level == "brief":
            return f"{self.name}: {self.description.split('.')[0]}."
        return f"{self.name}: {self.description}"

class PracticeGroups:
    """
    Container for practice group definitions. You can expand it if needed.
    """
    def __init__(self):
        self._groups: Dict[str, PracticeGroup] = {
            "Special Education": PracticeGroup(
                name="Special Education",
                description="Focuses on IDEA, Section 504, SELPA governance, IEP compliance, etc."
            ),
            "Student Services": PracticeGroup(
                name="Student Services",
                description="Addresses laws governing student rights, discipline, Title IX, etc."
            ),
            "Charter Schools": PracticeGroup(
                name="Charter Schools",
                description="Focuses on charter school authorization and oversight."
            ),
            "Business and Facilities": PracticeGroup(
                name="Business and Facilities",
                description="Handles public agency business operations, procurement, construction, CEQA, etc."
            ),
            "Board Governance": PracticeGroup(
                name="Board Governance",
                description="Advises on the Brown Act, Public Records Act, elections, conflicts of interest."
            ),
            "Labor and Employment": PracticeGroup(
                name="Labor and Employment",
                description="Collective bargaining, employee discipline, Title VII compliance, etc."
            ),
            "Litigation": PracticeGroup(
                name="Litigation",
                description="Handles civil litigation in state/federal courts, construction disputes, etc."
            ),
            "Public Finance": PracticeGroup(
                name="Public Finance",
                description="Public agency financing, bonds, tax/revenue anticipation notes, developer fees."
            ),
            "Technology and Privacy": PracticeGroup(
                name="Technology and Privacy",
                description="Data privacy, cybersecurity compliance, technology procurement, e-records."
            )
        }

    @property
    def groups(self) -> Dict[str, PracticeGroup]:
        return self._groups

    @property
    def group_names(self) -> Set[str]:
        return {g.name for g in self._groups.values()}

    def get_prompt_text(self, detail_level: str = "full") -> str:
        return "\n".join(
            group.format_for_prompt(detail_level)
            for group in self._groups.values()
        )

    def validate_groups(self, groups):
        return [g for g in groups if g in self.group_names]

    def get_group_by_name(self, name: str) -> Optional[PracticeGroup]:
        for group in self._groups.values():
            if group.name == name:
                return group
        return None
