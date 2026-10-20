// The browser-operation owner: the ONE per-activation object every browser door opens its
// plannotator review through (created in the composition root) — the draft doors
// (`/plan-review-browser`, `/objective-review-browser`, the plan-review flavor) and the
// code-review doors (`/pr-review-browser`'s PR modes, `/stack-review-browser` and
// `open_stack_review`). It sits above `DraftReviewSlot` and the Plannotator handoff and owns, for
// each operation it opens: the start (port pick + env preset through the door's handoff flavor),
// the companion-surface priming (the annotation surface, the door's companion context, the
// deferred-tool primes), readiness observation, decision observation with the tracked in-flight
// routing, replacement, the background tasks (their failures observed, never unhandled), console
// interception and cleanup. Subjects keep save, Direct-Edits, destination and publication rules
// (the door's `onDecision`); the slot keeps decision authority (the draft door's ladder); all
// presentation stays `report()` + `pi.sendUserMessage`. Because every door shares the one owner,
// any door's open replaces any other door's live review (a PR open retires a draft review —
// marker, companion clear, abort — and vice versa).
//
// THE TWO FLAVORS. The draft doors pass a companion (the draft-review wave context) and an
// applicability fence (`review.isCurrent`); the code-review doors pass neither — they have no
// companion context and no slot, so they are always applicable and their surfaces are the
// annotation surface alone (`mode: "review"`, `settle: settleCodeReviewOutcome`).
//
// THE START REFUSAL. A door whose source must be re-checked at the moment of launch (the stack
// door re-verifies its pinned patch digest — the start can wait on a predecessor's retirement)
// throws `BrowserStartRefusal` from `spec.start` before emitting anything: the owner reports
// its message verbatim and returns `failed {refused}`; any other start throw is the port-pick
// failure line and a bare `failed`.
//
// THE BACKGROUND OPEN: the server URL is deterministic the moment the port is picked, so `open`
// starts the handoff, primes, launches two background tasks and returns the URL — the door
// injects its guidance immediately. The readiness observer announces `ready` (plus one
// annotation-delivery continuation) or degrades on `timeout`; the decision task awaits the
// bridge (open-ended, exactly the `plan_review` bridge semantics) and routes a decided outcome.
//
// TWO FENCES, BOTH NEEDED. The RESOURCE fence is surface identity (`owns`): an operation may
// clear the annotation surface, clear its companion, announce readiness or degrade only while
// `annotations.surface` is still the very object it primed — the annotation module's own
// identity idiom — so a retired operation can never touch a successor's surfaces (the successor
// re-primed them). The APPLICABILITY fence is door-supplied (`spec.applicable`, the draft doors
// pass `review.isCurrent`): a blocking `plan_review` or `/implement-here` revokes a browser
// review's authority WITHOUT opening another browser operation, so its surfaces stay "owned"
// while its observer must stop announcing and degrading. `live(op)` (neither closed nor
// detached) is re-checked after every await in both tasks.
//
// DETACHING. Perk's wait on a review can end while its tab stays open — Plannotator's server is
// never stopped (abort-a-wait ≠ stop-a-server; a fixed port it still holds keeps refusing a
// second open, contracts §8.4). Three causes, each marking the tab through the code-owned
// `perk:wave` slot (`reviewDetachedStatus`): `replaced` (a newer open), `interrupted` (an
// external turn abort settled the bridge `aborted` — silent in-session, marker before the clear),
// `session-ended` (`session_shutdown` for reload/new/resume/fork; `quit` aborts without a push,
// the server dies with the process). Every detach push reports through a muted target — silent
// in-session whatever its outcome — is bounded (`DETACH_MARKER_BUDGET_MS`), is attempted
// immediately (the push helper sends first; readiness only gates its retries) and persists
// nothing.
//
// ORDERING INVARIANTS. (1) Register at entry: `open` makes the operation `current`
// synchronously, before its first await — invocation order is the authority, matching the
// slot's token, which also moves at door entry. (2) Detach before start: the predecessor is
// retired — routing cutoff → drain → marker → abort → quiesce → close — BEFORE the successor
// starts, and the start also waits for every earlier retirement still in flight and for the last
// started operation's readiness poll (even a closed one's), so the process-wide
// `PLANNOTATOR_PORT` preset windows never overlap (each readiness poll restores the value IT
// captured). (3) The routing cutoff (`detached`) is set
// synchronously when a detach begins, so a verdict arriving during the marker await or the
// drain never enters the subject router (it gets one warning instead). (4) An admitted decision
// (`routing`) is drained before the abort: the backend save is non-abortable and its session
// reconciliation needs a live ctx — `session_shutdown` is the last moment the old activation can
// finish it (Pi invalidates every captured ctx right after), so `shutdown` also awaits a
// predecessor a pending open is still retiring. (5) Marker before abort; abort before quiesce.
//
// ONE DEGRADE OWNER PER TERMINAL: the decision task degrades a settled-`unavailable` bridge (one
// error line naming the bridge's warning, then the degrade); the observer degrades a `timeout`
// and never races a settled bridge (`bridge_settled` is the decision task's). `degrade` is
// idempotent and gated by BOTH fences; a degraded operation stays current (a later open detaches
// it). THE POST-DEGRADE RULE, one for every door: a decided outcome arriving after the degrade
// is answered with one warning naming the re-run (`postDegradeDecisionWarning`) and never
// reaches `onDecision` — the degrade notice already moved the flow in-session and cleared the
// surface, so a late browser verdict carries nothing perk can route.
//
// Accepted edges: a network-failed marker push before readiness marks nothing (the unit dies
// with the clear); a push, quiesce or drain outliving its budget is abandoned — only the drain
// says so (a human-approved save is at stake); an early human decision mid-wave clears only the
// companion CONTEXT (a still-pending wave stays collectable, the wave module's timeout is the
// orphan insurance); a successor whose start fails (or refuses) after its predecessor was
// retired leaves no browser review (a draft door's slot already moved at door entry).

