// The driven-compaction seam: the shared Pi skeleton behind every `*-and-compact` warm door — a
// one-shot pending record, the `agent_settled` settle gate ("the driven run fully settled" —
// `turn_end` would compact mid-run), `ctx.compact`, and the completion-gated continuation. Each
// door supplies a spec carrying all of its prose and policy; this module owns only mechanics.
//
// Invariants every door inherits:
//   - Every invocation supersedes the one-shot slot; a drive re-arms it ONLY after the guidance
//     send returns (a throwing send can never leave a phantom record for a later settle).
//   - Consume-then-clear on settle: the record is strictly one-shot, even when handling throws.
//   - The compaction instructions and the continuation are computed synchronously while the
//     command/event context is current; `onComplete`/`onError` use the captured `pi`, never `ctx`.
//   - The continuation is dispatched optionless, and only after a compaction succeeded.
//   - Compaction arbitration: Pi's automatic threshold/overflow compaction (and perk's objective
//     threshold compaction) can land during the driven turn — Pi awaits its own compaction check
//     before emitting `agent_settled`, and a second manual compaction then fails with `Already
//     compacted`. A `session_compact` observed while a record is armed therefore makes the settle
//     arm skip its own compaction and dispatch the continuation directly; one observed while our
//     own compaction is in flight lets a failed compaction still resume on the foreign result.
//
// The pending record is in-memory by design (lost on `/reload` — the user re-runs the command).
// Human-only: registers a command, never a tool. The regression net for this seam is the
// `/commit-and-compact` door suite (`pi/v1/delivery/commitCompact.test.ts`), which pins every
// observable byte of these paths plus the arbitration arms — there is no separate fake-spec suite.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { bindingSuffix } from "../../substrate/bindingDelivery.ts";
import { registerPerkCommand } from "../../substrate/command.ts";
import { report, type Severity } from "../../surfaces/report.ts";

/** The invocation decision. `compact-now`'s notice is the FULL message (no drive window, so no
 * arbitration suffix); `drive`'s guidance is sent with the `command:<name>` binding suffix. */
export type DrivenStart<P, C> =
  | { kind: "skip"; warning: string }
  | { kind: "compact-now"; notice: string; completion: C }
  | { kind: "drive"; notice: string; guidance: string; pending: P };

/** The settle decision. `compact-now`'s notice is the BASE (e.g. "committed"); the seam appends
 * the outcome suffix (compacting, or resuming on a compaction that already landed). */
export type DrivenSettle<C> =
  | { kind: "skip"; warning: string }
  | { kind: "compact-now"; notice: string; completion: C };

export interface DrivenCompactionSpec<P, C> {
  /** The slash-command name — also the `report()` label, the `command:<name>` binding trigger,
   * and the `console.error` prefix. */
  command: string;
  description: string;
  start(ctx: ExtensionContext): DrivenStart<P, C>;
  settle(ctx: ExtensionContext, pending: P): DrivenSettle<C>;
  /** The compaction `customInstructions` (computed synchronously before `ctx.compact`). */
  instructions(ctx: ExtensionContext, completion: C): string;
  /** The continuation, rendered while ctx is current (never inside `onComplete`/`onError`). */
  continuation(ctx: ExtensionContext, completion: C): string;
}

/** Neutralize every tag spelling of `tag` inside repository-/model-controlled text quoted in a
 * fence, so quoted text can never close (or reopen) the fence it sits inside: the name directly
 * followed by `>`, or by whitespace (optionally with attribute-like text) and then `>`, matched
 * case-insensitively, gets its `>` escaped — `</working-draft >` → `</working-draft \>`. The
 * canonical spelling keeps its historical bytes (`${tag}>` → `${tag}\>`); a longer name that
 * merely starts with `tag` (`${tag}s>`) is a different tag and is left alone. */
export function fenceSafe(text: string, tag: string): string {
  const name = tag.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return text.replace(new RegExp(`(${name})((?:\\s[^<>]*)?)>`, "gi"), "$1$2\\>");
}

/** Register one `*-and-compact` door: the command, its `agent_settled` consumer, and the
 * `session_compact` arbitration observer. */
