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

import assert from "node:assert/strict";
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
import type { TestContext } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  fauxAssistantMessage,
  fauxText,
  fauxToolCall,
  getCurrentSystemPrompt,
  getCurrentTools,
} from "@earendil-works/pi-ai";
import { getModel } from "@earendil-works/pi-ai/compat";
import {
  AgentSession,
  createAgentSession,
  createToolSearchExtension,
  DefaultResourceLoader,
  type ExtensionAPI,
  type ExtensionUIContext,
  type InlineExtension,
  ModelRuntime,
  type SessionEntry,
  SessionManager,
  SettingsManager,
  VERSION,
} from "@earendil-works/pi-coding-agent";
import perk from "../index.ts";
import { type PlanRef, workflowDir, writePlanRef } from "../substrate/cache.ts";
import type { ToolGating } from "../substrate/toolGating.ts";
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
  /** How many `ui.setFooter` installs were captured (pi ≥ 0.84 disposes each replaced one). */
  footerInstallCount(): number;
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
   * Append a custom entry, then render that real persisted entry through the live runner's
   * registered entry renderer. `undefined` means the custom type has no renderer.
   */
  renderAppendedEntry(customType: string, data: unknown, width?: number): string[] | undefined;
  /**
   * A registered tool's declared definition surface (name/description/parameters/guidelines) —
   * the model-facing contract the door authors independently of its strict decode; null when the
   * tool is not registered. For schema pins (enum/maxItems) that would otherwise drift silently.
   */
  registeredTool(name: string): {
    name: string;
    label: string;
    description: string;
    parameters: unknown;
    promptSnippet?: string;
    promptGuidelines?: string[];
    executionMode?: string;
    /** Present only when the definition declares one (a perk `kind: query` tool). */
    outputSchema?: unknown;
  } | null;
  /**
   * A registered tool's `getAllTools()` record — Pi's view of its derived `exposure` and
   * `annotations`; null when the tool is not registered.
   */
  toolInfo(name: string): { name: string; exposure: string; annotations?: unknown } | null;
  /** A registered command's declared surface (invocation name + description) — the byte pin twin. */
  registeredCommand(name: string): { name: string; description?: string } | null;
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
  /** Invoke a registered tool's `execute` directly with a synthesized ctx. `opts.onUpdate`
   * captures streamed partial results (pi's `onUpdate` channel); `opts.ui` overlays scripted
   * dialog answers (select/input/editor) on the recording UI — the recording surfaces stay;
   * `opts.signal` rides the execute callback's AbortSignal slot and `opts.ctxSignal` lands on
   * `ctx.signal` (cancellation-threading pins for both sourcing conventions). */
  invokeTool(
    name: string,
    params: unknown,
    opts?: {
      onUpdate?: (partial: { content: { text?: string }[]; details: unknown }) => void;
      ui?: Record<string, unknown>;
      signal?: AbortSignal;
      ctxSignal?: AbortSignal;
    },
  ): Promise<{
    content: { text?: string }[];
    details: unknown;
    terminate?: boolean;
    structuredContent?: unknown;
    isError?: boolean;
  }>;
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
  /**
   * Re-emit `session_start` on the SAME extension runner — without re-activating the extension
   * factory (unlike `reload()`, which re-runs the factory and so resets module-level state).
   * Mirrors the payload shape `bindExtensions` emits. Discriminates once-only-per-activation
   * install guards from install-per-session_start behavior.
   */
  emitSessionStart(): Promise<void>;
  /** Fire a lifecycle event (session_before_fork / session_before_switch / session_compact) and return its result. */
  emitLifecycle(
    event:
      | { type: "session_before_fork"; entryId: string; position: "before" | "at" }
      | { type: "session_before_switch"; reason: "new" | "resume"; targetSessionFile?: string }
      | { type: "session_compact" }
      | { type: "session_tree"; newLeafId: string | null; oldLeafId: string | null },
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
      /** Extra handoff keys (the cold doors' `handoff_extra`, e.g. objective_id/node_id). */
      extra?: Record<string, unknown>;
    };
  } = {},
): string {
  const cwd = mkdtempSync(join(tmpdir(), "perk-cwd-"));
  mkdirSync(join(workflowDir(cwd), "handoff"), { recursive: true });
  if (opts.handoff) {
    const { runId, mode, stage, consumed, piSessionId, extra } = opts.handoff;
    writeFileSync(
      join(workflowDir(cwd), "handoff", `${runId}.json`),
      `${JSON.stringify(
        {
          run_id: runId,
          consumed: consumed ?? false,
          mode,
          stage,
          pi_session_id: piSessionId,
          ...(extra ?? {}),
        },
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

/** One planted raw entry: state (`custom`), a hidden injection (`customMessage`), or a turn. */
export type RawEntrySpec =
  | { custom: { type: string; data: unknown } }
  | { customMessage: { type: string; content: string } }
  | { user: string }
  | { assistant: string };

/**
 * Plant a session `.jsonl` from a flat list of entry specs (custom state entries, hidden
 * `custom_message` injections, user prompts, assistant messages — in order). Lets tests build
 * interleaved sequences (e.g. a `perk:workflow-state` seed followed by a cold user prompt).
 * Returns the file path; basename is the session id.
 */
export function plantRawSession(
  cwd: string,
  specs: RawEntrySpec[],
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
    if ("customMessage" in spec) {
      return {
        ...base,
        type: "custom_message",
        customType: spec.customMessage.type,
        content: spec.customMessage.content,
        display: false,
      };
    }
    if ("user" in spec) {
      return {
        ...base,
        type: "message",
        message: { role: "user", content: spec.user, timestamp: Date.parse(now) },
      };
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
 * stops here (never leaking the dev machine's ancestor dirs). `extraSettings` is shallow-merged
 * into the written settings (e.g. `defaultProvider`/`defaultModel`).
 */
export function scaffoldWorkerWorktree(opts: {
  runId: string;
  stage: "implement" | "address";
  planRef?: PlanRef;
  /** Settings `packages` list; default `[repoRoot]` (the live checkout by absolute path). */
  packages?: string[];
  /** Settings `defaultTools` (Pi's startup active-set preference); omitted when unset. */
  defaultTools?: string[];
  /** Extra project settings, shallow-merged over the defaults above. */
  extraSettings?: Record<string, unknown>;
}): string {
  const cwd = mkdtempSync(join(tmpdir(), "perk-worker-wt-"));
  // extension/testing/harness.ts -> repo root is two levels up.
  const repoRoot = resolve(import.meta.dirname, "..", "..");
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  const settings = {
    packages: opts.packages ?? [repoRoot],
    ...(opts.defaultTools !== undefined ? { defaultTools: opts.defaultTools } : {}),
    ...opts.extraSettings,
  };
  writeFileSync(
    join(cwd, ".pi", "settings.json"),
    `${JSON.stringify(settings, null, 2)}\n`,
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
  opts: { argvFile?: string; fullArgvFile?: string } = {},
): string {
  const path = join(cwd, "fake-perk.sh");
  const branches = Object.entries(routes)
    .map(([sub, { json, code }]) => {
      const body = JSON.stringify(json).replace(/'/g, "'\\''");
      return `  "${sub}") printf '%s' '${body}'; exit ${code ?? 0} ;;`;
    })
    .join("\n");
  // `argvFile` records one routing key per invocation (subcommand-order pins); `fullArgvFile`
  // records the COMPLETE argv, tab-separated, one invocation per line (wire/channel pins, e.g.
  // a staged stdin flag + its temp-file path).
  const capture =
    (opts.argvFile ? `printf '%s\\n' "$key" >> '${opts.argvFile.replace(/'/g, "'\\''")}'\n` : "") +
    (opts.fullArgvFile
      ? `printf '%s\\t' "$@" >> '${opts.fullArgvFile.replace(/'/g, "'\\''")}'\nprintf '\\n' >> '${opts.fullArgvFile.replace(/'/g, "'\\''")}'\n`
      : "");
  writeFileSync(
    path,
    `#!/usr/bin/env bash\nkey="$1"\nif [ -n "$2" ] && [ "\${2#-}" = "$2" ]; then key="$1 $2"; fi\n${capture}case "$key" in\n${branches}\n  *) >&2 echo "unexpected subcommand: $key"; exit 2 ;;\nesac\n`,
    "utf8",
  );
  chmodSync(path, 0o755);
  return path;
}

