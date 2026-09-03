// The objective working-draft feature: the fixed artifact constant and the draft operations
// over the WorkflowSession seam — the objective-flavored sibling of `authoring/plan/draft.ts`,
// JSON-envelope flavored (deliberately unshared shapes: a generic envelope would share syntax
// while erasing each flow's recovery semantics).
//
// Carve-out doctrine: the ops take NO path/name parameter — the artifact name is the fixed
// constant `OBJECTIVE_DRAFT_ARTIFACT` and every byte flows through the session seam (file +
// verified `session_artifacts` pointer), so the only thing they can ever touch is the one
// working-objective artifact in the current run's data dir (gitignored scratch). Full rewrite
// per call, never a save — `objective_save`/`/objective-save` still persist to GitHub.
//
// Format doctrine: JSON is the storage/transport format, NEVER the human review surface. The
// artifact carries `{schema_version, title?, prose, roadmap}` (plus, in a perk learn dream
// session, the gate-written `dream_report` block — contracts §8.63) — the structured roadmap
// rides verbatim (node-shape validation stays with the Python plane at save time, the
// `parse_structured_roadmap` path). The review surface reads the draft via
// `resumeObjectiveDraft` (digest-validated, classified valid/absent/refused) and renders markdown via
// `renderObjectiveDraft` (the prose + a roadmap table) — never raw JSON; the
// approval→`objective_save` orchestration feeds the recovered roadmap back as structured JSON.
//
// The §8.63 dream gate arrives INJECTED (`resolveDreamGate` — ctx-bound by the adapter) so the
// module stays session-pure; `dreamReportGate.ts` owns the matrix.

import type { SessionArtifactReceipt, WorkflowSession } from "../../session/workflowSession.ts";
import {
  type DreamReportGateOutcome,
  decodeDreamReportBlock,
  type ObjectiveDreamReportBlock,
} from "./dreamReportGate.ts";

/**
 * The reviewed objective delivery vocabulary (contracts §8.45) — the ONE authority every
 * layer derives from: the `DeliveryChoice` union, the tool schema's enum, and the decoder's
 * narrowing all read these values, so a new variant cannot drift between them.
 */
export const DELIVERY_CHOICES = ["incremental", "stacked"] as const;

/** The reviewed objective delivery choice (contracts §8.45). */
export type DeliveryChoice = (typeof DELIVERY_CHOICES)[number];

/** Whether `value` is a member of the §8.45 delivery vocabulary (the decoder's narrowing). */
export function isDeliveryChoice(value: string): value is DeliveryChoice {
  return (DELIVERY_CHOICES as readonly string[]).includes(value);
}

/** The fixed working-objective artifact name (one JSON file: prose + the structured roadmap). */
export const OBJECTIVE_DRAFT_ARTIFACT = "objective-draft.json";

/** The typed revise input — decode owns the shape at the tool boundary (pi/v1). */
export interface ObjectiveDraftInput {
  prose: string;
  title?: string;
  roadmap?: unknown[];
  /** The objective's target branch; omitted to use the repo default. */
  base?: string;
  /** The reviewed delivery choice; omitted ⇒ incremental (the §8.42 absence rule). */
  delivery?: DeliveryChoice;
  /** The dream-report input (perk learn dream only — §8.63); deep validation is the gate's. */
  dream_report?: unknown;
}

/**
 * The revise outcome (the `RevisePlanDraftResult` mirror, plus the §8.63 gate arm). `rejected`
 * splits by `reason` AND carries the exact `errorType` the adapter reports (`gate_refused` is
 * the dynamic arm — the resolver's own `invalid_input`/`bad_state`); `unverified` means an
 * effect may have landed but the read-back proof failed. `problem` carries the caller-facing
 * message bytes. `roadmapNodes` rides so the adapter's rendered twin ("… N roadmap nodes")
 * needs no re-parse.
 */
export type ReviseObjectiveDraftResult =
  | { status: "revised"; receipt: SessionArtifactReceipt; bytes: number; roadmapNodes: number }
  | { status: "unchanged"; receipt: SessionArtifactReceipt; bytes: number; roadmapNodes: number }
  | {
      status: "rejected";
      reason: "blank_prose" | "no_identity" | "gate_refused" | "write_refused";
      problem: string;
      errorType: "invalid_input" | "no_run_id" | "bad_state" | "write_failed";
    }
  | { status: "unverified"; problem: string };

/**
 * Rewrite the working objective draft (a whole-value replacement) through the session seam:
 * serialize the explicit-literal payload (deterministic key order; `title`/`base`/`delivery`
 * omitted when blank/absent; `schema_version` stays 1 — an additive optional field, fail-open
 * readers), gate `dream_report` at write time (§8.63 — validated here so a report-less dream
 * bundle can never reach review), then write. Diagnostic precedence preserved: blank prose →
 * identity → the dream gate → the write. A byte-identical rewrite short-circuits `unchanged`
 * (the session engine owns the probe). Never throws.
 */
