// FIXME: remove when pi-subagents clears recovered assistant errors for structured-output
// completion. This is an exact-source, proof-gated exception, never general failed-run salvage.
// All artifacts remain untrusted DATA. Missing/ambiguous proof preserves the original failure.

import { createHash } from "node:crypto";
import { closeSync, constants, fstatSync, openSync, readSync, realpathSync } from "node:fs";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { isDeepStrictEqual } from "node:util";
import { Compile } from "typebox/compile";
import type { WaveRunHandle, WaveStaleErrorRecovery } from "./transport.ts";

const VERSION = "0.65.1";
const STALE_ERROR = "Request timed out.";
const SOURCE_HASHES = {
  "src/runs/background/run-child-session.ts":
    "86f302832a21afdb0e79446d20d58be242d23c09f3d425bf4db254a09c10c940",
  "src/runs/background/subagent-runner.ts":
    "0468a7895fce4e7b54c7cb6616abb711c1860c531c103b963869c04072bf3a72",
  "src/runs/shared/structured-output.ts":
    "b251a8f692e9b8ddaa42692e30b751acb53529f34033c544f909bac9eaf90127",
};
const STATUS_LIMIT = 2 * 1024 * 1024;
const EVENTS_LIMIT = 16 * 1024 * 1024;
const REPORT_LIMIT = 1024 * 1024;

class ProofRefused extends Error {}
function requireProof(condition: unknown): asserts condition {
  if (!condition) throw new ProofRefused("stale-error compatibility proof refused");
}
function record(value: unknown): Record<string, unknown> {
  requireProof(typeof value === "object" && value !== null && !Array.isArray(value));
  return value as Record<string, unknown>;
}
function array(value: unknown): unknown[] {
  requireProof(Array.isArray(value));
  return value;
}
function text(value: unknown): string {
  requireProof(typeof value === "string" && value.length > 0);
  return value;
}
function time(value: unknown): number {
  requireProof(typeof value === "number" && Number.isFinite(value) && value > 0);
  return value;
}
function unique(rows: unknown, matches: (row: Record<string, unknown>) => boolean) {
  const found = array(rows).map(record).filter(matches);
  requireProof(found.length === 1);
  return record(found[0]);
}
function digest(raw: string): string {
  return createHash("sha256").update(raw).digest("hex");
}

/** Bound allocation/reads and refuse changing/non-regular files or symlinked descendants. */
function readWithin(root: string, file: string, limit: number): string {
  requireProof(isAbsolute(file));
  const canonicalRoot = realpathSync(root);
  const rel = relative(canonicalRoot, resolve(file));
  requireProof(rel !== "" && !isAbsolute(rel) && rel !== ".." && !rel.startsWith(`..${sep}`));
  const canonical = join(canonicalRoot, rel);
  requireProof(realpathSync(canonical) === canonical);
  const fd = openSync(canonical, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const before = fstatSync(fd);
    requireProof(before.isFile() && before.size > 0 && before.size <= limit);
    const bytes = Buffer.alloc(before.size);
    let offset = 0;
    while (offset < bytes.length) {
      const count = readSync(fd, bytes, offset, bytes.length - offset, offset);
      requireProof(count > 0);
      offset += count;
    }
    const after = fstatSync(fd);
    requireProof(
      before.size === after.size &&
        before.mtimeMs === after.mtimeMs &&
        before.ctimeMs === after.ctimeMs,
    );
    requireProof(realpathSync(canonical) === canonical);
    return bytes.toString("utf8");
  } finally {
    closeSync(fd);
  }
}
function jsonWithin(root: string, file: string, limit: number): unknown {
  return JSON.parse(readWithin(root, file, limit));
}
function canonicalChildFile(root: string, candidate: unknown): string {
  const file = text(candidate);
  requireProof(isAbsolute(file));
  // Resolve the platform's /var → /private/var alias, then require a direct structured-output
  // descendant. No arbitrary path supplied by a report or another child is ever read.
  const canonical = realpathSync(file);
  const rel = relative(root, canonical).split(sep);
  requireProof(
    rel.length === 3 &&
      rel[0] === "structured-output" &&
      rel[1]?.startsWith("pi-subagent-structured-"),
  );
  requireProof(realpathSync(dirname(file)) === join(root, "structured-output", text(rel[1])));
  return canonical;
}

