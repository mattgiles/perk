// Tests for the `/perk-selfcheck` session-wiring verifier: pure probes/report twins, plus a live
// integration that drives a REAL bound session and proves the converged context reached the prompt.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { formatSkillsForPrompt, type Skill, type ToolInfo } from "@earendil-works/pi-coding-agent";
import { BINDING_HEADER } from "../../substrate/bindingDelivery.ts";
import { REPORT_DETAIL_TYPE } from "../../surfaces/surfaces.ts";
import { loadPerkSession, scaffoldRepo } from "../../testing/harness.ts";
import {
  ambientIndexProbe,
  branchContextCensus,
  buildSelfcheckReport,
  MANAGED_AGENTS_MARKER,
  managedAgentsProbe,
  promptCensus,
  readAmbientIndex,
  renderCensus,
  toolsCensus,
} from "./selfcheck.ts";

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
  assert.match(report.summary, /^1\.2\.3: ok/);
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
// Pure: promptCensus
// ---------------------------------------------------------------------------

function fakeSkill(name: string, opts?: { hidden?: boolean }): Skill {
  return {
    name,
    description: `${name} description`,
    filePath: `/skills/${name}/SKILL.md`,
    baseDir: `/skills/${name}`,
    sourceInfo: { path: `/skills/${name}`, source: "test", scope: "project", origin: "top-level" },
    disableModelInvocation: opts?.hidden ?? false,
  };
}

test("promptCensus: counts every probed surface from fabricated options", () => {
  const skills = [fakeSkill("alpha"), fakeSkill("beta"), fakeSkill("ghost", { hidden: true })];
  const census = promptCensus({
    appendSystemPrompt: "a".repeat(120),
    contextFiles: [
      { path: "AGENTS.md", content: "x".repeat(50) },
      { path: "sub/AGENTS.md", content: "y".repeat(7) },
    ],
    skills,
    toolSnippets: { read: "read files", bash: "run bash" },
    promptGuidelines: ["guideline one", "two"],
  });
  assert.equal(census.basePromptChars, null);
  assert.equal(census.appendChars, 120);
  assert.equal(census.contextFiles.count, 2);
  assert.equal(census.contextFiles.totalChars, 57);
  assert.deepEqual(census.contextFiles.files, [
    { path: "AGENTS.md", chars: 50 },
    { path: "sub/AGENTS.md", chars: 7 },
  ]);
  assert.equal(census.skills.visible, 2);
  assert.equal(census.skills.hidden, 1);
  // The exact prompt-section contribution: pi's own formatter over the visible skills.
  const visible = skills.filter((s) => !s.disableModelInvocation);
  assert.equal(census.skills.promptSectionChars, formatSkillsForPrompt(visible).length);
  assert.ok(census.skills.promptSectionChars > 0);
  assert.equal(census.toolSnippetChars, "read files".length + "run bash".length);
  assert.equal(census.toolGuidelineChars, "guideline one".length + "two".length);
});

test("promptCensus: a customPrompt is measured (pi default → null)", () => {
  assert.equal(promptCensus({ customPrompt: "be terse" }).basePromptChars, 8);
  assert.equal(promptCensus({}).basePromptChars, null);
});

test("promptCensus: undefined options → zeros and null base prompt", () => {
  const census = promptCensus(undefined);
  assert.equal(census.basePromptChars, null);
  assert.equal(census.appendChars, 0);
  assert.deepEqual(census.contextFiles, { count: 0, totalChars: 0, files: [] });
  assert.deepEqual(census.skills, { visible: 0, hidden: 0, promptSectionChars: 0 });
  assert.equal(census.toolGuidelineChars, 0);
  assert.equal(census.toolSnippetChars, 0);
});

// ---------------------------------------------------------------------------
// Pure: toolsCensus
// ---------------------------------------------------------------------------

