// `/perk-selfcheck` — the session-wiring verifier.
//
// perk converges two pieces of session context onto disk and trusts Pi to splice them into the
// model's system prompt:
//
//   1. `.pi/APPEND_SYSTEM.md` — the COMPRESSED ambient routing index (maintained by `/learn-docs`,
//      NOT `perk init`). Pi loads it verbatim and joins it into `appendSystemPrompt`.
//   2. the `<!-- BEGIN perk managed -->` block in `AGENTS.md` — written by `perk init` (the Python
//      plane). Pi loads `AGENTS.md` into `contextFiles` as `{ path, content }`.
//
// `perk doctor` checks the DISK side (the files converged). This selfcheck checks the PROMPT side:
// it reads the live `getSystemPromptOptions()` (only available on a command context) and confirms
// the converged content actually *reached* the prompt. That closes perk's two-plane blind spot —
// doctor checks disk, selfcheck checks the prompt.
//
// The same report additionally carries a per-surface payload CENSUS — derived counts/chars for
// `appendSystemPrompt`, `contextFiles`, the skills catalog section, the active tool definitions,
// and perk-injected `custom_message` branch context. Report-only: the census never affects the
// ok/level verdict (contracts.md §8.7).
//
// Sensitivity: `getSystemPromptOptions()` exposes the full system-prompt construction inputs. This
// module logs ONLY derived output — identifiers (paths, skill/tool names, source strings,
// customTypes) and counts/chars; never prompt/content text. See docs/learned/pi/.

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import {
  type ExtensionAPI,
  formatSkillsForPrompt,
  type Skill,
  type ToolInfo,
} from "@earendil-works/pi-coding-agent";
import { BINDING_HEADER } from "../../substrate/bindingDelivery.ts";
import { registerPerkCommand } from "../../substrate/command.ts";
import { branchOf } from "../../substrate/workflowState.ts";
import { report as reportTo } from "../../surfaces/report.ts";

/** Project-scoped ambient routing index, relative to the repo root. */
export const AMBIENT_INDEX_REL_PATH = join(".pi", "APPEND_SYSTEM.md");

/** The managed `AGENTS.md` block marker (cross-plane: written by `perk init`, read here). */
export const MANAGED_AGENTS_MARKER = "<!-- BEGIN perk managed -->";

/** The slice of `BuildSystemPromptOptions` the verifier + census probe (all optional). */
export interface SystemPromptProbeInput {
  customPrompt?: string;
  appendSystemPrompt?: string;
  contextFiles?: { path: string; content: string }[];
  skills?: Skill[];
  selectedTools?: string[];
  toolSnippets?: Record<string, string>;
  promptGuidelines?: string[];
}

/** Read the on-disk ambient routing index (`.pi/APPEND_SYSTEM.md`), or `null` if absent. */
export function readAmbientIndex(cwd: string): string | null {
  const path = join(cwd, AMBIENT_INDEX_REL_PATH);
  if (!existsSync(path)) return null;
  try {
    return readFileSync(path, "utf8");
  } catch {
    return null;
  }
}

/** Derived booleans/counts for the ambient routing index — never the raw text. */
export interface AmbientIndexProbe {
  /** The `.pi/APPEND_SYSTEM.md` file exists on disk. */
  onDisk: boolean;
  /** Its verbatim content is present in `appendSystemPrompt`. */
  reachedPrompt: boolean;
  /** Either nothing to wire (no on-disk index) or it reached the prompt. */
  wired: boolean;
  /** Length of `appendSystemPrompt` (count only — never the content). */
  promptChars: number;
}

/**
 * Probe whether the on-disk ambient index reached `appendSystemPrompt`. Pi loads the file verbatim
 * and joins it with `\n\n`, so a trimmed substring match is the faithful "reached the prompt" test.
 * An absent on-disk index is `wired` (a fresh consumer repo has none until `/learn-docs` lands one).
 */
export function ambientIndexProbe(
  onDiskIndex: string | null,
  appendSystemPrompt: string | undefined,
): AmbientIndexProbe {
  const append = appendSystemPrompt ?? "";
  const onDisk = onDiskIndex !== null;
  const trimmed = (onDiskIndex ?? "").trim();
  const reachedPrompt = onDisk && trimmed.length > 0 && append.includes(trimmed);
  return {
    onDisk,
    reachedPrompt,
    wired: !onDisk || reachedPrompt,
    promptChars: append.length,
  };
}

