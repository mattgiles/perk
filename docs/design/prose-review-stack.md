# Prose Review Workbench — stack selection and security envelope

**Status:** binding stack selection for Objective #1764 (the Prose Review Workbench; PRD:
[prose-review-app-prd.md](./prose-review-app-prd.md)). Selected and shipped with the walking
skeleton — the minimal secure launcher (`perk-dev prose-review`) plus the served round-trip proof
— and now carrying the three-pane workbench shell (fragment-aware capability tree / mode bar +
focused in-memory editing), the relationship inspector (consumers, consuming shapes + delivery
siblings, concerns, lineage), header catalog search, workspace-backed whole-unit Compare mode, and
one browser-authoritative workspace with safe Markdown/YAML and catalog-mapped Python persistence.
The inspector, search, and comparison-option projection are pure in-memory `CatalogSnapshot`
queries. Markdown, YAML, Python AST, and TypeScript compiler-API adapters resolve exact logical
fragments over either the canonical load text or browser-supplied current text; Markdown, YAML, and
admitted Python-backed paths share one whole-buffer validation and atomic-save pipeline, while later
slices add Python call arguments, TypeScript persistence, assembly views, and executable check
handoffs without revisiting this stack.

## HTTP layer: FastAPI + uvicorn

- **Deps live in `packages/perk-dev/pyproject.toml` only** (`fastapi>=0.115`, `uvicorn>=0.30` —
  plain uvicorn, no `[standard]` extras). perk-dev is dev-only and never published; `src/perk` is
  untouched. The bounded-deps posture: no other backend dependency is anticipated for the whole
  objective.
