// The host-program composition (docs/design/pi-durable-v2-foundations.md §10 the host): one
// composition per host call, whatever the outcome; an assignment extension that would replace an
// installed one, or a malformed task set, is refused with `RangeError` before any lock or file is
// touched; the manifest's definitions correspond to the registry by construction; the expected
// manifest of the fake program is exactly the binding fixture's; and the assignment's model catalog
// and environment factory reach `Harness.open` (an empty catalog and no environment by default).

import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { createModels } from "@earendil-works/pi-ai/models";
import { type AnyTask, defineTask, Harness, type HarnessOptions } from "@earendil-works/pi-durable";
import { V2_DOCUMENTS } from "../durable/documents.ts";
import { BINDING_EXTENSION_NAME, STEP_TASK_NAME } from "../durable/tasks.ts";
import {
  composeProgram,
  expectedManifest,
  type HostProgram,
  type OpenHarness,
  readStatus,
  runHost,
} from "../host.ts";
import { FAKE_ASSIGNMENT_NAME, manifest, policyA } from "../testing/binding.ts";
import { CASE_TIMEOUT_MS } from "../testing/durable.ts";
import {
  expectIncompatible,
  expectQuiescent,
  expectStatus,
  fakeProgram,
  HOST_NOW,
  hostOptions,
  observed,
  storeIn,
} from "../testing/host.ts";

/** A do-nothing task named `name`. */
function taskNamed(name: string): AnyTask {
  return defineTask<null, { phase: "run" }, null>({
    name,
    version: 1,
    initial: () => ({ phase: "run" }),
    phases: { run: async () => {} },
    abort: async () => {},
  });
}

/** `program`, counting how often its assignment factory runs. */
function counted(program: HostProgram): { program: HostProgram; calls(): number } {
  let calls = 0;
  return {
    program: {
      ...program,
      assignment: (context) => {
        calls++;
        return program.assignment(context);
      },
    },
    calls: () => calls,
  };
}

test("one composition per host call, whatever the outcome", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const cases: [string, (options: ReturnType<typeof hostOptions>) => Promise<unknown>][] = [
    [
      "start",
      async (options) =>
        expectQuiescent(await runHost(options, { type: "start", observe: observed() })),
    ],
    ["status", async (options) => expectStatus(await readStatus(options))],
    [
      "a refused start",
      async (options) => {
        const outcome = await runHost(options, { type: "start", observe: observed() });
        assert.equal(outcome.kind, "refused");
      },
    ],
  ];
  for (const [name, call] of cases) {
    const spy = counted(fakeProgram());
    await call(hostOptions(store, spy.program));
    assert.equal(spy.calls(), 1, name);
  }
  const missing = counted(fakeProgram());
  expectIncompatible(
    await runHost(hostOptions(join(store, "absent"), missing.program), {
      type: "run",
      observe: observed(),
    }),
    "manifest_missing",
  );
  assert.equal(missing.calls(), 1, "a missing-store run");
});

test("an assignment extension named like an installed one is refused before any lock", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const store = await storeIn(t);
  const options = hostOptions(store, fakeProgram({ extensionName: BINDING_EXTENSION_NAME }));
  const named = (error: unknown): boolean =>
    error instanceof RangeError && error.message.includes(BINDING_EXTENSION_NAME);
  await assert.rejects(runHost(options, { type: "start", observe: observed() }), named);
  await assert.rejects(readStatus(options), named);
  assert.equal(existsSync(join(store, "owner")), false, "no owner directory");
  assert.equal(existsSync(store), false, "not even the store directory");
});

test("a malformed program or task set is refused with RangeError before any lock", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const programs: [string, HostProgram][] = [
    ["an unprefixed task name", fakeProgram({ extraTasks: [taskNamed("fixture.other")] })],
    ["a binding task's name", fakeProgram({ extraTasks: [taskNamed(STEP_TASK_NAME)] })],
    ["a repeated task name", fakeProgram({ extraTasks: [taskNamed(FAKE_ASSIGNMENT_NAME)] })],
    ["policy version 0", fakeProgram({ policyVersion: 0 })],
    [
      "a malformed policy",
      fakeProgram({
        policy: { capabilitySet: { ...policyA.capabilitySet, instructionsDigest: "nope" } },
      }),
    ],
  ];
  for (const [name, program] of programs) {
    const store = await storeIn(t);
    const options = hostOptions(store, program);
    await assert.rejects(
      runHost(options, { type: "start", observe: observed() }),
      RangeError,
      name,
    );
    await assert.rejects(readStatus(options), RangeError, name);
    assert.equal(existsSync(join(store, "owner")), false, `${name}: no owner directory`);
  }
});

test("the manifest's definitions correspond to the registry", { timeout: CASE_TIMEOUT_MS }, () => {
  const composition = composeProgram(hostOptions("/unused", fakeProgram()));
  const snapshot = composition.registry.snapshot();
  const documents = new Set<string>(V2_DOCUMENTS.map((token) => token.definition.kind));
  const tasks = Object.keys(composition.definitions).filter((name) => !documents.has(name));
  assert.deepEqual(
    tasks.sort(),
    [FAKE_ASSIGNMENT_NAME, "perk.v2.continuation", STEP_TASK_NAME].sort(),
  );
  for (const name of tasks) {
    const task = snapshot.task(name);
    assert.ok(task !== undefined, `${name} is registered`);
    assert.equal(task.definition.version, composition.definitions[name], `${name} at its version`);
  }
  assert.deepEqual(
    Object.keys(composition.definitions)
      .filter((name) => documents.has(name))
      .sort(),
    [...documents].sort(),
    "the remaining keys are exactly the ten v2 document kinds",
  );
  assert.equal(documents.size, 10);
});

test("the fake program's expected manifest is the binding fixture's", {
  timeout: CASE_TIMEOUT_MS,
}, () => {
  const options = hostOptions("/unused");
  assert.deepEqual(
    expectedManifest(composeProgram(options).definitions, options, HOST_NOW),
    manifest(),
  );
});

test("the assignment's models and env reach Harness.open; the defaults are empty", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const seen: HarnessOptions[] = [];
  const recordingOpen: OpenHarness = (storage, options, context) => {
    seen.push(options);
    return Harness.open(storage, options, context);
  };
  const models = createModels();
  const env: NonNullable<HarnessOptions["env"]> = () => undefined;
  const base = fakeProgram();
  const program: HostProgram = {
    ...base,
    assignment: (context) => ({ ...base.assignment(context), models, env }),
  };
  const store = await storeIn(t);
  const options = hostOptions(store, program, { openHarness: recordingOpen });
  expectQuiescent(await runHost(options, { type: "start", observe: observed() }));
  expectStatus(await readStatus(options));
  assert.equal(seen.length, 2);
  for (const opened of seen) {
    assert.equal(opened.models, models, "the assignment's catalog");
    assert.equal(opened.env, env, "the assignment's env factory");
  }
  const composition = composeProgram(options);
  assert.equal(composition.models, models);
  assert.equal(composition.env, env);

  seen.length = 0;
  const plain = await storeIn(t);
  expectQuiescent(
    await runHost(hostOptions(plain, fakeProgram(), { openHarness: recordingOpen }), {
      type: "start",
      observe: observed(),
    }),
  );
  assert.equal(seen.length, 1);
  const [opened] = seen;
  assert.ok(opened !== undefined);
  assert.notEqual(opened.models, models, "a fresh catalog");
  assert.equal(Object.hasOwn(opened, "env"), false, "no environment");
});
