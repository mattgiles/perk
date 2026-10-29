// The mechanisms evaluated and not chosen, measured as comparison evidence: a PID namespace (with
// die-with-parent), bubblewrap, a bare parent-death signal, an intent-first spawn journal with
// start-time identity, a cgroup v2 fence (plus a systemd scope availability row), and the
// report-only environment-label sweep. Every row quantifies one mechanism's stop set and residual
// on this host; none of them moves the verdict, so none asserts its outcome — only the probes' own
// instruments are asserted (a row is emitted, the test reaps what it started).

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { type TestContext, test } from "node:test";
import {
  cgroupPreflight,
  createFenceCgroup,
  killFenceCgroup,
} from "../testing/containment/cgroup.ts";
import { evidence } from "../testing/containment/evidence.ts";
import {
  GRACE_MS,
  killOwner,
  LEADER_EXITS,
  type OwnerConfig,
  probeDir,
  readPids,
  shProgram,
  startOwner,
  survivalMap,
  TREE,
  TREE_NAMES,
} from "../testing/containment/fixture.ts";
import { commandExists, probeCommand } from "../testing/containment/probe.ts";
import {
  fenceRegistered,
  type Identity,
  killIdentity,
  procAvailable,
  readIdentity,
  sweepMarkers,
  waitGone,
} from "../testing/containment/procfs.ts";
import { CGROUP_WRAPPER, JOURNAL_WRAPPER } from "../testing/containment/wrappers.ts";
import { CASE_TIMEOUT_MS, defer, waitFor } from "../testing/durable.ts";

const PROBE_TIMEOUT_MS = 5_000;
const NO_PROC = "no /proc: the probes read process identity from procfs";

/** The PID-namespace availability probe the crash case is gated on. */
const PIDNS_ARGV = ["unshare", "-Ur", "--pid", "--fork", "true"];

/** Run `program` through `NodeExecutionEnv` in a fresh probe dir, kill the owner at `ready`. */
async function crashAtReady(
  t: TestContext,
  program: (dir: string) => string[],
  expect: readonly string[],
  overrides: Partial<OwnerConfig> = {},
): Promise<{ dir: string; ids: Map<string, Identity>; exit: string; store: string }> {
  const dir = await probeDir(t);
  const store = randomUUID();
  const owner = startOwner(t, {
    env: "node",
    cwd: dir,
    dir,
    store,
    epoch: 1,
    program: program(dir),
    expect,
    ...overrides,
  });
  await owner.line("ready");
  const ids = readPids(t, dir, expect);
  const exit = await killOwner(owner);
  return { dir, ids, exit: JSON.stringify(exit), store };
}

function killAll(ids: ReadonlyMap<string, Identity>): void {
  for (const id of ids.values()) killIdentity(id);
}

test("pidns/availability: unprivileged user + PID + network namespaces", {
  timeout: CASE_TIMEOUT_MS,
}, (t) => {
  if (!commandExists("unshare")) {
    evidence(t, {
      mechanism: "pidns",
      criterion: "availability",
      result: "unavailable",
      detail: "unshare(1) is not on PATH",
    });
    return;
  }
  for (const argv of [["unshare", "-Ur", "true"], PIDNS_ARGV, ["unshare", "-Urn", "true"]]) {
    const outcome = probeCommand(argv, PROBE_TIMEOUT_MS);
    evidence(t, {
      mechanism: "pidns",
      criterion: "availability",
      result: outcome.ok ? "PASS" : "unavailable",
      detail: outcome.detail,
    });
  }
});

test("bwrap/availability: bubblewrap with a PID + network sandbox", {
  timeout: CASE_TIMEOUT_MS,
}, (t) => {
  if (!commandExists("bwrap")) {
    evidence(t, {
      mechanism: "bwrap",
      criterion: "availability",
      result: "unavailable",
      detail: "not installed (bwrap is not on PATH)",
    });
    return;
  }
  const outcome = probeCommand(
    [
      "bwrap",
      "--ro-bind",
      "/",
      "/",
      "--dev",
      "/dev",
      "--proc",
      "/proc",
      "--unshare-pid",
      "--unshare-net",
      "--die-with-parent",
      "true",
    ],
    PROBE_TIMEOUT_MS,
  );
  evidence(t, {
    mechanism: "bwrap",
    criterion: "availability",
    result: outcome.ok ? "PASS" : "unavailable",
    detail: outcome.detail,
  });
});

test("pdeathsig/crash-C: a direct child armed with PR_SET_PDEATHSIG dies with its owner", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  if (!procAvailable() || !commandExists("setpriv")) {
    evidence(t, {
      mechanism: "pdeathsig",
      criterion: "crash-C",
      result: "unavailable",
      detail: procAvailable() ? "setpriv(1) is not on PATH" : NO_PROC,
    });
    return;
  }
  const { dir, ids, exit } = await crashAtReady(
    t,
    (dir) => [
      "setpriv",
      "--pdeathsig=KILL",
      process.execPath,
      join(dir, "heartbeat.cjs"),
      dir,
      "child",
    ],
    ["child"],
  );
  const gone = await waitGone([...ids.values()], GRACE_MS);
  const map = await survivalMap(dir, ids);
  evidence(t, {
    mechanism: "pdeathsig",
    criterion: "crash-C",
    result: gone ? "PASS" : "FAIL",
    detail: `owner exit=${exit}; ${JSON.stringify(map)}`,
  });
  killAll(ids);
});

