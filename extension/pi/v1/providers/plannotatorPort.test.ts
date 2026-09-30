// The plannotator port-selection mirror (offline): plannotator's remote detection, its
// `parsePortSelection` table, the precedence resolver, the picker over injected seams, the two
// real-socket helpers, and the doors' readiness notice. Pinned at
// `@plannotator/pi-extension@0.27.22` — see plannotatorPort.ts.

import assert from "node:assert/strict";
import { createServer, type Server } from "node:net";
import { test } from "node:test";
import {
  browserUpNotice,
  isPlannotatorRemoteSession,
  LOCAL_PLANNOTATOR_PORTS,
  PLANNOTATOR_DEFAULT_REMOTE_PORT,
  type PlannotatorPortSelection,
  parsePortSelection,
  pickEphemeralPort,
  pickPlannotatorPort,
  portBinds,
  resolvePlannotatorPorts,
} from "./plannotatorPort.ts";

// --- isPlannotatorRemoteSession -------------------------------------------------------------------

test("isPlannotatorRemoteSession: PLANNOTATOR_REMOTE tri-state, else SSH detection", () => {
  const ssh = { SSH_CONNECTION: "10.0.0.1 22 10.0.0.2 5000" };
  const rows: [NodeJS.ProcessEnv, boolean][] = [
    [{ PLANNOTATOR_REMOTE: "1" }, true],
    [{ PLANNOTATOR_REMOTE: "true" }, true],
    [{ PLANNOTATOR_REMOTE: "TRUE" }, true],
    [{ PLANNOTATOR_REMOTE: "0", ...ssh }, false],
    [{ PLANNOTATOR_REMOTE: "false", ...ssh }, false],
    [{ PLANNOTATOR_REMOTE: "False", ...ssh }, false],
    [{ SSH_TTY: "/dev/pts/1" }, true],
    [{ ...ssh }, true],
    [{}, false],
    [{ PLANNOTATOR_REMOTE: " 1" }, false], // untrimmed: no override, no SSH → local
    [{ PLANNOTATOR_REMOTE: "yes", ...ssh }, true], // unknown value → SSH detection
  ];
  for (const [env, expected] of rows) {
    assert.equal(isPlannotatorRemoteSession(env), expected, JSON.stringify(env));
  }
});

// --- parsePortSelection ---------------------------------------------------------------------------

test("parsePortSelection: plannotator's fixed/range table", () => {
  assert.deepEqual(parsePortSelection("19432"), { kind: "fixed", ports: [19432] });
  assert.deepEqual(parsePortSelection(" 19432 "), { kind: "fixed", ports: [19432] });
  assert.deepEqual(parsePortSelection("0"), { kind: "fixed", ports: [0] });
  assert.deepEqual(parsePortSelection("65535"), { kind: "fixed", ports: [65535] });
  assert.equal(parsePortSelection("65536"), null);
  assert.deepEqual(parsePortSelection("19432-19435"), {
    kind: "range",
    ports: [19432, 19433, 19434, 19435],
  });
  assert.equal(parsePortSelection("19435-19432"), null);
  assert.equal(parsePortSelection("0-5"), null);
  assert.equal(parsePortSelection("1-65536"), null);
  for (const bad of ["abc", "", "19432-"]) {
    assert.equal(parsePortSelection(bad), null, JSON.stringify(bad));
  }
});

// --- resolvePlannotatorPorts ----------------------------------------------------------------------

test("resolvePlannotatorPorts: plannotator's precedence (env → remote default → random)", () => {
  const ssh = { SSH_CONNECTION: "10.0.0.1 22 10.0.0.2 5000" };
  const single = (port: number) => ({ kind: "single", port });
  const random = { kind: "random" };

  assert.deepEqual(resolvePlannotatorPorts({ PLANNOTATOR_PORT: "19432" }), {
    selection: single(19432),
    remote: false,
  });
  assert.deepEqual(resolvePlannotatorPorts({ PLANNOTATOR_PORT: "19432", ...ssh }), {
    selection: single(19432),
    remote: true,
  });
  assert.deepEqual(resolvePlannotatorPorts({ PLANNOTATOR_PORT: "19432-19435" }), {
    selection: { kind: "range", ports: [19432, 19433, 19434, 19435] },
    remote: false,
  });
  // A fixed 0 is plannotator's ephemeral bind — perk makes the OS pick itself.
  assert.deepEqual(resolvePlannotatorPorts({ PLANNOTATOR_PORT: "0", PLANNOTATOR_REMOTE: "1" }), {
    selection: random,
    remote: true,
  });
  // An unparseable value falls through SILENTLY to the remote rule.
  assert.deepEqual(resolvePlannotatorPorts({ PLANNOTATOR_PORT: "abc", PLANNOTATOR_REMOTE: "1" }), {
    selection: single(PLANNOTATOR_DEFAULT_REMOTE_PORT),
    remote: true,
  });
  assert.deepEqual(resolvePlannotatorPorts({ PLANNOTATOR_PORT: "abc" }), {
    selection: random,
    remote: false,
  });
  // An empty PLANNOTATOR_PORT is unset (plannotator's `if (envPort)` truthiness).
  assert.deepEqual(resolvePlannotatorPorts({ PLANNOTATOR_PORT: "", ...ssh }), {
    selection: single(19432),
    remote: true,
  });
  assert.deepEqual(resolvePlannotatorPorts({ PLANNOTATOR_REMOTE: "0", ...ssh }), {
    selection: random,
    remote: false,
  });
  assert.deepEqual(resolvePlannotatorPorts({}), { selection: random, remote: false });
});

