// Tests for the perk surfaces module: pins the charter-law
// vocabulary (slot keys, marks, glyphs, height bounds — `docs/design/tui-charter.md` §4/§5),
// unit-tests the composed `createPerkStatus` handle (D2 segment order + two-space join + headless
// no-op) and the `setStandingWidget` headless-safe setter (string[] + factory + placement forms),
// the D1 `windowProgress` windower, the themed `renderProgressLines` renderer, and the helpers.

import assert from "node:assert/strict";
import { test } from "node:test";
import { visibleWidth } from "@earendil-works/pi-tui";
import {
  CHECKPOINTS_WIDGET_MAX_LINES,
  composeFooterLine,
  createPerkStatus,
  FOOTER_MAX_LINES,
  type FooterDataLike,
  type FooterParts,
  formatBudgetLine,
  GLYPHS,
  installPerkFooter,
  MARK_CHECKPOINTS,
  MARK_OBJECTIVE,
  NOTIFY_MAX_LINES,
  type ProgressState,
  type ProgressWindowItem,
  perkFooter,
  progressLine,
  renderProgressLines,
  report,
  STATUS_SLOT_PERK,
  type StandingTarget,
  setStandingWidget,
  setWorkingMessage,
  stepGlyphKind,
  type ThemeLike,
  WIDGET_SLOT_CHECKPOINTS,
  type WorkingMessageTarget,
  windowProgress,
} from "./surfaces.ts";

// --- charter vocabulary pins (§2/§4/§5) ----------------------------------------------------------

test("slot keys + footer marks match the charter §2/§5 inventory", () => {
  assert.equal(STATUS_SLOT_PERK, "perk");
  assert.equal(WIDGET_SLOT_CHECKPOINTS, "perk-checkpoints");
  assert.equal(MARK_CHECKPOINTS, "📋");
  assert.equal(MARK_OBJECTIVE, "🎯");
});

test("glyph vocabulary matches the charter §5 / D3 table", () => {
  assert.deepEqual(GLYPHS, {
    done: { glyph: "✓", themeColor: "success" },
    current: { glyph: "▸", themeColor: "accent" },
    pending: { glyph: "○", themeColor: "dim" },
    warning: { glyph: "⚠", themeColor: "warning" },
    failure: { glyph: "✗", themeColor: "error" },
  });
});

test("height bounds match the charter §4 / D1/D8 budgets", () => {
  assert.equal(NOTIFY_MAX_LINES, 1);
  assert.equal(FOOTER_MAX_LINES, 1);
  assert.equal(CHECKPOINTS_WIDGET_MAX_LINES, 4);
});

test("surfaces.ts re-exports the report seam", () => {
  assert.equal(typeof report, "function");
});

// --- setWorkingMessage seam (vendored `whimsical`; charter §6 text-only, headless-no-op) ----------

test("setWorkingMessage forwards the message (and undefined) when hasUI", () => {
  const calls: (string | undefined)[] = [];
  const target: WorkingMessageTarget = {
    hasUI: true,
    ui: { setWorkingMessage: (message) => calls.push(message) },
  };
  setWorkingMessage(target, "Schlepping...");
  setWorkingMessage(target); // undefined restores pi's default
  assert.deepEqual(calls, ["Schlepping...", undefined]);
});

test("setWorkingMessage no-ops headlessly (never touches rich UI)", () => {
  const calls: (string | undefined)[] = [];
  const target: WorkingMessageTarget = {
    hasUI: false,
    ui: {
      setWorkingMessage: (message) => calls.push(message),
    },
  };
  setWorkingMessage(target, "Schlepping...");
  setWorkingMessage(target);
  assert.deepEqual(calls, []);
});

// --- createPerkStatus (the composed `perk` status, D2) ---------------------------------

interface Call {
  kind: "status" | "widget";
  slot: string;
  value: unknown;
  options?: unknown;
}

function fakeTarget(hasUI: boolean): { target: StandingTarget; calls: Call[] } {
  const calls: Call[] = [];
  const target: StandingTarget = {
    hasUI,
    ui: {
      setStatus(slot, value) {
        calls.push({ kind: "status", slot, value });
      },
      setWidget(slot, value, options) {
        calls.push({ kind: "widget", slot, value, options });
      },
    },
  };
  return { target, calls };
}

