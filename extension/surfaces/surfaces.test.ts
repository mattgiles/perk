// Tests for the perk surfaces module: pins the charter-law
// vocabulary (slot keys, marks, glyphs, height bounds — `docs/design/tui-charter.md` §4/§5),
// unit-tests the single-value `createPerkStatus` handle (publish/clear + headless no-op), the
// transcript marker renderers + `registerTranscriptRenderer` seam (audit §2.3), the footer
// machinery, and the helpers.

import assert from "node:assert/strict";
import { test } from "node:test";
import { visibleWidth } from "@earendil-works/pi-tui";
import {
  btwThreadEntryRenderer,
  btwThreadResetEntryRenderer,
  composeFooterLine,
  createPerkStatus,
  createReportDetailSink,
  FOOTER_MAX_LINES,
  type FooterDataLike,
  type FooterParts,
  formatBudgetLine,
  GLYPHS,
  installPerkFooter,
  Key,
  latestCacheHitRate,
  MARK_OBJECTIVE,
  NOTIFY_MAX_LINES,
  objectiveBudgetEntryRenderer,
  perkFooter,
  REPORT_DETAIL_TYPE,
  registerTranscriptRenderer,
  report,
  reportDetailEntryRenderer,
  STATUS_SLOT_PERK,
  type StandingTarget,
  setWorkingMessage,
  type ThemeLike,
  TRANSCRIPT_MARKER_MAX_LINES,
  type TranscriptRenderer,
  type TranscriptRendererHost,
  type UsageEntryLike,
  type WorkingMessageTarget,
  workflowStateEntryRenderer,
} from "./surfaces.ts";

// --- charter vocabulary pins (§2/§4/§5) ----------------------------------------------------------

test("slot keys + footer marks match the charter §2/§5 inventory", () => {
  assert.equal(STATUS_SLOT_PERK, "perk");
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
  // A collapsed transcript marker is exactly one line (expanded is human-requested scrollback).
  assert.equal(TRANSCRIPT_MARKER_MAX_LINES, 1);
});

