// The objective-refinement grounding CONTEXT: the fixed transfer artifact Python prepares
// (`perk objective refine` / `perk objective refine-context`) and the interior imports, reads
// and binds drafts to (contracts.md §8.67).
//
// Byte ownership: Python is the SOLE serializer of this artifact. The interior validates the
// raw string's digest and decodes it STRICTLY for use, but every write is the UNCHANGED raw
// string — never `JSON.stringify(parsed)`, never a trim or newline normalization. Readers hand
// back the validated fields together with the raw bytes and their digest so no consumer ever
// serializes the context a second time; the draft's `context_digest` is exactly that digest.
//
// Provenance is a capture-time observation, not a code-freshness gate: the interior renders it
// as such and never refreshes it.

import type {
  ReadArtifactResult,
  SessionArtifactReceipt,
  WorkflowSession,
} from "../../session/workflowSession.ts";
import { digestSessionData, REFINEMENT_CONTEXT_ARTIFACT } from "../../session/workflowSession.ts";

/** The registry stage id of the refinement session (the isolated, read-only stage). */
export const REFINE_STAGE = "objective-refine";

/** The fixed context artifact name — the SAME name in run scratch (cold) and session data. */
export { REFINEMENT_CONTEXT_ARTIFACT };

/** The handoff namespace the cold door carries (never a top-level objective_id/node_id). */
export const REFINEMENT_HANDOFF_KEY = "objective_refinement";

export interface RefinementCodeBasis {
  head_sha: string;
  dirty: boolean;
  captured_at: string;
}

export interface RefinementProvenance {
  authoring_run_id: string;
  authored_at: string;
  code_basis: RefinementCodeBasis;
}

export interface RefinementIdentity {
  backend: string;
  objective_id: string;
  objective_run_id: string;
  node_id: string;
  carrier_id: string;
}

export interface RefinementSource {
  description: string;
  slug: string | null;
  comment: string | null;
  depends_on: string[] | null;
  effective_depends_on: string[];
  issue_description: string;
}

export interface RefinementTarget {
  identity: RefinementIdentity;
  source: RefinementSource;
  source_digest: string;
  carrier_identifier: string;
  carrier_url: string;
  status: string;
  plan_ref: string | null;
  has_plan_metadata: boolean;
}

export interface RefinementPrior {
  markdown: string;
  source_digest: string;
  provenance: RefinementProvenance;
  saved_at: string;
}

/** The validated context fields (the TS mirror of Python's `RefinementContext`). */
export interface RefinementContext {
  schema_version: 1;
  run_id: string;
  target: RefinementTarget;
  expected: { comment_id: string | null; body_digest: string | null };
  provenance: RefinementProvenance;
  objective: { id: string; title: string; url: string };
  prior: RefinementPrior | null;
  engagement: string;
  warnings: string[];
}

/** The validated fields TOGETHER with the exact bytes they came from. */
export interface RefinementContextRead {
  context: RefinementContext;
  raw: string;
  digest: string;
}

export type DecodeRefinementContextResult =
  | { ok: true; context: RefinementContext }
  | { ok: false; problem: string };

// ------------------------------------------------------------------------- strict decoding

class Refuse extends Error {}

function refuse(path: string, why: string): never {
  throw new Refuse(`${path} ${why}`);
}

function obj(value: unknown, path: string, keys: readonly string[]): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    refuse(path, "is not an object");
  const record = value as Record<string, unknown>;
  const present = Object.keys(record);
  for (const key of keys) if (!(key in record)) refuse(`${path}.${key}`, "is missing");
  for (const key of present) if (!keys.includes(key)) refuse(`${path}.${key}`, "is unknown");
  return record;
}

function str(value: unknown, path: string): string {
  if (typeof value !== "string") refuse(path, "is not a string");
  return value;
}

function nonblank(value: unknown, path: string): string {
  const s = str(value, path);
  if (!s.trim()) refuse(path, "is blank");
  return s;
}

function nullableStr(value: unknown, path: string): string | null {
  return value === null ? null : str(value, path);
}

function bool(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") refuse(path, "is not a boolean");
  return value;
}

function strList(value: unknown, path: string): string[] {
  if (!Array.isArray(value)) refuse(path, "is not a list");
  return value.map((item, i) => str(item, `${path}[${i}]`));
}

const HEX40 = /^[0-9a-f]{40}$/;
const HEX64 = /^[0-9a-f]{64}$/;
const SAFE_ARTIFACT_DIGEST = /^sha256:[0-9a-f]{64}$/;

