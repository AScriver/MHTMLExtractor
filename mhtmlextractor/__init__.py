"""Public package interface for MHTML extraction."""

from .extractor import MHTMLExtractor
from .stats import ExtractionStats

__all__ = ["ExtractionStats", "MHTMLExtractor"]
