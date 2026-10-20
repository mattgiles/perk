// The one terminal-safe report seam — owns the `perk: <scope> — <message>` prefix, the severity,
// and the projection of complete diagnostics into a managed headline plus an optional durable detail
// sink (cf. the `branchOf`/`BranchSource` seam in workflowState.ts).

export type Severity = "info" | "warning" | "error";
export type ReportDetailSink = (text: string, severity: Severity) => void;

/** The minimal headless-aware surface report() needs. `ExtensionContext` satisfies it; tests fake it. */
export interface ReportTarget {
  hasUI: boolean;
  mode?: "tui" | "rpc" | "json" | "print";
  ui: { notify(message: string, type?: Severity): void };
}

const detailSinks = new WeakMap<ReportTarget, ReportDetailSink>();
const LOGICAL_LINE = /\r\n|\n|\r/;
const HORIZONTAL_WHITESPACE = /[^\S\r\n]+/g;

/** Attach display-only multiline report detail to this exact context object. */
export function attachReportDetailSink(target: ReportTarget, sink: ReportDetailSink): void {
  detailSinks.set(target, sink);
}

function headlineFor(prefix: string, message: string): string {
  for (const line of message.split(LOGICAL_LINE)) {
    const trimmed = line.trim();
    if (trimmed.length > 0) return `${prefix}${trimmed.replace(HORIZONTAL_WHITESPACE, " ")}`;
  }
  return prefix;
}

/**
 * Build and return the complete `perk: <scope> — <message>` value. Headless targets receive that
 * value on stderr. Headful targets receive a managed one-line headline; multiline detail goes to an
 * attached display-only sink in every non-RPC mode. `{ alsoLog: true }` is narrowly an RPC/headless
 * diagnostic mirror and never permits raw terminal output in a headful non-RPC context.
 *
 * The detail-sink append is BEST-EFFORT: the headline has already been delivered, and a diagnostic
 * append may never fail its caller — callers report from inside their own failure paths (a held
 * workflow-state append reports from its catch), and the warm-command sink rides the same Pi
 * persistence path that may just have failed. A throwing sink therefore falls back to ONE stderr
 * write carrying the complete value (the only headful non-RPC stderr write — the TUI charter's §1
 * bounded exception) and never propagates.
 */
export function report(
  target: ReportTarget,
  scope: string,
  severity: Severity,
  message: string,
  opts?: { alsoLog?: boolean },
): string {
  const prefix = `perk: ${scope} — `;
  const full = `${prefix}${message}`;
  if (!target.hasUI) {
    console.error(full);
    return full;
  }

  target.ui.notify(headlineFor(prefix, message), severity);
  if (target.mode === "rpc") {
    if (opts?.alsoLog) console.error(full);
    return full;
  }

  const sink = message.split(LOGICAL_LINE).length > 1 ? detailSinks.get(target) : undefined;
  if (sink !== undefined) {
    try {
      sink(full, severity);
    } catch {
      console.error(full);
    }
  }
  return full;
}