/** SourceInfo.path comes from the registered subagent tool, not cwd or model-supplied paths. */
function attest(entry: string | undefined): string {
  requireProof(entry !== undefined && isAbsolute(entry));
  const canonicalEntry = realpathSync(entry);
  let root = dirname(canonicalEntry);
  for (let depth = 0; depth < 8; depth++) {
    let manifest: Record<string, unknown> | undefined;
    try {
      manifest = record(jsonWithin(root, join(root, "package.json"), 64 * 1024));
    } catch (error) {
      if (!(error instanceof Error && "code" in error && error.code === "ENOENT")) throw error;
    }
    if (manifest?.name === "pi-subagents") {
      requireProof(manifest.version === VERSION);
      for (const [file, hash] of Object.entries(SOURCE_HASHES)) {
        requireProof(digest(readWithin(root, join(root, file), 512 * 1024)) === hash);
      }
      return canonicalEntry;
    }
    const parent = dirname(root);
    requireProof(parent !== root);
    root = parent;
  }
  throw new ProofRefused("no attested engine root");
}

interface ExpectedAssignment {
  key: string;
  agent: string;
  schema: object;
}
export interface StaleErrorGuardOptions {
  engineEntry: () => string | undefined;
  assignments: ExpectedAssignment[];
}

/** Prove the retry/capture/settlement sequence, including absence of later/hard failures. */
function proveEvents(raw: string, child: Record<string, unknown>, agent: string) {
  const rows: unknown[] = raw
    .trimEnd()
    .split("\n")
    .map((line) => JSON.parse(line));
  requireProof(rows.length > 0 && rows.length <= 50_000);
  let lastTime = 0;
  let errorSeen = false;
  let retryActive = false;
  let recovered = false;
  let call: { id: string; value: unknown } | undefined;
  let executionSucceeded = false;
  let captureSucceeded = false;
  let ended = false;
  let settled = false;
  const activeTools = new Set<string>();
  for (const value of rows) {
    const e = record(value);
    const kind = text(e.type);
    requireProof(
      !/timeout|timed_out|stop|interrupt|abort|cancel|extension_error|budget/i.test(kind),
    );
    if (e.subagentSource !== "child") {
      requireProof(e.runId === child.runId && kind.startsWith("subagent."));
      continue;
    }
    requireProof(
      e.subagentRunId === child.runId && e.subagentStepIndex === 0 && e.subagentAgent === agent,
    );
    const at = time(e.observedAt);
    requireProof(at >= lastTime && at >= time(child.startedAt) && at <= time(child.endedAt));
    lastTime = at;
    requireProof(!settled);
    if (kind === "auto_retry_start") {
      requireProof(errorSeen && !call && e.errorMessage === STALE_ERROR);
      retryActive = true;
    } else if (kind === "auto_retry_end") {
      requireProof(retryActive && e.success === true && !call);
      retryActive = false;
      recovered = true;
    } else if (kind === "message_end") {
      const message = record(e.message);
      if (message.role === "assistant") {
        requireProof(!call);
        if (message.errorMessage !== undefined) {
          requireProof(message.errorMessage === STALE_ERROR);
          errorSeen = true;
          recovered = false;
        }
        const calls = array(message.content)
          .map(record)
          .filter((part) => part.type === "toolCall");
        const capture = calls.find((part) => part.name === "structured_output");
        if (capture) {
          requireProof(
            errorSeen && recovered && !retryActive && calls.length === 1 && activeTools.size === 0,
          );
          call = { id: text(capture.id), value: record(capture.arguments).value };
        }
      } else if (message.role === "toolResult") {
        requireProof(message.isError === false);
        if (message.toolName === "structured_output") {
          requireProof(
            call && executionSucceeded && message.toolCallId === call.id && !captureSucceeded,
          );
          captureSucceeded = true;
        } else {
          requireProof(!call);
        }
      }
    } else if (kind === "tool_execution_start") {
      const id = text(e.toolCallId);
      requireProof(!activeTools.has(id));
      if (call)
        requireProof(
          e.toolName === "structured_output" && id === call.id && activeTools.size === 0,
        );
      activeTools.add(id);
    } else if (kind === "tool_execution_end") {
      const id = text(e.toolCallId);
      requireProof(activeTools.delete(id) && e.isError === false);
      if (e.toolName === "structured_output") {
        requireProof(call && id === call.id && !executionSucceeded);
        executionSucceeded = true;
      } else requireProof(!call);
    } else if (kind === "agent_end" && e.willRetry === false) {
      requireProof(captureSucceeded && recovered && activeTools.size === 0);
      ended = true;
    } else if (kind === "agent_settled") {
      requireProof(ended && captureSucceeded && recovered);
      settled = true;
    }
    if (captureSucceeded)
      requireProof(!["agent_start", "turn_start", "auto_retry_start"].includes(kind));
  }
  requireProof(
    call &&
      errorSeen &&
      recovered &&
      !retryActive &&
      executionSucceeded &&
      captureSucceeded &&
      ended &&
      settled,
  );
  return call;
}

