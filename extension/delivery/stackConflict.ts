// The §8.51 warm sync-conflict state machine (the stacked-delivery conflict half of the
// delivery family), Pi-free.
//
// The warm layer owns the DECISION tier only: fail-closed corroboration over the untrusted cold
// status projection, the bounded dispatch pipeline (`decideSyncResolution`), the auto-fire
// predicate, and the episode-settling reset rule. The real train state machine — journal,
// cascade, continuation manifests, recovery, landing — is Python-owned (contracts.md
// §8.42/§8.43/§8.49/§8.51); exterior effects reach TypeScript only as typed cold-door outcomes
// composed by the adapters in `pi/v1/delivery/`. No warm journal writes, no ref mutations, no
// readiness re-derivation.
//
// The warm transition table (contracts-grounded; the reconcile decision rows live in
// `delivery/stackReconcile.ts`):
//
// | Operation | Persisted facts (authority) | Warm gesture → cold effect | Consent | Typed arms | Recovery |
// |---|---|---|---|---|---|
// | SYNC cascade (§8.49) | Journal SYNC prepared/completed/abandoned; checkpoints; continuation manifest on conflict (Python-written) | `objective_stack_sync {}`/`{base}` → `sync --yes`; `{dry_run}` → no consent, no journal | human gesture = `--yes` | no-op (± base-advanced hint) / declined / synchronized N / dry-run preview; failure: `rebase_conflict` (continuation retained) et al. | `/objective-recover` classifies; conflict → continue/abort/resolve |
// | SYNC continue/abort (§8.49/§8.51) | Continuation manifest + temp refs + retained worktree | `{continue}`/`{abort}` → `--continue/--abort --yes` | human gesture | continued N / continuation declined / aborted-discarded | abandoned continuations self-clean; recover sweeps residue |
// | ADOPT (§8.49) | Same journal; adopted node's remote head | `objective_stack_adopt {node, confirm}`; dry-run previews | `confirm: true` + dry-run-first | adopted + cascade rendered | never enters this dispatch pipeline (adapter-pinned) |
// | Conflict dispatch (§8.51, warm-only) | Continuation manifest (containment-validated by the cold projection — `targets_contained`); fresh status projection; `conflict_resolution_attempts`; resolver lock dir | auto-fire on eligible refusal, or `{resolve: true}` | auto: the human's mutating gesture; resolve: explicit request | `dispatched(attempt/cap)` / `no_continuation` / `attempt_cap` / `resolver_busy` / `state_error` (total boundary) | increment verified BEFORE injection; unpersisted/thrown → withhold + release this call's claim |
//
// Progress is recorded only after verified effects: the counter reset fires only on a clean
// cold completion; the increment is persisted-and-verified before any dispatch injection.

import { basename, dirname } from "node:path";
import {
  booleanField,
  type ColdJson,
  numberField,
  objectField,
  objectListField,
  stringField,
} from "../substrate/coldDoor.ts";
import type { LeaseAcquisition } from "../substrate/resolverLease.ts";
import { type ConflictAttempts, inspectConflictBudget } from "./submit.ts";

/** The sync-tool invocation mode (which control flags the call carried) — decline wording and
 * the completion verb depend on it, and the flags do not fully disambiguate the envelope.
 * Deliberately narrow: adopt is NOT a `SyncMode` — its no-dispatch behavior is pinned at the
 * adopt adapter, never through a widened predicate. */
export type SyncMode = "sync" | "continue" | "abort";

// --- the interpolation vocabularies (module-private, fail-closed) --------------------------------
// Containment (`targets_contained`) is the cold plane's filesystem-truth validation; these
// lexical vocabularies guard the UNQUOTED template interpolations — which containment alone
// does not.

/** The identifier vocabulary for node/objective ids — whitelist validation doubles as
 * control-character/line-break exclusion, so a poisoned projection string can never break out
 * of the injected dispatch. Alphanumeric-first: ids reach unquoted CLI-argument positions in
 * the dispatch template, so an option-shaped `-`-leading id never passes. */
const ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
/** The ONE lineage predicate — the exact warm twin of the Python `_SAFE_LINEAGE_RE` vocabulary. */
const LINEAGE_RE = /^[0-9A-Za-z][0-9A-Za-z_-]{0,63}$/;
/** A canonical 26-char Crockford ULID operation id (`validated_targets`' shape, warm side). */
const OPERATION_ULID_RE = /^[0-9A-HJKMNP-TV-Z]{26}$/;
/**
 * The shell-inert absolute-path vocabulary: no space, no shell metacharacter — the dispatch
 * template renders an UNQUOTED `cd {{ worktree }}`, so containment here is what keeps the
 * interpolation from ever becoming shell syntax. A legitimate-but-exotic worktree root (e.g.
 * containing spaces) degrades to report-only — an accepted, recorded degradation.
 */