/**
 * Build a hermetic pi 0.84 `ModelRuntime` carrying a faux pi-ai provider as a NATIVE provider
 * registration. The session runtime streams through `ModelRuntime.prepareRequest` → the
 * provider's own stream closures (no compat api-registry lookup), so the provider object is
 * self-contained — but the faux core is still built from pi-ai *as pi-coding-agent sees it*
 * (the nested `node_modules/.../pi-coding-agent/node_modules/@earendil-works/pi-ai` copy when
 * present, else the deduped top-level) so stream/message shapes come from the same module
 * instance the runtime consumes (the per-instance-registry trap —
 * docs/learned/pi/headless-session-drive.md). Hermetic: an in-memory credential store, no
 * models.json read (`modelsPath: null`), no create-time refresh. `contextWindow` replaces the faux
 * default model's window (same id) — a small window lets a real prompt turn cross Pi's compaction
 * threshold offline.
 */
export async function fauxModelRuntime(options: { contextWindow?: number } = {}): Promise<{
  modelRuntime: ModelRuntime;
  getModel(): unknown;
  setResponses(responses: unknown[]): void;
  /** Provider stream calls so far — counted even for a request whose signal was already aborted. */
  callCount(): number;
}> {
  const piAi = await loadSdkPiAi();
  // `faux-1` is the faux provider's default model id; only the window is overridden.
  const faux = piAi.fauxProvider(
    options.contextWindow !== undefined
      ? { models: [{ id: "faux-1", contextWindow: options.contextWindow }] }
      : {},
  );
  const modelRuntime = await ModelRuntime.create({
    credentials: new piAi.InMemoryCredentialStore(),
    modelsPath: null,
    refreshOnCreate: false,
  });
  modelRuntime.registerNativeProvider(
    faux.provider as Parameters<typeof modelRuntime.registerNativeProvider>[0],
  );
  return {
    modelRuntime,
    getModel: () => faux.getModel(),
    setResponses: (responses) => faux.setResponses(responses as never),
    callCount: () => faux.state.callCount,
  };
}

/**
 * Whether the installed host SDK (`@earendil-works/pi-coding-agent`'s `VERSION`) is at least
 * `major.minor.patch` — a numeric compare that ignores any prerelease/build suffix. A test whose
 * expectation genuinely differs by host branches on this and keeps both arms.
 */
export function hostSdkAtLeast(major: number, minor: number, patch: number): boolean {
  const installed = VERSION.split(/[.+-]/).map((n) => Number.parseInt(n, 10));
  for (const [i, min] of [major, minor, patch].entries()) {
    const part = installed[i] ?? 0;
    if (part !== min) return part > min;
  }
  return true;
}

