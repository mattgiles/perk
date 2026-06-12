---
title: The IssueBackend seam — protocol, GitHub adapter, and the issue-tier consumer boundary
read_when: You are touching perk/issue_backend.py, perk/issues.py, an issue-tier consumer, adding a backend, the backend_id stamp discipline, opaque backend-owned ids, the doctor issues check, or fighting the boundary/import-direction tests.
---

# The IssueBackend seam

Objective #252 nodes 1.1/1.2 carved the backend-neutral issue tier: `perk/issue_backend.py` (the
protocol module — error type, frozen dataclasses, the 21-method `IssueBackend` Protocol) and
`perk/issues.py` (the `GitHubIssueBackend` adapter + `resolve_issue_backend`). All 21 issue-tier
consumers route through the resolver. This doc preserves the patterns, enforcement, and residuals.

## Protocol-module shape

`perk/runner.py` is the in-repo template for a contract module: module docstring + error type +
frozen dataclasses + a plain `Protocol`, all in one module. `perk/issue_backend.py` followed it;
future contract modules should too.

- **Static conformance via one annotated binding per implementation**: a function returning the
  protocol type with the concrete instance bound to a protocol-annotated local makes ty fail CI on
  any implementation↔protocol drift. No `@runtime_checkable`, no isinstance — one annotated
  binding per backend is the whole conformance suite.
- **Extraction-style plans should carry an explicit rename table** (old gateway name → protocol
  name, parameter re-typings, finder splits) — that level of specificity made nodes 1.1/1.2
  mechanical.

## Late-bound delegation over a heavily-monkeypatched substrate

`GitHubIssueBackend` resolves every delegate via **attribute access on the `github` module object
at call time**, so the ~94 existing `monkeypatch.setattr(github, ...)` fixtures keep intercepting
unchanged — even patches applied *after* backend construction. A dedicated late-binding test
(`tests/test_issues.py`) pins this guarantee; refactoring the adapter to bound-method references
would **silently break the entire suite's fixtures**.

The issue-tier function bodies deliberately remain in `github.py` as the backend's private
substrate. A physical move stays possible but is only worth the fixture churn once a second
backend exists and the fixtures migrate to a Fake backend (Node 4.1).

## Two-shape fixture rule after a seam re-type

- Tests feeding **monkeypatched gateway fakes** return the *native* gateway shape (the `github.py`
  dataclasses) — the adapter does the conversion, never the fake.
- Tests of **consumer-internal pure logic** construct the *neutral* protocol shape directly.

`tests/test_resume.py` has the paired-helper precedent (a native-state helper alongside a
neutral-state helper).

## Boundary + import-direction enforcement

- **Source-scan boundary test** (`tests/test_issues.py`): no module under `perk/` except
  `perk/issues.py` and `perk/github.py` may call the 21 issue-tier gateway functions. New
  production code reaches the issue tier via the resolver in `perk/issues.py`.
- **The import-direction guards are *substring* assertions over file text**, so they bite
  docstrings and comments too: `perk/github.py` prose cannot even *mention* the resolver's name or
  the protocol module's name. Phrase around it ("the resolver in the issues module") or loosen the
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

## `backend_id` + the stamp discipline

- **Adding a member to a `Protocol` breaks every fake, not just the real adapter.** `backend_id:
  str` on `IssueBackend` failed ty on the test suite's `_FakeBackend`, not only the planned
  `GitHubIssueBackend` conformance helper. The ty-checked `backend: IssueBackend = <impl>`
  annotated-binding pattern in tests is what catches this — keep one per fake/impl.
- **The stamp discipline**: `cache.plan-ref.provider` := the resolved backend's `backend_id`,
  stamped verbatim. `reconstruct_plan_ref` stays pure (provider passed in, no config read in
  `resume.py`). Stamp sites that hold no backend instance use
  `issues.resolve_issue_backend_id(repo_root)` — that id resolver exists precisely so stamping
  needn't construct a backend. Future stamp sites follow the pass-the-id-in pattern rather than
  reading config deep in pure modules.

## Required-kwarg-first as a caller census

When a plan says "add a required keyword," treat its named call sites as a **floor** — grep all
callers. The `[issues]` plan named only one `reconstruct_plan_ref` caller as needing
`provider=backend.backend_id`; the function had **four** production callers (`resume_cmd.py`,
`implement_cmd.py`, `run_worker.py`, `objective/run_cmd.py::_dispatch_stage_remote`). Making the
kwarg required is what surfaced them loudly — the type checker/test suite forces completeness.

## Doctor arm-mapping over a collapsed error type

The resolver deliberately collapses `tomllib.TOMLDecodeError` into `IssueBackendError` (consumers
need one error type), which erases the malformed-TOML vs bad-selection distinction doctor needs
(warn-defer vs fail). The landed shape: `_issues_check` calls `load_committed_issues_backend`
first to catch `TOMLDecodeError` (→ warn, defer to the config check), then calls the resolver and
maps its `IssueBackendError` arms. **Known substring coupling**: the linear-vs-unknown split
matches `"not yet supported"` in the resolver's error text — rewording it silently degrades the
tailored remediation (still `fail`, so not dangerous). If a third arm ever appears, give
`IssueBackendError` a structured kind instead.

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

## Gotchas / residuals

- **Module-name shadowing**: `perk/issues.py` collides with natural local names (e.g. an `issues`
  list) — import as `from perk import issues as issues_mod` where needed.
- **`PlanState` default friction**: the protocol's `PlanState` has no `state` default while the
  gateway shape does — backends must always populate it; expect fixture friction at extraction
  time.
- **`resolve_issue_backend`'s non-github `raise` arms are placeholders, not dead code** — each is
  replaced when that backend's constructing arm lands; don't "clean them up".
- `error_type="github_error"` for `IssueBackendError` at CLI boundaries is still GitHub-named (the
  rename was explicitly deferred).
- **The protocol's docstring contracts** (normalized `"OPEN"/"CLOSED"` states, string ids, the
  error-mapping discipline) are only enforced for backends covered by an annotated binding —
  drift is possible for anything outside that net.
- **`_FakeBackend` intentionally skips legacy paths** (the parse-roadmap-from-body path, the
  header-merge semantics) — growing it into a behavioral fake is Node 4.1's job, not assumed done.
- **The adapter's numeric-id error message differs** from the old raw `ValueError` paths on
  fail-open edges — untested but safe (all such sites are fail-open `except Exception`).

## Cross-references

- `perk/issue_backend.py` — the protocol module
- `perk/issues.py` — `GitHubIssueBackend`, `resolve_issue_backend`
- `perk/github.py` — the private substrate the adapter delegates into
- `tests/test_issue_backend.py`, `tests/test_issues.py` — conformance, late-binding, boundary, and
  import-direction tests
- `docs/learned/workflow/github-gateway.md` — the gateway the substrate lives in
- `docs/learned/workflow/linear-backend.md` — the Linear backend's client, dual-encoding markers,
  readiness wiring, and prompt rendering
- `docs/learned/toolchain/ty.md` — ty suppression syntax + enum strictness hit during this work