const SHELL_INERT_ABS_PATH_RE = /^\/[A-Za-z0-9._/-]+$/;
/** Branch names interpolate as unquoted git arguments — alphanumeric-first (option-shaped
 * `-`-leading refs are refused; git itself rejects them, so nothing legitimate is lost). */
const BRANCH_RE = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$/;

function hasDotDotSegment(path: string): boolean {
  return path.split("/").includes("..");
}

/** The sanitized dispatch facts — every string is whitelist-validated before it gets here. */
export interface SyncConflictDispatch {
  operationId: string;
  manifestPath: string;
  objective: string;
  node: string;
  branch: string;
  pr: number;
  worktree: string;
}

/**
 * Corroborate a retained sync conflict against the fresh status projection (§8.51): the
 * continuation facts, the cold projection's containment verdict (`targets_contained` — the
 * canonical Python `validated_targets` check relayed by §8.44; absent under version skew fails
 * closed), the refusal-message freshness token, lineage/worktree containment, the conflicting
 * layer's identity, and the interpolation vocabularies. Fail-closed: any miss is ineligible
 * with the specific reason. `refusalMessage === null` skips ONLY the freshness-token clause
 * (the explicit `resolve` path — there is no refusal; the human's request against the CURRENT
 * projection is the trigger).
 */
