// The runnable entrypoint for the headless stage-drive worker — a THIN entry that admits the
// loaded Pi SDK before any SDK-bearing module links (contracts.md §8.11, §8.76(f)).
//
// It does NO positioning, dispatch, or model fiction — positioning is the cold-door/runner's job
// (Gap 7): this entry consumes a PREPARED worktree (handoff/plan-ref/plan-body already
// materialized, `PERK_RUN_ID` already in the env) and FAILS CLOSED if `PERK_RUN_ID` is absent (it
// never mints).
//
// Order: parse args (usage → exit 2) → admit the loaded SDK against the shared host floor → only
// then `import()` the stage-execution seam → re-derive the seeded prompt from the worktree's
// `cache.plan-ref` → drive. The admission's one SDK observation (the public `VERSION`) is read by
// `substrate/hostSdkVersion.ts` through a namespace import, so an SDK whose named exports differ
// from what the adapter needs cannot fail the process at link time before the refusal runs: this
// file carries NO `@earendil-works/*` specifier and reaches the seam only dynamically (guard Rule
// F). A refused SDK ends the run through the same typed `RunOutcome` (`failed`/`model_error`,
// `error.type` `pi_version_unsupported` | `pi_version_unverifiable`) and the same §8.12
// `run_started`/`run_finished` pair as any drive, via the SDK-free envelope module — so the §8.15
// reporter shows it on the plan issue. A seam import that rejects AFTER admission (an SDK that
// reports a supported version but lacks the exports) is the typed `runtime_init` outcome. A host
// floor that cannot be read is a corrupt perk bundle, not a host verdict: exit 2.
//
// It hands the raw `--model` text to the drive as a seam-re-exported `WorkerModelRequest`: model
// resolution and auth admission run inside the drive, after the worktree's extensions registered
// their providers, so an unknown `--model` is a typed `RunOutcome` (exit 1), not a usage error.
// It wires SIGINT/SIGTERM to an AbortController, prints the `RunOutcome` JSON to stdout (a human
// summary to stderr), and exits 0 on `completed` else non-zero. Runs as `.ts` under node 22
// type-stripping.

import { argv, env, exit, stderr, stdout } from "node:process";
import { runEventsPath, workflowDir } from "./substrate/cache.ts";
import {
  admitHostSdk,
  formatHostSdkRefusal,
  type HostSdkAdmission,
  hostSdkErrorType,
} from "./substrate/hostAdmission.ts";
import { loadHostFloor } from "./substrate/hostFloor.ts";
import { loadedHostSdkVersion } from "./substrate/hostSdkVersion.ts";
import {
  assembleOutcome,
  createEventEmitter,
  type DriveBudget,
  type DriveStage,
  defaultEventSink,
  type RunOutcome,
  type TerminalVerdict,
} from "./worker/runEnvelope.ts";

/** Documented defaults for the budget watchdog (overridable via flags). */
const DEFAULT_BUDGET: DriveBudget = {
  maxTurns: 200,
  maxTokens: 2_000_000,
  wallClockMs: 30 * 60 * 1000, // 30 minutes
};

interface ParsedArgs {
  stage: DriveStage;
  worktree: string;
  model?: string;
  budget: DriveBudget;
}

/** Parse argv/env into the worker inputs; throws a plain Error on a usage/precondition failure. */
function parseArgs(rawArgv: string[], environ: NodeJS.ProcessEnv): ParsedArgs {
  const args = rawArgv.slice(2);
  const flags = new Map<string, string>();
  let stageArg: string | undefined;
  for (let i = 0; i < args.length; i++) {
    const a = args[i] ?? "";
    if (a.startsWith("--")) {
      const eq = a.indexOf("=");
      if (eq !== -1) flags.set(a.slice(2, eq), a.slice(eq + 1));
      else {
        flags.set(a.slice(2), args[i + 1] ?? "");
        i++;
      }
    } else if (stageArg === undefined) {
      stageArg = a;
    }
  }

  if (stageArg !== "implement" && stageArg !== "address") {
    throw new Error(`stage must be 'implement' or 'address' (got ${JSON.stringify(stageArg)})`);
  }
  if (!environ.PERK_RUN_ID) {
    throw new Error(
      "PERK_RUN_ID is required (the worker inherits it from positioning; it never mints).",
    );
  }

  const worktree = flags.get("worktree") ?? environ.PERK_WORKTREE ?? process.cwd();
  const budget: DriveBudget = {
    maxTurns: intFlag(flags.get("max-turns"), DEFAULT_BUDGET.maxTurns),
    maxTokens: intFlag(flags.get("max-tokens"), DEFAULT_BUDGET.maxTokens),
    wallClockMs: intFlag(flags.get("wall-clock-ms"), DEFAULT_BUDGET.wallClockMs),
  };
  const model = flags.get("model");
  return { stage: stageArg, worktree, model, budget };
}