test("createPerkStatus: a single segment publishes alone under the `perk` slot", () => {
  const { target, calls } = fakeTarget(true);
  const status = createPerkStatus();
  status.set(target, "objective", "🎯 251 · 1.2k tok · 5m");
  assert.deepEqual(calls, [{ kind: "status", slot: "perk", value: "🎯 251 · 1.2k tok · 5m" }]);

  const other = fakeTarget(true);
  const status2 = createPerkStatus();
  status2.set(other.target, "checkpoints", "📋 1/2");
  assert.deepEqual(other.calls, [{ kind: "status", slot: "perk", value: "📋 1/2" }]);
});

test("createPerkStatus: both segments compose objective-first with a two-space join (D2)", () => {
  const { target, calls } = fakeTarget(true);
  const status = createPerkStatus();
  // Published checkpoints-first — composition order must still be objective → checkpoints.
  status.set(target, "checkpoints", "📋 1/2");
  status.set(target, "objective", "🎯 251 · 1.2k tok · 5m");
  assert.deepEqual(calls.at(-1), {
    kind: "status",
    slot: "perk",
    value: "🎯 251 · 1.2k tok · 5m  📋 1/2",
  });
});

test("createPerkStatus: clearing one segment recomposes; clearing both clears the slot", () => {
  const { target, calls } = fakeTarget(true);
  const status = createPerkStatus();
  status.set(target, "objective", "🎯 251");
  status.set(target, "checkpoints", "📋 1/2");
  status.set(target, "objective", undefined);
  assert.deepEqual(calls.at(-1), { kind: "status", slot: "perk", value: "📋 1/2" });
  status.set(target, "checkpoints", undefined);
  assert.deepEqual(calls.at(-1), { kind: "status", slot: "perk", value: undefined });
});

test("createPerkStatus (headless): a full no-op — no UI calls, no resurrected text", () => {
  const headless = fakeTarget(false);
  const status = createPerkStatus();
  status.set(headless.target, "objective", "🎯 ghost");
  assert.deepEqual(headless.calls, []);
  // A later headful set must not resurrect headless-era text into the composition.
  const headful = fakeTarget(true);
  status.set(headful.target, "checkpoints", "📋 1/2");
  assert.deepEqual(headful.calls, [{ kind: "status", slot: "perk", value: "📋 1/2" }]);
});

// --- setStandingWidget ------------------------------------------------------------------------------

test("setStandingWidget (headful): string[] widget set", () => {
  const { target, calls } = fakeTarget(true);
  setStandingWidget(target, "perk-checkpoints", ["✓ 1. a", "▸ 2. b"]);
  assert.deepEqual(calls, [
    { kind: "widget", slot: "perk-checkpoints", value: ["✓ 1. a", "▸ 2. b"], options: undefined },
  ]);
});

test("setStandingWidget (headful): factory + placement forwarded as setWidget options", () => {
  const { target, calls } = fakeTarget(true);
  const factory = (_tui: unknown, theme: ThemeLike) => ({
    render: (_width: number) => [theme.fg("dim", "line")],
    invalidate: () => {},
  });
  setStandingWidget(target, "perk-checkpoints", factory, { placement: "belowEditor" });
  const widget = calls.find((c) => c.kind === "widget");
  assert.equal(widget?.value, factory, "the factory is forwarded as-is");
  assert.deepEqual(widget?.options, { placement: "belowEditor" });
});

test("setStandingWidget (headful): undefined clears the slot", () => {
  const { target, calls } = fakeTarget(true);
  setStandingWidget(target, "perk-checkpoints", undefined);
  assert.deepEqual(calls, [
    { kind: "widget", slot: "perk-checkpoints", value: undefined, options: undefined },
  ]);
});

test("setStandingWidget (headless): a no-op — never touches the UI", () => {
  const { target, calls } = fakeTarget(false);
  setStandingWidget(target, "perk-checkpoints", ["☑ 1. a"]);
  setStandingWidget(target, "perk-checkpoints", undefined);
  assert.deepEqual(calls, []);
});

