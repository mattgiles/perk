// The worker tools (docs/design/pi-durable-v2-foundations.md §12 the native assignment): three
// read tools beside Durable's built-in `read`, the report tool a worker finishes through, and the
// extension that carries them with the native assignment task.
//
// Invariants:
// - Every tool reads only through `api.env` — the snapshot environment the env factory builds —
//   and fails closed without one. Every path a tool touches passes the environment's own gate.
// - Output is deterministic: entries and paths are sorted bytewise (UTF-8), and every list is
//   capped with a final `[truncated]` line.
// - `grep` is a literal, case-sensitive substring search: a model-supplied regular expression could
//   backtrack catastrophically in the host process. `find` matches with `posix.matchesGlob` against
//   the path relative to the search root; no bespoke glob dialect.
// - The report tool is receipt-first: with an outcome already recorded under the attempt's
//   `accept-report` op id, it skips verification and lets the kernel replay or refuse. Otherwise it
//   verifies the snapshot, then accepts in one reconcile commit (`operateInTx`). Acceptance never
//   depends on termination: `control.terminate` is only requested (on acceptance, and on every
//   refusal but `invalid_report`, which the model may correct within the run).
// - Every report refusal carries the diagnostic code `perk.v2.refusal:<reason>`; no other tool emits
//   that prefix, so the attempt's `settle` phase can read the refusals back from the transcript.
// - The report arguments are checked by `parseFixtureReport` itself (`prepareArguments`) before
//   pi-ai's validation, which converts types first (a numeric summary would become text); the
//   schema is the model-facing statement of the same rule.

import { Buffer } from "node:buffer";
import { posix } from "node:path";
import type { Context, JsonValue } from "@earendil-works/chord";
import { type Static, Type } from "@earendil-works/pi-ai";
import {
  type AnyTask,
  defineExtension,
  defineTool,
  type Extension,
  type ToolExecutionApi,
  type ToolExecutionResult,
  type ToolRegistration,
} from "@earendil-works/pi-durable";
import { type ExecutionEnv, type FileInfo, getOrThrow } from "@earendil-works/pi-durable/env";
import { createReadTool } from "@earendil-works/pi-durable/tools";
import { FIXTURE_REPORT_TOOL, FIXTURE_WORKER_EXTENSION } from "../kernel/fixture.ts";
import { acceptReportOpId, launchOpId } from "../kernel/identity.ts";
import {
  type FixtureReport,
  indexRecords,
  KernelInvariantError,
  manifestDigestFor,
} from "../kernel/records.ts";
import { KernelRefusal, type Refusal } from "../kernel/refusal.ts";
import { parseFixtureReport } from "../kernel/report.ts";
import { REFUSAL_DIAGNOSTIC_PREFIX } from "./ending.ts";
import { type BindingDeps, type OperateOutcome, operateInTx } from "./operate.ts";
import { attemptOfConversation, readRecords } from "./records.ts";

/** Where a snapshot verification runs: before the worker exists, at acceptance, or at settle. */
export type VerifyPoint = "attempt-start" | "acceptance" | "settle";

export type SnapshotVerification =
  | { readonly ok: true }
  | { readonly ok: false; readonly problem: string };

/** Verify the snapshot of `tree` against `manifestDigest`; `point` names the call site. */
export type SnapshotVerifier = (
  tree: string,
  manifestDigest: string,
  point: VerifyPoint,
) => Promise<SnapshotVerification>;

export type ReportToolOptions = {
  /** The composed binding dependencies; a thunk, because the launcher is itself one of them. */
  readonly deps: () => BindingDeps;
  readonly verify: SnapshotVerifier;
};

/** At most this many `ls` entries and `find` paths. */
export const LIST_CAP = 500;
/** At most this many `grep` matches. */
export const MATCH_CAP = 200;
/** `grep` skips files larger than this. */
export const GREP_MAX_BYTES = 1024 * 1024;
/** `grep` cuts a matching line's text at this many characters. */
export const GREP_LINE_CHARS = 300;
/** `find` and `grep` never descend below this depth. */
export const WALK_MAX_DEPTH = 64;
export const TRUNCATED = "[truncated]";

