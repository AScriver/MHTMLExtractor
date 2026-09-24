"""End-to-end contracts for portable static references in extracted files."""

import base64
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, unquote

from mhtmlextractor import MHTMLExtractor, parse_mhtml


ORIGIN = "https://example.test"


def part(content_type, body, location=None, content_id=None):
    """Build one MIME part from explicit source bytes."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    headers = ["Content-Type: " + content_type, "Content-Transfer-Encoding: base64"]
    if location is not None:
        headers.append("Content-Location: " + location)
    if content_id is not None:
        headers.append("Content-ID: <" + content_id + ">")
    return "\r\n".join(headers).encode("latin-1") + b"\r\n\r\n" + base64.b64encode(body)


class FaultingRewriteTemp:
    def __init__(self, raw, stage):
        self.raw = raw
        self.stage = stage
        self.name = raw.name

    def __enter__(self):
        self.raw.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        result = self.raw.__exit__(exc_type, exc_value, traceback)
        if self.stage == "close":
            raise OSError("injected CSS rewrite close failure")
        return result

    def write(self, data):
        if self.stage == "write":
            self.raw.write(data[:7])
            raise OSError("injected CSS rewrite write failure")
        return self.raw.write(data)


class StaticReferenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mhtml-static-refs-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.case_number = 0

    def archive(self, parts, outer_location=None):
        self.case_number += 1
        source = self.root / ("case-" + str(self.case_number) + ".mhtml")
        headers = [b"MIME-Version: 1.0", b'Content-Type: multipart/related; boundary="static-reference-test"']
        if outer_location is not None:
            headers.append(b"Content-Location: " + outer_location.encode("ascii"))
        source.write_bytes(
            b"\r\n".join(headers) + b"\r\n\r\n"
            + b"".join(b"--static-reference-test\r\n" + item + b"\r\n" for item in parts)
            + b"--static-reference-test--\r\n"
        )
        return source

    def extract(self, parts, outer_location=None, memory=False, **options):
        source = self.archive(parts, outer_location)
        output = self.root / ("output-" + str(self.case_number))
        extractor = MHTMLExtractor(source, output_dir=output, create_in_memory_output=memory)
        stats = extractor.extract(**options)
        return source, output, extractor, stats

    def saved(self, output, suffix):
        matches = list(output.glob("*" + suffix))
        self.assertEqual(len(matches), 1, matches)
        return matches[0].read_text(encoding="utf-8")

    def test_html_rewrites_only_supported_tokens(self):
        image = ORIGIN + "/assets/pic.png"
        html = (
            '<img src="' + image + '"><video poster="' + image + '"></video>'
            '<object data="' + image + '"></object>'
            '<a href="' + image + '">link</a>'
            '<div style="background:url(' + image + ')"></div>'
            '<style>.x{background:url(' + image + ');content:"' + image + '"}</style>'
            '<p>' + image + '</p><!-- ' + image + ' -->'
            '<script>const url="' + image + '";</script>'
        )
        _, output, extractor, stats = self.extract([
            part("text/html; charset=utf-8", html, ORIGIN + "/index.html"),
            part("image/png", b"PNG", image),
        ])
        target = quote(extractor.url_mapping[image], safe="")
        saved = self.saved(output, ".html")
        for fragment in (
            '<img src="' + target + '">', '<video poster="' + target + '">',
            '<object data="' + target + '">', '<a href="' + target + '">',
            'background:url(' + target + ')',
        ):
            self.assertIn(fragment, saved)
        for fragment in (
            'content:"' + image + '"', '<p>' + image + '</p>',
            '<!-- ' + image + ' -->', '<script>const url="' + image + '";</script>',
        ):
            self.assertIn(fragment, saved)
        self.assertEqual((stats.written_files, stats.rewrite_failures), (2, 0))

    def test_query_entities_fragments_cid_and_token_boundaries(self):
        query = ORIGIN + "/a.png?one=1&two=2"
        longer = ORIGIN + "/a.png?one=1&two=20"
        values = [
            query, query.replace("&", "&amp;"), query.replace("&", "&#38;"),
            query.replace("&", "&#x26;"), query + "#section",
            ORIGIN + "/a.png?one=1&two=3", query + "x", longer,
            "cid:logo@id", "cid:logo%40id",
        ]
        html = "".join('<img id="' + str(i) + '" src="' + value + '">' for i, value in enumerate(values))
        _, output, extractor, _ = self.extract([
            part("text/html; charset=utf-8", html, ORIGIN + "/index.html"),
            part("image/png", b"FIRST", query),
            part("image/png", b"SECOND", longer),
            part("image/png", b"CID", ORIGIN + "/logo.png", "logo@id"),
        ])
        saved = self.saved(output, ".html")
        expected = [
            extractor.url_mapping[query], extractor.url_mapping[query],
            extractor.url_mapping[query], extractor.url_mapping[query],
            extractor.url_mapping[query] + "#section",
            values[5], values[6], extractor.url_mapping[longer],
            extractor.url_mapping["cid:logo@id"], extractor.url_mapping["cid:logo@id"],
        ]
        for i, value in enumerate(expected):
            self.assertIn('id="' + str(i) + '" src="' + value + '"', saved)
        self.assertNotEqual(extractor.url_mapping[query], extractor.url_mapping[longer])

    def test_relative_paths_and_percent_encoded_slash_have_distinct_targets(self):
        page = ORIGIN + "/pages/index.html"
        encoded = ORIGIN + "/pages/a%2Fb.png"
        slash = ORIGIN + "/pages/a/b.png"
        spaced = ORIGIN + "/pages/a%20b.png"
        html = (
            '<img src="a%2Fb.png"><img src="a/b.png">'
            '<img src="a%20b.png"><img src="//example.test/pages/a%2Fb.png">'
            '<img src="/pages/a/b.png"><img src="./a%20b.png">'
        )
        _, output, extractor, _ = self.extract([
            part("text/html; charset=utf-8", html, page),
            part("image/png", b"ENCODED", encoded),
            part("image/png", b"SLASH", slash),
            part("image/png", b"SPACE", spaced),
        ])
        saved = self.saved(output, ".html")
        for original, count in ((encoded, 2), (slash, 2), (spaced, 2)):
            self.assertEqual(saved.count('src="' + quote(extractor.url_mapping[original], safe="") + '"'), count)
        self.assertNotEqual(extractor.url_mapping[encoded], extractor.url_mapping[slash])

    def test_relative_double_slash_path_keeps_its_distinct_captured_identity(self):
        page = ORIGIN + "/pages/index.html"
        doubled = ORIGIN + "/pages/a//b.png"
        single = ORIGIN + "/pages/a/b.png"
        html = '<meta charset="utf-8"><img src="a//b.png"><img src="a/b.png">'
        _, output, extractor, _ = self.extract([
            part("text/html; charset=utf-8", html, page),
            part("image/png", b"DOUBLE", doubled),
            part("image/png", b"SINGLE", single),
        ])
        saved = self.saved(output, ".html")
        doubled_name = extractor.url_mapping[doubled]
        single_name = extractor.url_mapping[single]
        self.assertNotEqual(doubled_name, single_name)
        self.assertEqual(
            saved,
            '<meta charset="utf-8"><img src="' + doubled_name
            + '"><img src="' + single_name + '">',
        )

    def test_unquoted_attribute_and_entity_encoded_style_url(self):
        image = ORIGIN + "/a.png?one=1&two=2"
        html = (
            "<img src=" + image + ">"
            '<div style="background:url(&quot;' + image.replace("&", "&amp;") + '&quot;)"></div>'
        )
        _, output, extractor, _ = self.extract([
            part("text/html; charset=utf-8", html, ORIGIN + "/index.html"),
            part("image/png", b"PNG", image),
        ])
        saved = self.saved(output, ".html")
        target = quote(extractor.url_mapping[image], safe="")
        self.assertIn("<img src=" + target + ">", saved)
        self.assertIn("background:url(&quot;" + target + "&quot;)", saved)

    def test_semicolonless_named_charref_before_equals_uses_raw_url_identity(self):
        raw = ORIGIN + "/a.png?mark=&copy=2"
        decoded_other = ORIGIN + "/a.png?mark=©=2"
        html = '<meta charset="utf-8"><img src="' + raw + '">'
        _, output, extractor, _ = self.extract([
            part("text/html; charset=utf-8", html, ORIGIN + "/index.html"),
            part("image/png", b"RAW", raw),
            part("image/png", b"DECODED", decoded_other),
        ])
        self.assertNotEqual(extractor.url_mapping[raw], extractor.url_mapping[decoded_other])
        self.assertEqual(
            self.saved(output, ".html"),
            '<meta charset="utf-8"><img src="' + extractor.url_mapping[raw] + '">',
        )

    def test_first_base_controls_refs_and_all_base_hrefs_are_neutralized(self):
        page = ORIGIN + "/pages/index.html"
        image = ORIGIN + "/assets/pic.png"
        html = (
            '<base href="' + ORIGIN + '/assets/" target="_blank">'
            '<img id="before" src="pic.png">'
            '<base href="https://wrong.test/">'
            '<img id="after" src="pic.png">'
            '<img id="missing" src="missing.png">'
            '<a href="#local">fragment</a>'
        )
        _, output, extractor, _ = self.extract([
            part("text/html; charset=utf-8", html, page), part("image/png", b"PNG", image)
        ])
        saved = self.saved(output, ".html")
        target = quote(extractor.url_mapping[image], safe="")
        self.assertIn('id="before" src="' + target + '"', saved)
        self.assertIn('id="after" src="' + target + '"', saved)
        self.assertIn('id="missing" src="' + ORIGIN + '/assets/missing.png"', saved)
        self.assertIn('target="_blank"', saved)
        self.assertIn('href="#local"', saved)
        self.assertNotIn('<base href="' + ORIGIN + '/assets/"', saved)
        self.assertNotIn('<base href="https://wrong.test/"', saved)

    def test_unresolved_real_and_virtual_destinations_survive_flattening(self):
        cases = [
            ("pages/index.html", "assets/", "pages/assets/missing.png"),
            (None, "assets/", "assets/missing.png"),
            (ORIGIN + "/pages/index.html", ORIGIN + "/assets/", ORIGIN + "/assets/missing.png"),
        ]
        for location, base, destination in cases:
            with self.subTest(location=location):
                html = '<base href="' + base + '"><img src="missing.png">'
                _, output, _, _ = self.extract([part("text/html; charset=utf-8", html, location)])
                saved = self.saved(output, ".html")
                self.assertIn('src="' + destination + '"', saved)
                self.assertNotIn('<base href="' + base + '"', saved)
                self.assertNotIn("thismessage:", saved)

    def test_relative_part_locations_use_available_outer_mime_base(self):
        outer = ORIGIN + "/archive/root.mhtml"
        html = '<img src="../assets/pic.png">'
        _, output, extractor, _ = self.extract([
            part("text/html; charset=utf-8", html, "pages/index.html"),
            part("image/png", b"PNG", "assets/pic.png"),
        ], outer_location=outer)
        image_name = extractor.url_mapping["assets/pic.png"]
        self.assertIn('src="' + quote(image_name, safe="") + '"', self.saved(output, ".html"))

    def test_relative_outer_location_and_virtual_root_match_flat_part_locations(self):
        for outer in ("archive/root.mhtml", None):
            with self.subTest(outer=outer):
                _, output, extractor, _ = self.extract([
                    part("text/html; charset=utf-8", '<img src="../assets/pic.png">', "pages/index.html"),
                    part("image/png", b"PNG", "assets/pic.png"),
                ], outer_location=outer)
                image_name = extractor.url_mapping["assets/pic.png"]
                self.assertIn('src="' + quote(image_name, safe="") + '"', self.saved(output, ".html"))

    def test_external_css_uses_each_sheet_location_even_without_html(self):
        main = ORIGIN + "/css/main/site.css"
        theme = ORIGIN + "/css/shared/theme.css"
        image = ORIGIN + "/css/img/bg.png"
        deep = ORIGIN + "/css/shared/deep.png"
        main_body = (
            '@import url(../shared/theme.css);'
            '.x{background:url(../img/bg.png);content:"../img/bg.png"}'
            '/* ../img/bg.png */'
        )
        _, output, extractor, stats = self.extract([
            part("text/css; charset=utf-8", main_body, main),
            part("text/css; charset=utf-8", '.y{background:url(./deep.png)}', theme),
            part("image/png", b"BG", image), part("image/png", b"DEEP", deep),
        ])
        main_text = (output / extractor.url_mapping[main]).read_text("utf-8")
        theme_text = (output / extractor.url_mapping[theme]).read_text("utf-8")
        self.assertIn('@import url(' + extractor.url_mapping[theme] + ')', main_text)
        self.assertIn('background:url(' + extractor.url_mapping[image] + ')', main_text)
        self.assertIn('background:url(' + extractor.url_mapping[deep] + ')', theme_text)
        self.assertIn('content:"../img/bg.png"', main_text)
        self.assertIn('/* ../img/bg.png */', main_text)
        self.assertEqual((stats.written_files, stats.rewrite_failures), (4, 0))

    def test_css_quoted_imports_and_escapes_are_recognized_without_changing_strings(self):
        sheet = ORIGIN + "/css/site.css"
        image = ORIGIN + "/css/pic.png"
        theme = ORIGIN + "/css/theme.css"
        css = (
            '@import "theme.css";'
            '.a{background:u\\72l(pic.png)}'
            '.b{background:url("p\\69 c.png")}'
            '.c{content:"pic.png"}/* url(pic.png) */'
        )
        _, output, extractor, _ = self.extract([
            part("text/css; charset=utf-8", css, sheet),
            part("text/css; charset=utf-8", ".theme{}", theme),
            part("image/png", b"PNG", image),
        ])
        saved = (output / extractor.url_mapping[sheet]).read_text("utf-8")
        self.assertIn('"' + extractor.url_mapping[theme] + '"', saved)
        self.assertEqual(saved.count(extractor.url_mapping[image]), 2)
        self.assertIn('content:"pic.png"', saved)
        self.assertIn('/* url(pic.png) */', saved)

    def test_malformed_css_tokens_and_fragment_only_urls_remain_unchanged(self):
        image = ORIGIN + "/pic.png"
        css = (
            '.good{background:url(' + image + ')}'
            '.fragment{background:url(#local)}'
            '.data{background:url(data:image/png;base64,AAAA)}'
            '.broken{background:url("' + image + ')}'
            '/* url(' + image + ') */'
        )
        _, output, extractor, _ = self.extract([
            part("text/css; charset=utf-8", css, ORIGIN + "/site.css"),
            part("image/png", b"PNG", image),
        ])
        saved = self.saved(output, ".css")
        self.assertIn('.good{background:url(' + extractor.url_mapping[image] + ')}', saved)
        self.assertIn('.fragment{background:url(#local)}', saved)
        self.assertIn('.data{background:url(data:image/png;base64,AAAA)}', saved)
        self.assertIn('.broken{background:url("' + image + ')}', saved)
        self.assertIn('/* url(' + image + ') */', saved)

    def test_css_dimension_and_hash_tokens_are_not_url_functions(self):
        image = ORIGIN + "/pic.png"
        css = (
            '@charset "utf-8";'
            '.dimension{width:1url(' + image + ')}'
            '.hash{color:#url(' + image + ')}'
            '.real{background:url(' + image + ')}'
        )
        _, output, extractor, _ = self.extract([
            part("text/css; charset=utf-8", css, ORIGIN + "/site.css"),
            part("image/png", b"PNG", image),
        ])
        expected = css.replace(
            '.real{background:url(' + image + ')}',
            '.real{background:url(' + extractor.url_mapping[image] + ')}',
        )
        self.assertEqual(self.saved(output, ".css"), expected)

    def test_generated_filenames_are_url_escaped_after_output_relocation(self):
        page = ORIGIN + "/index.html"
        image = ORIGIN + "/a%20b%23c.png"
        _, output, extractor, _ = self.extract([
            part("text/html; charset=utf-8", '<img src="' + image + '">', page),
            part("image/png", b"PNG", image),
        ])
        name = extractor.url_mapping[image]
        self.assertTrue(any(character in name for character in " #%"), name)
        reference = quote(name, safe="")
        self.assertIn('src="' + reference + '"', self.saved(output, ".html"))
        moved = self.root / "relocated"
        shutil.copytree(output, moved)
        self.assertEqual((moved / unquote(reference)).read_bytes(), b"PNG")
        self.assertIn('src="' + reference + '"', self.saved(moved, ".html"))

    def test_unsupported_and_malformed_contexts_remain_unchanged(self):
        image = ORIGIN + "/pic.png"
        html = (
            '<form action="' + image + '"></form>'
            '<img srcset="' + image + ' 1x">'
            '<iframe srcdoc="&lt;img src=&quot;' + image + '&quot;&gt;"></iframe>'
            '<svg><image href="' + image + '"/></svg>'
            '<script/>var snippet="<img src=\\"' + image + '\\">";</script>'
            '<!-- <img src="' + image + '"> -->'
            '<img src="' + image + '">'
        )
        _, output, extractor, _ = self.extract([
            part("text/html; charset=utf-8", html, ORIGIN + "/index.html"),
            part("image/png", b"PNG", image),
        ])
        saved = self.saved(output, ".html")
        for unchanged in (
            '<form action="' + image + '">', '<img srcset="' + image + ' 1x">',
            'srcdoc="&lt;img src=&quot;' + image + '&quot;&gt;"',
            '<svg><image href="' + image + '"/></svg>',
            '<!-- <img src="' + image + '"> -->',
            '<script/>var snippet="<img src=\\"' + image + '\\">";</script>',
        ):
            self.assertIn(unchanged, saved)
        self.assertIn('<img src="' + extractor.url_mapping[image] + '">', saved)

    def test_unterminated_quoted_outer_tag_does_not_expose_fake_inner_img(self):
        image = ORIGIN + "/a.png"
        fake = '<div data-x="<img src=' + image + '>'
        html = '<meta charset="utf-8">' + fake
        _, output, _, _ = self.extract([
            part("text/html; charset=utf-8", html, ORIGIN + "/index.html"),
            part("image/png", b"PNG", image),
        ])
        self.assertEqual(self.saved(output, ".html"), html)

    def test_plaintext_keeps_literal_closing_tag_and_following_img_as_text(self):
        image = ORIGIN + "/a.png"
        html = (
            '<meta charset="utf-8"><plaintext>'
            'literal </plaintext><img src="' + image + '">'
        )
        _, output, _, _ = self.extract([
            part("text/html; charset=utf-8", html, ORIGIN + "/index.html"),
            part("image/png", b"PNG", image),
        ])
        self.assertEqual(self.saved(output, ".html"), html)

    def test_missing_cid_and_unsupported_schemes_remain_intact_after_base_removal(self):
        html = (
            '<base href="' + ORIGIN + '/assets/">'
            '<img src="cid:missing%40id">'
            '<img src="data:image/png;base64,AAAA">'
            '<a href="javascript:alert(1)">script</a>'
            '<a href="mailto:a@example.test">mail</a>'
            '<a href="#local">fragment</a>'
        )
        _, output, _, _ = self.extract([
            part("text/html; charset=utf-8", html, ORIGIN + "/index.html")
        ])
        saved = self.saved(output, ".html")
        for fragment in (
            'src="cid:missing%40id"', 'src="data:image/png;base64,AAAA"',
            'href="javascript:alert(1)"', 'href="mailto:a@example.test"',
            'href="#local"',
        ):
            self.assertIn(fragment, saved)
        self.assertNotIn('<base href="' + ORIGIN + '/assets/"', saved)

    def test_nonreference_mixed_newline_bytes_are_preserved(self):
        image = ORIGIN + "/pic.png"
        html = b'<meta charset="utf-8"><p>A\r\nB\rC\nD</p>\r\n<img src="' + image.encode("ascii") + b'">'
        _, output, extractor, _ = self.extract([
            part("text/html; charset=utf-8", html, ORIGIN + "/index.html"),
            part("image/png", b"PNG", image),
        ])
        expected = html.replace(image.encode("ascii"), extractor.url_mapping[image].encode("ascii"))
        self.assertEqual(next(output.glob("*.html")).read_bytes(), expected)

    def test_original_parse_content_and_no_output_modes(self):
        image = ORIGIN + "/pic.png"
        html = '<img src="' + image + '"><p>' + image + '</p>'
        source = self.archive([
            part("text/html; charset=utf-8", html, ORIGIN + "/index.html"),
            part("image/png", b"PNG", image),
        ])
        archive = parse_mhtml(source)
        self.assertEqual(archive.parts[0].content, html.encode("utf-8"))
        for options in ({"dry_run": True}, {"create_output_files": False}):
            with self.subTest(options=options):
                output = self.root / ("mode-" + str(len(list(self.root.glob("mode-*")))))
                extractor = MHTMLExtractor(source, output_dir=output, create_in_memory_output=True, **options)
                extractor.extract()
                self.assertFalse(output.exists())
        output = self.root / "normal"
        extractor = MHTMLExtractor(source, output_dir=output, create_in_memory_output=True)
        extractor.extract()
        self.assertEqual(extractor.extracted_contents[extractor.url_mapping[ORIGIN + "/index.html"]]["decoded_body"], html.encode("utf-8"))
        self.assertEqual(archive.parts[0].content, html.encode("utf-8"))
        self.assertEqual((output / extractor.url_mapping[image]).read_bytes(), b"PNG")

    def test_filters_keep_only_successfully_saved_targets_eligible(self):
        page = ORIGIN + "/index.html"
        image = ORIGIN + "/pic.png"
        sheet = ORIGIN + "/site.css"
        html = '<img src="' + image + '"><link href="' + sheet + '">'
        parts = [
            part("text/html; charset=utf-8", html, page),
            part("image/png", b"PNG", image),
            part("text/css; charset=utf-8", ".x{}", sheet),
        ]
        for option, expected_image, expected_sheet, expected_count in (
            ({"no_images": True}, False, True, 2),
            ({"no_css": True}, True, False, 2),
            ({"html_only": True}, False, False, 1),
        ):
            with self.subTest(option=option):
                _, output, extractor, stats = self.extract(parts, **option)
                saved = self.saved(output, ".html")
                image_ref = extractor.url_mapping.get(image, image) if expected_image else image
                sheet_ref = extractor.url_mapping.get(sheet, sheet) if expected_sheet else sheet
                self.assertIn('src="' + image_ref + '"', saved)
                self.assertIn('href="' + sheet_ref + '"', saved)
                self.assertEqual(stats.written_files, expected_count)

    def test_unsafe_text_is_not_rewritten_even_when_saved_target_exists(self):
        image = ORIGIN + "/pic.png"
        for content_type, suffix, body in (
            ("text/html; charset=utf-8", ".html", b'<img src="' + image.encode("ascii") + b'">\xff'),
            ("text/css; charset=x-unknown", ".css", b".x{background:url(" + image.encode("ascii") + b");content:\xff}"),
        ):
            with self.subTest(content_type=content_type):
                _, output, _, stats = self.extract([
                    part(content_type, body, ORIGIN + "/source" + suffix),
                    part("image/png", b"PNG", image),
                ])
                self.assertEqual(next(output.glob("*" + suffix)).read_bytes(), body)
                self.assertEqual((stats.written_files, stats.rewrite_failures), (2, 0))

    def test_failed_target_does_not_become_a_local_reference(self):
        page = ORIGIN + "/index.html"
        image = ORIGIN + "/pic.png"
        source = self.archive([
            part("text/html; charset=utf-8", '<img src="' + image + '">', page),
            part("image/png", b"PNG", image),
        ])
        original_open = Path.open
        for memory in (False, True):
            with self.subTest(memory=memory):
                output = self.root / ("failed-target-" + str(memory))
                extractor = MHTMLExtractor(source, output_dir=output, create_in_memory_output=memory)

                def fail_image(path, mode="r", *args, **kwargs):
                    if path.parent == output and path.suffix == ".png" and mode == "xb":
                        raise OSError("injected image write failure")
                    return original_open(path, mode, *args, **kwargs)

                with patch.object(Path, "open", fail_image), self.assertLogs(level="ERROR"):
                    stats = extractor.extract()
                self.assertIn('src="' + image + '"', self.saved(output, ".html"))
                self.assertEqual((stats.written_files, stats.failed_files), (1, 1))

    def test_canonical_alias_uses_last_archive_occurrence_before_write_gate(self):
        page = ORIGIN + "/archive/index.html"
        image = ORIGIN + "/archive/pic.png"
        outer = ORIGIN + "/archive/root.mhtml"
        html = '<img src="./pic.png">'
        source = self.archive([
            part("text/html; charset=utf-8", html, page),
            part("image/png", b"A", image),
            part("image/png", b"B", "pic.png"),
            part("image/png", b"C", image),
        ], outer_location=outer)
        parsed = parse_mhtml(source)
        middle_name = parsed.parts[2].filename
        last_name = parsed.parts[-1].filename
        original_open = Path.open
        for memory in (False, True):
            for fail_last in (False, True):
                with self.subTest(memory=memory, fail_last=fail_last):
                    output = self.root / ("alias-" + str(memory) + "-" + str(fail_last))
                    extractor = MHTMLExtractor(source, output_dir=output, create_in_memory_output=memory)

                    def fail_final(path, mode="r", *args, **kwargs):
                        if fail_last and path.parent == output and path.name == last_name and mode == "xb":
                            raise OSError("injected final alias write failure")
                        return original_open(path, mode, *args, **kwargs)

                    with patch.object(Path, "open", fail_final):
                        stats = extractor.extract()
                    saved = self.saved(output, ".html")
                    if fail_last and memory:
                        # Combined memory selects the final occurrence before its failed write.
                        self.assertIn('src="' + image + '"', saved)
                    elif fail_last:
                        # Disk-only raw-key selection omits failed A3, leaving written B2 latest.
                        self.assertIn('src="' + quote(middle_name, safe="") + '"', saved)
                    else:
                        self.assertIn('src="' + quote(last_name, safe="") + '"', saved)
                    self.assertEqual(stats.failed_files, int(fail_last))

    def test_css_rewrite_failure_preserves_initial_file_and_cleans_temp(self):
        sheet = ORIGIN + "/site.css"
        image = ORIGIN + "/pic.png"
        body = '@charset "utf-8";.x{background:url(' + image + ')}'
        source = self.archive([
            part("text/css; charset=utf-8", body, sheet),
            part("image/png", b"PNG", image),
        ])
        original_temp = tempfile.NamedTemporaryFile
        for stage in ("open", "write", "close", "replace"):
            with self.subTest(stage=stage):
                output = self.root / ("css-fault-" + stage)
                extractor = MHTMLExtractor(source, output_dir=output)

                def fault_temp(*args, **kwargs):
                    if stage == "open":
                        raise OSError("injected CSS rewrite temp open failure")
                    return FaultingRewriteTemp(original_temp(*args, **kwargs), stage)

                if stage == "replace":
                    context = patch("mhtmlextractor.links.os.replace", side_effect=OSError("injected CSS rewrite replace failure"))
                else:
                    context = patch("mhtmlextractor.links.tempfile.NamedTemporaryFile", side_effect=fault_temp)
                with context, self.assertLogs(level="ERROR"):
                    stats = extractor.extract()
                self.assertEqual((stats.written_files, stats.failed_files, stats.rewrite_failures), (2, 0, 1))
                self.assertEqual((output / extractor.url_mapping[sheet]).read_bytes(), body.encode("utf-8"))
                self.assertFalse(list(output.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
