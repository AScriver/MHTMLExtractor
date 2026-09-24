"""Source-preserving edits for static HTML and CSS resource references.

The caller owns URL resolution.  This module recognizes syntax, decodes values
for the caller, and escapes replacements for their original source context.
"""

import html
from html.entities import html5 as _HTML_ENTITIES
from typing import Callable, Optional


_SPACE = " \t\r\n\f"
_RAW_TEXT = frozenset(("script", "textarea", "title", "xmp", "iframe",
                       "noembed", "noframes", "plaintext"))
_HREF_TAGS = frozenset(("a", "area", "link"))
_SRC_TAGS = frozenset(("audio", "embed", "iframe", "img", "input",
                      "script", "source", "track", "video"))
_UNTERMINATED_TAG = object()


def _apply(source, edits):
    """Apply nonoverlapping source edits, retaining every other character."""
    if not edits:
        return source
    result = []
    end = 0
    for start, stop, replacement in sorted(edits, key=lambda edit: edit[0]):
        if start < end:
            raise ValueError("overlapping reference edits")
        result.extend((source[end:start], replacement))
        end = stop
    result.append(source[end:])
    return "".join(result)


def _css_escape_at(source, index):
    """Return (decoded character, next index), or None for a bad escape."""
    if index + 1 >= len(source) or source[index + 1] in "\r\n\f":
        return None
    end = index + 1
    if source[end] in "0123456789abcdefABCDEF":
        limit = min(len(source), end + 6)
        while end < limit and source[end] in "0123456789abcdefABCDEF":
            end += 1
        codepoint = int(source[index + 1:end], 16)
        if end < len(source) and source[end] in _SPACE:
            if source[end] == "\r" and end + 1 < len(source) and source[end + 1] == "\n":
                end += 1
            end += 1
        if not codepoint or codepoint > 0x10ffff or 0xd800 <= codepoint <= 0xdfff:
            codepoint = 0xfffd
        return chr(codepoint), end
    return source[end], end + 1


def _css_decode(source):
    result = []
    index = 0
    while index < len(source):
        if source[index] == "\\":
            escaped = _css_escape_at(source, index)
            if escaped is None:
                return None
            character, index = escaped
            result.append(character)
        else:
            result.append(source[index])
            index += 1
    return "".join(result)


def _css_string(source, start):
    """Read a CSS string; return (value span start, end, next) or None."""
    quote = source[start]
    index = start + 1
    while index < len(source):
        character = source[index]
        if character == quote:
            return start + 1, index, index + 1
        if character == "\\":
            if index + 1 < len(source) and source[index + 1] in "\r\n\f":
                index += 2
                if source[index - 1] == "\r" and index < len(source) and source[index] == "\n":
                    index += 1
                continue
            escaped = _css_escape_at(source, index)
            if escaped is None:
                return None
            index = escaped[1]
        elif character in "\r\n\f":
            return None
        else:
            index += 1
    return None


def _css_string_decode(source):
    # A backslash-newline is consumed without adding a character.
    result = []
    index = 0
    while index < len(source):
        if source[index] == "\\":
            if index + 1 < len(source) and source[index + 1] in "\r\n\f":
                index += 2
                if source[index - 1] == "\r" and index < len(source) and source[index] == "\n":
                    index += 1
                continue
            escaped = _css_escape_at(source, index)
            if escaped is None:
                return None
            character, index = escaped
            result.append(character)
        else:
            result.append(source[index])
            index += 1
    return "".join(result)


def _css_identifier(source, start):
    index = start
    decoded = []
    while index < len(source):
        character = source[index]
        if character.isalnum() or character in "_-" or ord(character) >= 128:
            decoded.append(character)
            index += 1
        elif character == "\\":
            escaped = _css_escape_at(source, index)
            if escaped is None:
                break
            character, index = escaped
            decoded.append(character)
        else:
            break
    return "".join(decoded), index


def _css_number_end(source, start):
    """Consume a CSS number and its optional dimension unit."""
    index = start
    if source[index] in "+-":
        index += 1
    digits_start = index
    while index < len(source) and source[index] in "0123456789":
        index += 1
    if index < len(source) and source[index] == "." and (
            index + 1 < len(source) and source[index + 1] in "0123456789"):
        index += 1
        while index < len(source) and source[index] in "0123456789":
            index += 1
    if index == digits_start:
        return start
    if index < len(source) and source[index] in "eE":
        exponent = index + 1
        if exponent < len(source) and source[exponent] in "+-":
            exponent += 1
        if exponent < len(source) and source[exponent] in "0123456789":
            index = exponent + 1
            while index < len(source) and source[index] in "0123456789":
                index += 1
    _, index = _css_identifier(source, index)
    return index


