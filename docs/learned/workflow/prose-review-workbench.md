---
title: The prose-review workbench + prose-map governance — launcher security, source adapters, edit workspace
read_when: Working on perk-dev prose-review, tools/prose-review, or tools/prose-map — launcher security, closed adapters, parser traps, wire DTOs, EditWorkspace, assembly/check/git/search/compare surfaces
cluster: prose-governance
---

# The prose-review workbench and prose-map governance

The binding architecture record is `docs/design/prose-review-stack.md`. It owns the system shape
and settled component boundaries. This learned doc does not duplicate that architecture; it
records the cross-cutting traps that recur when the prose-map catalog, FastAPI/Vite workbench,
source adapters, wire protocol, edit workspace, and the assembly / check / Git / search / compare
surfaces beside them evolve.

## Distillation

- The launcher contains every URL-derived read, passes websockets through only under the current
  no-websocket-route posture, rebuilds from disk, and has one `dist/` writer — "Launcher security
  and the development loop".
- Catalog failures are fail-closed by result trustworthiness (policy-definition errors block
  discovery, registration-shape errors become typed findings); `sync` is whole-projection (sweep
  foreign `unmapped-unit` drift, re-measure count pins from the catalog); a new governed tool bumps
  three pins under the opt-in suites `run_ci` never runs — "Prose-map catalog governance".
- Closed adapter vocabularies are exhaustive at domain/DTO/route boundaries; syntax validation
  precedes selectors and subprocess adapters are bounded — "Source-adapter contract craft".
- PyYAML merge tags, inherited values, and comment-suffixed document markers require lexical and
  semantic evidence — "PyYAML lexical-resolution traps".
- Python name policy is split — shared node-side predicate, resolution-only selector-string
  admission, a live-catalog test as the only tripwire — "Python AST and tokenize traps".
- TypeScript selectors keep one identity scheme per collision bucket and isolate the pinned private
  compiler seam — "TypeScript selector and compiler traps".
- Frontend wire vocabularies mirror Python manually, endpoint parsers stay local, identities are
  occurrence-based, and legal null combinations become unions — "Frontend wire posture".
- `EditWorkspace` trusts descriptors, validates cache algebra, returns defensive copies, and binds
  edits to revisions — "EditWorkspace invariants".
- Assembly, CheckRunner, Git observation, search, and compare: server-owned argv/refs, request
  paths admitted only by catalog membership, closed reason vocabularies mirrored per endpoint —
  "Shipped surfaces beyond the edit loop".
- JSX/component-render coverage remains a named browser-dogfood gap, not an implied unit-test pass —
  "Standing proof gap".
- The workbench constrains extension topology: registration prose stays inline (the TS adapter
  cannot follow identifier indirection), inlining changes fragment counts, and the prose suites
  are an opt-in carve-out run explicitly — "The workbench is a topology constraint on extension
  moves".

## Launcher security and the development loop

The launcher-facing web layer treats URL paths as untrusted input. The whole contained-read chain
belongs to one refusal boundary: resolve both candidate and root, prove containment, verify a regular
file, and read it. `Path.resolve()` itself can reject an embedded NUL, so guarding only the final
read is incomplete. The exception-taxonomy rationale lives in
`workflow/broad-catch-narrowing.md`; the owning implementation is
`packages/perk-dev/src/perk_dev/prose_review/web.py`.

The ASGI host guard deliberately passes websocket scopes through because the application currently
has no websocket route. That is a posture, not generic websocket security: adding any websocket
endpoint first requires an explicit origin/host policy for that protocol. Do not assume the HTTP
middleware silently protects a new upgrade path.

Development launch rebuilds the frontend and rereads source from disk. This keeps the workbench a
projection over current files instead of a stale daemon cache. It also establishes one-writer
ownership: only one process may write `tools/prose-review/dist/` at a time. Parallel launches must
serialize the build or use isolated outputs rather than racing on generated assets.

Every dev-only npm workspace extends the publish-isolation tests in the same PR. A workspace marked
private can still enter a root package's file surface through a broad include; wheel, sdist, npm
pack, and workspace-private assertions are separate containment layers.

## Prose-map catalog governance

Choose the failure layer from how trustworthy the result remains:

- A policy-definition error means discovery cannot be trusted at all and is a catalog load error.
- A registration-shape problem leaves enough context to return a typed discovery finding and a
  nonzero check result.
- Diagnostic overlap is acceptable when two independent invariants fail. Removing one message to
  make output look cleaner can erase the only signal at another boundary.

The catalog governs top-level source fields by design. It does not recursively claim every nested
SDK or authoring policy. Keep that boundary explicit so a new top-level field forces a policy
decision without turning the catalog into a general schema system.

