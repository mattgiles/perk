// The CI-execution feature (the Run→Report half of Run→Report→Fix→Verify), Pi-free.
//
// A deterministic check runner over the project's configured `[[ci.checks]]` rows: it selects,
// orders, glob-gates, runs, and REPORTS — it never edits, fixes, or loops. Checks execute
// CONCURRENTLY (each row must be independently runnable; declared order governs the report
// order, not execution order — sequencing that matters belongs inside one row's command, e.g.
// `cmd1 && cmd2`). The caller owns the entire fix loop; this feature is a stateless oracle
// invoked once per run (the `devrun` discipline: "run and report", never "run and fix").
//
// "Read-only" here is a property of THIS MODULE and its OUTPUT, not a sandbox: the check
// commands run with full shell access through the injected `RunConfiguredCheck` port. The
// untrusted-config scope gate (`decideCiScope`) and the output-isolation wrapping live with the
// adapter that composes the ports; the feature's own defenses are output routing (full output
// persisted through the `PersistCheckOutput` port, capped model-visible slice) and never-throw
// per-check folding.

import type { CiCheck } from "../substrate/config.ts";
import { capForModel, DEFAULT_MODEL_VISIBLE_CAP } from "../substrate/modelVisible.ts";

/** One configured check's outcome. `executed` carries no `passed` field — passed ≡
 * `exitCode === 0` (derived where needed, so a contradiction is unrepresentable); `skipped`
 * only ever arises from a declared glob, so `glob` is required. */
export type CiCheckOutcome =
  | {
      kind: "executed";
      name: string;
      command: string;
      exitCode: number;
      /** The capped, model-visible output (route-don't-relay — the full output was persisted
       * through the port). */
      shown: string;
      /** The port-minted opaque location of the persisted full output (`null` = persistence
       * failed; the failure rides `error`). */
      outputPath: string | null;
      bytesTotal: number;
      bytesShown: number;
      truncated: boolean;
      error?: string;
    }
  | { kind: "skipped"; name: string; command: string; glob: string };

/** The typed run outcome. `invalid_selection` carries the selection diagnostic (back-pressure
 * is feature meaning); `completed.passed` counts skipped checks as passed. Refusals and
 * tool-boundary decode failures are adapter shapes — they never enter this union. */
export type CiRunOutcome =
  | { kind: "not_configured" }
  | { kind: "invalid_selection"; message: string }
  | {
      kind: "completed";
      scope: "all" | "subset";
      passed: boolean;
      checks: readonly CiCheckOutcome[];
    };

/** The per-check display state of the typed live-progress stream. */
export type CiProgressState = "running" | "passed" | "failed" | "skipped";

export interface CiProgressEntry {
  readonly name: string;
  readonly state: CiProgressState;
}

/**
 * The delivery-specific typed progress event union. No per-event check identity — configured
 * names are not unique; the ORDERED entries snapshot is the correlation surface. `run_started`
 * fires synchronously before any check launches (skips already resolved); one `check_settled`
 * per executed-check completion. Every emission deep-copies the entry objects.
 */
export type CiProgressEvent =
  | { readonly kind: "run_started"; readonly entries: readonly CiProgressEntry[] }
  | { readonly kind: "check_settled"; readonly entries: readonly CiProgressEntry[] };

/** A single deterministic command execution outcome (output = trimmed stdout + "\n" + stderr). */
export interface CiExecOutcome {
  code: number;
  output: string;
}

/** The semantic port "run this configured check" (one production adapter: the Pi shell runner). */
export type RunConfiguredCheck = (
  check: CiCheck,
  opts: { signal?: AbortSignal },
) => Promise<CiExecOutcome>;

/** "Persist this check's full output and return its opaque location" — throws on failure. */
export type PersistCheckOutput = (checkName: string, output: string) => string;

/** The semantic port "changed files vs trunk"; `null` = unknown (the fail-open sentinel — the
 * run then skips nothing). One production adapter: the git composition in the Pi adapter. */
export type ObserveChangedFiles = (opts: {
  signal?: AbortSignal;
}) => Promise<ReadonlySet<string> | null>;

export type CiScope = "run" | "confirm" | "refuse";

/**
 * Decide how to treat project-supplied CI. Pure (the load-bearing safety boundary):
 *   - `[ci] trusted` (committed config), `--allow-project-ci`, or a per-session latch ⇒ "run"
 *     (trust runs on EVERY surface, overriding the headless refuse below)
 *   - else with UI ⇒ "confirm" (ask the human)
 *   - else (headless, no trust/flag) ⇒ "refuse" (fail closed)
 */
export function decideCiScope(args: {
  hasUI: boolean;
  allowFlag: boolean;
  approved: boolean;
  trusted: boolean;
}): CiScope {
  if (args.trusted || args.allowFlag || args.approved) return "run";
  return args.hasUI ? "confirm" : "refuse";
}

