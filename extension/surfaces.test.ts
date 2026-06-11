// Tests for the perk surfaces module (Objective #251, nodes 2.1/2.2): pins the charter-law
// vocabulary (slot keys, marks, glyphs, height bounds — `docs/design/tui-charter.md` §4/§5),
// unit-tests the `setStanding` headless-safe setter (string[] + factory + placement forms), the
// D1 `windowProgress` windower, the themed `renderProgressLines` renderer, and the format helpers.

import assert from "node:assert/strict";
import { test } from "node:test";
import { visibleWidth } from "@earendil-works/pi-tui";
import {
  CHECKPOINTS_WIDGET_MAX_LINES,
  FOOTER_MAX_LINES,
  formatBudgetLine,
  GLYPHS,
  MARK_CHECKPOINTS,
  MARK_OBJECTIVE,
  NOTIFY_MAX_LINES,
  OBJECTIVE_WIDGET_MAX_LINES,
  type ProgressState,
  type ProgressWindowItem,
  progressLine,
  renderProgressLines,
  report,
  STATUS_SLOT_CHECKPOINTS,
  STATUS_SLOT_OBJECTIVE,
  type StandingTarget,
  setStanding,
  stepGlyphKind,
  type ThemeLike,
  windowProgress,
} from "./surfaces.ts";

// --- charter vocabulary pins (§2/§4/§5) ----------------------------------------------------------

test("slot keys + footer marks match the charter §2/§5 inventory", () => {
  assert.equal(STATUS_SLOT_CHECKPOINTS, "perk-checkpoints");
  assert.equal(STATUS_SLOT_OBJECTIVE, "perk-objective");
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
  assert.equal(OBJECTIVE_WIDGET_MAX_LINES, 2);
});

test("surfaces.ts re-exports the report seam", () => {
  assert.equal(typeof report, "function");
});

// --- setStanding ----------------------------------------------------------------------------------

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

test("setStanding (headful): sets the paired status + widget", () => {
  const { target, calls } = fakeTarget(true);
  setStanding(target, "perk-checkpoints", { status: "📋 1/2", widget: ["✓ 1. a", "▸ 2. b"] });
  assert.deepEqual(calls, [
    { kind: "status", slot: "perk-checkpoints", value: "📋 1/2" },
    { kind: "widget", slot: "perk-checkpoints", value: ["✓ 1. a", "▸ 2. b"], options: undefined },
  ]);
});

test("setStanding (headful): factory widget + placement forwarded as setWidget options", () => {
  const { target, calls } = fakeTarget(true);
  const factory = (_tui: unknown, theme: ThemeLike) => ({
    render: (_width: number) => [theme.fg("dim", "line")],
    invalidate: () => {},
  });
  setStanding(target, "perk-checkpoints", {
    status: "📋 1/2",
    widget: factory,
    placement: "belowEditor",
  });
  const widget = calls.find((c) => c.kind === "widget");
  assert.equal(widget?.value, factory, "the factory is forwarded as-is");
  assert.deepEqual(widget?.options, { placement: "belowEditor" });
});

test("setStanding (headful): undefined clears both slots", () => {
  const { target, calls } = fakeTarget(true);
  setStanding(target, "perk-objective", undefined);
  assert.deepEqual(calls, [
    { kind: "status", slot: "perk-objective", value: undefined },
    { kind: "widget", slot: "perk-objective", value: undefined, options: undefined },
  ]);
});

test("setStanding (headless): a no-op — never touches the UI", () => {
  const { target, calls } = fakeTarget(false);
  setStanding(target, "perk-checkpoints", { status: "📋 1/2", widget: ["☑ 1. a"] });
  setStanding(target, "perk-checkpoints", undefined);
  assert.deepEqual(calls, []);
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
