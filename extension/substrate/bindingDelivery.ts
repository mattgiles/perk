// Warm-door (TS-extension) delivery of resolved skill bindings — the in-session twin of the cold
// door (perk/substrate/binding_delivery.py). Both planes render the SAME resolved overlay (defaults
// ⊕ user bindings; `nudge` -> a pointer line, `transclude` -> the inlined skill body) under the
// SAME header literal. The cold door appends it to a launch's initial prompt; this module renders
// it at two WARM surfaces:
//
//   Mechanism A — the session's RESOLVED trigger (`activeBindingTrigger`): a `before_agent_start`
//   handler (mirroring `pi/v1/plan.ts` / `pi/v1/objectiveAuthoring.ts`) injects that trigger's
//   bindings as a hidden context message. The trigger is the recorded stage's `stage:<id>`, or —
//   for a stage-less session in plan mode (persisted `mode: "read-only"`; the warm `/plan` toggle
//   and every other stage-less gated session, the same session `isPlanGuidanceStage(undefined)`
//   admits for plan guidance) — `stage:plan`. Plan mode is a MODE, never a recorded stage. This is
//   the delivery path for `stage:plan`'s `perk-plan` pointer, since a cold `perk plan` launches
//   idle (no initial prompt to augment) and a warm `/plan` records no stage at all.
//   Mechanism B — `bindingSuffix()` is appended into the guidance of perk's warm slash-commands so
//   each self-delivers its pointer (a warm `/objective-plan` records no stage, so Mechanism A
//   resolves it to `stage:plan`, never `stage:objective-plan`).
//
// This is the SINGLE delivery path for perk's own nudges. Delivery NEVER double-delivers. The
// cross-plane dedup marker is `BINDING_HEADER` on USER turns: the cold door's initial prompt and a
// warm command's Mechanism B seed carry it, and such a turn is that door's own delivery whatever
// it rendered — so it suppresses Mechanism A while live (a door that borrows a stage never also
// receives the borrowed stage's bindings warm). An OWNED `perk:binding-context` custom is evidence
// only for the render it carries byte-exactly: a warm session can change its trigger (a stage-less
// `/plan` followed by `/objective-refine`) or its overlay, and a stale owned copy must neither
// linger in model context nor block re-delivery of the current render — so the `context` strip
// retires every owned copy that is not the current render. Mechanism A therefore injects ONLY
// when neither the submitting turn's prompt NOR Pi's live context projection
// (`pi/v1/contextEvidence.ts`) carries such evidence (idempotent across turns/reloads; after
// compaction drops the original from model context it re-delivers, and a summary quoting the
// header never suppresses). The prompt scan is load-bearing on the launch turn: at
// `before_agent_start` the just-submitted prompt is NOT yet persisted, so the projection alone
// would miss a cold seed's binding suffix and double-deliver. The full branch is read only for
// the trigger (`activeRender` — one read yields both `stage` and `mode`) — eligibility survives
// compaction; delivery evidence is Pi's. A projection read failure escapes the hook to Pi's
// hook-error reporting rather than injecting a guessed copy.
//
// The runner fence: Mechanism A never fires in a runner child (the composition root's
// `runnerChild` closure — the fence every injected authoring context takes), and its `context`
// strip treats a runner child as "nothing renders". A floored wave lane persists exactly the
// stage-less `{mode: "read-only"}` shape a warm `/plan` leaves, so without the fence every lane
// would receive `stage:plan`'s bindings. Suppression only, never a grant.
//
// LBYL on the render path: a missing/unreadable transclude target degrades to the nudge pointer
// with a loud-but-non-fatal warning, never throws, never blocks a turn (only a session read
// failure — branch or projection — escapes the hooks). Resolver shape `issues` are NOT surfaced
// warm (the cold launch + doctor own them); only the transclude `warnings` are.

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { activeContextMessages, userContentCarriesMarker } from "../pi/v1/contextEvidence.ts";
import { loadDefaultBindings, resolveBindings, type SkillBinding } from "./bindings.ts";
import { loadPerkConfig } from "./config.ts";
import {
  type BranchEntry,
  branchOf,
  rebuildWorkflowState,
  type WorkflowState,
} from "./workflowState.ts";

/**
 * The cross-plane dedup marker AND render header. MUST stay byte-identical to the Python cold
 * door's `_HEADER` (perk/substrate/binding_delivery.py) — both planes render under it so a cold launch and a
 * warm injection never double-deliver. Pinned by a literal test in both planes (§8.9).
 */
export const BINDING_HEADER = "The following skill binding(s) apply here:";

/** The hidden context customType carrying a warm-injected stage-binding render (Mechanism A). */
export const BINDING_CONTEXT_TYPE = "perk:binding-context";

