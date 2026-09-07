import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  createDraftReviewActivation,
  type DraftReviewAccess,
  type DraftReviewRuntime,
} from "../pi/v1/draftReviewActivation.ts";
import type { ReviewOutcome } from "../pi/v1/review.ts";
import { openBranchWorkflowSession } from "../session/branchWorkflowSession.ts";
import type { DraftReviewRegistration } from "../session/draftReviewState.ts";
import { digestSessionData } from "../session/workflowSession.ts";
import { gitInit } from "./harness.ts";

/** Explicit test-only transport hooks. State/claim composition tests use the real coordinator. */
export function recordingDraftRegistration() {
  const calls: string[] = [];
  const registration: DraftReviewRegistration = {
    open(id) {
      calls.push(`open:${id}`);
      return { ok: true };
    },
    attach(id, review) {
      calls.push(`attach:${id}:${review}`);
      return { ok: true };
    },
    invalidateOpening(id, reason) {
      calls.push(`invalidate:${id}:${reason}`);
      return { ok: true };
    },
    subscriptionFailed(id, review) {
      calls.push(`subscribe:${id}:${review}`);
      return { ok: true };
    },
    diagnostic(code) {
      calls.push(`diagnostic:${code}`);
    },
  };
  return { registration, calls };
}

/** Browser resource tests use real activation/state/claims with explicit fake session storage. */
export function seedBrowserReviews(
  pi: ExtensionAPI,
  ctx: ExtensionContext,
  subject: "plan" | "objective",
  markdown: string,
  raw = markdown,
): DraftReviewAccess {
  gitInit(ctx.cwd, { dirty: false });
  const branch: unknown[] = [
    {
      type: "custom",
      customType: "perk:workflow-state",
      data: {
        run_id: "RID",
        stage: subject === "plan" ? "plan" : "objective-author",
        mode: "read-only",
      },
    },
  ];
  Object.assign(ctx, {
    sessionManager: { getBranch: () => branch, getSessionId: () => "browser-fixture" },
  });
  Object.assign(pi, {
    on() {},
    appendEntry(customType: string, data: unknown) {
      branch.push({ type: "custom", customType, data });
    },
  });
  const written = openBranchWorkflowSession(pi, ctx).writeArtifact(
    subject === "plan" ? "plan-draft.md" : "objective-draft.json",
    raw,
  );
  if (written.status !== "applied") throw new Error("browser fixture draft write failed");
  return createDraftReviewActivation(pi);
}
const mutationRuntimes = new WeakMap<ExtensionContext, DraftReviewRuntime>();
function mutationRuntime(ctx: ExtensionContext): DraftReviewRuntime {
  let runtime = mutationRuntimes.get(ctx);
  if (runtime === undefined) {
    // Policy tests fake only Pi's storage carrier; mutation identity/state/claims remain real.
    const pi = {
      on() {},
      appendEntry(type: string, data: unknown) {
        const manager = ctx.sessionManager;
        if (!("appendCustomEntry" in manager) || typeof manager.appendCustomEntry !== "function")
          throw new Error("Policy fixture needs a writable session manager");
        manager.appendCustomEntry(type, data);
      },
    } as unknown as ExtensionAPI;
    runtime = createDraftReviewActivation(pi);
    mutationRuntimes.set(ctx, runtime);
  }
  return runtime;
}
export const policyDraftReviews: DraftReviewRuntime = {
  mutate(ctx, reason, work, options) {
    return mutationRuntime(ctx).mutate(ctx, reason, work, options);
  },
  mutateAsync(ctx, reason, work) {
    return mutationRuntime(ctx).mutateAsync(ctx, reason, work);
  },
  prepare(_ctx, markdown = "", signal) {
    const abort = new AbortController();
    return {
      ok: true,
      value: {
        snapshot: {
          source: { kind: "parameter", plan: markdown, artifact_at_open: "absent" },
          raw: markdown,
          markdown,
          sourceDigest: digestSessionData(markdown),
          binding: {
            runId: "RID",
            subject: "plan",
            digest: digestSessionData("target"),
            warmNodeClaim: null,
          },
        },
        registration: recordingDraftRegistration().registration,
        signal: signal ?? abort.signal,
        isCurrent: () => true,
        degrade() {
          throw new Error("Policy fixture cannot authorize degradation");
        },
        async complete() {
          throw new Error(
            "Policy-only fixture cannot authorize production completion; use real activation/state/claims",
          );
        },
        dispose() {
          abort.abort();
        },
      },
    };
  },
};

/** Legacy policy callers now exercise real state/claims; only the upstream verdict is scripted. */
export function scriptedDraftReviewBridge(outcome: ReviewOutcome) {
  const reviewed: string[] = [];
  return {
    ...policyDraftReviews,
    reviewed,
    prepare(ctx: ExtensionContext, parameter?: string, signal?: AbortSignal) {
      if (!existsSync(join(ctx.cwd, ".git"))) gitInit(ctx.cwd, { dirty: false });
      return mutationRuntime(ctx).prepare(ctx, parameter, signal);
    },
    async review(markdown: string, registration: DraftReviewRegistration): Promise<ReviewOutcome> {
      const id = randomUUID();
      const opened = registration.open(id);
      if (!opened.ok) throw new Error(`scripted registration refused: ${opened.reason}`);
      if (outcome.status === "completed") {
        const attached = registration.attach(id, outcome.reviewId);
        if (!attached.ok) throw new Error(`scripted attachment refused: ${attached.reason}`);
      }
      reviewed.push(markdown);
      return outcome;
    },
  };
}