/**
 * pi-ai as pi-coding-agent sees it: the nested `pi-coding-agent/node_modules/@earendil-works/pi-ai`
 * copy when present, else the deduped top-level. pi-ai module state (the faux provider, the
 * credential store) is per instance, so anything handed to a real `ModelRuntime` must come from
 * the runtime's own instance (docs/learned/pi/headless-session-drive.md).
 */
export async function loadSdkPiAi(): Promise<typeof import("@earendil-works/pi-ai")> {
  const pcaIndex = fileURLToPath(import.meta.resolve("@earendil-works/pi-coding-agent"));
  // pcaIndex is <…>/pi-coding-agent/dist/index.js → the package root is one level up from dist/.
  const pcaRoot = resolve(dirname(pcaIndex), "..");
  const nested = join(pcaRoot, "node_modules", "@earendil-works", "pi-ai", "dist", "index.js");
  return existsSync(nested)
    ? ((await import(pathToFileURL(nested).href)) as typeof import("@earendil-works/pi-ai"))
    : await import("@earendil-works/pi-ai");
}

/**
 * Plant a project-tier provider extension at `<cwd>/.pi/extensions/worker-providers.ts` (returns
 * the path) so a worker drive exercises REAL extension-backed registration through the production
 * order: Pi's loader discovers the file from disk, the extension queues `registerProvider(provider)`
 * (native) and optionally `registerVirtualModel`, and `createAgentSessionServices` applies them
 * onto the worker's `ModelRuntime`. The loader's alias map resolves the extension's
 * `@earendil-works/pi-ai` import to the pi-ai copy pi-coding-agent itself uses, so the provider
 * object shares the runtime's module instance.
 *
 * The native provider wraps a faux core (every model `reasoning: true`, so a `:thinking` suffix
 * survives clamping) scripted with the implement-HAPPY replies (`submit`, then an idle stop).
 * Its auth is CREDENTIAL-GATED: configured only when the runtime's credential store holds an
 * `api_key` credential for `provider` — that gate is what makes "saved credentials" vs
 * "unavailable auth" observable (Pi's own faux provider is always configured). `virtual` adds a
 * virtual model whose router always targets the first physical model, so a public identity
 * that differs from the physical one is observable on the recorded assistant message.
 */
export function plantWorkerProviderExtension(
  cwd: string,
  opts: {
    provider: string;
    models: [string, ...string[]];
    virtual?: { provider: string; id: string };
  },
): string {
  const dir = join(cwd, ".pi", "extensions");
  mkdirSync(dir, { recursive: true });
  const path = join(dir, "worker-providers.ts");
  const models = opts.models.map((id) => ({ id, reasoning: true }));
  const virtual = opts.virtual
    ? `
  pi.registerVirtualModel({
    provider: ${JSON.stringify(opts.virtual.provider)},
    id: ${JSON.stringify(opts.virtual.id)},
    name: ${JSON.stringify(opts.virtual.id)},
    contextWindow: 200_000,
    maxTokens: 8_192,
    route: () => ({ model: core.models[0], thinkingLevel: "off" }),
  });
`
    : "";
  const source = `// Planted by the worker e2e tier (extension/testing/harness.ts).
import {
  createFauxCore,
  createProvider,
  fauxAssistantMessage,
  fauxText,
  fauxToolCall,
} from "@earendil-works/pi-ai";

export default function (pi) {
  const core = createFauxCore({
    provider: ${JSON.stringify(opts.provider)},
    models: ${JSON.stringify(models)},
  });
  core.setResponses([
    fauxAssistantMessage([fauxToolCall("submit", {})], { stopReason: "toolUse" }),
    fauxAssistantMessage([fauxText("done")], { stopReason: "stop" }),
  ]);
  pi.registerProvider(
    createProvider({
      id: ${JSON.stringify(opts.provider)},
      auth: {
        apiKey: {
          name: "worker fixture key",
          resolve: async ({ credential }) =>
            credential?.type === "api_key" && credential.key
              ? { auth: { apiKey: credential.key } }
              : undefined,
        },
      },
      models: core.models,
      api: {
        stream: core.stream,
        streamSimple: core.streamSimple,
        fetchDeferred: core.fetchDeferred,
        cancelDeferred: core.cancelDeferred,
      },
    }),
  );${virtual}}
`;
  writeFileSync(path, source, "utf8");
  return path;
}

/** One classifier request the recording fixture received (`stopReason` is set when it ends). */
export interface ClassifyCall {
  /** 1-based arrival order at the provider. */
  seq: number;
  /** The request's signal was already aborted when it reached the provider. */
  abortedAtStart: boolean;
  stopReason?: "stop" | "error" | "aborted";
  usage?: { input: number; output: number };
}

/** Resolve after `ms`, or as soon as `signal` aborts (an abort resolves; it never rejects). */
async function waitOrAbort(ms: number, signal: AbortSignal | undefined): Promise<void> {
  try {
    await delay(ms, undefined, { signal });
  } catch (error) {
    if ((error as { name?: unknown } | null)?.name !== "AbortError") throw error;
  }
}

