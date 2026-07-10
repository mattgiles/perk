// The terminal review door's R7 terminal auto-launch ladder — open hunk in a terminal the human can
// see, since hunk's TUI is constitutively a human surface (a `pi.exec` child gets pipes, no TTY).
//
// A pure `resolveTerminalLaunch` (platform + env + request → an argv + the rung tag, or `null` for
// "no launcher matched") and a thin fail-soft `launchInTerminal` runner. Never throws, never
// notifies — the caller owns messaging, and the loud print + clipboard copy are the universal
// fallback when no rung matches or a rung fails. The `hunk session get` handshake — not a spawn
// success — remains the ONLY verification the surface is actually up.
//
// The `PERK_TERMINAL_LAUNCH` env seam: unset → the platform default ladder; empty → disabled (the
// test seam); non-empty → a custom launcher receiving the worktree as `$1` and the command as
// `$2`.

import type { ExecHost } from "./coldDoor.ts";

/** Which rung of the ladder launched (or would launch) the surface. */
export type LaunchVia = "custom" | "tmux" | "ghostty" | "iterm2" | "terminal-app";

/** A human-readable name for each rung, for the door's launched-in-a-<surface> message. */
export const LAUNCH_SURFACE: Record<LaunchVia, string> = {
  custom: "terminal window",
  tmux: "tmux pane",
  ghostty: "Ghostty window",
  iterm2: "iTerm2 window",
  "terminal-app": "terminal window",
};

// The macOS AppleScript rungs are `on run argv` bodies: paths + commands ride argv (never
// interpolated into the script text), so no AppleScript string-quoting hazard exists.