def _css_space_comments(source, index):
    while index < len(source):
        if source[index] in _SPACE:
            index += 1
        elif source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                return len(source)
            index = end + 2
        else:
            break
    return index


def _css_bad_url_end(source, index):
    """Consume a malformed URL remnant without recognizing tokens inside it."""
    while index < len(source):
        if source[index] == ")":
            return index + 1
        if source[index] == "\\":
            escaped = _css_escape_at(source, index)
            if escaped is not None:
                index = escaped[1]
                continue
        index += 1
    return index


def _css_bad_string_end(source, index):
    """A bad string ends at its first unescaped newline; an open one at EOF."""
    while index < len(source):
        if source[index] in "\r\n\f":
            return index + 1
        if source[index] == "\\":
            escaped = _css_escape_at(source, index)
            if escaped is not None:
                index = escaped[1]
                continue
        index += 1
    return index


def _css_bad_quoted_url_end(source, index):
    """Keep an invalid quoted URL opaque through its enclosing close paren."""
    quote = source[index]
    index += 1
    while index < len(source):
        if source[index] == quote:
            return _css_bad_url_end(source, index + 1)
        if source[index] == "\\":
            escaped = _css_escape_at(source, index)
            if escaped is not None:
                index = escaped[1]
                continue
        index += 1
    return index


def _css_url(source, opening):
    """Return (start, end, quote, next) for a complete CSS url() token."""
    index = opening + 1
    while index < len(source) and source[index] in _SPACE:
        index += 1
    if index >= len(source):
        return None, len(source)
    if source[index] in "\"'":
        token = _css_string(source, index)
        if token is None:
            return None, _css_bad_quoted_url_end(source, index)
        start, end, index = token
        index = _css_space_comments(source, index)
        if index < len(source) and source[index] == ")":
            return (start, end, source[start - 1], index + 1), index + 1
        return None, _css_bad_url_end(source, index)
    start = index
    while index < len(source):
        character = source[index]
        if character == ")":
            return (start, index, None, index + 1), index + 1
        if character in _SPACE:
            end = index
            while index < len(source) and source[index] in _SPACE:
                index += 1
            if index < len(source) and source[index] == ")":
                return (start, end, None, index + 1), index + 1
            return None, _css_bad_url_end(source, index)
        if character in "\"'(\r\n\f" or ord(character) < 32 or ord(character) == 127:
            return None, _css_bad_url_end(source, index)
        if character == "\\":
            escaped = _css_escape_at(source, index)
            if escaped is None:
                return None, _css_bad_url_end(source, index)
            index = escaped[1]
        else:
            index += 1
    return None, index


def _css_encode(value, quote):
    result = []
    for character in value:
        codepoint = ord(character)
        if character == "\\" or (quote and character == quote) or (
                not quote and character in "\"'() \t\r\n\f"):
            result.append("\\" + character if character not in "\r\n\f" else
                          "\\{:x} ".format(codepoint))
        elif codepoint < 32 or codepoint == 127:
            result.append("\\{:x} ".format(codepoint))
        else:
            result.append(character)
    return "".join(result)


def _css_edits(source, rewrite_url):
    edits = []
    index = 0
    while index < len(source):
        character = source[index]
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            index = len(source) if end < 0 else end + 2
            continue
        if character in "\"'":
            token = _css_string(source, index)
            index = token[2] if token else _css_bad_string_end(source, index)
            continue
        if character == "#":
            _, end = _css_identifier(source, index + 1)
            index = end if end > index + 1 else index + 1
            continue
        if character == "@":
            identifier, end = _css_identifier(source, index + 1)
            if identifier.lower() == "import":
                next_index = _css_space_comments(source, end)
                if next_index < len(source) and source[next_index] in "\"'":
                    token = _css_string(source, next_index)
                    if token is not None:
                        start, stop, after = token
                        value = _css_string_decode(source[start:stop])
                        if value is not None:
                            replacement = rewrite_url(value)
                            if replacement != value:
                                edits.append((start, stop, _css_encode(replacement, source[next_index])))
                        index = after
                        continue
                    index = _css_bad_string_end(source, next_index)
                    continue
            index = end if end > index + 1 else index + 1
            continue
        if character in "0123456789.+-":
            end = _css_number_end(source, index)
            if end > index:
                index = end
                continue
        if character.isalpha() or character in "_-\\" or ord(character) >= 128:
            identifier, end = _css_identifier(source, index)
            if end > index:
                if identifier.lower() == "url" and end < len(source) and source[end] == "(":
                    token, after = _css_url(source, end)
                    if token is not None:
                        start, stop, quote, _ = token
                        value = _css_string_decode(source[start:stop]) if quote else _css_decode(source[start:stop])
                        if value is not None:
                            replacement = rewrite_url(value)
                            if replacement != value:
                                edits.append((start, stop, _css_encode(replacement, quote)))
                    index = after
                else:
                    index = end
                continue
        index += 1
    return edits