test("pidns/crash-C + descendants: a PID namespace whose init dies with the owner", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const gate =
    procAvailable() && commandExists("unshare") && commandExists("setpriv")
      ? probeCommand(PIDNS_ARGV, PROBE_TIMEOUT_MS)
      : { ok: false, detail: procAvailable() ? "unshare(1) or setpriv(1) missing" : NO_PROC };
  if (!gate.ok) {
    const detail = `gated on ${JSON.stringify(PIDNS_ARGV)}: ${gate.detail}`;
    evidence(t, { mechanism: "pidns", criterion: "crash-C", result: "not_measured", detail });
    evidence(t, { mechanism: "pidns", criterion: "descendants", result: "not_measured", detail });
    return;
  }
  const { dir, ids, exit } = await crashAtReady(
    t,
    (dir) => [
      "setpriv",
      "--pdeathsig=KILL",
      "unshare",
      "--user",
      "--map-root-user",
      "--pid",
      "--fork",
      "--kill-child=KILL",
      ...shProgram(TREE, dir),
    ],
    TREE_NAMES,
  );
  await waitGone([...ids.values()], GRACE_MS);
  const map = await survivalMap(dir, ids);
  const summary = `owner exit=${exit}; ${JSON.stringify(map)}`;
  evidence(t, {
    mechanism: "pidns",
    criterion: "crash-C",
    result: map.leader === "dead" ? "PASS" : "FAIL",
    detail: summary,
  });
  evidence(t, {
    mechanism: "pidns",
    criterion: "descendants",
    result: Object.values(map).every((state) => state === "dead") ? "PASS" : "FAIL",
    detail: summary,
  });
  killAll(ids);
});

test("journal/crash-C + descendants: the fence kills exactly the registered process", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  if (!procAvailable()) {
    evidence(t, {
      mechanism: "journal",
      criterion: "crash-C",
      result: "unavailable",
      detail: NO_PROC,
    });
    return;
  }
  const { dir, ids, exit } = await crashAtReady(
    t,
    (dir) => ["sh", "-c", JOURNAL_WRAPPER, "sh", dir, ...shProgram(TREE, dir)],
    TREE_NAMES,
  );
  const registered = readIdentity(join(dir, "registered"));
  const fence = fenceRegistered(join(dir, "registered"));
  const leader = ids.get("leader");
  const leaderGone = leader !== undefined && (await waitGone([leader], GRACE_MS));
  const map = await survivalMap(dir, ids);
  const summary = `owner exit=${exit}; registered=${JSON.stringify(registered)} (leader ${JSON.stringify(leader)}); fence=${fence}; ${JSON.stringify(map)}`;
  evidence(t, {
    mechanism: "journal",
    criterion: "crash-C",
    result: fence === "killed" && leaderGone ? "PASS" : "FAIL",
    detail: summary,
  });
  evidence(t, {
    mechanism: "journal",
    criterion: "descendants",
    result: "recorded",
    detail: summary,
  });
  killAll(ids);
});

test("journal/pid-reuse: the fence refuses a record whose start time no longer matches", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  if (!procAvailable()) {
    evidence(t, {
      mechanism: "journal",
      criterion: "pid-reuse",
      result: "unavailable",
      detail: NO_PROC,
    });
    return;
  }
  const dir = await probeDir(t);
  const decoyProcess = spawn(process.execPath, [join(dir, "heartbeat.cjs"), dir, "decoy"], {
    stdio: "ignore",
  });
  defer(t, () => {
    decoyProcess.kill("SIGKILL");
  });
  await waitFor(() => readIdentity(join(dir, "decoy.pid")) !== undefined, GRACE_MS);
  const decoy = readPids(t, dir, ["decoy"]);
  const id = decoy.get("decoy");
  assert.ok(id, "the decoy recorded its identity");
  const record = join(dir, "registered");
  writeFileSync(record, `${id.pid} ${BigInt(id.startTime) + 1n}\n`);
  const forged = fenceRegistered(record);
  const afterForged = (await survivalMap(dir, decoy)).decoy;
  writeFileSync(record, `${id.pid} ${id.startTime}\n`);
  const matching = fenceRegistered(record);
  const gone = await waitGone([id], GRACE_MS);
  const pass =
    forged === "stale" && afterForged === "alive (ticking)" && matching === "killed" && gone;
  evidence(t, {
    mechanism: "journal",
    criterion: "pid-reuse",
    result: pass ? "PASS" : "FAIL",
    detail: `forged start time → fence=${forged}, decoy ${afterForged}; matching record → fence=${matching}, decoy dead=${gone}`,
  });
  assert.ok(pass, "the journal fence's start-time check is the instrument under test");
});