Generated fragment ordering follows registry insertion order. Exact-output tests that change after a
registry reorder are identifying a contract change, not formatter noise. The compile-time exhaustive
policy registry in `tools/prose-map/selector.ts` (`TOOL_FIELD_POLICIES`, `satisfies`-pinned against
the SDK tool type) and its runtime unknown-field finding form the two-layer guard described in
`workflow/source-scan-guards.md`.

A governed tool gaining a described param moves multiple prose-map count pins at once (governed
tools / TS fragments / discovery candidates) — verify with the living-map check, never assume
the outcome (#1992).

**`perk-dev prose-map sync` is whole-projection and drift-intolerant.** `sync` validates the entire
catalog and refuses (exit 1, no write) while ANY finding stands — including `unmapped-unit` findings
for routes a concurrently-landed feature never mapped. So a PR editing one route inherits every
sibling's unrouted drift: sweep the foreign `unmapped-unit` findings to their own sibling routes in
the same PR (they are not "someone else's"), then **re-measure every count pin from the real
catalog after `sync`** — never compute the new pin from your own delta, because the sweep moved
counts you did not author.

**Adding a governed `promptGuidelines`-bearing tool bumps three pins** at once: the governed-tool
count in `tests/test_prose_map.py`, the fragment total in `tests/test_prose_review_source.py`, and
the discovery-candidate count in `tools/prose-map/selector.test.ts`. They live under
`just prose-review-test` + `just prose-review-check`, which `run_ci` / `just ci` do **NOT** run — the
default gate reports green while all three are stale. Run the carve-out suites explicitly in any PR
that touches a governed tool's prose. `typescript-symbol` is a valid catalog kind (`ProseKind` in
`tools/prose-map/catalog.ts`) that no adapter currently produces — do not "fix" its absence.

## Source-adapter contract craft

A closed refusal/reason vocabulary is exhaustive at every translation boundary: domain result,
Pydantic DTO, and HTTP route. Testing all domain reasons does not prove the route maps all reasons;
mirror the matrix at each boundary. Keep `adapter-unavailable` distinct from source syntax and
selector diagnostics because it is an operational inability to run the adapter, not a property of
the document.

Validate document-level syntax once before iterating selectors. A malformed source has one document
failure independent of how many selectors the request carried. Running syntax validation in the
selector loop multiplies one cause into cardinality-dependent findings and makes batches unstable.

When two adapters implement one contract, pin their shared ordering semantics in a contract test.
Without it, each can be locally correct while returning equivalent units in a different order,
which destabilizes occurrence identity and generated review prompts.

The subprocess adapter owns its temporary request file outside the repository and passes only the
path in argv. Bound concurrency with a per-instance non-blocking semaphore and bound execution with
a timeout. A busy adapter returns its operational refusal immediately rather than queueing an
unbounded model-facing request.

Freeze plan-sized interfaces aggressively: exact `__all__`, dataclass field order, reason copy
tables, and route mappings. Those pins make review-scope disputes decidable. "Not a finding" is
meaningful only when the accepted contract is exact enough to compare.

Owning modules are under
`packages/perk-dev/src/perk_dev/prose_review/source_adapter/`, with boundary models in
`prose_review/dto.py` and route assembly in `prose_review/web.py`.

## PyYAML lexical-resolution traps

YAML merge keys are identified by their composed node tag, not by the visible key text alone.
Aliases and explicit tagging can make text-based detection disagree with parser semantics. Inspect
the lexical/composed representation when the contract is about authored source shape.

Semantic loading and lexical composition also disagree about merge-inherited values. A loaded
mapping may contain a key that has no local source span because it arrived through a merge. Enumerate
those disagreement cases and map each to the closed adapter vocabulary; do not fabricate a selector
range for inherited content.

Multi-document frontmatter has delimiter edge cases. A document marker followed by a comment is
still reachable syntax even when a line-equality check misses it. Pin comment-suffixed markers and
other delimiter variants at the adapter boundary. The YAML adapter is
`packages/perk-dev/src/perk_dev/prose_review/source_adapter/yaml.py`.

## Python AST and tokenize traps

