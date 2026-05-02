"""Constants shared across the MHTML extractor package."""

import re

DEFAULT_BUFFER_SIZE = 8192
MIN_BUFFER_SIZE = 1024
MAX_BUFFER_SIZE = 1024 * 1024  # 1MB

SUPPORTED_ENCODINGS = {"base64", "quoted-printable", "7bit", "8bit", "binary"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico"}
TEXT_CONTENT_TYPES = {"text/html", "text/css", "text/javascript", "application/javascript"}

BOUNDARY_PATTERNS = (
    re.compile(r'boundary="([^"]+)"', re.IGNORECASE),
    re.compile(r"boundary=([^;\s]+)", re.IGNORECASE),
)
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')

LOG_FORMAT = "[%(asctime)s][%(filename)s:%(lineno)d][%(levelname)s]: %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"