import type { ExtensionContext, SessionShutdownEvent } from "@earendil-works/pi-coding-agent";
import {
  type ConsoleErrorInterceptor,
  interceptConsoleError,
} from "../../substrate/consoleCapture.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { type ReportTarget, report } from "../../surfaces/report.ts";
import type { ActivityHandle, ActivitySink, StandingTarget } from "../../surfaces/surfaces.ts";
import {
  type AnnotationMode,
  type AnnotationPushDeps,
  type AnnotationState,
  type AnnotationSurface,
  clearAnnotationSurface,
  primeAnnotationSurface,
  replaceWaveStatus,
  resumeAnnotationDelivery,
} from "./providers/annotations.ts";
import type {
  CodeReviewOutcome,
  RespondSink,
  StartBrowserDeps,
  StartedSurface,
} from "./providers/plannotatorHandoff.ts";
import { browserUpNotice } from "./providers/plannotatorPort.ts";
import { type ReviewDetachCause, reviewDetachedStatus } from "./providers/waveStatus.ts";
import type { ReviewOutcome } from "./reviewOutcome.ts";

// ------------------------------------------------------------------------ budgets + texts

/** plannotator can pause up to ~4 s between setup lines — the quiet window stays above that. */
export const CONSOLE_QUIET_MS = 6_000;

/** The detached-marker push budget (advisory; a push outliving it is abandoned silently). */
export const DETACH_MARKER_BUDGET_MS = 2_000;

/**
 * A detached operation's start/readiness settlement budget — at least the handoff's 1 s probe
 * cadence (the poll's sleep is not abortable) plus a port pick.
 */
export const QUIESCE_BUDGET_MS = 3_000;

/** The budget for an admitted in-flight decision (a save) at detach/shutdown. */
export const DECISION_DRAIN_BUDGET_MS = 60_000;

/** The cause words the detached-decision warning names. */
const DETACH_CAUSE_WORDS: Readonly<Record<ReviewDetachCause, string>> = {
  replaced: "replaced",
  interrupted: "interrupted",
  "session-ended": "session ended",
};

/** A decided outcome that arrived after the routing cutoff — never routed. */
export function detachedDecisionWarning(cause: ReviewDetachCause): string {
  return (
    `a browser decision arrived for a detached browser review (${DETACH_CAUSE_WORDS[cause]}) — ` +
    "ignored; nothing was saved"
  );
}