Python applies NFKC normalization to identifiers, so a source spelling can normalize into a hard
keyword even when its raw characters do not look reserved — and `ast.parse` hands back the
*normalized* name. The name policy is **split across two predicates, not one.** The node-side
predicate `python_symbol_name` (with `python_symbols`) in
`packages/perk-dev/src/perk_dev/prose_map/python.py` decides which module-body shapes are symbols
and excludes keyword names; it IS shared — discovery emits `symbol:<name>` from it and the
adapter's `_resolve` matches AST nodes with it. The selector-*string* admission is a separate,
resolution-only rule — `_selector_name` in
`packages/perk-dev/src/perk_dev/prose_review/source_adapter/python.py` (`symbol:` prefix,
`str.isidentifier()`, `keyword.iskeyword`) — that discovery never consults because it never parses
a selector string. So the keyword exclusion lives twice and `isidentifier()` once. The drift
hazard: widening the discovered language on one side (a new `python_symbols` shape, a dotted
selector grammar) without the other lets the catalog emit a selector the adapter refuses as
`unsupported-selector`, or lets the adapter admit a shape no catalog emits and no test exercises.
Nothing in code holds the two together; the tripwire is
`tests/test_prose_map.py::test_python_owned_prompt_wrappers_are_ast_selected`, which asserts every
live-catalog Python-backed selector passes the adapter's admission rule, flanked by the per-side
pins in `tests/test_prose_map_python.py` and
`tests/test_prose_review_source.py::test_python_adapter_rejects_every_unemitted_selector_shape`.
Extend both predicates in one change and keep those pins green; centralizing the admission is an
open follow-up lead, not a fact to cite.

Token-stream structural detection anchors on logical lines, not visual columns. Marker count or
pairing mismatch fails closed; guessing the intended block can edit the wrong prose. Keep producer
and consumer on one structural detector rather than re-deriving marker grammar in each.

AST location columns are UTF-8 byte offsets, while `tokenize` columns are Unicode code-point
positions. Preserve one line-start table and provide explicit conversions in each direction. After
an edit, recomposition of untouched prefix, replacement, and untouched suffix is the cheap
corruption invariant. The owning implementation is
`packages/perk-dev/src/perk_dev/prose_review/source_adapter/python.py`; the shared node-side
symbol language (`python_symbols`, `python_symbol_name`) stays in
`packages/perk-dev/src/perk_dev/prose_map/python.py`.

Finally, `ast.parse` success does not prove compilability. Run `compile(...)` as a non-executing
validation step; compiler-only restrictions can reject an AST that parsed successfully. This is
validation, not execution of the source.

## TypeScript selector and compiler traps

Do not mix identity schemes in one exact-match collision bucket. Raw catalog identities are
authoritative; owner-local aliases belong to their own resolution scope. Combining them allows an
alias collision to suppress a distinct catalog member or lets one member resolve differently by
entry path.

The adapter uses a pinned private TypeScript compiler seam because the runtime parse-diagnostics
member needed by the source contract is absent from the public type. Isolate that fact in one
function with one narrow local intersection type and pin it with a regression. Scattering casts
through the adapter turns an upstream change into silent partial behavior.

Pin the compiler parse target as part of the contract. Discovery and resolution must parse with the
same target or one can admit syntax the other classifies differently. The adapter lives at
`packages/perk-dev/src/perk_dev/prose_review/source_adapter/typescript.py`; frontend/compiler support
is under `tools/prose-map/`.

## Frontend wire posture

`tools/prose-review/src/wire.ts` is a hand-maintained closed vocabulary mirroring the Python
boundary models. Growth of a Python enum is therefore a two-sided wire-contract change. Do not rely
on structurally compatible strings to make an omitted TypeScript variant discoverable.

Keep one parser/loader module per endpoint. Endpoint-local decoding makes response ownership and
error labels obvious; a universal parser tends to accumulate nullable products and route-specific
switches. Construction-time precomputation in `create_app` also widens every CLI test stub of that
constructor, so include the stub update in the same planned file set.

Exported seams need production callers. After adding an export, grep its uses and reject a type
re-exported only from a consumer as accidental API surface. A compile-green unused seam is not an
implemented integration.

When the server deduplicates wire lists but does not guarantee pairwise-distinct members, frontend
identity is occurrence-based. Use positional occurrence identity rather than assuming value
uniqueness. This keeps selection and React keys stable for repeated equal values.

A contract with exactly a bounded set of legal null combinations is a discriminated union, not a
product of nullable fields. Make illegal combinations unrepresentable in TypeScript and mirror the
same discriminator in Python boundary validation.

Phrase docstring guarantees at the boundary that enforces them. Absolutes such as "all sources are
unique" or "this never returns null" become false when the next endpoint adds a legitimate arm;
state what the parser or adapter actually checks.

## EditWorkspace invariants

The server-side source read is descriptor-authoritative. Open non-blocking with no-follow, run
`fstat` on that descriptor, require a regular file, and read from the same descriptor. A normal
blocking open can hang on a FIFO before validation, and checking a path before opening permits a
replacement race. The FIFO fixture with a read trap proves non-blocking refusal; the
replace-during-`fstat` fixture proves the bytes come from the validated descriptor.

