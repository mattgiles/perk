import assert from "node:assert/strict";
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { GIST_DRAFT_ARTIFACT } from "../../authoring/gist/draft.ts";
import { completeGistReview } from "../../authoring/gist/review.ts";
import { type GistBackend, gistApprovalSave } from "../../authoring/gist/save.ts";
import { OBJECTIVE_DRAFT_ARTIFACT } from "../../authoring/objective/draft.ts";
import { completeObjectiveReview } from "../../authoring/objective/review.ts";
import { type ObjectiveBackend, objectiveApprovalSave } from "../../authoring/objective/save.ts";
import { PLAN_DRAFT_ARTIFACT } from "../../authoring/plan/draft.ts";
import { completePlanReview } from "../../authoring/plan/review.ts";
import type { PlanApprovalSaveDeps, PlanBackendSaveResult } from "../../authoring/plan/save.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import {
  captureDraftReviewBinding,
  type DraftReviewBinding,
  type TargetComponent,
} from "../../session/draftReviewBinding.ts";
import {
  DRAFT_REVIEW_ARTIFACT,
  deliveryMarker,
  encodeDraftReview,
  type ReviewSubject,
  readDraftReview,
} from "../../session/draftReviewState.ts";
import { sessionDataDir } from "../../substrate/cache.ts";
import { acquireDraftReviewLock, DRAFT_REVIEW_LOCK } from "../../substrate/draftReviewLock.ts";
import { type BranchEntry, WORKFLOW_STATE_TYPE } from "../../substrate/workflowState.ts";
import { fakeTargetComponents } from "../../testing/draftReview.ts";
import { openMemoryWorkflowSession } from "../../testing/memoryWorkflowSession.ts";
import { createDraftReviewDecisions, type DraftReviewCapability } from "./draftReviewDecisions.ts";
import {
  boundGistSaveDeps,
  boundObjectiveSaveDeps,
  boundPlanSaveDeps,
} from "./draftReviewEffects.ts";

const requestId = "11111111-1111-4111-8111-111111111111";
const successorId = "22222222-2222-4222-8222-222222222222";
const id = { requestId, reviewId: "upstream" };
function fixture(subject: ReviewSubject = "plan", parameter = false) {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "perk-draft-decisions-")));
  const session = openMemoryWorkflowSession({ runId: "RID" });
  let target: DraftReviewBinding = {
    runId: "RID",
    subject,
    digest: `sha256:${"a".repeat(64)}`,
    warmNodeClaim: null,
    components: fakeTargetComponents(),
  };
  session.draftReviewContext = () => ({
    ok: true,
    runId: "RID",
    subject: target.subject,
    warmNodeClaim: target.warmNodeClaim,
  });
  const name =
    subject === "plan"
      ? PLAN_DRAFT_ARTIFACT
      : subject === "objective"
        ? OBJECTIVE_DRAFT_ARTIFACT
        : GIST_DRAFT_ARTIFACT;
  const raw =
    subject === "plan"
      ? " \n# Reviewed 雪\n "
      : JSON.stringify({
          schema_version: 1,
          prose: "Reviewed",
          invisible: "bound",
          ...(subject === "objective" ? { roadmap: [] } : {}),
        });
  if (!parameter) session.writeArtifact(name, raw);
  let drifts = 0;
  const binding = () => ({ ok: true as const, binding: structuredClone(target) });
  let entries: readonly unknown[] = [];
  const decisions = createDraftReviewDecisions({
    cwd: root,
    sessionId: "parent",
    session: () => session,
    entries: () => entries,
    binding,
  });
  const prepare = () => {
    const prepared = decisions.prepare(parameter ? raw : undefined);
    assert.ok(prepared.ok, JSON.stringify(prepared));
    return prepared.value;
  };
  const registration = prepare().registration;
  const open = () => {
    assert.deepEqual(registration.open(requestId), { ok: true });
    assert.deepEqual(registration.attach(requestId, id.reviewId), { ok: true });
  };
  const record = () => {
    const read = readDraftReview(session);
    assert.ok(read.ok);
    assert.ok(read.record);
    return read.record;
  };
  const tool = (cap: DraftReviewCapability, content = "result") => {
    cap.deliver({ kind: "tool", tool_call_id: "call" }, content);
    return {
      type: "message",
      id: "entry",
      message: {
        role: "toolResult",
        toolCallId: "call",
        toolName: "plan_review",
        details: { draft_review_dispatch: cap.dispatchId },
        content,
      },
    };
  };
  return {
    root,
    session,
    decisions,
    registration,
    open,
    record,
    raw,
    name,
    prepare,
    tool,
    lock: join(sessionDataDir(root, "RID"), DRAFT_REVIEW_LOCK),
    persisted(value: readonly unknown[]) {
      entries = value;
    },
    target(update: Partial<DraftReviewBinding>) {
      target = { ...target, ...update };
    },
    /** Stage a genuine routing drift: a new aggregate digest with exactly `changed` components moved. */
    drift(changed: TargetComponent[], update: Partial<DraftReviewBinding> = {}) {
      drifts++;
      target = {
        ...target,
        ...update,
        digest: `sha256:${String(drifts).padStart(64, "0")}`,
        components: fakeTargetComponents("target", changed),
      };
      return target.digest;
    },
    binding,
    dispose() {
      rmSync(root, { recursive: true, force: true });
    },
  };
}
const reviewedDigest = `sha256:${"a".repeat(64)}`;

for (const reason of ["handshake-failed", "subscription-failed"] as const) {
  test(`readiness reuses same-review ${reason} invalidation without rewriting it`, () => {
    const f = fixture();
    try {
      assert.ok(f.registration.open(requestId).ok);
      const identity = { requestId, reviewId: reason === "handshake-failed" ? null : id.reviewId };
      if (reason === "handshake-failed")
        assert.ok(f.registration.invalidateOpening(requestId, reason).ok);
      else {
        assert.ok(f.registration.attach(requestId, id.reviewId).ok);
        assert.ok(f.registration.subscriptionFailed(requestId, id.reviewId).ok);
      }
      const prior = f.record();
      assert.deepEqual(f.decisions.degrade(identity, "RID"), { ok: true });
      assert.deepEqual(f.record(), prior, "a sound transport invalidation is already proof");
      assert.equal(existsSync(f.lock), false);
      assert.ok(f.registration.open(successorId).ok);
      const successor = f.record();
      assert.equal(f.decisions.degrade(identity, "RID").ok, false);
      assert.deepEqual(f.record(), successor, "a predecessor cannot grant successor fallback");
    } finally {
      f.dispose();
    }
  });
}

for (const reason of ["source-changed", "manual-save", "first-party-review"] as const) {
  test(`readiness does not reuse ${reason} invalidation as transport failure`, () => {
    const f = fixture();
    try {
      f.open();
      assert.ok(f.decisions.mutate(reason, () => {}).ok);
      const prior = f.record();
      assert.equal(f.decisions.degrade(id, "RID").ok, false);
      assert.deepEqual(f.record(), prior);
    } finally {
      f.dispose();
    }
  });
}

test("byte-identical draft mutation is proved inside exclusion and the supplied session expires on release", () => {
  const f = fixture();
  try {
    f.open();
    let escaped: { writeArtifact: typeof f.session.writeArtifact } | undefined;
    const result = f.decisions.mutate(
      "source-changed",
      (session) => {
        escaped = session;
        return session.writeArtifact(f.name, f.raw);
      },
      { draft: { subject: "plan", content: f.raw } },
    );
    assert.ok(result.ok);
    assert.equal(f.record().consumption.state, "pending");
    assert.throws(() => escaped?.writeArtifact(f.name, "late"));
    assert.equal(f.session.readArtifact(f.name).status, "found");
  } finally {
    f.dispose();
  }
});

