# Prose Review Workbench — stack selection and security envelope

**Status:** binding stack selection for Objective #1764 (the Prose Review Workbench; PRD:
[prose-review-app-prd.md](./prose-review-app-prd.md)). Selected and shipped with the walking
skeleton — the minimal secure launcher (`perk-dev prose-review`) plus the served round-trip proof
— and now carrying the three-pane workbench shell (fragment-aware capability tree / mode bar +
focused in-memory editing), the relationship inspector (consumers, consuming shapes + delivery
siblings, concerns, lineage), header catalog search, workspace-backed whole-unit Compare mode, the
Assembly preview mode (scenario picker, visibility toggles, separate/concatenated views, read-only
scenario variables in the inspector), and one browser-authoritative workspace with safe
Markdown/YAML, catalog-mapped Python, and catalog-mapped TypeScript persistence. The inspector, search, and comparison-option projection are
pure in-memory `CatalogSnapshot` queries. Markdown, YAML, Python AST, and TypeScript compiler-API
adapters resolve exact logical fragments over either the canonical load text or browser-supplied
current text; every admitted family shares one whole-buffer validation and atomic-save pipeline.
The Assembly preview is now shipped end to end — the backend `AssemblyRenderer` + the
scenario-options/render API below, and the Assembly-mode frontend that consumes them — the
CheckRunner executes the allowlisted targeted checks below on explicit user action, and the
read-only Git observation adapter annotates catalog files with working-tree status and serves
HEAD↔worktree diffs rendered by `@pierre/diffs`; later slices add Python call arguments without
revisiting this stack.

## HTTP layer: FastAPI + uvicorn

- **Deps live in `packages/perk-dev/pyproject.toml` only** (`fastapi>=0.115`, `uvicorn>=0.30` —
  plain uvicorn, no `[standard]` extras). perk-dev is dev-only and never published; `src/perk` is
  untouched. The bounded-deps posture: no other backend dependency is anticipated for the whole
  objective.