A keyed cache insertion needs an algebraic acceptance invariant, not only freshness and matching
request identity. Verify recomposition of source fragments and response identity before storing.
Return defensive copies from inspection APIs so a consumer cannot mutate cached authority behind
the workspace's revision tracking.

Edit commands are revision-bound and return discriminated applied, stale, or refused outcomes. A
stale command is ordinary concurrency evidence, not an exception to flatten into a transport error.
The client implementation is `tools/prose-review/src/editWorkspace.ts`; server adapter writes live
under `packages/perk-dev/src/perk_dev/prose_review/source_adapter/write.py`.

Do not pre-author accessors for imagined consumers. A consumer-less getter expands the cache and
revision contract without proving the shape serves a real flow; add it with the node that owns the
caller.

## Shipped surfaces beyond the edit loop

`docs/design/prose-review-stack.md` owns each of these five surfaces' shape under the heading
named below; only the recurring traps live here. Shared posture: argv, refs, and identity are
server-owned; a request-supplied path is admitted only by catalog membership
(`snapshot.units_for_path`, one fixed `404` detail); every reason vocabulary is closed in Python
and hand-mirrored by its own endpoint module in `tools/prose-review/src/`, not `wire.ts`.

### Assembly preview

(Design record: "Assembly preview: `AssemblyRenderer`, the options/render API, and the
Assembly-mode frontend".) Two failure tiers: a **request-wide** defect (unknown
assembly/scenario, scenario–assembly mismatch, duplicate or unknown workspace path) raises
`AssemblyRenderError` with a closed reason that `web.py` maps to `404`/`422` before any source
read; a **per-layer** defect is a *value* — `FailedAssemblyLayer` carrying the fixed copy in
`FAILURE_DETAILS` — returned in an HTTP 200. No path, OS error, adapter diagnostic, or raw
exception text enters a result. A buffered path (even an empty string) is never reread; one
canonical read or failure is shared per path. Every authored layer is emitted once, in order;
`optional` yields presence `varies`, never a filter. Code layers are atomic — one `extract_many`
over every fragment selector, any unresolved fragment fails the layer; prompt-root Markdown is
`scan_template`-gated (grammar, any include, identifiers outside the scenario's variables)
*before* `render_text`, and only `jinja2.TemplateError` becomes `template-render-failed`. The
render route shares `source_transaction_mutex` with saves and refuses `409 catalog stale` while
writes are frozen; checks do not (below).

### The allowlisted `CheckRunner`

(Design record: "CheckRunner: allowlisted targeted checks with streamed output and
cancellation".) The closed `CheckId` `Literal` is the whole admission boundary and
`CHECK_COMMANDS` the whole allowlist — fixed argv tuples plus a timeout; a request carries only
the id. One active slot (busy → `409`), a bounded record ring (evicted → `404`), idempotent
cancel. The spawn is list argv, no shell, `cwd=` the once-resolved repo root, one killable
session — and **inherits the server's environment**: no sandbox, the reviewed argv IS the safety.
Output is capped in code points and drained past the cap; poll offsets are server-issued
code-point indexes the client echoes, never JS string lengths. Checks validate the **working
tree**: they never take `source_transaction_mutex`, never see the browser buffer, and stay allowed
while writes are frozen. Totality is a cross-file invariant: `CheckRunner.start` and
`write.py::_suggested_checks` index `CHECK_COMMANDS[...]` directly, so a `CheckId` member without
a row is a `KeyError`; a complete change aligns `CheckId`, `CHECK_COMMANDS`, each adapter's
`affected_check_hints`, the frontend `CHECK_IDS` in `checks.ts`, and the exact-table pin in
`tests/test_prose_review_checks.py`.

### Read-only Git observation

(Design record: "Git observation: read-only working-tree status and diffs".) Read-only is a
**table property, not a type**: `GitReader` runs only `git status` and `git diff` from three
fixed argv tables (`STATUS_ARGV`, `DIFF_HEAD_ARGV_PREFIX`, `DIFF_UNTRACKED_ARGV_PREFIX` —
`core.fsmonitor=false`, `--no-renames`, `--no-ext-diff`, `--no-textconv`) under `GIT_ENV_OVERLAY`,
the request path being the one appended token after `--`. `_execute` accepts any argv tuple and
the structural test enumerates exactly those three tables — a fourth table or direct `_execute`
call is invisible to it, so extend the test with the table. `GitReader` checks no membership
itself; `web.py::git_diff` is the admission boundary. Bounds are layered: the worktree file is
stat-refused as `too-large` before any spawn (a stat `OSError` skips the guard), a timeout kills
the child, and the diff text is capped post-capture. Reasons are coarse on purpose —
`git-missing` is nominal for *any* spawn `OSError`, `git-error` is the fail-closed bucket, and
decode failures never escape (undecodable status records are counted anonymously; diff bytes
decode with replacement). `--no-renames` is load-bearing for the one-path-per-record porcelain
parser; badges and patches share the HEAD↔worktree baseline (only a solely-untracked path takes
the `--no-index` diff) — change one without the other and a badge promises what the patch cannot
show. The frontend diff cache is per status generation, invalidated whole on every completed
status; nothing polls git.

### Catalog search

(Design record: the search parsers under "The round-trip proof split"; the route under "HTTP
layer: FastAPI + uvicorn".) The index is built once per catalog generation over a closed metadata
corpus (capability/shape/fragment/concern labels, unit ids, source paths, tool names) — never file
contents or browser buffers. Matching is `strip().lower()` substring (not `casefold`); result
order is index order (capability preorder, then shapes, units, fragments, concerns), unranked and
undeduped; hits are capped while `total` is not; a blank trimmed query is a browse whose `matched`
is empty. Filters are **exact owning-unit attributes**: any active filter excludes
capability/shape/concern entries outright, a fragment inherits its unit, and `"shipped"` does not
fold in `"both"`. There is no domain refusal (loader loaded|failed; a bad enum is a framework
`422`), so the client's request-generation counter is the only stale-response guard; React keys
include the owning unit because fragment ids are owner-local.

### Comparison

(Design record: the options route under "HTTP layer: FastAPI + uvicorn"; the panes under
"Frontend: Vite + React + TypeScript".) `comparison_options` is a **pure snapshot projection** —
no server text diff, no source read — over five relation families in fixed order, empty families
omitted, zero groups a success, `None` the only refusal (`404 unknown comparison subject`). A
placement is either canonical or an exact shaped one-based layer position (shape and position
travel together — a union, not two nullables). Per-family dedup is semantic, so equal-looking
targets may remain: the client keys a choice by `(relation, index)`, never by target value. The
text compared is the **whole physical-file workspace buffer** on each side (`CenterPane` runs
`diffLines` from the `diff` package over `EditWorkspace` current text, unsaved edits included);
the snapshot is authoritative only for the options and no revision token binds the two.
`@pierre/diffs` renders Git drawer diffs only; Compare's migration onto it is intent, not fact.

## The workbench is a topology constraint on extension moves

Extension refactors must treat the prose-map/workbench tooling as a structural constraint, not an
afterthought:

- **The TS source adapter cannot follow identifier indirection.** Registration prose (tool
  descriptions, guidance strings) stays **inline at registration sites**, and `sendUserMessage`
  call sites stay out of whole-file-validated installers — moving prose behind an identifier
  removes it from the adapter's fragment view (#2170).
- **Identifier→literal inlining changes fragment granularity.** An in-place array adds
  (items − 1) fragments per array — predict the count-pin delta before the move instead of
  discovering it as test churn (#2173).
- **The prose suites are an opt-in carve-out from `just ci`.** A slice touching prose-map routes
  runs `just prose-review-test` / `just prose-review-check` explicitly, and `perk-dev prose-map
  sync` is an implied deliverable of ANY injection-surface change (#2169, #2172, #2155).

## Standing proof gap

JSX glue and rendered-component behavior still rely partly on recorded browser dogfood. The jsdom
harness in `toolchain/jsdom-react-component-harness.md` narrows that gap for mount, controlled input,
keyboard, and focus contracts, while `workflow/doc-reconciliation.md` defines the evidence-record
bar. Keep any remaining browser-only geometry or integration leg named as a residual; do not infer
it from controller tests.

## Cross-references

- `docs/design/prose-review-stack.md` — binding architecture and component ownership; the
  assembly, CheckRunner, Git-observation, HTTP-layer, frontend and round-trip-proof headings own
  the five surfaces summarized in "Shipped surfaces beyond the edit loop"
- `docs/design/prose-prompt-map.md` — generated prompt/prose graph and count tripwires
- `docs/learned/workflow/broad-catch-narrowing.md` — whole-chain containment and broad-catch policy
- `docs/learned/workflow/pydantic-boundary-models.md` — strict wire/subprocess boundary models
- `docs/learned/toolchain/jsdom-react-component-harness.md` — rendered component and keyboard tests
- `docs/learned/workflow/vacuity-proof-tests.md` — exhaustive matrix and manufactured-proof craft