export function reviseObjectiveDraft(
  input: ObjectiveDraftInput,
  deps: {
    session: WorkflowSession;
    /** The §8.63 gate, adapter-bound (`resolveDreamReportGate` over the production recovery capability). */
    resolveDreamGate: (input: unknown, generatedAt: string) => DreamReportGateOutcome;
  },
): ReviseObjectiveDraftResult {
  if (!input.prose.trim()) {
    return {
      status: "rejected",
      reason: "blank_prose",
      problem: "no objective prose to write (pass the full working draft)",
      errorType: "invalid_input",
    };
  }
  if (deps.session.runId === null) {
    return {
      status: "rejected",
      reason: "no_identity",
      problem: "session has no run_id — cannot write the objective-draft artifact",
      errorType: "no_run_id",
    };
  }

  // The §8.63 gate: validated at draft-write time via buildDreamReport, the ONE stamp stored
  // with the block; `absent` keeps the payload byte-identical (every non-dream path unchanged).
  const gate = deps.resolveDreamGate(input.dream_report, new Date().toISOString());
  if (gate.kind === "refuse") {
    return {
      status: "rejected",
      reason: "gate_refused",
      problem: gate.detail,
      errorType: gate.errorType,
    };
  }

  const title = input.title?.trim();
  const base = input.base?.trim();
  const delivery = input.delivery;
  const roadmap = input.roadmap ?? [];
  const payload = {
    schema_version: 1,
    ...(title ? { title } : {}),
    ...(base ? { base } : {}),
    ...(delivery ? { delivery } : {}),
    ...(gate.kind === "block" ? { dream_report: gate.block } : {}),
    prose: input.prose,
    roadmap,
  };
  const content = `${JSON.stringify(payload, null, 2)}\n`;
  const bytes = Buffer.byteLength(content, "utf8");

  const written = deps.session.writeArtifact(OBJECTIVE_DRAFT_ARTIFACT, content);
  switch (written.status) {
    case "applied":
      return { status: "revised", receipt: written.receipt, bytes, roadmapNodes: roadmap.length };
    case "unchanged":
      return {
        status: "unchanged",
        receipt: written.receipt,
        bytes,
        roadmapNodes: roadmap.length,
      };
    case "rejected":
      return {
        status: "rejected",
        reason: "write_refused",
        problem: `could not write the ${OBJECTIVE_DRAFT_ARTIFACT} artifact (see warnings)`,
        errorType: "write_failed",
      };
    case "unverified":
      return {
        status: "unverified",
        problem: `could not write the ${OBJECTIVE_DRAFT_ARTIFACT} artifact (see warnings)`,
      };
  }
}

// ------------------------------------------------------------------- the reader + the renderer

/** The validated working-objective draft shape consumers receive from `resumeObjectiveDraft`. */
export interface ObjectiveDraft {
  title?: string;
  prose: string;
  roadmap: unknown[];
  /** The objective's target branch; kept only when a non-blank string in the artifact. */
  base?: string;
  /** The reviewed delivery choice; kept only when exactly the enum (junk → absent, like `base`). */
  delivery?: DeliveryChoice;
  /** The dream-report block (§8.63); a present-but-malformed block refuses the WHOLE draft. */
  dream_report?: ObjectiveDreamReportBlock;
}

/** The classified resume outcome: a refused draft is a fail-closed STOP at every consumer —
 * it never takes the no-draft fallbacks' side effects (gate exit, driven turn). */
export type ResumeObjectiveDraftResult =
  | { kind: "valid"; draft: ObjectiveDraft }
  | { kind: "absent" }
  | { kind: "refused"; problem: string };

/**
 * Resume + validate the working-objective draft artifact from the session, classified: seam
 * `absent` → `absent` (the genuine no-draft arm); seam `invalid` → `refused` carrying the
 * seam's problem (a corrupted artifact is truthfully rendered at the edge — the seam's own
 * stderr tier is untouched); decoder refusals (`decodeObjectiveDraft`) pass through. Never
 * throws.
 */
export function resumeObjectiveDraft(session: WorkflowSession): ResumeObjectiveDraftResult {
  const read = session.readArtifact(OBJECTIVE_DRAFT_ARTIFACT);
  if (read.status === "absent") return { kind: "absent" };
  if (read.status === "invalid") return { kind: "refused", problem: read.problem };
  return decodeObjectiveDraft(read.content);
}

/**
 * Decode + validate working-objective artifact bytes (the content half of
 * `resumeObjectiveDraft`, for consumers that already hold the seam-validated bytes — e.g. the
 * browser door, whose stale-guard baseline and decode input must be the SAME read): malformed
 * JSON, a non-object payload, an unsupported `schema_version`, or blank prose → `refused`
 * with the decoder's problem. `roadmap` defaults to `[]` when absent/non-array; `title` is
 * kept only when a non-blank string. A present-but-malformed `dream_report` block refuses the
 * WHOLE draft — deliberately stricter than the lenient junk→absent handling of
 * `base`/`delivery`, because silently dropping a malformed report is exactly what §8.63
 * forbids. Never throws.
 */
