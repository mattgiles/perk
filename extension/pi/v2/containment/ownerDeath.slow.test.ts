// The containment problem, reproduced: a command run through Durable's `NodeExecutionEnv.exec` is
// spawned detached (its own session), so when its owner is SIGKILLed nothing kills it — the whole
// tree keeps running. The clean-close control proves the survival assertion is not vacuous: the
// same tree dies when the owner lives long enough to call `env.cleanup()`. This file also emits the
// `host` row every other containment row is read against. Rows: `perk-v2-containment {…}`
// diagnostics (docs/design/archive/pi-durable-v2-containment-characterization.md).

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import { evidence, hostEvidence } from "../testing/containment/evidence.ts";
import {
  GRACE_MS,
  killOwner,
  probeDir,
  READY_TIMEOUT_MS,
  readPids,
  shProgram,
  startOwner,
  survivalMap,
  TREE,
  TREE_GROUP_SET,
  TREE_NAMES,
} from "../testing/containment/fixture.ts";
import {
  killIdentity,
  procAvailable,
  processStat,
  waitGone,
} from "../testing/containment/procfs.ts";
import { CASE_TIMEOUT_MS } from "../testing/durable.ts";

test("host: the facts every containment row is read against", { timeout: CASE_TIMEOUT_MS }, (t) => {
  const facts = hostEvidence(t);
  assert.equal(facts.platform, process.platform);
});

test("repro/survival: a NodeExecutionEnv command tree outlives its SIGKILLed owner", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  if (!procAvailable()) {
    evidence(t, {
      mechanism: "repro",
      criterion: "survival",
      result: "unavailable",
      detail: "no /proc: the probes read process identity from procfs",
    });
    return;
  }
  const dir = await probeDir(t);
  const owner = startOwner(t, {
    env: "node",
    cwd: dir,
    dir,
    store: randomUUID(),
    epoch: 1,
    program: shProgram(TREE, dir),
    expect: TREE_NAMES,
  });
  await owner.line("ready");
  const ids = readPids(t, dir, TREE_NAMES);
  const exit = await killOwner(owner);
  const map = await survivalMap(dir, ids);
  const child = ids.get("child");
  assert.ok(child, "the child recorded its identity");
  const reproduced =
    exit.signal === "SIGKILL" &&
    map.child === "alive (ticking)" &&
    processStat(child.pid)?.startTime === child.startTime;
  evidence(t, {
    mechanism: "repro",
    criterion: "survival",
    result: reproduced ? "PASS" : "FAIL",
    detail: `owner exit=${JSON.stringify(exit)}; after the owner's exit: ${JSON.stringify(map)}`,
  });
  for (const id of ids.values()) killIdentity(id);
  assert.ok(await waitGone([...ids.values()], GRACE_MS), "the test reaps every survivor");
  assert.ok(reproduced, `the tree outlived its owner: ${JSON.stringify(map)}`);
});

test("repro/survival control: the same tree dies when the owner closes cleanly (env.cleanup)", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  if (!procAvailable()) {
    evidence(t, {
      mechanism: "repro",
      criterion: "survival",
      result: "unavailable",
      detail: "control: no /proc",
    });
    return;
  }
  const dir = await probeDir(t);
  const owner = startOwner(t, {
    env: "node",
    cwd: dir,
    dir,
    store: randomUUID(),
    epoch: 1,
    program: shProgram(TREE, dir),
    expect: TREE_NAMES,
    cleanOnStdinEnd: true,
  });
  await owner.line("ready");
  const ids = readPids(t, dir, TREE_NAMES);
  owner.closeStdin();
  const exit = await Promise.race([
    owner.exited,
    new Promise<undefined>((resolve) => {
      setTimeout(() => resolve(undefined), READY_TIMEOUT_MS);
    }),
  ]);
  const groupSet = TREE_GROUP_SET.map((name) => ids.get(name)).filter((id) => id !== undefined);
  const gone = await waitGone(groupSet, GRACE_MS);
  const map = await survivalMap(dir, ids);
  const controlled = exit?.code === 0 && gone;
  evidence(t, {
    mechanism: "repro",
    criterion: "survival",
    result: controlled ? "PASS" : "FAIL",
    detail: `control (clean close): owner exit=${JSON.stringify(exit)}; ${JSON.stringify(map)}`,
  });
  assert.ok(controlled, `a clean close kills the group set: ${JSON.stringify(map)}`);
});
