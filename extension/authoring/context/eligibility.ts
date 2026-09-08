// The ONE authoring-context eligibility policy (contracts.md §8.3/§8.23/§8.31) behind every
// Perk-owned authoring/adapter injection: the plan-authoring context, the objective-, gist- and
// refinement-authoring contexts, and the plannotator/tombell plan-adapter flavors all classify
// the session through `classifyAuthoringContext` instead of each re-deriving a stage exclusion
// list from the bare read-only gate. Pi-free and pure (guard Rule D covers `authoring/` by prefix):
// the Pi installers supply the three inputs from their own authorities and consume the kind.
//
// The rule is POSITIVE evidence, never inference: a session receives plan guidance only when
// (1) the effective read-only gate is active, (2) it is not a native runner child, and (3) the
// full-branch workflow state carries plan evidence — a plan-family `stage` (`plan`, `save`,
// `objective-plan`) or the warm `plan_authoring === true` intent bit the warm plan entries
// record (§8.3). The dedicated objective/gist/refinement stages take precedence and never fall
// through to plan guidance; explicit warm intent CAN authorize plan guidance in an otherwise unscoped or
// non-authoring parent stage without rewriting that stage. Nothing here infers intent from
// draft bytes, prompt markers, tool availability, plan-ref presence, node claims or a child's
// name — an older stage-less session carrying only `mode: "read-only"` stays restricted but
// receives no authoring guidance until the human re-enters `/plan` or an authoring factory.
//
// The runner bit is a SUPPRESSION signal only: a runner child receives no Perk authoring or
// plan-adapter guidance even when its inherited branch history carries authoring evidence, and
// the bit never grants tools or save authority. Legacy adopted children without the bit still
// fail the positive-evidence rule (adoption carries no authoring stage or warm intent).

import { GIST_AUTHOR_STAGE, GIST_SAVE_STAGE } from "../gist/draft.ts";
import { OBJECTIVE_AUTHOR_STAGE, OBJECTIVE_SAVE_STAGE } from "../objective/prose.ts";
import { REFINE_STAGE } from "../refinement/context.ts";

/**
 * The structural workflow-state slice the policy reads (§8.3 `stage` / `plan_authoring` / `mode`).
 * Declared here rather than imported: `authoring/` is a storage-free home (guard Rule H), so the
 * rebuilt state arrives as a parameter and the rebuilt values stay unvalidated `unknown`-ish —
 * the readers below accept literal values only.
 */
export interface AuthoringStateSlice {
  stage?: string;
  plan_authoring?: boolean;
  mode?: string;
}

/**
 * The plan-family stages whose cold claim IS plan evidence: `plan` (and its borrowers — `plan
 * from`, `plan replan`, `learn docs`, `learn code` all claim `plan`), the plan `save` stage, and
 * the `objective-plan` factory. Cold paths need no handoff field: the claimed stage suffices.
 */
export const PLAN_AUTHORING_STAGES: readonly string[] = ["plan", "save", "objective-plan"];

/**
 * The dedicated authoring stages with precedence over plan guidance: their own installers (or
 * the plannotator objective/gist/refinement flavors) own the session, so plan guidance never
 * falls through — even when a stray `plan_authoring: true` sits on the branch (an ad-hoc `/plan`
 * turn followed by a warm `/objective-refine`).
 */
export const DEDICATED_AUTHORING_STAGES: readonly string[] = [
  OBJECTIVE_AUTHOR_STAGE,
  OBJECTIVE_SAVE_STAGE,
  GIST_AUTHOR_STAGE,
  GIST_SAVE_STAGE,
  REFINE_STAGE,
];

/** The three policy inputs, each supplied by the caller's own authority. */
export interface AuthoringContextInput {
  /**
   * The EFFECTIVE read-only restriction: the gate object's `isActive()` (mode/active OR the
   * runner floor) for the gate-composing installers, or the persisted `mode === "read-only"`
   * twin for the adapters that never touch the gate.
   */
  gateActive: boolean;
  /** `PI_SUBAGENT_CHILD === "1"` at session_start — activation-local, suppression only. */
  runnerChild: boolean;
  /** The FULL-branch rebuilt workflow state (never the compacted message window). */
  state: Pick<AuthoringStateSlice, "stage" | "plan_authoring">;
}

/**
 * The classified authoring context of a session: a dedicated stage kind, `plan`, or `null`
 * (ineligible — gate off, runner child, or no positive plan evidence).
 */
export type AuthoringContextKind =
  | "plan"
  | "objective-author"
  | "objective-save"
  | "gist-author"
  | "gist-save"
  | "objective-refine";

/** Whether the persisted mode twin says read-only (the adapters' gate signal). */
export function readOnlyModeOf(state: Pick<AuthoringStateSlice, "mode">): boolean {
  return state.mode === "read-only";
}

/** Literal `true` only — the rebuilt branch value is unvalidated. */
export function hasWarmPlanIntent(state: Pick<AuthoringStateSlice, "plan_authoring">): boolean {
  return state.plan_authoring === true;
}

/** Whether `stage` is one of the dedicated objective/gist/refinement authoring stages. */
export function isDedicatedAuthoringStage(stage: string | undefined): boolean {
  return stage !== undefined && DEDICATED_AUTHORING_STAGES.includes(stage);
}

/**
 * Classify the session's authoring context. Order: gate off or runner child → null; a dedicated
 * stage → its own kind (precedence — plan evidence on the same branch is ignored); positive plan
 * evidence (plan-family stage OR warm intent) → `plan`; otherwise null.
 */
export function classifyAuthoringContext(
  input: AuthoringContextInput,
): AuthoringContextKind | null {
  if (!input.gateActive || input.runnerChild) return null;
  const stage = input.state.stage;
  switch (stage) {
    case OBJECTIVE_AUTHOR_STAGE:
      return "objective-author";
    case OBJECTIVE_SAVE_STAGE:
      return "objective-save";
    case GIST_AUTHOR_STAGE:
      return "gist-author";
    case GIST_SAVE_STAGE:
      return "gist-save";
    case REFINE_STAGE:
      return "objective-refine";
    default:
      break;
  }
  if (stage !== undefined && PLAN_AUTHORING_STAGES.includes(stage)) return "plan";
  return hasWarmPlanIntent(input.state) ? "plan" : null;
}

/** The plan-guidance eligibility rule (the classification's `plan` arm). */
export function isPlanAuthoringEligible(input: AuthoringContextInput): boolean {
  return classifyAuthoringContext(input) === "plan";
}
