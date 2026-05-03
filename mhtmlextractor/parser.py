"""Convenience API for parsing MHTML archives into typed in-memory results."""

from pathlib import Path
from typing import Union

from .constants import DEFAULT_BUFFER_SIZE
from .extractor import MHTMLExtractor
from .models import MHTMLArchive, MHTMLPart


def parse_mhtml(
    mhtml_path: Union[str, Path],
    *,
    buffer_size: int = DEFAULT_BUFFER_SIZE,
    no_css: bool = False,
    no_images: bool = False,
    html_only: bool = False,
) -> MHTMLArchive:
    """Parse an MHTML archive without writing files and return typed parts."""
    extractor = MHTMLExtractor(
        mhtml_path=mhtml_path,
        buffer_size=buffer_size,
        dry_run=True,
        create_in_memory_output=True,
        create_output_files=False,
    )
    stats = extractor.extract(no_css=no_css, no_images=no_images, html_only=html_only)
    parts = tuple(
        MHTMLPart(
            filename=filename,
            content_type=details["content_type"],
            content=details["decoded_body"],
            content_location=details.get("content_location"),
            content_id=details.get("content_id"),
        )
        for filename, details in extractor.extracted_contents.items()
    )
    return MHTMLArchive(
        path=Path(mhtml_path).resolve(),
        parts=parts,
        stats=stats,
        url_mapping=dict(extractor.url_mapping),
    )
