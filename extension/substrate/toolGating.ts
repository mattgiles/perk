// The tool-gating primitive (the keystone). Structural read-only enforcement, NOT prompting. The
// gate attaches to the existing `perk:workflow-state.mode` field (`read-only`/`read-write`) — no
// new registry stage — and lives beside per-stage tool scoping keyed off the workflow-state
// `stage` field (contracts.md §8.40). Both concerns read the one eligibility formula
// (`toolPolicy.ts`); this module owns the controller, the mode-context injection and the
// `tool_call` backstop. The bash verdict lives in `readOnlyBash.ts`.
//
// Four terms, kept apart:
//  - ACTIVATION is own-names-only: at every reconciliation point perk installs
//    `reconcileTarget` — the live active set with perk's own names replaced by the eligible ones —
//    and never activates or deactivates a foreign tool. The one non-perk exception is a builtin
//    the gate suspends (codemode: hidden-but-active, its own hook would hide every direct tool),
//    switched off while presenting read-only and back on at release (`suspensionStep`). A session
//    whose live set needs no change and whose presented mode does not flip gets NO
//    `setActiveTools` call (a bare session — no stage, read-write, no floor, default registration
//    — gets none at all).
//  - PRESENTATION is the loadout host's (`perk_stage`, registered by index.ts through
//    `registerLoadoutHost`): its `prepareLoadout` hides every declared tool ineligible in the
//    landing (by provenance — `hiddenDeclarationsFor`), so the gate and the diet reach foreign
//    tools without touching their activation. Hidden tools stay active and callable; their
//    prompt snippets drop out of the request, their guidelines do not. Fail-open.
//  - ENFORCEMENT is the read-only `tool_call` backstop: under the gate, edit/write, an
//    unregistered name, an ineligible tool and an unsafe bash command are blocked. Fail-closed.
//  - THE DISCOVERY COHORT: a session whose host has Pi's builtin `tool_search` registered and
//    active at `session_start` joins it (index.ts: `deferDiscoveryFamily` re-registers the pilot
//    family deferred, then `joinDiscoveryCohort`). The next install deactivates the family once
//    (still ONE perk install at startup); thereafter a family member is kept exactly while it is
//    active and eligible (`reconcileTarget`'s third term, cohort-only). Priming
//    (`primeDeferred`) is the one perk-initiated activation of a deferred tool: a warm door or a
//    wave launcher activates the members its carrier names. Every other session is a
//    nonparticipant and keeps today's always-declared loadout. Resets: resume/fork start from the
//    host's defaults (a primed or searched member is gone); `/reload` re-runs the factory, which
//    re-joins and re-deactivates; `/tree` restores the transcript's loadout and perk keeps it.
//
// The reconciliation points: `syncFromState` (session_start, session_tree, the doors' stage
// syncs), `enter`, `exit`, the `resources_discover` re-apply (after every extension's
// session_start — late registrants), and `before_agent_start` (ahead of the mode-context
// injection; Pi emits it once when a prompt starts, so a tool activated during the previous
// prompt — a `tool_search` hit — meets the policy before the next prompt's first request; within
// a prompt only the host's per-request hiding applies). The presented mode LEADS each install:
// the host's hook runs inside
// the install, and Pi rebuilds the prompt's snippet map from that run, so a gate exit restores
// edit/write's snippets in the same install.
//
// The exclusion contract: Pi's `--tools`/`--exclude-tools` (the SDK's `tools`/`excludeTools`)
// are registry filters — a filtered-out perk tool is never registered and never installed; a
// filtered-out host means no presentation at all (enforcement is unchanged). Every other absence
// of a registered, eligible perk tool from the active set (a `defaultTools` preference, a foreign
// `setActiveTools`) is undone by the next reconciliation — perk's own activation is
// policy-owned. Composition limit: codemode builds its description from the unfiltered callable
// set, so in a read-write stage session it may name diet-hidden tools; under the gate codemode is
// suspended.
//
// Substrate only: the gate-ENTRY consumers are perk-owned plan mode (`pi/v1/plan.ts`: `/plan`,
// `--plan`, `Ctrl+Alt+P`), the warm `/objective-plan` factory (`pi/v1/objectivePlanning.ts`) and
// the warm `/objective-refine` entry (`pi/v1/objectiveRefinement.ts`); `exit` rides the plan-mode
// toggle and the save/exit doors. The CI executor (`pi/v1/delivery/ci.ts`) never touches the gate.

