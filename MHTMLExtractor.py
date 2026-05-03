"""Compatibility wrapper for the mhtmlextractor package."""

import sys

from mhtmlextractor import (
    ExtractionStats,
    MHTMLArchive,
    MHTMLExtractor,
    MHTMLPart,
    parse_mhtml,
)
from mhtmlextractor.cli import build_arg_parser, configure_logging, main
from mhtmlextractor.constants import (
    DEFAULT_BUFFER_SIZE,
    IMAGE_EXTENSIONS,
    MAX_BUFFER_SIZE,
    MIN_BUFFER_SIZE,
    SUPPORTED_ENCODINGS,
    TEXT_CONTENT_TYPES,
)

__all__ = [
    "DEFAULT_BUFFER_SIZE",
    "ExtractionStats",
    "MHTMLArchive",
    "IMAGE_EXTENSIONS",
    "MAX_BUFFER_SIZE",
    "MIN_BUFFER_SIZE",
    "MHTMLExtractor",
    "MHTMLPart",
    "SUPPORTED_ENCODINGS",
    "TEXT_CONTENT_TYPES",
    "build_arg_parser",
    "configure_logging",
    "main",
    "parse_mhtml",
]


if __name__ == "__main__":
    sys.exit(main())
