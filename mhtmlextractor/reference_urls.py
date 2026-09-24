"""Exact static resource identities and portable output destinations."""

from dataclasses import dataclass
from typing import Dict, Optional, Set, Tuple
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from .constants import IMAGE_EXTENSIONS


@dataclass(frozen=True)
class ResourceInfo:
    """Part provenance only; bodies remain in extracted_contents."""
    content_type: str
    location: Optional[str]
    content_id: Optional[str]
    order: int


@dataclass(frozen=True)
class _Location:
    url: str
    virtual: bool = False


# An internal urllib adapter, disjoint from real file: identities. Never emitted.
_ROOT = _Location("file:///", True)
_SCHEMES = {"http", "https", "file", "ftp"}
_SPACE = " \t\r\n\f"


def _remove_dots(path: str) -> str:
    """RFC 3986 dot removal without unquoting paths or collapsing //."""
    result = ""
    while path:
        if path.startswith("../"):
            path = path[3:]
        elif path.startswith("./"):
            path = path[2:]
        elif path.startswith("/./") or path == "/.":
            path = "/" + path[3:]
        elif path.startswith("/../") or path == "/..":
            path = "/" + path[4:]
            result = result.rsplit("/", 1)[0]
        elif path in (".", ".."):
            break
        else:
            end = path.find("/", 1 if path.startswith("/") else 0)
            if end < 0:
                result += path
                break
            result += path[:end]
            path = path[end:]
    return result


def _resolve(reference: str, base: _Location) -> Optional[_Location]:
    reference = reference.strip(_SPACE)
    try:
        parts = urlsplit(reference)
        if parts.scheme and parts.scheme not in _SCHEMES:
            return None
        if parts.netloc and not parts.scheme and base.virtual:
            return None  # No real scheme is known for //host/path.
        joined = urljoin(base.url, reference)
        resolved = urlsplit(joined)
        # urljoin discards empty segments while merging a relative path. Keep
        # them: a//b and a/b can identify distinct captured resources.
        base_parts = urlsplit(base.url)
        if parts.scheme or parts.netloc or parts.path.startswith("/"):
            path = parts.path
        elif parts.path:
            parent = base_parts.path[:base_parts.path.rfind("/") + 1]
            if base_parts.netloc and not base_parts.path:
                parent = "/"
            path = parent + parts.path
        else:
            path = base_parts.path
        empty_query = "?" in reference.split("#", 1)[0] and not parts.query
        query = "" if empty_query else resolved.query
        url = urlunsplit((resolved.scheme, resolved.netloc, _remove_dots(path), query, ""))
        if empty_query or (not query and "?" in joined.split("#", 1)[0]):
            url += "?"
        if "#" in joined:
            url += "#" + resolved.fragment
        return _Location(url, base.virtual and not parts.scheme)
    except ValueError:
        return None


def _identity(location: _Location) -> Tuple[bool, str]:
    return location.virtual, location.url.split("#", 1)[0]


def _virtual_destination(location: _Location) -> str:
    value = location.url[len("file:///"):]
    if not value or value.startswith(("/", "?", "#")) or ":" in value.split("/", 1)[0]:
        value = "./" + value
    return value


class References:
    def __init__(self, mapping: Dict[str, str], metadata: Dict[str, ResourceInfo],
                 archive_location: Optional[str], written: Optional[Set[str]],
                 no_css: bool, no_images: bool) -> None:
        self.archive_base = _resolve(archive_location or "", _ROOT) or _ROOT
        self.targets = {}  # type: Dict[Tuple[bool, str], str]
        self.cids = {}  # type: Dict[str, str]
        self.written = written
        self.no_css = no_css
        self.no_images = no_images
        # Raw-key selections stay authoritative. Resolve aliases in occurrence
        # order before write gating; otherwise failed final parts resurrect old ones.
        entries = sorted(enumerate(mapping.items()), key=lambda entry:
                         metadata[entry[1][1]].order if entry[1][1] in metadata else entry[0])
        for _, (url, filename) in entries:
            info = metadata.get(filename)
            if url.lower().startswith("cid:"):
                if info is None or (info.content_id is not None and url == "cid:" + info.content_id):
                    self.cids[url[4:]] = filename
                continue
            location = _resolve(url, self.archive_base)
            if location is not None:
                self.targets[_identity(location)] = filename

    def _eligible(self, filename: Optional[str]) -> bool:
        if filename is None or (self.written is not None and filename not in self.written):
            return False
        if self.no_css and filename.lower().endswith(".css"):
            return False
        return not (self.no_images and any(filename.lower().endswith(ext) for ext in IMAGE_EXTENSIONS))

    def for_file(self, location: Optional[str]):
        source = _resolve(location or "", self.archive_base) or self.archive_base
        bases = {}  # type: Dict[Optional[str], _Location]

        def rewrite(value: str, html_base: Optional[str] = None) -> str:
            reference = value.strip(_SPACE)
            if not reference or reference.startswith("#"):
                return value
            if reference.lower().startswith("cid:"):
                cid, separator, fragment = reference[4:].partition("#")
                try:
                    target = self.cids.get(unquote(cid, encoding="ascii", errors="strict"))
                except UnicodeError:
                    return value
                if self._eligible(target):
                    return quote(target, safe="") + (separator + fragment if separator else "")
                return value
            if html_base not in bases:
                bases[html_base] = (_resolve(html_base, source) or source) if html_base is not None else source
            resolved = _resolve(reference, bases[html_base])
            if resolved is None:
                return value
            target = self.targets.get(_identity(resolved))
            if self._eligible(target):
                _, separator, fragment = resolved.url.partition("#")
                return quote(target, safe="") + (separator + fragment if separator else "")
            if urlsplit(reference).scheme:
                return value
            return _virtual_destination(resolved) if resolved.virtual else resolved.url

        return rewrite
