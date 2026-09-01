---
title: The IssueBackend seam — protocol, GitHub adapter, and the issue-tier consumer boundary
read_when: You are changing issue-backend reads/writes, presence-only diagnostics, plan-kind guards, adapters/resolution, backend fakes, conformance, or import-direction tests.
cluster: backends-and-integrations
---

# The IssueBackend seam

Objective #252 nodes 1.1/1.2 carved the backend-neutral issue tier: `src/perk/backends/issue_backend.py`
(the protocol module — error type, frozen dataclasses, the `IssueBackend` Protocol + its `backend_id`
attribute) and the `GitHubIssueBackend` adapter (`src/perk/backends/github/backend.py`), which
delegates into the plan/issue substrate `src/perk/backends/github/plans.py`, + `resolve_issue_backend`
(`src/perk/backends/resolve.py`; adapter and resolver were originally one *perk/backends/issues.py*,
since carved into the `src/perk/backends/github/` package). Consumers reach the tier only through the
resolver, enforced by the substrate-import scan (`tests/test_resolve.py::TestConsumerBoundary`). This
doc preserves the patterns, enforcement, and residuals.

## Distillation

- The tier is a protocol MODULE: error type + frozen dataclasses + the `IssueBackend` Protocol,
  every consumer routed through the resolver — "Protocol-module shape".
- The GitHub adapter delegates late-bound to the same module functions the suite monkeypatches —
  "Late-bound delegation over a heavily-monkeypatched substrate".
- Plan/objective ids are OPAQUE backend-owned strings: parse-time validation rejects only
  empty/path-unsafe shapes; the backend is the authority on junk (loosening a validator forces a
  decision on every "rejects garbage" test) — "Opaque string ids: the backend is the authority
  on junk".
- `backend_id` is stamped verbatim onto `cache.plan-ref.provider`; stamp sites without a backend
  instance use the id resolver (pass-the-id-in, never config reads in pure modules) —
  "`backend_id` + the stamp discipline".
