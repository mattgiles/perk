---
title: Narrowing broad exception catches — latent-bug exposure, census incompleteness, typed-catch derivation
read_when: You are narrowing broad `except Exception` catches to typed expected failures, choosing a typed catch set for a fail-open boundary, or planning an exception-posture sweep.
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
- **A fail-open catch that substitutes an empty value is only safe when the consumer is
  additive** — feeding it to a remove-capable reconciler converts a read failure into deletion
  (the full instance — the unreadable-config NO-OP posture — lives in `init-doctor.md`).

## Mixed-failure-mode helpers need the full per-arm catch set at translation boundaries

The inverse trap of copying a catch tuple too broadly is enumerating it too narrowly: a helper
with a **subprocess primary and a filesystem fallback** raises both failure modes, and a `--json`
boundary translating only the primary lets the fallback arm escape as a raw traceback (no envelope,
no stable exit code). The realized shape: `remove_review_worktree`
(`src/perk/cli/commands/pr/review/shared.py`) tries `git worktree remove` and falls back to
`shutil.rmtree` — so it raises `GitError` **and** `OSError`; the plan pinned `GitError`-only
translation and the rmtree arm's escape was caught by PR review, not planning.

**Rule:** when pinning per-arm error translation at a boundary, enumerate every failure mode of
the **helper being wrapped**, not just its primary subprocess — and pin envelope tests per arm.
The realized catch sites: `checkout_cmd.py` / `cleanup_cmd.py` in
`src/perk/cli/commands/pr/review/` — `except (GitError, OSError)` →
`UserFacingCliError(error_type="git_error")`.

## The sanctioned broad catch: an atomic-write helper's cleanup boundary

**An atomic-write helper's cleanup boundary is wider than `OSError`.** A caller-supplied
`encoding` can raise `LookupError`/`UnicodeEncodeError` *after* temp-file allocation, and cleanup
itself (`rmSync`/`unlink`) can throw and **mask the original error**. The shipped shape (anchors:
`src/perk/state/cache.py`, `extension/substrate/cache.ts`): the entire post-allocation region
catches everything (`BaseException` on the Python plane) → best-effort cleanup inside its own
suppressed try → bare `raise`. A deliberate broad catch is correct when it exists **only** to
remove temp state and always re-raises — the named exception to the narrow-typed-catch rule.

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
