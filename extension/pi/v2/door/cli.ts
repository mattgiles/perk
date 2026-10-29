// The host CLI (docs/design/pi-durable-v2-foundations.md §11, contracts.md §8.77): parse one
// `perk v2` host invocation, run its verb through the host over the fixture program and the
// production faux worker, and return the door envelope. `main.ts` is the process entry around it.
//
// Invariants:
// - Every option is required explicitly and given as one `--name=value` token by the Python door,
//   which owns every default; a missing, empty, foreign or unknown option is a usage error, and so
//   is anything but exactly one known verb.
// - Observation follows the tracked ref: `start` observes the door's `--repo`/`--ref`; `run` and
//   `reply` observe the `{repo, ref}` the host reads from the execution's records; `status` and
//   `cancel` never observe.
// - The envelope's clock is read once, after the host call returns. Host and binding faults
//   (`HostFault`, `BindingFault`, any other throw) propagate: they are never an outcome.

import { isAbsolute } from "node:path";
import { parseArgs } from "node:util";
import type { WorkerModels } from "../durable/assignment.ts";
import { fixtureWorkerModels } from "../durable/fauxWorker.ts";
import { type HostOptions, type Observe, readStatus, runHost, type TrackedRef } from "../host.ts";
import { isExecutionId } from "../kernel/identity.ts";
import { fixtureProgram } from "../program.ts";
import { gitObserver, observeGitSubject } from "../subject/observe.ts";
import {
  DOOR_VERBS,
  type DoorOutcome,
  type DoorVerb,
  doorOutcomeOfRun,
  doorOutcomeOfStatus,
  type Envelope,
  envelopeOf,
} from "./envelope.ts";

type Common = {
  readonly storeDir: string;
  readonly executionId: string;
  readonly repoIdentity: string;
};

export type CliCommand = Common &
  (
    | { readonly verb: "start"; readonly repo: string; readonly ref: string }
    | { readonly verb: "run" }
    | { readonly verb: "status" }
    | {
        readonly verb: "reply";
        readonly decisionId: string;
        readonly action: string;
        readonly actor: string;
      }
    | { readonly verb: "cancel"; readonly reason: string }
  );

export type Usage = { readonly kind: "usage"; readonly message: string };

export type ParsedCli = { readonly kind: "command"; readonly command: CliCommand } | Usage;

const COMMON_OPTIONS = ["store", "execution", "repo-identity"] as const;

/** Each verb's own options, beyond the common three. */
const VERB_OPTIONS: Readonly<Record<DoorVerb, readonly string[]>> = {
  start: ["repo", "ref"],
  run: [],
  status: [],
  reply: ["decision", "action", "actor"],
  cancel: ["reason"],
};

const OPTION_NAMES = [...COMMON_OPTIONS, ...new Set(Object.values(VERB_OPTIONS).flat())];

function usage(message: string): Usage {
  return { kind: "usage", message };
}

function isDoorVerb(value: string): value is DoorVerb {
  return (DOOR_VERBS as readonly string[]).includes(value);
}

function errorCode(error: unknown): unknown {
  return typeof error === "object" && error !== null ? Reflect.get(error, "code") : undefined;
}