- **Endpoints are sync `def`** — catalog queries are pure in-memory work over the request's captured
  immutable generation. `load_catalog` builds the launch generation and each successful save builds
  one complete replacement generation; the current generation swaps atomically. The only per-request
  repository-content reads belong to the three families below, and handlers return `*Out` Pydantic
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
- **Exactly three repository-content read families — the third is observation-only.** Built-asset
  reads (`index.html` included) go through `web.read_contained`; canonical-source reads and writes
  go through the SourceAdapter package (`perk_dev.prose_review.source_adapter`) — root-bound,
  catalog-membership-checked, text-only, and the exclusive canonical source I/O owner on the
  serving path (catalog *discovery* reads mapped sources once at load time; that is the catalog
  module's own contract). The third family is the read-only **Git observation adapter**
  (`perk_dev.prose_review.git`, its own section below): fixed non-mutating `git status`/`git diff`
  invocations over the resolved repo root that observe rather than open repository files (git
  itself reads object/worktree content), exposing no path the catalog does not already map. The package
  keeps the public facade stable while separating frozen contracts, contained reads/dispatch, and
  the Markdown/YAML/Python/TypeScript implementations. `source_adapter_for` is the single
  kind-plus-suffix dispatch authority for both focused read projection and save admission: every
  mapped unit on a path must resolve to the same concrete adapter instance. The TypeScript
  adapter's selector helper is fixed under an explicit helper checkout root, separate from the
  canonical-source trust root.
  TypeScript writes the exact already-authorized text and ordered selectors to a random private
  temporary request, invokes `node tools/prose-map/selector.ts <request-json-path>` through
  `perk.substrate.proc.run_checked`, and removes the directory on every outcome. That temporary
  snapshot is controlled subprocess IPC over already-authorized text — generated solely by the
  adapter and never request-selected — not a third repository-content path. The app constructs one
  TypeScript adapter for its lifetime and injects that same instance into reads, supplied-text
  projections, and saves; requests can select neither the adapter nor the helper root. `POST
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
  read reason as transient and non-cacheable, with retry only through the explicit control or target
  reselection. Save validation sends one strict request containing only the reviewed supplied
  complete buffer and every catalog-derived selector in unit/fragment order. Parser failure yields
  one syntax diagnostic; otherwise every unsupported, missing, ambiguous, or unsupported-source-shape
  result remains ordered and blocks replacement. A helper failure during save performs a fresh
  no-follow target sample: an unchanged baseline becomes determinate `write-failed`, changed bytes
  become conflict, and unsafe/unavailable drift keeps its closed refusal. No source temp exists on
  that arm, and only confirmed `write-failed` retains the exact frozen review for same-buffer retry.
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
  range resolution, batch revalidation, and per-family semantic check hints over the one closed
  `CheckId` vocabulary (`perk_dev.prose_review.checks`): Markdown suggests `prose-map` (plus
  `prompt-parity` for prompt templates via the shared `prompt_template_name` predicate), YAML adds
  `learned-docs`, Python adds `worker-prompt-pins`/`ruff`/`ty`, and TypeScript adds
  `worker-prompt-pins`/`worker-test-pins`/`biome`/`tsc`. Suggested-check display strings are
  sourced from the same `CHECK_COMMANDS` table the CheckRunner executes, so display and execution
  can never drift. Markdown, YAML, catalog-mapped Python, and `.ts` `typescript-tool`,
  `typescript-model-call`, and `typescript-symbol` paths participate in the shared whole-buffer
  persistence pipeline.
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
  identity-bearing `{unit, kind, file}` baseline plus existing lineage rows and named checks. The
  server persists `text.encode("utf-8")` verbatim after validation: it receives no compiler range,
  edit history, selector, path, or old prefix/suffix with which to reconstruct the file. Numeric
  ranges remain adapter/backend-internal; the DTO and frontend parse/view contracts stay
  family-neutral and additive toward unknown response fields.
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
- **Read projection and save admission share one family dispatch.** `source_adapter_for` admits
  mapped `.md` Markdown/managed-prose, `.yaml`/`.yml` ambient-routing, `.py`
  Python-symbol/managed-prose, and `.ts` TypeScript-tool/model-call/symbol units. Save derives the
  complete same-path mapped set and proceeds only when every unit resolves to the exact same adapter
  instance; missing, kind/suffix-mismatched, mixed, and unmapped requests remain
  `unsupported-family`. It refuses generated sources and every root-relative symlink component, and
  never interprets lineage targets as paths. An early target sample rejects an existing hash
  mismatch before temp creation. Exact UTF-8 bytes are then written to a unique same-directory temp;
  a second no-follow safety/hash/mode sample occurs after preparation, the latest mode is applied
  after writing, and `os.replace` follows without intervening rebuild or check work. Every
  pre-replace failure cleans the temp; there is no force, backup, rollback, `fsync`, owner/xattr/ACL,
  or production-helper promise.
- The FastAPI app is constructed with **`docs_url=None, redoc_url=None, openapi_url=None`**: the
  default `/docs` (Swagger UI) and `/redoc` pages load CDN-hosted assets and would violate the
  no-network-loaded-assets envelope; `/openapi.json` is locally generated but is an unused
  machine-readable surface this app never serves — disabled to minimize the surface area.

## Assembly preview: `AssemblyRenderer`, the options/render API, and the Assembly-mode frontend

- **One deep renderer module over a save-linearized generation.**
  `perk_dev.prose_review.assembly.AssemblyRenderer` is an app-lifetime object (resolved source
  root + the one app-scoped TypeScript adapter) whose single `render` method takes an explicit
  `CatalogSnapshot`, one validated assembly/scenario pair, nullable presentation overrides, and
  path-keyed workspace buffers — and returns every authored layer exactly once in authored order.
  The HTTP route runs the whole operation as one **source transaction**: `_CatalogState`'s mutex
  (renamed `source_transaction_mutex`) serializes renders with saves, the critical section spans
  writes-frozen rejection → generation capture → every canonical read/gate/prompt render/adapter
  extraction → DTO conversion, and a post-refresh-failure state refuses render with fixed HTTP 409
  `catalog stale` before any source read. One consequence pinned in tests: a render can only
  observe a busy TypeScript helper slot from *unlocked* read/projection overlap, never from a
  save. Out-of-process filesystem edits stay outside the app transaction.
- **Assembly-wide, no-shape, toggle-independent semantics.** The renderer accepts no session-shape
  id (a shape is navigation/provenance only) and never filters, expands, deduplicates, or reorders
  layers. Authored `optional: true` is descriptive presence variance — `presence="varies"` plus
  the exact marker `Presence varies by session shape or runtime.` — never a render-time filter.
  Presentation booleans resolve scenario defaults with nullable overrides but change only the
  top-level `ResolvedPresentation` echo; the per-layer tuple is byte-identical across toggle
  values, and clients derive display visibility from the role-only `visibility_control` metadata
  (`ambient-discovery` → `ambient`, `tool-contract` → `tools`, everything else null — bound
  skills and Pi boundaries are never ambient substitutes), so contradictory wire states are
  impossible.
- **Workspace-first, path-keyed source resolution.** Browser workspace identity is the
  catalog-authored root-relative path. The request may carry any catalog-known loaded file
  (duplicate or unknown paths invalidate the whole request as fixed 422 `invalid workspace
  buffers`); a buffered path — even an empty string — is never reread, and repeated same-path
  layers share one request-local canonical read outcome. Every canonical fallback read derives
  from the routed unit under the captured generation through the contained SourceAdapter reader;
  buffer keys never become filesystem read targets. A `SourceReadError` becomes a per-position
  typed `source-unavailable` failure with safe fixed copy while unrelated paths continue.
- **The preview gate in front of the unchanged production render seam.** Prompt-root Markdown
  (the shared `prompt_template_name` predicate, also used by scenario-fixture validation) is
  gated by `perk_dev.prompt_grammar.scan_template` — the frozen-subset scanner moved out of
  `tests/test_prompt_grammar.py`, now consumed by both the conformance guard and this gate —
  before `perk.prompts.render_text` ever compiles it: any out-of-subset block →
  `template-grammar-invalid`; any include (canonical or workspace) →
  `template-include-unsupported`, so no editable request can trigger the packaged `prompts_dir()`
  loader; any identifier outside the selected scenario's variables → `template-variable-unknown`,
  confining rendering to the TS mini-jinja twin's mapping-only namespace (jinja's Environment
  globals and `true`/`false`/`none` are unreachable). The scanner is whole-source —
  unterminated/multiline/stray/nested delimiters are violations — a documented **Python-side
  narrowing versus the TS runtime tokenizer** (`miniJinja.ts` accepts multiline tags and treats
  stray closers as text); the frozen construct set and both runtimes are unchanged
  (`shared/contracts.md §8.31`). Gate-passing structural errors (`if`/`endif` imbalance) surface
  as `template-render-failed` from an exact `jinja2.TemplateError` catch; the string-only
  variable contract stays a loud invariant.
- **Raw Markdown versus ordered source-native code fragments.** Markdown outside `prompts/`
  (skills, agent definitions) returns the exact whole text as one `raw-source` part, never parsed
  as Jinja. Non-Markdown owned layers dispatch once through `source_adapter_for` and call the new
  `SourceAdapter.extract_many` batch seam — one Python parse/compile/tokenize pass or one
  TypeScript helper invocation per layer (the helper protocol already accepted ordered selector
  batches; `resolve_range` now rides the one-item batch path and the base class owns
  resolution-to-extraction slicing) — returning one `source-fragments` part per catalog fragment
  in order with id/label provenance and exact source-native focus. Nothing is decoded, imported,
  evaluated, or executed. Code layers are atomic result variants: any unresolved fragment fails
  the whole authored layer with ordered safe problems (document-level `invalid-source` collapses
  to one unit-level problem; helper unavailability and a missing adapter family are unit-level
  `adapter-unavailable`/`unsupported-family`), and no partial content is returned while every
  sibling layer stays in the result. Adapter diagnostic text, helper protocol details, and raw
  exceptions never enter Assembly results — those remain on the focused edit/save surfaces.
- **Typed boundary placeholders.** Every closed `BoundaryKind` maps exhaustively to a stable
  semantic owner id (`pi-system`→`pi`, `user-content`→`user`, `runtime-state`→`runtime`,
  `borrowed-prompt`→`borrowed-package`); a boundary layer carries owner + kind + authored
  label/presentation and no source path, editable content, or guessed runtime text. Human-facing
  display copy stays in the frontend's `BOUNDARY_INFO` (reused verbatim by the Assembly cards).
- **Two strict HTTP surfaces.** `GET /api/assembly/options?assembly=<id>` is a pure snapshot
  query returning `AssemblyOptionsOut` (the assembly id plus complete ordered scenario fixtures
  with object-shaped sorted variables); unknown assembly is fixed 404 `unknown assembly`.
  `POST /api/assembly/render` accepts the exact strict body `{assembly, scenario, presentation:
  {include_ambient: bool|null, include_tools: bool|null}, buffers: [{path, text}]}` (required
  keys, `StrictInputModel` extra/coercion rejection) and returns the discriminated
  `AssemblyRenderOut` (`type: owned | boundary | failure`, common presentation nested under
  `presentation`, every `*Out` built via `from_domain`). One **Unicode-scalar input rule**:
  `path`/`text` reject unpaired surrogates (not-UTF-8-encodable strings) at the boundary, and the
  app's validation-error handler omits the default raw-input echo so a hostile buffer yields a
  serializable framework 422, never a 500. Selection failures map to fixed 404
  `unknown assembly render subject`; expected source/gate/render/adapter failures are guarded 200
  layer results with all siblings. The POST accepts repository text and therefore sits under the
  existing exact CSRF header rule; both routes retain the Host/Origin/CSP/no-store stamping.
- **Assembly-mode frontend (the consumption chain over the contract above).**
  `tools/prose-review/src/assembly.ts` mirrors both wire shapes with reject-unknown structural
  parsers — module-local closed vocabularies for the endpoint-only enums, a deliberately *open*
  non-empty `reason` on layer problems (the display contract is the server's fixed `detail`
  copy), and an empty `scenarios` array rejected at the parse boundary so a parsed options value
  always carries at least one scenario (the auto-first-scenario controller stays total).
  `assemblyLoad.ts` is the never-rejecting classified transport pair: options 404 → refused;
  render `not-sent` without fetching when the CSRF token is missing; the deterministic
  404/409/422 arms → refused (copy only — no retry affordance); everything else → failed, and —
  because render never mutates — failed renders carry a safe explicit `Re-render` retry.
  `assemblySession.ts` owns the two-stage options→render state machine with one latest-wins
  generation across both stages and the completion-merge rule: a render completion mutates only
  the live `ready` state's render slot (dropped when the generation moved or the state left
  `ready`), so same-generation visibility overrides survive an in-flight render. Opening a
  shape's assembly auto-selects the first ordered scenario and renders immediately; scenario
  switches reset both overrides to the new scenario's authored defaults. Assembly-local state
  mirrors Compare's lifetime — cleared on mode exit and subject change, re-opened by a
  catalog-epoch bump; a non-shape selection shows a fixed hint.
- **Client-derived visibility + the two views.** Visibility toggles never re-POST: hiding is
  derived locally (`override ?? scenario default` against each layer's `visibility_control`),
  which the toggle-independent per-layer wire contract above makes sound; render requests carry
  the nullable overrides so the server echo matches at request time (the echo is parsed for
  shape-soundness but the live derivation source is local state). The separate view renders one
  card per visible layer — owned parts as escaped text with fragment captions, boundary
  owner/explanation copy from `BOUNDARY_INFO` with the wire owner as data, failure problems with
  the server's fixed safe detail. The concatenated view joins visible layers with one blank
  line: owned parts verbatim, boundaries as `[[ boundary: <label> · owner: <owner> ]]`, failures
  as `[[ layer failed: <unit id> ]]`, with a fixed note when any visible layer's presence varies.
- **Workspace-backed live preview.** `EditWorkspace.exportBuffers()` exports the complete loaded
  workspace (`{path, text}` records, path-sorted, dirty or not — the render request is the
  browser's whole loaded workspace) as the render request's buffers; the App's global workspace
  subscription pokes the session, which fingerprints the serialized export sent with the last
  issued render and re-renders only on mismatch — an unsaved edit is visible in the preview
  without a save. The tree DTO now carries `SessionShapeOut.assembly` (`id, label, delivery,
  assembly, layers`) so a shape selection names the options/render subject, and the frontend
  `SessionShape` parser requires it non-empty. The selected scenario's variables render read-only
  in the inspector's shape branch; the center pane owns the controls.

## CheckRunner: allowlisted targeted checks with streamed output and cancellation

- **One app-owned allowlist module.** `perk_dev.prose_review.checks` is the single source of
  truth for check identity (`CheckId`, the closed nine-id vocabulary), display command, and
  execution: every `CHECK_COMMANDS` entry is a complete fixed argv (no `just` recipes, no
  `npm run` script indirection), the display string IS the joined executed argv, and the client
  only ever sends a check id — zero argv content is request-derived. Every entry is check-only
  (`uv run --no-sync` / `npx --no-install` pin env-sync and network-install side effects out);
  `run_ci`, `just`, formatters, and the full gates are structurally absent and pinned absent by
  the allowlist test. `source_adapter/contract.py`'s `CheckHintId` is a re-export of `CheckId`
  (import direction: contract → checks; no cycle).
- **The streaming/cancellable process seam is app-owned.** `perk.substrate.proc.run_checked`
  stays blocking-and-capture and is not reused. Exactly one `subprocess.Popen` call site
  (`CheckRunner._spawn`, sanctioned in `tests/test_tooling.py` with mandatory `cwd=` and
  `start_new_session=`): list argv, no shell anywhere, stdin devnull, one merged ordered
  stdout+stderr text stream (stdlib incremental decoding, `errors="replace"`), and
  `start_new_session=True` so the whole child tree is one killable process group. A daemon
  reader thread captures line-by-line under the runner's one lock, capped at 2,000,000 code
  points — past the cap the record is `truncated` and the reader drains without storing, so the
  pipe never blocks the child. Offsets are Python str indexes over the monotone append-only
  capture.
- **The single-finalizer rule.** The reader thread is the only path that assigns a terminal
  status, clears the single active slot, and cancels the timeout timer (spawn failure aside,
  recorded terminal `spawn-failed` synchronously in `start()` before either exists). The daemon
  timeout timer and `cancel()` only set their flag under the lock and run the process-group kill
  escalation outside it — SIGTERM, then up to 5s polling the WHOLE process group
  (`killpg(pgid, 0)` — a SIGTERM-resistant descendant that outlives the leader must still be
  SIGKILLed, or it could hold the merged pipe open and wedge the reader/slot), then SIGKILL;
  never `wait()` (the reader owns the one reap). Terminal status follows flag precedence `cancelled` > `timeout` >
  exit-code-derived, with `exit_code` non-null only for `passed`/`failed`.
- **One run slot, bounded records, offset polling.** One active run app-wide: a busy slot is
  HTTP 409; a bounded ring retains the 20 most recent records (evicted/unknown runs are the
  fixed 404 `unknown check run`). Four sync-def routes on the existing envelope:
  `POST /api/checks/run` (strict `{check: CheckId}` body — the closed Literal is the whole
  admission boundary: unknown ids are the framework 422),
  `GET /api/checks/run/{run_id}?offset=N` (`ge=0`, clamped to the captured length),
  `POST /api/checks/run/{run_id}/cancel` (an empty 204 status-only acknowledgment — the
  client's polling loop is the one reader of run state; idempotent on terminal
  runs), and `GET /api/checks/latest` — the reconciliation read serving page-reload re-adoption
  and indeterminate-start recovery. Both POSTs sit under the existing CSRF rule; the pure-ASGI
  guard needed no change (streaming-transparency was pinned for exactly this consumer).
- **Isolated from the source transaction; app-scoped shutdown.** Check runs never take
  `source_transaction_mutex`, never read or swap the catalog generation, and stay permitted
  while `writes_frozen` (read-only and useful for diagnosis); a run observes the live working
  tree, so concurrent saves are permitted by design. `create_app` wires `runner.shutdown()` into
  the FastAPI lifespan (no `atexit`): uvicorn's graceful shutdown kills the active run's process
  group and joins the reader, so the launcher never leaks a running suite and repeated app/test
  construction leaks nothing process-global. `check_commands` is the injection seam (the
  `reload_catalog` pattern) — tests substitute `sys.executable`-based argv under real ids.
- **The client session (`checkSession.ts`) polls at 500ms with one writer.** `checks.ts` owns
  the closed frontend vocabulary (ids, statuses, notice copy) and reject-unknown parsers;
  `save.ts` reuses `CHECK_IDS` for suggested-check parsing — one vocabulary, no drift. The
  session adopts a started run, polls with the growing offset, retires terminal runs into the
  App-level newest-first history (capped at 20), treats a poll/cancel 404 as the
  terminal-unrecoverable client-only `lost` state, reconciles refused/indeterminate starts
  through `latest` (adopting only run ids the session has never observed — a terminal record
  seen on mount is recorded as known, so a stale pre-existing run can never masquerade as a
  failed start's outcome), treats the empty cancel acknowledgment as status-only (the polling
  loop is the one writer of run state), and re-adopts a still-running run on mount. Starting any check opens the workspace
  drawer's Checks section — notice line, per-run rows (label, `<code>` command, text status,
  exit code, truncation marker, Cancel/Run again), and captured output in a lazily-mounted
  `<details>` `<pre>` rendered strictly as JSX text.

## Git observation: read-only working-tree status and diffs

- **One app-owned read-only adapter.** `perk_dev.prose_review.git.GitReader` (app-lifetime,
  injectable via `create_app(git_reader=...)` — the `check_commands` seam) owns ALL Git
  interaction. Its argv tables are module-level constants pinned by test: `git status --porcelain
  --no-renames --untracked-files=all -z` and the two diff forms (`git diff --no-ext-diff
  --no-textconv --no-color HEAD -- <path>`; untracked paths take the synthesized add-diff
  `git diff … --no-index -- /dev/null <path>`), each prefixed with `-c core.fsmonitor=false`
  (the config key may name an external hook executable). No endpoint or process adapter exposes
  any mutating Git operation (the PRD non-goal); structural never-rules pin every argv to
  `git` + `status`/`diff` with zero mutating tokens, and the only request-derived argv content is
  one catalog-membership-validated path placed after `--` — executed under
  `GIT_LITERAL_PATHSPECS=1`, so a catalog file legally named like a glob (or one starting with
  `:(magic)`) can never expand into other files. `src/perk/substrate/git.py` is
  deliberately broad (checkout/reset/push/…) and is NOT the exposed adapter; everything lives in
  perk-dev.
- **One bytes-mode spawn site.** `git._run_captured_bytes` is the second sanctioned perk-dev
  subprocess literal (the checks-`_spawn` precedent, `tests/test_tooling.py`): porcelain `-z`
  emits raw pathname bytes and diff output embeds file content bytes, so
  `perk.substrate.proc.run_captured` (text-mode, strict locale decode) is unusable. All decoding
  happens inside the adapter's failure boundary: porcelain records decode strict-UTF-8 PER RECORD
  (an undecodable pathname is counted as an anonymous outside-catalog change — it can never name
  a catalog path — while a structurally malformed record fails the whole status closed); diff
  bytes decode with `errors="replace"`, so a request can never surface a decode error.
- **The narrowed, honest process-envelope claim.** The env overlay pins off prompts
  (`GIT_TERMINAL_PROMPT=0`), opportunistic index writes (`GIT_OPTIONAL_LOCKS=0`), partial-clone
  lazy fetches (`GIT_NO_LAZY_FETCH=1` — `git diff HEAD` may otherwise contact a promisor remote),
  and pathspec expansion (`GIT_LITERAL_PATHSPECS=1`); fsmonitor hooks are pinned off per
  invocation; `--no-ext-diff`/`--no-textconv` pin external diff drivers and textconv helpers off. Git-config-driven content filters
  (`filter.<driver>.clean` selected by `.gitattributes`) are explicitly OUTSIDE the suppression
  claim: they run with the repo owner's own configuration and authority — the workbench adds no
  authority beyond what `git status`/`git diff` already execute in the owner's shell. The timeout
  kill is `subprocess.run`'s child-only kill (no process-group escalation) — an accepted,
  documented residual.
- **The folded per-file state derives from the served diff baseline.** One view: working tree vs
  `HEAD` (staged + unstaged combined). Porcelain XY pairs fold to the closed vocabulary
  `modified | added | deleted | untracked | conflicted` by HEAD/worktree presence — unmerged
  pairs are `conflicted`; intent-to-add (` A`) is a new path relative to HEAD → `added`; a
  both-absent record (e.g. `AD`) is dropped entirely (its HEAD diff is empty — no row, no badge,
  not counted); same-path records coalesce into ONE entry with tracked records winning (`git rm
  --cached` leaves `D ` + `??`, and `git diff HEAD` serves the staged deletion the tracked record
  describes); an unrecognized XY lands safely in `modified` — so a badge never promises a change
  its diff can't show. `--no-index` rc 1 is disambiguated
  explicitly (it means "differs" OR an operational error): only a clean-stderr, non-empty-patch
  rc 1 is a difference; everything else fails closed as `git-error`.
- **Bounds.** The only unbounded input — an arbitrary worktree file — is refused BEFORE spawning
  git (`stat().st_size > 5_000_000` → `too-large`); the decoded diff text is capped at its first
  500,000 code points with `truncated=True`. Accepted, documented residuals: HEAD-side content is
  committed repository state (bounded by the repo the owner committed), and status output is
  O(changed paths) porcelain records with no file content. Executions run with a fixed 10s
  timeout, fresh per request — no caching, no coupling to the catalog generation.
- **Two always-200 GET envelopes.** `GET /api/git/status` → `GitStatusOut`: the handler captures
  the current generation and partitions the reader's folded entries by `units_for_path`
  membership — catalog-mapped paths list path-sorted `entries`, everything else (anonymous
  undecodable records included) is only ever counted in `other_change_count`. `GET
  /api/git/diff?path=…` → `GitDiffOut`; a path with no mapped units in the current generation is
  the fixed no-leak 404 `unknown path` (the `/api/source` posture) — reader unavailability is
  never an error status but a tagged envelope with the closed reason vocabulary
  `git-missing | timeout | too-large | git-error`. Envelope invariants are enforced by DTO
  construction and re-pinned by the frontend's reject-unknown parsers (contradictions parse to
  null): available status ⇒ `reason is None`; unavailable status ⇒ no entries and a zero count;
  available diff ⇒ `reason is None` and `diff` a string (possibly empty); unavailable diff ⇒
  `diff is None` and `truncated is False`. Both GETs are read-only (no CSRF), and time-varying
  Git state is never baked into the immutable tree/inspect DTOs — the frontend joins by `path`.
- **The frontend surfaces.** `src/git.ts` owns the closed wire vocabulary, the reject-unknown
  parsers, the classified never-throwing fetch helpers, and the complete fixed copy tables;
  `src/gitDiffCache.ts` is the per-row diff state machine (fetch once per status snapshot,
  results retained across close/reopen, generation-tagged latest-wins invalidation on every new
  status outcome, out-of-order stale responses dropped). The App loads status through the
  existing catalog-tree effect shape (cancelled-flag cleanup) keyed on the catalog epoch plus a
  manual refresh counter (bumped by the drawer's Refresh button and by a writes-frozen false→true
  transition — a save landed even though the catalog refresh failed); during a refresh the prior
  loaded view stays visible with Refresh locked. Tree unit branches (canonical and shape-layer
  placements alike) render a text state badge (never color-only), the inspector identity block
  gains a "Working tree" row with a View-changes drawer handoff, and the workspace drawer gains
  the "Git changes" section (the Checks-section pattern): path-sorted rows with lazily-mounted
  per-row diff bodies, a count-only note for changes outside the catalog, and fixed copy for
  every loading/failed/unavailable/empty/truncated arm.

### Diff rendering: `@pierre/diffs`

- **The adoption.** Drawer diffs render through `@pierre/diffs@1.3.5` (exact dev-only pin,
  wholesale through the workspace's zero-runtime-dependency posture): `PatchDiff` in unified
  view with `disableFileHeader: true`, `hunkSeparators: 'simple'`, the default pierre dark/light
  themes, and `themeType: 'system'`. The default `shiki-js` engine bundles through Vite and
  serves same-origin (`script-src 'self'` unchanged; its lazily-imported language chunks are
  ordinary `/assets` modules).
- **The CSP tradeoff.** The library injects shadow-root `<style>` nodes AND emits `style="…"`
  attributes, so `style-src` carries `'unsafe-inline'` (both the `-elem` and `-attr` vectors —
  no narrower carve-out exists). Accepted deliberately: script-src/connect/img/font stay
  `'self'`, so style injection has no exfiltration destination; the dom-sinks scan and the
  reject-unknown parsers remain the HTML/script-injection guards, and our own code keeps the
  app.css-only discipline as a house rule (the `app.css` header comment).
- **The jsdom seam constraint.** The library's heavy DOM/layout machinery (ResizeObserver,
  scrollbar measuring, virtualization) is not renderable in jsdom, so `GitDiffView.tsx` is the
  ONLY module importing `@pierre/diffs/react`; `main.tsx` (the production composition root)
  passes it into `App`, whose default for the `gitDiffView` prop is the built-in literal-text
  view — one composition shape, no conditional fallback; the real-renderer leg is proven by tsc
  plus the browser dogfood. `PatchDiff` rejects an empty patch, so empty and truncated rows
  render the built-in text view/fixed copy instead — the rejection is structurally unreachable.
- **Future-migration intent (recorded, not scheduled).** The save-review diff
  (`saveReview.ts`'s `createTwoFilesPatch` `<pre>`) and Compare mode (`CenterPane`'s `diffLines`
  panes) are candidates to migrate onto `@pierre/diffs` once the Git-diff adoption has soaked —
  a deliberate user-requested follow-up, out of scope for the Git-annotation slice.

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
  Browser affordances carry no duplicate source-family table: the backend remains the admission
  authority. `canReview`, the frozen review, and `canSave` are exposed only while the current
  projected view is editable. Navigating to a same-path whole-unit, indirect, unsupported, missing,
  ambiguous, invalid, or adapter-unavailable presentation hides the textarea/review/actions without
  deleting the path-owned buffer or review; returning to an editable fragment restores them.
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
  retryable reconciliation, never ordinary save retry. A loaded `refused/write-failed` is different:
  the server has re-confirmed the baseline, so the workspace retains the exact frozen review and
  permits an explicit byte-identical same-buffer dispatch. Any edit, discard, reload, baseline
  adoption, other refusal, conflict, or indeterminate result keeps the existing invalidation and
  recovery rules. Successful save adopts returned metadata and retains its read-only lineage/check
  report. Catalog-refresh failure or reconciled lost success
  freezes later writes with truthful external repair/copy guidance. There is no custom unload text,
  background persistence, backup, autosave, or force overwrite. In-app check execution exists only
  through the explicit allowlisted CheckRunner on user action (the section above) — saves still
  never auto-run anything.
- **Frontend dev loop (one `dist/` writer at a time):** launch the server once
  (`perk-dev prose-review` rebuilds on launch), then start the **build watcher**
  (`npm run dev --workspace tools/prose-review` = `vite build --watch`, not a dev server) and
  simply reload the page — the server rereads `dist/` from disk on every request, so no relaunch
  is needed to pick up watcher output. Stop the watcher before relaunching: the launcher's own
  rebuild writes the same `dist/`, and two concurrent writers may race. Vite's actual dev server
  is deliberately unusable against the API: the single-origin Host guard rejects any other
  origin, and no CORS/proxy escape hatch exists.

## Keyboard & accessibility

The PRD §5 contract, hardened across the shipped surfaces. Deliberate simplicity: every
interactive element is a native control keeping its own Tab stop — **no** ARIA composite-widget
roles (no `role="tree"`, no combobox), **no** roving tabindex, and **no** single-key shortcut
layer. The additions below make the PRD's seven verbs *efficiently* reachable; revisit only if a
later acceptance pass demands more.

### Shortcut vocabulary

| Key | Where | Behavior |
| --- | --- | --- |
| `F6` / `Shift+F6` | global | Cycle pane focus forward/backward: header → tree → center → inspector → drawer (only while open) → wrap. Moves DOM focus to the pane container (`tabIndex={-1}`); `preventDefault()`. |
| `ArrowDown`/`ArrowUp` | tree pane | Move focus to the next/previous button inside the tree pane in DOM order (visible order — collapsed branches are unmounted), clamped at the ends. When the pane container itself is focused (post-F6), `ArrowDown` focuses the first button. |
| `Home`/`End` | tree pane | First/last tree button. |
| `Esc` | search bar | Close the results panel; focus returns to the search input. |
| `ArrowDown` | search input, panel open | Focus the first selectable result button. |
| `ArrowDown`/`ArrowUp` | search result buttons | Next/previous result, clamped; `ArrowUp` from the first result returns focus to the input. |
| `Esc` | workspace drawer | Close the drawer; focus returns to the Workspace button. |
| `Ctrl/Cmd+S` | global | Review-gated save mirroring the buttons exactly: with a loaded source in Edit mode — if a review is open and `canSave` → `saveReviewed`; else if no review is open and `canReview` → `beginSaveReview`; else no-op. Always `preventDefault()` (the browser save-page dialog is suppressed app-wide). |
| `n` / `p` (no modifiers) | inside the Compare result | Next/previous change (same action as the legend buttons). |

### Focus policy

- Opening the drawer does **not** steal focus (the button's `aria-expanded` conveys state; the
  drawer joins the F6 cycle and native Tab order). The drawer's **Open** action (select source +
  close drawer) focuses the center pane container so focus is never left on an unmounted node.
- Selection changes (tree/search/inspector) never steal focus — F6 covers moving to the result.
- Mode switching and relationship selection get no dedicated keys: F6-to-center reaches the mode
  bar in one Tab; F6-to-inspector reaches the relation buttons.

### Non-color state rules

State is never communicated by color alone: check statuses, Git states, `Dirty`, and
editable/read-only badges are text; mode and assembly-view buttons carry `aria-pressed` +
font-weight; the selected comparison target carries font-weight + `aria-current`. The selected
tree entry adds `aria-current="true"`, `font-weight: 600`, and an inset `currentcolor` start bar
(shape, not hue) over its background tint. Compare chunks render as native `del`/`ins` with
explicit `line-through`/`underline` decorations (mirrored onto the legend badges); the tinted
backgrounds are the secondary cue.

### Focus visibility and the 200%-zoom reflow

- **Authored focus rings, never suppression.** The programmatic-focus targets (the five pane
  containers, `del`/`ins` chunks, the comparison panes) get an authored
  `:focus { outline: 2px solid currentcolor; outline-offset: -2px; }` — UA `:focus-visible`
  heuristics don't reliably ring `tabIndex={-1}` elements. Native controls keep UA defaults; no
  other focus restyling exists, and `app.css` never suppresses outlines — a source-scan guard in
  `accessibilityComponents.test.ts` pins `/outline\s*:\s*(none|0)/` absent.
- **One `@media (max-width: 960px)` block** is the 200%-zoom proxy (common 1280–1920-px windows
  at 200% land at 640–960 CSS px — the PRD names no exact width, only the licensed
  inspector-stacking reflow): the grid becomes two columns / four rows (tree stays left, the
  inspector stacks under the center pane, both keep their own scroll), the comparison grid stacks
  to one column with a `12rem` per-pane `min-height`, and the search bar wraps.

Behavior contracts live in `tools/prose-review/keyboardNav.test.ts` (the pure cycle/step
helpers) and `tools/prose-review/accessibilityComponents.test.ts` (the rendered
contract); the CDP browser leg re-verifies real focus rings, `F6` reachability, and the CSS
geometry that jsdom cannot observe.

## Build policy: rebuild on every launch

The launcher runs the Vite build (via `perk.substrate.proc.run_checked`) before binding the
socket; a build failure is a typed CLI error (`frontend_build_failed`) and no server starts.
Existence is never treated as freshness. Tests never share the launcher's `dist/`: the
server-integration fixture builds unconditionally, once per module, into a fixture-owned temp
directory (`vite --outDir`), so no two processes ever write one output dir.

### Test regime: the prose suites are opt-in

The perk-dev prose suites — `tests/test_prose_review_*.py`, `tests/test_prose_map*.py`,
`tools/prose-map/*.test.ts`, and `tools/prose-review/*.test.ts` — are a deliberate opt-in
carve-out from the default framework suites: they are heavy (Vite builds, real uvicorn servers,
the Node selector helper) and guard a personal maintainer tool, so default `pytest`/`just test`
runs and the `[[ci.checks]]` rows never collect or run them (there is no `prose-review-check` CI
row). The two explicit runners are `just prose-review-test` (sets `PERK_PROSE_REVIEW_TESTS=1`,
lifting the `tests/conftest.py` collection-ignore gate) and `just prose-review-check` (workspace
tsc + the prose-map and workbench node:test suites + the Vite build). Static coverage stays
default: `typecheck-js` still runs the workspace tsc, `typecheck-py` (ty) still covers `tests/`,
and `lint-py`/`lint-js` still lint everything. Accepted consequence (explicit decision): the
repo-wide living-map drift guard (`test_prose_map.py::test_repository_prose_map_is_complete_and_current`)
leaves default CI — map drift is caught only by on-demand runs of the suite or the in-app
prose-map check.

## The security envelope (pinned invariants)

The guard is the **outermost ASGI wrapper** (`SecurityGuardMiddleware(fastapi_app)` — outside
Starlette's `ServerErrorMiddleware`), HTTP-scope-only; lifespan/websocket scopes pass through
untouched (no websocket routes exist — a future node adding them must give them their own guard
policy first; the lifespan pass-through is what runs the CheckRunner's shutdown hook). Pure ASGI
keeps the guard streaming-transparent, which the offset-polling CheckRunner now relies on.

| Invariant | Enforcement | Test |
|---|---|---|
| Loopback origin only: exactly `127.0.0.1:<port>` | The launcher binds `127.0.0.1:0`; the guard requires the `Host` header to byte-equal the one printed origin (`localhost` spellings, foreign hosts, missing port all 403) | `test_prose_review_web.py::test_host_rejection` (×3); `test_prose_review_integration.py::test_wrong_host_is_rejected_over_real_http` |
| Origin exact-match | An `Origin` header, when present, must equal `http://127.0.0.1:<port>` exactly, else 403 | `test_origin_exact_match_passes_and_foreign_origin_is_rejected` |
| CSRF token on every non-GET/HEAD request | Meta-tag injection: `index.html`'s `__PROSE_REVIEW_CSRF__` placeholder is replaced at serve time with the process token (`secrets.token_urlsafe(32)`); the guard requires **exactly one** `X-Prose-Review-Csrf` header `secrets.compare_digest`-matching it (zero/duplicate/wrong → 403). Projection and save share one mutation-header helper and refuse missing/empty metadata locally. | `test_csrf_all_four_arms`; projection/save security arms in `test_prose_review_web.py`; `sourceLoad.test.ts`; `saveLoad.test.ts` |
| Repo-rooted read containment | Every **repository-content** read belongs to one of three families. Built-asset reads (`index.html` included) go through the contained-read helper: re-resolve the dist root, require it under the resolved repo root, resolve the candidate, require it under the dist root and a regular file — an escaping `dist/` symlink cannot launder outside targets in. Canonical-source reads go through the SourceAdapter (`perk_dev.prose_review.source_adapter`): lexical absolute-path rejection, resolved containment under the repo root, catalog membership, one descriptor for regular-file/mode/byte sampling, and strict UTF-8 — serving-path-exclusive. Supplied-text projection never calls that reader. The adapter-owned random TypeScript request is controlled IPC containing only that already-authorized snapshot; its generated path, fixed helper root, and unconditional cleanup are separately pinned. The third family is the observation-only GitReader (its own rows below). | traversal, child-symlink, `assets/`-dir-symlink, `dist`-root-symlink, and `index.html`-symlink tests in `test_prose_review_web.py`; traversal/absolute/symlink/NUL/non-text, same-descriptor metadata, canonical-read exclusion, and TypeScript temp-snapshot/cleanup/root-separation arms in `test_prose_review_source.py` |
| Repo-rooted conditional write containment | Save accepts no caller path/selector/adapter/mode. The active catalog resolves every same-path unit through `source_adapter_for` and admits only one shared Markdown, YAML, Python, or TypeScript adapter identity; generated sources, unmapped/mixed families, absolute/traversal/nonregular paths, and every symlink component refuse. Python validation parses/compiler-validates without execution; TypeScript sends only the reviewed buffer and catalog selectors through the fixed parser-only helper. Both re-resolve every mapped selector before mutation. Early and post-temp no-follow samples enforce the load hash; only a late-matching same-directory temp reaches `os.replace`, while helper failure re-samples before returning determinate failure/conflict. | adapter-identity admission, Python non-execution/validation, real TypeScript helper success/failure, lineage, traversal/symlink, early/late conflict, exact-byte/mode, atomicity, and failure-cleanup arms in `test_prose_review_save.py`; production catalog-refresh and strict HTTP arms in `test_prose_review_web.py`; separate-root real-uvicorn saves in `test_prose_review_integration.py` |
| Text-only rendering (this node's slice) | React JSX text interpolation (escaped by default) + a node:test source scan banning HTML sinks (`innerHTML`, `outerHTML`, `insertAdjacentHTML`, `dangerouslySetInnerHTML`, `document.write`) + the CSP as backstop | `tools/prose-review/dom-sinks.test.ts` (with a vacuousness self-check) |
| CSP + hardening headers on **every** HTTP response | `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'` plus `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` — stamped by the guard on rejections, 404s, and framework-generated 500s alike. `style-src` carries `'unsafe-inline'` solely for `@pierre/diffs`' shadow-root `<style>` nodes and style attributes (both `-elem` and `-attr` vectors; no narrower carve-out exists) — an accepted, documented envelope amendment; every other directive is unchanged and style injection has no exfiltration destination | header assertions on every response shape, incl. `test_unhandled_exception_response_is_still_header_stamped` (pins the outermost placement) |
| No framework doc surfaces | `docs_url=None, redoc_url=None, openapi_url=None` | `test_framework_doc_surfaces_are_disabled` (×3) |
| Closed fixed-argv check allowlist | `CHECK_COMMANDS` is the one execution table: complete fixed argv per id, zero request-derived argv, no `just`/`npm run` script indirection, no mutating flags, `run_ci` and the full gates structurally absent; the client sends only a closed `CheckId` (Literal-validated 422 boundary) | the allowlist pin + structural-invariant tests in `test_prose_review_checks.py`; 422/404 arms in `test_prose_review_web.py` |
| No shell in check execution | One sanctioned `subprocess.Popen` site (`checks._spawn`): list argv, `cwd=`, `start_new_session=`, devnull stdin, merged text pipes | the Popen guard in `test_tooling.py`; spawn/capture arms in `test_prose_review_checks.py` |
| One check-run slot + reconciliation | A busy slot is HTTP 409 `check already running`; `GET /api/checks/latest` is the reconciliation read for reloaded/raced clients; a bounded 20-record ring backs polling with the fixed 404 `unknown check run` beyond it | busy/ring/latest tests in `test_prose_review_checks.py` + `test_prose_review_web.py` |
| Bounded check-output capture | 2,000,000-code-point cap; past it the record is `truncated` and the reader drains without storing (the child never blocks on a full pipe) | `test_output_cap_truncates_and_keeps_draining` |
| Process-group cancellation/timeout with a single finalizer | Cancel/timeout set flags under the lock and escalate SIGTERM → 5s whole-group-probed grace → SIGKILL outside it (the probe is `killpg(pgid, 0)`, so a SIGTERM-resistant descendant is still killed); only the reader thread assigns terminal status, clears the slot, and cancels the timer; flag precedence `cancelled` > `timeout` > exit-code | cancel/timeout/idempotence/resistant-descendant/thread-settling tests in `test_prose_review_checks.py`; the real-HTTP cancel round trip + lifespan-shutdown-with-active-run arm in `test_prose_review_integration.py` |
| Check shutdown is app-scoped | `runner.shutdown()` rides the FastAPI lifespan (no `atexit`): the active run's process group dies and the reader joins on graceful shutdown | `test_shutdown_kills_the_active_run_and_leaves_no_threads` |
| Checks never touch catalog state | Check runs never take `source_transaction_mutex`, never read or swap the generation, and stay permitted while `writes_frozen`; they observe the live working tree by design | `test_checks_stay_permitted_while_writes_are_frozen` |
| Fixed read-only Git argv + env pins | The three argv tables are module constants: every argv starts `git`, the subcommand ∈ {`status`, `diff`}, the only `-c` is `core.fsmonitor=false`, and no mutating token exists; the env overlay pins `GIT_TERMINAL_PROMPT=0`, `GIT_OPTIONAL_LOCKS=0`, `GIT_NO_LAZY_FETCH=1`, `GIT_LITERAL_PATHSPECS=1`; every execution uses `cwd=<repo root>` and a 10s timeout. Config-driven `filter.<driver>.clean` content filters are outside the suppression claim (the owner's own git config/authority); the timeout kill is child-only — both accepted, documented residuals | `test_fixed_argv_constants_are_pinned`, `test_structural_never_rules_over_every_fixed_argv`, `test_every_execution_uses_pinned_cwd_timeout_and_env_overlay` in `test_prose_review_git.py` |
| One bytes-mode captured Git spawn | `git._run_captured_bytes` is the only other sanctioned perk-dev subprocess literal (list argv, explicit `check=`/`timeout=`); porcelain and diff bytes decode inside the adapter's failure boundary (per-record strict UTF-8, `errors="replace"` diff text), so responses are always-200 envelopes | the wrapper guard in `test_tooling.py`; fold/decode/failure arms in `test_prose_review_git.py` |
| Catalog-scoped Git exposure | The status handler partitions folded entries by captured-generation `units_for_path` membership — non-catalog paths (anonymous undecodable records included) are count-only, never listed; a non-catalog diff path is the fixed no-leak 404 `unknown path`; the diff path is the only request-derived argv content, sits after `--`, and is literal (`GIT_LITERAL_PATHSPECS=1` — never a pathspec) | partitioning/404/envelope pins in `test_prose_review_web.py`; the literal-pathspec real-git arm in `test_prose_review_git.py`; the real-repo round trip in `test_prose_review_integration.py` |
| Bounded Git diff serving | The worktree file is size-checked BEFORE any spawn (> 5,000,000 bytes → `too-large`); decoded diff text caps at 500,000 code points with `truncated=True` (truncated rows render the built-in text view, never the library). HEAD-side content (committed state) and O(changed paths) status output are accepted, documented bounds | bounds arms in `test_prose_review_git.py`; the truncated-row gate in `workspaceComponents.test.ts` |

## The round-trip proof split

The original round-trip proof — the served page rendering `CatalogSummaryOut` — is **historical**:
the served page is now the three-pane workbench shell, which fetches `/api/catalog/tree` and
`/api/source` through their typed parse boundaries (`parseTree` / `parseUnitSource`, with the
closed wire vocabulary in `tools/prose-review/src/wire.ts`). `/api/catalog/summary` still serves
its original contract; `parseSummary` remains its typed local mirror, now exercised by tests only.
The relationship inspector, catalog search, and comparison projection added `/api/inspect`,
`/api/search`, and `/api/compare` — all pure in-memory snapshot queries (the search index is built
once in `create_app`), so no new file-read family was added there (the Git observation adapter
later became the deliberate, observation-only third family — its own section above). `parseUnitInspect`, `parseSearch`,
`parseComparisonOptions`, and the nested source parsers structurally require known fields and closed
vocabularies while tolerating additive unknown response keys. The comparison options loader adds
response-origin matching plus endpoint-specific latest-wins/clear/dispose invalidation.
The proof structure remains **server integration** (real Vite build, real uvicorn on a pre-bound
socket, real nested `*Out` DTOs, a CSRF-authenticated supplied-text projection with unchanged disk
load afterward, and exact-byte/mode/hash Markdown, YAML, focused Python, and focused TypeScript saves
followed by catalog refresh observations. The writable source trust root and fixed TypeScript helper
checkout root remain separate. Production-reload coverage rebuilds a disposable real catalog after
marker-preserving Python and TypeScript saves, proves the replacement generation still exposes the
edited TypeScript unit and permits a later save, and pins marker-removing Python saves to the
committed-but-stale write freeze. Frontend proof remains node:test coverage of every parse/transport
boundary and the pure workspace state machine, including determinate write-failed same-buffer retry.
(All of these proof suites now run only through the opt-in `just prose-review-test` /
`just prose-review-check` gates — the test-regime section above — never in default CI.)
A jsdom harness loads TSX through the exact-pinned `tsx` API to exercise the rendered App coordinator
(fragment preservation, placement invalidation, stale outcomes, mode reset, duplicate choice
occurrence identity, attention drawer, discard, unload lifecycle, catalog-epoch refresh, and write
freeze) and CenterPane (shared path loads, focused textarea, transient retry, native current-text
diff chunks, frozen save review, same-path direct/indirect presentation gating, diagnostics,
conflict/reconciliation, and escaped handoffs). The keyboard & accessibility contract (the section
above) adds `keyboardNav.test.ts` for the pure pane-cycle/list-step helpers and
`accessibilityComponents.test.ts` for the rendered contract — F6 cycling with the open-drawer leg,
tree arrow navigation and `aria-current`, search panel keys, drawer Esc/Open focus moves, the
review-gated Mod+S round trip, Compare `del`/`ins` traversal, and the never-suppress-outline
source scan. The packaging guard pins the diff and test libraries
as exact dev-only dependencies while preserving the workspace's zero-runtime-dependency posture.

The launcher-served **browser** leg covers source-native focused editing across
Markdown/YAML/Python/TypeScript, alias/back-navigation retention, immediate workspace-backed Compare,
two-file dirty/Open behavior, mode preservation, and explicit reviewed
Markdown/YAML/Python/TypeScript persistence. Mapped Python named symbols and direct TypeScript
fragments use the shared full-file review/save controls, while Python-backed managed prose preserves
its read-only materialization handoff and unsupported/indirect TypeScript expressions remain
explicitly non-editable. The rendered jsdom contract covers temporary-invalid focus,
stale-helper/transient retry, discard cancel/confirm, exact manual reversion, `beforeunload`, frozen
full-file diff metadata, hostile-text escaping, conflict Copy/Reload, indeterminate reconciliation,
catalog refresh/invalidation, and refresh-failure freeze. Shape-origin layer selection,
placement-aware option refresh, graph-backed target families, boundary omission, independent pane
scrolling, empty-target copy, mode-local reset, the Assembly preview (auto first-scenario render,
POST-free visibility toggles, exact concatenated markers, scenario-switch override reset,
buffer-edit re-render through the injected-workspace seam, hostile-text escaping),
relationship/search, and Host/Origin/CSP/no-store hardening remain in the regression pass. Unsaved workspace state still
has no browser persistence; only an explicit revision-reviewed save can mutate an admitted canonical
file.

## Acceptance evidence (PRD §11)

The eight acceptance scenarios, each with its automated evidence (the exact suites/tests — all in
the opt-in prose gates, the test-regime section above) and its manual leg. The manual walk ran
against the real launcher and real checkout (headless Chrome over CDP, trusted key events for the
keyboard legs — the node 5.2/5.3 dogfood convention); the full per-scenario checklist is recorded
on the node's plan issue (#1869, closed by the node PR).

| # | Scenario | Automated evidence | Manual leg (recorded on #1869) |
|---|---|---|---|
| 1 | Warm/cold family | `test_prose_review_catalog.py` (real-catalog `plan.warm`/`plan.cold`, canonical aliases: `test_consumers_and_aliases_distinguish_canonical_and_shape_placements`); `test_prose_review_comparison.py` (plan-skill warm↔cold sibling options); `comparisonComponents.test.ts`; the integration compare round trip | Planning → Plan authoring lists both doors; the inspector names both as consumers of one canonical skill unit; Compare cold↔warm shows no differences |
| 2 | Shared buffer | `editWorkspace.test.ts` (one buffer per path); `workspaceComponents.test.ts` (alias/Compare shared unsaved bytes); `assemblyComponents.test.ts` (App-level buffer-edit re-render) | The plan skill edited via one assembly placement; alias, Compare, and Assembly panes all reflect the one buffer |
| 3 | Layered preview | `test_prose_review_assembly.py`; integration `test_assembly_options_…`/`test_guarded_assembly_render_round_trips_workspace_buffers_over_real_http`; `assembly*.test.ts` | `implement-interactive` and `implement-remote` previewed (the PRD's named pair); boundary placeholders labeled; per-scenario defaults applied |
| 4 | Safe save | `test_prose_review_save.py` (exact bytes/mode/atomicity); `test_prose_review_web.py` (generation swap); integration `test_all_editable_families_save_over_real_http_with_exact_atomic_write`; `save.test.ts`/`saveLoad.test.ts`/`workspaceComponents.test.ts` (review gate, baseline adoption) | A real Markdown section edited → review diff → byte-exact save (fs-verified) → clean workspace → suggested prose-map check run to `Passed · exit 0` |
| 5 | Conflict | `test_early_conflict_creates_no_temp`, `test_late_conflict_after_temp_preparation_cleans_temp_without_replacement`, `test_failure_classifier_reports_external_change_as_conflict`; frontend conflict Copy/Reload tests | External edit after load → save refuses; disk keeps the external content, the buffer keeps the edit; Copy Edits + confirmed Reload offered |
| 6 | Invalid source | TS parser-diagnostic save arms; `test_python_save_missing_mapped_symbol_is_validation_failure_without_mutation`; `test_validation_is_syntax_first_and_leaves_target_unchanged`; the missing-heading batch arms in `test_prose_review_source.py` | Broken TS syntax refused at save with the structural diagnostic, disk untouched; mapped-heading removal is structurally unreachable from the UI (headings live in read-only context; whole-unit markdown is read-only) — the refusal itself is automated |
| 7 | Containment | traversal/symlink/generated/unmapped arms across `test_prose_review_save.py`/`test_prose_review_source.py`/`test_prose_review_web.py` (asset containment incl. dist-root symlinks) | Spot-check only (the save transport is path-incapable from the UI): traversal/absolute unit ids 404, CSRF-less save 403, non-catalog git diff the no-leak 404 — the automated arms are primary |
| 8 | Graph drift | `test_prose_map.py` CLI drift failure + repo currency; the checks allowlist pin; `test_prose_review_checks.py::test_real_prose_map_argv_passes_against_the_repository` (the real-argv transport arm) | An unmapped model-facing tool field injected → the drawer's prose-map run fails naming it (`unclassified-tool-field … walkProbe`); revert → passes |

Cross-cutting additions from this node: `tools/prose-review/hostilePayload.test.ts` (ONE hostile
payload through all five panes — source, save-review diff + drawer Git diff, validation/refusal
error surfaces, Assembly separate + concatenated preview, check output — literal at every stop,
zero materialized elements) plus a browser-side hostile spot-check during the walk.

**A11y verification outcome (verify-only, no new code — a11y is a recorded non-goal):** the
check-output and Git-annotation surfaces inherit the keyboard & accessibility contract — F6
reaches the open drawer, Tab reaches Cancel/Run again, the Output disclosure, Git Refresh, the
per-row Diff disclosures, and the inspector View-changes handoff; statuses are readable as text.
**Accepted limitation (recorded, not fixed):** the scrollable text regions (`.check-run-output`,
`.git-diff-raw`, `.save-diff`, `.assembly-rendered`, `.source-text`) have `overflow: auto` but no
`tabIndex`, so they are not keyboard-scrollable.
