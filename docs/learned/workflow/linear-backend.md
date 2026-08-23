---
title: Linear issue backend
read_when: You are touching `src/perk/backends/linear/`, Linear GraphQL queries or test fakes, perk metadata (attachments or inline markers), init/doctor readiness, or the project-backed objective store.
cluster: backends-and-integrations
---

# The Linear issue backend

Objective #252 Phase 2/3 built the Linear backend in layers: the httpx GraphQL client
(`src/perk/backends/linear/client.py`), the `LinearIssueBackend` adapter
(`src/perk/backends/linear/backend.py`; both originally flat `linear.py` / `linear_backend.py`
modules, since folded into the `src/perk/backends/linear/` package), dual-encoding
metadata markers in `src/perk/plan.py` / the `src/perk/objective/` package, init/doctor readiness
wiring, and backend-aware prompt rendering. Backend-agnostic protocol learnings live in `issue-backend.md`;
this doc is the Linear-specific knowledge. Since #1355 the header/node/manifest metadata kinds
ride native Linear attachments (see the attachment-native section below); dual-encoding governs
only the still-inline surfaces.

## Distillation

- Auth is a *plain* `Authorization: <key>` header (Bearer is OAuth2-only); rate limiting arrives
  as HTTP 400 with `errors[].extensions.code == "RATELIMITED"`, so the client parses the body
  errors-array-first regardless of status; partial GraphQL success fails loud and discards
  partial data — "Linear API facts".
- The client returns `data` or raises (`LinearGraphQLError.codes`, never message substrings);
  lookup-miss `None` semantics belong to the backend — "The client/consumer contract".
- Perk metadata kinds ride **native issue attachments** (URL-as-upsert-identity,
  REPLACE-whole-envelope, the URL-reuse invariant) since #1355 — "Attachment-native perk
  metadata"; dual-encoding governs only the still-inline surfaces — "Dual-encoding metadata
  markers" (+ the presence-check bug class beside it).
- init/doctor readiness is ONE never-raising report-shaped probe with two consumers (doctor
  lookup-only vs init converge, split by `ensure_labels`) — "Readiness wiring (init/doctor)".
- Issue mutations take the **bare boundary identifier** through the module-level
  `_request_issue_mutation` wrapper — no resolve-on-demand layer (`uuid_for` deleted) —
  "Bare-identifier mutations + the module-level mutation wrapper".
- The project-backed objective store's live ops (node-issue materialization, milestone reuse,
  relations) — "Linear Projects substrate" + "Project-backed objective ops".
- Offline testing: httpx `MockTransport` recipes + the scripted GraphQL fake — "Offline test
  recipes"; register more-specific query needles FIRST — "`_FakeLinear` insertion-order
  substring footgun"; the stateful-fake lifecycle discipline — "E2E lifecycle test craft".
- `upload_file` is one resolver-owned method; strict marker parsing never strips first;
  byte-identity across a lossy transcoder rejects its whole normalization domain — "File upload
  + strict-parse boundary craft".
- Historical: "Live-validation record (dated)" + "Live-spike process craft" carry the dated
  live-run evidence.

## Linear API facts (audited against official docs)

- **Auth**: personal API keys use a *plain* `Authorization: <key>` header — `Bearer` is
  OAuth2-only. Getting this wrong fails confusingly; the test suite pins the raw-key form.
- **Rate limiting arrives as HTTP 400**, not 429: `errors[].extensions.code == "RATELIMITED"`.
  Consequence: `src/perk/backends/linear/client.py` parses the JSON body **errors-array-first, regardless of
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

### Not-found discrimination (#558, proven live 2026-06)

- **The canonical discriminator is a PAIRING**: `INPUT_ERROR` present in `exc.codes` **AND** the
  `"entity not found"` message prefix — because `INPUT_ERROR` is **generic** (it also fires on
  argument-validation errors), a code alone over-matches. One module-level helper
  `_is_entity_not_found(exc)` in the client layer (`src/perk/backends/linear/client.py`) backs
  every not-found read site.
- **Before tightening an error predicate to a GraphQL `extensions.code`, confirm the code is
  *specific*.** Linear reuses generic codes across unrelated failure classes.
- **Folding a live observation into a predicate means re-shaping the offline twins to the observed
  reality in the same change.** The fakes emitted `codes=()`; a naive predicate tightening silently
  re-raised the *whole* not-found suite until the twins gained the observed code.
- **Discrimination tests must prove the tightening NARROWED** — the valuable cases are the
  *negative* ones: a not-found message under `RATELIMITED` (or with no code) **re-raises**; a
  generic `INPUT_ERROR` carrying a non-not-found message **re-raises**. Only the paired shape is
  swallowed.
- **An unfired gating observation ships as a documented deferral, not an edit** (#558, 2026-06:
  RATELIMITED fail-loud kept; `uuid_for` kept, later collapsed — the bare-identifier-mutations
  section below).

## Bare-identifier mutations + the module-level mutation wrapper (#562/#620)

The verified issue mutations (`issueUpdate`/`commentCreate`) take the **bare boundary identifier**
directly (observed live 2026-06-15, #564: both succeed with `PER-n`; a bogus `PER-99999` still
errors `INPUT_ERROR` / "Entity not found"); `LinearClient.uuid_for` + its cache are **deleted** —
no resolve-on-demand layer remains. The durable architecture:

