"""Duplicate archive resources must survive every output mode."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from MHTMLExtractor import parse_mhtml as legacy_parse_mhtml
from mhtmlextractor import MHTMLExtractor, parse_mhtml


REPEAT = "https://example.test/repeat.html"
OTHER = "https://example.test/other.html"
BASE = "repeat_" + hashlib.md5(REPEAT.encode()).hexdigest() + ".html"
SECOND = BASE.replace(".html", "_1.html")
THIRD = BASE.replace(".html", "_2.html")
OTHER_NAME = "other_" + hashlib.md5(OTHER.encode()).hexdigest() + ".html"
HTML_DECLARATION = '<meta charset="utf-8">'
CSS_DECLARATION = '@charset "utf-8";'
MODES = (
    ("dry", {"dry_run": True}),
    ("dry_memory", {"dry_run": True, "create_in_memory_output": True}),
    ("memory", {"create_in_memory_output": True, "create_output_files": False}),
    ("disk", {}),
    ("combined", {"create_in_memory_output": True}),
    ("disabled", {"create_output_files": False}),
)


def html_part(body, location=REPEAT, content_id=None):
    return ("text/html", body, location, content_id)


class DuplicatePartTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mhtml-duplicates-")
        self.addCleanup(temporary.cleanup)
        # Match the extractor's canonical paths when TEMP contains an alias.
        self.root = Path(temporary.name).resolve()

    def archive(self, parts, name="input"):
        payload = [b'Content-Type: multipart/related; boundary="duplicates"\r\n\r\n']
        for content_type, body, location, content_id in parts:
            headers = ["Content-Type: " + content_type]
            if location is not None:
                headers.append("Content-Location: " + location)
            if content_id is not None:
                headers.append("Content-ID: <" + content_id + ">")
            if isinstance(body, bytes):
                headers.append("Content-Transfer-Encoding: binary")
            else:
                body = body.encode("ascii")
            payload.extend((b"--duplicates\r\n", "\r\n".join(headers).encode("ascii"),
                            b"\r\n\r\n", body, b"\r\n"))
        payload.append(b"--duplicates--\r\n")
        source = self.root / (name + ".mhtml")
        source.write_bytes(b"".join(payload))
        return source

    def assert_stats(self, stats, parts, written=0, failed=0):
        total_size = sum(len(body if isinstance(body, bytes) else body.encode("utf-8"))
                         for _, body, _, _ in parts)
        self.assertEqual((stats.total_parts, stats.total_size, stats.written_files,
                          stats.failed_files, stats.rewrite_failures),
                         (len(parts), total_size, written, failed, 0))

    def assert_memory(self, contents, parts, names):
        self.assertEqual(list(contents), names)
        self.assertEqual([entry["decoded_body"] for entry in contents.values()],
                         [part[1] for part in parts])
        self.assertEqual([entry["content_location"] for entry in contents.values()],
                         [part[2] for part in parts])
        self.assertEqual([entry["content_id"] for entry in contents.values()],
                         [part[3] for part in parts])

    def assert_disk(self, output, parts, names):
        self.assertEqual({path.name for path in output.iterdir()}, set(names))
        for part, filename in zip(parts, names):
            body = part[1]
            expected = body if isinstance(body, bytes) else body.encode("utf-8")
            if part[0] == "text/html":
                expected = HTML_DECLARATION.encode("ascii") + expected
            elif part[0] == "text/css":
                expected = CSS_DECLARATION.encode("ascii") + expected
            self.assertEqual((output / filename).read_bytes(), expected)

    def test_duplicate_locations_keep_every_body_in_archive_order_across_modes(self):
        cases = (
            ([html_part("FIRST", content_id="first"),
              html_part("SECOND", content_id="second")], [BASE, SECOND]),
            ([html_part("FIRST", content_id="first"),
              html_part("MIDDLE", OTHER, "middle"),
              html_part("THIRD", content_id="third")], [BASE, OTHER_NAME, SECOND]),
        )
        for case, (parts, names) in enumerate(cases):
            source = self.archive(parts, str(case))
            for parser in (parse_mhtml, legacy_parse_mhtml):
                with self.subTest(case=case, parser=parser.__module__):
                    archive = parser(source)
                    self.assertEqual([part.filename for part in archive.parts], names)
                    self.assertEqual([part.content for part in archive.parts],
                                     [part[1] for part in parts])
                    self.assertEqual([part.content_id for part in archive.parts],
                                     [part[3] for part in parts])
                    self.assertEqual(archive.url_mapping[REPEAT], SECOND)
                    self.assert_stats(archive.stats, parts)
            for mode, options in MODES:
                with self.subTest(case=case, mode=mode):
                    output = self.root / (str(case) + mode)
                    extractor = MHTMLExtractor(source, output_dir=output, **options)
                    with self.assertLogs(level="INFO") as captured:
                        stats = extractor.extract()
                    self.assertEqual([extractor.url_mapping["cid:" + part[3]]
                                      for part in parts], names)
                    self.assertEqual(extractor.url_mapping[REPEAT], SECOND)
                    writing = mode in ("disk", "combined")
                    self.assert_stats(stats, parts, written=len(parts) if writing else 0)
                    self.assertEqual(stats.html_files, len(parts))
                    if options.get("create_in_memory_output"):
                        self.assert_memory(extractor.extracted_contents, parts, names)
                    else:
                        self.assertEqual(extractor.extracted_contents, {})
                    if writing:
                        self.assert_disk(output, parts, names)
                    else:
                        self.assertFalse(output.exists())
                    if options.get("dry_run"):
                        planned = [record.getMessage() for record in captured.records
                                   if "[DRY RUN] Would extract:" in record.getMessage()]
                        self.assertEqual(planned, ["[DRY RUN] Would extract: " + name
                                                   + " (text/html)" for name in names])

    def test_duplicate_cid_selects_last_target_without_losing_distinct_parts(self):
        parts = [html_part("FIRST", REPEAT, "shared"),
                 html_part("SECOND", OTHER, "shared")]
        source = self.archive(parts)
        archive = parse_mhtml(source)
        self.assertEqual([part.content for part in archive.parts], ["FIRST", "SECOND"])
        self.assertEqual(archive.url_mapping["cid:shared"], OTHER_NAME)
        for mode, options in MODES:
            with self.subTest(mode=mode):
                output = self.root / mode
                extractor = MHTMLExtractor(source, output_dir=output, **options)
                stats = extractor.extract()
                self.assertEqual(extractor.url_mapping,
                                 {REPEAT: BASE, OTHER: OTHER_NAME, "cid:shared": OTHER_NAME})
                if options.get("create_in_memory_output"):
                    self.assert_memory(extractor.extracted_contents, parts, [BASE, OTHER_NAME])
                if mode in ("disk", "combined"):
                    self.assert_disk(output, parts, [BASE, OTHER_NAME])
                self.assertEqual((stats.total_parts, stats.failed_files), (2, 0))

    def test_no_write_modes_do_not_call_output_mutators_for_duplicates(self):
        source = self.archive([html_part("FIRST"), html_part("SECOND")])
        with patch.object(MHTMLExtractor, "_setup_output_directory") as setup, \
                patch.object(MHTMLExtractor, "_write_to_file") as write, \
                patch("mhtmlextractor.extractor.update_extracted_html_links") as rewrite:
            self.assertEqual(len(parse_mhtml(source).parts), 2)
            for mode, options in MODES:
                if mode not in ("disk", "combined"):
                    MHTMLExtractor(source, output_dir=self.root / mode, **options).extract()
            setup.assert_not_called()
            write.assert_not_called()
            rewrite.assert_not_called()

    def test_generated_candidates_and_existing_suffixes_are_reserved_in_every_mode(self):
        parts = [html_part(body, None, "part" + str(index))
                 for index, body in enumerate(("ONE", "TWO", "THREE", "FOUR"))]
        source = self.archive(parts)
        candidates = ["collision", "collision", "collision_1", "collision"]
        names = ["collision.html", "collision_1.html", "collision_1_1.html", "collision_2.html"]
        with patch("mhtmlextractor.filenames.uuid.uuid4", side_effect=candidates):
            archive = parse_mhtml(source)
        self.assertEqual([part.filename for part in archive.parts], names)
        self.assertEqual([part.content for part in archive.parts], [part[1] for part in parts])
        for mode, options in MODES:
            with self.subTest(mode=mode):
                output = self.root / mode
                extractor = MHTMLExtractor(source, output_dir=output, **options)
                with patch("mhtmlextractor.filenames.uuid.uuid4", side_effect=candidates):
                    stats = extractor.extract()
                self.assertEqual([extractor.url_mapping["cid:" + part[3]] for part in parts], names)
                if options.get("create_in_memory_output"):
                    self.assert_memory(extractor.extracted_contents, parts, names)
                writing = mode in ("disk", "combined")
                if writing:
                    self.assert_disk(output, parts, names)
                self.assert_stats(stats, parts, written=4 if writing else 0)

    def test_missing_metadata_retains_binary_bodies_with_colliding_random_names(self):
        parts = [("image/png", body, None, None) for body in (b"\xff\x00FIRST", b"\xfe\x00SECOND")]
        source = self.archive(parts)
        with patch("mhtmlextractor.filenames.uuid.uuid4", return_value="random"):
            archive = parse_mhtml(source)
        self.assertEqual([part.filename for part in archive.parts], ["random.png", "random_1.png"])
        self.assertEqual([part.content for part in archive.parts], [part[1] for part in parts])
        self.assertTrue(all(part.content_location is None and part.content_id is None
                            for part in archive.parts))
        self.assertEqual(archive.url_mapping, {})
        self.assertEqual(archive.stats.image_files, 2)
        self.assert_stats(archive.stats, parts)

    def test_malformed_location_fallbacks_use_the_same_collision_rules(self):
        malformed = "http://[invalid"
        parts = [html_part("FIRST", malformed, "first"),
                 html_part("SECOND", malformed, "second")]
        source = self.archive(parts)
        names = ["fallback.bin", "fallback_1.bin"]
        with patch("mhtmlextractor.filenames.uuid.uuid4", return_value="fallback"), \
                self.assertLogs(level="ERROR"):
            archive = parse_mhtml(source)
        self.assertEqual([part.filename for part in archive.parts], names)
        self.assertEqual([part.content for part in archive.parts], ["FIRST", "SECOND"])
        for mode, options in MODES:
            with self.subTest(mode=mode):
                output = self.root / mode
                extractor = MHTMLExtractor(source, output_dir=output, **options)
                with patch("mhtmlextractor.filenames.uuid.uuid4", return_value="fallback"), \
                        self.assertLogs(level="ERROR"):
                    stats = extractor.extract()
                self.assertEqual([extractor.url_mapping["cid:" + part[3]] for part in parts], names)
                self.assertEqual(extractor.url_mapping[malformed], names[-1])
                if options.get("create_in_memory_output"):
                    self.assert_memory(extractor.extracted_contents, parts, names)
                if mode in ("disk", "combined"):
                    self.assert_disk(output, parts, names)
                self.assertEqual(stats.failed_files, 0)

    def test_disk_conflicts_and_archive_reservations_share_the_suffix_search(self):
        parts = [html_part(body, content_id="part" + str(index))
                 for index, body in enumerate(("FIRST", "SECOND", "THIRD"))]
        source = self.archive(parts)
        for memory in (False, True):
            with self.subTest(memory=memory):
                output = self.root / str(memory)
                output.mkdir()
                sentinels = {}
                for name in (BASE, THIRD):
                    path = output / name
                    path.write_bytes(b"existing owner data")
                    sentinels[name] = (path.read_bytes(), path.stat().st_mtime_ns)
                extractor = MHTMLExtractor(source, output_dir=output, create_in_memory_output=memory)
                stats = extractor.extract()
                names = [SECOND, BASE.replace(".html", "_3.html"), BASE.replace(".html", "_4.html")]
                self.assertEqual([extractor.url_mapping["cid:" + part[3]] for part in parts], names)
                for name, before in sentinels.items():
                    path = output / name
                    self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
                for part, name in zip(parts, names):
                    self.assertEqual((output / name).read_text(), HTML_DECLARATION + part[1])
                self.assertEqual(len(list(output.iterdir())), 5)
                self.assert_stats(stats, parts, written=3)
                if memory:
                    self.assert_memory(extractor.extracted_contents, parts, names)

    def test_dry_run_reserves_names_without_checking_existing_output_paths(self):
        parts = [html_part("FIRST", content_id="first"), html_part("SECOND", content_id="second")]
        source = self.archive(parts)
        output = self.root / "out"
        output.mkdir()
        sentinel = output / BASE
        sentinel.write_bytes(b"existing data")
        before = (sentinel.read_bytes(), sentinel.stat().st_mtime_ns)
        extractor = MHTMLExtractor(source, output_dir=output, dry_run=True, create_in_memory_output=True)
        with patch.object(Path, "exists", side_effect=AssertionError("dry-run checked filesystem")):
            stats = extractor.extract()
        self.assert_memory(extractor.extracted_contents, parts, [BASE, SECOND])
        self.assert_stats(stats, parts)
        self.assertEqual((sentinel.read_bytes(), sentinel.stat().st_mtime_ns), before)
        self.assertEqual([path.name for path in output.iterdir()], [BASE])

    def test_filters_do_not_reserve_names_or_replace_selected_mappings(self):
        parts = [("text/css", "CSS", REPEAT, "css"),
                 ("image/png", b"\x00PNG", REPEAT, "image"),
                 html_part("FIRST", content_id="first"),
                 html_part("SECOND", content_id="second")]
        source = self.archive(parts)
        cases = (("html_only", parts[2:], (2, 0, 0)),
                 ("no_css", parts[1:], (2, 0, 1)),
                 ("no_images", [parts[0]] + parts[2:], (2, 1, 0)))
        for option, selected, counts in cases:
            names = [BASE, SECOND, THIRD][:len(selected)]
            with self.subTest(filter=option, mode="parse"):
                archive = parse_mhtml(source, **{option: True})
                self.assertEqual([part.filename for part in archive.parts], names)
                self.assertEqual([part.content for part in archive.parts], [part[1] for part in selected])
                self.assert_stats(archive.stats, selected)
                self.assertEqual((archive.stats.html_files, archive.stats.css_files, archive.stats.image_files), counts)
                self.assertEqual(archive.stats.filtered_files, len(parts) - len(selected))
            with self.subTest(filter=option, mode="combined"):
                output = self.root / option
                extractor = MHTMLExtractor(source, output_dir=output, create_in_memory_output=True)
                stats = extractor.extract(**{option: True})
                self.assert_memory(extractor.extracted_contents, selected, names)
                self.assert_disk(output, selected, names)
                self.assert_stats(stats, selected, written=len(selected))
                self.assertEqual(stats.filtered_files, len(parts) - len(selected))
                self.assertEqual(stats.skipped_files, stats.filtered_files)
                self.assertEqual(extractor.url_mapping[REPEAT], names[-1])
                self.assertEqual(set(extractor.url_mapping),
                                 {REPEAT} | {"cid:" + part[3] for part in selected})

    def test_failed_duplicate_writes_do_not_release_names_or_discard_memory(self):
        parts = [html_part("FIRST", content_id="first"), html_part("SECOND", content_id="second")]
        source = self.archive(parts)
        names = [BASE, SECOND]
        original_open = Path.open
        for memory in (False, True):
            for failed_index in (0, 1):
                with self.subTest(memory=memory, failed_index=failed_index):
                    output = self.root / (str(memory) + str(failed_index))
                    extractor = MHTMLExtractor(source, output_dir=output, create_in_memory_output=memory)

                    def fail_selected(path, mode="r", *args, **kwargs):
                        if path.parent == output and path.name == names[failed_index] and mode == "xb":
                            raise OSError("injected duplicate write failure")
                        return original_open(path, mode, *args, **kwargs)

                    with patch.object(Path, "open", fail_selected), self.assertLogs(level="ERROR"):
                        stats = extractor.extract()
                    successful_index = 1 - failed_index
                    self.assert_disk(output, [parts[successful_index]], [names[successful_index]])
                    self.assert_stats(stats, parts, written=1, failed=1)
                    target = SECOND if memory else names[successful_index]
                    self.assertEqual(extractor.url_mapping[REPEAT], target)
                    if memory:
                        self.assert_memory(extractor.extracted_contents, parts, names)
                        self.assertEqual([extractor.url_mapping["cid:" + part[3]] for part in parts], names)
                    else:
                        self.assertEqual(extractor.extracted_contents, {})
                        self.assertNotIn("cid:" + parts[failed_index][3], extractor.url_mapping)

    def test_html_links_use_last_applicable_duplicate_target(self):
        page_url = "https://example.test/index.html"
        page_body = '<a href="' + REPEAT + '">URL</a><img src="cid:shared">'
        parts = [html_part(page_body, page_url), html_part("FIRST", REPEAT, "shared"),
                 html_part("SECOND", REPEAT, "shared")]
        source = self.archive(parts)
        original_open = Path.open
        for memory in (False, True):
            for fail_last in (False, True):
                with self.subTest(memory=memory, fail_last=fail_last):
                    output = self.root / (str(memory) + str(fail_last))
                    extractor = MHTMLExtractor(source, output_dir=output, create_in_memory_output=memory)

                    def fail_last_duplicate(path, mode="r", *args, **kwargs):
                        if fail_last and path.parent == output and path.name == SECOND and mode == "xb":
                            raise OSError("injected last duplicate write failure")
                        return original_open(path, mode, *args, **kwargs)

                    with patch.object(Path, "open", fail_last_duplicate):
                        stats = extractor.extract()
                    mapping_target = BASE if fail_last and not memory else SECOND
                    self.assertEqual(extractor.url_mapping[REPEAT], mapping_target)
                    self.assertEqual(extractor.url_mapping["cid:shared"], mapping_target)
                    expected_html = page_body
                    if not (fail_last and memory):
                        expected_html = page_body.replace(REPEAT, mapping_target).replace("cid:shared", mapping_target)
                    page_name = extractor.url_mapping[page_url]
                    self.assertEqual((output / page_name).read_text(), HTML_DECLARATION + expected_html)
                    self.assert_stats(stats, parts, written=2 if fail_last else 3, failed=int(fail_last))
                    if memory:
                        self.assert_memory(extractor.extracted_contents, parts, [page_name, BASE, SECOND])


if __name__ == "__main__":
    unittest.main()