function fakeTool(name: string, source: string): ToolInfo {
  return {
    name,
    description: `${name} tool`,
    parameters: { type: "object" } as ToolInfo["parameters"],
    sourceInfo: { path: `/ext/${source}`, source, scope: "project", origin: "package" },
  };
}

function schemaCharsOf(tool: ToolInfo): number {
  return JSON.stringify({
    name: tool.name,
    description: tool.description,
    parameters: tool.parameters,
  }).length;
}

test("toolsCensus: active/all counts, active-only schema chars, stable per-source rows", () => {
  const read = fakeTool("read", "builtin");
  const write = fakeTool("write", "builtin");
  const submit = fakeTool("submit", "a-perk");
  const inactive = fakeTool("land", "a-perk");
  const census = toolsCensus([read, write, submit, inactive], ["read", "write", "submit"]);
  assert.equal(census.active, 3);
  assert.equal(census.all, 4);
  // schemaChars sums ONLY the active tools (the per-request definitions payload).
  assert.equal(
    census.schemaChars,
    schemaCharsOf(read) + schemaCharsOf(write) + schemaCharsOf(submit),
  );
  assert.deepEqual(census.bySource, [
    { source: "a-perk", active: 1, schemaChars: schemaCharsOf(submit) },
    { source: "builtin", active: 2, schemaChars: schemaCharsOf(read) + schemaCharsOf(write) },
  ]);
});

test("toolsCensus: no tools → zeros, no source rows", () => {
  const census = toolsCensus([], []);
  assert.deepEqual(census, { active: 0, all: 0, schemaChars: 0, bySource: [] });
});

// ---------------------------------------------------------------------------
// Pure: branchContextCensus
// ---------------------------------------------------------------------------

test("branchContextCensus: perk custom_message copies counted; workflow state excluded", () => {
  const census = branchContextCensus([
    { type: "custom_message", customType: "perk:mode-context", content: "a".repeat(40) },
    { type: "custom_message", customType: "perk:mode-context", content: "b".repeat(60) },
    // A `type: "custom"` state entry (workflow state) must NOT count as injected context.
    { type: "custom", customType: "perk:workflow-state", content: "c".repeat(99) },
    // A non-perk custom_message counts under "other" (borrowed packages).
    { type: "custom_message", customType: "other:overlay", content: "d".repeat(10) },
    // Array-form content sums the text-part lengths only.
    {
      type: "custom_message",
      customType: "perk:binding-context",
      content: [
        { type: "text", text: "12345" },
        { type: "image", data: "zzz" },
      ],
    },
    // A user message embedding the binding header counts toward bindingHeaderCopies.
    { type: "user", content: `hello\n${BINDING_HEADER}\nrest` },
    { type: "assistant", content: "plain turn" },
  ]);
  assert.equal(census.entries, 7);
  assert.deepEqual(census.perkContexts, [
    { customType: "perk:binding-context", copies: 1, totalChars: 5 },
    { customType: "perk:mode-context", copies: 2, totalChars: 100 },
  ]);
  assert.deepEqual(census.otherCustomMessages, { copies: 1, totalChars: 10 });
  assert.equal(census.bindingHeaderCopies, 1);
});

test("branchContextCensus: empty branch → zeros", () => {
  const census = branchContextCensus([]);
  assert.deepEqual(census, {
    entries: 0,
    perkContexts: [],
    otherCustomMessages: { copies: 0, totalChars: 0 },
    bindingHeaderCopies: 0,
  });
});

// ---------------------------------------------------------------------------
// renderCensus — the stable line grammar (the closing audit diffs these exact keys)
// ---------------------------------------------------------------------------

