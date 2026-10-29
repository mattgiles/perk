// A3 — the environment refuses path escapes, writes and exec (docs/design/pi-durable-v2-foundations.md
// §12 the native assignment): `SnapshotEnv` over a temp root holding a file, a directory, a symlink
// to an outside file, one to an outside directory and an inside-pointing one; the root trusted only
// as a real directory, at open and at every gate; in-run, a worker's escaping reads (and `bash`)
// are errors that carry no outside content, a root swapped for a symlink mid-run fails closed, the
// same tools succeed on inside paths, and the env factory gives every non-worker conversation none.

import assert from "node:assert/strict";
import {
  mkdirSync,
  readFileSync,
  renameSync,
  symlinkSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import type { ConversationId } from "@earendil-works/pi-durable";
import type { ExecutionEnv, Result } from "@earendil-works/pi-durable/env";
import { SnapshotEnv, snapshotEnvFactory, WORKSPACE_ROOT } from "../durable/snapshotEnv.ts";
import { composeProgram, runHost } from "../host.ts";
import { snapshotDir, snapshotManifestPath } from "../subject/snapshot.ts";
import { CASE_TIMEOUT_MS, defer, deferred, tempDir } from "../testing/durable.ts";
import { expectQuiescent } from "../testing/host.ts";
import { readTree } from "../testing/subject.ts";
import {
  after,
  allWorkerResultTexts,
  assertScript,
  barrier,
  call,
  fixtureAttemptId,
  fixtureSubject,
  nativeOptions,
  openStoreHarness,
  reportCall,
  roleScript,
  round,
  startNative,
  withStore,
} from "../testing/worker.ts";

const context = BACKGROUND_CONTEXT;
const SECRET = "TOP-SECRET-7f3a";

type Layout = { readonly root: string; readonly outside: string };

/** `<tmp>/subjects/root` with a file, a directory and three symlinks, beside `<tmp>/outside`. */
async function layout(t: Parameters<typeof tempDir>[0]): Promise<Layout> {
  const base = await tempDir(t, "perk-v2-env-");
  const outside = join(base, "outside");
  mkdirSync(join(outside, "sub"), { recursive: true });
  writeFileSync(join(outside, "secret.txt"), `${SECRET}\n`);
  const root = join(base, "subjects", "root");
  mkdirSync(join(root, "dir"), { recursive: true });
  writeFileSync(join(root, "file.txt"), "inside\n");
  writeFileSync(join(root, "dir", "inner.txt"), "inner\n");
  symlinkSync(join(outside, "secret.txt"), join(root, "link-out-file"));
  symlinkSync(outside, join(root, "link-out-dir"));
  symlinkSync("file.txt", join(root, "link-in"));
  return { root, outside };
}

function errorCodeOf<T>(result: Result<T, { readonly code: string }>): string | null {
  return result.ok ? null : result.error.code;
}

async function openEnv(root: string): Promise<SnapshotEnv> {
  const env = await SnapshotEnv.open(root);
  assert.ok(env !== null, "a real directory opens");
  return env;
}

test("A3: escapes and symlink components are refused; inside paths are allowed", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { root, outside } = await layout(t);
  const env = await openEnv(root);
  const denied = [
    "..",
    "../outside/secret.txt",
    "dir/../../outside/secret.txt",
    join(outside, "secret.txt"),
    "/etc/hostname",
    "link-out-file",
    "link-out-dir",
    "link-out-dir/secret.txt",
    "link-in",
  ];
  for (const path of denied) {
    assert.equal(errorCodeOf(await env.absolutePath(path, context)), "permission_denied", path);
    assert.equal(errorCodeOf(await env.readTextFile(path, context)), "permission_denied", path);
    assert.equal(errorCodeOf(await env.exists(path, context)), "permission_denied", path);
    assert.equal(errorCodeOf(await env.listDir(path, context)), "permission_denied", path);
    assert.equal(errorCodeOf(await env.fileInfo(path, context)), "permission_denied", path);
    assert.equal(
      errorCodeOf(await env.openBinaryReader(path, undefined, context)),
      "permission_denied",
      path,
    );
  }
  for (const path of ["", "a\0b"]) {
    assert.equal(
      errorCodeOf(await env.absolutePath(path, context)),
      "invalid",
      JSON.stringify(path),
    );
    assert.equal(
      errorCodeOf(await env.readTextFile(path, context)),
      "invalid",
      JSON.stringify(path),
    );
  }
  const allowed = await env.readTextFile("dir/../file.txt", context);
  assert.deepEqual(allowed, { ok: true, value: "inside\n" });
  const absolute = await env.readTextFile(join(root, "dir", "inner.txt"), context);
  assert.deepEqual(absolute, { ok: true, value: "inner\n" });
  assert.deepEqual(await env.absolutePath(".", context), { ok: true, value: root });
  assert.deepEqual(await env.canonicalPath("file.txt", context), {
    ok: true,
    value: join(root, "file.txt"),
  });
  assert.deepEqual(await env.exists("absent.txt", context), { ok: true, value: false });
  assert.equal(errorCodeOf(await env.readTextFile("absent.txt", context)), "not_found");
});

