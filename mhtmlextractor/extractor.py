"""Core MHTML extraction workflow."""

import logging
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Union

from .constants import DEFAULT_BUFFER_SIZE, MAX_BUFFER_SIZE, MIN_BUFFER_SIZE
from .decoding import decode_body as decode_content_body
from .decoding import is_text_content as content_is_text
from .filenames import deduplicate_filename as deduplicate_output_filename
from .filenames import extract_filename as extract_part_filename
from .filenames import sanitize_filename as sanitize_output_filename
from .headers import get_content_type as parse_content_type
from .headers import get_header_value as parse_header_value
from .headers import read_boundary as parse_boundary
from .links import update_all_html_links as update_extracted_html_links
from .links import update_html_links as update_single_html_links
from .stats import ExtractionStats


class MHTMLExtractor:
    """
    Extract files from MHTML documents with improved memory efficiency,
    error handling, and code quality.

    Attributes:
        mhtml_path: The path to the MHTML document.
        output_dir: The directory where extracted files will be saved.
        buffer_size: The buffer size used when reading the MHTML file.
        boundary: The boundary string used in the MHTML document.
        extracted_count: A counter for the number of files extracted.
        url_mapping: A dictionary mapping original URLs to new filenames.
        saved_html_files: List of saved HTML filenames.
        stats: Statistics about the extraction process.
        dry_run: If True, only analyze without extracting files.
    """

    def __init__(
        self,
        mhtml_path: Optional[Union[str, Path]] = None,
        output_dir: Union[str, Path] = "./extracted_mhtml",
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        clear_output_dir: bool = False,
        dry_run: bool = False,
        create_in_memory_output: bool = False,
        create_output_files: bool = True,
    ) -> None:
        """
        Initialize the MHTMLExtractor class.

        Args:
            mhtml_path: Path to the MHTML document.
            output_dir: Output directory for extracted files.
            buffer_size: Buffer size for reading the MHTML file.
            clear_output_dir: If True, clears the output directory before extraction.
            dry_run: If True, only analyze the MHTML file without extracting files.
            create_in_memory_output: If True, stores extracted content in memory.
            create_output_files: If True, writes extracted files to output_dir.

        Raises:
            FileNotFoundError: If the MHTML file does not exist.
            ValueError: If buffer_size is invalid or mhtml_path is not a file.
            PermissionError: If unable to create or access output directory.
        """
        if mhtml_path is not None:
            self.mhtml_path = Path(mhtml_path).resolve()
            if not self.mhtml_path.exists():
                raise FileNotFoundError(f"MHTML file not found: {self.mhtml_path}")
            if not self.mhtml_path.is_file():
                raise ValueError(f"Path is not a file: {self.mhtml_path}")
        else:
            self.mhtml_path = None

        self.output_dir = Path(output_dir).resolve()
        self.buffer_size = self._optimize_buffer_size(buffer_size)

        self.boundary: Optional[str] = None
        self.extracted_count: int = 0
        self.url_mapping: Dict[str, str] = {}
        self.saved_html_files: List[str] = []
        self.stats = ExtractionStats()
        self.dry_run = dry_run
        self.create_in_memory_output = create_in_memory_output
        self.create_output_files = create_output_files
        self.extracted_contents: Dict[str, Dict[str, Union[str, bytes]]] = {}

        if not dry_run and self.create_output_files:
            self._setup_output_directory(clear_output_dir)

    def _optimize_buffer_size(self, buffer_size: int) -> int:
        """
        Optimize buffer size based on file size and system constraints.

        Args:
            buffer_size: Requested buffer size.

        Returns:
            Optimized buffer size.

        Raises:
            ValueError: If buffer size is invalid.
        """
        if buffer_size < MIN_BUFFER_SIZE:
            raise ValueError(f"Buffer size must be at least {MIN_BUFFER_SIZE} bytes")

        if buffer_size > MAX_BUFFER_SIZE:
            logging.warning(f"Buffer size {buffer_size} is very large, limiting to {MAX_BUFFER_SIZE}")
            buffer_size = MAX_BUFFER_SIZE

        if self.mhtml_path is not None:
            try:
                file_size = self.mhtml_path.stat().st_size
                optimal_size = min(max(file_size // 100, MIN_BUFFER_SIZE), MAX_BUFFER_SIZE)
                if optimal_size != buffer_size:
                    logging.info(f"Optimizing buffer size from {buffer_size} to {optimal_size} based on file size")
                    return optimal_size
            except OSError:
                logging.warning("Could not determine file size for buffer optimization")

        return buffer_size

    def _setup_output_directory(self, clear: bool = False) -> None:
        """
        Set up the output directory with proper error handling.

        Args:
            clear: Whether to clear the directory if it exists.

        Raises:
            PermissionError: If unable to create or access the directory.
        """
        try:
            if not self.output_dir.exists():
                self.output_dir.mkdir(parents=True, exist_ok=True)
                logging.info(f"Created output directory: {self.output_dir}")
            elif clear:
                self._clear_directory(self.output_dir)
                logging.info(f"Cleared output directory: {self.output_dir}")

            test_file = self.output_dir / ".mhtml_extractor_test"
            try:
                test_file.touch()
                test_file.unlink()
            except OSError as e:
                raise PermissionError(f"No write permission in output directory: {self.output_dir}") from e

        except OSError as e:
            raise PermissionError(f"Error setting up output directory: {e}") from e

    @staticmethod
    def _clear_directory(directory_path: Path) -> None:
        """
        Safely clear a directory's contents.

        Args:
            directory_path: Path to the directory to clear.
        """
        for item in directory_path.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except OSError as e:
                logging.warning(f"Could not remove {item}: {e}")

    @staticmethod
    def ensure_directory_exists(directory_path: Union[str, Path], clear: bool = False) -> None:
        """
        Legacy method for backward compatibility.

        Args:
            directory_path: Path to the directory.
            clear: Whether to clear the directory.
        """
        path = Path(directory_path)
        try:
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
            elif clear:
                MHTMLExtractor._clear_directory(path)
        except Exception as e:
            logging.error(f"Error during directory setup: {e}")

    @staticmethod
    def is_text_content(decoded_content: Union[str, bytes]) -> bool:
        """Return True when content appears to be human-readable text."""
        return content_is_text(decoded_content)

    @staticmethod
    def _get_header_value(headers: str, header_name: str) -> Optional[str]:
        """Return a stripped header value from a raw MHTML part header block."""
        return parse_header_value(headers, header_name)

    @staticmethod
    def _get_content_type(headers: str) -> Optional[str]:
        """Return a normalized content type without parameters."""
        return parse_content_type(headers)

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Return a filesystem-safe filename stem from untrusted header data."""
        return sanitize_output_filename(filename)

    @staticmethod
    def _read_boundary(temp_buffer: str) -> Optional[str]:
        """Extract a boundary string from MHTML headers."""
        return parse_boundary(temp_buffer)

    @staticmethod
    def _decode_body(encoding: Optional[str], body: str) -> Union[str, bytes]:
        """Decode body content based on the Content-Transfer-Encoding header."""
        return decode_content_body(encoding, body)

    def _deduplicate_filename(self, filename: str) -> str:
        """Append a numeric suffix when an output filename already exists."""
        return deduplicate_output_filename(filename, self.output_dir, self.dry_run)

    def _extract_filename(self, headers: str, content_type: str) -> str:
        """Determine the filename based on headers or generate one if necessary."""
        return extract_part_filename(headers, content_type, self.output_dir, self.dry_run)

    def _process_part(self, part: str, no_css: bool = False, no_images: bool = False, html_only: bool = False) -> None:
        """
        Process each MHTML part and extract its content.

        Args:
            part: A part of the MHTML document.
            no_css: If True, CSS files will not be extracted.
            no_images: If True, image files will not be extracted.
            html_only: If True, only HTML files will be extracted.
        """
        try:
            if "\r\n\r\n" in part:
                headers, body = part.split("\r\n\r\n", 1)
            elif "\n\n" in part:
                headers, body = part.split("\n\n", 1)
            else:
                logging.warning("Could not find header/body separator in part")
                return

            content_type = self._get_content_type(headers)
            if not content_type:
                logging.debug("No Content-Type found in part, skipping")
                self.stats.skipped_files += 1
                return

            if self._should_skip_content(content_type, no_css, no_images, html_only):
                self.stats.skipped_files += 1
                return

            encoding = self._get_header_value(headers, "Content-Transfer-Encoding")
            if encoding:
                encoding = encoding.lower()

            decoded_body = self._decode_body(encoding, body)
            self._update_stats(content_type, decoded_body)

            filename = self._extract_filename(headers, content_type)

            location = self._get_header_value(headers, "Content-Location")
            if location:
                self.url_mapping[location] = filename

            content_id = self._get_header_value(headers, "Content-ID")
            if content_id:
                cid = "cid:" + content_id.strip("<>")
                self.url_mapping[cid] = filename

            if self.create_in_memory_output:
                self.extracted_contents[filename] = {
                    "content_type": content_type,
                    "decoded_body": decoded_body,
                }

            if not self.dry_run and self.create_output_files:
                self._write_to_file(filename, content_type, decoded_body)
            elif self.dry_run:
                logging.info(f"[DRY RUN] Would extract: {filename} ({content_type})")

        except Exception as e:
            logging.error(f"Error processing MHTML part: {e}")
            self.stats.skipped_files += 1

    def _should_skip_content(self, content_type: str, no_css: bool, no_images: bool, html_only: bool) -> bool:
        """
        Determine if content should be skipped based on filters.

        Args:
            content_type: The MIME type of the content.
            no_css: Skip CSS files.
            no_images: Skip image files.
            html_only: Only process HTML files.

        Returns:
            True if content should be skipped.
        """
        if no_css and "css" in content_type:
            return True
        if no_images and "image" in content_type:
            return True
        if html_only and "html" not in content_type:
            return True
        return False

    def _update_stats(self, content_type: str, decoded_body: Union[str, bytes]) -> None:
        """
        Update extraction statistics.

        Args:
            content_type: The MIME type of the content.
            decoded_body: The decoded content.
        """
        self.stats.total_parts += 1

        if isinstance(decoded_body, str):
            size = len(decoded_body.encode("utf-8"))
        else:
            size = len(decoded_body)
        self.stats.total_size += size

        if "html" in content_type:
            self.stats.html_files += 1
        elif "css" in content_type:
            self.stats.css_files += 1
        elif "image" in content_type:
            self.stats.image_files += 1
        else:
            self.stats.other_files += 1

    def _write_to_file(self, filename: str, content_type: str, decoded_body: Union[str, bytes]) -> None:
        """
        Write decoded content to a file.

        Args:
            filename: The file name to write.
            content_type: The content type of the data.
            decoded_body: The decoded content to write.

        Raises:
            OSError: If file cannot be written.
        """
        try:
            if isinstance(decoded_body, str):
                decoded_body = decoded_body.encode("utf-8")

            if "html" in content_type:
                self.saved_html_files.append(filename)

            file_path = self.output_dir / filename
            with file_path.open("wb") as out_file:
                out_file.write(decoded_body)

            logging.debug(f"Wrote {len(decoded_body)} bytes to {filename}")

        except OSError as e:
            logging.error(f"Error writing file {filename}: {e}")
            raise

    def _update_html_links(
        self,
        filepath: Path,
        sorted_urls: List[str],
        no_css: bool = False,
        no_images: bool = False,
        html_only: bool = False,
    ) -> None:
        """Update links in one extracted HTML file."""
        update_single_html_links(
            filepath,
            sorted_urls,
            self.url_mapping,
            no_css=no_css,
            no_images=no_images,
            html_only=html_only,
        )

    def extract(self, no_css: bool = False, no_images: bool = False, html_only: bool = False) -> ExtractionStats:
        """
        Extract files from MHTML into separate files.

        Args:
            no_css: If True, CSS files will not be extracted.
            no_images: If True, image files will not be extracted.
            html_only: If True, only HTML files will be extracted.

        Returns:
            ExtractionStats object with details about the extraction.

        Raises:
            FileNotFoundError: If MHTML file does not exist.
            PermissionError: If unable to read MHTML file or write output.
        """
        start_time = time.time()
        temp_buffer_chunks: List[str] = []

        try:
            if self.dry_run:
                logging.info(f"[DRY RUN] Analyzing MHTML file: {self.mhtml_path}")
            else:
                logging.info(f"Extracting from: {self.mhtml_path} to: {self.output_dir}")

            with self.mhtml_path.open("r", encoding="utf-8", errors="replace") as file:
                while True:
                    chunk = file.read(self.buffer_size)
                    if not chunk:
                        break

                    temp_buffer_chunks.append(chunk)

                    if not self.boundary:
                        joined_buffer = "".join(temp_buffer_chunks)
                        self.boundary = self._read_boundary(joined_buffer)
                        if self.boundary:
                            logging.debug(f"Boundary found: {self.boundary}")

                    if self.boundary:
                        joined_buffer = "".join(temp_buffer_chunks)
                        parts = joined_buffer.split("--" + self.boundary)
                        temp_buffer_chunks = [parts[-1]]

                        for part in parts[:-1]:
                            if self.extracted_count > 0:
                                self._process_part(part.strip(), no_css, no_images, html_only)
                            self.extracted_count += 1

                if temp_buffer_chunks and self.boundary:
                    remaining_part = "".join(temp_buffer_chunks).strip()
                    if remaining_part and remaining_part != "--":
                        self._process_part(remaining_part, no_css, no_images, html_only)

            if not self.dry_run and not html_only and self.saved_html_files:
                self._update_all_html_links(no_css, no_images, html_only)

            self.stats.extraction_time = time.time() - start_time
            self._log_extraction_summary()

            return self.stats

        except Exception as e:
            logging.error(f"Error during extraction: {e}")
            raise

    def _update_all_html_links(self, no_css: bool, no_images: bool, html_only: bool) -> None:
        """
        Update links in all saved HTML files.

        Args:
            no_css: Skip CSS link updates.
            no_images: Skip image link updates.
            html_only: Skip all link updates.
        """
        update_extracted_html_links(
            self.output_dir,
            self.saved_html_files,
            self.url_mapping,
            no_css,
            no_images,
            html_only,
        )

    def _log_extraction_summary(self) -> None:
        """Log a summary of the extraction process."""
        if self.dry_run:
            logging.info("[DRY RUN] Analysis complete:")
        else:
            logging.info("Extraction complete:")

        logging.info(f"  Total parts processed: {self.stats.total_parts}")
        logging.info(f"  HTML files: {self.stats.html_files}")
        logging.info(f"  CSS files: {self.stats.css_files}")
        logging.info(f"  Image files: {self.stats.image_files}")
        logging.info(f"  Other files: {self.stats.other_files}")
        logging.info(f"  Skipped files: {self.stats.skipped_files}")
        logging.info(f"  Total size: {self.stats.total_size:,} bytes")
        logging.info(f"  Extraction time: {self.stats.extraction_time:.2f} seconds")

        if not self.dry_run:
            if self.create_output_files:
                near = " (relative to script file)" if str(self.output_dir).startswith("./") else ""
                logging.info(f"Extracted {self.extracted_count - 1} files into {self.output_dir}{near}.")

            if self.create_in_memory_output:
                logging.info(f"Extracted {self.extracted_count - 1} files content into `extracted_contents` property.")
