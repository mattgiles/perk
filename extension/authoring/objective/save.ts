// The objective save feature: the narrow exterior `ObjectiveBackend` port (one production
// adapter — the `perk objective create` cold door in pi/v1 — plus one deterministic fake in the
// tests: the port admission rule), the `saveObjective` operation, and the shared
// APPROVED-review → save orchestration `objectiveApprovalSave` (the `gistApprovalSave`/
// `planApprovalSave` mirror — three sibling flows, deliberately unshared shapes).
//
// Identity-less saves stay legal: `session.runId === null` ⇒ the backend sees `runId: null`
// (the adapter omits `--run-id`) and the LINKAGE op still runs — workflow-state appends are
// branch-backed and identity-independent (today's behavior, preserved). Backend saves are not
// abortable mid-flight (stated, not changed).
//
// The §8.63 dream gate arrives INJECTED (ctx-bound by the adapter); the §8.64 transfer staging
// (the reviewed CANONICAL parts crossing to the Python plane) is the ADAPTER's — the port's
// `dreamParts` carries the gate-proven parts and the adapter stages the run-scoped
// `dream-report-transfer.json` handoff atomically before the cold door.

import type { WorkflowChangeResult, WorkflowSession } from "../../session/workflowSession.ts";
import type { DeliveryChoice } from "./draft.ts";
import { resumeObjectiveDraft } from "./draft.ts";
import type { DreamReportGateOutcome, ObjectiveDreamReportBlock } from "./dreamReportGate.ts";

/** The backend save facts (`id` is the opaque string objective id — contracts §8.21). */
export type ObjectiveBackendSaveResult =
  | { status: "saved"; id: string; url: string; existed: boolean | null }
  | { status: "failed"; message: string; errorType: string };

/**
 * The narrow exterior port the save operation writes through. `runId: null` means the caller
 * has no session identity — the adapter omits its run linkage (an identity-less save keeps
 * working). `dreamParts` (the §8.63 gate-proven CANONICAL parts) makes the adapter stage the
 * §8.64 transfer handoff before invoking the door.
 */
export interface ObjectiveBackend {
  create(req: {
    prose: string;
    title?: string;
    base?: string;
    delivery?: DeliveryChoice;
    roadmap?: unknown[];
    runId: string | null;
    dreamParts?: string[];
  }): Promise<ObjectiveBackendSaveResult>;
}

/**
 * The §8.63 dream-report carrier's two proven sources, as a discriminated union so a partial
 * "reviewed" bag cannot compile: the direct tool path supplies only the raw `input` (the save
 * stamps `generated_at` fresh); the approval path passes the reviewed artifact block through
 * WHOLE — stored stamp AND stored parts (byte-compared against the fresh re-render).
 */
export type DreamReportCarrier =
  | { source: "direct"; input: unknown }
  | { source: "reviewed"; block: ObjectiveDreamReportBlock };

/** The typed save input — decode owns the shape at the tool boundary (pi/v1). */
export interface SaveObjectiveInput {
  prose: string;
  title?: string;
  roadmap?: unknown[];
  base?: string;
  delivery?: DeliveryChoice;
  dream_report?: DreamReportCarrier;
}

/**
 * The save outcome. The saved arm carries the backend facts plus the session seam's own
 * `WorkflowChangeResult` linkage VERBATIM (the `SavePlanOutcome` precedent; `null` = not
 * attempted — a failed save never touches the session). The adapter renders the terminating
 * "Saved/Found existing objective #id → url" twin and appends the budget activation marker iff
 * the linkage was attempted and not `unchanged` (byte-equivalent to the historical
 * `linked !== objectiveId` guard — applied/unverified/rejected all imply "differed", and the
 * marker never keyed off the append's read-back result).
 */
export type SaveObjectiveOutcome =
  | {
      status: "saved";
      id: string;
      url: string;
      existed: boolean | null;
      linkage: WorkflowChangeResult | null;
    }
  | { status: "failed"; message: string; errorType: string };

/** The dependency bag the save operation runs over (the adapter composes production values). */
export interface ObjectiveSaveDeps {
  session: WorkflowSession;
  backend: ObjectiveBackend;
  /** The §8.63 gate, adapter-bound (`resolveDreamReportGate` over the production recovery capability). */
  resolveDreamGate: (input: unknown, generatedAt: string) => DreamReportGateOutcome;
}

/**
 * The single save operation every objective-save surface calls. Ordering preserved exactly:
 * validate the non-blank prose → the §8.63 fail-closed gate re-validation (presence is the
 * `input.dream_report === undefined` boundary — an `{input: undefined}` carrier is never
 * constructed) → the approval path's stored-parts byte-compare (the same stored `generated_at`
 * stamp keeps the comparison deterministic; drift/tamper between draft-write and save refuses
 * `bad_state`, nothing saved) → `backend.create` with `runId: session.runId` → on success,
 * link the live session (`apply({kind: "link-objective"})` — the seam appends iff the rebuilt
 * `active_objective` differs, strict read-back). Whitespace-only `title`/`base` normalize to
 * absent (trim-or-omit, matching the draft path — a blank `--title` can no longer reach the
 * cold door). Never throws.
 */
