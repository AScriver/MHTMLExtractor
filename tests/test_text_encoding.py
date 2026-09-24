"""Public behavior for saving MHTML text with a safe UTF-8 declaration."""

import base64
import quopri
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from MHTMLExtractor import parse_mhtml as legacy_parse_mhtml
from mhtmlextractor import MHTMLExtractor, parse_mhtml
from mhtmlextractor.links import update_html_links


REPO = Path(__file__).resolve().parents[1]
HTML_URL = "https://example.test/index.html"
CSS_URL = "https://example.test/site.css"
CSS_LINK = '<link href="' + CSS_URL + '">'
CP1252_ALIASES = (
    "ansi_x3.4-1968", "ascii", "cp1252", "cp819", "csisolatin1",
    "ibm819", "iso-8859-1", "iso-ir-100", "iso8859-1", "iso88591",
    "iso_8859-1", "iso_8859-1:1987", "l1", "latin1", "us-ascii",
    "windows-1252", "x-cp1252",
)
UTF8_ALIASES = (
    "unicode-1-1-utf-8", "unicode11utf8", "unicode20utf8",
    "utf-8", "utf8", "x-unicode20utf8",
)


def part(content_type, body, transfer="base64", location=HTML_URL):
    """Build a MIME part while keeping body bytes under test explicit."""
    headers = ["Content-Type: " + content_type, "Content-Location: " + location]
    if transfer is not None:
        headers.append("Content-Transfer-Encoding: " + transfer)
    if transfer == "base64":
        wire_body = base64.b64encode(body)
    elif transfer == "quoted-printable":
        wire_body = quopri.encodestring(body)
    else:
        wire_body = body
    return "\r\n".join(headers).encode("ascii") + b"\r\n\r\n" + wire_body


def archive_bytes(parts):
    boundary = b"text-encoding-test"
    return (
        b'MIME-Version: 1.0\r\nContent-Type: multipart/related; boundary="'
        + boundary + b'"\r\n\r\n'
        + b"".join(b"--" + boundary + b"\r\n" + item + b"\r\n" for item in parts)
        + b"--" + boundary + b"--\r\n"
    )


class TextEncodingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mhtml-text-encoding-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.next_case = 0

    def source(self, parts):
        self.next_case += 1
        source = self.root / ("case-" + str(self.next_case) + ".mhtml")
        source.write_bytes(archive_bytes(parts))
        return source

    def extract(self, parts, *, html_only=False, no_css=False):
        source = self.source(parts)
        output = self.root / ("out-" + str(self.next_case))
        extractor = MHTMLExtractor(source, output_dir=output, create_in_memory_output=True)
        stats = extractor.extract(html_only=html_only, no_css=no_css)
        return source, output, extractor, stats

    def only_saved(self, output):
        files = list(output.iterdir())
        self.assertEqual(len(files), 1)
        return files[0].read_bytes()

    def assert_utf8_html(self, saved, text):
        decoded = saved.decode("utf-8", errors="strict")
        self.assertIn(text, decoded)
        self.assertNotIn("\ufffd", decoded)
        declaration = re.search(
            rb"<meta\b[^>]*charset\s*=\s*['\"]?utf-8[^>]*>", saved.lower()
        )
        self.assertIsNotNone(declaration)
        self.assertLessEqual(declaration.end(), 1024)
        return decoded

    def assert_utf8_css(self, saved, text):
        decoded = saved.decode("utf-8", errors="strict")
        self.assertIn(text, decoded)
        self.assertNotIn("\ufffd", decoded)
        self.assertTrue(decoded.lower().startswith('@charset "utf-8";'), decoded[:80])
        return decoded

    def test_cp1252_html_transfer_encodings_are_normalized_only_on_disk(self):
        body = b'<html><head><meta charset="windows-1252"></head><body>Caf\xe9 \x80</body></html>'
        for transfer in ("base64", "quoted-printable", "8bit", "binary"):
            with self.subTest(transfer=transfer):
                source, output, extractor, stats = self.extract(
                    [part("text/html; charset=windows-1252", body, transfer)]
                )
                parsed = parse_mhtml(source)
                self.assertEqual([item.content for item in parsed.parts], [body])
                filename = parsed.parts[0].filename
                self.assertEqual(extractor.extracted_contents[filename]["decoded_body"], body)
                saved = (output / filename).read_bytes()
                decoded = self.assert_utf8_html(saved, "Caf\u00e9 \u20ac")
                self.assertNotIn("windows-1252", decoded.lower())
                self.assertEqual((stats.written_files, stats.failed_files), (1, 0))

    def test_cp1252_css_quoted_printable_and_inband_only(self):
        body = b'@charset "windows-1252"; .x::after{content:"\xe9 \x80"}'
        for content_type in ("text/css; charset=windows-1252", "text/css"):
            with self.subTest(content_type=content_type):
                _, output, _, stats = self.extract(
                    [part(content_type, body, "quoted-printable", CSS_URL)]
                )
                decoded = self.assert_utf8_css(self.only_saved(output), 'content:"\u00e9 \u20ac"')
                self.assertNotIn("windows-1252", decoded.lower())
                self.assertEqual((stats.written_files, stats.failed_files), (1, 0))

    def test_cp1252_undefined_control_bytes_keep_their_unicode_scalars(self):
        body = b'<meta charset="windows-1252"><p>\x80\x81\x8d\x8f\x90\x9d\xe9</p>'
        _, output, _, stats = self.extract([part("text/html; charset=windows-1252", body)])
        decoded = self.assert_utf8_html(self.only_saved(output),
                                        "\u20ac\u0081\u008d\u008f\u0090\u009d\u00e9")
        self.assertIn(b"\xe2\x82\xac\xc2\x81\xc2\x8d\xc2\x8f\xc2\x90\xc2\x9d\xc3\xa9",
                      decoded.encode("utf-8"))
        self.assertEqual(stats.failed_files, 0)

    def test_mime_charset_quoted_whitespace_case_and_folding(self):
        body = b'<meta charset="windows-1252"><p>\x80</p>'
        content_types = (
            'text/html; ChArSeT = "  WiNdOwS-1252  "',
            'text/html;\r\n\tcharset="windows-1252"',
            'text/html; charset = "windows-1252"',
        )
        for content_type in content_types:
            with self.subTest(content_type=content_type):
                _, output, _, stats = self.extract([part(content_type, body)])
                self.assert_utf8_html(self.only_saved(output), "\u20ac")
                self.assertEqual(stats.failed_files, 0)

    def test_inband_html_and_default_text_without_transfer_header(self):
        body = b'<html><head><meta charset="windows-1252"></head><body>\x80</body></html>'
        source, output, extractor, stats = self.extract([part("text/html", body)])
        self.assertEqual(parse_mhtml(source).parts[0].content, body)
        self.assert_utf8_html(self.only_saved(output), "\u20ac")
        self.assertEqual(stats.failed_files, 0)

        bare = b"<p>Caf\xe9 \x80</p>"
        source, output, extractor, stats = self.extract(
            [part("text/html; charset=windows-1252", bare, None)]
        )
        self.assertEqual(parse_mhtml(source).parts[0].content, bare.decode("latin-1"))
        self.assertEqual(next(iter(extractor.extracted_contents.values()))["decoded_body"],
                         bare.decode("latin-1"))
        decoded = self.assert_utf8_html(self.only_saved(output), "Caf\u00e9 \u20ac")
        self.assertNotIn("\x80", decoded)
        self.assertEqual(stats.failed_files, 0)

    def test_all_selected_web_aliases_and_rejected_python_names(self):
        for label in CP1252_ALIASES:
            with self.subTest(label=label):
                body = b'<html><head><meta charset="' + label.encode() + b'"></head><body>\x80</body></html>'
                _, output, _, stats = self.extract([part("text/html; charset=" + label, body)])
                self.assert_utf8_html(self.only_saved(output), "\u20ac")
                self.assertEqual(stats.failed_files, 0)
        for label in UTF8_ALIASES:
            with self.subTest(label=label):
                body = b'<html><head><meta charset="' + label.encode() + b'"></head><body>\xc3\xa9</body></html>'
                _, output, _, stats = self.extract([part("text/html; charset=" + label, body)])
                self.assert_utf8_html(self.only_saved(output), "\u00e9")
                self.assertEqual(stats.failed_files, 0)
        for label in ("x-unknown", "utf_8", "utf-8-sig", "cp65001", "latin-1",
                      "utf-16", "utf-16le", "utf-16be", ""):
            with self.subTest(rejected=label):
                body = b"<p>ASCII source</p>"
                _, output, _, stats = self.extract([part("text/html; charset=" + label, body)])
                self.assertEqual(self.only_saved(output), body)
                self.assertEqual((stats.written_files, stats.failed_files), (1, 1))

    def test_bom_overrides_conflicting_mime_and_both_utf16_byte_orders(self):
        for codec, bom in (("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff")):
            with self.subTest(codec=codec):
                body = bom + '<html><head><meta charset="windows-1252"></head><body>\u20ac</body></html>'.encode(codec)
                source, output, extractor, stats = self.extract(
                    [part("text/html; charset=windows-1252", body)]
                )
                self.assertEqual(parse_mhtml(source).parts[0].content, body)
                self.assertEqual(next(iter(extractor.extracted_contents.values()))["decoded_body"], body)
                saved = self.only_saved(output)
                self.assertFalse(saved.startswith(bom))
                self.assertNotIn(b"\x00", saved)
                self.assert_utf8_html(saved, "\u20ac")
                self.assertEqual(stats.failed_files, 0)
        body = b"\xef\xbb\xbf" + '<html><head><meta charset="windows-1252"></head><body>\u20ac</body></html>'.encode("utf-8")
        _, output, _, stats = self.extract([part("text/html; charset=windows-1252", body)])
        self.assert_utf8_html(self.only_saved(output), "\u20ac")
        self.assertEqual(stats.failed_files, 0)

    def test_bom_overrides_invalid_mime_but_invalid_bom_text_falls_back(self):
        for codec, bom in (("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff")):
            for label in ("x-unknown", ""):
                with self.subTest(codec=codec, label=label):
                    body = bom + '<meta charset="x-unknown"><p>\u20ac</p>'.encode(codec)
                    _, output, _, stats = self.extract([
                        part("text/html; charset=" + label, body)
                    ])
                    self.assert_utf8_html(self.only_saved(output), "\u20ac")
                    self.assertEqual(stats.failed_files, 0)
        malformed = (
            b"\xff\xfe<\x00p\x00>\x00\xff",  # truncated UTF-16LE code unit
            b"\xfe\xff\x00<\x00p\xd8\x00",  # unmatched UTF-16BE surrogate
            b"\xef\xbb\xbf<p>\xe2\x82",    # truncated UTF-8 with a valid BOM
            b"<p>\xe2\x82",                    # truncated undeclared UTF-8
        )
        for body in malformed:
            with self.subTest(malformed=body[:8]):
                _, output, _, stats = self.extract([part("text/html", body)])
                self.assertEqual(self.only_saved(output), body)
                self.assertEqual((stats.written_files, stats.failed_files), (1, 1))

    def test_mime_overrides_inband_and_undeclared_uses_strict_utf8(self):
        body = '<html><head><meta charset="windows-1252"></head><body>Caf\u00e9</body></html>'.encode("utf-8")
        _, output, _, stats = self.extract([part("text/html; charset=utf-8", body)])
        decoded = self.assert_utf8_html(self.only_saved(output), "Caf\u00e9")
        self.assertNotIn("windows-1252", decoded.lower())
        self.assertEqual(stats.failed_files, 0)
        undecorated = "<p>Caf\u00e9</p>".encode("utf-8")
        _, output, _, stats = self.extract([part("text/html", undecorated)])
        self.assert_utf8_html(self.only_saved(output), "Caf\u00e9")
        self.assertEqual(stats.failed_files, 0)

    def test_failed_text_keeps_raw_bytes_and_never_localizes_links(self):
        cases = (
            ("text/html; charset=x-unknown", b'<meta charset="x-unknown"><p>ASCII</p>' + CSS_LINK.encode()),
            ("text/html; charset=utf-8", b'<meta charset="utf-8"><p>\xe9</p>' + CSS_LINK.encode()),
            ("text/html", b"<p>\xe9</p>" + CSS_LINK.encode()),
        )
        for content_type, body in cases:
            with self.subTest(content_type=content_type, body=body):
                source, output, extractor, stats = self.extract([
                    part(content_type, body), part("text/css", b"body{}", location=CSS_URL)
                ])
                filename = parse_mhtml(source).parts[0].filename
                self.assertEqual((output / filename).read_bytes(), body)
                self.assertEqual(extractor.extracted_contents[filename]["decoded_body"], body)
                self.assertEqual((stats.written_files, stats.failed_files,
                                  stats.rewrite_failures), (2, 1, 0))

    def test_instance_link_update_keeps_known_unsafe_ascii_html_intact(self):
        unsafe = b'<meta charset="x-unknown"><p>ASCII</p>' + CSS_LINK.encode()
        source, output, extractor, stats = self.extract([
            part("text/html; charset=x-unknown", unsafe),
            part("text/css", b"body{}", location=CSS_URL),
        ])
        filename = parse_mhtml(source).parts[0].filename
        html_path = output / filename
        self.assertEqual(html_path.read_bytes(), unsafe)
        extractor._update_html_links(html_path, [CSS_URL])
        self.assertEqual(html_path.read_bytes(), unsafe)
        self.assertEqual((stats.written_files, stats.failed_files,
                          stats.rewrite_failures), (2, 1, 0))

    def test_invalid_mime_cannot_fall_through_to_valid_meta_or_utf8(self):
        for charset in ("x-unknown", ""):
            with self.subTest(charset=charset):
                body = b'<meta charset="utf-8"><p>ASCII</p>'
                _, output, _, stats = self.extract(
                    [part("text/html; charset=" + charset, body)]
                )
                self.assertEqual(self.only_saved(output), body)
                self.assertEqual(stats.failed_files, 1)

        css = b'@charset "utf-8"; .x{color:red}'
        _, output, _, stats = self.extract([
            part("text/css; charset=x-unknown", css, location=CSS_URL)
        ])
        self.assertEqual(self.only_saved(output), css)
        self.assertEqual(stats.failed_files, 1)

    def test_css_does_not_inherit_html_charset(self):
        html = b'<meta charset="windows-1252"><p>\x80</p>'
        css = b'.x{content:"\xe9"}'
        source, output, _, stats = self.extract([
            part("text/html; charset=windows-1252", html),
            part("text/css", css, location=CSS_URL),
        ])
        html_name, css_name = [item.filename for item in parse_mhtml(source).parts]
        self.assert_utf8_html((output / html_name).read_bytes(), "\u20ac")
        self.assertEqual((output / css_name).read_bytes(), css)
        self.assertEqual((stats.written_files, stats.failed_files), (2, 1))

    def test_direct_link_rewrite_rejects_invalid_utf8_without_mutating_file(self):
        html = b'<p>\xe9</p>' + CSS_LINK.encode("ascii")
        target = self.root / "direct-link.html"
        target.write_bytes(html)
        with self.assertRaises(UnicodeDecodeError):
            update_html_links(target, [CSS_URL], {CSS_URL: "site.css"})
        self.assertEqual(target.read_bytes(), html)

    def test_html_meta_lookalikes_do_not_preempt_real_declaration(self):
        decoy = (b'<!-- <meta charset="utf-8"> -->'
                 b'<script>"<meta charset=\\"utf-8\\">"</script>'
                 b'<style>/* <meta charset="utf-8"> */</style>'
                 b'<title><meta charset="utf-8"></title>'
                 b'<textarea><meta charset="utf-8"></textarea>'
                 b'<div data-example="<meta charset=\'utf-8\'>"></div>')
        body = b'<html><head>' + decoy + b'<meta charset="windows-1252"></head><body>\x80</body></html>'
        _, output, _, stats = self.extract([part("text/html", body)])
        decoded = self.assert_utf8_html(self.only_saved(output), "\u20ac")
        self.assertIn(decoy.decode("ascii"), decoded)
        self.assertEqual(stats.failed_files, 0)

    def test_html_meta_forms_and_reversed_http_equiv_are_repaired(self):
        bodies = (
            b'<html><head><meta charset=windows-1252></head><body>\x80</body></html>',
            b"<html><head><meta charset='windows-1252'></head><body>\x80</body></html>",
            b'<HTML><HEAD><META CHARSET="WINDOWS-1252"></HEAD><BODY>\x80</BODY></HTML>',
            b'<html><head><meta content="text/html; charset=windows-1252" '
            b'http-equiv="Content-Type"></head><body>\x80</body></html>',
        )
        for body in bodies:
            with self.subTest(body=body[:70]):
                _, output, _, stats = self.extract([part("text/html", body)])
                decoded = self.assert_utf8_html(self.only_saved(output), "\u20ac")
                self.assertNotIn("windows-1252", decoded.lower())
                self.assertEqual(stats.failed_files, 0)

    def test_all_conflicting_declarations_are_repaired(self):
        body = ('<html><head><meta charset="windows-1252">'
                '<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">'
                '<meta charset=utf8></head><body>\u20ac</body></html>').encode("utf-8")
        _, output, _, stats = self.extract([part("text/html; charset=utf-8", body)])
        decoded = self.assert_utf8_html(self.only_saved(output), "\u20ac")
        self.assertNotIn("windows-1252", decoded.lower())
        self.assertNotIn("iso-8859-1", decoded.lower())
        self.assertGreaterEqual(decoded.lower().count("utf-8"), 3)
        self.assertEqual(stats.failed_files, 0)

    def test_expanded_text_keeps_entire_meta_declaration_within_first_1024_bytes(self):
        # Each CP1252 euro expands from one byte to three before the original meta.
        body = (b'<html><head>' + b"\x80" * 335 +
                b'<meta charset="windows-1252"></head><body>tail</body></html>')
        _, output, _, stats = self.extract([
            part("text/html; charset=windows-1252", body)
        ])
        decoded = self.assert_utf8_html(self.only_saved(output), "\u20ac" * 335)
        self.assertNotIn("windows-1252", decoded.lower())
        self.assertEqual(stats.failed_files, 0)

    def test_tag_like_text_in_raw_and_rcdata_contexts_is_never_repaired(self):
        snippets = (
            '<script/><meta charset="windows-1252"></script>',
            '<style/><meta charset="windows-1252"></style>',
            '<title/><meta charset="windows-1252"></title>',
            '<textarea/><meta charset="windows-1252"></textarea>',
            '<title><b><meta charset="windows-1252"></b></title>',
        )
        for snippet in snippets:
            with self.subTest(snippet=snippet):
                html = '<html><head>' + snippet + '</head><body>\u20ac</body></html>'
                _, output, _, stats = self.extract([
                    part("text/html; charset=utf-8", html.encode("utf-8"))
                ])
                decoded = self.assert_utf8_html(self.only_saved(output), "\u20ac")
                self.assertIn(snippet, decoded)
                self.assertEqual(decoded.count('charset="windows-1252"'), 1)
                self.assertEqual(stats.failed_files, 0)

    def test_vertical_tab_and_nbsp_inside_attribute_are_not_meta_delimiters(self):
        for separator in (b"\x0b", b"\xa0"):
            with self.subTest(separator=separator):
                body = b'<meta data-note=foo' + separator + b'charset=windows-1252><p>\x80</p>'
                _, output, _, stats = self.extract([part("text/html", body)])
                self.assertEqual(self.only_saved(output), body)
                self.assertEqual((stats.written_files, stats.failed_files), (1, 1))

                _, output, _, stats = self.extract([
                    part("text/html; charset=windows-1252", body)
                ])
                decoded = self.assert_utf8_html(self.only_saved(output), "\u20ac")
                self.assertIn('<meta data-note=foo' + separator.decode("windows-1252") +
                              'charset=windows-1252>', decoded)
                self.assertEqual(stats.failed_files, 0)

    def test_escaped_legacy_charset_repairs_only_value_and_keeps_parameters(self):
        body = (b'<html><head><meta http-equiv="Content-Type" '
                b'content="text/html; foo=bar; charset=&quot;windows-1252&quot;; baz=qux">'
                b'</head><body>\x80</body></html>')
        _, output, _, stats = self.extract([part("text/html", body)])
        decoded = self.only_saved(output).decode("utf-8", errors="strict")
        self.assertIn("\u20ac", decoded)
        self.assertIn("foo=bar", decoded)
        self.assertIn("baz=qux", decoded)
        self.assertRegex(decoded.lower(),
                         r'charset=&quot;utf-8&quot;; baz=qux')
        self.assertNotIn("windows-1252", decoded.lower())
        self.assertEqual(stats.failed_files, 0)

    def test_oversized_doctype_fails_closed_and_skips_link_rewrite(self):
        doctype = b"<!DOCTYPE html " + b" " * 1010 + b">"
        body = doctype + b"<html><body>ASCII" + CSS_LINK.encode() + b"</body></html>"
        source, output, _, stats = self.extract([
            part("text/html; charset=utf-8", body),
            part("text/css", b"body{}", location=CSS_URL),
        ])
        filename = parse_mhtml(source).parts[0].filename
        self.assertEqual((output / filename).read_bytes(), body)
        self.assertEqual((stats.written_files, stats.failed_files,
                          stats.rewrite_failures), (2, 1, 0))

    def test_bare_and_empty_meta_charset_attributes_become_real_utf8_values(self):
        for marker in ("<meta CHARSET>", '<meta charset="">', "<meta charset=>"):
            with self.subTest(marker=marker):
                body = ('<html><head>' + marker + '</head><body>\u20ac</body></html>').encode("utf-8")
                _, output, _, stats = self.extract([part("text/html; charset=utf-8", body)])
                decoded = self.assert_utf8_html(self.only_saved(output), "\u20ac")
                self.assertRegex(decoded.lower(), r'<meta\s+charset\s*=\s*[\'\"]?utf-8')
                self.assertNotIn("charsetutf-8", decoded.lower())
                self.assertEqual(stats.failed_files, 0)

    def test_html_http_equiv_missing_head_and_late_meta_are_repaired_early(self):
        http_equiv = (b'<html><head><meta http-equiv="Content-Type" '
                      b'content="text/html; charset=windows-1252"></head><body>\x80</body></html>')
        missing_head = b'<!DOCTYPE html><html><body>\x80</body></html>'
        late_meta = (b'<html><head>' + b" " * 1100 +
                     b'<meta charset="windows-1252"></head><body>\x80</body></html>')
        for name, body in (("http-equiv", http_equiv), ("missing-head", missing_head),
                           ("late-meta", late_meta)):
            with self.subTest(name=name):
                content_type = "text/html" if name == "http-equiv" else "text/html; charset=windows-1252"
                _, output, _, stats = self.extract([part(content_type, body)])
                saved = self.only_saved(output)
                decoded = self.assert_utf8_html(saved, "\u20ac")
                self.assertNotIn("windows-1252", decoded.lower())
                if name == "missing-head":
                    self.assertTrue(saved.startswith(b"<!DOCTYPE html>"))
                self.assertEqual(stats.failed_files, 0)

    def test_css_declaration_requires_exact_leading_double_quoted_syntax(self):
        valid = b'@charset "windows-1252"; .x{content:"\x80"}'
        single_quoted = b"@charset 'windows-1252'; .x{content:'\x80'}"
        late = b"/*" + b"x" * 1100 + b"*/@charset \"windows-1252\";.x{content:'\x80'}"
        _, output, _, stats = self.extract([part("text/css", valid, location=CSS_URL)])
        self.assert_utf8_css(self.only_saved(output), 'content:"\u20ac"')
        self.assertEqual(stats.failed_files, 0)
        for body in (single_quoted, late):
            with self.subTest(body=body[:24]):
                _, output, _, stats = self.extract([part("text/css", body, location=CSS_URL)])
                self.assertEqual(self.only_saved(output), body)
                self.assertEqual(stats.failed_files, 1)

    def test_non_target_parts_keep_high_bytes_and_ascii_7bit_stays_readable(self):
        for content_type, location in (
            ("application/xhtml+xml", "https://example.test/a.xhtml"),
            ("text/xml", "https://example.test/a.xml"),
            ("application/javascript", "https://example.test/a.js"),
            ("text/plain", "https://example.test/a.txt"),
            ("application/octet-stream", "https://example.test/a.bin"),
        ):
            with self.subTest(content_type=content_type):
                body = b"\x00\x80\xe9\xff"
                _, output, _, stats = self.extract([part(content_type, body, "binary", location)])
                self.assertEqual(self.only_saved(output), body)
                self.assertEqual(stats.failed_files, 0)
        body = b"<p>ASCII only</p>"
        _, output, _, stats = self.extract([part("text/html; charset=us-ascii", body, "7bit")])
        self.assert_utf8_html(self.only_saved(output), "ASCII only")
        self.assertEqual(stats.failed_files, 0)

    def test_malformed_high_bytes_on_non_target_default_and_7bit_keep_octets(self):
        # High bytes violate 7bit MIME; this still checks the disk preservation boundary.
        body = b"\x00\x80\xe9\xff"
        for transfer in (None, "7bit"):
            with self.subTest(transfer=transfer):
                source, output, extractor, stats = self.extract([
                    part("application/octet-stream", body, transfer,
                         "https://example.test/a.bin")
                ])
                self.assertEqual(parse_mhtml(source).parts[0].content,
                                 body.decode("latin-1"))
                self.assertEqual(next(iter(extractor.extracted_contents.values()))["decoded_body"],
                                 body.decode("latin-1"))
                self.assertEqual(self.only_saved(output), body)
                self.assertEqual((stats.written_files, stats.failed_files), (1, 0))

    def test_dry_run_and_memory_only_leave_original_content_and_no_output(self):
        body = b'<meta charset="windows-1252"><p>\xe9 \x80</p>'
        source = self.source([part("text/html; charset=windows-1252", body)])
        for mode in ("dry", "memory"):
            with self.subTest(mode=mode):
                output = self.root / ("no-output-" + mode)
                extractor = MHTMLExtractor(
                    source, output_dir=output, dry_run=(mode == "dry"),
                    create_in_memory_output=True, create_output_files=(mode == "dry"),
                )
                stats = extractor.extract()
                self.assertFalse(output.exists())
                self.assertEqual(next(iter(extractor.extracted_contents.values()))["decoded_body"], body)
                self.assertEqual((stats.written_files, stats.failed_files), (0, 0))
        for parser in (parse_mhtml, legacy_parse_mhtml):
            self.assertEqual(parser(source).parts[0].content, body)

    def test_html_only_and_no_css_still_normalize_selected_html(self):
        html = b'<meta charset="windows-1252"><p>\x80</p>'
        css = b'@charset "windows-1252";.x{content:"\x80"}'
        parts = [part("text/html; charset=windows-1252", html),
                 part("text/css; charset=windows-1252", css, location=CSS_URL)]
        for option in ("html_only", "no_css"):
            with self.subTest(option=option):
                _, output, _, stats = self.extract(parts, **{option: True})
                self.assert_utf8_html(self.only_saved(output), "\u20ac")
                self.assertEqual((stats.written_files, stats.filtered_files, stats.failed_files),
                                 (1, 1, 0))

    def test_duplicate_fallback_does_not_block_later_successful_parts(self):
        unsafe = b'<meta charset="x-unknown"><p>ASCII</p>' + CSS_LINK.encode()
        safe = b'<meta charset="utf-8"><p>SECOND</p>' + CSS_LINK.encode()
        source, output, _, stats = self.extract([
            part("text/html; charset=x-unknown", unsafe),
            part("text/html; charset=utf-8", safe),
            part("text/css", b"body{}", location=CSS_URL),
        ])
        parsed = parse_mhtml(source)
        first, second, stylesheet = [item.filename for item in parsed.parts]
        self.assertNotEqual(first, second)
        self.assertEqual((output / first).read_bytes(), unsafe)
        rewritten = (output / second).read_bytes().decode("utf-8")
        self.assertIn(stylesheet, rewritten)
        self.assertNotIn(CSS_URL, rewritten)
        self.assertEqual((stats.written_files, stats.failed_files, stats.rewrite_failures),
                         (3, 1, 0))

    def test_normalization_failure_plus_write_fault_is_counted_once(self):
        body = b'<meta charset="x-unknown"><p>ASCII</p>'
        source = self.source([part("text/html; charset=x-unknown", body)])
        extractor = MHTMLExtractor(source, output_dir=self.root / "fault-output")
        with patch.object(extractor, "_write_to_file", side_effect=OSError("injected write failure")):
            stats = extractor.extract()
        self.assertEqual((stats.written_files, stats.failed_files), (0, 1))
        self.assertEqual(list(extractor.output_dir.iterdir()), [])

    def test_quiet_cli_exits_nonzero_and_reports_text_failure(self):
        source = self.source([part("text/html; charset=x-unknown", b"<p>ASCII</p>")])
        output = self.root / "cli-output"
        command = [sys.executable, "-B", str(REPO / "MHTMLExtractor.py"),
                   str(source), "--output_dir", str(output), "--quiet"]
        completed = subprocess.run(command, cwd=str(REPO), capture_output=True,
                                   text=True, check=False)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("failed", completed.stderr.lower())
        self.assertEqual(completed.stdout, "")
        self.assertEqual(self.only_saved(output), b"<p>ASCII</p>")

    def test_ascii_without_transfer_keeps_parse_and_memory_str_and_cli_succeeds(self):
        body = b"<p>ASCII only</p>"
        source, output, extractor, stats = self.extract([part("text/html", body, None)])
        filename = parse_mhtml(source).parts[0].filename
        self.assertEqual(parse_mhtml(source).parts[0].content, body.decode("ascii"))
        self.assertEqual(extractor.extracted_contents[filename]["decoded_body"],
                         body.decode("ascii"))
        self.assert_utf8_html((output / filename).read_bytes(), "ASCII only")
        self.assertEqual((stats.written_files, stats.failed_files), (1, 0))

        cli_output = self.root / "cli-good-output"
        command = [sys.executable, "-B", str(REPO / "MHTMLExtractor.py"),
                   str(source), "--output_dir", str(cli_output), "--quiet"]
        completed = subprocess.run(command, cwd=str(REPO), capture_output=True,
                                   text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assert_utf8_html(self.only_saved(cli_output), "ASCII only")


if __name__ == "__main__":
    unittest.main()