// --- createPerkStatus get/subscribe ----------------------------------------------------

test("createPerkStatus: get returns the current segment text (undefined when unset)", () => {
  const { target } = fakeTarget(true);
  const status = createPerkStatus();
  assert.equal(status.get("objective"), undefined);
  status.set(target, "objective", "🎯 251");
  assert.equal(status.get("objective"), "🎯 251");
  assert.equal(status.get("checkpoints"), undefined);
  status.set(target, "objective", undefined);
  assert.equal(status.get("objective"), undefined);
});

test("createPerkStatus: subscribe fires per headful set; never on headless; unsubscribe stops", () => {
  const headful = fakeTarget(true);
  const headless = fakeTarget(false);
  const status = createPerkStatus();
  let fired = 0;
  const unsubscribe = status.subscribe(() => {
    fired += 1;
  });
  status.set(headful.target, "objective", "🎯 251");
  assert.equal(fired, 1);
  status.set(headless.target, "checkpoints", "📋 ghost"); // headless: full no-op, no notify
  assert.equal(fired, 1);
  status.set(headful.target, "checkpoints", "📋 1/2");
  assert.equal(fired, 2);
  unsubscribe();
  status.set(headful.target, "objective", undefined);
  assert.equal(fired, 2);
});

// --- composeFooterLine (charter D2/D9) -------------------------------------------------

/** Passthrough theme for width math (no ANSI / tags). */
const plainTheme: ThemeLike = { fg: (_color, text) => text };

function allParts(): FooterParts {
  return {
    identity: "perk v0.0.1",
    objective: "🎯 251 · 12.3k tok · 5m",
    checkpoints: "📋 1/3 · ▸4",
    branch: "thebranch",
    model: "themodel",
    context: { percent: 42.3, contextWindow: 200_000 },
    guests: ["guestone", "guesttwo"],
  };
}

test("composeFooterLine: charter order, two-space joins, right-aligned with padding", () => {
  const width = 120;
  const line = composeFooterLine(allParts(), plainTheme, width);
  const left = "perk v0.0.1  🎯 251 · 12.3k tok · 5m  📋 1/3 · ▸4";
  const right = "thebranch  themodel  42.3%/200k  guestone  guesttwo";
  assert.ok(line.startsWith(left), `left group leads: ${JSON.stringify(line)}`);
  assert.ok(line.endsWith(right), `right group trails: ${JSON.stringify(line)}`);
  // Right-aligned: padding fills the line out to exactly `width`.
  assert.equal(visibleWidth(line), width);
  assert.ok(/ {2,}/.test(line.slice(left.length, line.length - right.length)));
});

test("composeFooterLine: absent parts are omitted (identity alone composes bare)", () => {
  const line = composeFooterLine({ identity: "perk v0.0.1", guests: [] }, plainTheme, 80);
  assert.equal(line, "perk v0.0.1");
});

test("composeFooterLine: guest statuses are sanitized (newlines/tabs/space runs collapse)", () => {
  const line = composeFooterLine({ identity: "perk", guests: ["a\nb\t  c "] }, plainTheme, 80);
  assert.ok(line.endsWith("a b c"), JSON.stringify(line));
});

test("composeFooterLine: context formats like pi's footer and colors by threshold", () => {
  const tag: ThemeLike = { fg: (color, text) => `<${color}>${text}</>` };
  const ctx = (percent: number | null) =>
    composeFooterLine(
      { identity: "p", context: { percent, contextWindow: 200_000 }, guests: [] },
      tag,
      200,
    );
  assert.ok(ctx(42.3).includes("<dim>42.3%/200k</>"), ctx(42.3));
  assert.ok(ctx(75).includes("<warning>75.0%/200k</>"), ctx(75));
  assert.ok(ctx(95).includes("<error>95.0%/200k</>"), ctx(95));
  assert.ok(ctx(null).includes("<dim>?/200k</>"), ctx(null));
});

