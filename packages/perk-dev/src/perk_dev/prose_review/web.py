"""The Prose Review Workbench HTTP layer: a loopback-only FastAPI app in a security guard.

The exported :func:`create_app` returns the FastAPI app wrapped in
:class:`SecurityGuardMiddleware` — the guard sits OUTSIDE Starlette's
``ServerErrorMiddleware``, so even a framework-generated 500 from an unhandled handler
exception carries the security headers. The guard applies only to HTTP scopes; every
other scope (lifespan, websocket) passes through untouched — the inner app registers no
websocket routes, so Starlette rejects any handshake, and a future node adding
websockets must give them their own guard policy first. Pure ASGI keeps the guard
streaming-transparent.

Handlers query the ``CatalogSnapshot`` and respond with ``*Out`` models only — a
handler may look up domain values and hand them to a ``from_domain`` constructor, but
no domain object is ever serialized into a response body. File reads fall into
exactly two families: built-asset reads
(``index.html`` included) go through the contained-read helper that proves both the
dist root and the candidate sit under the repository root of trust (a symlinked
``dist/`` must not launder outside targets in); canonical-source reads go through the
SourceAdapter (:mod:`perk_dev.prose_review.source_adapter`) — root-bound,
catalog-membership-checked, and text-only.
"""

import json
import secrets
from collections.abc import Awaitable, Callable, MutableMapping
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response

from perk_dev.prose_map.models import Audience, ProseKind, ProseRole
from perk_dev.prose_review import search as search_module
from perk_dev.prose_review import source_adapter
from perk_dev.prose_review.catalog import CatalogSnapshot
from perk_dev.prose_review.dto import (
    CapabilityTreeOut,
    CatalogSummaryOut,
    SearchOut,
    UnitInspectOut,
    UnitSourceOut,
)
from perk_dev.prose_review.source_adapter import SourceReadError, SourceReadFailure

# One fixed 404 detail per closed read-failure reason. Containment failures stay
# indistinguishable from missing files (the no-leak posture).
_SOURCE_READ_DETAILS: dict[SourceReadFailure, str] = {
    "unknown_unit": "unknown unit",
    "not_found": "source not found",
    "not_text": "source is not utf-8 text",
}

# The ASGI vocabulary (identical to the spec's shapes) — local aliases so this module
# depends only on the declared fastapi/uvicorn deps, not transitively on starlette.
type Scope = MutableMapping[str, Any]
type Message = MutableMapping[str, Any]
type Receive = Callable[[], Awaitable[Message]]
type Send = Callable[[Message], Awaitable[None]]
type AsgiApp = Callable[[Scope, Receive, Send], Awaitable[None]]

CSRF_HEADER = "X-Prose-Review-Csrf"
CSRF_PLACEHOLDER = "__PROSE_REVIEW_CSRF__"

# The guard's raw-scope matcher is derived from the one header-name SSOT above (ASGI
# header names arrive lowercased).
_CSRF_HEADER_BYTES = CSRF_HEADER.lower().encode("ascii")

_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)

# Stamped on EVERY HTTP response — rejections, 404s, and framework-generated 500s alike.
_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"content-security-policy", _CSP.encode("ascii")),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
)

# Explicit Content-Type map for served build assets; anything unlisted is an opaque blob.
_CONTENT_TYPES: dict[str, str] = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}


def read_contained(repo_resolved: Path, dist_dir: Path, relative: str) -> bytes | None:
    """Read ``relative`` under ``dist_dir`` only if the whole chain stays contained.

    The dist root is re-resolved per read and must itself sit under the resolved
    repository root — trusting the subdir alone would let an escaping ``dist/`` (or
    ``dist/assets/``) symlink launder outside targets into the trusted root. The
    candidate must then resolve under the resolved dist root and be a regular file.
    Any containment failure (or read race) is ``None``; policy (404 vs 500) stays with
    the routes. The whole chain sits inside one failure boundary: ``relative`` is
    URL-controlled (uvicorn percent-decodes request paths), so an OS-invalid path — an
    embedded NUL (``ValueError``), a symlink loop or a mid-read race (``OSError``) —
    must degrade to ``None``, never an unhandled 500.
    """
    try:
        dist_resolved = dist_dir.resolve()
        if not dist_resolved.is_relative_to(repo_resolved):
            return None
        candidate = (dist_resolved / relative).resolve()
        if not candidate.is_relative_to(dist_resolved):
            return None
        if not candidate.is_file():
            return None
        return candidate.read_bytes()
    except (OSError, ValueError):
        return None