export function decodeObjectiveDraft(
  content: string,
): Exclude<ResumeObjectiveDraftResult, { kind: "absent" }> {
  const refuse = (why: string): { kind: "refused"; problem: string } => ({
    kind: "refused",
    problem: `${OBJECTIVE_DRAFT_ARTIFACT} ${why} — refusing the draft`,
  });
  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
  } catch {
    return refuse("is not valid JSON");
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return refuse("is not a JSON object");
  }
  const payload = parsed as Record<string, unknown>;
  if (payload.schema_version !== 1) {
    return refuse(`has an unsupported schema_version (${JSON.stringify(payload.schema_version)})`);
  }
  const prose = payload.prose;
  if (typeof prose !== "string" || !prose.trim()) {
    return refuse("has no prose");
  }
  const roadmap = Array.isArray(payload.roadmap) ? payload.roadmap : [];
  const title =
    typeof payload.title === "string" && payload.title.trim() ? payload.title : undefined;
  const base = typeof payload.base === "string" && payload.base.trim() ? payload.base : undefined;
  const delivery =
    typeof payload.delivery === "string" && isDeliveryChoice(payload.delivery)
      ? payload.delivery
      : undefined;
  let dreamReport: ObjectiveDreamReportBlock | undefined;
  if ("dream_report" in payload) {
    const block = decodeDreamReportBlock(payload.dream_report);
    if (block === null) {
      return refuse("carries a malformed dream_report block");
    }
    dreamReport = block;
  }
  return {
    kind: "valid",
    draft: {
      ...(title !== undefined ? { title } : {}),
      ...(base !== undefined ? { base } : {}),
      ...(delivery !== undefined ? { delivery } : {}),
      ...(dreamReport !== undefined ? { dream_report: dreamReport } : {}),
      prose,
      roadmap,
    },
  };
}

/** Sanitize a table cell: `|` escaped, newlines collapsed to a single space. */
function tableCell(value: string): string {
  return value.replace(/\r?\n/g, " ").replace(/\|/g, "\\|");
}

/** Read a string field off an unknown-shaped roadmap node (`""` when absent/mistyped). */
function nodeString(node: unknown, key: string): string {
  if (typeof node !== "object" || node === null) return "";
  const value = (node as Record<string, unknown>)[key];
  return typeof value === "string" ? value : "";
}

/** Render a node's `depends_on` as a `", "`-join of its string members; `-` when empty/absent. */
function nodeDependsOn(node: unknown): string {
  if (typeof node !== "object" || node === null) return "-";
  const value = (node as Record<string, unknown>).depends_on;
  if (!Array.isArray(value)) return "-";
  const deps = value.filter((d): d is string => typeof d === "string");
  return deps.length > 0 ? deps.join(", ") : "-";
}

/** The always-present prominent `**Delivery:**` review line (contracts §8.45). */
function deliveryLine(draft: ObjectiveDraft): string {
  if (draft.delivery === "stacked") {
    return (
      "**Delivery: STACKED** — all non-skipped roadmap nodes land as ONE atomic pull-request " +
      "train (capability-checked at save)"
    );
  }
  return "**Delivery: incremental** (the default — each plan lands independently)";
}

/**
 * Render the draft as the markdown review surface (JSON is storage/transport only — contracts
 * §8.1): the optional `# title` heading, the prose verbatim, and (when the roadmap is non-empty)
 * a `## Roadmap` section with ONE markdown table. A prominent `**Delivery:**` line renders
 * directly under the title unconditionally (the reviewed choice must be visible either way —
 * contracts §8.45). The `Phase` column appears only when some node carries a non-blank string
 * `phase`. When the draft carries a `dream_report` block, the stored CANONICAL parts append as
 * the final section — the review surface IS the approval bundle: the objective and its report
 * review (and are approved or denied) together (§8.63); the parts carry their own
 * `# Dream report — <run_id>` headers. Pure; never throws.
 */
export function renderObjectiveDraft(draft: ObjectiveDraft): string {
  let out = "";
  if (draft.title) out += `# ${draft.title}\n\n`;
  out += `${deliveryLine(draft)}\n\n`;
  out += draft.prose;

  if (draft.roadmap.length > 0) {
    const withPhase = draft.roadmap.some((node) => nodeString(node, "phase").trim().length > 0);
    const header = withPhase
      ? "| Node | Phase | Description | Depends On | Status |\n| --- | --- | --- | --- | --- |"
      : "| Node | Description | Depends On | Status |\n| --- | --- | --- | --- |";
    const rows = draft.roadmap.map((node) => {
      const cells = [
        tableCell(nodeString(node, "id")),
        ...(withPhase ? [tableCell(nodeString(node, "phase"))] : []),
        tableCell(nodeString(node, "description")),
        tableCell(nodeDependsOn(node)),
        tableCell(nodeString(node, "status") || "pending"),
      ];
      return `| ${cells.join(" | ")} |`;
    });
    out = `${out.trimEnd()}\n\n## Roadmap\n\n${header}\n${rows.join("\n")}\n`;
  }

  if (draft.dream_report === undefined) return out;
  // The approval bundle: objective first, then the stored CANONICAL report parts.
  return `${out.trimEnd()}\n\n${draft.dream_report.parts.join("\n\n")}\n`;
}
