# MHTMLExtractor

MHTMLExtractor extracts resources from MHTML / MIME HTML web archives. It can be
used as an installable command-line tool or as a Python package for typed,
in-memory parsing.

The project uses only Python's standard library.

## Requirements

- Python 3.7 or newer

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

The CLI exits nonzero for a failed part write or HTML link rewrite, including
partial success. Successfully written files are retained. HTML rewrites replace
the original only after the complete replacement has been written and closed;
a failed rewrite preserves the original extracted HTML. Write errors remain
visible with `--quiet`. A run with no selected, decoded parts also exits nonzero,
including when every part was filtered out.

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
| `failed_files` | Selected parts that failed processing or initial writing. |
| `rewrite_failures` | Failed HTML postprocessing operations, separate from initial file writes. |

An HTML file can have a successful initial write and a failed rewrite. Its
original bytes remain available, but the overall extraction has failed. Disk
links are updated only for resources successfully written to disk.

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

Run the test suite:

```bash
python -m unittest discover -s tests
```

Run a package syntax check:

```bash
python -m compileall -q MHTMLExtractor.py mhtmlextractor
```

Check the installed command surface from a local editable install:

```bash
mhtml-extract --help
```

## License

MHTMLExtractor is released under the MIT License. See `LICENSE`.
