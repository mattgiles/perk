// The verdict lane, measured: supervised execution — worker commands run through Pi's own pi-env
// daemon started locally (`RemoteExecutionEnv` over `Connection({ command: [localDaemon()] })`).
// The daemon's stdin is the owner's pipe; it starts every command in a new session and, when that
// pipe closes, kills every session it started. Each case SIGKILLs the owner at one milestone and
// reads which processes died. The rule-required rows (availability, crash-A/B/C, descendants,
// pid-reuse, group-kill-mitigated) assert PASS where the lane is available; the residual rows
// (setsid-escape, leader-exited, group-kill) record a survival map and assert nothing about it.

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { accessSync, constants } from "node:fs";
import { join } from "node:path";
import { type TestContext, test } from "node:test";
import { Connection } from "@earendil-works/pi-env";
import { type Criterion, daemonPath, evidence } from "../testing/containment/evidence.ts";
import {
  describeAppearances,
  diedInGrace,
  GRACE_MS,
  killOwner,
  LEADER_EXITS,
  type Owner,
  probeDir,
  readPids,
  shProgram,
  startOwner,
  survivalMap,
  TREE,
  TREE_GROUP_SET,
  TREE_NAMES,
  watchAppearances,
} from "../testing/containment/fixture.ts";
import { commandExists } from "../testing/containment/probe.ts";
import {
  type Identity,
  isDead,
  killIdentity,
  procAvailable,
  processStat,
  waitGone,
} from "../testing/containment/procfs.ts";
import { CASE_TIMEOUT_MS, defer } from "../testing/durable.ts";

const DAEMON = daemonPath();

/** Why the lane cannot be measured on this host, or `undefined` when it can. */
function laneUnavailable(): string | undefined {
  if ("error" in DAEMON) return `localDaemon() throws: ${DAEMON.error}`;
  if (!procAvailable()) return "no /proc: the probes read process identity from procfs";
  try {
    accessSync(DAEMON.path, constants.X_OK);
  } catch (error) {
    return `no executable daemon at ${DAEMON.path}: ${String(error)}`;
  }
  return undefined;
}

const UNAVAILABLE = laneUnavailable();

/** Emit `row` as `unavailable` (returning true) when the lane cannot run here. */
function unavailable(
  t: TestContext,
  row: { readonly mechanism: "supervised"; readonly criterion: Criterion },
): boolean {
  if (UNAVAILABLE === undefined) return false;
  evidence(t, { ...row, result: "unavailable", detail: UNAVAILABLE });
  return true;
}

/** An owner running `TREE` (or `program`) through a supervised environment in a fresh probe dir. */
async function supervisedOwner(
  t: TestContext,
  options: {
    readonly program?: (dir: string) => string[];
    readonly expect?: readonly string[];
    readonly daemonWrap?: "setsid";
    readonly detached?: boolean;
  } = {},
): Promise<{ dir: string; owner: Owner }> {
  const dir = await probeDir(t);
  const owner = startOwner(
    t,
    {
      env: "supervised",
      ...(options.daemonWrap === undefined ? {} : { daemonWrap: options.daemonWrap }),
      cwd: dir,
      dir,
      store: randomUUID(),
      epoch: 1,
      program: options.program?.(dir) ?? shProgram(TREE, dir),
      expect: options.expect ?? TREE_NAMES,
    },
    { detached: options.detached === true },
  );
  return { dir, owner };
}

function pick(ids: ReadonlyMap<string, Identity>, names: readonly string[]): Identity[] {
  return names.map((name) => ids.get(name)).filter((id) => id !== undefined);
}

function daemonState(owner: Owner): string {
  const daemon = owner.daemon();
  if (daemon === undefined) return "daemon: never reported";
  return `daemon ${daemon.pid}: ${isDead(daemon) ? "dead" : "alive"}`;
}

test("supervised/availability: the packaged local daemon answers hello", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  if (unavailable(t, { mechanism: "supervised", criterion: "availability" })) return;
  assert.ok("path" in DAEMON);
  const connection = new Connection({ command: [DAEMON.path] });
  defer(t, () => connection.close());
  let detail: string;
  let ok = false;
  try {
    const info = await connection.info();
    ok = info.protocol === 1;
    detail = `path=${DAEMON.path} version=${info.version} protocol=${info.protocol} pid=${info.pid} os=${info.os} arch=${info.arch}`;
  } catch (error) {
    detail = `path=${DAEMON.path} hello failed: ${String(error)}`;
  }
  const result = evidence(t, {
    mechanism: "supervised",
    criterion: "availability",
    result: ok ? "PASS" : "FAIL",
    detail,
  });
  assert.equal(result, "PASS", detail);
});

