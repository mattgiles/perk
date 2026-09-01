// The §8.56 evidence-gated reconcile decision (the stacked-delivery close half), Pi-free.
//
// After a mutating stack land/recover whose envelope carries journal-assembled reconcile
// evidence (≥1 layer), the session is driven into the reconcile pass. This module owns the
// DECISION + the evidence mint; rendering and injection stay adapter-side
// (`pi/v1/delivery/stackDrive.ts`). The gate is EVIDENCE PRESENCE, never `objective_closed` or
// the invocation's action rows: the Python plane attaches evidence on a real close transition
// AND on recover's already-closed journal-complete re-emission (the death-after-close repair —
// an `objective_closed: false` envelope with evidence must still drive, or the crash window
// would suppress the drive permanently). At-least-once: duplicate cross-machine drives are
// possible and harmless — the reconcile pass is idempotent ("skip if nothing stale").
//
// The warm transition rows this decision serves (the conflict rows live in
// `delivery/stackConflict.ts`):
//
// | Operation | Persisted facts (authority) | Warm gesture → cold effect | Consent | Typed arms | Recovery |
// |---|---|---|---|---|---|
// | RECOVER (§8.51) | Journal fold + fresh product-state proof (Python) | `{dry_run}` classify-only; `{}` concludes all-after; `{abandon,confirm}`/`{accept_prefix,confirm}` | confirm for conclusions | classification rows / landed layers / sweep report / evidence (may drive) | recover IS the recovery surface; at-least-once evidence re-emission (reconcile idempotent) |
// | STACK LAND (§8.55/§8.56) | Readiness composed from the train (Python); LAND journal op | `{dry_run}` preview; `{confirm}` → `land --yes` | `confirm: true` + dry-run-first | merged (+close+evidence→drive) / pending / unexpected_enqueued (UNRESOLVED — report and STOP) / completed_without_merge closed/NOT-closed / declined | `/objective-recover` concludes against fresh authority |

import {
  booleanField,
  type ColdJson,
  numberField,
  objectField,
  objectListField,
  stringField,
} from "../substrate/coldDoor.ts";

/** The identifier vocabulary for evidence interpolation (objective/node/plan ids) —
 * whitelist validation doubles as control-character/line-break exclusion, so a poisoned
 * journal string can never break out of its evidence row. */
const EVIDENCE_ID_RE = /^[A-Za-z0-9._-]{1,64}$/;
const EVIDENCE_SHA_RE = /^[0-9a-fA-F]{4,64}$/;
/** The printable-https vocabulary the minted URL must reconstruct into. */
const PRINTABLE_HTTPS_RE = /^https:\/\/[\x21-\x7e]+$/;

/** One sanitized evidence row — every field is a validated primitive (failures render `"?"`). */
export interface StackReconcileEvidenceRow {
  node: string;
  plan: string;
  /** The PR rendered for the row: a positive safe integer's decimal form, else `"?"`. */
  pr: string;
  baseSha: string;
  headSha: string;
  mergeSha: string;
}

/**
 * The validated drive evidence — NOMINAL and mint-only (the ReadyDriveEvidence precedent): the
 * `#private` field makes structural forgery impossible, the constructor is unreachable outside
 * this module, and `decideStackReconcile` mints it ONLY after per-field sanitization. Every
 * field is a validated primitive SNAPSHOTTED (frozen) at mint time — the evidence never aliases
 * the caller-reachable payload, so post-decision payload mutation cannot reach the drive
 * render. The drive template interpolates exclusively from this type.
 */
class StackReconcileEvidence {
  // The ONE `#private` field supplies the nominal guarantee; the getter below reads it.
  readonly #objective: string;
  /** The validated https URL (`""` when the payload's url failed validation). */
  readonly url: string;
  readonly rows: readonly Readonly<StackReconcileEvidenceRow>[];
  readonly finalBaseSha: string;