function intFlag(raw: string | undefined, fallback: number): number {
  if (raw === undefined || raw === "") return fallback;
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

/** Print the outcome JSON (stdout), the human summary and the run-events breadcrumb (stderr). */
function report(outcome: RunOutcome, worktree: string): void {
  stdout.write(`${JSON.stringify(outcome)}\n`);
  stderr.write(summarize(outcome));
  // Breadcrumb: where the structured run-event stream landed (cache-tier NDJSON).
  stderr.write(`perk worker: run events → ${runEventsPath(worktree, env.PERK_RUN_ID ?? "")}\n`);
}

/**
 * End a run before any drive exists: the typed zero-turn outcome plus the §8.12
 * `run_started`/`run_finished` pair through the default file sink (seq 0/1), then exit 1.
 */
function refuseBeforeDrive(parsed: ParsedArgs, startMs: number, verdict: TerminalVerdict): 1 {
  const runId = env.PERK_RUN_ID ?? "";
  const outcome = assembleOutcome({
    stage: parsed.stage,
    verdict,
    budget: { turns: 0, tokens: 0, elapsed_ms: Math.max(0, Date.now() - startMs) },
  });
  const emitter = createEventEmitter(defaultEventSink(parsed.worktree, runId), Date.now, startMs);
  emitter.emit({ kind: "run_started", run_id: runId, stage: parsed.stage });
  emitter.emit({ kind: "run_finished", outcome });
  report(outcome, parsed.worktree);
  return 1;
}

async function main(): Promise<number> {
  const startMs = Date.now();
  let parsed: ParsedArgs;
  try {
    parsed = parseArgs(argv, env);
  } catch (err) {
    stderr.write(`perk worker: ${err instanceof Error ? err.message : String(err)}\n`);
    return 2;
  }

  // The SDK-boundary admission: before any extension, resource, provider or model work.
  let hostSdk: HostSdkAdmission;
  try {
    hostSdk = admitHostSdk(loadedHostSdkVersion(), loadHostFloor().piMinVersion);
  } catch (err) {
    stderr.write(
      `perk worker: host floor unreadable — ${err instanceof Error ? err.message : String(err)}\n`,
    );
    return 2;
  }
  if (hostSdk.outcome !== "admitted") {
    return refuseBeforeDrive(parsed, startMs, {
      status: "failed",
      terminal_signal: "model_error",
      pr: null,
      errorType: hostSdkErrorType(hostSdk),
      errorMessage: formatHostSdkRefusal(hostSdk, "worker"),
    });
  }

  let seam: typeof import("./worker/stageExecution.ts");
  try {
    seam = await import("./worker/stageExecution.ts");
  } catch (err) {
    // Admitted by VERSION, yet the SDK-bearing graph failed to link (missing exports).
    const message = err instanceof Error ? err.message : String(err);
    return refuseBeforeDrive(parsed, startMs, {
      status: "failed",
      terminal_signal: "model_error",
      pr: null,
      errorType: "runtime_init",
      errorMessage: `worker runtime initialization failed: ${message}`,
    });
  }

  const initialPrompt = seam.initialPromptForWorktree(parsed.worktree, parsed.stage);
  if (initialPrompt === null) {
    stderr.write(
      `perk worker: no plan-ref under ${workflowDir(parsed.worktree)} — cannot seed the ${parsed.stage} prompt.\n`,
    );
    return 2;
  }

  // Headless model/auth: the raw `--model` text rides the request unresolved. Inside the drive it
  // resolves with pi's CLI semantics (fuzzy matching, `provider/pattern`, a `:thinking` suffix)
  // AFTER extension registration, else the SDK's default chain picks at session creation;
  // an unknown model or a provider without configured auth is a zero-turn typed outcome.
  const controller = new AbortController();
  const onSignal = (): void => controller.abort();
  process.on("SIGINT", onSignal);
  process.on("SIGTERM", onSignal);

  let outcome: RunOutcome;
  try {
    outcome = await seam.runStage({
      worktree: parsed.worktree,
      stage: parsed.stage,
      initialPrompt,
      model: new seam.WorkerModelRequest({ pattern: parsed.model }),
      budget: parsed.budget,
      signal: controller.signal,
    });
  } finally {
    process.off("SIGINT", onSignal);
    process.off("SIGTERM", onSignal);
  }

  report(outcome, parsed.worktree);
  return outcome.status === "completed" ? 0 : 1;
}

/** A one-line human summary for stderr (structured JSON stays on stdout). */
function summarize(o: RunOutcome): string {
  const pr = o.pr ? ` pr=#${o.pr.number}` : "";
  const why = o.error ? ` — ${o.error.summary}` : "";
  return `perk worker: ${o.stage} ${o.status} (${o.terminal_signal})${pr} · ${o.budget.turns} turns, ${o.budget.tokens} tok, ${o.budget.elapsed_ms}ms${why}\n`;
}

const code = await main();
exit(code);
