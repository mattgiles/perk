---
title: Narrowing broad exception catches — latent-bug exposure, census incompleteness, typed-catch derivation
read_when: You are deriving catches at parser/adapter trust boundaries, widening user input, designing degrade-and-continue or cleanup catches, or guarding path containment.
cluster: quality-and-guards
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
- **A guard that silently fail-closes crash repair is itself the targeted failure mode.** A
  corroboration read on a repair path must not swallow its store error into bare `False`: that
  makes a transient backend failure indistinguishable from a clean no-evidence exit and silently
  skips the repair. Error boundaries must report, never silently erase, this distinction. The
  recovery evidence probe in `src/perk/delivery/recover.py` degrades with a loud skip note that
  tells the operator to rerun recover.

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

The N-consumer variant: **when a boundary helper is consumed by N commands, do the
exception-translation census at the helper**, mapping every documented failure of the underlying
reads to `UserFacingCliError` — per-consumer catch sets drift immediately. Instance: the
stacked-selection seam (`src/perk/cli/commands/objective/shared.py`) initially caught only the
reconstruction error while two sibling documented failures escaped as tracebacks through all
three consumers, each with a different partial catch set.

## Declared fail-open ("never raises") contracts need adversarial-fixture sweeps

A declared "never raises" contract is verified boundary-by-boundary with adversarial fixtures —
every filesystem call gets a paired fixture: `chmod 0o000` (+ skip-under-root) for the
permission arms; a *directory* named like the expected file for the open-raises arm; corrupt
bytes after a valid header for the decode arm. Sub-rules, each with its instance from the
perk-dev audit census (`packages/perk-dev/src/perk_dev/audit/corpus.py`):

- **Two readers of one file with different decode leniency is a trap.** A lenient header-confirm
  followed by a strict full parse turns a damaged historical file into a whole-run abort — catch
  the stricter reader's failure at the read edge and use the resulting sentinel downstream
  (header-confirmed but parse-empty ⇒ account it unreadable, never confirmed-empty).
- **Guard exotic stdlib arms reachable from untrusted/scanned text**, not just format-mismatch
  `ValueError`: `int()` raises past CPython's ~4300-digit conversion cap;
  `datetime.astimezone()` raises `OverflowError` on valid-but-extreme aware timestamps — put the
  conversion *inside* the try. Micro-fact: date **subtraction** never overflows, unlike
  date ± timedelta near the date range bounds.

## A "degrade, never raise" invariant is only as strong as its enumerated exception set

The flip side of narrowing: when an *invariant* guards a boundary (e.g. "a verified merge never
error-exits over bookkeeping"), the narrowed catch set must be audited against the **full**
expected-failure set at that boundary, not just the failures the author remembered — one
unenumerated exception type turns the promised degrade into a raise exactly where the invariant
mattered. Auditing the invariant means deriving the set from the try-block's operations (the rule
above), then checking it against the boundary's *promise*.

## Widening a trust boundary reopens exception posture

When an endpoint starts feeding user-supplied text into an existing parser, re-derive the catch at
that parser boundary. A previously settled tuple may cover only the old trusted inputs. Start from
the library's full error taxonomy, and catch the documented base class when variants are not a
stable subclass family. If some variants omit fields used in diagnostics, read them through a safe
fallback rather than narrowing the catch to the convenient variant.

The right width is taxonomy-driven: neither reflexively `Exception` nor the narrowest error seen in
one fixture. Pair malformed-input cases with the new endpoint so the widened boundary cannot regress
back to raw tracebacks.

## Sanctioned broad catches are policy boundaries

### Atomic-write cleanup

An atomic-write helper's cleanup boundary is wider than `OSError`. A caller-supplied

`encoding` can raise `LookupError`/`UnicodeEncodeError` *after* temp-file allocation, and cleanup
itself (`rmSync`/`unlink`) can throw and **mask the original error**. The shipped shape (anchors:
`src/perk/state/cache.py`, `extension/substrate/cache.ts`): the entire post-allocation region
catches everything (`BaseException` on the Python plane) → best-effort cleanup inside its own
suppressed try → bare `raise`. A deliberate broad catch is correct when it exists **only** to
remove temp state and always re-raises — the named exception to the narrow-typed-catch rule.

### Degrade-and-continue browser opening

A second sanctioned shape is an explicitly marked degrade-and-continue boundary where every
failure has the same policy. Browser opener backends can raise arbitrary platform-specific types;
if opening is optional, catch broadly, report the refusal/degrade, and continue. This is not error
swallowing: the boundary is named, the outcome is observable, and no failure variant would change
the caller's decision.

## Whole-chain containment for URL-derived paths

A URL-derived path can contain an embedded NUL, making `Path.resolve()` raise `ValueError` rather
than `OSError`. Put the entire containment chain inside one refusal boundary: resolve the candidate
and allowed root, check relativity/containment, confirm a file, and read it. Wrapping only the final
read leaves earlier adversarial-path failures as raw exceptions. `perk_dev/prose_review/web.py` is
the reference boundary. Degrade every failure in that chain to the same contained-read refusal;
never continue with a partially checked path.

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
