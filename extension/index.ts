// perk Pi extension — the session *interior*.
//
// The tier-3 session-state mechanics (contracts.md §8.2/§8.3): claim PERK_RUN_ID on
// `session_start` (verified-linkage), rebuild `perk:workflow-state` on `session_start` AND
// `session_tree` (per-field LWW), and derive a child run_id on fork.

import { existsSync, mkdirSync } from "node:fs";
import { basename, join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerAddress } from "./doors/address.ts";
import { registerAnnotationPushTool } from "./doors/annotationPush.ts";
import { registerAuditWave } from "./doors/auditWaveTools.ts";
import { registerCiExecutor } from "./doors/ciExecutor.ts";
import { registerCommitAndCompact } from "./doors/commitCompact.ts";
import { registerDraftReviewWaveTools } from "./doors/draftReviewWaveTools.ts";
import { registerDreamWave } from "./doors/dreamWaveTools.ts";
import { registerHarvestWave } from "./doors/harvestWaveTools.ts";
import { registerLand } from "./doors/land.ts";
import { registerLearn } from "./doors/learn.ts";
import { CODE_DOOR, DOCS_DOOR, registerLearnFactoryDoor } from "./doors/learnFactory.ts";
import { registerLifecycleGates } from "./doors/lifecycleGates.ts";
import {
  openObjectiveReviewSurface,
  registerObjectiveReviewBrowser,
} from "./doors/objectiveReviewBrowser.ts";
import { registerObjectiveStack } from "./doors/objectiveStack.ts";
import { plannotatorPresent } from "./doors/plannotatorHandoff.ts";
import { openPlanReviewSurface, registerPlanReviewBrowser } from "./doors/planReviewBrowser.ts";
import { registerPrReview } from "./doors/prReview.ts";
import { registerPrReviewBrowser } from "./doors/prReviewBrowser.ts";
import { registerPrReviewDynamic } from "./doors/prReviewDynamic.ts";
import { registerPrReviewTerminal } from "./doors/prReviewTerminal.ts";
import { registerReady } from "./doors/ready.ts";
import { registerReviewWaveTools } from "./doors/reviewWaveTools.ts";
import { registerSelfcheck } from "./doors/selfcheck.ts";
import { registerOpenStackReview, registerStackReviewBrowser } from "./doors/stackReviewBrowser.ts";
import { registerSubmit } from "./doors/submit.ts";
import { registerSubmitPrReview } from "./doors/submitPrReview.ts";
import { registerObjectiveAuthor } from "./factories/objectiveAuthor.ts";
import { registerObjectiveDraft } from "./factories/objectiveDraft.ts";
import { registerObjectivePlan } from "./factories/objectivePlan.ts";
import { registerObjectiveSave } from "./factories/objectiveSave.ts";
import { createHunkFeedbackReceiver } from "./hunkFeedback/receiver.ts";
import { installGistBindings } from "./pi/v1/gist.ts";
import { installObjectiveBindings } from "./pi/v1/objective.ts";
import { installPlanBindings } from "./pi/v1/plan.ts";
import { installPlannotatorPlanAdapter } from "./pi/v1/providers/plannotator.ts";
import { installTombellPlanAdapter } from "./pi/v1/providers/tombell.ts";
import {
  branchSessionStateStore,
  establishSessionIdentity,
  resolveRunStage,
} from "./session/lifecycle.ts";
import { createAgentScratchProvisioner, registerAgentScratch } from "./substrate/agentScratch.ts";
import { registerBindingDelivery } from "./substrate/bindingDelivery.ts";
import {
  atomicWriteFileSync,
  ensureRunScratch,
  markHandoffConsumed,
  readHandoff,
  readPlanRef,
  setMarker,
  workflowDir,
} from "./substrate/cache.ts";
import { loadRegistry, type Registry, stageConsumesPlanRef } from "./substrate/registry.ts";
import { perkVersion, sharedDir, versionStamp } from "./substrate/resources.ts";
import { mintRunId } from "./substrate/runId.ts";
import { captureSessionPointer } from "./substrate/sessionPointers.ts";
import { registerToolGating } from "./substrate/toolGating.ts";
import {
  appendWorkflowState,
  branchOf,
  planRefsEqual,
  rebuildWorkflowState,
  WORKFLOW_STATE_TYPE,
  type WorkflowState,
} from "./substrate/workflowState.ts";
import { isPerkFooterReferenceSelected } from "./surfaces/footerProvider.ts";
import { report } from "./surfaces/report.ts";
import {
  createPerkStatus,
  installPerkFooter,
  latestCacheHitRate,
  REPORT_DETAIL_TYPE,
  registerTranscriptRenderer,
  reportDetailEntryRenderer,
  workflowStateEntryRenderer,
} from "./surfaces/surfaces.ts";
import { registerBtw } from "./vendor/btw/btw.ts";
import { registerWhimsical } from "./vendor/whimsical/whimsical.ts";

