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
// Sensitivity: `getSystemPromptOptions()` exposes the full system-prompt construction inputs. This
// module logs ONLY derived booleans/counts (never the raw prompt text). See docs/learned/pi/.

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { report as reportTo } from "../surfaces/report.ts";

/** Project-scoped ambient routing index, relative to the repo root. */
export const AMBIENT_INDEX_REL_PATH = join(".pi", "APPEND_SYSTEM.md");

/** The managed `AGENTS.md` block marker (cross-plane: written by `perk init`, read here). */
export const MANAGED_AGENTS_MARKER = "<!-- BEGIN perk managed -->";

/** The narrow slice of `BuildSystemPromptOptions` the verifier probes. */
export interface SystemPromptProbeInput {
  appendSystemPrompt?: string;
  contextFiles?: { path: string; content: string }[];
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

/**
 * Register `/perk-selfcheck`: the session-wiring verifier. Runs on a command context (the only
 * context exposing `getSystemPromptOptions()`), so it sees the live splice — not just disk.
 */
export function registerSelfcheck(
  pi: ExtensionAPI,
  opts: { version: string; sharedOk: boolean },
): void {
  pi.registerCommand("perk-selfcheck", {
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
      // Headless-safe: report() surfaces the derived booleans/counts (never raw prompt content).
      reportTo(ctx, "selfcheck", report.level, report.summary);
    },
  });
}
