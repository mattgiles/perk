"""The Prose Review Workbench HTTP layer: a loopback-only FastAPI app in a security guard.

The exported :func:`create_app` returns the FastAPI app wrapped in
:class:`SecurityGuardMiddleware` — the guard sits OUTSIDE Starlette's
``ServerErrorMiddleware``, so even a framework-generated 500 from an unhandled handler
exception carries the security headers. The guard applies only to HTTP scopes; every
other scope (lifespan, websocket) passes through untouched — the inner app registers no
websocket routes, so Starlette rejects any handshake, and a future node adding
websockets must give them their own guard policy first. Pure ASGI keeps the guard
streaming-transparent.

Handlers capture the app's current immutable catalog generation and respond with
``*Out`` models only — a handler may look up domain values and hand them to a
``from_domain`` constructor, but
no domain object is ever serialized into a response body. Repository-content reads
fall into exactly two families: built-asset reads (``index.html`` included) go through
the contained-read helper that proves both the dist root and the candidate sit under
the repository root of trust (a symlinked ``dist/`` must not launder outside targets
in); canonical-source reads go through the SourceAdapter
(:mod:`perk_dev.prose_review.source_adapter`) — root-bound, catalog-membership-checked,
and text-only. The TypeScript adapter's random temporary snapshot is controlled IPC
over that already-authorized text, not another repository-content read family.
"""

import json
import logging
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, MutableMapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import Field, field_validator

from perk.boundary import StrictInputModel
from perk_dev.prose_map.models import Audience, ProseKind, ProseRole
from perk_dev.prose_review import comparison as comparison_module
from perk_dev.prose_review import search as search_module
from perk_dev.prose_review import source_adapter
from perk_dev.prose_review.assembly import (
    AssemblyRenderer,
    AssemblyRenderError,
    AssemblyRenderErrorReason,
    PresentationOverrides,
    WorkspaceBuffer,
)
from perk_dev.prose_review.catalog import CatalogSnapshot, load_catalog
from perk_dev.prose_review.checks import (
    CheckCommand,
    CheckId,
    CheckRunner,
    UnknownCheckError,
)
from perk_dev.prose_review.dto import (
    AssemblyOptionsOut,
    AssemblyRenderOut,
    CapabilityTreeOut,
    CatalogSummaryOut,
    CheckRunOut,
    ComparisonOptionsOut,
    LatestCheckOut,
    SearchOut,
    SourceSaveOut,
    SourceViewOut,
    UnitInspectOut,
    UnitSourceOut,
    source_save_out,
)
from perk_dev.prose_review.source_adapter import (
    SourceReadError,
    SourceReadFailure,
    SourceRefused,
    SourceSaved,
)
from perk_dev.prose_review.source_adapter.typescript import TypeScriptSourceAdapter
from perk_dev.prose_review.source_adapter.write import CATALOG_STALE_DETAIL

logger = logging.getLogger(__name__)

# One fixed 404 detail per closed read-failure reason. Containment failures stay
# indistinguishable from missing files (the no-leak posture).
_SOURCE_READ_DETAILS: dict[SourceReadFailure, str] = {
    "unknown_unit": "unknown unit",
    "unknown_fragment": "unknown fragment",
    "not_found": "source not found",
    "not_text": "source is not utf-8 text",
}

