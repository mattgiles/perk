// Tests for the perk surfaces module (Objective #251, node 2.1): pins the charter-law vocabulary
// (slot keys, marks, glyphs, height bounds — `docs/design/tui-charter.md` §4/§5), unit-tests the
// `setStanding` headless-safe setter, and covers the relocated format helpers.

import assert from "node:assert/strict";
import { test } from "node:test";
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
  progressLine,
  report,
  STATUS_SLOT_CHECKPOINTS,
  STATUS_SLOT_OBJECTIVE,
  type StandingTarget,
  setStanding,
  stepGlyph,
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
  value: string | string[] | undefined;
}

function fakeTarget(hasUI: boolean): { target: StandingTarget; calls: Call[] } {
  const calls: Call[] = [];
  const target: StandingTarget = {
    hasUI,
    ui: {
      setStatus(slot, value) {
        calls.push({ kind: "status", slot, value });
      },
      setWidget(slot, value) {
        calls.push({ kind: "widget", slot, value });
      },
    },
  };
  return { target, calls };
}

test("setStanding (headful): sets the paired status + widget", () => {
  const { target, calls } = fakeTarget(true);
  setStanding(target, "perk-checkpoints", { status: "📋 1/2", widget: ["☑ 1. a", "▶ 2. b"] });
  assert.deepEqual(calls, [
    { kind: "status", slot: "perk-checkpoints", value: "📋 1/2" },
    { kind: "widget", slot: "perk-checkpoints", value: ["☑ 1. a", "▶ 2. b"] },
  ]);
});

test("setStanding (headful): undefined clears both slots", () => {
  const { target, calls } = fakeTarget(true);
  setStanding(target, "perk-objective", undefined);
  assert.deepEqual(calls, [
    { kind: "status", slot: "perk-objective", value: undefined },
    { kind: "widget", slot: "perk-objective", value: undefined },
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
    "1/2 · ▶2",
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

test("stepGlyph: ☑ completed, ▶ current, ☐ pending (charter-retired set, replaced in node 2.2)", () => {
  const s = state(
    [
      [1, "a", true],
      [2, "b", false],
      [3, "c", false],
    ],
    2,
  );
  assert.equal(stepGlyph(s, s.steps[0] as never), "☑");
  assert.equal(stepGlyph(s, s.steps[1] as never), "▶");
  assert.equal(stepGlyph(s, s.steps[2] as never), "☐");
});

test("formatBudgetLine: tokens + elapsed", () => {
  assert.equal(formatBudgetLine({ tokens: 12_345, elapsedMs: 65_000 }), "12.3k tok · 1m");
  assert.equal(formatBudgetLine({ tokens: 500, elapsedMs: 5_000 }), "500 tok · 5s");
  assert.equal(formatBudgetLine({ tokens: 0, elapsedMs: 3_700_000 }), "0 tok · 1h1m");
});
