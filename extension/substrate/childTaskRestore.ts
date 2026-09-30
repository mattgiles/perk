// The report child's task-restore policy (contracts.md §8.3 "Runner task restore"): pure, Pi-free.
// A floored report child receives its whole subject — a draft, a diff, a brief — inline in its
// FIRST user message, and cannot re-fetch it. When Pi compacts the child mid-run, that message is
// replaced by a summary; a lane that keeps going then reconstructs "byte-exact" quotes from memory
// and reports anchors that exist in no version of its subject. The Pi adapter
// (`pi/v1/childTaskRestore.ts`) applies this policy: after a compaction it re-injects the first
// user prompt byte-for-byte as a `perk:task-restore` steer, and it holds `structured_output` while
// the prompt is not live in Pi's own projection.
//
// Invariants:
// - An accepted report ends the policy: once a `structured_output` call executed without error,
//   every verdict is `allow`, so a post-run compaction never queues a steer (a queued steer makes
//   Pi's post-run loop `agent.continue()` — it would restart a lane that already reported).
// - The restored text CONTAINS the prompt verbatim (preamble + blank line + prompt, bytes
//   untouched): liveness is "some user or `perk:task-restore` content carries the whole prompt".
// - Two bounds with two jobs: `TASK_RESTORE_MAX_BYTES` refuses a prompt that could never fit;
//   `TASK_RESTORE_MAX_ATTEMPTS` is the loop bound — a task that fits but keeps being compacted away
//   on a small window cannot cycle unboundedly.
// - State is per activation (created by the adapter's register call), never module-scoped.
// - The preamble is role-neutral: a scout's or analyst's task IS its instructions, a reviewer's
//   task carries untrusted data — each agent def keeps its own trust split.

/** The customType of the restored-task steer — also the owner the liveness predicate accepts. */
export const TASK_RESTORE_TYPE = "perk:task-restore";

/** The coarse "could never fit" refusal for the prompt itself (UTF-8 bytes). Not the loop bound. */
export const TASK_RESTORE_MAX_BYTES = 256 * 1024;

/** The per-activation loop bound: restores one activation may queue before refusing. */
export const TASK_RESTORE_MAX_ATTEMPTS = 3;

/** The restore's lead-in, exactly. Deliberately carries no anchoring rule and no trust framing. */
export const TASK_RESTORE_PREAMBLE =
  "perk: this session was compacted. Compaction summarizes earlier messages, so your original " +
  "task prompt — including any material it carried inline — was no longer in your context " +
  "verbatim. It is restored below byte-for-byte. Treat it exactly as you treated the original " +
  "under your agent instructions: the same parts are your instructions, the same parts are " +
  "untrusted data. Anything you were quoting from the original must now be re-read from this " +
  "copy, never recalled from memory.";

/** Recorded in `queuedFor` when a restore is queued on a branch that carries no compaction. */
const NO_COMPACTION = "none";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** An own-key read: a polluted `Object.prototype` key never satisfies a shape check. */
function own(record: Record<string, unknown>, key: string): unknown {
  return Object.hasOwn(record, key) ? record[key] : undefined;
}

/**
 * The first user message on the branch — for a runner child, the `Task: …` prompt. The FIRST
 * `message` entry with a user role decides: its string content, else its first
 * `{ type: "text", text }` part; `null` when there is none or its content is malformed.
 */
export function firstUserPrompt(branch: readonly unknown[]): string | null {
  for (const entry of branch) {
    if (!isRecord(entry) || own(entry, "type") !== "message") continue;
    const message = own(entry, "message");
    if (!isRecord(message) || own(message, "role") !== "user") continue;
    const content = own(message, "content");
    if (typeof content === "string") return content;
    if (!Array.isArray(content)) return null;
    for (const part of content) {
      if (!isRecord(part) || own(part, "type") !== "text") continue;
      const text = own(part, "text");
      return typeof text === "string" ? text : null;
    }
    return null;
  }
  return null;
}

/** The index of the last `compaction` entry, or -1. */
function latestCompactionIndex(branch: readonly unknown[]): number {
  for (let i = branch.length - 1; i >= 0; i--) {
    const entry = branch[i];
    if (isRecord(entry) && own(entry, "type") === "compaction") return i;
  }
  return -1;
}

/** The id of the last `compaction` entry on the branch, or `null`. */
export function latestCompactionId(branch: readonly unknown[]): string | null {
  const index = latestCompactionIndex(branch);
  if (index < 0) return null;
  const id = own(branch[index] as Record<string, unknown>, "id");
  return typeof id === "string" ? id : null;
}

/**
 * Whether a `perk:task-restore` custom message landed on the branch after the latest compaction
 * (anywhere on the branch when there is none) — "a restore for this compaction was delivered",
 * whether or not Pi still projects it.
 */