function recoverChild(
  handle: WaveRunHandle,
  parent: Record<string, unknown>,
  expected: ExpectedAssignment,
  validate: (value: unknown) => boolean,
) {
  const step = unique(parent.steps, (s) => s.workflowKey === expected.key);
  requireProof(
    step.agent === expected.agent &&
      step.parentWorkflowRunId === handle.asyncId &&
      step.status === "failed" &&
      step.async === true,
  );
  const runId = text(step.runId);
  requireProof(runId.length <= 128 && basename(runId) === runId && runId !== "." && runId !== "..");
  requireProof(
    array(parent.steps)
      .map(record)
      .filter((s) => s.runId === runId).length === 1,
  );
  const inventory = record(parent.workflowChildren);
  requireProof(
    inventory.version === 1 &&
      inventory.inventoryComplete === true &&
      inventory.workflowState === "completed" &&
      inventory.workflowRunId === handle.asyncId,
  );
  const member = unique(inventory.children, (s) => s.childId === expected.key);
  requireProof(
    member.agent === expected.agent && member.runId === runId && member.state === "failed",
  );
  requireProof(
    array(inventory.children)
      .map(record)
      .filter((s) => s.runId === runId).length === 1,
  );
  const store = dirname(realpathSync(handle.asyncDir));
  const root = join(store, runId);
  requireProof(realpathSync(root) === root);
  const child = record(jsonWithin(root, join(root, "status.json"), STATUS_LIMIT));
  requireProof(
    child.runId === runId &&
      child.parentWorkflowRunId === handle.asyncId &&
      child.workflowKey === expected.key,
  );
  requireProof(
    child.mode === "single" &&
      child.state === "failed" &&
      child.sessionId === parent.sessionId &&
      child.cwd === parent.cwd,
  );
  requireProof(child.error === undefined || child.error === STALE_ERROR);
  requireProof(
    time(child.startedAt) >= time(parent.startedAt) && time(child.endedAt) <= time(parent.endedAt),
  );
  requireProof(
    time(child.endedAt) < time(child.deadlineAt) &&
      time(child.endedAt) - time(child.startedAt) < time(child.timeoutMs),
  );
  for (const flag of ["timedOut", "stopped", "interrupted", "forcedTermination"])
    requireProof(child[flag] !== true);
  const terminal = record(child.processTerminal);
  requireProof(terminal.state === "observed" && terminal.runId === runId);
  const instances = array(terminal.instances);
  requireProof(instances.length === 1);
  const process = record(instances[0]);
  requireProof(process.kind === "runner" && process.exitCode === 0 && process.signal === null);
  const steps = array(child.steps);
  requireProof(steps.length === 1);
  const result = record(steps[0]);
  requireProof(
    result.agent === expected.agent &&
      result.context === "fresh" &&
      result.sessionFile === step.sessionFile,
  );
  requireProof(result.status === "failed" && result.exitCode === 1 && result.error === STALE_ERROR);
  requireProof(
    array(result.attemptedModels).length === 1 && array(result.modelAttempts).length === 1,
  );
  const diagnostic = record(record(result.effects).settlementDiagnostic);
  requireProof(
    diagnostic.finalTextPresent === false && diagnostic.afterCompactionSettlement === false,
  );
  const mutation = record(diagnostic.mutation);
  requireProof(
    mutation.expected === false && mutation.attempted === false && mutation.observed === false,
  );
  const requiredOutput = record(diagnostic.requiredOutput);
  requireProof(
    requiredOutput.kind === "structured" &&
      requiredOutput.missing === false &&
      requiredOutput.path === result.structuredOutputPath,
  );
  const acceptance = record(result.acceptance);
  requireProof(
    acceptance.status === "not-required" && record(acceptance.effectiveAcceptance).level === "none",
  );
  const outputPath = canonicalChildFile(root, result.structuredOutputPath);
  const schemaPath = canonicalChildFile(root, result.structuredOutputSchemaPath);
  requireProof(
    basename(outputPath) === "output.json" &&
      basename(schemaPath) === "schema.json" &&
      dirname(outputPath) === dirname(schemaPath),
  );
  requireProof(isDeepStrictEqual(jsonWithin(root, schemaPath, REPORT_LIMIT), expected.schema));
  const events = readWithin(root, join(root, "events.jsonl"), EVENTS_LIMIT);
  const call = proveEvents(events, child, expected.agent);
  const raw = readWithin(root, outputPath, REPORT_LIMIT);
  const report: unknown = JSON.parse(raw);
  requireProof(
    record(report).angle === expected.key &&
      isDeepStrictEqual(report, call.value) &&
      validate(report),
  );
  return {
    report,
    recovery: {
      key: expected.key,
      runId,
      originalError: STALE_ERROR,
      reason: "pi-subagents-0.65.1-stale-assistant-error" as const,
      reportHash: digest(raw),
      eventsHash: digest(events),
      sourceHash: SOURCE_HASHES["src/runs/background/run-child-session.ts"],
    },
  };
}

