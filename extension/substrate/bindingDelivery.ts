// Warm-door (TS-extension) delivery of resolved skill bindings — the in-session twin of the cold
// door (perk/substrate/binding_delivery.py). Both planes render the SAME resolved overlay (defaults
// ⊕ user bindings; `nudge` -> a pointer line, `transclude` -> the inlined skill body) under the
// SAME header literal. The cold door appends it to a launch's initial prompt; this module renders
// it at two WARM surfaces:
//
//   Mechanism A — stage triggers: a `before_agent_start` handler (mirroring planMode.ts /
//   objectiveAuthor.ts) injects the launched stage's bindings as a hidden context message — the
//   delivery path for `stage:plan`'s `perk-plan` pointer, since a cold `perk plan` launches idle
//   (no initial prompt to augment).
//   Mechanism B — `bindingSuffix()` is appended into the guidance of perk's warm slash-commands so
//   each self-delivers its pointer (a warm `/objective-plan` run outside a stage:objective-plan
//   session gets none from Mechanism A).
//
// This is the SINGLE delivery path for perk's own nudges. Delivery NEVER double-delivers: the
// cold↔warm dedup marker is `BINDING_HEADER` itself — the cold door's initial prompt and every warm
// injection carry it, so Mechanism A injects ONLY when nothing on the branch already carries the
// header (idempotent across turns/reloads; after compaction drops the original it re-delivers).
//
// LBYL throughout: a missing/unreadable transclude target degrades to the nudge pointer with a
// loud-but-non-fatal warning, never throws, never blocks a turn. Resolver shape `issues` are NOT
// surfaced warm (the cold launch + doctor own them); only the transclude `warnings` are.

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { loadDefaultBindings, resolveBindings, type SkillBinding } from "./bindings.ts";
import { loadPerkConfig } from "./config.ts";
import { type BranchEntry, branchOf, rebuildWorkflowState } from "./workflowState.ts";

/**
 * The cross-plane dedup marker AND render header. MUST stay byte-identical to the Python cold
 * door's `_HEADER` (perk/substrate/binding_delivery.py) — both planes render under it so a cold launch and a
 * warm injection never double-deliver. Pinned by a literal test in both planes (§8.9).
 */
export const BINDING_HEADER = "The following skill binding(s) apply here:";

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
 * The full resolved bindings: the shipped defaults ⊕ the user overlay. The TS twin of cold's
 * `resolve_bindings(...).bindings` (perk/substrate/binding_delivery.py) — delivers the defaults too
 * (perk's own nudges are no longer hardcoded), so there is no longer a default subtraction.
 */
export function resolvedBindings(cwd: string): SkillBinding[] {
  return resolveBindings(loadPerkConfig(cwd).bindings, loadDefaultBindings()).bindings;
}

/**
 * Render the resolved bindings matching `trigger` into a header-joined fragment (or `null` when
 * none match). `nudge` renders a `Follow the \`<skill>\` skill.` pointer; `transclude` inlines
 * `.agents/skills/<skill>/SKILL.md` (frontmatter stripped), degrading to the nudge pointer with a
 * loud-but-non-fatal warning when the file is absent/unreadable. Pure but for the LBYL file read.
 */
export function renderBindings(cwd: string, trigger: string): BindingRender {
  const mine = resolvedBindings(cwd).filter((binding) => binding.trigger === trigger);
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
    } else if (!skillInstalled(cwd, binding.skill)) {
      // The nudge mirror of the transclude warning: a binding to a skill that is
      // not installed is reported loud-but-non-fatal, never silently delivered. The pointer is
      // still emitted so the model gets the nudge.
      warnings.push(
        `skill binding: skill \`${binding.skill}\` for \`${binding.trigger}\` is not installed ` +
          `under ${SKILLS_SUBDIR}/${binding.skill}/${SKILL_FILENAME} — the pointer may dangle.`,
      );
    }
    parts.push(`Follow the \`${binding.skill}\` skill.`);
  }
  const text = parts.length > 0 ? [BINDING_HEADER, ...parts].join("\n\n") : null;
  return { text, warnings };
}

/**
 * The Mechanism-B suffix: the rendered bindings for `trigger` to append into a warm command's
 * guidance (empty string when none match). Every perk warm slash-command self-delivers its pointer
 * this way, by `stage:<id>` or `command:<id>`. A leading blank line keeps it
 * visually distinct from the guidance it follows. Any render warnings (missing transclude target or
 * uninstalled nudge skill) are `console.error`-ed loud-but-non-fatal — the nudge
 * fallback still reaches the model, but the misconfiguration is no longer surfaced silently.
 */
export function bindingSuffix(cwd: string, trigger: string): string {
  const { text, warnings } = renderBindings(cwd, trigger);
  for (const warning of warnings) console.error(`perk: ${warning}`);
  return text ? `\n\n${text}` : "";
}

/** Whether `.agents/skills/<skill>/SKILL.md` exists under `cwd` (the warm delivery read path). */
function skillInstalled(cwd: string, skill: string): boolean {
  return existsSync(join(cwd, SKILLS_SUBDIR, skill, SKILL_FILENAME));
}

/** Read `.agents/skills/<skill>/SKILL.md` (frontmatter stripped); `null` if absent/unreadable. */
function readSkillBody(cwd: string, skill: string): string | null {
  const path = join(cwd, SKILLS_SUBDIR, skill, SKILL_FILENAME);
  if (!existsSync(path)) return null;
  try {
    // Normalize CRLF/CR before stripping (the miniJinja.ts pattern): Node's readFileSync keeps
    // `\r\n` where Python's read_text() normalizes, so without this a CRLF checkout would defeat
    // the `---\n` frontmatter check AND break the cross-plane byte parity pinned by
    // tests/test_binding_render_parity.py.
    return stripFrontmatter(readFileSync(path, "utf8").replace(/\r\n?/g, "\n"));
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
 * bindings are live; strip the stale custom otherwise). Inert when nothing matches the stage;
 * never throws. Mechanism B (`bindingSuffix`) is wired by the command modules themselves.
 */
export function registerBindingDelivery(pi: ExtensionAPI): void {
  // Mechanism A — inject the launched stage's resolved bindings as a hidden context message,
  // but ONLY when no entry on the branch already carries BINDING_HEADER (the cold door's initial
  // prompt or a prior warm inject) — the cold↔warm idempotency guard.
  pi.on("before_agent_start", async (_event, ctx) => {
    const branch = branchOf(ctx);
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
    const branch = branchOf(ctx);
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