def rewrite_css(source: str, rewrite_url: Callable[[str], str]) -> str:
    """Rewrite complete CSS url() and quoted @import values in source."""
    return _apply(source, _css_edits(source, rewrite_url))


def _html_entities_with_spans(source):
    """Decode attribute entities and map decoded characters to raw spans."""
    decoded = []
    spans = []
    index = 0
    while index < len(source):
        if source[index] == "&":
            end = index + 1
            value = None
            if end < len(source) and source[end] == "#":
                end += 1
                digits = "0123456789"
                if end < len(source) and source[end] in "xX":
                    end += 1
                    digits += "abcdefABCDEF"
                first_digit = end
                while end < len(source) and source[end] in digits:
                    end += 1
                if end > first_digit:
                    if end < len(source) and source[end] == ";":
                        end += 1
                    value = html.unescape(source[index:end])
            else:
                # In an attribute, a semicolonless named reference followed by
                # '=' or an ASCII letter/digit is literal source text.
                limit = min(len(source), index + 33)
                candidate_end = end
                while candidate_end < limit and (
                        candidate_end < len(source) and source[candidate_end] in
                        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"):
                    candidate_end += 1
                    key = source[index + 1:candidate_end]
                    if key in _HTML_ENTITIES:
                        next_character = source[candidate_end:candidate_end + 1]
                        if not next_character or next_character not in (
                                "=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"):
                            end = candidate_end
                            value = _HTML_ENTITIES[key]
                    if candidate_end < len(source) and source[candidate_end] == ";":
                        key += ";"
                        if key in _HTML_ENTITIES:
                            end = candidate_end + 1
                            value = _HTML_ENTITIES[key]
                        break
            if value is not None:
                decoded.append(value)
                spans.extend((index, end) for _ in value)
                index = end
                continue
        decoded.append(source[index])
        spans.append((index, index + 1))
        index += 1
    return "".join(decoded), spans


def _html_encode(value, quote):
    value = value.replace("&", "&amp;")
    if quote == '"':
        return value.replace('"', "&quot;")
    if quote == "'":
        return value.replace("'", "&#39;")
    result = []
    for character in value:
        if character in _SPACE or character in "\"'`=<>/":
            result.append("&#{};".format(ord(character)))
        else:
            result.append(character)
    return "".join(result)


def _html_tag(source, start):
    """Parse one markup tag with exact attribute value spans."""
    index = start + 1
    closing = index < len(source) and source[index] == "/"
    if closing:
        index += 1
    if index >= len(source) or not source[index].isalpha() or ord(source[index]) >= 128:
        return None
    name_start = index
    while index < len(source) and (source[index].isalnum() or source[index] in ":-_"):
        index += 1
    name = source[name_start:index].lower()
    if index < len(source) and source[index] not in _SPACE + "/>":
        return _UNTERMINATED_TAG
    attributes = []
    while index < len(source):
        while index < len(source) and source[index] in _SPACE:
            index += 1
        if index >= len(source):
            return _UNTERMINATED_TAG
        if source[index] == ">":
            return name, closing, attributes, index + 1
        if source[index] == "/" and index + 1 < len(source) and source[index + 1] == ">":
            return name, closing, attributes, index + 2
        if source[index] == "/":
            index += 1
            continue
        attr_start = index
        while index < len(source) and source[index] not in _SPACE + '=/>"\'<' :
            index += 1
        if index == attr_start:
            index += 1
            continue
        attr_name = source[attr_start:index].lower()
        while index < len(source) and source[index] in _SPACE:
            index += 1
        value_start = value_end = None
        quote = None
        if index < len(source) and source[index] == "=":
            index += 1
            while index < len(source) and source[index] in _SPACE:
                index += 1
            if index >= len(source):
                return _UNTERMINATED_TAG
            if source[index] in "\"'":
                quote = source[index]
                value_start = index + 1
                value_end = source.find(quote, value_start)
                if value_end < 0:
                    return _UNTERMINATED_TAG
                index = value_end + 1
            else:
                value_start = index
                while index < len(source) and source[index] not in _SPACE + ">":
                    index += 1
                value_end = index
        attributes.append((attr_name, attr_start, index, value_start, value_end, quote))
    return _UNTERMINATED_TAG


def _raw_end(source, start, name):
    lower = source.lower()
    marker = "</" + name
    index = lower.find(marker, start)
    while index >= 0:
        after = index + len(marker)
        if after >= len(source) or source[after] in _SPACE + "/>":
            return index
        index = lower.find(marker, after)
    return len(source)


def _html_tokens(source):
    """Yield actual HTML start tags and style block spans, excluding raw/foreign text."""
    index = 0
    foreign = []
    while index < len(source):
        start = source.find("<", index)
        if start < 0:
            return
        if source.startswith("<!--", start):
            end = source.find("-->", start + 4)
            index = len(source) if end < 0 else end + 3
            continue
        if source.startswith("<!", start) or source.startswith("<?", start):
            end = source.find(">", start + 2)
            index = len(source) if end < 0 else end + 1
            continue
        token = _html_tag(source, start)
        if token is _UNTERMINATED_TAG:
            return
        if token is None:
            index = start + 1
            continue
        name, closing, attributes, end = token
        if foreign:
            if closing:
                if name in foreign:
                    foreign = foreign[:foreign.index(name)]
            elif name in ("svg", "math") and source[end - 2:end] != "/>":
                foreign.append(name)
            index = end
            continue
        if not closing:
            if name in ("svg", "math"):
                if source[end - 2:end] != "/>":
                    foreign.append(name)
            else:
                yield name, attributes, None
                if name == "style":
                    close = _raw_end(source, end, name)
                    yield None, None, (end, close)
                    index = close
                    continue
                if name in _RAW_TEXT:
                    index = len(source) if name == "plaintext" else _raw_end(source, end, name)
                    continue
        index = end


def rewrite_html(source: str,
                 rewrite_url: Callable[[str, Optional[str]], str]) -> str:
    """Rewrite supported static HTML references and remove all base hrefs.

    ``rewrite_url`` receives the decoded complete URL value and the first HTML
    base href (or None).  It returns a semantic URL, which this layer escapes
    for the original HTML or embedded CSS context.
    """
    tokens = list(_html_tokens(source))
    first_base = None
    for name, attributes, _ in tokens:
        if name == "base":
            for attr_name, _, _, start, stop, _ in attributes:
                if attr_name == "href":
                    first_base = _html_entities_with_spans(source[start:stop])[0] if start is not None else ""
                    break
            if first_base is not None:
                break
    edits = []
    for name, attributes, style_span in tokens:
        if style_span is not None:
            start, stop = style_span
            edits.extend((start + a, start + b, c) for a, b, c in _css_edits(
                source[start:stop], lambda value: rewrite_url(value, first_base)))
            continue
        seen = set()
        for attr_name, attr_start, attr_end, start, stop, quote in attributes:
            if name == "base" and attr_name == "href":
                edits.append((attr_start, attr_end, ""))
                continue
            if attr_name in seen:
                continue
            seen.add(attr_name)
            if start is None:
                continue
            supported = ((attr_name == "href" and name in _HREF_TAGS) or
                         (attr_name == "src" and name in _SRC_TAGS) or
                         (attr_name == "poster" and name == "video") or
                         (attr_name == "data" and name == "object"))
            if supported:
                value = _html_entities_with_spans(source[start:stop])[0]
                replacement = rewrite_url(value, first_base)
                if replacement != value:
                    edits.append((start, stop, _html_encode(replacement, quote)))
            elif attr_name == "style":
                decoded, spans = _html_entities_with_spans(source[start:stop])
                for css_start, css_stop, css_replacement in _css_edits(
                        decoded, lambda value: rewrite_url(value, first_base)):
                    if css_start == css_stop:
                        continue
                    raw_start = spans[css_start][0]
                    raw_stop = spans[css_stop - 1][1]
                    edits.append((start + raw_start, start + raw_stop,
                                  _html_encode(css_replacement, quote)))
    return _apply(source, edits)
