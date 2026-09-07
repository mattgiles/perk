import assert from "node:assert/strict";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type TestContext, test } from "node:test";
import { sessionDataDir } from "../substrate/cache.ts";
import {
  digestSessionData,
  readSessionDataStrict,
  type SessionArtifactCtx,
} from "../substrate/sessionData.ts";
import { type EntrySink, WORKFLOW_STATE_TYPE } from "../substrate/workflowState.ts";
import { openMemoryWorkflowSession } from "../testing/memoryWorkflowSession.ts";
import { openBranchWorkflowSession } from "./branchWorkflowSession.ts";
import { branchSessionStateStore } from "./lifecycle.ts";
import { openWorkflowSession } from "./workflowSession.ts";

const strict = { provenance: "strict" } as const;
const name = "draft-review.json";
function entry(data: Record<string, unknown>) {
  return { type: "custom", customType: WORKFLOW_STATE_TYPE, data };
}
function pointer(content = "old") {
  return {
    run_id: "run",
    name,
    path: "untrusted/informational",
    digest: digestSessionData(content),
    at: "2026-01-01T00:00:00Z",
  };
}
function fixture(t: TestContext) {
  const cwd = mkdtempSync(join(tmpdir(), "perk-strict-artifact-"));
  t.after(() => rmSync(cwd, { recursive: true, force: true }));
  const branch: unknown[] = [entry({ run_id: "run" })];
  let throwing = false;
  let dropAppend = false;
  const source: SessionArtifactCtx = {
    cwd,
    hasUI: false,
    ui: { notify() {} },
    sessionManager: {
      getBranch() {
        if (throwing) throw new Error("induced state read failure");
        return branch;
      },
    },
  };
  let appends = 0;
  const sink: EntrySink = {
    appendEntry(customType, data) {
      appends++;
      if (!dropAppend) branch.push({ type: "custom", customType, data });
    },
  };
  return {
    cwd,
    branch,
    source,
    sink,
    session: openBranchWorkflowSession(sink, source),
    seed(data: Record<string, unknown>) {
      branch.push(entry(data));
    },
    throwReads() {
      throwing = true;
    },
    dropAppends() {
      dropAppend = true;
    },
    appends: () => appends,
    path: join(sessionDataDir(cwd, "run"), name),
  };
}

for (const binding of ["branch", "memory"] as const) {
  test(`${binding}: strict absent → applied → found → unchanged, ordinary behavior unchanged`, (t) => {
    const session =
      binding === "branch" ? fixture(t).session : openMemoryWorkflowSession({ runId: "run" });
    assert.deepEqual(session.readArtifact(name, strict), { status: "absent" });
    assert.equal(session.writeArtifact(name, "exact UTF-8 ☃\n", strict).status, "applied");
    assert.deepEqual(session.readArtifact(name, strict), {
      status: "found",
      content: "exact UTF-8 ☃\n",
    });
    assert.equal(session.writeArtifact(name, "exact UTF-8 ☃\n", strict).status, "unchanged");
    assert.equal(session.writeArtifact(name, "", strict).status, "applied");
    assert.deepEqual(session.readArtifact(name, strict), { status: "found", content: "" });
  });
}

const malformedMaps: unknown[] = [
  false,
  1,
  "bad",
  [],
  { [name]: null },
  { [name]: [] },
  { [name]: { run_id: "run", digest: digestSessionData("old") } },
  ...[
    { run_id: "../run" },
    { digest: "sha256:BAD" },
    { name: "other" },
    { path: null },
    { at: 0 },
  ].map((patch) => ({ [name]: { ...pointer(), ...patch } })),
  { [name]: pointer(), sibling: null },
  new Date(0),
  new Map(),
];
for (const [i, map] of malformedMaps.entries()) {
  test(`malformed provenance map/pointer ${i} refuses strict read and write without effects`, (t) => {
    const f = fixture(t);
    f.seed({ session_artifacts: map });
    assert.equal(f.session.readArtifact(name, strict).status, "invalid");
    assert.equal(f.session.writeArtifact(name, "new", strict).status, "rejected");
    assert.equal(f.appends(), 0);
    assert.equal(existsSync(f.path), false);
  });
}