import type {
  ExtensionAPI,
  ExtensionContext,
  ToolLoadout,
  ToolLoadoutChanges,
} from "@earendil-works/pi-coding-agent";
import { render } from "./prompts.ts";
import { readOnlyBashVerdict } from "./readOnlyBash.ts";
import {
  carveOutWritersFor,
  discoveryFamily,
  hiddenDeclarationsFor,
  isEligible,
  isPerkTool,
  LOADOUT_HOST_NAME,
  type Mode,
  normalizeStage,
  type Provenance,
  reconcileTarget,
  sameNames,
  suspensionStep,
} from "./toolPolicy.ts";
import { branchCarries, branchOf, WORKFLOW_STATE_TYPE } from "./workflowState.ts";

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
  /** Enter read-only mode: persist `mode=read-only` + reconcile perk's tools. (Called by plan mode — `/plan`, `--plan`, `Ctrl+Alt+P` — the warm objective-plan factory and the warm objective-refine entry; never the CI executor.) */
  enter(ctx?: ExtensionContext): void;
  /** Exit read-only mode: persist `mode=read-write` + reconcile perk's tools. (Called by the plan-mode toggle and the save/exit doors.) */
  exit(ctx?: ExtensionContext): void;
  /** Whether the gate is currently active (in-memory source of truth for `tool_call`). */
  isActive(): boolean;
  /**
   * The loadout host's hook: hide every declared tool ineligible in the presented landing, plus
   * the host itself. Never throws — a failure hides only the host (presentation is fail-open; the
   * backstop still enforces).
   */
  prepareLoadout(loadout: ToolLoadout): ToolLoadoutChanges;
  /**
   * Join the discovery cohort with the family `deferDiscoveryFamily` re-registered deferred: the
   * next reconciliation removes those names from the live set once, as part of its one install.
   * Idempotent per activation (a second call is a no-op); installs nothing itself.
   */
  joinDiscoveryCohort(family: readonly string[]): void;
  /**
   * Primed activation: activate the deferred family members among `names` that are registered,
   * eligible in the presented landing and not yet active, in catalog order; returns them. A no-op
   * (`[]`, no install) outside the cohort. Never throws — a failure is reported and returns `[]`
   * (presentation is fail-open: the model can still `tool_search`; enforcement is untouched).
   */
  primeDeferred(names: readonly string[]): string[];
  /** The selfcheck read: whether this session joined the cohort, and the whole family if so. */
  discovery(): { cohort: boolean; family: readonly string[] };
}