function requireEnv(api: ToolExecutionApi): ExecutionEnv {
  if (api.env === undefined) throw new Error("no execution environment");
  return api.env;
}

/** Bytewise (UTF-8) order. */
export function compareBytes(a: string, b: string): number {
  return Buffer.compare(Buffer.from(a, "utf8"), Buffer.from(b, "utf8"));
}

function textResult(lines: readonly string[], empty: string): ToolExecutionResult {
  return { output: [{ type: "text", text: lines.length === 0 ? empty : lines.join("\n") }] };
}

function capped(lines: readonly string[], cap: number): string[] {
  return lines.length > cap ? [...lines.slice(0, cap), TRUNCATED] : [...lines];
}

/** The contained absolute path of a tool's `path` argument (default the root). */
async function resolveStart(
  env: ExecutionEnv,
  path: string | undefined,
  context: Context,
): Promise<string> {
  return getOrThrow(await env.absolutePath(path ?? ".", context));
}

/** `absolute` relative to the environment root (`""` for the root itself). */
function rootRelative(env: ExecutionEnv, absolute: string): string {
  return posix.relative(env.cwd, absolute);
}

type Walked = {
  /** Relative to the search root. */
  readonly relative: string;
  readonly absolute: string;
  readonly info: FileInfo;
};

/** Every entry below `start`, depth-capped; a symlink entry is listed but never descended. */
async function walk(env: ExecutionEnv, start: string, context: Context): Promise<Walked[]> {
  const walked: Walked[] = [];
  const visit = async (dir: string, prefix: string, depth: number): Promise<void> => {
    for (const info of getOrThrow(await env.listDir(dir, context))) {
      const relative = prefix === "" ? info.name : `${prefix}/${info.name}`;
      const absolute = posix.join(dir, info.name);
      walked.push({ relative, absolute, info });
      if (info.kind === "directory" && depth < WALK_MAX_DEPTH) {
        await visit(absolute, relative, depth + 1);
      }
    }
  };
  await visit(start, "", 1);
  return walked;
}

const lsSchema = Type.Object({
  path: Type.Optional(
    Type.String({ description: "Directory to list, relative to the snapshot root (default .)" }),
  ),
});

/** `ls {path?}`: one directory's names, `/` after a directory and `@` after a symlink entry. */
export const lsTool = defineTool({
  name: "ls",
  description:
    "List one directory of the read-only snapshot. Directories end in /, symlink entries in @.",
  parameters: lsSchema,
  replay: "safe",
  async execute(args, api, context) {
    const env = requireEnv(api);
    const dir = await resolveStart(env, args.path, context);
    const names = getOrThrow(await env.listDir(dir, context))
      .map((info) =>
        info.kind === "directory"
          ? `${info.name}/`
          : info.kind === "symlink"
            ? `${info.name}@`
            : info.name,
      )
      .sort(compareBytes);
    return textResult(capped(names, LIST_CAP), "(empty directory)");
  },
});

const findSchema = Type.Object({
  pattern: Type.String({
    description: "Glob matched against each path relative to the search root, e.g. **/*.ts",
  }),
  path: Type.Optional(
    Type.String({ description: "Directory to search, relative to the snapshot root (default .)" }),
  ),
});

/** `find {pattern, path?}`: the paths below the search root whose relative path matches the glob. */
export const findTool = defineTool({
  name: "find",
  description:
    "Find paths in the read-only snapshot whose path relative to the search directory matches a glob. Paths are printed relative to the snapshot root.",
  parameters: findSchema,
  replay: "safe",
  async execute(args, api, context) {
    const env = requireEnv(api);
    const start = await resolveStart(env, args.path, context);
    const paths = (await walk(env, start, context))
      .filter((entry) => posix.matchesGlob(entry.relative, args.pattern))
      .map((entry) => rootRelative(env, entry.absolute))
      .sort(compareBytes);
    return textResult(capped(paths, LIST_CAP), "(no matches)");
  },
});

const grepSchema = Type.Object({
  text: Type.String({ description: "Literal, case-sensitive text to search for (not a regex)" }),
  path: Type.Optional(
    Type.String({
      description: "File or directory to search, relative to the snapshot root (default .)",
    }),
  ),
});

