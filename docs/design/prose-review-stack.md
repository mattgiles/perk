# Prose Review Workbench — stack selection and security envelope

**Status:** binding stack selection for Objective #1764 (the Prose Review Workbench; PRD:
[prose-review-app-prd.md](./prose-review-app-prd.md)). Selected and shipped with the walking
skeleton — the minimal secure launcher (`perk-dev prose-review`) plus the served round-trip proof.
Later nodes build the workbench UI, relationship DTOs, source reads, and writers on this stack
without revisiting it.

## HTTP layer: FastAPI + uvicorn

- **Deps live in `packages/perk-dev/pyproject.toml` only** (`fastapi>=0.115`, `uvicorn>=0.30` —
  plain uvicorn, no `[standard]` extras). perk-dev is dev-only and never published; `src/perk` is
  untouched. The bounded-deps posture: no other backend dependency is anticipated for the whole
  objective.
- **Endpoints are sync `def`** — every query is pure in-memory work over the immutable
  `CatalogSnapshot` (`load_catalog` builds once) — and return `*Out` Pydantic models
  (`perk.boundary.OutputModel`, `from_domain` constructors). The HTTP layer never touches domain
  objects.
- The FastAPI app is constructed with **`docs_url=None, redoc_url=None, openapi_url=None`**: the
  default `/docs`/`/redoc`/`/openapi.json` surfaces load CDN assets and would violate the
  no-network-loaded-assets envelope.

## Frontend: Vite + React + TypeScript

- A dedicated npm workspace **`tools/prose-review/`** (the `docs/site` workspace precedent), all
  devDependencies exact-pinned: `react@19.2.8`, `react-dom@19.2.8`, `@types/react@19.2.18`,
  `@types/react-dom@19.2.4`, `vite@8.2.1`, `@vitejs/plugin-react@6.0.5` (TypeScript hoists from
  the root install). Dev-only, never published.
- `vite build` emits `tools/prose-review/dist/` (gitignored). The Python backend serves the built
  assets — **single origin, no network-loaded assets, no dev-server proxying**. Vite's build emits
  only external `<script type="module">`/stylesheet tags (no inline scripts), so
  `script-src 'self'` holds.
- **Frontend dev loop:** `npm run dev --workspace tools/prose-review` runs `vite build --watch`;
  relaunch (or just reload against a fresh launch) to pick a build up. The Vite dev server is
  deliberately unusable against the API: the single-origin Host guard rejects any other origin,
  and no CORS/proxy escape hatch exists.

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
| Repo-rooted read containment | Every file read (`index.html` included) goes through one contained-read helper: re-resolve the dist root, require it under the resolved repo root, resolve the candidate, require it under the dist root and a regular file — an escaping `dist/` symlink cannot launder outside targets in | traversal, child-symlink, `assets/`-dir-symlink, `dist`-root-symlink, and `index.html`-symlink tests in `test_prose_review_web.py` |
| Text-only rendering (this node's slice) | React JSX text interpolation (escaped by default) + a node:test source scan banning HTML sinks (`innerHTML`, `outerHTML`, `insertAdjacentHTML`, `dangerouslySetInnerHTML`, `document.write`) + the CSP as backstop | `tools/prose-review/dom-sinks.test.ts` (with a vacuousness self-check) |
| CSP + hardening headers on **every** HTTP response | `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'` plus `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` — stamped by the guard on rejections, 404s, and framework-generated 500s alike | header assertions on every response shape, incl. `test_unhandled_exception_response_is_still_header_stamped` (pins the outermost placement) |
| No framework doc surfaces | `docs_url=None, redoc_url=None, openapi_url=None` | `test_framework_doc_surfaces_are_disabled` (×3) |

## The round-trip proof split

The automated proof is a **server-integration** test (real Vite build, real uvicorn on a pre-bound
socket, real `CatalogSummaryOut`) plus node:test coverage of the frontend's typed parse boundary
(`parseSummary` in `tools/prose-review/src/summary.ts` — a local wire-shape mirror; OpenAPI schema
generation and runtime schema-validation libraries are out of scope). The **browser** leg (the
page fetches the DTO and renders it) is a manual acceptance step; the automated browser-level
hostile-payload pass across all panes is a later node's deliverable by the objective's design.
