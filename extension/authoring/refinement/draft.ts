// The objective-refinement working DRAFT: the one model-facing artifact (`objective_refinement_draft`
// writes it), bound to the session's context by run id + exact context digest, and the review
// rendering over the validated (draft, context) pair (contracts.md §8.67).
//
// Byte ownership: TypeScript alone serializes drafts — the explicit property order
// `schema_version`, `run_id`, `context_digest`, `markdown`, compact `JSON.stringify`, one LF.
// The Markdown is the model's ONLY contribution: it cannot supply a title, path, target, digest,
// run id or expectation. Python parses the transferred draft without reserializing or trimming.
//
// A draft is USABLE only when both strict session pointers verify, the run ids match, the
// draft's `context_digest` equals the current context artifact's digest, the context fields
// validate, and the Markdown is nonblank. A context re-prepared after the draft makes the draft
// `mismatch` (evidence that needs rewriting), never a silent rebind.

import type { SessionArtifactReceipt, WorkflowSession } from "../../session/workflowSession.ts";
import {
  checkoutObservationLine,
  isArtifactDigest,
  type RefinementContextRead,
  resumeRefinementContext,
} from "./context.ts";

/** The fixed working-draft artifact name (one small JSON envelope around the Markdown). */
export const REFINEMENT_DRAFT_ARTIFACT = "objective-refinement-draft.json";

export interface RefinementDraft {
  run_id: string;
  context_digest: string;
  markdown: string;
}

/** The validated (draft, context) pair plus the draft's exact bytes — the review + save unit. */
export interface RefinementDraftPair {
  draft: RefinementDraft;
  draftRaw: string;
  context: RefinementContextRead;
}

/**
 * Serialize a draft: the fixed property order, compact `JSON.stringify`, exactly one trailing LF.
 * Pure; never throws.
 */
export function encodeRefinementDraft(draft: {
  runId: string;
  contextDigest: string;
  markdown: string;
}): string {
  return `${JSON.stringify({
    schema_version: 1,
    run_id: draft.runId,
    context_digest: draft.contextDigest,
    markdown: draft.markdown,
  })}\n`;
}

export type DecodeRefinementDraftResult =
  | { ok: true; draft: RefinementDraft }
  | { ok: false; problem: string };

/**
 * Strictly decode draft bytes: a JSON object with exactly the four keys, `schema_version` 1, a
 * nonblank run id, a `sha256:` context digest and nonblank Markdown (tested with trim, NEVER
 * trimmed). Never throws.
 */
export function decodeRefinementDraft(raw: string): DecodeRefinementDraftResult {
  const refuse = (why: string): { ok: false; problem: string } => ({
    ok: false,
    problem: `${REFINEMENT_DRAFT_ARTIFACT} ${why}`,
  });
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return refuse("is not valid JSON");
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))
    return refuse("is not a JSON object");
  const p = parsed as Record<string, unknown>;
  const keys = Object.keys(p).sort();
  const expected = ["context_digest", "markdown", "run_id", "schema_version"];
  if (keys.length !== expected.length || keys.some((k, i) => k !== expected[i]))
    return refuse("does not carry exactly schema_version, run_id, context_digest, markdown");
  if (p.schema_version !== 1) return refuse("has an unsupported schema_version");
  if (typeof p.run_id !== "string" || !p.run_id.trim()) return refuse("has a blank run_id");
  if (typeof p.context_digest !== "string" || !isArtifactDigest(p.context_digest))
    return refuse("has a malformed context_digest");
  if (typeof p.markdown !== "string" || !p.markdown.trim()) return refuse("has blank markdown");
  return {
    ok: true,
    draft: { run_id: p.run_id, context_digest: p.context_digest, markdown: p.markdown },
  };
}

// ------------------------------------------------------------------------------- revise

export type ReviseRefinementDraftResult =
  | {
      status: "revised";
      receipt: SessionArtifactReceipt;
      bytes: number;
      context: RefinementContextRead;
    }
  | {
      status: "unchanged";
      receipt: SessionArtifactReceipt;
      bytes: number;
      context: RefinementContextRead;
    }
  | {
      status: "rejected";
      reason: "blank_markdown" | "no_identity" | "no_context" | "context_refused" | "write_refused";
      problem: string;
    }
  | { status: "unverified"; problem: string };

/**
 * Rewrite the working draft (a whole-value replacement) bound to the CURRENT context: blank
 * Markdown is refused first, then missing identity, then the strict context resume (absent →
 * the session needs a grounding pass; refused → a fail-closed stop), then the verified write of
 * the small fixed envelope. Identical bytes are `unchanged`. Never throws.
 */
