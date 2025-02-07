from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List
from datetime import datetime


class CodeAction(Enum):
    """
    Enumerates the different ways a code section might be affected
    by a trailer bill (e.g., added, amended, repealed).
    """
    UNKNOWN = "unknown"
    ADDED = "added"
    AMENDED = "amended"
    REPEALED = "repealed"
    REPEALED_AND_ADDED = "repealed_and_added"
    AMENDED_AND_REPEALED = "amended_and_repealed"


class SectionType(Enum):
    """
    If you want to classify sections further (e.g. add, repeal, etc.).
    Otherwise, you can just leave it as UNKNOWN or remove this entirely.
    """
    UNKNOWN = "unknown"
    # Possible custom types:
    # ADD = "add"
    # AMEND = "amend"
    # REPEAL = "repeal"
    # ...


@dataclass
class CodeReference:
    """
    Represents a reference to a particular Code (e.g. Government Code)
    and a specific section number (e.g. 8594.14).
    """
    section: str
    code_name: str


@dataclass
class BillSection:
    """
    Represents a 'SEC. 1.' style section from the bill with:
    - Text
    - Code references
    - Potential links to multiple digest items
    """
    number: str
    text: str
    code_references: List[CodeReference] = field(default_factory=list)
    digest_references: List[str] = field(default_factory=list)  # <-- Changed from single "digest_reference"
    section_type: Optional[SectionType] = None
    relationship_type: Optional[str] = None


@dataclass
class DigestSection:
    """
    Represents a single numbered entry in the Legislative Counsel's Digest,
    including:
    - The snippet for existing law vs. proposed changes
    - Code references
    - Linked bill sections
    """
    number: str
    text: str
    existing_law: str
    proposed_changes: str
    code_references: List[CodeReference] = field(default_factory=list)
    bill_sections: List[str] = field(default_factory=list)


@dataclass
class TrailerBill:
    """
    Represents the entire trailer bill, including metadata, raw text,
    digest sections, and parsed 'bill sections.'
    """
    bill_number: str
    title: str
    chapter_number: str
    date_approved: Optional[datetime] = None
    date_filed: Optional[datetime] = None
    raw_text: str = ""
    digest_sections: List[DigestSection] = field(default_factory=list)
    bill_sections: List[BillSection] = field(default_factory=list)