test("composeFooterLine: system text is dim; segments render verbatim", () => {
  const tag: ThemeLike = { fg: (color, text) => `<${color}>${text}</>` };
  const line = composeFooterLine(
    {
      identity: "perk v0.0.1",
      objective: "🎯 251",
      checkpoints: "📋 1/3",
      branch: "main",
      model: "gpt-5",
      guests: ["g1"],
    },
    tag,
    400,
  );
  assert.ok(line.includes("<dim>perk v0.0.1</>"));
  assert.ok(line.includes("<dim>main</>"));
  assert.ok(line.includes("<dim>gpt-5</>"));
  assert.ok(line.includes("<dim>g1</>"));
  // segments verbatim — not theme-wrapped
  assert.ok(line.includes("  🎯 251  "));
  assert.ok(line.includes("📋 1/3"));
});

test("composeFooterLine: D9 drop order — guests (rightmost first) → model → branch → context → checkpoints", () => {
  // dropRank: lower drops first. identity + objective are never dropped (rank ∞).
  const droppables: [string, number][] = [
    ["guesttwo", 0],
    ["guestone", 1],
    ["themodel", 2],
    ["thebranch", 3],
    ["42.3%/200k", 4],
    ["📋 1/3 · ▸4", 5],
  ];
  const neverDrop = "perk v0.0.1  🎯 251 · 12.3k tok · 5m";
  const seen = new Set<number>();
  for (let width = 130; width >= visibleWidth(neverDrop); width -= 1) {
    const line = composeFooterLine(allParts(), plainTheme, width);
    // the never-exceed-width law (D9), at every width
    assert.ok(visibleWidth(line) <= width, `width ${width}: ${visibleWidth(line)} > ${width}`);
    // identity + objective always whole at these widths
    assert.ok(line.startsWith(neverDrop), `width ${width}: ${JSON.stringify(line)}`);
    const present = droppables.filter(([text]) => line.includes(text)).map(([, rank]) => rank);
    for (const rank of present) seen.add(rank);
    // drop-order invariant: if rank r survives, every higher rank survives too
    const min = Math.min(...present, Number.POSITIVE_INFINITY);
    for (const [, rank] of droppables) {
      if (rank > min)
        assert.ok(present.includes(rank), `width ${width}: rank ${rank} dropped early`);
    }
  }
  assert.equal(seen.size, 6, "the sweep exercised every droppable");
});

test("composeFooterLine: truncates as a last resort once only identity + objective remain", () => {
  const line = composeFooterLine(allParts(), plainTheme, 20);
  assert.ok(visibleWidth(line) <= 20, `${visibleWidth(line)}: ${JSON.stringify(line)}`);
  assert.ok(line.startsWith("perk v0.0.1"));
  // emoji-aware truncation (🎯 is 2 cells) — still within the budget
  const tiny = composeFooterLine(allParts(), plainTheme, 14);
  assert.ok(visibleWidth(tiny) <= 14, JSON.stringify(tiny));
});

test("composeFooterLine: always exactly one line (no newlines), FOOTER_MAX_LINES stays 1", () => {
  assert.equal(FOOTER_MAX_LINES, 1);
  for (const width of [10, 40, 80, 200]) {
    assert.ok(!composeFooterLine(allParts(), plainTheme, width).includes("\n"));
  }
});

// --- perkFooter / installPerkFooter (D2 reactivity) ------------------------------------

function fakeFooterData(
  opts: { branch?: string | null; statuses?: Map<string, string> } = {},
): FooterDataLike & { fireBranchChange(): void; branchSubscribers(): number } {
  const callbacks = new Set<() => void>();
  return {
    getGitBranch: () => (opts.branch === undefined ? "main" : opts.branch),
    getExtensionStatuses: () => opts.statuses ?? new Map<string, string>(),
    onBranchChange(callback) {
      callbacks.add(callback);
      return () => callbacks.delete(callback);
    },
    fireBranchChange() {
      for (const cb of callbacks) cb();
    },
    branchSubscribers: () => callbacks.size,
  };
}

