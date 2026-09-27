"""The docs freshness probe's HTTP and sitemap half (contracts.md §8.75(i)).

:class:`HttpProbe` is one bounded ``httpx`` client: a conditional ``GET`` per page that reads no
body, and a size-capped text fetch for the site inventory (``sitemap.xml`` / ``llms.txt``). Only
the documented ``httpx`` failure roots (``HTTPError``, ``InvalidURL``) become :class:`ProbeError`;
nothing broader is caught. Accepted leniency: httpx reads intermediate redirect bodies before
handing over the final response — bounded by :data:`REDIRECT_LIMIT` hops, small in practice.

:func:`inventory_fingerprint` is the ``weak`` evidence tier: a hash of the sitemap's
``(loc, lastmod)`` set and/or the ``llms.txt`` body — never an HTML body.
"""

import hashlib
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from types import TracebackType
from typing import Self

import httpx

from perk import __version__

DOCS_REQUEST_TIMEOUT = 10.0  # seconds, httpx per-operation
DOCS_ENTRY_BUDGET = 60.0  # seconds of wall clock per docs entry, checked between requests
DOCS_PAGE_PROBE_LIMIT = 20  # page requests per entry, the seed included
PAGE_ERROR_STOP = 3  # consecutive page transport errors abandon the remaining pages
REDIRECT_LIMIT = 5
SITEMAP_CHILD_LIMIT = 5  # child sitemaps followed from a sitemap index
INVENTORY_BODY_LIMIT = 2 * 1024 * 1024  # bytes read from one inventory response


class ProbeError(Exception):
    """A page or inventory request that produced no HTTP status (transport, redirect loop,
    invalid URL)."""


@dataclass(frozen=True)
class PageResponse:
    status: int
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class TextResponse:
    """``body`` is ``None`` for a non-200 status or a body over :data:`INVENTORY_BODY_LIMIT`."""

    status: int
    body: bytes | None


@dataclass(frozen=True)
class SitemapDoc:
    """A parsed sitemap: ``urls`` from a ``<urlset>``, ``children`` from a ``<sitemapindex>``."""

    urls: tuple[tuple[str, str | None], ...]
    children: tuple[str, ...]


class HttpProbe:
    """One bounded HTTP client for a ``check`` run (a context manager).

    ``transport`` is the test seam (an ``httpx.MockTransport``); ``clock`` is the monotonic
    clock the per-entry wall-clock budget reads.
    """

    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.clock = clock
        self._client = httpx.Client(
            timeout=httpx.Timeout(DOCS_REQUEST_TIMEOUT),
            follow_redirects=True,
            max_redirects=REDIRECT_LIMIT,
            headers={"User-Agent": f"perk-librarian/{__version__}"},
            transport=transport,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._client.close()

    def page(self, url: str, *, etag: str | None, last_modified: str | None) -> PageResponse:
        """A conditional ``GET`` of ``url`` that reads no body.

        Validators travel as latin-1 text — a 1:1 map of the header's raw bytes — so an
        obs-text validator round-trips byte-exactly into the next conditional request. A
        recorded value outside latin-1 (never produced here) cannot be sent: ``ProbeError``.
        """
        headers: dict[bytes, bytes] = {}
        try:
            if etag is not None:
                headers[b"If-None-Match"] = etag.encode("latin-1")
            if last_modified is not None:
                headers[b"If-Modified-Since"] = last_modified.encode("latin-1")
        except UnicodeEncodeError as exc:
            raise ProbeError(
                f"{url}: the recorded validator cannot be sent as a header ({exc})"
            ) from exc
        try:
            with self._client.stream("GET", url, headers=headers) as response:
                return PageResponse(
                    status=response.status_code,
                    etag=_raw_header(response, b"etag"),
                    last_modified=_raw_header(response, b"last-modified"),
                )
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise _probe_error(url, exc) from exc

    def text(self, url: str) -> TextResponse:
        """``GET`` ``url`` reading at most :data:`INVENTORY_BODY_LIMIT` bytes of a 200 body."""
        try:
            with self._client.stream("GET", url) as response:
                if response.status_code != 200:
                    return TextResponse(status=response.status_code, body=None)
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > INVENTORY_BODY_LIMIT:
                        return TextResponse(status=200, body=None)
                    chunks.append(chunk)
                return TextResponse(status=200, body=b"".join(chunks))
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise _probe_error(url, exc) from exc


def _raw_header(response: httpx.Response, name: bytes) -> str | None:
    """The first ``name`` header's raw bytes as latin-1 text (a 1:1 byte map)."""
    for key, value in response.headers.raw:
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _probe_error(url: str, exc: Exception) -> ProbeError:
    return ProbeError(f"{url}: {type(exc).__name__}: {exc}")


def _local(tag: str) -> str:
    """An element's local name (namespace-agnostic)."""
    return tag.rpartition("}")[2]


def _child_text(element: ElementTree.Element, name: str) -> str | None:
    for child in element:
        if _local(child.tag) == name:
            text = (child.text or "").strip()
            return text or None
    return None


def parse_sitemap(body: bytes) -> SitemapDoc | None:
    """Parse a ``<urlset>`` or ``<sitemapindex>``; ``None`` when unparseable or neither.

    A document declaring a DOCTYPE is refused (sitemaps never carry one — the entity-expansion
    guard for an untrusted body). Besides ``ParseError``, the parser raises ``LookupError`` for
    an unknown or non-text declared encoding and ``ValueError`` for a multi-byte one; all three
    mean "not a parseable sitemap".
    """
    if b"<!DOCTYPE" in body.upper():
        return None
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, LookupError, ValueError):
        return None
    kind = _local(root.tag)
    if kind == "urlset":
        urls = tuple(
            (loc, _child_text(element, "lastmod"))
            for element in root
            if _local(element.tag) == "url" and (loc := _child_text(element, "loc")) is not None
        )
        return SitemapDoc(urls=urls, children=())
    if kind == "sitemapindex":
        children = tuple(
            loc
            for element in root
            if _local(element.tag) == "sitemap" and (loc := _child_text(element, "loc")) is not None
        )
        return SitemapDoc(urls=(), children=children)
    return None


def inventory_fingerprint(
    sitemap_urls: Iterable[tuple[str, str | None]], llms_body: bytes | None
) -> str | None:
    """``sitemap=<sha256>`` over the sorted ``loc\\tlastmod`` lines (when any URL parsed) and
    ``llms=<sha256>`` of the ``llms.txt`` body (when fetched), ``;``-joined; ``None`` when
    neither."""
    parts: list[str] = []
    lines = sorted(f"{loc}\t{lastmod or ''}" for loc, lastmod in sitemap_urls)
    if lines:
        parts.append(f"sitemap={hashlib.sha256('\n'.join(lines).encode()).hexdigest()}")
    if llms_body is not None:
        parts.append(f"llms={hashlib.sha256(llms_body).hexdigest()}")
    return ";".join(parts) or None
