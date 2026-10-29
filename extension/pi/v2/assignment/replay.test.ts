// A5 — the refusals hold for a tool replayed after a crash, and a crash never duplicates work
// (docs/design/pi-durable-v2-foundations.md §12 the native assignment, P4, P7, P9). Binding-level
// over SQLite: a first process runs until a chosen point, its storage is cut off (a crash, not a
// close), and a second process over the same file — the same faux catalog, a fresh composition —
// recovers. A report blocked before acceptance reruns against a tampered snapshot and is refused;
// a report whose acceptance landed reruns into a replay; interrupted escaping `ls`/`grep` calls
// rerun into the same refusal; and a worker submission whose admission landed before its mapping
// is deduplicated by request id, mapped once, and answered by one run. Controls show the second
// process really reran: its env factory and verifier were called and the results are its own.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { EnvTarget, HarnessOptions } from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { DURABLE_MAP_KIND, OUTCOME_KIND } from "../durable/documents.ts";
import { type AttemptEnding, readAttemptEndings } from "../durable/ending.ts";
import { operate } from "../durable/operate.ts";
import { type ReadRecordSet, readRecords } from "../durable/records.ts";
import {
  type Composition,
  composeProgram,
  expectedManifest,
  type HostOptions,
  STORE_DATABASE,
} from "../host.ts";
import { acceptReportOpId, submitOpId } from "../kernel/identity.ts";
import { type FixtureProgramOptions, fixtureProgram } from "../program.ts";
import { verifySnapshot } from "../subject/snapshot.ts";
import { expectApplied, ofType, type Role, storeDocuments } from "../testing/binding.ts";
import {
  CASE_TIMEOUT_MS,
  crashable,
  fauxSetup,
  type Opened,
  type Setup,
  waitFor,
} from "../testing/durable.ts";
import { HOST_NOW, hostOptions } from "../testing/host.ts";
import {
  call,
  crashAfterCommit,
  createsDocument,
  FINAL,
  fixtureAttemptId,
  fixtureSubject,
  openProgramHarness,
  type Reported,
  type RoleScripts,
  reportCall,
  roleScript,
  round,
  type Subject,
  snapshotTamper,
  withStore,
  writesSubmission,
} from "../testing/worker.ts";

type Cut = { readonly crash: () => void };

type FirstProcess = {
  readonly subject: Subject;
  readonly setup: Setup;
  readonly script: ReturnType<typeof roleScript>;
  readonly opened: Opened;
  readonly cut: Cut;
};

function optionsFor(store: string, program: FixtureProgramOptions): HostOptions {
  return hostOptions(store, fixtureProgram(program));
}

/**
 * Observe a fixture subject, open the first process over `wrap(storage)` with `program`, commit
 * `start` and resume. The caller waits for its point, then cuts the process off.
 */
async function firstProcess(
  t: Parameters<typeof fixtureSubject>[0],
  scripts: (tree: string) => RoleScripts,
  program: (subject: Subject, setup: Setup) => Omit<FixtureProgramOptions, "models">,
  wrap: (
    inner: Awaited<ReturnType<typeof openNodeSqliteStorage>>,
    subject: Subject,
  ) => { storage: Parameters<typeof openProgramHarness>[1] } & Cut,
  env?: (composition: Composition, subject: Subject) => HarnessOptions["env"],
): Promise<FirstProcess> {
  const subject = await fixtureSubject(t);
  const observation = await subject.observe();
  assert.equal(observation.kind, "observed");
  if (observation.kind !== "observed") throw new Error("unobserved");
  const setup = fauxSetup();
  const script = roleScript(setup.faux, subject.tree, scripts(subject.tree));
  const options = optionsFor(subject.store, {
    models: setup.models,
    ...program(subject, setup),
  });
  const composition = composeProgram(options);
  const wired =
    env === undefined ? composition : { ...composition, env: env(composition, subject) };
  const cut = wrap(await openNodeSqliteStorage(`${subject.store}/${STORE_DATABASE}`), subject);
  const opened = await openProgramHarness(t, cut.storage, wired, []);
  expectApplied(
    await operate(
      { harness: opened.harness, executionConversationId: opened.root.id, deps: composition.deps },
      {
        type: "start",
        manifest: expectedManifest(composition.definitions, options, HOST_NOW),
        observation: observation.facts,
      },
    ),
  );
  opened.harness.resume();
  return { subject, setup, script, opened, cut };
}

