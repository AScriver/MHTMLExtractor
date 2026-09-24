"""Strict, side-effect-free normalization of disk HTML and CSS to UTF-8.

This deliberately supports a closed subset of WHATWG encoding labels: UTF-8
and Windows-1252. UTF-16 is supported only when its byte-order mark is present.
Other labels, including Python-only codec aliases, fail rather than guessing.
"""

import re
from html import unescape
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple


class TextNormalizationError(ValueError):
    """The selected text encoding cannot be normalized without guessing."""


_UTF8_LABELS = frozenset((
    "unicode-1-1-utf-8", "unicode11utf8", "unicode20utf8",
    "utf-8", "utf8", "x-unicode20utf8",
))
_WINDOWS1252_LABELS = frozenset((
    "ansi_x3.4-1968", "ascii", "cp1252", "cp819", "csisolatin1",
    "ibm819", "iso-8859-1", "iso-ir-100", "iso8859-1", "iso88591",
    "iso_8859-1", "iso_8859-1:1987", "l1", "latin1", "us-ascii",
    "windows-1252", "x-cp1252",
))
_ASCII_WHITESPACE = "\t\n\f\r "
_WINDOWS1252_HIGH = (
    "\u20ac\u0081\u201a\u0192\u201e\u2026\u2020\u2021"
    "\u02c6\u2030\u0160\u2039\u0152\u008d\u017d\u008f"
    "\u0090\u2018\u2019\u201c\u201d\u2022\u2013\u2014"
    "\u02dc\u2122\u0161\u203a\u0153\u009d\u017e\u0178"
)
_CSS_CHARSET = re.compile(r'^@charset "([^"\r\n]*)";')
_LEGACY_CHARSET = re.compile(r'(?i)(?:^|;)\s*charset\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^;\s]*))')
_ENTITY = re.compile(r'&(?:#[0-9]+|#[xX][0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);?')


def _encoding(label: str) -> str:
    canonical = label.strip(_ASCII_WHITESPACE).lower()
    if canonical in _UTF8_LABELS:
        return "utf-8"
    if canonical in _WINDOWS1252_LABELS:
        return "windows-1252"
    raise TextNormalizationError("Unsupported or empty charset: {!r}".format(label))


def _decode(raw: bytes, encoding: str) -> str:
    try:
        if encoding == "windows-1252":
            return "".join(
                _WINDOWS1252_HIGH[value - 0x80] if 0x80 <= value <= 0x9f
                else chr(value) for value in raw
            )
        return raw.decode(encoding, errors="strict")
    except UnicodeError as exc:
        raise TextNormalizationError("Invalid bytes for {}".format(encoding)) from exc


def _attributes(tag: str) -> Dict[str, List[Tuple[str, int, int, bool]]]:
    """Read attribute value spans without mistaking quoted text for attributes."""
    attrs = {}  # type: Dict[str, List[Tuple[str, int, int, bool]]]
    opener = re.match(r"<meta(?=[\t\n\f\r />])", tag, re.IGNORECASE)
    if opener is None:
        return attrs
    index = opener.end()
    while index < len(tag):
        while index < len(tag) and tag[index] in _ASCII_WHITESPACE:
            index += 1
        if index >= len(tag) or tag[index] in "/>":
            break
        start = index
        while index < len(tag) and tag[index] not in _ASCII_WHITESPACE and tag[index] not in "=/>":
            index += 1
        if index == start:
            index += 1
            continue
        name = tag[start:index].lower()
        name_end = index
        while index < len(tag) and tag[index] in _ASCII_WHITESPACE:
            index += 1
        has_equals = index < len(tag) and tag[index] == "="
        if has_equals:
            index += 1
            while index < len(tag) and tag[index] in _ASCII_WHITESPACE:
                index += 1
            if index < len(tag) and tag[index] in "\"'":
                quote = tag[index]
                index += 1
                value_start = index
                while index < len(tag) and tag[index] != quote:
                    index += 1
                value_end = index
                if index < len(tag):
                    index += 1
            else:
                value_start = index
                while index < len(tag) and tag[index] not in _ASCII_WHITESPACE and tag[index] != ">":
                    index += 1
                value_end = index
        else:
            value_start = value_end = name_end
        attrs.setdefault(name, []).append((
            unescape(tag[value_start:value_end]), value_start, value_end, has_equals
        ))
    return attrs


