// The command/extension test harness (dev-only; excluded from the published tarball).
//
// Drives a REAL `pi` AgentSession with the perk extension bound, so later turns can verify the
// interior end-to-end instead of only as isolated pure functions. Everything here runs OFFLINE:
// no API key, no model turn, no network. The session lifecycle (session_start / session_tree /
// command invocation) is what exercises perk's interior.
//
// Design facts this harness relies on:
//   - binding (not creation) emits session_start -> we call session.bindExtensions(...)
//   - ctx.hasUI tracks uiContext presence       -> `headful` toggles it
//   - keyless getModel + never prompting        -> offline
//   - keep via session.reload()                 -> reload() re-emits session_start
//   - fork via a planted session .jsonl         -> plantSession()

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
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { getModel } from "@earendil-works/pi-ai/compat";
import {
  type AgentSession,
  createAgentSession,
  DefaultResourceLoader,
  type ExtensionUIContext,
  type SessionEntry,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import perk from "../index.ts";
import { type PlanRef, workflowDir, writePlanRef } from "../substrate/cache.ts";
import {
  type BranchEntry,
  branchOf,
  rebuildWorkflowState,
  type WorkflowState,
} from "../substrate/workflowState.ts";

/**
 * Pi's run-mode union. Mirrors `@earendil-works/pi-coding-agent`'s `ExtensionMode` (which the
 * package re-exports only from a deep path, not the root entry), so we restate it here.
 */
type ExtensionMode = "tui" | "rpc" | "json" | "print";

/** The `.perk-t3.json` sentinel the extension writes under PERK_SELFCHECK. */
export interface Sentinel {
  source: string;
  run_id: string | null;
  /** Workflow mode (read-only/read-write) — drives tool gating. */
  mode: string | null;
  /** Pi run mode (tui/rpc/json/print) — recorded from `ctx.mode`. */
  run_mode: string | null;
  predecessor: string | null;
  pi_session_id: string | null;
  active_plan_ref: PlanRef | null;
}

export interface PerkSession {
  readonly session: AgentSession;
  /** Captured `ui.notify` calls (headful only). */
  readonly notifies: readonly string[];
  /** Captured `ui.notify` calls with severity (headful only). */
  readonly notifyEvents: readonly { message: string; severity?: string }[];
  /** Captured `ui.setStatus(slot, value)` calls (headful only). */
  readonly statuses: readonly { slot: string; value: string | undefined }[];
  /**
   * Captured `ui.setWidget(slot, value)` calls (headful only). Factory widgets are rendered
   * through a passthrough fake theme at width 80; `placement` is captured from the options arg.
   */
  readonly widgets: readonly { slot: string; value: string[] | undefined; placement?: string }[];
  /** Captured `ui.setWorkingIndicator(...)` args (headful only) — tests assert it stays empty. */
  readonly workingIndicators: readonly unknown[];
  /** The last captured `ui.setFooter` factory, or null if none was set. */
  footerFactory(): unknown | null;
  /**
   * Invoke the captured footer factory with a fake tui/theme/footerData and render at `width`
   * (default 80). Throws when no factory was captured.
   */
  renderFooter(
    width?: number,
    data?: { branch?: string | null; statuses?: Map<string, string> },
  ): string[];
  /** The PERK_SELFCHECK sentinel, or null if not yet written. */
  sentinel(): Sentinel | null;
  /** Rebuild `perk:workflow-state` from the live session branch. */
  workflowState(): WorkflowState;
  /** Entry ids on the current branch (excludes the session header). */
  entryIds(): string[];
  /** Registered extension command invocation names (e.g. "perk-selfcheck"). */
  registeredCommands(): string[];
  /**
   * A registered tool's declared definition surface (name/description/parameters/guidelines) —
   * the model-facing contract the door authors independently of its strict decode; null when the
   * tool is not registered. For schema pins (enum/maxItems) that would otherwise drift silently.
   */
  registeredTool(name: string): {
    name: string;
    description: string;
    parameters: unknown;
    promptGuidelines?: string[];
  } | null;
  /** Fire `session_tree` by navigating to an entry. */
  navigateTo(entryId: string): Promise<void>;
  /** Invoke an extension command headlessly (no model turn). */
  invokeCommand(name: string, args?: string): Promise<void>;
  /**
   * Invoke a registered command's handler directly with a synthesized command context whose
   * `newSession` is recorded (it does NOT create a real session). Returns the captured handoff:
   * the `newSession` options seen + any messages the `withSession` callback seeded.
   */
  runCommandHandler(
    name: string,
    args?: string,
  ): Promise<{ newSessionCalls: { parentSession?: string }[]; seeded: string[] }>;
  /** Invoke a registered tool's `execute` directly with a synthesized ctx. */
  invokeTool(
    name: string,
    params: unknown,
  ): Promise<{ content: { text?: string }[]; details: unknown; terminate?: boolean }>;
  /** Fire a `tool_call` event through the runner; returns the gating verdict (block/reason). */
  emitToolCall(
    toolName: string,
    input: Record<string, unknown>,
  ): Promise<{ block?: boolean; reason?: string } | undefined>;
  /** Fire `before_agent_start` (optionally with the submitting turn's prompt); returns the
   * injected custom messages (customType + content). */
  emitBeforeAgentStart(prompt?: string): Promise<{ customType?: string; content?: unknown }[]>;
  /** Run messages through the `context` filter chain; returns the surviving messages. */
  emitContext(messages: Record<string, unknown>[]): Promise<Record<string, unknown>[]>;
  /** Fire a lifecycle event (session_before_fork / session_before_switch / session_compact) and return its result. */
  emitLifecycle(
    event:
      | { type: "session_before_fork"; entryId: string; position: "before" | "at" }
      | { type: "session_before_switch"; reason: "new" | "resume"; targetSessionFile?: string }
      | { type: "session_compact" },
  ): Promise<{ cancel?: boolean } | undefined>;
  /** Set a registered CLI flag value (simulates `pi --<name>`); take effect on the next reload. */
  setFlag(name: string, value: boolean | string): void;
  /** Re-emit `session_start` (reason "reload"); optional env overrides applied first. */
  reload(env?: Record<string, string | undefined>): Promise<void>;
  /** Dispose the session and restore process.env. */
  dispose(): void;
}

const TICK_MS = 50;
const tick = () => new Promise((resolve) => setTimeout(resolve, TICK_MS));

/**
 * Create a temp cwd with a minimal `.perk/workflow/` scaffold (+ optional handoff). `consumed` +
 * `piSessionId` plant an already-claimed run so lifecycle tests can exercise the env-child
 * adopt arm.
 */
export function scaffoldRepo(
  opts: {
    handoff?: {
      runId: string;
      mode?: string;
      stage?: string;
      consumed?: boolean;
      piSessionId?: string;
    };
  } = {},
): string {
  const cwd = mkdtempSync(join(tmpdir(), "perk-cwd-"));
  mkdirSync(join(workflowDir(cwd), "handoff"), { recursive: true });
  if (opts.handoff) {
    const { runId, mode, stage, consumed, piSessionId } = opts.handoff;
    writeFileSync(
      join(workflowDir(cwd), "handoff", `${runId}.json`),
      `${JSON.stringify(
        { run_id: runId, consumed: consumed ?? false, mode, stage, pi_session_id: piSessionId },
        null,
        2,
      )}\n`,
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
  opts: { fileName?: string; assistantText?: string; planMode?: boolean } = {},
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
  const lastId = (): string | null => {
    const last = entries.at(-1);
    return last ? (last.id as string) : null;
  };
  // Optional borrowed pi-plan state entry (for the /plan-save fail-fast guard).
  if (opts.planMode !== undefined) {
    entries.push({
      type: "custom",
      id: "pm0",
      parentId: lastId(),
      timestamp: now,
      customType: "plan-mode-state",
      data: { enabled: opts.planMode },
    });
  }
  // Optional trailing assistant message (for /plan-save's extractPlanMarkdown).
  if (opts.assistantText !== undefined) {
    entries.push({
      type: "message",
      id: "m0",
      parentId: lastId(),
      timestamp: now,
      message: { role: "assistant", content: [{ type: "text", text: opts.assistantText }] },
    });
  }
  writeFileSync(path, `${[header, ...entries].map((e) => JSON.stringify(e)).join("\n")}\n`, "utf8");
  return path;
}

/**
 * Plant a session `.jsonl` from a flat list of entry specs (custom entries + assistant messages,
 * in order). Lets tests build interleaved sequences (e.g. a `perk:workflow-state` seed followed
 * by assistant turns). Returns the file path; basename is the session id.
 */
export function plantRawSession(
  cwd: string,
  specs: ({ custom: { type: string; data: unknown } } | { assistant: string })[],
  opts: { fileName?: string } = {},
): string {
  const fileName = opts.fileName ?? "planted-raw.jsonl";
  const path = join(cwd, fileName);
  const now = new Date().toISOString();
  const header = { type: "session", version: 3, id: "planted", timestamp: now, cwd };
  const entries: Record<string, unknown>[] = specs.map((spec, i) => {
    const base = { id: `e${i}`, parentId: i === 0 ? null : `e${i - 1}`, timestamp: now };
    if ("custom" in spec) {
      return { ...base, type: "custom", customType: spec.custom.type, data: spec.custom.data };
    }
    return {
      ...base,
      type: "message",
      message: { role: "assistant", content: [{ type: "text", text: spec.assistant }] },
    };
  });
  writeFileSync(path, `${[header, ...entries].map((e) => JSON.stringify(e)).join("\n")}\n`, "utf8");
  return path;
}

/**
 * `git init` a scaffold into a real repo with one seed commit; when `dirty`, leave an uncommitted
 * file so the dirty-repo lifecycle gate fires. Test-only (uses execFileSync).
 */
export function gitInit(cwd: string, opts: { dirty: boolean }): void {
  const g = (...args: string[]) => execFileSync("git", args, { cwd, stdio: "ignore" });
  g("init", "-q");
  g("config", "user.email", "t@example.com");
  g("config", "user.name", "perk tests");
  // Mirror a real perk repo: the workflow cache is gitignored, and pi session files live in the
  // agent dir (not the repo tree) — the harness plants a `.jsonl` in cwd for convenience, so ignore
  // it too. Net: only real source edits (e.g. uncommitted.txt) dirty the tree.
  writeFileSync(join(cwd, ".gitignore"), "/.perk/workflow/\n*.jsonl\nfake-perk.sh\n", "utf8");
  writeFileSync(join(cwd, "seed.txt"), "seed\n", "utf8");
  g("add", "-A");
  g("commit", "-qm", "seed");
  if (opts.dirty) writeFileSync(join(cwd, "uncommitted.txt"), "dirty\n", "utf8");
}

/**
 * Write an executable fake `perk` (for PERK_BIN): prints `stdout` and exits `code`. Lets the
 * warm-door tests exercise the real `pi.exec` delegation path fully offline. When `argvFile` is
 * given, the fake first writes its argv (one arg per line) to that path so a test can assert the
 * exact delegated command (e.g. `--pr` present, `--status` absent).
 */
export function fakePerk(
  cwd: string,
  opts: { stdout: string; code?: number; argvFile?: string },
): string {
  const path = join(cwd, "fake-perk.sh");
  const body = opts.stdout.replace(/'/g, "'\\''");
  const capture = opts.argvFile
    ? `printf '%s\\n' "$@" > '${opts.argvFile.replace(/'/g, "'\\''")}'\n`
    : "";
  writeFileSync(
    path,
    `#!/usr/bin/env bash\n${capture}printf '%s' '${body}'\nexit ${opts.code ?? 0}\n`,
    "utf8",
  );
  chmodSync(path, 0o755);
  return path;
}

/**
 * Scaffold a temp worktree that loads the REAL `@mgiles/perk` extension end-to-end. The
 * worktree's `.pi/settings.json` references the live checkout by ABSOLUTE path (offline, no
 * install) — the PRODUCTION load path: the worker's disk-layered settings resolve this project-tier
 * `packages` list, so pi reads `<repoRoot>/package.json` `pi.extensions` and binds the real
 * extension. `packages` overrides the list (e.g. `[]` scaffolds a worktree whose session registers
 * zero perk tools — the `no_extension_tools` preflight scenario). Plants the handoff + plan-ref +
 * PERK_RUN_ID claim path, and `git init`s so the resource loader's ancestor `.agents/skills` walk
 * stops here (never leaking the dev machine's ancestor dirs).
 */
export function scaffoldWorkerWorktree(opts: {
  runId: string;
  stage: "implement" | "address";
  planRef?: PlanRef;
  /** Settings `packages` list; default `[repoRoot]` (the live checkout by absolute path). */
  packages?: string[];
}): string {
  const cwd = mkdtempSync(join(tmpdir(), "perk-worker-wt-"));
  // extension/testing/harness.ts -> repo root is two levels up.
  const repoRoot = resolve(import.meta.dirname, "..", "..");
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(
    join(cwd, ".pi", "settings.json"),
    `${JSON.stringify({ packages: opts.packages ?? [repoRoot] }, null, 2)}\n`,
    "utf8",
  );
  mkdirSync(join(workflowDir(cwd), "handoff"), { recursive: true });
  writeFileSync(
    join(workflowDir(cwd), "handoff", `${opts.runId}.json`),
    `${JSON.stringify({ run_id: opts.runId, consumed: false, mode: "read-write", stage: opts.stage }, null, 2)}\n`,
    "utf8",
  );
  writePlanRef(
    cwd,
    opts.planRef ?? {
      provider: "github",
      pr_id: "148",
      url: "https://github.com/mattgiles/perk/issues/148",
      labels: [],
      objective_id: "137",
    },
  );
  execFileSync("git", ["init", "-q"], { cwd, stdio: "ignore" });
  return cwd;
}

/**
 * Write an executable fake `perk` that ROUTES on the subcommand: the first two non-flag argv
 * tokens (`"$1 $2"` for grouped commands like `pr submit`, falling back to `"$1"` when `$2` is
 * absent or a `-`-prefixed flag). A matched route prints its JSON and exits `code` (default 0);
 * an unmatched subcommand errors loudly (exit 2). Returns the path (for PERK_BIN). The
 * GitHub-free seam both terminating tools shell out through (`pr submit`, `pr resolve-threads`).
 * Leaves the simpler `fakePerk` untouched.
 */
export function fakePerkRouter(
  cwd: string,
  routes: Record<string, { json: unknown; code?: number }>,
): string {
  const path = join(cwd, "fake-perk.sh");
  const branches = Object.entries(routes)
    .map(([sub, { json, code }]) => {
      const body = JSON.stringify(json).replace(/'/g, "'\\''");
      return `  "${sub}") printf '%s' '${body}'; exit ${code ?? 0} ;;`;
    })
    .join("\n");
  writeFileSync(
    path,
    `#!/usr/bin/env bash\nkey="$1"\nif [ -n "$2" ] && [ "\${2#-}" = "$2" ]; then key="$1 $2"; fi\ncase "$key" in\n${branches}\n  *) >&2 echo "unexpected subcommand: $key"; exit 2 ;;\nesac\n`,
    "utf8",
  );
  chmodSync(path, 0o755);
  return path;
}

/**
 * Register a faux pi-ai provider in the SAME `@earendil-works/pi-ai` module instance that
 * `pi-coding-agent`'s session runtime streams through. pi-coding-agent ships its own bundled copy of
 * pi-ai (separate `node_modules/.../pi-coding-agent/node_modules/@earendil-works/pi-ai`), so a faux
 * provider registered via the TOP-LEVEL pi-ai import lands in a DIFFERENT api-registry than the one
 * the runtime resolves — yielding "No API provider registered for api: faux…". This helper resolves
 * pi-ai *as pi-coding-agent sees it* (nested copy when present, else the deduped top-level) and
 * registers there. Async (dynamic import): callers `await fauxModelRegistration()`.
 */
export async function fauxModelRegistration(): Promise<{
  getModel(): unknown;
  setResponses(responses: unknown[]): void;
  unregister(): void;
}> {
  const pcaIndex = fileURLToPath(import.meta.resolve("@earendil-works/pi-coding-agent"));
  // pcaIndex is <…>/pi-coding-agent/dist/index.js → the package root is one level up from dist/.
  const pcaRoot = resolve(dirname(pcaIndex), "..");
  // `registerFauxProvider` lives on the /compat entrypoint from pi-ai 0.80 (dist/compat.js —
  // same module instance / same api-registry as that copy's core entry).
  const nested = join(pcaRoot, "node_modules", "@earendil-works", "pi-ai", "dist", "compat.js");
  const piAi = existsSync(nested)
    ? ((await import(pathToFileURL(nested).href)) as typeof import("@earendil-works/pi-ai/compat"))
    : await import("@earendil-works/pi-ai/compat");
  return piAi.registerFauxProvider() as unknown as {
    getModel(): unknown;
    setResponses(responses: unknown[]): void;
    unregister(): void;
  };
}

/** A widget component factory as the harness sees it (pi's `setWidget` factory form). */
type WidgetFactory = (
  tui: unknown,
  theme: { fg(color: string, text: string): string },
) => { render(width: number): string[] };

function headfulUIContext(
  notifies: string[],
  statuses: { slot: string; value: string | undefined }[] = [],
  widgets: { slot: string; value: string[] | undefined; placement?: string }[] = [],
  notifyEvents: { message: string; severity?: string }[] = [],
  footers: unknown[] = [],
  workingIndicators: unknown[] = [],
): ExtensionUIContext {
  // Minimal context: records notify (+ severity) + setStatus/setWidget so tests can assert UI.
  // Factory widgets are invoked with a passthrough fake theme and rendered at width 80, so the
  // recorded `value` is always a string[] (existing asserts keep working). setFooter captures the
  // factory (rendered on demand via PerkSession.renderFooter); setWorkingIndicator records its
  // args so tests can assert it is NEVER called (D5 rescinded).
  const fakeTheme = { fg: (_color: string, text: string) => text };
  return {
    notify: (message: string, severity?: string) => {
      notifies.push(message);
      notifyEvents.push({ message, severity });
    },
    setStatus: (slot: string, value: string | undefined) => {
      statuses.push({ slot, value });
    },
    setWidget: (
      slot: string,
      value: string[] | WidgetFactory | undefined,
      options?: { placement?: string },
    ) => {
      const rendered = typeof value === "function" ? value(undefined, fakeTheme).render(80) : value;
      widgets.push({ slot, value: rendered, placement: options?.placement });
    },
    setFooter: (factory: unknown) => {
      footers.push(factory);
    },
    setWorkingIndicator: (options?: unknown) => {
      workingIndicators.push(options);
    },
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
  /** Pi run mode forwarded to `bindExtensions` (drives `ctx.mode`). Defaults to Pi's "print". */
  mode?: ExtensionMode;
  /** Session model override (e.g. a faux-provider model); defaults to the keyless anthropic model. */
  model?: unknown;
  /**
   * Extra extension factories bound AFTER perk (e.g. a fake plannotator registering its
   * `plannotator-review` command so presence probes see it). Offline like everything here.
   */
  extraExtensions?: ((pi: Parameters<typeof perk>[0]) => void | Promise<void>)[];
}): Promise<PerkSession> {
  const { cwd, headful = true } = opts;
  const agentDir = mkdtempSync(join(tmpdir(), "perk-agent-"));
  const savedEnv = new Map<string, string | undefined>();
  // Sentinels on by default so the lifecycle is observable; PERK_NO_LLM on by default so harness-
  // bound sessions stay fully offline (no title-generation model call) even on a dev machine that
  // has provider API keys in its env. PERK_CLIPBOARD_CMD/PERK_TERMINAL_LAUNCH default to ""
  // (disabled) so no harness-driven suite clobbers the dev machine's clipboard or spawns a
  // terminal window. Caller env is spread last, so all remain overridable per-test.
  applyEnv(
    {
      PERK_SELFCHECK: "1",
      PERK_NO_LLM: "1",
      PERK_CLIPBOARD_CMD: "",
      PERK_TERMINAL_LAUNCH: "",
      ...(opts.env ?? {}),
    },
    savedEnv,
  );

  const notifies: string[] = [];
  const notifyEvents: { message: string; severity?: string }[] = [];
  const statuses: { slot: string; value: string | undefined }[] = [];
  const widgets: { slot: string; value: string[] | undefined; placement?: string }[] = [];
  const footers: unknown[] = [];
  const workingIndicators: unknown[] = [];
  const loader = new DefaultResourceLoader({
    cwd,
    agentDir,
    // Named inline factory: startup/extension-load-error surfaces then say `<inline:perk>`
    // instead of the positional `<inline:1>`.
    extensionFactories: [{ name: "perk", factory: perk }, ...(opts.extraExtensions ?? [])],
  });
  await loader.reload();
  const model =
    (opts.model as ReturnType<typeof getModel> | undefined) ??
    getModel("anthropic", "claude-sonnet-4-5") ??
    undefined;
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
    uiContext: headful
      ? headfulUIContext(notifies, statuses, widgets, notifyEvents, footers, workingIndicators)
      : undefined,
    // Forward the Pi run mode so `ctx.mode` (and the `run_mode` sentinel) is observable.
    mode: opts.mode,
    // Surface (don't swallow) extension-handler failures; a real bug also fails downstream asserts.
    onError: (err) => console.error(`perk harness: extension error in ${err.event}: ${err.error}`),
  });
  await tick();

  const branchEntries = (): BranchEntry[] => branchOf(session);

  return {
    session,
    notifies,
    notifyEvents,
    statuses,
    widgets,
    workingIndicators,
    footerFactory: () => footers.at(-1) ?? null,
    renderFooter(width = 80, data = {}) {
      const factory = footers.at(-1) as
        | ((
            tui: { requestRender(): void },
            theme: { fg(color: string, text: string): string },
            footerData: {
              getGitBranch(): string | null;
              getExtensionStatuses(): ReadonlyMap<string, string>;
              onBranchChange(callback: () => void): () => void;
            },
          ) => { render(width: number): string[] })
        | undefined;
      if (!factory) throw new Error("no footer factory captured");
      const fakeTheme = { fg: (_color: string, text: string) => text };
      const component = factory({ requestRender: () => {} }, fakeTheme, {
        getGitBranch: () => (data.branch === undefined ? "main" : data.branch),
        getExtensionStatuses: () => data.statuses ?? new Map<string, string>(),
        onBranchChange: () => () => {},
      });
      return component.render(width);
    },
    sentinel() {
      const path = join(workflowDir(cwd), ".perk-t3.json");
      if (!existsSync(path)) return null;
      return JSON.parse(readFileSync(path, "utf8")) as Sentinel;
    },
    workflowState: () => rebuildWorkflowState(branchEntries()),
    entryIds: () => session.sessionManager.getEntries().map((e: SessionEntry) => e.id),
    registeredCommands: () =>
      session.extensionRunner.getRegisteredCommands().map((c) => c.invocationName),
    registeredTool(name: string) {
      const def = session.extensionRunner.getToolDefinition(name);
      if (!def) return null;
      return {
        name: def.name,
        description: def.description,
        parameters: def.parameters as unknown,
        ...(def.promptGuidelines !== undefined ? { promptGuidelines: def.promptGuidelines } : {}),
      };
    },
    async navigateTo(entryId: string) {
      await session.navigateTree(entryId);
      await tick();
    },
    async invokeCommand(name: string, args?: string) {
      await session.prompt(args ? `/${name} ${args}` : `/${name}`);
      await tick();
    },
    async runCommandHandler(name: string, args = "") {
      const cmd = session.extensionRunner
        .getRegisteredCommands()
        .find((c) => c.invocationName === name);
      if (!cmd) throw new Error(`command not registered: ${name}`);
      const newSessionCalls: { parentSession?: string }[] = [];
      const seeded: string[] = [];
      const replaced = {
        async sendUserMessage(content: unknown) {
          seeded.push(typeof content === "string" ? content : JSON.stringify(content));
        },
        async sendMessage(message: { content?: unknown }) {
          seeded.push(
            typeof message.content === "string" ? message.content : JSON.stringify(message.content),
          );
        },
      };
      const ctx = {
        cwd,
        hasUI: headful,
        mode: (opts.mode ?? "print") as ExtensionMode,
        // Thread the session's capture arrays so severity-aware asserts (`notifyEvents`) see
        // handler-driven notifies too, not only bound-session ones.
        ui: headfulUIContext(notifies, statuses, widgets, notifyEvents),
        sessionManager: session.sessionManager,
        signal: undefined,
        isIdle: () => true,
        // Command contexts expose the live system-prompt construction options. The synthesized
        // stub forwards the real bound session's options so selfcheck-style probes work offline.
        getSystemPromptOptions: () =>
          (
            session as unknown as {
              getSystemPromptOptions?: () => unknown;
              _baseSystemPromptOptions?: unknown;
            }
          )._baseSystemPromptOptions ?? { cwd },
        async waitForIdle() {},
        async newSession(options?: {
          parentSession?: string;
          withSession?: (c: unknown) => Promise<void>;
        }) {
          newSessionCalls.push({ parentSession: options?.parentSession });
          if (options?.withSession) await options.withSession(replaced);
          return { cancelled: false };
        },
      } as unknown as Parameters<typeof cmd.handler>[1];
      await cmd.handler(args, ctx);
      await tick();
      return { newSessionCalls, seeded };
    },
    async invokeTool(name: string, params: unknown) {
      const tool = session.extensionRunner
        .getAllRegisteredTools()
        .find((t) => t.definition.name === name);
      if (!tool) throw new Error(`tool not registered: ${name}`);
      const ctx = {
        cwd,
        hasUI: headful,
        mode: (opts.mode ?? "print") as ExtensionMode,
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
    async emitToolCall(toolName, input) {
      const result = await session.extensionRunner.emitToolCall({
        type: "tool_call",
        toolCallId: `tc-${toolName}`,
        toolName,
        input,
      } as never);
      await tick();
      return result as { block?: boolean; reason?: string } | undefined;
    },
    async emitBeforeAgentStart(prompt?: string) {
      const runner = session.extensionRunner as unknown as {
        emitBeforeAgentStart: (
          prompt: string,
          images: undefined,
          systemPrompt: string,
          systemPromptOptions: unknown,
        ) => Promise<{ messages?: { customType?: string; content?: unknown }[] } | undefined>;
      };
      const result = await runner.emitBeforeAgentStart(prompt ?? "", undefined, "", {} as never);
      await tick();
      return result?.messages ?? [];
    },
    async emitContext(messages) {
      const runner = session.extensionRunner as unknown as {
        emitContext: (m: Record<string, unknown>[]) => Promise<Record<string, unknown>[]>;
      };
      const result = await runner.emitContext(messages as never);
      await tick();
      return result as Record<string, unknown>[];
    },
    async emitLifecycle(event) {
      const result = await session.extensionRunner.emit(event as never);
      await tick();
      return result as { cancel?: boolean } | undefined;
    },
    setFlag(name: string, value: boolean | string) {
      (
        session.extensionRunner as unknown as {
          setFlagValue: (n: string, v: boolean | string) => void;
        }
      ).setFlagValue(name, value);
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

/**
 * Spy on the live session's `sendUserMessage` (the delegate behind `pi.sendUserMessage`) — the
 * keyless offline session can't run an injected turn, so capture the injection instead.
 */
export function spyInjections(h: PerkSession): string[] {
  const injected: string[] = [];
  (h.session as unknown as { sendUserMessage: (c: unknown) => Promise<void> }).sendUserMessage =
    async (c) => {
      injected.push(typeof c === "string" ? c : JSON.stringify(c));
    };
  return injected;
}