test("surfaces.ts re-exports the report seam and the Key keybinding vocabulary", () => {
  assert.equal(typeof report, "function");
  assert.equal(typeof Key.ctrlAlt, "function");
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

// --- createPerkStatus (the single-value `perk` status, D2) ---------------------------------

interface Call {
  slot: string;
  value: string | undefined;
}

function fakeTarget(hasUI: boolean): { target: StandingTarget; calls: Call[] } {
  const calls: Call[] = [];
  const target: StandingTarget = {
    hasUI,
    ui: {
      setStatus(slot, value) {
        calls.push({ slot, value });
      },
    },
  };
  return { target, calls };
}

test("createPerkStatus: the value publishes under the `perk` slot", () => {
  const { target, calls } = fakeTarget(true);
  const status = createPerkStatus();
  status.set(target, "🎯 251 · 1.2k tok · 5m");
  assert.deepEqual(calls, [{ slot: "perk", value: "🎯 251 · 1.2k tok · 5m" }]);
});

test("createPerkStatus: undefined clears the slot", () => {
  const { target, calls } = fakeTarget(true);
  const status = createPerkStatus();
  status.set(target, "🎯 251");
  status.set(target, undefined);
  assert.deepEqual(calls.at(-1), { slot: "perk", value: undefined });
});

test("createPerkStatus (headless): a full no-op — no UI calls, no resurrected text", () => {
  const headless = fakeTarget(false);
  const status = createPerkStatus();
  status.set(headless.target, "🎯 ghost");
  assert.deepEqual(headless.calls, []);
  // Headless-era text must never become visible later: a later headful get() stays unset.
  assert.equal(status.get(), undefined);
  const headful = fakeTarget(true);
  status.set(headful.target, "🎯 251");
  assert.deepEqual(headful.calls, [{ slot: "perk", value: "🎯 251" }]);
  assert.equal(status.get(), "🎯 251");
});

// --- createPerkStatus get/subscribe ----------------------------------------------------

test("createPerkStatus: get returns the current text (undefined when unset)", () => {
  const { target } = fakeTarget(true);
  const status = createPerkStatus();
  assert.equal(status.get(), undefined);
  status.set(target, "🎯 251");
  assert.equal(status.get(), "🎯 251");
  status.set(target, undefined);
  assert.equal(status.get(), undefined);
});

test("createPerkStatus: subscribe fires per headful set; never on headless; unsubscribe stops", () => {
  const headful = fakeTarget(true);
  const headless = fakeTarget(false);
  const status = createPerkStatus();
  let fired = 0;
  const unsubscribe = status.subscribe(() => {
    fired += 1;
  });
  status.set(headful.target, "🎯 251");
  assert.equal(fired, 1);
  status.set(headless.target, "🎯 ghost"); // headless: full no-op, no notify
  assert.equal(fired, 1);
  status.set(headful.target, "🎯 252");
  assert.equal(fired, 2);
  unsubscribe();
  status.set(headful.target, undefined);
  assert.equal(fired, 2);
});

// --- composeFooterLine (charter D2/D9) -------------------------------------------------

/** Passthrough theme for width math (no ANSI / tags). */
const plainTheme: ThemeLike = { fg: (_color, text) => text };

function allParts(): FooterParts {
  return {
    identity: "perk v0.0.1",
    objective: "🎯 251 · 12.3k tok · 5m",
    branch: "thebranch",
    model: "themodel",
    thinking: "high",
    // Digits deliberately distinct from the context fixture (42.3%/200k) so the D9 sweep's
    // `line.includes(...)` presence checks stay unambiguous.
    cache: "CH88.8%",
    context: { percent: 42.3, contextWindow: 200_000 },
    guests: ["guestone", "guesttwo"],
  };
}

test("composeFooterLine: charter order, two-space joins, right-aligned with padding", () => {
  const width = 120;
  const line = composeFooterLine(allParts(), plainTheme, width);
  const left = "perk v0.0.1  🎯 251 · 12.3k tok · 5m";
  const right = "thebranch  themodel  high  CH88.8%  42.3%/200k  guestone  guesttwo";
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
      branch: "main",
      model: "gpt-5",
      thinking: "high",
      cache: "CH88.8%",
      guests: ["g1"],
    },
    tag,
    400,
  );
  assert.ok(line.includes("<dim>perk v0.0.1</>"));
  assert.ok(line.includes("<dim>main</>"));
  assert.ok(line.includes("<dim>gpt-5</>"));
  assert.ok(line.includes("<dim>high</>"));
  assert.ok(line.includes("<dim>CH88.8%</>"));
  assert.ok(line.includes("<dim>g1</>"));
  // the segment renders verbatim — not theme-wrapped
  assert.ok(line.includes("  🎯 251  "));
});

