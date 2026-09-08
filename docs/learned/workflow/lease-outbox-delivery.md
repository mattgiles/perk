---
title: Lease-fenced outboxes, exclusive file claims & observation-acked delivery
read_when: You are touching extension/hunkFeedback/, designing a file-lease/lock protocol or an outbox-ack bridge, choosing between resolverLease and the exclusiveFileClaim wrappers, or reviewing check-then-act.
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
| The exclusive file claim | `extension/substrate/exclusiveFileClaim.ts` | **none** — no retries, no cleanup on death | no — an existing file is busy even for the same PID | a stale holder must force **manual** recovery |

The shared primitive mints a UUID token, creates the file exclusively with an owner-only mode,
fsyncs and reads the record back, and fences release on descriptor/path identity. Its thin
wrappers own the path and metadata: `extension/substrate/worktreeResolverLock.ts` (keyed on the
canonical per-worktree git dir — `workflow/mergeability-and-conflict-resolution.md`) and
`extension/substrate/draftReviewLock.ts` (the run-scoped draft-review claim —
`workflow/plan-review-flow.md`). The rule behind the table: reach for the *claim* when a
same-session retry must reacquire; reach for the no-reclamation primitive when an orphan or dead
PID can never prove that no effects happened, so a human must look. Extraction lesson: the
worktree lock was refactored onto the primitive while preserving its exported API, record shape,
filename, and its real child-process contention tests THROUGH the extraction — the preserved
tests were the safety net that made the extraction reviewable.

## Observation-acked delivery

- **Acceptance must prove exact membership:** batch acceptance = one persisted message carrying
  EVERY record's marker. First-record-marker matching over-acks reconstructed batches (unacked A
  + new B re-batches as [A,B] and matches A's old message). Ack readers validate the full
  versioned shape; unknown/malformed acks warn and redeliver (duplicate-safe), never silently
  suppress.
- **The only delivery evidence is the persisted entry** — `pi.sendUserMessage` is
  fire-and-forget (see `pi/extension-api.md`).
- The draft-review dispatch surface applies the same shape: delivery is proven only by later
  persisted branch evidence — a persisted `plan_review` tool result with the fixed toolCallId, or
  the code-authored user-message marker `<!-- perk:draft-review-dispatch:<id> -->` outside the
  untrusted block — never by `message_end`/`sendUserMessage` spies (fire-and-forget, or firing
  before the append). `turn_end` sees persisted entries; `message_end` alone does not
  (`workflow/plan-review-flow.md`).

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
- `extension/substrate/exclusiveFileClaim.ts` (+ `worktreeResolverLock.ts`, `draftReviewLock.ts`) — the no-reclamation primitive and its wrappers
- `docs/learned/workflow/mergeability-and-conflict-resolution.md` — the worktree-scoped execution lock
- `docs/learned/workflow/plan-review-flow.md` — the persisted draft-review protocol the run-scoped claim serves
