---
title: The prose-review workbench + prose-map governance — launcher security, source adapters, edit workspace
read_when: Working on perk-dev prose-review, tools/prose-review, or tools/prose-map — launcher security postures, closed adapters, parser traps, wire DTOs, EditWorkspace invariants
cluster: prose-governance
---

# The prose-review workbench and prose-map governance

The binding architecture record is `docs/design/prose-review-stack.md`. It owns the system shape
and settled component boundaries. This learned doc does not duplicate that architecture; it records
the cross-cutting traps that recur when the prose-map catalog, FastAPI/Vite workbench, source
adapters, wire protocol, and edit workspace evolve.

## Distillation

- The launcher contains every URL-derived read, passes websockets through only under the current
  no-websocket-route posture, rebuilds from disk, and has one `dist/` writer — "Launcher security
  and the development loop".
- Catalog failures are fail-closed according to result trustworthiness; policy-definition errors
  prevent discovery while registration-shape errors become typed findings; a new described param
  moves multiple count pins (verify via the living-map check) — "Prose-map catalog
  governance".
- Closed adapter vocabularies are exhaustive at domain/DTO/route boundaries; syntax validation
  precedes selectors and subprocess adapters are bounded — "Source-adapter contract craft".
- PyYAML merge tags, inherited values, and comment-suffixed document markers require lexical and
  semantic evidence — "PyYAML lexical-resolution traps".
- Python extraction centralizes normalized-name policy, maps byte/code-point offsets explicitly,
  and compiles after parsing — "Python AST and tokenize traps".
- TypeScript selectors keep one identity scheme per collision bucket and isolate the pinned private
  compiler seam — "TypeScript selector and compiler traps".
- Frontend wire vocabularies mirror Python manually, endpoint parsers stay local, identities are
  occurrence-based, and legal null combinations become unions — "Frontend wire posture".
- `EditWorkspace` trusts descriptors, validates cache algebra, returns defensive copies, and binds
  edits to revisions — "EditWorkspace invariants".
- JSX/component-render coverage remains a named browser-dogfood gap, not an implied unit-test pass —
  "Standing proof gap".

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
policy registry in `tools/prose-map/catalog.ts` and its runtime unknown-field finding form the
two-layer guard described in `workflow/source-scan-guards.md`.

A governed tool gaining a described param moves multiple prose-map count pins at once (governed
tools / TS fragments / discovery candidates) — verify with the living-map check, never assume
the outcome (#1992).

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

Python applies NFKC normalization to identifiers. A source spelling can normalize into a hard
keyword even when its raw characters do not look reserved. Apply keyword and name exclusions once
in the shared name predicate used by both discovery and resolution. Duplicating the rule lets the
catalog discover a selector that the adapter later refuses.

Token-stream structural detection anchors on logical lines, not visual columns. Marker count or
pairing mismatch fails closed; guessing the intended block can edit the wrong prose. Keep producer
and consumer on one structural detector rather than re-deriving marker grammar in each.

AST location columns are UTF-8 byte offsets, while `tokenize` columns are Unicode code-point
positions. Preserve one line-start table and provide explicit conversions in each direction. After
an edit, recomposition of untouched prefix, replacement, and untouched suffix is the cheap
corruption invariant. The owning implementation is
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

## Standing proof gap

JSX glue and rendered-component behavior still rely partly on recorded browser dogfood. The jsdom
harness in `toolchain/jsdom-react-component-harness.md` narrows that gap for mount, controlled input,
keyboard, and focus contracts, while `workflow/doc-reconciliation.md` defines the evidence-record
bar. Keep any remaining browser-only geometry or integration leg named as a residual; do not infer
it from controller tests.

## Cross-references

- `docs/design/prose-review-stack.md` — binding architecture and component ownership
- `docs/design/prose-prompt-map.md` — generated prompt/prose graph and count tripwires
- `docs/learned/workflow/broad-catch-narrowing.md` — whole-chain containment and broad-catch policy
- `docs/learned/workflow/pydantic-boundary-models.md` — strict wire/subprocess boundary models
- `docs/learned/toolchain/jsdom-react-component-harness.md` — rendered component and keyboard tests
- `docs/learned/workflow/vacuity-proof-tests.md` — exhaustive matrix and manufactured-proof craft
