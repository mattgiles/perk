// perk Pi extension — the session *interior*.
//
// The tier-3 session-state mechanics (contracts.md §8.2/§8.3): claim PERK_RUN_ID on
// `session_start` (verified-linkage), rebuild `perk:workflow-state` on `session_start` AND
// `session_tree` (per-field LWW), and derive a child run_id on fork.

import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerPlanAdapterPlannotator } from "./adapters/planAdapterPlannotator.ts";
import { registerPlanAdapterTombell } from "./adapters/planAdapterTombell.ts";
import { registerTodoAdapterJuicesharp } from "./adapters/todoAdapterJuicesharp.ts";
import { registerCheckpoints } from "./checkpoints/checkpoints.ts";
import { registerAddress } from "./doors/address.ts";
import { registerAskUser } from "./doors/askUser.ts";
import { registerCiExecutor } from "./doors/ciExecutor.ts";
import { registerCommitAndCompact } from "./doors/commitCompact.ts";
import { registerLand } from "./doors/land.ts";
import { registerLearn } from "./doors/learn.ts";
import { CODE_DOOR, DOCS_DOOR, registerLearnFactoryDoor } from "./doors/learnFactory.ts";
import { registerLifecycleGates } from "./doors/lifecycleGates.ts";
import { registerPrReview } from "./doors/prReview.ts";
import { registerPrReviewBrowser } from "./doors/prReviewBrowser.ts";
import { registerPrReviewDynamic } from "./doors/prReviewDynamic.ts";
import { registerPrReviewTerminal } from "./doors/prReviewTerminal.ts";
import { registerReady } from "./doors/ready.ts";
import { registerSelfcheck } from "./doors/selfcheck.ts";
import { registerSubmit } from "./doors/submit.ts";
import { registerSubmitPrReview } from "./doors/submitPrReview.ts";
import { registerGistAuthor } from "./factories/gistAuthor.ts";
import { registerGistDraft } from "./factories/gistDraft.ts";
import { registerGistSave } from "./factories/gistSave.ts";
import { registerImplementHere } from "./factories/implementHere.ts";
import { registerObjective } from "./factories/objective.ts";
import { registerObjectiveAuthor } from "./factories/objectiveAuthor.ts";
import { registerObjectiveDraft } from "./factories/objectiveDraft.ts";
import { registerObjectivePlan } from "./factories/objectivePlan.ts";
import { registerObjectiveSave } from "./factories/objectiveSave.ts";
import { registerPlanDraft } from "./factories/planDraft.ts";
import { registerPlanMode } from "./factories/planMode.ts";
import { registerPlanReview } from "./factories/planReview.ts";
import { registerPlanSave } from "./factories/planSave.ts";
import { registerBindingDelivery } from "./substrate/bindingDelivery.ts";
import {
  ensureRunScratch,
  markHandoffConsumed,
  readHandoff,
  readPlanRef,
  setMarker,
  workflowDir,
} from "./substrate/cache.ts";
import { loadRegistry, type Registry, stageConsumesPlanRef } from "./substrate/registry.ts";
import { perkVersion, sharedDir } from "./substrate/resources.ts";
import { mintRunId } from "./substrate/runId.ts";
import { captureSessionPointer } from "./substrate/sessionPointers.ts";
import { registerToolGating } from "./substrate/toolGating.ts";
import {
  appendWorkflowState,
  branchOf,
  decideClaim,
  planRefsEqual,
  rebuildWorkflowState,
  resolveRunStage,
  WORKFLOW_STATE_TYPE,
  type WorkflowState,
} from "./substrate/workflowState.ts";
import { isPerkFooterReferenceSelected } from "./surfaces/footerProvider.ts";
import { report } from "./surfaces/report.ts";
import {
  createPerkStatus,
  installPerkFooter,
  latestCacheHitRate,
  registerTranscriptRenderer,
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
    writeFileSync(
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
      "utf8",
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

  // Vendored `btw`: a `/btw` human-only side-chat popover backed by an isolated in-memory
  // AgentSession. Takes `gating` for the gate-mirror — its side-session toolset + cache key follow
  // perk's read-only gate (`sideSessionTools`), so the isolated session never bypasses the read-only
  // guarantee. Its `ctx.ui.custom` overlay is the ONE sanctioned charter exception (§6 D6): human-
  // invoked only, `hasUI`-gated, no model tool, not a stage/door — never machine-reachable.
  registerBtw(pi, gating);

  // Vendored `whimsical`: flavors pi's default working-message label with a random phrase per
  // turn, via the headless-no-op `setWorkingMessage` surfaces seam. Always on, no config toggle.
  registerWhimsical(pi);

  // perk-owned plan mode: the `/plan` + Ctrl+Alt+P + `--plan` toggle surface over the
  // read-only gate, plus the plan-authoring context injection. perk owns plan mode end-to-end now (the
  // borrowed `@tombell/pi-plan` is retired).
  registerPlanMode(pi, gating);

  // The first 3rd-party plan adapter: a perk-owned, injection-only bridge that re-enables
  // `@tombell/pi-plan` as a real plan provider. Always registered, but INERT unless
  // `[providers] plan = "tombell-plan"`; it directs the foreign free-form prose `/plan` surface into
  // perk's canonical `plan_save` → `cache.plan-ref` contract. It needs no `gating` (Invariant 1: the
  // read-only gate stays perk's, engaged by the cold-door launch — the shim never arbitrates tools).
  registerPlanAdapterTombell(pi);

  // The second 3rd-party plan adapter — AUGMENT posture: `@plannotator/pi-extension` contributes
  // its browser plan-review UI while perk's plan surface + gate stay (planMode skips only
  // `--plan`/`Ctrl+Alt+P` under this selection). Always registered, but INERT unless
  // `[providers] plan = "plannotator-plan"`. Injection-only — the `plan_review`
  // tool moved to planReview.ts (below), which dispatches to this adapter's event-bus bridge
  // when plannotator is selected.
  registerPlanAdapterPlannotator(pi);

  // `plan_review`, perk's UNIVERSAL review door: plannotator-selected → the event-bus
  // bridge; ANY other selection → the first-party in-TUI editor review. It takes `gating` only to
  // COMPOSE the approvalSave seam on an APPROVED review (auto-save → D1a gate exit) — Invariant 1
  // holds: the door composes the gate through the seam, never owns it.
  registerPlanReview(pi, gating);

  // Objective-author context injection (the objective mirror of plan mode's authoring
  // half). Keyed off (read-only gate AND stage === objective-author); planMode defers to it.
  registerObjectiveAuthor(pi, gating);

  // Gist-author context injection (the gist mirror). Keyed off (read-only gate AND
  // stage === gist-author); planMode defers to it too.
  registerGistAuthor(pi, gating);
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

  // The composed `perk` status handle (charter D2): one slot, ordered objective →
  // checkpoints segments. Created once here (no hidden module state) and threaded into the two
  // segment publishers below; the footer reads it back via get/subscribe.
  const perkStatus = createPerkStatus();

  // Install the perk-owned footer once per session (charter D2/D7). Once-only: pi's
  // dispose contract for a REPLACED footer factory is unverified, so re-installing on every
  // session_start (reload) could leak the previous handle subscription.
  let footerInstalled = false;

  // Transcript marker for `perk:workflow-state` deltas (audit §2.3): the renderer body lives in
  // surfaces.ts, this registration is wiring, and the seam carries the typeof feature-detect
  // (pre-0.80.4 hosts stay inert). One registration covers every workflow-state appender.
  registerTranscriptRenderer(pi, WORKFLOW_STATE_TYPE, workflowStateEntryRenderer);

  pi.on("session_start", async (_event, ctx) => {
    const branchEntries = () => branchOf(ctx);
    const sessionFile = ctx.sessionManager.getSessionFile();
    const currentSessionId = sessionFile ? basename(sessionFile) : null;

    // Headless-safe linkage failure: loud (notify if UI + stderr), non-fatal, leaves unclaimed.
    const reportError = (message: string) => {
      report(ctx, "workflow-state linkage error", "error", message, { alsoLog: true });
    };

    const decision = decideClaim({
      state: rebuildWorkflowState(branchEntries()),
      currentSessionId,
      envRunId: process.env.PERK_RUN_ID ?? null,
      cwd: ctx.cwd,
    });

    // `claim`/`adopt` carry no prior branch state (adopt's is written by its arm below).
    let resolved: WorkflowState =
      decision.action === "claim" || decision.action === "adopt" ? {} : decision.state;
    let minted = false;

    if (decision.action === "claim") {
      // Cold claim — establish before consume (strict).
      const handoff = readHandoff(ctx.cwd, decision.runId);
      if (handoff === null || handoff.run_id !== decision.runId) {
        reportError(`handoff missing or mismatched for run ${decision.runId}`);
      } else {
        const data: WorkflowState = {
          run_id: decision.runId,
          pi_session_id: currentSessionId ?? undefined,
          mode: handoff.mode,
          // Record the launched stage so the interior can tell e.g. objective-author from plan
          // (both are read-only) and inject the right authoring context (planMode vs objectiveAuthor).
          stage: handoff.stage,
        };
        const okAppend = appendWorkflowState(pi, ctx, {
          data,
          field: "run_id",
          expected: decision.runId,
          scope: "workflow-state linkage error",
          failure: `read-back failed for run ${decision.runId}`,
        });
        if (!okAppend) {
          // do NOT consume
        } else {
          markHandoffConsumed(ctx.cwd, decision.runId, {
            piSessionId: currentSessionId ?? undefined,
          });
          resolved = data;
        }
      }
    } else if (decision.action === "fork") {
      // Inherited a run_id from a different session file → isolate the child's scratch.
      ensureRunScratch(ctx.cwd, decision.childRunId);
      const data: WorkflowState = {
        run_id: decision.childRunId,
        pi_session_id: currentSessionId ?? undefined,
        predecessor: decision.parentRunId,
        mode: decision.state.mode,
      };
      pi.appendEntry(WORKFLOW_STATE_TYPE, data);
      resolved = data;
    } else if (decision.action === "adopt") {
      // An env-inherited run id whose handoff was already consumed by a different session: a
      // spawned child (contracts §8.2). Mirror the fork arm — derived child identity, isolated
      // scratch, inherited mode (read-only gating survives) — minus everything that belongs to
      // the launched session: never re-consume the handoff (its pi_session_id keeps the true
      // claimer), no `stage` (no stage impersonation / stage-binding injection), and no
      // implementation/main pointer capture (resolveRunStage stays null for adopt).
      ensureRunScratch(ctx.cwd, decision.childRunId);
      const data: WorkflowState = {
        run_id: decision.childRunId,
        pi_session_id: currentSessionId ?? undefined,
        predecessor: decision.parentRunId,
        mode: decision.mode,
      };
      pi.appendEntry(WORKFLOW_STATE_TYPE, data);
      resolved = data;
    } else if (decision.action === "none") {
      // A warm session with no identity mints its own run_id so
      // per-run state (the session data dir) can key off it. No disk artifacts —
      // dirs are the accessor's job; provenance is recorded separately. A failed cold claim above never
      // falls here (claim stays a loud unclaimed error).
      const runId = mintRunId();
      const data: WorkflowState = { run_id: runId, pi_session_id: currentSessionId ?? undefined };
      const okAppend = appendWorkflowState(pi, ctx, {
        data,
        field: "run_id",
        expected: runId,
        scope: "workflow-state linkage error",
        failure: `read-back failed for minted run ${runId}`,
      });
      if (okAppend) {
        resolved = { ...decision.state, ...data };
        minted = true;
      }
    }

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
    // The headless worker's inner session lands here too (.main); driveStage records the matching
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
    // Footer-seam install-site vacating: under a foreign `[providers] footer` selection perk does
    // NOT install its own footer, leaving the foreign footer (`pi-powerline-footer` / `pi-bar`) as
    // the sole footer surface. perk's objective/checkpoints progress still reaches it via the
    // composed `perk` setStatus slot. Fail-safe: any config-read error resolves to install.
    if (ctx.hasUI && !footerInstalled && isPerkFooterReferenceSelected(ctx.cwd)) {
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
      footerInstalled = true;
    }

    if (process.env.PERK_SELFCHECK) {
      try {
        const dir = workflowDir(ctx.cwd);
        if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
        // The gate sentinel (unchanged — those gates parse this line).
        writeFileSync(
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
    if (process.env.PERK_SELFCHECK) {
      writeT3Sentinel(ctx.cwd, "tree", state, ctx.mode ?? null);
    }
  });

  // Warm door: the `plan_save` tool + `/plan-save` command. Takes `gating`:
  // a successful command-path save exits read-only mode (the read-only → read-write boundary).
  registerPlanSave(pi, gating);

  // The `/implement-here` command: the human-only no-save exit from plan mode (§8.23) —
  // implement the reviewed draft in-session, no issue created. Composes the gate through the
  // implementHereExit seam; no model tool is registered (machine-unreachable by construction).
  registerImplementHere(pi, gating);

  // The `plan_draft` working-draft file tool. Registered in the factory so it
  // exists before the gate snapshots tools; its name is in READ_ONLY_TOOLS (the structural
  // session-data carve-out), so it survives plan mode.
  registerPlanDraft(pi);

  // The `objective_draft` working-objective file tool (the plan_draft twin).
  registerObjectiveDraft(pi);

  // The `gist_draft` working-gist file tool (the third draft carve-out).
  registerGistDraft(pi);

  // The universal `ask_user_question` tool: lets a model interactively ask the human a
  // clarifying question (free-text or multiple-choice). Registered in the factory so it exists
  // before the gate snapshots tools; its name is in READ_ONLY_TOOLS so it survives plan mode.
  registerAskUser(pi);

  // Lifecycle gates: the dirty-repo switch/fork guard + the guard-only `/implement`.
  registerLifecycleGates(pi);

  // Warm door: the `submit` tool + `/submit` command.
  registerSubmit(pi);

  // The warm `ready` door: the deliberate draft→ready review gate (submit keeps draft).
  registerReady(pi);

  // Warm doors: `land` merges + sets pending-learn; `learn` clears it (TS-only).
  registerLand(pi);
  registerLearn(pi);

  // The warm `/address` review loop: the `resolve_review_threads` tool + `/address`
  // command. Classify-then-act (the verbose feedback fetch + classification runs in an isolated
  // spawned child; the parent fixes actionable items and batch-resolves the threads).
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

  // The warm `/pr-review-terminal` door: the terminal review entry — hunk always, no provider
  // dispatch (the command IS the selection); posting rides `submit_pr_review` above.
  registerPrReviewTerminal(pi);

  // The warm `/pr-review-browser` door: the browser review entry — plannotator always, opened
  // in the background (pre-PR it absorbs the since-base local browser review); posting is the
  // human's own platform-post from the UI, with `submit_pr_review` for request-changes only.
  registerPrReviewBrowser(pi);

  // The read-only CI executor: the `run_ci` tool + `/ci` command + `--allow-project-ci`
  // flag. Runs the project's `[ci]` named checks deterministically and reports (never fixes/loops).
  registerCiExecutor(pi);

  // perk-owned checkpoints: seed from the plan body's `## Steps`, advance on `[DONE:n]`.
  // Inert when no step list is present (perk plans are prose). Own `session_start`/`session_tree`/
  // `turn_end` handlers (coexist with the others; pi.on supports multiple handlers per event).
  // Todo-seam deferral: perk is the reference todo provider (`perk-checkpoints`); these
  // runtime surfaces step aside when a foreign `[providers] todo` is selected (the todo-seam mirror
  // of planMode's plan-seam deferral) — silent on the event handlers, announced on `/checkpoints`.
  registerCheckpoints(pi, perkStatus);

  // The FIRST 3rd-party todo adapter (the todo-seam mirror of registerPlanAdapterTombell).
  // Injection-only: inert unless `[providers] todo = "juicesharp-todo"` is selected AND the session
  // is an active workflow. It carries perk's implement-progress discipline onto `@juicesharp/rpiv-
  // todo`'s checklist overlay (perk's own checkpoints deferred). No `gating` argument —
  // the shim NEVER arbitrates tools (Invariant 1); no registration-time vacating (no command-name
  // collision on the todo seam, unlike the plan seam); never writes `perk:checkpoint`.
  registerTodoAdapterJuicesharp(pi);

  // The objective substrate: `/objective` set/clear, budget accounting, threshold
  // compaction, all keyed off the now-live `active_objective`. Inert when no objective is active.
  // (The deterministic objective mechanics live in the Python plane: `perk objective …`.)
  registerObjective(pi, perkStatus);

  // The warm `/commit-and-compact` utility door: drive a commit of the work so far, then
  // compact the session once HEAD has actually advanced (clean/read-only trees compact
  // immediately; no commit → compaction skipped, loudly). Human-only — no tool twin.
  registerCommitAndCompact(pi, gating);

  // The warm `objective_save` door: the `objective_save` tool + `/objective-save` command
  // (the objective mirror of plan-save). Takes `gating` for the read-only → read-write boundary.
  registerObjectiveSave(pi, gating);

  // The warm `gist_save` door: the `gist_save` tool + `/gist-save` command (the gist mirror).
  registerGistSave(pi, gating);

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
