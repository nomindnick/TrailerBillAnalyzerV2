# practice_groups.py

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
        else:
            return f"{self.name}: {self.description}"

class PracticeGroups:
    """
    Container for the law firm's actual practice group definitions,
    with nuanced descriptions to help with embeddings-based classification.
    """

    def __init__(self):
        self._groups: Dict[str, PracticeGroup] = {
            "Charter Schools": PracticeGroup(
                name="Charter Schools",
                description=(
                    "Assists school districts and county offices of education that authorize or oversee charter schools "
                    "with all aspects of charter school law. This includes reviewing new and renewal petitions, drafting "
                    "and negotiating MOUs, addressing facilities issues (including Proposition 39), and advising on special "
                    "education compliance within charter schools. Also handles oversight, revocations, and litigation or "
                    "disputes regarding charter school operations and facilities use."
                )
            ),
            "Facilities and Business": PracticeGroup(
                name="Facilities and Business",
                description=(
                    "Focuses on public agency business operations and facility-related issues. This includes procurement "
                    "of goods and services, budgeting and auditing, contract development and review, energy projects, "
                    "construction law (bidding, prevailing wage, project delivery methods), CEQA compliance, "
                    "developer fees, real property transactions (acquisition, leasing, eminent domain), and public "
                    "finance structures (including bond counsel services). Provides guidance on daily operations and "
                    "long-term planning for building and maintaining agency facilities."
                )
            ),
            "Governance": PracticeGroup(
                name="Governance",
                description=(
                    "Advises boards and elected bodies on a wide range of public agency governance issues, including "
                    "the Ralph M. Brown Act's open meeting requirements, Public Records Act compliance, conflicts of "
                    "interest, ethics, elections, and board bylaws/policies. Assists in drafting policies, conducting "
                    "effective board meetings, responding to public concerns, and ensuring transparency. Also handles "
                    "board member training, litigation defense in Brown Act suits, and best practices for board governance."
                )
            ),
            "Investigations": PracticeGroup(
                name="Investigations",
                description=(
                    "Conducts or advises on neutral, thorough, and timely internal investigations for public agencies, "
                    "covering allegations of discrimination, harassment, sexual misconduct, conflicts of interest, Title IX "
                    "matters, employee misconduct, and financial fraud. Ensures compliance with unique public-sector "
                    "requirements and provides training on investigative techniques."
                )
            ),
            "Labor and Employment": PracticeGroup(
                name="Labor and Employment",
                description=(
                    "Covers all aspects of labor relations and employment law for public agencies. This includes collective "
                    "bargaining, contract grievances, hiring, discipline and dismissals, wage and hour compliance, employee "
                    "benefits and leaves, discrimination and retaliation claims, and workplace safety. Represents clients "
                    "before administrative bodies like PERB, EEOC, and DFEH, and in court. Advises on Title VII, ADA, ADEA, "
                    "FEHA, FMLA/CFRA, employee privacy rights, investigations, and employee relations strategies."
                )
            ),
            "Litigation": PracticeGroup(
                name="Litigation",
                description=(
                    "Represents public agencies in civil litigation, administrative hearings, and appeals. Handles disputes "
                    "involving construction, contracts, personal injury/tort defense, discrimination, harassment, employment "
                    "disputes, civil rights (Section 1983), CEQA challenges, and police/public safety matters."
                )
            ),
            "Municipal": PracticeGroup(
                name="Municipal",
                description=(
                    "Serves cities, counties, and special districts with comprehensive legal counsel on public agency matters. "
                    "Areas include land use and zoning, environmental law (CEQA/water), public contracting, fees, taxes, "
                    "assessments, code enforcement, intergovernmental relations, law enforcement, elections, open government "
                    "compliance, and municipal litigation."
                )
            ),
            "Public Finance": PracticeGroup(
                name="Public Finance",
                description=(
                    "Advises on public agency financing, including bond counsel services for general obligation bonds, "
                    "Mello-Roos and Mark-Roos bonds, certificates of participation, revenue bonds, and tax/revenue notes. "
                    "Assists with parcel taxes, developer fees, special assessments, and post-issuance compliance."
                )
            ),
            "Special Education": PracticeGroup(
                name="Special Education",
                description=(
                    "Provides counsel on all matters under IDEA, Section 504, and related laws. Handles due process "
                    "hearings, mediations, CDE/OCR complaints, and litigation. Advises on IEPs, SELPA governance, "
                    "mental health services, discipline of students with disabilities, and Section 504 compliance."
                )
            ),
            "Student": PracticeGroup(
                name="Student",
                description=(
                    "Focuses on issues affecting K-12 and community college students, including student rights, discipline, "
                    "residency, records, bullying, Title IX compliance for students, and student fees. Also addresses "
                    "free speech, dress codes, extracurricular eligibility, and ensures legal compliance in student-related "
                    "disputes."
                )
            ),
            "Title IX": PracticeGroup(
                name="Title IX",
                description=(
                    "Specializes in preventing and addressing sex-based discrimination and harassment in public agencies. "
                    "Advises on compliance with guidelines, sexual misconduct investigations, athletics equity, transgender "
                    "rights, and Title IX coordinator roles, ensuring thorough and legally sound processes."
                )
            ),
        }

    @property
    def groups(self) -> Dict[str, PracticeGroup]:
        return self._groups

    @property
    def group_names(self) -> Set[str]:
        return {g.name for g in self._groups.values()}

    def validate_groups(self, groups):
        valid_names = self.group_names
        return [g for g in groups if g in valid_names]

    def get_group_by_name(self, name: str) -> Optional[PracticeGroup]:
        return self._groups.get(name, None)