export function reviseRefinementDraft(
  input: { markdown: string },
  session: WorkflowSession,
): ReviseRefinementDraftResult {
  if (!input.markdown.trim()) {
    return {
      status: "rejected",
      reason: "blank_markdown",
      problem: "no refinement markdown to write (pass the full working draft)",
    };
  }
  const identity = session.currentRunIdentity();
  if (!identity.ok) {
    return {
      status: "rejected",
      reason: "no_identity",
      problem: `session identity ${identity.reason} — cannot write the refinement draft`,
    };
  }
  const context = resumeRefinementContext(session);
  if (context.kind === "absent") {
    return {
      status: "rejected",
      reason: "no_context",
      problem:
        "no refinement context in this session — enter a grounding pass first (perk objective " +
        "refine <objective> or /objective-refine)",
    };
  }
  if (context.kind === "refused") {
    return {
      status: "rejected",
      reason: "context_refused",
      problem: `the refinement context is invalid: ${context.problem}`,
    };
  }
  const content = encodeRefinementDraft({
    runId: identity.runId,
    contextDigest: context.read.digest,
    markdown: input.markdown,
  });
  const bytes = Buffer.byteLength(content, "utf8");
  const written = session.writeArtifact(REFINEMENT_DRAFT_ARTIFACT, content, {
    provenance: "strict",
  });
  switch (written.status) {
    case "applied":
      return { status: "revised", receipt: written.receipt, bytes, context: context.read };
    case "unchanged":
      return { status: "unchanged", receipt: written.receipt, bytes, context: context.read };
    case "rejected":
      return {
        status: "rejected",
        reason: "write_refused",
        problem: `could not write the ${REFINEMENT_DRAFT_ARTIFACT} artifact (${written.problem})`,
      };
    case "unverified":
      return {
        status: "unverified",
        problem: `could not write the ${REFINEMENT_DRAFT_ARTIFACT} artifact (${written.problem})`,
      };
  }
}

// ------------------------------------------------------------------------------- resume

/** The classified draft resume. `mismatch` is a usable-looking draft bound to a DIFFERENT
 * context (re-prepared after it was written) — evidence that must be rewritten, never routed. */
export type ResumeRefinementDraftResult =
  | { kind: "valid"; pair: RefinementDraftPair }
  | { kind: "absent" }
  | { kind: "no-context" }
  | { kind: "mismatch"; problem: string }
  | { kind: "refused"; problem: string };

/**
 * Resume the (draft, context) pair strictly: identity → strict context → strict draft → the
 * binding check (matching run id AND exact context digest). Corruption, orphan pointers,
 * fork/wrong-run data and a context mismatch never fall back to plans or to any other artifact.
 * Never throws.
 */
export function resumeRefinementDraft(session: WorkflowSession): ResumeRefinementDraftResult {
  const identity = session.currentRunIdentity();
  if (!identity.ok) return { kind: "refused", problem: `session identity ${identity.reason}` };
  const context = resumeRefinementContext(session);
  if (context.kind === "refused") return { kind: "refused", problem: context.problem };
  const read = session.readArtifact(REFINEMENT_DRAFT_ARTIFACT, { provenance: "strict" });
  if (read.status === "invalid") return { kind: "refused", problem: read.problem };
  if (context.kind === "absent")
    return read.status === "absent" ? { kind: "absent" } : { kind: "no-context" };
  if (read.status === "absent") return { kind: "absent" };
  const decoded = decodeRefinementDraft(read.content);
  if (!decoded.ok) return { kind: "refused", problem: decoded.problem };
  const draft = decoded.draft;
  if (draft.run_id !== identity.runId)
    return { kind: "refused", problem: `${REFINEMENT_DRAFT_ARTIFACT} belongs to another run` };
  if (draft.context_digest !== context.read.digest)
    return {
      kind: "mismatch",
      problem:
        "the working draft was written against an earlier refinement context (the context was " +
        "re-prepared since) — rewrite it with objective_refinement_draft against the current context",
    };
  return { kind: "valid", pair: { draft, draftRaw: read.content, context: context.read } };
}

// ------------------------------------------------------------------------------- render

/**
 * Render the validated pair as the review surface: identity + carrier + pass time, a prominent
 * advisory notice, the capture-time observation label (never "verified/frozen/current"), then
 * the FULL Markdown verbatim. Identity/provenance are immutable review metadata — the
 * Markdown below the rule is the only reviewable content. Pure; never throws.
 */
export function renderRefinementDraft(pair: RefinementDraftPair): string {
  const c = pair.context.context;
  const t = c.target;
  const head = [
    `# Refinement — objective ${c.objective.id} · node ${t.identity.node_id}`,
    "",
    `Objective: ${c.objective.title}`,
    `Node ${t.identity.node_id} (${t.status}): ${t.source.description}`,
    `Carrier: ${t.carrier_identifier}${t.carrier_url ? ` — ${t.carrier_url}` : ""}`,
    `Authoring pass started: ${c.provenance.authored_at} (run ${c.provenance.authoring_run_id})`,
    c.prior !== null
      ? `Replaces the prior refinement saved at ${c.prior.saved_at} (full-content replacement).`
      : "First refinement of this node.",
    "",
    "> ADVISORY: this is a dated refinement of a FUTURE node, not an executable plan. Saving it " +
      "writes only the node's marked refinement comment — no plan is created, no node is claimed, " +
      "no status changes. Unresolved future assumptions are legitimate here.",
    ">",
    `> ${checkoutObservationLine(c.provenance)}`,
    "",
    "---",
    "",
  ];
  return head.join("\n") + pair.draft.markdown;
}