# Fixed status/detail per closed request-wide render failure: selection failures share one
# no-leak 404, workspace-record failures share one 422. These happen before any source work
# and never masquerade as a layer result.
_ASSEMBLY_RENDER_ERROR_RESPONSES: dict[AssemblyRenderErrorReason, tuple[int, str]] = {
    "unknown-assembly": (404, "unknown assembly render subject"),
    "unknown-scenario": (404, "unknown assembly render subject"),
    "scenario-assembly-mismatch": (404, "unknown assembly render subject"),
    "duplicate-workspace-path": (422, "invalid workspace buffers"),
    "unknown-workspace-path": (422, "invalid workspace buffers"),
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


class SourceProjectionInput(StrictInputModel):
    """The exact machine-authored body for stateless source projection."""

    unit: str
    fragment: str | None
    text: str


class SourceSaveInput(StrictInputModel):
    """The path-incapable reviewed whole-buffer save request."""

    unit: str
    load_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str


class AssemblyPresentationInput(StrictInputModel):
    """Required-key nullable presentation overrides (null = the scenario default)."""

    include_ambient: bool | None
    include_tools: bool | None


class AssemblyWorkspaceBufferInput(StrictInputModel):
    """One path-keyed browser workspace buffer (structural validation only)."""

    path: str = Field(min_length=1)
    text: str

    @field_validator("path", "text")
    @classmethod
    def _require_unicode_scalars(cls, value: str) -> str:
        # The one Unicode-scalar boundary rule: an unpaired surrogate delivered as a JSON
        # escape must 422 here, before any handler logic — canonical reads are already
        # strict UTF-8 and scenario variables are authored catalog strings, so every
        # accepted render's response text stays UTF-8-serializable.
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("workspace text must be UTF-8-encodable Unicode scalars") from exc
        return value


class AssemblyRenderInput(StrictInputModel):
    """The exact strict assembly render request body."""

    assembly: str = Field(min_length=1)
    scenario: str = Field(min_length=1)
    presentation: AssemblyPresentationInput
    buffers: list[AssemblyWorkspaceBufferInput]


class CheckRunInput(StrictInputModel):
    """The check-start request: one closed allowlist id, zero request-derived argv."""

    check: CheckId


@dataclass(frozen=True, slots=True)
class _CatalogGeneration:
    snapshot: CatalogSnapshot
    tree: CapabilityTreeOut
    search_index: tuple[search_module.SearchEntry, ...]

    @classmethod
    def build(cls, snapshot: CatalogSnapshot) -> "_CatalogGeneration":
        return cls(
            snapshot=snapshot,
            tree=CapabilityTreeOut.from_domain(snapshot),
            search_index=search_module.build_search_index(snapshot),
        )


class _CatalogState:
    """One swappable read generation plus the serialized source-transaction state.

    ``source_transaction_mutex`` linearizes every save AND every assembly render:
    a save atomically replaces source before the catalog reload/generation swap, so
    an unserialized render could pair an old snapshot with replaced bytes. Ordinary
    read/projection endpoints still capture ``generation`` without the mutex.
    """

    def __init__(self, generation: _CatalogGeneration) -> None:
        self.generation = generation
        self.writes_frozen = False
        self.source_transaction_mutex = Lock()


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
    selector_root: Path,
    dist_dir: Path,
    allowed_host: str,
    csrf_token: str,
    reload_catalog: Callable[[Path], CatalogSnapshot] | None = None,
    check_commands: Mapping[CheckId, CheckCommand] | None = None,
) -> SecurityGuardMiddleware:
    """Build the guarded app over an app-scoped, swappable immutable catalog generation.

    ``repo_root`` is resolved once here (the source root of trust); ``selector_root``
    locates fixed helper code and dependencies separately; ``dist_dir`` is kept
    unresolved and re-resolved per read by :func:`read_contained`. The default
    framework surfaces are disabled: ``/docs``/``/redoc`` load CDN-hosted UI assets
    (violating the no-network-loaded-assets envelope), and ``/openapi.json`` — though
    locally generated — is an unused machine-readable surface this app never serves.
    """
    repo_resolved = repo_root.resolve()
    typescript_adapter = TypeScriptSourceAdapter(selector_root)
    # The renderer reuses the one app-scoped TypeScript adapter so its helper slot stays
    # a real cross-operation resource bound (never a render-only helper instance).
    renderer = AssemblyRenderer(repo_resolved, typescript_adapter)
    state = _CatalogState(_CatalogGeneration.build(snapshot))
    reload_snapshot = load_catalog if reload_catalog is None else reload_catalog
    # The app-lifetime CheckRunner; `check_commands` is the test seam (the
    # `reload_catalog` pattern). Check runs are isolated from the source transaction:
    # they never take `source_transaction_mutex`, never touch the catalog generation,
    # and stay permitted while writes are frozen (read-only and useful for diagnosis).
    runner = CheckRunner(repo_resolved, commands=check_commands)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # uvicorn's graceful shutdown runs this, so the launcher never leaks a
        # running check; the outer guard passes lifespan scopes through untouched.
        yield
        runner.shutdown()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        # The framework 422 without the default raw-input echo: request text is
        # untrusted and may carry unpaired surrogates (delivered as JSON escapes) that
        # Starlette's UTF-8 JSON encoding cannot serialize — echoing it back would turn
        # a strict rejection into a 500. loc/msg/type keep the 422 diagnosable.
        errors = [
            {key: value for key, value in error.items() if key not in ("input", "ctx")}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        raw = read_contained(repo_resolved, dist_dir, "index.html")
        if raw is None:
            raise HTTPException(status_code=500, detail="frontend not built or not contained")
        return HTMLResponse(raw.decode("utf-8").replace(CSRF_PLACEHOLDER, csrf_token))

    @app.get("/api/catalog/summary", response_model=CatalogSummaryOut)
    def catalog_summary() -> CatalogSummaryOut:
        generation = state.generation
        return CatalogSummaryOut.from_domain(generation.snapshot)

    @app.get("/api/catalog/tree", response_model=CapabilityTreeOut)
    def catalog_tree() -> CapabilityTreeOut:
        generation = state.generation
        return generation.tree

    @app.get("/api/inspect", response_model=UnitInspectOut)
    def inspect(unit: str) -> UnitInspectOut:
        generation = state.generation
        routed = generation.snapshot.get_unit(unit)
        if routed is None:
            # The /api/source no-leak posture: one fixed detail for an unknown unit.
            raise HTTPException(status_code=404, detail="unknown unit")
        return UnitInspectOut.from_domain(generation.snapshot, routed)

    @app.get("/api/compare", response_model=ComparisonOptionsOut)
    def compare(
        unit: str,
        shape: str | None = None,
        position: int | None = None,
    ) -> ComparisonOptionsOut:
        generation = state.generation
        options = comparison_module.comparison_options(
            generation.snapshot,
            unit,
            shape_id=shape,
            position=position,
        )
        if options is None:
            raise HTTPException(status_code=404, detail="unknown comparison subject")
        return ComparisonOptionsOut.from_domain(options)

    @app.get("/api/search", response_model=SearchOut)
    def catalog_search(
        q: str = "",
        audience: Audience | None = None,
        role: ProseRole | None = None,
        kind: ProseKind | None = None,
    ) -> SearchOut:
        generation = state.generation
        return SearchOut.from_domain(
            search_module.search(
                generation.search_index,
                q,
                audience=audience,
                role=role,
                kind=kind,
            )
        )

    @app.get("/api/source", response_model=UnitSourceOut)
    def source(unit: str, fragment: str | None = None) -> UnitSourceOut:
        generation = state.generation
        try:
            loaded = source_adapter.read_source(
                generation.snapshot,
                repo_resolved,
                unit,
                fragment,
                typescript_adapter=typescript_adapter,
            )
        except SourceReadError as exc:
            raise HTTPException(status_code=404, detail=_SOURCE_READ_DETAILS[exc.reason]) from exc
        return UnitSourceOut.from_domain(loaded)

    @app.post("/api/source/project", response_model=SourceViewOut)
    def project_source(request: SourceProjectionInput) -> SourceViewOut:
        generation = state.generation
        try:
            view = source_adapter.project_source(
                generation.snapshot,
                request.unit,
                request.fragment,
                request.text,
                typescript_adapter=typescript_adapter,
            )
        except SourceReadError as exc:
            raise HTTPException(status_code=404, detail=_SOURCE_READ_DETAILS[exc.reason]) from exc
        return SourceViewOut.from_domain(view)

    @app.get("/api/assembly/options", response_model=AssemblyOptionsOut)
    def assembly_options(assembly: str) -> AssemblyOptionsOut:
        generation = state.generation
        view = generation.snapshot.get_assembly(assembly)
        if view is None:
            raise HTTPException(status_code=404, detail="unknown assembly")
        return AssemblyOptionsOut.from_domain(view)

    @app.post("/api/assembly/render", response_model=AssemblyRenderOut)
    def assembly_render(request: AssemblyRenderInput) -> AssemblyRenderOut:
        overrides = PresentationOverrides(
            include_ambient=request.presentation.include_ambient,
            include_tools=request.presentation.include_tools,
        )
        buffers = tuple(
            WorkspaceBuffer(path=record.path, text=record.text) for record in request.buffers
        )
        # The whole render is one source transaction relative to Workbench saves: the
        # captured generation and every canonical read/gate/prompt render/extraction —
        # through response conversion — happen under the mutex, so one graph generation
        # and source-byte interval back every successful response.
        with state.source_transaction_mutex:
            if state.writes_frozen:
                # The old generation must never be combined with source bytes left by a
                # save whose refresh failed: refuse before any source read.
                raise HTTPException(status_code=409, detail="catalog stale")
            generation = state.generation
            try:
                rendered = renderer.render(
                    generation.snapshot,
                    assembly_id=request.assembly,
                    scenario_id=request.scenario,
                    presentation=overrides,
                    workspace_buffers=buffers,
                )
            except AssemblyRenderError as exc:
                status_code, detail = _ASSEMBLY_RENDER_ERROR_RESPONSES[exc.reason]
                raise HTTPException(status_code=status_code, detail=detail) from exc
            return AssemblyRenderOut.from_domain(rendered)

    @app.post("/api/source/save", response_model=SourceSaveOut)
    def save_source(request: SourceSaveInput) -> SourceSaveOut:
        with state.source_transaction_mutex:
            generation = state.generation
            if state.writes_frozen:
                return source_save_out(
                    SourceRefused(
                        status="refused",
                        reason="catalog-stale",
                        detail=CATALOG_STALE_DETAIL,
                    )
                )
            if generation.snapshot.get_unit(request.unit) is None:
                raise HTTPException(status_code=404, detail="unknown unit")
            result = source_adapter.save_source(
                generation.snapshot,
                repo_resolved,
                request.unit,
                request.load_hash,
                request.text,
                typescript_adapter=typescript_adapter,
            )
            if isinstance(result, SourceSaved):
                try:
                    refreshed = reload_snapshot(repo_resolved)
                    replacement = _CatalogGeneration.build(refreshed)
                except Exception:
                    # Replacement has committed, so every refresh failure must freeze writes even
                    # when a parser or generation constructor missed the catalog error taxonomy.
                    logger.exception("catalog refresh failed after source save")
                    state.writes_frozen = True
                    result = replace(
                        result,
                        catalog_refreshed=False,
                        refresh_detail=CATALOG_STALE_DETAIL,
                    )
                else:
                    state.generation = replacement
            return source_save_out(result)

    @app.post("/api/checks/run", response_model=CheckRunOut)
    def start_check(request: CheckRunInput) -> CheckRunOut:
        try:
            started = runner.start(request.check)
        except UnknownCheckError as exc:
            # Reachable only with a partial injected mapping: the Literal boundary
            # already 422s ids outside the closed vocabulary.
            raise HTTPException(status_code=404, detail="unknown check") from exc
        if started is None:
            raise HTTPException(status_code=409, detail="check already running")
        return CheckRunOut.from_domain(started, 0)

    @app.get("/api/checks/run/{run_id}", response_model=CheckRunOut)
    def poll_check(run_id: str, offset: int = Query(default=0, ge=0)) -> CheckRunOut:
        snapshot_now = runner.get(run_id)
        if snapshot_now is None:
            raise HTTPException(status_code=404, detail="unknown check run")
        return CheckRunOut.from_domain(snapshot_now, offset)

    @app.post("/api/checks/run/{run_id}/cancel", response_model=CheckRunOut)
    def cancel_check(run_id: str) -> CheckRunOut:
        # A status-only acknowledgment for the client (its polling loop remains the
        # one writer of run state); idempotent on a terminal run.
        cancelled = runner.cancel(run_id)
        if cancelled is None:
            raise HTTPException(status_code=404, detail="unknown check run")
        return CheckRunOut.from_domain(cancelled, 0)

    @app.get("/api/checks/latest", response_model=LatestCheckOut)
    def latest_check() -> LatestCheckOut:
        # The reconciliation read: page-reload re-adoption and indeterminate-start
        # recovery (a fast run that went terminal before the client could ask is
        # still visible here, so starts need no idempotency token).
        return LatestCheckOut.from_domain(runner.latest())

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