export async function saveObjective(
  input: SaveObjectiveInput,
  deps: ObjectiveSaveDeps,
): Promise<SaveObjectiveOutcome> {
  const prose = input.prose.trim();
  if (!prose) {
    return {
      status: "failed",
      message: "no objective prose to save (draft the objective first)",
      errorType: "invalid_input",
    };
  }
  const title = input.title?.trim() || undefined;
  const base = input.base?.trim() || undefined;

  const carrier = input.dream_report;
  const generatedAt =
    carrier?.source === "reviewed" ? carrier.block.generated_at : new Date().toISOString();
  const gate =
    carrier === undefined
      ? deps.resolveDreamGate(undefined, generatedAt)
      : deps.resolveDreamGate(
          carrier.source === "reviewed" ? carrier.block.input : carrier.input,
          generatedAt,
        );
  if (gate.kind === "refuse") {
    return { status: "failed", message: gate.detail, errorType: gate.errorType };
  }
  if (gate.kind === "block" && carrier?.source === "reviewed") {
    // The approval path: the reviewed (stored) parts must byte-match the re-render against
    // freshly recovered context.
    if (JSON.stringify(gate.block.parts) !== JSON.stringify(carrier.block.parts)) {
      return {
        status: "failed",
        message: "the reviewed report no longer matches the wave state — re-draft and re-review",
        errorType: "bad_state",
      };
    }
  }

  const saved = await deps.backend.create({
    prose,
    ...(title !== undefined ? { title } : {}),
    ...(base !== undefined ? { base } : {}),
    ...(input.delivery !== undefined ? { delivery: input.delivery } : {}),
    ...(input.roadmap !== undefined ? { roadmap: input.roadmap } : {}),
    runId: deps.session.runId,
    ...(gate.kind === "block" ? { dreamParts: gate.block.parts } : {}),
  });
  if (saved.status === "failed") return saved;

  // Link the live session: the seam appends iff the rebuilt `active_objective` differs, with a
  // strict read-back — verbatim into the outcome (the seam's report() stays the loudness
  // channel; a linkage failure is loud-but-non-fatal, the save stands).
  const linkage = deps.session.apply({ kind: "link-objective", objective: saved.id });
  return { status: "saved", id: saved.id, url: saved.url, existed: saved.existed, linkage };
}

/** The structural gate slice the approval→save flow releases (the `GistGate`/`PlanGate` sibling). */
export interface ObjectiveGate {
  isActive(): boolean;
  exit(): void;
}

/** The approval→save dependency bag: the save deps + the gate. */
export interface ObjectiveApprovalSaveDeps extends ObjectiveSaveDeps {
  gate: ObjectiveGate;
}

/** The approval→save orchestration outcome (the objective `ApprovalSaveOutcome`). */
export type ObjectiveApprovalSaveOutcome =
  | { status: "no-draft" }
  | {
      status: "saved";
      result: Extract<SaveObjectiveOutcome, { status: "saved" }>;
      gateExited: boolean;
    }
  | {
      status: "save-failed";
      result: Extract<SaveObjectiveOutcome, { status: "failed" }>;
      gateExited: false;
    };

/**
 * The shared APPROVED-review → save orchestration (the objective sibling of `planApprovalSave`):
 * an APPROVED objective review (`plan_review`'s objective arm) and the manual `/objective-save`
 * failsafe both run THIS. Flow: re-read the STRUCTURED draft artifact at save time
 * (`resumeObjectiveDraft` — never the rendered markdown, never in-hand bytes; the artifact's
 * `dream_report` block passes through whole: stored stamp + stored parts) → `saveObjective` →
 * gate exit ONLY on a successful save while read-only (the D1a pattern: snapshot
 * `gate.isActive()` BEFORE the save; a failed save leaves the gate ON). No draft → `no-draft`
 * (nothing saved, the gate untouched); callers render their own fallback. Title precedence: an
 * explicit `opts.title` wins; else the draft's `title`; else the cold door derives from the
 * prose heading.
 */
export async function objectiveApprovalSave(
  deps: ObjectiveApprovalSaveDeps,
  opts: { title?: string } = {},
): Promise<ObjectiveApprovalSaveOutcome> {
  const draft = resumeObjectiveDraft(deps.session);
  if (draft === null) return { status: "no-draft" };
  // D1a: snapshot the gate BEFORE the save; on success, exit it so save marks the read-only →
  // read-write boundary in one gesture. A failed save leaves the gate on.
  const wasReadOnly = deps.gate.isActive();
  const title = opts.title ?? draft.title;
  const result = await saveObjective(
    {
      prose: draft.prose,
      ...(title !== undefined ? { title } : {}),
      roadmap: draft.roadmap,
      ...(draft.base !== undefined ? { base: draft.base } : {}),
      ...(draft.delivery !== undefined ? { delivery: draft.delivery } : {}),
      ...(draft.dream_report !== undefined
        ? { dream_report: { source: "reviewed" as const, block: draft.dream_report } }
        : {}),
    },
    deps,
  );
  if (result.status === "failed") return { status: "save-failed", result, gateExited: false };
  let gateExited = false;
  if (wasReadOnly) {
    deps.gate.exit();
    gateExited = true;
  }
  return { status: "saved", result, gateExited };
}
