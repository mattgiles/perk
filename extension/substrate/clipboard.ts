// A fail-soft "copy this text to the OS clipboard" seam for the extension interior. Used by the
// terminal review door's R7 hunk handoff so the human always has the launch command one paste
// away — belt-and-braces beside the loud print and the terminal auto-launch.
//
// Two functions: a pure `resolveClipboardScript` (platform + env → a POSIX `sh` script, or `null`
// for "don't copy") and a thin `copyToClipboard` runner that stages the text in a temp file and
// shells the script. Never throws, never notifies — the caller owns all messaging. The
// `PERK_CLIPBOARD_CMD` env seam: unset → the platform default; empty → disabled (the test seam);
// non-empty → a custom copier.

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExecHost } from "./coldDoor.ts";

/**
 * Resolve the clipboard-copy shell script for `platform` + the `PERK_CLIPBOARD_CMD` override. The
 * script copies the file named by `$1`; returns `null` for "don't copy".
 *
 * - `envCmd === ""` → `null` (the test seam / explicit opt-out);
 * - `envCmd` non-empty → `<envCmd> < "$1"` (custom override — receives the file path as `$1`);
 * - `darwin` → `pbcopy < "$1"`;
 * - `linux`/other POSIX → a `command -v` chain (`wl-copy` → `xclip` → `xsel`), else `exit 127`;
 * - `win32` → `null` (no POSIX `sh`; the print+launch fallback covers it).
 */
export function resolveClipboardScript(
  platform: string,
  envCmd: string | undefined,
): string | null {
  if (envCmd !== undefined) {
    if (envCmd === "") return null;
    return `${envCmd} < "$1"`;
  }
  if (platform === "darwin") return `pbcopy < "$1"`;
  if (platform === "win32") return null;
  return (
    'if command -v wl-copy >/dev/null 2>&1; then wl-copy < "$1"; ' +
    'elif command -v xclip >/dev/null 2>&1; then xclip -selection clipboard < "$1"; ' +
    'elif command -v xsel >/dev/null 2>&1; then xsel --clipboard --input < "$1"; ' +
    "else exit 127; fi"
  );
}

/**
 * Copy `text` to the OS clipboard, best-effort. Resolves the script from `process.platform` +
 * `process.env.PERK_CLIPBOARD_CMD`; a `null` script (win32, or the disabled seam) short-circuits
 * to `false` without shelling. Otherwise stages `text` in a temp file and runs
 * `sh -c <script> sh <file>` with a 3s cap (guards a display-less `xclip` hanging). Returns
 * `true` iff the copier exited 0 and was not killed. Any throw → `false`. Never rejects, never
 * notifies.
 */
export async function copyToClipboard(
  pi: ExecHost,
  ctx: { cwd: string; signal?: AbortSignal },
  text: string,
): Promise<boolean> {
  const script = resolveClipboardScript(process.platform, process.env.PERK_CLIPBOARD_CMD);
  if (script === null) return false;
  let dir: string | undefined;
  try {
    dir = mkdtempSync(join(tmpdir(), "perk-clip-"));
    const file = join(dir, "clip.txt");
    writeFileSync(file, text, "utf8");
    const res = await pi.exec("sh", ["-c", script, "sh", file], {
      cwd: ctx.cwd,
      signal: ctx.signal,
      timeout: 3000,
    });
    return res.code === 0 && !res.killed;
  } catch {
    return false;
  } finally {
    if (dir !== undefined) {
      try {
        rmSync(dir, { recursive: true, force: true });
      } catch {
        // best-effort cleanup — a leaked temp file is harmless
      }
    }
  }
}