test("A3: every write member is refused and leaves the tree byte-identical; no exec or watch", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { root } = await layout(t);
  const env: ExecutionEnv = await openEnv(root);
  const before = readTree(root);
  const writes: [string, () => Promise<Result<unknown, { readonly code: string }>>][] = [
    ["writeFile", () => env.writeFile("file.txt", "x", context)],
    ["writeFile (new)", () => env.writeFile("new.txt", "x", context)],
    ["appendFile", () => env.appendFile("file.txt", "x", context)],
    ["truncateFile", () => env.truncateFile("file.txt", 0, context)],
    ["flushFile", () => env.flushFile("file.txt", context)],
    ["renameFile", () => env.renameFile("file.txt", "moved.txt", context)],
    ["createDir", () => env.createDir("made", { recursive: true }, context)],
    ["remove", () => env.remove("file.txt", { recursive: true, force: true }, context)],
    ["createTempDir", () => env.createTempDir("x", context)],
    ["createTempFile", () => env.createTempFile({}, context)],
  ];
  for (const [name, write] of writes) {
    assert.equal(errorCodeOf(await write()), "permission_denied", name);
  }
  assert.deepEqual(readTree(root), before, "byte-identical");
  assert.equal(
    errorCodeOf(await env.exec("cat file.txt", undefined, context)),
    "shell_unavailable",
  );
  assert.equal(errorCodeOf(await env.watch([], () => {}, context)), "not_supported");
  assert.equal(env.listFiles, undefined, "listFiles is not implemented");
});

test("A3: the root is trusted only as a real directory, at open and at every gate", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const { root, outside } = await layout(t);
  const base = join(root, "..", "..");
  const linkedRoot = join(base, "subjects", "linked");
  symlinkSync(root, linkedRoot);
  assert.equal(await SnapshotEnv.open(linkedRoot), null, "a symlink to a real directory");
  assert.equal(await SnapshotEnv.open(join(root, "file.txt")), null, "a file");
  assert.equal(await SnapshotEnv.open(join(base, "subjects", "absent")), null, "absent");

  const env = await openEnv(root);
  assert.deepEqual(await env.readTextFile("file.txt", context), { ok: true, value: "inside\n" });
  renameSync(root, `${root}.moved`);
  symlinkSync(outside, root);
  defer(t, () => {
    unlinkSync(root);
    renameSync(`${root}.moved`, root);
  });
  for (const path of [".", "secret.txt", "sub", join(root, "secret.txt")]) {
    assert.equal(errorCodeOf(await env.readTextFile(path, context)), "permission_denied", path);
    assert.equal(errorCodeOf(await env.listDir(path, context)), "permission_denied", path);
    assert.equal(errorCodeOf(await env.exists(path, context)), "permission_denied", path);
  }
});

test("A3 (in run): escaping reads are errors with no outside content; bash is unavailable", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const outside = await tempDir(t, "perk-v2-outside-");
  writeFileSync(join(outside, "secret.txt"), `${SECRET}\n`);
  const started = await startNative(t, (tree) => ({
    a: [
      round(
        call("read", { path: join(outside, "secret.txt") }, "e1"),
        call("read", { path: `../${tree}.manifest` }, "e2"),
        call("ls", { path: ".." }, "e3"),
        call("grep", { text: SECRET, path: outside }, "e4"),
        call("find", { pattern: "**", path: "../.." }, "e5"),
        call("bash", { command: `cat ${join(outside, "secret.txt")}` }, "e6"),
      ),
      reportCall(tree),
    ],
    b: [reportCall(tree)],
  }));
  const { tree, store } = started;
  const view = expectQuiescent(started.outcome).view;
  assert.equal(view.waitReason, "pending_decision");
  assertScript(started.script, { a: { consumed: 2, leftover: 0 } });
  const results = await withStore(store, async (storeView) => {
    const worker = view.records.durableMap.get(fixtureAttemptId("a", tree));
    assert.ok(worker !== undefined);
    return storeView.toolResults(worker.durableId);
  });
  const escapes = results.filter((result) => result.message.toolName !== "report");
  assert.deepEqual(
    escapes
      .map((result) => [result.message.toolCallId, result.message.isError])
      .sort(([a], [b]) => String(a).localeCompare(String(b))),
    [
      ["e1", true],
      ["e2", true],
      ["e3", true],
      ["e4", true],
      ["e5", true],
      ["e6", true],
    ],
  );
  for (const result of escapes) {
    const codes = result.diagnostics.map((diagnostic) => diagnostic.code);
    if (result.message.toolCallId === "e6") {
      assert.deepEqual(codes, ["tool_unavailable"], "bash is not a worker tool");
    } else {
      assert.deepEqual(codes, ["tool_error"], String(result.message.toolCallId));
      assert.match(result.text, /escapes the snapshot root/);
    }
  }
  const manifestLine = readFileSync(snapshotManifestPath(store, tree), "utf8").split("\n")[0];
  assert.ok(manifestLine !== undefined && manifestLine.length > 0);
  for (const text of await allWorkerResultTexts(store)) {
    assert.ok(!text.includes(SECRET), "no outside content");
    assert.ok(!text.includes(manifestLine), "no manifest content");
  }
});