/**
 * Run one configured check deterministically: run the port, persist the FULL combined output
 * through the `PersistCheckOutput` port, cap the model-visible output. Never throws — a
 * run-port throw becomes `exitCode: -1` with the error captured; a persistence throw folds to
 * the same failure shape (`error` = the thrown message, `outputPath: null`) with the exit code
 * intact.
 */
async function runOneCheck(
  check: CiCheck,
  runCheck: RunConfiguredCheck,
  persistOutput: PersistCheckOutput,
  signal?: AbortSignal,
): Promise<CiCheckOutcome> {
  let outcome: CiExecOutcome;
  try {
    outcome = await runCheck(check, { signal });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      kind: "executed",
      name: check.name,
      command: check.command,
      exitCode: -1,
      shown: message,
      outputPath: null,
      bytesTotal: 0,
      bytesShown: 0,
      truncated: false,
      error: message,
    };
  }

  // Persist the full output through the port: a returned string IS the location; ANY throw
  // folds to the failure shape (the port owns write+verify semantics — no post-write probe).
  let outputPath: string | null = null;
  let writeError: string | undefined;
  try {
    outputPath = persistOutput(check.name, outcome.output);
  } catch (err) {
    writeError = err instanceof Error ? err.message : String(err);
  }

  // Tail-keep: pytest/tsc failure summaries live at the END of the output, so the model-visible
  // slice keeps the last `cap` bytes; the persisted location still holds the full output.
  const capped = capForModel(outcome.output, DEFAULT_MODEL_VISIBLE_CAP, outputPath, "tail");
  return {
    kind: "executed",
    name: check.name,
    command: check.command,
    exitCode: outcome.code,
    shown: capped.shown,
    outputPath,
    bytesTotal: capped.bytesTotal,
    bytesShown: capped.bytesShown,
    truncated: capped.truncated,
    ...(writeError ? { error: writeError } : {}),
  };
}

/**
 * Dependency-free glob match. `glob` is a single comma-separated pattern string; the path matches
 * iff it matches ANY pattern. Each pattern is translated to an anchored RegExp: regex metachars
 * escaped, then `**` → `.*` (crosses directories) and `*` → `[^/]*` (one segment). A slash-free
 * pattern is matched against the path's BASENAME (so `*.py` gates any `.py` at any depth, the
 * gitignore/fnmatch rule); a pattern containing `/` is matched against the full repo-relative
 * POSIX path.
 */
function matchesGlob(path: string, glob: string): boolean {
  for (const raw of glob.split(",")) {
    const pattern = raw.trim();
    if (!pattern) continue;
    // Escape regex metachars, including `*` (restored below to glob semantics).
    const escaped = pattern.replace(/[.+^${}()|[\]\\*]/g, "\\$&");
    // Restore glob stars in one pass (so the single-`*` rule never clobbers a `**`): the escaped
    // forms are `\*\*` (→ `.*`, crosses dirs) and `\*` (→ `[^/]*`, one segment).
    const body = escaped.replace(/\\\*\\\*|\\\*/g, (m) => (m === "\\*\\*" ? ".*" : "[^/]*"));
    const subject = pattern.includes("/") ? path : (path.split("/").pop() ?? path);
    if (new RegExp(`^${body}$`).test(subject)) return true;
  }
  return false;
}

/** A skipped-check outcome: not executed because its glob matched no changed file (vs trunk). */
function skippedResult(check: CiCheck, glob: string): CiCheckOutcome {
  return { kind: "skipped", name: check.name, command: check.command, glob };
}

export interface RunCiChecksOpts {
  checks: CiCheck[];
  only?: string;
  signal?: AbortSignal;
}

export interface RunCiChecksDeps {
  runCheck: RunConfiguredCheck;
  /** Persist one check's full output; the returned string is the opaque location this feature
   * treats as data (a throw folds to the check's failure shape). */
  persistOutput: PersistCheckOutput;
  observeChangedFiles: ObserveChangedFiles;
  /** Optional typed live-progress sink. Failure-owned here: a throwing OR async-rejecting sink
   * can neither affect the run nor leak an unhandled rejection. */
  onProgress?: (event: CiProgressEvent) => void;
}

/**
 * Run the selected checks (or all when `only` is omitted) CONCURRENTLY and report every result
 * in the config's DECLARED order — declared order governs the report, not execution, so each
 * `[[ci.checks]]` row must be independently runnable (sequencing that matters belongs inside one
 * row's command, e.g. `cmd1 && cmd2`). `only` accepts one name or a comma-separated list — an
 * EXACT name match wins before any comma-splitting (so a configured name that itself contains a
 * comma or surrounding whitespace stays selectable), and each requested name selects the FIRST
 * declared row with that name (duplicates never broaden a selection); the selected rows still
 * run concurrently and report in declared order. Empty checks ⇒ inert `not_configured`; an
 * unknown (or missing) `only` name ⇒ an actionable `invalid_selection` listing the available
 * names (back-pressure, not a silent failure). Does NOT stop at the first failure.
 * `passed = every executed check exited 0` (skips count as passed).
 *
 * **Change-scoped gating (run-all path only).** When any selected check declares a `glob`, the
 * changed-file set (vs trunk) is observed ONCE — before any check launches — and each globbed
 * check is skipped when no changed file matches (never a failure). A check with no `glob`
 * always runs; an explicit `only` always runs (no glob gate, no observation); a fail-open
 * `null` observation runs everything (never skip on uncertainty). No observation happens when
 * no selected row is globbed.
 */
