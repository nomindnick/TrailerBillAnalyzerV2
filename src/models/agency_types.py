from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from enum import Enum


class AgencyImpactLevel(Enum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    NONE = "none"


@dataclass
class AgencyType:
    """
    Represents a type of local public agency with description for embedding comparison
    """
    name: str
    description: str
    keywords: List[str]
    examples: List[str]

    def format_for_embedding(self) -> str:
        """Format agency type info for embedding generation"""
        return f"{self.name}: {self.description} Examples: {', '.join(self.examples)}. Keywords: {', '.join(self.keywords)}"


class AgencyTypes:
    """
    Container for all local public agency types supported by the system
    """

    def __init__(self):
        self._agency_types: Dict[str, AgencyType] = {
            "School District": AgencyType(
                name="School District",
                description="A local educational agency (LEA) that operates K-12 public schools within a specific geographic area. School districts are governed by elected school boards and are responsible for implementing state education requirements, maintaining school facilities, hiring staff, and providing educational services to students.",
                keywords=["school district", "unified school district", "elementary school district", "high school district", "K-12 district", "LEA", "local educational agency", "school board", "board of education", "public school", "superintendent", "LCFF", "local control funding formula"],
                examples=["Los Angeles Unified School District", "San Diego Unified School District", "Long Beach Unified School District", "Fresno Unified School District", "elementary school district", "high school district"]
            ),

            "Charter School": AgencyType(
                name="Charter School",
                description="A publicly funded independent school established under a charter with a local school district, county office of education, or the state board of education. Charter schools have more flexibility in their operations but must meet accountability requirements specified in their charter petition.",
                keywords=["charter school", "public charter", "charter academy", "charter network", "charter management organization", "CMO", "charter petition", "charter authorizer", "charter renewal", "independent charter", "dependent charter", "SB 740", "Prop 39", "authorizing agency"],
                examples=["Green Dot Public Schools", "KIPP Schools", "Aspire Public Schools", "independent charter school", "network charter"]
            ),

            "County Office of Education": AgencyType(
                name="County Office of Education",
                description="A regional educational agency that provides services to school districts within a county, including specialized educational programs, fiscal oversight, credentialing, curriculum support, and staff development. COEs also operate schools for specific student populations and serve as an intermediary between local districts and the state.",
                keywords=["county office of education", "COE", "county superintendent of schools", "county board of education", "SELPA", "alternative education", "court schools", "juvenile court schools", "regional occupational program", "ROP", "county committee on school district organization"],
                examples=["Los Angeles County Office of Education", "San Diego County Office of Education", "Orange County Department of Education", "county committee", "county board"]
            ),

            "Community College": AgencyType(
                name="Community College",
                description="A public two-year college that offers associate degrees, certificates, and transfer programs. Community colleges are governed by locally elected boards of trustees and are part of the California Community College system, serving as open-access institutions providing higher education, career technical education, and workforce development.",
                keywords=["community college", "community college district", "junior college", "two-year college", "CCC", "California Community Colleges", "board of trustees", "academic senate", "associate degree", "certificate program", "transfer program", "AB 1725", "student equity", "SSSP", "guided pathways"],
                examples=["Los Angeles Community College District", "San Diego Community College District", "Peralta Community College District", "City College of San Francisco", "community college district"]
            ),

            "City": AgencyType(
                name="City",
                description="A general law or charter municipality that provides local government services to residents in an incorporated area. Cities have police powers to regulate local affairs including land use, public safety, infrastructure, utilities, and community services. Cities are governed by elected city councils and operate under either general law or their own charter.",
                keywords=["city", "town", "municipality", "incorporated city", "general law city", "charter city", "city council", "mayor", "city manager", "municipal code", "ordinance", "city attorney", "city clerk", "planning commission", "zoning", "redevelopment", "public works", "police department", "fire department"],
                examples=["City of Los Angeles", "City of San Diego", "City of San Francisco", "City of Sacramento", "municipal government", "incorporated area"]
            ),

            "County": AgencyType(
                name="County",
                description="A political subdivision of the state that provides a wide range of services to residents in both incorporated and unincorporated areas. Counties administer state and federal programs, maintain public records, conduct elections, assess property, collect taxes, and provide health and social services. They are governed by elected boards of supervisors.",
                keywords=["county", "board of supervisors", "county executive", "county administrator", "county counsel", "sheriff", "district attorney", "assessor", "tax collector", "recorder", "elections", "public health", "social services", "probation", "public guardian", "county hospital", "mental health services", "unincorporated area"],
                examples=["County of Los Angeles", "County of San Diego", "County of Orange", "County of Sacramento", "county government", "unincorporated county"]
            ),

            "Special District": AgencyType(
                name="Special District",
                description="An independent local government agency formed to provide specific services within a defined area. Special districts focus on particular functions such as water, fire protection, healthcare, parks, cemeteries, mosquito abatement, or transit. They are governed by elected or appointed boards and typically have taxing or fee authority to fund their operations.",
                keywords=["special district", "independent special district", "dependent special district", "utility district", "water district", "fire district", "healthcare district", "hospital district", "park district", "recreation district", "sanitation district", "cemetery district", "mosquito abatement district", "irrigation district", "resource conservation district", "community services district", "CSD", "municipal utility district", "MUD", "transit district"],
                examples=["East Bay Municipal Utility District", "Metropolitan Water District", "Sacramento Municipal Utility District", "San Francisco Bay Area Rapid Transit District (BART)", "water district", "fire protection district", "healthcare district"]
            ),

            "Joint Powers Authority": AgencyType(
                name="Joint Powers Authority",
                description="A legal entity created by agreement between two or more public agencies to jointly exercise common powers. JPAs enable collaboration across jurisdictional boundaries for regional planning, shared services, risk pooling, financing, or infrastructure projects. They are governed by appointed boards representing the member agencies.",
                keywords=["joint powers authority", "JPA", "joint powers agreement", "regional authority", "joint agency", "joint exercise of powers", "interagency cooperation", "Government Code 6500", "risk pool", "insurance pool", "financing authority", "regional planning", "shared services", "transportation authority", "waste management authority", "water authority"],
                examples=["Association of Bay Area Governments (ABAG)", "California Joint Powers Insurance Authority", "South Bay Cities Council of Governments", "Sacramento Area Council of Governments (SACOG)", "Southern California Association of Governments (SCAG)"]
            ),

            "No Local Agency Impact": AgencyType(
                name="No Local Agency Impact",
                description="The legislative change does not directly or indirectly impact any local public agencies. The provisions only affect state agencies, private entities, or individuals without creating requirements, funding changes, or regulatory impacts for local government entities.",
                keywords=["no impact", "no local impact", "state only", "no agency impact", "non-local", "state agency only", "private entity", "individual", "no local government", "no jurisdiction", "state department", "state board", "state commission"],
                examples=["State departments only", "Private organizations only", "No effect on local bodies", "State-level oversight only", "No local agency requirements"]
            )
        }

    @property
    def agency_types(self) -> Dict[str, AgencyType]:
        """Returns dictionary of agency types"""
        return self._agency_types

    @property
    def agency_names(self) -> Set[str]:
        """Returns set of agency type names"""
        return set(self._agency_types.keys())

    def get_agency_type(self, name: str) -> Optional[AgencyType]:
        """Get agency type by name"""
        return self._agency_types.get(name)

    def get_all_formatted_for_embedding(self) -> List[str]:
        """Get all agency types formatted for embedding"""
        return [agency.format_for_embedding() for agency in self._agency_types.values()]

    def get_all_by_name(self) -> Dict[str, str]:
        """Get dictionary mapping agency names to their embedding text"""
        return {agency.name: agency.format_for_embedding() for agency in self._agency_types.values()}