for (const map of [undefined, null, {}]) {
  test(`valid empty map ${JSON.stringify(map)} allows absent namespace but never orphan bytes`, (t) => {
    const f = fixture(t);
    f.seed({ session_artifacts: map });
    assert.deepEqual(f.session.readArtifact(name, strict), { status: "absent" });
    mkdirSync(sessionDataDir(f.cwd, "run"), { recursive: true });
    writeFileSync(f.path, "orphan");
    assert.deepEqual(f.session.readArtifact(name), { status: "absent" });
    const read = f.session.readArtifact(name, strict);
    assert.equal(read.status, "invalid");
    if (read.status === "invalid") assert.match(read.problem, /orphan/);
    assert.equal(f.session.writeArtifact(name, "replacement", strict).status, "rejected");
    assert.equal(readFileSync(f.path, "utf8"), "orphan");
    assert.equal(f.appends(), 0);
  });
}

for (const runId of [undefined, null, "", "../escape", 42]) {
  test(`strict no/unsafe identity ${JSON.stringify(runId)} is not absence`, (t) => {
    const f = fixture(t);
    f.branch.length = 0;
    f.seed({ run_id: runId });
    assert.equal(f.session.readArtifact(name, strict).status, "invalid");
    assert.equal(f.session.writeArtifact(name, "new", strict).status, "rejected");
    assert.deepEqual(f.session.readArtifact(name), { status: "absent" });
    assert.equal(existsSync(f.path), false);
  });
}

test("throwing state reads fail closed even when session opened with sound identity", (t) => {
  const f = fixture(t);
  f.throwReads();
  assert.equal(f.session.readArtifact(name, strict).status, "invalid");
  assert.equal(f.session.writeArtifact(name, "new", strict).status, "rejected");
  assert.deepEqual(f.session.readArtifact(name), { status: "absent" });
  assert.equal(f.appends(), 0);
});

for (const change of ["missing", "corrupt"] as const) {
  test(`pointer with ${change} file refuses strict replacement`, (t) => {
    const f = fixture(t);
    assert.equal(f.session.writeArtifact(name, "old", strict).status, "applied");
    if (change === "missing") rmSync(f.path);
    else writeFileSync(f.path, "disk ahead");
    assert.equal(f.session.readArtifact(name, strict).status, "invalid");
    assert.equal(f.session.writeArtifact(name, "new", strict).status, "rejected");
    assert.equal(f.appends(), 1);
    if (change === "corrupt") assert.equal(readFileSync(f.path, "utf8"), "disk ahead");
  });
}

test("inherited pointer never reads parent bytes; empty fork is usable, fork orphan refuses", (t) => {
  const f = fixture(t);
  assert.equal(f.session.writeArtifact(name, "parent", strict).status, "applied");
  f.seed({ run_id: "run.1" });
  assert.deepEqual(f.session.readArtifact(name, strict), { status: "absent" });
  assert.equal(readFileSync(f.path, "utf8"), "parent");
  assert.equal(f.session.writeArtifact(name, "child", strict).status, "applied");
  assert.deepEqual(f.session.readArtifact(name, strict), { status: "found", content: "child" });
  f.seed({ run_id: "run.2" });
  mkdirSync(sessionDataDir(f.cwd, "run.2"), { recursive: true });
  writeFileSync(join(sessionDataDir(f.cwd, "run.2"), name), "orphan");
  assert.equal(f.session.readArtifact(name, strict).status, "invalid");
});

test("independent stale branch snapshot refuses advanced disk bytes, never overwrites", (t) => {
  const f = fixture(t);
  assert.equal(f.session.writeArtifact(name, "old", strict).status, "applied");
  const snapshot = [...f.branch];
  let attempted = 0;
  const stale = openBranchWorkflowSession(
    {
      appendEntry() {
        attempted++;
      },
    },
    {
      ...f.source,
      sessionManager: { getBranch: () => snapshot },
    },
  );
  assert.equal(f.session.writeArtifact(name, "successor", strict).status, "applied");
  assert.equal(stale.readArtifact(name, strict).status, "invalid");
  assert.equal(stale.writeArtifact(name, "stale replacement", strict).status, "rejected");
  assert.equal(attempted, 0);
  assert.equal(readFileSync(f.path, "utf8"), "successor");
});

