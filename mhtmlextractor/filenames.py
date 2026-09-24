"""Filename generation helpers for extracted MHTML resources."""

import hashlib
import logging
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Optional, Set
from urllib.parse import unquote, urlparse

from .constants import INVALID_FILENAME_CHARS
from .headers import get_header_value


# Python's mimetypes table may not map some obsolete or archive-common
# MIME types, so keep extracted filenames useful.
CONTENT_TYPE_EXTENSION_OVERRIDES = {
    "application/javascript": ".js",
    "application/ecmascript": ".js",
    "application/x-javascript": ".js",
    "text/ecmascript": ".js",
    "text/jscript": ".js",
    "text/x-javascript": ".js",
    "application/ld+json": ".jsonld",
    "application/font-woff": ".woff",
}


def sanitize_filename(filename: str) -> str:
    """Return a filesystem-safe filename stem from untrusted header data."""
    sanitized = INVALID_FILENAME_CHARS.sub("_", filename).strip()
    return sanitized or "unnamed"


def deduplicate_filename(
    filename: str,
    output_dir: Path,
    dry_run: bool = False,
    reserved_filenames: Optional[Set[str]] = None,
) -> str:
    """
    Append a numeric suffix when a filename is reserved or already exists.

    Args:
        filename: Candidate filename.
        output_dir: Directory where the file would be written.
        dry_run: If True, skip filesystem conflict checks.
        reserved_filenames: Names already selected for this archive.

    Returns:
        A filename that is unreserved and, unless dry_run, absent on disk.
    """
    original_filename = filename
    counter = 1
    while (reserved_filenames is not None and filename in reserved_filenames) or (
        not dry_run and (output_dir / filename).exists()
    ):
        name_part, ext_part = os.path.splitext(original_filename)
        filename = f"{name_part}_{counter}{ext_part}"
        counter += 1
    return filename


def extract_filename(
    headers: str,
    content_type: str,
    output_dir: Path,
    dry_run: bool = False,
    reserved_filenames: Optional[Set[str]] = None,
) -> str:
    """
    Determine an extracted resource filename from headers and content type.

    Args:
        headers: Part headers from the MHTML document.
        content_type: The content type of the part, such as text/html.
        output_dir: Directory where files are written.
        dry_run: If True, skip filesystem conflict checks.
        reserved_filenames: Names already selected for this archive.

    Returns:
        The determined filename.
    """
    content_type = content_type.split(";", 1)[0].strip().lower()
    extension = (
        CONTENT_TYPE_EXTENSION_OVERRIDES.get(content_type)
        or mimetypes.guess_extension(content_type)
        or ""
    )
    location = get_header_value(headers, "Content-Location")

    if not location:
        filename = f"{uuid.uuid4()}{extension}"
        return deduplicate_filename(filename, output_dir, dry_run, reserved_filenames)

    try:
        parsed_url = urlparse(location)
        path_base_name = os.path.basename(unquote(parsed_url.path))
        base_name = path_base_name or parsed_url.netloc
        base_name = sanitize_filename(base_name)
        if path_base_name:
            name_part, ext_part = os.path.splitext(base_name)
        else:
            name_part, ext_part = base_name, ""
        final_extension = ext_part or extension
        filename_stem = name_part or "unnamed"

        url_hash = hashlib.md5(location.encode("utf-8")).hexdigest()
        filename = f"{filename_stem}_{url_hash}{final_extension}"
        return deduplicate_filename(filename, output_dir, dry_run, reserved_filenames)
    except (OSError, ValueError) as e:
        logging.error(f"Error extracting filename: {e}")
        filename = f"{uuid.uuid4()}.bin"
        return deduplicate_filename(filename, output_dir, dry_run, reserved_filenames)
