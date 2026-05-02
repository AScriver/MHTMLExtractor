"""Helpers for parsing raw MHTML headers."""

import logging
import re
from typing import Optional

from .constants import BOUNDARY_PATTERNS


def get_header_value(headers: str, header_name: str) -> Optional[str]:
    """
    Return a stripped header value from a raw MHTML part header block.

    Args:
        headers: Raw header text from one MHTML part.
        header_name: Header name to look up.

    Returns:
        The header value, or None when the header is absent.
    """
    pattern = rf"^{re.escape(header_name)}:\s*([^\r\n]+)"
    match = re.search(pattern, headers, re.IGNORECASE | re.MULTILINE)
    if match:
        return match.group(1).strip()
    return None


def get_content_type(headers: str) -> Optional[str]:
    """Return a normalized content type without parameters."""
    content_type = get_header_value(headers, "Content-Type")
    if content_type:
        return content_type.split(";", 1)[0].strip().lower()
    return None


def read_boundary(temp_buffer: str) -> Optional[str]:
    """
    Extract a boundary string from the MHTML headers.

    Args:
        temp_buffer: A buffer containing part of the MHTML document.

    Returns:
        The extracted boundary string or None if not found.
    """
    for pattern in BOUNDARY_PATTERNS:
        boundary_match = pattern.search(temp_buffer)
        if boundary_match:
            boundary = boundary_match.group(1).strip()
            if boundary:
                logging.debug(f"Found boundary: {boundary}")
                return boundary

    return None