/** A decided outcome that arrived after the review degraded — never routed (every door). */
export function postDegradeDecisionWarning(scope: string): string {
  return (
    "a browser decision arrived after the review degraded — ignored (nothing routed, nothing " +
    `saved); re-run /${scope} to review again`
  );
}

/** The drain budget expired with an admitted decision still saving — proceed, loudly. */
export function decisionDrainExpiredWarning(scope: string): string {
  return (
    `a browser decision for /${scope} is still being saved after ` +
    `${DECISION_DRAIN_BUDGET_MS / 1000} s — proceeding; check the issue backend for this run id ` +
    "before saving again"
  );
}

/** The server noun per annotation mode — byte-stable with the doors' historical texts. */
const SERVER_NOUN: Readonly<Record<AnnotationMode, string>> = {
  plan: "plan-review",
  review: "review",
};

/**
 * The detach pushes' report target: silent in-session for every outcome (an HTTP rejection or
 * exhausted retries never surfaces — the marker is advisory and the operation is ending).
 */
const MUTED_TARGET: ReportTarget = { hasUI: true, ui: { notify() {} } };

// ------------------------------------------------------------------------ the interface

/** How a settled bridge outcome classifies for the owner. */
export type BrowserSettlement =
  | { kind: "decided" }
  | { kind: "unavailable"; warning: string }
  | { kind: "aborted" };

/** What the owner hands the door's handoff flavor at start. */
export interface BrowserLaunch {
  /** The operation's signal: the owner's own abort composed with the opening turn's. */
  signal: AbortSignal;
  activity: ActivitySink;
  deps: StartBrowserDeps;
}

/** One door's browser operation: the handoff it starts plus its subject-side hooks. */
export interface BrowserOperationSpec<T> {
  /** The door's report scope — also its command name (`re-run /<scope>`). */
  scope: string;
  /**
   * The handoff flavor bound by the door. A launch-time source check throws
   * `BrowserStartRefusal` before anything is emitted.
   */
  start(launch: BrowserLaunch): Promise<StartedSurface<T>>;
  /** The primed annotation mode ("plan": the draft doors; "review": the code-review doors). */
  mode: AnnotationMode;
  /** The deferred tools the door's guidance names (`gating.primeDeferred` at prime time). */
  primes: readonly string[];
  /** The door's companion context (the draft doors' draft-review context; code review: none). */
  companion?: { prime(): void; clear(): void };
  /**
   * The door-supplied applicability fence for observer EMISSIONS (announce/degrade): the draft
   * doors pass `review.isCurrent`. Default: always applicable.
   */
  applicable?: () => boolean;
  /** The model-facing never-ready text (door-specific). */
  degradeNotice: string;
  /** Classify the bridge outcome. */
  settle(out: T): BrowserSettlement;
  /** Subject routing for a DECIDED outcome only. */
  onDecision(out: T): Promise<void>;
}

/**
 * What `open` launched: `opened` (started and primed — the URL is deterministic); `failed`
 * (nothing launched — the start failed and was reported loudly; `refused` carries the message
 * of a door's `BrowserStartRefusal`, absent for a port-pick failure); `retired` (nothing
 * launched — a newer open or the shutdown retired this one before it started; the newer open's
 * guidance stands, so a caller must never fall back to another review surface on this arm).
 */
export type BrowserOpenResult =
  | { readonly kind: "opened"; readonly url: string }
  | { readonly kind: "failed"; readonly refused?: string }
  | { readonly kind: "retired" };

/**
 * A door's launch-time refusal, thrown from `spec.start` BEFORE the handoff emits anything (the
 * stack door's re-verified patch digest). The owner reports the message verbatim (no port-pick
 * prefix) and returns `failed {refused: message}`.
 */
export class BrowserStartRefusal extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BrowserStartRefusal";
  }
}

/** The ctx slice the owner needs (`ExtensionContext` satisfies it; tests fake it). */
export type BrowserOperationContext = ReportTarget &
  StandingTarget &
  Pick<ExtensionContext, "isIdle" | "signal">;

