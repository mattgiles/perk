---
title: Linear issue backend
read_when: You are touching `perk/backends/linear.py` / `perk/backends/linear_backend.py`, Linear GraphQL queries, dual-encoding metadata markers, Linear readiness in init/doctor, backend-aware prompt rendering, agent-session emission (`perk/backends/linear_agent.py`), the stateful `FakeLinearWorkspace` lifecycle fake, the live-smoke results (Modes 1 & 2 ran green, the paired not-found discriminator `_is_entity_not_found`, the `[issues] team` KEY-not-name gotcha), the forward-looking Linear Projects substrate for the unbuilt Phase-3 ObjectiveStore, or the live-spike firing mechanism.
---

# The Linear issue backend

Objective #252 Phase 2/3 built the Linear backend in layers: the httpx GraphQL client
(`perk/backends/linear.py`), the `LinearIssueBackend` adapter (`perk/backends/linear_backend.py`), dual-encoding
metadata markers in `perk/plan.py`/`perk/objective.py`, init/doctor readiness wiring, and
backend-aware prompt rendering. Backend-agnostic protocol learnings live in `issue-backend.md`;
this doc is the Linear-specific knowledge.

## Linear API facts (audited against official docs)

- **Auth**: personal API keys use a *plain* `Authorization: <key>` header — `Bearer` is
  OAuth2-only. Getting this wrong fails confusingly; the test suite pins the raw-key form.
