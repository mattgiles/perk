// Tests for the `/perk-selfcheck` session-wiring verifier: pure probes/report twins, plus a live
// integration that drives a REAL bound session and proves the converged context reached the prompt.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { type Api, fauxAssistantMessage, fauxText, type Model } from "@earendil-works/pi-ai";
import { formatSkillsForPrompt, type Skill, type ToolInfo } from "@earendil-works/pi-coding-agent";
import { BINDING_HEADER } from "../../substrate/bindingDelivery.ts";
import { admitHostSdk, type HostSdkAdmission } from "../../substrate/hostAdmission.ts";
import { loadedHostSdkVersion } from "../../substrate/hostSdkVersion.ts";
import { type BridgeStatus, NATIVE_SDK_CENSUS } from "../../substrate/nativeSdkBridge.ts";
import { branchUsageCensus } from "../../substrate/usageLedger.ts";
import { REPORT_DETAIL_TYPE } from "../../surfaces/surfaces.ts";
import { fauxModelRuntime, loadPerkSession, scaffoldRepo } from "../../testing/harness.ts";
import {
  ambientIndexProbe,
  branchContextCensus,
  buildSelfcheckReport,
  contextCensus,
  MANAGED_AGENTS_MARKER,
  managedAgentsProbe,
  modelIdentityCensus,
  promptCensus,
  readAmbientIndex,
  readLiveProjection,
  renderCensus,
  toolsCensus,
} from "./selfcheck.ts";

/** An inert bridge status for the pure report/census twins (the harness proves the real one). */
const NO_BRIDGE: BridgeStatus = {
  state: "unsupported:embedded-host",
  hostEntry: null,
  roots: [],
  specifiers: 0,
  reused: false,
  detail: "",
};

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
    bridge: NO_BRIDGE,
  });
  assert.equal(report.ok, true);
  assert.equal(report.level, "info");
  assert.match(report.summary, /^1\.2\.3: ok/);
  assert.match(report.summary, /ambient=reached/);
  assert.match(report.summary, /agents=reached/);
  assert.match(report.summary, /; bridge=unsupported:embedded-host$/);
  assert.equal(report.bridge, NO_BRIDGE);
});

test("buildSelfcheckReport: the bridge state never affects ok/level", () => {
  const index = "# routing index";
  const report = buildSelfcheckReport({
    version: "1.0.0",
    sharedOk: true,
    onDiskIndex: index,
    options: {
      appendSystemPrompt: index,
      contextFiles: [{ path: "AGENTS.md", content: MANAGED_AGENTS_MARKER }],
    },
    bridge: { ...NO_BRIDGE, state: "failed:register-hooks", detail: "boom" },
  });
  assert.equal(report.ok, true);
  assert.equal(report.level, "info");
  assert.match(report.summary, /; bridge=failed:register-hooks$/);
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
    bridge: NO_BRIDGE,
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
    bridge: NO_BRIDGE,
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
    bridge: NO_BRIDGE,
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
    bridge: NO_BRIDGE,
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
    // Pi's default for a tool that declares no exposure — the live ToolInfo shape.
    exposure: "direct",
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
  const census = branchContextCensus(
    [
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
    ],
    [],
  );
  assert.equal(census.entries, 7);
  assert.deepEqual(census.perkContexts, [
    { customType: "perk:binding-context", copies: 1, totalChars: 5, live: 0 },
    { customType: "perk:mode-context", copies: 2, totalChars: 100, live: 0 },
  ]);
  assert.deepEqual(census.otherCustomMessages, { copies: 1, totalChars: 10 });
  assert.equal(census.bindingHeaderCopies, 1);
});

test("branchContextCensus: live counts come from the projection, distinct from historical copies", () => {
  // Two historical copies (one compacted away), one live copy in the current projection.
  const entries = [
    { type: "custom_message", customType: "perk:mode-context", content: "a".repeat(40) },
    { type: "compaction" },
    { type: "custom_message", customType: "perk:mode-context", content: "b".repeat(40) },
  ];
  const projection = [
    { role: "compactionSummary" },
    { role: "custom", customType: "perk:mode-context" },
    // Another owner's custom message and a user turn never count toward the row.
    { role: "custom", customType: "other:overlay" },
    { role: "user" },
  ];
  const census = branchContextCensus(entries, projection);
  assert.deepEqual(census.perkContexts, [
    { customType: "perk:mode-context", copies: 2, totalChars: 80, live: 1 },
  ]);
});

