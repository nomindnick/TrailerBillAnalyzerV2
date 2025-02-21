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
        """
        Return the group's information in a format suitable for prompts.
        detail_level can be "minimal", "brief", or "full".
        """
        if detail_level == "minimal":
            return self.name
        elif detail_level == "brief":
            # Return the first sentence or so of the description.
            return f"{self.name}: {self.description.split('.')[0]}."
        else:
            # "full" detail: return the entire description
            return f"{self.name}: {self.description}"

class PracticeGroups:
    """
    Container for the law firm's actual practice group definitions, with
    nuanced descriptions to help AI determine the most relevant practice group
    for each legislative change in a trailer bill.
    """

    def __init__(self):
        self._groups: Dict[str, PracticeGroup] = {
            "Charter Schools": PracticeGroup(
                name="Charter Schools",
                description=(
                    "Assists public agencies that authorize or oversee charter schools with all aspects of "
                    "charter school law. This includes reviewing new and renewal petitions, drafting and negotiating "
                    "MOUs, addressing facilities issues (including Proposition 39), and advising on special education "
                    "compliance within charter schools. Also handles oversight, revocations, and litigation or disputes "
                    "regarding charter school operations and facilities use."
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
                    "the Ralph M. Brown Act's open meeting requirements, Public Records Act (PRA) compliance, conflicts "
                    "of interest, ethics, elections, and board bylaws/policies. Assists in drafting policies, conducting "
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
                    "requirements (e.g., Weingarten rights, peace officer procedural safeguards) and provides training on "
                    "investigative techniques. Helps maintain objectivity, protect agency interests, and produce "
                    "comprehensive, legally compliant investigative findings."
                )
            ),
            "Labor and Employment": PracticeGroup(
                name="Labor and Employment",
                description=(
                    "Covers all aspects of labor relations and employment law for public agencies. This includes collective "
                    "bargaining, contract grievances, hiring, discipline and dismissals, wage and hour compliance, employee "
                    "benefits and leaves, discrimination and retaliation claims, and workplace safety. Represents clients "
                    "before administrative bodies like PERB, EEOC, and DFEH, and in state and federal court. Advises on "
                    "Title VII, ADA, ADEA, FEHA, FMLA/CFRA, employee privacy rights, investigations, and employee relations "
                    "strategies, including strike preparation and settlement negotiations."
                )
            ),
            "Litigation": PracticeGroup(
                name="Litigation",
                description=(
                    "Represents public agencies in a wide range of civil litigation, administrative hearings, and appeals. "
                    "Handles disputes involving construction, contracts, personal injury and tort defense, discrimination, "
                    "harassment, employment disputes, civil rights (including Section 1983), CEQA challenges, and police or "
                    "public safety matters. The group appears before state and federal courts, arbitrations, mediations, and "
                    "administrative bodies, providing a strong, proactive defense as well as strategic advice on dispute "
                    "resolution and risk management."
                )
            ),
            "Municipal": PracticeGroup(
                name="Municipal",
                description=(
                    "Serves cities, counties, and special districts with comprehensive legal counsel on public agency matters. "
                    "Areas include land use and zoning, environmental law (including CEQA and water issues), public contracting, "
                    "fees, taxes and assessments, code enforcement, intergovernmental relations, elections and voting rights, "
                    "and open government compliance. Provides general counsel services, drafts ordinances, and represents "
                    "clients in municipal litigation, ensuring compliance with the complex legal framework surrounding local "
                    "governments."
                )
            ),
            "Public Finance": PracticeGroup(
                name="Public Finance",
                description=(
                    "Advises on public agency financing, including bond counsel and disclosure counsel services for general "
                    "obligation bonds, Mello-Roos and Mark-Roos bonds, certificates of participation, revenue bonds, and tax "
                    "and revenue anticipation notes. Assists with parcel taxes, developer fees, special assessments, and "
                    "post-issuance compliance. Works closely with clients on election-related matters, facilities planning, "
                    "and ensuring that financing practices comply with federal and state regulations."
                )
            ),
            "Special Education": PracticeGroup(
                name="Special Education",
                description=(
                    "Provides thorough counsel on all matters under IDEA, Section 504, and related laws. Handles due process "
                    "hearings, mediations, CDE/OCR complaints, and litigation involving special education services. Advises on "
                    "IEPs, SELPA governance, mental health services, discipline of students with disabilities, Section 504 "
                    "plans, and dispute resolution. Offers training, policy guidance, and legal strategies to ensure "
                    "compliance and protect the rights of students and educational agencies alike."
                )
            ),
            "Student": PracticeGroup(
                name="Student",
                description=(
                    "Focuses on issues affecting K-12 and community college students, including student rights, discipline "
                    "(suspension/expulsion), residency, student records, privacy, bullying and harassment, Title IX compliance "
                    "for students, and student fees. Also addresses free speech and expression, dress codes, extracurricular "
                    "eligibility, and compliance with a range of federal and state mandates. Provides counsel on student "
                    "policies, ensures legal compliance, and represents clients in hearings and litigation involving "
                    "student-related disputes."
                )
            ),
            "Title IX": PracticeGroup(
                name="Title IX",
                description=(
                    "Specializes in preventing and addressing sex-based discrimination and harassment in public agencies, "
                    "especially in educational settings. Advises on compliance with federal and state guidelines, sexual "
                    "misconduct investigations, athletics equity, transgender student and employee rights, and Title IX "
                    "coordinator roles. Works closely with Student, Labor, and Investigations groups to offer training, draft "
                    "policies, and ensure thorough and legally sound processes in responding to sexual harassment and assault "
                    "allegations."
                )
            ),
        }

    @property
    def groups(self) -> Dict[str, PracticeGroup]:
        """
        Returns the dictionary of practice group objects keyed by their group name.
        """
        return self._groups

    @property
    def group_names(self) -> Set[str]:
        """
        Returns a set of all practice group names.
        """
        return {g.name for g in self._groups.values()}

    def get_prompt_text(self, detail_level: str = "full") -> str:
        """
        Returns a single string containing practice group info suitable for an AI prompt.
        """
        return "\n".join(
            group.format_for_prompt(detail_level)
            for group in self._groups.values()
        )

    def validate_groups(self, groups):
        """
        Filters the provided list of group names, keeping only valid ones.
        """
        valid_names = self.group_names
        return [g for g in groups if g in valid_names]

    def get_group_by_name(self, name: str) -> Optional[PracticeGroup]:
        """
        Retrieves the practice group object by exact name match, or returns None if not found.
        """
        return self._groups.get(name, None)