/** `grep {text, path?}`: literal, case-sensitive matches as `path:line:text`. */
export const grepTool = defineTool({
  name: "grep",
  description:
    "Search the read-only snapshot for literal, case-sensitive text (never a regular expression). Prints path:line:text, paths relative to the snapshot root.",
  parameters: grepSchema,
  replay: "safe",
  async execute(args, api, context) {
    const env = requireEnv(api);
    if (args.text === "") throw new Error("grep: text is empty");
    const start = await resolveStart(env, args.path, context);
    const startInfo = getOrThrow(await env.fileInfo(start, context));
    const files =
      startInfo.kind === "directory"
        ? (await walk(env, start, context))
            .filter((entry) => entry.info.kind === "file")
            .map((entry) => ({ absolute: entry.absolute, size: entry.info.size }))
        : [{ absolute: start, size: startInfo.size }];
    const ordered = files
      .map((file) => ({ ...file, path: rootRelative(env, file.absolute) }))
      .sort((a, b) => compareBytes(a.path, b.path));
    const matches: string[] = [];
    for (const file of ordered) {
      if (file.size > GREP_MAX_BYTES) continue;
      const text = getOrThrow(await env.readTextFile(file.absolute, context));
      if (text.includes("\0")) continue;
      const lines = text.split("\n");
      for (let i = 0; i < lines.length; i++) {
        const line = (lines[i] ?? "").replace(/\r$/, "");
        if (!line.includes(args.text)) continue;
        matches.push(`${file.path}:${i + 1}:${line.slice(0, GREP_LINE_CHARS)}`);
        if (matches.length > MATCH_CAP) return textResult(capped(matches, MATCH_CAP), "");
      }
    }
    return textResult(matches, "(no matches)");
  },
});

// One character of a well-formed string: anything but a surrogate, or a surrogate pair.
const TEXT_CHAR = String.raw`(?:[^\uD800-\uDFFF]|[\uD800-\uDBFF][\uDC00-\uDFFF])`;
// One character of a snapshot-path segment: also no `/`, LF or NUL.
const PATH_CHAR = String.raw`(?:[^\n\u0000/\uD800-\uDFFF]|[\uD800-\uDBFF][\uDC00-\uDFFF])`;
// A segment that is not exactly `.` or `..`.
const PATH_SEGMENT = String.raw`(?!\.\.?(?:/|$))${PATH_CHAR}+`;

/** The fixture report schema: `parseFixtureReport`'s rule, stated for the model. */
export const FIXTURE_REPORT_SCHEMA = Type.Object(
  {
    subjectDigest: Type.String({
      pattern: "^(?:[0-9a-f]{40}|[0-9a-f]{64})$",
      description: "The git tree named in the request",
    }),
    summary: Type.String({ pattern: `^${TEXT_CHAR}+$`, description: "Non-empty summary" }),
    findings: Type.Array(
      Type.Object(
        {
          path: Type.String({
            pattern: `^${PATH_SEGMENT}(?:/${PATH_SEGMENT})*$`,
            description: "Snapshot-relative path",
          }),
          note: Type.String({ pattern: `^${TEXT_CHAR}+$`, description: "Non-empty note" }),
        },
        { additionalProperties: false },
      ),
    ),
  },
  { additionalProperties: false },
);

export type FixtureReportArgs = Static<typeof FIXTURE_REPORT_SCHEMA>;

/** A fixture report as a fresh, mutable JSON value. */
function reportJson(report: FixtureReport): FixtureReportArgs {
  return {
    subjectDigest: report.subjectDigest,
    summary: report.summary,
    findings: report.findings.map((finding) => ({ path: finding.path, note: finding.note })),
  };
}

/** The raw arguments as a fixture report; throws (an `invalid_arguments` result) otherwise. */
export function prepareReportArguments(args: unknown): FixtureReportArgs {
  const report = parseFixtureReport(args);
  if (report === null) throw new Error("report does not match the fixture-report schema");
  return reportJson(report);
}