- Growing a Protocol signature — even with DEFAULTED params — ripples to two test sites (ty on
  the fake's conformance, pytest on kwarg-recorder equality) — "Growing a protocol signature".
- The invariants any new backend must keep (not-found substrings, numeric-id edge tags,
  mixed-tier except tuples) — "Cross-backend contracts to preserve".
- Issue kind and payload health are separate axes; presence-only flags are computed at the backend
  read boundary without decoding a plan — "Presence-only evidence and guarded writers".
- Diagnostics choose the weakest read carrying the evidence, while invariant writes are enforced
  by the backend and explained by the door — "Presence-only evidence and guarded writers".
- Default-miss fakes hide redirect/targeting mistakes; map every plausible target to a distinct
  value or exception and keep whole-repo consumer censuses — "Backend fake posture".

## Protocol-module shape

`src/perk/run/runner.py` is the in-repo template for a contract module: module docstring + error type +
frozen dataclasses + a plain `Protocol`, all in one module. `src/perk/backends/issue_backend.py` followed it;
future contract modules should too.

- **Static conformance via one annotated binding per implementation**: a function returning the
  protocol type with the concrete instance bound to a protocol-annotated local makes ty fail CI on
  any implementation↔protocol drift. No `@runtime_checkable`, no isinstance — one annotated
  binding per backend is the whole conformance suite. The current bindings are
  `tests/test_issue_backend.py::_make_backend` (`_FakeBackend`),
  `tests/test_github_backend.py::_make_backend` (`GitHubIssueBackend`), and `tests/_linear_fakes.py`
  (`LinearIssueBackend`) — together with the protocol module itself, they own the census of what
  the Protocol carries; this doc deliberately restates no method count.
- **Extraction-style plans should carry an explicit rename table** (old gateway name → protocol
  name, parameter re-typings, finder splits) — that level of specificity made nodes 1.1/1.2
  mechanical.

## Late-bound delegation over a heavily-monkeypatched substrate

`GitHubIssueBackend` resolves every delegate via **attribute access on the `plans` module object
(`perk.backends.github.plans`) at call time**, so the suite's `monkeypatch.setattr(plans, ...)`
fixtures keep intercepting unchanged — even patches applied *after* backend construction, pinned by
`tests/test_github_backend.py::TestLateBinding::test_patch_after_construction_still_intercepts`.
Refactoring the adapter to bound-method references would **silently break the entire suite's
fixtures**.

The physical move happened: the issue-tier function bodies live in
`src/perk/backends/github/plans.py` (the GitHub backend's private substrate), and the late-binding
guarantee moved with them.

## Two-shape fixture rule after a seam re-type

- Tests feeding **monkeypatched gateway fakes** return the *native* gateway shape (the substrate
  dataclasses in `src/perk/backends/github/plans.py`) — the adapter does the conversion, never the fake.
- Tests of **consumer-internal pure logic** construct the *neutral* protocol shape directly.

`tests/test_resume.py` has the paired-helper precedent (a native-state helper alongside a
neutral-state helper).

## Boundary + import-direction enforcement

- **Substrate-import boundary test**
  (`tests/test_resolve.py::TestConsumerBoundary::test_no_production_module_imports_the_substrate_directly`):
  an **import** scan, not a per-function-call scan — no module under `src/perk/` outside the
  `src/perk/backends/github/` package may import the substrate modules (`SUBSTRATE_MODULES` =
  `perk.backends.github.plans` + `perk.backends.github.objectives`). Production reaches
  issue/objective ops through `resolve.resolve_issue_backend` / `resolve.resolve_objective_store`;
  one test covers **both** tiers.
  - **No allowlist special-case remains**: `GitHubObjectiveStore.close_objective` legitimately
    calls `plans.close_issue` directly (a GitHub objective IS an issue), and it does so from
    *inside* the allowed package — the whole backend package is the allowed set (see
    `objective-store.md`).
- **The import-direction guards are *substring* assertions over raw source text**
  (`tests/test_issue_backend.py::TestImportDirection`), so they bite docstrings and comments too:
  `src/perk/github/` source must not contain `issue_backend`, a dotted `perk.backends` path, or
  `perk.delivery` — slash-form prose references are the sanctioned phrasing, per the test's own
  comment. Phrase around the forbidden spellings ("the issue-backend adapter") or loosen the
  guard to import-statement scanning.

## Cross-backend contracts to preserve

- **Error translation keeps `str(exc)` verbatim**, and at least one consumer maps `"not found"`
  message substrings to a typed error — any future backend (Linear) must keep not-found messages
  containing that substring or the mapping breaks.
- **Numeric-id edges are tagged and greppable**: every `--json` field that must stay a number
  converts at the serialization edge under the literal comment tag
  `# GitHub-numeric id assumption — re-shape when Linear lands (#252 Phase 2/3)`. Grep that tag to
  find every envelope edge Phase 2/3 must re-shape.
- **Mixed-tier `try` blocks** (one `try` spanning issue-tier + PR/CI-tier calls) use
  `except (GitHubError, IssueBackendError)` tuples — keep the tuples until the tiers fully
  separate.

## Opaque string ids: the backend is the authority on junk

Plan/objective ids are opaque backend-owned strings. Parse-time validation rejects **only**
empty/path-unsafe shapes (`/`, `.`, `..`); formerly-rejected inputs (`not-a-number`, `#abc`) are
now *valid* opaque ids that the **backend** rejects (GitHub's number-conversion edge raises
`github_error`). When loosening a validator, expect **every "rejects garbage" negative test to
need an explicit decision**: re-point at genuinely-invalid input (`bad/id`, booleans) or re-purpose
to assert the new contract (e.g. the supervisor's malformed-`pr`-backlink case no longer silently
degrades to `plan_required`).

### Sweep ALL id consumers, not just decoders

The relaxation's blast radius reached beyond the planned decoder list: the warm objective tools
(the objective-planning tools' formerly number-typed params, the `/objective-reconcile` `\d+` arg parser),
`workflow run list`'s `isdigit()` PR-overlay gate, and `launch.py`'s checkpoint gate — which ALSO
had a `provider != "github"` early-return that skipped Linear; both gates had to go. **Grep for
`isdigit` / `\d+` / number-typed params when widening an id type.** The string-or-number tool-param
shape lives in `extension/substrate/toolParams.ts` (`idParam`/`idArrayParam` — see
`pi/tool-param-decode.md`).

### URL-peeling in the shared id parser (the single chokepoint)

`src/perk/cli/plan_selection.py::parse_plan_id` is the **single chokepoint** every plan/objective
id-taking command routes through: `perk implement`, `perk plan resume`/`replan`/`from`, and all
`perk objective` verbs (via the thin `parse_objective_id` alias in
`src/perk/cli/commands/objective/shared.py`). So a
pure-function change there gained all ~15 commands the URL-acceptance feature **uniformly** — the
payoff of one shared opaque-id parser.

Durable design decisions:

- **Scheme-gate-first ordering.** Consult the URL helper (the module-level pure `_id_from_url`)
  only when the input's scheme is `http`/`https`, so a bare id stays **byte-for-byte unchanged**.
  This is the key to a zero-regression *additive* parser.
- **Key on path SHAPE, not host string.** `/issues/<digits>` transparently covers GitHub
  Enterprise with **no host allowlist**; Linear is `/issue/IDENT` and `/project/SLUG`.
- **`/pull/N` is deliberately REJECTED.** A PR number is a *different object* than the plan-issue —
  silently resolving it would be a wrong-object footgun. Reject it with an `invalid_input` URL
  message.
  *(Since narrowed: the rejection now lives only in this pure parser tier — direct
  `parse_plan_id` callers such as `plan replan`/`watch`/`from` and objective ids keep it —
  while `select_plan` (the network-side seam behind `implement`/`address`/`ready`/`plan
  resume`) accepts PR selectors (`pr_number_from_url` + a digits fallback) and resolves them
  to the plan, guarded by corroboration against the plan's own recorded `plan-header.pr`. The
  wrong-object footgun stays closed: resolution is never silent — the head branch is only a
  candidate, and a non-corroborating PR refuses typed.)*
- **The peeled id stays OPAQUE past the parser.** No backend-host validation: a GitHub URL pasted
  into a Linear repo extracts a token that the configured backend then fails with the normal
  not-found error. This keeps the parser pure / backend-agnostic and usable *before* backend
  resolution. (Linear project URLs resolve because `project(id:)` accepts the slug.)

Testing recipe: a pure unit module exercises the parser directly (the right tier for a pure string
fn); the resume integration test monkeypatches `resolve.resolve_issue_backend` to a tiny fake,
because the GitHub backend's `get_plan` does `int(issue_id)` and can't take a Linear-shaped id.

This is **Python-plane only** — no `shared/contracts.md` change. Warm doors operate on ids already
in `cache.plan-ref`, never a user-pasted URL. (The TS `idParam`/`idArrayParam` opaque-id shape lives
in `pi/tool-param-decode.md`, already cross-referenced below.)

## Per-backend land closure

GitHub keeps `Closes #N` in the squash body byte-identically; non-github backends get a
`Plan: <id> — <url>` line plus an explicit fail-open `close_issue` (surfaced as the
`plan_issue_closed` envelope field). **Branch on `backend_id`, never on id shape.** Known gap:
`extension/pi/v1/delivery/land.ts` ignores `plan_issue_closed`, so the warm `/land` message doesn't mention the
explicit close under Linear. Also: the GitHub envelope renames (`issue.number`→`issue.id` etc.)
are **deliberately breaking** for external `perk … --json` consumers; contracts §8.21 is the
canonical record.

## `backend_id` + the stamp discipline

- **Adding a member to a `Protocol` breaks every fake, not just the real adapter.** `backend_id:
  str` on `IssueBackend` failed ty on the test suite's `_FakeBackend`, not only the planned
  `GitHubIssueBackend` conformance helper. The ty-checked `backend: IssueBackend = <impl>`
  annotated-binding pattern in tests is what catches this — keep one per fake/impl.
- **The stamp discipline**: `cache.plan-ref.provider` := the resolved backend's `backend_id`,
  stamped verbatim. `reconstruct_plan_ref` stays pure (provider passed in, no config read in
  `resume.py`). Stamp sites that hold no backend instance use
  `resolve.resolve_issue_backend_id(repo_root)` — that id resolver exists precisely so stamping
  needn't construct a backend. Future stamp sites follow the pass-the-id-in pattern rather than
  reading config deep in pure modules.

## Required-kwarg-first as a caller census

When a plan says "add a required keyword," treat its named call sites as a **floor** — grep all
callers. The `[issues]` plan named only one `reconstruct_plan_ref` caller as needing
`provider=backend.backend_id`; the function had **four** production callers (`resume_cmd.py`,
`implement_cmd.py`, `run_worker.py`, `objective/run_cmd.py::_dispatch_stage_remote`). Making the
kwarg required is what surfaced them loudly — the type checker/test suite forces completeness.

## Growing a protocol signature — even DEFAULTED params ripple to two test sites

Adding two **defaulted** params (`decision` / `target`) to the `create_learn_issue` **protocol** broke
two structurally-different test sites, each caught by a **different** gate:

- **ty (not pytest):** a conformant fake stopped conforming to the protocol → `invalid-assignment` at
  the annotated binding. **Defaulted params don't make a fake conformant — the fake's signature must
  grow too.** Surfaces ONLY under `ty check`, never at runtime or in pytest.
- **pytest:** a kwarg-**recorder** delegation test does an exact-dict equality on captured kwargs, so
  the two new kwargs (`decision: None, target: None`) must be added to the expected dict.

**Census rule when growing an issue-backend protocol signature:** update (a) every conformant fake's
signature AND (b) every kwarg-recorder exact-dict assertion. `grep "def create_learn_issue"` finds the
fakes; only `ty check tests perk` + full pytest **together** catch both arms. Cross-reference
`learn-evidence-pipeline.md` for the feature that triggered this.

## Doctor arm-mapping over a collapsed error type

The resolver deliberately collapses `tomllib.TOMLDecodeError` into `IssueBackendError` (consumers
need one error type), which erases the malformed-TOML vs bad-selection distinction doctor needs
(warn-defer vs fail). The landed shape: `_issues_check` (now in
`src/perk/convergence/doctor/checks.py`) calls `load_committed_issues_backend`
first to catch `TOMLDecodeError` (→ warn, defer to the config check), then calls the resolver and
maps its outcomes by the **returned backend id**: absent/`github` → ok; `linear` with a committed
team → ok; `linear` without a team → fail; an unknown selection → fail via the resolver's raise.
The check maps resolver outcomes and never duplicates the vocabulary (its docstring's own rule).
If arms multiply, give `IssueBackendError` a structured kind instead.

## Opaque backend-owned header ids

`objective_comment_id` is `int | str | None` (GitHub numeric, Linear string UUID). Read sites
accept `str | int` and `str()` it before use; consumers must never interpret it. The remaining CLI
envelope `int(...)` coercions stay tagged `# GitHub-numeric id assumption` (the grep tag below).

## Selection-managed package entries are two-directional

`_converge_linear_package` is the second instance of the `_converge_provider_packages` shape: an
identity-matched settings entry is *removed* when the selection is absent — hand-adding the
package without selecting it is explicitly unsupported. Composing it inside `_converge_settings`
keeps it under the `settings-wiring` SSOT (doctor dry-runs/fixes it with zero new
checks/capabilities).

## Presence-only evidence and guarded writers

Issue kind and payload health are independent evidence axes. Positive identification uses stored
presence-only flags computed at the backend read boundary. It must not decode the payload or ask a
consumer to inspect body text: on Linear, kind headers can ride attachments that a body read never
sees. Keying a recovery or repair refusal on decoded-header truthiness locks the door precisely when
a damaged payload makes recovery necessary.

Enforce write invariants at the backend mutation boundary through its typed error channel. A door
may preflight the same rule to provide a friendlier typed refusal, but it does not replace writer
enforcement. The read-then-PATCH race remains inherent on non-transactional backends; document it
rather than implying the UX preflight is a lock.

Read tolerance can turn a fail-early path into a fail-late path after side effects. Before loosening
any read, trace the next write and ask what can already have changed when it fails. Tolerance belongs
in deliberately presence-only reads, never in plan reconstruction.

Diagnostics use the weakest read that carries their evidence. Prefer `read_issue` for stored marker
presence over `get_plan`, and resolve the actual carrier through contracts §8.43
`journal_carrier_id` before reading. A generic writer that becomes merge-only will also break tests
that quietly used it as a creator; reseed those fixtures through the sanctioned creation seam
instead of reopening create behavior.

## Backend fake posture

A fake whose unmapped input returns a benign miss hides wrong-target and stale-redirect bugs. Wire
every plausible target with distinguishable results so a mistargeted read fails loudly. Grow the
same map additively for error cases by allowing an exception-valued entry to raise; do not add a
second special-case fake path. As with protocol changes elsewhere in this doc, a whole-repo census
of consumers and conforming fakes is stronger than an enumerated fixture-fallout list.

## Gotchas / residuals

- **Module-name shadowing**: the pre-carve *perk/backends/issues.py* collided with natural local names
  (e.g. an `issues` list), forcing `from perk import issues as issues_mod` imports — the carve into
  `src/perk/backends/github/` + `src/perk/backends/resolve.py` dissolved it; avoid module names that
  collide with natural locals when adding backend modules.
- **`PlanState` default friction**: the protocol's `PlanState` has no `state` default while the
  gateway shape does — backends must always populate it; expect fixture friction at extraction
  time.
- **`resolve_issue_backend`'s Linear constructing arm landed** — config-driven selection is live;
  the Linear arm requires a committed `[issues] team` + the `LINEAR_API_KEY` env var (either
  missing raises a hinted `IssueBackendError`). The one remaining final `raise` is a defensive
  known-id-without-implementation arm, unreachable today — keep it, don't "clean it up".
- `error_type="github_error"` for `IssueBackendError` at CLI boundaries is still GitHub-named (the
  rename was explicitly deferred).
- **The protocol's docstring contracts** (normalized `"OPEN"/"CLOSED"` states, string ids, the
  error-mapping discipline) are only enforced for backends covered by an annotated binding —
  drift is possible for anything outside that net.
- **`_FakeBackend` intentionally skips legacy paths** (the parse-roadmap-from-body path, the
  header-merge semantics) — growing it into a behavioral fake is Node 4.1's job, not assumed done.
- **The adapter's numeric-id error message differs** from the old raw `ValueError` paths on
  fail-open edges — untested but safe (all such sites are fail-open `except Exception`).

## Growing a read contract across TWO conformance-checked protocols at once (#687)

Adding the three engagement reads to **both** `IssueBackend` (issue-keyed) and `ObjectiveStore`
(objective-keyed) at once forced conformance across **7 sites**: 5 production implementers + 2 test
fakes. The dormant `LinearObjectiveStore` and both fakes are the **easy misses** — census all 7 up
front (whole-repo `ty check` is the oracle). (See `human-engagement-reads.md` for the full
subsystem story.)

## github-native rows → adapter mapping; the import-direction docstring trap (#690)

The honest engagement substrate is `src/perk/backends/github/engagement.py`: it returns
**github-native rows** (`IssueCommentRow` / `DescriptionEditRow`, carrying raw author fields) and
imports only the downward `perk.github._exec` transport; the **adapter**
(`src/perk/backends/github/backend.py`) maps them to the neutral `engagement.*` contract via
`classify_author` (`src/perk/backends/engagement.py`). The gateway never imports the backend tier —
and the import-direction guard (`tests/test_issue_backend.py::TestImportDirection`) is a **raw
source-string scan over the whole `src/perk/github/` package**, so even a **docstring** that
mentions the backend-tier module path trips it. Keep gateway prose free of the literal module path
(say "the issue-backend adapter").

## `read_issue` — the third issue-read shape (#708)

Beside `get_plan` / `get_plan_body`, `read_issue(*, issue_id) -> AdoptableIssue | None` reads a
*non-perk* issue's raw title+body+state (state normalized to `OPEN | CLOSED` at the adapter). It
exists because neither sibling can read a raw human issue. (See `in-place-adoption.md`.)

## Cross-references

- `src/perk/backends/issue_backend.py` — the protocol module
- `src/perk/backends/github/backend.py` — `GitHubIssueBackend`; `src/perk/backends/resolve.py` —
  `resolve_issue_backend`, `resolve_issue_backend_id`
- `src/perk/backends/github/plans.py` — the plan/issue substrate the adapter delegates into
- `src/perk/github/` — the gh transport gateway whose `_exec` helper family the substrate rides
- `tests/test_issue_backend.py`, `tests/test_github_backend.py`, `tests/test_resolve.py` —
  conformance/import-direction, delegation/late-binding, and resolver/boundary tests
- `docs/learned/workflow/github-gateway.md` — the gh transport/PR-tier gateway package
- `docs/learned/workflow/linear-backend.md` — the Linear backend's client, dual-encoding markers,
  readiness wiring, and prompt rendering
- `docs/learned/workflow/objective-store.md` — the parallel objective-storage tier split off the
  same monolith
- `docs/learned/workflow/human-engagement-reads.md` — the engagement read contract across both tiers
- `docs/learned/workflow/in-place-adoption.md` — `read_issue` and the adoption writers
- `docs/learned/toolchain/ty.md` — ty suppression syntax + enum strictness hit during this work