test("renderCensus: full block pins the line grammar", () => {
  const block = renderCensus(
    {
      basePromptChars: null,
      appendChars: 34562,
      contextFiles: { count: 1, totalChars: 18234, files: [{ path: "AGENTS.md", chars: 18234 }] },
      skills: { visible: 28, hidden: 3, promptSectionChars: 13800 },
      toolGuidelineChars: 2400,
      toolSnippetChars: 800,
    },
    {
      active: 24,
      all: 41,
      schemaChars: 61234,
      bySource: [
        { source: "builtin", active: 20, schemaChars: 50000 },
        { source: "perk", active: 4, schemaChars: 11234 },
      ],
    },
    {
      entries: 142,
      perkContexts: [
        { customType: "perk:binding-context", copies: 1, totalChars: 900 },
        { customType: "perk:mode-context", copies: 3, totalChars: 14400 },
      ],
      otherCustomMessages: { copies: 0, totalChars: 0 },
      bindingHeaderCopies: 2,
    },
  );
  assert.equal(
    block,
    [
      "census:",
      "  base-prompt: pi-default (not measured)",
      "  append-system-prompt: 34562c",
      "  context-files: 1 file(s), 18234c — AGENTS.md=18234c",
      "  skills: 28 visible + 3 hidden; prompt-section=13800c",
      "  tools: 24 active / 41 registered; schemas=61234c; guidelines=2400c; snippets=800c",
      "    per source: builtin=20 (50000c); perk=4 (11234c)",
      "  branch: 142 entries; binding-header-copies=2",
      "    perk contexts: perk:binding-context ×1 (900c); perk:mode-context ×3 (14400c); other custom_message ×0 (0c)",
    ].join("\n"),
  );
});

test("renderCensus: custom base prompt, empty surfaces → none/omitted segments", () => {
  const block = renderCensus(
    {
      basePromptChars: 4820,
      appendChars: 0,
      contextFiles: { count: 0, totalChars: 0, files: [] },
      skills: { visible: 0, hidden: 0, promptSectionChars: 0 },
      toolGuidelineChars: 0,
      toolSnippetChars: 0,
    },
    { active: 0, all: 0, schemaChars: 0, bySource: [] },
    {
      entries: 3,
      perkContexts: [],
      otherCustomMessages: { copies: 1, totalChars: 12 },
      bindingHeaderCopies: 0,
    },
  );
  assert.equal(
    block,
    [
      "census:",
      "  base-prompt: custom 4820c",
      "  append-system-prompt: 0c",
      "  context-files: 0 file(s), 0c",
      "  skills: 0 visible + 0 hidden; prompt-section=0c",
      "  tools: 0 active / 0 registered; schemas=0c; guidelines=0c; snippets=0c",
      "  branch: 3 entries; binding-header-copies=0",
      "    perk contexts: none; other custom_message ×1 (12c)",
    ].join("\n"),
  );
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
    assert.match(msg, /^perk: selfcheck — .*: ok/, `expected ok wiring, got: ${msg}`);
    assert.match(msg, /ambient=reached/);
    assert.match(msg, /agents=reached/);
  } finally {
    h.dispose();
  }
});

test("selfcheck (live): the report-detail entry carries the census block", async () => {
  const cwd = scaffoldRepo();
  convergeContext(cwd);
  const h = await loadPerkSession({ cwd });
  try {
    await h.invokeCommand("perk-selfcheck");
    const msg = h.notifies.at(-1) ?? "";
    assert.match(msg, /^perk: selfcheck — .*: ok/, `expected ok wiring, got: ${msg}`);
    assert.doesNotMatch(msg, /\n/);

    const entries = h.session.sessionManager.getEntries() as unknown as {
      customType?: string;
      data?: { text?: string; severity?: string };
    }[];
    const detail = entries.find((entry) => entry.customType === REPORT_DETAIL_TYPE);
    assert.equal(detail?.data?.severity, "info");
    const text = detail?.data?.text ?? "";
    assert.match(text, /\ncensus:\n/);
    assert.match(text, /append-system-prompt: \d+c/);
    assert.match(text, /tools: \d+ active \/ \d+ registered/);
    assert.match(text, /branch: \d+ entries; binding-header-copies=\d+/);
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