/** Single-quote `s` for a POSIX shell line (the standard `'\''` embedded-quote escape). */
function shQuote(s: string): string {
  return `'${s.replaceAll("'", `'\\''`)}'`;
}

/**
 * Wrap `command` in the human's interactive **login shell** (`$SHELL -i -l -c '<command>'`) for
 * the rungs whose execution context is rc-less — Ghostty's surface `command` is argv-exec'd
 * (quote-aware word split, a relative arg0 joined onto the working directory, never a shell
 * line), and tmux commands run under the server environment. `-i -l` sources the human's rc
 * files, so the launched window resolves binaries exactly like the human's own terminal — which
 * is what the bare command needs: `hunk` AND the `node` its `#!/usr/bin/env node` shebang
 * re-resolves are often on PATH only via rc activation (mise/nvm; both misses were hit live).
 * `$SHELL` when absolute, else `/bin/zsh` on darwin (the macOS default) / `/bin/sh` elsewhere.
 * The shell-line rungs (iTerm2/Terminal.app) type into an interactive login shell already and
 * take the bare command; so does the custom launcher (it owns its own environment).
 */
function interactiveShellWrap(
  platform: string,
  env: Record<string, string | undefined>,
  command: string,
): string {
  const shell =
    env.SHELL !== undefined && env.SHELL.startsWith("/")
      ? env.SHELL
      : platform === "darwin"
        ? "/bin/zsh"
        : "/bin/sh";
  return `${shell} -i -l -c ${shQuote(command)}`;
}

/** Ghostty ≥ 1.3: a native surface configuration (cwd + command as argv items 1/2). */
const GHOSTTY_SCRIPT = `on run argv
	tell application "Ghostty"
		set cfg to (new surface configuration)
		set (initial working directory of cfg) to (item 1 of argv)
		set (command of cfg) to (item 2 of argv)
		set (wait after command of cfg) to true
		new window with configuration cfg
		activate
	end tell
end run`;

/** iTerm2: a new window whose current session runs the composed shell line (argv item 1). */
const ITERM_SCRIPT = `on run argv
	tell application "iTerm"
		set w to (create window with default profile)
		tell current session of w to write text (item 1 of argv)
		activate
	end tell
end run`;

/** Terminal.app: the universal macOS fallback — `do script` the composed shell line (argv item 1). */
const TERMINAL_SCRIPT = `on run argv
	tell application "Terminal"
		do script (item 1 of argv)
		activate
	end tell
end run`;

export interface LaunchRequest {
  /** The review worktree — the terminal's working directory. */
  cwd: string;
  /**
   * The bare surface command to run there, e.g. `hunk diff <sha12>`. The rc-less rungs wrap it
   * in the human's interactive login shell (see `interactiveShellWrap`).
   */
  command: string;
}

/**
 * Resolve the terminal-launch argv + rung tag for `platform` + `env` + `req`, first match wins:
 *
 * 1. `PERK_TERMINAL_LAUNCH === ""` → `null` (the test seam / opt-out);
 * 2. `PERK_TERMINAL_LAUNCH` non-empty → a custom `sh -c` launcher (worktree `$1`, command `$2`);
 * 3. `TMUX` set → a `tmux split-window` pane beside pi (no consent prompts);
 * 4. `darwin`, keyed off `TERM_PROGRAM` → the matching osascript rung (ghostty / iterm2 /
 *    terminal-app; anything unrecognized — vscode, WezTerm, absent — falls to terminal-app, the
 *    universal macOS fallback);
 * 5. otherwise → `null` (no Linux emulator sniffing — tmux + the custom seam cover it).
 *
 * Rungs that set the working directory natively (ghostty's `initial working directory`, tmux's
 * `-c`) receive the command wrapped in the human's interactive login shell (see
 * `interactiveShellWrap` — their execution contexts are rc-less); the shell-line rungs
 * (iterm2/terminal-app) receive `cd '<cwd>' && <command>` as one arg (the cwd single-quoted —
 * worktree paths can carry spaces; the command is perk-composed, never quoted) typed into an
 * interactive login shell the terminal itself opens.
 */
export function resolveTerminalLaunch(
  platform: string,
  env: Record<string, string | undefined>,
  req: LaunchRequest,
): { argv: string[]; via: LaunchVia } | null {
  const custom = env.PERK_TERMINAL_LAUNCH;
  if (custom !== undefined) {
    if (custom === "") return null;
    return { argv: ["sh", "-c", custom, "sh", req.cwd, req.command], via: "custom" };
  }

  if (env.TMUX !== undefined && env.TMUX !== "") {
    const wrapped = interactiveShellWrap(platform, env, req.command);
    return { argv: ["tmux", "split-window", "-h", "-c", req.cwd, wrapped], via: "tmux" };
  }

  if (platform === "darwin") {
    // The shell-line rungs run this through the terminal's shell — quote the cwd (paths can
    // carry spaces/quotes); the command is perk-composed (`hunk diff <sha12>`), never quoted.
    const shellLine = `cd ${shQuote(req.cwd)} && ${req.command}`;
    const term = env.TERM_PROGRAM;
    if (term === "ghostty") {
      const wrapped = interactiveShellWrap(platform, env, req.command);
      return { argv: ["osascript", "-e", GHOSTTY_SCRIPT, req.cwd, wrapped], via: "ghostty" };
    }
    if (term === "iTerm.app") {
      return { argv: ["osascript", "-e", ITERM_SCRIPT, shellLine], via: "iterm2" };
    }
    // Apple_Terminal, vscode, WezTerm, or absent → Terminal.app (the universal macOS fallback).
    return { argv: ["osascript", "-e", TERMINAL_SCRIPT, shellLine], via: "terminal-app" };
  }

  return null;
}

/**
 * Launch the surface command in a terminal the human can see, best-effort. Resolves the rung from
 * `process.platform` + `process.env`; a `null` resolution (disabled seam, unmatched platform)
 * short-circuits to `{launched: false}`. Otherwise shells the argv with a 15s cap (guards an
 * unanswered macOS Automation/TCC consent dialog blocking `osascript`). Fail-soft on
 * throw/nonzero/killed — a denied or unanswered consent is just another failed rung, and the
 * print+clipboard fallback already covers the human. Never rejects, never notifies.
 */
export async function launchInTerminal(
  pi: ExecHost,
  ctx: { cwd: string; signal?: AbortSignal },
  req: LaunchRequest,
): Promise<{ launched: boolean; via?: LaunchVia }> {
  const resolved = resolveTerminalLaunch(process.platform, process.env, req);
  if (resolved === null) return { launched: false };
  const [cmd, ...rest] = resolved.argv;
  if (cmd === undefined) return { launched: false };
  try {
    const res = await pi.exec(cmd, rest, { cwd: ctx.cwd, signal: ctx.signal, timeout: 15_000 });
    if (res.killed || res.code !== 0) return { launched: false };
    return { launched: true, via: resolved.via };
  } catch {
    return { launched: false };
  }
}
