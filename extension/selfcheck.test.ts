// Tests for the `/perk-selfcheck` session-wiring verifier: pure probes/report twins, plus a live
// integration that drives a REAL bound session and proves the converged context reached the prompt.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import {
  ambientIndexProbe,
  buildSelfcheckReport,
  MANAGED_AGENTS_MARKER,
  managedAgentsProbe,
  readAmbientIndex,
} from "./selfcheck.ts";
import { loadPerkSession, scaffoldRepo } from "./testing/harness.ts";

// ---------------------------------------------------------------------------
// Pure: ambientIndexProbe
// ---------------------------------------------------------------------------

test("ambientIndexProbe: on-disk index whose content reached the prompt is wired", () => {
  const index = "# routing\n\n- workflow/ — read when …";
  const probe = ambientIndexProbe(index, `preamble\n\n${index}\n\nmore`);
  assert.equal(probe.onDisk, true);
  assert.equal(probe.reachedPrompt, true);
  assert.equal(probe.wired, true);
  assert.ok(probe.promptChars > index.length);
});

test("ambientIndexProbe: on-disk index NOT in the prompt is a wiring gap", () => {
  const probe = ambientIndexProbe("# routing index", "an unrelated append");
  assert.equal(probe.onDisk, true);
  assert.equal(probe.reachedPrompt, false);
  assert.equal(probe.wired, false);
});

test("ambientIndexProbe: matches on trimmed content (verbatim load + join newlines)", () => {
  const index = "\n\n## Durable learnings\n- pi/ — context\n\n";
  const probe = ambientIndexProbe(index, `x\n\n${index.trim()}\n\ny`);
  assert.equal(probe.reachedPrompt, true);
});

test("ambientIndexProbe: absent on-disk index is wired (nothing to splice yet)", () => {
  const probe = ambientIndexProbe(null, "append without an index");
  assert.equal(probe.onDisk, false);
  assert.equal(probe.reachedPrompt, false);
  assert.equal(probe.wired, true);
});

test("ambientIndexProbe: undefined appendSystemPrompt counts zero chars", () => {
  const probe = ambientIndexProbe(null, undefined);
  assert.equal(probe.promptChars, 0);
  assert.equal(probe.wired, true);
});

// ---------------------------------------------------------------------------
// Pure: managedAgentsProbe
// ---------------------------------------------------------------------------

test("managedAgentsProbe: a context file carrying the managed marker reached the prompt", () => {
  const probe = managedAgentsProbe([
    { path: "/repo/AGENTS.md", content: `# AGENTS\n${MANAGED_AGENTS_MARKER}\n…` },
    { path: "/repo/sub/AGENTS.md", content: "no marker here" },
  ]);
  assert.equal(probe.contextFileCount, 2);
  assert.equal(probe.reachedPrompt, true);
});

test("managedAgentsProbe: no marker anywhere is a wiring gap", () => {
  const probe = managedAgentsProbe([{ path: "/repo/AGENTS.md", content: "plain agents" }]);
  assert.equal(probe.reachedPrompt, false);
});

test("managedAgentsProbe: undefined context files is empty, not a throw", () => {
  const probe = managedAgentsProbe(undefined);
  assert.equal(probe.contextFileCount, 0);
  assert.equal(probe.reachedPrompt, false);
});

// ---------------------------------------------------------------------------
// Pure: buildSelfcheckReport
// ---------------------------------------------------------------------------

test("buildSelfcheckReport: all wired → ok + info", () => {
  const index = "# routing index";
  const report = buildSelfcheckReport({
    version: "1.2.3",
    sharedOk: true,
    onDiskIndex: index,
    options: {
      appendSystemPrompt: `head\n\n${index}`,
      contextFiles: [{ path: "AGENTS.md", content: MANAGED_AGENTS_MARKER }],
    },
  });
  assert.equal(report.ok, true);
  assert.equal(report.level, "info");
  assert.match(report.summary, /perk 1\.2\.3 selfcheck: ok/);
  assert.match(report.summary, /ambient=reached/);
  assert.match(report.summary, /agents=reached/);
});

test("buildSelfcheckReport: ambient on disk but absent from prompt → gap + warning", () => {
  const report = buildSelfcheckReport({
    version: "1.0.0",
    sharedOk: true,
    onDiskIndex: "# routing index",
    options: {
      appendSystemPrompt: "unrelated",
      contextFiles: [{ path: "AGENTS.md", content: MANAGED_AGENTS_MARKER }],
    },
  });
  assert.equal(report.ok, false);
  assert.equal(report.level, "warning");
  assert.match(report.summary, /WIRING GAP/);
  assert.match(report.summary, /ambient=MISSING/);
});

