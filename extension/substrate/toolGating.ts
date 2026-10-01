// The tool-gating primitive (the keystone). Structural read-only enforcement, NOT
// prompting. Mirrors pi's authoritative `examples/extensions/plan-mode/` recipe (the
// `setActiveTools` allowlist + `tool_call` bash sub-allowlist + `before_agent_start` injection
// (once-only per SELECTED BRANCH: full-branch-scan dedup'd on the marker — historical, so a
// copy compaction has summarized out of model context still suppresses; enforcement never rode
// the prose) + `context` strip-when-off) and `preset.ts`'s snapshot-then-restore. The gate attaches to the
// existing `perk:workflow-state.mode` field (`read-only`/`read-write`) — no new registry stage.
// Beside the gate lives per-stage active-tool scoping over the diet universe (the tool catalog +
// the enumerated borrowed-package census), keyed off the workflow-state `stage` field and applied
// at the same rebuild points (contracts.md §8.40) — fail-open where the gate is fail-closed, save
// the one refused call: a borrowed lazy loader invoked where the tools it enables are ineligible.
// Both concerns install views DERIVED from the one eligibility formula (`toolPolicy.ts`); this
// module owns only the controller, the mode-context injection and the lazy-owner reconciliation.
// The bash verdict lives in `readOnlyBash.ts`.
//
// Substrate only: the gate-ENTRY consumers are perk-owned plan mode (`pi/v1/plan.ts`: `/plan`,
// `--plan`, `Ctrl+Alt+P`), the warm `/objective-plan` factory (`pi/v1/objectivePlanning.ts`) and
// the warm `/objective-refine` entry (`pi/v1/objectiveRefinement.ts`); `exit` rides the plan-mode
// toggle and the save/exit doors. The CI executor (`pi/v1/delivery/ci.ts`) never touches the gate.
// The allowlist-restore is wired into the existing `session_start`/`session_tree` rebuild points
// plus one `resources_discover` re-apply.

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { render } from "./prompts.ts";
import { readOnlyBashVerdict } from "./readOnlyBash.ts";
import {
  carveOutWritersFor,
  dietUniverse,
  gatedToolsFor,
  isEligible,
  normalizeStage,
  stageToolsFor,
} from "./toolPolicy.ts";
import { branchCarries, branchOf, WORKFLOW_STATE_TYPE } from "./workflowState.ts";

/**
 * Borrowed lazy-activation loaders → the tools each one activates (contracts.md §8.40). While
 * the loader is registered, a lazy-owned tool's ACTIVATION is its owner's decision — the owner
 * hides it until the model calls the loader, and replays the recorded selection on navigation;
 * perk owns only its ELIGIBILITY (mode/stage). Each loader rides the same family constant as the tools it enables, so its
 * eligibility equals theirs everywhere (pinned). Look entries up with `Object.hasOwn` first: a
 * tool named like a prototype key must not match.
 */
export const LAZY_TOOL_LOADERS: Readonly<Record<string, readonly string[]>> = {
  subagents_enable: ["subagent"],
  web_enable: ["web_search", "source_check", "fetch_content", "get_search_content"],
};

/**
 * The tools lazy-owned in this session: those of every loader currently REGISTERED (active or
 * not). An owner that registers its tools eagerly and no loader — an older version, or its
 * host-probe fallback — owns nothing lazily: nothing could re-enable a tool perk stripped, so its
 * tools keep the ordinary snapshot/allowlist behavior.
 */
function lazyOwnedBy(registered: Iterable<string>): ReadonlySet<string> {
  const owned = new Set<string>();
  for (const name of registered) {
    if (!Object.hasOwn(LAZY_TOOL_LOADERS, name)) continue;
    for (const tool of LAZY_TOOL_LOADERS[name] ?? []) owned.add(tool);
  }
  return owned;
}

/** The live tool state one install reads: the active set + the tools lazy-owned right now. */
type LiveSelection = { active: ReadonlySet<string>; lazyOwned: ReadonlySet<string> };

/**
 * Owner-selected membership: drop a lazy-owned name unless its owner currently has it active.
 * Every other name passes through.
 */