function bareDigest(value: unknown, path: string): string {
  const s = str(value, path);
  if (!HEX64.test(s)) refuse(path, "is not a 64-char lowercase hex digest");
  return s;
}

function provenanceOf(value: unknown, path: string): RefinementProvenance {
  const p = obj(value, path, ["authoring_run_id", "authored_at", "code_basis"]);
  const cb = obj(p.code_basis, `${path}.code_basis`, ["head_sha", "dirty", "captured_at"]);
  const head = str(cb.head_sha, `${path}.code_basis.head_sha`);
  if (!HEX40.test(head)) refuse(`${path}.code_basis.head_sha`, "is not a 40-char lowercase sha");
  return {
    authoring_run_id: nonblank(p.authoring_run_id, `${path}.authoring_run_id`),
    authored_at: nonblank(p.authored_at, `${path}.authored_at`),
    code_basis: {
      head_sha: head,
      dirty: bool(cb.dirty, `${path}.code_basis.dirty`),
      captured_at: nonblank(cb.captured_at, `${path}.code_basis.captured_at`),
    },
  };
}

/**
 * Strictly decode transferred context bytes for USE (validation only — the artifact bytes are
 * never rebuilt from this value). Every defect — malformed JSON, a non-object, unknown or
 * missing keys at any level, mistyped scalars, an unknown `schema_version`, blank identity
 * fields, a non-canonical digest, an inconsistent expectation — is a classified refusal
 * carrying the exact problem. Never throws.
 */
export function decodeRefinementContext(raw: string): DecodeRefinementContextResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { ok: false, problem: `${REFINEMENT_CONTEXT_ARTIFACT} is not valid JSON` };
  }
  try {
    const c = obj(parsed, "context", [
      "schema_version",
      "run_id",
      "target",
      "expected",
      "provenance",
      "objective",
      "prior",
      "engagement",
      "warnings",
    ]);
    if (c.schema_version !== 1) refuse("context.schema_version", "is not 1");
    const t = obj(c.target, "context.target", [
      "identity",
      "source",
      "source_digest",
      "carrier_identifier",
      "carrier_url",
      "status",
      "plan_ref",
      "has_plan_metadata",
    ]);
    const id = obj(t.identity, "context.target.identity", [
      "backend",
      "objective_id",
      "objective_run_id",
      "node_id",
      "carrier_id",
    ]);
    const s = obj(t.source, "context.target.source", [
      "description",
      "slug",
      "comment",
      "depends_on",
      "effective_depends_on",
      "issue_description",
    ]);
    const expected = obj(c.expected, "context.expected", ["comment_id", "body_digest"]);
    const commentId = nullableStr(expected.comment_id, "context.expected.comment_id");
    const bodyDigest = nullableStr(expected.body_digest, "context.expected.body_digest");
    if ((commentId === null) !== (bodyDigest === null))
      refuse("context.expected", "must carry both comment_id and body_digest, or neither");
    if (commentId !== null && !commentId.trim()) refuse("context.expected.comment_id", "is blank");
    if (bodyDigest !== null && !HEX64.test(bodyDigest))
      refuse("context.expected.body_digest", "is not a 64-char lowercase hex digest");
    const o = obj(c.objective, "context.objective", ["id", "title", "url"]);
    let prior: RefinementPrior | null = null;
    if (c.prior !== null) {
      const p = obj(c.prior, "context.prior", [
        "markdown",
        "source_digest",
        "provenance",
        "saved_at",
      ]);
      prior = {
        markdown: nonblank(p.markdown, "context.prior.markdown"),
        source_digest: bareDigest(p.source_digest, "context.prior.source_digest"),
        provenance: provenanceOf(p.provenance, "context.prior.provenance"),
        saved_at: str(p.saved_at, "context.prior.saved_at"),
      };
    }
    const context: RefinementContext = {
      schema_version: 1,
      run_id: nonblank(c.run_id, "context.run_id"),
      target: {
        identity: {
          backend: nonblank(id.backend, "context.target.identity.backend"),
          objective_id: nonblank(id.objective_id, "context.target.identity.objective_id"),
          objective_run_id: nonblank(
            id.objective_run_id,
            "context.target.identity.objective_run_id",
          ),
          node_id: nonblank(id.node_id, "context.target.identity.node_id"),
          carrier_id: nonblank(id.carrier_id, "context.target.identity.carrier_id"),
        },
        source: {
          description: str(s.description, "context.target.source.description"),
          slug: nullableStr(s.slug, "context.target.source.slug"),
          comment: nullableStr(s.comment, "context.target.source.comment"),
          depends_on:
            s.depends_on === null
              ? null
              : strList(s.depends_on, "context.target.source.depends_on"),
          effective_depends_on: strList(
            s.effective_depends_on,
            "context.target.source.effective_depends_on",
          ),
          issue_description: str(s.issue_description, "context.target.source.issue_description"),
        },
        source_digest: bareDigest(t.source_digest, "context.target.source_digest"),
        carrier_identifier: nonblank(t.carrier_identifier, "context.target.carrier_identifier"),
        carrier_url: str(t.carrier_url, "context.target.carrier_url"),
        status: nonblank(t.status, "context.target.status"),
        plan_ref: nullableStr(t.plan_ref, "context.target.plan_ref"),
        has_plan_metadata: bool(t.has_plan_metadata, "context.target.has_plan_metadata"),
      },
      expected: { comment_id: commentId, body_digest: bodyDigest },
      provenance: provenanceOf(c.provenance, "context.provenance"),
      objective: {
        id: nonblank(o.id, "context.objective.id"),
        title: str(o.title, "context.objective.title"),
        url: str(o.url, "context.objective.url"),
      },
      prior,
      engagement: str(c.engagement, "context.engagement"),
      warnings: strList(c.warnings, "context.warnings"),
    };
    return { ok: true, context };
  } catch (error) {
    if (error instanceof Refuse)
      return { ok: false, problem: `${REFINEMENT_CONTEXT_ARTIFACT} ${error.message}` };
    return { ok: false, problem: `${REFINEMENT_CONTEXT_ARTIFACT} could not be decoded` };
  }
}