class _HTMLDeclarations(HTMLParser):
    """Locate real meta tags and insertion points while keeping source spans."""

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.source = source
        self.line_starts = [0] + [match.end() for match in re.finditer("\n", source)]
        self.metas = []  # type: List[Tuple[int, int, str, Optional[str]]]
        self.head_end = None  # type: Optional[int]
        self.html_end = None  # type: Optional[int]
        self.doctype_end = None  # type: Optional[int]
        self.raw_context = None  # type: Optional[str]
        self.feed(source)
        self.close()

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.line_starts[line - 1] + column

    def handle_decl(self, decl: str) -> None:
        if self.doctype_end is None and decl.lower().startswith("doctype"):
            self.doctype_end = self._offset() + len(decl) + 3

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        raw = self.get_starttag_text()
        start = self._offset()
        end = start + len(raw)
        if self.raw_context is not None:
            return
        if tag in ("script", "style", "title", "textarea"):
            self.raw_context = tag
            return
        if tag == "head" and self.head_end is None:
            self.head_end = end
        elif tag == "html" and self.html_end is None:
            self.html_end = end
        elif tag == "meta":
            self._add_meta(start, end, raw)

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag in ("script", "style", "title", "textarea"):
            # HTML ignores the self-closing slash on these non-void elements.
            self.handle_starttag(tag, attrs)
            return
        if tag == "meta" and self.raw_context is None:
            start = self._offset()
            raw = self.get_starttag_text()
            self._add_meta(start, start + len(raw), raw)

    def handle_endtag(self, tag: str) -> None:
        if tag == self.raw_context:
            self.raw_context = None

    def _add_meta(self, start: int, end: int, raw: str) -> None:
        attrs = _attributes(raw)
        if "charset" in attrs:
            self.metas.append((start, end, raw, attrs["charset"][0][0]))
            return
        equiv = attrs.get("http-equiv", [("", 0, 0, False)])[0][0]
        if equiv.strip(_ASCII_WHITESPACE).lower() != "content-type":
            return
        content = attrs.get("content", [("", 0, 0, False)])[0][0]
        match = _LEGACY_CHARSET.search(content)
        if match is not None:
            self.metas.append((start, end, raw, next(
                (group for group in match.groups() if group is not None), ""
            )))


def _unescape_with_spans(raw: str) -> Tuple[str, List[Tuple[int, int]]]:
    """Track each decoded attribute character back to its source span."""
    decoded = []  # type: List[str]
    spans = []  # type: List[Tuple[int, int]]
    cursor = 0
    for match in _ENTITY.finditer(raw):
        for position in range(cursor, match.start()):
            decoded.append(raw[position])
            spans.append((position, position + 1))
        entity = match.group(0)
        value = unescape(entity)
        if value == entity:
            for position in range(match.start(), match.end()):
                decoded.append(raw[position])
                spans.append((position, position + 1))
        else:
            for character in value:
                decoded.append(character)
                spans.append((match.start(), match.end()))
        cursor = match.end()
    for position in range(cursor, len(raw)):
        decoded.append(raw[position])
        spans.append((position, position + 1))
    result = "".join(decoded)
    if result != unescape(raw):
        raise TextNormalizationError("Cannot locate HTML charset source span")
    return result, spans


def _repair_legacy_content(raw: str) -> str:
    content, spans = _unescape_with_spans(raw)
    changes = []  # type: List[Tuple[int, int]]
    for match in _LEGACY_CHARSET.finditer(content):
        group = next(number for number in (1, 2, 3)
                     if match.group(number) is not None)
        start, end = match.span(group)
        raw_start = spans[start][0] if start < len(spans) else len(raw)
        raw_end = spans[end - 1][1] if end > start else raw_start
        if (start and start < len(spans) and spans[start - 1] == spans[start]) or (
            end and end < len(spans) and spans[end - 1] == spans[end]
        ):
            raise TextNormalizationError("Cannot split HTML character reference")
        changes.append((raw_start, raw_end))
    for start, end in reversed(changes):
        raw = raw[:start] + "utf-8" + raw[end:]
    return raw