/**
 * A RECORDING faux classifier provider: a real pi-ai `createProvider({ classifiers })` built from
 * pi-ai as pi-coding-agent sees it, for `ModelRuntime.registerNativeProvider` on the drive's
 * injected runtime (the same seam `fauxModelRuntime` uses for chat). In-process and in-memory:
 * every request reaching the provider is appended to `calls`; `started(seq)` is a barrier that
 * resolves once request `seq` has arrived (immediately if it already has) and never rejects —
 * race it against the drive so it can never dangle.
 *
 * Auth resolves unconditionally (configured against any credential store). Each request reports
 * the fixed `usage`, waits (`delayMs`, default 0; or — for `seq >= hold.from` — until its signal
 * aborts, `hold.maxMs` being only a hang guard), then ends `aborted` without usage when its signal
 * aborted during the wait, `error` WITH usage when `seq === failCall`, else `stop` with usage.
 */
export async function recordingClassifier(opts: {
  provider: string;
  id: string;
  usage: { input: number; output: number };
  delayMs?: number;
  failCall?: number;
  hold?: { from: number; maxMs: number };
}): Promise<{
  provider: Parameters<ModelRuntime["registerNativeProvider"]>[0];
  model: { provider: string; id: string };
  calls: ClassifyCall[];
  started(seq: number): Promise<void>;
}> {
  const piAi = await loadSdkPiAi();
  const api = "faux-classify";
  const calls: ClassifyCall[] = [];
  const waiters = new Map<number, (() => void)[]>();
  const usage = {
    input: opts.usage.input,
    output: opts.usage.output,
    cacheRead: 0,
    cacheWrite: 0,
    totalTokens: opts.usage.input + opts.usage.output,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
  };
  const classify = async (
    model: { provider: string; id: string },
    _context: unknown,
    options?: { signal?: AbortSignal },
  ) => {
    const signal = options?.signal;
    const call: ClassifyCall = { seq: calls.length + 1, abortedAtStart: signal?.aborted === true };
    calls.push(call);
    for (const release of waiters.get(call.seq) ?? []) release();
    waiters.delete(call.seq);
    const held = opts.hold !== undefined && call.seq >= opts.hold.from;
    await waitOrAbort(held && opts.hold ? opts.hold.maxMs : (opts.delayMs ?? 0), signal);
    const base = {
      api,
      provider: model.provider,
      model: model.id,
      answers: {},
      timestamp: Date.now(),
    };
    if (signal?.aborted) {
      call.stopReason = "aborted";
      return { ...base, stopReason: "aborted" as const, errorMessage: "aborted" };
    }
    call.usage = { ...opts.usage };
    if (call.seq === opts.failCall) {
      call.stopReason = "error";
      return { ...base, usage, stopReason: "error" as const, errorMessage: "faux failure" };
    }
    call.stopReason = "stop";
    return { ...base, usage, stopReason: "stop" as const };
  };
  const provider = piAi.createProvider({
    id: opts.provider,
    auth: { apiKey: { name: "fixture", resolve: async () => ({ auth: { apiKey: "faux" } }) } },
    models: [
      {
        type: "classifier",
        id: opts.id,
        name: opts.id,
        api,
        provider: opts.provider,
        baseUrl: "",
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 8_192,
      },
    ],
    classifiers: { [api]: { classify } },
  });
  return {
    provider: provider as Parameters<ModelRuntime["registerNativeProvider"]>[0],
    model: { provider: opts.provider, id: opts.id },
    calls,
    started: (seq) =>
      calls.length >= seq
        ? Promise.resolve()
        : new Promise<void>((resolve) => {
            waiters.set(seq, [...(waiters.get(seq) ?? []), resolve]);
          }),
  };
}

/**
 * Plant `<cwd>/.pi/extensions/worker-model-tools.ts` (returns the path): the model-using tools a
 * worker drive exercises through Pi's own loader. `tool` registers `faux_classify_tool`, which
 * calls `ctx.modelRegistry.classify` on the named classifier and reports the result's `usage` on
 * its own tool result (failing unless the call stopped normally). `codemode` registers Pi's REAL
 * `createCodemodeExtension({ mode: "on", models })` — the loader's alias map resolves the import to
 * the host package, so the sandbox's worker/wasm paths resolve from it; activate it with the
 * scaffold's `defaultTools: ["+codemode"]` (it registers inactive).
 */
export function plantWorkerModelTools(
  cwd: string,
  opts: { tool?: { provider: string; id: string }; codemode?: { models: boolean } },
): string {
  const dir = join(cwd, ".pi", "extensions");
  mkdirSync(dir, { recursive: true });
  const path = join(dir, "worker-model-tools.ts");
  const tool = opts.tool
    ? `
  pi.registerTool({
    name: "faux_classify_tool",
    label: "faux_classify_tool",
    description: "Classify with the fixture classifier model.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
    async execute(_id, _params, signal, _onUpdate, ctx) {
      const model = ctx.modelRegistry.getModelOfType(
        "classifier",
        ${JSON.stringify(opts.tool.provider)},
        ${JSON.stringify(opts.tool.id)},
      );
      const r = await ctx.modelRegistry.classify(
        model,
        { state: {}, questions: { q: { type: "bool", instructions: "x", criteria: { true: "t", false: "f" } } } },
        { signal },
      );
      return {
        content: [{ type: "text", text: r.stopReason }],
        details: { stopReason: r.stopReason },
        ...(r.usage ? { usage: r.usage } : {}),
        ...(r.stopReason === "stop" ? {} : { isError: true }),
      };
    },
  });
`
    : "";
  const codemode = opts.codemode
    ? `
  createCodemodeExtension({ mode: "on", models: ${JSON.stringify(opts.codemode.models)} })(pi);
`
    : "";
  const source = `// Planted by the worker e2e tier (extension/testing/harness.ts).
${opts.codemode ? 'import { createCodemodeExtension } from "@earendil-works/pi-coding-agent";\n' : ""}
export default function (pi) {${tool}${codemode}}
`;
  writeFileSync(path, source, "utf8");
  return path;
}

