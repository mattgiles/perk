// Perk-owned Pi session names (contracts.md §8.71(h)) — the Pi-free naming core.
//
// The name grammar: `<origin stage> | plan #N | objective #O / <node> | <title>` — segments
// omitted when unknown, never guessed; a node renders ONLY beside an objective; no gist segment.
//
// The origin rule: a session is nameable only when its branch carries cold-launch provenance —
// the FIRST `perk:workflow-state` entry carrying BOTH `run_id` and `stage` (the cold claim's
// combined entry). NOT the LWW `stage` (an implement conversation stays `implement` after later
// stage appends), NOT the warm stage-only `enter-refinement-stage` append (a minted hand-run or
// adopted session that runs a warm `/objective-refine` pass stays unnamed). A fork inherits its
// parent's origin because the parent's claim entry heads the fork's branch; an adopted
// env-child's fresh branch has none.
//
// The ownership rule: perk overwrites Pi's current name only when it is absent or equals perk's
// own last record (`session_name`) — a differing `/name` or `pi --name` value is preserved.
// Accepted residual: a human `/name` that repeats perk's record byte-for-byte is
// indistinguishable from perk's own write and is treated as owned (perk never inspects
// `session_info` entry provenance).
//
// The hint policy: `override` (the cold claim and the later draft/save refreshes — newest wins)
// vs `fill` (a reload replays its retained launch-era handoff only into fields nothing has
// learned yet, so a later-learned title survives reopen). Hints are decoded before they
// participate, so a blank/undefined field can never clobber a stored value; learned hints persist
// regardless of ownership — only the name write is ownership-gated.
//
// The control-character rule: Pi strips only CR/LF and writes the name into an OSC terminal-title
// sequence, so every segment AND the joined result are stripped of C0/C1 controls, the Unicode
// line/paragraph separators and the bidi/format controls before they reach `setSessionName`.
//
// Best-effort posture: one `failed` outcome (rendered as a warning by the Pi binding), never a
// blocked startup. Effects enter only through the structural `SessionNamePorts` slice, so the
// whole module is unit-testable with fakes (the extension-seams recipe).

import {
  type BranchEntry,
  WORKFLOW_STATE_TYPE,
  type WorkflowState,
} from "../substrate/workflowState.ts";

/** The learned naming hints — the handoff's `naming` object and the stored `session_naming`. */
export interface NamingHints {
  title?: string;
  node?: string;
}

/** The maximum title length in Unicode code points (never split a surrogate pair). */
const TITLE_CAP = 80;

/**
 * Every character a terminal or Pi's title sink could interpret: C0 controls (`U+0000–U+001F`),
 * DEL (`U+007F`), C1 controls (`U+0080–U+009F`), the line/paragraph separators
 * (`U+2028`/`U+2029`) and the Unicode bidi/format controls (`U+061C` — the Arabic letter mark,
 * the one `Bidi_Control` character outside the General Punctuation block — `U+200B–U+200F`,
 * `U+202A–U+202E`, `U+2060–U+2064`, `U+2066–U+2069`, `U+FEFF`).
 */