- **Shared issue-mutation behavior both op classes need lives MODULE-LEVEL, not on one op class.**
  The verified-mutation call sites span **two** client-only op classes (the issue ops AND the
  project ops' attach-issue-to-project), and — per the substrate-home principle below — the
  project ops do **not** compose the issue ops; both only register the shared client. A method on
  one class is unreachable from the other. So the not-found-mapping wrapper is a **free function
  parameterized by `client`** (`_request_issue_mutation`, `src/perk/backends/linear/_helpers.py`),
  the only shape that avoids four copies. *General rule: shared mutation behavior the two op
  classes both need is module-level (client-parameterized), because they are **siblings over a
  shared client, not a composition**.*
- **A byte-identical not-found mapping survives the deletion by RELOCATING it** into that thin
  request wrapper (it governs only the wrapped `request` call; the `success is not True` payload
  checks stay AFTER the wrapper returns). And **capture-at-create beats resolve-on-demand** for the
  one consumer that still needs a UUID: a raw create variant returns the create-time UUID for the
  UUID-only `issueRelationCreate` (relations still take UUIDs; zero extra queries).
- One intentional `uuid_for` string survives in production — a docstring back-reference on the
  request wrapper (a `grep` for `uuid_for` in `src/perk/` hits it; **expected, not a leftover**).
  The test-fakes dropped their scripted `UuidForIssue` reply entries / branch and **flipped
  mutation-id assertions from the resolved UUID to the boundary identifier** (plus `assert not` a
  resolution query fired).

## Attachment-native perk metadata (the #1355 storage model)

The perk metadata kinds enumerated by the `*_KIND` constants in
`src/perk/backends/linear/attachments.py` — `plan-header`, `learn-header`, `gist-header`,
`objective-node`, `objective-header`, `objective-manifest` — are stored as **native Linear issue
attachments** carrying a machine-readable `metadata` envelope, no longer as inline-code blocks in
bodies. The envelope shape is `source` / `schema_version` / `kind` / `payload_json` (see
`src/perk/backends/linear/attachments.py`).

- **URL as upsert identity.** Attachment URLs use the honest non-resolving
  `https://perk.invalid/...` scheme (RFC-2606 `.invalid`); Linear's `attachmentCreate` upserts by
  `(url, issueId)`, and write semantics are **REPLACE-whole-envelope** — partial writes don't
  exist, which is why the writers always re-emit the full envelope.
- **The URL-reuse invariant.** Every writer reuses the *found* attachment's URL, never re-derives
  it. This started as one line in the plan-header update and hardened into a contract rule
  enforced on every writer (including the node-issue writers) — when adding a new attachment
  writer, thread the found URL through, don't recompute.
- **The per-project canceled metadata sentinel issue** (`project_store.py`). Linear exposes no
  public project-attachment mutation and no arbitrary project metadata, so a canceled, empty
  sentinel issue titled "Perk: objective metadata" attached to the project carries the
  `objective-header` + `objective-manifest` envelopes. It is state-independent by design (born
  canceled) and never an adoptable/mappable candidate.
- **`attachmentsForURL` O(1) finds** back the run_id-keyed idempotency lookups (`backend.py`) —
  with the broader-lookup parity trap below.
- **Tolerant vs fail-loud decode twins** (`attachments.py`). `has_perk_attachment` is
  presence-only and never raises — classification/gather paths take it; `find_perk_attachment`
  fails loud on a malformed payload — mutation-path reads take it. Review found two sites using
  the fail-loud decoder where the tolerant posture was contractually required — when adding a
  read site, pick the twin by whether the path classifies or mutates.
  - **Both twins run the lenient envelope parse first**, so a malformed envelope **shape** (e.g.
    a non-string `source`/`kind`) raises pydantic `ValidationError` — not `IssueBackendError` —
    from either twin; `has_perk_attachment` is not strictly "never raises". A tolerant
    list/classification reader calling `find_perk_attachment` must catch
    `(IssueBackendError, ValidationError)` — shipped example: the pending-learn classification
    read in `src/perk/backends/linear/backend.py`, hardened after PR review found exactly this
    gap (one stray attachment on any row would otherwise abort the whole listing).
  - **Plan-authoring corollary:** plans for tolerant reads over external metadata must enumerate
    each malformedness boundary separately — malformed *payload* vs malformed *envelope/schema*
    are different exception classes — and require a test per boundary ("absent/malformed ⇒
    silently not-pending" without naming the second exception type is how the gap shipped).
- **Surfaces still inline.** Plan-body comments, Reconcilable markers, and callouts still use the
  dual-encoding inline-code sentinels — the next section still governs those.

### Migration traps (#1355)

- **Sequential-identifier shift.** Inserting a new "first issue" into a Linear create flow (the
  sentinel is created before node-issues) shifts every subsequent `ENG-N` identifier — ~60
  lifecycle-test assertions needed renumbering. When adding an issue to an existing creation
  sequence, check position-in-sequence impact on identifier-pinning tests first.
- **Broader-lookup migrations lose implicit filters.** Replacing the label-scoped *open-issues*
  scan with the state-independent `attachmentsForURL` silently dropped the "open only" filter,
  and the single-node variant was order-dependent on multi-hit. When swapping a scoped query for
  a broader primitive, enumerate the old query's implicit filters (state, label, team scope) and
  re-apply them explicitly — and make multi-hit behavior deterministic (first non-terminal wins).
- **"Dormant" code isn't insulated from shared-infrastructure deletions.** The migration assumed
  the dormant `objectives.py` store stays byte-untouched, but deleting a shared find-by-run-id op
  forced relocating it into the dormant store (a third consumer the plan undercounted). Count ALL
  consumers of a shared op before deleting it, including dormant ones.

## Dual-encoding metadata markers

`src/perk/plan.py` renders metadata blocks in two forms: HTML `<!-- perk:x -->` markers for GitHub and
inline-code `` `perk:x` `` sentinels for Linear (ProseMirror strips HTML comments). Since #1355
dual-encoding governs only the still-inline surfaces (plan-body comments, Reconcilable markers,
callouts) — the header/node/manifest kinds moved to native attachments (see the attachment-native
section above).

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
  `` `perk:x` `` rewrite rule locally (import direction `linear/backend.py → objective` forbids
  importing the transcoder). If `to_linear_markdown`'s marker rule ever changes, both sites must
  change; the guard is `tests/test_objective.py`'s transcoded-fixture tests (real
  `to_linear_markdown` output run through the objective engines).

## Two composition disciplines

- **Issue descriptions are composed directly inline-code-style**
  (`render_metadata_block(..., style="inline-code")`, the `create_learn_issue` precedent).
- **Comment bodies are transcoded** via `to_linear_markdown` because they're rendered from
  the `src/perk/objective/` package's HTML marker constants.

Two distinct disciplines in one backend — keep them straight when adding ops.

## Backend behavioral pins

- Comments are **sorted client-side ascending by `createdAt`** to pin GitHub's oldest-first
  first-match semantics — never trust Linear's default connection ordering.
- Label idempotency is **lookup-first and unscoped** (a workspace-level label counts; a
  team-scoped create on a duplicate name errors), with a duplicate-race re-lookup arm.
- `LinearIssueBackend.backend_id` is a module-level `"linear"` literal — never import
  `perk.backends.resolve` for it (the resolver imports the Linear backend module at wiring time; the
  import-direction test pins this).
- The ensured perk labels live in `src/perk/backends/linear/readiness.py`'s `_PERK_LABELS`
  (duplicating the plan/objective constants by reference, not value) — **adding a perk label
  requires touching that tuple** or it silently stops being ensured at init.
- `[issues] team` resolves by Linear team **KEY** (e.g. `PER`), **not** the workspace / display
  name (#554, observed live). A name silently fails team resolution and surfaces only at **land**
  as the *non-fatal* `plan issue close skipped (non-fatal): Linear team '<x>' not found`
  (`plan_issue_closed: false`); the GitHub squash-merge still succeeds.

## Readiness wiring (init/doctor)

- `check_readiness` (`src/perk/backends/linear/readiness.py`) is **one report-shaped probe with two consumers**: doctor
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

- `client_from_env(env=None, *, repo_root: Path | None = None)` is **env-first** (stripped), then
  falls back to the `repo_root` `.perk/local.toml` `[linear] api_key`; the `repo_root=None` default
  keeps every pre-existing caller byte-identical (#654).
- **The reader anchors to the main checkout** (#730): `config.load_local_linear_api_key` reads
  `git.main_worktree_root(repo_root) or repo_root`, so the gitignored key is found from inside a
  linked worktree **independent of whether the `launch_stage` env-seed fired** (#730 corrected the
  partially-true "the env-seed carries it" framing that masked this). One reader feeds both the
  cold-door fallback and the env-seed; the env-seed still wins when env is set. See
  `docs/learned/workflow/worktree-lifecycle.md` for the `main_worktree_root` primitive.
- Threaded at four in-process sites (`resolve_issue_backend`, `resolve_objective_store`,
  `doctor._linear_checks`, `init._linear_readiness`); a **fifth** (`doctor._fix_linear_labels`)
  deliberately stays env-only pending a "config fallback everywhere" symmetry pass.
- **Signature-widening rule (#654)**: adding the `repo_root` kwarg broke 21 lifecycle tests faking
  `monkeypatch.setattr(linear, "client_from_env", lambda: ws)`. When you widen a function's
  signature, grep ALL `monkeypatch.setattr(..., "<fn>", lambda ...)` fakes of it and loosen them to
  `lambda *a, **k`.
- **Out of scope (flagged):** `LINEAR_AGENT_TOKEN` (a distinct secret; the `[linear]` table leaves
  room for a future `agent_token` key, not added); `--remote` (the remote runner provides its own
  secrets); no TS-plane mirror (the TS extension reads no Linear key).

See `docs/learned/workflow/config-tables.md` for the local-only secret-fallback reader shape and
`docs/learned/workflow/cold-door-launch.md` for the env-seed merge order at the launch seam.

## Agent-session emission (one-way, internally gated)

`src/perk/backends/linear/agent.py` + the `agent-session.json` cache helpers emit Linear AgentSession /
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
gate open** (monkeypatch `emission_enabled` in `src/perk/backends/linear/agent.py` → True, plus a canned
`cache.read_agent_session` for follow-up emitters) and **break the substrate**
(`agent_client_from_env` raising), then assert exit-code/`--json`-payload byte-neutrality
end-to-end through the real fail-soft wrapper. Reusable whenever a fail-open side-channel is wired
into a host command.

Plus the MockTransport injection recipe for module-internal client construction: monkeypatch the
module's `LinearClient` symbol with a keyword-only factory that closes over a transport — records
every request the emitters compose without touching emitter code or the real client class.

## E2E lifecycle test craft

- **Named GraphQL operations make substring-keyed fakes routable**: naming an operation gives the
  substring-keyed fakes a distinct needle, and most-specific-needle-first insertion order does the
  rest (historical exhibit: the resolution layer's `UuidForIssue` named op, deleted with the #562
  collapse). Needle-ordering detail is owned by the two insertion-order sections below.
- **The stateful `FakeLinearWorkspace` discipline**: the fake tolerates identifier-or-UUID on
  reads AND mutations (the Mode 2 live finding, 2026-06-15) — there is no resolution layer to pin.
  Lifecycle tests instead assert **no `UuidForIssue` query fires**
  (`assert not _queries(fake, "UuidForIssue")`) and make mutation-id assertions with the boundary
  identifier (the #562/#620 bare-identifier section above is the authority); junk ids still raise
  `Entity not found` (`INPUT_ERROR`). Page size 2 exercises the cursor loop on tiny data for free.
- **Late-bound `linear.client_from_env` monkeypatching** runs the whole real stack (resolver →
  `LinearIssueBackend` → real CLI commands) offline; only the GitHub PR tier needs the classic
  gateway fakes. **One shared workspace threading the entire lifecycle in a single test** catches
  cross-command contract drift (e.g. the plan-body comment must be patched, not duplicated, on
  re-save) that per-command tests can't.
- **A new mutation needs the fake to ROUTE it AND have the needed workflow states (#855).**
  Exercising objective replan (supersede) surfaced three `FakeLinearWorkspace`
  (`tests/_linear_fakes.py`) gaps: (a) a **`"projectId"` arm in the `issueUpdate(` handler**
  (attach-to-project was previously unrouted); (b) a **new `projectUpdateCreate(` arm** — the
  fail-open status update previously hit the `unrouted` `AssertionError`, and `objective create`'s
  status update only survived because its caller wraps it in `except Exception`; and (c) a
  **`canceled`-type workflow state in `_STATES`** — without it `_workflow_state_id("canceled")`
  returns `None`, so the cancel-dropped path is a silent no-op that can't be asserted. **General
  rule:** when testing a new Linear mutation against the fake, confirm it actually routes the
  operation AND has the workflow states the path needs.

## Backend-aware prompts (Node 3.1)

- **Per-plane plan-read SSOT helpers**: `src/perk/run/launch/prompts.py::_plan_read_instruction`
  (re-exported by the `src/perk/run/launch/` package) ↔
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
`src/perk/cli/commands/objective/shared.py`) ↔ byte-identical `objectiveReadInstruction` (TS,
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
  github-arm output is literally byte-identical** after the change (no test pins it).
- **Cold-vs-warm backend-source asymmetry is the load-bearing design call.** Cold has
  `store.backend_id` + `state.url` already in hand (free). Warm must resolve the backend from
  `resolveIssueBackendId(ctx.cwd)` (the committed `.perk/config.toml`, main-checkout-anchored —
  **NOT** `loadPerkConfig`'s overlay) and
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
- **The scripted GraphQL fake** (`tests/_linear_fakes.py::_FakeLinear`): responses keyed by
  query-substring in **insertion order** — order more-specific needles first (`"comments(first"`
  before `"issue(id"`, since the comments query also contains `issue(id:`); per-key queues pop
  until one entry remains, then reuse it (pagination scripting + repeated-call reuse for free).
- **ty + GraphQL payloads**: navigating `dict[str, object]` responses needs a narrowing-helper
  family (`_require_dict`/`_require_list`/`_require_str` with `cast`, raising `IssueBackendError`
  on malformed shapes — doubling as the never-silently-truncate guard). In tests, one
  `_input_payload()` cast helper beats per-site `assert isinstance` (which ty doesn't narrow
  through `__getitem__`). See `toolchain/ty.md`.
- **Query-shape tests use non-default parameters**: a `per_page=50` pin passes even against a
  hardcoded default (`limit=9` → `per_page=9` doesn't), and the selection fields a decoder reads
  must be pinned on the *recorded query* — scripted fakes return fields regardless of the
  selection (extends the doc's existing selection-pin discipline).

## Live-validation record (dated)

The live smoke gate ran **green** across every mode — no backend defect, docs-only PRs; the items
the live runs did *not* answer live in the Still-deferred register below.

- **2026-06-15 — Modes 1 & 2 + the Projects spike (#554/#558/#564/#567):**
  - **ProseMirror round-trip is CLEAN** — `find_metadata_block` survives a real round-trip with no
    raw-HTML artifacts; a re-save **patches the body comment in place** (count stays 1: the
    form-preserving `replace_metadata_block` path, live). *(Predates #1355 — proved the inline
    model.)*
  - **String `PER-*` identifiers flow through every `--json` envelope** end-to-end; closure is the
    explicit `close_issue` call, never a merge-message magic word.
  - The generic-`INPUT_ERROR` missing-entity observation seeded the paired not-found
    discriminator — see the Not-found discrimination section above.
- **2026-06-16 — Mode 4, project-backed objective lifecycle (#621):**
  - **Find-by-run-id is idempotent** (same UUID / `existed:true`, no duplicates); metadata
    round-trips clean through create→reconcile; node↔plan unification creates **no new
    `perk:plan` issue**.
  - **Project Updates post on create / land / reconcile**; **close** drives the Project to
    `completed`; the node workflow-state mirror fires **both directions** (in-progress→started,
    done→completed).
  - Also proven live: `projectUpdateCreate`, `set_project_state`, `list_projects`,
    `_workflow_state_id`, and the #626 ops (`attach_issue_to_milestone`,
    `project_issues_with_milestones`). No RATELIMITED at low volume.
  - **Setup gotchas** (running Linear from a GitHub-default repo): backend selection reads the
    **committed `.perk/config.toml` only** — a local overlay silently no-ops (see
    `config-tables.md`); use **`uv run perk`**, never a stale global install (see
    `toolchain/worktree-node-modules.md`); the doctor `linear` group appears only once committed
    config selects linear.

### GitHub-integration coexistence (#564, 2026-06-15)

- The Linear GitHub integration links PRs as **attachments, not comments** — the linkback-tolerance
  concern is structurally moot (the offline twin
  `test_foreign_linkback_comment_does_not_perturb_marker_scans` is *stricter* than reality); perk's
  `plan-PER-<n>` branch auto-links without Linear's branch template; on-land `close_issue` beside a
  Done-on-merge automation is a **same-state write**.
- **"Installed ≠ connected"**: the decisive isolation test is a control PR in `issue.branchName`'s
  canonical format — `team.gitAutomationStates` confirms automation *config*, and the App
  installation is not introspectable from a normal `gh` token.

## Linear Projects substrate + `LinearProjectObjectiveStore` (now BUILT)

The project-backed objective store was built on the #567 spike substrate (Objective #548 Phase 3,
2026-06); the tier contract lives in `objective-store.md` — the Linear-specific mechanics are here.

### The substrate-home principle (the load-bearing #582/#586 lesson)

**The only thing that should encapsulate Linear GraphQL client logic is `LinearClient`.** The op
classes (`_LinearIssueOps`, `_LinearProjectOps`) must each register **only the client**, never one
another. Shared machinery — team-id/viewer-id resolution + caches, pagination, the `_require_*`
narrowing helpers, the not-found discriminator — belongs **on the client**.

- **Treat prior standing architectural guidance as load-bearing; don't re-litigate it with leading
  questions** (#582: a leading confirm-this question manufactured a plan-level "Confirmed with the
  user" against the user's standing guidance, so a faithful implementer shipped the composition
  defect — the error must be caught at planning time).
- **Acknowledge-don't-revert** (#586): the defective node stayed `done` with its description
  rewritten to name the defect; the correction was overloaded onto the next node.

### The re-homing recipe (#586)

When client machinery moves onto `LinearClient`, a **request-only structural seam can no longer
carry behavior** — retype every seam to `LinearClient` and have **both fakes** (scripted +
stateful) **SUBCLASS it** (no `super().__init__`; just init the two caches directly), so they
inherit the real machinery routed through their overridden `request` and every existing GraphQL-
document assertion stays byte-green. This is the general recipe for promoting machinery off a
delegated collaborator onto its client tier.

- The `_require_*` helpers + the not-found discriminator moved **DOWN** to the client layer
  (`src/perk/backends/linear/client.py`, re-imported by `backend.py`) to avoid an import cycle. The `INPUT_ERROR`-in-`.codes`
  AND `"entity not found"`-message pairing stayed intact (do not loosen to `.codes`-only).
- The **team-id cache is keyed by `team_key`** (the client stays team-agnostic at construction; op
  classes pass their bound team_key). A single shared cache via the client beats op-class
  composition — it de-dupes when only one op class is in play.
- **Decoupling over DRY:** symmetric client-only op classes inline a tiny mutation (e.g.
  attach-issue-to-project) rather than reach a sibling.

### `_create_issue` made label-optional

Build `labelIds` into the input **only when non-None** (node-issues carry no perk label — they are
discovered by project membership + the node block); the same conditional-key shape as
`project_id` / `milestone_id`: omit the key, never an explicit `null`.

### Project-backed `create_objective` shape (#586)

- **Overview = inline-code `objective-header` block + a Reconcilable prose region, NO roadmap
  table** *(the header half is superseded by #1355: the `objective-header` now rides the
  per-project metadata sentinel issue as an attachment — see the attachment-native section; the
  overview keeps the Reconcilable prose region)*. Compose the markers in HTML form, then pass the
  WHOLE overview through the Linear-markdown transcoder so markers become inline-code sentinels.
  **The roadmap is derived LIVE from node-issues — never stored as a YAML block on the Linear
  side.**
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
  reads back as `None` (sequential inference then applies downstream). No identifier→UUID
  resolution layer exists anywhere (the #562 collapse): the project store passes ids straight
  through, and tests assert no `UuidForIssue` query fires.
- **The node-status workflow-state mirror keeps a SEPARATE states cache** from the learn-close path
  (byte-stable), and **fails open** by swallowing the backend error (`LinearGraphQLError` is a
  subclass, so both a `success:false` payload AND a raised error are caught); a `None` state id is
  skipped silently before any write.
- **Live-observed reconstruction limits (#621)** — the empirical baseline the #626 drift doctor
  formalizes: `objective show --json` **omits `depends_on`** and **derives `phase` from the node
  id** (not the milestone), and `get_objective` **silently absorbs drift** — an un-assigned node
  disappears, an unknown relation is dropped, a milestone rename is invisible — which is exactly
  why the manifest-pinned drift doctor exists.

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

Live probe fact (Mode 4, #621): `issueRelationCreate`'s `type` is a GraphQL **enum** — a quoted
inline literal fails validation; pass it via a typed `$input` variable.

### Milestone + create facts (retained from the spike)

- `projectCreate(input:{teamIds,name,content})` accepts `content` at create (the 2024 create-then-
  `projectUpdate` workaround no longer applies); a `documentCreate` round-trip is kept as a proven
  fallback in reserve.
- **Milestone list order is NOT insertion order** — key phases by milestone **name**, never list
  position.
- **`list_projects` was proven live 2026-06-16 (#621)** — see the Live-validation record above
  (the #567 spike had covered create/overview/milestone/attach/relation, not list-projects). No
  RATELIMITED at spike volume.

## Project-backed objective ops (Phase 4: Nodes 4.1–4.4)

Objective #548 Phase 4 layered four additive enrichments onto `LinearProjectObjectiveStore`
(backend-aware seed prompts are in the Backend-aware-prompts section above; GitHub stayed
unchanged throughout).

### `add_objective_node` project-store flow (#614)

The project store materializes a node-**issue**, not a roadmap-block re-render (the split lives in
`objective-store.md`). Pipeline: `get_objective` → `objective.add_node` (compute `<phase>.<n>`) →
`project_or_none(content)` (phase-name enrichment: `enrich_phase_names` reads `### Phase N: name`,
falls back to `phase_label`) → `ensure_phase_milestone(known=None)` →
`_create_issue(project_id, milestone_id)` → one `create_issue_relation` per `depends_on`. The
`known=None` branch was pre-built (#606) *explicitly for this future add-node caller* (its
docstring says so) — a load-bearing seam, not fiction.

### The id-collision `None` branch is genuinely UNREACHABLE via real inputs (#614)

`add_node`'s id-collision `None` return has no realistic trigger (any occupying node would be
counted in `max_num` → contradiction). **Don't write a unit test forcing the impossible branch** —
test the *gateway error mapping* instead: monkeypatch `objective.add_node` to return `None` and
assert the "collision" message maps to the CLI `invalid_input` arm.

### `FakeLinear` add-node fixture gotchas (#614)

- One `add_objective_node` path issues **two** `project_or_none` reads → a 2-element list under the
  `project(id` key.
- `_create_issue` triggers a team-id lookup → the fixture needs a `teams(filter` entry.
- Register the more-specific needle first — see the `_FakeLinear` section above.

### The phase→milestone seam: route an existing caller through a future seam without behavior change (#606)

`ensure_phase_milestone(*, project_id, name, known=None)` routed the current create-objective
caller through the future add-node seam by seeding that caller's `known` map **empty** — the
lookup branch never fires, so the mutation sequence is byte-equivalent to the old blind loop with
**no extra `projectMilestones` read**. **Prove byte-equivalence with a *negative* assertion**
(`assert not _queries(fake, "projectMilestones(")`), not output equality. **Name is the dedup key**
(no phase-key→id registry); the phase-header-text-drift duplicate-milestone edge was deferred to
the drift-repair node.

### Fail-open Project Updates (#606)

`projectUpdateCreate` bodies come from **pure backend-neutral composers**
(`src/perk/objective/render.py`) computed from counts the call site already holds → **no extra
network reads**. Each call site wraps in `try/except`, logs a non-fatal stderr line (`... skipped
(non-fatal): {exc}`), and **never changes the command result**; in `_reconcile_objective_on_land`
the post lives in its own helper (`_post_landed_update`) so a failure can't discard already-marked
node ids. `projectUpdateCreate(` does not substring-collide with `projectUpdate(` (next char `C`),
but place the more-specific needle first defensively.

### The manifest-drift architecture (#609) — for the follow-up implementer

The load-bearing decisions:

- **Drift is only tractable against a persisted manifest.** `LinearProjectObjectiveStore.get_objective`
  derives the roadmap **live** from node-issues (no stored roadmap table — Node 3.2), so there is no
  baseline to diff; baseline-free heuristics (sequence-gap, empty-milestone) can't *repair* a deleted
  node's slug/description and were rejected as more complex long-term.
- **Linear has no invisible project-level metadata field** — ProseMirror drops HTML comments (the
  reason markers are transcoded to inline code), and attachment `metadata` is issue-scoped.
  *Historical (superseded by #1355):* the manifest originally landed as a
  visible-but-unobtrusive inline-code block in the project overview, beside `objective-header`,
  written through the idempotent `update_project_content` path — it is now an
  `objective-manifest` attachment on the metadata sentinel issue (see the attachment-native
  section). Still true: the manifest owns structural identity, and status stays observed-only
  (next bullet).
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
- *Historical (superseded by #1355 — the manifest now rides the sentinel issue as an
  attachment):* **the `replace_metadata_block` append-when-absent path emits an HTML form** (bad
  for Linear's ProseMirror), so a *fresh* manifest insert did **not** go through that path: render
  the block as inline-code and splice it manually before the reconcilable marker (derive the split
  point from the Linear-markdown rendering of the reconcilable start marker). The *present*-block
  update path stays form-preserving and is safe.
- **`FakeLinearWorkspace` must cascade-delete relations on issue delete** (mirrors Linear's real
  cascade) — else a stale `(blocker, blocked)` tuple survives a deleted issue and crashes the
  blocked-by lookup on the missing uuid. Store-level drift tests drive the real project store, then
  mutate the fake's issues/relations/milestones directly to inject each drift class.
- Both new ops were **offline-only / not-live-proven** at authoring time — now live-proven, see the
  Live-validation record above.

### `check_project_readiness` (#603) — a separate function

`check_project_readiness(client, *, team_key) -> LinearProjectReadiness` is a **separate** function
beside `check_readiness` (keeps the issue tier byte-stable), wired into `doctor`'s linear checks (two
new checks) and `init`'s linear readiness (a nullable `LinearReport.project` sub-report). The test
census + the non-fatal-sub-report discipline live in `init-doctor.md` — keep the detail there to
avoid duplication.

## Live-spike process craft

- **The firing mechanism**: `client_from_env()` (`src/perk/backends/linear/client.py`) +
  `LinearClient.request(QUERY, VARS)`, resolving the team UUID via
  `teams(filter:{key:{eq:"PER"}})`; the throwaway runner lives in `/tmp` — no bespoke committed
  scripts.
- **Check `LINEAR_API_KEY` in the session env** before assuming a live node must be deferred to an
  operator — a live spike may be fireable in-session.
- **The `--json` cold workers drive the deterministic mutation paths sessionlessly**;
  `perk implement` is the only stage with no `--json` worker (the work *is* the session) —
  position its worktree via `perk worktree create plan-<id>` and copy
  `.perk/workflow/plan-ref.json` into the new worktree (the PR-workers read the worktree-local
  plan-ref).
- **Probe side-effects clobber idempotency**: overwriting an issue *description* while probing
  destroys its `plan-header` sentinel, so a later `perk plan save` creates a **new** issue — use a
  throwaway field or restore immediately.
- **Python `urllib` HTTPS fails on this host** (`CERTIFICATE_VERIFY_FAILED`) — use `curl` for
  ad-hoc Linear GraphQL probes.

### Reconciliation pattern (cross-cutting)

When a measurement node **resolves a decision the prose framed as open** (overview-vs-document →
overview; not-found `.codes` tightening → paired predicate), that conditional is the prime stale spot
for `/objective-reconcile` to flip. (Terse by design; the full reconciliation pattern lives in
`doc-reconciliation.md`.)

## Idiomatic backend: attribution, labels, attachments, prose-first (#678)

- **The bottleneck is the leverage** (#678): `assigneeId` once in `_create_issue_raw` covers all
  issue creates; `leadId` + `startDate` once in `create_project` covers all projects — no
  per-caller threading. `viewer_id()` is a cached resolver mirroring `team_id` memoization.
- **Fake-init cache seeding (recurring)**: both fakes subclass `LinearClient` **without**
  `super().__init__`, so every new client cache must be seeded directly or the resolver raises
  `AttributeError`; the scripted `_FakeLinear` pre-seeds, the stateful `FakeLinearWorkspace`
  leaves it `None` (exercises the real request path).
- **Adding a perk label is a wide ripple** (`_PERK_LABELS`, readiness count tests, doctor/init
  docstrings, contracts §, user docs) — grep the readiness label-count comments and count-asserts
  first. Labels are workspace-scoped (no `teamId` in the create input; lookup was already
  unscoped).
- **`attachmentCreate` is idempotent by URL** (no id to track) → safe to post on every PR stamp;
  wired fail-open into `update_plan_header` (catches `(IssueBackendError, GitHubError,
  ValueError)` — the `ValueError` covers `int(pr_field)`). Bookkeeping must never fail a header
  stamp.
- **Reads are position-independent (marker scans); one write wasn't**: the prose-first reorder
  flipped the manifest backfill insert point from before the Reconcilable START marker to after
  the END marker (the manifest has since moved to a sentinel-issue attachment, #1355). **Never
  guess-and-ship an unverified externally-rendered form** — the collapsible-toggle wrapper shipped
  as a recorded decision point, not a guess (a lossy round-trip would break marker-matching).

## Byte-stable sibling selection + `_is_entity_not_found` (#687)

The honest engagement reads reaffirm the **"leave the byte-stable marker-matching selection
untouched, add a sibling query"** rule: add `_comments_with_authors` (which selects
`editedAt`/`user`/`botActor`) **beside** the byte-stable `_comments`, proven with a
`git show <base>:file | sed -n` diff. The paired **INPUT_ERROR + "entity not found"** not-found
discriminator (`_is_entity_not_found`) folds a missing issue/session → empty; **auth failures raise**
(fail-loud accommodates the unproven personal-key-vs-agent-token question). (See
`human-engagement-reads.md`.)

## GraphQL type-literacy consolidation (Node 3.1, PR #731)

- **Substrate-home placement** (#731): the *generic* narrowing helpers (`_opt_*`/`_require_*`)
  live in the client layer (`src/perk/backends/linear/client.py`); the *domain* payload mapping
  lives in the package leaf `src/perk/backends/linear/_helpers.py`, which **imports** the
  generics. Generic narrowing is substrate; payload-shape knowledge is domain — keep them in
  their own tiers.
- **One standing exception**: `src/perk/backends/linear/agent.py::_parse_created_session` carries
  two direct `cast("dict[str, object]", …)` local narrowings — the confinement claim covers the
  helper-riding call sites, not a package-wide zero.
- The generic `_opt_*`/`_require_*` detail and the disposition-matching rule live in
  `toolchain/ty.md` (the lenient-twin section) — don't duplicate it here.

## Issue-tier boundary model (the `TypedDict` pilot retired)

The Node-3.1 `LinearIssueNode` `TypedDict` pilot (PR #731) was **retired** for a lenient response model
(`LinearIssueNodeModel` + nested `_IssueStateNode` in `src/perk/backends/linear/_helpers.py`), mirroring
the GitHub node-2.1 boundary→domain pattern. Because the one recurring selection
(`id identifier url title description state{type}`) feeds **two** domain objects — `PlanState` via
`get_plan` AND `AdoptableIssue` via `read_issue` — there is **no single `to_domain()`**: the model
exposes validated field accessors + a `normalized_state()` helper and each call site assembles its
own domain object (the model-crosses-the-boundary / call-site-assembles split). `identifier` is the
only required field (it IS the boundary id `PlanState.id` / `AdoptableIssue.id`); the rest are
tolerant-default, so only the present-but-malformed error TYPE changes (→ a labelled
`IssueBackendError` with a `"read plan issue …"` source). The `translate_validation_errors` wraps
ONLY `model_validate`, never the downstream `_get_pr` (which already raises `IssueBackendError`). The
engagement-mapper helpers (`_require_str` / `_opt_str` / `_opt_dict`) STAY — they back the still-inline
out-of-scope engagement reads. Full recipe in `pydantic-boundary-models.md` (the
gateway-application section).

## `_FakeLinear` insertion-order substring footgun (RECONFIRMED, #711)

Every `project(id` sub-query contains the `project(id` substring; in the scripted-response dict
register the **more-specific needles** (`projectMilestones(`, `issues(first`) **BEFORE** the generic
`project(id`, else the wrong response matches. (Reconfirms the established more-specific-needle-first
rule.) The adoption-writer instance: the `project_issues_for_adoption` / `project_milestones` /
`project_or_none` collision in the project-backed adoption flow. The #1355 instance: the
more-specific needles `issues(first` / `projectMilestones(` registered before the generic
`project(id`.

## Native cancellation vs perk's attachment status — orthogonal authorities

The cancellation/doctor work over the project-backed store pinned the authority split:

- **Native workflow state and perk's attachment status are orthogonal authorities.** A native
  `canceled` state is an *external-intent read override*: the store exposes an effective SKIPPED
  while provenance preserves the attachment status. Repair writes only the objective-node
  attachment, **never** native state. And rollback verification needs a **fresh state-bearing
  read** — a reopened native node vanishes from the projection, so the pre-rollback snapshot
  can't confirm the rollback.
- **State-bearing reads use a sibling query** — `project_issues_for_objective_projection` in
  `src/perk/backends/linear/project_ops.py`, the established byte-stable sibling-query pattern
  for consumer-specific selections (never widen an existing byte-stable query).
- **The issueCreate→attachment window needs a create-time fingerprint.** A rerun can't identify
  a fresh node-issue whose discovery key isn't yet attached; the materialization-recovery read
  fingerprints the atomically-created fields (project/title/description/milestone/label) to
  resume the attachment write.
- Residual: the projection, the state-bearing query, the attachment-only conditional writer, and
  the transfer path are **fake-proven only** — no authenticated live run yet. Remember this
  before trusting `--fix` against a real workspace.

## File upload + strict-parse boundary craft (#1996)

From the dream-companion artifact work:

- **`LinearClient.upload_file` is one method owning reservation + signed-PUT choreography**,
  computing size from the actual content bytes. A strategy hierarchy for one non-noop behavior
  with one caller is over-structure — a resolver-owned function suffices.
- **When byte-identity convergence spans a lossy transcoder, the invariance predicate rejects the
  transcoder's ENTIRE normalization domain** (the full `str.splitlines()` set, mirrored in both
  planes, parity-pinned) — or an immutable create-once record conflicts forever.
- **Never `strip()` a body before strict marker-grammar parsing** — normalization-before-parse
  converts corruption into false negatives.
- **Untrusted-at-rest reads wrap read + decode + parse uniformly at the boundary.**

## Still-deferred register (trimmed)

The live runs in the Live-validation record above resolved the fidelity / not-found /
mutation-acceptance items; what remains unobserved:

- **RATELIMITED retry/backoff** — still unobserved at low CLI volume; the typed loud failure stands.
- **`LINEAR_API_KEY` as a GHA secret** for headless/remote runs.
- **Agent-session deferrals**: `perk address` emission, the `agentSessionUpdate.plan` checklist
  (technology preview), elicitation, retry/backoff, a webhook receiver (emission is one-way).
- **Remote-vs-local agent-session pointer residual**: a remote-created agent session is invisible to
  a later *local* land (`agent-session.json` lives in the runner's checkout, so the local land skips
  its emission with a stderr note) — accepted; a durable issue-tier session pointer would fix it.
- **#1355 attachment lifecycle not live-proven**: validated offline + a one-day API-mechanics
  spike only; it has not run against live Linear (notably `entityExternalLinkCreate`'s live
  evidence is a docstring claim).
- **#1355 crash windows**: accepted create→attachment crash windows (issue tier + sentinel) have
  no recovery script or chaos coverage.
- **#1355 fail-open arms** (Resources link, PR card, status mirror) are only scripted to succeed
  in tests.
- **#1355 clean break**: pre-#1355 Linear artifacts are invisible to reads — accepted as
  disposable dogfood data; no migration playbook exists if that assumption changes.

## Cross-references

- `docs/learned/workflow/pydantic-boundary-models.md` — the boundary↔domain conversion recipe (the
  issue-tier `LinearIssueNodeModel` applies its 1-shape→N-domains accessors + normalizer split)
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
- `docs/learned/workflow/human-engagement-reads.md` — Linear's honest engagement-read mechanics
- `docs/learned/workflow/in-place-adoption.md` — the Linear project-backed adoption writer
- `docs/learned/toolchain/ty.md` — the narrowing-helper family for deep untyped payloads