function isReadOnlyMode(mode: string | undefined): boolean {
  return mode === "read-only";
}

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
  // The mode the loadout host presents. Leads every install (so the hook run inside the install
  // already sees it); on a failed install it falls back to the settled gate.
  let presentedMode: Mode = "read-write";
  // The builtins the gate switched off (codemode), restored when the presentation turns
  // read-write. Updated only after a successful install.
  let suspended: string[] = [];
  // Whether this activation joined the discovery cohort, and the family the next install must
  // deactivate once (cleared only after a successful install).
  let cohort = false;
  let pendingDeferral: string[] = [];

  function hasFloor(): boolean {
    try {
      return readOnlyFloor();
    } catch {
      // A broken restriction supplier cannot grant authority for this observation.
      return true;
    }
  }

  const isActive = () => active || hasFloor();

  /**
   * Reconcile perk's own tools for a (gate, stage) landing (contracts.md §8.40). The in-memory
   * gate latches ON before any fallible read (fail-closed) and is released only after a
   * successful install. The presented mode and stage lead the install; an install happens only
   * when perk's names must change or a suspended builtin must be switched off or back on — or
   * when the presented mode flips under an active host, so Pi rebuilds the prompt's snippet map
   * for the new presentation (a gate exit restores edit/write's snippets even when no perk name
   * changed).
   */
  function apply(nextActive: boolean, nextStage: string | null): void {
    if (nextActive) active = true;
    const effective = nextActive || hasFloor();
    const previousMode = presentedMode;
    stageId = nextStage;
    presentedMode = effective ? "read-only" : "read-write";
    try {
      const live = pi.getActiveTools();
      const infos = provenanceMap();
      const step = suspensionStep({ active: live, infos }, presentedMode, suspended);
      const deferring = new Set(pendingDeferral.filter(isPerkTool));
      const joined = step.active.filter((name) => !deferring.has(name));
      const target =
        reconcileTarget(
          { active: joined, registered: [...infos.keys()] },
          stageId,
          presentedMode,
          cohort,
        ) ?? joined;
      if (!sameNames(target, live)) pi.setActiveTools(target);
      else if (presentedMode !== previousMode && live.includes(LOADOUT_HOST_NAME)) {
        pi.setActiveTools(live);
      }
      suspended = step.suspended;
      pendingDeferral = [];
    } catch (error) {
      presentedMode = isActive() ? "read-only" : "read-write";
      throw error;
    }
    active = nextActive;
  }

  // Pi fires `resources_discover` after EVERY extension's `session_start` has run — the point
  // where startup-late registrants (pi-subagents' `subagent_supervisor`) meet the landing. A no-op
  // when nothing changed; a throw is Pi-reported and never opens the gate.
  pi.on("resources_discover", async () => {
    apply(active, stageId);
  });

  /** Every registered tool's provenance, by name. */
  function provenanceMap(): Map<string, Provenance> {
    return new Map(pi.getAllTools().map((t) => [t.name, t.sourceInfo] as const));
  }

  /** The registered tool's provenance, or undefined when the name is not registered here. */
  function registeredProvenance(name: string): Provenance | undefined {
    return pi.getAllTools().find((t) => t.name === name)?.sourceInfo;
  }

  // Enforce the whole policy even if presentation failed or a tool was activated between
  // reconciliations.
  pi.on("tool_call", async (event) => {
    try {
      if (!isActive()) return;
      if (event.toolName === "edit" || event.toolName === "write") {
        return {
          block: true,
          reason: `perk read-only mode: ${event.toolName} is blocked (file modifications disabled).`,
        };
      }
      // A name this session never registered is never callable here — a catalogued perk name
      // included (classification is by catalog, callability by the live registry).
      const provenance = registeredProvenance(event.toolName);
      if (provenance === undefined) {
        return {
          block: true,
          reason: `perk read-only mode: ${event.toolName} is blocked (tool not registered).`,
        };
      }
      if (!isEligible(event.toolName, provenance, stageId, "read-only")) {
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

  pi.on("before_agent_start", async (_event, ctx) => {
    // Reconcile as each prompt starts, gated or not: a tool activated since the last point (a
    // `tool_search` hit during the previous prompt) meets the landing before this prompt's first
    // request. Pi treats the live loadout as authoritative unless a later handler edits
    // `selectedTools` explicitly.
    try {
      apply(active, stageId);
    } catch (error) {
      console.error(`perk: tool reconciliation failed before the prompt — ${error}`);
    }
    // Inject the hidden read-only mode context while active (display:false → not in transcript).
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
    joinDiscoveryCohort(family: readonly string[]): void {
      if (cohort) return;
      cohort = true;
      pendingDeferral = [...family];
    },
    primeDeferred(names: readonly string[]): string[] {
      if (!cohort) return [];
      try {
        const wanted = new Set(names);
        const live = pi.getActiveTools();
        const registered = new Set(pi.getAllTools().map((t) => t.name));
        const targets = discoveryFamily().filter(
          (name) =>
            wanted.has(name) &&
            registered.has(name) &&
            isEligible(name, undefined, stageId, presentedMode) &&
            !live.includes(name),
        );
        if (targets.length > 0) pi.setActiveTools([...live, ...targets]);
        return targets;
      } catch (error) {
        console.error(`perk: priming failed — ${error}`);
        return [];
      }
    },
    discovery() {
      return { cohort, family: cohort ? discoveryFamily() : [] };
    },
    prepareLoadout(loadout: ToolLoadout): ToolLoadoutChanges {
      try {
        return {
          hiddenDeclarations: hiddenDeclarationsFor(
            loadout.declared.map((t) => t.name),
            provenanceMap(),
            stageId,
            presentedMode,
          ),
        };
      } catch (error) {
        console.error(`perk: loadout presentation failed — ${error}`);
        return { hiddenDeclarations: [LOADOUT_HOST_NAME] };
      }
    },
  };
}