export function corroborateSyncConflict(
  payload: ColdJson,
  refusalMessage: string | null,
): { eligible: true; dispatch: SyncConflictDispatch } | { eligible: false; reason: string } {
  const ineligible = (reason: string) => ({ eligible: false as const, reason });
  const continuation = objectField(payload, "continuation");
  if (continuation === undefined) {
    return ineligible(
      "the status projection reports no pending continuation — nothing was retained (a failed " +
        "manifest write cleans its residue); fix the underlying issue and rerun the sync",
    );
  }
  if (booleanField(continuation, "parseable") !== true) {
    return ineligible(
      "the pending continuation manifest is UNPARSEABLE — automated resolution cannot " +
        "corroborate it; discard the retained continuation via objective_stack_sync " +
        "{ abort: true } and rerun the sync",
    );
  }
  // The containment gate: the cold projection computes the canonical `validated_targets`
  // containment (Python filesystem truth — symlink-safe). A poisoned or symlinked manifest
  // worktree can never mint a dispatch; an older CLI omits the field and fails closed.
  if (booleanField(continuation, "targets_contained") !== true) {
    return ineligible(
      "the pending continuation's targets are not containment-validated by the cold status " +
        "projection — resolve the rebase by hand in the retained worktree, or discard via " +
        "objective_stack_sync { abort: true } (an older perk CLI never validates; update so " +
        "both planes match).",
    );
  }
  const operationId = stringField(continuation, "operation_id");
  const node = stringField(continuation, "conflict_node_id");
  const worktree = stringField(continuation, "worktree_path");
  const manifestPath = stringField(continuation, "manifest_path");
  if (
    operationId === undefined ||
    node === undefined ||
    worktree === undefined ||
    manifestPath === undefined
  ) {
    return ineligible(
      "the pending continuation is missing operation/layer/path facts — resolve the rebase by " +
        "hand in the retained worktree, or discard via objective_stack_sync { abort: true }",
    );
  }
  if (!ID_RE.test(node)) {
    return ineligible(
      "the continuation's conflict node id falls outside the identifier vocabulary — refusing " +
        "to dispatch; resolve by hand in the retained worktree",
    );
  }
  // Freshness: every `rebase_conflict` arm names the layer whose rebase actually STOPPED as
  // `for layer <node_id> ` (trailing space — `2.2` never matches `2.22`). On the continue-time
  // failed-rewrite arm the PRESERVED manifest names the OLD layer while the message names the
  // NEW one — the mismatch keeps the drive report-only over stale layer facts.
  if (refusalMessage !== null && !refusalMessage.includes(`for layer ${node} `)) {
    return ineligible(
      `the refusal does not name the manifest's conflict layer ${node} — the retained ` +
        "manifest may be a stale snapshot (a failed progress rewrite preserves the previous " +
        "one); resolve the in-progress rebase by hand in the retained worktree, or discard via " +
        "objective_stack_sync { abort: true }",
    );
  }
  const train = objectField(payload, "train") ?? {};
  const lineage = stringField(train, "delivery_lineage");
  if (lineage === undefined || !LINEAGE_RE.test(lineage)) {
    return ineligible(
      "the train reports no vocabulary-valid delivery lineage — refusing to derive the claim " +
        "path; dispatch the resolution by hand",
    );
  }
  if (
    basename(manifestPath) !== `${lineage}.json` ||
    basename(dirname(manifestPath)) !== "sync-continuations"
  ) {
    return ineligible(
      "the continuation manifest path is not sync-continuations/<lineage>.json — refusing to " +
        "claim it; dispatch the resolution by hand",
    );
  }
  if (!OPERATION_ULID_RE.test(operationId)) {
    return ineligible(
      "the continuation's operation id is not a canonical ULID — refusing to dispatch; resolve " +
        "by hand in the retained worktree",
    );
  }
  if (
    !SHELL_INERT_ABS_PATH_RE.test(worktree) ||
    hasDotDotSegment(worktree) ||
    basename(worktree) !== `sync-${operationId}`
  ) {
    return ineligible(
      "the retained worktree path falls outside the shell-inert containment vocabulary " +
        "(absolute, sync-<operation-id>, no spaces or shell metacharacters) — dispatch the " +
        "resolution by hand in the retained worktree the status names",
    );
  }
  const layer = objectListField(train, "layers").find(
    (row) => stringField(row, "node_id") === node,
  );
  if (layer === undefined) {
    return ineligible(
      "the conflicting layer is missing from the train projection — refusing to dispatch; " +
        "inspect the train and resolve by hand",
    );
  }
  const branch = stringField(layer, "branch");
  const pr = numberField(layer, "pr_number");
  if (branch === undefined || pr === undefined) {
    return ineligible(
      "the conflicting layer carries no branch/PR identity — the resolver's retained mode " +
        "requires the PR; resolve by hand in the retained worktree",
    );
  }
  if (!BRANCH_RE.test(branch) || branch.startsWith("/") || hasDotDotSegment(branch)) {
    return ineligible(
      "the conflicting layer's branch falls outside the interpolation vocabulary — refusing " +
        "to dispatch; resolve by hand in the retained worktree",
    );
  }
  // The redirect-resolved ACTIVE objective id — never the requested one (the
  // driveStackReconcile rule): out-of-vocabulary → never drive.
  const objective = stringField(objectField(payload, "objective") ?? {}, "id");
  if (objective === undefined || !ID_RE.test(objective)) {
    return ineligible(
      "the projection's objective id falls outside the identifier vocabulary — refusing to " +
        "dispatch; resolve by hand in the retained worktree",
    );
  }
  return {
    eligible: true,
    dispatch: { operationId, manifestPath, objective, node, branch, pr, worktree },
  };
}

/**
 * The §8.51 auto-fire rule: a MUTATING sync/continue — never dry-run, never abort (adopt never
 * reaches this predicate; its no-dispatch behavior is adapter-pinned) — refusing
 * `rebase_conflict` is dispatch-eligible (the human's mutating gesture is the approval).
 */
export function autoDispatchEligible(
  mode: SyncMode,
  dryRun: boolean,
  failure: { errorType: string } | null,
): boolean {
  if (failure === null || failure.errorType !== "rebase_conflict") return false;
  if (dryRun) return false;
  return mode === "sync" || mode === "continue";
}

/**
 * The episode-settling reset rule: any clean, non-declined MUTATING completion re-opens the
 * shared bounded conflict budget (write 0, preserving the equal-value short-circuit — an
 * already-zero counter appends nothing). Never throws: a thrown or `false` write returns
 * `false`, and the ADAPTER reports the reset-failure warning — a stale counter must be visible,
 * never fatal to an already-verified cold completion.
 */
export function settleSyncEpisode(
  attempts: ConflictAttempts,
  outcome: { mutating: boolean; declined: boolean },
): boolean {
  if (!outcome.mutating || outcome.declined) return true;
  try {
    if (attempts.read() === 0) return true;
    return attempts.write(0);
  } catch {
    return false;
  }
}

/** The resolver-claim port — production = `acquireResolverLease`/`releaseResolverClaim`
 * (substrate/resolverLease.ts), composed module-privately by the sync adapter. */