test("branchContextCensus: a throwing projection read leaves live unknown (never throws)", () => {
  const live = readLiveProjection({
    sessionManager: {
      buildSessionProjection: () => {
        throw new Error("projection unavailable");
      },
    },
  });
  assert.equal(live, null);
  const census = branchContextCensus(
    [{ type: "custom_message", customType: "perk:mode-context", content: "x" }],
    live,
  );
  assert.deepEqual(census.perkContexts, [
    { customType: "perk:mode-context", copies: 1, totalChars: 1, live: null },
  ]);
});

test("branchContextCensus: empty branch → zeros", () => {
  const census = branchContextCensus([], []);
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

const ADMITTED_SDK: HostSdkAdmission = {
  outcome: "admitted",
  observed: "1.0.0",
  required: "1.0.0",
  detail: "",
};

test("renderCensus: full block pins the line grammar", () => {
  const block = renderCensus({
    prompt: {
      basePromptChars: null,
      appendChars: 34562,
      contextFiles: { count: 1, totalChars: 18234, files: [{ path: "AGENTS.md", chars: 18234 }] },
      skills: { visible: 28, hidden: 3, promptSectionChars: 13800 },
      toolGuidelineChars: 2400,
      toolSnippetChars: 800,
    },
    tools: {
      active: 24,
      all: 41,
      schemaChars: 61234,
      bySource: [
        { source: "builtin", active: 20, schemaChars: 50000 },
        { source: "perk", active: 4, schemaChars: 11234 },
      ],
    },
    branch: {
      entries: 142,
      perkContexts: [
        { customType: "perk:binding-context", copies: 1, totalChars: 900, live: 1 },
        { customType: "perk:mode-context", copies: 3, totalChars: 14400, live: null },
      ],
      otherCustomMessages: { copies: 0, totalChars: 0 },
      bindingHeaderCopies: 2,
    },
    model: {
      selected: { key: "router/auto", api: "pi-virtual" },
      dispatched: "ext-faux/m-1",
      relation: "differs",
      responses: [
        { model: "ext-faux/m-1", count: 3 },
        { model: "ext-faux/m-2", count: 1 },
      ],
      errors: 1,
      aborted: 0,
    },
    usage: {
      totals: {
        records: 5,
        input: 1000,
        output: 234,
        cacheRead: 5000,
        cacheWrite: 800,
        cost: 0.0123,
      },
      bySource: { assistant: 4, toolResult: 1, compaction: 0, branchSummary: 0, usageEntry: 0 },
    },
    context: { projected: 142, window: { contextWindow: 200000, tokens: 90000, percent: 45 } },
    bridge: {
      state: "installed",
      hostEntry: "/pi/dist/index.js",
      roots: ["/repo/consumers/pi-subagents", "/repo/consumers/pi-web-access"],
      specifiers: NATIVE_SDK_CENSUS.length,
      reused: true,
      detail: "",
    },
    discovery: { cohort: true, family: ["collect_review_wave", "push_annotations"] },
    hostSdk: ADMITTED_SDK,
  });
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
      "  discovery: cohort (family: collect_review_wave, push_annotations)",
      "  branch: 142 entries; binding-header-copies=2",
      "    perk contexts: perk:binding-context ×1 (900c) live=1; perk:mode-context ×3 (14400c) live=?; other custom_message ×0 (0c)",
      "  model: selected=router/auto (api=pi-virtual); dispatched=ext-faux/m-1; differs",
      "    responses: ext-faux/m-1 ×3; ext-faux/m-2 ×1; errors=1; aborted=0",
      "  usage: records=5 (assistant=4, tool=1, compaction=0, branch-summary=0, usage-entry=0); fresh=1234 (in=1000 out=234); cache read=5000 write=800; cost=$0.0123",
      "  context: projection=142 messages (pre-transform; the outgoing request is not observed); window=200000 used=90000 (45%)",
      "  wave children: usage=unavailable (separate sessions; no owned-run attribution read)",
      "  host sdk: 1.0.0 (floor >= 1.0.0)",
      `  native sdk bridge: installed (roots=2, specifiers=${NATIVE_SDK_CENSUS.length}, reused)`,
      "    host: /pi/dist/index.js",
      "    roots: 2 — /repo/consumers/pi-subagents, /repo/consumers/pi-web-access",
    ].join("\n"),
  );
});