test("delivery releases immediately even if the caller has not returned, and next opening observes persisted evidence", async () => {
  const f = fixture();
  try {
    f.open();
    let complete: (() => void) | undefined;
    const wait = new Promise<void>((resolve) => {
      complete = resolve;
    });
    let evidence: unknown;
    const pending = f.decisions.dispatch({
      id,
      runId: "RID",
      approved: false,
      effect: "revision",
      execute: async (cap) => {
        evidence = f.tool(cap);
        assert.equal(existsSync(f.lock), false);
        const acquired = acquireDraftReviewLock(f.root, {
          sessionId: "probe",
          runId: "RID",
          requestId: successorId,
        });
        assert.equal(acquired.kind, "acquired");
        if (acquired.kind === "acquired") acquired.claim.finish("release");
        await wait;
        return "returned later";
      },
    });
    f.persisted([evidence]);
    assert.ok(f.registration.open(successorId).ok);
    assert.equal(f.record().request_id, successorId);
    assert.equal(f.record().consumption.state, "opening");
    assert.ok(complete);
    complete();
    assert.ok((await pending).ok);
  } finally {
    f.dispose();
  }
});

test("undecodable backend replies are backend-unconfirmed, and denied candidates cannot save", async () => {
  const f = fixture();
  try {
    f.open();
    const denied = await f.decisions.dispatch({
      id,
      runId: "RID",
      approved: false,
      effect: "save",
      execute: async () => assert.fail("denied save"),
    });
    assert.ok(!denied.ok);
    assert.equal(f.record().consumption.state, "pending");
    const broken = await f.decisions.dispatch({
      id,
      runId: "RID",
      approved: true,
      effect: "save",
      execute: async (cap) => {
        await cap.save(async () => undefined as never);
        assert.fail("undecodable backend success");
      },
    });
    assert.ok(!broken.ok);
    const c = f.record().consumption;
    assert.ok(c.state === "uncertain");
    assert.equal(c.reason, "backend-unconfirmed");
  } finally {
    f.dispose();
  }
});

test("registration is synchronous and claims are released outside hooks; superseded handshakes never overwrite", () => {
  const f = fixture();
  try {
    assert.equal(f.decisions.prepare().ok, true);
    assert.equal(existsSync(f.lock), false);
    assert.deepEqual(f.registration.open(requestId), { ok: true });
    assert.equal(f.record().consumption.state, "opening");
    assert.equal(existsSync(f.lock), false);
    assert.deepEqual(f.registration.open(successorId), { ok: true });
    const late = f.registration.attach(requestId, "late");
    assert.ok(!late.ok);
    assert.equal(late.reason, "superseded");
    assert.equal(f.record().request_id, successorId);
    const abort = f.registration.invalidateOpening(requestId, "opening-aborted");
    assert.ok(!abort.ok);
    assert.equal(abort.reason, "superseded");
    assert.deepEqual(f.registration.attach(successorId, "new"), { ok: true });
    assert.equal(f.record().correlation.review_id, "new");
    assert.equal(existsSync(f.lock), false);
  } finally {
    f.dispose();
  }
});

test("registration attaches only unchanged source, subject and conservative target; known pending survives local teardown", () => {
  for (const changed of ["source-changed", "subject-changed", "target-changed"] as const) {
    const f = fixture();
    try {
      assert.ok(f.registration.open(requestId).ok);
      if (changed === "source-changed") f.session.writeArtifact(f.name, "changed");
      if (changed === "subject-changed") f.target({ subject: "gist" });
      if (changed === "target-changed") f.target({ digest: `sha256:${"b".repeat(64)}` });
      const attached = f.registration.attach(requestId, id.reviewId);
      assert.ok(!attached.ok);
      assert.equal(attached.reason, changed);
      assert.deepEqual(f.record().consumption, { state: "invalidated", reason: changed });
      assert.equal(f.record().correlation.review_id, null);
    } finally {
      f.dispose();
    }
  }
  const f = fixture();
  try {
    f.open();
    assert.ok(f.decisions.end([]).ok);
    assert.equal(f.record().consumption.state, "pending");
  } finally {
    f.dispose();
  }
});

test("one raw→decoded→rendered snapshot binds invisible structured fields; exact nonblank parameter has no broken-provenance fallback", () => {
  for (const subject of ["plan", "objective", "gist"] as const) {
    const f = fixture(subject);
    try {
      const snapshot = f.prepare().snapshot;
      assert.equal(snapshot.raw, f.raw);
      if (subject === "plan") assert.equal(snapshot.markdown, f.raw);
      else
        assert.equal(
          snapshot.markdown,
          subject === "objective"
            ? "**Delivery: incremental** (the default — each plan lands independently)\n\nReviewed"
            : "Reviewed",
        );
      assert.ok(f.registration.open(requestId).ok);
      f.session.writeArtifact(
        f.name,
        subject === "plan" ? `${f.raw}\n` : f.raw.replace('"bound"', '"changed"'),
      );
      const result = f.registration.attach(requestId, "review");
      assert.ok(!result.ok);
      assert.equal(result.reason, "source-changed");
    } finally {
      f.dispose();
    }
  }
  const f = fixture("plan", true);
  try {
    assert.deepEqual(f.prepare().snapshot.source, {
      kind: "parameter",
      plan: f.raw,
      artifact_at_open: "absent",
    });
    assert.ok(f.registration.open(requestId).ok);
    f.session.writeArtifact(f.name, f.raw);
    assert.ok(!f.registration.attach(requestId, "review").ok);
    f.session.corruptContent(f.name);
    const result = f.decisions.prepare(f.raw);
    assert.ok(!result.ok);
    assert.equal(result.reason, "invalid-state");
  } finally {
    f.dispose();
  }
});

test("verified dispatch fences a backend and nested competitors, releases after expectation, then consumes persisted evidence once", async () => {
  const f = fixture();
  try {
    f.open();
    let saves = 0;
    let evidence: unknown;
    const outcome = await f.decisions.dispatch({
      id,
      runId: "RID",
      approved: true,
      effect: "save",
      execute: async (cap) => {
        assert.equal(f.record().consumption.state, "dispatch");
        assert.equal(existsSync(f.lock), true);
        const competitor = f.decisions.mutate("manual-save", () =>
          assert.fail("competitor effect"),
        );
        assert.ok(!competitor.ok);
        assert.equal(competitor.reason, "busy");
        const result = await cap.save(async (bound) => {
          saves++;
          assert.equal(bound.source, f.raw);
          const current = f.record().consumption;
          assert.ok(current.state === "dispatch");
          assert.equal(current.attempt.save.state, "started");
          assert.ok(!f.registration.open(successorId).ok);
          return { receipt: { id: "42", url: "url" }, value: "saved/gate-exited" };
        });
        assert.equal(result, "saved/gate-exited");
        evidence = f.tool(cap);
        return result;
      },
    });
    assert.ok(outcome.ok);
    assert.deepEqual(outcome.saveReceipt, { id: "42", url: "url" });
    assert.equal(saves, 1);
    assert.equal(existsSync(f.lock), false);
    assert.equal(f.record().consumption.state, "dispatch");
    assert.deepEqual(f.decisions.observe([]), { ok: true });
    assert.equal(f.record().consumption.state, "dispatch");
    // Legitimate post-save linkage/source changes cannot invalidate exact delivery proof.
    f.target({ digest: `sha256:${"b".repeat(64)}` });
    f.session.writeArtifact(f.name, "next draft");
    f.session.draftReviewContext = () => ({ ok: false, reason: "invalid-state" });
    assert.deepEqual(f.decisions.observe([evidence]), { ok: true });
    assert.equal(f.record().consumption.state, "consumed");
    const duplicate = await f.decisions.dispatch({
      id,
      runId: "RID",
      approved: false,
      effect: "revision",
      execute: async () => assert.fail("duplicate effect"),
    });
    assert.ok(duplicate.ok);
    assert.deepEqual(duplicate.value, { status: "consumed" });
    assert.equal(saves, 1);
  } finally {
    f.dispose();
  }
});

