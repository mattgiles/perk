// The human-facing projection of a gate transition result (contracts.md §8.40/§8.3): one notice
// sentence per held transition, a best-effort reporter through the surfaces seam, and the D1a
// approval-gate slice over ToolGating. Presentation lives here (the adapter layer); the Pi-free
// seams see only the typed `GateTransition`.
//
// Reporting a held transition may never fail its caller — a caller can hold a landed save or a
// receipt. The notice is single-line by construction (the thrown text is folded for display), so
// `report()` never routes it to the detail sink (whose append rides the same persistence path a
// persist-failed release just failed on); a throwing surface falls back to one stderr line.

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { ApprovalGate } from "../../authoring/review/approvalGate.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import type { GateTransition } from "../../substrate/toolPolicy.ts";
import { branchOf, rebuildWorkflowState } from "../../substrate/workflowState.ts";
import { report, type Severity } from "../../surfaces/report.ts";

export type GateTransitionNotice = { severity: Severity; message: string };

const NEWLINE_RUN = /\s*(?:\r\n|\n|\r)\s*/g;

/** A transition that did not land as asked. */
export type HeldTransition = Exclude<GateTransition, { status: "applied" }>;

/** The one human-facing sentence for a transition that did not land as asked; null when applied. */
export function gateTransitionNotice(t: HeldTransition): GateTransitionNotice;
export function gateTransitionNotice(t: GateTransition): GateTransitionNotice | null;
export function gateTransitionNotice(t: GateTransition): GateTransitionNotice | null {
  if (t.status === "applied") return null;
  if (t.status === "restricted") {
    return {
      severity: "warning",
      message:
        "the read-only gate stays on — this session carries a runner restriction floor that no in-session gesture lifts",
    };
  }
  const verb = t.requested === "read-only" ? "enter read-only" : "release the read-only gate";
  const cause = t.step === "persist" ? "mode persistence failed" : "tool reconciliation failed";
  const error = t.error.replace(NEWLINE_RUN, " ");
  const tail =
    t.step === "persist"
      ? "; the persisted mode is unverified (the next session start re-syncs from the branch)"
      : "";
  return {
    severity: "error",
    message: `could not ${verb} (${cause}: ${error}) — the session is ${t.access}${tail}`,
  };
}

/**
 * Report a held transition through the surfaces seam, best-effort: never throws; returns the
 * notice (null when applied — nothing is reported).
 */
export function reportGateTransition(
  ctx: ExtensionContext,
  scope: string,
  t: GateTransition,
  suffix?: string,
  opts?: { alsoLog?: boolean },
): GateTransitionNotice | null {
  const notice = gateTransitionNotice(t);
  if (notice === null) return null;
  const message = suffix ? `${notice.message}${suffix}` : notice.message;
  try {
    report(ctx, scope, notice.severity, message, opts);
  } catch {
    console.error(`perk: ${scope} — ${message}`);
  }
  return notice;
}

/**
 * The D1a gate slice over ToolGating: `exit` releases the gate, reports a held release
 * (best-effort, scope `read-only`) and always returns the transition. The one composition site
 * for every approval→save flow.
 */
export function approvalGateFor(gating: ToolGating, ctx: ExtensionContext): ApprovalGate {
  return {
    isActive: () => gating.isActive(),
    exit: () => {
      const t = gating.exit(ctx);
      reportGateTransition(ctx, "read-only", t);
      return t;
    },
  };
}

/**
 * Whether a warm door must enter the gate: unless the session is gated in memory AND the branch
 * already persists `mode: read-only`. The in-memory latch alone is not enough — a held entry
 * whose append failed latches the gate without persisting it, and a door's stage sync re-scopes
 * tools without ever writing the mode, so a retry must re-attempt the mode write (an unpersisted
 * gate loses plan guidance and re-opens at the next rebuild point).
 */
export function gateEntryNeeded(gating: ToolGating, ctx: ExtensionContext): boolean {
  return !gating.isActive() || rebuildWorkflowState(branchOf(ctx)).mode !== "read-only";
}