test("A3 (in run): a root swapped for an outside symlink mid-run fails closed", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const outside = await tempDir(t, "perk-v2-outside-");
  writeFileSync(join(outside, "secret.txt"), `${SECRET}\n`);
  const subject = await fixtureSubject(t);
  const { tree, store } = subject;
  const host = nativeOptions(store);
  const both = barrier(2);
  let restoreRoot: (() => void) | undefined;
  const restored = deferred();
  defer(t, () => restoreRoot?.());
  const script = roleScript(host.setup.faux, tree, {
    a: [
      async () => {
        await both.arrive();
        const root = snapshotDir(store, tree);
        renameSync(root, `${root}.moved`);
        symlinkSync(outside, root);
        restoreRoot = () => {
          unlinkSync(root);
          renameSync(`${root}.moved`, root);
        };
        return round(call("read", { path: "secret.txt" }, "s1"));
      },
      after(() => {
        restoreRoot?.();
        restoreRoot = undefined;
        restored.resolve();
      }, reportCall(tree)),
    ],
    b: [
      after(async () => {
        await both.arrive();
        await restored.promise;
      }, reportCall(tree)),
    ],
  });
  const outcome = await runHost(host.options, { type: "start", observe: subject.observe });
  const view = expectQuiescent(outcome).view;
  assert.equal(view.waitReason, "pending_decision", "both reports accepted after the restore");
  assertScript(script, { a: { consumed: 2, leftover: 0 }, b: { consumed: 1, leftover: 0 } });
  const results = await withStore(store, async (storeView) => {
    const worker = view.records.durableMap.get(fixtureAttemptId("a", tree));
    assert.ok(worker !== undefined);
    return storeView.toolResults(worker.durableId);
  });
  const read = results.find((result) => result.message.toolCallId === "s1");
  assert.equal(read?.message.isError, true, "the read under a swapped root is an error");
  for (const text of await allWorkerResultTexts(store)) {
    assert.ok(!text.includes(SECRET), "no outside content");
  }
});

test("A3 (control): the same tools succeed on inside paths", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const started = await startNative(t, (tree) => ({
    a: [
      round(
        call("read", { path: "a.txt" }, "i1"),
        call("ls", {}, "i2"),
        call("grep", { text: "beta" }, "i3"),
        call("find", { pattern: "**/*.ts" }, "i4"),
      ),
      reportCall(tree),
    ],
    b: [reportCall(tree)],
  }));
  const view = expectQuiescent(started.outcome).view;
  assert.equal(view.waitReason, "pending_decision");
  const results = await withStore(started.store, async (storeView) => {
    const worker = view.records.durableMap.get(fixtureAttemptId("a", started.tree));
    assert.ok(worker !== undefined);
    return storeView.toolResults(worker.durableId);
  });
  const texts = new Map(
    results
      .filter((result) => result.message.toolName !== "report")
      .map((result) => [result.message.toolCallId, [result.message.isError, result.text]]),
  );
  assert.deepEqual(Object.fromEntries(texts), {
    i1: [false, "alpha\n"],
    i2: [false, "a.txt\ndir/"],
    i3: [false, "dir/b.ts:1:beta"],
    i4: [false, "dir/b.ts"],
  });
});

test("A3 (fail closed): the env factory gives a non-worker conversation no environment", {
  timeout: CASE_TIMEOUT_MS,
}, async (t) => {
  const started = await startNative(t, (tree) => ({
    a: [reportCall(tree)],
    b: [reportCall(tree)],
  }));
  const view = expectQuiescent(started.outcome).view;
  const worker = view.records.durableMap.get(fixtureAttemptId("a", started.tree));
  assert.ok(worker !== undefined);
  const opened = await openStoreHarness(t, started.store, composeProgram(started.options));
  const factory = snapshotEnvFactory({ snapshotRoot: (tree) => snapshotDir(started.store, tree) });
  const envFor = (conversationId: number, cwd: string | undefined) =>
    factory(
      {
        conversationId: conversationId as ConversationId,
        ...(cwd === undefined ? {} : { cwd }),
        read: opened.harness,
      },
      context,
    );
  assert.equal(
    await envFor(opened.root.id, WORKSPACE_ROOT),
    undefined,
    "the execution conversation",
  );
  assert.equal(await envFor(opened.root.id, undefined), undefined, "no cwd");
  assert.equal(await envFor(worker.durableId, "elsewhere"), undefined, "another cwd");
  assert.equal(await envFor(worker.durableId, undefined), undefined, "a worker without its cwd");
  assert.equal(await envFor(9_999_999, WORKSPACE_ROOT), undefined, "an unknown conversation");
  const env = await envFor(worker.durableId, WORKSPACE_ROOT);
  assert.ok(env instanceof SnapshotEnv, "the worker conversation gets the snapshot environment");
  assert.equal(env.cwd, snapshotDir(started.store, started.tree));
  await opened.dispose();
});
