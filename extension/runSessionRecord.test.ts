// Live composition tests for the run-session record write at `session_start` (contracts.md §8.35
// `sessions`) over the REAL bound ports (offline — no LLM, no network): every IDENTIFIED arm
// (claim / keep / fork / adopt / mint) of a file-backed session with a canonical run id records
// exactly one `{pi_session_id, session_file, cwd, at}` entry under its OWN run id; a reload is the
// in-place `unchanged`; an in-memory session or a non-canonical id records no entry. The class/site
// capture's own (permissive) write path is pinned here only as the scoping boundary of the new
// gate — its behavior matrix lives in `sessionLifecycle.test.ts`.
//
// The harness's `scaffoldRepo()` cwd is NOT git-inited, so `mainCheckoutRoot(cwd)` falls back to
// the cwd and every write lands under it — except the one linked-worktree case at the end, which
// pins the main-checkout placement the fallback cases cannot distinguish.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, realpathSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { workflowDir } from "./substrate/cache.ts";
import {
  readSessionPointers,
  recordSessionPointer,
  type SessionPointer,
} from "./substrate/sessionPointers.ts";
import { gitInit, loadPerkSession, plantSession, scaffoldRepo } from "./testing/harness.ts";

// A canonical run id — the `01RID` fixtures the sibling suites use are deliberately
// non-canonical and never reach the new write.
const RID = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const TO_ISO_STRING = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;

test("claimed: the cold claim records its conversation beside the implementation capture", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: RID, mode: "read-write", stage: "implement" } });
  const file = plantSession(cwd, []);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: RID },
    sessionManager: SessionManager.open(file),
  });
  try {
    assert.equal(h.workflowState().run_id, RID);
    const record = readSessionPointers(cwd, RID);
    assert.ok(record !== null);
    // The two capture kinds coexist in ONE file.
    assert.equal(record.implementation.main?.pi_session_id, "planted-parent.jsonl");
    assert.equal(record.sessions.length, 1);
    const entry = record.sessions[0];
    assert.ok(entry);
    assert.match(entry.at, TO_ISO_STRING);
    assert.deepEqual(entry, {
      pi_session_id: "planted-parent.jsonl",
      session_file: file,
      cwd,
      at: entry.at,
    });
  } finally {
    h.dispose();
  }
});

test("kept: one entry, and a reload is the in-place `unchanged` (byte-identical `at`)", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [
    { run_id: RID, pi_session_id: "planted-parent.jsonl", mode: "read-write", stage: "implement" },
  ]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    const first = readSessionPointers(cwd, RID)?.sessions;
    assert.equal(first?.length, 1);
    assert.equal(first?.[0]?.pi_session_id, "planted-parent.jsonl");
    assert.equal(first?.[0]?.session_file, file);
    assert.equal(first?.[0]?.cwd, cwd);

    await h.emitSessionStart();
    const again = readSessionPointers(cwd, RID)?.sessions;
    assert.deepEqual(again, first, "a reload never duplicates or refreshes the entry");
  } finally {
    h.dispose();
  }
});

test("forked: the child records under its derived id; the parent's record is untouched", async () => {
  const cwd = scaffoldRepo();
  // A planted state whose pi_session_id differs from the file basename forces the fork arm.
  const file = plantSession(
    cwd,
    [{ run_id: RID, pi_session_id: "parent.jsonl", mode: "read-write" }],
    {
      fileName: "child.jsonl",
    },
  );
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    assert.equal(h.workflowState().run_id, `${RID}.1`);
    const child = readSessionPointers(cwd, `${RID}.1`);
    assert.equal(child?.sessions.length, 1);
    assert.equal(child?.sessions[0]?.pi_session_id, "child.jsonl");
    assert.equal(child?.sessions[0]?.session_file, file);
    assert.equal(readSessionPointers(cwd, RID), null, "the parent never wrote a record here");
  } finally {
    h.dispose();
  }
});

