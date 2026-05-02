"""Content decoding helpers."""

import base64
import logging
import quopri
import re
from typing import Union


def is_text_content(decoded_content: Union[str, bytes]) -> bool:
    """
    Determine if the given content is likely to be human-readable text.

    Args:
        decoded_content: Content to analyze.

    Returns:
        True if content appears to be text, False otherwise.
    """
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
        return False


def decode_body(encoding: str, body: str) -> Union[str, bytes]:
    """
    Decode body content based on the Content-Transfer-Encoding header.

    Args:
        encoding: The content encoding, such as base64 or quoted-printable.
        body: Body content to decode.

    Returns:
        Decoded content, or the original body when encoding is absent or unsupported.
    """
    if not encoding:
        return body

    encoding = encoding.lower().strip()

    try:
        if encoding == "base64":
            clean_body = re.sub(r"\s+", "", body)
            return base64.b64decode(clean_body)
        if encoding == "quoted-printable":
            return quopri.decodestring(body.encode()).decode("utf-8", errors="replace")
        if encoding in {"7bit", "8bit", "binary"}:
            return body

        logging.warning(f"Unsupported encoding: {encoding}, treating as plain text")
        return body
    except Exception as e:
        logging.error(f"Error decoding body with encoding '{encoding}': {e}")
        return body