test("supervised/crash-A: owner killed right before exec() — nothing it started survives", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  if (unavailable(t, { mechanism: "supervised", criterion: "crash-A" })) return;
  const { dir, owner } = await supervisedOwner(t);
  await owner.line("exec");
  const exit = await killOwner(owner);
  const fates = await watchAppearances(dir, TREE_NAMES);
  const pass = exit.signal === "SIGKILL" && diedInGrace(fates, TREE_GROUP_SET);
  const detail = `owner exit=${JSON.stringify(exit)}; ${describeAppearances(fates)}; ${daemonState(owner)}`;
  const result = evidence(t, {
    mechanism: "supervised",
    criterion: "crash-A",
    result: pass ? "PASS" : "FAIL",
    detail,
  });
  assert.equal(result, "PASS", detail);
});

test("supervised/crash-B: owner killed at the command's first output — the group set dies", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  if (unavailable(t, { mechanism: "supervised", criterion: "crash-B" })) return;
  const { dir, owner } = await supervisedOwner(t);
  await owner.line("started");
  const exit = await killOwner(owner);
  const fates = await watchAppearances(dir, TREE_NAMES);
  const pass =
    exit.signal === "SIGKILL" &&
    fates.get("leader")?.appearedMs !== undefined &&
    diedInGrace(fates, TREE_GROUP_SET);
  const detail = `owner exit=${JSON.stringify(exit)}; ${describeAppearances(fates)}; ${daemonState(owner)}`;
  const result = evidence(t, {
    mechanism: "supervised",
    criterion: "crash-B",
    result: pass ? "PASS" : "FAIL",
    detail,
  });
  assert.equal(result, "PASS", detail);
});

test("supervised/crash-C + descendants + setsid-escape: owner killed with the whole tree running", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  if (unavailable(t, { mechanism: "supervised", criterion: "crash-C" })) return;
  const { dir, owner } = await supervisedOwner(t);
  await owner.line("ready");
  const ids = readPids(t, dir, TREE_NAMES);
  const exit = await killOwner(owner);
  await waitGone(pick(ids, TREE_GROUP_SET), GRACE_MS);
  const map = await survivalMap(dir, ids);
  const summary = `owner exit=${JSON.stringify(exit)}; ${JSON.stringify(map)}; ${daemonState(owner)}`;
  const leaderDead = exit.signal === "SIGKILL" && map.leader === "dead";
  const descendantsDead = ["child", "middle", "grandchild", "scrubbed"].every(
    (name) => map[name] === "dead",
  );
  const setsid = ids.get("setsid");
  const escaped =
    setsid === undefined
      ? "never recorded"
      : `${map.setsid}; sid=${processStat(setsid.pid)?.sid ?? "gone"} (own session: ${setsid.pid})`;
  evidence(t, {
    mechanism: "supervised",
    criterion: "crash-C",
    result: leaderDead ? "PASS" : "FAIL",
    detail: summary,
  });
  evidence(t, {
    mechanism: "supervised",
    criterion: "descendants",
    result: leaderDead && descendantsDead ? "PASS" : "FAIL",
    detail: summary,
  });
  evidence(t, {
    mechanism: "supervised",
    criterion: "setsid-escape",
    result: "recorded",
    detail: `setsid: ${escaped}`,
  });
  if (setsid !== undefined) killIdentity(setsid);
  assert.ok(leaderDead && descendantsDead, summary);
});

test("supervised/leader-exited: background work that outlives its command's leader", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  if (unavailable(t, { mechanism: "supervised", criterion: "leader-exited" })) return;
  const { dir, owner } = await supervisedOwner(t, {
    program: (dir) => shProgram(LEADER_EXITS, dir),
    expect: ["bg"],
  });
  const settled = await owner.line("settled");
  await owner.line("ready");
  const ids = readPids(t, dir, ["bg"]);
  const exit = await killOwner(owner);
  await waitGone(pick(ids, ["bg"]), GRACE_MS);
  const map = await survivalMap(dir, ids);
  evidence(t, {
    mechanism: "supervised",
    criterion: "leader-exited",
    result: "recorded",
    detail: `${settled}; owner exit=${JSON.stringify(exit)}; ${JSON.stringify(map)}; ${daemonState(owner)}`,
  });
  for (const id of ids.values()) killIdentity(id);
});

