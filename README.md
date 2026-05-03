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
--clear_output_dir      Clear the output directory before extraction.
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
    clear_output_dir=True,
)

stats = extractor.extract(no_css=False, no_images=False, html_only=False)
print(stats.total_parts)
```

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
