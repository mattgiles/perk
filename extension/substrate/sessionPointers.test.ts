// Unit tests for the run-cache session-pointer carrier (contracts.md §8.35): the
// read-modify-write merge, the `captureSessionPointer` convenience, headless/best-effort no-ops,
// and the `mainCheckoutRoot` git-common-dir resolution. Offline + node builtins only.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { runScratchDir } from "./cache.ts";
import { mainCheckoutRoot } from "./git.ts";
import {
  captureSessionPointer,
  type RunSessionEntry,
  readSessionPointers,
  recordRunSession,
  recordSessionPointer,
  type SessionPointer,
} from "./sessionPointers.ts";

function tempCwd(): string {
  return mkdtempSync(join(tmpdir(), "session-pointers-test-"));
}

function captureStderr(fn: () => void): string[] {
  const lines: string[] = [];
  const original = console.error;
  console.error = (...args: unknown[]) => {
    lines.push(args.map(String).join(" "));
  };
  try {
    fn();
  } finally {
    console.error = original;
  }
  return lines;
}

const PM: SessionPointer = {
  pi_session_id: "pm.jsonl",
  session_file: "/abs/pm.jsonl",
  parent_pi_session_id: null,
  at: "2026-06-01T00:00:00Z",
};
const IM: SessionPointer = {
  pi_session_id: "im.jsonl",
  session_file: "/abs/im.jsonl",
  parent_pi_session_id: "parent.jsonl",
  at: "2026-06-02T00:00:00Z",
};

// A canonical run id — `recordRunSession` refuses anything off the strict grammar, so the
// non-canonical `01RID` fixtures above can never reach its write path.
const RID = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const SA: RunSessionEntry = {
  pi_session_id: "a.jsonl",
  session_file: "/abs/a.jsonl",
  cwd: "/abs/wt-a",
  at: "2026-06-01T00:00:00.000Z",
};
const SB: RunSessionEntry = {
  pi_session_id: "b.jsonl",
  session_file: "/abs/b.jsonl",
  cwd: "/abs/wt-b",
  at: "2026-06-02T00:00:00.000Z",
};

// The cross-plane byte pins (ASCII content) — the SAME literals live in
// tests/test_session_pointers.py; the Python writer must emit them verbatim.
const EMPTY_RECORD_BYTES = [
  "{",
  '  "run_id": "01RID",',
  '  "planning": {',
  '    "main": {',
  '      "pi_session_id": "pm.jsonl",',
  '      "session_file": "/abs/pm.jsonl",',
  '      "parent_pi_session_id": null,',
  '      "at": "2026-06-01T00:00:00Z"',
  "    },",
  '    "worker": null',
  "  },",
  '  "implementation": {',
  '    "main": null,',
  '    "worker": null',
  "  },",
  '  "sessions": []',
  "}",
  "",
].join("\n");
const TWO_SESSIONS_BYTES = [
  "{",
  `  "run_id": "${RID}",`,
  '  "planning": {',
  '    "main": null,',
  '    "worker": null',
  "  },",
  '  "implementation": {',
  '    "main": null,',
  '    "worker": null',
  "  },",
  '  "sessions": [',
  "    {",
  '      "pi_session_id": "a.jsonl",',
  '      "session_file": "/abs/a.jsonl",',
  '      "cwd": "/abs/wt-a",',
  '      "at": "2026-06-01T00:00:00.000Z"',
  "    },",
  "    {",
  '      "pi_session_id": "b.jsonl",',
  '      "session_file": "/abs/b.jsonl",',
  '      "cwd": "/abs/wt-b",',
  '      "at": "2026-06-02T00:00:00.000Z"',
  "    }",
  "  ]",
  "}",
  "",
].join("\n");

// --- read-modify-write merge ------------------------------------------------------------------