export function installDrivenCompaction<P, C>(
  pi: ExtensionAPI,
  spec: DrivenCompactionSpec<P, C>,
): void {
  // The armed record rides a wrapper so `null` stays the unarmed marker for EVERY `P` — a spec
  // whose pending token is itself null (or nullable) can never read as unarmed.
  let armed: { record: P } | null = null;
  let compactedMeanwhile = false;
  let inFlight = false;
  const say = (ctx: ExtensionContext, severity: Severity, message: string): void => {
    report(ctx, spec.command, severity, message);
  };

  // Pi emits this for automatic threshold/overflow compaction and for every manual one — our
  // own included (that success-path observation is simply ignored by `onComplete`).
  pi.on("session_compact", async () => {
    if (armed !== null || inFlight) compactedMeanwhile = true;
  });

  const dispatchContinuation = (continuation: string): void => {
    try {
      // Optionless on purpose: resume immediately under the active stage's own bindings.
      pi.sendUserMessage(continuation);
    } catch (error) {
      console.error(`perk: ${spec.command} — continuation dispatch failed — ${error}`);
    }
  };

  const compactNow = (ctx: ExtensionContext, completion: C): void => {
    // Render while the command/event context is current: manual compaction stays in the same
    // AgentSession + runner, so the callbacks may use captured `pi` (never `ctx` or fresh state).
    const customInstructions = spec.instructions(ctx, completion);
    const continuation = spec.continuation(ctx, completion);
    compactedMeanwhile = false;
    inFlight = true;
    ctx.compact({
      customInstructions,
      onComplete: () => {
        inFlight = false;
        dispatchContinuation(continuation);
      },
      onError: (error) => {
        inFlight = false;
        // A foreign compaction that landed between settle and our own attempt makes ours fail
        // (`Already compacted`) — the session WAS compacted, so resume on that result.
        if (compactedMeanwhile) {
          console.error(
            `perk: ${spec.command} — compaction failed after another compaction landed (${error}) — resuming on the result`,
          );
          dispatchContinuation(continuation);
        } else {
          console.error(`perk: ${spec.command} — compaction failed — ${error}`);
        }
      },
    });
  };

  pi.on("agent_settled", async (_event, ctx) => {
    if (armed === null) return;
    const { record } = armed;
    armed = null; // consume-then-clear: the record is strictly one-shot
    try {
      const outcome = spec.settle(ctx, record);
      switch (outcome.kind) {
        case "skip":
          say(ctx, "warning", outcome.warning);
          return;
        case "compact-now":
          if (compactedMeanwhile) {
            // Pi's native compaction completes before `agent_settled`: a second manual one would
            // throw `Already compacted`, so continue straight onto the compacted session.
            say(
              ctx,
              "info",
              `${outcome.notice} — the session was already compacted during the driven turn; resuming on the result…`,
            );
            dispatchContinuation(spec.continuation(ctx, outcome.completion));
            return;
          }
          say(ctx, "info", `${outcome.notice} — compacting the session…`);
          compactNow(ctx, outcome.completion);
          return;
      }
      const exhaustive: never = outcome; // no default arm: union growth breaks the seam here
      throw new Error(`unreachable settle outcome: ${JSON.stringify(exhaustive)}`);
    } catch (error) {
      console.error(`perk: ${spec.command} — settle handling failed — ${error}`);
    }
  });

  registerPerkCommand(pi, spec.command, {
    description: spec.description,
    handler: async (_args, ctx) => {
      // Every invocation supersedes the one-shot slot (the drive arm re-arms it post-send) — a
      // stale record must never survive a non-drive/failed reinvocation into a later settle.
      armed = null;
      const outcome = spec.start(ctx);
      switch (outcome.kind) {
        case "skip":
          say(ctx, "warning", outcome.warning);
          return;
        case "compact-now":
          say(ctx, "info", outcome.notice);
          compactNow(ctx, outcome.completion);
          return;
        case "drive":
          say(ctx, "info", outcome.notice);
          // Drive unconditionally — report() already carries the headless stderr fallback.
          pi.sendUserMessage(outcome.guidance + bindingSuffix(ctx.cwd, `command:${spec.command}`));
          // Arm ONLY after the send: a throwing send leaves the slot unset, so a later
          // `agent_settled` can never consume a phantom record.
          compactedMeanwhile = false;
          armed = { record: outcome.pending };
          return;
      }
      const exhaustive: never = outcome; // no default arm: union growth breaks the seam here
      throw new Error(`unreachable start outcome: ${JSON.stringify(exhaustive)}`);
    },
  });
}