/** Derived booleans/counts for the managed `AGENTS.md` block — never the raw text. */
export interface ManagedAgentsProbe {
  /** Number of context files spliced into the prompt. */
  contextFileCount: number;
  /** Some context file carries the `<!-- BEGIN perk managed -->` marker. */
  reachedPrompt: boolean;
}

/** Probe whether the managed `AGENTS.md` block reached `contextFiles`. */
export function managedAgentsProbe(
  contextFiles: { path: string; content: string }[] | undefined,
): ManagedAgentsProbe {
  const files = contextFiles ?? [];
  return {
    contextFileCount: files.length,
    reachedPrompt: files.some((f) => f.content.includes(MANAGED_AGENTS_MARKER)),
  };
}

/** The full derived selfcheck report (booleans/counts + a one-line summary, no raw content). */
export interface SelfcheckReport {
  version: string;
  sharedOk: boolean;
  ambient: AmbientIndexProbe;
  agents: ManagedAgentsProbe;
  /** Everything the session needs is wired through to the prompt. */
  ok: boolean;
  /** One-line, content-free summary (safe to surface in UI/logs). */
  summary: string;
  level: "info" | "warning";
}

/** Build the derived selfcheck report from the version, shared-dir state, and the live prompt. */
export function buildSelfcheckReport(input: {
  version: string;
  sharedOk: boolean;
  onDiskIndex: string | null;
  options: SystemPromptProbeInput | undefined;
}): SelfcheckReport {
  const { version, sharedOk, onDiskIndex, options } = input;
  const ambient = ambientIndexProbe(onDiskIndex, options?.appendSystemPrompt);
  const agents = managedAgentsProbe(options?.contextFiles);
  const ok = sharedOk && ambient.wired && agents.reachedPrompt;
  const summary =
    `${version}: ${ok ? "ok" : "WIRING GAP"}; ` +
    `shared=${sharedOk ? "ok" : "miss"}; ` +
    `ambient=${ambient.onDisk ? (ambient.reachedPrompt ? "reached" : "MISSING") : "none"} ` +
    `(append=${ambient.promptChars}c); ` +
    `agents=${agents.reachedPrompt ? "reached" : "MISSING"} (files=${agents.contextFileCount})`;
  return { version, sharedOk, ambient, agents, ok, summary, level: ok ? "info" : "warning" };
}

// ---------------------------------------------------------------------------
// The per-surface payload census (contracts.md §8.7). Pure builders over the same
// `getSystemPromptOptions()` slice plus the tool registry and the session branch. All counts are
// `string.length` char counts (rendered with a `c` suffix). Identifiers (paths, skill/tool names,
// source strings, customTypes) and counts/chars only — never prompt/content text.
// ---------------------------------------------------------------------------

/** Derived per-surface counts for the system-prompt construction inputs. */
export interface PromptCensus {
  /** `customPrompt` length; `null` = pi's built-in default is in use (not measurable here). */
  basePromptChars: number | null;
  appendChars: number;
  contextFiles: { count: number; totalChars: number; files: { path: string; chars: number }[] };
  /** `hidden` = skills with `disableModelInvocation`; `promptSectionChars` is the exact
   *  system-prompt contribution (pi's own exported `formatSkillsForPrompt`). */
  skills: { visible: number; hidden: number; promptSectionChars: number };
  toolGuidelineChars: number;
  toolSnippetChars: number;
}

/** Census the system-prompt surfaces from the probed options (undefined → zeros). */
export function promptCensus(options: SystemPromptProbeInput | undefined): PromptCensus {
  const files = (options?.contextFiles ?? []).map((f) => ({
    path: f.path,
    chars: f.content.length,
  }));
  const skills = options?.skills ?? [];
  const hidden = skills.filter((s) => s.disableModelInvocation).length;
  let guidelineChars = 0;
  for (const g of options?.promptGuidelines ?? []) guidelineChars += g.length;
  let snippetChars = 0;
  for (const s of Object.values(options?.toolSnippets ?? {})) snippetChars += s.length;
  return {
    basePromptChars: options?.customPrompt === undefined ? null : options.customPrompt.length,
    appendChars: (options?.appendSystemPrompt ?? "").length,
    contextFiles: {
      count: files.length,
      totalChars: files.reduce((sum, f) => sum + f.chars, 0),
      files,
    },
    skills: {
      visible: skills.length - hidden,
      hidden,
      // formatSkillsForPrompt filters disableModelInvocation skills itself, so passing the full
      // list measures exactly the visible skills' prompt-section contribution.
      promptSectionChars: formatSkillsForPrompt(skills).length,
    },
    toolGuidelineChars: guidelineChars,
    toolSnippetChars: snippetChars,
  };
}