/** Whether a string is the `sha256:<64 lowercase hex>` session-data digest shape. */
export function isArtifactDigest(value: string): boolean {
  return SAFE_ARTIFACT_DIGEST.test(value);
}

// --------------------------------------------------------------------------- the transfer

export type ValidateContextTransferResult =
  | { ok: true; read: RefinementContextRead }
  | { ok: false; problem: string };

/**
 * Validate a raw transferred context string against its declared digest and the session's run:
 * the digest is computed over the EXACT string (final LF included), the shape is decoded
 * strictly, and `run_id` must be the current run. Parsing is validation only — the returned
 * `raw` is the caller's unchanged string. Never throws.
 */
export function validateContextTransfer(
  raw: string,
  opts: { runId: string; expectedDigest?: string },
): ValidateContextTransferResult {
  const digest = digestSessionData(raw);
  if (opts.expectedDigest !== undefined) {
    if (!isArtifactDigest(opts.expectedDigest))
      return { ok: false, problem: "the declared context digest is not a sha256: digest" };
    if (opts.expectedDigest !== digest)
      return { ok: false, problem: "the transferred context bytes do not match their digest" };
  }
  const decoded = decodeRefinementContext(raw);
  if (!decoded.ok) return decoded;
  if (decoded.context.run_id !== opts.runId)
    return {
      ok: false,
      problem: `the transferred context belongs to run ${JSON.stringify(decoded.context.run_id)}, not this run`,
    };
  return { ok: true, read: { context: decoded.context, raw, digest } };
}

export type ImportRefinementContextResult =
  | { status: "imported"; receipt: SessionArtifactReceipt; read: RefinementContextRead }
  | { status: "unchanged"; receipt: SessionArtifactReceipt; read: RefinementContextRead }
  | { status: "rejected"; problem: string }
  | { status: "unverified"; problem: string };

/**
 * Persist a validated transfer as the session's context artifact — the UNCHANGED raw string
 * through the session write. `unchanged` is the byte-identical short-circuit (a
 * re-prepared context whose bytes happen to be identical is no new context). Never throws.
 */
export function importRefinementContext(
  session: WorkflowSession,
  read: RefinementContextRead,
): ImportRefinementContextResult {
  const written = session.writeArtifact(REFINEMENT_CONTEXT_ARTIFACT, read.raw);
  switch (written.status) {
    case "applied":
      return { status: "imported", receipt: written.receipt, read };
    case "unchanged":
      return { status: "unchanged", receipt: written.receipt, read };
    case "rejected":
      return { status: "rejected", problem: written.problem };
    case "unverified":
      return { status: "unverified", problem: written.problem };
  }
}

export type ColdImportResult =
  | { status: "imported" | "unchanged"; read: RefinementContextRead }
  | { status: "not-applicable" }
  | { status: "refused"; problem: string };

/** The transfer read port the edge binds to the run's fixed scratch path (`null` = missing). */
export interface ColdImportPorts {
  readTransfer(): string | null;
}

