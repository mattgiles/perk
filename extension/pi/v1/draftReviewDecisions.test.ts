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
import { OBJECTIVE_DRAFT_ARTIFACT } from "../../authoring/objective/draft.ts";
import { PLAN_DRAFT_ARTIFACT } from "../../authoring/plan/draft.ts";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import type { DraftReviewBinding } from "../../session/draftReviewBinding.ts";
import {
  DRAFT_REVIEW_ARTIFACT,
  deliveryMarker,
  type ReviewSubject,
  readDraftReview,
} from "../../session/draftReviewState.ts";
import { sessionDataDir } from "../../substrate/cache.ts";
import { acquireDraftReviewLock, DRAFT_REVIEW_LOCK } from "../../substrate/draftReviewLock.ts";
import { type BranchEntry, WORKFLOW_STATE_TYPE } from "../../substrate/workflowState.ts";
import { openMemoryWorkflowSession } from "../../testing/memoryWorkflowSession.ts";
import { createDraftReviewDecisions, type DraftReviewCapability } from "./draftReviewDecisions.ts";

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
    dispose() {
      rmSync(root, { recursive: true, force: true });
    },
  };
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