/** Derived counts for the tool-definitions payload (active tools = the per-request payload). */
export interface ToolsCensus {
  active: number;
  all: number;
  /** Sum of `JSON.stringify({name, description, parameters})` over ACTIVE tools. */
  schemaChars: number;
  /** Active tools grouped by `sourceInfo.source`, sorted by source string (stable output). */
  bySource: { source: string; active: number; schemaChars: number }[];
}

/** Census the tool registry: active vs registered counts + per-source schema chars. */
export function toolsCensus(allTools: ToolInfo[], activeNames: string[]): ToolsCensus {
  const activeSet = new Set(activeNames);
  const bySource = new Map<string, { active: number; schemaChars: number }>();
  let schemaChars = 0;
  for (const tool of allTools) {
    if (!activeSet.has(tool.name)) continue;
    const chars = JSON.stringify({
      name: tool.name,
      description: tool.description,
      parameters: tool.parameters,
    }).length;
    schemaChars += chars;
    const row = bySource.get(tool.sourceInfo.source) ?? { active: 0, schemaChars: 0 };
    row.active += 1;
    row.schemaChars += chars;
    bySource.set(tool.sourceInfo.source, row);
  }
  return {
    active: activeNames.length,
    all: allTools.length,
    schemaChars,
    bySource: [...bySource.entries()]
      .map(([source, row]) => ({ source, ...row }))
      .sort((a, b) => (a.source < b.source ? -1 : a.source > b.source ? 1 : 0)),
  };
}

/**
 * The structural slice of a session entry the branch census reads. Injected contexts persist as
 * `type: "custom_message"` entries carrying `content` — distinct from `type: "custom"` state
 * entries (workflow state, objective budget), which the census must NOT count as context.
 */
export interface CensusBranchEntry {
  type: string;
  customType?: string;
  content?: unknown;
}

/** Derived counts for perk-injected branch context (perk's customTypes share the `perk:` prefix). */
export interface BranchContextCensus {
  entries: number;
  /** `custom_message` entries whose customType starts with `perk:`, sorted by customType. */
  perkContexts: { customType: string; copies: number; totalChars: number }[];
  /** `custom_message` entries without the `perk:` prefix (borrowed packages). */
  otherCustomMessages: { copies: number; totalChars: number };
  /** Entries (any type) whose JSON form carries `BINDING_HEADER` — the cold↔warm dedup marker. */
  bindingHeaderCopies: number;
}

/** Char count of a `custom_message` entry's content — string, `text`-part array, or JSON size. */
function contentChars(content: unknown): number {
  if (content === undefined) return 0;
  if (typeof content === "string") return content.length;
  if (Array.isArray(content)) {
    let sum = 0;
    for (const part of content) {
      if (typeof part !== "object" || part === null || Array.isArray(part)) continue;
      const text = (part as { text?: unknown }).text;
      if (typeof text === "string") sum += text.length;
    }
    return sum;
  }
  return JSON.stringify(content).length;
}

/** Census the session branch's injected context (counts/chars only — never message content). */
export function branchContextCensus(entries: readonly CensusBranchEntry[]): BranchContextCensus {
  const perk = new Map<string, { copies: number; totalChars: number }>();
  const other = { copies: 0, totalChars: 0 };
  let bindingHeaderCopies = 0;
  for (const entry of entries) {
    if (JSON.stringify(entry).includes(BINDING_HEADER)) bindingHeaderCopies += 1;
    if (entry.type !== "custom_message") continue;
    const chars = contentChars(entry.content);
    const customType = entry.customType ?? "";
    if (customType.startsWith("perk:")) {
      const row = perk.get(customType) ?? { copies: 0, totalChars: 0 };
      row.copies += 1;
      row.totalChars += chars;
      perk.set(customType, row);
    } else {
      other.copies += 1;
      other.totalChars += chars;
    }
  }
  return {
    entries: entries.length,
    perkContexts: [...perk.entries()]
      .map(([customType, row]) => ({ customType, ...row }))
      .sort((a, b) => (a.customType < b.customType ? -1 : a.customType > b.customType ? 1 : 0)),
    otherCustomMessages: other,
    bindingHeaderCopies,
  };
}