export interface ResolverClaim {
  acquire(manifestPath: string, operationId: string): LeaseAcquisition;
  release(manifestPath: string, token: string): void;
}

/** The dispatch pipeline's ports — action-specific, never a facade. `readProjection` is the
 * corroborating `perk objective stack status --json` re-read (module-private in the adapter). */
export interface SyncResolutionDeps {
  readProjection: () => Promise<{ ok: true; payload: ColdJson } | { ok: false; message: string }>;
  claim: ResolverClaim;
  attempts: ConflictAttempts;
}

/** The closed dispatch outcome — kinds map 1:1 onto the tool-surface `errorType`s. */
export type SyncResolutionOutcome =
  | { kind: "dispatched"; dispatch: SyncConflictDispatch; attempt: number; cap: number }
  | { kind: "no_continuation" | "attempt_cap" | "resolver_busy" | "state_error"; reason: string };

function releaseQuietly(claim: ResolverClaim, held: { manifestPath: string; token: string }): void {
  try {
    claim.release(held.manifestPath, held.token);
  } catch {
    // best-effort — leftover claim residue self-heals via the lease's reclaim rules
  }
}

/**
 * The shared dispatch pipeline (auto-drive AND the explicit `resolve` request), in pinned
 * order: re-read the status projection → corroborate (containment + vocabularies) → inspect the
 * shared bounded budget → take the resolver claim → persist the verified increment (a
 * precondition for dispatch — an unverifiable counter must never bypass the cap; a `false`
 * commit withholds and releases THIS call's claim, token-fenced) → `dispatched`. Rendering and
 * injection stay adapter-side. Resolve-and-stop: nothing here publishes — the injected template
 * owns the outcome gate and the human's `continue` stays the only publication gesture.
 *
 * Total boundary: every thrown port failure — a throwing projection read, claim port, or
 * counter read/write — is caught and translated to the typed `state_error` arm (reason prefixed
 * `conflict-dispatch state failure:`), releasing this call's claim when one was acquired. The
 * closed union is honest; nothing escapes as a rejection.
 */
export async function decideSyncResolution(
  deps: SyncResolutionDeps,
  refusalMessage: string | null,
): Promise<SyncResolutionOutcome> {
  let held: { manifestPath: string; token: string } | null = null;
  try {
    const projection = await deps.readProjection();
    if (!projection.ok) {
      return {
        kind: "no_continuation",
        reason: `the corroborating status re-read failed — ${projection.message}`,
      };
    }
    const corroborated = corroborateSyncConflict(projection.payload, refusalMessage);
    if (!corroborated.eligible) {
      return { kind: "no_continuation", reason: corroborated.reason };
    }
    const dispatch = corroborated.dispatch;
    const budget = inspectConflictBudget(deps.attempts);
    if (budget.kind === "exhausted") {
      return {
        kind: "attempt_cap",
        reason:
          `the rebase conflict persists after ${budget.attempts} resolution attempt(s) — ` +
          `resolve manually in the retained worktree ${dispatch.worktree} ` +
          "(`git rebase --continue`), then resume via objective_stack_sync { continue: true } " +
          "or discard via { abort: true }.",
      };
    }
    const lease = deps.claim.acquire(dispatch.manifestPath, dispatch.operationId);
    if (!lease.acquired) {
      return {
        kind: lease.kind === "busy" ? "resolver_busy" : "state_error",
        reason: lease.reason,
      };
    }
    held = { manifestPath: dispatch.manifestPath, token: lease.token };
    if (!deps.attempts.write(budget.next)) {
      // The seam's strict read-back boolean passes through unsoftened: the verified increment
      // is a precondition for dispatch — without it the cap is unenforceable. Release the
      // claim acquired in THIS call so the withheld dispatch leaves no phantom holder —
      // token-fenced, so a successor's raced-in claim is never deleted.
      releaseQuietly(deps.claim, held);
      held = null;
      return {
        kind: "state_error",
        reason: "the attempt counter could not be persisted — dispatch withheld",
      };
    }
    // Dispatched: the claim deliberately stays held (fire-and-forget dispatch; the lease
    // self-heals — see substrate/resolverLease.ts).
    held = null;
    return { kind: "dispatched", dispatch, attempt: budget.next, cap: budget.cap };
  } catch (error) {
    if (held !== null) releaseQuietly(deps.claim, held);
    const message = error instanceof Error ? error.message : String(error);
    return { kind: "state_error", reason: `conflict-dispatch state failure: ${message}` };
  }
}
