---
title: Narrowing broad exception catches — latent-bug exposure, census incompleteness, typed-catch derivation
read_when: You are narrowing broad exception catches (`except Exception`) to typed expected failures, choosing a typed catch set for a fail-open boundary, or planning an exception-posture sweep.
---

# Narrowing broad exception catches

Craft from narrowing 16 `except Exception` fail-open boundaries in the Python plane to typed
expected failures. The narrowed posture itself (fail-open covers expected infra failures, not bugs;
programming errors propagate) lives in `shared/contracts.md` prose and the propagation-pin tests —
this doc carries the *sweep craft*: what a planner of a similar sweep should expect and how to
derive each typed set.

## Plan for latent-bug exposure

A narrowing sweep should **EXPECT to surface test bugs the old catches swallowed** — budget an
explicit "fix the latent test bugs the narrowing exposes" step rather than assuming existing tests
pass unchanged. Two classes observed:

- **Incomplete test fakes**: a store fake missing `get_objective` whose `AttributeError` had been
  silently swallowed by a broad catch in `_resolve_plan_base`; narrowing made it fail honestly —
  fixed by completing the fake (return `None`, like its siblings).
- **Incomplete subprocess mocks**: a `SimpleNamespace(returncode=0)` fake with no `stdout` only
  worked because a broad catch ate the resulting `AttributeError` deep in a gh JSON parse — fixed
  by no-opping the reporters like every sibling test in the file.

These are **positive findings** — they validate the sweep's premise (broad catches hide bugs).

## A grep census of exception-behavior sites is incomplete by construction

The plan's grep census found 3 emitter fakes to retype; the full CI run found a 4th. **The
full-suite failure list is the real census** — re-verify any grep census of exception-*behavior*
sites against a full CI run, don't trust it.

## Derive the typed set from the try-block's operations

Never copy a catch tuple mechanically — enumerate what the try-block actually does:

- **Fail-open + filesystem I/O ⇒ tuple catch** `(IssueBackendError, OSError)` — anchors:
  `perk/backends/linear/agent.py` (writing `agent-session.json`), `perk/run/run_report.py`
  (appending `GITHUB_STEP_SUMMARY`).
- **Pure-backend-call siblings** catch the domain error alone.

## Payload-parse failures are backend errors

A malformed external-API payload raises `IssueBackendError`/`ObjectiveStoreError` — the
adapter/client is the error-translation boundary — not `ValueError`. The `linear/client.py`
precedent is canonical; `_parse_created_session` was retyped to match it.

## Cross-references

- `shared/contracts.md` — the fail-open formulation (expected infra failures, not bugs) + the
  propagation-pin tests that enforce it
- `docs/learned/workflow/objective-store.md` — `ObjectiveStoreError` is NOT a subclass of
  `IssueBackendError` (the not-a-subclass fact lives there)
- `docs/learned/workflow/issue-backend.md` — the backend error taxonomy the typed sets draw from