/**
 * Render the census as a fixed multi-line block. The line grammar (the `census:` /
 * `append-system-prompt:` / `context-files:` / `skills:` / `tools:` / `per source:` / `branch:` /
 * `perk contexts:` keys) is stable — the closing audit diffs against these exact keys.
 */
export function renderCensus(
  prompt: PromptCensus,
  tools: ToolsCensus,
  branch: BranchContextCensus,
): string {
  const lines: string[] = ["census:"];
  lines.push(
    prompt.basePromptChars === null
      ? "  base-prompt: pi-default (not measured)"
      : `  base-prompt: custom ${prompt.basePromptChars}c`,
  );
  lines.push(`  append-system-prompt: ${prompt.appendChars}c`);
  const fileList = prompt.contextFiles.files.map((f) => `${f.path}=${f.chars}c`).join(", ");
  lines.push(
    `  context-files: ${prompt.contextFiles.count} file(s), ${prompt.contextFiles.totalChars}c` +
      (fileList.length > 0 ? ` — ${fileList}` : ""),
  );
  lines.push(
    `  skills: ${prompt.skills.visible} visible + ${prompt.skills.hidden} hidden; ` +
      `prompt-section=${prompt.skills.promptSectionChars}c`,
  );
  lines.push(
    `  tools: ${tools.active} active / ${tools.all} registered; schemas=${tools.schemaChars}c; ` +
      `guidelines=${prompt.toolGuidelineChars}c; snippets=${prompt.toolSnippetChars}c`,
  );
  if (tools.bySource.length > 0) {
    const rows = tools.bySource
      .map((r) => `${r.source}=${r.active} (${r.schemaChars}c)`)
      .join("; ");
    lines.push(`    per source: ${rows}`);
  }
  lines.push(
    `  branch: ${branch.entries} entries; binding-header-copies=${branch.bindingHeaderCopies}`,
  );
  const perkRows = branch.perkContexts.map(
    (r) => `${r.customType} ×${r.copies} (${r.totalChars}c)`,
  );
  const perkSegment = perkRows.length > 0 ? perkRows.join("; ") : "none";
  lines.push(
    `    perk contexts: ${perkSegment}; other custom_message ` +
      `×${branch.otherCustomMessages.copies} (${branch.otherCustomMessages.totalChars}c)`,
  );
  return lines.join("\n");
}

/**
 * Register `/perk-selfcheck`: the session-wiring verifier. Runs on a command context (the only
 * context exposing `getSystemPromptOptions()`), so it sees the live splice — not just disk.
 */
export function registerSelfcheck(
  pi: ExtensionAPI,
  opts: { version: string; sharedOk: boolean },
): void {
  registerPerkCommand(pi, "perk-selfcheck", {
    description:
      "Verify perk's session wiring: the ambient index + managed AGENTS block reached the prompt.",
    handler: async (_args, ctx) => {
      const options = ctx.getSystemPromptOptions() as SystemPromptProbeInput;
      const report = buildSelfcheckReport({
        version: opts.version,
        sharedOk: opts.sharedOk,
        onDiskIndex: readAmbientIndex(ctx.cwd),
        options,
      });
      // The census is report-only: it rides the same report but never affects ok/level. A command
      // doesn't fire `before_agent_start`, so the branch reads as of the last completed turn.
      const census = renderCensus(
        promptCensus(options),
        toolsCensus(pi.getAllTools(), pi.getActiveTools()),
        branchContextCensus(branchOf(ctx)),
      );
      // Headless-safe: report() surfaces the derived counts/identifiers (never raw prompt content).
      reportTo(ctx, "selfcheck", report.level, `${report.summary}\n${census}`);
    },
  });
}