test("renderCensus: custom base prompt, empty surfaces → none/omitted/unavailable segments", () => {
  const block = renderCensus({
    prompt: {
      basePromptChars: 4820,
      appendChars: 0,
      contextFiles: { count: 0, totalChars: 0, files: [] },
      skills: { visible: 0, hidden: 0, promptSectionChars: 0 },
      toolGuidelineChars: 0,
      toolSnippetChars: 0,
    },
    tools: { active: 0, all: 0, schemaChars: 0, bySource: [] },
    branch: {
      entries: 3,
      perkContexts: [],
      otherCustomMessages: { copies: 1, totalChars: 12 },
      bindingHeaderCopies: 0,
    },
    model: modelIdentityCensus(undefined, []),
    usage: branchUsageCensus([]),
    context: contextCensus(null, null),
    bridge: { ...NO_BRIDGE, state: "failed:host-entry", detail: "no entry" },
    discovery: { cohort: false, family: [] },
    // Never reached in production (an activation is admitted); the render stays type-honest.
    hostSdk: { outcome: "unverifiable", observed: null, required: "1.0.0", detail: "x" },
  });
  assert.equal(
    block,
    [
      "census:",
      "  base-prompt: custom 4820c",
      "  append-system-prompt: 0c",
      "  context-files: 0 file(s), 0c",
      "  skills: 0 visible + 0 hidden; prompt-section=0c",
      "  tools: 0 active / 0 registered; schemas=0c; guidelines=0c; snippets=0c",
      "  discovery: nonparticipant",
      "  branch: 3 entries; binding-header-copies=0",
      "    perk contexts: none; other custom_message ×1 (12c)",
      "  model: selected=none; dispatched=none; n/a",
      "    responses: none",
      "  usage: unavailable (no usage records on the branch)",
      "  context: projection=? messages (pre-transform; the outgoing request is not observed); limits=unavailable",
      "  wave children: usage=unavailable (separate sessions; no owned-run attribution read)",
      "  host sdk: ? (floor >= 1.0.0)",
      "  native sdk bridge: failed:host-entry — no entry",
      "    host: -",
      "    roots: 0",
    ].join("\n"),
  );
});

test("renderCensus: a nonparticipant with a member still deferred names it (a failed re-declaration)", () => {
  const discoveryLine = (discovery: { cohort: boolean; family: readonly string[] }) =>
    renderCensus({
      prompt: promptCensus(undefined),
      tools: toolsCensus([], []),
      branch: branchContextCensus([], []),
      model: modelIdentityCensus(undefined, []),
      usage: branchUsageCensus([]),
      context: contextCensus(null, null),
      bridge: NO_BRIDGE,
      discovery,
      hostSdk: ADMITTED_SDK,
    })
      .split("\n")
      .find((line) => line.startsWith("  discovery:"));
  assert.equal(
    discoveryLine({ cohort: false, family: ["objective_stack_status", "push_annotations"] }),
    "  discovery: nonparticipant (still deferred: objective_stack_status, push_annotations)",
  );
  assert.equal(discoveryLine({ cohort: false, family: [] }), "  discovery: nonparticipant");
});

// ---------------------------------------------------------------------------
// Pure: modelIdentityCensus / contextCensus (the model, usage and context rows)
// ---------------------------------------------------------------------------

/** A branch assistant `message` entry. */
const assistantEntry = (fields: Record<string, unknown>): Record<string, unknown> => ({
  type: "message",
  message: { role: "assistant", ...fields },
});

/** Render only the five rows this node adds (the block between `perk contexts:` and `host sdk:`). */
function identityRows(
  model: ReturnType<typeof modelIdentityCensus>,
  usage: ReturnType<typeof branchUsageCensus>,
  context: ReturnType<typeof contextCensus>,
): string[] {
  const block = renderCensus({
    prompt: promptCensus(undefined),
    tools: toolsCensus([], []),
    branch: branchContextCensus([], []),
    model,
    usage,
    context,
    bridge: NO_BRIDGE,
    discovery: { cohort: false, family: [] },
    hostSdk: ADMITTED_SDK,
  }).split("\n");
  const start = block.findIndex((line) => line.startsWith("    perk contexts:")) + 1;
  const end = block.findIndex((line) => line.startsWith("  host sdk:"));
  return block.slice(start, end);
}

