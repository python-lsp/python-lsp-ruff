from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Location:
    row: int
    column: int


@dataclass
class Edit:
    content: str
    location: Location
    end_location: Location


@dataclass
class Fix:
    edits: List[Edit]
    message: str
    applicability: str


@dataclass
class Check:
    code: str
    message: str
    filename: str
    location: Location
    end_location: Location
    fix: Optional[Fix] = None
