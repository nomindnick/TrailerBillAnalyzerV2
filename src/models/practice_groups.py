from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum

class PracticeGroupRelevance(Enum):
    """Defines the relevance level of a practice group for a given change"""
    PRIMARY = "primary"
    SECONDARY = "secondary"

@dataclass
class PracticeGroup:
    """Represents a practice group and its description"""
    name: str
    description: str

    def format_for_prompt(self, detail_level: str = "full") -> str:
        """Format practice group info for different prompt types"""
        if detail_level == "minimal":
            return self.name
        elif detail_level == "brief":
            return f"{self.name}: {self.description.split('.')[0]}."
        return f"{self.name}: {self.description}"

class PracticeGroups:
    """Container for practice group definitions and related methods"""
    def __init__(self):
        self.groups: Dict[str, PracticeGroup] = {
            "special_education": PracticeGroup(
                name="Special Education",
                description="Handles matters involving the Individuals with Disabilities Education Act (IDEA), Section 504, and related California special education laws. Primary focus areas include IEP compliance, special education due process, SELPA governance, mental health services, and disputes regarding placement, services, and accommodations for students with disabilities."
            ),
            "student_services": PracticeGroup(
                name="Student Services",
                description="Addresses laws governing student rights, discipline, and educational programs including student free speech, privacy rights, search and seizure, suspension/expulsion, discrimination, harassment, and Title IX compliance. Covers matters related to student records, residency, attendance, transfers, and specialized programs like continuation schools and community day schools."
            ),
            "charter_schools": PracticeGroup(
                name="Charter Schools",
                description="Focuses on charter school authorization, oversight, and facilities issues under California Charter Schools Act and Proposition 39. Key areas include petition review/renewal, memoranda of understanding, facilities agreements, oversight compliance, and revocation proceedings."
            ),
            "business_facilities": PracticeGroup(
                name="Business and Facilities",
                description="Handles public agency business operations including procurement, contracting, construction, real property transactions, and facilities funding. Core areas include bidding requirements, construction contracts, developer fees, property acquisition/disposition, environmental compliance (CEQA), and state facilities funding programs."
            ),
            "board_governance": PracticeGroup(
                name="Board Governance",
                description="Advises on laws governing public agency operations including the Brown Act, Public Records Act, Political Reform Act, and California Voting Rights Act. Focuses on board policies, conflicts of interest, ethics requirements, election matters, and public transparency obligations."
            ),
            "labor_employment": PracticeGroup(
                name="Labor and Employment",
                description="Covers employment law matters including collective bargaining, employee discipline, discrimination/harassment, leaves, accommodations, and wage/hour compliance. Key areas include certificated and classified employment, PERB proceedings, FEHA/Title VII compliance, and CalSTRS/CalPERS benefits."
            ),
            "litigation": PracticeGroup(
                name="Litigation",
                description="Handles civil litigation in state and federal courts including writs, civil rights claims, construction disputes, and administrative proceedings. Focus areas include ADA compliance, discrimination claims, personal injury defense, and challenges to agency decisions."
            ),
            "public_finance": PracticeGroup(
                name="Public Finance",
                description="Advises on public agency financing including bonds, certificates of participation, and special taxes/assessments. Key areas include Proposition 39 bonds, refunding bonds, tax/revenue anticipation notes, developer fees, and parcel taxes."
            ),
            "technology_privacy": PracticeGroup(
                name="Technology and Privacy",
                description="Addresses technology procurement, data privacy, electronic communications, and records retention requirements. Focus areas include student data privacy, cybersecurity compliance, technology contracts, and electronic public records obligations."
            )
        }

    def get_prompt_text(self, detail_level: str = "full") -> str:
        """Generate formatted text for AI prompt"""
        return "\n".join(
            group.format_for_prompt(detail_level)
            for group in self.groups.values()
        )

    def validate_groups(self, groups: List[str]) -> List[str]:
        """Validate that provided groups exist"""
        valid_names = {group.name for group in self.groups.values()}
        return [g for g in groups if g in valid_names]

    def get_group_by_name(self, name: str) -> Optional[PracticeGroup]:
        """Get a practice group by its display name"""
        for group in self.groups.values():
            if group.name == name:
                return group
        return None