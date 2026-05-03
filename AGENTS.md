# Agent Guide

## Install

- Use Python 3.7 or newer.
- From the repository root, install normally with `python -m pip install .`.
- For local development, install editable with `python -m pip install -e .`.
- After installation, confirm the command surface with `mhtml-extract --help`.

## Import

```python
from mhtmlextractor import MHTMLExtractor, parse_mhtml
from mhtmlextractor import MHTMLArchive, MHTMLPart, ExtractionStats
```

The legacy compatibility import also exists:

```python
from MHTMLExtractor import MHTMLExtractor, parse_mhtml
```

Prefer `mhtmlextractor` for new code.

## Parse

Use `parse_mhtml()` when you need typed, in-memory results and do not want files written:

```python
from mhtmlextractor import parse_mhtml

archive = parse_mhtml("example.mhtml", html_only=False, no_css=False, no_images=False)

for part in archive.parts:
    print(part.filename, part.content_type, part.content_location, part.content_id)
```

Use `MHTMLExtractor` or `mhtml-extract` when you need files written to disk.

## Test

- Run tests with `python -m unittest discover -s tests`.
- Run a syntax check with `python -m compileall -q MHTMLExtractor.py mhtmlextractor`.
- Do not use `python -m py_compile mhtmlextractor\*.py` in PowerShell; the wildcard can be passed literally.
- For installability changes, verify an editable install and run `mhtml-extract --help`.

## Avoid Unsafe Assumptions

- Do not assume every part has `Content-Location` or `Content-ID`; handle `None`.
- Do not assume `MHTMLPart.content` is always text; it may be `str` or `bytes`.
- Do not assume parsing writes files. `parse_mhtml()` is intentionally in-memory.
- Do not add a second in-memory part store; `extracted_contents` is the source of truth.
- Do not overwrite or clear extraction output unless the user explicitly asks for it.
- Keep both public import surfaces working unless the user asks to remove compatibility.
