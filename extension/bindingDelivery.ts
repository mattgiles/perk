// Node 2.2 — warm-door (TS-extension) delivery of user-originated skill bindings. The in-session
// twin of Node 2.1's cold door (perk/binding_delivery.py): both planes render the SAME
// user-originated overlay (`nudge` -> a pointer line, `transclude` -> the inlined skill body) under
// the SAME header literal. The cold door appends it to a launch's initial prompt; this module
// renders it at two WARM surfaces:
//
//   Mechanism A — stage triggers: a `before_agent_start` handler (mirroring planMode.ts /
//   objectiveAuthor.ts) injects the launched stage's bindings as a hidden context message.
//   Mechanism B — command triggers: `commandBindingSuffix()` is appended into the guidance of the
//   two non-stage warm slash-commands (`/objective-reconcile`, `/learn-docs`).
//
// Delivery is ADDITIVE (perk's hardcoded "Follow the … skill" strings are untouched — Node 2.3
// migrates them) and NEVER double-delivers. The cold↔warm dedup marker is `BINDING_HEADER` itself:
// the cold door's initial prompt and every warm injection carry it, so Mechanism A injects ONLY
// when nothing already on the branch carries the header (idempotent across turns/reloads; after
// compaction drops the original the header disappears and it re-delivers — its ongoing value).
//
// LBYL throughout (dignified-python's TS sibling): a missing/unreadable transclude target degrades
// to the nudge pointer with a loud-but-non-fatal warning, never throws, never blocks a turn.
// Resolver shape `issues` are NOT surfaced warm (the cold launch + doctor own them); only the
// transclude `warnings` are.

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { loadDefaultBindings, resolveBindings, type SkillBinding } from "./bindings.ts";
import { loadPerkConfig } from "./config.ts";
import { type BranchEntry, rebuildWorkflowState } from "./workflowState.ts";

/**
 * The cross-plane dedup marker AND render header. MUST stay byte-identical to the Python cold
 * door's `_HEADER` (perk/binding_delivery.py) — both planes render under it so a cold launch and a
 * warm injection never double-deliver. Pinned by a literal test in both planes (§8.9).
 */
export const BINDING_HEADER =
  "The following skill binding(s) apply here (configured via .pi/perk.toml):";

/** The hidden context customType carrying a warm-injected stage-binding render (Mechanism A). */
export const BINDING_CONTEXT_TYPE = "perk:binding-context";

const SKILLS_SUBDIR = join(".agents", "skills");
const SKILL_FILENAME = "SKILL.md";

/** The rendered warm delivery for one trigger: the prompt fragment (or `null`) + any warnings. */
export interface BindingRender {
  text: string | null;
  warnings: string[];
}

/**
 * Value-equality key for a binding — the TS twin of Python's frozen-dataclass set membership. A
 * `SkillBinding` is a plain object (no value identity), so the user-originated filter compares the
 * full tuple, exactly mirroring `binding not in default_set`.
 */
function bindingKey(binding: SkillBinding): string {
  return JSON.stringify([
    binding.trigger,
    binding.kind,
    binding.targetId,
    binding.skill,
    binding.mode,
  ]);
}

/**
 * The user-originated resolved bindings: the resolved overlay MINUS the shipped defaults (by exact
 * value-equality). The TS twin of cold's `mine` (perk/binding_delivery.py) — perk still hardcodes
 * its own default nudges, so re-delivering a default would double up.
 */
export function userOriginatedBindings(cwd: string): SkillBinding[] {
  const defaults = loadDefaultBindings();
  const resolved = resolveBindings(loadPerkConfig(cwd).bindings, defaults).bindings;
  const defaultKeys = new Set(defaults.map(bindingKey));
  return resolved.filter((binding) => !defaultKeys.has(bindingKey(binding)));
}

/**
 * Render the user-originated bindings matching `trigger` into a header-joined fragment (or `null`
 * when none match). `nudge` renders a `Follow the \`<skill>\` skill.` pointer; `transclude` inlines
 * `.agents/skills/<skill>/SKILL.md` (frontmatter stripped), degrading to the nudge pointer with a
 * loud-but-non-fatal warning when the file is absent/unreadable. Pure but for the LBYL file read.
 */
export function renderBindings(cwd: string, trigger: string): BindingRender {
  const mine = userOriginatedBindings(cwd).filter((binding) => binding.trigger === trigger);
  const warnings: string[] = [];
  const parts: string[] = [];
  for (const binding of mine) {
    if (binding.mode === "transclude") {
      const body = readSkillBody(cwd, binding.skill);
      if (body !== null) {
        parts.push(`Skill \`${binding.skill}\` (inlined for \`${binding.trigger}\`):\n\n${body}`);
        continue;
      }
      warnings.push(
        `skill binding: transclude target for \`${binding.skill}\` not found under ` +
          `${SKILLS_SUBDIR}/${binding.skill}/${SKILL_FILENAME} — falling back to a pointer.`,
      );
    }
    parts.push(`Follow the \`${binding.skill}\` skill.`);
  }
  const text = parts.length > 0 ? [BINDING_HEADER, ...parts].join("\n\n") : null;
  return { text, warnings };
}