export interface BrowserOperationOwner {
  /**
   * Open a browser operation: retire the previous one (detached `replaced`), wait until every
   * earlier start has quiesced, start, prime, launch the background tasks.
   */
  open<T>(ctx: BrowserOperationContext, spec: BrowserOperationSpec<T>): Promise<BrowserOpenResult>;
  /**
   * `session_shutdown`: detach the current operation (`session-ended`; no push on `quit`), then
   * wait for every retirement still in flight and the last start's readiness poll.
   */
  shutdown(ctx: BrowserOperationContext, reason: SessionShutdownEvent["reason"]): Promise<void>;
}

/** The `ReviewOutcome` classifier the plan-review flavor's doors pass as `settle`. */
export function settleReviewOutcome(out: ReviewOutcome): BrowserSettlement {
  switch (out.status) {
    case "completed":
      return { kind: "decided" };
    case "unavailable":
      return { kind: "unavailable", warning: out.warning };
    case "aborted":
    case "dismissed":
    case "implement-here":
      // dismissed/implement-here are first-party only — the bridge never produces them.
      return { kind: "aborted" };
  }
}

/**
 * The `CodeReviewOutcome` classifier the code-review doors pass as `settle`. A `handled` reply is
 * a decision whatever it carries — the `exit` (closed without feedback) arm included: the door's
 * respond mapper renders it.
 */
export function settleCodeReviewOutcome(out: CodeReviewOutcome): BrowserSettlement {
  switch (out.status) {
    case "handled":
      return { kind: "decided" };
    case "unavailable":
    case "error":
      return { kind: "unavailable", warning: out.warning };
    case "aborted":
      return { kind: "aborted" };
  }
}

// ------------------------------------------------------------------------ operation state

interface Deferred<T> {
  promise: Promise<T>;
  resolve(value: T): void;
}