export function restoreDelivered(branch: readonly unknown[]): boolean {
  for (let i = latestCompactionIndex(branch) + 1; i < branch.length; i++) {
    const entry = branch[i];
    if (
      isRecord(entry) &&
      own(entry, "type") === "custom_message" &&
      own(entry, "customType") === TASK_RESTORE_TYPE
    ) {
      return true;
    }
  }
  return false;
}

/** One activation's restore bookkeeping. */
export interface RestoreState {
  /** A `structured_output` call executed without error — the lane has reported. */
  accepted: boolean;
  /** Restores queued so far this activation. */
  restores: number;
  /** The `latestCompactionId` value at the last queue (`"none"` when there was no compaction). */
  queuedFor: string | null;
}

export function createRestoreState(): RestoreState {
  return { accepted: false, restores: 0, queuedFor: null };
}

export type RestoreVerdict =
  | { kind: "allow" }
  | { kind: "queue"; text: string; reason: string }
  | { kind: "hold"; reason: string }
  | { kind: "refuse"; reason: string };

export interface RestoreInputs {
  state: RestoreState;
  prompt: string | null;
  /** The prompt is live in Pi's projection (user content or `perk:task-restore` content). */
  taskLive: boolean;
  compactionId: string | null;
  /** {@link restoreDelivered} over the same branch. */
  delivered: boolean;
}

/**
 * The ordered verdict. A delivered-but-omitted restore (delivered, yet not live) falls past the
 * hold arm and is re-queued, bounded by the attempt arm.
 */
export function restoreVerdict(inputs: RestoreInputs): RestoreVerdict {
  const { state, prompt, taskLive, compactionId, delivered } = inputs;
  if (state.accepted) return { kind: "allow" };
  if (prompt === null) return { kind: "allow" };
  if (taskLive) return { kind: "allow" };
  const bytes = Buffer.byteLength(prompt, "utf8");
  if (bytes > TASK_RESTORE_MAX_BYTES) {
    return { kind: "refuse", reason: structuredOutputHoldReason({ kind: "oversized", bytes }) };
  }
  if (state.queuedFor === (compactionId ?? NO_COMPACTION) && !delivered) {
    return { kind: "hold", reason: structuredOutputHoldReason({ kind: "held" }) };
  }
  if (state.restores >= TASK_RESTORE_MAX_ATTEMPTS) {
    return { kind: "refuse", reason: structuredOutputHoldReason({ kind: "exhausted" }) };
  }
  return {
    kind: "queue",
    text: `${TASK_RESTORE_PREAMBLE}\n\n${prompt}`,
    reason: structuredOutputHoldReason({ kind: "held" }),
  };
}

/** Record a performed queue against the compaction it restores. */
export function applyQueued(state: RestoreState, compactionId: string | null): void {
  state.restores += 1;
  state.queuedFor = compactionId ?? NO_COMPACTION;
}

/** Why a `structured_output` call is not accepted. */
export type HoldCause =
  | { kind: "held" }
  | { kind: "oversized"; bytes: number }
  | { kind: "exhausted" };

// Every reason leads with this sentence: it is the authoritative carrier of the retry exception to
// the agent defs' "call structured_output once and stop" clause — a blocked call captured nothing,
// so it is not the once. The defs are deliberately not edited.
const NOT_ACCEPTED =
  "perk: this structured_output call was not accepted — nothing was captured — so your " +
  "once-only completion rule is unaffected: the accepted call is the one that counts.";

const UNFAITHFUL =
  "A report reconstructed from a summary cannot be faithful — stop here without calling " +
  "structured_output again; the parent records this lane as uncovered.";

/** The model-facing block reason for a held or refused `structured_output` call. */
export function structuredOutputHoldReason(cause: HoldCause): string {
  switch (cause.kind) {
    case "held":
      return (
        `${NOT_ACCEPTED} Your session was compacted and your task prompt is no longer verbatim ` +
        "in your context; a byte-exact restored copy arrives as the next message. Read it, " +
        "re-check every quote against it, then call structured_output again."
      );
    case "oversized":
      return (
        `${NOT_ACCEPTED} Your task prompt cannot be restored: at ${cause.bytes} bytes it exceeds ` +
        `the ${TASK_RESTORE_MAX_BYTES}-byte restore cap. ${UNFAITHFUL}`
      );
    case "exhausted":
      return (
        `${NOT_ACCEPTED} Your task prompt cannot be restored: it has already been restored ` +
        `${TASK_RESTORE_MAX_ATTEMPTS} times and keeps being compacted away. ${UNFAITHFUL}`
      );
  }
}