test("modelIdentityCensus: a plain selection that answered renders `same`", () => {
  const census = modelIdentityCensus(
    { provider: "anthropic", id: "claude-x", api: "anthropic-messages" },
    [assistantEntry({ provider: "anthropic", model: "claude-x", stopReason: "stop" })],
  );
  assert.deepEqual(census, {
    selected: { key: "anthropic/claude-x", api: "anthropic-messages" },
    dispatched: "anthropic/claude-x",
    relation: "same",
    responses: [{ model: "anthropic/claude-x", count: 1 }],
    errors: 0,
    aborted: 0,
  });
});

test("modelIdentityCensus: `same` compares the requested physical id, before any →responseModel suffix", () => {
  const census = modelIdentityCensus({ provider: "openai", id: "gpt-5", api: "openai-responses" }, [
    assistantEntry({ provider: "openai", model: "gpt-5", responseModel: "gpt-5-2026" }),
  ]);
  assert.equal(census.dispatched, "openai/gpt-5→gpt-5-2026");
  assert.equal(census.relation, "same");
});

test("modelIdentityCensus: no selection or no successful response renders `n/a`", () => {
  const noSelection = modelIdentityCensus(undefined, [
    assistantEntry({ provider: "faux", model: "faux-1" }),
  ]);
  assert.equal(noSelection.selected, null);
  assert.equal(noSelection.relation, "n/a");
  const onlyFailures = modelIdentityCensus({ provider: "router", id: "auto", api: "pi-virtual" }, [
    assistantEntry({ provider: "router", model: "auto", stopReason: "error" }),
    assistantEntry({ provider: "faux", model: "faux-1", stopReason: "aborted" }),
  ]);
  assert.equal(onlyFailures.dispatched, null);
  assert.equal(onlyFailures.relation, "n/a");
  assert.deepEqual(
    identityRows(onlyFailures, branchUsageCensus([]), contextCensus(3, null)).slice(0, 2),
    [
      "  model: selected=router/auto (api=pi-virtual); dispatched=none; n/a",
      "    responses: errors=1; aborted=1",
    ],
    "failures are counted, never dispatched",
  );
});

test("renderCensus: a populated plain-model block renders `same`, the usage sources and a recorded zero cost", () => {
  const entries = [
    assistantEntry({
      provider: "faux",
      model: "faux-1",
      stopReason: "stop",
      usage: { input: 10, output: 5, cacheRead: 0, cacheWrite: 0, cost: { total: 0 } },
    }),
    { type: "compaction", usage: { input: 3, output: 1, cacheRead: 2, cacheWrite: 0 } },
  ];
  assert.deepEqual(
    identityRows(
      modelIdentityCensus({ provider: "faux", id: "faux-1", api: "faux" }, entries),
      branchUsageCensus(entries),
      contextCensus(7, { tokens: 1234, contextWindow: 8192, percent: 15.06 }),
    ),
    [
      "  model: selected=faux/faux-1 (api=faux); dispatched=faux/faux-1; same",
      "    responses: faux/faux-1 ×1; errors=0; aborted=0",
      "  usage: records=2 (assistant=1, tool=0, compaction=1, branch-summary=0, usage-entry=0); fresh=19 (in=13 out=6); cache read=2 write=0; cost=$0.0000",
      "  context: projection=7 messages (pre-transform; the outgoing request is not observed); window=8192 used=1234 (15%)",
      "  wave children: usage=unavailable (separate sessions; no owned-run attribution read)",
    ],
  );
});