function deferred<T>(): Deferred<T> {
  let resolve: (value: T) => void = () => {};
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

/** The type-erased part of an operation the owner retires/closes without knowing `T`. */
interface OperationCore {
  readonly scope: string;
  readonly ctx: BrowserOperationContext;
  readonly controller: AbortController;
  readonly companion: { prime(): void; clear(): void } | undefined;
  /** The annotation surface this operation primed (the resource-fence identity). */
  surface: AnnotationSurface | null;
  degraded: boolean;
  closed: boolean;
  /** The routing cutoff — set synchronously when a detach begins. */
  detached: ReviewDetachCause | null;
  /** The admitted in-flight decision (drained at detach/shutdown). */
  routing: Promise<void> | null;
  interceptor: ConsoleErrorInterceptor | null;
  /** Resolved once the start (pick/preset) and the readiness poll ended — the env restored. */
  readonly quiesced: Deferred<void>;
}

interface Operation<T> extends OperationCore {
  readonly spec: BrowserOperationSpec<T>;
}

function live(op: OperationCore): boolean {
  return !op.closed && op.detached === null;
}

function detailOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

// ------------------------------------------------------------------------ the owner

/** Create the activation's browser-operation owner (one per composition root). */
export function createBrowserOperationOwner(
  pi: RespondSink,
  deps: {
    annotations: AnnotationState;
    gating: Pick<ToolGating, "primeDeferred">;
    status: ActivityHandle;
    /** The activation's port selection. */
    browserDeps?: StartBrowserDeps;
    /** Tests: the detach push's fetch. */
    annotationDeps?: AnnotationPushDeps;
    consoleQuietMs?: number;
    /** Tests: the owner's budget timers. */
    sleep?: (ms: number) => Promise<void>;
  },
): BrowserOperationOwner {
  const { annotations, gating, status } = deps;
  const quietMs = deps.consoleQuietMs ?? CONSOLE_QUIET_MS;
  let current: OperationCore | null = null;
  /**
   * The last operation that began its start — retained after it closes: its readiness poll may
   * still hold the process-wide `PLANNOTATOR_PORT` preset until it quiesces (a decision can close
   * an operation while its poll sleeps), so every later start waits for it.
   */
  let lastStarted: OperationCore | null = null;
  /**
   * Every detach still in flight with its target — a later start and `shutdown` await them all
   * (a predecessor's drain included), never one targeting the waiter itself.
   */
  const detaching = new Set<{ target: OperationCore; done: Promise<void> }>();

  /** The in-flight detaches, except any retiring `self` (a waiter never waits on its own). */
  const pendingRetirements = (self: OperationCore | null): Promise<void>[] =>
    [...detaching].filter((entry) => entry.target !== self).map((entry) => entry.done);

  /** The resource fence: the annotation surface is still the very object this op primed. */
  const owns = (op: OperationCore): boolean =>
    annotations.surface !== null && annotations.surface === op.surface;

  const applicable = <T>(op: Operation<T>): boolean => op.spec.applicable?.() ?? true;

  /** Race `p` against the budget: true when `p` settled first (either way), false on expiry. */
  const bounded = async (p: Promise<unknown>, ms: number): Promise<boolean> => {
    let cancel = (): void => {};
    const timer =
      deps.sleep !== undefined
        ? deps.sleep(ms)
        : new Promise<void>((resolve) => {
            const handle = setTimeout(resolve, ms);
            (handle as { unref?: () => void }).unref?.();
            cancel = () => clearTimeout(handle);
          });
    try {
      return await Promise.race([
        p.then(
          () => true,
          () => true,
        ),
        timer.then(() => false),
      ]);
    } finally {
      cancel();
    }
  };

  /** A background task's failure: reported while the op is open, else one stderr line. */
  const failed = (op: OperationCore, task: string, error: unknown): void => {
    const message = `the browser ${task} failed: ${detailOf(error)}`;
    if (!op.closed) {
      try {
        report(op.ctx, op.scope, "error", message, { alsoLog: true });
        return;
      } catch {
        // A ctx gone stale mid-report: fall through to the one stderr line.
      }
    }
    console.error(`perk: ${op.scope} — ${message}`);
  };

  /** Idempotent: drop this op's surfaces (only while it still owns them) and its interception. */
  const close = (op: OperationCore): void => {
    if (op.closed) return;
    op.closed = true;
    if (owns(op)) {
      clearAnnotationSurface(annotations);
      op.companion?.clear();
    }
    op.interceptor?.restore();
    if (current === op) current = null;
  };

  /** Replace the tab's `perk:wave` marker with the detached notice (muted, bounded). */
  const pushDetachMarker = async (op: OperationCore, cause: ReviewDetachCause): Promise<void> => {
    if (!owns(op)) return; // degraded, closed or re-primed — not this op's surface anymore
    await bounded(
      replaceWaveStatus(annotations, MUTED_TARGET, reviewDetachedStatus(cause), {
        ...deps.annotationDeps,
        sleep: () => Promise.resolve(),
      }),
      DETACH_MARKER_BUDGET_MS,
    );
  };

  /** Retire an operation: cutoff → drain → marker → abort → quiesce → close. */
  const detach = async (
    ctx: BrowserOperationContext,
    op: OperationCore,
    cause: ReviewDetachCause,
    opts: { marker: boolean },
  ): Promise<void> => {
    if (op.closed) return;
    // The routing cutoff, synchronous: a verdict arriving from here on is never routed. Only
    // the detach that set it owns the marker (an `interrupted` push may already be in flight).
    const owner = op.detached === null;
    if (owner) op.detached = cause;
    const routing = op.routing;
    if (routing !== null) {
      const drained = await bounded(routing, DECISION_DRAIN_BUDGET_MS);
      if (!drained) report(ctx, op.scope, "warning", decisionDrainExpiredWarning(op.scope));
    }
    // After a routed decision the op already closed and no longer owns the surface — no push.
    if (opts.marker && owner && routing === null) await pushDetachMarker(op, cause);
    // The owner aborts ITS waits only: the bridge disposes its listener and settles `aborted`;
    // the readiness poll settles `aborted` at its next iteration and restores the env var.
    op.controller.abort();
    await bounded(op.quiesced.promise, QUIESCE_BUDGET_MS);
    close(op);
  };

  /** `detach`, tracked until it settles. */
  const retire = (
    ctx: BrowserOperationContext,
    op: OperationCore,
    cause: ReviewDetachCause,
    opts: { marker: boolean },
  ): Promise<void> => {
    const entry = { target: op, done: detach(ctx, op, cause, opts) };
    const untrack = (): void => {
      detaching.delete(entry);
    };
    detaching.add(entry);
    entry.done.then(untrack, untrack);
    return entry.done;
  };

  /** The one degrade path (idempotent): loud error + the notice + this op's surfaces cleared. */
  const degrade = <T>(op: Operation<T>, url: string): void => {
    // Both fences: a review that no longer speaks for the session, or whose surface another
    // browser re-primed, neither reports, nor injects the fallback, nor flips `degraded`.
    if (op.degraded || !applicable(op) || !owns(op)) return;
    op.degraded = true;
    report(
      op.ctx,
      op.scope,
      "error",
      `the plannotator ${SERVER_NOUN[op.spec.mode]} server did not become ready at ${url} — ` +
        "the browser review is unavailable",
      { alsoLog: true },
    );
    if (op.ctx.isIdle()) pi.sendUserMessage(op.spec.degradeNotice);
    else pi.sendUserMessage(op.spec.degradeNotice, { deliverAs: "followUp" });
    // A post-degrade push refuses `no_surface`; a post-degrade wave start refuses
    // `no_draft_context` — consistent with "surface findings in-session".
    clearAnnotationSurface(annotations);
    op.companion?.clear();
  };

  /** The readiness observer: announce `ready`, degrade `timeout`; every other arm is silent. */
  const observe = async <T>(op: Operation<T>, started: StartedSurface<T>): Promise<void> => {
    const state = await started.readiness;
    if (!live(op) || !applicable(op)) return;
    if (state === "ready") {
      if (owns(op)) {
        report(op.ctx, op.scope, "info", browserUpNotice(started));
        resumeAnnotationDelivery(annotations, op.surface, pi, op.ctx);
      }
      return;
    }
    // `aborted` → the wait was interrupted; `bridge_settled` → the decision task owns every
    // settlement-driven terminal (a handshake failure degrades THERE, exactly once).
    if (state === "timeout") degrade(op, started.url);
  };

  /** The decision task: await the bridge, classify, route a decided outcome (tracked). */
  const decide = async <T>(op: Operation<T>, started: StartedSurface<T>): Promise<void> => {
    op.interceptor = interceptConsoleError(
      (line) => {
        if (!op.closed) report(op.ctx, op.scope, "info", line);
      },
      { quietMs },
    );
    try {
      const out = await started.bridgePromise;
      const settled = op.spec.settle(out);
      if (settled.kind === "aborted") {
        // An external turn abort (the owner did not cause it): mark the tab, stay silent.
        if (op.detached === null) {
          op.detached = "interrupted";
          await pushDetachMarker(op, "interrupted");
        }
        return;
      }
      if (op.detached !== null) {
        // A closed op stays silent: its ctx may be stale.
        if (settled.kind === "decided" && !op.closed) {
          report(op.ctx, op.scope, "warning", detachedDecisionWarning(op.detached));
        }
        return;
      }
      if (op.degraded) {
        // The observer's timeout already degraded: a decision is ignored loudly; a handshake
        // failure adds only its own warning line (the notice was injected once).
        if (settled.kind === "decided") {
          report(op.ctx, op.scope, "warning", postDegradeDecisionWarning(op.scope));
        } else if (settled.kind === "unavailable") {
          report(op.ctx, op.scope, "error", settled.warning, { alsoLog: true });
        }
        return;
      }
      if (settled.kind === "unavailable") {
        report(op.ctx, op.scope, "error", settled.warning, { alsoLog: true });
        degrade(op, started.url);
        return;
      }
      op.routing = op.spec.onDecision(out);
      try {
        await op.routing;
      } finally {
        op.routing = null;
      }
    } catch (error) {
      failed(op, "decision task", error);
    } finally {
      close(op);
      op.interceptor?.restore();
    }
  };

  return {
    async open<T>(
      ctx: BrowserOperationContext,
      spec: BrowserOperationSpec<T>,
    ): Promise<BrowserOpenResult> {
      // The repo's two-source cancellation idiom: the owner's abort OR the opening turn's.
      const turnSignal = ctx.signal;
      const controller = new AbortController();
      const signal =
        turnSignal !== undefined
          ? AbortSignal.any([controller.signal, turnSignal])
          : controller.signal;
      const op: Operation<T> = {
        scope: spec.scope,
        ctx,
        controller,
        companion: spec.companion,
        spec,
        surface: null,
        degraded: false,
        closed: false,
        detached: null,
        routing: null,
        interceptor: null,
        quiesced: deferred<void>(),
      };
      // Register synchronously, before the first await: invocation order is the authority.
      const previous = current;
      current = op;
      const retiring = previous !== null && !previous.closed ? previous : null;
      if (retiring !== null) await retire(ctx, retiring, "replaced", { marker: true });
      // Serialize the start behind every earlier retirement still in flight (an older admitted
      // save the predecessor was still draining included) and behind the last start's readiness
      // poll (possibly a closed operation's), so preset windows never overlap. Each wait is
      // bounded by its own budgets.
      await Promise.allSettled(pendingRetirements(op));
      const prior = lastStarted;
      if (prior !== null) await bounded(prior.quiesced.promise, QUIESCE_BUDGET_MS);
      // A newer open or a shutdown retired this one while it waited: nothing started, nothing
      // primed, nothing reported — the newer open's guidance stands.
      if (!live(op)) {
        op.quiesced.resolve();
        return { kind: "retired" };
      }
      if (retiring !== null) {
        report(
          ctx,
          spec.scope,
          "info",
          `the earlier browser review (${retiring.scope}) was replaced — its tab is marked ` +
            "detached and its decision will not be routed",
        );
      }

      lastStarted = op;
      let started: StartedSurface<T>;
      try {
        started = await spec.start({
          signal,
          // A retired op begins no activity (its ctx may already be stale).
          activity: (text) => (live(op) ? status.beginActivity(ctx, text) : () => {}),
          deps: deps.browserDeps ?? {},
        });
      } catch (error) {
        const retired = !live(op);
        const refusal = error instanceof BrowserStartRefusal ? error : null;
        if (!retired) {
          report(
            ctx,
            spec.scope,
            "error",
            refusal !== null
              ? refusal.message
              : `could not pick a free local port for the plannotator ${SERVER_NOUN[spec.mode]} ` +
                  `server: ${detailOf(error)}`,
            { alsoLog: true },
          );
        }
        close(op);
        op.quiesced.resolve();
        if (retired) return { kind: "retired" };
        return refusal !== null ? { kind: "failed", refused: refusal.message } : { kind: "failed" };
      }
      // Quiesced = the readiness poll ended (its `finally` restored the env var it captured).
      void started.readiness.then(
        () => op.quiesced.resolve(),
        () => op.quiesced.resolve(),
      );
      // Retired during the start: its controller is already aborted, so the bridge and the poll
      // settle `aborted` on their own — prime nothing, launch nothing.
      if (!live(op)) return { kind: "retired" };

      primeAnnotationSurface(annotations, { mode: spec.mode, url: started.url });
      op.surface = annotations.surface;
      spec.companion?.prime();
      gating.primeDeferred(spec.primes);

      void observe(op, started).catch((error: unknown) => failed(op, "readiness observer", error));
      void decide(op, started).catch((error: unknown) => failed(op, "decision task", error));
      return { kind: "opened", url: started.url };
    },

    async shutdown(ctx, reason): Promise<void> {
      const op = current;
      // On `quit` the server dies with the process — no push.
      if (op !== null && !op.closed) {
        await retire(ctx, op, "session-ended", { marker: reason !== "quit" });
      }
      // A predecessor still being retired by a pending open (its admitted save draining) must
      // finish while this ctx is live too — each detach is itself bounded. And the last start's
      // readiness poll (a closed operation's, its decision already routed) restores the env
      // var before the next activation can preset it.
      await Promise.allSettled(pendingRetirements(null));
      const prior = lastStarted;
      if (prior !== null) await bounded(prior.quiesced.promise, QUIESCE_BUDGET_MS);
    },
  };
}