test("adopted: an env-child records under its derived id; the parent's slots and sessions are untouched", async () => {
  const cwd = scaffoldRepo({
    handoff: {
      runId: RID,
      mode: "read-only",
      stage: "plan",
      consumed: true,
      piSessionId: "parent.jsonl",
    },
  });
  const parentPointer: SessionPointer = {
    pi_session_id: "parent.jsonl",
    session_file: "/sessions/parent.jsonl",
    parent_pi_session_id: null,
    at: "2026-06-01T00:00:00Z",
  };
  recordSessionPointer(cwd, RID, "implementation", "main", parentPointer);
  const file = plantSession(cwd, [], { fileName: "child.jsonl" });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: RID },
    sessionManager: SessionManager.open(file),
  });
  try {
    assert.equal(h.workflowState().run_id, `${RID}.1`);
    const child = readSessionPointers(cwd, `${RID}.1`);
    assert.equal(child?.sessions.length, 1);
    assert.equal(child?.sessions[0]?.pi_session_id, "child.jsonl");
    assert.equal(child?.implementation.main, null, "an adopted child captures no slot");
    const parent = readSessionPointers(cwd, RID);
    assert.deepEqual(parent?.implementation.main, parentPointer);
    assert.deepEqual(parent?.sessions, []);
  } finally {
    h.dispose();
  }
});

test("minted: a warm identity-less file-backed session records under its minted id", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, []);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    const runId = h.workflowState().run_id;
    assert.ok(runId, "a run id was minted");
    const record = readSessionPointers(cwd, runId);
    assert.equal(record?.sessions.length, 1);
    assert.equal(record?.sessions[0]?.pi_session_id, "planted-parent.jsonl");
    assert.equal(record?.sessions[0]?.session_file, file);
  } finally {
    h.dispose();
  }
});

test("in-memory: a session without a file records nothing (and warns nothing)", async (t) => {
  const errors: string[] = [];
  t.mock.method(console, "error", (message: unknown) => errors.push(String(message)));
  const cwd = scaffoldRepo({ handoff: { runId: RID, mode: "read-write", stage: "implement" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: RID } });
  try {
    assert.equal(h.workflowState().run_id, RID, "the claim still settles");
    assert.equal(readSessionPointers(cwd, RID), null);
    assert.equal(errors.filter((line) => line.includes("could not record run session")).length, 0);
  } finally {
    h.dispose();
  }
});

test("linked worktree: the record lands under the MAIN checkout while the entry keeps the worktree cwd", async () => {
  // The placement pin: `session_start` must route the write through `mainCheckoutRoot(cwd)`.
  // Every fallback case above has cwd == carrier root and would pass even if it did not.
  const main = scaffoldRepo();
  gitInit(main, { dirty: false });
  const wt = join(main, "..", `${main.split("/").pop()}-wt`);
  execFileSync("git", ["worktree", "add", "-q", "-b", "plan-x", wt], {
    cwd: main,
    stdio: "ignore",
  });
  try {
    mkdirSync(join(workflowDir(wt), "handoff"), { recursive: true });
    const file = plantSession(wt, [
      {
        run_id: RID,
        pi_session_id: "planted-parent.jsonl",
        mode: "read-write",
        stage: "implement",
      },
    ]);
    const h = await loadPerkSession({ cwd: wt, sessionManager: SessionManager.open(file) });
    try {
      assert.equal(h.workflowState().run_id, RID);
      // Read through the SAME resolution the writer used (realpath both sides: macOS tmp paths
      // alias /private/var ↔ /var, and git reports the physical location).
      const record = readSessionPointers(main, RID);
      assert.ok(record !== null, "the record exists under the main checkout");
      assert.equal(record.sessions.length, 1);
      assert.equal(record.sessions[0]?.pi_session_id, "planted-parent.jsonl");
      assert.equal(record.sessions[0]?.session_file, file);
      assert.equal(
        realpathSync(record.sessions[0]?.cwd ?? ""),
        realpathSync(wt),
        "the entry records the linked worktree as its cwd",
      );
      assert.equal(
        readSessionPointers(wt, RID),
        null,
        "no record was written under the linked worktree's own scratch tree",
      );
    } finally {
      h.dispose();
    }
  } finally {
    execFileSync("git", ["worktree", "remove", "--force", wt], { cwd: main, stdio: "ignore" });
  }
});

test("non-canonical id: no sessions entry, while the class/site capture's permissive path is unchanged", async () => {
  // The scoping boundary of the grammar gate: it guards THIS record only.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  const file = plantSession(cwd, []);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    sessionManager: SessionManager.open(file),
  });
  try {
    assert.equal(h.workflowState().run_id, "01RID");
    const record = readSessionPointers(cwd, "01RID");
    assert.equal(record?.implementation.main?.pi_session_id, "planted-parent.jsonl");
    assert.deepEqual(record?.sessions, []);
  } finally {
    h.dispose();
  }
});
