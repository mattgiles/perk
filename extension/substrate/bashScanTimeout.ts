// The bash scan-timeout guard's pure policy: the default `timeout` for gitignore-blind scans issued
// through Pi's `bash` tool, the command classifier, and the expiry steer. Recursive `grep -r…` and
// `find` without `-maxdepth` ignore `.gitignore`, so from a checkout carrying `node_modules/`,
// `.venv/`, `.worktrees/` and the like they walk everything — observed running for minutes to the
// better part of an hour with no `timeout` on the call, so nothing stopped them. Every
// legitimately scoped scan finished in single-digit seconds. The hooks that apply this policy
// (the `tool_call` injection + the `tool_result` note) live in the Pi adapter home,
// `pi/v1/bashScanTimeout.ts`; the contract is contracts.md §8.69.
//
// The override contract: an explicit `timeout` of ANY value on the call is the model's override —
// never rewritten or capped. Expiry is detected only from Pi's own terminal `Command timed out
// after N seconds` status line, never from a line the command printed.
//
// Classifier design: regex-only over each physical line's quote-aware top-level segments (the
// gate's splitter, reused so both hooks agree on what a segment is and a flag in a LATER pipeline
// stage — `grep -n foo f | sort -r` — is never attributed to the grep). The command word is
// matched at ANY command boundary inside a segment rather than as the segment's leading word, so
// wrapper prefixes (`env`/`nice`/`time`/`nohup`/`xargs`), nested shells (`sh -c '…'`) and `$(…)`
// substitutions are covered without enumerating wrappers. Over-matching is tolerated by design —
// a spurious 30s cap on a fast command is harmless, a missed scan is the bug. The accepted
// over-matches (pinned as such in the tests, so any future tightening is deliberate):
// `echo grep -r`, `git grep -rn foo`, `rg -n 'grep -rn foo' src/`, `grep -n "x -r y" f`.
// Incidental precision, not a goal: a quote-adjacent cluster (`"-r"`, `'grep -r'`) is not a flag
// position, so quoted flags do not match.

import { splitTopLevelSegments } from "./toolGating.ts";

/**
 * The injected default, in seconds — the ONE source of truth for the number. The managed
 * `AGENTS.md` bullet the Python plane renders (`_agents_inner()`) mirrors it verbatim and a Python
 * parity test pins the mirror; change both in the same turn.
 */
export const SCAN_TIMEOUT_SECONDS = 30;

export type ScanKind = "recursive-grep" | "unbounded-find";

/**
 * A grep-family or `find` command word at a command boundary: segment start, whitespace, a quote,
 * a backtick, `(` (as in `$(`) or a `\` alias-bypass, with an optional `dir/` path prefix, followed
 * by whitespace or end. `ast-grep` never matches (`-` precedes `grep`); `docs/find.md` and
 * `findings/` never match (`.`/`i` follow `find`).
 */
const COMMAND_WORD =
  /(?:^|[\s'"`(\\])(?:[\w./-]*\/)?(grep|egrep|fgrep|zgrep|zegrep|zfgrep|bzgrep|xzgrep|rgrep|find)(?=\s|$)/g;

/**
 * A recursion flag in a grep's tail: a whitespace-delimited short cluster containing `r`/`R`
 * (`-r`, `-rn`, `-rniE`, `-Rl`, `-nr`, `-rnA3`) or one of the explicit long forms. Other long
 * options (`--color=never`, `--exclude-dir=…`) never match — the cluster arm cannot consume the
 * second `-`.
 */
const RECURSIVE_FLAG =
  /(?:^|\s)(?:--recursive|--dereference-recursive|--directories=recurse|(?:-d|--directories)\s+recurse|-[A-Za-z0-9]*[rR][A-Za-z0-9]*)(?=\s|$)/;

/** A depth bound in a find's tail — the only thing that exempts a `find` (`-prune`/`-not -path` still walk). */
const MAXDEPTH_FLAG = /(?:^|\s)-maxdepth(?=\s|$)/;

/**
 * Pi's terminal status line for an expired bash call. No `m` flag — `$` is end-of-string, so the
 * line must be the LAST thing in the text (Pi's `appendStatus` always places the status last), never
 * a line the command itself printed mid-output.
 */
const TIMEOUT_STATUS = /(?:^|\n)Command timed out after (\S+) seconds$/;

/**
 * Classify a bash command as a gitignore-blind scan, or `null`. Pure and offline-testable. Per
 * physical line, per quote-aware top-level segment, in order: the first segment that classifies
 * decides. Fast non-scans (`rg`, `fd`, `ast-grep`, `grep -n foo file`) are `null`.
 */
export function classifyScanCommand(command: string): ScanKind | null {
  for (const line of command.split("\n")) {
    for (const segment of splitTopLevelSegments(line)) {
      const kind = classifySegment(segment);
      if (kind !== null) return kind;
    }
  }
  return null;
}

function classifySegment(segment: string): ScanKind | null {
  // A fresh matcher per segment: the shared regex is global (stateful `lastIndex`).
  const words = new RegExp(COMMAND_WORD.source, "g");
  let match = words.exec(segment);
  while (match !== null) {
    const word = match[1];
    const tail = segment.slice(match.index + match[0].length);
    if (word === "rgrep") return "recursive-grep";
    if (word === "find") {
      if (!MAXDEPTH_FLAG.test(tail)) return "unbounded-find";
    } else if (RECURSIVE_FLAG.test(tail)) {
      return "recursive-grep";
    }
    match = words.exec(segment);
  }
  return null;
}

/**
 * The seconds from Pi's terminal timeout status when `text` (a bash error result's last text
 * block) ENDS with it; `null` otherwise — including when the literal appears mid-output.
 */
export function expiredAfterSeconds(text: string): string | null {
  return TIMEOUT_STATUS.exec(text)?.[1] ?? null;
}

/** The steer appended to an expired scan's result (`seconds` as parsed from Pi's status line). */
export function scanTimeoutNote(kind: ScanKind, seconds: string): string {
  const what = kind === "recursive-grep" ? "recursive grep" : "unbounded find";
  return (
    `perk: this ${what} hit the ${seconds}s timeout. Recursive \`grep -r…\` and \`find\` without ` +
    "`-maxdepth` ignore `.gitignore` (they walk `node_modules`, `.venv`, `.worktrees`, …). Prefer " +
    "the `grep`/`find` tools or `rg`/`fd`, which honor `.gitignore`; to run this command anyway, " +
    "pass a larger explicit `timeout` (seconds) on the bash call."
  );
}
