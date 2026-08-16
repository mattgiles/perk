# Prose Review Workbench — stack selection and security envelope

**Status:** binding stack selection for Objective #1764 (the Prose Review Workbench; PRD:
[prose-review-app-prd.md](./prose-review-app-prd.md)). Selected and shipped with the walking
skeleton — the minimal secure launcher (`perk-dev prose-review`) plus the served round-trip proof
— and now carrying the three-pane workbench shell (fragment-aware capability tree / mode bar +
segmented source focus), the relationship inspector (consumers, consuming shapes + delivery
siblings, concerns, lineage), header catalog search, and snapshot-backed whole-unit Compare mode.
The inspector, search, and comparison-option projection are pure in-memory `CatalogSnapshot`
queries. Markdown, YAML, Python AST, and TypeScript compiler-API read adapters resolve exact logical
fragments; later nodes add Python call arguments, assembly views, and writers on this stack without
revisiting it.

## HTTP layer: FastAPI + uvicorn

- **Deps live in `packages/perk-dev/pyproject.toml` only** (`fastapi>=0.115`, `uvicorn>=0.30` —
  plain uvicorn, no `[standard]` extras). perk-dev is dev-only and never published; `src/perk` is
  untouched. The bounded-deps posture: no other backend dependency is anticipated for the whole
  objective.
- **Endpoints are sync `def`** — catalog queries are pure in-memory work over the immutable
  `CatalogSnapshot` (`load_catalog` builds once), and the only per-request repository-content reads
  belong to the two families below — and return `*Out` Pydantic models (`perk.boundary.OutputModel`,
  `from_domain` constructors). Domain objects are never serialized into a response body —
  handlers query the snapshot and hand domain values to the `from_domain` constructors; every
  body is an `*Out` model.
- **Comparison options are a pure snapshot projection.** `GET /api/compare` accepts a canonical
  unit and an optional coherent shape/one-based-position pair, then projects exactly five relation
  families in fixed order: delivery siblings, adjacent authored assembly layers, alias consumers,
  concern relatives, and capability parent/child hierarchy. The first three preserve authoritative
  assembly/shape placement; concern and capability targets are canonical. Capability relations walk
  the canonical routed unit's immediate parent then immediate children, with deterministic preorder
  subtree traversal, and never treat shape-expanded assembly layers as reassigned to the shape's
  capability. The endpoint reads no source and adds no graph fields or repository-content path.