test("source-changed is stale DATA once; degradation/manual invalidation and subject/target mismatch authorize no effects", async () => {
  for (const change of [
    "source-changed",
    "degraded",
    "manual-save",
    "target-changed",
    "subject-changed",
  ] as const) {
    const f = fixture();
    try {
      f.open();
      if (change === "source-changed" || change === "degraded" || change === "manual-save") {
        const changed = f.decisions.mutate(change, (session) =>
          session.writeArtifact(f.name, "changed"),
        );
        assert.ok(changed.ok);
      } else
        f.target(
          change === "target-changed"
            ? { digest: `sha256:${"c".repeat(64)}` }
            : { subject: "gist" },
        );
      let calls = 0;
      const result = await f.decisions.dispatch({
        id,
        runId: "RID",
        approved: false,
        effect: "revision",
        execute: async (cap) => {
          calls++;
          assert.equal(change, "source-changed");
          assert.equal(cap.effect, "stale-reference");
          f.tool(cap);
          return "diagnostic only";
        },
      });
      if (change === "source-changed") {
        assert.ok(result.ok);
        assert.equal(calls, 1);
      } else {
        assert.ok(!result.ok);
        assert.equal(calls, 0);
      }
      const duplicate = await f.decisions.dispatch({
        id,
        runId: "RID",
        approved: true,
        effect: "save",
        execute: async () => assert.fail("late effect"),
      });
      assert.ok(!duplicate.ok);
    } finally {
      f.dispose();
    }
  }
});

test("attached parameter plus even byte-identical new artifact is stale DATA only; failed patch never bypasses broken intent", async () => {
  const parameter = fixture("plan", true);
  try {
    parameter.open();
    parameter.session.writeArtifact(parameter.name, parameter.raw);
    const result = await parameter.decisions.dispatch({
      id,
      runId: "RID",
      approved: true,
      effect: "save",
      execute: async (cap) => {
        assert.equal(cap.effect, "stale-reference");
        assert.throws(() => cap.writePlan("must not patch"));
        await assert.rejects(cap.save(async () => assert.fail("parameter fallback save")));
        parameter.tool(cap);
        return "stale DATA";
      },
    });
    assert.ok(result.ok);
    assert.equal(result.saveReceipt, null);
  } finally {
    parameter.dispose();
  }
  const broken = fixture();
  try {
    broken.open();
    const result = await broken.decisions.dispatch({
      id,
      runId: "RID",
      approved: true,
      effect: "save",
      execute: async (cap) => {
        broken.session.failNextPointerAppend();
        assert.equal(cap.writePlan("partial edited bytes").status, "unverified");
        broken.session.corruptContent(DRAFT_REVIEW_ARTIFACT);
        await cap.save(async () => assert.fail("original fallback over broken intent"));
        return "unreachable";
      },
    });
    assert.ok(!result.ok);
    assert.equal(result.reason, "invalid-state");
    assert.equal(existsSync(broken.lock), true);
  } finally {
    broken.dispose();
  }
});

test("owned patches save verified edited bytes or ONLY frozen original on rejected/unverified write-back", async () => {
  for (const failure of ["none", "rejected", "unverified"] as const) {
    const f = fixture();
    try {
      f.open();
      let saves = 0;
      const result = await f.decisions.dispatch({
        id,
        runId: "RID",
        approved: true,
        effect: "save",
        execute: async (cap) => {
          if (failure === "rejected") f.session.failNextWrite();
          if (failure === "unverified") f.session.failNextPointerAppend();
          const patch = cap.writePlan("edited bytes");
          assert.equal(patch.status, failure === "none" ? "applied" : failure);
          await cap.save(async (bound) => {
            saves++;
            assert.equal(bound.source, failure === "none" ? "edited bytes" : f.raw);
            return { receipt: { id: "42", url: "url" }, value: "saved" };
          });
          f.tool(cap);
          return "saved";
        },
      });
      assert.ok(result.ok, JSON.stringify(result));
      assert.equal(saves, 1);
    } finally {
      f.dispose();
    }
  }
});

test("source/target/subject revalidation after title-generation awaits stops backend; receipt survives later bookkeeping failure", async () => {
  for (const drift of ["source", "target", "subject"] as const) {
    const f = fixture();
    try {
      f.open();
      const result = await f.decisions.dispatch({
        id,
        runId: "RID",
        approved: true,
        effect: "save",
        execute: async (cap) => {
          await Promise.resolve();
          if (drift === "source") f.session.writeArtifact(f.name, "changed externally");
          if (drift === "target") f.target({ digest: `sha256:${"d".repeat(64)}` });
          if (drift === "subject") f.target({ subject: "objective" });
          await cap.save(async () => assert.fail("backend after drift"));
          return "unreachable";
        },
      });
      assert.ok(!result.ok);
      assert.equal(f.record().consumption.state, "uncertain");
    } finally {
      f.dispose();
    }
  }
  const f = fixture();
  try {
    f.open();
    const result = await f.decisions.dispatch({
      id,
      runId: "RID",
      approved: true,
      effect: "save",
      execute: async (cap) => {
        await cap.save(async () => {
          f.session.failNextPointerAppend();
          return { receipt: { id: "42", url: "url" }, value: "saved with gate exited" };
        });
        assert.fail("delivery after confirmation checkpoint failed");
      },
    });
    assert.ok(!result.ok);
    assert.equal(result.reason, "persistence-failed");
    assert.deepEqual(result.saveReceipt, { id: "42", url: "url" });
    assert.equal(existsSync(f.lock), true);
  } finally {
    f.dispose();
  }
});

