---
title: Lease-fenced outboxes & observation-acked delivery (the hunk feedback bridge)
read_when: You are touching extension/hunkFeedback/, designing a file-lease/lock-dir protocol or an outbox-ack bridge between a CLI and a live session, or reviewing check-then-act windows in lease code.
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

## Observation-acked delivery

- **Acceptance must prove exact membership:** batch acceptance = one persisted message carrying
  EVERY record's marker. First-record-marker matching over-acks reconstructed batches (unacked A
  + new B re-batches as [A,B] and matches A's old message). Ack readers validate the full
  versioned shape; unknown/malformed acks warn and redeliver (duplicate-safe), never silently
  suppress.
- **The only delivery evidence is the persisted entry** — `pi.sendUserMessage` is
  fire-and-forget (see `pi/extension-api.md`).

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
