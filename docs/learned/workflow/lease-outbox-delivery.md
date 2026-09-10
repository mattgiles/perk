---
title: Lease-fenced outboxes, exclusion primitives & observation-acked delivery
read_when: You are touching extension/hunkFeedback/, designing a file-lease/lock protocol or an outbox-ack bridge, choosing between resolverLease and worktreeResolverLock, or reviewing check-then-act.
cluster: quality-and-guards
---

# Lease-fenced outboxes & observation-acked delivery

The hunk feedback bridge delivers saved Hunk watch notes from a CLI-side outbox into the live
implement session as injected messages. Anchors: `extension/hunkFeedback/` — `store.ts` (the
appenders + lease protocol), `inbox.ts` (the lease-holding inbox consumer), `receiver.ts`,
`perkFeedback.ts` — plus the watch CLI `src/perk/cli/commands/plan/watch_cmd.py`. The durable
knowledge is the protocol shapes and their traps, which generalize to any CLI↔session bridge
built on files.

## Lease protocol traps

- **The check-then-act trap:** stale-lease judgment → quarantine rename is check-then-act — a
  competing reclaimer can complete a FULL reclaim inside that window, so the "stale" dir you
  rename can be a **fresh successor lease**. Fix shape: post-rename freshness re-check →
  restore → go passive.
- **Directory-identity (inode) fencing:** renew/release on a replaceable lock dir need identity
  fencing on top of token checks; design residual windows to degrade **fail-closed on both
  sides** — never two live consumers, never misdelivery.
- **"We own it" is not a fence.** Ownership is proven per acquisition: mint a per-acquisition
  ownership token into the lease record, and release token-fenced — quarantine-rename the lock
  dir, verify the token in the moved state, then delete (or restore on mismatch). A process's
  memory of having acquired is not evidence at release time.
- **The post-rename re-check re-judges the FULL non-reclaimability predicate** against the
  *moved* state — grace window included — and restores any claim that changed since the original
  judgment; re-checking only the field that triggered the reclaim re-opens the race.
- **Lease fs catches need three-way classification:** a missing/malformed lease is DATA (it
  routes to the reclaim rules); expected race codes (ENOENT/EEXIST) are contention; everything
  else propagates to a typed io_error arm — a blanket catch turns real I/O failures into
  phantom contention.

The realized second instance: the `/objective-sync` resolver-dispatch lease (PR #2075) —
`extension/substrate/resolverLease.ts`.

## Which exclusion primitive — a decision table

perk now carries three machine-local exclusion shapes; pick by what a stale holder should force:

| Primitive | Where | Reclaim on staleness | Same-session reacquire | Use when |
|---|---|---|---|---|
| The hunk lease | `extension/hunkFeedback/store.ts` | quarantine-rename reclaim, inode fencing, grace window | via reclaim rules | a long-lived consumer role that must fail over |
| The resolver lease (a session **claim**) | `extension/substrate/resolverLease.ts` | dead-PID reclamation via a reclaimability predicate | yes (same PID) | a retry inside the same session must reacquire |
| The worktree resolver lock | `extension/substrate/worktreeResolverLock.ts` | **none** — no retries, no cleanup on death | no — an existing file is busy even for the same PID | a stale holder must force **manual** recovery |

The worktree resolver lock is again the **single self-contained §8.3 lock** (keyed on the
canonical per-worktree git dir — `workflow/mergeability-and-conflict-resolution.md`): it mints a
UUID token, creates the file exclusively with an owner-only mode, fsyncs and reads the record
back, and fences release on descriptor/path identity. It was briefly extracted onto a shared
`exclusiveFileClaim` primitive with a `draftReviewLock` sibling; both left with the persisted
draft-review protocol (`workflow/plan-review-flow.md`) and the lock was restored as one module.
The rule behind the table: reach for the *claim* when a same-session retry must reacquire; reach
for the no-reclamation lock when an orphan or dead PID can never prove that no effects happened,
so a human must look.

Two lessons from the round trip:

- **Mint the token INSIDE the cleanup-protected init block, after the exclusive create.** The
  pre-extraction lock minted its token before the try that owned the descriptor; a minting failure
  left an open descriptor plus an empty lock file that wedged every later acquisition as `busy`.
  The restored module mints via `opts.token` (the fault seam, defaulting to `randomUUID`) inside
  the protected block, and a test proves a throwing minter yields a typed `io-error`, unlinks the
  fresh file, closes the descriptor, and lets the next acquisition succeed.
- **"Restore verbatim" bounds the diff, not the review.** The byte-for-byte restore of the
  pre-extraction lock carried that pre-existing gap — which the intermediate extraction had
  fixed. When a refactor is rolled back, compare the restored module against what the extraction
  *improved*, not only against what it broke; a verbatim restore is a scope decision about the
  diff, never evidence the old code was right.

## Observation-acked delivery

- **Acceptance must prove exact membership:** batch acceptance = one persisted message carrying
  EVERY record's marker. First-record-marker matching over-acks reconstructed batches (unacked A
  + new B re-batches as [A,B] and matches A's old message). Ack readers validate the full
  versioned shape; unknown/malformed acks warn and redeliver (duplicate-safe), never silently
  suppress.
- **The only delivery evidence is the persisted entry** — `pi.sendUserMessage` is
  fire-and-forget (see `pi/extension-api.md`).
- The browser draft-review doors apply the same shape: a decision's delivery to the model is
  proven only by later persisted branch evidence (the injected user message with its digest and
  code-authored marker outside the untrusted block) — never by `message_end`/`sendUserMessage`
  spies (fire-and-forget, or firing before the append). `turn_end` sees persisted entries;
  `message_end` alone does not (`workflow/plan-review-flow.md` § "Testing recipes").

## Provenance fences for disposable local outboxes

Refuse git-TRACKED entries under the family (force-added checkout content posing as live
feedback), refuse symlinked path components on every appender, and sanitize non-body metadata
(control chars → U+FFFD) before interpolating into rendered messages.

## Live-smoke recipe

`/reload` the *current* TUI implement session — the extension factory re-runs from disk and the
new receiver claims the lease in place (the sanctioned live-smoke path for stateful
session-scoped receivers; see `pi/extension-api.md`). Launch the watch with the **worktree's own
CLI** (`cd .worktrees/plan-N && uv run perk plan watch N`) — the main checkout's perk is old
code.

## Deterministic testing

The injected-seam FakeTimers recipe and the test-only race hooks live in
`toolchain/node-test-async-determinism.md` — cross-ref, don't duplicate.

## Residual

Hunk API v4 is docs-verified only (the resolved binary speaks v2); the verified-generation set
`{2, 4}` + runtime payload validation is the guard — a v4 runtime proof should ride the next
hunk upgrade that ships one (the detail lives as a code comment at the guard in
`extension/hunkFeedback/`).

## Cross-references

- `docs/learned/pi/extension-api.md` — `pi.sendUserMessage` fire-and-forget; `/reload` re-claims
- `docs/learned/toolchain/node-test-async-determinism.md` — FakeTimers seams + race hooks
- `extension/substrate/worktreeResolverLock.ts` (+ `.test.ts`) — the no-reclamation §8.3 lock and its token-minting fault seam
- `extension/substrate/resolverLease.ts` — the same-PID-reacquirable session claim
- `docs/learned/workflow/mergeability-and-conflict-resolution.md` — the worktree-scoped execution lock
- `docs/learned/workflow/plan-review-flow.md` — the in-memory draft-review guards that replaced the run-scoped claim
