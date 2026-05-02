import hashlib
import logging
import tempfile
import unittest
from pathlib import Path

from MHTMLExtractor import DEFAULT_BUFFER_SIZE, MHTMLExtractor, build_arg_parser, configure_logging
from mhtmlextractor.constants import DEFAULT_BUFFER_SIZE as PACKAGE_DEFAULT_BUFFER_SIZE
from mhtmlextractor import MHTMLExtractor as PackageMHTMLExtractor


def hashed_filename(location, stem, suffix):
    url_hash = hashlib.md5(location.encode()).hexdigest()
    return f"{stem}_{url_hash}{suffix}"


class FilenameExtractionTests(unittest.TestCase):
    def make_extractor(self, output_dir, dry_run=False):
        return MHTMLExtractor(output_dir=output_dir, dry_run=dry_run)

    def test_url_path_extension_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            extractor = self.make_extractor(temp_dir)
            location = "https://example.com/index.html"
            headers = f"Content-Location: {location}\r\n"

            filename = extractor._extract_filename(headers, "text/html")

        self.assertEqual(filename, hashed_filename(location, "index", ".html"))

    def test_mime_extension_is_used_when_url_has_no_extension(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            extractor = self.make_extractor(temp_dir)
            location = "https://example.com/assets/site"
            headers = f"Content-Location: {location}\r\n"

            filename = extractor._extract_filename(headers, "text/css")

        self.assertEqual(filename, hashed_filename(location, "site", ".css"))

    def test_query_strings_do_not_duplicate_extensions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            extractor = self.make_extractor(temp_dir)
            location = "https://example.com/assets/site.css?version=1"
            headers = f"Content-Location: {location}\r\n"

            filename = extractor._extract_filename(headers, "text/css")

        self.assertEqual(filename, hashed_filename(location, "site", ".css"))

    def test_conflict_counter_is_inserted_before_extension(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            extractor = self.make_extractor(output_dir)
            location = "https://example.com/assets/site.css"
            headers = f"Content-Location: {location}\r\n"
            first_filename = hashed_filename(location, "site", ".css")
            (output_dir / first_filename).touch()

            filename = extractor._extract_filename(headers, "text/css")

        self.assertEqual(filename, first_filename.replace(".css", "_1.css"))


class ContentHandlingTests(unittest.TestCase):
    def test_content_filters_are_explicit(self):
        extractor = MHTMLExtractor(dry_run=True)

        self.assertTrue(extractor._should_skip_content("text/css", no_css=True, no_images=False, html_only=False))
        self.assertTrue(extractor._should_skip_content("image/png", no_css=False, no_images=True, html_only=False))
        self.assertTrue(extractor._should_skip_content("text/css", no_css=False, no_images=False, html_only=True))
        self.assertFalse(extractor._should_skip_content("text/html", no_css=False, no_images=False, html_only=True))

    def test_decode_body_returns_plain_text_for_unknown_encoding(self):
        self.assertEqual(
            MHTMLExtractor._decode_body("x-custom", "plain text"),
            "plain text",
        )


class LinkUpdateTests(unittest.TestCase):
    def test_updates_raw_url_with_query_ampersand(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "index.html"
            original_url = "https://example.com/assets/site.css?theme=light&v=1"
            html_path.write_text(f'<link rel="stylesheet" href="{original_url}">', encoding="utf-8")
            extractor = MHTMLExtractor(output_dir=temp_dir)
            extractor.url_mapping[original_url] = "site_123.css"

            extractor._update_html_links(html_path, [original_url])

            self.assertEqual(
                html_path.read_text(encoding="utf-8"),
                '<link rel="stylesheet" href="site_123.css">',
            )


class ExtractionTests(unittest.TestCase):
    def test_binary_transfer_part_preserves_original_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)
            output_dir = work_dir / "out"
            mhtml_path = work_dir / "binary.mhtml"
            location = "https://example.com/image.jpg"
            payload = b"\xff\xd8\xff\xe0\r\nbinary-jpeg-data   "
            boundary = b"issue8-boundary"
            mhtml_path.write_bytes(
                b'Content-Type: multipart/related; boundary="issue8-boundary"\r\n'
                b"\r\n"
                b"--" + boundary + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Transfer-Encoding: binary\r\n"
                b"Content-Location: " + location.encode("ascii") + b"\r\n"
                b"\r\n"
                + payload
                + b"\r\n--" + boundary + b"--\r\n"
            )

            extractor = MHTMLExtractor(mhtml_path=mhtml_path, output_dir=output_dir)
            extractor.extract()

            filename = hashed_filename(location, "image", ".jpg")
            self.assertEqual((output_dir / filename).read_bytes(), payload)


class CliTests(unittest.TestCase):
    def test_legacy_module_exports_package_extractor(self):
        self.assertIs(MHTMLExtractor, PackageMHTMLExtractor)

    def test_legacy_module_exports_constants(self):
        self.assertEqual(DEFAULT_BUFFER_SIZE, PACKAGE_DEFAULT_BUFFER_SIZE)

    def test_parser_accepts_expected_options(self):
        parser = build_arg_parser()

        args = parser.parse_args(["sample.mhtml", "--output_dir", "out", "--dry-run", "--verbose"])

        self.assertEqual(args.mhtml_path, "sample.mhtml")
        self.assertEqual(args.output_dir, "out")
        self.assertTrue(args.dry_run)
        self.assertTrue(args.verbose)

    def test_configure_logging_honors_quiet_before_verbose(self):
        class Args:
            quiet = True
            verbose = True

        configure_logging(Args())

        self.assertEqual(logging.getLogger().level, logging.ERROR)


if __name__ == "__main__":
    unittest.main()
