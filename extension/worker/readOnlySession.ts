// The perk-owned, in-process read-only child session (context-isolation primitive #1).
//
// A deterministic, fully-isolated read-only child spun at the SDK level via `createAgentSession`,
// plus the handoff contract both context-isolation primitives honor (the in-process one here; the
// spawned shape later): cap the model-visible output, keep the FULL result in a verified scratch
// file + a structured block, and return DOUBLE-DELIVERY (compact prose for the human + a structured
// block for the orchestrator). Route-don't-relay is enforced structurally — the raw child output
// never enters the parent; only a path/summary does. This is substrate only; its consumer is the
// read-only CI executor. No registry stage, no door change, no cross-CLI behavior.
//
// Relationship to the in-session gate (extension/substrate/toolGating.ts): its READ_ONLY_TOOLS is the *in-session* allowlist
// and includes a sub-allowlisted `bash`. This SDK-level set is the STRICTER ["read","grep","find",
// "ls"] (no bash) — a separate constant, not a reuse. The CI executor composes its own allowlist when it needs a
// gated test-runner command; that is not authored here.
//
// Isolation comes from the DefaultResourceLoader `no*` flags + the tools allowlist — NOT from
// `extensionFactories: []` (which is already the default and controls only inline factories; it
// does not stop `loader.reload()` from resolving the project's `.pi/settings.json` packages and
// loading perk's own extension into the child). The `no*` flags keep perk's machinery out of the
// child and keep the path offline/deterministic. A custom loader is reloaded by the caller.

import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Api, Model } from "@earendil-works/pi-ai";
import {
  type AgentSession,
  createAgentSession,
  DefaultResourceLoader,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { runScratchDir, scratchDir } from "../substrate/cache.ts";

/**
 * The SDK-level read-only allowlist (no `bash`; stricter than the in-session READ_ONLY_TOOLS).
 * Mirrors pi's read-only recipe (examples/sdk/05-tools.ts).
 */
export const SDK_READ_ONLY_TOOLS = ["read", "grep", "find", "ls"];

/** The model-visible byte cap (matches subagent's PER_TASK_OUTPUT_CAP); overridable per call. */
export const DEFAULT_MODEL_VISIBLE_CAP = 50 * 1024;

/** Minimal structural shape of a session message (we only read assistant text parts). */
interface MessageLike {
  role?: string;
  content?: unknown;
}

/**
 * Scan messages newest-first for the last assistant message's first text part; "" if none.
 * Pure — mirrors subagent's getFinalOutput.
 */
export function extractFinalAssistantText(messages: readonly MessageLike[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg?.role !== "assistant") continue;
    const content = msg.content;
    if (typeof content === "string") return content;
    if (Array.isArray(content)) {
      for (const part of content) {
        const p = part as { type?: string; text?: string };
        if (p.type === "text" && typeof p.text === "string") return p.text;
      }
    }
  }
  return "";
}

export interface CapResult {
  /** The (possibly truncated) text safe to show the model. */
  shown: string;
  /** Total UTF-8 byte length of the original text. */
  bytesTotal: number;
  /** UTF-8 byte length of `shown` (before the truncation notice). */
  bytesShown: number;
  /** Whether truncation occurred. */
  truncated: boolean;
}

/**
 * UTF-8-byte-safe truncation (subagent's byte-trim loop). Under cap ⇒ unchanged, truncated:false.
 * When truncated, appends a notice that points at the scratch file holding the full result.
 * Pure.
 */
export function capForModel(
  text: string,
  cap: number = DEFAULT_MODEL_VISIBLE_CAP,
  scratchPath: string | null = null,
): CapResult {
  const bytesTotal = Buffer.byteLength(text, "utf8");
  if (bytesTotal <= cap) {
    return { shown: text, bytesTotal, bytesShown: bytesTotal, truncated: false };
  }
  let trimmed = text.slice(0, cap);
  while (Buffer.byteLength(trimmed, "utf8") > cap) trimmed = trimmed.slice(0, -1);
  const bytesShown = Buffer.byteLength(trimmed, "utf8");
  const omitted = bytesTotal - bytesShown;
  const where = scratchPath ? ` Full output preserved at ${scratchPath}.` : "";
  const notice = `\n\n[Output truncated: ${omitted} bytes omitted.${where}]`;
  return { shown: `${trimmed}${notice}`, bytesTotal, bytesShown, truncated: true };
}

/**
 * The structured half of the double-delivery handoff — the block the orchestrator parses (and the
 * CI executor will place in a tool's forking-safe `details`).
 */
export interface ChildStructured {
  success: boolean;
  summary: string;
  scratchPath: string | null;
  bytesTotal: number;
  bytesShown: number;
  truncated: boolean;
  error?: string;
}

/**
 * The full double-delivery handoff: `prose` is the capped human-facing summary; `structured` is the
 * orchestrator-facing block; `scratchPath` is the verified path to the full result
 * (route-don't-relay — the raw output never enters the parent beyond the cap).
 */
export interface ChildHandoff {
  success: boolean;
  prose: string;
  structured: ChildStructured;
  scratchPath: string | null;
}

