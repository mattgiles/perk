# Prose Review Workbench — stack selection and security envelope

**Status:** binding stack selection for Objective #1764 (the Prose Review Workbench; PRD:
[prose-review-app-prd.md](./prose-review-app-prd.md)). Selected and shipped with the walking
skeleton — the minimal secure launcher (`perk-dev prose-review`) plus the served round-trip proof
— and now carrying the three-pane workbench shell (fragment-aware capability tree / mode bar +
segmented source focus), the relationship inspector (consumers, consuming shapes + delivery
siblings, concerns, lineage), and header catalog search — the inspector and search are pure
in-memory `CatalogSnapshot` queries. Markdown and YAML read adapters now resolve exact logical
fragments; later nodes add the Python/TypeScript families, compare/assembly views, and writers on
this stack without revisiting it.

## HTTP layer: FastAPI + uvicorn

- **Deps live in `packages/perk-dev/pyproject.toml` only** (`fastapi>=0.115`, `uvicorn>=0.30` —
  plain uvicorn, no `[standard]` extras). perk-dev is dev-only and never published; `src/perk` is
  untouched. The bounded-deps posture: no other backend dependency is anticipated for the whole
  objective.
- **Endpoints are sync `def`** — catalog queries are pure in-memory work over the immutable
  `CatalogSnapshot` (`load_catalog` builds once), and the only per-request filesystem work is the
  two read families below — and return `*Out` Pydantic models (`perk.boundary.OutputModel`,
  `from_domain` constructors). Domain objects are never serialized into a response body —
  handlers query the snapshot and hand domain values to the `from_domain` constructors; every
  body is an `*Out` model.
