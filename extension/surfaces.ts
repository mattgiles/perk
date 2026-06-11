// The perk surfaces module — Objective #251, node 2.1. The one module that owns perk's UI
// vocabulary per the TUI charter (`docs/design/tui-charter.md` §3–§5): standing-surface slot keys,
// footer identity marks, the §5 glyph + theming vocabulary, the §4 height bounds, the
// `setStanding` standing-surface setter, and the pure format helpers the standing surfaces render
// with. The notify seam itself stays in `report.ts` (re-exported here so "the surfaces module" is
// surfaces.ts + report.ts for the node 4.1 guard).
//
// Charter law mirrored here: GLYPHS + the checkpoints height bound now have a behavioral
// consumer (checkpoints.ts renders through `renderProgressLines`/`windowProgress`, node 2.2);
// the objective bound binds in node 2.3 and the regression guard in node 4.1.

import { truncateToWidth } from "@earendil-works/pi-tui";

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
 * The minimal theme surface perk's themed renderers need (`theme.fg(color, text)`). Pi's real
 * `Theme` satisfies it structurally; tests fake it with a tagging `fg`. Keeping the structural
 * type here keeps surfaces.ts dependency-light (no `Theme` import).
 */
export interface ThemeLike {
  fg(color: string, text: string): string;
}

/**
 * A standing-widget component factory in pi's `setWidget` factory shape: invoked with the live
 * `(tui, theme)`, returns a component whose `render(width)` computes themed lines **per call**
 * (the D10 stateless-render pattern — never cache themed strings). NOTE: pi's RPC mode drops
 * factory widgets (only string[] forwards) — an accepted trade-off recorded in contracts.md.
 */
export type StandingWidgetFactory = (
  tui: unknown,
  theme: ThemeLike,
) => { render(width: number): string[]; invalidate(): void };

/**
 * The minimal headless-aware surface `setStanding` needs. `ExtensionContext` satisfies it; tests
 * fake it (the same minimal-structural-interface recipe as report.ts's `ReportTarget` — see
 * `docs/learned/pi/extension-seams.md`).
 */
export interface StandingTarget {
  hasUI: boolean;
  ui: {
    setStatus(slot: string, value: string | undefined): void;
    setWidget(
      slot: string,
      value: string[] | StandingWidgetFactory | undefined,
      options?: { placement?: "aboveEditor" | "belowEditor" },
    ): void;
  };
}

/** Set (or clear, with undefined) a paired status+widget slot; no-op headless. */
export function setStanding(
  target: StandingTarget,
  slot: string,
  surface:
    | {
        status: string;
        widget: string[] | StandingWidgetFactory;
        placement?: "aboveEditor" | "belowEditor";
      }
    | undefined,
): void {
  if (!target.hasUI) return;
  target.ui.setStatus(slot, surface?.status);
  if (surface?.placement) {
    target.ui.setWidget(slot, surface.widget, { placement: surface.placement });
  } else {
    target.ui.setWidget(slot, surface?.widget);
  }
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

/** The `done/total` checkpoint progress summary (with `· ▸n` when a step is current). */
export function progressLine(state: ProgressState): string {
  const done = state.steps.filter((s) => s.completed).length;
  const base = `${done}/${state.steps.length}`;
  return state.current != null ? `${base} · ▸${state.current}` : base;
}

/** The `GLYPHS` kind for a step: done if completed, current if it IS the current step, else pending. */
export function stepGlyphKind(state: ProgressState, s: ProgressStep): GlyphKind {
  if (s.completed) return "done";
  if (s.step === state.current) return "current";
  return "pending";
}

/** A windowed progress item: a visible step, or an elision marker for the hidden steps. */
export type ProgressWindowItem =
  | { kind: "step"; step: ProgressStep }
  | { kind: "elision"; hidden: number; side: "earlier" | "later" };

/**
 * The D1 sliding window: at most `cap` step items (elision markers extra). For `n ≤ cap` all
 * steps show with no markers. Otherwise the window anchors on the current step (`current == null`
 * ⟹ all complete ⟹ anchor at the end) sitting second when possible — one earlier step above,
 * the rest below — with `… +N earlier` / `… +N later` markers for the hidden steps.
 */
export function windowProgress(state: ProgressState, cap: number): ProgressWindowItem[] {
  const n = state.steps.length;
  if (n <= cap) return state.steps.map((step) => ({ kind: "step", step }));
  const anchorIdx =
    state.current != null
      ? Math.max(
          state.steps.findIndex((s) => s.step === state.current),
          0,
        )
      : n - 1;
  const start = Math.min(Math.max(anchorIdx - 1, 0), n - cap);
  const items: ProgressWindowItem[] = [];
  if (start > 0) items.push({ kind: "elision", hidden: start, side: "earlier" });
  for (const step of state.steps.slice(start, start + cap)) items.push({ kind: "step", step });
  const later = n - start - cap;
  if (later > 0) items.push({ kind: "elision", hidden: later, side: "later" });
  return items;
}

/**
 * The themed checkpoints-widget lines (charter D1/D3/D9/D10): the `windowProgress` window mapped
 * to `✓/▸/○ <n>. <text>` lines colored per the §5 table (completed text muted, elision markers
 * dim), every line width-truncated via pi-tui's `truncateToWidth` (ANSI- and wide-glyph-aware).
 * Pure per call — call it inside a component's `render()` so theming stays live (D10).
 */
export function renderProgressLines(
  state: ProgressState,
  theme: ThemeLike,
  width: number,
): string[] {
  return windowProgress(state, CHECKPOINTS_WIDGET_MAX_LINES).map((item) => {
    if (item.kind === "elision") {
      return truncateToWidth(theme.fg("dim", `… +${item.hidden} ${item.side}`), width);
    }
    const kind = stepGlyphKind(state, item.step);
    const glyph = theme.fg(GLYPHS[kind].themeColor, GLYPHS[kind].glyph);
    const text = `${item.step.step}. ${item.step.text}`;
    const line = `${glyph} ${kind === "done" ? theme.fg("muted", text) : text}`;
    return truncateToWidth(line, width);
  });
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