test("buildSelfcheckReport: managed AGENTS block missing → gap", () => {
  const report = buildSelfcheckReport({
    version: "1.0.0",
    sharedOk: true,
    onDiskIndex: null,
    options: { appendSystemPrompt: "x", contextFiles: [{ path: "AGENTS.md", content: "plain" }] },
  });
  assert.equal(report.ok, false);
  assert.match(report.summary, /agents=MISSING/);
});

test("buildSelfcheckReport: shared miss fails ok even when context is wired", () => {
  const index = "# routing index";
  const report = buildSelfcheckReport({
    version: "1.0.0",
    sharedOk: false,
    onDiskIndex: index,
    options: {
      appendSystemPrompt: index,
      contextFiles: [{ path: "AGENTS.md", content: MANAGED_AGENTS_MARKER }],
    },
  });
  assert.equal(report.ok, false);
  assert.match(report.summary, /shared=miss/);
});

test("buildSelfcheckReport: undefined options (prompt not yet built) → gap, no throw", () => {
  const report = buildSelfcheckReport({
    version: "1.0.0",
    sharedOk: true,
    onDiskIndex: null,
    options: undefined,
  });
  assert.equal(report.ok, false);
  assert.equal(report.agents.reachedPrompt, false);
});

// ---------------------------------------------------------------------------
// readAmbientIndex
// ---------------------------------------------------------------------------

test("readAmbientIndex: reads .pi/APPEND_SYSTEM.md, null when absent", () => {
  const cwd = scaffoldRepo();
  assert.equal(readAmbientIndex(cwd), null);
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(join(cwd, ".pi", "APPEND_SYSTEM.md"), "ambient body", "utf8");
  assert.equal(readAmbientIndex(cwd), "ambient body");
});

// ---------------------------------------------------------------------------
// Integration: the live verifier over a REAL bound session
// ---------------------------------------------------------------------------

// A distinctive ambient index so the verbatim substring probe is unambiguous.
const AMBIENT_BODY =
  "## Durable learnings\n\n- selfcheck-probe-sentinel — a distinctive marker line.";
const AGENTS_BODY = `# AGENTS\n\n${MANAGED_AGENTS_MARKER}\n## perk conventions\nperk version: 0.0.1\n<!-- END perk managed -->\n`;

function convergeContext(cwd: string): void {
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(join(cwd, ".pi", "APPEND_SYSTEM.md"), `${AMBIENT_BODY}\n`, "utf8");
  writeFileSync(join(cwd, "AGENTS.md"), AGENTS_BODY, "utf8");
}

test("selfcheck (live): converged ambient index + managed AGENTS reach the prompt", async () => {
  const cwd = scaffoldRepo();
  convergeContext(cwd);
  const h = await loadPerkSession({ cwd });
  try {
    await h.invokeCommand("perk-selfcheck");
    const msg = h.notifies.at(-1) ?? "";
    assert.match(msg, /selfcheck: ok/, `expected ok wiring, got: ${msg}`);
    assert.match(msg, /ambient=reached/);
    assert.match(msg, /agents=reached/);
  } finally {
    h.dispose();
  }
});

test("selfcheck (live): a missing managed AGENTS block is reported as a gap", async () => {
  const cwd = scaffoldRepo();
  // Converge the ambient index but NOT a managed AGENTS.md block.
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(join(cwd, ".pi", "APPEND_SYSTEM.md"), `${AMBIENT_BODY}\n`, "utf8");
  writeFileSync(join(cwd, "AGENTS.md"), "# AGENTS\n\nno managed block here\n", "utf8");
  const h = await loadPerkSession({ cwd });
  try {
    await h.invokeCommand("perk-selfcheck");
    const msg = h.notifies.at(-1) ?? "";
    assert.match(msg, /WIRING GAP/, `expected a gap, got: ${msg}`);
    assert.match(msg, /agents=MISSING/);
  } finally {
    h.dispose();
  }
});

// ---------------------------------------------------------------------------
// Change A: ctx.mode recorded as run_mode in the .perk-t3.json sentinel
// ---------------------------------------------------------------------------

test('run_mode: defaults to Pi\'s "print" when no mode is forwarded', async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    const s = h.sentinel();
    assert.equal(s?.run_mode, "print");
    // run_mode (Pi mode) is distinct from the workflow `mode` (gating).
    assert.equal(s?.mode, "read-only");
  } finally {
    h.dispose();
  }
});

test("run_mode: a forwarded tui mode is recorded from ctx.mode", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, mode: "tui" });
  try {
    assert.equal(h.sentinel()?.run_mode, "tui");
  } finally {
    h.dispose();
  }
});
