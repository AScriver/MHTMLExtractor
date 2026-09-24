"""Observable file-safety and outcome regressions for extraction."""

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from MHTMLExtractor import MHTMLExtractor as LegacyExtractor
from MHTMLExtractor import parse_mhtml as legacy_parse_mhtml
from mhtmlextractor import MHTMLExtractor, parse_mhtml
from mhtmlextractor.cli import main


HTML_URL = "https://example.test/index.html"
CSS_URL = "https://example.test/site.css"
HTML_BODY = '<html><link rel="stylesheet" href="' + CSS_URL + '"></html>'
CSS_BODY = "body{color:red}"
REPO_ROOT = Path(__file__).resolve().parents[1]


def make_archive(path, html=True, css=True, image=False, untyped=False):
    parts = []
    if html:
        parts.append((b"Content-Type: text/html\r\nContent-Location: " + HTML_URL.encode(), HTML_BODY.encode()))
    if css:
        parts.append((b"Content-Type: text/css\r\nContent-Location: " + CSS_URL.encode(), CSS_BODY.encode()))
    if image:
        parts.append((b"Content-Type: image/png\r\nContent-Transfer-Encoding: binary\r\n", b"\xff\x00binary"))
    if untyped:
        parts.append((b"Content-Location: https://example.test/untyped", b"untyped"))
    payload = [b'Content-Type: multipart/related; boundary="safety-boundary"\r\n\r\n']
    for headers, body in parts:
        payload.extend((b"--safety-boundary\r\n", headers, b"\r\n\r\n", body, b"\r\n"))
    payload.append(b"--safety-boundary--\r\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(payload))
    return path


def snapshot(path):
    if not path.exists():
        return None
    data = path.read_bytes()
    return (hashlib.sha256(data).hexdigest(), path.stat().st_mtime_ns)


def output_files(output):
    return sorted(path for path in output.iterdir() if path.is_file()) if output.exists() else []


class FaultingWriter:
    def __init__(self, raw, stage):
        self.raw = raw
        self.stage = stage

    def __enter__(self):
        self.raw.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        result = self.raw.__exit__(exc_type, exc_value, traceback)
        if self.stage == "close":
            raise OSError("injected initial close failure")
        return result

    def write(self, data):
        if self.stage == "write":
            self.raw.write(data[:7])
            raise OSError("injected initial write failure")
        return self.raw.write(data)


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
            raise OSError("injected rewrite close failure")
        return result

    def write(self, data):
        if self.stage == "write":
            self.raw.write(data[:7])
            raise OSError("injected rewrite write failure")
        return self.raw.write(data)


class FaultingProbeCleanup:
    def __init__(self, raw):
        self.raw = raw

    def __enter__(self):
        self.raw.__enter__()
        return self

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def __exit__(self, exc_type, exc_value, traceback):
        # Leave the owned probe open until the test's finally block cleans it.
        raise OSError("injected probe cleanup failure")


class FileSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mhtml-a61-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def archive_and_output(self, name="case", **options):
        case = self.root / name
        source = make_archive(case / "input.mhtml", **options)
        return source, case / "out"

    def test_fixed_probe_sentinel_is_preserved_and_probe_leaves_no_residue(self):
        source, output = self.archive_and_output()
        output.mkdir()
        sentinel = output / ".mhtml_extractor_test"
        sentinel.write_bytes(b"owner's fixed-name sentinel")
        before = snapshot(sentinel)
        stats = MHTMLExtractor(source, output_dir=output).extract()
        self.assertEqual(snapshot(sentinel), before)
        self.assertEqual(stats.written_files, 2)
        self.assertEqual(len(output_files(output)), 3)
        self.assertEqual({path.suffix for path in output_files(output) if path != sentinel}, {".html", ".css"})

    def test_probe_creation_failure_preserves_unrelated_entries(self):
        source, output = self.archive_and_output()
        output.mkdir()
        sentinel = output / ".mhtml_extractor_test"
        sentinel.write_bytes(b"existing")
        before = snapshot(sentinel)
        with patch("mhtmlextractor.extractor.tempfile.NamedTemporaryFile", side_effect=OSError("probe blocked")):
            with self.assertRaises((OSError, PermissionError)):
                MHTMLExtractor(source, output_dir=output)
        self.assertEqual(snapshot(sentinel), before)
        self.assertEqual(output_files(output), [sentinel])

    def test_probe_cleanup_failure_preserves_unrelated_entries(self):
        source, output = self.archive_and_output()
        output.mkdir()
        sentinel = output / ".mhtml_extractor_test"
        sentinel.write_bytes(b"existing")
        before = snapshot(sentinel)
        original_temp = tempfile.NamedTemporaryFile
        probes = []

        def fail_cleanup(*args, **kwargs):
            probe = FaultingProbeCleanup(original_temp(*args, **kwargs))
            probes.append(probe)
            return probe

        try:
            with patch("mhtmlextractor.extractor.tempfile.NamedTemporaryFile",
                       side_effect=fail_cleanup):
                with self.assertRaisesRegex(PermissionError,
                                            "Could not remove temporary writability probe"):
                    MHTMLExtractor(source, output_dir=output)
        finally:
            for probe in probes:
                probe.raw.close()
        self.assertEqual(snapshot(sentinel), before)
        self.assertEqual(output_files(output), [sentinel])

    def test_clear_rejects_direct_nested_and_raw_relative_paths_before_deletion(self):
        for spelling in ("direct", "nested", "relative_dotdot", "case"):
            with self.subTest(spelling=spelling):
                case = self.root / spelling
                output = case / "out"
                source = output / ("nested/input.mhtml" if spelling == "nested" else "input.mhtml")
                make_archive(source)
                sibling = output / "sibling.txt"
                sibling.write_bytes(b"preserve sibling")
                before = (snapshot(source), snapshot(sibling))
                source_arg = str(source)
                output_arg = str(output)
                if spelling == "relative_dotdot":
                    source_arg = os.path.relpath(str(source), str(case))
                    source_arg = os.path.join("out", "child", "..", ".", "input.mhtml")
                    output_arg = os.path.join("out", ".")
                    prior = Path.cwd()
                    os.chdir(case)
                elif spelling == "case" and os.name == "nt":
                    source_arg = source_arg.swapcase()
                    output_arg = output_arg.swapcase()
                try:
                    code = main([source_arg, "--output_dir", output_arg, "--clear_output_dir"])
                finally:
                    if spelling == "relative_dotdot":
                        os.chdir(prior)
                self.assertNotEqual(code, 0)
                self.assertEqual((snapshot(source), snapshot(sibling)), before)

    def test_clear_rejects_supported_file_symlink_alias(self):
        case = self.root / "alias"
        output = case / "out"
        source = make_archive(output / "input.mhtml")
        outside_alias = case / "outside-link.mhtml"
        try:
            os.symlink(source, outside_alias)
        except (OSError, NotImplementedError) as error:
            self.skipTest("file symlink unavailable: " + str(error))
        sibling = output / "sibling.txt"
        sibling.write_bytes(b"preserve")
        before = (snapshot(source), snapshot(sibling))
        code = main([str(outside_alias), "--output_dir", str(output), "--clear_output_dir"])
        self.assertNotEqual(code, 0)
        self.assertEqual((snapshot(source), snapshot(sibling)), before)

    def test_clear_allows_outside_input_and_similar_prefix_directory(self):
        for name in ("outside", "similar_prefix"):
            with self.subTest(name=name):
                case = self.root / name
                output = case / "out"
                source_dir = case if name == "outside" else case / "out-neighbor"
                source = make_archive(source_dir / "input.mhtml")
                output.mkdir()
                stale = output / "stale.txt"
                stale.write_bytes(b"remove only by requested clear")
                source_before = snapshot(source)
                code = main([str(source), "--output_dir", str(output), "--clear_output_dir"])
                self.assertEqual(code, 0)
                self.assertEqual(snapshot(source), source_before)
                self.assertFalse(stale.exists())
                self.assertEqual(len(output_files(output)), 2)

    def test_existing_output_collision_retains_original_bytes_and_mtime(self):
        source, output = self.archive_and_output()
        output.mkdir()
        expected_html = next(part.filename for part in parse_mhtml(source).parts if part.content_type == "text/html")
        old = output / expected_html
        old.write_bytes(b"preexisting output")
        before = snapshot(old)
        stats = MHTMLExtractor(source, output_dir=output).extract()
        self.assertEqual(snapshot(old), before)
        self.assertEqual(stats.written_files, 2)
        self.assertEqual(len(output_files(output)), 3)
        self.assertTrue(any(path.name.endswith("_1.html") for path in output_files(output)))

    def test_late_collision_preserves_competing_file_and_reports_failure(self):
        source, output = self.archive_and_output()
        extractor = MHTMLExtractor(source, output_dir=output)
        original = extractor._extract_filename
        competitor = []

        def create_after_selection(headers, content_type):
            filename = original(headers, content_type)
            if "css" in content_type:
                path = output / filename
                path.write_bytes(b"late competitor sentinel")
                competitor.append((path, snapshot(path)))
            return filename

        with patch.object(extractor, "_extract_filename", side_effect=create_after_selection):
            stats = extractor.extract()
        self.assertEqual(len(competitor), 1)
        self.assertEqual(snapshot(competitor[0][0]), competitor[0][1])
        self.assertEqual((stats.written_files, stats.failed_files), (1, 1))
        self.assertEqual(len(output_files(output)), 2)

    def test_initial_open_write_and_close_failures_keep_success_and_remove_partial(self):
        original_open = Path.open
        for stage in ("open", "write", "close"):
            with self.subTest(stage=stage):
                source, output = self.archive_and_output(stage)
                extractor = MHTMLExtractor(source, output_dir=output)

                def fault_open(path, mode="r", *args, **kwargs):
                    if path.parent == output and path.suffix == ".css" and mode == "xb":
                        if stage == "open":
                            raise OSError("injected initial open failure")
                        return FaultingWriter(original_open(path, mode, *args, **kwargs), stage)
                    return original_open(path, mode, *args, **kwargs)

                with patch.object(Path, "open", fault_open):
                    stats = extractor.extract()
                self.assertEqual((stats.total_parts, stats.written_files, stats.filtered_files,
                                  stats.failed_files, stats.rewrite_failures), (2, 1, 0, 1, 0))
                self.assertEqual(len(output_files(output)), 1)
                html = output_files(output)[0]
                self.assertEqual(html.suffix, ".html")
                self.assertIn(CSS_URL.encode(), html.read_bytes())
                self.assertNotIn(CSS_URL, extractor.url_mapping)

    def test_html_rewrite_temp_open_write_close_and_replace_failures_preserve_original(self):
        original_temp = tempfile.NamedTemporaryFile
        for stage in ("open", "write", "close", "replace"):
            with self.subTest(stage=stage):
                source, output = self.archive_and_output("rewrite_" + stage)
                extractor = MHTMLExtractor(source, output_dir=output)

                def fault_temp(*args, **kwargs):
                    if stage == "open":
                        raise OSError("injected rewrite temporary open failure")
                    return FaultingRewriteTemp(original_temp(*args, **kwargs), stage)

                if stage == "replace":
                    fault_context = patch("mhtmlextractor.links.os.replace",
                                          side_effect=OSError("injected rewrite replace failure"))
                else:
                    fault_context = patch("mhtmlextractor.links.tempfile.NamedTemporaryFile",
                                          side_effect=fault_temp)
                with fault_context, self.assertLogs(level="ERROR") as captured:
                    stats = extractor.extract()
                self.assertEqual((stats.total_parts, stats.written_files, stats.failed_files,
                                  stats.rewrite_failures), (2, 2, 0, 1))
                files = output_files(output)
                self.assertEqual(len(files), 2)
                html_file = next(path for path in files if path.suffix == ".html")
                self.assertEqual(html_file.read_bytes(), HTML_BODY.encode())
                self.assertFalse(any(path.suffix == ".tmp" for path in files))
                self.assertIn("injected rewrite", "\n".join(captured.output))

    def test_successful_html_rewrite_uses_only_written_css_file(self):
        source, output = self.archive_and_output()
        stats = MHTMLExtractor(source, output_dir=output).extract()
        files = output_files(output)
        html_file = next(path for path in files if path.suffix == ".html")
        css_file = next(path for path in files if path.suffix == ".css")
        self.assertEqual(html_file.read_text(encoding="utf-8"),
                         HTML_BODY.replace(CSS_URL, css_file.name))
        self.assertEqual((stats.written_files, stats.failed_files, stats.rewrite_failures),
                         (2, 0, 0))

    def test_cli_reports_rewrite_failure_after_completed_initial_writes(self):
        source, output = self.archive_and_output()
        with patch("mhtmlextractor.links.os.replace",
                   side_effect=OSError("injected CLI rewrite replace failure")):
            code = main([str(source), "--output_dir", str(output)])
        self.assertNotEqual(code, 0)
        files = output_files(output)
        self.assertEqual(len(files), 2)
        html_file = next(path for path in files if path.suffix == ".html")
        self.assertEqual(html_file.read_bytes(), HTML_BODY.encode())

    def test_first_initial_write_failure_allows_later_success(self):
        source, output = self.archive_and_output()
        extractor = MHTMLExtractor(source, output_dir=output)
        original_open = Path.open

        def fault_html(path, mode="r", *args, **kwargs):
            if path.parent == output and path.suffix == ".html" and mode == "xb":
                raise OSError("injected first write open failure")
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", fault_html):
            stats = extractor.extract()
        self.assertEqual((stats.total_parts, stats.written_files, stats.failed_files), (2, 1, 1))
        self.assertEqual([path.suffix for path in output_files(output)], [".css"])
        self.assertEqual(extractor.saved_html_files, [])
        self.assertNotIn(HTML_URL, extractor.url_mapping)

    def test_dry_run_clear_never_calls_output_mutators_for_existing_or_missing_dir(self):
        for exists in (True, False):
            with self.subTest(exists=exists):
                source, output = self.archive_and_output(str(exists))
                marker = output / "marker"
                if exists:
                    output.mkdir()
                    marker.write_bytes(b"keep")
                before = snapshot(marker)
                with patch.object(MHTMLExtractor, "_setup_output_directory") as setup_call, \
                        patch.object(MHTMLExtractor, "_write_to_file") as write_call, \
                        patch("mhtmlextractor.extractor.update_extracted_html_links") as rewrite_call:
                    stats = MHTMLExtractor(source, output_dir=output, clear_output_dir=True, dry_run=True).extract()
                setup_call.assert_not_called()
                write_call.assert_not_called()
                rewrite_call.assert_not_called()
                self.assertEqual(stats.total_parts, 2)
                self.assertEqual((stats.written_files, stats.failed_files, stats.rewrite_failures), (0, 0, 0))
                self.assertEqual(snapshot(marker), before)
                self.assertEqual(output.exists(), exists)

    def test_parse_optional_headers_text_bytes_no_writes_and_legacy_imports(self):
        source, output = self.archive_and_output(html=True, css=False, image=True)
        with patch.object(MHTMLExtractor, "_setup_output_directory") as setup_call, \
                patch.object(MHTMLExtractor, "_write_to_file") as write_call, \
                patch("mhtmlextractor.extractor.update_extracted_html_links") as rewrite_call:
            archive = parse_mhtml(source)
        setup_call.assert_not_called()
        write_call.assert_not_called()
        rewrite_call.assert_not_called()
        self.assertFalse(output.exists())
        self.assertIs(MHTMLExtractor, LegacyExtractor)
        self.assertIs(parse_mhtml, legacy_parse_mhtml)
        self.assertEqual(len(archive.parts), 2)
        self.assertIsInstance(archive.parts[0].content, str)
        self.assertIsInstance(archive.parts[1].content, bytes)
        self.assertIsNone(archive.parts[1].content_location)
        self.assertIsNone(archive.parts[1].content_id)
        self.assertEqual((archive.stats.written_files, archive.stats.failed_files,
                          archive.stats.rewrite_failures), (0, 0, 0))

    def test_combined_memory_and_files_uses_single_content_mapping(self):
        source, output = self.archive_and_output()
        extractor = MHTMLExtractor(source, output_dir=output, create_in_memory_output=True)
        stats = extractor.extract()
        self.assertEqual(stats.written_files, 2)
        self.assertEqual(len(output_files(output)), 2)
        self.assertEqual(len(extractor.extracted_contents), 2)
        self.assertEqual({v["content_type"] for v in extractor.extracted_contents.values()},
                         {"text/html", "text/css"})

    def test_combined_memory_retains_failed_css_without_rewriting_disk_html_to_it(self):
        source, output = self.archive_and_output()
        extractor = MHTMLExtractor(source, output_dir=output, create_in_memory_output=True)
        original_open = Path.open

        def fault_css(path, mode="r", *args, **kwargs):
            if path.parent == output and path.suffix == ".css" and mode == "xb":
                raise OSError("injected combined CSS write failure")
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", fault_css):
            stats = extractor.extract()
        self.assertEqual((stats.total_parts, stats.written_files, stats.failed_files,
                          stats.rewrite_failures), (2, 1, 1, 0))
        self.assertEqual(len(extractor.extracted_contents), 2)
        self.assertIn(CSS_URL, extractor.url_mapping)
        self.assertEqual([path.suffix for path in output_files(output)], [".html"])
        self.assertEqual(output_files(output)[0].read_bytes(), HTML_BODY.encode())

    def test_normal_filtered_all_filtered_and_untyped_accounting(self):
        source, output = self.archive_and_output("normal", untyped=True)
        normal = MHTMLExtractor(source, output_dir=output).extract()
        self.assertEqual((normal.total_parts, normal.html_files, normal.css_files,
                          normal.written_files, normal.filtered_files, normal.failed_files,
                          normal.skipped_files, normal.total_size),
                         (2, 1, 1, 2, 0, 0, 1, len(HTML_BODY.encode()) + len(CSS_BODY.encode())))
        source, output = self.archive_and_output("html_only", untyped=True)
        filtered = MHTMLExtractor(source, output_dir=output).extract(html_only=True)
        self.assertEqual((filtered.total_parts, filtered.written_files, filtered.filtered_files,
                          filtered.failed_files, filtered.skipped_files, filtered.total_size),
                         (1, 1, 1, 0, 2, len(HTML_BODY.encode())))
        source, output = self.archive_and_output("all_filtered", html=False)
        all_filtered = MHTMLExtractor(source, output_dir=output).extract(html_only=True)
        self.assertEqual((all_filtered.total_parts, all_filtered.written_files,
                          all_filtered.filtered_files, all_filtered.skipped_files), (0, 0, 1, 1))
        self.assertNotEqual(main([str(source), "--output_dir", str(output / "cli"), "--html-only"]), 0)

    def test_real_cli_process_exits_for_success_total_and_partial_write_failure(self):
        source, output = self.archive_and_output()
        success = subprocess.run([sys.executable, "-B", str(REPO_ROOT / "MHTMLExtractor.py"),
                                  str(source), "--output_dir", str(output)],
                                 cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30)
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertEqual(len(output_files(output)), 2)
        child = (
            "import sys\n"
            "from unittest.mock import patch\n"
            "from mhtmlextractor.cli import main\n"
            "from mhtmlextractor.extractor import MHTMLExtractor\n"
            "original=MHTMLExtractor._write_to_file\n"
            "calls=[]\n"
            "def fault(self, name, kind, body):\n"
            "    calls.append(name)\n"
            "    if sys.argv[3]=='total' or len(calls)==2: raise OSError('injected CLI write failure')\n"
            "    return original(self, name, kind, body)\n"
            "with patch.object(MHTMLExtractor, '_write_to_file', fault):\n"
            "    sys.exit(main([sys.argv[1], '--output_dir', sys.argv[2], *sys.argv[4:]]))\n"
        )
        for mode, expected_written in (("total", 0), ("partial", 1)):
            with self.subTest(mode=mode):
                destination = self.root / mode / "out"
                result = subprocess.run([sys.executable, "-B", "-c", child,
                                         str(source), str(destination), mode, "--quiet"],
                                        cwd=str(REPO_ROOT), capture_output=True, text=True,
                                        timeout=30)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(output_files(destination)), expected_written)
                self.assertIn("injected CLI write failure", result.stderr)
                self.assertIn("Failed writing MHTML part", result.stderr)
                self.assertNotIn("Extraction complete", result.stderr)


if __name__ == "__main__":
    unittest.main()