/**
 * The cold claim's ONE-TIME context import (contracts.md §8.67): on the actual `objective-refine`
 * cold claim, read the fixed run-scratch transfer the door materialized (through the edge-bound
 * port), validate its declared digest (from the namespaced handoff block), run, stage and strict
 * shape, and write the exact raw string as the session artifact. `not-applicable` for every
 * non-refinement claim; every defect is a fail-closed `refused` (the session stays read-only and
 * unusable for drafting — never an orphan repair, missing-pointer reimport or target refresh).
 * Never throws.
 */
export function importColdRefinementContext(
  session: WorkflowSession,
  claim: { runId: string; stage: string | undefined; handoff: Record<string, unknown> },
  ports: ColdImportPorts,
): ColdImportResult {
  if (claim.stage !== REFINE_STAGE) return { status: "not-applicable" };
  const refuse = (problem: string): ColdImportResult => ({ status: "refused", problem });
  const identity = session.currentRunIdentity();
  if (!identity.ok) return refuse(`session identity ${identity.reason}`);
  if (identity.runId !== claim.runId) return refuse("the claimed run is not the session's run");
  const block = claim.handoff[REFINEMENT_HANDOFF_KEY];
  if (typeof block !== "object" || block === null || Array.isArray(block))
    return refuse(`the handoff carries no ${REFINEMENT_HANDOFF_KEY} block`);
  const declared = (block as Record<string, unknown>).context_digest;
  if (typeof declared !== "string" || !isArtifactDigest(declared))
    return refuse("the handoff's context_digest is not a sha256: digest");
  let raw: string | null;
  try {
    raw = ports.readTransfer();
  } catch (error) {
    return refuse(`could not read the context transfer (${String(error)})`);
  }
  if (raw === null) return refuse("the context transfer is missing from the run's scratch");
  const validated = validateContextTransfer(raw, { runId: claim.runId, expectedDigest: declared });
  if (!validated.ok) return refuse(validated.problem);
  const imported = importRefinementContext(session, validated.read);
  switch (imported.status) {
    case "imported":
    case "unchanged":
      return { status: imported.status, read: imported.read };
    case "rejected":
    case "unverified":
      return refuse(`could not persist the context artifact (${imported.problem})`);
  }
}

/** The classified context resume: `absent` is the genuine no-context arm; `refused` is a
 * fail-closed STOP (a corrupt/orphan/foreign artifact never falls back to anything). */
export type ResumeRefinementContextResult =
  | { kind: "valid"; read: RefinementContextRead }
  | { kind: "absent" }
  | { kind: "refused"; problem: string };

/**
 * Strictly resume the session's context artifact: the session read (a foreign-run pointer reads
 * `absent` — fork isolation; a missing/digest-mismatched file is `invalid`), the strict decode,
 * and the run check against the session identity (a wrong-run transfer refuses `not this run`).
 * Returns the raw bytes + digest beside the fields. Never throws.
 */
export function resumeRefinementContext(session: WorkflowSession): ResumeRefinementContextResult {
  const identity = session.currentRunIdentity();
  if (!identity.ok) return { kind: "refused", problem: `session identity ${identity.reason}` };
  const read: ReadArtifactResult = session.readArtifact(REFINEMENT_CONTEXT_ARTIFACT);
  if (read.status === "absent") return { kind: "absent" };
  if (read.status === "invalid") return { kind: "refused", problem: read.problem };
  const validated = validateContextTransfer(read.content, { runId: identity.runId });
  if (!validated.ok) return { kind: "refused", problem: validated.problem };
  return { kind: "valid", read: validated.read };
}

/** The one-line target summary every refinement surface relays (never the full context). */
export function describeRefinementTarget(context: RefinementContext): string {
  const t = context.target;
  return (
    `objective ${context.objective.id} node ${t.identity.node_id} (${t.status}; ` +
    `${t.carrier_identifier}${context.prior !== null ? "; re-refining a prior refinement" : ""})`
  );
}

/**
 * The capture-time observation line — the ONLY way the interior labels code provenance
 * (contracts.md §8.67): a dated observation, never "verified", "frozen" or "current" code.
 */
export function checkoutObservationLine(provenance: RefinementProvenance): string {
  const cb = provenance.code_basis;
  return (
    `Checkout observation captured at ${cb.captured_at}: HEAD ${cb.head_sha}, dirty ${cb.dirty}; ` +
    "uncommitted files were not snapshotted and later checkout changes are not detected. " +
    "This is not a freshness guarantee."
  );
}