/** Plan mode's binding trigger: a stage-less gated session resolves to the `plan` stage's bindings. */
const PLAN_MODE_TRIGGER = "stage:plan";

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
 * none match). `nudge` renders a `Follow the \`<skill>\` skill (read
 * \`.agents/skills/<skill>/SKILL.md\`).` pointer — the read path is unconditional, so a skill
 * hidden from the ambient prompt (`disable-model-invocation: true`) stays reachable; `transclude`
 * inlines
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
    parts.push(
      `Follow the \`${binding.skill}\` skill ` +
        `(read \`${SKILLS_SUBDIR}/${binding.skill}/${SKILL_FILENAME}\`).`,
    );
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
 * The session's Mechanism-A binding trigger, a pure function of the rebuilt workflow state: a
 * recorded stage → `stage:<id>` regardless of the gate (a `/plan` toggle inside a stage-recorded
 * session keeps the run's own bindings); no stage and a persisted read-only `mode` → plan mode's
 * `stage:plan`; otherwise `null`. Runner children are fenced by the caller, not here.
 */
export function activeBindingTrigger(state: WorkflowState): string | null {
  if (state.stage) return `stage:${state.stage}`;
  if (state.mode === "read-only") return PLAN_MODE_TRIGGER;
  return null;
}

/** The resolved trigger's render, or `null` when the session resolves to no trigger. */
function activeRender(cwd: string, branch: readonly BranchEntry[]): BindingRender | null {
  const trigger = activeBindingTrigger(rebuildWorkflowState(branch));
  return trigger === null ? null : renderBindings(cwd, trigger);
}

/**
 * Whether a delivery of the current binding render is live in Pi's context projection: a USER
 * turn carrying the header (the persisted cold prompt or a warm command's Mechanism B seed — a
 * door's own delivery, whatever it rendered), or an owned custom that IS `render` byte-exactly
 * (an owned copy of a superseded render is not evidence). Throws when the projection read fails —
 * the hook boundary owns that.
 */
function deliveryIsLive(ctx: ExtensionContext, render: string): boolean {
  const live = activeContextMessages(ctx);
  return (
    userContentCarriesMarker(live, BINDING_HEADER) ||
    live.some((message) => isOwnedCopyOf(message, render))
  );
}

/**
 * Whether `message` is an owned binding-context custom whose content IS `render` byte-exactly (a
 * string, or one `{ type: "text" }` part). Exact, not a substring scan: an owned copy is only ever
 * the render it was injected with, and a superseded render that merely CONTAINS the current one
 * (an overlay whose trailing binding was removed) must retire, not count. Structural over Pi's
 * message shapes (session files are parsed unvalidated) so the `context` strip reuses it.
 */
function isOwnedCopyOf(message: unknown, render: string): boolean {
  const { customType, content } = message as { customType?: unknown; content?: unknown };
  if (customType !== BINDING_CONTEXT_TYPE) return false;
  if (typeof content === "string") return content === render;
  if (!Array.isArray(content)) return false;
  return content.some((part) => {
    if (typeof part !== "object" || part === null) return false;
    const { type, text } = part as { type?: unknown; text?: unknown };
    return type === "text" && text === render;
  });
}

/**
 * Register warm-door binding delivery: Mechanism A's dedup-guarded `before_agent_start` injection
 * of the session's resolved trigger plus a render-exact `context` strip (keep only the owned copy
 * of the current render; retire every other). Inert when nothing renders; the render path never
 * throws (only a failed session read escapes to Pi's hook-error reporting). `runnerChild` is the
 * composition root's per-`session_start` runner bit — suppression only, ahead of any read.
 * Mechanism B (`bindingSuffix`) is wired by the command modules themselves.
 */
export function registerBindingDelivery(pi: ExtensionAPI, runnerChild: () => boolean): void {
  // Mechanism A — inject the resolved trigger's bindings as a hidden context message, but ONLY
  // when neither the submitting turn's prompt NOR Pi's live context projection already carries a
  // live delivery (a door-seeded user turn's header, or an owned copy of this exact render) — the
  // cold↔warm idempotency guard. The `event.prompt` scan covers the launch turn, where the
  // just-submitted prompt is not yet persisted; a worker prompt carries no header, so Mechanism A
  // still fires there (contracts.md §8.38). Render-before-dedup: an inert session never reads the
  // projection; a runner child reads nothing at all.
  pi.on("before_agent_start", async (event, ctx) => {
    if (runnerChild()) return;
    const rendered = activeRender(ctx.cwd, branchOf(ctx));
    if (rendered === null || rendered.text === null) return;
    if (event.prompt.includes(BINDING_HEADER)) return;
    if (deliveryIsLive(ctx, rendered.text)) return;
    for (const warning of rendered.warnings) console.error(`perk: ${warning}`);
    return {
      message: {
        customType: BINDING_CONTEXT_TYPE,
        content: rendered.text,
        display: false,
      },
    };
  });

  // Render-exact retention: keep an owned binding-context custom only while it IS the current
  // render (the model must see the nudge, and the dedup above relies on it persisting on
  // the branch); retire every other owned copy — a superseded trigger (the session changed stage
  // or entered/left plan mode), an edited overlay, or anything at all when nothing renders (a
  // runner child included). Retention mirrors evidence.
  //
  // Deliberately NARROWER than the injected authoring contexts: it strips ONLY the
  // BINDING_CONTEXT_TYPE custom, never a user message carrying the header — a cold launch's
  // initial prompt or a warm seed legitimately carries BINDING_HEADER and must survive in context,
  // even after the trigger stops binding. The strip never reads the projection (it filters the
  // messages Pi hands it).
  pi.on("context", async (event, ctx) => {
    const current = runnerChild() ? null : (activeRender(ctx.cwd, branchOf(ctx))?.text ?? null);
    return {
      messages: event.messages.filter((m) => {
        if ((m as { customType?: unknown }).customType !== BINDING_CONTEXT_TYPE) return true;
        return current !== null && isOwnedCopyOf(m, current);
      }),
    };
  });
}
