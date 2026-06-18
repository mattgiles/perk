---
title: Linear issue backend
read_when: You are touching `perk/backends/linear.py` / `perk/backends/linear_backend.py`, Linear GraphQL queries, dual-encoding metadata markers, Linear readiness in init/doctor, the env-first/config-fallback `client_from_env` seam + the worktree env-seed bridge (the gitignored `perk.local.toml` carried into a linked worktree, the widening-broke-21-fakes `*a,**k` rule), backend-aware prompt rendering (incl. the third `objective_read_instruction` seam + the cold-vs-warm backend-source asymmetry), agent-session emission (`perk/backends/linear_agent.py`), the stateful `FakeLinearWorkspace` lifecycle fake, the live-smoke results (Modes 1 & 2 ran green, the paired not-found discriminator `_is_entity_not_found`, the `[issues] team` KEY-not-name gotcha), the project-backed `LinearProjectObjectiveStore` + the Projects substrate now on `LinearClient`, the Phase-4 project-objective ops (add-node, the phase→milestone seam, fail-open Project Updates, the manifest-drift design, the project readiness probe), or the live-spike firing mechanism.
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

## The env-first / config-fallback `client_from_env` seam + the worktree env bridge (#654)

`client_from_env(env=None, *, repo_root: Path | None = None)` is **env-first** (stripped), then
falls back to the `repo_root` `perk.local.toml` `[linear] api_key` when env is blank. The
`repo_root=None` default preserves every existing caller byte-for-byte. It is threaded at four
in-process sites (`resolve_issue_backend`, `resolve_objective_store`, `doctor._linear_checks`,
`init._linear_readiness`); a **fifth** site (`doctor._fix_linear_labels`) was intentionally left
env-only (low impact; a future "config fallback everywhere" pass should thread it for symmetry).

- **The worktree/gitignore bridge (the cross-cutting insight).** A *gitignored* local file IS
  honored *inside worktrees* — by design, **via the env-seed, not a file copy**. `launch_stage`
  reads `load_local_linear_api_key(repo_root)` where `repo_root` is the **main checkout**, and
  builds the env dict **before `os.chdir(worktree)`**. The gitignored file is never copied into the
  linked worktree, but it doesn't need to be: all worktree-resident consumers (the borrowed
  in-session `pi-mono-linear` `linear_*` tools AND any `perk <stage> --json` cold-door worker)
  **inherit the seeded session env**, and `client_from_env` reads env-first, so the inherited value
  wins. The `client_from_env(repo_root=worktree)` fallback is effectively moot inside a worktree (no
  file there) — **the env-seed carries it.**
- **Gotcha — widening `client_from_env` broke 21 lifecycle tests.** Adding the `repo_root` kwarg
  broke the shared fake `monkeypatch.setattr(linear, "client_from_env", lambda: ws)` with
  `TypeError: unexpected keyword argument`. Fix: `lambda *a, **k: ws`. **Rule: when you widen a
  function's signature, grep ALL `monkeypatch.setattr(..., "<fn>", lambda ...)` fakes of it and
  loosen them to `*a, **k`.**
- **Out of scope (flagged):** `LINEAR_AGENT_TOKEN` (a distinct secret; the `[linear]` table leaves
  room for a future `agent_token` key, not added); `--remote` (returns before the local exec-env
  block; the remote runner provides its own secrets); no TS-plane mirror (the TS extension reads no
  Linear key — the `launch_stage` env-seed is the only bridge).

See `docs/learned/workflow/config-tables.md` for the local-only secret-fallback reader shape and
`docs/learned/workflow/cold-door-launch.md` for the env-seed merge order at the launch seam.

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

### The third backend-aware seam: `objective_read_instruction` (Node 4.1, #600)

Objective seed prompts gained their own backend-aware read clause, mirroring the plan-read precedent:
one parity-pinned helper per plane — `objective_read_instruction` (Python,
`perk/cli/commands/objective/shared.py`) ↔ byte-identical `objectiveReadInstruction` (TS,
`extension/factories/objectivePlan.ts`) — appended as a **supplemental clause** to the existing
`perk objective show <id>` step in the three objective seed prompts (cold `_seed_prompt`, warm
`factoryGuidance` + `reconcileGuidance`). Byte-parity is pinned by a paired `OBJECTIVE_LINEAR_SUBSTRINGS`
lockstep substring list in `tests/test_objective_prompt_parity.py` ↔
`extension/factories/objectivePlan.test.ts` — the **same `LINEAR_READ_SUBSTRINGS` discipline**
documented above (a third instance; see `shared-contracts.md`).

