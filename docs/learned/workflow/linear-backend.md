---
title: Linear issue backend
read_when: You are touching `perk/linear.py` / `perk/linear_backend.py`, Linear GraphQL queries, dual-encoding metadata markers, Linear readiness in init/doctor, backend-aware prompt rendering, or planning the Node 4.1 live smoke.
---

# The Linear issue backend

Objective #252 Phase 2/3 built the Linear backend in layers: the httpx GraphQL client
(`perk/linear.py`), the `LinearIssueBackend` adapter (`perk/linear_backend.py`), dual-encoding
metadata markers in `perk/plan.py`/`perk/objective.py`, init/doctor readiness wiring, and
backend-aware prompt rendering. Backend-agnostic protocol learnings live in `issue-backend.md`;
this doc is the Linear-specific knowledge.

## Linear API facts (audited against official docs)

- **Auth**: personal API keys use a *plain* `Authorization: <key>` header — `Bearer` is
  OAuth2-only. Getting this wrong fails confusingly; the test suite pins the raw-key form.
- **Rate limiting arrives as HTTP 400**, not 429: `errors[].extensions.code == "RATELIMITED"`.
  Consequence: `perk/linear.py`'s client parses the JSON body **errors-array-first, regardless of
  HTTP status**; status-based handling is only the fallback for non-2xx bodies without GraphQL
  errors.
- **Partial success is real**: HTTP 200 can carry `errors` alongside partial `data`. The client
  fails loud and discards partial data — perk's narrow queries never want partial results.

## The client/consumer contract

- `LinearClient.request()` returns the `data` dict or raises; **lookup-miss `None` fields inside
  `data` are the caller's domain** — the client never interprets them. The backend owns the
  `... | None` not-found semantics.
- Branch on `LinearGraphQLError.codes` (de-duplicated, order-preserved `extensions.code` values),
  **never on message substrings**. `RATELIMITED_CODE` is exported.
- The client IS the error boundary (no intermediate Linear-private error type): everything is
  `IssueBackendError`, GraphQL-level failures the `LinearGraphQLError` subclass.
- **No retry/backoff on RATELIMITED** — a typed loud failure by design (Linear's API-key budget of
  ~2,500–5,000 req/h is huge headroom for CLI-scale use).

## Dual-encoding metadata markers

`perk/plan.py` renders metadata blocks in two forms: HTML `<!-- perk:x -->` markers for GitHub and
inline-code `` `perk:x` `` sentinels for Linear (ProseMirror strips HTML comments).

- **The transcoder ↔ renderer byte-identity invariant**:
  `to_linear_markdown(render_metadata_block(key, data))` equals
  `render_metadata_block(key, data, style="inline-code")` **byte-exactly** (marker rewrite +
  dropping the exact `<details>` wrapper lines reproduces the inline render, blank lines included).
  A test pins this; if the html renderer's whitespace shape ever changes, revisit the transcoder's
  wrapper-line drop.
- **`replace_metadata_block` is form-preserving** (html block → html re-render; inline → inline);
  the append-when-absent arm deliberately stays HTML (only GitHub callers append today). If a
  Linear-side caller ever appends a block, that arm needs a style parameter.
- **Incoming markers are transcoded before matching** (`find_comment_id_by_marker` /
  `upsert_marked_comment`), so a GitHub-encoded marker (e.g. `RUN_REPORT_MARKER`) stays idempotent
  end-to-end against Linear-encoded comments.

## The dual-encoding presence-check bug class

**Any presence check gating an "absent is valid" path must match BOTH encodings.**
`objective._has_block` matched only the HTML open marker, so a Linear roadmap silently parsed as
roadmap-free (`parse_roadmap_nodes` returned "valid roadmap-free" instead of parsing). Fixed via
`plan.has_metadata_block` — presence-only, both encodings, the absent-vs-malformed discriminator
(since `find_metadata_block` returns `None` for both). When auditing other backends/encodings,
grep for raw `in text` marker checks near valid-when-absent semantics.

Related facts:

- **Form preservation generalizes to bare marker pairs**: `objective._find_marker_pair` returns
  the *concrete found marker strings*, so callers splice with the found forms — HTML behavior stays
  byte-identical and Linear bodies never get HTML reintroduced. HTML-first scan order pins
  deterministic behavior on pathological both-forms bodies (tested).
- **Known duplication**: `objective._inline_marker` re-derives the `<!-- perk:x -->` →
  `` `perk:x` `` rewrite rule locally (import direction `linear_backend → objective` forbids
  importing the transcoder). If `to_linear_markdown`'s marker rule ever changes, both sites must
  change; the guard is `tests/test_objective.py`'s transcoded-fixture tests (real
  `to_linear_markdown` output run through the objective engines).

## Two composition disciplines

- **Issue descriptions are composed directly inline-code-style**
  (`render_metadata_block(..., style="inline-code")`, the `create_learn_issue` precedent).
- **Comment bodies are transcoded** via `to_linear_markdown` because they're rendered from
  `objective.py`'s HTML marker constants.

Two distinct disciplines in one backend — keep them straight when adding ops.

## Backend behavioral pins

- Comments are **sorted client-side ascending by `createdAt`** to pin GitHub's oldest-first
  first-match semantics — never trust Linear's default connection ordering.
- Label idempotency is **lookup-first and unscoped** (a workspace-level label counts; a
  team-scoped create on a duplicate name errors), with a duplicate-race re-lookup arm.
- `LinearIssueBackend.backend_id` is a module-level `"linear"` literal — never import
  `perk.issues` for it (the resolver imports `linear_backend` at wiring time; the import-direction
  test pins this).
