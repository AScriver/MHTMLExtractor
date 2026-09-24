# MHTMLExtractor

MHTMLExtractor extracts resources from MHTML / MIME HTML web archives. It can be
used as an installable command-line tool or as a Python package for typed,
in-memory parsing.

The project uses only Python's standard library.

## Requirements

- Python 3.7 or newer

The source compatibility CI matrix covers x64 CPython 3.7 through 3.14 on
Windows and Linux. The package has no upper Python version cap; versions beyond
this matrix are not yet verified. Compatibility testing of older Python versions
does not imply upstream maintenance. See the
[official Python version status](https://devguide.python.org/versions/).

## Installation

From the repository root:

```bash
python -m pip install .
```

For local development:

```bash
python -m pip install -e .
```

After installation, the `mhtml-extract` command is available on your PATH.

## Command Line

Extract an archive into the current directory:

```bash
mhtml-extract example.mhtml
```

Choose an output directory:

```bash
mhtml-extract example.mhtml --output_dir ./extracted
```

Preview what the archive contains without writing files:

```bash
mhtml-extract example.mhtml --dry-run --verbose
```

Extract only HTML parts:

```bash
mhtml-extract example.mhtml --html-only
```

Skip CSS and image parts:

```bash
mhtml-extract example.mhtml --no-css --no-images
```

Common options:

```text
--output_dir PATH       Directory for extracted files. CLI default: current directory.
--buffer_size BYTES     Read buffer size. Default: 8192.
--clear_output_dir      Recursively clear output before extraction (input must be outside it).
--no-css                Skip CSS files.
--no-images             Skip image files.
--html-only             Extract only HTML files.
--dry-run               Analyze the archive without writing files.
--verbose, -v           Enable verbose logging.
--quiet, -q             Suppress all output except errors.
```

The legacy script entry point is still available:

```bash
python MHTMLExtractor.py example.mhtml
```

Existing output files are preserved during ordinary extraction; colliding names
receive a numeric suffix. If another file appears at the selected name before
the write, extraction reports a failure instead of overwriting it.

`--clear_output_dir` explicitly removes the output directory's contents,
including subdirectories. The resolved input archive must be outside that
directory; otherwise extraction rejects the request before deleting anything.
`--dry-run` does not create, clear, probe, or write output, even when combined
with `--clear_output_dir`.

The CLI exits nonzero for failed text normalization, a part write, or an HTML/CSS reference rewrite, including
partial success. Successfully written files are retained. Reference rewrites replace
the original only after the complete replacement has been written and closed;
a failed rewrite preserves the original extracted file. Write errors remain
visible with `--quiet`. A run with no selected, decoded parts also exits nonzero,
including when every part was filtered out.

### Text encodings on disk

Extracted `text/html` and `text/css` files are normalized to UTF-8. HTML encoding
declarations (`meta charset` and `http-equiv="Content-Type"`) are updated, with
an early UTF-8 declaration added when necessary. CSS receives a leading
`@charset "utf-8";` declaration. This also applies with `--html-only`; it does
not depend on the link-rewriting pass.

Encoding selection uses a UTF-8 or UTF-16 BOM first, then the MIME `charset`
parameter, then an actual HTML encoding declaration or the exact leading CSS
`@charset "...";` form. Undeclared text must be valid UTF-8. A present but empty
or unsupported selected label fails instead of falling through to another
encoding. A BOM overrides lower-priority declarations.

Supported labels follow the [WHATWG Encoding Standard](https://encoding.spec.whatwg.org/#names-and-labels),
with ASCII case and surrounding ASCII whitespace ignored:

- UTF-8: `unicode-1-1-utf-8`, `unicode11utf8`, `unicode20utf8`, `utf-8`, `utf8`,
  `x-unicode20utf8`.
- Windows-1252: `ansi_x3.4-1968`, `ascii`, `cp1252`, `cp819`, `csisolatin1`,
  `ibm819`, `iso-8859-1`, `iso-ir-100`, `iso8859-1`, `iso88591`, `iso_8859-1`,
  `iso_8859-1:1987`, `l1`, `latin1`, `us-ascii`, `windows-1252`, `x-cp1252`.
- UTF-16LE and UTF-16BE are supported only with a BOM. Label-only UTF-16 and
  other Python codec names are unsupported.

This is a bounded policy: it does not guess an encoding or implement CSS
encoding inheritance from a referring page. An unsupported label, invalid
selected byte sequence, or unsafe declaration normalization preserves the
original transfer-decoded bytes on disk and reports a failed part. That file
is excluded from subsequent text rewriting, even if its bytes happen to be
valid UTF-8. Other MIME types, including XML, XHTML, JavaScript, plain text,
and binary resources, retain their original octets.

These transformations affect disk output only. `parse_mhtml()` and
`extracted_contents` retain the original transfer-decoded `str` or `bytes`.
In particular, a transport `str` is the original Latin-1 byte representation,
not a promise that its characters have been decoded using the declared charset.
Parsing, dry-run, and memory-only extraction do not normalize or write text.

### Static resource references

Saved HTML and CSS use portable, URL-escaped filenames for captured resources
that were successfully written. References are matched as complete URLs,
including their query; resource fragments are retained. Supported contexts are
HTML `href`/`src` on URL-bearing elements, `video poster`, `object data`, style
attributes and blocks, and external CSS `url()` and quoted or `url()` imports.
HTML character references and CSS escapes are decoded for matching. Paragraphs,
comments, script text, ordinary CSS strings, and unrelated markup are preserved,
including the normalized file's original line endings.

Relative references use the original document or stylesheet location, with
the first HTML `base href` and available outer MIME `Content-Location` supplying
context. Every HTML base `href` is removed after resolution; `target` is kept.
Uncaptured, filtered, and failed-write destinations retain their source URL,
made absolute where necessary. With no absolute source location, a private
archive root resolves relative identities; unresolved paths are written relative
to the output directory without inventing a remote address. Document-local
`#fragment` references stay local. General URL paths are not percent-decoded
into different identities; percent-escaped `cid:` references match Content-IDs.
HTTP, HTTPS, file, and FTP locations are supported; other schemes remain intact
unless a `cid:` reference has a captured target. Extraction never fetches URLs.

This is static reference localization, not a browser or MIME-tree reconstruction.
Script code and dynamic requests, form actions, `srcset`, `srcdoc`, SVG/XML
(including foreign subtrees), and nested MIME scopes are not transformed.
Their relative runtime behavior after base removal is outside this guarantee.
Malformed reference tokens are left intact. CSS-only archives are processed;
`--html-only` skips reference rewriting. Files preserved after failed text
normalization are never rewritten. In-memory parse results remain unchanged.

## Python API

Use `parse_mhtml()` when you want a typed in-memory result and do not want files
written to disk.

```python
from mhtmlextractor import parse_mhtml

archive = parse_mhtml("example.mhtml")

print(archive.path)
print(archive.stats.total_parts)

for part in archive.parts:
    print(part.filename, part.content_type)
    print(part.content_location)
    print(part.content_id)
    print(part.content)
```

`parse_mhtml()` returns an `MHTMLArchive`:

- `path`: resolved `Path` to the input archive
- `parts`: tuple of `MHTMLPart` values in archive order
- `stats`: `ExtractionStats` produced by the extractor
- `url_mapping`: mapping of source URLs / content IDs to generated filenames

Each `MHTMLPart` contains:

- `filename`
- `content_type`
- `content`
- `content_location`
- `content_id`

Every selected part receives its own filename, even when multiple parts share
a `Content-Location` or `Content-ID`. Collisions receive numeric suffixes before
the extension (`name.html`, `name_1.html`, and so on), preserving every body in
archive order. With no existing output conflicts, parsing, dry-run, memory-only,
and disk extraction allocate the same names from the same candidates. Resources
without a location still use random UUID names, so their names can differ between
runs. Dry-run ignores existing output files but reserves names within the archive.

`url_mapping` selects one target per source URL or `cid:` identifier. Duplicate
identifiers use the last selected part; all earlier parts remain in `parts` or
`extracted_contents` under their own filenames. Filtered parts do not reserve
names or change mappings.

The parser accepts the same content filters as the extractor:

```python
from mhtmlextractor import parse_mhtml

archive = parse_mhtml(
    "example.mhtml",
    html_only=True,
)
```

The legacy top-level import remains available for compatibility:

```python
from MHTMLExtractor import parse_mhtml
```

## File Extraction From Python

Use `MHTMLExtractor` directly when you want to write extracted files or need
lower-level control over extraction.

```python
from mhtmlextractor import MHTMLExtractor

extractor = MHTMLExtractor(
    mhtml_path="example.mhtml",
    output_dir="./extracted",
)

stats = extractor.extract(no_css=False, no_images=False, html_only=False)
print(stats.written_files)
print(stats.failed_files, stats.rewrite_failures)
```

`extract()` returns statistics for both successful and failed parts; callers
should check `failed_files` and `rewrite_failures` before treating a run as
successful. Setup and input errors still raise exceptions.

| Statistic | Meaning |
| --- | --- |
| `total_parts`, type counts, `total_size` | Selected, decoded content, including a part whose later file write failed. These remain available during parsing and dry-run. |
| `written_files` | Initial output files successfully written and closed; zero in no-write modes. |
| `filtered_files` | Parts excluded by content filters. |
| `skipped_files` | Filtered or otherwise skipped input, excluding processing/write failures. |
| `failed_files` | Selected parts that failed processing, text normalization, or initial writing; counted once per failed part. |
| `rewrite_failures` | Failed HTML/CSS reference postprocessing operations, separate from initial file writes. |

An HTML or CSS file can have a successful initial write and a failed rewrite. Its
original bytes remain available, but the overall extraction has failed. Disk
links are updated only for resources successfully written to disk.
Likewise, preserving a part's original bytes after failed normalization counts
as both a successful initial write and a failed part. Those preserved files
are not eligible for text rewriting.

For disk-only extraction, duplicate identifier mappings select the last
successfully written part. With combined memory and file output, mappings select
the last part retained in memory, even if its disk write failed; HTML rewriting
excludes such failed targets. A failed write does not release its reserved name,
so later parts cannot replace its retained in-memory body.

For in-memory access through the lower-level extractor:

```python
from mhtmlextractor import MHTMLExtractor

extractor = MHTMLExtractor(
    mhtml_path="example.mhtml",
    create_in_memory_output=True,
    create_output_files=False,
)
extractor.extract()

for filename, details in extractor.extracted_contents.items():
    print(filename)
    print(details["content_type"])
    print(details["decoded_body"])
```

For new in-memory code, prefer `parse_mhtml()` because it returns typed result
objects.

## Behavior Notes

- Filenames are derived from `Content-Location` when available, sanitized for
  filesystem use, and made unique with a URL-derived hash.
- `Content-ID` values are normalized and included in `MHTMLPart.content_id`.
- Extracted HTML links are updated to point at generated local filenames unless
  `--html-only` is used.
- `--dry-run` analyzes archives without writing output files.
- `--no-css`, `--no-images`, and `--html-only` filter extracted or parsed parts.

## Development

The [source compatibility workflow](.github/workflows/tests.yml) runs on pushes
and pull requests using Windows Server 2022 and Ubuntu 22.04, with x64 CPython
3.7 through 3.14. It runs the source tests and syntax check directly from the
checkout using only the standard library; no package installation is required.
Each matrix job reports its interpreter version and runs independently so one
failure does not cancel the other versions.

Run the same test suite locally:

```bash
python -m unittest discover -s tests
```

CI adds `-v` to show individual tests and skip reasons. The TOML metadata test
skips on Python 3.7 through 3.10 because `tomllib` is available from Python 3.11;
the extraction tests still run. A symlink test may skip when the platform cannot
create symlinks.

Run a package syntax check:

```bash
python -m compileall -q MHTMLExtractor.py mhtmlextractor
```

Check the installed command surface from a local editable install:

```bash
mhtml-extract --help
```

Source compatibility and editable-install checks do not verify installed wheel
or source-distribution behavior; those require separate clean installations.

## License

MHTMLExtractor is released under the MIT License. See `LICENSE`.
