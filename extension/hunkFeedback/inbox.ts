// The hunk watch feedback inbox (contracts.md §8.58): the single-flight delivery machine that
// drains the worktree outbox into the one eligible implement session.
//
//   idle → dispatching → awaiting-observation → acknowledged → idle
//                                 └→ backoff → dispatching
//
// Exactly ONE unacknowledged batch exists between injection and acknowledgement; while it awaits
// observation no new batch is injected — triggers (watch events, poll ticks, overflow) only mark
// the inbox dirty. Acknowledgement requires transcript OBSERVATION (`transport.isInjected`), not
// call-return: Pi's `sendUserMessage` is a void wrapper over in-memory queues an abort discards.
// Backoff resets ONLY on observation, so persistent asynchronous rejection backs off
// exponentially instead of retrying every poll tick — and unconfirmed messages can never
// accumulate (one in flight, ever). Duplicates possible, silent loss not.
//
// Failure containment: every background callback is wrapped — nothing ever escapes into the
// host session. Watcher failure degrades permanently to poll-only (polling is the correctness
// path); a failed lease verification closes the inbox fail-closed (misdelivery is never the
// fallback). Diagnostics route through `deps.report`, never into the model conversation.
//
// All effects arrive through `deps` (clock, timers, watch factory, report sink) — deterministic
// under test, no hidden globals.

import {
  hunkConsumerLockDir,
  hunkDeliveredPath,
  hunkOutboxPath,
  hunkWatchDir,
} from "../substrate/cache.ts";
import { lsFiles } from "../substrate/git.ts";
import {
  acquireLease,
  appendAcks,
  type DeliveryAck,
  type FeedbackRecord,
  HEARTBEAT_MS,
  readDeliveredIds,
  readOutbox,
  releaseLease,
  renewHeartbeat,
  sweepQuarantine,
  verifyLease,
} from "./store.ts";

// Implementation constants (§8.58) — code constants, deliberately not config.
export const DEBOUNCE_MS = 500;
export const POLL_MS = 10_000;
export const BATCH_MAX_RECORDS = 10;
export const BATCH_MAX_BYTES = 49_152;
export const BACKOFF_BASE_MS = 1_000;
export const BACKOFF_CAP_MS = 60_000;
/** An in-flight batch is only demotable once it has had ≥ one poll interval to land. */
export const IN_FLIGHT_MIN_AGE_MS = POLL_MS;

export interface ConsumerIdentity {
  cwd: string;
  runId: string;
  piSessionId: string;
  /** The worktree plan-ref's `pr_id` — records for any other plan are held, never delivered. */
  planId: string;
}

export interface FeedbackTransport {
  /** Render + sendUserMessage (idle vs steer). A synchronous throw = refusal (records stay pending). */
  inject(batch: readonly FeedbackRecord[]): void;
  /** True when the batch's injected message is observed as a persisted user-message entry on the branch. */
  isInjected(batch: readonly FeedbackRecord[]): boolean;
  isIdle(): boolean;
}

export interface FeedbackInboxHandle {
  close(): void;
}

/** The lease was foreign and fresh — this session stays passive (and says so, once). */
export interface PassiveClaim {
  passive: true;
  reason: string;
}

export interface InboxTimers {
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
  setInterval(fn: () => void, ms: number): unknown;
  clearInterval(handle: unknown): void;
}

export interface InboxWatcher {
  close(): void;
}

/** An `fs.watch` factory seam; construction may throw (degrades to poll-only). */
export type WatchFactory = (
  dir: string,
  onChange: () => void,
  onError: (error: unknown) => void,
) => InboxWatcher;

export interface InboxDeps {
  now(): number;
  timers: InboxTimers;
  watch: WatchFactory;
  report(severity: "info" | "warning" | "error", message: string): void;
}

export interface HunkFeedbackInbox {
  open(
    identity: ConsumerIdentity,
    transport: FeedbackTransport,
  ): FeedbackInboxHandle | PassiveClaim;
}