- The four ensured labels live in `linear_backend._PERK_LABELS` (duplicating the plan/objective
  constants by reference, not value) — **adding a fifth perk label requires touching that tuple**
  or it silently stops being ensured at init.

## Readiness wiring (init/doctor)

- `linear_backend.check_readiness` is **one report-shaped probe with two consumers**: doctor
  (lookup-only) and init/`--fix` (converge), split by an `ensure_labels` flag. It **never raises**
  — every failure mode is a field. Phases short-circuit auth → team → labels, and the
  short-circuit itself is asserted in tests by counting fake-client requests.
- **Probe results carry only what was *discovered*** (user, team_ok, labels). If a render needs an
  input value (the team key for `✓ Linear: <user>, team <key>`), carry it on the wrapping report
  (`LinearReport.team`), never echo inputs back from the probe result.
- Readiness may construct a **throwaway `LinearIssueBackend`** to reach its privates
  (`_team_id()`/`_ensure_label_id()`/`_lookup_label_id()`) — `repo_root` is only consumed by the
  PR tier (`get_plan`), so a dummy path is safe.
- The verify-gated `linear-team` warn arm exists so the network group says *why it stopped*
  (readiness not checked) instead of silently skipping — the no-silent-pass posture.

See `init-doctor.md` for the general rule that network repairs live in the verify-gated repair
gesture, never a `ManagedConvergence`.

## Backend-aware prompts (Node 3.1)

- **Per-plane plan-read SSOT helpers**: `perk/launch.py::_plan_read_instruction` ↔
  `extension/lifecycleGates.ts::planReadInstruction`, byte-parity pinned by lockstep
  `LINEAR_READ_SUBSTRINGS` lists asserted from BOTH suites
  (`tests/test_worker_prompt_parity.py` ↔ `extension/worker.test.ts`).
- **The linear plan-read arm is prose, not a command** (a `linear_get_issue` /
  `linear_list_comments` tool recipe with an `open <url>` fallback). The prompt scaffold tolerates
  either shape; parity substrings are literal fragments of the *instruction*, not the scaffold, so
  they pin the linear arm specifically.
- **Prompt sites branch on the stamped `cache.plan-ref.provider`, NOT on config** — the stamping
  rule makes the ref the authority. The TS config mirror `resolveIssueBackendId` remains a
  deliberately-dormant fail-safe; don't "fix" prompt sites to read it.
- **PR-side guidance is backend-universal** (`gh pr` only) under any issue backend — `/submit`,
  `/land`, the address prompts, learn's `gh pr list --head plan-<pr_id> --state merged`
  derivation all stay untouched.
- **Skills `references:` frontmatter + `backends/{github,linear}.md` subdirectory routing** works
  with zero init/doctor changes — delivery is whole-directory sync; the launch prompt naming the
  backend is the routing signal the model uses to pick `backends/<backend>.md` (see
  `skill-bindings.md`).

## Offline test recipes

- **httpx `MockTransport(handler)`** with a request-recording closure: the handler records
  `httpx.Request` objects for composition asserts (method/URL/headers/JSON body). Clients are
  per-request `with httpx.Client(...)` — consumers have zero `close()` obligations.
- **The scripted GraphQL fake** (`tests/test_linear_backend.py::_FakeLinear`): responses keyed by
  query-substring in **insertion order** — order more-specific needles first (`"comments(first"`
  before `"issue(id"`, since the comments query also contains `issue(id:`); per-key queues pop
  until one entry remains, then reuse it (pagination scripting + repeated-call reuse for free).
- **ty + GraphQL payloads**: navigating `dict[str, object]` responses needs a narrowing-helper
  family (`_require_dict`/`_require_list`/`_require_str` with `cast`, raising `IssueBackendError`
  on malformed shapes — doubling as the never-silently-truncate guard). In tests, one
  `_input_payload()` cast helper beats per-site `assert isinstance` (which ty doesn't narrow
  through `__getitem__`). See `toolchain/ty.md`.

## Node 4.1 deferral register (carried, flagged)

- Live round-trip / ProseMirror fidelity is **mitigated-not-proven** (documented-supported
  constructs only); the live smoke gate proves it.
- `"not found"` *message-substring* tolerance in `_issue_or_none`/`_comment_body_or_none` (no
  stable `extensions.code` observed yet) — tighten to `.codes` when 4.1 observes one (flagged in
  both docstrings).
- GraphQL **type strings in queries are unverified live** (`$teamId: ID!` vs `String!` etc.) —
  offline fakes only check substrings.
- RATELIMITED retry/backoff (deferred until live call patterns exist).
- `LINEAR_API_KEY` as a GHA secret for headless/remote runs.
- `--json` envelope numeric-id re-shaping (see the grep tag in `issue-backend.md`).

## Sources

- Issues #347, #356, #361, #370, #376 (PRs #344, #354, #359, #368, #375)

## Cross-references

- `docs/learned/workflow/issue-backend.md` — the backend-agnostic protocol seam
- `docs/learned/workflow/init-doctor.md` — verify-gated network repairs, the readiness shape
- `docs/learned/workflow/config-tables.md` — the committed-only `[issues]` table shape
- `docs/learned/workflow/shared-contracts.md` — the cross-plane SSOT prompt-fragment pattern
- `docs/learned/workflow/skill-bindings.md` — skills `references:` subdirectory routing
- `docs/learned/toolchain/ty.md` — the narrowing-helper family for deep untyped payloads
