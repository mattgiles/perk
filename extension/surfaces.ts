// The perk surfaces module — Objective #251, node 2.1. The one module that owns perk's UI
// vocabulary per the TUI charter (`docs/design/tui-charter.md` §3–§5): standing-surface slot keys,
// footer identity marks, the §5 glyph + theming vocabulary, the §4 height bounds, the
// `setStanding` standing-surface setter, and the pure format helpers the standing surfaces render
// with. The notify seam itself stays in `report.ts` (re-exported here so "the surfaces module" is
// surfaces.ts + report.ts for the node 4.1 guard).
//
// Charter law mirrored here (no behavioral consumers yet for GLYPHS / the height bounds — they
// are pinned by surfaces.test.ts now and enforced in nodes 2.2/2.3/4.1; locked shape, not
// fiction).

// Re-exports: the notify seam stays in report.ts; surfaces.ts is the one import for UI vocabulary.
export { type ReportTarget, report, type Severity } from "./report.ts";

// --- standing-surface slot keys (charter §2) ---
// NOTE: same string as providers.ts PERK_CHECKPOINTS_PROVIDER_ID but a different concept
// (UI slot vs provider id) — deliberately NOT merged.
export const STATUS_SLOT_CHECKPOINTS = "perk-checkpoints";
export const STATUS_SLOT_OBJECTIVE = "perk-objective";

// --- footer identity marks (charter §5 / D3: emoji are footer-only identity, 2 cells wide) ---
export const MARK_CHECKPOINTS = "📋";
export const MARK_OBJECTIVE = "🎯";

// --- glyph vocabulary (charter §5 / D3) — data only; themed rendering binds in nodes 2.2/3.1 ---
export type GlyphKind = "done" | "current" | "pending" | "warning" | "failure";
export const GLYPHS: Record<GlyphKind, { glyph: string; themeColor: string }> = {
  done: { glyph: "✓", themeColor: "success" },
  current: { glyph: "▸", themeColor: "accent" },
  pending: { glyph: "○", themeColor: "dim" },
  warning: { glyph: "⚠", themeColor: "warning" },
  failure: { glyph: "✗", themeColor: "error" },
};

// --- height bounds (charter §4 / D1/D8) — enforcement lands in nodes 2.2/2.3/4.1 ---
export const NOTIFY_MAX_LINES = 1;
export const FOOTER_MAX_LINES = 1;
export const CHECKPOINTS_WIDGET_MAX_LINES = 4;
export const OBJECTIVE_WIDGET_MAX_LINES = 2;

// --- the standing-surface setter -----------------------------------------------------------------

/**
 * The minimal headless-aware surface `setStanding` needs. `ExtensionContext` satisfies it; tests
 * fake it (the same minimal-structural-interface recipe as report.ts's `ReportTarget` — see
 * `docs/learned/pi/extension-seams.md`).
 */
export interface StandingTarget {
  hasUI: boolean;
  ui: {
    setStatus(slot: string, value: string | undefined): void;
    setWidget(slot: string, value: string[] | undefined): void;
  };
}

/** Set (or clear, with undefined) a paired status+widget slot; no-op headless. */
export function setStanding(
  target: StandingTarget,
  slot: string,
  surface: { status: string; widget: string[] } | undefined,
): void {
  if (!target.hasUI) return;
  target.ui.setStatus(slot, surface?.status);
  target.ui.setWidget(slot, surface?.widget);
}

// --- format helpers (relocated from checkpoints.ts / objective.ts, verbatim) --------------------
// Structural parameter types (not CheckpointState/CheckpointStep imports) keep surfaces.ts
// dependency-free and avoid an import cycle with the surface controllers.

export interface ProgressStep {
  step: number;
  text: string;
  completed: boolean;
}

export interface ProgressState {
  steps: ProgressStep[];
  /** The in-progress step number, or `null`. */
  current: number | null;
}

/** The `done/total` checkpoint progress summary (with `· ▶n` when a step is current). */
export function progressLine(state: ProgressState): string {
  const done = state.steps.filter((s) => s.completed).length;
  const base = `${done}/${state.steps.length}`;
  return state.current != null ? `${base} · ▶${state.current}` : base;
}

/**
 * The glyph for a step: ☑ completed, ▶ the current step, ☐ otherwise. NOTE: `☑ ▶ ☐` are
 * charter-retired (§5 / D3) — node 2.2 replaces them with the `GLYPHS` vocabulary above.
 */
export function stepGlyph(state: ProgressState, s: ProgressStep): string {
  if (s.completed) return "☑";
  if (s.step === state.current) return "▶";
  return "☐";
}

function formatTokens(tokens: number): string {
  if (tokens < 1000) return `${tokens}`;
  return `${(tokens / 1000).toFixed(1)}k`;
}

function formatElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  if (totalSec < 60) return `${totalSec}s`;
  const min = Math.floor(totalSec / 60);
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  return `${hr}h${min % 60}m`;
}

/** A compact one-line budget summary (e.g. `12.3k tok · 5m`). */
export function formatBudgetLine(args: { tokens: number; elapsedMs: number }): string {
  return `${formatTokens(args.tokens)} tok · ${formatElapsed(args.elapsedMs)}`;
}