- **Exactly two repository-content read families.** Built-asset reads (`index.html` included) go
  through `web.read_contained`; canonical-source reads go through the SourceAdapter package
  (`perk_dev.prose_review.source_adapter`) — root-bound, catalog-membership-checked, text-only,
  and the exclusive reader of canonical source content on the serving path (catalog *discovery*
  reads mapped sources once at load time; that is the catalog module's own contract). The package
  keeps the public facade stable while separating frozen contracts, contained reads/dispatch, and
  the Markdown/YAML/Python/TypeScript implementations. The TypeScript adapter's selector helper is
  fixed under an explicit helper checkout root, separate from the canonical-source trust root.
  Python writes the exact already-authorized text and ordered selectors to a random private
  temporary request, invokes `node tools/prose-map/selector.ts <request-json-path>` through
  `perk.substrate.proc.run_checked`, and removes the directory on every outcome. That temporary
  snapshot is controlled subprocess IPC over already-authorized text — generated solely by the
  adapter and never request-selected — not a third repository-content path.
- **TypeScript selector resolution has one shared AST authority.** `tools/prose-map/selector.ts`
  owns static property handling, registered-tool field traversal/policy, enclosing owners,
  depth-first ordinals, event/workflow/`completeStructured` sites, and raw selector identity;
  `catalog.ts` maps those shared records into the unchanged discovery DTO while the helper groups
  every exact raw site and treats collisions as ambiguity. Raw discovery identities take precedence
  over parent-linked helper aliases when their text collides. The helper parses supplied text exactly
  once with `createSourceFile(..., ES2022, ..., ScriptKind.TS)`, isolates and shape-checks the pinned
  TypeScript 6.0.3 runtime `parseDiagnostics` seam, and never creates a `Program`, resolves imports,
  reads libraries/repository source, type-checks, or executes code. A helper-only bare
  `symbol:<name>` grammar covers direct module-body named functions/classes and single direct-name
  variable statements without expanding the catalog.
- **Focused TypeScript ranges stay source-native and fail closed.** Direct strings,
  no-substitution/interpolated templates, `+` builders containing a string/template leaf, and
  `before_agent_start` arrow/function callbacks are focusable; parentheses, `as`, type assertions,
  `satisfies`, and non-null wrappers remain part of the range. Identifiers, shorthand fields,
  calls, object/array literals, spread/dynamic indirection, and other expression shapes remain
  whole-file readable with `unsupported-source-shape`, never a guessed range. Node converts every
  compiler position and diagnostic coordinate from UTF-16 to Unicode-code-point indexes before the
  strict versioned response crosses the subprocess boundary; Python validates ranges, result
  order/identity, reason/location pairings, and all TypeScript line-break forms before slicing the
  same text. A five-second helper timeout plus one app-scoped non-blocking `BoundedSemaphore` allows
  at most one helper process and no waiting queue; busy, spawn, timeout, exit, temp-file, and protocol
  failures return the typed whole-file `adapter-unavailable` presentation. TypeScript replacement
  and buffer-native write revalidation remain deferred to Node 3.4.
- The Python AST adapter accepts only the currently discovered `symbol:<name>` language:
  module-body functions, async functions, assignments with exactly one direct `ast.Name` among
  their targets, and annotated assignments whose target is a direct `ast.Name`; `<name>` must be a
  Python identifier that is not a hard keyword (contextual soft keywords remain valid). It parses,
  compiler-validates without execution, and tokenizes once per source operation so decorated
  function ranges begin at their physical `@` marker and AST UTF-8 byte columns become exact
  Unicode string indexes. Python call arguments remain deferred. The structured-text adapters
  expose exact range resolution, batch revalidation, and semantic check hints (`prose-map`, plus
  `learned-docs` for YAML); they do not expose persistence or replacement hooks yet.
  `GET /api/source` remains the one source endpoint and accepts an optional composite fragment id,
  returning either exact context/focus/context segments or a typed, whole-file read-only fallback.
  Numeric ranges remain backend-internal; the DTO and frontend parse/view contract stay
  family-neutral.
- The FastAPI app is constructed with **`docs_url=None, redoc_url=None, openapi_url=None`**: the
  default `/docs` (Swagger UI) and `/redoc` pages load CDN-hosted assets and would violate the
  no-network-loaded-assets envelope; `/openapi.json` is locally generated but is an unused
  machine-readable surface this app never serves — disabled to minimize the surface area.

## Frontend: Vite + React + TypeScript

- A dedicated npm workspace **`tools/prose-review/`** (the `docs/site` workspace precedent), all
  devDependencies exact-pinned: `react@19.2.8`, `react-dom@19.2.8`, `@types/react@19.2.18`,
  `@types/react-dom@19.2.4`, `vite@8.2.1`, `@vitejs/plugin-react@6.0.5`, and `diff@8.0.4`
  (TypeScript hoists from the root install). The workspace has no runtime `dependencies` key:
  every client and tool pin is dev-only because the built workbench is never published.
- `vite build` emits `tools/prose-review/dist/` (gitignored). The Python backend serves the built
  assets — **single origin, no network-loaded assets, no dev-server proxying**. Vite's build emits
  only external `<script type="module">`/stylesheet tags (no inline scripts), so
  `script-src 'self'` holds.
- **Placement and source identity stay separate.** Tree selection carries optional shape/layer
  provenance, while `/api/source` loader identity remains canonical unit plus optional fragment.
  Compare invalidation uses whole-unit unit/shape/position identity and ignores fragment-only
  navigation. The inspector chooses only server-projected targets; selecting one does not mutate the
  global mode or tree selection. Compare derives two whole-unit `/api/source` targets: equal unit ids
  share one existing source loader and the exact same loaded object across both panes, while distinct
  ids use two independent existing loaders. `/api/source` and its read path are unchanged.
- **Current text is diff input, not relation state.** The browser reconstructs each supplied source
  exactly as `before + focus + after`, calls `diffLines` directly, and renders its native typed
  chunks. It introduces no copied segment model, server-side diff, source cache, or comparison-specific
  source coordinator. The same seam is ready for the workspace-owned unsaved content that replaces
  fresh disk loads later: relation semantics and pane rendering do not change when current text comes
  from buffers.
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
| Repo-rooted read containment | Every **repository-content** read belongs to one of two families. Built-asset reads (`index.html` included) go through the contained-read helper: re-resolve the dist root, require it under the resolved repo root, resolve the candidate, require it under the dist root and a regular file — an escaping `dist/` symlink cannot launder outside targets in. Canonical-source reads go through the SourceAdapter (`perk_dev.prose_review.source_adapter`): lexical absolute-path rejection, resolved containment under the repo root, catalog membership, strict UTF-8 text only — serving-path-exclusive. The adapter-owned random TypeScript request is controlled IPC containing only that already-authorized snapshot; its generated path, fixed helper root, and unconditional cleanup are separately pinned. | traversal, child-symlink, `assets/`-dir-symlink, `dist`-root-symlink, and `index.html`-symlink tests in `test_prose_review_web.py`; traversal/absolute/symlink/NUL/non-text plus TypeScript temp-snapshot/cleanup/root-separation arms in `test_prose_review_source.py` |
| Text-only rendering (this node's slice) | React JSX text interpolation (escaped by default) + a node:test source scan banning HTML sinks (`innerHTML`, `outerHTML`, `insertAdjacentHTML`, `dangerouslySetInnerHTML`, `document.write`) + the CSP as backstop | `tools/prose-review/dom-sinks.test.ts` (with a vacuousness self-check) |
| CSP + hardening headers on **every** HTTP response | `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'` plus `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` — stamped by the guard on rejections, 404s, and framework-generated 500s alike | header assertions on every response shape, incl. `test_unhandled_exception_response_is_still_header_stamped` (pins the outermost placement) |
| No framework doc surfaces | `docs_url=None, redoc_url=None, openapi_url=None` | `test_framework_doc_surfaces_are_disabled` (×3) |

## The round-trip proof split

The original round-trip proof — the served page rendering `CatalogSummaryOut` — is **historical**:
the served page is now the three-pane workbench shell, which fetches `/api/catalog/tree` and
`/api/source` through their typed parse boundaries (`parseTree` / `parseUnitSource`, with the
closed wire vocabulary in `tools/prose-review/src/wire.ts`). `/api/catalog/summary` still serves
its original contract; `parseSummary` remains its typed local mirror, now exercised by tests only.
The relationship inspector, catalog search, and comparison projection added `/api/inspect`,
`/api/search`, and `/api/compare` — all pure in-memory snapshot queries (the search index is built
once in `create_app`), so **no third file-read family** was added. `parseUnitInspect`, `parseSearch`,
and `parseComparisonOptions` are typed reject-unknown boundaries; the comparison options loader
adds response-origin matching plus endpoint-specific latest-wins/clear/dispose invalidation.
The proof structure remains **server integration** (real Vite build, real uvicorn on a pre-bound
socket, real `*Out` DTOs, a comparison target followed through the unchanged source endpoint, and a
real TypeScript fragment resolved through the separate helper checkout root) plus node:test coverage
of every frontend parse/loader boundary and existing source-loader lifecycle. The packaging guard
pins `diff` as an exact dev-only dependency while preserving the workspace's zero-runtime-dependency
posture.

The launcher-served **browser** leg covers shape-origin layer selection, placement-aware option
refresh with fragment-only preservation, the five graph-backed target families and boundary
omission, same-unit one-request/no-difference rendering, distinct-unit native line chunks across the
Markdown/YAML/Python/TypeScript families, independent pane scrolling, empty-target copy, mode-local
reset, and regression checks for Edit/Assembly/navigation plus Host/Origin/CSP/no-store hardening.
Boundary explanations and the relationship/search surfaces remain part of that proof; the automated
browser-level hostile-payload pass across all panes is a later deliverable by the objective's design.
