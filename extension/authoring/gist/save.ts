// The gist save feature: the narrow exterior `GistBackend` port (one production adapter — the
// `perk gist create` cold door in pi/v1 — plus one deterministic fake in the tests: the port
// admission rule), the `saveGist` operation, and the shared APPROVED-review → save orchestration
// `gistApprovalSave` (the exported name contracts.md §8.41 pins).
//
// Unlike the plan/objective siblings there is NO session linkage after the save — nothing
// consumes a gist in-session (adoption happens later via the cold doors), so a successful save
// just carries the backend's id/url/scope facts for the caller to relay.

import type { WorkflowSession } from "../../session/workflowSession.ts";
import { GIST_SCOPES, type GistScope, resumeGistDraft } from "./draft.ts";

/** The backend save facts (`id` is the opaque string gist id — contracts §8.21). */
export type GistBackendSaveResult =
  | { status: "saved"; id: string; url: string; existed: boolean | null; scope: string | null }
  | { status: "failed"; message: string; errorType: string };

/**
 * The narrow exterior port the save operation writes through. `runId: null` means the caller has
 * no session identity — the backend omits its run linkage (an identity-less save keeps working).
 */
export interface GistBackend {
  save(req: {
    prose: string;
    title?: string;
    scope?: GistScope;
    runId: string | null;
  }): Promise<GistBackendSaveResult>;
}

/**
 * The save outcome: the backend facts, or a typed refusal/failure (message bytes caller-facing).
 * Deliberately the SAME union as the backend result — `saveGist` adds the local validation
 * refusals on the shared `failed` variant and otherwise returns the backend value unchanged, so
 * a second hand-mirrored vocabulary would only invite drift. Alias, not copy.
 */
export type SaveGistOutcome = GistBackendSaveResult;

/**
 * The single save operation both surfaces call: validate the prose/scope (the exact refusals the
 * save always had), then write through the backend port. The backend owns scope resolution
 * beyond the explicit value (launch-handoff seed, default). Never throws.
 */
export async function saveGist(
  input: { prose: string; title?: string; scope?: GistScope },
  deps: { backend: GistBackend; runId: string | null },
): Promise<SaveGistOutcome> {
  const prose = input.prose.trim();
  if (!prose) {
    return {
      status: "failed",
      message: "no gist prose to save (draft the gist first)",
      errorType: "invalid_input",
    };
  }
  if (input.scope !== undefined && !(GIST_SCOPES as readonly string[]).includes(input.scope)) {
    return {
      status: "failed",
      message: "scope must be plan or objective",
      errorType: "invalid_input",
    };
  }
  return deps.backend.save({
    prose,
    ...(input.title !== undefined ? { title: input.title } : {}),
    ...(input.scope !== undefined ? { scope: input.scope } : {}),
    runId: deps.runId,
  });
}

/** The structural gate slice the approval→save flow releases (the adapter builds it over ToolGating). */
export interface GistGate {
  isActive(): boolean;
  exit(): void;
}

/** The approval→save orchestration outcome (the gist `ApprovalSaveOutcome`). `refused-draft`
 * is the fail-closed stop for an invalid artifact: nothing saved, the gate never touched —
 * distinct from `no-draft` (the genuine draft-less fallback arm). */
export type GistApprovalSaveOutcome =
  | { status: "no-draft" }
  | { status: "refused-draft"; problem: string }
  | { status: "saved"; save: Extract<SaveGistOutcome, { status: "saved" }>; gateExited: boolean }
  | {
      status: "save-failed";
      save: Extract<SaveGistOutcome, { status: "failed" }>;
      gateExited: false;
    };

/**
 * The shared APPROVED-review → save orchestration (an APPROVED `plan_review` gist arm and the
 * manual `/gist-save` failsafe both run THIS). Flow: re-read the draft artifact at save time
 * (`resumeGistDraft` — never the rendered markdown, never in-hand bytes) → `saveGist` → gate
 * exit on a verified successful save while read-only (the D1a pattern: snapshot
 * `gate.isActive()` BEFORE the save; a failed save leaves the gate ON). No draft → `no-draft`
 * (nothing saved, the gate untouched); a REFUSED draft → `refused-draft` before the gate
 * snapshot (fail-closed stop — `gateExited` semantics never arise). Title precedence:
 * the explicit override (`/gist-save [title]` — a pinned behavior) wins over the draft's; scope
 * is always the draft's.
 */
export async function gistApprovalSave(
  deps: { session: WorkflowSession; backend: GistBackend; gate: GistGate },
  opts: { title?: string } = {},
): Promise<GistApprovalSaveOutcome> {
  const resumed = resumeGistDraft(deps.session);
  if (resumed.kind === "absent") return { status: "no-draft" };
  if (resumed.kind === "refused") return { status: "refused-draft", problem: resumed.problem };
  const draft = resumed.draft;
  // D1a: snapshot the gate BEFORE the save; on success, exit it so save marks the read-only →
  // read-write boundary in one gesture. A failed save leaves the gate on.
  const wasReadOnly = deps.gate.isActive();
  const save = await saveGist(
    {
      prose: draft.prose,
      ...(opts.title !== undefined || draft.title !== undefined
        ? { title: opts.title ?? draft.title }
        : {}),
      ...(draft.scope !== undefined ? { scope: draft.scope } : {}),
    },
    { backend: deps.backend, runId: deps.session.runId },
  );
  if (save.status !== "saved") return { status: "save-failed", save, gateExited: false };
  let gateExited = false;
  if (wasReadOnly) {
    deps.gate.exit();
    gateExited = true;
  }
  return { status: "saved", save, gateExited };
}
