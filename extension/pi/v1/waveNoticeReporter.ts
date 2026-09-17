// The once-per-activation wave-notice reporter: turns the report wave's `duplicate-responders`
// notice (a context-less pi-subagents RPC responder answered before the live instance — pi's
// pre-trust load keeps a user-scope duplicate of the project's pi-subagents alive on the bus
// with no session context) into ONE `perk: waves — …` warning over the retained session ctx.
//
// The retained-ctx pattern is `SubmitConflictController.setContext`: the composition root calls
// `setContext(ctx)` on `session_start`/`session_tree`, and the reporter renders through the
// terminal-safe `report()` seam (headless targets go to stderr by construction). A notice that
// arrives before any ctx is retained (pre-`session_start`, or a bare factory) goes to
// `console.error` as the full report line and STILL latches — the warning is never repeated
// within one extension activation (a `/reload` or session switch re-activates the extension and
// may warn again). No flow module participates: the wave's fail-open `onNotice` seam is the
// only input, and no tool result is modified.

import { type ReportTarget, report } from "../../surfaces/report.ts";
import type { WaveNotice } from "../../waves/reportWave.ts";

export interface WaveNoticeReporter {
  /** Retain the latest session ctx (never resets the latch). */
  setContext(ctx: ReportTarget): void;
  /** The wave's `onNotice` seam: the first notice per kind warns; later ones are dropped. */
  onNotice(notice: WaveNotice): void;
}

const SCOPE = "waves";

/** The tested prose of the duplicate-load warning (one line; `report()` owns the prefix). */
export function renderWaveNotice(notice: WaveNotice): string {
  return (
    "A duplicate pi-subagents extension is loaded in this session: a context-less pi-subagents " +
    `RPC responder answered perk's ${notice.method} request with \`${notice.superseded}\` before ` +
    "the live instance succeeded — typically a user-scope npm:pi-subagents entry beside the " +
    "project entry, which pi's pre-trust load keeps alive. perk resolved the request against the " +
    "successful reply. Run `perk doctor` (subagent-package-scope), remove the duplicate, then " +
    "restart the session (/reload does not clear it). Shown once per extension activation."
  );
}

export function createWaveNoticeReporter(): WaveNoticeReporter {
  let current: ReportTarget | undefined;
  const latched = new Set<WaveNotice["kind"]>();
  return {
    setContext(ctx) {
      current = ctx;
    },
    onNotice(notice) {
      if (latched.has(notice.kind)) return;
      latched.add(notice.kind);
      const message = renderWaveNotice(notice);
      if (current === undefined) {
        console.error(`perk: ${SCOPE} — ${message}`);
        return;
      }
      report(current, SCOPE, "warning", message);
    },
  };
}
