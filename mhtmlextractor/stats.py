"""Extraction statistics model."""

from dataclasses import dataclass


@dataclass
class ExtractionStats:
    """Statistics for the extraction process."""

    total_parts: int = 0
    html_files: int = 0
    css_files: int = 0
    image_files: int = 0
    other_files: int = 0
    skipped_files: int = 0
    total_size: int = 0
    extraction_time: float = 0.0
