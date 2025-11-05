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

DEFAULT_BUFFER_SIZE = 8192
MIN_BUFFER_SIZE = 1024
MAX_BUFFER_SIZE = 1024 * 1024
SUPPORTED_ENCODINGS = {"base64", "quoted-printable", "7bit", "8bit", "binary"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico"}
TEXT_CONTENT_TYPES = {"text/html", "text/css", "text/javascript", "application/javascript"}

logging.basicConfig(level=logging.CRITICAL)


@dataclass
class ExtractionStats:
    total_parts: int = 0
    html_files: int = 0
    css_files: int = 0
    image_files: int = 0
    other_files: int = 0
    skipped_files: int = 0
    total_size: int = 0
    extraction_time: float = 0.0


class MHTMLExtractor:

    def __init__(
        self,
        mhtml_path: Union[str, Path],
        output_dir: Union[str, Path],
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        clear_output_dir: bool = False,
        dry_run: bool = False
    ) -> None:
        self.mhtml_path = Path(mhtml_path).resolve()
        self.output_dir = Path(output_dir).resolve()

        if not self.mhtml_path.exists() or not self.mhtml_path.is_file():
            self.is_valid = False
            return

        self.buffer_size = self._optimize_buffer_size(buffer_size)

        self.boundary: Optional[str] = None
        self.extracted_count: int = 0
        self.url_mapping: Dict[str, str] = {}
        self.saved_html_files: List[str] = []
        self.stats = ExtractionStats()
        self.dry_run = dry_run
        self.is_valid = True

        if not dry_run:
            self._setup_output_directory(clear_output_dir)
            if not self.is_valid:
                return


    def _optimize_buffer_size(self, buffer_size: int) -> int:
        if buffer_size < MIN_BUFFER_SIZE:
            buffer_size = MIN_BUFFER_SIZE

        if buffer_size > MAX_BUFFER_SIZE:
            buffer_size = MAX_BUFFER_SIZE

        try:
            file_size = self.mhtml_path.stat().st_size
            optimal_size = min(max(file_size // 100, MIN_BUFFER_SIZE), MAX_BUFFER_SIZE)
            if optimal_size != buffer_size:
                buffer_size = optimal_size
        except OSError:
            pass

        return buffer_size

    def _setup_output_directory(self, clear: bool = False) -> None:
        try:
            if not self.output_dir.exists():
                self.output_dir.mkdir(parents=True, exist_ok=True)
            elif clear:
                self._clear_directory(self.output_dir)

            test_file = self.output_dir / ".mhtml_extractor_test"
            try:
                test_file.touch()
                test_file.unlink()
            except OSError:
                self.is_valid = False

        except OSError:
            self.is_valid = False


    @staticmethod
    def _clear_directory(directory_path: Path) -> None:
        for item in directory_path.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except OSError:
                pass

    @staticmethod
    def ensure_directory_exists(directory_path: Union[str, Path], clear: bool = False) -> None:
        path = Path(directory_path)
        try:
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
            elif clear:
                MHTMLExtractor._clear_directory(path)
        except Exception:
            pass

    @staticmethod
    def is_text_content(decoded_content: Union[str, bytes]) -> bool:
        if isinstance(decoded_content, str):
            return True
        if b"\0" in decoded_content:
            return False
        sample = decoded_content[:1024]
        text_chars = {7, 8, 9, 10, 12, 13} | set(range(0x20, 0x7F))
        if all(byte in text_chars for byte in sample):
            return True
        try:
            decoded_content.decode("utf-8")
            return True
        except UnicodeDecodeError:
            pass
        return False

    @staticmethod
    def _read_boundary(temp_buffer: str) -> Optional[str]:
        try:
            patterns = [
                r'boundary="([^"]+)"',
                r'boundary=([^;\s]+)',
            ]
            for pattern in patterns:
                boundary_match = re.search(pattern, temp_buffer, re.IGNORECASE)
                if boundary_match:
                    boundary = boundary_match.group(1).strip()
                    if boundary:
                        return boundary
        except Exception:
            pass
        return None

    @staticmethod
    def _decode_body(encoding: Optional[str], body: str) -> Union[str, bytes]:
        if not encoding:
            return body
        encoding = encoding.lower().strip()
        try:
            if encoding == "base64":
                clean_body = re.sub(r'\s+', '', body)
                return base64.b64decode(clean_body)
            elif encoding == "quoted-printable":
                return quopri.decodestring(body.encode()).decode('utf-8', errors='replace')
            elif encoding in {"7bit", "8bit", "binary"}:
                return body
            else:
                return body
        except Exception:
            return body

    def _extract_filename(self, headers: str, content_type: str) -> str:
        try:
            content_location_match = re.search(r"Content-Location:\s*([^\r\n]+)", headers, re.IGNORECASE)
            extension = mimetypes.guess_extension(content_type) or ""
            if content_location_match:
                location = content_location_match.group(1).strip()
                parsed_url = urlparse(location)
                base_name = os.path.basename(unquote(parsed_url.path)) or parsed_url.netloc
                base_name = re.sub(r'[<>:"/\\|?*]', '_', base_name) or "unnamed"
                url_hash = hashlib.md5(location.encode()).hexdigest()
                filename = f"{base_name}_{url_hash}{extension}"
                original_filename = filename
                counter = 1
                while not self.dry_run and (self.output_dir / filename).exists():
                    name_part, ext_part = os.path.splitext(original_filename)
                    filename = f"{name_part}_{counter}{ext_part}"
                    counter += 1
            else:
                filename = f"{uuid.uuid4()}{extension}"
            return filename
        except Exception:
            return f"{uuid.uuid4()}.bin"

    def _process_part(self, part: str, no_css: bool = False, no_images: bool = False,
                      allowed_types: Optional[List[str]] = None) -> None:
        try:
            if "\r\n\r\n" in part:
                headers, body = part.split("\r\n\r\n", 1)
            elif "\n\n" in part:
                headers, body = part.split("\n\n", 1)
            else:
                return

            content_type_match = re.search(r"Content-Type:\s*([^\r\n;]+)", headers, re.IGNORECASE)
            content_transfer_encoding_match = re.search(r"Content-Transfer-Encoding:\s*([^\r\n]+)", headers, re.IGNORECASE)
            content_location_match = re.search(r"Content-Location:\s*([^\r\n]+)", headers, re.IGNORECASE)
            content_id_match = re.search(r"Content-ID:\s*<([^>]+)>", headers, re.IGNORECASE)

            if not content_type_match:
                self.stats.skipped_files += 1
                return

            content_type = content_type_match.group(1).strip().lower()

            if self._should_skip_content(content_type, no_css, no_images, allowed_types):
                self.stats.skipped_files += 1
                return

            encoding = None
            if content_transfer_encoding_match:
                encoding = content_transfer_encoding_match.group(1).strip().lower()

            decoded_body = self._decode_body(encoding, body)

            self._update_stats(content_type, decoded_body)

            filename = self._extract_filename(headers, content_type)

            if content_location_match:
                location = content_location_match.group(1).strip()
                self.url_mapping[location] = filename

            if content_id_match:
                cid = "cid:" + content_id_match.group(1)
                self.url_mapping[cid] = filename

            if not self.dry_run:
                self._write_to_file(filename, content_type, decoded_body)

        except Exception:
            self.stats.skipped_files += 1

    def _should_skip_content(self, content_type: str, no_css: bool, no_images: bool,
                             allowed_types: Optional[List[str]] = None) -> bool:
        if allowed_types:
            type_map = {
                "html": "html",
                "css": "css",
                "img": "image",
                "image": "image",
                "js": "javascript",
                "javascript": "javascript",
                "other": None,
            }
            normalized = [t.strip().lower() for t in allowed_types if t.strip()]
            is_core = any(k in content_type for k in ("html", "css", "image", "javascript"))
            is_other = not is_core
            allowed = False
            for kw in normalized:
                if kw is None:
                    if is_other:
                        allowed = True
                        break
                elif kw in content_type:
                    allowed = True
                    break
            if not allowed:
                return True

        if no_css and "css" in content_type:
            return True
        if no_images and ("image" in content_type):
            return True
        return False

    def _update_stats(self, content_type: str, decoded_body: Union[str, bytes]) -> None:
        self.stats.total_parts += 1
        if isinstance(decoded_body, str):
            size = len(decoded_body.encode('utf-8'))
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
        try:
            if isinstance(decoded_body, str):
                decoded_body = decoded_body.encode("utf-8")
            if "html" in content_type:
                self.saved_html_files.append(filename)
            file_path = self.output_dir / filename
            with open(file_path, "wb") as out_file:
                out_file.write(decoded_body)
        except OSError:
            pass

    def _update_html_links(self, filepath: Path, sorted_urls: List[str], hash_pattern: re.Pattern,
                          no_css: bool = False, no_images: bool = False) -> None:
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as html_file:
                content = html_file.read()
            original_content = content
            for original_url in sorted_urls:
                new_filename = self.url_mapping[original_url]
                if no_css and new_filename.endswith(".css"):
                    continue
                if no_images and any(new_filename.endswith(ext) for ext in IMAGE_EXTENSIONS):
                    continue
                escaped_url = re.escape(original_url)
                content = re.sub(escaped_url, new_filename, content)
            if content != original_content:
                with open(filepath, "w", encoding="utf-8") as html_file:
                    html_file.write(content)
        except Exception:
            pass

    def extract(self, no_css: bool = False, no_images: bool = False,
                allowed_types: Optional[List[str]] = None) -> ExtractionStats:
        if not self.is_valid:
            return self.stats

        start_time = time.time()
        temp_buffer_chunks: List[str] = []

        try:
            with open(self.mhtml_path, "r", encoding="utf-8", errors="replace") as file:
                while True:
                    chunk = file.read(self.buffer_size)
                    if not chunk:
                        break
                    temp_buffer_chunks.append(chunk)

                    if not self.boundary:
                        joined_buffer = "".join(temp_buffer_chunks)
                        self.boundary = self._read_boundary(joined_buffer)

                    if self.boundary:
                        joined_buffer = "".join(temp_buffer_chunks)
                        parts = joined_buffer.split("--" + self.boundary)
                        temp_buffer_chunks = [parts[-1]]

                        for part in parts[:-1]:
                            if self.extracted_count > 0:
                                self._process_part(part.strip(), no_css, no_images, allowed_types)
                            self.extracted_count += 1

                if temp_buffer_chunks and self.boundary:
                    remaining_part = "".join(temp_buffer_chunks).strip()
                    if remaining_part and remaining_part != "--":
                        self._process_part(remaining_part, no_css, no_images, allowed_types)

            if not self.dry_run and self.saved_html_files:
                self._update_all_html_links(no_css, no_images)

            self.stats.extraction_time = time.time() - start_time
            return self.stats
        except Exception:
            return self.stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("mhtml_path", type=str)
    parser.add_argument("--output_dir", type=str, default=".")
    parser.add_argument("--buffer_size", type=int, default=DEFAULT_BUFFER_SIZE)
    parser.add_argument("--clear_output_dir", action="store_true")
    parser.add_argument("--no-css", action="store_true")
    parser.add_argument("--no-images", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--extract-types",
        type=str
    )

    args = parser.parse_args([])

    allowed_types = None
    if args.extract_types:
        allowed_types = [t.strip().lower() for t in args.extract_types.split(",") if t.strip()]

    try:
        extractor = MHTMLExtractor(
            mhtml_path=args.mhtml_path,
            output_dir=args.output_dir,
            buffer_size=args.buffer_size,
            clear_output_dir=args.clear_output_dir,
            dry_run=args.dry_run,
        )

        if extractor.is_valid:
            extractor.extract(args.no_css, args.no_images, allowed_types=allowed_types)

    except Exception:
        pass