// Node 1.2 — the runnable entrypoint shim for the headless stage-drive worker.
//
// A THIN CLI over `driveStage`. It does NO positioning, dispatch, or model fiction — positioning is
// the cold-door/runner's job (Gap 7): this shim consumes a PREPARED worktree (handoff/plan-ref/plan-
// body already materialized, `PERK_RUN_ID` already in the env) and FAILS CLOSED if `PERK_RUN_ID` is
// absent (it never mints). It resolves the model/auth headlessly (env-var key resolution, Gap 5),
// re-derives the seeded prompt from the worktree's `cache.plan-ref`, wires SIGINT/SIGTERM to an
// AbortController, drives the stage, prints the `RunOutcome` JSON to stdout (a human summary to
// stderr), and exits 0 on `completed` else non-zero. Runs as `.ts` under node 22 type-stripping.

import { argv, env, exit, stderr, stdout } from "node:process";
import type { Api, Model } from "@earendil-works/pi-ai";
import { AuthStorage, ModelRegistry } from "@earendil-works/pi-coding-agent";
import {
  type DriveBudget,
  type DriveStage,
  driveStage,
  initialPromptForWorktree,
  type RunOutcome,
} from "./worker.ts";

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
export function parseArgs(rawArgv: string[], environ: NodeJS.ProcessEnv): ParsedArgs {
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
      `perk worker: no plan-ref under ${parsed.worktree}/.pi/workflow — cannot seed the ${parsed.stage} prompt.\n`,
    );
    return 2;
  }

  // Headless auth/model (Gap 5): env-var key resolution; `--model provider/id` else first available.
  const authStorage = AuthStorage.create();
  const modelRegistry = ModelRegistry.create(authStorage);
  let model: Model<Api> | undefined;
  if (parsed.model) {
    const [provider, ...rest] = parsed.model.split("/");
    model = modelRegistry.find(provider ?? "", rest.join("/"));
    if (!model) {
      stderr.write(`perk worker: model '${parsed.model}' not found in the registry.\n`);
      return 2;
    }
  }

  const controller = new AbortController();
  const onSignal = (): void => controller.abort();
  process.on("SIGINT", onSignal);
  process.on("SIGTERM", onSignal);

  let outcome: RunOutcome;
  try {
    outcome = await driveStage({
      worktree: parsed.worktree,
      stage: parsed.stage,
      initialPrompt,
      model,
      authStorage,
      modelRegistry,
      budget: parsed.budget,
      signal: controller.signal,
    });
  } finally {
    process.off("SIGINT", onSignal);
    process.off("SIGTERM", onSignal);
  }

  stdout.write(`${JSON.stringify(outcome)}\n`);
  stderr.write(summarize(outcome));
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