test("LOCAL_PLANNOTATOR_PORTS: frozen, local, random", () => {
  assert.equal(Object.isFrozen(LOCAL_PLANNOTATOR_PORTS), true);
  assert.equal(LOCAL_PLANNOTATOR_PORTS.remote, false);
  assert.deepEqual(LOCAL_PLANNOTATOR_PORTS.selection, { kind: "random" });
});

// --- pickPlannotatorPort --------------------------------------------------------------------------

/** Recording fakes for the picker seams. */
function fakeDeps(probeAnswers: boolean[] = []) {
  const probed: number[] = [];
  let ephemeralCalls = 0;
  return {
    probed,
    ephemeralCalls: () => ephemeralCalls,
    deps: {
      ephemeral: () => {
        ephemeralCalls++;
        return Promise.resolve(45123);
      },
      probe: (port: number) => {
        probed.push(port);
        return Promise.resolve(probeAnswers[probed.length - 1] ?? false);
      },
    },
  };
}

test("pickPlannotatorPort: random → the ephemeral pick, never probes", async () => {
  const fake = fakeDeps();
  const port = await pickPlannotatorPort({ kind: "random" }, fake.deps);
  assert.equal(port, 45123);
  assert.equal(fake.ephemeralCalls(), 1);
  assert.deepEqual(fake.probed, []);
});

test("pickPlannotatorPort: single → the port once the probe reports it bindable", async () => {
  const fake = fakeDeps([true]);
  const port = await pickPlannotatorPort({ kind: "single", port: 19432 }, fake.deps);
  assert.equal(port, 19432);
  assert.equal(fake.ephemeralCalls(), 0);
  assert.deepEqual(fake.probed, [19432]);
});

test("pickPlannotatorPort: an occupied single port is refused, naming the port and the remedy", async () => {
  const fake = fakeDeps([false]);
  await assert.rejects(
    pickPlannotatorPort({ kind: "single", port: 19432 }, fake.deps),
    (error: unknown) =>
      error instanceof Error &&
      error.message.includes("19432 is in use") &&
      error.message.includes("PLANNOTATOR_PORT to a range"),
  );
  assert.deepEqual(fake.probed, [19432], "probed once, never retried or replaced");
  assert.equal(fake.ephemeralCalls(), 0, "never falls back to an ephemeral port");
});

test("pickPlannotatorPort: range → the first bindable port, probed in ascending order", async () => {
  const fake = fakeDeps([false, false, true, true]);
  const selection: PlannotatorPortSelection = {
    kind: "range",
    ports: [19432, 19433, 19434, 19435],
  };
  assert.equal(await pickPlannotatorPort(selection, fake.deps), 19434);
  assert.deepEqual(fake.probed, [19432, 19433, 19434]);
  assert.equal(fake.ephemeralCalls(), 0);
});

test("pickPlannotatorPort: an exhausted range rejects naming the range", async () => {
  const fake = fakeDeps();
  await assert.rejects(
    pickPlannotatorPort({ kind: "range", ports: [19432, 19433] }, fake.deps),
    (error: unknown) =>
      error instanceof Error &&
      error.message.includes("19432-19433") &&
      error.message.includes("exhausted"),
  );
  assert.deepEqual(fake.probed, [19432, 19433]);
});

// --- real sockets ---------------------------------------------------------------------------------

/** Listen on a loopback ephemeral port and return the held server + its port. */
async function holdPort(): Promise<{ server: Server; port: number }> {
  return await new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address !== null ? address.port : 0;
      resolve({ server, port });
    });
  });
}

test("portBinds: false while a loopback listener holds the port, true after it closes", async () => {
  const { server, port } = await holdPort();
  try {
    assert.equal(await portBinds(port), false);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
  assert.equal(await portBinds(port), true);
});

test("pickEphemeralPort: returns a concrete TCP port", async () => {
  const port = await pickEphemeralPort();
  assert.ok(Number.isInteger(port) && port >= 1 && port <= 65535, String(port));
});

// --- browserUpNotice ------------------------------------------------------------------------------

test("browserUpNotice: local keeps the legacy text; remote points at the tunnel/tailnet", () => {
  const url = "http://127.0.0.1:19432";
  assert.equal(
    browserUpNotice({ url, remote: false }),
    "plannotator is up at http://127.0.0.1:19432 — browser opening",
  );
  const remote = browserUpNotice({ url, remote: true });
  assert.ok(remote.includes(url), remote);
  assert.ok(remote.includes("tunnel or tailnet"), remote);
  assert.ok(!remote.includes("browser opening"), remote);
});