test("recordSessionPointer: a planning write and an implementation write don't clobber", () => {
  const cwd = tempCwd();
  try {
    assert.equal(recordSessionPointer(cwd, "01RID", "planning", "main", PM), true);
    assert.equal(recordSessionPointer(cwd, "01RID", "implementation", "main", IM), true);
    const record = readSessionPointers(cwd, "01RID");
    assert.ok(record !== null);
    assert.equal(record.run_id, "01RID");
    assert.deepEqual(record.planning.main, PM);
    assert.equal(record.planning.worker, null);
    assert.deepEqual(record.implementation.main, IM);
    assert.equal(record.implementation.worker, null);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("readSessionPointers: absent record is null; corrupt file is null (best-effort)", () => {
  const cwd = tempCwd();
  try {
    assert.equal(readSessionPointers(cwd, "01NOPE"), null);
    // A successful write then a deliberate corruption reads back as null, not a throw.
    recordSessionPointer(cwd, "01RID", "planning", "main", PM);
    const path = join(runScratchDir(cwd, "01RID"), "session-pointers.json");
    rmSync(path, { force: true });
    assert.equal(readSessionPointers(cwd, "01RID"), null);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("serialize is byte-stable: explicit key order + 2-space indent + trailing newline", () => {
  const cwd = tempCwd();
  try {
    recordSessionPointer(cwd, "01RID", "planning", "main", PM);
    const path = join(runScratchDir(cwd, "01RID"), "session-pointers.json");
    const raw = readFileSync(path, "utf8");
    assert.equal(raw, EMPTY_RECORD_BYTES);
    const reparsed = JSON.parse(raw);
    assert.deepEqual(Object.keys(reparsed), ["run_id", "planning", "implementation", "sessions"]);
    assert.deepEqual(Object.keys(reparsed.planning.main), [
      "pi_session_id",
      "session_file",
      "parent_pi_session_id",
      "at",
    ]);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("serialize: a two-entry sessions record matches the cross-plane byte pin", () => {
  const cwd = tempCwd();
  try {
    assert.equal(recordRunSession(cwd, RID, SA), "appended");
    assert.equal(recordRunSession(cwd, RID, SB), "appended");
    const path = join(runScratchDir(cwd, RID), "session-pointers.json");
    assert.equal(readFileSync(path, "utf8"), TWO_SESSIONS_BYTES);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- recordRunSession: the run's resumable-conversation index -----------------------------------

test("recordRunSession: appended → updated (at kept) → unchanged (no write) → a second id appends", () => {
  const cwd = tempCwd();
  try {
    assert.equal(recordRunSession(cwd, RID, SA), "appended");
    assert.deepEqual(readSessionPointers(cwd, RID)?.sessions, [SA]);

    // Same pi_session_id, differing cwd: replaced in place, `at` untouched, still ONE entry.
    const moved = {
      ...SA,
      session_file: "/moved/a.jsonl",
      cwd: "/abs/wt-a2",
      at: "2099-01-01T00:00:00.000Z",
    };
    assert.equal(recordRunSession(cwd, RID, moved), "updated");
    const afterUpdate = readSessionPointers(cwd, RID)?.sessions;
    assert.deepEqual(afterUpdate, [{ ...SA, session_file: "/moved/a.jsonl", cwd: "/abs/wt-a2" }]);

    // An identical entry is `unchanged` and the file bytes are untouched.
    const path = join(runScratchDir(cwd, RID), "session-pointers.json");
    const before = readFileSync(path, "utf8");
    assert.equal(recordRunSession(cwd, RID, moved), "unchanged");
    assert.equal(readFileSync(path, "utf8"), before);

    // A second pi_session_id appends; order is preserved.
    assert.equal(recordRunSession(cwd, RID, SB), "appended");
    assert.deepEqual(
      readSessionPointers(cwd, RID)?.sessions.map((s) => s.pi_session_id),
      ["a.jsonl", "b.jsonl"],
    );
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("recordRunSession and recordSessionPointer preserve each other's fields (the merge holds)", () => {
  const cwd = tempCwd();
  try {
    recordSessionPointer(cwd, RID, "implementation", "main", IM);
    assert.equal(recordRunSession(cwd, RID, SA), "appended");
    let record = readSessionPointers(cwd, RID);
    assert.deepEqual(record?.implementation.main, IM, "the slot survives a sessions write");
    assert.deepEqual(record?.sessions, [SA]);

    recordSessionPointer(cwd, RID, "planning", "main", PM);
    record = readSessionPointers(cwd, RID);
    assert.deepEqual(record?.sessions, [SA], "sessions survive a slot write");
    assert.deepEqual(record?.planning.main, PM);
    assert.deepEqual(record?.implementation.main, IM);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("a legacy record without `sessions` reads as [] and re-serializes with the key", () => {
  const cwd = tempCwd();
  try {
    const dir = runScratchDir(cwd, RID);
    mkdirSync(dir, { recursive: true });
    const path = join(dir, "session-pointers.json");
    writeFileSync(
      path,
      `${JSON.stringify(
        {
          run_id: RID,
          planning: { main: PM, worker: null },
          implementation: { main: null, worker: null },
        },
        null,
        2,
      )}\n`,
    );
    assert.deepEqual(readSessionPointers(cwd, RID)?.sessions, []);
    assert.equal(recordRunSession(cwd, RID, SA), "appended");
    const reparsed = JSON.parse(readFileSync(path, "utf8"));
    assert.deepEqual(Object.keys(reparsed), ["run_id", "planning", "implementation", "sessions"]);
    assert.deepEqual(reparsed.planning.main, PM);
    assert.deepEqual(reparsed.sessions, [SA]);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("recordRunSession warns + returns failed on an unwritable root, never throws", () => {
  const cwd = tempCwd();
  try {
    chmodSync(cwd, 0o500);
    let result = "appended";
    const warnings = captureStderr(() => {
      result = recordRunSession(cwd, RID, SA);
    });
    assert.equal(result, "failed");
    assert.equal(warnings.length, 1);
    assert.ok(warnings[0]?.includes(`could not record run session for ${RID}`));
  } finally {
    chmodSync(cwd, 0o700);
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("recordRunSession refuses a non-canonical run id BEFORE any path is derived", () => {
  for (const bad of [`${RID}./../x`, `${RID}/x`, "../x", "01RID"]) {
    const root = tempCwd();
    try {
      let result = "appended";
      const warnings = captureStderr(() => {
        result = recordRunSession(root, bad, SA);
      });
      assert.equal(result, "failed", `expected ${JSON.stringify(bad)} refused`);
      assert.equal(warnings.length, 1);
      assert.ok(warnings[0]?.includes("non-canonical run id"));
      assert.equal(existsSync(join(root, ".perk")), false, "nothing is created under root");
      assert.equal(existsSync(join(root, "x")), false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  }
});

// --- captureSessionPointer convenience --------------------------------------------------------

test("captureSessionPointer derives pi_session_id from the basename and threads the parent", () => {
  const cwd = tempCwd();
  try {
    const ok = captureSessionPointer({
      cwd,
      runId: "01RID",
      klass: "implementation",
      site: "main",
      sessionFile: "/sessions/abc-123.jsonl",
      parentSessionId: "parent.jsonl",
    });
    assert.equal(ok, true);
    const record = readSessionPointers(cwd, "01RID");
    assert.equal(record?.implementation.main?.pi_session_id, "abc-123.jsonl");
    assert.equal(record?.implementation.main?.session_file, "/sessions/abc-123.jsonl");
    assert.equal(record?.implementation.main?.parent_pi_session_id, "parent.jsonl");
    assert.match(record?.implementation.main?.at ?? "", /^\d{4}-/);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("captureSessionPointer: missing sessionFile or runId is a no-op (false), writes nothing", () => {
  const cwd = tempCwd();
  try {
    const base = { cwd, klass: "planning", site: "main" } as const;
    assert.equal(captureSessionPointer({ ...base, runId: "01RID", sessionFile: null }), false);
    assert.equal(captureSessionPointer({ ...base, runId: "01RID", sessionFile: "" }), false);
    assert.equal(captureSessionPointer({ ...base, runId: "", sessionFile: "/a.jsonl" }), false);
    assert.equal(readSessionPointers(cwd, "01RID"), null);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- preserveForeign: first-write-wins ---------------------------------------------------------

test("preserveForeign: a foreign pointer in the slot skips the write + warns (record unchanged)", () => {
  const cwd = tempCwd();
  try {
    recordSessionPointer(cwd, "01RID", "implementation", "main", IM);
    const path = join(runScratchDir(cwd, "01RID"), "session-pointers.json");
    const before = readFileSync(path, "utf8");
    let result = true;
    const warnings = captureStderr(() => {
      result = recordSessionPointer(cwd, "01RID", "implementation", "main", PM, {
        preserveForeign: true,
      });
    });
    assert.equal(result, false);
    assert.ok(
      warnings.some((w) => w.includes("im.jsonl") && w.includes("pm.jsonl")),
      `expected a warning naming both session ids, got ${JSON.stringify(warnings)}`,
    );
    assert.equal(readFileSync(path, "utf8"), before, "the record is byte-unchanged");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("preserveForeign: an empty slot still writes", () => {
  const cwd = tempCwd();
  try {
    const ok = recordSessionPointer(cwd, "01RID", "implementation", "main", IM, {
      preserveForeign: true,
    });
    assert.equal(ok, true);
    assert.deepEqual(readSessionPointers(cwd, "01RID")?.implementation.main, IM);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("preserveForeign: a same-session re-capture refreshes the slot", () => {
  const cwd = tempCwd();
  try {
    recordSessionPointer(cwd, "01RID", "implementation", "main", IM);
    const refreshed = { ...IM, at: "2026-06-03T00:00:00Z" };
    const ok = recordSessionPointer(cwd, "01RID", "implementation", "main", refreshed, {
      preserveForeign: true,
    });
    assert.equal(ok, true);
    assert.equal(readSessionPointers(cwd, "01RID")?.implementation.main?.at, refreshed.at);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("default (no preserveForeign) keeps overwrite semantics", () => {
  const cwd = tempCwd();
  try {
    recordSessionPointer(cwd, "01RID", "implementation", "main", IM);
    assert.equal(recordSessionPointer(cwd, "01RID", "implementation", "main", PM), true);
    assert.deepEqual(readSessionPointers(cwd, "01RID")?.implementation.main, PM);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("captureSessionPointer threads preserveForeign through to the guard", () => {
  const cwd = tempCwd();
  try {
    recordSessionPointer(cwd, "01RID", "implementation", "main", IM);
    let result = true;
    const warnings = captureStderr(() => {
      result = captureSessionPointer({
        cwd,
        runId: "01RID",
        klass: "implementation",
        site: "main",
        sessionFile: "/sessions/other.jsonl",
        preserveForeign: true,
      });
    });
    assert.equal(result, false);
    assert.ok(warnings.some((w) => w.includes("skipping foreign overwrite")));
    assert.equal(readSessionPointers(cwd, "01RID")?.implementation.main?.pi_session_id, "im.jsonl");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- best-effort failure ----------------------------------------------------------------------

test("recordSessionPointer warns + returns false on an unwritable root, never throws", () => {
  const cwd = tempCwd();
  try {
    chmodSync(cwd, 0o500); // read+execute only — mkdir of the scratch tree fails
    let result = true;
    const warnings = captureStderr(() => {
      result = recordSessionPointer(cwd, "01RID", "planning", "main", PM);
    });
    assert.equal(result, false);
    assert.ok(warnings.some((w) => w.includes("could not record session pointer")));
  } finally {
    chmodSync(cwd, 0o700);
    rmSync(cwd, { recursive: true, force: true });
  }
});

// --- mainCheckoutRoot -------------------------------------------------------------------------

test("mainCheckoutRoot: non-repo cwd falls back to cwd", () => {
  const cwd = tempCwd();
  try {
    assert.equal(mainCheckoutRoot(cwd), cwd);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("mainCheckoutRoot: a linked worktree resolves to the MAIN checkout root", () => {
  const main = tempCwd();
  try {
    const g = (...args: string[]) => execFileSync("git", args, { cwd: main, stdio: "ignore" });
    g("init", "-q");
    g("config", "user.email", "t@example.com");
    g("config", "user.name", "perk tests");
    g("commit", "--allow-empty", "-qm", "seed");
    const wt = join(main, "..", `${main.split("/").pop()}-wt`);
    execFileSync("git", ["worktree", "add", "-q", "-b", "feat", wt], {
      cwd: main,
      stdio: "ignore",
    });
    try {
      // From inside the linked worktree, the main checkout root is resolved (realpath both sides
      // to neutralize macOS /private symlinking on tmp paths).
      const realMain = realpathSync(
        execFileSync("git", ["rev-parse", "--show-toplevel"], {
          cwd: main,
          encoding: "utf8",
        }).trim(),
      );
      // realpath both sides: `path.resolve` is lexical (no symlink resolution), but the resolved
      // dir is the SAME inode via the macOS /private/var ↔ /var tmp symlink (the carrier still
      // reads/writes the one physical location).
      assert.equal(realpathSync(mainCheckoutRoot(wt)), realMain);
      assert.equal(realpathSync(mainCheckoutRoot(main)), realMain);
    } finally {
      execFileSync("git", ["worktree", "remove", "--force", wt], { cwd: main, stdio: "ignore" });
    }
  } finally {
    rmSync(main, { recursive: true, force: true });
  }
});
