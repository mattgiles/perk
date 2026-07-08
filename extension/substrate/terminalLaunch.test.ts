import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { ExecOptions, ExecResult } from "@earendil-works/pi-coding-agent";
import type { ExecHost } from "./coldDoor.ts";
import { launchInTerminal, resolveTerminalLaunch } from "./terminalLaunch.ts";

function realExec(): ExecHost {
  return {
    exec(command: string, args: string[], options?: ExecOptions): Promise<ExecResult> {
      return new Promise((resolve) => {
        execFile(
          command,
          args,
          { cwd: options?.cwd, timeout: options?.timeout, encoding: "utf8" },
          (err, stdout, stderr) => {
            const code =
              err && typeof (err as { code?: unknown }).code === "number"
                ? ((err as { code: number }).code ?? 1)
                : err
                  ? 1
                  : 0;
            const killed = Boolean(err && (err as { killed?: boolean }).killed);
            resolve({ stdout: stdout ?? "", stderr: stderr ?? "", code, killed });
          },
        );
      });
    },
  };
}

function withEnv<T>(overrides: Record<string, string | undefined>, fn: () => T): T {
  const saved = new Map<string, string | undefined>();
  for (const [k, v] of Object.entries(overrides)) {
    saved.set(k, process.env[k]);
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  try {
    return fn();
  } finally {
    for (const [k, v] of saved) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

const REQ = { cwd: "/wt/review-148", command: "hunk diff 0f8a1b2c3d4e" };

// --- resolveTerminalLaunch matrix -------------------------------------------------------------

test("resolveTerminalLaunch: the empty launch env is the disabled seam (null)", () => {
  assert.equal(resolveTerminalLaunch("darwin", { PERK_TERMINAL_LAUNCH: "" }, REQ), null);
  assert.equal(
    resolveTerminalLaunch("linux", { PERK_TERMINAL_LAUNCH: "", TMUX: "/tmp/x" }, REQ),
    null,
  );
});

test("resolveTerminalLaunch: a custom launcher gets cwd as $1 and command as $2", () => {
  const r = resolveTerminalLaunch("linux", { PERK_TERMINAL_LAUNCH: "my-term" }, REQ);
  assert.deepEqual(r, {
    argv: ["sh", "-c", "my-term", "sh", "/wt/review-148", "hunk diff 0f8a1b2c3d4e"],
    via: "custom",
  });
});

test("resolveTerminalLaunch: TMUX takes a split-window pane (before the darwin ladder)", () => {
  const r = resolveTerminalLaunch("darwin", { TMUX: "/tmp/tmux-1000/default,123,0" }, REQ);
  assert.deepEqual(r, {
    argv: ["tmux", "split-window", "-h", "-c", "/wt/review-148", "hunk diff 0f8a1b2c3d4e"],
    via: "tmux",
  });
});

test("resolveTerminalLaunch: darwin + ghostty builds the native surface script (cwd/command as argv)", () => {
  const r = resolveTerminalLaunch("darwin", { TERM_PROGRAM: "ghostty" }, REQ);
  assert.ok(r !== null);
  assert.equal(r?.via, "ghostty");
  assert.equal(r?.argv[0], "osascript");
  assert.equal(r?.argv[1], "-e");
  // cwd + command ride argv (no AppleScript interpolation)
  assert.equal(r?.argv[r.argv.length - 2], "/wt/review-148");
  assert.equal(r?.argv[r.argv.length - 1], "hunk diff 0f8a1b2c3d4e");
  const script = r?.argv[2] ?? "";
  assert.match(script, /initial working directory/);
  assert.match(script, /set \(command of cfg\)/);
  assert.match(script, /wait after command/);
});

test("resolveTerminalLaunch: darwin + iTerm.app writes the composed shell line", () => {
  const r = resolveTerminalLaunch("darwin", { TERM_PROGRAM: "iTerm.app" }, REQ);
  assert.ok(r !== null);
  assert.equal(r?.via, "iterm2");
  assert.equal(r?.argv[0], "osascript");
  const shellLine = r?.argv[r.argv.length - 1] ?? "";
  assert.equal(shellLine, "cd /wt/review-148 && hunk diff 0f8a1b2c3d4e");
  assert.match(r?.argv[2] ?? "", /write text/);
});

test("resolveTerminalLaunch: darwin + Apple_Terminal (and unknown) fall to Terminal.app", () => {
  for (const term of ["Apple_Terminal", "vscode", undefined]) {
    const r = resolveTerminalLaunch("darwin", { TERM_PROGRAM: term }, REQ);
    assert.equal(r?.via, "terminal-app", `TERM_PROGRAM=${term} → terminal-app`);
    assert.equal(r?.argv[r.argv.length - 1], "cd /wt/review-148 && hunk diff 0f8a1b2c3d4e");
    assert.match(r?.argv[2] ?? "", /do script/);
  }
});

test("resolveTerminalLaunch: linux with no tmux and no custom env → null", () => {
  assert.equal(resolveTerminalLaunch("linux", {}, REQ), null);
  assert.equal(resolveTerminalLaunch("linux", { TERM_PROGRAM: "ghostty" }, REQ), null);
});

// --- launchInTerminal end-to-end --------------------------------------------------------------

test("launchInTerminal: a custom launcher runs and receives $1=cwd $2=command", async () => {
  const dir = mkdtempSync(join(tmpdir(), "term-e2e-"));
  const capture = join(dir, "argv.txt");
  try {
    const r = await withEnv(
      { PERK_TERMINAL_LAUNCH: `printf '%s\\n%s' "$1" "$2" > "${capture}"` },
      () => launchInTerminal(realExec(), { cwd: dir }, { cwd: "/wt/x", command: "hunk diff abc" }),
    );
    assert.deepEqual(r, { launched: true, via: "custom" });
    assert.equal(readFileSync(capture, "utf8"), "/wt/x\nhunk diff abc");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("launchInTerminal: a nonzero rung is fail-soft (launched:false, no throw)", async () => {
  const r = await withEnv({ PERK_TERMINAL_LAUNCH: "false" }, () =>
    launchInTerminal(realExec(), { cwd: tmpdir() }, { cwd: "/wt/x", command: "hunk diff abc" }),
  );
  assert.deepEqual(r, { launched: false });
});

test("launchInTerminal: the disabled seam short-circuits without shelling", async () => {
  const calls: number[] = [];
  const pi: ExecHost = {
    exec: () => {
      calls.push(1);
      return Promise.resolve({ stdout: "", stderr: "", code: 0, killed: false });
    },
  };
  const r = await withEnv({ PERK_TERMINAL_LAUNCH: "" }, () =>
    launchInTerminal(pi, { cwd: tmpdir() }, { cwd: "/wt/x", command: "hunk diff abc" }),
  );
  assert.deepEqual(r, { launched: false });
  assert.equal(calls.length, 0);
});