test("supervised/pid-reuse: the daemon holds its command's pid until it reaps it", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  if (unavailable(t, { mechanism: "supervised", criterion: "pid-reuse" })) return;
  const { dir, owner } = await supervisedOwner(t, {
    program: (dir) => [process.execPath, join(dir, "heartbeat.cjs"), dir, "leader"],
    expect: ["leader"],
  });
  await owner.line("ready");
  const daemon = owner.daemon();
  assert.ok(daemon, "the owner reported its daemon");
  const leader = readPids(t, dir, ["leader"]).get("leader");
  assert.ok(leader, "the leader recorded its identity");
  const before = processStat(leader.pid);
  const parented = before?.ppid === daemon.pid;
  const ownGroup = before?.pgid === leader.pid && before.sid === leader.pid;
  let zombie = false;
  let held = false;
  process.kill(daemon.pid, "SIGSTOP");
  try {
    process.kill(leader.pid, "SIGKILL");
    const deadline = Date.now() + GRACE_MS;
    while (!zombie && Date.now() < deadline) {
      zombie = processStat(leader.pid)?.state === "Z";
      if (!zombie) await new Promise((resolve) => setTimeout(resolve, 20));
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
    const still = processStat(leader.pid);
    held = zombie && still?.state === "Z" && still.startTime === leader.startTime;
  } finally {
    process.kill(daemon.pid, "SIGCONT");
  }
  const deadline = Date.now() + GRACE_MS;
  let reaped = false;
  while (!reaped && Date.now() < deadline) {
    const now = processStat(leader.pid);
    reaped = now === undefined || now.startTime !== leader.startTime;
    if (!reaped) await new Promise((resolve) => setTimeout(resolve, 20));
  }
  const pass = parented && ownGroup && zombie && held && reaped;
  const detail = `leader ${leader.pid}: ppid=${before?.ppid} (daemon ${daemon.pid}) pgid=${before?.pgid} sid=${before?.sid}; killed with the daemon stopped → zombie=${zombie}, still a zombie 200 ms later=${held}; daemon resumed → reaped=${reaped}`;
  const result = evidence(t, {
    mechanism: "supervised",
    criterion: "pid-reuse",
    result: pass ? "PASS" : "FAIL",
    detail,
  });
  assert.equal(result, "PASS", detail);
});

test("supervised/group-kill: owner and plain daemon killed together as one process group", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  if (unavailable(t, { mechanism: "supervised", criterion: "group-kill" })) return;
  const { dir, owner } = await supervisedOwner(t, { detached: true });
  await owner.line("ready");
  const ids = readPids(t, dir, TREE_NAMES);
  const exit = await killOwner(owner, { group: true });
  await waitGone(pick(ids, TREE_GROUP_SET), GRACE_MS);
  const map = await survivalMap(dir, ids);
  evidence(t, {
    mechanism: "supervised",
    criterion: "group-kill",
    result: "recorded",
    detail: `owner exit=${JSON.stringify(exit)}; ${JSON.stringify(map)}; ${daemonState(owner)}`,
  });
  for (const id of ids.values()) killIdentity(id);
});

test("supervised/group-kill-mitigated: a setsid-wrapped daemon outlives the owner's group kill and stops the tree", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  if (unavailable(t, { mechanism: "supervised", criterion: "group-kill-mitigated" })) return;
  if (!commandExists("setsid")) {
    evidence(t, {
      mechanism: "supervised",
      criterion: "group-kill-mitigated",
      result: "unavailable",
      detail: "setsid(1) is not on PATH",
    });
    return;
  }
  const { dir, owner } = await supervisedOwner(t, { daemonWrap: "setsid", detached: true });
  await owner.line("ready");
  const ids = readPids(t, dir, TREE_NAMES);
  const exit = await killOwner(owner, { group: true });
  const gone = await waitGone(pick(ids, TREE_GROUP_SET), GRACE_MS);
  const map = await survivalMap(dir, ids);
  const detail = `owner exit=${JSON.stringify(exit)}; ${JSON.stringify(map)}; ${daemonState(owner)}`;
  const result = evidence(t, {
    mechanism: "supervised",
    criterion: "group-kill-mitigated",
    result: exit.signal === "SIGKILL" && gone ? "PASS" : "FAIL",
    detail,
  });
  const setsid = ids.get("setsid");
  if (setsid !== undefined) killIdentity(setsid);
  assert.equal(result, "PASS", detail);
});