/**
 * Plant `<cwd>/.pi/extensions/worker-mcp-registrar.ts` (returns the path): a project extension
 * whose factory registers one MCP server (`inert`, a `node -e "process.exit(0)"` stdio command
 * that would exit at once if anything ever spawned it). With no loaded extension connecting MCP
 * servers, Pi reports the registration at bind as a `register_mcp_server` extension error and
 * never connects it — the observable that distinguishes an absent MCP handler from a loaded one.
 */
export function plantMcpRegistrar(cwd: string): string {
  const dir = join(cwd, ".pi", "extensions");
  mkdirSync(dir, { recursive: true });
  const path = join(dir, "worker-mcp-registrar.ts");
  const server = { command: process.execPath, args: ["-e", "process.exit(0)"] };
  const source = `// Planted by the worker e2e tier (extension/testing/harness.ts).
export default function (pi) {
  pi.registerMcpServer("inert", ${JSON.stringify(server)});
}
`;
  writeFileSync(path, source, "utf8");
  return path;
}

/**
 * A hermetic `ModelRuntime` with NO provider seeded — any non-builtin provider must come from a
 * planted extension's registration. Hermetic: an in-memory credential store pre-populated with one
 * `{ type: "api_key", key }` credential per `credentials` entry (provider id → key), no
 * models.json read (`modelsPath: null`), no create-time refresh. Builtin providers are still
 * present and their availability stays ambient-sensitive (env keys), so assert only on the
 * fixture provider.
 */
export async function bareModelRuntime(
  opts: { credentials?: Record<string, string> } = {},
): Promise<ModelRuntime> {
  const piAi = await loadSdkPiAi();
  const store = new piAi.InMemoryCredentialStore();
  for (const [providerId, key] of Object.entries(opts.credentials ?? {})) {
    await store.modify(providerId, async () => ({ type: "api_key", key }));
  }
  return ModelRuntime.create({ credentials: store, modelsPath: null, refreshOnCreate: false });
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

/**
 * The one shared fake tool body every fake extension registers (a no-op tool). `defaultActive:
 * false` registers it inactive (Pi's own opt-out — the tool exists but is not activated on
 * registration).
 */
export function registerFakeTool(
  pi: ExtensionAPI,
  name: string,
  opts: { defaultActive?: boolean; promptSnippet?: string } = {},
): void {
  pi.registerTool({
    name,
    label: name,
    description: `fake tool ${name} (test)`,
    parameters: { type: "object", properties: {} },
    ...(opts.defaultActive === false ? { defaultActive: false } : {}),
    ...(opts.promptSnippet !== undefined ? { promptSnippet: opts.promptSnippet } : {}),
    async execute() {
      return { content: [{ type: "text", text: "ok" }], details: {} };
    },
  });
}

/**
 * A fake npm package installed into the session's user-scope package directory before the load:
 * `<agentDir>/npm/node_modules/<name>/{package.json, extension.js}`, listed verbatim (`spec`) in
 * `<agentDir>/settings.json` `packages` — so Pi resolves it offline exactly like an installed
 * borrow and its tools carry real package provenance (`sourceInfo.source === spec`).
 * `extension` is the ESM source of `extension.js` (`export default function (pi) { … }`).
 */
export type FakePackage = { spec: string; name: string; version: string; extension: string };

/** A FakePackage from an `npm:` spec (`npm:name@1.2.3`, `npm:@scope/name@1.2.3`; default 1.0.0). */
export function fakeNpmPackage(spec: string, extension: string): FakePackage {
  const body = spec.replace(/^npm:/, "");
  const at = body.indexOf("@", body.startsWith("@") ? 1 : 0);
  const name = at === -1 ? body : body.slice(0, at);
  const version = at === -1 ? "1.0.0" : body.slice(at + 1);
  return { spec, name, version, extension };
}

function installFakePackages(agentDir: string, packages: readonly FakePackage[]): void {
  for (const pkg of packages) {
    const dir = join(agentDir, "npm", "node_modules", pkg.name);
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "package.json"),
      `${JSON.stringify({ name: pkg.name, version: pkg.version, type: "module", pi: { extensions: ["./extension.js"] } }, null, 2)}\n`,
      "utf8",
    );
    writeFileSync(join(dir, "extension.js"), pkg.extension, "utf8");
  }
  writeFileSync(
    join(agentDir, "settings.json"),
    `${JSON.stringify({ packages: packages.map((pkg) => pkg.spec) }, null, 2)}\n`,
    "utf8",
  );
}

