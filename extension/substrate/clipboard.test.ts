import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { ExecOptions, ExecResult } from "@earendil-works/pi-coding-agent";
import { copyToClipboard, resolveClipboardScript } from "./clipboard.ts";
import type { ExecHost } from "./coldDoor.ts";

// A real `sh`-running ExecHost so the end-to-end arms actually shell the resolved script.
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

function withEnv<T>(key: string, value: string | undefined, fn: () => T): T {
  const saved = process.env[key];
  if (value === undefined) delete process.env[key];
  else process.env[key] = value;
  try {
    return fn();
  } finally {
    if (saved === undefined) delete process.env[key];
    else process.env[key] = saved;
  }
}

// --- resolveClipboardScript -------------------------------------------------------------------

test("resolveClipboardScript: the empty env is the disabled seam (null on every platform)", () => {
  for (const platform of ["darwin", "linux", "win32", "freebsd"]) {
    assert.equal(resolveClipboardScript(platform, ""), null);
  }
});

test('resolveClipboardScript: a non-empty env is the custom override (< "$1")', () => {
  assert.equal(resolveClipboardScript("darwin", "pbcopy"), 'pbcopy < "$1"');
  assert.equal(resolveClipboardScript("linux", "my-copier --stdin"), 'my-copier --stdin < "$1"');
});

test("resolveClipboardScript: platform defaults (unset env)", () => {
  assert.equal(resolveClipboardScript("darwin", undefined), 'pbcopy < "$1"');
  assert.equal(resolveClipboardScript("win32", undefined), null);
  const linux = resolveClipboardScript("linux", undefined);
  assert.ok(linux !== null);
  assert.match(linux ?? "", /wl-copy/);
  assert.match(linux ?? "", /xclip -selection clipboard/);
  assert.match(linux ?? "", /xsel --clipboard --input/);
  assert.match(linux ?? "", /exit 127/);
  // an unknown POSIX platform falls to the same chain
  assert.equal(resolveClipboardScript("freebsd", undefined), linux);
});

// --- copyToClipboard --------------------------------------------------------------------------

test("copyToClipboard: a custom copier receives the file whose content equals the text", async () => {
  const dir = mkdtempSync(join(tmpdir(), "clip-e2e-"));
  const capture = join(dir, "captured.txt");
  try {
    const ok = await withEnv("PERK_CLIPBOARD_CMD", `cat > "${capture}"`, () =>
      copyToClipboard(realExec(), { cwd: dir }, "cd /wt && hunk diff abc123"),
    );
    assert.equal(ok, true);
    assert.equal(readFileSync(capture, "utf8"), "cd /wt && hunk diff abc123");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("copyToClipboard: the disabled seam short-circuits (false, no exec)", async () => {
  const calls: number[] = [];
  const pi: ExecHost = {
    exec: () => {
      calls.push(1);
      return Promise.resolve({ stdout: "", stderr: "", code: 0, killed: false });
    },
  };
  const ok = await withEnv("PERK_CLIPBOARD_CMD", "", () =>
    copyToClipboard(pi, { cwd: tmpdir() }, "x"),
  );
  assert.equal(ok, false);
  assert.equal(calls.length, 0, "the disabled seam never shells");
});

test("copyToClipboard: a failing copier returns false (never throws)", async () => {
  const ok = await withEnv("PERK_CLIPBOARD_CMD", "false", () =>
    copyToClipboard(realExec(), { cwd: tmpdir() }, "x"),
  );
  assert.equal(ok, false);
});
