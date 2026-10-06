// The runnable entrypoint shim for the headless stage-drive worker.
//
// A THIN CLI over the stage-execution seam's `runStage`. It does NO positioning, dispatch, or
// model fiction — positioning is the cold-door/runner's job (Gap 7): this shim consumes a PREPARED
// worktree (handoff/plan-ref/plan-body already materialized, `PERK_RUN_ID` already in the env) and
// FAILS CLOSED if `PERK_RUN_ID` is absent (it never mints). It hands the raw `--model` text to
// the drive as a seam-re-exported `WorkerModelRequest`: model resolution and auth admission run
// inside the drive, after the worktree's extensions registered their providers, so an unknown
// `--model` is a typed `RunOutcome` (exit 1), not a usage error. This file imports ONLY the seam
// and carries ZERO SDK imports (guard Rule F). It re-derives the seeded prompt from the
// worktree's `cache.plan-ref`, wires SIGINT/SIGTERM to an AbortController, drives the stage,
// prints the `RunOutcome` JSON to stdout (a human summary to stderr), and exits 0 on `completed`
// else non-zero. Runs as `.ts` under node 22 type-stripping.

import { argv, env, exit, stderr, stdout } from "node:process";
import { runEventsPath, workflowDir } from "./substrate/cache.ts";
import {
  type DriveBudget,
  type DriveStage,
  initialPromptForWorktree,
  type RunOutcome,
  runStage,
  WorkerModelRequest,
} from "./worker/stageExecution.ts";

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

async function main(): Promise<number> {
  let parsed: ParsedArgs;
  try {
    parsed = parseArgs(argv, env);
  } catch (err) {
    stderr.write(`perk worker: ${err instanceof Error ? err.message : String(err)}\n`);
    return 2;
  }

  const initialPrompt = initialPromptForWorktree(parsed.worktree, parsed.stage);
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
    outcome = await runStage({
      worktree: parsed.worktree,
      stage: parsed.stage,
      initialPrompt,
      model: new WorkerModelRequest({ pattern: parsed.model }),
      budget: parsed.budget,
      signal: controller.signal,
    });
  } finally {
    process.off("SIGINT", onSignal);
    process.off("SIGTERM", onSignal);
  }

  stdout.write(`${JSON.stringify(outcome)}\n`);
  stderr.write(summarize(outcome));
  // Breadcrumb: where the structured run-event stream landed (cache-tier NDJSON).
  stderr.write(
    `perk worker: run events → ${runEventsPath(parsed.worktree, env.PERK_RUN_ID ?? "")}\n`,
  );
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
