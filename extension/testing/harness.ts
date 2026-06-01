// P1.T1 — the command/extension test harness (dev-only; excluded from the published tarball).
//
// Drives a REAL `pi` AgentSession with the perk extension bound, so later turns can verify the
// interior end-to-end instead of only as isolated pure functions. Everything here runs OFFLINE:
// no API key, no model turn, no network. The session lifecycle (session_start / session_tree /
// command invocation) is what exercises perk's interior — see docs/planning/phase-1-turn-1.md.
//
// Spike findings that shape this file (turn-1 §3):
//   F1 binding (not creation) emits session_start -> we call session.bindExtensions(...)
//   F2 ctx.hasUI tracks uiContext presence       -> `headful` toggles it
//   F3 keyless getModel + never prompting        -> offline
//   F5 keep via session.reload()                 -> reload() re-emits session_start
//   F6 fork via a planted session .jsonl         -> plantSession()

import { execFileSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { getModel } from "@earendil-works/pi-ai";
import {
  type AgentSession,
  createAgentSession,
  DefaultResourceLoader,
  type ExtensionUIContext,
  type SessionEntry,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { type PlanRef, workflowDir } from "../cache.ts";
import perk from "../index.ts";
import { type BranchEntry, rebuildWorkflowState, type WorkflowState } from "../workflowState.ts";

/** The `.perk-t3.json` sentinel the extension writes under PERK_SELFCHECK. */
export interface Sentinel {
  source: string;
  run_id: string | null;
  mode: string | null;
  predecessor: string | null;
  pi_session_id: string | null;
  active_plan_ref: PlanRef | null;
}

export interface PerkSession {
  readonly session: AgentSession;
  /** Captured `ui.notify` calls (headful only). */
  readonly notifies: readonly string[];
  /** The PERK_SELFCHECK sentinel, or null if not yet written. */
  sentinel(): Sentinel | null;
  /** Rebuild `perk:workflow-state` from the live session branch. */
  workflowState(): WorkflowState;
  /** Entry ids on the current branch (excludes the session header). */
  entryIds(): string[];
  /** Registered extension command invocation names (e.g. "perk-selfcheck"). */
  registeredCommands(): string[];
  /** Fire `session_tree` by navigating to an entry. */
  navigateTo(entryId: string): Promise<void>;
  /** Invoke an extension command headlessly (no model turn). */
  invokeCommand(name: string): Promise<void>;
  /** Invoke a registered tool's `execute` directly with a synthesized ctx (turn-3 §3.5 S3). */
  invokeTool(
    name: string,
    params: unknown,
  ): Promise<{ content: { text?: string }[]; details: unknown; terminate?: boolean }>;
  /** Fire a lifecycle event (session_before_fork / session_before_switch) and return its result. */
  emitLifecycle(
    event:
      | { type: "session_before_fork"; entryId: string; position: "before" | "at" }
      | { type: "session_before_switch"; reason: "new" | "resume"; targetSessionFile?: string },
  ): Promise<{ cancel?: boolean } | undefined>;
  /** Re-emit `session_start` (reason "reload"); optional env overrides applied first. */
  reload(env?: Record<string, string | undefined>): Promise<void>;
  /** Dispose the session and restore process.env. */
  dispose(): void;
}

const TICK_MS = 50;
const tick = () => new Promise((resolve) => setTimeout(resolve, TICK_MS));

/** Create a temp cwd with a minimal `.pi/workflow/` scaffold (+ optional handoff). */
export function scaffoldRepo(opts: { handoff?: { runId: string; mode?: string } } = {}): string {
  const cwd = mkdtempSync(join(tmpdir(), "perk-cwd-"));
  mkdirSync(join(workflowDir(cwd), "handoff"), { recursive: true });
  if (opts.handoff) {
    const { runId, mode } = opts.handoff;
    writeFileSync(
      join(workflowDir(cwd), "handoff", `${runId}.json`),
      `${JSON.stringify({ run_id: runId, consumed: false, mode }, null, 2)}\n`,
      "utf8",
    );
  }
  return cwd;
}

/**
 * Plant a session `.jsonl` carrying `perk:workflow-state` entries and return its path. The file
 * basename is the session id, so callers control claim/keep/fork: pass `piSessionId` ≠ the basename
 * to force a fork, or equal to it (or omit) for keep.
 */
export function plantSession(
  cwd: string,
  states: Partial<WorkflowState>[],
  opts: { fileName?: string; assistantText?: string } = {},
): string {
  const fileName = opts.fileName ?? "planted-parent.jsonl";
  const path = join(cwd, fileName);
  const now = new Date().toISOString();
  const header = { type: "session", version: 3, id: "planted", timestamp: now, cwd };
  const entries: Record<string, unknown>[] = states.map((data, i) => ({
    type: "custom",
    id: `c${i}`,
    parentId: i === 0 ? null : `c${i - 1}`,
    timestamp: now,
    customType: "perk:workflow-state",
    data,
  }));
  // Optional trailing assistant message (for /plan-save's extractPlanMarkdown).
  if (opts.assistantText !== undefined) {
    entries.push({
      type: "message",
      id: "m0",
      parentId: entries.length ? `c${entries.length - 1}` : null,
      timestamp: now,
      message: { role: "assistant", content: [{ type: "text", text: opts.assistantText }] },
    });
  }
  writeFileSync(path, `${[header, ...entries].map((e) => JSON.stringify(e)).join("\n")}\n`, "utf8");
  return path;
}

/**
 * `git init` a scaffold into a real repo with one seed commit; when `dirty`, leave an uncommitted
 * file so the dirty-repo lifecycle gate (turn-4b) fires. Test-only (uses execFileSync).
 */
export function gitInit(cwd: string, opts: { dirty: boolean }): void {
  const g = (...args: string[]) => execFileSync("git", args, { cwd, stdio: "ignore" });
  g("init", "-q");
  g("config", "user.email", "t@example.com");
  g("config", "user.name", "perk tests");
  // Mirror a real perk repo: the workflow cache is gitignored, and pi session files live in the
  // agent dir (not the repo tree) — the harness plants a `.jsonl` in cwd for convenience, so ignore
  // it too. Net: only real source edits (e.g. uncommitted.txt) dirty the tree.
  writeFileSync(join(cwd, ".gitignore"), "/.pi/workflow/\n*.jsonl\nfake-perk.sh\n", "utf8");
  writeFileSync(join(cwd, "seed.txt"), "seed\n", "utf8");
  g("add", "-A");
  g("commit", "-qm", "seed");
  if (opts.dirty) writeFileSync(join(cwd, "uncommitted.txt"), "dirty\n", "utf8");
}

/**
 * Write an executable fake `perk` (for PERK_BIN): on `plan-save`, prints `stdout` and exits
 * `code`. Lets the warm-door tests exercise the real `pi.exec` delegation path fully offline.
 */
export function fakePerk(cwd: string, opts: { stdout: string; code?: number }): string {
  const path = join(cwd, "fake-perk.sh");
  const body = opts.stdout.replace(/'/g, "'\\''");
  writeFileSync(
    path,
    `#!/usr/bin/env bash\nprintf '%s' '${body}'\nexit ${opts.code ?? 0}\n`,
    "utf8",
  );
  chmodSync(path, 0o755);
  return path;
}

function headfulUIContext(notifies: string[]): ExtensionUIContext {
  // Minimal context: the extension only calls notify; the runtime touches setStatus/setWidget.
  return {
    notify: (message: string) => {
      notifies.push(message);
    },
    setStatus: () => {},
    setWidget: () => {},
  } as unknown as ExtensionUIContext;
}

function applyEnv(
  overrides: Record<string, string | undefined>,
  saved: Map<string, string | undefined>,
): void {
  for (const [key, value] of Object.entries(overrides)) {
    if (!saved.has(key)) saved.set(key, process.env[key]);
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
}

/**
 * Create an AgentSession with ONLY the perk extension, deterministic in-memory settings, and a
 * keyless model that is never prompted; then bind extensions (which emits session_start).
 */
export async function loadPerkSession(opts: {
  cwd: string;
  env?: Record<string, string | undefined>;
  sessionManager?: SessionManager;
  headful?: boolean;
}): Promise<PerkSession> {
  const { cwd, headful = true } = opts;
  const agentDir = mkdtempSync(join(tmpdir(), "perk-agent-"));
  const savedEnv = new Map<string, string | undefined>();
  // Sentinels on by default so the lifecycle is observable; caller env may override.
  applyEnv({ PERK_SELFCHECK: "1", ...(opts.env ?? {}) }, savedEnv);

  const notifies: string[] = [];
  const loader = new DefaultResourceLoader({ cwd, agentDir, extensionFactories: [perk] });
  await loader.reload();
  const model = getModel("anthropic", "claude-sonnet-4-5") ?? undefined;
  const { session } = await createAgentSession({
    cwd,
    agentDir,
    model,
    resourceLoader: loader,
    sessionManager: opts.sessionManager ?? SessionManager.inMemory(cwd),
    settingsManager: SettingsManager.inMemory({
      compaction: { enabled: false },
      retry: { enabled: false },
    }),
  });

  await session.bindExtensions({
    uiContext: headful ? headfulUIContext(notifies) : undefined,
    // Surface (don't swallow) extension-handler failures; a real bug also fails downstream asserts.
    onError: (err) => console.error(`perk harness: extension error in ${err.event}: ${err.error}`),
  });
  await tick();

  const branchEntries = (): BranchEntry[] =>
    session.sessionManager.getBranch() as unknown as BranchEntry[];

  return {
    session,
    notifies,
    sentinel() {
      const path = join(workflowDir(cwd), ".perk-t3.json");
      if (!existsSync(path)) return null;
      return JSON.parse(readFileSync(path, "utf8")) as Sentinel;
    },
    workflowState: () => rebuildWorkflowState(branchEntries()),
    entryIds: () => session.sessionManager.getEntries().map((e: SessionEntry) => e.id),
    registeredCommands: () =>
      session.extensionRunner.getRegisteredCommands().map((c) => c.invocationName),
    async navigateTo(entryId: string) {
      await session.navigateTree(entryId);
      await tick();
    },
    async invokeCommand(name: string) {
      await session.prompt(`/${name}`);
      await tick();
    },
    async invokeTool(name: string, params: unknown) {
      const tool = session.extensionRunner
        .getAllRegisteredTools()
        .find((t) => t.definition.name === name);
      if (!tool) throw new Error(`tool not registered: ${name}`);
      const ctx = {
        cwd,
        hasUI: headful,
        ui: headfulUIContext(notifies),
        sessionManager: session.sessionManager,
        signal: undefined,
        isIdle: () => true,
      } as unknown as Parameters<typeof tool.definition.execute>[4];
      const result = await tool.definition.execute(
        `tc-${name}`,
        params as never,
        undefined,
        undefined,
        ctx,
      );
      await tick();
      return result as { content: { text?: string }[]; details: unknown; terminate?: boolean };
    },
    async emitLifecycle(event) {
      const result = await session.extensionRunner.emit(event as never);
      await tick();
      return result as { cancel?: boolean } | undefined;
    },
    async reload(env?: Record<string, string | undefined>) {
      if (env) applyEnv(env, savedEnv);
      await session.reload();
      await tick();
    },
    dispose() {
      for (const [key, value] of savedEnv) {
        if (value === undefined) delete process.env[key];
        else process.env[key] = value;
      }
      session.dispose();
    },
  };
}