const CONTROL_CHARACTERS =
  // biome-ignore lint/suspicious/noControlCharactersInRegex: the point is to strip them
  /[\u0000-\u001f\u007f-\u009f\u061c\u2028\u2029\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;

/** Remove (never replace) every control character `CONTROL_CHARACTERS` names. */
export function stripControls(text: string): string {
  return text.replace(CONTROL_CHARACTERS, "");
}

/**
 * Normalize a raw title for the name's last segment: collapse whitespace runs (tabs/newlines
 * included — so a wrapped title keeps its word boundary instead of losing the control
 * character); strip controls; trim; strip a leading run of `#` (+ following spaces); cap at
 * `TITLE_CAP` code points (longer → the first 79 code points + `…`, never a split surrogate
 * pair); blank → `null`.
 */
export function normalizeTitle(raw: string | null | undefined): string | null {
  if (typeof raw !== "string") return null;
  let text = stripControls(raw.replace(/\s+/g, " ")).trim().replace(/\s+/g, " ");
  text = text.replace(/^#+\s*/, "");
  if (text === "") return null;
  const points = Array.from(text);
  if (points.length > TITLE_CAP) {
    text = `${points.slice(0, TITLE_CAP - 1).join("")}…`;
  }
  return text;
}

/**
 * The TS twin of Python `plan.derive_title`: the first ATX `# ` heading with 0–3 spaces of
 * indent outside a ```` ``` ````/`~~~` fence, else `null`. Raw heading text — callers normalize.
 */
export function deriveTitle(markdown: string): string | null {
  let fence: string | null = null;
  for (const line of markdown.split(/\r?\n/)) {
    const stripped = line.replace(/^ +/, "");
    if (stripped.startsWith("```") || stripped.startsWith("~~~")) {
      const marker = stripped.slice(0, 3);
      fence = fence === null ? marker : marker === fence ? null : fence;
      continue;
    }
    if (fence !== null) continue; // inside a code fence — a leading `#` here is not a heading
    if (line.length - stripped.length <= 3 && stripped.startsWith("# ")) {
      const title = stripped.slice(2).trim();
      if (title !== "") return title;
    }
  }
  return null;
}

/**
 * The ONE identifier narrowing: a string's control-stripped, trimmed form, or `null` when the
 * value is not a string or is blank after that. Used both when identifiers are decoded from the
 * unvalidated rebuilt state (BEFORE ranking — so a control-only or blank higher-tier value can
 * never win precedence and then vanish at compose time) and again inside `composeSessionName`
 * (belt-and-braces on its public inputs).
 */
function cleanId(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const cleaned = stripControls(value).trim();
  return cleaned === "" ? null : cleaned;
}

/**
 * Compose the name from its known parts. Every id passes through `stripControls` + trim (blank →
 * omitted); a node renders ONLY with an objective; the title is normalized; the joined result is
 * stripped once more so the ONE exit to `setSessionName` is control-free by construction.
 */
export function composeSessionName(parts: {
  purpose: string;
  planId: string | null;
  objectiveId: string | null;
  nodeId: string | null;
  title: string | null;
}): string {
  const segments: string[] = [];
  const purpose = cleanId(parts.purpose);
  if (purpose !== null) segments.push(purpose);
  const planId = cleanId(parts.planId);
  if (planId !== null) segments.push(`plan #${planId}`);
  const objectiveId = cleanId(parts.objectiveId);
  if (objectiveId !== null) {
    const nodeId = cleanId(parts.nodeId);
    segments.push(
      nodeId === null ? `objective #${objectiveId}` : `objective #${objectiveId} / ${nodeId}`,
    );
  }
  const title = normalizeTitle(parts.title);
  if (title !== null) segments.push(title);
  return stripControls(segments.join(" | "));
}

/**
 * The origin stage — durable cold-launch provenance: the FIRST `perk:workflow-state` entry whose
 * data carries BOTH a non-empty string `run_id` AND a non-empty string `stage`. Only the cold
 * claim's combined entry carries both (fork/adopt entries carry `run_id` without `stage`; the warm
 * `enter-refinement-stage` append carries `stage` alone), so a minted hand-run or adopted session
 * stays `null` even after a warm refinement pass, while a fork inherits its parent's origin.
 */
export function originStage(branch: readonly BranchEntry[]): string | null {
  for (const entry of branch) {
    if (entry.type !== "custom" || entry.customType !== WORKFLOW_STATE_TYPE) continue;
    const data = entry.data ?? {};
    const runId = cleanId(data.run_id);
    const stage = cleanId(data.stage);
    if (runId !== null && stage !== null) return stage;
  }
  return null;
}

/**
 * Structurally decode naming hints from ANY source — the handoff `naming` object, the stored
 * `session_naming`, or the caller's own `hints`: a non-null object's `title`/`node` when non-blank
 * strings (trimmed, controls stripped); anything else → the field is absent. The core normalizes
 * its input, so a present-but-`undefined` or blank hint field can never clobber a stored value.
 *
 * The title is prose: its whitespace runs (tabs/newlines included) collapse to one space BEFORE
 * the control strip, exactly as `normalizeTitle` does, so a multi-line node description keeps
 * its word boundaries in the persisted hint. The node is an identifier and stays strict.
 */
export function decodeNamingHints(value: unknown): NamingHints {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return {};
  const record = value as Record<string, unknown>;
  const hints: NamingHints = {};
  const title =
    typeof record.title === "string" ? cleanId(record.title.replace(/\s+/g, " ")) : null;
  if (title !== null) hints.title = title;
  const node = cleanId(record.node);
  if (node !== null) hints.node = node;
  return hints;
}

/**
 * `override`: decoded hint fields win over stored ones (the cold claim; the later draft/save
 * refreshes — newest wins). `fill`: decoded hint fields apply ONLY where the stored field is
 * absent (a reload replaying its retained launch-era handoff must never revert a later-learned
 * title).
 */
export type HintPolicy = "override" | "fill";

/** The structural effects slice the refresh flows through (the Pi binding composes it). */
export interface SessionNamePorts {
  branch(): readonly BranchEntry[];
  rebuild(): WorkflowState;
  append(data: WorkflowState): void;
  getSessionName(): string | undefined;
  setSessionName(name: string): void;
}

export type SessionNameOutcome =
  | { status: "applied"; name: string }
  | { status: "unchanged"; name: string }
  | { status: "preserved"; current: string }
  | { status: "skipped"; reason: "no-origin" }
  | { status: "failed"; problem: string };

function hintsEqual(a: NamingHints, b: NamingHints): boolean {
  return a.title === b.title && a.node === b.node;
}

/**
 * The all-or-nothing `objective_node_claim` decode (mirrors `workflowSession.ts::readClaim`, with
 * both fields narrowed to their final control-stripped, trimmed form).
 */
function decodeClaim(value: unknown): { objective: string; node: string } | null {
  if (typeof value !== "object" || value === null) return null;
  const record = value as Record<string, unknown>;
  const objective = cleanId(record.objective);
  const node = cleanId(record.node);
  return objective !== null && node !== null ? { objective, node } : null;
}

/**
 * Refresh the perk-owned session name: origin → persist merged hints → decode-then-rank the
 * identifiers → compose → ownership-gated write. Everything runs inside ONE try/catch (`failed`
 * with the problem text); nothing is appended when there is no origin.
 *
 * Decode, then rank: every identifier is narrowed from the unvalidated rebuilt state to its
 * FINAL form (a non-blank string after control stripping + trim, via `cleanId`) BEFORE
 * precedence, so a malformed, blank or control-only high-priority value never suppresses a
 * valid lower-tier one, and a half-valid claim never pairs its node with a fallback objective.
 *
 * An append that throws AFTER a successful `setSessionName` is `failed` and leaves the name in
 * place; the next refresh classifies it `preserved` (accepted residual — the ownership record is
 * missing).
 */
export function refreshSessionName(
  ports: SessionNamePorts,
  input: { hints: NamingHints; policy: HintPolicy },
): SessionNameOutcome {
  try {
    const purpose = originStage(ports.branch());
    if (purpose === null) return { status: "skipped", reason: "no-origin" };

    const state = ports.rebuild();
    const stored = decodeNamingHints(state.session_naming);
    const hints = decodeNamingHints(input.hints);
    const merged: NamingHints =
      input.policy === "override" ? { ...stored, ...hints } : { ...hints, ...stored };
    if ((merged.title !== undefined || merged.node !== undefined) && !hintsEqual(merged, stored)) {
      ports.append({ session_naming: merged }); // learned facts persist regardless of ownership
    }

    const claim = decodeClaim(state.objective_node_claim);
    const planId = cleanId(state.active_plan_ref?.pr_id);
    const refObjective = cleanId(state.active_plan_ref?.objective_id);
    const activeObjective = cleanId(state.active_objective);
    const objectiveId = claim?.objective ?? refObjective ?? activeObjective;
    const nodeId = objectiveId === null ? null : (claim?.node ?? merged.node ?? null);
    const title = merged.title ?? null;

    const composed = composeSessionName({ purpose, planId, objectiveId, nodeId, title });
    const current = ports.getSessionName();
    const owned = current === undefined || current === state.session_name;
    if (!owned) return { status: "preserved", current };
    if (composed === current) return { status: "unchanged", name: composed };
    ports.setSessionName(composed);
    ports.append({ session_name: composed });
    return { status: "applied", name: composed };
  } catch (error) {
    return { status: "failed", problem: String(error) };
  }
}
