from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List
from datetime import datetime

class CodeAction(Enum):
    UNKNOWN = "unknown"
    ADDED = "added"
    AMENDED = "amended"
    REPEALED = "repealed"
    REPEALED_AND_ADDED = "repealed_and_added"
    AMENDED_AND_REPEALED = "amended_and_repealed"

class SectionType(Enum):
    UNKNOWN = "unknown"

@dataclass
class CodeReference:
    section: str
    code_name: str

@dataclass
class BillSection:
    number: str  # e.g. "1", "2"
    original_label: str  # e.g. "SECTION 1." or "SEC. 2."
    text: str
    code_references: List[CodeReference] = field(default_factory=list)
    digest_reference: Optional[str] = None
    section_type: Optional[SectionType] = None
    relationship_type: Optional[str] = None

@dataclass
class DigestSection:
    number: str
    text: str
    existing_law: str
    proposed_changes: str
    code_references: List[CodeReference] = field(default_factory=list)
    bill_sections: List[str] = field(default_factory=list)

@dataclass
class TrailerBill:
    bill_number: str
    title: str
    chapter_number: str
    date_approved: Optional[datetime] = None
    date_filed: Optional[datetime] = None
    raw_text: str = ""
    digest_sections: List[DigestSection] = field(default_factory=list)
    bill_sections: List[BillSection] = field(default_factory=list)