async def _reject(send: Send, detail: str) -> None:
    """Send a self-built 403 JSON rejection that carries the security headers."""
    body = json.dumps({"detail": detail}).encode("ascii")
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                *_SECURITY_HEADERS,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class SecurityGuardMiddleware:
    """The outermost pure-ASGI security envelope (HTTP scopes only).

    Order matters: Host exact-match, then Origin (when present), then the CSRF token
    for any method outside GET/HEAD — and only then forward, stamping the security
    headers onto ``http.response.start``. ASGI header names are already lowercased
    bytes, so raw-scope collection sees every spelling of a duplicated header.
    """

    def __init__(self, app: AsgiApp, *, allowed_host: str, csrf_token: str) -> None:
        self._app = app
        self._allowed_host = allowed_host.encode("ascii")
        self._allowed_origin = f"http://{allowed_host}".encode("ascii")
        self._csrf_token = csrf_token.encode("ascii")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers: list[tuple[bytes, bytes]] = list(scope["headers"])
        # Exactly one Host header, byte-equal to the one printed origin — `localhost`
        # spellings, foreign hosts, and a missing port are all rejected.
        hosts = [value for name, value in headers if name == b"host"]
        if hosts != [self._allowed_host]:
            await _reject(send, "forbidden host")
            return
        origins = [value for name, value in headers if name == b"origin"]
        if origins and origins != [self._allowed_origin]:
            await _reject(send, "forbidden origin")
            return
        if scope["method"] not in ("GET", "HEAD"):
            tokens = [value for name, value in headers if name == _CSRF_HEADER_BYTES]
            # Exactly one header, constant-time-equal to the process token: zero,
            # duplicate, and wrong-valued headers are all 403.
            if len(tokens) != 1 or not secrets.compare_digest(tokens[0], self._csrf_token):
                await _reject(send, "forbidden csrf token")
                return

        async def send_stamped(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *_SECURITY_HEADERS]
            await send(message)

        await self._app(scope, receive, send_stamped)


def create_app(
    *,
    snapshot: CatalogSnapshot,
    repo_root: Path,
    dist_dir: Path,
    allowed_host: str,
    csrf_token: str,
) -> SecurityGuardMiddleware:
    """Build the guard-wrapped workbench app over one immutable catalog snapshot.

    ``repo_root`` is resolved once here (the root of trust); ``dist_dir`` is kept
    unresolved and re-resolved per read by :func:`read_contained`. The default
    framework surfaces are disabled: ``/docs``/``/redoc`` load CDN-hosted UI assets
    (violating the no-network-loaded-assets envelope), and ``/openapi.json`` — though
    locally generated — is an unused machine-readable surface this app never serves.
    """
    repo_resolved = repo_root.resolve()
    # The snapshot is immutable, so the tree DTO and the search index are computed
    # exactly once.
    tree = CapabilityTreeOut.from_domain(snapshot)
    search_index = search_module.build_search_index(snapshot)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        raw = read_contained(repo_resolved, dist_dir, "index.html")
        if raw is None:
            raise HTTPException(status_code=500, detail="frontend not built or not contained")
        return HTMLResponse(raw.decode("utf-8").replace(CSRF_PLACEHOLDER, csrf_token))

    @app.get("/api/catalog/summary", response_model=CatalogSummaryOut)
    def catalog_summary() -> CatalogSummaryOut:
        return CatalogSummaryOut.from_domain(snapshot)

    @app.get("/api/catalog/tree", response_model=CapabilityTreeOut)
    def catalog_tree() -> CapabilityTreeOut:
        return tree

    @app.get("/api/inspect", response_model=UnitInspectOut)
    def inspect(unit: str) -> UnitInspectOut:
        routed = snapshot.get_unit(unit)
        if routed is None:
            # The /api/source no-leak posture: one fixed detail for an unknown unit.
            raise HTTPException(status_code=404, detail="unknown unit")
        return UnitInspectOut.from_domain(snapshot, routed)

    @app.get("/api/search", response_model=SearchOut)
    def catalog_search(
        q: str = "",
        audience: Audience | None = None,
        role: ProseRole | None = None,
        kind: ProseKind | None = None,
    ) -> SearchOut:
        return SearchOut.from_domain(
            search_module.search(search_index, q, audience=audience, role=role, kind=kind)
        )

    @app.get("/api/source", response_model=UnitSourceOut)
    def source(unit: str) -> UnitSourceOut:
        try:
            whole = source_adapter.read_whole_file(snapshot, repo_resolved, unit)
        except SourceReadError as exc:
            raise HTTPException(status_code=404, detail=_SOURCE_READ_DETAILS[exc.reason]) from exc
        return UnitSourceOut.from_domain(whole)

    @app.get("/assets/{asset_path:path}")
    def asset(asset_path: str) -> Response:
        raw = read_contained(repo_resolved, dist_dir, f"assets/{asset_path}")
        if raw is None:
            raise HTTPException(status_code=404, detail="not found")
        media_type = _CONTENT_TYPES.get(
            PurePosixPath(asset_path).suffix, "application/octet-stream"
        )
        return Response(content=raw, media_type=media_type)

    return SecurityGuardMiddleware(app, allowed_host=allowed_host, csrf_token=csrf_token)