function refusalResult(refusal: Refusal): ToolExecutionResult {
  return {
    output: [{ type: "text", text: `${refusal.reason}: ${refusal.detail}` }],
    isError: true,
    diagnostics: [
      {
        severity: "error",
        code: `${REFUSAL_DIAGNOSTIC_PREFIX}${refusal.reason}`,
        message: refusal.detail,
      },
    ],
    ...(refusal.reason === "invalid_report" ? {} : { control: { terminate: true } }),
  };
}

/** The report-outcome record an accepting outcome carries. */
function acceptedReport(
  outcome: Extract<OperateOutcome, { readonly kind: "applied" | "replayed" }>,
  opId: string,
): FixtureReport {
  const record =
    outcome.kind === "replayed"
      ? outcome.receipt.record
      : (outcome.receipt?.record ??
        outcome.recorded.find(
          (recorded) => recorded.type !== "manifest" && recorded.opId === opId,
        ));
  if (record?.type !== "report-outcome") {
    throw new KernelInvariantError(`${opId}: acceptance returned no report outcome`);
  }
  return record.report;
}

/** The report tool over the binding dependencies and the snapshot verifier. */
export function createReportTool(options: ReportToolOptions) {
  return defineTool({
    name: FIXTURE_REPORT_TOOL,
    description:
      "Finish the review: call exactly once, alone in its turn, as your last action, with the subject tree, a summary and your findings.",
    parameters: FIXTURE_REPORT_SCHEMA,
    structuredOutputSchema: FIXTURE_REPORT_SCHEMA,
    replay: "safe",
    prepareArguments: prepareReportArguments,
    async execute(args, api, context): Promise<ToolExecutionResult> {
      const read = await readRecords(api);
      const index = indexRecords(read.records);
      const attempt = attemptOfConversation(index, read.durableMap, api.conversationId);
      if (attempt === null) {
        return refusalResult({
          reason: "invalid_input",
          detail: `conversation ${api.conversationId} is no attempt's worker conversation`,
        });
      }
      const assignment = index.assignments.get(attempt.assignmentId);
      const tree = assignment?.subject.digest;
      const digest = tree === undefined ? null : manifestDigestFor(index, tree);
      const launch = read.durableMap.get(launchOpId(attempt.attemptId));
      if (tree === undefined || digest === null || launch?.durableKind !== "task") {
        throw new KernelInvariantError(
          `${attempt.opId}: no assignment, observed manifest digest or launch row`,
        );
      }
      const opId = acceptReportOpId(attempt.attemptId);
      if (!index.byOpId.has(opId)) {
        const verification = await options.verify(tree, digest, "acceptance");
        if (!verification.ok) {
          return refusalResult({ reason: "snapshot_tampered", detail: verification.problem });
        }
      }
      let outcome: Extract<OperateOutcome, { readonly kind: "applied" | "replayed" }>;
      try {
        outcome = await api.commit(async (tx) => {
          const owner = (await tx.conversation(api.conversationId))?.owner;
          if (owner === undefined || owner.taskId !== launch.durableId) {
            throw new KernelInvariantError(
              `conversation ${api.conversationId} is not owned by the launched task ${launch.durableId}`,
            );
          }
          return operateInTx(
            tx,
            {
              type: "accept-report",
              attemptId: attempt.attemptId,
              report: args,
              verifiedDigest: digest,
            },
            options.deps(),
            owner.conversationId,
          );
        }, context);
      } catch (error) {
        if (error instanceof KernelRefusal) {
          return refusalResult({ reason: error.reason, detail: error.detail });
        }
        throw error;
      }
      const report: JsonValue = reportJson(acceptedReport(outcome, opId));
      return {
        output: [{ type: "text", text: `accepted ${opId}` }],
        structuredOutput: report,
        control: { terminate: true },
      };
    },
  });
}

/**
 * The worker extension: Durable's built-in `read` exactly as built (replay-unsafe), the three read
 * tools, the report tool, and the given tasks (the native assignment task).
 */
export function workerExtension(options: ReportToolOptions, tasks: readonly AnyTask[]): Extension {
  const tools: readonly ToolRegistration[] = [
    createReadTool(),
    lsTool,
    grepTool,
    findTool,
    createReportTool(options),
  ];
  return defineExtension({ name: FIXTURE_WORKER_EXTENSION, tools, tasks });
}