test("composeFooterLine: D9 drop order — guests (rightmost first) → thinking → model → branch → cache → context", () => {
  // dropRank: lower drops first. identity + objective are never dropped (rank ∞).
  const droppables: [string, number][] = [
    ["guesttwo", 0],
    ["guestone", 1],
    ["high", 2],
    ["themodel", 3],
    ["thebranch", 4],
    ["CH88.8%", 5],
    ["42.3%/200k", 6],
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
  assert.equal(seen.size, 7, "the sweep exercised every droppable");
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

test("perkFooter: renders exactly one line with the live objective, branch, model, cache, context", () => {
  const { target } = fakeTarget(true);
  const status = createPerkStatus();
  status.set(target, "🎯 251");
  let rate: number | null = 88.8;
  const factory = perkFooter({
    identity: "perk v0.0.1",
    status,
    getModelId: () => "gpt-5",
    getThinkingLevel: () => "high",
    getCacheHitRate: () => rate,
    getContext: () => ({ percent: 42.3, contextWindow: 200_000 }),
  });
  const component = factory({ requestRender: () => {} }, plainTheme, fakeFooterData());
  const lines = component.render(120);
  assert.equal(lines.length, 1);
  const line = lines[0] as string;
  assert.ok(line.includes("perk v0.0.1  🎯 251"));
  assert.ok(line.includes("main  gpt-5  high  CH88.8%  42.3%/200k"));
  // live read: a later set shows up on the next render (D10 stateless render)
  status.set(target, "🎯 252");
  assert.ok((component.render(120)[0] as string).includes("🎯 252"));
  // a null rate omits the cache segment on the next render (pi's display gate)
  rate = null;
  assert.ok(!(component.render(120)[0] as string).includes("CH"));
  component.dispose();
});

test("perkFooter: excludes the perk slot from guest statuses, renders others sorted", () => {
  const status = createPerkStatus();
  const factory = perkFooter({
    identity: "perk",
    status,
    getModelId: () => null,
    getThinkingLevel: () => null,
    getCacheHitRate: () => null,
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
    getThinkingLevel: () => null,
    getCacheHitRate: () => null,
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
  status.set(target, "🎯 251");
  assert.equal(renders, 1);
  data.fireBranchChange();
  assert.equal(renders, 2);
  component.dispose();
  status.set(target, "🎯 252");
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
    getThinkingLevel: () => null,
    getCacheHitRate: () => null,
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

// --- latestCacheHitRate (the local mirror of pi's footer CH computation) --------------------------

function assistantEntry(usage: {
  input: number;
  cacheRead: number;
  cacheWrite: number;
}): UsageEntryLike {
  return { type: "message", message: { role: "assistant", usage } };
}

test("latestCacheHitRate: empty entries → null", () => {
  assert.equal(latestCacheHitRate([]), null);
});

test("latestCacheHitRate: no cache activity → null (pi's display gate)", () => {
  assert.equal(
    latestCacheHitRate([assistantEntry({ input: 100, cacheRead: 0, cacheWrite: 0 })]),
    null,
  );
});

test("latestCacheHitRate: a single cached entry → the exact pi formula value", () => {
  // cacheRead / (input + cacheRead + cacheWrite) * 100 = 300 / 500 * 100
  assert.equal(
    latestCacheHitRate([assistantEntry({ input: 100, cacheRead: 300, cacheWrite: 100 })]),
    60,
  );
  // cache-write-only still passes the gate (pi renders CH0.0% here)
  assert.equal(
    latestCacheHitRate([assistantEntry({ input: 100, cacheRead: 0, cacheWrite: 100 })]),
    0,
  );
});

test("latestCacheHitRate: the latest usage-bearing assistant entry wins", () => {
  assert.equal(
    latestCacheHitRate([
      assistantEntry({ input: 100, cacheRead: 300, cacheWrite: 100 }),
      assistantEntry({ input: 0, cacheRead: 500, cacheWrite: 0 }),
    ]),
    100,
  );
});

test("latestCacheHitRate: a trailing zero-prompt-token assistant entry resets to null", () => {
  // Mirrors pi exactly: the last recompute sets `undefined` even though totals stay > 0.
  assert.equal(
    latestCacheHitRate([
      assistantEntry({ input: 100, cacheRead: 300, cacheWrite: 100 }),
      assistantEntry({ input: 0, cacheRead: 0, cacheWrite: 0 }),
    ]),
    null,
  );
});

test("latestCacheHitRate: non-message / non-assistant / usage-less entries are ignored", () => {
  assert.equal(
    latestCacheHitRate([
      { type: "custom" },
      {
        type: "message",
        message: { role: "user", usage: { input: 0, cacheRead: 999, cacheWrite: 0 } },
      },
      assistantEntry({ input: 100, cacheRead: 300, cacheWrite: 100 }),
      { type: "message", message: { role: "assistant" } },
    ]),
    60,
  );
});

// --- the widened cache-activity gate (pi 0.84.1 parity): toolResult + entry-level usage ---------

test("latestCacheHitRate: toolResult-only cache activity passes the gate; CH reads the assistant", () => {
  // The only cache activity sits on a `toolResult` message's usage (pi 0.81.0 usage accounting);
  // the CH value still comes from the latest usage-bearing assistant message.
  assert.equal(
    latestCacheHitRate([
      assistantEntry({ input: 100, cacheRead: 0, cacheWrite: 0 }),
      {
        type: "message",
        message: { role: "toolResult", usage: { input: 10, cacheRead: 50, cacheWrite: 0 } },
      },
    ]),
    0,
  );
});

for (const entryType of ["branch_summary", "compaction"] as const) {
  test(`latestCacheHitRate: ${entryType} entry-level usage passes the gate; CH reads the assistant`, () => {
    assert.equal(
      latestCacheHitRate([
        assistantEntry({ input: 100, cacheRead: 0, cacheWrite: 0 }),
        { type: entryType, usage: { input: 10, cacheRead: 0, cacheWrite: 40 } },
      ]),
      0,
    );
  });
}

test("latestCacheHitRate: zero cache activity everywhere (all paths) → null", () => {
  assert.equal(
    latestCacheHitRate([
      assistantEntry({ input: 100, cacheRead: 0, cacheWrite: 0 }),
      {
        type: "message",
        message: { role: "toolResult", usage: { input: 10, cacheRead: 0, cacheWrite: 0 } },
      },
      { type: "branch_summary", usage: { input: 10, cacheRead: 0, cacheWrite: 0 } },
      { type: "compaction", usage: { input: 10, cacheRead: 0, cacheWrite: 0 } },
    ]),
    null,
  );
});

// --- format helpers ---------------------------------------------------------------------

const tagTheme: ThemeLike = { fg: (color, text) => `<${color}>${text}</>` };

test("formatBudgetLine: tokens + elapsed", () => {
  assert.equal(formatBudgetLine({ tokens: 500, elapsedMs: 5_000 }), "500 tok · 5s");
  assert.equal(formatBudgetLine({ tokens: 0, elapsedMs: 3_700_000 }), "0 tok · 1h1m");
  // 12_345 sits in the rounded-k tier under pi 0.84.1's formatTokens (was `12.3k`).
  assert.equal(formatBudgetLine({ tokens: 12_345, elapsedMs: 65_000 }), "12k tok · 1m");
});

test("formatBudgetLine: pi 0.84.1's formatTokens tier boundaries", () => {
  const tok = (tokens: number) => formatBudgetLine({ tokens, elapsedMs: 0 }).split(" tok")[0];
  // Each switch point pinned from BOTH sides (`<`, never `<=` — a `<=` regression flips the
  // at-threshold value into the lower tier and breaks parity with pi's footer).
  assert.equal(tok(999), "999"); // raw tier (< 1000)
  assert.equal(tok(1_000), "1.0k"); // the 1k switch point enters the one-decimal k tier
  assert.equal(tok(9_999), "10.0k"); // one-decimal k tier (< 10k)
  assert.equal(tok(10_000), "10k"); // the 10k switch point enters the rounded k tier
  assert.equal(tok(200_000), "200k"); // rounded k tier — the old `.0`-strip pin falls out here
  assert.equal(tok(234_500), "235k"); // rounded k tier (< 1M)
  assert.equal(tok(999_999), "1000k"); // top of the rounded k tier (pi renders `1000k` too)
  assert.equal(tok(1_000_000), "1.0M"); // the 1M switch point enters the one-decimal M tier
  assert.equal(tok(1_234_500), "1.2M"); // one-decimal M tier (< 10M) — the budget-line M ripple
  assert.equal(tok(9_999_999), "10.0M"); // top of the one-decimal M tier
  assert.equal(tok(10_000_000), "10M"); // the 10M switch point enters the rounded M tier
  assert.equal(tok(12_345_000), "12M"); // rounded M tier
});

// --- registerTranscriptRenderer (the one seam + typeof feature-detect) ----------------------------

test("registerTranscriptRenderer: forwards (customType, renderer) to a hosting registerEntryRenderer", () => {
  const calls: { customType: string; renderer: TranscriptRenderer }[] = [];
  const host: TranscriptRendererHost = {
    registerEntryRenderer(customType, renderer) {
      calls.push({ customType, renderer });
    },
  };
  registerTranscriptRenderer(host, "perk:workflow-state", workflowStateEntryRenderer);
  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.customType, "perk:workflow-state");
  assert.equal(calls[0]?.renderer, workflowStateEntryRenderer);
});

test("registerTranscriptRenderer: a host without the method is a silent no-op (pre-0.80.4)", () => {
  assert.doesNotThrow(() => {
    registerTranscriptRenderer({}, "perk:workflow-state", workflowStateEntryRenderer);
  });
});

// --- generic report-detail transcript entries ----------------------------------------------------

test("createReportDetailSink appends the exact generic type and payload", () => {
  const entries: { customType: string; data?: unknown }[] = [];
  const sink = createReportDetailSink({
    appendEntry(customType, data) {
      entries.push({ customType, data });
    },
  });
  const text = "perk: submit — failed\ncomplete \u001b[2Jdetail\u0007";
  sink(text, "error");
  assert.equal(REPORT_DETAIL_TYPE, "perk:report-detail");
  assert.deepEqual(entries, [
    {
      customType: "perk:report-detail",
      data: { text, severity: "error" },
    },
  ]);
});

// --- the transcript renderers ---------------------------------------------------------------------

/** Render an entry: `undefined` when the renderer declined, else the component's lines. */
function renderMarker(
  renderer: TranscriptRenderer,
  data: unknown,
  opts: { expanded?: boolean; theme?: ThemeLike; width?: number } = {},
): string[] | undefined {
  const component = renderer(
    { data },
    { expanded: opts.expanded ?? false },
    opts.theme ?? tagTheme,
  );
  return component?.render(opts.width ?? 200);
}

test("reportDetailEntryRenderer renders every logical row with live severity styling", () => {
  const text = "perk: submit — failed\r\nfetch first\n\rerror: rejected";
  const expected = [
    "<error>perk: submit — failed</>",
    "<dim>fetch first</>",
    "",
    "<dim>error: rejected</>",
  ];
  assert.deepEqual(renderMarker(reportDetailEntryRenderer, { text, severity: "error" }), expected);
  assert.deepEqual(
    renderMarker(reportDetailEntryRenderer, { text, severity: "error" }, { expanded: true }),
    expected,
  );

  let palette = "first";
  const liveTheme: ThemeLike = { fg: (color, value) => `<${palette}:${color}>${value}</>` };
  const component = reportDetailEntryRenderer(
    { data: { text: "headline\ndetail", severity: "warning" } },
    { expanded: false },
    liveTheme,
  );
  assert.ok(component !== undefined);
  assert.deepEqual(component.render(200), ["<first:warning>headline</>", "<first:dim>detail</>"]);
  palette = "second";
  assert.deepEqual(component.render(200), ["<second:warning>headline</>", "<second:dim>detail</>"]);
});

for (const [severity, firstColor] of [
  ["info", "dim"],
  ["warning", "warning"],
  ["error", "error"],
] as const) {
  test(`reportDetailEntryRenderer styles ${severity} first row ${firstColor}`, () => {
    assert.deepEqual(renderMarker(reportDetailEntryRenderer, { text: "first\nnext", severity }), [
      `<${firstColor}>first</>`,
      "<dim>next</>",
    ]);
  });
}

test("reportDetailEntryRenderer strips terminal controls only from rendered rows", () => {
  const text =
    "perk:\u001b[2J safe\u0007\r\n" +
    "osc\u001b]0;title\u0007 kept\n" +
    "apc\u001b_payload\u001b\\ done\n" +
    "c1\u009b31mred\u009c!";
  assert.deepEqual(renderMarker(reportDetailEntryRenderer, { text, severity: "error" }), [
    "<error>perk: safe</>",
    "<dim>osc kept</>",
    "<dim>apc done</>",
    "<dim>c1red!</>",
  ]);
});

test("reportDetailEntryRenderer rejects malformed data", () => {
  for (const data of [
    undefined,
    null,
    [],
    new Date(),
    Object.create({ text: "text", severity: "info" }),
    {},
    { text: "text" },
    { severity: "info" },
    { text: "", severity: "info" },
    { text: " \r\n\t", severity: "info" },
    { text: 7, severity: "info" },
    { text: "text", severity: "fatal" },
  ]) {
    assert.equal(renderMarker(reportDetailEntryRenderer, data), undefined, JSON.stringify(data));
  }
});

test("reportDetailEntryRenderer truncates every row to the available width", () => {
  const lines = renderMarker(
    reportDetailEntryRenderer,
    { text: "a very long headline\na very long continuation", severity: "info" },
    { theme: plainTheme, width: 10 },
  );
  assert.ok(lines !== undefined);
  assert.equal(lines.length, 2);
  for (const line of lines) assert.ok(visibleWidth(line) <= 10, JSON.stringify(line));
});

// --- the transcript marker renderers ---------------------------------------------------------------

test("workflowStateEntryRenderer: the headline-field vocabulary + precedence", () => {
  const collapsed = (data: unknown) => renderMarker(workflowStateEntryRenderer, data)?.[0];
  // 1. run_id — fork/child form, else claim form with optional stage + mode suffixes.
  assert.equal(
    collapsed({ run_id: "r1.1", predecessor: "r1" }),
    "<dim>perk: workflow — run r1.1 · child of r1</>",
  );
  assert.equal(collapsed({ run_id: "r1" }), "<dim>perk: workflow — run r1 claimed</>");
  assert.equal(
    collapsed({ run_id: "r1", stage: "implement", mode: "read-only" }),
    "<dim>perk: workflow — run r1 claimed · stage implement · read-only</>",
  );
  // Precedence: a run claim beats a bare mode line.
  assert.equal(
    collapsed({ run_id: "r1", mode: "read-only" }),
    "<dim>perk: workflow — run r1 claimed · read-only</>",
  );
  // 2. mode flips.
  assert.equal(collapsed({ mode: "read-only" }), "<dim>perk: workflow — read-only mode</>");
  // 3. active_objective — key presence, null means cleared.
  assert.equal(
    collapsed({ active_objective: "251" }),
    "<dim>perk: workflow — objective 251 activated</>",
  );
  assert.equal(collapsed({ active_objective: null }), "<dim>perk: workflow — objective cleared</>");
  // 4. plan link.
  assert.equal(
    collapsed({ active_plan_ref: { provider: "github", pr_id: "1309" } }),
    "<dim>perk: workflow — plan 1309 linked</>",
  );
  // 5. node claim — SET renders; a cleared (null) claim stays invisible.
  assert.equal(
    collapsed({ objective_node_claim: { objective: "1297", node: "2.2" } }),
    "<dim>perk: workflow — node 2.2 claimed for objective 1297</>",
  );
  assert.equal(collapsed({ objective_node_claim: null }), undefined);
});

test("workflowStateEntryRenderer: bookkeeping deltas + malformed data → undefined", () => {
  for (const data of [
    undefined,
    null,
    "read-only",
    [],
    {},
    { session_artifacts: { "notes.json": {} } },
    { last_review_batch: { pr: 7 } },
    { last_pr_review: { pr: 7 } },
    { last_review: { pr: 7 } },
    { conflict_resolution_attempts: 2 },
    { active_plan_ref: null },
    { active_plan_ref: { pr_id: 1309 } },
  ]) {
    assert.equal(renderMarker(workflowStateEntryRenderer, data), undefined, JSON.stringify(data));
  }
});

test("workflowStateEntryRenderer (expanded): the collapsed line + one dim JSON detail line", () => {
  const data = { mode: "read-only" };
  const lines = renderMarker(workflowStateEntryRenderer, data, { expanded: true });
  assert.deepEqual(lines, [
    "<dim>perk: workflow — read-only mode</>",
    `<dim>${JSON.stringify(data)}</>`,
  ]);
});

test("objectiveBudgetEntryRenderer: collapsed marker + expanded activation line; malformed → undefined", () => {
  const data = { objective_id: "251", activated_at: "2026-07-10T00:00:00Z" };
  assert.deepEqual(renderMarker(objectiveBudgetEntryRenderer, data), [
    "<dim>perk: objective — 251 budget tracking started</>",
  ]);
  assert.deepEqual(renderMarker(objectiveBudgetEntryRenderer, data, { expanded: true }), [
    "<dim>perk: objective — 251 budget tracking started</>",
    "<dim>activated at 2026-07-10T00:00:00Z</>",
  ]);
  for (const bad of [undefined, null, {}, { objective_id: "251" }, { objective_id: 251 }]) {
    assert.equal(renderMarker(objectiveBudgetEntryRenderer, bad), undefined, JSON.stringify(bad));
  }
});

test("btwThreadEntryRenderer: first question line collapsed; accent question + dim answer expanded", () => {
  const data = {
    question: "what is a seam?\n(second line)",
    answer: "a narrow interface\nyou can test through",
  };
  assert.deepEqual(renderMarker(btwThreadEntryRenderer, data), [
    "<dim>perk: btw — what is a seam?</>",
  ]);
  assert.deepEqual(renderMarker(btwThreadEntryRenderer, data, { expanded: true }), [
    "<accent>perk: btw — what is a seam?</>",
    "<dim>a narrow interface</>",
    "<dim>you can test through</>",
  ]);
  for (const bad of [undefined, null, {}, { question: "q" }, { question: "q", answer: 1 }]) {
    assert.equal(renderMarker(btwThreadEntryRenderer, bad), undefined, JSON.stringify(bad));
  }
});

test("btwThreadResetEntryRenderer: thread-reset marker + expanded ISO timestamp; malformed → undefined", () => {
  const data = { timestamp: Date.UTC(2026, 6, 10, 12, 0, 0) };
  assert.deepEqual(renderMarker(btwThreadResetEntryRenderer, data), [
    "<dim>perk: btw — thread reset</>",
  ]);
  assert.deepEqual(renderMarker(btwThreadResetEntryRenderer, data, { expanded: true }), [
    "<dim>perk: btw — thread reset</>",
    "<dim>2026-07-10T12:00:00.000Z</>",
  ]);
  for (const bad of [undefined, null, {}, { timestamp: "now" }, { timestamp: Number.NaN }]) {
    assert.equal(renderMarker(btwThreadResetEntryRenderer, bad), undefined, JSON.stringify(bad));
  }
});

test("transcript markers: every emitted line is width-truncated (D9)", () => {
  const width = 24;
  const long = "a very long piece of content that cannot possibly fit in the narrow width";
  const cases: [TranscriptRenderer, unknown][] = [
    [workflowStateEntryRenderer, { run_id: long, stage: long, mode: long }],
    [objectiveBudgetEntryRenderer, { objective_id: long, activated_at: long }],
    [btwThreadEntryRenderer, { question: long, answer: `${long}\n${long}` }],
    [btwThreadResetEntryRenderer, { timestamp: 0 }],
  ];
  for (const [renderer, data] of cases) {
    for (const expanded of [false, true]) {
      const lines = renderMarker(renderer, data, { expanded, theme: plainTheme, width });
      assert.ok(lines !== undefined && lines.length > 0);
      for (const line of lines) {
        assert.ok(visibleWidth(line) <= width, `≤ ${width}: ${JSON.stringify(line)}`);
      }
    }
  }
});
