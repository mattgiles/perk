// Bounded, side-effect-free command probes for the containment availability rows (dev-only): run
// one argv with piped stdio and a hard timeout, and report its exit status and stderr verbatim —
// an availability row's detail is the command's own explanation, never a paraphrase.

import { spawnSync } from "node:child_process";
import { accessSync, constants, statSync } from "node:fs";
import { delimiter, join } from "node:path";

export type ProbeOutcome = {
  /** The command exited 0. */
  readonly ok: boolean;
  /** `exit=<status> signal=<signal> stderr=<trimmed stderr>` (plus `error=` on a spawn failure). */
  readonly detail: string;
};

/** Run `argv` (no shell) with a `timeoutMs` bound; stdin is closed, stdout/stderr captured. */
export function probeCommand(argv: readonly string[], timeoutMs: number): ProbeOutcome {
  const [program, ...args] = argv;
  if (program === undefined) throw new Error("probeCommand needs a program");
  const result = spawnSync(program, args, {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    timeout: timeoutMs,
    killSignal: "SIGKILL",
  });
  const parts = [
    `argv=${JSON.stringify(argv)}`,
    `exit=${result.status ?? "none"}`,
    `signal=${result.signal ?? "none"}`,
    `stderr=${JSON.stringify((result.stderr ?? "").trim())}`,
  ];
  if (result.error !== undefined) parts.push(`error=${JSON.stringify(result.error.message)}`);
  return { ok: result.status === 0 && result.error === undefined, detail: parts.join(" ") };
}

/** Whether `name` is an executable file on `PATH` (no `which` subprocess). */
export function commandExists(name: string): boolean {
  for (const dir of (process.env.PATH ?? "").split(delimiter)) {
    if (dir === "") continue;
    const candidate = join(dir, name);
    try {
      if (!statSync(candidate).isFile()) continue;
      accessSync(candidate, constants.X_OK);
      return true;
    } catch {
      // Not here; keep looking.
    }
  }
  return false;
}
