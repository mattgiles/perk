// The perk surfaces module. The one module that owns perk's UI
// vocabulary per the TUI charter (`docs/design/tui-charter.md` §3–§5): the single-value `perk`
// status slot key, footer identity marks, the §5 glyph + theming vocabulary, the §4 height
// bounds, the `createPerkStatus` status handle, and the pure format helpers the standing
// surfaces render with. The notify seam itself stays in `report.ts` (re-exported here so "the
// surfaces module" is surfaces.ts + report.ts for the surfaces guard).
//
// Perk status (charter §6 D2): perk presents ONE footer status under the single
// `perk` slot — the single-value objective segment (the checkpoint substrate is retired, so
// there is no composition step). The per-feature status slots and widgets are retired (D8
// sanctioned). The perk-owned footer (`perkFooter`/`installPerkFooter` below) renders the value
// directly; the `perk` status slot keeps publishing — it is the RPC-visible surface (setFooter
// is an RPC no-op).

import { truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";

// `Key` is keybinding vocabulary (`pi.registerShortcut(Key.ctrlAlt("p"), …)`), not rich UI —
// re-exported so pi-tui imports stay structurally confined to the surfaces module (the
// surfacesGuard pi-tui import rule) without allowlisting the shortcut-registering modules.
export { Key } from "@earendil-works/pi-tui";
// Re-exports: the notify seam stays in report.ts; surfaces.ts is the one import for UI vocabulary.
export { type ReportTarget, report, type Severity } from "./report.ts";

// --- standing-surface slot keys (charter §2) ---
// The ONE perk status slot (D2): perk's single status value renders under this key.
export const STATUS_SLOT_PERK = "perk";

// --- footer identity marks (charter §5 / D3: emoji are footer-only identity, 2 cells wide) ---
export const MARK_OBJECTIVE = "🎯";

// --- glyph vocabulary (charter §5 / D3) — charter-law data, pinned by tests ---
export type GlyphKind = "done" | "current" | "pending" | "warning" | "failure";
export const GLYPHS: Record<GlyphKind, { glyph: string; themeColor: string }> = {
  done: { glyph: "✓", themeColor: "success" },
  current: { glyph: "▸", themeColor: "accent" },
  pending: { glyph: "○", themeColor: "dim" },
  warning: { glyph: "⚠", themeColor: "warning" },
  failure: { glyph: "✗", themeColor: "error" },
};

// --- height bounds (charter §4 / D1/D8) — enforced by the report() notify budget and the footer builder ---
export const NOTIFY_MAX_LINES = 1;
export const FOOTER_MAX_LINES = 1;

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
 * The minimal headless-aware surface the status handle needs — the `perk` status slot is the one
 * standing surface it serves. `ExtensionContext` satisfies it; tests fake it (the same
 * minimal-structural-interface recipe as report.ts's `ReportTarget` — see
 * `docs/learned/pi/extension-seams.md`).
 */
export interface StandingTarget {
  hasUI: boolean;
  ui: {
    setStatus(slot: string, value: string | undefined): void;
  };
}

// --- the working-message seam (vendored `whimsical`; charter §6 permitted text-only) ------------

/**
 * The minimal headless-aware surface the `setWorkingMessage` seam needs. `ExtensionContext`
 * satisfies it; tests fake it (the `StandingTarget`/`ReportTarget` minimal-structural recipe).
 * `setWorkingMessage` sets only a plain text label on pi's existing default working indicator
 * (`undefined` restores pi's default per the SDK contract) — distinct from the declined
 * `setWorkingIndicator` (D5).
 */
export interface WorkingMessageTarget {
  hasUI: boolean;
  ui: { setWorkingMessage(message?: string): void };
}

/**
 * Set (or, with `undefined`, restore pi's default) the working-message label; no-op headless.
 * The one sanctioned `ctx.ui.setWorkingMessage` call site (guard allowlist) — `whimsical` routes
 * its per-turn phrase through here. Text-only and headless-no-op, so it never touches rich UI in a
 * cold/headless/RPC session.
 */
export function setWorkingMessage(target: WorkingMessageTarget, message?: string): void {
  if (!target.hasUI) return;
  target.ui.setWorkingMessage(message);
}

// --- the perk status (charter D2) --------------------------------------------

/**
 * The single-value status handle: the objective publisher sets the one value through `set`, and
 * the handle republishes the single `perk` status slot. The footer reads the value back via `get`
 * and repaints via `subscribe` — the slot's `setStatus` dual-publish is deliberate (RPC clients
 * see the slot; setFooter is an RPC no-op).
 */
export interface PerkStatusHandle {
  /** Set (or clear, with undefined) the one value; publishes the slot. No-op headless. */
  set(target: StandingTarget, text: string | undefined): void;
  /** The current text (undefined when unset). */
  get(): string | undefined;
  /**
   * Subscribe to publishes: the listener fires after every headful `set` (headless `set`
   * calls are full no-ops, so nothing fires). Returns an unsubscribe.
   */
  subscribe(listener: () => void): () => void;
}

/**
 * Create the single-value `perk` status handle (one per extension instance — created in index.ts
 * and passed to the objective publisher; no hidden module state). Headless calls are full no-ops
 * (never record the text, so headless-era text can't resurrect in a later headful render).
 * `undefined` clears the slot. No width handling: pi's footer truncates the status line itself.
 */
export function createPerkStatus(): PerkStatusHandle {
  let value: string | undefined;
  const listeners = new Set<() => void>();
  return {
    set(target, text) {
      if (!target.hasUI) return;
      value = text;
      target.ui.setStatus(STATUS_SLOT_PERK, text);
      for (const listener of listeners) listener();
    },
    get() {
      return value;
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

// --- the perk-owned footer (charter D2) -----------------------------------------------

/**
 * The raw material for one composed footer line. Left group (charter order 1–2): `identity`,
 * `objective` — the segment renders verbatim (it carries its own 🎯 mark).
 * Right group (charter order 4, 5, +context, 6): `branch`, `model`, `thinking`, `cache`,
 * `context`, `guests` — right-aligned, non-segment system text dim-themed.
 */
export interface FooterParts {
  /** e.g. `perk v0.0.1` — standing identity (D7), dim. */
  identity: string;
  /** The 🎯 objective segment, verbatim (`handle.get()`). */
  objective?: string;
  /** Git branch (dim); omitted when not in a repo. */
  branch?: string;
  /** Model id (dim); omitted when no model. */
  model?: string;
  /** The session thinking level (dim; e.g. `high`/`off`); omitted when there is no model. */
  thinking?: string;
  /** The prompt-cache-hit segment, e.g. `CH42.3%` (dim; right group); omitted until cache activity. */
  cache?: string;
  /** Context usage — rendered `<pct>%/<window>` (dim; warning >70, error >90; `?` when null). */
  context?: { percent: number | null; contextWindow: number };
  /** Guest extension statuses (dim), pre-sorted by slot key; sanitized here. */
  guests: string[];
}

/**
 * A structural slice of pi's `SessionEntry` — only what `latestCacheHitRate` reads. Keeps
 * surfaces.ts dependency-light (no pi imports; `SessionEntry[]` is assignable) — the same
 * structural-mirror pattern as `FooterDataLike`/`ThemeLike`.
 */
export interface UsageEntryLike {
  type: string;
  message?: {
    role?: string;
    usage?: { input: number; cacheRead: number; cacheWrite: number };
  };
  /** Entry-level usage on `branch_summary`/`compaction` entries (pi 0.81.0 usage accounting). */
  usage?: { input: number; cacheRead: number; cacheWrite: number };
}

/**
 * The prompt-cache-hit rate of the latest usage-bearing assistant message, as a percentage —
 * an exact local mirror of pi 0.84.1's default-footer `CH` computation (pi's cache-stats helpers
 * are unexported; the `sanitizeGuestStatus` reimplementation precedent). Includes pi's display
 * gate: returns `null` unless the session shows cache activity — total cacheRead or cacheWrite
 * > 0 summed over assistant messages, `toolResult` messages carrying `usage`, and
 * `branch_summary`/`compaction` entries' entry-level `usage` — AND the latest usage-bearing
 * assistant message has prompt tokens > 0 (a trailing zero-prompt-token assistant message resets
 * the rate, exactly like pi's `undefined`). The CH VALUE always comes from the latest
 * usage-bearing assistant message; the non-assistant entries only widen the activity gate.
 */
export function latestCacheHitRate(entries: readonly UsageEntryLike[]): number | null {
  let totalCacheRead = 0;
  let totalCacheWrite = 0;
  let latest: number | null = null;
  for (const entry of entries) {
    if (entry.type === "message" && entry.message?.role === "assistant") {
      const usage = entry.message.usage;
      if (usage === undefined) continue;
      totalCacheRead += usage.cacheRead;
      totalCacheWrite += usage.cacheWrite;
      const promptTokens = usage.input + usage.cacheRead + usage.cacheWrite;
      latest = promptTokens > 0 ? (usage.cacheRead / promptTokens) * 100 : null;
    } else if (entry.type === "message" && entry.message?.role === "toolResult") {
      const usage = entry.message.usage;
      if (usage === undefined) continue;
      totalCacheRead += usage.cacheRead;
      totalCacheWrite += usage.cacheWrite;
    } else if (
      (entry.type === "branch_summary" || entry.type === "compaction") &&
      entry.usage !== undefined
    ) {
      totalCacheRead += entry.usage.cacheRead;
      totalCacheWrite += entry.usage.cacheWrite;
    }
  }
  if (totalCacheRead <= 0 && totalCacheWrite <= 0) return null;
  return latest;
}

/** Pi's `sanitizeStatusText` behavior, reimplemented locally (pi does not export it). */
function sanitizeGuestStatus(text: string): string {
  return text
    .replace(/[\r\n\t]/g, " ")
    .replace(/ +/g, " ")
    .trim();
}

/** The context segment, mirroring pi's default footer: `42.3%/200k`, `?/200k` when unknown. */
function formatContextSegment(
  context: { percent: number | null; contextWindow: number },
  theme: ThemeLike,
): string {
  const pct = context.percent;
  const text = `${pct === null ? "?" : `${pct.toFixed(1)}%`}/${formatTokens(context.contextWindow)}`;
  if (pct !== null && pct > 90) return theme.fg("error", text);
  if (pct !== null && pct > 70) return theme.fg("warning", text);
  return theme.fg("dim", text);
}

/**
 * Compose THE one footer line (FOOTER_MAX_LINES = 1): left group = identity + objective
 * (two-space-joined, charter order); right group = branch + model + context + guests
 * (two-space-joined), right-aligned with ≥2 spaces of padding. When the line exceeds `width`,
 * whole segments drop in the extended D9 order — guests (rightmost-first) → thinking → model →
 * branch → cache → context; `identity` and `objective` are NEVER dropped — then
 * `truncateToWidth` as the last resort (ANSI- and 2-cell-emoji-aware).
 */
export function composeFooterLine(parts: FooterParts, theme: ThemeLike, width: number): string {
  const keep = {
    guests: parts.guests.map((g) => sanitizeGuestStatus(g)),
    model: true,
    thinking: true,
    branch: true,
    cache: true,
    context: true,
  };
  const compose = (): string => {
    const left = [theme.fg("dim", parts.identity)];
    if (parts.objective !== undefined) left.push(parts.objective);
    const right: string[] = [];
    if (keep.branch && parts.branch !== undefined) right.push(theme.fg("dim", parts.branch));
    if (keep.model && parts.model !== undefined) right.push(theme.fg("dim", parts.model));
    if (keep.thinking && parts.thinking !== undefined) right.push(theme.fg("dim", parts.thinking));
    if (keep.cache && parts.cache !== undefined) right.push(theme.fg("dim", parts.cache));
    if (keep.context && parts.context !== undefined) {
      right.push(formatContextSegment(parts.context, theme));
    }
    for (const guest of keep.guests) right.push(theme.fg("dim", guest));
    const leftText = left.join("  ");
    if (right.length === 0) return leftText;
    const rightText = right.join("  ");
    const padding = Math.max(2, width - visibleWidth(leftText) - visibleWidth(rightText));
    return `${leftText}${" ".repeat(padding)}${rightText}`;
  };
  let line = compose();
  while (visibleWidth(line) > width) {
    if (keep.guests.length > 0) keep.guests.pop();
    else if (keep.thinking) keep.thinking = false;
    else if (keep.model) keep.model = false;
    else if (keep.branch) keep.branch = false;
    else if (keep.cache) keep.cache = false;
    else if (keep.context) keep.context = false;
    else break; // identity + objective only — nothing left to drop
    line = compose();
  }
  return truncateToWidth(line, width);
}

/**
 * Structural mirror of pi's `ReadonlyFooterDataProvider` (keeps surfaces.ts dependency-light;
 * the real provider satisfies it).
 */
export interface FooterDataLike {
  getGitBranch(): string | null;
  getExtensionStatuses(): ReadonlyMap<string, string>;
  onBranchChange(callback: () => void): () => void;
}

/** What `perkFooter` needs from the extension: identity, the status handle, and live closures. */
export interface PerkFooterDeps {
  identity: string;
  status: PerkStatusHandle;
  getModelId(): string | null;
  getThinkingLevel(): string | null;
  getCacheHitRate(): number | null;
  getContext(): { percent: number | null; contextWindow: number } | null;
}

/**
 * The footer component factory shape `setFooter` receives. Pi's real signature —
 * `(tui: TUI, theme: Theme, footerData: ReadonlyFooterDataProvider) => Component & { dispose?() }`
 * — satisfies this narrower structural type.
 */
export type PerkFooterFactory = (
  tui: { requestRender(): void },
  theme: ThemeLike,
  footerData: FooterDataLike,
) => { render(width: number): string[]; invalidate(): void; dispose(): void };

/**
 * The perk-owned footer factory (charter D2): replaces pi's default footer wholesale with one
 * line in the intended split layout. `render` gathers everything live per call (D10 stateless
 * render): the objective value via the handle, branch/guests via `footerData` (excluding perk's
 * own `STATUS_SLOT_PERK` — the slot keeps publishing for RPC, but the footer renders the value
 * directly), model/cache/context via the deps closures. Reactivity (the D2 contract): repaints on
 * every handle recompose and on branch change; `dispose` detaches both. Lifecycle (pi ≥ 0.84,
 * verified at 0.84.1): `setExtensionFooter` disposes a replaced factory's component, and pi's
 * `resetExtensionUI` restores the built-in footer (disposing this one) on /reload and before
 * session replacement — so installing a fresh factory per headful `session_start` leaks nothing.
 *
 * Two DELIBERATE divergences from pi's default footer remain: no `(auto)` context suffix
 * (auto-compact state is not extension-readable) and no cost/`(sub)` segment (charter scope).
 */
export function perkFooter(deps: PerkFooterDeps): PerkFooterFactory {
  return (tui, theme, footerData) => {
    const unsubscribeStatus = deps.status.subscribe(() => tui.requestRender());
    const unsubscribeBranch = footerData.onBranchChange(() => tui.requestRender());
    return {
      render(width) {
        const guests = [...footerData.getExtensionStatuses().entries()]
          .filter(([key]) => key !== STATUS_SLOT_PERK)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([, text]) => text);
        const rate = deps.getCacheHitRate();
        const parts: FooterParts = {
          identity: deps.identity,
          objective: deps.status.get(),
          branch: footerData.getGitBranch() ?? undefined,
          model: deps.getModelId() ?? undefined,
          thinking: deps.getThinkingLevel() ?? undefined,
          cache: rate === null ? undefined : `CH${rate.toFixed(1)}%`,
          context: deps.getContext() ?? undefined,
          guests,
        };
        return [composeFooterLine(parts, theme, width)];
      },
      invalidate() {
        // nothing cached — render() recomputes everything per call (D10)
      },
      dispose() {
        unsubscribeStatus();
        unsubscribeBranch();
      },
    };
  };
}

/**
 * Install the perk-owned footer (sole-owner law, D2); no-op headless. Safe to call on every
 * headful `session_start`: pi ≥ 0.84 disposes the replaced factory (see `perkFooter`).
 */
export function installPerkFooter(
  target: { hasUI: boolean; ui: { setFooter(factory: PerkFooterFactory | undefined): void } },
  deps: PerkFooterDeps,
): void {
  if (!target.hasUI) return;
  target.ui.setFooter(perkFooter(deps));
}

// --- format helpers --------------------------------------------------------------------------

/** Pi 0.84.1's default-footer `formatTokens` tiers, mirrored exactly (`200000` → `200k`). */
function formatTokens(tokens: number): string {
  if (tokens < 1000) return `${tokens}`;
  if (tokens < 10_000) return `${(tokens / 1000).toFixed(1)}k`;
  if (tokens < 1_000_000) return `${Math.round(tokens / 1000)}k`;
  if (tokens < 10_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  return `${Math.round(tokens / 1_000_000)}M`;
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

// --- the transcript markers — display-only entry renderers ---------------------------------------
// The audit §2.3 verdict (docs/design/pi-adoption-audit.md): perk's display-only custom-entry
// families render as durable one-line transcript markers. Renderer BODIES live here (a transcript
// renderer IS a rich-UI surface the surfaces module owns); registration is wiring at the feature
// modules via the `registerTranscriptRenderer` seam below. Renderers are an interactive-TUI-only
// concern (never invoked in json/RPC mode), so registration is inert-safe everywhere.

/** Structural slice of pi's `CustomEntry` — the only field the marker renderers read. */
export interface TranscriptEntryLike {
  data?: unknown;
}

/** Structural mirror of pi's `EntryRenderOptions`. */
export interface EntryRenderOptionsLike {
  expanded: boolean;
}

/**
 * A transcript entry renderer, assignable to pi's `EntryRenderer<unknown>`: the params are
 * structural supertypes of pi's (`CustomEntry`/`EntryRenderOptions`/`Theme`), and the returned
 * object satisfies pi-tui's structural `Component` (`render(width): string[]`; `handleInput` is
 * optional). `undefined` = render nothing (malformed/missing `data` stays invisible — exactly the
 * pre-renderer behavior).
 */
export type TranscriptRenderer = (
  entry: TranscriptEntryLike,
  options: EntryRenderOptionsLike,
  theme: ThemeLike,
) => { render(width: number): string[] } | undefined;

/**
 * The minimal host surface the registration seam needs. The member is OPTIONAL and
 * method-syntax (bivariant — the `PerkFooterFactory` recipe): pi ≥ 0.80.4's `ExtensionAPI`
 * satisfies it; pre-0.80.4 hosts simply don't have the method.
 */
export interface TranscriptRendererHost {
  registerEntryRenderer?(customType: string, renderer: TranscriptRenderer): void;
}

/**
 * The one sanctioned `registerEntryRenderer` call site (guard-confined) carrying the one typeof
 * feature-detect: on a pre-0.80.4 host the method is absent (calling it would `TypeError`), so
 * registration is a silent no-op and the entries stay invisible — exactly today's behavior.
 */
export function registerTranscriptRenderer(
  host: TranscriptRendererHost,
  customType: string,
  renderer: TranscriptRenderer,
): void {
  if (typeof host.registerEntryRenderer !== "function") return; // pre-0.80.4 host: inert
  host.registerEntryRenderer(customType, renderer);
}

/**
 * Charter budget: a COLLAPSED transcript marker is exactly one line. The expanded view is
 * human-requested scrollback and renders its full detail unbounded (the whole btw answer).
 */
export const TRANSCRIPT_MARKER_MAX_LINES = 1;

/**
 * The collapsed-marker grammar: the `report()` transition grammar `perk: <scope> — <message>`,
 * dim, D9-truncated. Emoji stay footer-only (D3).
 */
function markerLine(scope: string, message: string, theme: ThemeLike, width: number): string {
  return truncateToWidth(theme.fg("dim", `perk: ${scope} — ${message}`), width);
}

/** The three-clause object-shape guard: a plain (non-null, non-array) object or null. */
function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

/**
 * The first matching workflow-state field's marker message — a deliberately BOUNDED vocabulary
 * (the four headline fields + a SET `objective_node_claim`), extensible later. Bookkeeping deltas
 * (`session_artifacts`, `last_review*`, `conflict_resolution_attempts`, cleared node claims) stay
 * invisible by returning null.
 */
function workflowStateMessage(data: Record<string, unknown>): string | null {
  if (typeof data.run_id === "string") {
    if (typeof data.predecessor === "string") {
      return `run ${data.run_id} · child of ${data.predecessor}`;
    }
    let message = `run ${data.run_id} claimed`;
    if (typeof data.stage === "string") message += ` · stage ${data.stage}`;
    if (typeof data.mode === "string") message += ` · ${data.mode}`;
    return message;
  }
  if (typeof data.mode === "string") return `${data.mode} mode`;
  // Key-presence check (not value truthiness): an explicit null means "cleared" here.
  if (Object.hasOwn(data, "active_objective")) {
    if (typeof data.active_objective === "string") {
      return `objective ${data.active_objective} activated`;
    }
    if (data.active_objective === null) return "objective cleared";
  }
  const planRef = asRecord(data.active_plan_ref);
  if (planRef !== null && typeof planRef.pr_id === "string") {
    return `plan ${planRef.pr_id} linked`;
  }
  const claim = asRecord(data.objective_node_claim);
  if (claim !== null && typeof claim.objective === "string" && typeof claim.node === "string") {
    // A cleared claim (null) stays invisible — only the SET claim is a marker-worthy moment.
    return `node ${claim.node} claimed for objective ${claim.objective}`;
  }
  return null;
}

/**
 * `perk:workflow-state` marker: the first matching headline field renders (precedence:
 * run claim/fork → mode flip → objective set/clear → plan link → node claim); bookkeeping-only
 * deltas stay invisible. Expanded: the collapsed line + the raw delta as one dim JSON line
 * (/learn-grade debuggability).
 */
export const workflowStateEntryRenderer: TranscriptRenderer = (entry, options, theme) => {
  const data = asRecord(entry.data);
  if (data === null) return undefined;
  const message = workflowStateMessage(data);
  if (message === null) return undefined;
  return {
    render(width) {
      const collapsed = markerLine("workflow", message, theme, width);
      if (!options.expanded) return [collapsed];
      return [collapsed, truncateToWidth(theme.fg("dim", JSON.stringify(data)), width)];
    },
  };
};

/**
 * `perk:objective-budget` marker (`{ objective_id, activated_at }` activation entries).
 * Collapsed: `perk: objective — <id> budget tracking started`. Expanded: + a dim activation
 * timestamp line.
 */
export const objectiveBudgetEntryRenderer: TranscriptRenderer = (entry, options, theme) => {
  const data = asRecord(entry.data);
  if (data === null) return undefined;
  const objectiveId = data.objective_id;
  const activatedAt = data.activated_at;
  if (typeof objectiveId !== "string" || typeof activatedAt !== "string") return undefined;
  return {
    render(width) {
      const collapsed = markerLine(
        "objective",
        `${objectiveId} budget tracking started`,
        theme,
        width,
      );
      if (!options.expanded) return [collapsed];
      return [collapsed, truncateToWidth(theme.fg("dim", `activated at ${activatedAt}`), width)];
    },
  };
};

/**
 * `btw-thread-entry` marker. Collapsed: `perk: btw — <first line of question>` (dim). Expanded:
 * the question line accented + the answer split on newlines, each line dim + width-truncated —
 * no wrapping (a bounded choice: the marker is a durable pointer; the `/btw` overlay remains the
 * full reader).
 */
export const btwThreadEntryRenderer: TranscriptRenderer = (entry, options, theme) => {
  const data = asRecord(entry.data);
  if (data === null) return undefined;
  const question = data.question;
  const answer = data.answer;
  if (typeof question !== "string" || typeof answer !== "string") return undefined;
  const headline = question.split("\n", 1)[0] ?? "";
  return {
    render(width) {
      if (!options.expanded) return [markerLine("btw", headline, theme, width)];
      return [
        truncateToWidth(theme.fg("accent", `perk: btw — ${headline}`), width),
        ...answer.split("\n").map((line) => truncateToWidth(theme.fg("dim", line), width)),
      ];
    },
  };
};

/** `btw-thread-reset` marker: `perk: btw — thread reset` (+ a dim ISO timestamp line expanded). */
export const btwThreadResetEntryRenderer: TranscriptRenderer = (entry, options, theme) => {
  const data = asRecord(entry.data);
  if (data === null) return undefined;
  const timestamp = data.timestamp;
  if (typeof timestamp !== "number" || !Number.isFinite(timestamp)) return undefined;
  return {
    render(width) {
      const collapsed = markerLine("btw", "thread reset", theme, width);
      if (!options.expanded) return [collapsed];
      return [
        collapsed,
        truncateToWidth(theme.fg("dim", new Date(timestamp).toISOString()), width),
      ];
    },
  };
};