test("cgroup/availability + systemd-scope/availability: an unprivileged fence cgroup here", {
  timeout: CASE_TIMEOUT_MS,
}, (t) => {
  const preflight = cgroupPreflight();
  evidence(t, {
    mechanism: "cgroup",
    criterion: "availability",
    result: preflight.ok ? "PASS" : "unavailable",
    detail: preflight.ok ? `fence root ${preflight.root}` : preflight.reason,
  });
  if (!commandExists("systemd-run")) {
    evidence(t, {
      mechanism: "systemd-scope",
      criterion: "availability",
      result: "unavailable",
      detail: "systemd-run(1) is not on PATH",
    });
    return;
  }
  const outcome = probeCommand(
    ["systemd-run", "--user", "--scope", "--quiet", "true"],
    PROBE_TIMEOUT_MS * 2,
  );
  evidence(t, {
    mechanism: "systemd-scope",
    criterion: "availability",
    result: outcome.ok ? "PASS" : "unavailable",
    detail: outcome.detail,
  });
});

test("cgroup/crash-C + descendants: cgroup.kill stops every process in the fence", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const preflight = procAvailable() ? cgroupPreflight() : ({ ok: false, reason: NO_PROC } as const);
  if (!preflight.ok) {
    const detail = `preflight: ${preflight.reason}`;
    evidence(t, { mechanism: "cgroup", criterion: "crash-C", result: "not_measured", detail });
    evidence(t, { mechanism: "cgroup", criterion: "descendants", result: "not_measured", detail });
    return;
  }
  const treeFence = createFenceCgroup(t, preflight.root);
  const tree = await crashAtReady(
    t,
    (dir) => ["sh", "-c", CGROUP_WRAPPER, "sh", treeFence, ...shProgram(TREE, dir)],
    TREE_NAMES,
  );
  const treeKill = await killFenceCgroup(treeFence);
  const treeGone = await waitGone([...tree.ids.values()], GRACE_MS);
  const treeMap = await survivalMap(tree.dir, tree.ids);

  const bgFence = createFenceCgroup(t, preflight.root);
  const bg = await crashAtReady(
    t,
    (dir) => ["sh", "-c", CGROUP_WRAPPER, "sh", bgFence, ...shProgram(LEADER_EXITS, dir)],
    ["bg"],
  );
  const bgKill = await killFenceCgroup(bgFence);
  const bgGone = await waitGone([...bg.ids.values()], GRACE_MS);
  const bgMap = await survivalMap(bg.dir, bg.ids);

  const treeDetail = `tree: owner exit=${tree.exit}; fence ${JSON.stringify(treeKill)}; ${JSON.stringify(treeMap)}`;
  const bgDetail = `leader-exited: owner exit=${bg.exit}; fence ${JSON.stringify(bgKill)}; ${JSON.stringify(bgMap)}`;
  evidence(t, {
    mechanism: "cgroup",
    criterion: "crash-C",
    result: treeGone && treeKill.removed ? "PASS" : "FAIL",
    detail: treeDetail,
  });
  evidence(t, {
    mechanism: "cgroup",
    criterion: "descendants",
    result: treeGone && bgGone && treeKill.removed && bgKill.removed ? "PASS" : "FAIL",
    detail: `${treeDetail} | ${bgDetail}`,
  });
  killAll(tree.ids);
  killAll(bg.ids);
});

test("marker/report: the environment-label sweep lists an earlier epoch's labelled survivors", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  if (!procAvailable()) {
    evidence(t, {
      mechanism: "marker",
      criterion: "report",
      result: "unavailable",
      detail: NO_PROC,
    });
    return;
  }
  const { ids, exit, store } = await crashAtReady(t, (dir) => shProgram(TREE, dir), TREE_NAMES);
  const swept = sweepMarkers(store, 2);
  const expected = ["leader", "child", "middle", "grandchild", "setsid"];
  const listed =
    swept === "not_observable"
      ? []
      : swept.map((found) => {
          const name = [...ids].find(
            ([, id]) => id.pid === found.pid && id.startTime === found.startTime,
          )?.[0];
          return `${name ?? `unknown pid ${found.pid}`}@epoch${found.epoch}`;
        });
  const names = listed.map((entry) => entry.slice(0, entry.indexOf("@"))).sort();
  const pass =
    swept !== "not_observable" && JSON.stringify(names) === JSON.stringify([...expected].sort());
  evidence(t, {
    mechanism: "marker",
    criterion: "report",
    result: swept === "not_observable" ? "unavailable" : pass ? "PASS" : "FAIL",
    detail: `owner exit=${exit}; sweep(store, below epoch 2) listed ${JSON.stringify(listed)}; expected ${JSON.stringify(expected)}`,
  });
  killAll(ids);
});