  constructor(
    objective: string,
    url: string,
    rows: StackReconcileEvidenceRow[],
    finalBaseSha: string,
  ) {
    this.#objective = objective;
    this.url = url;
    this.rows = Object.freeze(rows.map((row) => Object.freeze({ ...row })));
    this.finalBaseSha = finalBaseSha;
  }

  get objective(): string {
    return this.#objective;
  }
}

export type { StackReconcileEvidence };

function evidenceToken(source: ColdJson, key: string): string {
  const value = stringField(source, key);
  return value !== undefined && EVIDENCE_ID_RE.test(value) ? value : "?";
}

function evidenceSha(source: ColdJson, key: string): string {
  const value = stringField(source, key);
  return value !== undefined && EVIDENCE_SHA_RE.test(value) ? value : "?";
}

/** The PR render vocabulary: only a positive safe integer renders (a float, a negative, an
 * unsafe magnitude, or a non-number degrades to `"?"` — never an exotic numeric form). */
function evidencePr(source: ColdJson): string {
  const value = numberField(source, "pr_number");
  return value !== undefined && Number.isSafeInteger(value) && value > 0 ? String(value) : "?";
}

/**
 * The URL mint: accepted only when `new URL(...)` parses with protocol `https:`, empty
 * username/password, and the RECONSTRUCTED `href` inside the printable vocabulary — the minted
 * value is the reconstruction, never the raw string; anything else is `""` (the drive renders
 * without a link). The reconstruction must equal the raw input: a url the parser had to REPAIR
 * (percent-encoding a space, a backtick, a control character) is refused rather than silently
 * rewritten — the parser's escaping would otherwise launder interpolation-hostile bytes into a
 * vocabulary-passing form.
 */
function evidenceUrl(raw: string | undefined): string {
  if (raw === undefined) return "";
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return "";
  }
  if (parsed.protocol !== "https:") return "";
  if (parsed.username !== "" || parsed.password !== "") return "";
  if (!PRINTABLE_HTTPS_RE.test(parsed.href)) return "";
  return parsed.href === raw ? parsed.href : "";
}

/** The reconcile decision: drive with minted evidence, or nothing. */
export type StackReconcileDecision =
  | { drive: false }
  | { drive: true; evidence: StackReconcileEvidence };

/**
 * Decide the §8.56 reconcile drive over a mutating land/recover envelope (untrusted DATA). The
 * gate: never dry-run; `reconcile_evidence` present with ≥1 layer; the redirect-resolved ACTIVE
 * objective id (never the requested one) inside the identifier vocabulary. On drive, the
 * evidence is minted from per-field-sanitized primitives — journal-originated strings are
 * untrusted DATA headed for a steering message, so every field is whitelist-validated against
 * its vocabulary; anything else renders as `"?"` (ids/SHAs/PR) or `""` (url).
 */
export function decideStackReconcile(payload: ColdJson): StackReconcileDecision {
  if (booleanField(payload, "dry_run") === true) return { drive: false };
  const evidence = objectField(payload, "reconcile_evidence");
  if (evidence === undefined) return { drive: false };
  const layers = objectListField(evidence, "layers");
  if (layers.length === 0) return { drive: false };
  const obj = objectField(payload, "objective") ?? {};
  const id = stringField(obj, "id");
  if (id === undefined || !EVIDENCE_ID_RE.test(id)) return { drive: false };
  const rows = layers.map((layer) => ({
    node: evidenceToken(layer, "node_id"),
    plan: evidenceToken(layer, "plan_id"),
    pr: evidencePr(layer),
    baseSha: evidenceSha(layer, "base_sha"),
    headSha: evidenceSha(layer, "head_sha"),
    mergeSha: evidenceSha(layer, "merge_commit_sha"),
  }));
  return {
    drive: true,
    evidence: new StackReconcileEvidence(
      id,
      evidenceUrl(stringField(obj, "url")),
      rows,
      evidenceSha(evidence, "final_base_sha"),
    ),
  };
}
