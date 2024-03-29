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

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(filename)s:%(lineno)d][%(levelname)s]: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler()],
)


class MHTMLExtractor:
    """
    A class to extract files from MHTML documents.

    Attributes:
        mhtml_path (str): The path to the MHTML document.
        output_dir (str): The directory where extracted files will be saved.
        buffer_size (int): The size of the buffer used when reading the MHTML file.
        boundary (str): The boundary string used in the MHTML document.
        extracted_count (int): A counter for the number of files extracted.
        url_mapping (dict): A dictionary mapping original URLs to new filenames.
    """

    def __init__(self, mhtml_path, output_dir, buffer_size=8192, clear_output_dir=False):
        """
        Initialize the MHTMLExtractor class.

        Args:
            mhtml_path (str): Path to the MHTML document.
            output_dir (str): Output directory for the extracted files.
            buffer_size (int, optional): Buffer size for reading the MHTML file. Defaults to 8192.
            clear_output_dir (bool, optional): If True, clears the output directory before extraction. Defaults to False.
        """
        self.mhtml_path = mhtml_path
        self.output_dir = output_dir
        self.buffer_size = buffer_size
        self.boundary = None
        self.extracted_count = 0
        self.url_mapping = {}  # Mapping between Content-Location and new filenames
        self.saved_html_files = []  # List to keep track of saved HTML filenames

        self.ensure_directory_exists(self.output_dir, clear_output_dir)

    def ensure_directory_exists(self, directory_path, clear=False):
        try:
            if not os.path.exists(directory_path):
                os.makedirs(directory_path)
            elif clear:
                for filename in os.listdir(directory_path):
                    file_path = os.path.join(directory_path, filename)
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
        except Exception as e:
            logging.error(f"Error during directory setup: {e}")

    def is_text_content(decoded_content):
        """Determine if the given content is likely to be human-readable text."""

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

    def _read_boundary(self, temp_buffer):
        """
        Extract boundary string from the MHTML headers.

        Args:
            temp_buffer (str): A buffer containing part of the MHTML document.

        Returns:
            str: The extracted boundary string or None if not found.
        """
        try:
            boundary_match = re.search(r'boundary="([^"]+)"', temp_buffer)
            if boundary_match:
                return boundary_match.group(1)
        except Exception as e:
            logging.error(f"Error reading boundary: {e}")
        return None

    def _decode_body(self, encoding, body):
        """
        Decode the body content based on the Content-Transfer-Encoding header.

        Args:
            encoding (str): The content encoding (e.g., "base64", "quoted-printable").
            body (str): The body content to be decoded.

        Returns:
            str: The decoded body content.
        """
        try:
            if encoding == "base64":
                return base64.b64decode(body)
            elif encoding == "quoted-printable":
                return quopri.decodestring(body)
        except Exception as e:
            logging.error(f"Error decoding body: {e}")
            return body
        return body

    def _extract_filename(self, headers, content_type):
        """
        Determine the filename based on headers or generate one if necessary.

        Args:
            headers (str): Part headers from the MHTML document.
            content_type (str): The content type of the part (e.g., "text/html").

        Returns:
            str: The determined filename.
        """
        try:
            content_location_match = re.search(r"Content-Location: ([^\n]+)", headers)
            extension = mimetypes.guess_extension(content_type)

            # If Content-Location is provided in the headers, use it to derive a filename
            if content_location_match:
                location = content_location_match.group(1)
                parsed_url = urlparse(location)
                base_name = os.path.basename(unquote(parsed_url.path)) or parsed_url.netloc
                url_hash = hashlib.md5(location.encode()).hexdigest()

                filename = f"{base_name}_{url_hash}{extension or ''}"
                original_filename = filename
                counter = 1

                # Handle potential filename conflicts by appending a counter
                while os.path.exists(os.path.join(self.output_dir, filename)):
                    filename = f"{original_filename}_{counter}"
                    counter += 1
            else:
                # If Content-Location isn't provided, generate a random filename
                filename = str(uuid.uuid4()) + (extension or "")
            return filename
        except Exception as e:
            logging.error(f"Error extracting filename: {e}")
            return str(uuid.uuid4())

    def _process_part(self, part, no_css=False, no_images=False, html_only=False):
        """
        Process each MHTML part and extract its content.

        Args:
            part (str): A part of the MHTML document.
            no_css (bool): If True, CSS files will not be extracted.
            no_images (bool): If True, image files will not be extracted.
            html_only (bool): If True, only HTML files will be extracted.
        """
        try:
            headers, body = part.split("\n\n", 1)

            # Extract various headers from the part
            content_type_match = re.search(r"Content-Type: ([^\n]+)", headers, re.IGNORECASE)
            content_transfer_encoding_match = re.search(r"Content-Transfer-Encoding: ([^\n]+)", headers, re.IGNORECASE)
            content_location_match = re.search(r"Content-Location: ([^\n]+)", headers, re.IGNORECASE)
            content_id_match = re.search(r"Content-ID: <([^>]+)>", headers, re.IGNORECASE)

            if not content_type_match:
                return

            content_type = content_type_match.group(1).split(";")[0].strip()

            if no_css and "css" in content_type:
                return
            if no_images and ("image" in content_type or "img" in content_type):
                return
            if html_only and "html" not in content_type:
                return

            encoding = None
            if content_transfer_encoding_match:
                encoding = content_transfer_encoding_match.group(1).strip().lower()

            # Decode the body based on its encoding
            decoded_body = self._decode_body(encoding, body)

            # Determine the filename for this part
            filename = self._extract_filename(headers, content_type)

            # Update our URL to filename mapping
            if content_location_match:
                location = content_location_match.group(1)
                self.url_mapping[location] = filename

            if content_id_match:
                cid = "cid:" + content_id_match.group(1)
                self.url_mapping[cid] = filename

            # Write the content to a file
            self._write_to_file(filename, content_type, decoded_body)
        except Exception as e:
            logging.error(f"Error processing MHTML part: {e}")

    def _write_to_file(self, filename, content_type, decoded_body):
        """
        Write the decoded content to a file.

        Args:
            filename (str): The name of the file to be written.
            content_type (str): The content type of the data (e.g., "text/html").
            decoded_body (str): The decoded content to be written.
        """
        # If the content is text-based, ensure it's in bytes format for writing (since file will be in 'wb' mode)
        if isinstance(decoded_body, str):
            decoded_body = bytes(decoded_body, encoding="utf-8")

        if "html" in content_type:
            # Append this filename to our list of saved HTML files
            self.saved_html_files.append(filename)

        # Try to write the decoded content to the specified file
        with open(os.path.join(self.output_dir, filename), "wb") as out_file:
            out_file.write(decoded_body)

    def _update_html_links(self, filepath, sorted_urls, hash_pattern, no_css=False, no_images=False, html_only=False):
        """
        Update the links in HTML files.
        There has got to be a better way of achieving this instead of loading the entire contents into memory again.
        We unfortunately dont have the updated file names until the other files have been parsed...

        Args:
            filepath (str): The path to the HTML file.
            sorted_urls (list): A list of URLs sorted by length.
            hash_pattern (re.Pattern): A compiled regular expression pattern for hashed filenames.
        """
        # If html_only flag is set, we dont need to update anything.
        if html_only:
            return

        with open(filepath, "r", encoding="utf-8") as html_file:
            content = html_file.read()

            # For each original URL, replace it with the new filename in the content
            for original_url in sorted_urls:
                new_filename = self.url_mapping[original_url]

                # Skip updating links for CSS files if no_css flag is set
                if no_css and new_filename.endswith(".css"):
                    continue

                # Skip updating links for image files if no_images flag is set
                if no_images and any(new_filename.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"]):
                    continue

                matches = list(re.finditer(re.escape(original_url), content))

                # Replace the links in the content
                for match in reversed(matches):
                    if not hash_pattern.match(content, match.end()):
                        content = content[: match.start()] + new_filename + content[match.end() :]

        with open(filepath, "w", encoding="utf-8") as html_file:
            html_file.write(content)

    def extract(self, no_css=False, no_images=False, html_only=False):
        """
        Extract files from MHTML into separate files.
        """
        temp_buffer_chunks = []  # Use a list to store chunks and join them when needed

        try:
            with open(self.mhtml_path, "r", encoding="utf-8") as file:
                # Continuously read from the MHTML file until no more content is left
                while True:
                    chunk = file.read(self.buffer_size)
                    if not chunk:
                        break

                    """
                    Python strings are immutable, This means that every time you concatenate two strings using 
                    the '+' operator, a new string is created in memory, and the contents of the two original 
                    strings are copied over to this new string. The time complexity of the following line is O(n^2)
                    
                    temp_buffer_chunks += chunk
                    
                    On the other hand, the list join method avoids this overhead by creating a single new string 
                    and copying the content of each string in the list to the new string only once. This results 
                    in a linear time complexity of O(n).
                    """
                    temp_buffer_chunks.append(chunk)

                    # If the boundary hasn't been determined yet, try to find it
                    if not self.boundary:
                        self.boundary = self._read_boundary("".join(temp_buffer_chunks))

                    # Split the buffer by the boundary to process each part
                    parts = "".join(temp_buffer_chunks).split("--" + self.boundary)

                    # Retain the last part in case it's incomplete
                    temp_buffer_chunks = [parts[-1]]  # Retain the last part in case it's incomplete

                    for part in parts[:-1]:
                        if self.extracted_count > 0:  # Skip the headers
                            self._process_part(part, no_css, no_images, html_only)

                        self.extracted_count += 1

            if html_only:
                return

            # After processing all parts, sort URLs by length (longest first)
            sorted_urls = sorted(self.url_mapping.keys(), key=len, reverse=True)
            hash_pattern = re.compile(r"_[a-f0-9]{32}\.html")

            # Update links in all saved HTML files to reflect new filenames
            for filename in self.saved_html_files:
                filepath = os.path.join(self.output_dir, filename)
                self._update_html_links(filepath, sorted_urls, hash_pattern)

            logging.info(f"Extracted {self.extracted_count-1} files into {self.output_dir}")
        except Exception as e:
            logging.error(f"Error during extraction: {e}")


if __name__ == "__main__":
    # Argument parsing setup
    parser = argparse.ArgumentParser(description="Extract files from MHTML documents.")
    parser.add_argument("mhtml_path", type=str, help="Path to the MHTML document.")
    parser.add_argument("--output_dir", type=str, default=".", help="Output directory for the extracted files.")
    parser.add_argument("--buffer_size", type=int, default=8192, help="Buffer size for reading the MHTML file. Defaults to 8192.")
    parser.add_argument("--clear_output_dir", action="store_true", help="If set, clears the output directory before extraction.")
    parser.add_argument("--no-css", action="store_true", help="If set, CSS files will not be extracted.")
    parser.add_argument("--no-images", action="store_true", help="If set, image files will not be extracted.")
    parser.add_argument("--html-only", action="store_true", help="If set, only HTML files will be extracted.")
    # parser.add_argument("--main_only", action="store_true", help="If set, only the main HTML file will be extracted.")

    args = parser.parse_args()

    # Example usage with command-line arguments
    extractor = MHTMLExtractor(
        mhtml_path=args.mhtml_path,
        output_dir=args.output_dir,
        buffer_size=args.buffer_size,
        clear_output_dir=args.clear_output_dir,
    )

    extractor.extract(args.no_css, args.no_images, args.html_only)