for (const fault of ["rejected", "unverified"] as const) {
  for (const phase of [
    "opening",
    "attach",
    "intent",
    "save-started",
    "save-confirmed",
    "delivery",
    "completion",
  ] as const) {
    test(`${fault} ${phase} write retains claim and never speculates another state write/effect`, async () => {
      const f = fixture();
      try {
        let armed = true;
        let writesAfterFault = 0;
        let faulted = false;
        let saves = 0;
        let evidence: unknown;
        const originalWrite = f.session.writeArtifact.bind(f.session);
        f.session.writeArtifact = (name, content, options) => {
          if (name === DRAFT_REVIEW_ARTIFACT) {
            if (faulted) writesAfterFault++;
            const c = JSON.parse(content).consumption;
            const matches =
              phase === "opening"
                ? c.state === "opening"
                : phase === "attach"
                  ? c.state === "pending"
                  : phase === "completion"
                    ? c.state === "consumed"
                    : c.state === "dispatch" &&
                      (phase === "intent"
                        ? c.attempt.save.state === "not-started"
                        : phase === "save-started"
                          ? c.attempt.save.state === "started"
                          : phase === "save-confirmed"
                            ? c.attempt.save.state === "confirmed" && c.attempt.delivery === null
                            : c.attempt.delivery !== null);
            if (armed && matches) {
              armed = false;
              faulted = true;
              if (fault === "rejected") f.session.failNextWrite();
              else f.session.failNextPointerAppend();
            }
          }
          return originalWrite(name, content, options);
        };
        let refused = f.registration.open(requestId);
        if (refused.ok) refused = f.registration.attach(requestId, id.reviewId);
        if (refused.ok)
          refused = await f.decisions.dispatch({
            id,
            runId: "RID",
            approved: true,
            effect: "save",
            execute: async (cap) => {
              await cap.save(async () => {
                saves++;
                return { receipt: { id: "42", url: "url" }, value: "saved" };
              });
              evidence = f.tool(cap);
              return "result";
            },
          });
        if (refused.ok) refused = f.decisions.observe([evidence]);
        assert.ok(!refused.ok, phase);
        assert.equal(refused.reason, "persistence-failed");
        assert.equal(faulted, true);
        assert.equal(writesAfterFault, 0);
        assert.equal(existsSync(f.lock), true);
        assert.equal(saves, ["save-confirmed", "delivery", "completion"].includes(phase) ? 1 : 0);
        const blocked = f.decisions.mutate("manual-save", () =>
          assert.fail("mutation after retained failure"),
        );
        assert.ok(!blocked.ok);
        assert.equal(blocked.reason, "busy");
      } finally {
        f.dispose();
      }
    });
  }
}

test("abort/error/send/activation-end uncertainty preserves facts; ordinary observation never guesses delivery", async () => {
  for (const failure of [
    "pre-abort",
    "post-intent-abort",
    "backend-throw",
    "backend-unconfirmed",
    "effect-throw",
    "send-throw",
    "no-delivery",
    "shutdown",
  ] as const) {
    const f = fixture();
    try {
      f.open();
      const abort = new AbortController();
      if (failure === "pre-abort") abort.abort();
      const result = await f.decisions.dispatch({
        id,
        runId: "RID",
        approved: true,
        effect: "save",
        signal: abort.signal,
        execute: async (cap) => {
          if (failure === "post-intent-abort") abort.abort();
          if (failure === "effect-throw") throw new Error("effect");
          await cap.save(async () => {
            if (failure === "backend-throw") throw new Error("backend");
            return {
              receipt: failure === "backend-unconfirmed" ? null : { id: "42", url: "url" },
              value: "saved",
            };
          });
          if (failure === "no-delivery") return "not delivered";
          const text = `result\n${deliveryMarker({ kind: "user" }, cap.dispatchId)}`;
          cap.deliver({ kind: "user" }, text, () => {
            if (failure === "send-throw") throw new Error("send");
          });
          return "saved";
        },
      });
      if (failure === "pre-abort") {
        assert.ok(!result.ok);
        assert.equal(f.record().consumption.state, "pending");
        continue;
      }
      if (failure === "shutdown") {
        assert.ok(result.ok);
        assert.ok(f.decisions.observe([]).ok);
        assert.equal(f.record().consumption.state, "dispatch");
        assert.ok(f.decisions.end([]).ok);
      } else assert.ok(!result.ok);
      const c = f.record().consumption;
      assert.ok(c.state === "uncertain");
      assert.equal(
        c.reason,
        failure === "post-intent-abort"
          ? "aborted-after-intent"
          : failure.startsWith("backend")
            ? "backend-unconfirmed"
            : failure === "effect-throw"
              ? "effect-failed"
              : "delivery-unconfirmed",
      );
      assert.ok(!f.decisions.mutate("manual-save", () => assert.fail("uncertain retry")).ok);
    } finally {
      f.dispose();
    }
  }
});

test("same activation observes before guarded rewrite; new activation never consumes or resends previous intent", async () => {
  const f = fixture();
  try {
    f.open();
    let entry: unknown;
    let escaped: DraftReviewCapability | undefined;
    const result = await f.decisions.dispatch({
      id,
      runId: "RID",
      approved: false,
      effect: "revision",
      execute: async (cap) => {
        escaped = cap;
        entry = f.tool(cap);
        return "revision";
      },
    });
    assert.ok(result.ok);
    assert.throws(() => escaped?.deliver({ kind: "tool", tool_call_id: "other" }, "late"));
    const newActivation = createDraftReviewDecisions({
      cwd: f.root,
      sessionId: "parent",
      session: () => f.session,
      entries: () => [],
    });
    assert.ok(newActivation.observe([entry]).ok);
    assert.equal(f.record().consumption.state, "dispatch");
    const next = newActivation.mutate("source-changed", () =>
      assert.fail("new activation mutation"),
    );
    assert.ok(!next.ok);
    assert.equal(next.reason, "unresolved-dispatch");
    const rewrite = f.decisions.mutate(
      "source-changed",
      (session) => session.writeArtifact(f.name, "revised"),
      { entries: [entry] },
    );
    assert.ok(rewrite.ok);
    assert.equal(f.record().consumption.state, "consumed");
  } finally {
    f.dispose();
  }
});

test("ownership replacement stops state writes/effects and preserves replacement residue", async () => {
  const f = fixture();
  try {
    f.open();
    const result = await f.decisions.dispatch({
      id,
      runId: "RID",
      approved: true,
      effect: "save",
      execute: async (cap) => {
        rmSync(f.lock);
        const replacement = acquireDraftReviewLock(f.root, {
          sessionId: "other",
          runId: "RID",
          requestId: successorId,
        });
        assert.equal(replacement.kind, "acquired");
        if (replacement.kind === "acquired") replacement.claim.finish("retain");
        await cap.save(async () => assert.fail("lost ownership save"));
        return "unreachable";
      },
    });
    assert.ok(!result.ok);
    assert.equal(result.reason, "ownership-lost");
    assert.equal(f.record().consumption.state, "dispatch");
    assert.equal(JSON.parse(readFileSync(f.lock, "utf8")).requestId, successorId);
  } finally {
    f.dispose();
  }
});