/** Wait for the first process's crash point; a miss fails with the scripts' state. */
async function crashedWithin(first: FirstProcess): Promise<void> {
  const { crashed } = first.cut as ReturnType<typeof crashAfterCommit>;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const missed = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      const { script } = first;
      reject(
        new Error(
          `the crash point was not reached: consumed a=${script.consumed("a")} b=${script.consumed("b")}, strays=${script.strays()}`,
        ),
      );
    }, 10_000);
  });
  try {
    await Promise.race([crashed, missed]);
  } finally {
    clearTimeout(timer);
  }
}

function plainCrashable(t: Parameters<typeof fixtureSubject>[0]) {
  return (inner: Awaited<ReturnType<typeof openNodeSqliteStorage>>) => crashable(t, inner);
}

type Recovered = {
  readonly records: ReadRecordSet;
  readonly endings: ReadonlyMap<string, AttemptEnding>;
  readonly verifierCalls: number;
  readonly envCalls: number;
  readonly reports: Reported[];
};

/** Cut the first process off, open the second over the same file, and run it to quiescence. */
async function recover(
  t: Parameters<typeof fixtureSubject>[0],
  first: FirstProcess,
): Promise<Recovered> {
  first.cut.crash();
  first.opened.abandon();
  let verifierCalls = 0;
  let envCalls = 0;
  const options = optionsFor(first.subject.store, {
    models: first.setup.models,
    verifier: (storeDir, tree, digest) => {
      verifierCalls++;
      return verifySnapshot(storeDir, tree, digest);
    },
  });
  const composition = composeProgram(options);
  const inner = composition.env;
  assert.ok(inner !== undefined);
  const counted: Composition = {
    ...composition,
    env: (target, context) => {
      envCalls++;
      return inner(target, context);
    },
  };
  const reports: Reported[] = [];
  const storage = await openNodeSqliteStorage(`${first.subject.store}/${STORE_DATABASE}`);
  const opened = await openProgramHarness(t, storage, counted, reports);
  opened.harness.resume();
  await waitFor(() => !opened.harness.wake().active, 20_000);
  const records = await readRecords(opened.harness);
  const endings = await readAttemptEndings(opened.harness, records);
  await opened.dispose();
  return { records, endings, verifierCalls, envCalls, reports };
}

async function workerResults(store: string, records: ReadRecordSet, role: Role, tree: string) {
  return withStore(store, async (view) => {
    const worker = records.durableMap.get(fixtureAttemptId(role, tree));
    assert.ok(worker !== undefined, `role ${role}: a worker`);
    return view.toolResults(worker.durableId);
  });
}

function outcomesOf(records: ReadRecordSet, role: Role, tree: string) {
  return ofType(records.records, "report-outcome").filter(
    (outcome) => outcome.attemptId === fixtureAttemptId(role, tree),
  );
}