test("perkFooter: renders exactly one line with live segments, branch, model, context", () => {
  const { target } = fakeTarget(true);
  const status = createPerkStatus();
  status.set(target, "objective", "🎯 251");
  const factory = perkFooter({
    identity: "perk v0.0.1",
    status,
    getModelId: () => "gpt-5",
    getContext: () => ({ percent: 42.3, contextWindow: 200_000 }),
  });
  const component = factory({ requestRender: () => {} }, plainTheme, fakeFooterData());
  const lines = component.render(120);
  assert.equal(lines.length, 1);
  const line = lines[0] as string;
  assert.ok(line.includes("perk v0.0.1  🎯 251"));
  assert.ok(line.includes("main  gpt-5  42.3%/200k"));
  // live read: a later set shows up on the next render (D10 stateless render)
  status.set(target, "checkpoints", "📋 2/3");
  assert.ok((component.render(120)[0] as string).includes("📋 2/3"));
  component.dispose();
});

test("perkFooter: excludes the perk slot from guest statuses, renders others sorted", () => {
  const status = createPerkStatus();
  const factory = perkFooter({
    identity: "perk",
    status,
    getModelId: () => null,
    getContext: () => null,
  });
  const data = fakeFooterData({
    branch: null,
    statuses: new Map([
      ["zeta", "zstatus"],
      ["perk", "🎯 must-not-show"],
      ["alpha", "astatus"],
    ]),
  });
  const component = factory({ requestRender: () => {} }, plainTheme, data);
  const line = component.render(120)[0] as string;
  assert.ok(!line.includes("must-not-show"), line);
  assert.ok(line.endsWith("astatus  zstatus"), line);
  component.dispose();
});

test("perkFooter: repaints on handle set + branch change; dispose detaches both", () => {
  const { target } = fakeTarget(true);
  const status = createPerkStatus();
  const factory = perkFooter({
    identity: "perk",
    status,
    getModelId: () => null,
    getContext: () => null,
  });
  const data = fakeFooterData();
  let renders = 0;
  const component = factory(
    {
      requestRender: () => {
        renders += 1;
      },
    },
    plainTheme,
    data,
  );
  status.set(target, "objective", "🎯 251");
  assert.equal(renders, 1);
  data.fireBranchChange();
  assert.equal(renders, 2);
  component.dispose();
  status.set(target, "objective", "🎯 252");
  data.fireBranchChange();
  assert.equal(renders, 2, "dispose detached both subscriptions");
  assert.equal(data.branchSubscribers(), 0);
});

test("installPerkFooter: installs headful, full no-op headless", () => {
  const status = createPerkStatus();
  const deps = {
    identity: "perk",
    status,
    getModelId: () => null,
    getContext: () => null,
  };
  const installed: unknown[] = [];
  installPerkFooter({ hasUI: true, ui: { setFooter: (factory) => installed.push(factory) } }, deps);
  assert.equal(installed.length, 1);
  assert.equal(typeof installed[0], "function");
  installPerkFooter(
    { hasUI: false, ui: { setFooter: (factory) => installed.push(factory) } },
    deps,
  );
  assert.equal(installed.length, 1, "headless never touches setFooter");
});

// --- relocated format helpers ---------------------------------------------------------------------

function state(steps: [number, string, boolean][], current: number | null): ProgressState {
  return { steps: steps.map(([step, text, completed]) => ({ step, text, completed })), current };
}

test("progressLine: done/total with the current-step suffix", () => {
  assert.equal(
    progressLine(
      state(
        [
          [1, "a", true],
          [2, "b", false],
        ],
        2,
      ),
    ),
    "1/2 · ▸2",
  );
  assert.equal(
    progressLine(
      state(
        [
          [1, "a", true],
          [2, "b", true],
        ],
        null,
      ),
    ),
    "2/2",
  );
});

test("stepGlyphKind: done completed, current in-progress, pending otherwise", () => {
  const s = state(
    [
      [1, "a", true],
      [2, "b", false],
      [3, "c", false],
    ],
    2,
  );
  assert.equal(stepGlyphKind(s, s.steps[0] as never), "done");
  assert.equal(stepGlyphKind(s, s.steps[1] as never), "current");
  assert.equal(stepGlyphKind(s, s.steps[2] as never), "pending");
});

