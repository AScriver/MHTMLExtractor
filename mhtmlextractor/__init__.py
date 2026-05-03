"""Public package interface for MHTML extraction."""

from .extractor import MHTMLExtractor
from .models import MHTMLArchive, MHTMLPart
from .parser import parse_mhtml
from .stats import ExtractionStats

__all__ = [
    "ExtractionStats",
    "MHTMLArchive",
    "MHTMLExtractor",
    "MHTMLPart",
    "parse_mhtml",
]
