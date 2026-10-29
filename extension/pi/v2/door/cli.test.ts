// V5 — the host CLI in process (docs/design/pi-durable-v2-foundations.md §11, contracts.md §8.77):
// `runCli` over real temp git repos and SQLite stores with the production faux worker drives
// `start` → `status` → `reply` to completion, reports `owner_busy` while another owner holds the
// lock, `incompatible` for an unknown execution, `observation_failed` for a missing ref, `refused`
// for a stale reply, `ok` for a cancel, and a usage error for every malformed invocation.

import assert from "node:assert/strict";
import { join } from "node:path";
import { test } from "node:test";
import { parseCliArgs, runCli } from "../door/cli.ts";
import type { Envelope } from "../door/envelope.ts";
import type { ViewSnapshot } from "../door/snapshot.ts";
import { FIXTURE_ACTOR } from "../kernel/fixture.ts";
import { cancelOpId, continuationOpId, replyOpId } from "../kernel/identity.ts";
import { acquireOwnerLock } from "../store/ownerLock.ts";
import { decisionIdOf, E } from "../testing/binding.ts";
import { cliArgv, doorTarget } from "../testing/door.ts";
import { CASE_TIMEOUT_MS, tempDir } from "../testing/durable.ts";
import { commitAll, writeFiles } from "../testing/subject.ts";
import { withStore } from "../testing/worker.ts";

function viewOf(envelope: Envelope): ViewSnapshot {
  const status = envelope.status;
  if (status === null || !("diagnostics" in status)) {
    assert.fail(`expected a view snapshot: ${JSON.stringify(envelope)}`);
  }
  return status;
}

test("V5: start, status and reply drive an execution to completion over the faux worker", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const target = await doorTarget(t);
  const started = await target.envelope("start", target.startOptions);
  assert.equal(started.outcome, "pending_decision", JSON.stringify(started));
  assert.equal(started.verb, "start");
  assert.equal(started.executionId, E);
  assert.equal(started.epoch, 1);
  assert.equal(started.receipt, null);
  const view = viewOf(started);
  assert.equal(view.state, "waiting");
  assert.equal(view.waitReason, "pending_decision");
  assert.equal(view.observation?.tree, target.tree);
  assert.deepEqual(
    view.assignments.map((row) => [row.role, row.current, row.attempts[0]?.ending?.end]),
    [
      ["a", true, "accepted"],
      ["b", true, "accepted"],
    ],
  );
  assert.ok(view.assignments.every((row) => row.acceptedOutcomeId !== null));
  const d = decisionIdOf(target.tree);
  assert.deepEqual(view.decision, {
    decisionId: d,
    subjectDigest: target.tree,
    allowedActions: ["approve", "reject"],
    actor: FIXTURE_ACTOR,
  });
  // Each role's faux worker ran in its own worker conversation.
  await withStore(target.store, async (store) => {
    assert.equal((await store.workers()).length, 2, "two worker conversations");
  });

  const status = await target.envelope("status");
  assert.equal(status.outcome, "ok");
  assert.equal(status.epoch, 2);
  assert.equal(viewOf(status).state, "waiting");
  assert.equal(viewOf(status).waitReason, "pending_decision");

  const reply = { decision: d, action: "approve", actor: FIXTURE_ACTOR };
  const replied = await target.envelope("reply", reply);
  assert.equal(replied.outcome, "ok", JSON.stringify(replied));
  assert.equal(viewOf(replied).state, "completed");
  assert.equal(viewOf(replied).decision, null);
  const receipt = replied.receipt;
  assert.equal(receipt?.kind, "reply");
  assert.equal(receipt?.opId, replyOpId(d));
  assert.equal(receipt?.continuation?.opId, continuationOpId(d));
  assert.equal(typeof receipt?.continuation?.taskId, "number");

  const again = await target.envelope("reply", reply);
  assert.equal(again.outcome, "ok");
  assert.deepEqual(again.receipt, receipt, "a repeated reply returns the same receipt");
});

test("V5: status while another owner holds the lock is owner_busy carrying its epoch", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const target = await doorTarget(t);
  await target.envelope("start", target.startOptions);
  const lock = await acquireOwnerLock(target.store);
  assert.equal(lock.kind, "acquired");
  try {
    const busy = await target.envelope("status");
    assert.deepEqual(busy, {
      envelope: 1,
      outcome: "owner_busy",
      verb: "status",
      executionId: E,
      epoch: lock.epoch,
      status: null,
      receipt: null,
      refusal: null,
      mismatch: null,
      error: null,
    });
  } finally {
    if (lock.kind === "acquired") await lock.release();
  }
});