- **Rate limiting arrives as HTTP 400**, not 429: `errors[].extensions.code == "RATELIMITED"`.
  Consequence: `perk/backends/linear.py`'s client parses the JSON body **errors-array-first, regardless of
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
  `perk.backends.issues` for it (the resolver imports `linear_backend` at wiring time; the import-direction
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

## Agent-session emission (one-way, internally gated)

`perk/backends/linear_agent.py` + the `agent-session.json` cache helpers emit Linear AgentSession /
AgentActivity updates during implement runs. Four hook sites (`launch_stage`, `run_worker`,
`_pr_submit_impl`, `_pr_land_impl`) each make a **bare unconditional call** — the gate (stamped
`provider == "linear"` + `LINEAR_AGENT_TOKEN` present) and the try/except live INSIDE each emitter.
This keeps hook sites one-line with no per-site gating to drift, and makes "dormant by default /
byte-identical without the token" provable **per-emitter** (zero-requests tests) rather than
per-site.

### Linear agent API facts (offline-verified, NOT live)

- AgentSession/AgentActivity need an OAuth `actor=app` token (a personal `LINEAR_API_KEY` is
  rejected); the header form is `Authorization: Bearer` — hence the additive `bearer=True` mode on
  `LinearClient` (the personal-key header is byte-unchanged).
- The sanctioned proactive create is `agentSessionCreateOnIssue` (accepts the human identifier,
  e.g. `ENG-123`, as `issueId`).
- Session status is **derived automatically from activities** — no manual state management;
  sessions go stale ~30 min after the last activity.

### Testing a fail-open side-channel

The wrong test shape: monkeypatch the emitter with a raising spy — the try/except is *inside* the
emitter, so the raise propagates, fails the test, and proves nothing. The honest shape: **force the
gate open** (monkeypatch `linear_agent.emission_enabled` → True, plus a canned
`cache.read_agent_session` for follow-up emitters) and **break the substrate**
(`agent_client_from_env` raising), then assert exit-code/`--json`-payload byte-neutrality
end-to-end through the real fail-soft wrapper. Reusable whenever a fail-open side-channel is wired
into a host command.

Plus the MockTransport injection recipe for module-internal client construction: monkeypatch the
module's `LinearClient` symbol with a keyword-only factory that closes over a transport — records
every request the emitters compose without touching emitter code or the real client class.

## E2E lifecycle validation patterns (from the string-id work)

- **Named GraphQL operations make substring-keyed fakes routable**: the UUID lookup is a named
  operation — `query UuidForIssue($id: String!) { issue(id: $id) { id } }` — so both the scripted
  fake and the stateful fake route it distinctly from generic `issue(id` reads. With
  substring-keyed response dicts, **insertion order disambiguates** — the most specific needle
  first.
- **Read-seeding kills the extra mutation query**: every issue read seeds the identifier→UUID
  cache, so the common read-then-mutate path costs zero extra requests; only cold mutations pay one
  lookup.
- **The stateful `FakeLinearWorkspace` discipline**: identifier-or-UUID tolerated on *reads* (the
  documented `issue(id:)` tolerance), **UUIDs ONLY on mutations** — passing an identifier to a
  mutation raises `Entity not found`, structurally pinning the `_uuid_for` discipline with no
  explicit assertion. Page size 2 exercises the cursor loop on tiny data for free.
- **Late-bound `linear.client_from_env` monkeypatching** runs the whole real stack (resolver →
  `LinearIssueBackend` → real CLI commands) offline; only the GitHub PR tier needs the classic
  gateway fakes. **One shared workspace threading the entire lifecycle in a single test** catches
  cross-command contract drift (e.g. the plan-body comment must be patched, not duplicated, on
  re-save) that per-command tests can't.

## Backend-aware prompts (Node 3.1)

- **Per-plane plan-read SSOT helpers**: `perk/run/launch.py::_plan_read_instruction` ↔
  `extension/doors/lifecycleGates.ts::planReadInstruction`, byte-parity pinned by lockstep
  `LINEAR_READ_SUBSTRINGS` lists asserted from BOTH suites
  (`tests/test_worker_prompt_parity.py` ↔ `extension/worker/worker.test.ts`).
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

## Live smoke gate — RAN green (Modes 1 & 2 + the Projects spike)

The gate that `docs/linear-smoke-gate.md` once held UNRUN has now **run**: Mode 1 (issue lifecycle,
#554), Mode 2 (GitHub-integration coexistence, #564), and the Linear Projects spike (#567) all fired
**green — no backend defect, docs-only PRs.** The facts below resolve what the runbook reserved; the
residual register at the bottom carries only the items the live runs did *not* answer.

### Proven-live fidelity facts

- **ProseMirror round-trip is CLEAN.** `find_metadata_block` survives a real Linear round-trip for
  the plan-header (issue description), the plan-body (first comment), and the objective body comment
  sentinels — **no raw HTML / `<details>` artifacts**. A re-save **patches the body comment in
  place** (comment count stays 1), confirming the form-preserving `replace_metadata_block` path live.
- **Missing-entity shape**: `issue(id:"PER-9999")` → `message: "Entity not found: Issue"` with
  `extensions.code: "INPUT_ERROR"` — a **generic** input-error code, *not* a dedicated `NOT_FOUND`
  (see the discriminator below).
- **String `PER-*` identifiers flow through every `--json` envelope** end-to-end; the squash footer is
  `Plan: PER-<n> — <url>` (no `Closes #N`, no Linear magic words — closure is the explicit
  `close_issue` call, not a merge-message side effect).

### Not-found discrimination tightened (#558)

The reserved deferral "tighten `"not found"` to `.codes` when 4.1 observes one" is **RESOLVED — but
NOT in the `.codes`-only direction the roadmap reserved.** Because `INPUT_ERROR` is **generic** (it
also fires on argument-validation errors), the correct discriminator is the **pairing** of
`INPUT_ERROR` present in `exc.codes` **AND** the `"entity not found"` message prefix. One
module-level helper `_is_entity_not_found(exc)` now backs the three sites (`_issue_or_none`,
`_uuid_for`, `_comment_body_or_none`). The cross-cutting lessons:

- **Before tightening an error predicate to a GraphQL `extensions.code`, confirm the code is
  *specific*.** Linear reuses generic codes across unrelated failure classes; a code alone can
  over-match.
- **Folding a live observation into a predicate means re-shaping the offline twins to the observed
  reality in the same change.** The fakes emitted `codes=()`; a naive predicate tightening silently
  re-raised the *whole* not-found suite until the twins gained the observed code.
- **Discrimination tests must prove the tightening NARROWED** — the valuable cases are the *negative*
  ones: a not-found message under `RATELIMITED` (or with no code) now **re-raises**; a generic
  `INPUT_ERROR` carrying a non-not-found message **re-raises**. Only the paired shape is swallowed.

Two reserved hardenings deliberately shipped as **documented deferrals, not edits** — RATELIMITED
fail-loud (kept) and `_uuid_for` (kept, see below) — the honest outcome of a gating observation that
did not fire.

### Mutation identifier acceptance (#564)

`issueUpdate(id:"PER-n")` and `commentCreate(input:{issueId:"PER-n"})` both succeed with the **bare
identifier** (a bogus `PER-99999` still errors `INPUT_ERROR` / "Entity not found"), so `_uuid_for`
*could* collapse to a pass-through. That is **substantive but deferred to follow-up #562** — not
done here. The existing `_uuid_for` discipline note (UUIDs-only-on-mutations in the
`FakeLinearWorkspace` section) still stands as the offline pin until the collapse lands.

### GitHub-integration coexistence (#564)

- **The Linear GitHub integration links PRs as attachments (issue sidebar), NOT comments.** So the
  "linkback tolerance" concern (foreign comments perturbing marker-keyed scans) is **structurally
  moot** — the offline twin `test_foreign_linkback_comment_does_not_perturb_marker_scans` is
  *stricter* than reality.
- **perk's `plan-PER-<n>` branch auto-links directly** — it does **not** need Linear's
  `username/identifier-title` branch template (a control PR in that exact format linked identically).
- **On-land `close_issue` beside a Done-on-merge automation is a same-state write** — it refreshes
  `completedAt` but produces **no new state-history transition** (history stays monotonic
  Backlog → In Progress → Done).
- **"Installed ≠ connected" (the big operational lesson).** The Linear GitHub App installed on the
  org but **not wired to the run repo** means **zero** PR events reach Linear regardless of branch
  name. The decisive isolation test is a **control PR from `issue.branchName`'s canonical format**:
  if even that doesn't link, it's the *connection*, not perk's branch name. You **cannot** introspect
  the App installation from a normal `gh` token (a "count 0" is a 404, not an empty list);
  `team.gitAutomationStates { event, state, branchPattern }` confirms automation *config* even when
  the repo mapping itself is uncheckable.

### Config gotcha (#554)

`[issues] team` resolves by Linear team **KEY** (e.g. `PER`), **not** the workspace / display name.
A name silently fails team resolution and surfaces only at **land** as a *non-fatal*
`plan issue close skipped (non-fatal): Linear team '<x>' not found` (`plan_issue_closed: false`); the
GitHub squash-merge still succeeds.

## Linear Projects substrate (the ObjectiveStore spike, #567)

Forward-looking facts for the **not-yet-built** Phase-3 ObjectiveStore (recorded as proven substrate,
explicitly **not yet consumed by any built code** — no fiction about the store itself):

- **`projectCreate(input:{teamIds,name,content})` accepts `content` at create.** The historical 2024
  create-then-`projectUpdate` workaround no longer applies — write the overview in one call.
- **The overview round-trip is CLEAN**, so machine state can live in the **Project overview** (a
  single surface). A `documentCreate` round-trip is kept as a **proven fallback in reserve**.
- **Blocking-relation direction is carried by the field, not the enum.**
  `issueRelationCreate(type:"blocks")` — read forward via `relations`, inverse via `inverseRelations`;
  the `type` enum stays `"blocks"` on **both** sides. Reconstruct `depends_on` from `inverseRelations`,
  **never a `"blockedBy"` enum** (there isn't one).
- **Milestone list order is NOT insertion order** — key phases by milestone **name**, never list
  position.
- **Not-found error shapes diverge.** Bogus `project(id)` / `projectMilestoneCreate` / `document(id)`
  match the issue `INPUT_ERROR` + `"Entity not found: <Type>"` shape — **BUT `issueRelationCreate`
  with a bad `relatedIssueId` returns `INVALID_INPUT` / "Argument Validation Error"** (argument
  validation fires *before* entity lookup, so neither code nor prefix matches). A Projects not-found
  path must **special-case the relation-create error**.
- No RATELIMITED at spike volume.

## Measurement-node / live-spike process facts

- **The firing mechanism**: import `perk.backends.linear.client_from_env()` +
  `LinearClient.request(QUERY, VARS)`, resolving the team UUID via
  `teams(filter:{key:{eq:"PER"}})`. The throwaway runner lives in `/tmp` (no committed `scripts/`
  file) — honors the "no bespoke scripts" discipline while still capturing machine GraphQL documents
  + error shapes.
- **Check `LINEAR_API_KEY` in the session env before assuming a live node must be deferred** to an
  operator — a live spike may be fireable in-session.
- **Driving session-stages from a non-interactive harness**: the `--json` cold workers
  (`perk plan save --plan-file … --json`, `perk pr submit/land --json`, `perk learn capture … --json`,
  `perk objective … --json`) exercise the deterministic mutation paths **without a session**.
  **`perk implement` is the only stage with no `--json` worker** (the work *is* the session) — to
  position its worktree manually, `perk worktree create plan-<id>` then **copy
  `.pi/workflow/plan-ref.json` into the new worktree** (the PR-workers read the worktree-local
  plan-ref).
- **Gotcha — probe side-effects clobber idempotency**: overwriting an issue *description* while
  probing destroys its `plan-header` sentinel, so a later `perk plan save` creates a **new** issue
  (idempotency keys off that sentinel). Use a throwaway field or restore immediately.
- **Gotcha — Python `urllib` SSL fails in this env** (`CERTIFICATE_VERIFY_FAILED`); use `curl` for
  ad-hoc Linear GraphQL probes.
- **Runbook drift corrected** in `docs/linear-smoke-gate.md`: `perk init --verify` is **not** a flag
  (labels are created by `perk doctor --fix`); `perk plan-save` is `perk plan save`; `perk resume` is
  `perk plan resume`; the `perk submit` / `perk land` flat aliases *do* work; `perk pr land` is
  idempotent on an already-merged PR.

### Reconciliation pattern (cross-cutting)

When a measurement node **resolves a decision the prose framed as open** (overview-vs-document →
overview; not-found `.codes` tightening → paired predicate), that conditional is the prime stale spot
for `/objective-reconcile` to flip. (Terse by design; the full reconciliation pattern lives in
`doc-reconciliation.md`.)

## Still-deferred register (trimmed)

The live smoke resolved the fidelity / not-found / mutation-acceptance items above; what remains
unobserved:

- **RATELIMITED retry/backoff** — still unobserved at low CLI volume; the typed loud failure stands.
- **`LINEAR_API_KEY` as a GHA secret** for headless/remote runs.
- **Agent-session deferrals**: `perk address` emission, the `agentSessionUpdate.plan` checklist
  (technology preview), elicitation, retry/backoff, a webhook receiver (emission is one-way).
- **Remote-vs-local agent-session pointer residual**: a remote-created agent session is invisible to
  a later *local* land (`agent-session.json` lives in the runner's checkout, so the local land skips
  its emission with a stderr note) — accepted; a durable issue-tier session pointer would fix it.

## Sources

- Issues #347, #356, #361, #370, #376, #389, #400 (PRs #344, #354, #359, #368, #375, #387, #399)
- Live-smoke results: #554 (PR #553), #558 (PR #557), #564 (PRs #561/#563), #567 (PRs #565/#566),
  and follow-up #562 (the deferred `_uuid_for` collapse)

## Cross-references

- `docs/learned/workflow/issue-backend.md` — the backend-agnostic protocol seam
- `docs/learned/workflow/init-doctor.md` — verify-gated network repairs, the readiness shape
- `docs/learned/workflow/config-tables.md` — the committed-only `[issues]` table shape
- `docs/learned/workflow/shared-contracts.md` — the cross-plane SSOT prompt-fragment pattern
- `docs/learned/workflow/skill-bindings.md` — skills `references:` subdirectory routing
- `docs/learned/workflow/mergeability-and-conflict-resolution.md` — the `/submit` mergeability gate
  (the live-smoke mergeability gotchas in #554 live there)
- `docs/learned/workflow/doc-reconciliation.md` — the measurement-node-resolves-an-open-conditional
  reconciliation pattern
- `docs/learned/toolchain/ty.md` — the narrowing-helper family for deep untyped payloads