test("A5 (i): a report blocked before acceptance reruns after a crash and is refused", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  let blocked = 0;
  const first = await firstProcess(
    t,
    (tree) => ({ a: [reportCall(tree), FINAL], b: [reportCall(tree), FINAL] }),
    () => ({
      onVerify: async (point) => {
        if (point !== "acceptance") return;
        blocked++;
        await new Promise(() => {});
      },
    }),
    plainCrashable(t),
  );
  await waitFor(() => blocked === 2);
  snapshotTamper(first.subject.store, first.subject.tree).tamper();
  const recovered = await recover(t, first);
  const { tree, store } = first.subject;
  assert.deepEqual(ofType(recovered.records.records, "report-outcome"), [], "nothing accepted");
  for (const role of ["a", "b"] as const) {
    const ending = recovered.endings.get(fixtureAttemptId(role, tree));
    assert.equal(ending?.end, "repair", `role ${role}`);
    if (ending?.end === "repair") assert.equal(ending.cause, "snapshot_tampered");
    const results = await workerResults(store, recovered.records, role, tree);
    const report = results.filter((result) => result.message.toolName === "report");
    assert.equal(report.length, 1, `role ${role}: one report result`);
    assert.equal(report[0]?.message.isError, true);
    assert.deepEqual(
      report[0]?.diagnostics.map((diagnostic) => diagnostic.code),
      ["perk.v2.refusal:snapshot_tampered"],
    );
    assert.equal(first.script.consumed(role), 1, `role ${role}: no further model request`);
  }
  assert.ok(recovered.verifierCalls >= 2, "the second process verified (the reruns are its own)");
  assert.ok(recovered.envCalls >= 1, "the second process built environments");
});

test("A5 (ii): a crash right after the acceptance commit reruns into a replay", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const first = await firstProcess(
    t,
    (tree) => ({ a: [reportCall(tree), FINAL], b: [reportCall(tree), reportCall(tree)] }),
    () => ({}),
    (inner, subject) =>
      crashAfterCommit(t, inner, (writes) =>
        createsDocument(
          writes,
          OUTCOME_KIND,
          acceptReportOpId(fixtureAttemptId("a", subject.tree)),
        ),
      ),
  );
  await crashedWithin(first);
  const { tree, store } = first.subject;
  // At the crash the outcome has landed and the tool result has not.
  const landed = await storeDocuments(`${store}/${STORE_DATABASE}`);
  assert.ok(landed.get(OUTCOME_KIND)?.has(acceptReportOpId(fixtureAttemptId("a", tree))));
  const workerOfA = (await storeDocuments(`${store}/${STORE_DATABASE}`))
    .get(DURABLE_MAP_KIND)
    ?.get(fixtureAttemptId("a", tree));
  const conversationOfA = workerOfA?.durableId;
  assert.equal(typeof conversationOfA, "number");
  const before = await withStore(store, async (view) =>
    (await view.toolResults(Number(conversationOfA))).filter(
      (result) => result.message.toolName === "report",
    ),
  );
  assert.deepEqual(before, [], "role a committed no report result before the crash");
  const recovered = await recover(t, first);
  const outcomes = outcomesOf(recovered.records, "a", tree);
  assert.equal(outcomes.length, 1, "exactly one outcome");
  assert.deepEqual(recovered.endings.get(fixtureAttemptId("a", tree)), {
    end: "accepted",
    outcomeId: outcomes[0]?.opId,
  });
  assert.equal(recovered.endings.get(fixtureAttemptId("b", tree))?.end, "accepted");
  assert.equal(outcomesOf(recovered.records, "b", tree).length, 1);
  assert.equal(first.script.consumed("a"), 1, "no further model request for role a");
  assert.equal(first.script.leftover("a"), 1);
  const report = (await workerResults(store, recovered.records, "a", tree)).filter(
    (result) => result.message.toolName === "report",
  );
  assert.equal(report.length, 1, "the rerun's result is the only one (the crash lost the first)");
  assert.equal(report[0]?.message.isError, false);
  assert.match(report[0]?.text ?? "", /^accepted .*\/accept-report$/);
  assert.ok(recovered.verifierCalls >= 1, "the second process ran (settle verified)");
});

/** Whether the env target is role `role`'s worker conversation over `tree`. */
async function isWorkerOf(target: EnvTarget, role: Role, tree: string): Promise<boolean> {
  const { durableMap } = await readRecords(target.read);
  const row = durableMap.get(fixtureAttemptId(role, tree));
  return row?.durableKind === "conversation" && row.durableId === target.conversationId;
}