test("V5: run and status on an unknown execution are incompatible with no epoch", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const target = await doorTarget(t);
  const missing = { store: join(await tempDir(t, "perk-v2-door-"), "absent") };
  for (const verb of ["run", "status"] as const) {
    const envelope = await target.envelope(verb, missing);
    assert.equal(envelope.outcome, "incompatible", verb);
    assert.equal(envelope.epoch, null);
    assert.deepEqual(envelope.status, { state: "incompatible" });
    assert.deepEqual(envelope.mismatch, {
      field: "manifest_missing",
      expected: null,
      found: null,
    });
  }
});

test("V5: start with a nonexistent ref is observation_failed", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const target = await doorTarget(t);
  const failed = await target.envelope("start", {
    ...target.startOptions,
    ref: "refs/heads/missing",
  });
  assert.equal(failed.outcome, "observation_failed");
  assert.equal(failed.epoch, 1);
  assert.equal(failed.status, null);
  assert.match(failed.error?.message ?? "", /does not resolve to a commit/);
});

test("V5: a reply after the tracked ref moved to a new tree is refused stale_subject", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const target = await doorTarget(t);
  await target.envelope("start", target.startOptions);
  writeFiles(target.repo, { "a.txt": "changed\n" });
  commitAll(target.repo, "c2");
  const refused = await target.envelope("reply", {
    decision: decisionIdOf(target.tree),
    action: "approve",
    actor: FIXTURE_ACTOR,
  });
  assert.equal(refused.outcome, "refused", JSON.stringify(refused));
  assert.equal(refused.refusal?.reason, "stale_subject");
  assert.equal(refused.status, null);
});

test("V5: cancel is ok cancelled with the cancellation receipt", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const target = await doorTarget(t);
  await target.envelope("start", target.startOptions);
  const cancelled = await target.envelope("cancel", { reason: "operator stop" });
  assert.equal(cancelled.outcome, "ok");
  assert.equal(viewOf(cancelled).state, "cancelled");
  assert.deepEqual(viewOf(cancelled).cancellation, { reason: "operator stop" });
  assert.deepEqual(cancelled.receipt, {
    opId: cancelOpId(E),
    kind: "cancellation",
    continuation: null,
  });
});

test("V5: every malformed invocation is a usage error", async () => {
  const common = {
    store: "/abs/store",
    execution: E,
    "repo-identity": "/abs/repo/.git",
  };
  const usageOf = (argv: string[]): string => {
    const parsed = parseCliArgs(argv);
    assert.equal(parsed.kind, "usage", JSON.stringify(argv));
    return parsed.kind === "usage" ? parsed.message : "";
  };
  assert.match(usageOf(cliArgv("bogus", common)), /unknown verb/);
  assert.match(usageOf(cliArgv("status", common).slice(1)), /exactly one verb/);
  assert.match(usageOf([...cliArgv("status", common), "run"]), /exactly one verb/);
  assert.match(usageOf(cliArgv("start", { ...common, repo: "/r" })), /requires --ref/);
  assert.match(usageOf(cliArgv("cancel", common)), /requires --reason/);
  assert.match(
    usageOf(cliArgv("reply", { ...common, decision: "d", action: "approve" })),
    /requires --actor/,
  );
  assert.match(usageOf(cliArgv("run", { ...common, reason: "x" })), /not an option of run/);
  assert.match(usageOf(cliArgv("status", { ...common, repo: "/r" })), /not an option of status/);
  assert.match(usageOf(cliArgv("status", { ...common, store: "relative/store" })), /not absolute/);
  assert.match(
    usageOf(cliArgv("status", { ...common, "repo-identity": "repo/.git" })),
    /not absolute/,
  );
  assert.match(
    usageOf(cliArgv("status", { ...common, execution: "not-a-ulid" })),
    /not an execution id/,
  );
  assert.match(usageOf(cliArgv("cancel", { ...common, reason: "" })), /--reason is empty/);
  assert.match(usageOf([...cliArgv("status", common), "--bogus=1"]), /bogus/);
  assert.match(usageOf(["status", "--store"]), /store/);
  // A value that itself starts with `--` survives the `--name=value` form.
  const parsed = parseCliArgs(cliArgv("cancel", { ...common, reason: "--not-an-option" }));
  assert.ok(parsed.kind === "command" && parsed.command.verb === "cancel");
  assert.equal(parsed.command.verb === "cancel" ? parsed.command.reason : "", "--not-an-option");
  // runCli returns the usage error without touching anything.
  assert.deepEqual(await runCli(cliArgv("bogus", common)), {
    kind: "usage",
    message: 'unknown verb "bogus"',
  });
});