- **Endpoints are sync `def`** — catalog queries are pure in-memory work over the request's captured
  immutable generation. `load_catalog` builds the launch generation and each successful save builds
  one complete replacement generation; the current generation swaps atomically. The only per-request
  repository-content reads belong to the two families below, and handlers return `*Out` Pydantic
  models (`perk.boundary.OutputModel`,
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
  through `web.read_contained`; canonical-source reads and writes go through the SourceAdapter
  package (`perk_dev.prose_review.source_adapter`) — root-bound, catalog-membership-checked,
  text-only, and the exclusive canonical source I/O owner on the serving path (catalog *discovery*
  reads mapped sources once at load time; that is the catalog module's own contract). The package
  keeps the public facade stable while separating frozen contracts, contained reads/dispatch, and
  the Markdown/YAML/Python/TypeScript implementations. The TypeScript adapter's selector helper is
  fixed under an explicit helper checkout root, separate from the canonical-source trust root.
  TypeScript writes the exact already-authorized text and ordered selectors to a random private
  temporary request, invokes `node tools/prose-map/selector.ts <request-json-path>` through
  `perk.substrate.proc.run_checked`, and removes the directory on every outcome. That temporary
  snapshot is controlled subprocess IPC over already-authorized text — generated solely by the
  adapter and never request-selected — not a third repository-content path. `POST
  /api/source/project` selects a fixed adapter only through catalog unit/fragment identity and
  projects browser-supplied text without calling any canonical source reader; TypeScript projection
  deliberately retains that same private temporary-request/helper IPC.
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
  failures return the typed whole-file `adapter-unavailable` presentation. The browser treats that
  reason as transient and non-cacheable, with retry only through the explicit control or target
  reselection. TypeScript replacement validation remains deferred.
- The Python AST adapter accepts only the currently discovered `symbol:<name>` language:
  module-body functions, async functions, assignments with exactly one direct `ast.Name` among
  their targets, and annotated assignments whose target is a direct `ast.Name`; `<name>` must be a
  Python identifier that is not a hard keyword (contextual soft keywords remain valid). It parses,
  compiler-validates without execution, and tokenizes once per source operation so decorated
  function ranges begin at their physical `@` marker and AST UTF-8 byte columns become exact
  Unicode string indexes. For admitted `.py` `python-symbol` and `managed-prose` saves, batch
  validation reuses that single parse/compiler/tokenizer pass and re-resolves every mapped
  `symbol:<name>` selector against the reviewed complete buffer before the common replacement tail.
  The validation-only code object is discarded: repository Python is never imported, evaluated, or
  executed. Python call arguments remain unsupported. The structured-text adapters expose exact
  range resolution, batch revalidation, and semantic check hints (`prose-map`, plus `learned-docs`
  for YAML). Markdown, YAML, and catalog-mapped Python participate in the shared whole-buffer
  persistence pipeline; TypeScript persistence remains deferred.
  `GET /api/source` is the only canonical source-load endpoint and accepts an optional composite
  fragment id. Its nested response separates immutable file metadata (`path`, `stat.S_IMODE` mode,
  exact newline classification, SHA-256 load hash) from the metadata-free focused view; the exact
  loaded text is still only `before + focus + after`. The canonical reader resolves containment,
  opens the resolved candidate once, and samples regular-file status, permission bits, and bytes
  from that one descriptor before strict UTF-8 decoding. `POST /api/source/project` accepts the
  strict exact body `{unit, fragment, text}`, stores nothing, and returns only a focused view over
  supplied text. Unknown catalog identities retain the fixed no-leak 404s, while malformed or extra
  request fields stay at the guard-stamped 422 boundary. `POST /api/source/save` accepts the strict
  path-incapable body `{unit, load_hash, text}`. It derives path, mapped selectors, adapter, lineage,
  and current catalog generation server-side and returns a tagged outcome; success carries an
  identity-bearing `{unit, kind, file}` baseline plus existing lineage rows and named checks. Numeric
  ranges remain backend-internal; the DTO and frontend parse/view contracts stay family-neutral and
  additive toward unknown response fields.
- **One app-scoped transaction linearizes every save.** After taking the save mutex, the handler
  samples the current immutable generation and write-freeze state, authorizes and validates against
  that generation, performs replacement, rebuilds snapshot/tree/search from disk exactly once, and
  atomically swaps the complete generation before releasing the mutex. A refresh failure leaves the
  successful write in place, retains the prior read generation, and freezes later writes. The closed
  pre-save gate is adapter syntax, every mapped selector on the path, and
  containment/membership/lineage safety—never catalog rebuild, template rendering, subprocess checks,
  or command execution. Python discovery-marker membership is observed only by the post-commit
  catalog rebuild. A valid save that removes the marker remains committed; a resulting rebuild
  failure retains the prior read generation and enters the same frozen-write recovery state.
- **The write helper is stricter than canonical reads.** It admits only mapped `.md`
  Markdown/managed-prose, `.yaml`/`.yml` ambient-routing, and `.py` Python-symbol/managed-prose paths;
  TypeScript remains unsupported. It refuses generated sources and every root-relative symlink
  component, and never interprets lineage targets as paths. An early target
  sample rejects an existing hash mismatch before temp creation. Exact UTF-8 bytes are then written
  to a unique same-directory temp; a second no-follow safety/hash/mode sample occurs after preparation,
  the latest mode is applied after writing, and `os.replace` follows without intervening rebuild or
  check work. Every pre-replace failure cleans the temp; there is no force, backup, rollback, `fsync`,
  owner/xattr/ACL, or production-helper promise.
- The FastAPI app is constructed with **`docs_url=None, redoc_url=None, openapi_url=None`**: the
  default `/docs` (Swagger UI) and `/redoc` pages load CDN-hosted assets and would violate the
  no-network-loaded-assets envelope; `/openapi.json` is locally generated but is an unused
  machine-readable surface this app never serves — disabled to minimize the surface area.

## Frontend: Vite + React + TypeScript

- A dedicated npm workspace **`tools/prose-review/`** (the `docs/site` workspace precedent), all
  devDependencies exact-pinned: React + type declarations, Vite + its React plugin, `diff@8.0.4`,
  and the jsdom/tsx component-test harness (`jsdom@29.1.1`, `@types/jsdom@27.0.0`,
  `tsx@4.23.12`; TypeScript hoists from the root install). The workspace has no runtime
  `dependencies` key: every client and tool pin is dev-only because the built workbench is never
  published.
- `vite build` emits `tools/prose-review/dist/` (gitignored). The Python backend serves the built
  assets — **single origin, no network-loaded assets, no dev-server proxying**. Vite's build emits
  only external `<script type="module">`/stylesheet tags (no inline scripts), so
  `script-src 'self'` holds.
- **Placement and source identity stay separate.** Tree selection carries optional shape/layer
  provenance, while source target identity remains canonical unit plus optional fragment. Compare
  invalidation uses whole-unit unit/shape/position identity and ignores fragment-only navigation.
  The inspector chooses only server-projected targets; selecting one does not mutate the global mode
  or tree selection. File identity is instead the catalog-authored root-relative path: aliases,
  fragments, placements, search hits, concern links, and even different unit ids naming one path
  share one browser buffer.
- **`EditWorkspace` is the browser authority.** One framework-independent workspace lives for the
  App lifetime. Each path entry retains immutable load text/UTF-8 bytes, mode, newline style, and
  load hash alongside one mutable string-native current text and browser-local revision. UTF-8
  encoding is used for defensive byte snapshots and exact dirty comparison, never as a second
  mutable authority. No workspace text exists in Python globals, browser persistence, cookies, or a
  service worker. A revision-bound review freezes the complete loaded/current buffers, unified diff,
  and byte/newline/final-newline/BOM metadata; only that exact revision can enter the save transport.
- **Focused editing preserves source-native boundaries.** Editable views render escaped `before`
  and `after` in separate read-only regions and only the LF-normalized focus in a controlled
  textarea. A display-to-raw boundary map plus character diff preserves each unchanged CRLF, lone CR,
  and LF terminator; inserted breaks use the loaded uniform style, then the first focus/current
  terminator, then LF. One edited target lens per path is protected across temporary invalidity.
  Every other target is document-wide invalidated and must re-project against the current whole
  text before becoming editable; editing a different successfully projected target replaces the
  protected lens without losing prior bytes.
- **The workspace owns keyed requests and Compare text.** Canonical loads coalesce by path;
  projections coalesce by path/target/revision. Consumers subscribe by path and never cancel a
  shared request when switching or unmounting. Cache acceptance requires a live workspace, the
  captured revision, exact response identity, and full-text reconstruction; disposal aborts all
  workspace-owned requests. Stable read-only results cache only at their revision, while
  `adapter-unavailable` is returned only to current awaiters and never cached. Compare synthesizes
  whole-unit views from current workspace text, including across different unit ids on one path,
  then calls `diffLines` directly; relation/options state remains snapshot-backed and unchanged.
- **Dirty/discard/unload and save attention are byte exact.** Dirty count is the number of paths
  whose encoded current text differs from immutable load bytes. Exact manual reversion becomes clean.
  Ordinary per-file confirmed discard restores load text without rereading disk or replacing
  metadata, invalidates views, and leaves other files untouched. Conflict, indeterminate,
  reconciliation, and reload states cannot be discarded; the path-sorted drawer therefore counts
  attention rows rather than only dirty files, while `beforeunload` remains dirty-byte-based. Save,
  Reload, and reconciliation lock only their path. Conflict offers confirmed canonical Reload and
  complete-file Copy Edits. A post-dispatch unknown result globally suspends saves while a no-store
  canonical load distinguishes submitted, prior, and third content; unresolved outcomes remain
  retryable reconciliation, never ordinary save retry. Successful save adopts returned metadata and
  retains its read-only lineage/check report. Catalog-refresh failure or reconciled lost success
  freezes later writes with truthful external repair/copy guidance. There is no custom unload text,
  background persistence, backup, autosave, force overwrite, or in-app check execution.
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
| CSRF token on every non-GET/HEAD request | Meta-tag injection: `index.html`'s `__PROSE_REVIEW_CSRF__` placeholder is replaced at serve time with the process token (`secrets.token_urlsafe(32)`); the guard requires **exactly one** `X-Prose-Review-Csrf` header `secrets.compare_digest`-matching it (zero/duplicate/wrong → 403). Projection and save share one mutation-header helper and refuse missing/empty metadata locally. | `test_csrf_all_four_arms`; projection/save security arms in `test_prose_review_web.py`; `sourceLoad.test.ts`; `saveLoad.test.ts` |
| Repo-rooted read containment | Every **repository-content** read belongs to one of two families. Built-asset reads (`index.html` included) go through the contained-read helper: re-resolve the dist root, require it under the resolved repo root, resolve the candidate, require it under the dist root and a regular file — an escaping `dist/` symlink cannot launder outside targets in. Canonical-source reads go through the SourceAdapter (`perk_dev.prose_review.source_adapter`): lexical absolute-path rejection, resolved containment under the repo root, catalog membership, one descriptor for regular-file/mode/byte sampling, and strict UTF-8 — serving-path-exclusive. Supplied-text projection never calls that reader. The adapter-owned random TypeScript request is controlled IPC containing only that already-authorized snapshot; its generated path, fixed helper root, and unconditional cleanup are separately pinned. | traversal, child-symlink, `assets/`-dir-symlink, `dist`-root-symlink, and `index.html`-symlink tests in `test_prose_review_web.py`; traversal/absolute/symlink/NUL/non-text, same-descriptor metadata, canonical-read exclusion, and TypeScript temp-snapshot/cleanup/root-separation arms in `test_prose_review_source.py` |
| Repo-rooted conditional write containment | Save accepts no caller path/selector/adapter/mode. The active catalog derives one closed Markdown, YAML, or Python family and every selector on its path; generated sources, unmapped/mixed families, absolute/traversal/nonregular paths, and every symlink component refuse. Python validation parses, compiler-validates without execution, tokenizes, and re-resolves every mapped named-symbol selector before mutation. Early and post-temp no-follow samples enforce the load hash; only a late-matching same-directory temp reaches `os.replace`. | direct admission, Python non-execution/validation, lineage, traversal/symlink, early/late conflict, exact-byte/mode, atomicity, and failure-cleanup arms in `test_prose_review_save.py`; production catalog-refresh and strict HTTP arms in `test_prose_review_web.py`; real-uvicorn save arms in `test_prose_review_integration.py` |
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
`parseComparisonOptions`, and the nested source parsers structurally require known fields and closed
vocabularies while tolerating additive unknown response keys. The comparison options loader adds
response-origin matching plus endpoint-specific latest-wins/clear/dispose invalidation.
The proof structure remains **server integration** (real Vite build, real uvicorn on a pre-bound
socket, real nested `*Out` DTOs, a CSRF-authenticated supplied-text projection with unchanged disk
load afterward, exact-byte/mode/hash Markdown, YAML, and focused Python saves followed by refreshed
reads, and a real TypeScript fragment resolved through the separate helper checkout root). Separate
production-reload coverage rebuilds a disposable real catalog after marker-preserving Python saves
and pins marker-removing saves to the committed-but-stale write freeze. Frontend proof remains
node:test coverage of every parse/transport boundary and the pure workspace state machine. A jsdom
harness loads TSX through the exact-pinned `tsx` API to exercise the rendered App coordinator (fragment preservation, placement invalidation, stale outcomes, mode reset, duplicate
choice occurrence identity, attention drawer, discard, unload lifecycle, catalog-epoch refresh, and
write freeze) and CenterPane (shared path loads, focused textarea, transient retry, native
current-text diff chunks, frozen save review, diagnostics, conflict/reconciliation, and escaped
handoffs). The packaging guard pins the diff and test libraries as exact dev-only
dependencies while preserving the workspace's zero-runtime-dependency posture.

The launcher-served **browser** leg covers source-native focused editing across
Markdown/YAML/Python/TypeScript, alias/back-navigation retention, immediate workspace-backed Compare,
two-file dirty/Open behavior, mode preservation, and explicit reviewed Markdown/YAML/Python
persistence. Mapped Python named symbols use the shared full-file review/save controls, and
Python-backed managed prose preserves its read-only materialization handoff; TypeScript remains
in-memory-only. The rendered jsdom contract covers temporary-invalid focus,
stale-helper/transient retry, discard cancel/confirm, exact manual reversion, `beforeunload`, frozen
full-file diff metadata, hostile-text escaping, conflict Copy/Reload, indeterminate reconciliation,
catalog refresh/invalidation, and refresh-failure freeze. Shape-origin layer selection,
placement-aware option refresh, graph-backed target families, boundary omission, independent pane
scrolling, empty-target copy, mode-local reset, Assembly's honest placeholder, relationship/search,
and Host/Origin/CSP/no-store hardening remain in the regression pass. Unsaved workspace state still
has no browser persistence; only an explicit revision-reviewed save can mutate an admitted canonical
file.
