import os
import re
import mimetypes
import uuid
import base64
import quopri
from urllib.parse import urlparse, unquote
import hashlib
import shutil
import logging
import argparse
from typing import Optional, Dict, List, Tuple, Union
from pathlib import Path
from dataclasses import dataclass
import time

# Constants
DEFAULT_BUFFER_SIZE = 8192
MIN_BUFFER_SIZE = 1024
MAX_BUFFER_SIZE = 1024 * 1024  # 1MB
SUPPORTED_ENCODINGS = {"base64", "quoted-printable", "7bit", "8bit", "binary"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico"}
TEXT_CONTENT_TYPES = {"text/html", "text/css", "text/javascript", "application/javascript"}

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(filename)s:%(lineno)d][%(levelname)s]: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler()],
)


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


class MHTMLExtractor:
    """
    A high-performance class to extract files from MHTML documents with improved
    memory efficiency, error handling, and code quality.

    Attributes:
        mhtml_path (Path): The path to the MHTML document.
        output_dir (Path): The directory where extracted files will be saved.
        buffer_size (int): The size of the buffer used when reading the MHTML file.
        boundary (Optional[str]): The boundary string used in the MHTML document.
        extracted_count (int): A counter for the number of files extracted.
        url_mapping (Dict[str, str]): A dictionary mapping original URLs to new filenames.
        saved_html_files (List[str]): List to keep track of saved HTML filenames.
        stats (ExtractionStats): Statistics about the extraction process.
        dry_run (bool): If True, only analyze without extracting files.
    """

    def __init__(
        self, 
        mhtml_path: Union[str, Path], 
        output_dir: Union[str, Path], 
        buffer_size: int = DEFAULT_BUFFER_SIZE, 
        clear_output_dir: bool = False,
        dry_run: bool = False
    ) -> None:
        """
        Initialize the MHTMLExtractor class with enhanced validation and performance optimizations.

        Args:
            mhtml_path: Path to the MHTML document.
            output_dir: Output directory for the extracted files.
            buffer_size: Buffer size for reading the MHTML file. Auto-optimized if needed.
            clear_output_dir: If True, clears the output directory before extraction.
            dry_run: If True, only analyze the MHTML file without extracting files.
            
        Raises:
            FileNotFoundError: If the MHTML file doesn't exist.
            ValueError: If buffer_size is invalid.
            PermissionError: If unable to create/access output directory.
        """
        # Validate and convert paths
        self.mhtml_path = Path(mhtml_path).resolve()
        self.output_dir = Path(output_dir).resolve()
        
        # Validate MHTML file exists
        if not self.mhtml_path.exists():
            raise FileNotFoundError(f"MHTML file not found: {self.mhtml_path}")
        
        if not self.mhtml_path.is_file():
            raise ValueError(f"Path is not a file: {self.mhtml_path}")
        
        # Validate and optimize buffer size
        self.buffer_size = self._optimize_buffer_size(buffer_size)
        
        # Initialize attributes
        self.boundary: Optional[str] = None
        self.extracted_count: int = 0
        self.url_mapping: Dict[str, str] = {}
        self.saved_html_files: List[str] = []
        self.stats = ExtractionStats()
        self.dry_run = dry_run
        
        # Setup output directory
        if not dry_run:
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
        
        # Auto-optimize based on file size
        try:
            file_size = self.mhtml_path.stat().st_size
            # Use larger buffer for larger files, but cap it
            optimal_size = min(max(file_size // 100, MIN_BUFFER_SIZE), MAX_BUFFER_SIZE)
            if optimal_size != buffer_size:
                logging.info(f"Optimizing buffer size from {buffer_size} to {optimal_size} based on file size")
                return optimal_size
        except OSError:
            logging.warning("Could not determine file size for buffer optimization")
        
        return buffer_size

    def _setup_output_directory(self, clear: bool = False) -> None:
        """
        Setup the output directory with proper error handling.
        
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
                
            # Test write permissions
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
        """
        Determine if the given content is likely to be human-readable text.
        
        Args:
            decoded_content: Content to analyze.
            
        Returns:
            True if content appears to be text, False otherwise.
        """
        # If it's already a string, then it's text
        if isinstance(decoded_content, str):
            return True

        # If there are null bytes, it's likely binary
        if b"\0" in decoded_content:
            return False

        # Check a sample for common ASCII characters
        sample = decoded_content[:1024]  # Check the first 1KB
        text_chars = {7, 8, 9, 10, 12, 13} | set(range(0x20, 0x7F))
        if all(byte in text_chars for byte in sample):
            return True

        # Try decoding as UTF-8
        try:
            decoded_content.decode("utf-8")
            return True
        except UnicodeDecodeError:
            pass

        return False

    @staticmethod
    def _read_boundary(temp_buffer: str) -> Optional[str]:
        """
        Extract boundary string from the MHTML headers with improved error handling.

        Args:
            temp_buffer: A buffer containing part of the MHTML document.

        Returns:
            The extracted boundary string or None if not found.
        """
        try:
            # Try different boundary patterns
            patterns = [
                r'boundary="([^"]+)"',  # Quoted boundary
                r'boundary=([^;\s]+)',  # Unquoted boundary
            ]
            
            for pattern in patterns:
                boundary_match = re.search(pattern, temp_buffer, re.IGNORECASE)
                if boundary_match:
                    boundary = boundary_match.group(1).strip()
                    if boundary:
                        logging.debug(f"Found boundary: {boundary}")
                        return boundary
                        
        except Exception as e:
            logging.error(f"Error reading boundary: {e}")
        
        return None

    @staticmethod
    def _decode_body(encoding: Optional[str], body: str) -> Union[str, bytes]:
        """
        Decode the body content based on the Content-Transfer-Encoding header.

        Args:
            encoding: The content encoding (e.g., "base64", "quoted-printable").
            body: The body content to be decoded.

        Returns:
            The decoded body content.
            
        Raises:
            ValueError: If encoding is not supported.
        """
        if not encoding:
            return body
            
        encoding = encoding.lower().strip()
        
        try:
            if encoding == "base64":
                # Remove whitespace and newlines before decoding
                clean_body = re.sub(r'\s+', '', body)
                return base64.b64decode(clean_body)
            elif encoding == "quoted-printable":
                return quopri.decodestring(body.encode()).decode('utf-8', errors='replace')
            elif encoding in {"7bit", "8bit", "binary"}:
                return body
            else:
                logging.warning(f"Unsupported encoding: {encoding}, treating as plain text")
                return body
        except Exception as e:
            logging.error(f"Error decoding body with encoding '{encoding}': {e}")
            return body

    def _extract_filename(self, headers: str, content_type: str) -> str:
        """
        Determine the filename based on headers or generate one if necessary.

        Args:
            headers: Part headers from the MHTML document.
            content_type: The content type of the part (e.g., "text/html").

        Returns:
            The determined filename.
        """
        try:
            content_location_match = re.search(r"Content-Location:\s*([^\r\n]+)", headers, re.IGNORECASE)
            extension = mimetypes.guess_extension(content_type) or ""

            # If Content-Location is provided in the headers, use it to derive a filename
            if content_location_match:
                location = content_location_match.group(1).strip()
                parsed_url = urlparse(location)
                base_name = os.path.basename(unquote(parsed_url.path)) or parsed_url.netloc
                
                # Clean the base name
                base_name = re.sub(r'[<>:"/\\|?*]', '_', base_name)
                if not base_name:
                    base_name = "unnamed"
                
                url_hash = hashlib.md5(location.encode()).hexdigest()
                filename = f"{base_name}_{url_hash}{extension}"
                
                # Handle potential filename conflicts by appending a counter
                original_filename = filename
                counter = 1
                while not self.dry_run and (self.output_dir / filename).exists():
                    name_part, ext_part = os.path.splitext(original_filename)
                    filename = f"{name_part}_{counter}{ext_part}"
                    counter += 1
            else:
                # If Content-Location isn't provided, generate a UUID-based filename
                filename = f"{uuid.uuid4()}{extension}"
                
            return filename
            
        except Exception as e:
            logging.error(f"Error extracting filename: {e}")
            return f"{uuid.uuid4()}.bin"

    def _process_part(self, part: str, no_css: bool = False, no_images: bool = False, html_only: bool = False) -> None:
        """
        Process each MHTML part and extract its content with improved parsing and validation.

        Args:
            part: A part of the MHTML document.
            no_css: If True, CSS files will not be extracted.
            no_images: If True, image files will not be extracted.
            html_only: If True, only HTML files will be extracted.
        """
        try:
            # Split headers and body more robustly
            if "\r\n\r\n" in part:
                headers, body = part.split("\r\n\r\n", 1)
            elif "\n\n" in part:
                headers, body = part.split("\n\n", 1)
            else:
                logging.warning("Could not find header/body separator in part")
                return

            # Extract various headers from the part with improved regex
            content_type_match = re.search(r"Content-Type:\s*([^\r\n;]+)", headers, re.IGNORECASE)
            content_transfer_encoding_match = re.search(r"Content-Transfer-Encoding:\s*([^\r\n]+)", headers, re.IGNORECASE)
            content_location_match = re.search(r"Content-Location:\s*([^\r\n]+)", headers, re.IGNORECASE)
            content_id_match = re.search(r"Content-ID:\s*<([^>]+)>", headers, re.IGNORECASE)

            if not content_type_match:
                logging.debug("No Content-Type found in part, skipping")
                self.stats.skipped_files += 1
                return

            content_type = content_type_match.group(1).strip().lower()

            # Apply filters
            if self._should_skip_content(content_type, no_css, no_images, html_only):
                self.stats.skipped_files += 1
                return

            encoding = None
            if content_transfer_encoding_match:
                encoding = content_transfer_encoding_match.group(1).strip().lower()

            # Decode the body based on its encoding
            decoded_body = self._decode_body(encoding, body)

            # Update statistics
            self._update_stats(content_type, decoded_body)

            # Determine the filename for this part
            filename = self._extract_filename(headers, content_type)

            # Update our URL to filename mapping
            if content_location_match:
                location = content_location_match.group(1).strip()
                self.url_mapping[location] = filename

            if content_id_match:
                cid = "cid:" + content_id_match.group(1)
                self.url_mapping[cid] = filename

            # Write the content to a file (if not dry run)
            if not self.dry_run:
                self._write_to_file(filename, content_type, decoded_body)
            else:
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
        if no_images and ("image" in content_type):
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
        
        # Calculate size
        if isinstance(decoded_body, str):
            size = len(decoded_body.encode('utf-8'))
        else:
            size = len(decoded_body)
        self.stats.total_size += size
        
        # Categorize by type
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
        Write the decoded content to a file with proper error handling.

        Args:
            filename: The name of the file to be written.
            content_type: The content type of the data (e.g., "text/html").
            decoded_body: The decoded content to be written.
            
        Raises:
            OSError: If file cannot be written.
        """
        try:
            # Ensure content is in bytes format for writing
            if isinstance(decoded_body, str):
                decoded_body = decoded_body.encode("utf-8")

            if "html" in content_type:
                # Append this filename to our list of saved HTML files
                self.saved_html_files.append(filename)

            # Write the decoded content to the specified file
            file_path = self.output_dir / filename
            with open(file_path, "wb") as out_file:
                out_file.write(decoded_body)
                
            logging.debug(f"Wrote {len(decoded_body)} bytes to {filename}")
            
        except OSError as e:
            logging.error(f"Error writing file {filename}: {e}")
            raise

    def _update_html_links(self, filepath: Path, sorted_urls: List[str], hash_pattern: re.Pattern, 
                          no_css: bool = False, no_images: bool = False, html_only: bool = False) -> None:
        """
        Update the links in HTML files with improved performance and error handling.

        Args:
            filepath: The path to the HTML file.
            sorted_urls: A list of URLs sorted by length.
            hash_pattern: A compiled regular expression pattern for hashed filenames.
            no_css: Skip CSS link updates if True.
            no_images: Skip image link updates if True.
            html_only: Skip all link updates if True.
        """
        # If html_only flag is set, we don't need to update anything.
        if html_only:
            return

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as html_file:
                content = html_file.read()

            original_content = content
            
            # For each original URL, replace it with the new filename in the content
            for original_url in sorted_urls:
                new_filename = self.url_mapping[original_url]

                # Skip updating links for CSS files if no_css flag is set
                if no_css and new_filename.endswith(".css"):
                    continue

                # Skip updating links for image files if no_images flag is set
                if no_images and any(new_filename.endswith(ext) for ext in IMAGE_EXTENSIONS):
                    continue

                # Use re.sub for more efficient replacement
                escaped_url = re.escape(original_url)
                content = re.sub(escaped_url, new_filename, content)

            # Only write if content changed
            if content != original_content:
                with open(filepath, "w", encoding="utf-8") as html_file:
                    html_file.write(content)
                logging.debug(f"Updated links in {filepath.name}")
            
        except Exception as e:
            logging.error(f"Error updating HTML links in {filepath}: {e}")

    def extract(self, no_css: bool = False, no_images: bool = False, html_only: bool = False) -> ExtractionStats:
        """
        Extract files from MHTML into separate files with enhanced performance and error handling.
        
        Args:
            no_css: If True, CSS files will not be extracted.
            no_images: If True, image files will not be extracted.
            html_only: If True, only HTML files will be extracted.
            
        Returns:
            ExtractionStats object with details about the extraction.
            
        Raises:
            FileNotFoundError: If MHTML file doesn't exist.
            PermissionError: If unable to read MHTML file or write to output directory.
        """
        start_time = time.time()
        temp_buffer_chunks: List[str] = []  # Use a list to store chunks efficiently

        try:
            if self.dry_run:
                logging.info(f"[DRY RUN] Analyzing MHTML file: {self.mhtml_path}")
            else:
                logging.info(f"Extracting from: {self.mhtml_path} to: {self.output_dir}")

            with open(self.mhtml_path, "r", encoding="utf-8", errors="replace") as file:
                # Continuously read from the MHTML file until no more content is left
                while True:
                    chunk = file.read(self.buffer_size)
                    if not chunk:
                        break

                    # Use list for efficient string concatenation (O(n) instead of O(n²))
                    temp_buffer_chunks.append(chunk)

                    # If the boundary hasn't been determined yet, try to find it
                    if not self.boundary:
                        joined_buffer = "".join(temp_buffer_chunks)
                        self.boundary = self._read_boundary(joined_buffer)
                        if self.boundary:
                            logging.debug(f"Boundary found: {self.boundary}")

                    # Only process if we have a boundary
                    if self.boundary:
                        # Split the buffer by the boundary to process each part
                        joined_buffer = "".join(temp_buffer_chunks)
                        parts = joined_buffer.split("--" + self.boundary)

                        # Retain the last part in case it's incomplete
                        temp_buffer_chunks = [parts[-1]]

                        # Process all complete parts
                        for part in parts[:-1]:
                            if self.extracted_count > 0:  # Skip the headers
                                self._process_part(part.strip(), no_css, no_images, html_only)
                            self.extracted_count += 1

                # Process any remaining part
                if temp_buffer_chunks and self.boundary:
                    remaining_part = "".join(temp_buffer_chunks).strip()
                    if remaining_part and remaining_part != "--":
                        self._process_part(remaining_part, no_css, no_images, html_only)

            # Update HTML links if not in dry run mode and not html_only
            if not self.dry_run and not html_only and self.saved_html_files:
                self._update_all_html_links(no_css, no_images, html_only)

            # Finalize statistics
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
        if not self.url_mapping:
            return
            
        # Sort URLs by length (longest first) for proper replacement
        sorted_urls = sorted(self.url_mapping.keys(), key=len, reverse=True)
        hash_pattern = re.compile(r"_[a-f0-9]{32}\.")

        logging.info(f"Updating links in {len(self.saved_html_files)} HTML files...")
        
        for filename in self.saved_html_files:
            filepath = self.output_dir / filename
            if filepath.exists():
                self._update_html_links(filepath, sorted_urls, hash_pattern, no_css, no_images, html_only)

    def _log_extraction_summary(self) -> None:
        """Log a summary of the extraction process."""
        if self.dry_run:
            logging.info(f"[DRY RUN] Analysis complete:")
        else:
            logging.info(f"Extraction complete:")
            
        logging.info(f"  Total parts processed: {self.stats.total_parts}")
        logging.info(f"  HTML files: {self.stats.html_files}")
        logging.info(f"  CSS files: {self.stats.css_files}")
        logging.info(f"  Image files: {self.stats.image_files}")
        logging.info(f"  Other files: {self.stats.other_files}")
        logging.info(f"  Skipped files: {self.stats.skipped_files}")
        logging.info(f"  Total size: {self.stats.total_size:,} bytes")
        logging.info(f"  Extraction time: {self.stats.extraction_time:.2f} seconds")
        
        if not self.dry_run:
            logging.info(f"  Output directory: {self.output_dir}")


if __name__ == "__main__":
    # Enhanced argument parsing setup with better help and validation
    parser = argparse.ArgumentParser(
        description="Extract files from MHTML documents with enhanced performance and features.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s document.mhtml
  %(prog)s document.mhtml --output_dir ./extracted
  %(prog)s document.mhtml --html-only --dry-run
  %(prog)s document.mhtml --no-css --no-images --buffer_size 16384
        """
    )
    
    parser.add_argument("mhtml_path", type=str, help="Path to the MHTML document.")
    parser.add_argument("--output_dir", type=str, default=".", help="Output directory for the extracted files. (default: current directory)")
    parser.add_argument("--buffer_size", type=int, default=DEFAULT_BUFFER_SIZE, help=f"Buffer size for reading the MHTML file. (default: {DEFAULT_BUFFER_SIZE})")
    parser.add_argument("--clear_output_dir", action="store_true", help="If set, clears the output directory before extraction.")
    parser.add_argument("--no-css", action="store_true", help="If set, CSS files will not be extracted.")
    parser.add_argument("--no-images", action="store_true", help="If set, image files will not be extracted.")
    parser.add_argument("--html-only", action="store_true", help="If set, only HTML files will be extracted.")
    parser.add_argument("--dry-run", action="store_true", help="If set, analyze the MHTML file without extracting files.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging output.")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress all output except errors.")

    args = parser.parse_args()

    # Configure logging based on verbosity
    if args.quiet:
        logging.getLogger().setLevel(logging.ERROR)
    elif args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        # Create extractor with enhanced error handling
        extractor = MHTMLExtractor(
            mhtml_path=args.mhtml_path,
            output_dir=args.output_dir,
            buffer_size=args.buffer_size,
            clear_output_dir=args.clear_output_dir,
            dry_run=args.dry_run,
        )

        # Perform extraction
        stats = extractor.extract(args.no_css, args.no_images, args.html_only)
        
        # Exit with appropriate code
        if stats.total_parts == 0:
            logging.warning("No parts were found in the MHTML file")
            exit(1)
        else:
            exit(0)
            
    except FileNotFoundError as e:
        logging.error(f"File not found: {e}")
        exit(1)
    except PermissionError as e:
        logging.error(f"Permission denied: {e}")
        exit(1)
    except ValueError as e:
        logging.error(f"Invalid argument: {e}")
        exit(1)
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        exit(1)
