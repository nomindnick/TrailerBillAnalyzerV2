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
            "City": AgencyType(
                name="City",
                description="A city is a general law or charter municipality that provides local government and services to residents in an urban area.",
                keywords=["city", "cities", "municipality", "municipalities", "town", "local government"],
                examples=["City of San Francisco", "City of Los Angeles", "City of San Diego"]
            ),

            "County": AgencyType(
                name="County",
                description="A county is a political and geographic subdivision of a state that provides various services to residents across a region.",
                keywords=["county", "counties", "board of supervisors", "county government"],
                examples=["County of Los Angeles", "County of San Diego", "County of Orange"]
            ),

            "School District": AgencyType(
                name="School District",
                description="A school district is a special-purpose local government entity that operates public primary and secondary schools within a defined area.",
                keywords=["school district", "unified school district", "elementary school district", "high school district", "K-12 district"],
                examples=["Los Angeles Unified School District", "San Diego Unified School District", "Long Beach Unified School District"]
            ),

            "Community College District": AgencyType(
                name="Community College District",
                description="A community college district is a special-purpose local government entity that operates public community colleges within a defined area.",
                keywords=["community college district", "college district", "junior college district", "two-year college"],
                examples=["Los Angeles Community College District", "San Diego Community College District", "Peralta Community College District"]
            ),

            "Special District": AgencyType(
                name="Special District",
                description="A special district is a local government agency formed to provide a specific service such as water, fire protection, parks, or sanitation within a designated area.",
                keywords=["special district", "utility district", "water district", "fire district", "park district", "sanitation district", "irrigation district"],
                examples=["East Bay Municipal Utility District", "Metropolitan Water District", "San Francisco Bay Area Rapid Transit District (BART)"]
            ),

            "Joint Powers Authority": AgencyType(
                name="Joint Powers Authority",
                description="A joint powers authority (JPA) is an entity formed by two or more public agencies to jointly exercise common powers, typically to provide shared services or regional planning.",
                keywords=["joint powers authority", "JPA", "joint powers agreement", "regional authority", "joint agency", "joint exercise of powers", "interagency cooperation"],
                examples=["Association of Bay Area Governments (ABAG)", "South Bay Cities Council of Governments", "Sacramento Area Council of Governments (SACOG)"]
            ),

            "Charter School": AgencyType(
                name="Charter School",
                description="A charter school is a publicly funded independent school established under a charter with a local school district, county office of education, or the state board of education.",
                keywords=["charter school", "public charter", "charter academy", "charter network", "charter management organization", "CMO"],
                examples=["Green Dot Public Schools", "KIPP Schools", "Aspire Public Schools"]
            ),

            "County Office of Education": AgencyType(
                name="County Office of Education",
                description="A county office of education (COE) provides educational programs, services, and support to school districts within a county, often focusing on specialized education and administrative services.",
                keywords=["county office of education", "COE", "county superintendent of schools", "county department of education"],
                examples=["Los Angeles County Office of Education", "San Diego County Office of Education", "Orange County Department of Education"]
            ),

            "Law Enforcement Agency": AgencyType(
                name="Law Enforcement Agency",
                description="A local law enforcement agency such as police departments, sheriff's offices, and other agencies responsible for enforcing laws and maintaining public safety at the local level.",
                keywords=["police department", "sheriff", "sheriff's department", "law enforcement", "public safety agency", "county sheriff", "city police"],
                examples=["Los Angeles Police Department", "San Diego Sheriff's Department", "San Francisco Police Department"]
            ),

            "Transit Agency": AgencyType(
                name="Transit Agency",
                description="A public agency responsible for operating public transportation services within a specific geographical area, including bus, rail, and other transit systems.",
                keywords=["transit agency", "transportation authority", "transit district", "public transportation", "transit operator", "bus agency", "transit system"],
                examples=["Los Angeles County Metropolitan Transportation Authority (Metro)", "San Francisco Municipal Transportation Agency (SFMTA)", "AC Transit"]
            ),

            "Housing Authority": AgencyType(
                name="Housing Authority",
                description="A public agency that provides affordable housing assistance to low-income residents through programs such as public housing and Section 8 vouchers.",
                keywords=["housing authority", "public housing agency", "housing commission", "housing department", "affordable housing agency"],
                examples=["Housing Authority of the City of Los Angeles", "San Diego Housing Commission", "Oakland Housing Authority"]
            ),

            "No Local Agency Impact": AgencyType(
                name="No Local Agency Impact",
                description="The bill section does not directly or indirectly impact any local public agencies.",
                keywords=["no impact", "no local impact", "state only", "no agency impact", "non-local", "state agency only"],
                examples=["State departments only", "Private organizations only", "No effect on local bodies"]
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