test("A5 (iii): interrupted escaping ls and grep rerun into the same refusal", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  let armed = false;
  let blocked = 0;
  const first = await firstProcess(
    t,
    (tree) => ({
      a: [
        async () => {
          armed = true;
          return round(
            call("ls", { path: ".." }, "e1"),
            call("grep", { text: "alpha", path: ".." }, "e2"),
          );
        },
        reportCall(tree),
      ],
      b: [reportCall(tree), reportCall(tree)],
    }),
    () => ({}),
    plainCrashable(t),
    (composition, subject) => {
      const inner = composition.env;
      assert.ok(inner !== undefined);
      return async (target, context) => {
        if (armed && (await isWorkerOf(target, "a", subject.tree))) {
          blocked++;
          return new Promise(() => {});
        }
        return inner(target, context);
      };
    },
  );
  await waitFor(() => blocked === 2);
  const { tree, store } = first.subject;
  const recovered = await recover(t, first);
  assert.ok(recovered.envCalls >= 2, "the second process built the reruns' environments");
  const results = await workerResults(store, recovered.records, "a", tree);
  const escapes = results
    .filter((result) => result.message.toolName !== "report")
    .map((result) => [result.message.toolCallId, result.message.isError, result.diagnostics])
    .sort(([x], [y]) => String(x).localeCompare(String(y)));
  assert.deepEqual(
    escapes.map(([id, isError]) => [id, isError]),
    [
      ["e1", true],
      ["e2", true],
    ],
  );
  for (const result of results.filter((candidate) => candidate.message.toolName !== "report")) {
    assert.match(result.text, /escapes the snapshot root/);
  }
  assert.equal(recovered.endings.get(fixtureAttemptId("a", tree))?.end, "accepted");
  assert.equal(first.script.consumed("a"), 2);
});

test("A5 (iv): a crash between the worker submission's admission and its mapping submits once", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const first = await firstProcess(
    t,
    (tree) => ({ a: [reportCall(tree), FINAL], b: [reportCall(tree), reportCall(tree)] }),
    () => ({}),
    (inner, subject) =>
      crashAfterCommit(t, inner, (writes) =>
        writesSubmission(writes, submitOpId(fixtureAttemptId("a", subject.tree))),
      ),
  );
  await crashedWithin(first);
  const { tree, store } = first.subject;
  const attemptId = fixtureAttemptId("a", tree);
  // At the crash the admission has landed and the mapping has not.
  const rows = (await storeDocuments(`${store}/${STORE_DATABASE}`)).get(DURABLE_MAP_KIND);
  assert.ok(rows?.has(attemptId), "the worker conversation is mapped");
  assert.equal(rows?.has(submitOpId(attemptId)), false, "the submission is not mapped yet");
  const recovered = await recover(t, first);
  const worker = recovered.records.durableMap.get(attemptId);
  const mapped = recovered.records.durableMap.get(submitOpId(attemptId));
  assert.equal(worker?.durableKind, "conversation");
  assert.equal(mapped?.durableKind, "submission");
  const { submissions, runs } = await withStore(store, async (view) => {
    assert.ok(worker !== undefined);
    return {
      submissions: await view.submissions(worker.durableId),
      runs: await view.tasks(worker.durableId, "pi.generation"),
    };
  });
  assert.deepEqual(
    submissions.map((record) => [record.id, record.requestId, record.status]),
    [[mapped?.durableId, submitOpId(attemptId), "done"]],
    "exactly one submission, the mapped one",
  );
  assert.equal(runs.length, 1, "no second run");
  const outcomes = outcomesOf(recovered.records, "a", tree);
  assert.equal(outcomes.length, 1);
  assert.deepEqual(recovered.endings.get(attemptId), {
    end: "accepted",
    outcomeId: outcomes[0]?.opId,
  });
  assert.equal(first.script.consumed("a"), 1, "one model request for role a");
});