def _repair_meta(tag: str) -> str:
    attrs = _attributes(tag)
    changes = []  # type: List[Tuple[int, int, str]]
    for _, start, end, has_equals in attrs.get("charset", []):
        replacement = "utf-8" if has_equals else '="utf-8"'
        changes.append((start, end, replacement))
    equiv = attrs.get("http-equiv", [("", 0, 0, False)])[0][0]
    if equiv.strip(_ASCII_WHITESPACE).lower() == "content-type":
        for _, start, end, _ in attrs.get("content", []):
            raw_value = tag[start:end]
            if _LEGACY_CHARSET.search(unescape(raw_value)) is None:
                continue
            changes.append((start, end, _repair_legacy_content(raw_value)))
    for start, end, replacement in sorted(changes, reverse=True):
        tag = tag[:start] + replacement + tag[end:]
    return tag


def _html(source: str, declarations: _HTMLDeclarations) -> bytes:
    changes = [(start, end, _repair_meta(raw))
               for start, end, raw, _ in declarations.metas]
    for start, end, replacement in sorted(changes, reverse=True):
        source = source[:start] + replacement + source[end:]

    # An early declaration is needed even when the original one moved beyond
    # byte 1024 after transcoding from a single-byte source.
    repaired = _HTMLDeclarations(source)
    early = any(len(source[:end].encode("utf-8")) <= 1024
                for _, end, _, _ in repaired.metas)
    if not early:
        marker = '<meta charset="utf-8">'
        for position in (repaired.head_end, repaired.html_end, repaired.doctype_end,
                         0 if repaired.doctype_end is None else None):
            if position is None:
                continue
            if repaired.doctype_end is not None and position < repaired.doctype_end:
                continue
            if len((source[:position] + marker).encode("utf-8")) <= 1024:
                source = source[:position] + marker + source[position:]
                break
        else:
            raise TextNormalizationError("Cannot place HTML charset within first 1024 bytes")
    return source.encode("utf-8")


def _css(source: str) -> bytes:
    match = _CSS_CHARSET.match(source)
    if match is not None and len(match.group(0).encode("utf-8")) <= 1024:
        source = '@charset "utf-8";' + source[match.end():]
    else:
        source = '@charset "utf-8";' + source
    return source.encode("utf-8")


def normalize_text(raw: bytes, content_type: str,
                   mime_charset: Optional[str]) -> bytes:
    """Normalize a target part to UTF-8, or raise on uncertain input.

    The BOM wins over MIME charset, which wins over an in-band declaration.
    With no declaration, only strict UTF-8 input is accepted. Non-target media
    types are returned unchanged. This function never changes an archive part.
    """
    if content_type not in ("text/html", "text/css"):
        return raw
    bom_encoding = None
    if raw.startswith(b"\xef\xbb\xbf"):
        bom_encoding, raw = "utf-8", raw[3:]
    elif raw.startswith(b"\xff\xfe"):
        bom_encoding, raw = "utf-16-le", raw[2:]
    elif raw.startswith(b"\xfe\xff"):
        bom_encoding, raw = "utf-16-be", raw[2:]

    sniffed = None  # type: Optional[_HTMLDeclarations]
    in_band = None  # type: Optional[str]
    if bom_encoding is None and mime_charset is None:
        if content_type == "text/html":
            sniffed = _HTMLDeclarations(raw.decode("latin1"))
            if sniffed.metas:
                in_band = sniffed.metas[0][3]
        else:
            css_match = _CSS_CHARSET.match(raw.decode("latin1"))
            if css_match is not None and css_match.end() <= 1024:
                in_band = css_match.group(1)

    encoding = bom_encoding or (
        _encoding(mime_charset) if mime_charset is not None else
        _encoding(in_band) if in_band is not None else "utf-8"
    )
    source = _decode(raw, encoding)
    if content_type == "text/css":
        return _css(source)
    try:
        return _html(source, _HTMLDeclarations(source))
    except TextNormalizationError:
        raise
    except (ValueError, UnicodeError) as exc:
        raise TextNormalizationError("Cannot safely repair HTML charset") from exc