function ownerSelected(names: Iterable<string>, live: LiveSelection): string[] {
  return [...names].filter((name) => !live.lazyOwned.has(name) || live.active.has(name));
}

/** Where a loader call was refused: under the gate (optionally stage-scoped), or by a stage. */
export type LazyLoaderRefusalScope =
  | { kind: "gated"; stage: string | null }
  | { kind: "stage"; stage: string };

/** The stage-naming refusal reason for a loader called outside its tools' eligibility. */
export function lazyLoaderRefusalReason(loader: string, scope: LazyLoaderRefusalScope): string {
  const enabled = Object.hasOwn(LAZY_TOOL_LOADERS, loader) ? LAZY_TOOL_LOADERS[loader] : undefined;
  const tools = (enabled ?? []).join(", ");
  if (scope.kind === "gated") {
    const where = scope.stage === null ? "this gated session" : `the gated ${scope.stage} session`;
    return `perk read-only mode: ${loader} is blocked (its tools — ${tools} — are not allowlisted in ${where}).`;
  }
  return `perk stage scoping: ${loader} is blocked (its tools — ${tools} — are not available in the ${scope.stage} stage).`;
}

/** The read-only marker / custom-message type injected into context while active. */
const MODE_CONTEXT_TYPE = "perk:mode-context";
/** Every rendered flavor's marker starts with this (the perk-dev audit corpus scans for it). */
const MODE_MARKER_FAMILY = "[READ-ONLY MODE]";
/**
 * The pre-migration refinement flavor's marker — DETECTION-ONLY, never rendered again: a resumed
 * transcript's legacy block is dropped as stale while gated and stripped on gate exit, and a
 * legacy marker-bearing user echo keeps being stripped.
 */
const LEGACY_REFINEMENT_MARKER = "[READ-ONLY REFINEMENT MODE]";
const MODE_MARKERS: readonly string[] = [MODE_MARKER_FAMILY, LEGACY_REFINEMENT_MARKER];

/**
 * The selected flavor's dedup marker: one per scoped stage plus the unscoped flavor (an unknown
 * stage renders unscoped). The closing parenthesis keeps any flavor from being a prefix of another,
 * so neither flavor's presence masks another's dedup scan.
 */
export function readOnlyMarker(stage: string | null): string {
  const scoped = normalizeStage(stage);
  return scoped === null
    ? `${MODE_MARKER_FAMILY} (unscoped)`
    : `${MODE_MARKER_FAMILY} (stage ${scoped})`;
}

/**
 * The injected read-only context for a stage, naming exactly the carve-out writers eligible under
 * the gate there (no other tool enumeration — the gated view IS the active set). Rendered per
 * call: the catalog fills as the installers register, after this module is imported.
 */
export function renderReadOnlyContext(stage: string | null): string {
  const writers = carveOutWritersFor(normalizeStage(stage));
  const lines =
    writers.length === 0
      ? ["- No bounded writer is sanctioned in this session."]
      : writers.map((w) => `- \`${w.name}\` is a sanctioned bounded write: ${w.carveOut}.`);
  return render("contexts/read-only.md", {
    marker: readOnlyMarker(stage),
    writers: lines.join("\n"),
  });
}

/** The unscoped rendering of the read-only context. */
export function readOnlyContext(): string {
  return renderReadOnlyContext(null);
}

/** The mode-context flavor for a stage. */
function modeContextFor(stage: string | null): { marker: string; content: string } {
  return { marker: readOnlyMarker(stage), content: renderReadOnlyContext(stage) };
}

function textCarries(content: unknown, needles: readonly string[]): boolean {
  if (typeof content === "string") return needles.some((n) => content.includes(n));
  if (Array.isArray(content)) {
    return content.some((c) => {
      const part = c as { type?: string; text?: string };
      return part.type === "text" && needles.some((n) => (part.text ?? "").includes(n));
    });
  }
  return false;
}

// --- the controller -----------------------------------------------------------------------------

