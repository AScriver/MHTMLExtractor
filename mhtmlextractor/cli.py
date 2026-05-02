"""Command-line interface for MHTMLExtractor."""

import argparse
import logging
from typing import Optional, Sequence

from .constants import DEFAULT_BUFFER_SIZE, LOG_DATE_FORMAT, LOG_FORMAT
from .extractor import MHTMLExtractor


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Extract files from MHTML documents with enhanced performance and features.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s document.mhtml
  %(prog)s document.mhtml --output_dir ./extracted
  %(prog)s document.mhtml --html-only --dry-run
  %(prog)s document.mhtml --no-css --no-images --buffer_size 16384
        """,
    )
    parser.add_argument("mhtml_path", type=str, help="Path to the MHTML document.")
    parser.add_argument(
        "--output_dir",
        type=str,
        default=".",
        help="Output directory for the extracted files. (default: current directory)",
    )
    parser.add_argument(
        "--buffer_size",
        type=int,
        default=DEFAULT_BUFFER_SIZE,
        help=f"Buffer size for reading the MHTML file. (default: {DEFAULT_BUFFER_SIZE})",
    )
    parser.add_argument("--clear_output_dir", action="store_true", help="If set, clears the output directory before extraction.")
    parser.add_argument("--no-css", action="store_true", help="If set, CSS files will not be extracted.")
    parser.add_argument("--no-images", action="store_true", help="If set, image files will not be extracted.")
    parser.add_argument("--html-only", action="store_true", help="If set, only HTML files will be extracted.")
    parser.add_argument("--dry-run", action="store_true", help="If set, analyze the MHTML file without extracting files.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging output.")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress all output except errors.")
    return parser


def configure_logging(args: argparse.Namespace) -> None:
    """Configure logging from parsed CLI arguments."""
    if args.quiet:
        level = logging.ERROR
    elif args.verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format=LOG_FORMAT,
            datefmt=LOG_DATE_FORMAT,
            handlers=[logging.StreamHandler()],
        )
    root_logger.setLevel(level)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the MHTML extractor CLI and return a process exit code."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    configure_logging(args)

    try:
        extractor = MHTMLExtractor(
            mhtml_path=args.mhtml_path,
            output_dir=args.output_dir,
            buffer_size=args.buffer_size,
            clear_output_dir=args.clear_output_dir,
            dry_run=args.dry_run,
        )

        stats = extractor.extract(args.no_css, args.no_images, args.html_only)

        if stats.total_parts == 0:
            logging.warning("No parts were found in the MHTML file")
            return 1
        return 0

    except FileNotFoundError as e:
        logging.error(f"File not found: {e}")
        return 1
    except PermissionError as e:
        logging.error(f"Permission denied: {e}")
        return 1
    except ValueError as e:
        logging.error(f"Invalid argument: {e}")
        return 1
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1