for (const prior of [false, true]) {
  test(`content-written/pointer-dropped ${prior ? "replacement" : "initial"} is unverified and refuses next strict write`, (t) => {
    const f = fixture(t);
    if (prior) assert.equal(f.session.writeArtifact(name, "old", strict).status, "applied");
    f.dropAppends();
    assert.equal(f.session.writeArtifact(name, "new", strict).status, "unverified");
    const appends = f.appends();
    assert.equal(f.session.readArtifact(name, strict).status, "invalid");
    assert.equal(f.session.writeArtifact(name, "speculative repair", strict).status, "rejected");
    assert.equal(f.appends(), appends);
    assert.equal(readFileSync(f.path, "utf8"), "new");
  });
}

test("pointer append with malformed informational fields cannot verify a strict write", (t) => {
  const f = fixture(t);
  let appends = 0;
  const session = openBranchWorkflowSession(
    {
      appendEntry() {
        appends++;
        f.seed({ session_artifacts: { [name]: { ...pointer("new"), path: null } } });
      },
    },
    f.source,
  );
  assert.equal(session.writeArtifact(name, "new", strict).status, "unverified");
  assert.equal(session.writeArtifact(name, "repair", strict).status, "rejected");
  assert.equal(appends, 1);
  assert.equal(readFileSync(f.path, "utf8"), "new");
});

for (const unsafe of ["file-directory", "file-symlink", "data-symlink"]) {
  test(`strict content I/O ${unsafe} is invalid, never ENOENT fallback`, (t) => {
    const f = fixture(t);
    const data = sessionDataDir(f.cwd, "run");
    if (unsafe === "data-symlink") {
      mkdirSync(join(data, ".."), { recursive: true });
      symlinkSync(join(f.cwd, "missing"), data);
    } else {
      mkdirSync(data, { recursive: true });
      if (unsafe === "file-directory") mkdirSync(f.path);
      else symlinkSync(join(f.cwd, "missing"), f.path);
    }
    assert.deepEqual(readSessionDataStrict(f.cwd, "run", name), { status: "io-error" });
    assert.equal(f.session.readArtifact(name, strict).status, "invalid");
    assert.equal(f.session.writeArtifact(name, "new", strict).status, "rejected");
  });
}

for (const mode of [
  "read-throw",
  "read-io",
  "store-reject",
  "store-throw",
  "bad-readback",
  "readback-io",
  "state-after-store",
  "map-after-store",
  "identity-after-store",
] as const) {
  test(`strict port fault ${mode} stops without speculative append`, (t) => {
    const f = fixture(t);
    let stores = 0;
    let content: string | undefined;
    const session = openWorkflowSession({
      state: branchSessionStateStore(f.sink, f.source),
      artifacts: {
        load: () => content ?? null,
        loadStrict() {
          if (mode === "read-throw") throw new Error("induced");
          if (mode === "read-io" || (mode === "readback-io" && stores > 0))
            return { status: "io-error" };
          return content === undefined ? { status: "absent" } : { status: "found", content };
        },
        store(_runId, _name, bytes) {
          stores++;
          if (mode === "store-reject") return false;
          if (mode === "store-throw") throw new Error("ambiguous effect");
          content = mode === "bad-readback" ? "different" : bytes;
          if (mode === "state-after-store") f.throwReads();
          if (mode === "map-after-store") f.seed({ session_artifacts: { sibling: null } });
          if (mode === "identity-after-store") f.seed({ run_id: "run.1" });
          return true;
        },
        displayPath: () => name,
      },
    });
    const result = session.writeArtifact(name, "expected", strict);
    assert.equal(
      result.status,
      ["read-throw", "read-io", "store-reject"].includes(mode) ? "rejected" : "unverified",
    );
    assert.equal(stores, mode.startsWith("read-") ? 0 : 1);
    assert.equal(f.appends(), 0);
  });
}