/** The API the plan-mode and read-only-stage consumers use + the lifecycle hooks index.ts wires. */
export interface ToolGating {
  /**
   * Reapply the gate + stage scoping from a rebuilt `mode` + `stage` (called on session_start
   * AND session_tree). `stage` is the branch-LWW workflow-state stage id (undefined = unscoped).
   */
  syncFromState(mode: string | undefined, stage: string | undefined): void;
  /** Enter read-only mode: persist `mode=read-only` + snapshot/restrict tools. (Called by plan mode — `/plan`, `--plan`, `Ctrl+Alt+P` — the warm objective-plan factory and the warm objective-refine entry; never the CI executor.) */
  enter(ctx?: ExtensionContext): void;
  /** Exit read-only mode: persist `mode=read-write` + restore tools. (Called by the plan-mode toggle and the save/exit doors.) */
  exit(ctx?: ExtensionContext): void;
  /** Whether the gate is currently active (in-memory source of truth for `tool_call`). */
  isActive(): boolean;
}

function isReadOnlyMode(mode: string | undefined): boolean {
  return mode === "read-only";
}

/** The engagement record: the host's active starting set (the restore authority — never
 * `getAllTools()` — for every name EXCEPT lazy-owned ones, whose membership is the owner's live
 * selection), the registry census at snapshot time, and the late registrants admitted so far. */
type Engaged = { snapshot: readonly string[]; census: ReadonlySet<string>; admitted: Set<string> };

