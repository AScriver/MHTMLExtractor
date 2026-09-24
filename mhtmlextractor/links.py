"""Atomic static HTML/CSS reference rewriting."""

import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Set

from .reference_syntax import rewrite_css, rewrite_html
from .reference_urls import References, ResourceInfo


def update_html_links(
    filepath: Path,
    sorted_urls: List[str],
    url_mapping: Dict[str, str],
    no_css: bool = False,
    no_images: bool = False,
    html_only: bool = False,
    resource_info: Optional[Dict[str, ResourceInfo]] = None,
    archive_location: Optional[str] = None,
    written_filenames: Optional[Set[str]] = None,
) -> None:
    """
    Update links in an HTML file to point at extracted resource filenames.

    Args:
        filepath: Path to the HTML file.
        sorted_urls: Selected URL keys (legacy argument; ordering is immaterial).
        url_mapping: Mapping from original URLs to extracted filenames.
        no_css: Skip CSS link updates if True.
        no_images: Skip image link updates if True.
        html_only: Skip all link updates if True.
    """
    if html_only:
        return

    metadata = resource_info or {}
    references = References({url: url_mapping[url] for url in sorted_urls}, metadata,
                            archive_location, written_filenames, no_css, no_images)
    _update_file(filepath, references, metadata.get(filepath.name))


def _update_file(filepath: Path, references: References, info: Optional[ResourceInfo]) -> None:
    # No universal-newline conversion: unchanged source spans retain their bytes.
    original_content = filepath.read_bytes().decode("utf-8")
    rewrite = references.for_file(info.location if info else None)
    content = (rewrite_css(original_content, rewrite) if info and info.content_type == "text/css"
               else rewrite_html(original_content, rewrite))

    if content != original_content:
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=str(filepath.parent),
                prefix=f".{filepath.name}.", suffix=".tmp", delete=False,
            ) as html_file:
                temporary_path = Path(html_file.name)
                html_file.write(content)
            os.replace(str(temporary_path), str(filepath))
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError as cleanup_error:
                    logging.error(f"Could not remove incomplete reference rewrite {temporary_path}: {cleanup_error}")
        logging.debug(f"Updated links in {filepath.name}")

def update_all_html_links(
    output_dir: Path,
    saved_html_files: List[str],
    url_mapping: Dict[str, str],
    no_css: bool,
    no_images: bool,
    html_only: bool,
    resource_info: Optional[Dict[str, ResourceInfo]] = None,
    archive_location: Optional[str] = None,
    written_filenames: Optional[Set[str]] = None,
) -> int:
    """
    Update references in eligible saved HTML/CSS files. Historical names are
    retained for compatibility; callers provide only safe source files, but
    all selected mappings, including targets whose writes failed.

    Args:
        output_dir: Directory containing saved HTML/CSS files.
        saved_html_files: Filenames of eligible extracted HTML/CSS files.
        url_mapping: Mapping from original URLs to extracted filenames.
        no_css: Skip CSS link updates.
        no_images: Skip image link updates.
        html_only: Skip all link updates.
    """
    if html_only:
        return 0

    metadata = resource_info or {}
    references = References(url_mapping, metadata, archive_location, written_filenames, no_css, no_images)
    logging.info(f"Updating static references in {len(saved_html_files)} HTML/CSS files...")

    failures = 0
    for filename in saved_html_files:
        filepath = output_dir / filename
        try:
            _update_file(filepath, references, metadata.get(filename))
        except Exception as error:
            failures += 1
            logging.error(f"Failed to rewrite static references in {filepath}: {error}")
    return failures