/** perk's extension entry by path — the Mode B (provenance-real) load. */
export const PERK_EXTENSION_PATH = resolve(import.meta.dirname, "..", "index.ts");

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
  /** Original replacement prompt, retained by the resource loader on reload. */
  systemPrompt?: string;
  headful?: boolean;
  /** Pi run mode forwarded to `bindExtensions` (drives `ctx.mode`). Defaults to Pi's "print". */
  mode?: ExtensionMode;
  /** Session model override (e.g. a faux-provider model); defaults to the keyless anthropic model. */
  model?: unknown;
  /**
   * The session's canonical model/auth runtime — e.g. `fauxModelRuntime().modelRuntime`, so a
   * real prompt turn runs offline; defaults to the SDK's agentDir-derived runtime.
   */
  modelRuntime?: ModelRuntime;
  /**
   * Extra extension factories bound AFTER perk (e.g. a fake plannotator registering its
   * `plannotator-review` command so presence probes see it). Offline like everything here. Pi's
   * full `InlineExtension` shape: a bare factory loads as `<inline:N>` (unknown provenance), a
   * named one as `<inline:name>`, and `{ name, factory, builtin: true }` through the
   * `builtin:<name>` path with `source: "builtin"` (the CLI's own tool_search/codemode shape).
   */
  extraExtensions?: InlineExtension[];
  /**
   * Mode B — provenance-real packages: when set, perk loads by PATH (`additionalExtensionPaths`
   * — CLI paths load before settings packages, production's perk-first order) instead of the
   * inline factory, and each fake package is installed into the user-scope package directory
   * and listed in `<agentDir>/settings.json` (`PI_OFFLINE=1` keeps resolution local). perk then
   * runs in the extension loader's own module instance: assert only through the live session.
   * The construction-only perk options (resolverEngine, …) do not apply in this mode.
   */
  packages?: readonly FakePackage[];
  /** Pi's registry allowlist (`createAgentSession({ tools })` — the CLI's `--tools`). */
  tools?: string[];
  /** Pi's registry denylist (`createAgentSession({ excludeTools })` — `--exclude-tools`). */
  excludeTools?: string[];
  /** Construction-only fake lock/config inputs for foreground resolver tests. */
  resolverEngine?: NonNullable<Parameters<typeof perk>[1]>["resolverEngine"];
  /** Construction-only fake native-config input for the librarian writer's engine. */
  librarianEngine?: NonNullable<Parameters<typeof perk>[1]>["librarianEngine"];
  stackResolutionDelivery?: NonNullable<Parameters<typeof perk>[1]>["stackResolutionDelivery"];
  /** Construction-only recording receiver for the startup/navigation sync-order pins. */
  feedbackReceiverFactory?: NonNullable<Parameters<typeof perk>[1]>["feedbackReceiverFactory"];
  /** Construction-only injected host-SDK bridge status (drives the reporting arms). */
  nativeSdkBridge?: NonNullable<Parameters<typeof perk>[1]>["nativeSdkBridge"];
  /**
   * In-memory settings shallow-merged over the deterministic defaults (compaction and retry
   * off) — e.g. `{ compaction: { enabled: true, reserveTokens, keepRecentTokens } }` to exercise
   * Pi's real threshold compaction on a faux-runtime turn.
   */
  settings?: {
    compaction?: { enabled?: boolean; reserveTokens?: number; keepRecentTokens?: number };
    /** Pi's startup active-set preference (`+name`/`-name` modifiers or plain names). */
    defaultTools?: string[];
    codemode?: { mode?: "on" | "only" };
  };
}): Promise<PerkSession> {
  const { cwd, headful = true } = opts;
  const agentDir = mkdtempSync(join(tmpdir(), "perk-agent-"));
  const modeB = opts.packages !== undefined;
  if (modeB) installFakePackages(agentDir, opts.packages ?? []);
  const savedEnv = new Map<string, string | undefined>();
  // Sentinels on by default so the lifecycle is observable. PERK_CLIPBOARD_CMD/PERK_TERMINAL_LAUNCH
  // default to "" (disabled) so no harness-driven suite clobbers the dev machine's clipboard or
  // spawns a terminal window. PLANNOTATOR_REMOTE/PLANNOTATOR_PORT pin the local port selection:
  // the composition root resolves it from process.env at activation, and an SSH-launched test
  // shell carries SSH_CONNECTION, so without these every harness-driven browser-door test would
  // silently switch to the 19432 single port when the suite runs over SSH (a test opts in with
  // `env: { PLANNOTATOR_PORT: ... }`). Caller env is spread last, so all remain overridable
  // per-test.
  applyEnv(
    {
      PERK_SELFCHECK: "1",
      PERK_RUN_ID: undefined,
      PI_SUBAGENT_CHILD: undefined,
      PI_SUBAGENT_EXTENSION_BINDINGS: undefined,
      PI_SUBAGENT_CHILD_AGENT: undefined,
      PERK_CLIPBOARD_CMD: "",
      PERK_TERMINAL_LAUNCH: "",
      PLANNOTATOR_REMOTE: "0",
      PLANNOTATOR_PORT: undefined,
      ...(modeB ? { PI_OFFLINE: "1" } : {}),
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
  const inlinePerk: InlineExtension[] = modeB
    ? []
    : [
        // Named inline factory: startup/extension-load-error surfaces then say `<inline:perk>`
        // instead of the positional `<inline:1>`.
        {
          name: "perk",
          factory: (pi) =>
            perk(pi, {
              resolverEngine: opts.resolverEngine,
              librarianEngine: opts.librarianEngine,
              stackResolutionDelivery: opts.stackResolutionDelivery,
              feedbackReceiverFactory: opts.feedbackReceiverFactory,
              nativeSdkBridge: opts.nativeSdkBridge,
            }),
        },
      ];
  const loader = new DefaultResourceLoader({
    cwd,
    agentDir,
    systemPrompt: opts.systemPrompt,
    ...(modeB ? { additionalExtensionPaths: [PERK_EXTENSION_PATH] } : {}),
    extensionFactories: [...inlinePerk, ...(opts.extraExtensions ?? [])],
  });
  await loader.reload();
  if (modeB) {
    // A path-loaded perk or a fake package that fails to load must fail the fixture, not degrade
    // silently into a session without it.
    const { errors } = loader.getExtensions();
    if (errors.length > 0) {
      throw new Error(
        `perk harness: extension load failed — ${errors.map((e) => `${e.path}: ${e.error}`).join("; ")}`,
      );
    }
  }
  const model =
    (opts.model as ReturnType<typeof getModel> | undefined) ??
    getModel("anthropic", "claude-sonnet-4-5") ??
    undefined;
  const { session } = await createAgentSession({
    cwd,
    agentDir,
    model,
    ...(opts.modelRuntime !== undefined ? { modelRuntime: opts.modelRuntime } : {}),
    resourceLoader: loader,
    ...(opts.tools !== undefined ? { tools: opts.tools } : {}),
    ...(opts.excludeTools !== undefined ? { excludeTools: opts.excludeTools } : {}),
    sessionManager: opts.sessionManager ?? SessionManager.inMemory(cwd),
    settingsManager: SettingsManager.inMemory({
      compaction: { enabled: false },
      retry: { enabled: false },
      ...(opts.settings ?? {}),
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
    footerInstallCount: () => footers.length,
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
    renderAppendedEntry(customType, data, width = 80) {
      const renderer = session.extensionRunner.getEntryRenderer(customType);
      if (!renderer) return undefined;
      const entryId = session.sessionManager.appendCustomEntry(customType, data);
      const entry = session.sessionManager
        .getEntries()
        .find((candidate) => candidate.id === entryId);
      if (!entry) throw new Error(`appended entry not found: ${entryId}`);
      const theme = { fg: (color: string, text: string) => `<${color}>${text}</>` };
      return renderer(entry as never, { expanded: false }, theme as never)?.render(width);
    },
    registeredTool(name: string) {
      const def = session.extensionRunner.getToolDefinition(name);
      if (!def) return null;
      return {
        name: def.name,
        label: def.label,
        description: def.description,
        parameters: def.parameters as unknown,
        ...(def.promptSnippet !== undefined ? { promptSnippet: def.promptSnippet } : {}),
        ...(def.promptGuidelines !== undefined ? { promptGuidelines: def.promptGuidelines } : {}),
        ...(def.executionMode !== undefined ? { executionMode: def.executionMode as string } : {}),
        ...(def.outputSchema !== undefined ? { outputSchema: def.outputSchema as unknown } : {}),
      };
    },
    toolInfo(name: string) {
      const info = session.getAllTools().find((t) => t.name === name);
      if (!info) return null;
      return {
        name: info.name,
        exposure: info.exposure,
        ...(info.annotations !== undefined ? { annotations: info.annotations } : {}),
      };
    },
    registeredCommand(name: string) {
      const command = session.extensionRunner.getCommand(name);
      if (!command) return null;
      return {
        name: command.invocationName,
        ...(command.description !== undefined ? { description: command.description } : {}),
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
    async invokeTool(
      name: string,
      params: unknown,
      toolOpts?: {
        onUpdate?: (partial: { content: { text?: string }[]; details: unknown }) => void;
        ui?: Record<string, unknown>;
        signal?: AbortSignal;
        /** Placed on `ctx.signal` (production tools source cancellation from the context, not
         * the execute callback's signal slot — this knob exercises that path). */
        ctxSignal?: AbortSignal;
      },
    ) {
      const tool = session.extensionRunner
        .getAllRegisteredTools()
        .find((t) => t.definition.name === name);
      if (!tool) throw new Error(`tool not registered: ${name}`);
      const ctx = {
        cwd,
        hasUI: headful,
        mode: (opts.mode ?? "print") as ExtensionMode,
        ui: {
          ...(headfulUIContext(notifies) as unknown as Record<string, unknown>),
          ...(toolOpts?.ui ?? {}),
        },
        sessionManager: session.sessionManager,
        signal: toolOpts?.ctxSignal,
        isIdle: () => true,
      } as unknown as Parameters<typeof tool.definition.execute>[4];
      const result = await tool.definition.execute(
        `tc-${name}`,
        params as never,
        toolOpts?.signal as Parameters<typeof tool.definition.execute>[2],
        toolOpts?.onUpdate as Parameters<typeof tool.definition.execute>[3],
        ctx,
      );
      await tick();
      return result as {
        content: { text?: string }[];
        details: unknown;
        terminate?: boolean;
        structuredContent?: unknown;
        isError?: boolean;
      };
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
    async emitSessionStart() {
      await session.extensionRunner.emit({ type: "session_start", reason: "startup" } as never);
      await tick();
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
export function spyInjections(h: PerkSession, optionsSeen?: unknown[]): string[] {
  const injected: string[] = [];
  (
    h.session as unknown as {
      sendUserMessage: (c: unknown, options?: unknown) => Promise<void>;
    }
  ).sendUserMessage = async (c, options) => {
    injected.push(typeof c === "string" ? c : JSON.stringify(c));
    optionsSeen?.push(options);
  };
  return injected;
}

// --- shared fixture pieces for the tool-activation suites ---------------------------------------

/**
 * loadPerkSession with process.cwd() pointed at the scaffold for the load: provider vacating
 * (e.g. perk's plan surface under a foreign `[providers] plan`) resolves `process.cwd()` at
 * factory time, so running a suite from a repo with its own selections would otherwise leak into
 * what registers. Restores cwd before returning.
 */
export async function loadAt(
  cwd: string,
  opts: Omit<Parameters<typeof loadPerkSession>[0], "cwd"> = {},
): Promise<PerkSession> {
  const savedCwd = process.cwd();
  process.chdir(cwd);
  try {
    return await loadPerkSession({ cwd, ...opts });
  } finally {
    process.chdir(savedCwd);
  }
}

/** A Mode A session claimed into a (stage, mode) landing through the handoff. */
export async function staged(
  stage: string,
  mode: "read-only" | "read-write",
  opts: Omit<Parameters<typeof loadPerkSession>[0], "cwd"> & {
    /** Extra handoff keys (e.g. an objective id the plan-ref does not carry). */
    handoffExtra?: Record<string, unknown>;
    /** A plan-ref written into the scaffold before the load. */
    planRef?: PlanRef;
  } = {},
): Promise<PerkSession> {
  const { handoffExtra, planRef, ...loadOpts } = opts;
  const runId = `01OWN${stage.replaceAll("-", "").toUpperCase()}${mode === "read-only" ? "RO" : "RW"}`;
  const cwd = scaffoldRepo({ handoff: { runId, mode, stage, extra: handoffExtra } });
  if (planRef !== undefined) writePlanRef(cwd, planRef);
  return loadAt(cwd, { ...loadOpts, env: { PERK_RUN_ID: runId, ...(loadOpts.env ?? {}) } });
}

/** One captured model request: the declared tools (the model-visible census) and the prompt. */
export type RecordedRequest = { tools: string[]; declared: unknown[]; prompt: string };

/** A faux runtime whose every scripted response first records the request it answers. */
export async function recordingRuntime() {
  const reg = await fauxModelRuntime();
  const requests: RecordedRequest[] = [];
  const record = (reply: () => unknown) => (context: { messages: never }) => {
    const declared = getCurrentTools(context.messages);
    requests.push({
      tools: declared.map((t) => t.name),
      declared,
      prompt: getCurrentSystemPrompt(context.messages),
    });
    return reply();
  };
  const stop = () => fauxAssistantMessage([fauxText("done")], { stopReason: "stop" });
  return {
    reg,
    requests,
    /** Script one plain census turn. */
    census() {
      reg.setResponses([record(stop)]);
    },
    /** Script a turn that calls `tool` with `args`, then stops. */
    callThenStop(tool: string, args: Parameters<typeof fauxToolCall>[1]) {
      reg.setResponses([
        record(() =>
          fauxAssistantMessage([fauxToolCall(tool, args, { id: `call-${tool}` })], {
            stopReason: "toolUse",
          }),
        ),
        record(stop),
      ]);
    },
    last: (): RecordedRequest => {
      const request = requests.at(-1);
      assert.ok(request !== undefined, "a model request was made");
      return request;
    },
  };
}

/**
 * Record every install perk itself makes (attributed by stack to the gating module) while the
 * test runs — Pi's own installs (registration refreshes, transcript restores) are not perk's.
 * Each record carries the live set the install replaced, so a pin can prove an install only added
 * (the restoration-window rule, contracts.md §8.40).
 */
export function recordPerkInstalls(t: TestContext): PerkInstall[] {
  const installs: PerkInstall[] = [];
  const original = AgentSession.prototype.setActiveToolsByName;
  t.mock.method(
    AgentSession.prototype,
    "setActiveToolsByName",
    function (this: AgentSession, names: string[]) {
      if (new Error().stack?.includes("substrate/toolGating.ts") === true)
        installs.push({ names: [...names], before: this.getActiveToolNames() });
      return original.call(this, names);
    },
  );
  return installs;
}

/** One install perk made: the names it installed and the live active set it replaced. */
export type PerkInstall = { names: string[]; before: string[] };

/** Pi's real builtin `tool_search`, loaded through the CLI's builtin path (`source: "builtin"`). */
export const toolSearch = (): InlineExtension => ({
  name: "tool-search",
  factory: createToolSearchExtension(),
  builtin: true,
});

/**
 * The discovery-cohort opt-in (load beside `toolSearch()`): Pi's `+name` modifier activates the
 * registered builtin at startup, so perk joins the cohort at `session_start`.
 */
export const COHORT_SETTINGS = { defaultTools: ["+tool_search"] };

/**
 * Like `spyInjections`, but also records the live active tool set at each injection — proving a
 * door primed its deferred tools BEFORE its guidance reached the model.
 */
export function spyInjectionLoadouts(h: PerkSession): { injected: string[]; active: string[][] } {
  const out = { injected: [] as string[], active: [] as string[][] };
  (
    h.session as unknown as {
      sendUserMessage: (c: unknown, options?: unknown) => Promise<void>;
    }
  ).sendUserMessage = async (c) => {
    out.injected.push(typeof c === "string" ? c : JSON.stringify(c));
    out.active.push(h.session.getActiveToolNames());
  };
  return out;
}

/**
 * A ToolGating fake recording exits and every `primeDeferred` call (the door tests assert a door
 * primes exactly its constant); `active` is the isActive snapshot. It reports a nonparticipant
 * session: priming activates nothing and the cohort join is a no-op.
 */
export function fakeGating(
  active: boolean,
): ToolGating & { exits: number; primes: (readonly string[])[] } {
  const g = {
    exits: 0,
    primes: [] as (readonly string[])[],
    syncFromState() {},
    enter() {},
    exit() {
      g.exits += 1;
    },
    isActive: () => active,
    prepareLoadout: () => ({ hiddenDeclarations: [] }),
    joinDiscoveryCohort() {},
    primeDeferred(names: readonly string[]): string[] {
      g.primes.push([...names]);
      return [];
    },
    discovery: () => ({ cohort: false, family: [] as readonly string[] }),
  };
  return g;
}