/** Parse the host CLI's argv (without `node` and the script); a typed command or a usage error. */
export function parseCliArgs(argv: readonly string[]): ParsedCli {
  let parsed: { values: Record<string, string | undefined>; positionals: string[] };
  try {
    parsed = parseArgs({
      args: [...argv],
      strict: true,
      allowPositionals: true,
      options: Object.fromEntries(OPTION_NAMES.map((name) => [name, { type: "string" }] as const)),
    });
  } catch (error) {
    const code = errorCode(error);
    if (typeof code === "string" && code.startsWith("ERR_PARSE_ARGS")) {
      return usage(error instanceof Error ? error.message : String(error));
    }
    throw error;
  }
  const { values, positionals } = parsed;
  if (positionals.length !== 1) {
    return usage(`expected exactly one verb (${DOOR_VERBS.join(", ")}), got ${positionals.length}`);
  }
  const [verb = ""] = positionals;
  if (!isDoorVerb(verb)) return usage(`unknown verb ${JSON.stringify(verb)}`);
  const allowed = new Set<string>([...COMMON_OPTIONS, ...VERB_OPTIONS[verb]]);
  for (const [name, value] of Object.entries(values)) {
    if (value === undefined) continue;
    if (!allowed.has(name)) return usage(`--${name} is not an option of ${verb}`);
    if (value === "") return usage(`--${name} is empty`);
  }
  for (const name of allowed) {
    if (values[name] === undefined) return usage(`${verb} requires --${name}`);
  }
  const option = (name: string): string => values[name] ?? "";
  const storeDir = option("store");
  const executionId = option("execution");
  const repoIdentity = option("repo-identity");
  if (!isAbsolute(storeDir)) return usage(`--store ${JSON.stringify(storeDir)} is not absolute`);
  if (!isExecutionId(executionId)) {
    return usage(`--execution ${JSON.stringify(executionId)} is not an execution id`);
  }
  if (!isAbsolute(repoIdentity)) {
    return usage(`--repo-identity ${JSON.stringify(repoIdentity)} is not absolute`);
  }
  const common: Common = { storeDir, executionId, repoIdentity };
  switch (verb) {
    case "start":
      return {
        kind: "command",
        command: { ...common, verb, repo: option("repo"), ref: option("ref") },
      };
    case "run":
    case "status":
      return { kind: "command", command: { ...common, verb } };
    case "reply":
      return {
        kind: "command",
        command: {
          ...common,
          verb,
          decisionId: option("decision"),
          action: option("action"),
          actor: option("actor"),
        },
      };
    case "cancel":
      return { kind: "command", command: { ...common, verb, reason: option("reason") } };
  }
}

export type CliDeps = {
  /** The wall clock: observation times, the manifest's `createdAt`, the envelope; default `Date.now`. */
  readonly now?: () => number;
  /** The worker model catalog; default `fixtureWorkerModels()`. */
  readonly models?: WorkerModels;
  /** Default: one stderr line per report. */
  readonly onReport?: HostOptions["onReport"];
};

/**
 * The tracked observer the door hands `run` and `reply`: it observes the tracked ref the host read
 * from the records, and fails to observe when the execution records none.
 */
export function trackedObserver(storeDir: string, now: () => number): Observe {
  return (tracked: TrackedRef | null) =>
    tracked === null
      ? Promise.resolve({
          kind: "observation_failed",
          detail: "the execution records no tracked ref",
        })
      : observeGitSubject({ storeDir, repo: tracked.repo, ref: tracked.ref, now });
}

function reportToStderr(error: unknown, info: { readonly type: string }): void {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`perk v2 host report (${info.type}): ${message}\n`);
}

/** Run one host CLI invocation: its envelope, or a usage error. Faults propagate. */
export async function runCli(
  argv: readonly string[],
  deps: CliDeps = {},
): Promise<{ readonly kind: "envelope"; readonly envelope: Envelope } | Usage> {
  const parsed = parseCliArgs(argv);
  if (parsed.kind === "usage") return parsed;
  const { command } = parsed;
  const now = deps.now ?? Date.now;
  const { storeDir } = command;
  const options: HostOptions = {
    storeDir,
    workspace: { repoIdentity: command.repoIdentity, executionId: command.executionId },
    program: fixtureProgram({ models: deps.models ?? fixtureWorkerModels() }),
    now,
    onReport: deps.onReport ?? reportToStderr,
  };
  let outcome: DoorOutcome;
  switch (command.verb) {
    case "start":
      outcome = doorOutcomeOfRun(
        await runHost(options, {
          type: "start",
          observe: gitObserver({ storeDir, repo: command.repo, ref: command.ref, now }),
        }),
      );
      break;
    case "run":
      outcome = doorOutcomeOfRun(
        await runHost(options, { type: "run", observe: trackedObserver(storeDir, now) }),
      );
      break;
    case "reply":
      outcome = doorOutcomeOfRun(
        await runHost(options, {
          type: "reply",
          observe: trackedObserver(storeDir, now),
          decisionId: command.decisionId,
          action: command.action,
          actor: command.actor,
        }),
      );
      break;
    case "cancel":
      outcome = doorOutcomeOfRun(
        await runHost(options, { type: "cancel", reason: command.reason }),
      );
      break;
    case "status":
      outcome = doorOutcomeOfStatus(await readStatus(options));
      break;
  }
  return {
    kind: "envelope",
    envelope: envelopeOf(command.verb, command.executionId, outcome, now()),
  };
}