// Cross-plane proof marker (TS writes via cache.ts; the Python helper reads it — gate check 3).
const T3_MARKER = "t3-extension-cache-write";

function writeT3Sentinel(
  cwd: string,
  source: string,
  state: WorkflowState,
  runMode: string | null,
): void {
  try {
    const dir = workflowDir(cwd);
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
    atomicWriteFileSync(
      join(dir, ".perk-t3.json"),
      `${JSON.stringify({
        source,
        // The launch *workflow* mode (read-only/read-write) — drives tool gating.
        run_id: state.run_id ?? null,
        mode: state.mode ?? null,
        // The Pi *run* mode (tui/rpc/json/print) — observability `hasUI` can't express. Distinct
        // from the workflow `mode` above; recorded straight from `ctx.mode`.
        run_mode: runMode,
        predecessor: state.predecessor ?? null,
        pi_session_id: state.pi_session_id ?? null,
        active_plan_ref: state.active_plan_ref ?? null,
      })}\n`,
    );
  } catch {
    // never throw from a probe
  }
}

export default function (pi: ExtensionAPI) {
  const version = perkVersion();

  // The read-only tool-gating primitive. Attaches to perk:workflow-state.mode; synced on
  // both session_start AND session_tree below. enter/exit are the surface the gated stages consume.
  const gating = registerToolGating(pi);

  // Run-owned disposable scratch guidance for every eligible write-capable model turn. One
  // activation-scoped provisioner shares retry/warning suppression with the isolated /btw side
  // session; no model tool or process-global temp environment is introduced.
  const agentScratch = createAgentScratchProvisioner();
  registerAgentScratch(pi, agentScratch);

  // Vendored `btw`: a `/btw` human-only side-chat popover backed by an isolated in-memory
  // AgentSession. Takes `gating` for the gate-mirror — its side-session toolset + cache key follow
  // perk's read-only gate (`sideSessionTools`), so the isolated session never bypasses the read-only
  // guarantee. Its `ctx.ui.custom` overlay is the ONE sanctioned charter exception (§6 D6): human-
  // invoked only, `hasUI`-gated, no model tool, not a stage/door — never machine-reachable.
  registerBtw(pi, gating, agentScratch);

  // Vendored `whimsical`: flavors pi's default working-message label with a random phrase per
  // turn, via the headless-no-op `setWorkingMessage` surfaces seam. Always on, no config toggle.
  registerWhimsical(pi);

  // The v1 plan installer: perk-owned plan mode (the `/plan` + Ctrl+Alt+P + `--plan` toggle
  // surface over the read-only gate, plus the plan-authoring context injection — this call
  // sits at the frozen hooks-ordering slot the mode surface always held), the
  // `plan_draft`/`plan_save` tools, the `/plan-save` + `/implement-here` commands, and
  // `plan_review` — perk's UNIVERSAL review door (plannotator-selected → the event-bus bridge;
  // ANY other selection → the first-party in-TUI editor review). Takes `gating` to toggle plan
  // mode and to COMPOSE the approval→save seam (auto-save → D1a gate exit) — Invariant 1 holds:
  // the surfaces compose the gate through the seams, never own it. The injected wave-launch
  // deps power the plannotator launch chooser (§8.23): the presence probe + the two door open
  // cores are composed HERE so the pi/v1 review arms import nothing from door modules (the
  // value-import cycle break — planReviewBrowser.ts value-imports the review arms).
  installPlanBindings(pi, gating, {
    present: () => plannotatorPresent(pi),
    plan: (ctx, opts) => openPlanReviewSurface(pi, ctx, gating, opts),
    objective: (ctx, opts) => openObjectiveReviewSurface(pi, ctx, gating, opts),
  });

  // The first 3rd-party plan adapter: a perk-owned, injection-only bridge that re-enables
  // `@tombell/pi-plan` as a real plan provider. Always registered, but INERT unless
  // `[providers] plan = "tombell-plan"`; it directs the foreign free-form prose `/plan` surface into
  // perk's canonical `plan_save` → `cache.plan-ref` contract. It needs no `gating` (Invariant 1: the
  // read-only gate stays perk's, engaged by the cold-door launch — the shim never arbitrates tools).
  installTombellPlanAdapter(pi);

  // The second 3rd-party plan adapter — AUGMENT posture: `@plannotator/pi-extension` contributes
  // its browser plan-review UI while perk's plan surface + gate stay (the plan installer skips
  // only `--plan`/`Ctrl+Alt+P` under this selection). Always registered, but INERT unless
  // `[providers] plan = "plannotator-plan"`. Injection-only — the `plan_review` tool lives in
  // the plan installer (above), which dispatches to this adapter's event-bus bridge when
  // plannotator is selected.
  installPlannotatorPlanAdapter(pi);

  // Objective-author context injection (the objective mirror of plan mode's authoring
  // half). Keyed off (read-only gate AND stage === objective-author); planMode defers to it.
  registerObjectiveAuthor(pi, gating);

  // The v1 gist installer: the gist-authoring context hook pair (this call sits at the frozen
  // hooks-ordering slot the injection always held; planMode defers to it too), plus the
  // `gist_draft`/`gist_save` tools and the `/gist-save` command (registration is name-keyed —
  // only the hooks ordering is frozen).
  installGistBindings(pi, gating);
  let sharedOk = false;
  try {
    sharedDir();
    sharedOk = true;
  } catch {
    sharedOk = false;
  }

  let registry: Registry | null = null;
  let registryStages = -1;
  try {
    registry = loadRegistry();
    registryStages = registry.stages.length;
  } catch {
    registry = null;
    registryStages = -1;
  }
  const registryOk = registryStages > 0;

  // The single-value `perk` status handle (charter D2): one slot carrying the objective
  // segment. Created once here (no hidden module state) and threaded into the objective
  // publisher below; the footer reads it back via get/subscribe.
  const perkStatus = createPerkStatus();

  // The generic full report-detail entry and the `perk:workflow-state` transition marker. Renderer
  // bodies live in surfaces.ts; registration is wiring through the pre-0.80.4-safe seam. The report
  // family is appended by command-attached sinks; one workflow registration covers every appender.
  registerTranscriptRenderer(pi, REPORT_DETAIL_TYPE, reportDetailEntryRenderer);
  registerTranscriptRenderer(pi, WORKFLOW_STATE_TYPE, workflowStateEntryRenderer);

  // The hunk watch feedback receiver controller (contracts §8.58) — factory-scoped (no module
  // globals). Synced from session_start/session_tree below; closed on session_shutdown so the
  // consumer lease releases with the session. A stale /reload predecessor instance is retired
  // by the lease fencing (fresh token per same-identity reacquire + verify-before-inject).
  const feedbackReceiver = createHunkFeedbackReceiver(pi);
  pi.on("session_shutdown", async () => {
    feedbackReceiver.close();
  });

  pi.on("session_start", async (_event, ctx) => {
    const branchEntries = () => branchOf(ctx);
    const sessionFile = ctx.sessionManager.getSessionFile();
    const currentSessionId = sessionFile ? basename(sessionFile) : null;

    // Terminal-safe linkage failure: managed headline when headful, complete stderr when headless
    // (plus the explicit RPC mirror); non-fatal and leaves the run unclaimed.
    const reportError = (message: string) => {
      report(ctx, "workflow-state linkage error", "error", message, { alsoLog: true });
    };

    // The session-audit exact-vintage stamp (§8.3), recorded by every run-identity arm
    // (claim/fork/adopt/mint); undefined on the perkVersion() failure sentinel, which drops the
    // key on serialize and leaves the session on the timestamp-estimate arm.
    const stamp = versionStamp(version);

    // The identity lifecycle (claim / fork / adopt / mint / keep) is the named session
    // operation (session/lifecycle.ts owns the arms); this handler binds the production ports
    // and renders the outcome's per-arm problems/warnings with the exact report scopes the
    // arms always used. The strict appends keep reporting read-back failures through the
    // strict-append seam's own loudness channel.
    const identity = establishSessionIdentity(
      branchSessionStateStore(pi, ctx),
      {
        readHandoff: (runId) => readHandoff(ctx.cwd, runId),
        markHandoffConsumed: (runId, opts) => markHandoffConsumed(ctx.cwd, runId, opts),
        ensureRunScratch: (runId) => ensureRunScratch(ctx.cwd, runId),
        mintRunId,
        versionStamp: stamp,
      },
      { currentSessionId, envRunId: process.env.PERK_RUN_ID ?? null, cwd: ctx.cwd },
    );
    for (const problem of identity.problems) reportError(problem);
    for (const warning of identity.warnings) {
      report(ctx, "run scratch", "warning", warning, { alsoLog: true });
    }
    const decision = identity.decision;
    const minted = identity.arm === "minted";
    let resolved: WorkflowState = identity.resolved;

    // Reapply the read-only allowlist + stage scoping from the resolved mode/stage — FIRST,
    // before the plan-ref/stage reconciliation below. `resolved.mode` is final once the
    // claim/fork/none arms settle (the later blocks only touch `active_plan_ref` / capture
    // pointers), and ordering the sync ahead of them guarantees no cache read or reconciliation
    // failure can leave the gate unsynced (defense in depth on top of the total cache readers).
    // The scope stage is the workflow-state `stage` key (§8.40): claim → the handoff-recorded
    // stage just appended; keep/none → the branch-LWW stage; fork INHERITS the parent's stage (a
    // forked implement session is an implement session); adopt NEVER impersonates (subagent
    // children stay unscoped — their fresh branch carries no stage, so session_tree agrees). A
    // failed claim leaves `resolved` empty → no stage → unscoped (stage scoping is fail-open).
    // Fail-closed on the gate: if the sync throws, leave it as-is (a failed sync never opens it).
    const scopeStage =
      decision.action === "adopt"
        ? undefined
        : (resolved.stage ?? (decision.action === "fork" ? decision.state.stage : undefined));
    try {
      gating.syncFromState(resolved.mode, scopeStage);
    } catch (error) {
      console.error(`perk: tool-gating sync failed on session_start — ${error}`);
    }

    // Plan-ref linkage (stage-gated): reconcile the cache.plan-ref file into
    // active_plan_ref — but ONLY when the launched stage *consumes* the ref (its registry
    // `requires`/`reads` list `cache.plan-ref`). That is the worktree binding stages
    // (implement/submit/address/land/learn); the root `worktree: none` stages
    // (plan/objective-plan/save) must NOT inherit the root *selector* into a fresh planning
    // session. Idempotent by (provider, pr_id), strict read-back, headless-safe. Runs after the
    // run_id claim so the run is settled first; the two append independent LWW fields.
    // Reload/fork/tree (no launched stage) rely on the LWW rebuild — never re-read the file.
    const linked = rebuildWorkflowState(branchEntries()).active_plan_ref ?? null;
    const runStage = resolveRunStage(decision, ctx.cwd);
    // Registry-missing is permissive when a stage is present, to preserve implement linkage.
    const consumesPlanRef =
      runStage !== null && (registry === null || stageConsumesPlanRef(registry, runStage));
    if (consumesPlanRef) {
      const cachedRef = readPlanRef(ctx.cwd);
      if (cachedRef !== null) {
        if (planRefsEqual(linked, cachedRef)) {
          resolved = { ...resolved, active_plan_ref: linked };
        } else {
          if (
            appendWorkflowState(pi, ctx, {
              data: { active_plan_ref: cachedRef },
              field: "active_plan_ref",
              expected: cachedRef,
              scope: "workflow-state linkage error",
              failure: `plan-ref read-back failed for ${cachedRef.provider}:${cachedRef.pr_id}`,
              equals: planRefsEqual,
            })
          ) {
            resolved = { ...resolved, active_plan_ref: cachedRef };
          }
        }
      } else if (linked !== null) {
        resolved = { ...resolved, active_plan_ref: linked };
      }
    } else if (linked !== null) {
      // Non-consuming stage (or no launched stage): preserve any already-linked ref via LWW,
      // but NEVER read the cache file — the root selector must not leak in.
      resolved = { ...resolved, active_plan_ref: linked };
    }

    // Implementation session pointer (contracts.md §8.35): an implement session self-keys its own
    // session file into the shared main checkout so a later/other session resolves it cross-run.
    // The headless worker's inner session lands here too (.main); runStage records the matching
    // .worker. A forked implement session inherits the parent's launched stage + threads the
    // inherited parent session id as fork provenance. Best-effort + non-fatal (carrier warns).
    // First-write-wins (`preserveForeign`): this is the corroborated shadowing defect site — the
    // claimer's original capture stays authoritative, and any future shadow vector warns loudly
    // instead of silently corrupting /learn evidence.
    const implStage =
      runStage ?? (decision.action === "fork" ? (decision.state.stage ?? null) : null);
    if (resolved.run_id && implStage === "implement") {
      captureSessionPointer({
        cwd: ctx.cwd,
        runId: resolved.run_id,
        klass: "implementation",
        site: "main",
        sessionFile,
        parentSessionId: decision.action === "fork" ? (decision.state.pi_session_id ?? null) : null,
        preserveForeign: true,
      });
    }

    // The hunk watch feedback receiver (§8.58): sync strictly AFTER the run-identity claim and
    // the plan-ref reconciliation above, so an unclaimed or mislinked session never touches the
    // outbox. Eligibility (interactive TUI + implement stage + non-adopted + settled identity +
    // plan-ref match against one fresh cache read) is evaluated inside sync; every ineligible
    // shape closes any open inbox. Never throws (the controller contains its own failures).
    feedbackReceiver.sync(ctx, {
      stage: implStage,
      adopted: decision.action === "adopt",
      runId: resolved.run_id ?? null,
      piSessionId: currentSessionId,
      activePlanRef: resolved.active_plan_ref ?? null,
      mode: ctx.mode ?? null,
    });

    // Soft version-parity drift signal: pi can lazy-install / load a stale `npm:@mgiles/perk`, so the
    // extension actually running may differ from the `perk` CLI that launched it. The local launch
    // seam injects PERK_CLI_VERSION; compare it against this extension's own `perkVersion()`. Soft +
    // non-fatal (warning), headless-safe via report(). No once-guard — may re-emit on reload, fine
    // for a soft warning. Silent for ad-hoc `pi` (no env) and the self-repo (versions equal).
    const cliVersion = (process.env.PERK_CLI_VERSION ?? "").trim();
    if (cliVersion && version && cliVersion !== version) {
      report(
        ctx,
        "version parity",
        "warning",
        `the loaded @mgiles/perk extension (v${version}) differs from the running perk CLI ` +
          `(v${cliVersion}) — run 'perk doctor --fix' to reinstall the pinned version`,
        { alsoLog: true },
      );
    }

    // Charter D7: perk identity is standing footer state, not a transition — the
    // `v<version> loaded` toast (and its headless stderr mirror) is retired. D5 is rescinded:
    // perk keeps pi's default working indicator (no setWorkingIndicator call anywhere).
    // Install on EVERY headful session_start: pi ≥ 0.84's `setExtensionFooter` explicitly
    // disposes a replaced footer factory (verified at 0.84.1), and `resetExtensionUI` restores
    // the built-in footer on /reload and before session replacement — both paths also re-run
    // this extension factory, so repeated installs leak nothing and each install's deps
    // closures capture the current event's ctx.
    // Footer-seam install-site vacating: under a foreign `[providers] footer` selection perk does
    // NOT install its own footer, leaving the foreign footer (`pi-powerline-footer` / `pi-bar`) as
    // the sole footer surface. perk's objective progress still reaches it via the
    // single-value `perk` setStatus slot. Fail-safe: any config-read error resolves to install.
    if (ctx.hasUI && isPerkFooterReferenceSelected(ctx.cwd)) {
      installPerkFooter(ctx, {
        identity: `perk v${version}`,
        status: perkStatus,
        getModelId: () => ctx.model?.id ?? null,
        getThinkingLevel: () => (ctx.model ? pi.getThinkingLevel() : null),
        getCacheHitRate: () => latestCacheHitRate(ctx.sessionManager.getEntries()),
        getContext: () => {
          const usage = ctx.getContextUsage();
          return usage ? { percent: usage.percent, contextWindow: usage.contextWindow } : null;
        },
      });
    }

    if (process.env.PERK_SELFCHECK) {
      try {
        const dir = workflowDir(ctx.cwd);
        if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
        // The gate sentinel (unchanged — those gates parse this line).
        atomicWriteFileSync(
          join(dir, ".perk-loaded"),
          `perk ${version} loaded; shared=${sharedOk ? "ok" : "miss"}; ` +
            `registry=${registryOk ? "ok" : "miss"} stages=${registryStages}; hasUI=${ctx.hasUI}\n`,
        );
        writeT3Sentinel(ctx.cwd, minted ? "mint" : decision.source, resolved, ctx.mode ?? null);
        setMarker(ctx.cwd, T3_MARKER); // cross-plane cache write (gate check 3)
      } catch {
        // never throw from a load probe
      }
    }
  });

  // Non-negotiable: rebuild on branch navigation too, or state goes stale after /tree (§8.3).
  pi.on("session_tree", async (_event, ctx) => {
    const state = rebuildWorkflowState(branchOf(ctx));
    // Non-negotiable: re-sync the gate + stage scoping on tree navigation too (mode and stage are
    // per-field LWW — the branch-rebuilt stage is the §8.40 key). Fail-closed on the gate.
    try {
      gating.syncFromState(state.mode, state.stage);
    } catch (error) {
      console.error(`perk: tool-gating sync failed on session_tree — ${error}`);
    }
    // Re-sync the feedback receiver from the LWW-rebuilt state (§8.58). `adopted: false` is
    // right here: an env-adopted child's fresh branch carries no stage, so the stage gate
    // alone keeps it inert on tree navigation.
    feedbackReceiver.sync(ctx, {
      stage: state.stage ?? null,
      adopted: false,
      runId: state.run_id ?? null,
      piSessionId: state.pi_session_id ?? null,
      activePlanRef: state.active_plan_ref ?? null,
      mode: ctx.mode ?? null,
    });
    if (process.env.PERK_SELFCHECK) {
      writeT3Sentinel(ctx.cwd, "tree", state, ctx.mode ?? null);
    }
  });

  // The `objective_draft` working-objective file tool (the plan_draft twin).
  registerObjectiveDraft(pi);

  // Lifecycle gates: the dirty-repo switch/fork guard + the guard-only `/implement`.
  registerLifecycleGates(pi);

  // Warm door: the `submit` tool + `/submit` command.
  registerSubmit(pi);

  // The warm `ready` door: the deliberate draft→ready review gate (submit keeps draft).
  // Takes `gating`: the warm ready→reconcile continuation refuses (loudly) to drive the
  // ready-time pass into a read-only session (contracts.md §8.66).
  registerReady(pi, gating);

  // Warm doors: `land` merges + sets pending-learn; `learn` clears it (TS-only).
  registerLand(pi);
  registerLearn(pi);

  // The warm stacked-delivery surface (§8.51): `/objective-stack` (read) +
  // `/objective-sync`/`/objective-recover` (drives) + the four typed stack tools. Takes
  // `gating` for the driving commands' gate-on soft refusal (stack sync/recovery mutates
  // published branches; the stack tools never join READ_ONLY_TOOLS).
  registerObjectiveStack(pi, gating);

  // The warm `/address` review loop: the submit-then-resolve `finalize_address` tool + `/address`
  // command. Classify-then-act (the verbose feedback fetch + classification runs in an isolated
  // spawned child; the parent fixes actionable items and finalizes the committed repairs).
  registerAddress(pi);

  // The warm `/pr-review` door: automated code review in a FRESH, isolated subagent that
  // POSTS its review to the PR (the deliberate departure from /address's read-only-child rule).
  registerPrReview(pi);

  // The EXPERIMENTAL warm `/pr-review-dynamic` door: the selector-driven sibling — angle
  // selection delegated to a fresh perk.review-angle-selector lane, normalized in
  // module-rendered code; posting shares /pr-review's post_pr_review + clean guard. The
  // baseline /pr-review stays canonical; promotion/retire is a later dogfood's call.
  registerPrReviewDynamic(pi);

  // The warm `submit_pr_review` tool: the human-gated curated-posting surface both review
  // doors ride (contracts §8.4) — neither door registers tools of its own.
  registerSubmitPrReview(pi);

  // The flow-scoped review-wave pair (`start_review_wave`/`collect_review_wave`) both human
  // review doors drive: non-blocking adversarial-review launch + the typed collect, flow-scoped
  // via the session's pending-wave guard.
  registerReviewWaveTools(pi);
  registerAuditWave(pi);
  registerHarvestWave(pi);
  registerDreamWave(pi);

  // The flow-scoped draft-review-wave pair (`start_draft_review_wave`/
  // `collect_draft_review_wave`) the draft-review door drives: non-blocking draft-review
  // launch over the door-primed context + the typed collect.
  registerDraftReviewWaveTools(pi);

  // The door-primed browser annotation tool (`push_annotations`): the browser door primes the
  // surface handle on open and clears it on settle/degrade — the tool refuses outside a
  // door-opened flow.
  registerAnnotationPushTool(pi);

  // The warm `/pr-review-terminal` door: the terminal review entry — hunk always, no provider
  // dispatch (the command IS the selection); posting rides `submit_pr_review` above.
  registerPrReviewTerminal(pi);

  // The warm `/pr-review-browser` door: the browser review entry — plannotator always, opened
  // in the background (pre-PR it absorbs the since-base local browser review); posting is the
  // human's own platform-post from the UI, with `submit_pr_review` for request-changes only.
  registerPrReviewBrowser(pi);

  // The warm `/stack-review-browser` door + its cold-launch twin (`open_stack_review`): the
  // stacked-PR browser review over the combined base→top diff — one reviewer wave with
  // `stack: true`, then judgment-routed per-PR posting through `submit_pr_review`.
  registerStackReviewBrowser(pi);
  registerOpenStackReview(pi);

  // The warm `/plan-review-browser` door: the summonable streaming draft review — the
  // plannotator plan-review browser on the working plan draft, draft reviewers streaming
  // phrase-anchored findings in; APPROVE auto-saves via the approvalSave seam, DENY returns a
  // model-mediated revision round.
  registerPlanReviewBrowser(pi, gating);

  // The warm `/objective-review-browser` door: the summonable streaming objective-draft review
  // — the plannotator plan-review browser on the RENDERED working objective draft, draft
  // reviewers streaming phrase-anchored findings in; APPROVE auto-saves via the
  // objectiveApprovalSave seam, Direct Edits = a model-mediated revise round (never auto-saved).
  registerObjectiveReviewBrowser(pi, gating);

  // The read-only CI executor: the `run_ci` tool + `/ci` command + `--allow-project-ci`
  // flag. Runs the project's `[ci]` named checks deterministically and reports (never fixes/loops).
  registerCiExecutor(pi);

  // The objective substrate: `/objective` set/clear, budget accounting, threshold
  // compaction, all keyed off the now-live `active_objective`. Inert when no objective is active.
  // (The deterministic objective mechanics live in the Python plane: `perk objective …`.)
  installObjectiveBindings(pi, perkStatus);

  // The warm `/commit-and-compact` utility door: drive a commit of the work so far, compact once
  // a successful outcome is known, then completion-gate an automatic evidence-first continuation
  // (clean/read-only trees compact immediately; no commit → no compaction or continuation).
  // Human-only — no tool twin.
  registerCommitAndCompact(pi, gating);

  // The warm `objective_save` door: the `objective_save` tool + `/objective-save` command
  // (the objective mirror of plan-save). Takes `gating` for the read-only → read-write boundary.
  registerObjectiveSave(pi, gating);

  // The objective plan factory's warm transition surface: the `objective_node` bounded
  // tool (delegates to the Python cold door; `status:"done"` requires a completion audit) + the
  // `/objective-plan` command (select the next node and author a bounded plan). The command now
  // enters the read-only gate on invocation (parity with the cold door's `mode: read-only`
  // handoff; exit stays with plan_save / `/plan` off) — hence `gating`.
  registerObjectivePlan(pi, gating);

  // The learned-docs plan factory's warm surface: the `/learn-docs` command gathers open
  // perk:learn issues into an inbox (via the `perk learn docs --gather` cold door) and injects the
  // factory guidance so the model authors a docs/learned consolidation plan (no model tool).
  registerLearnFactoryDoor(pi, DOCS_DOOR);

  // The learn-code plan factory's warm surface: the `/learn-code` command gathers pre-stamped
  // SHOULD_BE_CODE perk:learn issues into an inbox (via the `perk learn code --gather` cold door)
  // and injects the factory guidance so the model authors a code-routing plan (no model tool).
  registerLearnFactoryDoor(pi, CODE_DOOR);

  // Warm-door skill-binding delivery: Mechanism A's `before_agent_start` injection of
  // the launched stage's user-originated bindings (+ the stale-context strip). Mechanism B (the
  // `command:<id>` suffix) is wired into the `/objective-reconcile` + `/learn-docs` +
  // `/learn-code` guidance.
  registerBindingDelivery(pi);

  // `/perk-selfcheck` — the session-wiring verifier (turned from a liveness ping into a real check
  // that the converged ambient index reached `appendSystemPrompt` and the managed `AGENTS.md` block
  // reached `contextFiles`). doctor checks disk; selfcheck checks the prompt.
  registerSelfcheck(pi, { version, sharedOk });
}
