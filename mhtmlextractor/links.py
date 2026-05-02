"""HTML link update helpers."""

import html
import logging
from pathlib import Path
from typing import Dict, List

from .constants import IMAGE_EXTENSIONS


def update_html_links(
    filepath: Path,
    sorted_urls: List[str],
    url_mapping: Dict[str, str],
    no_css: bool = False,
    no_images: bool = False,
    html_only: bool = False,
) -> None:
    """
    Update links in an HTML file to point at extracted resource filenames.

    Args:
        filepath: Path to the HTML file.
        sorted_urls: URLs sorted by descending length for stable replacement.
        url_mapping: Mapping from original URLs to extracted filenames.
        no_css: Skip CSS link updates if True.
        no_images: Skip image link updates if True.
        html_only: Skip all link updates if True.
    """
    if html_only:
        return

    try:
        with filepath.open("r", encoding="utf-8", errors="replace") as html_file:
            content = html_file.read()

        original_content = content

        for original_url in sorted_urls:
            new_filename = url_mapping[original_url]

            if no_css and new_filename.lower().endswith(".css"):
                continue

            if no_images and any(new_filename.lower().endswith(ext) for ext in IMAGE_EXTENSIONS):
                continue

            html_escaped_url = html.escape(original_url)
            content = content.replace(html_escaped_url, new_filename)
            if html_escaped_url != original_url:
                content = content.replace(original_url, new_filename)

        if content != original_content:
            with filepath.open("w", encoding="utf-8") as html_file:
                html_file.write(content)
            logging.debug(f"Updated links in {filepath.name}")

    except Exception as e:
        logging.error(f"Error updating HTML links in {filepath}: {e}")


def update_all_html_links(
    output_dir: Path,
    saved_html_files: List[str],
    url_mapping: Dict[str, str],
    no_css: bool,
    no_images: bool,
    html_only: bool,
) -> None:
    """
    Update links in all saved HTML files.

    Args:
        output_dir: Directory containing saved HTML files.
        saved_html_files: Filenames of extracted HTML files.
        url_mapping: Mapping from original URLs to extracted filenames.
        no_css: Skip CSS link updates.
        no_images: Skip image link updates.
        html_only: Skip all link updates.
    """
    if not url_mapping:
        return

    sorted_urls = sorted(url_mapping.keys(), key=len, reverse=True)
    logging.info(f"Updating links in {len(saved_html_files)} HTML files...")

    for filename in saved_html_files:
        filepath = output_dir / filename
        if filepath.exists():
            update_html_links(filepath, sorted_urls, url_mapping, no_css, no_images, html_only)
