"""Typed result models for parsed MHTML archives."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

from .stats import ExtractionStats


@dataclass(frozen=True)
class MHTMLPart:
    """One decoded resource part from an MHTML archive."""

    filename: str
    content_type: str
    content: Union[str, bytes]
    content_location: Optional[str] = None
    content_id: Optional[str] = None


@dataclass(frozen=True)
class MHTMLArchive:
    """Parsed MHTML archive contents and extraction metadata."""

    path: Path
    parts: Tuple[MHTMLPart, ...]
    stats: ExtractionStats
    url_mapping: Dict[str, str]
