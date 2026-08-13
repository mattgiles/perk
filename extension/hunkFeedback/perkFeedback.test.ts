// The bundled Hunk publisher's event contract (§8.58): version/payload gates, refusal arms,
// the single-append publish, and the path parity that pins the standalone construction site to
// the interior cache seam.

import assert from "node:assert/strict";
import { appendFileSync, mkdirSync, mkdtempSync, realpathSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { hunkOutboxPath, hunkWatchDir } from "../substrate/cache.ts";
import perkFeedback, {
  buildFeedbackRecord,
  createPublisher,
  type HunkApiSlice,
  type HunkReviewNote,
  hunkWatchPaths,
  MAX_BODY_BYTES,
  MAX_RECORD_BYTES,
  normalizeBody,
  type PublisherDeps,
  SUPPORTED_HUNK_API_VERSIONS,
  validateNotePayload,
} from "./perkFeedback.ts";
import { readOutbox } from "./store.ts";

function tmp(): string {
  // realpath'd up front: the publisher realpath-compares the event cwd against the declared
  // root and derives the store path from the RESOLVED root, and macOS /tmp is a symlink.
  return realpathSync(mkdtempSync(join(tmpdir(), "perk-hunk-pub-")));
}

function note(overrides: Partial<HunkReviewNote> = {}): HunkReviewNote {
  return {
    id: "note-1",
    fileId: "f1",
    filePath: "src/a.ts",
    hunkIndex: 2,
    side: "new",
    line: 14,
    body: "tighten this loop",
    draft: false,
    ...overrides,
  };
}

/** A fake Hunk API: records handlers + logs; `emit` drives events with a notify-capturing ctx. */
class FakeHunk implements HunkApiSlice {
  readonly apiVersion: number;
  readonly handlers = new Map<string, (payload: unknown, ctx: unknown) => void>();
  readonly logs: string[] = [];
  readonly notifies: { message: string; type?: string }[] = [];
  constructor(apiVersion: number) {
    this.apiVersion = apiVersion;
  }
  on(event: string, handler: (payload: never, ctx: never) => void): void {
    this.handlers.set(event, handler as (payload: unknown, ctx: unknown) => void);
  }
  log(message: string): void {
    this.logs.push(message);
  }
  emit(event: string, payload: unknown, cwd: string): void {
    this.handlers.get(event)?.(payload, {
      cwd,
      notify: (message: string, type?: string) => this.notifies.push({ message, type }),
    });
  }
}

function withEnv<T>(env: Record<string, string | undefined>, fn: () => T): T {
  const saved = new Map<string, string | undefined>();
  for (const [key, value] of Object.entries(env)) {
    saved.set(key, process.env[key]);
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  try {
    return fn();
  } finally {
    for (const [key, value] of saved) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

function launchEnv(root: string): Record<string, string> {
  return {
    PERK_HUNK_WATCH_ID: "01WATCH",
    PERK_HUNK_PLAN_ID: "42",
    PERK_HUNK_WORKTREE_ROOT: root,
  };
}

// --- pure helpers ------------------------------------------------------------------------------

test("normalizeBody: CRLF → LF, outer trim", () => {
  assert.equal(normalizeBody("  a\r\nb\r\nc \n"), "a\nb\nc");
  assert.equal(normalizeBody(" \r\n "), "");
});

test("validateNotePayload: the strict draft gate", () => {
  assert.equal(validateNotePayload({ note: note() }).ok, true);
  assert.deepEqual(validateNotePayload({ note: note({ draft: true }) }), {
    ok: false,
    kind: "draft",
  });
  const anomalous = validateNotePayload({ note: { ...note(), draft: "no" } });
  assert.ok(!anomalous.ok && anomalous.kind === "anomalous-draft");
  const missing = validateNotePayload({ note: { ...note(), draft: undefined } });
  assert.ok(!missing.ok && missing.kind === "anomalous-draft");
});

test("validateNotePayload: malformed fields are named", () => {
  const cases: [Partial<HunkReviewNote>, RegExp][] = [
    [{ id: "" }, /id/],
    [{ filePath: "" }, /filePath/],
    [{ hunkIndex: -1 }, /hunkIndex/],
    [{ hunkIndex: 1.5 }, /hunkIndex/],
    [{ side: "both" as never }, /side/],
    [{ line: 0 }, /line/],
    [{ body: 7 as never }, /body/],
  ];
  for (const [override, pattern] of cases) {
    const result = validateNotePayload({ note: { ...note(), ...override } });
    assert.ok(!result.ok && result.kind === "malformed", JSON.stringify(override));
    assert.match(result.detail, pattern);
  }
  const noNote = validateNotePayload({});
  assert.ok(!noNote.ok && noNote.kind === "malformed");
});

test("buildFeedbackRecord: stable identity + anchor mapping", () => {
  const record = buildFeedbackRecord(note(), {
    watchId: "01WATCH",
    planId: "SAV-9",
    changesetId: "cs-1",
    createdAt: "2026-01-01T00:00:00.000Z",
  });
  assert.equal(record.feedback_id, "01WATCH:note-1");
  assert.equal(record.plan_id, "SAV-9");
  assert.deepEqual(record.anchor, { file_path: "src/a.ts", hunk_index: 2, side: "new", line: 14 });
});

test("path parity: hunkWatchPaths equals the interior cache-seam helpers", () => {
  const root = "/some/worktree";
  const paths = hunkWatchPaths(root);
  assert.equal(paths.dir, hunkWatchDir(root));
  assert.equal(paths.outbox, hunkOutboxPath(root));
});

// --- createPublisher ---------------------------------------------------------------------------

function publisherIn(root: string, overrides: Partial<PublisherDeps> = {}) {
  const appends: { path: string; line: string }[] = [];
  const publisher = createPublisher({
    watchId: "01WATCH",
    planId: "42",
    worktreeRoot: root,
    append: (path, line) => appends.push({ path, line }),
    now: () => "2026-01-01T00:00:00.000Z",
    ...overrides,
  });
  return { publisher, appends };
}

test("publish: one valid note → one full-line append under the declared root", () => {
  const root = tmp();
  const { publisher, appends } = publisherIn(root);
  const result = publisher.publish({ note: note() }, { cwd: root, changesetId: "cs-7" });
  assert.equal(result.status, "published");
  assert.equal(appends.length, 1);
  assert.equal(appends[0]?.path, hunkWatchPaths(root).outbox);
  assert.ok(appends[0]?.line.endsWith("\n"));
  const parsed = JSON.parse(appends[0]?.line ?? "");
  assert.equal(parsed.feedback_id, "01WATCH:note-1");
  assert.equal(parsed.changeset_id, "cs-7");
});

test("publish: a cwd that is not the declared worktree is refused, nothing written", () => {
  const root = tmp();
  const elsewhere = tmp();
  const { publisher, appends } = publisherIn(root);
  const result = publisher.publish({ note: note() }, { cwd: elsewhere, changesetId: null });
  assert.equal(result.status, "refused");
  assert.ok(result.status === "refused" && /not the watched worktree/.test(result.warning));
  assert.deepEqual(appends, []);
});

test("publish: empty and oversized bodies are refused (never truncated, never 'queued')", () => {
  const root = tmp();
  const { publisher, appends } = publisherIn(root);
  const empty = publisher.publish(
    { note: note({ body: "  \r\n " }) },
    { cwd: root, changesetId: null },
  );
  assert.ok(empty.status === "refused" && /empty/.test(empty.warning));
  const oversized = publisher.publish(
    { note: note({ body: "x".repeat(MAX_BODY_BYTES + 1) }) },
    { cwd: root, changesetId: null },
  );
  assert.ok(oversized.status === "refused" && /NOT queued/.test(oversized.warning));
  assert.deepEqual(appends, []);
});

test("publish: byte bounds are UTF-8 bytes with exact boundaries (never char counts)", () => {
  const root = tmp();
  const { publisher, appends } = publisherIn(root);
  // Exactly MAX_BODY_BYTES is legal…
  const exact = publisher.publish(
    { note: note({ body: "x".repeat(MAX_BODY_BYTES) }) },
    { cwd: root, changesetId: null },
  );
  assert.equal(exact.status, "published");
  // …and a MULTIBYTE body one byte over is refused even though its CHARACTER count is far
  // below the limit (é = 2 UTF-8 bytes): the bound is bytes, not JS string length.
  const multibyte = `${"é".repeat(MAX_BODY_BYTES / 2 - 1)}abc`; // 16385 bytes, 8194 chars
  assert.equal(Buffer.byteLength(multibyte, "utf8"), MAX_BODY_BYTES + 1);
  const over = publisher.publish(
    { note: note({ body: multibyte }) },
    { cwd: root, changesetId: null },
  );
  assert.ok(over.status === "refused" && /NOT queued/.test(over.warning));
  assert.equal(appends.length, 1); // only the exact-boundary publish appended
});

test("publish: a legal body with oversized metadata trips the RECORD bound, nothing appended", () => {
  const root = tmp();
  const { publisher, appends } = publisherIn(root);
  // Body legal (≤ 16 KiB) but a pathological filePath pushes the serialized record past 32 KiB.
  const result = publisher.publish(
    {
      note: note({
        body: "x".repeat(MAX_BODY_BYTES - 1),
        filePath: `src/${"p".repeat(MAX_RECORD_BYTES - MAX_BODY_BYTES)}.ts`,
      }),
    },
    { cwd: root, changesetId: null },
  );
  assert.ok(result.status === "refused");
  assert.match(result.warning, /serialized feedback record exceeds/);
  assert.deepEqual(appends, []);
});

test("publish: a symlinked outbox (or hunk-watch dir) is refused, nothing written through it", () => {
  const root = tmp();
  const paths = hunkWatchPaths(root);
  mkdirSync(paths.dir, { recursive: true });
  const elsewhere = join(root, "exfil.ndjson");
  appendFileSync(elsewhere, "", "utf8");
  symlinkSync(elsewhere, paths.outbox);
  const { publisher, appends } = publisherIn(root);
  const viaFile = publisher.publish({ note: note() }, { cwd: root, changesetId: null });
  assert.ok(viaFile.status === "refused" && /outbox is a symlink/.test(viaFile.warning));
  assert.deepEqual(appends, []);

  // A symlinked FAMILY DIR is refused too (any component under the worktree root).
  const root2 = tmp();
  const real = join(root2, "elsewhere");
  mkdirSync(real, { recursive: true });
  mkdirSync(join(root2, ".perk", "workflow"), { recursive: true });
  symlinkSync(real, join(root2, ".perk", "workflow", "hunk-watch"));
  const second = publisherIn(root2);
  const viaDir = second.publisher.publish({ note: note() }, { cwd: root2, changesetId: null });
  assert.ok(viaDir.status === "refused" && /hunk-watch dir is symlinked/.test(viaDir.warning));
  assert.deepEqual(second.appends, []);
});

test("publish: an append failure surfaces the concrete error and never claims queued", () => {
  const root = tmp();
  const { publisher } = publisherIn(root, {
    append: () => {
      throw new Error("ENOSPC: no space left on device");
    },
  });
  const result = publisher.publish({ note: note() }, { cwd: root, changesetId: null });
  assert.ok(result.status === "refused" && /ENOSPC/.test(result.warning));
});

test("publish: two publisher instances interleave safely with unique stable ids", () => {
  const root = tmp();
  const outbox = hunkWatchPaths(root).outbox;
  const realAppend = (path: string, line: string) => {
    // The factory's production append — recreated here to exercise the real file interleave.
    mkdirSync(hunkWatchPaths(root).dir, { recursive: true });
    if (path !== outbox) throw new Error(`unexpected path ${path}`);
    appendFileSync(path, line, "utf8");
  };
  const a = createPublisher({
    watchId: "01WATCHA",
    planId: "42",
    worktreeRoot: root,
    append: realAppend,
    now: () => "2026-01-01T00:00:00.000Z",
  });
  const b = createPublisher({
    watchId: "01WATCHB",
    planId: "42",
    worktreeRoot: root,
    append: realAppend,
    now: () => "2026-01-01T00:00:01.000Z",
  });
  assert.equal(
    a.publish({ note: note({ id: "n1" }) }, { cwd: root, changesetId: null }).status,
    "published",
  );
  assert.equal(
    b.publish({ note: note({ id: "n1" }) }, { cwd: root, changesetId: null }).status,
    "published",
  );
  assert.equal(
    a.publish({ note: note({ id: "n2" }) }, { cwd: root, changesetId: null }).status,
    "published",
  );
  const read = readOutbox(outbox);
  assert.deepEqual(read.warnings, []);
  assert.deepEqual(
    read.records.map((r) => r.feedback_id),
    ["01WATCHA:n1", "01WATCHB:n1", "01WATCHA:n2"],
  );
});

// --- the extension factory -----------------------------------------------------------------

test("factory: a saved note publishes one valid record and notifies queued", () => {
  const root = tmp();
  withEnv(launchEnv(root), () => {
    const hunk = new FakeHunk(2);
    perkFeedback(hunk);
    hunk.emit("startup", { cwd: root }, root);
    assert.ok(hunk.notifies.some((n) => n.message.includes("perk feedback active")));
    hunk.emit("changeset_loaded", { changeset: { id: "cs-1" } }, root);
    hunk.emit("note_created", { note: note() }, root);
    assert.ok(
      hunk.notifies.some((n) => n.message === "Feedback queued for the implementation session"),
    );
    const read = readOutbox(hunkOutboxPath(root));
    assert.equal(read.records.length, 1);
    assert.equal(read.records[0]?.feedback_id, "01WATCH:note-1");
    assert.equal(read.records[0]?.changeset_id, "cs-1");
    assert.equal(read.records[0]?.watch_instance_id, "01WATCH");
    assert.equal(read.records[0]?.plan_id, "42");
  });
});

test("factory: only note_created can publish — note_edited has NO handler", () => {
  const root = tmp();
  withEnv(launchEnv(root), () => {
    const hunk = new FakeHunk(4);
    perkFeedback(hunk);
    assert.deepEqual([...hunk.handlers.keys()].sort(), [
      "changeset_loaded",
      "note_created",
      "session_reload",
      "startup",
    ]);
  });
});

test("factory: draft-true is skipped silently; a non-boolean draft is skipped with a log", () => {
  const root = tmp();
  withEnv(launchEnv(root), () => {
    const hunk = new FakeHunk(2);
    perkFeedback(hunk);
    hunk.emit("note_created", { note: note({ draft: true }) }, root);
    assert.deepEqual(hunk.notifies, []);
    assert.deepEqual(hunk.logs, []);
    hunk.emit("note_created", { note: { ...note(), draft: "weird" } }, root);
    assert.deepEqual(hunk.notifies, []);
    assert.equal(hunk.logs.length, 1);
    assert.match(hunk.logs[0] ?? "", /note\.draft/);
    assert.deepEqual(readOutbox(hunkOutboxPath(root)).records, []);
  });
});

test("factory: malformed payloads are refused visibly, nothing written", () => {
  const root = tmp();
  withEnv(launchEnv(root), () => {
    const hunk = new FakeHunk(2);
    perkFeedback(hunk);
    hunk.emit("note_created", { note: { ...note(), line: 0 } }, root);
    assert.equal(hunk.notifies.length, 1);
    assert.match(hunk.notifies[0]?.message ?? "", /not queued.*line/);
    assert.equal(hunk.notifies[0]?.type, "warning");
    assert.deepEqual(readOutbox(hunkOutboxPath(root)).records, []);
  });
});

test("factory: unsupported apiVersions register no note handler and warn once at startup", () => {
  const root = tmp();
  withEnv(launchEnv(root), () => {
    for (const version of [1, 3, 5, Number.NaN]) {
      const hunk = new FakeHunk(version);
      perkFeedback(hunk);
      assert.ok(!hunk.handlers.has("note_created"), `v${version} must not register note_created`);
      assert.deepEqual([...hunk.handlers.keys()], ["startup"]); // reviewing intact
      hunk.emit("startup", { cwd: root }, root);
      assert.equal(hunk.notifies.length, 1);
      assert.match(hunk.notifies[0]?.message ?? "", /perk feedback disabled/);
      assert.match(hunk.notifies[0]?.message ?? "", /v\{2, 4\}/);
      assert.equal(hunk.logs.length, 1);
    }
    // The verified set itself is pinned: exactly {2, 4} until a new artifact is examined.
    assert.deepEqual([...SUPPORTED_HUNK_API_VERSIONS].sort(), [2, 4]);
  });
});

test("factory: missing/blank launch metadata disables feedback with one loud startup warning", () => {
  const root = tmp();
  for (const broken of [
    { ...launchEnv(root), PERK_HUNK_WATCH_ID: undefined },
    { ...launchEnv(root), PERK_HUNK_PLAN_ID: "  " },
    { ...launchEnv(root), PERK_HUNK_WORKTREE_ROOT: undefined },
  ]) {
    withEnv(broken as Record<string, string | undefined>, () => {
      const hunk = new FakeHunk(2);
      perkFeedback(hunk);
      assert.ok(!hunk.handlers.has("note_created"));
      hunk.emit("startup", { cwd: root }, root);
      assert.equal(hunk.notifies.length, 1);
      assert.match(hunk.notifies[0]?.message ?? "", /missing launch metadata.*PERK_HUNK_/);
    });
  }
});

test("factory: session_reload retunes the retained changeset id", () => {
  const root = tmp();
  withEnv(launchEnv(root), () => {
    const hunk = new FakeHunk(2);
    perkFeedback(hunk);
    hunk.emit("changeset_loaded", { changeset: { id: "cs-1" } }, root);
    hunk.emit("note_created", { note: note({ id: "n1" }) }, root);
    hunk.emit("session_reload", { changeset: { id: "cs-2" }, reason: "watch" }, root);
    hunk.emit("note_created", { note: note({ id: "n2" }) }, root);
    const read = readOutbox(hunkOutboxPath(root));
    assert.deepEqual(
      read.records.map((r) => r.changeset_id),
      ["cs-1", "cs-2"],
    );
  });
});

test("factory: a cwd mismatch is refused visibly, nothing written", () => {
  const root = tmp();
  const elsewhere = tmp();
  withEnv(launchEnv(root), () => {
    const hunk = new FakeHunk(2);
    perkFeedback(hunk);
    hunk.emit("note_created", { note: note() }, elsewhere);
    assert.equal(hunk.notifies.length, 1);
    assert.match(hunk.notifies[0]?.message ?? "", /not queued.*not the watched worktree/);
    assert.deepEqual(readOutbox(hunkOutboxPath(root)).records, []);
  });
});