/**
 * Create a locked-down, SDK-level read-only child session. Isolation = the DefaultResourceLoader
 * `no*` flags + the tools allowlist; a throwaway temp `agentDir` (a locked-down child loads nothing
 * from it, and there is no production ctx.agentDir). Creating the session is OFFLINE; only
 * `prompt()` requires a key. The caller must `dispose()` the returned session.
 */
export async function createReadOnlySession(opts: {
  cwd: string;
  model?: Model<Api>;
  tools?: string[];
}): Promise<{ session: AgentSession }> {
  // A throwaway temp agentDir — a locked-down child loads nothing from it (no production
  // ctx.agentDir exists), exactly as the offline harness does.
  const agentDir = mkdtempSync(join(tmpdir(), "perk-ro-agent-"));
  const loader = new DefaultResourceLoader({
    cwd: opts.cwd,
    agentDir,
    noExtensions: true,
    noSkills: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
  });
  // A custom loader is NOT auto-reloaded by createAgentSession — reload it ourselves.
  await loader.reload();
  const { session } = await createAgentSession({
    cwd: opts.cwd,
    model: opts.model,
    resourceLoader: loader,
    tools: opts.tools ?? SDK_READ_ONLY_TOOLS,
    sessionManager: SessionManager.inMemory(opts.cwd),
    settingsManager: SettingsManager.inMemory({
      compaction: { enabled: false },
      retry: { enabled: false },
    }),
  });
  return { session };
}

export interface RunReadOnlyChildOpts {
  cwd: string;
  task: string;
  model?: Model<Api>;
  tools?: string[];
  runId?: string;
  step?: string;
  modelVisibleCap?: number;
  signal?: AbortSignal;
}

export interface RunReadOnlyChildDeps {
  createSession?: (opts: {
    cwd: string;
    model?: Model<Api>;
    tools?: string[];
  }) => Promise<{ session: AgentSession }>;
  runTask?: (session: AgentSession, task: string, signal?: AbortSignal) => Promise<string>;
}

/** Default production runTask: prompt the child, then extract its final assistant text. */
async function defaultRunTask(
  session: AgentSession,
  task: string,
  _signal?: AbortSignal,
): Promise<string> {
  await session.prompt(task);
  return extractFinalAssistantText(session.messages as unknown as MessageLike[]);
}

/** Resolve the scratch file path for a child's full output (run-scoped when a runId is given). */
function resolveScratchPath(cwd: string, runId?: string, step?: string): string {
  if (runId) {
    const dir = runScratchDir(cwd, runId);
    mkdirSync(dir, { recursive: true });
    return join(dir, `${step ?? "child"}.md`);
  }
  const base = scratchDir(cwd);
  mkdirSync(base, { recursive: true });
  const dir = mkdtempSync(join(base, "child-"));
  return join(dir, `${step ?? "child"}.md`);
}

function failure(prose: string, error: string): ChildHandoff {
  return {
    success: false,
    prose,
    scratchPath: null,
    structured: {
      success: false,
      summary: prose,
      scratchPath: null,
      bytesTotal: 0,
      bytesShown: 0,
      truncated: false,
      error,
    },
  };
}

/**
 * One-shot read-only child orchestrator implementing the handoff contract: create the read-only
 * session, run the task, write the full raw output to a scratch file and VERIFY it
 * (write→verify→pass-path), cap the model-visible output into prose, and return
 * double-delivery. Fail loud + fail closed: NEVER throws to the parent — on any error it returns
 * `{ success:false, scratchPath:null }` with the error in both `prose` and `structured.error`.
 */
export async function runReadOnlyChild(
  opts: RunReadOnlyChildOpts,
  deps: RunReadOnlyChildDeps = {},
): Promise<ChildHandoff> {
  const createSession = deps.createSession ?? createReadOnlySession;
  const runTask = deps.runTask ?? defaultRunTask;
  const cap = opts.modelVisibleCap ?? DEFAULT_MODEL_VISIBLE_CAP;

  if (opts.signal?.aborted) return failure("read-only child aborted before start.", "aborted");

  let session: AgentSession | null = null;
  try {
    const created = await createSession({ cwd: opts.cwd, model: opts.model, tools: opts.tools });
    session = created.session;

    const output = await runTask(session, opts.task, opts.signal);

    if (opts.signal?.aborted) return failure("read-only child aborted.", "aborted");

    // write → verify → pass-path: persist the full result, then confirm it landed.
    const scratchPath = resolveScratchPath(opts.cwd, opts.runId, opts.step);
    writeFileSync(scratchPath, output, "utf8");
    if (!existsSync(scratchPath)) {
      return failure("read-only child: scratch write could not be verified.", "scratch-verify");
    }

    const capped = capForModel(output, cap, scratchPath);
    return {
      success: true,
      prose: capped.shown,
      scratchPath,
      structured: {
        success: true,
        summary: capped.shown,
        scratchPath,
        bytesTotal: capped.bytesTotal,
        bytesShown: capped.bytesShown,
        truncated: capped.truncated,
      },
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return failure(`read-only child failed: ${message}`, message);
  } finally {
    session?.dispose();
  }
}