test("contextCensus: unknown tokens/percent (post-compaction) render `used=? (?%)`", () => {
  const context = contextCensus(12, { tokens: null, contextWindow: 200000, percent: null });
  assert.deepEqual(context, {
    projected: 12,
    window: { contextWindow: 200000, tokens: null, percent: null },
  });
  const [, , , row] = identityRows(
    modelIdentityCensus(undefined, []),
    branchUsageCensus([]),
    context,
  );
  assert.equal(
    row,
    "  context: projection=12 messages (pre-transform; the outgoing request is not observed); window=200000 used=? (?%)",
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
    // The harness binds the factory in the test process (argv[1] is the test runner, not a Pi
    // CLI), so the bridge is the inert embedded-host state — and registers no hook.
    assert.match(msg, /; bridge=unsupported:embedded-host/);
    // The entry admitted the installed SDK; the census reports it beside the floor.
    const installed = admitHostSdk(loadedHostSdkVersion(), "1.4.0").observed ?? "";
    assert.ok(
      text.includes(`\n  host sdk: ${installed} (floor >= 1.4.0)\n  native sdk bridge:`),
      text,
    );
    assert.match(
      text,
      /\n {2}native sdk bridge: unsupported:embedded-host\n {4}host: -\n {4}roots: 0/,
    );
  } finally {
    h.dispose();
  }
});

/** The selfcheck's report-detail text from the session's entries. */
function selfcheckDetail(h: Awaited<ReturnType<typeof loadPerkSession>>): string {
  const entries = h.session.sessionManager.getEntries() as unknown as {
    customType?: string;
    data?: { text?: string };
  }[];
  return entries.findLast((entry) => entry.customType === REPORT_DETAIL_TYPE)?.data?.text ?? "";
}

const WAVE_ROW =
  "\n  wave children: usage=unavailable (separate sessions; no owned-run attribution read)\n";

test("selfcheck (live): a virtual selection is reported beside the physical model that answered", async () => {
  const cwd = scaffoldRepo();
  convergeContext(cwd);
  const reg = await fauxModelRuntime();
  const target = reg.getModel() as Model<Api>;
  reg.modelRuntime.registerVirtualModel({
    provider: "router",
    id: "auto",
    name: "Auto",
    route: () => ({ model: target, thinkingLevel: "off" }),
  });
  const h = await loadPerkSession({
    cwd,
    model: reg.modelRuntime.getModel("router", "auto"),
    modelRuntime: reg.modelRuntime,
  });
  try {
    reg.setResponses([fauxAssistantMessage([fauxText("done")], { stopReason: "stop" })]);
    await h.session.prompt("hello");
    await h.invokeCommand("perk-selfcheck");
    const text = selfcheckDetail(h);
    assert.ok(
      text.includes(
        "\n  model: selected=router/auto (api=pi-virtual); dispatched=faux/faux-1; differs\n",
      ),
      text,
    );
    assert.ok(text.includes("\n    responses: faux/faux-1 ×1; errors=0; aborted=0\n"), text);
    assert.match(
      text,
      /\n {2}usage: records=1 \(assistant=1, tool=0, compaction=0, branch-summary=0, usage-entry=0\); fresh=\d+ \(in=\d+ out=\d+\); cache read=\d+ write=\d+; cost=\$0\.0000\n/,
    );
    assert.match(
      text,
      /\n {2}context: projection=\d+ messages \(pre-transform; the outgoing request is not observed\); window=\d+ used=(\d+|\?) \((\d+|\?)%\)\n/,
    );
    assert.ok(text.includes(WAVE_ROW), text);
    // The rows sit after the branch rows and before the host-SDK block.
    assert.ok(text.indexOf("\n  model: ") > text.indexOf("\n    perk contexts: "));
    assert.ok(text.indexOf(WAVE_ROW) < text.indexOf("\n  host sdk: "));
  } finally {
    h.dispose();
  }
});

test("selfcheck (live): a session that never answered reports dispatched=none, n/a and unavailable usage", async () => {
  const cwd = scaffoldRepo();
  convergeContext(cwd);
  const h = await loadPerkSession({ cwd });
  try {
    await h.invokeCommand("perk-selfcheck");
    const text = selfcheckDetail(h);
    assert.match(
      text,
      /\n {2}model: selected=anthropic\/claude-sonnet-4-5 \(api=[^)]+\); dispatched=none; n\/a\n/,
    );
    assert.ok(text.includes("\n    responses: none\n"), text);
    assert.ok(text.includes("\n  usage: unavailable (no usage records on the branch)\n"), text);
    assert.match(
      text,
      /\n {2}context: projection=\d+ messages \(pre-transform; the outgoing request is not observed\); /,
    );
    assert.ok(text.includes(WAVE_ROW), text);
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