test("independent real branch snapshots refuse advanced review bytes rather than overwrite a successor", () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "perk-draft-stale-")));
  const branch: BranchEntry[] = [
    { type: "custom", customType: WORKFLOW_STATE_TYPE, data: { run_id: "RID" } },
  ];
  const source = (entries: BranchEntry[]) => ({
    cwd: root,
    hasUI: false,
    ui: { notify() {} },
    sessionManager: { getBranch: () => entries },
  });
  const sink = (entries: BranchEntry[]) => ({
    appendEntry(customType: string, data?: unknown) {
      entries.push({ type: "custom", customType, data: data as Record<string, unknown> });
    },
  });
  const binding = () => ({
    ok: true as const,
    binding: {
      runId: "RID",
      subject: "plan" as const,
      digest: `sha256:${"a".repeat(64)}`,
      warmNodeClaim: null,
      components: fakeTargetComponents(),
    },
  });
  try {
    const session = openBranchWorkflowSession(sink(branch), source(branch));
    session.writeArtifact(PLAN_DRAFT_ARTIFACT, "reviewed");
    const a = createDraftReviewDecisions({
      cwd: root,
      sessionId: "a",
      session: () => session,
      entries: () => [],
      binding,
    });
    const prepared = a.prepare();
    assert.ok(prepared.ok);
    assert.ok(prepared.value.registration.open(requestId).ok);
    const staleBranch = [...branch];
    const staleSession = openBranchWorkflowSession(sink(staleBranch), source(staleBranch));
    const b = createDraftReviewDecisions({
      cwd: root,
      sessionId: "b",
      session: () => staleSession,
      entries: () => [],
      binding,
    });
    const stale = b.prepare();
    assert.ok(stale.ok);
    assert.ok(prepared.value.registration.attach(requestId, "upstream").ok);
    const path = join(sessionDataDir(root, "RID"), DRAFT_REVIEW_ARTIFACT);
    const advanced = readFileSync(path, "utf8");
    const refusal = stale.value.registration.open(successorId);
    assert.ok(!refusal.ok);
    assert.equal(refusal.reason, "invalid-state");
    assert.equal(readFileSync(path, "utf8"), advanced);
    const lock = join(sessionDataDir(root, "RID"), DRAFT_REVIEW_LOCK);
    assert.equal(existsSync(lock), true);
    // Orphan-looking opening bytes are not authority and cannot be laundered by the old pointer.
    writeFileSync(path, "{}");
    assert.equal(readDraftReview(session).ok, false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

function deferredVoid() {
  let settle: (() => void) | undefined;
  const promise = new Promise<void>((resolve) => {
    settle = resolve;
  });
  return {
    promise,
    resolve() {
      assert.ok(settle);
      settle();
    },
  };
}

function planEffects(f: ReturnType<typeof fixture>) {
  let active = true;
  let exits = 0;
  const requests: Parameters<PlanApprovalSaveDeps["backend"]["save"]>[0][] = [];
  const saved: PlanBackendSaveResult = {
    status: "saved",
    ref: {
      provider: "github",
      pr_id: "42",
      url: "https://example.test/42",
      labels: [],
      objective_id: "objective",
      base: null,
    },
    existed: false,
    updated: false,
    cached: true,
    nodeLink: { linked: true, node: "1.1", status: "in_progress", error: null },
  };
  const deps: PlanApprovalSaveDeps = {
    session: f.session,
    backend: {
      async save(request) {
        requests.push(request);
        return saved;
      },
    },
    gate: {
      isActive: () => active,
      exit() {
        active = false;
        exits += 1;
      },
    },
    async generateTitle() {
      return "Bound title";
    },
    capturePlanningPointer() {},
  };
  const complete = (cap: DraftReviewCapability) =>
    completePlanReview(
      { ...boundPlanSaveDeps(deps, cap), allowImplementHere: true },
      { outcome: { status: "approved", reviewId: id.reviewId }, plan: f.raw, edited: false },
      { source: "plan-draft", paramMismatch: false },
    );
  return { deps, requests, saved, complete, exits: () => exits };
}

for (const changed of ["source", "target"] as const) {
  test(`bound plan completion revalidates ${changed} AFTER title generation and before backend`, async () => {
    const f = fixture();
    try {
      f.open();
      const effects = planEffects(f);
      effects.deps.generateTitle = async () => {
        assert.equal(f.record().consumption.state, "dispatch", "intent precedes the title await");
        if (changed === "source") f.session.writeArtifact(f.name, "different source");
        else f.target({ digest: `sha256:${"b".repeat(64)}` });
        return "title";
      };
      const result = await f.decisions.dispatch({
        id,
        runId: "RID",
        approved: true,
        effect: "save",
        execute: effects.complete,
      });
      assert.ok(!result.ok);
      assert.equal(result.reason, `${changed}-changed`);
      assert.equal(effects.requests.length, 0);
      assert.equal(effects.exits(), 0);
      const c = f.record().consumption;
      assert.ok(c.state === "uncertain");
      assert.equal(c.reason, "effect-failed");
      assert.deepEqual(c.attempt.save, { state: "not-started" });
    } finally {
      f.dispose();
    }
  });
}

test("bound plan backend pause retains exclusion, binds node inputs, and releases only after delivery expectation", async () => {
  const f = fixture();
  try {
    f.target({ warmNodeClaim: { objective: "objective", node: "1.1" } });
    // Capture a new registration with the claim projection before opening.
    const prepared = f.prepare();
    assert.ok(prepared.registration.open(requestId).ok);
    assert.ok(prepared.registration.attach(requestId, id.reviewId).ok);
    f.session.apply({ kind: "record-node-claim", claim: { objective: "objective", node: "1.1" } });
    const effects = planEffects(f);
    const entered = deferredVoid();
    const release = deferredVoid();
    const save = effects.deps.backend.save;
    effects.deps.backend.save = async (request) => {
      const c = f.record().consumption;
      assert.ok(c.state === "dispatch");
      assert.deepEqual(c.attempt.save, { state: "started" });
      entered.resolve();
      await release.promise;
      return save(request);
    };
    let entry: unknown;
    const pending = f.decisions.dispatch({
      id,
      runId: "RID",
      approved: true,
      effect: "save",
      async execute(cap) {
        const result = await effects.complete(cap);
        assert.equal(result.status, "approvedSaved");
        assert.ok(result.status === "approvedSaved");
        assert.equal(result.save.gateExited, true);
        entry = f.tool(cap);
        return result;
      },
    });
    await entered.promise;
    const competing = f.decisions.mutate("manual-save", () =>
      assert.fail("competitor must not run"),
    );
    assert.ok(!competing.ok);
    assert.equal(competing.reason, "busy");
    assert.equal(effects.exits(), 0);
    release.resolve();
    const result = await pending;
    assert.ok(result.ok);
    assert.deepEqual(result.saveReceipt, { id: "42", url: "https://example.test/42" });
    assert.equal(effects.requests.length, 1);
    assert.equal(effects.requests[0]?.objectiveId, "objective");
    assert.equal(effects.requests[0]?.nodeId, "1.1");
    assert.equal(effects.requests[0]?.title, "Bound title");
    assert.equal(effects.requests[0]?.plan, f.raw.trim());
    assert.equal(effects.exits(), 1);
    assert.equal(f.session.nodeClaim(), null);
    assert.equal(existsSync(f.lock), false);
    f.persisted([entry]);
    const rewrite = f.decisions.mutate(
      "source-changed",
      (session) => session.writeArtifact(f.name, "next revision"),
      { draft: { subject: "plan", content: "next revision" } },
    );
    assert.ok(rewrite.ok, "the next mutation first observes persisted delivery");
    assert.equal(f.record().consumption.state, "consumed");
  } finally {
    f.dispose();
  }
});

test("a save receipt cannot authorize a gate effect after ownership is replaced during backend await", async () => {
  const f = fixture();
  try {
    f.open();
    const effects = planEffects(f);
    const save = effects.deps.backend.save;
    effects.deps.backend.save = async (request) => {
      const result = await save(request);
      rmSync(f.lock);
      const replacement = acquireDraftReviewLock(f.root, {
        sessionId: "other",
        runId: "RID",
        requestId: successorId,
      });
      assert.ok(replacement.kind === "acquired");
      replacement.claim.finish("retain");
      return result;
    };
    const result = await f.decisions.dispatch({
      id,
      runId: "RID",
      approved: true,
      effect: "save",
      execute: effects.complete,
    });
    assert.ok(!result.ok);
    assert.equal(result.reason, "ownership-lost");
    assert.deepEqual(result.saveReceipt, { id: "42", url: "https://example.test/42" });
    assert.equal(effects.exits(), 0);
    assert.equal(effects.requests.length, 1);
    assert.equal(f.record().consumption.state, "dispatch");
    assert.equal(existsSync(f.lock), true);
  } finally {
    f.dispose();
  }
});

for (const failure of ["gate-callback", "receipt-write", "ownership-loss"] as const) {
  test(`throwing receipt callback (${failure}) retains verified save facts and fences writes`, async () => {
    const f = fixture();
    try {
      f.open();
      const receipt = { id: "42", url: "https://example.test/42" };
      let saves = 0;
      let callbacks = 0;
      const result = await f.decisions.dispatch({
        id,
        runId: "RID",
        approved: true,
        effect: "save",
        async execute(capability) {
          await capability.save(
            async () => {
              saves++;
              return { receipt, value: "saved" };
            },
            () => {
              callbacks++;
              if (failure === "receipt-write") f.session.failNextWrite();
              if (failure === "ownership-loss") {
                rmSync(f.lock);
                writeFileSync(f.lock, "replacement owner");
              }
              throw new Error("controlled gate callback failure");
            },
          );
          assert.fail("a failed callback cannot continue to delivery");
        },
      });
      assert.ok(!result.ok);
      assert.equal(
        result.reason,
        failure === "receipt-write"
          ? "persistence-failed"
          : failure === "ownership-loss"
            ? "ownership-lost"
            : "io-error",
      );
      assert.deepEqual(result.saveReceipt, receipt);
      assert.equal(result.gateExited, false, "a throwing callback proves no gate exit");
      assert.equal(saves, 1);
      assert.equal(callbacks, 1);
      const c = f.record().consumption;
      if (failure === "gate-callback") {
        assert.ok(c.state === "uncertain");
        assert.equal(c.reason, "effect-failed", "the backend receipt was confirmed");
        assert.deepEqual(c.attempt.save, { state: "confirmed", ...receipt });
        assert.equal(c.attempt.delivery, null);
        assert.equal(existsSync(f.lock), false);
      } else {
        assert.ok(c.state === "dispatch");
        assert.deepEqual(c.attempt.save, { state: "started" });
        assert.equal(c.attempt.delivery, null);
        assert.equal(
          existsSync(f.lock),
          true,
          "no speculative write after persistence/ownership failure",
        );
        if (failure === "ownership-loss")
          assert.equal(readFileSync(f.lock, "utf8"), "replacement owner");
      }
      const retry = await f.decisions.mutateAsync("manual-save", async () =>
        assert.fail("no automatic save retry"),
      );
      assert.ok(!retry.ok);
      assert.equal(saves, 1);
    } finally {
      f.dispose();
    }
  });
}

for (const failure of ["receipt-write", "pointer-capture"] as const) {
  test(`confirmed plan save/gate survives ${failure} failure without replay`, async () => {
    const f = fixture();
    try {
      f.open();
      const effects = planEffects(f);
      if (failure === "receipt-write") {
        const save = effects.deps.backend.save;
        effects.deps.backend.save = async (request) => {
          const result = await save(request);
          f.session.failNextWrite();
          return result;
        };
      } else {
        effects.deps.capturePlanningPointer = () => {
          throw new Error("pointer capture unavailable");
        };
      }
      const result = await f.decisions.dispatch({
        id,
        runId: "RID",
        approved: true,
        effect: "save",
        execute: effects.complete,
      });
      assert.ok(!result.ok);
      assert.equal(result.reason, failure === "receipt-write" ? "persistence-failed" : "io-error");
      assert.deepEqual(result.saveReceipt, { id: "42", url: "https://example.test/42" });
      assert.equal(effects.requests.length, 1);
      assert.equal(effects.exits(), 1, "definitive save exits before fallible bookkeeping");
      assert.equal(result.gateExited, true, "gate fact survives even a failed receipt write");
      const c = f.record().consumption;
      if (failure === "receipt-write") {
        assert.ok(c.state === "dispatch");
        assert.deepEqual(c.attempt.save, { state: "started" });
        assert.equal(
          existsSync(f.lock),
          true,
          "failed state write retains claim with no speculative uncertainty write",
        );
      } else {
        assert.ok(c.state === "uncertain");
        assert.equal(c.reason, "effect-failed");
        assert.deepEqual(c.attempt.save, {
          state: "confirmed",
          id: "42",
          url: "https://example.test/42",
        });
      }
      const retry = await f.decisions.mutateAsync("manual-save", async () =>
        assert.fail("no blind retry"),
      );
      assert.ok(!retry.ok);
    } finally {
      f.dispose();
    }
  });
}

for (const subject of ["objective", "gist"] as const) {
  test(`bound ${subject} completion preserves structured policy and confirms one typed receipt`, async () => {
    const f = fixture(subject);
    try {
      const raw = JSON.stringify({
        schema_version: 1,
        prose: "Reviewed",
        title: "Title",
        ...(subject === "objective"
          ? {
              roadmap: [{ id: "1.1", description: "node", slug: "invisible" }],
              base: "develop",
              delivery: "stacked",
            }
          : { scope: "objective" }),
      });
      f.session.writeArtifact(f.name, raw);
      const prepared = f.prepare();
      assert.ok(prepared.registration.open(requestId).ok);
      assert.ok(prepared.registration.attach(requestId, id.reviewId).ok);
      let active = true;
      let exits = 0;
      const gate = {
        isActive: () => active,
        exit() {
          active = false;
          exits++;
        },
      };
      const requests: unknown[] = [];
      const receipt = {
        status: "saved" as const,
        id: "7",
        url: "https://example.test/7",
        existed: false,
      };
      const objective: ObjectiveBackend = {
        async create(request) {
          requests.push(request);
          return receipt;
        },
      };
      const gist: GistBackend = {
        async save(request) {
          requests.push(request);
          return { ...receipt, scope: "objective" };
        },
      };
      const result = await f.decisions.dispatch({
        id,
        runId: "RID",
        approved: true,
        effect: "save",
        async execute(cap) {
          if (subject === "objective") {
            const deps = boundObjectiveSaveDeps(
              {
                session: f.session,
                backend: objective,
                gate,
                resolveDreamGate: () => ({ kind: "absent" }),
              },
              cap,
            );
            const saved = await completeObjectiveReview({ status: "approved" }, () =>
              objectiveApprovalSave(deps),
            );
            assert.equal(saved.status, "approvedSave");
          } else {
            const deps = boundGistSaveDeps({ session: f.session, backend: gist, gate }, cap);
            const saved = await completeGistReview({ status: "approved" }, () =>
              gistApprovalSave(deps),
            );
            assert.equal(saved.status, "approvedSaved");
          }
          f.tool(cap);
        },
      });
      assert.ok(result.ok);
      assert.deepEqual(result.saveReceipt, { id: "7", url: "https://example.test/7" });
      assert.equal(exits, 1);
      assert.deepEqual(requests, [
        subject === "objective"
          ? {
              prose: "Reviewed",
              title: "Title",
              roadmap: [{ id: "1.1", description: "node", slug: "invisible" }],
              base: "develop",
              delivery: "stacked",
              runId: "RID",
            }
          : { prose: "Reviewed", title: "Title", scope: "objective", runId: "RID" },
      ]);
    } finally {
      f.dispose();
    }
  });
}

test("async eligibility mutation invalidates before awaiting and expires its explicit session capability", async () => {
  const f = fixture();
  try {
    f.open();
    const entered = deferredVoid();
    const release = deferredVoid();
    const operation = f.decisions.mutateAsync("manual-save", async (session) => {
      assert.deepEqual(f.record().consumption, { state: "invalidated", reason: "manual-save" });
      entered.resolve();
      await release.promise;
      session.apply({ kind: "clear-node-claim", claim: { objective: "objective", node: "1.1" } });
      // Store only the structural session slice, not a global exemption.
      return session;
    });
    await entered.promise;
    const refusal = f.registration.open(successorId);
    assert.ok(!refusal.ok);
    assert.equal(refusal.reason, "busy");
    release.resolve();
    const result = await operation;
    assert.ok(result.ok);
    assert.throws(() => result.value.writeArtifact(f.name, "late"));
    assert.equal(existsSync(f.lock), false);
  } finally {
    f.dispose();
  }
});

test("throwing current identity refuses ordinary mutation before acquisition or effects", async () => {
  const f = fixture();
  try {
    f.session.currentRunIdentity = () => {
      throw new Error("state unavailable");
    };
    const result = await f.decisions.mutateAsync("manual-save", async () =>
      assert.fail("no effects"),
    );
    assert.ok(!result.ok);
    assert.equal(result.reason, "io-error");
    assert.equal(existsSync(f.lock), false);
  } finally {
    f.dispose();
  }
});

test("bound completion with an unverified corrupted patch invokes backend once with original bytes only", async (t) => {
  const f = fixture();
  try {
    f.open();
    const effects = planEffects(f);
    const write = f.session.writeArtifact.bind(f.session);
    t.mock.method(
      f.session,
      "writeArtifact",
      (name: string, content: string, options?: { provenance: "strict" }) => {
        if (name !== PLAN_DRAFT_ARTIFACT) return write(name, content, options);
        const result = write(name, "# Partial corrupted patch", options);
        assert.ok(result.status === "applied" || result.status === "unchanged");
        return { status: "unverified", reason: "write_failed" };
      },
    );
    const result = await f.decisions.dispatch({
      id,
      runId: "RID",
      approved: true,
      effect: "save",
      async execute(cap) {
        const completed = await completePlanReview(
          { ...boundPlanSaveDeps(effects.deps, cap), allowImplementHere: true },
          {
            plan: f.raw,
            edited: false,
            outcome: {
              status: "approvedDirectEdits",
              diff: "@@ -2,1 +2,1 @@\n-# Reviewed 雪\n+# Edited 雪\n",
              rawFeedback: "FULL direct edits",
            },
          },
          { source: "plan-draft", paramMismatch: false },
        );
        assert.ok(completed.status === "approvedSaved");
        assert.equal(completed.directEditsFailed, true);
        assert.equal(completed.feedback, "FULL direct edits");
        f.tool(cap);
      },
    });
    assert.ok(result.ok);
    assert.equal(effects.requests.length, 1);
    assert.equal(effects.requests[0]?.plan, f.raw.trim());
    assert.equal(effects.exits(), 1);
    const artifact = f.session.readArtifact(f.name);
    assert.ok(artifact.status === "found");
    assert.equal(artifact.content, "# Partial corrupted patch");
  } finally {
    f.dispose();
  }
});

for (const runId of [null, "../unsafe", "RID"] as const) {
  test(`ordinary mutation requires a safe current-run namespace (${runId})`, async () => {
    const f = fixture();
    try {
      const session = openMemoryWorkflowSession({ runId });
      const decisions = createDraftReviewDecisions({
        cwd: f.root,
        sessionId: "test",
        session: () => session,
        entries: () => [],
      });
      let calls = 0;
      const outcome = await decisions.mutateAsync("manual-save", async () => {
        calls++;
      });
      assert.equal(outcome.ok, runId === "RID");
      assert.equal(calls, runId === "RID" ? 1 : 0);
      if (!outcome.ok) assert.equal(outcome.reason, "no-identity");
    } finally {
      f.dispose();
    }
  });
}

test("genuine routing drift at attach names the checkpoint and the changed component; the record invalidates without attaching", () => {
  const f = fixture();
  try {
    assert.ok(f.registration.open(requestId).ok);
    const current = f.drift(["main_config.issues.backend"]);
    const attached = f.registration.attach(requestId, id.reviewId);
    assert.ok(!attached.ok);
    assert.equal(attached.reason, "target-changed");
    assert.equal(
      attached.detail,
      `draft review refused: target-changed; checkpoint: attach; reviewed target: ${reviewedDigest}; current target: ${current}; changed components: main_config.issues.backend`,
    );
    assert.deepEqual(f.record().consumption, { state: "invalidated", reason: "target-changed" });
    assert.equal(f.record().correlation.review_id, null);
    assert.equal(existsSync(f.lock), false);
  } finally {
    f.dispose();
  }
});

test("genuine routing drift at open refuses before any record write, explained against the frozen snapshot", () => {
  const f = fixture();
  try {
    const current = f.drift(["worktree_config.workflow.base", "main_local.linear.api_key"]);
    const opened = f.registration.open(requestId);
    assert.ok(!opened.ok);
    assert.equal(opened.reason, "target-changed");
    assert.match(
      opened.detail,
      /^draft review refused: target-changed; checkpoint: open; reviewed target: sha256:a{64}; current target: /,
    );
    assert.ok(
      opened.detail.endsWith(
        `current target: ${current}; changed components: worktree_config.workflow.base, main_local.linear.api_key`,
      ),
    );
    const read = readDraftReview(f.session);
    assert.ok(read.ok && read.record === null, "nothing is opened for a drifted target");
    assert.equal(existsSync(f.lock), false);
  } finally {
    f.dispose();
  }
});

test("genuine drift at candidate dispatch reports several changed fields in fixed order with zero backend calls", async () => {
  for (const change of ["target", "subject"] as const) {
    const f = fixture();
    try {
      f.open();
      const current =
        change === "target"
          ? f.drift(["worktree_local.workflow.base", "main_local.linear.api_key"])
          : f.drift(["identity", "worktree_config.workflow.base", "worktree_local.workflow.base"], {
              subject: "gist",
            });
      let executed = 0;
      const result = await f.decisions.dispatch({
        id,
        runId: "RID",
        approved: true,
        effect: "save",
        execute: async () => {
          executed++;
          return "never";
        },
      });
      assert.ok(!result.ok);
      assert.equal(result.reason, change === "target" ? "target-changed" : "subject-changed");
      assert.equal(
        result.detail,
        `draft review refused: ${result.reason}; checkpoint: candidate; reviewed target: ${reviewedDigest}; current target: ${current}; changed components: ${
          change === "target"
            ? "worktree_local.workflow.base, main_local.linear.api_key"
            : "identity, worktree_config.workflow.base, worktree_local.workflow.base"
        }`,
      );
      assert.equal(executed, 0);
      assert.equal(result.saveReceipt, null);
      assert.equal(result.gateExited, false);
      assert.deepEqual(f.record().consumption, { state: "invalidated", reason: result.reason });
      assert.equal(existsSync(f.lock), false);
      // The invalidated record refuses a later candidate WITHOUT effects (unchanged transition table).
      const late = await f.decisions.dispatch({
        id,
        runId: "RID",
        approved: false,
        effect: "revision",
        execute: async () => assert.fail("late effect"),
      });
      assert.ok(!late.ok);
      assert.equal(late.reason, "invalid-state", "other-invalidated refuses without effects");
      assert.ok(!late.detail.includes("changed components"), "no drift story for a dead record");
    } finally {
      f.dispose();
    }
  }
});

test("genuine drift after the title await stops before the backend, explained at the save checkpoint; the dispatch turns uncertain", async () => {
  const f = fixture();
  try {
    f.open();
    let backend = 0;
    let current = "";
    const result = await f.decisions.dispatch({
      id,
      runId: "RID",
      approved: true,
      effect: "save",
      execute: async (cap) => {
        await Promise.resolve();
        current = f.drift(["main_config.issues.team"]);
        await cap.save(async () => {
          backend++;
          return { receipt: { id: "42", url: "url" }, value: "saved" };
        });
        return "unreachable";
      },
    });
    assert.ok(!result.ok);
    assert.equal(result.reason, "target-changed");
    assert.equal(
      result.detail,
      `draft review refused: target-changed; checkpoint: save; reviewed target: ${reviewedDigest}; current target: ${current}; changed components: main_config.issues.team`,
    );
    assert.equal(backend, 0);
    assert.equal(result.saveReceipt, null);
    const state = f.record().consumption;
    assert.equal(state.state, "uncertain");
    if (state.state === "uncertain") {
      assert.equal(state.reason, "effect-failed");
      assert.deepEqual(state.attempt.save, { state: "not-started" });
    }
    assert.equal(existsSync(f.lock), false);
  } finally {
    f.dispose();
  }
});

test("dispatch explanations need a matching activation-local baseline: a foreign coordinator, a rewritten digest, and an ended activation report unavailable", async () => {
  const f = fixture();
  try {
    f.open();
    // A coordinator that never opened this request has no baseline (never reconstructed from disk).
    const foreign = createDraftReviewDecisions({
      cwd: f.root,
      sessionId: "foreign",
      session: () => f.session,
      entries: () => [],
      binding: f.binding,
    });
    const current = f.drift(["main_config.issues.backend"]);
    const unexplained = await foreign.dispatch({
      id,
      runId: "RID",
      approved: false,
      effect: "revision",
      execute: async () => assert.fail("no effect"),
    });
    assert.ok(!unexplained.ok);
    assert.equal(
      unexplained.detail,
      `draft review refused: target-changed; checkpoint: candidate; reviewed target: ${reviewedDigest}; current target: ${current}; changed components: unavailable (no matching diagnostic baseline)`,
    );
    assert.deepEqual(f.record().consumption, { state: "invalidated", reason: "target-changed" });
  } finally {
    f.dispose();
  }
  const g = fixture();
  try {
    g.open();
    // Same request ID, but the persisted target digest is not the one this activation opened.
    const record = g.record();
    const rewritten = {
      ...record,
      correlation: {
        ...record.correlation,
        target: { ...record.correlation.target, digest: `sha256:${"e".repeat(64)}` },
      },
    };
    assert.equal(
      g.session.writeArtifact(DRAFT_REVIEW_ARTIFACT, encodeDraftReview(rewritten)).status,
      "applied",
    );
    const result = await g.decisions.dispatch({
      id,
      runId: "RID",
      approved: false,
      effect: "revision",
      execute: async () => assert.fail("no effect"),
    });
    assert.ok(!result.ok);
    assert.equal(result.reason, "target-changed");
    assert.match(
      result.detail,
      /changed components: unavailable \(no matching diagnostic baseline\)$/,
    );
    assert.match(
      result.detail,
      new RegExp(`reviewed target: sha256:e{64}; current target: ${reviewedDigest}`),
    );
  } finally {
    g.dispose();
  }
  const h = fixture();
  try {
    h.open();
    assert.ok(h.decisions.end([]).ok);
    const current = h.drift(["environment"]);
    const ended = await h.decisions.dispatch({
      id,
      runId: "RID",
      approved: false,
      effect: "revision",
      execute: async () => assert.fail("no effect"),
    });
    assert.ok(!ended.ok);
    assert.equal(ended.reason, "invalid-state", "an ended activation grants nothing");
    assert.ok(!ended.detail.includes(current));
  } finally {
    h.dispose();
  }
});

test("a successor opening rebinds the baseline: the successor's drift is explained, the predecessor is merely superseded", async () => {
  const f = fixture();
  try {
    f.open();
    const successor = f.prepare().registration;
    assert.ok(successor.open(successorId).ok);
    assert.ok(successor.attach(successorId, "next").ok);
    const current = f.drift(["git_config"]);
    const stale = await f.decisions.dispatch({
      id,
      runId: "RID",
      approved: false,
      effect: "revision",
      execute: async () => assert.fail("predecessor effect"),
    });
    assert.ok(!stale.ok);
    assert.equal(stale.reason, "superseded");
    assert.ok(!stale.detail.includes("changed components"));
    const explained = await f.decisions.dispatch({
      id: { requestId: successorId, reviewId: "next" },
      runId: "RID",
      approved: false,
      effect: "revision",
      execute: async () => assert.fail("successor effect"),
    });
    assert.ok(!explained.ok);
    assert.equal(
      explained.detail,
      `draft review refused: target-changed; checkpoint: candidate; reviewed target: ${reviewedDigest}; current target: ${current}; changed components: git_config`,
    );
  } finally {
    f.dispose();
  }
});

test("a routing-config file that fails to parse refuses with its file role and never echoes the secret it carries", async () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "perk-draft-decisions-secret-")));
  const session = openMemoryWorkflowSession({ runId: "RID" });
  session.draftReviewContext = () => ({
    ok: true,
    runId: "RID",
    subject: "plan",
    warmNodeClaim: null,
  });
  session.writeArtifact(PLAN_DRAFT_ARTIFACT, "# Reviewed\n");
  const files = new Map<string, string>();
  const secret = "lin_api_SECRET_9f8e7d6c";
  const decisions = createDraftReviewDecisions({
    cwd: root,
    sessionId: "parent",
    session: () => session,
    entries: () => [],
    binding: (current) =>
      captureDraftReviewBinding(root, current, {
        git: () => ({
          worktreeRoot: root,
          gitDir: join(root, ".git"),
          gitCommonDir: join(root, ".git"),
          configBytes: new Uint8Array(),
        }),
        read: (path) => {
          const text = files.get(path);
          return text === undefined ? null : Buffer.from(text);
        },
        environment: () => ({}),
      }),
  });
  try {
    files.set(join(root, ".perk", "local.toml"), `[linear]\napi_key = "${secret}"\n`);
    const prepared = decisions.prepare();
    assert.ok(prepared.ok);
    assert.ok(prepared.value.registration.open(requestId).ok);
    assert.ok(prepared.value.registration.attach(requestId, id.reviewId).ok);
    // The secret file becomes unparseable (a bare, unquoted key) while the review is pending.
    files.set(join(root, ".perk", "local.toml"), `[linear]\napi_key = ${secret}\n`);
    const result = await decisions.dispatch({
      id,
      runId: "RID",
      approved: true,
      effect: "save",
      execute: async () => assert.fail("no effect"),
    });
    assert.ok(!result.ok);
    assert.equal(result.reason, "io-error");
    assert.equal(
      result.detail,
      "draft review refused: io-error; routing config worktree_local/main_local: TOML parse failed",
    );
    assert.ok(!result.detail.includes(secret));
    assert.ok(!JSON.stringify(readDraftReview(session)).includes(secret));
    const read = readDraftReview(session);
    assert.ok(read.ok && read.record);
    assert.equal(read.record.consumption.state, "pending", "a capture refusal is not a verdict");
    // A well-formed rotation of the same secret IS routing drift, explained by component only.
    files.set(join(root, ".perk", "local.toml"), `[linear]\napi_key = "${secret}-rotated"\n`);
    const rotated = await decisions.dispatch({
      id,
      runId: "RID",
      approved: true,
      effect: "save",
      execute: async () => assert.fail("no effect"),
    });
    assert.ok(!rotated.ok);
    assert.equal(rotated.reason, "target-changed");
    assert.match(
      rotated.detail,
      /checkpoint: candidate;.*changed components: main_local\.linear\.api_key$/,
    );
    assert.ok(!rotated.detail.includes(secret));
    assert.ok(!JSON.stringify(readDraftReview(session)).includes(secret));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
