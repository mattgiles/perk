---
title: The IssueBackend seam — protocol, GitHub adapter, and the issue-tier consumer boundary
read_when: You are touching perk/issue_backend.py, perk/issues.py, an issue-tier consumer, adding a backend (Linear), or fighting the boundary/import-direction tests.
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

## Gotchas / residuals

- **Module-name shadowing**: `perk/issues.py` collides with natural local names (e.g. an `issues`
  list) — import as `from perk import issues as issues_mod` where needed.
- **`PlanState` default friction**: the protocol's `PlanState` has no `state` default while the
  gateway shape does — backends must always populate it; expect fixture friction at extraction
  time.
- **`resolve_issue_backend` returns GitHub unconditionally** until Node 1.3 (the `[issues]` config
  read, doctor check, and contracts amendment are deferred there by design).
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
- `docs/learned/toolchain/ty.md` — ty suppression syntax + enum strictness hit during this work