- **The supplemental-clause pattern beats replacement.** The helper returns `""` for github (and any
  non-linear) so the existing prompt is **byte-unchanged** (no churn) — achieved by injecting the
  clause *around* the existing punctuation (the clause carries a **leading space**), NOT by rewording
  the line. A naive `; mark` → `. Mark` rewrite churns the github arm; the guard is to **verify the
  github-arm output is literally byte-identical** after the change (caught by re-reading the diff
  intent, not a test).
- **Cold-vs-warm backend-source asymmetry is the load-bearing design call.** Cold has
  `store.backend_id` + `state.url` already in hand (free). Warm must resolve the backend from
  `resolveIssueBackendId(ctx.cwd)` (committed `.pi/perk.toml`, **NOT** `loadPerkConfig`'s overlay) and
  fetch the url via a `runColdDoor(["objective","show",id,"--json"])` round-trip **only when
  `backend === "linear"`** (github needs no clause → no fetch), and **fail-open** to the indirect
  `run \`perk objective show <id>\` for its URL` form. Config is authoritative for the warm plane
  because cross-backend objectives are unsupported by policy (no store-vs-config skew to guard). This
  consumed the previously-**dormant** `resolveIssueBackendId` — its first real consumer.
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

The gate that `docs/planning/linear-smoke-gate.md` once held UNRUN has now **run**: Mode 1 (issue lifecycle,
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
*could* collapse to a pass-through. That observation **delivered as #562 (PR for #620)** — see below.

#### The `uuid_for` collapse delivered (#562 / #620)

The deferred collapse landed: `LinearClient.uuid_for` + its cache are **deleted**, and the verified
mutations now pass the **bare boundary identifier** directly (no resolve-on-demand). Two reusable
lessons:

- **Shared issue-mutation behavior both op classes need lives MODULE-LEVEL, not on one op class.**
  The plan said "a tiny private helper on the issue-ops class," but the verified-mutation call sites
  span **two** client-only op classes (the issue ops AND the project ops' attach-issue-to-project),
  and — per the substrate-home principle above — the project ops do **not** compose the issue ops;
  both only register the shared client. A method on one class is unreachable from the other. So the
  not-found-mapping wrapper is a **free function parameterized by `client`** (`_request_issue_mutation`),
  the only shape that avoids four copies. *General rule: shared mutation behavior the two op classes
  both need is module-level (client-parameterized), because they are **siblings over a shared client,
  not a composition**.*
- **A byte-identical not-found mapping survives the deletion by RELOCATING it** into that thin
  request wrapper (it governs only the wrapped `request` call; the `success is not True` payload
  checks stay AFTER the wrapper returns). And **capture-at-create beats resolve-on-demand** for the
  one consumer that still needs a UUID: a raw create variant returns the create-time UUID for the
  UUID-only `issueRelationCreate` (relations still take UUIDs; zero extra queries).
- One intentional `uuid_for` string survives in production — a docstring back-reference on the
  request wrapper (a `grep` for `uuid_for` in `perk/` hits it; **expected, not a leftover**). The
  test-fakes dropped their scripted `UuidForIssue` reply entries / branch and **flipped mutation-id
  assertions from the resolved UUID to the boundary identifier** (plus `assert not` a resolution
  query fired).

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

### Mode 4 — project-backed objective lifecycle proven live (#621)

The four previously not-live-proven Project ops are now **proven live** (driven from perk's own
GitHub-backed dev repo against team PER):

- **Idempotency:** find-by-run-id returns the **same UUID** / `existed:true` with **no duplicate**
  milestones or issues.
- **Project Update posts on create / land / reconcile**; **close** drives the Project state to
  `completed`; the **node workflow-state mirror fires BOTH directions** (in-progress→started at
  plan-save, done→completed on mark-done).
- **ProseMirror metadata round-trip is CLEAN** through create→reconcile (zero HTML artifacts), and
  a re-save **patches in place**. **Node↔plan unification creates NO new `perk:plan` issue** (the
  plan-header merges into the node-issue). **No RATELIMITED** at low volume.

**Setup gotchas** (running Linear from a GitHub-default repo):

- **Backend selection reads COMMITTED `.pi/perk.toml` only** — the `.pi/perk.local.toml` overlay is
  deliberately **ignored** (same committed-only discipline as compaction). So pointing perk at
  Linear needs a **working-tree edit** to committed `.pi/perk.toml` reverted before commit; a local
  overlay silently no-ops.
- Use **`uv run perk`**, not the stale global `perk` (a separate uv-tool install). The doctor
  `linear` group only appears **once committed config selects linear**.

**GraphQL probe gotchas:** `issueRelationCreate`'s `type` is a GraphQL **enum** — a quoted inline
literal fails validation; pass it via a typed `$input` variable. And **urllib HTTPS fails on this
host** (`CERTIFICATE_VERIFY_FAILED`) — use `curl` for ad-hoc probes (see Measurement-node facts).

**`get_objective` reconstruction facts** (the empirical baseline the #626 drift doctor formalizes):
`objective show --json` **omits `depends_on`** and **derives `phase` from the node id** (not the
milestone); `depends_on` is reconstructed from **blocking relations**. And `get_objective` **silently
absorbs drift** — an un-assigned node disappears, an unknown relation is dropped, a milestone rename
is invisible — which is exactly why the manifest-pinned drift doctor exists.

## Linear Projects substrate + `LinearProjectObjectiveStore` (now BUILT)

Objective #548 Phase 3 built the project-backed objective store on top of the #567 spike substrate.
The tier contract (dormant-contract → atomic-removal recipe, resolver, translate-CM) lives in
`objective-store.md`; the Linear-specific mechanics are here. Built across Nodes 3.1–3.4 (PRs #579,
#584/#585, #588, #594).

### The substrate-home principle (the load-bearing #582/#586 lesson)

**The only thing that should encapsulate Linear GraphQL client logic is `LinearClient`.** The op
classes (`_LinearIssueOps`, `_LinearProjectOps`) must each register **only the client**, never one
another. Shared machinery — team-id/uuid resolution + caches, pagination, the `_require_*`
narrowing helpers, the not-found discriminator — belongs **on the client**.

#582 landed the **opposite** (`_LinearProjectOps` composing `_LinearIssueOps`) as a **defect**, and
the *why* it landed is the durable lesson: the plan's "Confirmed with the user" was manufactured by
a leading confirm-this question asked *after* the user had given standing architectural guidance to
the contrary. An implementer faithfully following a saved plan still ships the defect, so the error
must be caught at **planning** time. **Durable: treat prior standing architectural guidance as
load-bearing; don't re-litigate it with leading questions.** #586 corrected it (acknowledge-don't-
revert: the node stayed `done`, its description rewritten to name the defect, the correction
overloaded onto the next node via a `PREREQUISITE CORRECTION` block + a referenced
`docs/planning/` context file).

### The re-homing recipe (#586)

When client machinery moves onto `LinearClient`, a **request-only structural seam can no longer
carry behavior** — retype every seam to `LinearClient` and have **both fakes** (scripted +
stateful) **SUBCLASS it** (no `super().__init__`; just init the two caches directly), so they
inherit the real machinery routed through their overridden `request` and every existing GraphQL-
document assertion stays byte-green. This is the general recipe for promoting machinery off a
delegated collaborator onto its client tier.

- The `_require_*` helpers + the not-found discriminator moved **DOWN** to `linear.py` (the lower
  layer, re-imported by `linear_backend.py`) to avoid an import cycle. The `INPUT_ERROR`-in-`.codes`
  AND `"entity not found"`-message pairing stayed intact (do not loosen to `.codes`-only).
- The **team-id cache is keyed by `team_key`** (the client stays team-agnostic at construction; op
  classes pass their bound team_key). A single shared cache via the client beats op-class
  composition — it de-dupes when only one op class is in play.
- **Decoupling over DRY:** symmetric client-only op classes inline a tiny mutation (e.g.
  attach-issue-to-project) rather than reach a sibling; a public `cache_uuid(identifier, uuid)` seam
  lets read paths seed the shared cache without touching a private attr.

### `_create_issue` made label-optional

Build `labelIds` into the input **only when non-None** — node-issues carry no perk label (they are
discovered by project membership + the node block), and the change is byte-identical for every
existing label-passing caller. Same conditional-key shape as the `project_id` / `milestone_id`
additions (omit the key, never an explicit `null`).

### Project-backed `create_objective` shape (#586)

- **Overview = inline-code `objective-header` block + a Reconcilable prose region, NO roadmap
  table.** Compose the header + markers in HTML form, then pass the WHOLE overview through the
  Linear-markdown transcoder so markers become inline-code sentinels. **The roadmap is derived LIVE
  from node-issues — never stored as a YAML block on the Linear side.**
- **`find_objective` dedup** scans projects and parses each overview's header block
  (dual-encoding-tolerant), matching the header `run_id`; the project id is opaque. Infra failures
  propagate (mapped to `ObjectiveStoreError`), never masked as `None`.
- **Natural node ordering** uses a sort key with a numeric/lexical **discriminator slot** (so a
  numeric trailing segment sorts ahead of a non-numeric one AND `int`/`str` never mix in one
  comparison slot) — this makes `3.2 < 3.10`. Shared by the create-order (3.2) and read-order (3.3)
  paths.
- **Explicit-`depends_on`-only blocking relations** (skip both `None`-inferred and `()`-explicit-
  none); direction is dep-BLOCKS-node. The node block excludes `pr` (plan-header authority) and
  `depends_on` (derived from relations).

### Read + mutation surface (#589)

- **`get_objective` reconstructs `depends_on` from blocking relations** — lossy: an explicit `()`
  reads back as `None` (sequential inference then applies downstream). A passed node-issue UUID
  still **re-resolves through the uuid lookup** because project-issue reads don't seed the uuid
  cache (unlike create/find) — script that lookup in tests.
- **The node-status workflow-state mirror keeps a SEPARATE states cache** from the learn-close path
  (byte-stable), and **fails open** by swallowing the backend error (`LinearGraphQLError` is a
  subclass, so both a `success:false` payload AND a raised error are caught); a `None` state id is
  skipped silently before any write.

### The `_FakeLinear` substring-keyed fake — insertion ORDER is load-bearing (the sharpest footgun)

The scripted fake matches responses by query-**SUBSTRING** in insertion order, so when one query's
needle is a substring of another's, register the **more-specific needle FIRST**. The canonical trap
(#589): `get_objective` is the first method calling BOTH `project_or_none` (key `"project(id"`) and
`project_issues` (whose query contains both `"project(id"` and `"issues(first"`). If `"project(id"`
is registered first, the project-issues call wrongly resolves to the project response and pagination
blows up. **General rule: when two scripted queries share a prefix, order the dict so the
longer/more-specific needle wins.**

### `FakeLinearWorkspace` Projects routing arm-ORDER (#595)

Adding Projects to the stateful lifecycle fake exposes the same collision tax: the list-projects,
project-issues, and relation reads must be **arm-ordered before** their substring-superset queries
(`"projects(first"` before `"team(id"`; `"project(id"` before `"issues(first"`/`"issue(id"`;
`"inverseRelations("`/`"relations("` before `"issue(id"`). Project mutations (`projectUpdate(`,
`projectCreate(`) don't contain `"project(id"`, so they don't collide. Mis-ordered arms mis-route
**silently**. (Reinforces the existing "named GraphQL operations make substring fakes routable"
note.)

### Adding a `_require_*`-parsed field to a selection = sweep every raw-row fixture (#595)

When a parsed GraphQL selection grows a required field (e.g. `project_issues` gaining `url`), every
offline fixture that hand-builds raw rows — both the scripted `_FakeLinear` tests and the stateful
workspace's node builder — must add it, or they raise the **wrong (masking)** error. Offline-fixture-
sweep discipline applies to any new required field on a parsed selection.

### `issueRelationCreate` not-found DIVERGES

Bogus `project(id)` / `projectMilestoneCreate` / `document(id)` match the issue `INPUT_ERROR` +
`"Entity not found: <Type>"` shape — **BUT `issueRelationCreate` with a bad `relatedIssueId`
returns `INVALID_INPUT` / "Argument Validation Error"** (argument validation fires *before* entity
lookup). So relation-create must **NOT** route through the not-found discriminator and fails loud
(the store passes already-resolved UUIDs). Relation *reads* filter `type == "blocks"` (Linear
returns related/duplicate/blocks); direction is carried by the field (`relations` vs
`inverseRelations`), the enum stays `"blocks"` — there is no `"blockedBy"` enum.

### Milestone + create facts (retained from the spike)

- `projectCreate(input:{teamIds,name,content})` accepts `content` at create (the 2024 create-then-
  `projectUpdate` workaround no longer applies); a `documentCreate` round-trip is kept as a proven
  fallback in reserve.
- **Milestone list order is NOT insertion order** — key phases by milestone **name**, never list
  position.
- **`list_projects` query shape live-status:** offline-covered only at landing (the #567 spike
  covered create/overview/milestone/attach/relation, not list-projects). If a later live run covers
  it, reconcile this line; do NOT invent a result. No RATELIMITED at spike volume.

## Project-backed objective ops (Phase 4: Nodes 4.1–4.4)

Objective #548 Phase 4 layered four additive enrichments onto `LinearProjectObjectiveStore` (the
backend-aware seed prompts are in the Backend-aware-prompts section above; GitHub stays unchanged
throughout). Built across Nodes 4.1–4.4 (PRs #599, #602, #605, #608) plus the `add_objective_node`
surface (PR #613).

### `add_objective_node` project-store flow (#614)

The project store materializes a node-**issue**, not a roadmap-block re-render (the
re-render-vs-materialize split lives in `objective-store.md`). The live pipeline:
`get_objective` (compute the live roadmap) → `objective.add_node` (compute `<phase>.<n>`) →
`project_or_none(content)` for phase-name enrichment → `ensure_phase_milestone(known=None)` →
`_create_issue(project_id, milestone_id)` → one `create_issue_relation` per `depends_on`.

- **Crucial reuse:** the `known=None` branch of `ensure_phase_milestone` was pre-built by Node 4.3
  *explicitly for a future add-node-to-an-existing-objective path* (its docstring says so) — this is
  that caller. Load-bearing seam, not fiction.
- Phase-name enrichment reads `### Phase N: name` from the overview prose (`enrich_phase_names`) and
  falls back to `Phase N` (`phase_label`) when no header exists.

### The id-collision `None` branch is genuinely UNREACHABLE via real inputs (#614)

`add_node`'s id-collision `None` return is a defensive guard with no realistic trigger: any node
already occupying the computed `<phase>.<n>` would carry a numeric suffix → be counted in `max_num`
→ contradiction (new id = max+1). **Don't write a unit test forcing the impossible branch** —
instead test the *gateway error mapping*: monkeypatch `objective.add_node` to return `None` and
assert the `GitHubError`/`ObjectiveStoreError` "collision" message maps to the CLI `invalid_input`
arm.

### `FakeLinear` add-node fixture gotchas (#614)

- A single `add_objective_node` path issues **two** `project_or_none` reads (get_objective's + the
  content-enrichment one) → supply a **2-element list** under the `project(id` key.
- `_create_issue` triggers a team-id lookup → the fixture needs a `teams(filter` entry even for an
  add-node test.
- Reaffirms the substring-insertion-order footgun (register the more-specific needle first) — see
  the `_FakeLinear` section above; don't re-explain.

### The phase→milestone seam: route an existing caller through a future seam without behavior change (#606)

`ensure_phase_milestone(*, project_id, name, known=None)` is a load-bearing seam a *future* caller
(add-node) reuses. To route the *current* (create-objective) caller through it **today without a
behavior change**, seed that caller's `known` map **empty**: the lookup branch then never fires
(every name a guaranteed miss → identical `create_project_milestone` sequence as the old blind loop,
**no extra `projectMilestones` read**); the reusable value lives entirely in the `known is None`
branch for the future caller. **Prove byte-equivalence with a *negative* assertion**
(`assert not _queries(fake, "projectMilestones(")`), not output equality. **Name is the dedup key**
(no phase-key→id registry); the phase-header-text-drift duplicate-milestone edge is deferred to the
drift-repair node.

### Fail-open Project Updates (#606)

`projectUpdateCreate` bodies come from **pure backend-neutral composers** (`perk/objective.py`)
computed from counts the call site already holds → **no extra network reads**. Each call site wraps
in `try/except`, logs a non-fatal stderr line (`... skipped (non-fatal): {exc}`), and **never
changes the command result**; in `_reconcile_objective_on_land` the post lives in its own helper
(`_post_landed_update`) so a failure can't discard already-marked node ids (same isolation as the
existing close fail-open). `projectUpdateCreate(` does **not** substring-collide with `projectUpdate(`
(next char `C`), but place the more-specific needle first defensively. `projectUpdateCreate` was
offline-covered only at authoring — now **proven live** along with `set_project_state` /
`list_projects` / `_workflow_state_id` (the Mode-4 confirmations above, #621).

### The manifest-drift architecture (#609) — for the follow-up implementer

The canonical spec is `docs/planning/objective-repair.md` (read it, don't re-derive). The
load-bearing decisions:

- **Drift is only tractable against a persisted manifest.** `LinearProjectObjectiveStore.get_objective`
  derives the roadmap **live** from node-issues (no stored roadmap table — Node 3.2), so there is no
  baseline to diff; baseline-free heuristics (sequence-gap, empty-milestone) can't *repair* a deleted
  node's slug/description and were rejected as more complex long-term.
- **Linear has no invisible project-level metadata field** — ProseMirror drops HTML comments (the
  reason markers are transcoded to inline code), and attachment `metadata` is issue-scoped. So the
  manifest lands as a **visible-but-unobtrusive inline-code block in the project overview**, beside
  `objective-header`, written through the existing idempotent `update_project_content` path.
- **The manifest owns structural identity; status stays observed-only** (live state owned by each
  node-issue's `objective-node` block) — the split is what makes recreate repairs safe (restore
  structure without inventing status).
- **The observed snapshot needs a new sibling op:** `_LinearProjectOps.project_issues` carries no
  milestone membership, so don't perturb `get_objective`'s byte-stable query — add a sibling.

### Manifest-drift Linear mechanics delivered (#626)

The #609 design landed (drift engine + worker detail live in `objective-store.md` / `cli-command-groups.md`).
The **Linear-backend-specific** mechanics:

- **`attach_issue_to_milestone` mirrors `attach_issue_to_project`** — the **bare boundary identifier**
  through the module-level mutation wrapper, **no UUID resolution** (consistent with the #562 collapse
  above). The observed-snapshot read is a `project_issues` **sibling**, `project_issues_with_milestones`,
  that joins each issue's milestone id/name; the byte-stable `project_issues` query is left untouched.
- **The `replace_metadata_block` append-when-absent path emits an HTML form** (bad for Linear's
  ProseMirror). So a *fresh* manifest insert does **not** go through that path: render the block as
  inline-code and splice it manually before the reconcilable marker (derive the split point from the
  Linear-markdown rendering of the reconcilable start marker). The *present*-block update path stays
  form-preserving and is safe.
- **`FakeLinearWorkspace` must cascade-delete relations on issue delete** (mirrors Linear's real
  cascade) — else a stale `(blocker, blocked)` tuple survives a deleted issue and crashes the
  blocked-by lookup on the missing uuid. Store-level drift tests drive the real project store, then
  mutate the fake's issues/relations/milestones directly to inject each drift class.
- Both new ops were **offline-only / not-live-proven** at authoring time — now live-proven, see the
  Mode-4 confirmations below.

### `check_project_readiness` (#603) — a separate function

`check_project_readiness(client, *, team_key) -> LinearProjectReadiness` is a **separate** function
beside `check_readiness` (keeps the issue tier byte-stable), wired into `doctor`'s linear checks (two
new checks) and `init`'s linear readiness (a nullable `LinearReport.project` sub-report). The test
census + the non-fatal-sub-report discipline live in `init-doctor.md` — keep the detail there to
avoid duplication.

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
- **Runbook drift corrected** in `docs/planning/linear-smoke-gate.md`: `perk init --verify` is **not** a flag
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
- Projects substrate + `LinearProjectObjectiveStore` (Objective #548 Phase 3): #571 (PR #569),
  #575 (PR #574), #582 (PR #579), #586 (PRs #584/#585), #589 (PR #588), #595 (PR #594)

## Cross-references

- `docs/learned/workflow/issue-backend.md` — the backend-agnostic protocol seam
- `docs/learned/workflow/objective-store.md` — the objective-storage tier contract the
  project-backed store implements (the facade refactor, resolver, translate-CM, node↔plan unification)
- `docs/learned/workflow/init-doctor.md` — verify-gated network repairs, the readiness shape
- `docs/learned/workflow/config-tables.md` — the committed-only `[issues]` table shape + the local-only secret-fallback reader
- `docs/learned/workflow/cold-door-launch.md` — the launch-seam Linear-key env-seed (merge-order setdefault)
- `docs/learned/workflow/shared-contracts.md` — the cross-plane SSOT prompt-fragment pattern
- `docs/learned/workflow/skill-bindings.md` — skills `references:` subdirectory routing
- `docs/learned/workflow/mergeability-and-conflict-resolution.md` — the `/submit` mergeability gate
  (the live-smoke mergeability gotchas in #554 live there)
- `docs/learned/workflow/doc-reconciliation.md` — the measurement-node-resolves-an-open-conditional
  reconciliation pattern
- `docs/learned/toolchain/ty.md` — the narrowing-helper family for deep untyped payloads