- **Exactly two file-read families.** Built-asset reads (`index.html` included) go through
  `web.read_contained`; canonical-source reads go through the SourceAdapter package
  (`perk_dev.prose_review.source_adapter`) — root-bound, catalog-membership-checked, text-only,
  and the exclusive reader of canonical source content on the serving path (catalog *discovery*
  reads mapped sources once at load time; that is the catalog module's own contract). The package
  keeps the public facade stable while separating frozen contracts, contained reads/dispatch, and
  the Markdown/YAML implementations. The structured-text adapters expose exact range resolution,
  batch revalidation, and semantic check hints (`prose-map`, plus `learned-docs` for YAML); they do
  not expose persistence or replacement hooks yet. `GET /api/source` remains the one source
  endpoint and accepts an optional composite fragment id, returning either exact
  context/focus/context segments or a typed, whole-file read-only fallback.
- The FastAPI app is constructed with **`docs_url=None, redoc_url=None, openapi_url=None`**: the
  default `/docs` (Swagger UI) and `/redoc` pages load CDN-hosted assets and would violate the
  no-network-loaded-assets envelope; `/openapi.json` is locally generated but is an unused
  machine-readable surface this app never serves — disabled to minimize the surface area.

## Frontend: Vite + React + TypeScript

- A dedicated npm workspace **`tools/prose-review/`** (the `docs/site` workspace precedent), all
  devDependencies exact-pinned: `react@19.2.8`, `react-dom@19.2.8`, `@types/react@19.2.18`,
  `@types/react-dom@19.2.4`, `vite@8.2.1`, `@vitejs/plugin-react@6.0.5` (TypeScript hoists from
  the root install). Dev-only, never published.
- `vite build` emits `tools/prose-review/dist/` (gitignored). The Python backend serves the built
  assets — **single origin, no network-loaded assets, no dev-server proxying**. Vite's build emits
  only external `<script type="module">`/stylesheet tags (no inline scripts), so
  `script-src 'self'` holds.
- **Frontend dev loop (one `dist/` writer at a time):** launch the server once
  (`perk-dev prose-review` rebuilds on launch), then start the **build watcher**
  (`npm run dev --workspace tools/prose-review` = `vite build --watch`, not a dev server) and
  simply reload the page — the server rereads `dist/` from disk on every request, so no relaunch
  is needed to pick up watcher output. Stop the watcher before relaunching: the launcher's own
  rebuild writes the same `dist/`, and two concurrent writers may race. Vite's actual dev server
  is deliberately unusable against the API: the single-origin Host guard rejects any other
  origin, and no CORS/proxy escape hatch exists.

## Build policy: rebuild on every launch

The launcher runs the Vite build (via `perk.substrate.proc.run_checked`) before binding the
socket; a build failure is a typed CLI error (`frontend_build_failed`) and no server starts.
Existence is never treated as freshness. Tests never share the launcher's `dist/`: the
server-integration fixture builds unconditionally, once per module, into a fixture-owned temp
directory (`vite --outDir`), so no two processes ever write one output dir.

## The security envelope (pinned invariants)

The guard is the **outermost ASGI wrapper** (`SecurityGuardMiddleware(fastapi_app)` — outside
Starlette's `ServerErrorMiddleware`), HTTP-scope-only; lifespan/websocket scopes pass through
untouched (no websocket routes exist — a future node adding them must give them their own guard
policy first). Pure ASGI keeps the guard streaming-transparent for the later streaming
CheckRunner.

| Invariant | Enforcement | Test |
|---|---|---|
| Loopback origin only: exactly `127.0.0.1:<port>` | The launcher binds `127.0.0.1:0`; the guard requires the `Host` header to byte-equal the one printed origin (`localhost` spellings, foreign hosts, missing port all 403) | `test_prose_review_web.py::test_host_rejection` (×3); `test_prose_review_integration.py::test_wrong_host_is_rejected_over_real_http` |
| Origin exact-match | An `Origin` header, when present, must equal `http://127.0.0.1:<port>` exactly, else 403 | `test_origin_exact_match_passes_and_foreign_origin_is_rejected` |
| CSRF token on every non-GET/HEAD request | Meta-tag injection: `index.html`'s `__PROSE_REVIEW_CSRF__` placeholder is replaced at serve time with the process token (`secrets.token_urlsafe(32)`); the guard requires **exactly one** `X-Prose-Review-Csrf` header `secrets.compare_digest`-matching it (zero/duplicate/wrong → 403) | `test_csrf_all_four_arms` (403 ×3 + the pass-through 405 proof) |
| Repo-rooted read containment | Every file read belongs to one of two families. Built-asset reads (`index.html` included) go through the contained-read helper: re-resolve the dist root, require it under the resolved repo root, resolve the candidate, require it under the dist root and a regular file — an escaping `dist/` symlink cannot launder outside targets in. Canonical-source reads go through the SourceAdapter (`perk_dev.prose_review.source_adapter`): lexical absolute-path rejection, resolved containment under the repo root, catalog membership, strict UTF-8 text only — serving-path-exclusive | traversal, child-symlink, `assets/`-dir-symlink, `dist`-root-symlink, and `index.html`-symlink tests in `test_prose_review_web.py`; traversal/absolute/symlink/NUL/non-text arms in `test_prose_review_source.py` |
| Text-only rendering (this node's slice) | React JSX text interpolation (escaped by default) + a node:test source scan banning HTML sinks (`innerHTML`, `outerHTML`, `insertAdjacentHTML`, `dangerouslySetInnerHTML`, `document.write`) + the CSP as backstop | `tools/prose-review/dom-sinks.test.ts` (with a vacuousness self-check) |
| CSP + hardening headers on **every** HTTP response | `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'` plus `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` — stamped by the guard on rejections, 404s, and framework-generated 500s alike | header assertions on every response shape, incl. `test_unhandled_exception_response_is_still_header_stamped` (pins the outermost placement) |
| No framework doc surfaces | `docs_url=None, redoc_url=None, openapi_url=None` | `test_framework_doc_surfaces_are_disabled` (×3) |

## The round-trip proof split

The original round-trip proof — the served page rendering `CatalogSummaryOut` — is **historical**:
the served page is now the three-pane workbench shell, which fetches `/api/catalog/tree` and
`/api/source` through their typed parse boundaries (`parseTree` / `parseUnitSource`, with the
closed wire vocabulary in `tools/prose-review/src/wire.ts`). `/api/catalog/summary` still serves
its original contract; `parseSummary` remains its typed local mirror, now exercised by tests only.
The relationship inspector and catalog search added `/api/inspect` and `/api/search` — both pure
in-memory snapshot queries (the search index is built once in `create_app`), so **no third
file-read family** was added; `parseUnitInspect` / `parseSearch` join the typed parse boundaries
(same reject-unknown posture, node:test-covered).
The proof structure is unchanged: **server-integration** tests (real Vite build, real uvicorn on a
pre-bound socket, real `*Out` DTOs) plus node:test coverage of each frontend parse boundary (local
wire-shape mirrors; OpenAPI schema generation and runtime schema-validation libraries are out of
scope). The **browser** leg (the shell expands fragment branches, preserves composite selection across
aliases and search, renders exact context/focus/context segments, and keeps the unit-scoped
relationship inspector stable while fragment identity changes) is a manual acceptance step.
Boundary explanations and the existing relationship/search surfaces remain part of that proof; the
automated browser-level hostile-payload pass across all panes is a later node's deliverable by the
objective's design.