export function createHunkFeedbackInbox(deps: InboxDeps): HunkFeedbackInbox {
  return {
    open(identity, transport) {
      const lockDir = hunkConsumerLockDir(identity.cwd);
      const outboxPath = hunkOutboxPath(identity.cwd);
      const deliveredPath = hunkDeliveredPath(identity.cwd);
      const watchDir = hunkWatchDir(identity.cwd);
      const { now, timers, report } = deps;

      // Provenance fence (§8.58): the family is DISPOSABLE LOCAL state — a git-TRACKED entry
      // under it means checkout-supplied bytes (a force-added outbox/symlink) are posing as
      // live watch feedback. Refuse to open, loudly; nothing under the family is read.
      const tracked = lsFiles(identity.cwd, watchDir);
      if (tracked.length > 0) {
        const reason =
          "tracked file(s) under .perk/workflow/hunk-watch — repository-supplied feedback is " +
          `refused (untrack them to re-enable the bridge): ${tracked.join(", ")}`;
        report("error", reason);
        return { passive: true, reason };
      }

      // Quarantine sweep first (leftovers from a crashed reclaimer are harmless but dirty),
      // then the lease: a fresh foreign holder means this session never inspects the stream.
      for (const warning of sweepQuarantine(lockDir)) report("warning", warning);
      const lease = acquireLease(
        lockDir,
        {
          runId: identity.runId,
          piSessionId: identity.piSessionId,
        },
        now,
      );
      if (!lease.owned) return { passive: true, reason: lease.reason };
      const token = lease.token;

      // Accepted-but-unacknowledged suppression lives here too: an id whose ack append failed
      // stays in this set for the rest of the session (may redeliver in a later one — §8.58).
      const deliveredRead = readDeliveredIds(deliveredPath);
      const delivered = deliveredRead.ids;

      type Phase = "idle" | "awaiting" | "backoff";
      let phase: Phase = "idle";
      let dirty = false;
      let closed = false;
      let inFlight: { batch: readonly FeedbackRecord[]; injectedAt: number } | null = null;
      /** The CURRENT backoff delay; 0 = no failures since the last observation (the only reset). */
      let backoffMs = 0;
      let backoffTimer: unknown = null;
      let debounceTimer: unknown = null;
      let pollHandle: unknown = null;
      let heartbeatHandle: unknown = null;
      let watcher: InboxWatcher | null = null;
      const reportedOnce = new Set<string>();
      const heldPlanIds = new Set<string>();

      const reportOnce = (severity: "warning" | "error", message: string): void => {
        if (reportedOnce.has(message)) return;
        reportedOnce.add(message);
        report(severity, message);
      };

      const close = (): void => {
        if (closed) return;
        closed = true;
        if (debounceTimer !== null) timers.clearTimeout(debounceTimer);
        if (backoffTimer !== null) timers.clearTimeout(backoffTimer);
        if (pollHandle !== null) timers.clearInterval(pollHandle);
        if (heartbeatHandle !== null) timers.clearInterval(heartbeatHandle);
        try {
          watcher?.close();
        } catch {
          // disposal is best-effort
        }
        watcher = null;
        inFlight = null;
        releaseLease(lockDir, token); // removes only on token match
      };

      /** Fail-closed shutdown: the lease is no longer provably ours — stop, loudly, once. */
      const closeFailClosed = (): void => {
        reportOnce(
          "error",
          "feedback lease verification failed — closing the hunk feedback inbox (records stay queued for the next eligible session)",
        );
        close();
      };

      const enterBackoff = (): void => {
        // Never resets on dispatch: consecutive failures double toward the cap.
        backoffMs = backoffMs === 0 ? BACKOFF_BASE_MS : Math.min(backoffMs * 2, BACKOFF_CAP_MS);
        phase = "backoff";
        dirty = true;
        backoffTimer = timers.setTimeout(() => {
          backoffTimer = null;
          if (closed) return;
          phase = "idle";
          guard(dispatch);
        }, backoffMs);
      };

      const acknowledge = (batch: readonly FeedbackRecord[]): void => {
        const at = new Date(now()).toISOString();
        const acks: DeliveryAck[] = batch.map((record) => ({
          schema: 1,
          feedback_id: record.feedback_id,
          delivered_at: at,
          run_id: identity.runId,
          pi_session_id: identity.piSessionId,
        }));
        try {
          appendAcks(identity.cwd, acks);
        } catch (error) {
          // The message IS on the transcript — suppress same-session redelivery in memory; a
          // later session may redeliver (at-least-once, stated plainly).
          report(
            "warning",
            `could not append feedback acknowledgements (${error}) — delivery stands; the records may redeliver in a later session`,
          );
        }
        for (const record of batch) delivered.add(record.feedback_id);
        backoffMs = 0; // the ONLY reset site: transcript observation
        inFlight = null;
        phase = "idle";
        if (dirty) dispatch();
      };

      /** One dispatch pass — only ever entered from `idle`. */
      const dispatch = (): void => {
        if (closed || phase !== "idle") return;
        dirty = false;
        const read = readOutbox(outboxPath);
        for (const warning of read.warnings) reportOnce("warning", warning);
        const pending: FeedbackRecord[] = [];
        for (const record of read.records) {
          if (delivered.has(record.feedback_id)) continue;
          if (record.plan_id !== identity.planId) {
            if (!heldPlanIds.has(record.feedback_id)) {
              heldPlanIds.add(record.feedback_id);
              report(
                "warning",
                `holding feedback ${record.feedback_id} addressed to plan ${record.plan_id} — this session implements plan ${identity.planId}`,
              );
            }
            continue; // held: never delivered, never acked
          }
          pending.push(record);
        }
        if (pending.length === 0) return;

        // Bounded batch, append order retained; the remainder re-marks dirty.
        const batch: FeedbackRecord[] = [];
        let bytes = 0;
        for (const record of pending) {
          const size = Buffer.byteLength(record.body, "utf8");
          if (
            batch.length > 0 &&
            (batch.length >= BATCH_MAX_RECORDS || bytes + size > BATCH_MAX_BYTES)
          ) {
            break;
          }
          batch.push(record);
          bytes += size;
        }
        if (batch.length < pending.length) dirty = true;

        // The delivery fence: verify the lease immediately before every injection.
        if (!verifyLease(lockDir, token)) {
          closeFailClosed();
          return;
        }
        if (transport.isInjected(batch)) {
          // A prior injection survives on this branch — acknowledge without re-injecting.
          acknowledge(batch);
          return;
        }
        try {
          transport.inject(batch);
        } catch (error) {
          report("warning", `feedback injection refused synchronously (${error}) — backing off`);
          enterBackoff();
          return;
        }
        inFlight = { batch, injectedAt: now() };
        phase = "awaiting";
      };

      /** Wrap a background callback: report, never throw into the host session. */
      const guard = (fn: () => void): void => {
        try {
          fn();
        } catch (error) {
          reportOnce("error", `hunk feedback inbox error: ${error}`);
        }
      };

      const pollTick = (): void => {
        if (closed) return;
        if (phase === "awaiting" && inFlight !== null) {
          const flight = inFlight;
          if (transport.isInjected(flight.batch)) {
            acknowledge(flight.batch);
            return;
          }
          if (transport.isIdle() && now() - flight.injectedAt >= IN_FLIGHT_MIN_AGE_MS) {
            // The session went idle again without the message landing (an abort-discarded
            // steer queue or a failed turn) — demote: the records return to pending (they are
            // still in the outbox and not delivered) and backoff owns the next dispatch.
            inFlight = null;
            enterBackoff();
          }
          return;
        }
        if (phase === "idle") {
          dispatch(); // polling is the correctness path — the watcher may be dead
          return;
        }
        dirty = true; // backoff owns the next dispatch; triggers only mark dirty
      };

      const onWatchEvent = (): void => {
        if (closed) return;
        dirty = true;
        if (debounceTimer !== null) timers.clearTimeout(debounceTimer);
        debounceTimer = timers.setTimeout(() => {
          debounceTimer = null;
          if (closed) return;
          if (phase === "idle") guard(dispatch);
        }, DEBOUNCE_MS);
      };

      const heartbeatTick = (): void => {
        if (closed) return;
        try {
          renewHeartbeat(lockDir, token, now);
        } catch (error) {
          // The pre-injection verifyLease remains the delivery fence — report, keep going.
          reportOnce("warning", `feedback lease heartbeat failed: ${error}`);
        }
      };

      for (const warning of deliveredRead.warnings) reportOnce("warning", warning);

      // The immediate initial drain, then low-latency watch + poll fallback + heartbeat.
      guard(dispatch);
      if (closed) return { close }; // the drain closed fail-closed — install nothing
      try {
        watcher = deps.watch(
          watchDir,
          () => guard(onWatchEvent),
          (error) => {
            guard(() => {
              reportOnce(
                "warning",
                `hunk feedback watcher failed (${error}) — continuing on the polling fallback`,
              );
              try {
                watcher?.close();
              } catch {
                // best-effort
              }
              watcher = null;
            });
          },
        );
      } catch (error) {
        reportOnce(
          "warning",
          `could not watch the feedback outbox (${error}) — continuing on the polling fallback`,
        );
        watcher = null;
      }
      pollHandle = timers.setInterval(() => guard(pollTick), POLL_MS);
      heartbeatHandle = timers.setInterval(() => guard(heartbeatTick), HEARTBEAT_MS);

      return { close };
    },
  };
}