export async function runCiChecks(
  opts: RunCiChecksOpts,
  deps: RunCiChecksDeps,
): Promise<CiRunOutcome> {
  const checks = opts.checks;
  if (checks.length === 0) {
    return { kind: "not_configured" };
  }
  const names = checks.map((c) => c.name);

  // Explicit selection: `only` is one configured name or a comma-separated list. An exact name
  // match is tried FIRST (compatibility: any accepted name — even one containing a comma or
  // surrounding whitespace — stays selectable); only a non-matching string is comma-split.
  // Selected rows run in DECLARED order (not argument order); no glob gate, no observation.
  let selected = checks;
  let explicit = false;
  if (opts.only !== undefined) {
    const exact = checks.find((c) => c.name === opts.only);
    const requested = exact
      ? [exact.name]
      : opts.only
          .split(",")
          .map((s) => s.trim())
          .filter((s) => s.length > 0);
    if (requested.length === 0) {
      return {
        kind: "invalid_selection",
        message: `no check names given; available: ${names.join(", ")}`,
      };
    }
    const unknown = requested.filter((n) => !names.includes(n));
    if (unknown.length > 0) {
      return {
        kind: "invalid_selection",
        message: `unknown check${unknown.length > 1 ? "s" : ""} '${unknown.join("', '")}'; available: ${names.join(", ")}`,
      };
    }
    // Each requested name selects the FIRST declared row with that name (the pre-concurrency
    // `find` semantics): duplicate names never broaden an explicit selection into extra rows
    // racing on the same name-keyed persisted-output target.
    const wanted = new Set(requested);
    const seen = new Set<string>();
    selected = checks.filter((c) => {
      if (!wanted.has(c.name) || seen.has(c.name)) return false;
      seen.add(c.name);
      return true;
    });
    explicit = true;
  }

  // The changed-set observation (compute-once, before run_started and before any launch);
  // a throwing observer folds to the same fail-open `null` its contract already means.
  const gate = !explicit && selected.some((c) => c.glob);
  let changed: ReadonlySet<string> | null = null;
  if (gate) {
    try {
      changed = await deps.observeChangedFiles({ signal: opts.signal });
    } catch {
      changed = null;
    }
  }

  // Skip a globbed check only when we KNOW the changed set (changed !== null) and nothing matches.
  const skipsByGlob = (check: CiCheck): boolean => {
    if (explicit || !check.glob || changed === null) return false;
    const glob = check.glob;
    return ![...changed].some((f) => matchesGlob(f, glob));
  };

  // Typed live progress: one ordered state entry per selected check (skips resolve
  // synchronously), a `run_started` emission before any launch, one `check_settled` per
  // executed-check completion. Every emission deep-copies the entries — a retained earlier
  // event never mutates, and a sink mutating its received entries cannot affect later events
  // or the outcome. Progress is cosmetic: a throwing sink is contained (the callback
  // contract is synchronous `void`).
  const onProgress = deps.onProgress;
  const states = selected.map((check): { name: string; state: CiProgressState } => ({
    name: check.name,
    state: skipsByGlob(check) ? "skipped" : "running",
  }));
  const emit = (kind: CiProgressEvent["kind"]): void => {
    if (!onProgress) return;
    try {
      onProgress({
        kind,
        entries: states.map((entry) => ({ name: entry.name, state: entry.state })),
      });
    } catch {
      // Progress must never break the run.
    }
  };
  emit("run_started");

  // Launch every non-skipped check at once; `map` + `Promise.all` keeps `results` in declared
  // order regardless of completion order, and `runOneCheck` never throws, so `Promise.all`
  // cannot reject. Wall time is the MAX of the check durations, not the sum.
  const results: CiCheckOutcome[] = await Promise.all(
    selected.map((check, i) => {
      const glob = check.glob;
      if (glob !== undefined && skipsByGlob(check)) {
        return Promise.resolve(skippedResult(check, glob));
      }
      return runOneCheck(check, deps.runCheck, deps.persistOutput, opts.signal).then((result) => {
        const entry = states[i];
        if (entry) {
          entry.state = result.kind === "executed" && result.exitCode === 0 ? "passed" : "failed";
        }
        emit("check_settled");
        return result;
      });
    }),
  );
  return {
    kind: "completed",
    scope: explicit ? "subset" : "all",
    passed: results.every((c) => c.kind === "skipped" || c.exitCode === 0),
    checks: results,
  };
}