/**
 * The Mechanism-B suffix: the rendered `command:<id>` bindings to append into a warm command's
 * guidance (empty string when none match). A leading blank line keeps it visually distinct from the
 * guidance it follows. The transclude warning (if any) degrades silently here — the nudge fallback
 * is what reaches the model; the loud surface is the cold launch + doctor.
 */
export function commandBindingSuffix(cwd: string, trigger: string): string {
  const { text } = renderBindings(cwd, trigger);
  return text ? `\n\n${text}` : "";
}

/** Read `.agents/skills/<skill>/SKILL.md` (frontmatter stripped); `null` if absent/unreadable. */
function readSkillBody(cwd: string, skill: string): string | null {
  const path = join(cwd, SKILLS_SUBDIR, skill, SKILL_FILENAME);
  if (!existsSync(path)) return null;
  try {
    return stripFrontmatter(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

/** Drop a leading `---`-delimited YAML frontmatter block; return the body stripped. */
function stripFrontmatter(text: string): string {
  if (!text.startsWith("---\n")) return text;
  const lines = text.split("\n");
  for (let i = 1; i < lines.length; i++) {
    if (lines[i] === "---")
      return lines
        .slice(i + 1)
        .join("\n")
        .trim();
  }
  return text; // no closing delimiter — leave the text unchanged
}

/**
 * Whether anything on the branch already carries `BINDING_HEADER` — the cold launch's initial
 * prompt OR a prior warm injection. Serializing each entry is the robust, shape-agnostic scan: the
 * header is a distinctive literal, so a substring hit means "already delivered on this branch".
 */
function branchHasHeader(branch: readonly BranchEntry[]): boolean {
  return branch.some((entry) => JSON.stringify(entry).includes(BINDING_HEADER));
}

/** The launched stage's `stage:<id>` render, or `null` when there is no stage / nothing matches. */
function activeStageRender(cwd: string, branch: readonly BranchEntry[]): BindingRender | null {
  const stage = rebuildWorkflowState(branch).stage;
  if (!stage) return null;
  return renderBindings(cwd, `stage:${stage}`);
}

/**
 * Register warm-door binding delivery: Mechanism A's dedup-guarded `before_agent_start` injection
 * plus a `context` strip mirroring planMode.ts / objectiveAuthor.ts (keep while the stage's
 * bindings are live; strip the stale custom otherwise). Inert when nothing is user-originated;
 * never throws. Mechanism B (`commandBindingSuffix`) is wired by the command modules themselves.
 */
export function registerBindingDelivery(pi: ExtensionAPI): void {
  // Mechanism A — inject the launched stage's user-originated bindings as a hidden context message,
  // but ONLY when no entry on the branch already carries BINDING_HEADER (the cold door's initial
  // prompt or a prior warm inject) — the cold↔warm idempotency guard.
  pi.on("before_agent_start", async (_event, ctx) => {
    const branch = ctx.sessionManager.getBranch() as unknown as BranchEntry[];
    const rendered = activeStageRender(ctx.cwd, branch);
    if (rendered === null || rendered.text === null) return;
    if (branchHasHeader(branch)) return;
    for (const warning of rendered.warnings) console.error(`perk: ${warning}`);
    return {
      message: {
        customType: BINDING_CONTEXT_TYPE,
        content: rendered.text,
        display: false,
      },
    };
  });

  // Strip a STALE binding-context custom from the model window when the current stage no longer
  // renders bindings (stage changed, or the overlay was removed) — the same hygiene planMode /
  // objectiveAuthor apply to their authoring contexts. While the stage IS live we keep it (the
  // model must see the nudge), and the dedup above relies on it persisting on the branch.
  //
  // Deliberately NARROWER than planMode: it strips ONLY the BINDING_CONTEXT_TYPE custom, never a
  // user message carrying the header — a cold launch's initial prompt legitimately carries
  // BINDING_HEADER and must survive in context.
  pi.on("context", async (event, ctx) => {
    const branch = ctx.sessionManager.getBranch() as unknown as BranchEntry[];
    const rendered = activeStageRender(ctx.cwd, branch);
    if (rendered !== null && rendered.text !== null) return;
    return {
      messages: event.messages.filter((m) => {
        const msg = m as { customType?: string };
        return msg.customType !== BINDING_CONTEXT_TYPE;
      }),
    };
  });
}
