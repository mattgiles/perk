// The one headless-safe report seam — owns the `perk: <scope> — <message>` prefix, the severity,
// and the `hasUI ? notify : console.error` routing so callers inherit the headless-fail-safe
// invariant for free (cf. the `branchOf`/`BranchSource` seam in workflowState.ts).

export type Severity = "info" | "warning" | "error";

/** The minimal headless-aware surface report() needs. `ExtensionContext` satisfies it; tests fake it. */
export interface ReportTarget {
  hasUI: boolean;
  ui: { notify(message: string, type?: Severity): void };
}

/**
 * The single headless-safe report seam. Builds `perk: <scope> — <message>`, notifies the UI when
 * present and otherwise writes to stderr (the headless-fail-safe invariant — callers inherit it for
 * free). Pass { alsoLog: true } to ALSO write to stderr when headful (cold-door failures land in run
 * logs even in a TUI). Returns the prefixed string for reuse (tool-result text, etc.).
 */
export function report(
  target: ReportTarget,
  scope: string,
  severity: Severity,
  message: string,
  opts?: { alsoLog?: boolean },
): string {
  const full = `perk: ${scope} — ${message}`;
  if (target.hasUI) {
    target.ui.notify(full, severity);
    if (opts?.alsoLog) console.error(full);
  } else {
    console.error(full);
  }
  return full;
}