// --- windowProgress (charter D1) -------------------------------------------------------------------

/** Build an n-step state with `completed` for steps < current. */
function nState(n: number, current: number | null): ProgressState {
  return {
    steps: Array.from({ length: n }, (_, i) => ({
      step: i + 1,
      text: `t${i + 1}`,
      completed: current != null ? i + 1 < current : true,
    })),
    current,
  };
}

function shape(items: ProgressWindowItem[]): (string | number)[] {
  return items.map((i) => (i.kind === "step" ? i.step.step : `${i.side}+${i.hidden}`));
}

test("windowProgress: n ≤ cap shows all steps, no markers", () => {
  assert.deepEqual(shape(windowProgress(nState(4, 2), 4)), [1, 2, 3, 4]);
  assert.deepEqual(shape(windowProgress(nState(1, 1), 4)), [1]);
});

test("windowProgress: current at the start — trailing marker only", () => {
  assert.deepEqual(shape(windowProgress(nState(7, 1), 4)), [1, 2, 3, 4, "later+3"]);
});

test("windowProgress: current in the middle — both markers, current second", () => {
  const items = windowProgress(nState(7, 4), 4);
  assert.deepEqual(shape(items), ["earlier+2", 3, 4, 5, 6, "later+1"]);
});

test("windowProgress: current near the end — leading marker only", () => {
  assert.deepEqual(shape(windowProgress(nState(7, 7), 4)), ["earlier+3", 4, 5, 6, 7]);
});

test("windowProgress: all complete anchors at the end", () => {
  assert.deepEqual(shape(windowProgress(nState(6, null), 4)), ["earlier+2", 3, 4, 5, 6]);
});

test("windowProgress: cap honored — never more than cap step items", () => {
  for (const current of [1, 2, 3, 5, 9, 10, null]) {
    const items = windowProgress(nState(10, current as number | null), 4);
    assert.equal(items.filter((i) => i.kind === "step").length, 4, `current=${current}`);
  }
});

// --- renderProgressLines (charter D1/D3/D9/D10) -----------------------------------------------------

const tagTheme: ThemeLike = { fg: (color, text) => `<${color}>${text}</>` };

test("renderProgressLines: themed glyphs, muted done text, dim elision", () => {
  const s = state(
    [
      [1, "alpha", true],
      [2, "beta", false],
      [3, "gamma", false],
    ],
    2,
  );
  assert.deepEqual(renderProgressLines(s, tagTheme, 200), [
    "<success>✓</> <muted>1. alpha</>",
    "<accent>▸</> 2. beta",
    "<dim>○</> 3. gamma",
  ]);
});

test("renderProgressLines: windowed >4 steps render ≤4 step lines + dim elision markers", () => {
  const lines = renderProgressLines(nState(7, 4), tagTheme, 200);
  assert.equal(lines.length, 6, "4 step lines + 2 elision markers");
  assert.equal(lines[0], "<dim>… +2 earlier</>");
  assert.equal(lines.at(-1), "<dim>… +1 later</>");
  assert.ok(lines[2]?.includes("<accent>▸</>"), "current step themed accent");
});

test("renderProgressLines: width-truncates every line (D9)", () => {
  const s = state([[1, "a very long step text that will not fit", false]], 1);
  const lines = renderProgressLines(s, { fg: (_c, t) => t }, 12);
  assert.equal(lines.length, 1);
  const line = lines[0] as string;
  assert.ok(visibleWidth(line) <= 12, `truncated to width: ${JSON.stringify(line)}`);
  assert.ok(visibleWidth(line) < visibleWidth("▸ 1. a very long step text that will not fit"));
});

test("formatBudgetLine: tokens + elapsed", () => {
  assert.equal(formatBudgetLine({ tokens: 12_345, elapsedMs: 65_000 }), "12.3k tok · 1m");
  assert.equal(formatBudgetLine({ tokens: 500, elapsedMs: 5_000 }), "500 tok · 5s");
  assert.equal(formatBudgetLine({ tokens: 0, elapsedMs: 3_700_000 }), "0 tok · 1h1m");
});