export function registerToolGating(
  pi: ExtensionAPI,
  readOnlyFloor: () => boolean = () => false,
): ToolGating {
  // In-memory gate (mirrors plan-mode's `planModeEnabled`): the authority `tool_call` consults.
  // Fail-closed — a failed sync never opens this; tool_call blocks on any internal error.
  let active = false;
  // The branch-LWW stage id this session is scoped to (null = unscoped). Fail-open by contrast
  // with `active`: no stage / unknown stage / any lookup miss → no filtering.
  let stageId: string | null = null;
  // Taken ONCE on the first engagement of either concern (the preset.ts discipline, shared by the
  // gate and stage scoping); cleared when neither is engaged any more.
  let engaged: Engaged | null = null;

  function hasFloor(): boolean {
    try {
      return readOnlyFloor();
    } catch {
      // A broken restriction supplier cannot grant authority for this observation.
      return true;
    }
  }

  const isActive = () => active || hasFloor();
  // The gate-ON view follows the scoped stage (recomputed per observation — a late stage sync
  // re-scopes it, and the catalog fills after this controller is created).
  const gatedToolNames = (): ReadonlySet<string> => new Set(gatedToolsFor(stageId));

  /**
   * Recompute + install the active tool set from both concerns (contracts.md §8.40):
   *  - gate ON → the stage's gated view (`gatedToolsFor` — every name the eligibility formula
   *    admits read-only there: the stage's non-blocked tools plus the mode-over-stage set), NO
   *    further stage filter (the gated view already IS the diet).
   *  - gate OFF + stage scoped → a SUBTRACTIVE filter over the baseline (`baseline`): names
   *    outside the diet universe (builtins, child-side tools, un-enumerated foreign tools) pass
   *    through untouched; diet-universe names (the catalog ∪ BORROWED_TOOLS) survive only when
   *    the stage's diet (`stageToolsFor`) carries them.
   *  - neither engaged → restore the baseline and forget it (a session that never engages gets
   *    ZERO setActiveTools calls — bare warm sessions stay byte-identical).
   * Lazy-owned names (the tools of every REGISTERED loader in LAZY_TOOL_LOADERS) take their
   * membership from the owner's live selection in every arm: the gated view is a ceiling
   * (installed only while the owner has the tool selected), and the baseline neither restores one
   * the owner hid nor drops one it enabled. perk never re-activates or restores a lazy-owned tool
   * — Pi's transcript restore and the owner's recorded-selection replay do; perk only keeps it or
   * (by stage) strips it. While engaged the set is re-installed on every sync (tree navigation
   * across mode entries must recompute correctly).
   */

  /**
   * The gate-OFF reconciliation baseline: `snapshot ∪ admitted` under owner-selected membership,
   * plus every lazy-owned tool currently active. A tool the census never saw (pi-subagents'
   * `subagent_supervisor` registers in its own `session_start`, after perk's sync) is admitted
   * the first time it is seen active and stays admitted through perk's own filtering (so a
   * navigation back to an admitting stage restores it); an owner that deactivates its late tool
   * before perk ever sees it active is respected; a tool the census saw inactive is never
   * re-activated. A lazy-owned snapshot member the owner has since hidden is dropped, and one the
   * owner enabled after the snapshot is kept. Gate-OFF paths only (the gate-ON set is by name —
   * no bookkeeping there).
   */
  function baseline(e: Engaged, live: LiveSelection): string[] {
    for (const name of live.active) if (!e.census.has(name)) e.admitted.add(name);
    const lazyActive = [...live.active].filter((name) => live.lazyOwned.has(name));
    return [...new Set([...ownerSelected([...e.snapshot, ...e.admitted], live), ...lazyActive])];
  }

  /** The owner's live selection, read per install (after the first-engagement snapshot). */
  function readLive(): LiveSelection {
    return {
      active: new Set(pi.getActiveTools()),
      lazyOwned: lazyOwnedBy(pi.getAllTools().map((t) => t.name)),
    };
  }

  function apply(nextActive: boolean, nextStage: string | null): void {
    // Fail-closed: a read-only sync engages the in-memory gate BEFORE the fallible reads/installs.
    if (nextActive) active = true;
    const effective = nextActive || hasFloor();
    const stageList = stageToolsFor(nextStage);
    // First engagement of either concern: ONE literal (a throwing read records no half state).
    if ((effective || stageList !== undefined) && engaged === null) {
      engaged = {
        snapshot: pi.getActiveTools(),
        census: new Set(pi.getAllTools().map((t) => t.name)),
        admitted: new Set(),
      };
    }
    // The live reads follow the snapshot literal above, so the fail-closed ordering is unchanged.
    if (effective) {
      pi.setActiveTools(ownerSelected(gatedToolsFor(nextStage), readLive()));
    } else if (engaged !== null) {
      const base = baseline(engaged, readLive());
      if (stageList !== undefined) {
        // The diet universe is computed per install: the catalog fills after the controller.
        const scoped = new Set(dietUniverse());
        pi.setActiveTools(base.filter((name) => !scoped.has(name) || stageList.includes(name)));
      } else {
        pi.setActiveTools(base);
        engaged = null;
      }
    }
    active = nextActive;
    stageId = nextStage;
  }

  // Pi fires `resources_discover` after EVERY extension's `session_start` has run (pi-subagents
  // registers `subagent_supervisor` there, after perk's sync) — the one point where startup-late
  // registrants meet the gate/stage diet: re-apply the in-memory mode/stage (no rebuild, no other
  // checkpoint). Idempotent on `reason: "reload"`; a throw is Pi-reported and never opens the gate.
  pi.on("resources_discover", async () => {
    apply(active, stageId);
  });

  /**
   * The lazy-loader refusal (the one stage-enforced `tool_call`, contracts.md §8.40): a loader
   * called where the tools it enables are ineligible is refused with a stage-naming reason. The
   * owner re-advertises its loader every turn in its own `before_agent_start`, AFTER perk's
   * handler, so schema removal cannot hide it — refusing the activation call is the only way to
   * keep a stage-excluded tool from being reintroduced. The activated tool itself stays under
   * the fail-open stage filter. An unscoped or unknown-stage session never refuses.
   */
  function lazyLoaderRefusal(toolName: string): string | null {
    if (!Object.hasOwn(LAZY_TOOL_LOADERS, toolName)) return null;
    if (isActive()) {
      return gatedToolNames().has(toolName)
        ? null
        : lazyLoaderRefusalReason(toolName, { kind: "gated", stage: stageId });
    }
    const stageList = stageToolsFor(stageId);
    return stageId !== null && stageList !== undefined && !stageList.includes(toolName)
      ? lazyLoaderRefusalReason(toolName, { kind: "stage", stage: stageId })
      : null;
  }

  // Enforce the whole allowlist even if toolset narrowing failed or foreign tools registered late.
  pi.on("tool_call", async (event) => {
    try {
      const refusal = lazyLoaderRefusal(event.toolName);
      if (refusal !== null) return { block: true, reason: refusal };
      if (!isActive()) return;
      if (event.toolName === "edit" || event.toolName === "write") {
        return {
          block: true,
          reason: `perk read-only mode: ${event.toolName} is blocked (file modifications disabled).`,
        };
      }
      if (!isEligible(event.toolName, stageId, "read-only")) {
        return {
          block: true,
          reason: `perk read-only mode: ${event.toolName} is blocked (tool not allowlisted).`,
        };
      }
      if (event.toolName === "bash") {
        const command = String((event.input as { command?: unknown }).command ?? "");
        const verdict = readOnlyBashVerdict(command);
        if (!verdict.allowed) {
          return {
            block: true,
            reason: `perk read-only mode: command blocked (not allowlisted).\nCommand: ${command}\nReason: ${verdict.reason}`,
          };
        }
      }
      return;
    } catch {
      // Never let an internal error open the gate — fail closed.
      return { block: true, reason: "perk read-only mode: blocked (internal gating error)." };
    }
  });

  // Inject the hidden read-only mode context while active (display:false → not shown in transcript).
  pi.on("before_agent_start", async (_event, ctx) => {
    if (!isActive()) return;
    // Once-only per selected branch: injected customs persist to the branch, and the FULL-branch
    // scan (not live model context) dedups — a copy compaction summarized away still counts as
    // delivered on this branch history and is NOT re-injected; navigating to a branch that never
    // carried it injects again. Deliberate: this is the structural gate's guidance, and the gate
    // itself (tool_call) enforces regardless of what the model can still read.
    // The flavor follows the scoped stage: it names that stage's carve-out writers. The dedup key
    // is the SELECTED flavor's marker, so a session gated unscoped that then claims a stage still
    // receives that stage's flavor once.
    const flavor = modeContextFor(stageId);
    try {
      if (branchCarries(branchOf(ctx), flavor.marker)) return;
    } catch {
      // An unreadable branch cannot suppress required read-only guidance.
    }
    return {
      message: { customType: MODE_CONTEXT_TYPE, content: flavor.content, display: false },
    };
  });

  // Gate OFF: strip every mode-context flavor, legacy ones included (so none lingers). Gate ON:
  // retain ONLY the current flavor's injected block — a block from before a stage change (or a
  // pre-migration legacy block) is dropped from model context (the injected customType only; user
  // content is never touched while the gate is on).
  pi.on("context", async (event) => {
    if (isActive()) {
      const current = modeContextFor(stageId).marker;
      const stale = (m: unknown): boolean => {
        const msg = m as { customType?: string; content?: unknown };
        return (
          msg.customType === MODE_CONTEXT_TYPE &&
          textCarries(msg.content, MODE_MARKERS) &&
          !textCarries(msg.content, [current])
        );
      };
      // No stale flavor → no intervention (the hook stays a no-op for every other message).
      if (!event.messages.some(stale)) return;
      return { messages: event.messages.filter((m) => !stale(m)) };
    }
    return {
      messages: event.messages.filter((m) => {
        const msg = m as { customType?: string; role?: string; content?: unknown };
        if (msg.customType === MODE_CONTEXT_TYPE) return false;
        if (msg.role !== "user") return true;
        return !textCarries(msg.content, MODE_MARKERS);
      }),
    };
  });

  return {
    syncFromState(mode: string | undefined, stage: string | undefined): void {
      apply(isReadOnlyMode(mode), stage ?? null);
    },
    enter(_ctx?: ExtensionContext): void {
      pi.appendEntry(WORKFLOW_STATE_TYPE, { mode: "read-only" });
      apply(true, stageId);
    },
    exit(_ctx?: ExtensionContext): void {
      if (hasFloor()) {
        apply(true, stageId);
        return;
      }
      pi.appendEntry(WORKFLOW_STATE_TYPE, { mode: "read-write" });
      apply(false, stageId);
    },
    isActive,
  };
}