/** No guard is enabled unless original schemas and the registered engine source are attested. */
export function createStaleErrorGuard(options: StaleErrorGuardOptions) {
  let entry: string;
  let expected: { assignment: ExpectedAssignment; validate: (value: unknown) => boolean }[];
  try {
    entry = attest(options.engineEntry());
    expected = options.assignments.map((a) => {
      const assignment = { ...a, schema: structuredClone(a.schema) };
      const validator = Compile(assignment.schema);
      return { assignment, validate: (value: unknown) => validator.Check(value) };
    });
  } catch {
    // This optional compatibility boundary never widens a normal failure on unavailable proof.
    return undefined;
  }
  return (
    handle: WaveRunHandle,
    rawStatus: string,
  ): { value: unknown; recoveries: WaveStaleErrorRecovery[] } | undefined => {
    try {
      requireProof(
        Buffer.byteLength(rawStatus) <= STATUS_LIMIT && attest(options.engineEntry()) === entry,
      );
      const parent = record(JSON.parse(rawStatus));
      requireProof(
        parent.runId === handle.asyncId &&
          parent.mode === "workflow" &&
          parent.state === "complete",
      );
      requireProof(parent.error === undefined && time(parent.endedAt) < time(parent.deadlineAt));
      const entries = array(record(parent.workflow).value).map(record);
      requireProof(
        entries.length === expected.length &&
          new Set(entries.map((e) => e.key)).size === entries.length,
      );
      const recoveries: WaveStaleErrorRecovery[] = [];
      const value = entries.map((row) => {
        const spec = expected.find((e) => e.assignment.key === row.key);
        requireProof(spec);
        if (
          row.ok !== false ||
          row.report !== null ||
          typeof row.error !== "string" ||
          !/^(?:Run fan-out: \d+\/\d+ used, \d+ remaining\n)?Request timed out\.$/.test(row.error)
        )
          return row;
        try {
          const recovered = recoverChild(handle, parent, spec.assignment, spec.validate);
          recoveries.push({ ...recovered.recovery, originalError: row.error });
          return { ...row, ok: true, error: null, report: recovered.report };
        } catch {
          // Refusal leaves this exact row intact; siblings are independent. No artifact is edited.
          return row;
        }
      });
      return { value, recoveries };
    } catch {
      return undefined;
    }
  };
}
