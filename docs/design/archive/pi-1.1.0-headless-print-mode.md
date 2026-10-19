# Record: headless print mode on Pi 1.1.0 + pi-subagents 0.76.1 — the #2660 reproduction and the post-terminal attribution

**Status:** measured. The live rows ran 2026-10-19 20:04:06Z–20:16:26Z (UTC), and the record was
authored the same day on branch `plan-2723` (base `4bf7583d`). It implements plan #2723
(Objective #2707, node 2.4). The classification and disposition tables were committed at
`7f335793`, before the first row ran. No pin, floor, stamp, setting, agent definition or
production source moved: the diff is this record and two `CONTEXT.md` glossary terms.

**Verdict:**

- **#2660 — LOOPS / LOOPS, and #2660 is closed.** The disposition row that fired is R1 `LOOPS`, R2
  `LOOPS`: "Persists on Pi 1.1.0 + pi-subagents 0.76.1 and reproduces without perk: an upstream
  limitation of the print-mode parent after a refused lane's wake; outside perk's report path
  (`worktree: false` on every lane); no perk regression, no repair." All four scored replicates
  hit the watchdog. The fixed endpoint rule would make this `UNRESOLVED`, because two P rows
  are `INVALID` (next bullet). **Operator deviation (2026-10-19, in the implement session):**
  #2660 is decided from the two R arm classes alone, and the comment + close was executed (see
  [#2660 disposition](#2660-disposition)).
- **H — `INCONCLUSIVE`.** P2 and P4 are `INVALID` under the V4 wording ("exactly one assistant
  entry after the wake user entry"). In every settle wake turn the model read the child's output
  (one `read` call; two in P2's re-run), then answered: two assistant entries, `toolUse` then
  `stop`, on each attempt and its re-run. The two valid rows, P1 and P3, hold every scorable cell (C1, S1, S2).
  The operator kept this verdict literal. The record also shows, unscored, what a multi-entry
  reading of V4 would give: `PARTIAL`, with S3 failing.
- **`[object Object]`: fixed since #2671 and confirmed offline.** The fix is
  `extension/worker/sdkAdapter.ts::formatExtensionError`, used by `headlessBinding().onError`,
  landed at `919c34dd`. The pin passes: `✔ formatExtensionError: Pi's ExtensionError renders
  path, event and message; other values fall back (0.05775ms)`.

Two findings fall outside the pre-registered questions; neither was predicted:

- **A `badmodel` lane loops too.** R3 hit the watchdog, unlike 0.75.0's X1, which exited. On this
  pair the non-exit no longer depends on the pre-spawn failure kind.
- **Waiting for the wake turn removes the loop in both arms.** R1t and R2t exit 0 with no
  `<boundary>` and no stale-ctx line.

Measured rows quote command output. Source-derived statements cite the installed dists (PATH Pi
1.1.0 under `~/.local/share/mise/installs/node/26.3.0/lib/node_modules/@earendil-works/pi-coding-agent/dist`,
its nested `pi-agent-core` 1.1.0, and `$WT/.pi/npm/node_modules/pi-subagents/src` 0.76.1) and are
labelled SOURCE-DERIVED. A passing test is never quoted as observed live behaviour.

**Path abbreviations in quotes:** `$WT` = `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2723`.
`$SCRATCH` = `$WT/.perk/workflow/scratch/runs/01M5AVMXZ91ZQ0CDZR2T6XQ3BF/agent/live` (gitignored).
`$AUTHED` = `/var/folders/90/b55dzd451137c93rcngpgdh00000gp/T/perk-2660-authed.ubuw88S9ao`.
`$MODEL` = `anthropic/claude-haiku-5-5`. Pi's stale-ctx message is elided where
marked. Apart from these substitutions, quotes are verbatim.

## Versions

| Component | Version / value |
| --- | --- |
| PATH `pi` (`which pi`, `pi --version`) | `1.1.0` at `~/.local/share/mise/installs/node/26.3.0/bin/pi` |
| Root SDK (`node_modules/@earendil-works/pi-coding-agent/package.json`) | `1.1.0` |
| Worktree engine (`.pi/npm/node_modules/pi-subagents/package.json`) | `0.76.1` |
| Node | `v26.3.0` |
| `$MODEL` (parent `--model` and every lane `model`) | `anthropic/claude-haiku-5-5` — the cheapest Anthropic model in the installed catalog (`pi-ai` `providers/data/anthropic.json`: $0.10 / $0.50 per Mtok input/output; `claude-haiku-4-5` is $1 / $5) |
| Parent launches | **14 of 16**: 9 mandatory, 2 conditional (R1t, R2t), 3 re-runs (P1, P2, P4) |
| Live wall | 20:04:06Z → 20:16:26Z = **12 min 20 s** of 60 |
| Measured spend | **$0.023245** over the rows: lane `totalCost.costUsd` $0.001123, parents' persisted assistant `usage.cost.total` $0.022122. A pre-row model preflight (below) cost $0.000094. Not measurable: any provider request made by a turn after `dispose()` (no network witness; such turns persist nothing) |

## Summary

| Question | Measured rows | Offline / source evidence | Verdict |
| --- | --- | --- | --- |
| #2660: does a print-mode parent loop after a lane refused at worktree admission, with and without perk? | R1, R1-r2 (perk) `LOOPS`; R2, R2-r2 (no-perk) `LOOPS`; R3 (`badmodel`, perk) `LOOPS`; R1t, R2t (settle) `EXITS` | `prepareWorkflowLaunchParams` explicit-wins; `renderWaveScript` `worktree: false`; the two `reportWave.test.ts` assertions | LOOPS / LOOPS → comment + close (executed; operator deviation from the endpoint coupling) |
| H: are the post-terminal lines a dispose-aborted wake turn, and which are perk's? | P1 (= R4, re-run valid), P3 valid; P2, P4 `INVALID` (V4 wording) | the SOURCE-DERIVED mechanism below | `INCONCLUSIVE` (valid rows hold C1, S1, S2; `<boundary>` `HOST`, stale-ctx `PERK-ADDITIVE`, loadout `ABSENT`) |
| Worker `[object Object]` | none, by decision | `formatExtensionError` + its pin; `919c34dd` (#2671) | fixed, confirmed offline |

## Supported-path impact

This is offline and source evidence, not a live row. Perk's report path cannot reach worktree
admission:

- **The renderer pins it.** `extension/waves/reportWave.ts::renderWaveScript` writes
  `worktree: false` on every `runs.all` item. The assignment cannot override it: the renderer
  selects fields explicitly.
- **Two tests assert it** (`node --test extension/waves/reportWave.test.ts`, 88/88 pass):
  - `✔ start: every report child carries the constant packet and caller-checkout placement` /
    `✔ run: …` assert `item.worktree === false` for every report role.
  - `✔ the renderer rejects hostile extra fields: the packet and placement cannot be overridden`
    feeds an assignment carrying `worktree: true` and asserts `raw?.worktree === false`.
- **The engine lets the explicit value win** (SOURCE-DERIVED). In pi-subagents 0.76.1
  `src/runs/foreground/subagent-executor.js`, `prepareWorkflowLaunchParams` spreads
  `...workflowDefaults` and then `...childParams`, so an explicit child `worktree: false` beats a
  default (`:4431–4433`; the retained-resume branch's `childParams.worktree ??
  workflowDefaults.worktree` at `:4387`). `preflightWorkflowWorktrees` then skips every call whose
  effective `(effective.worktree ?? input.defaultWorktree) !== true` (`:4344`).

So the refused-lane trigger in R1/R2 is unreachable from perk's report waves. The loop it exposes
is the print-mode host's, not a perk path's.

## The source-derived mechanism

Each bullet was read on the installed dists named above. They are SOURCE-DERIVED and were tested
by the rows, never asserted as measured. "Confirmed by" names the rows whose readings agree.

- **Print mode disposes as soon as the prompt returns.** `dist/modes/print-mode.js::runPrintMode`
  runs `await session.prompt(initialMessage)`, then `finally { … await disposeRuntime() }`.
  `disposeRuntime` unsubscribes the JSON stdout stream first, then calls `runtimeHost.dispose()`.
  Its `onError` is `console.error(\`Extension error (${err.extensionPath}): ${err.error}\`)`, so
  `event` and `stack` are dropped. Confirmed by every quoted `Extension error (…)` line.
- **A command's prompt returns without waiting.** `dist/core/agent-session.js::prompt`
  (`:1525–1531`) returns right after an extension command's handler completes ("Extension command
  executed, no prompt to send"). It never waits for a run the command triggered. Confirmed: in
  every `return` row `session_shutdown` follows `probe: settled-at` within ≤ 2 ms.
- **The runtime emits shutdown before it disposes the session.**
  `dist/core/agent-session-runtime.js::dispose` (`:296–303`) emits `session_shutdown` with
  `reason: "quit"`, then calls `this.session.dispose()`. Confirmed: every row's
  `session_shutdown` line reads `reason: "quit"` and `ctxStale: false`.
- **What dispose does.** `AgentSession.dispose()` (`:992–1004`) calls `this.agent.abort()`, then
  `this._extensionRunner.invalidate(<the stale message>)`, then `_disconnectFromAgent()`.
  - Once disconnected, agent `message_*`/`agent_end` events no longer reach extensions or the
    session file.
  - The `finishTurn` hook (`_installAgentBoundaryHooks`, `:522–534`) stays installed. An
    in-flight turn ending after dispose therefore runs `_dispatchTurnEndBoundary` (`:488–500`).
    That finds no persisted entry and, when any extension has a `turn_end` handler, emits
    `{extensionPath: "<boundary>", event: "turn_end", error: "turn_end could not resolve the
    persisted assistant entry ID"}`.
  - The probe registers no `turn_end` handler. pi-subagents does, in both arms
    (`src/watchdog/register-main.js:395`), and perk does in the perk arm
    (`extension/pi/v1/objective.ts`).
- **Extensions still receive events after invalidation.** `dist/core/extensions/runner.js::emit`
  (`:813–836`) and `emitContext` (`:1006`) keep calling handlers after `invalidate()`. The ctx
  getters (`ui`, `hasUI`, `cwd`, `sessionManager`, …; `:614–687`) throw the stale message through
  `assertActive()` (`:488–491`).
  - The `context` event comes from the agent's `transformContext` hook (`dist/core/sdk.js:278–283`).
  - `agent_settled` comes from `_emitAgentSettled` (`:684–691`), which runs in the run loop's
    `finally` (`:1404–1412`).
  - Neither path goes through the disconnected subscription. Confirmed: the probe's own
    `context`/`agent_settled` observers ran after `session_shutdown` and read `ctxStale: true`
    (R rows, P1, P3).
- **The perk handlers that could throw.** Perk handlers that touch ctx after dispose produce one
  `Extension error ($WT/extension/index.ts): This extension ctx is stale …` line per dispatch.
  Candidates on `context`: `extension/substrate/agentScratch.ts:132`, `bindingDelivery.ts:279`,
  `extension/pi/v1/contextInjection.ts:200`. Candidates on `agent_settled`:
  `extension/pi/v1/objective.ts:236`, `extension/pi/v1/drivenCompaction.ts:134`.
  `extension/substrate/toolGating.ts:437`'s `context` handler reaches `prepareLoadout`, whose
  catch prints `perk: loadout presentation failed — …` (`:535`). Which handler threw first is not
  observable, because print mode drops `event`.
- **How pi-subagents wakes an idle parent.** pi-subagents 0.76.1
  `src/shared/parent-wake.js::createParentWake`, on an idle parent, sends the notice with
  `triggerTurn: false`, then `pi.sendUserMessage("Subagent updates above.", {deliverAs:
  "steer"})`. A handled or failed wake emits no `agent_start` and is abandoned after
  `WAKE_PENDING_MS` = 10 s.
  - `src/runs/background/notify.js::incrementalChildCompletionTriggersTurn` (`:235–239`) returns
    `false` for a completed child while its workflow is still running, and wakes otherwise.
  - Confirmed: R rows woke on the `Workflow child failed …\nStatus: workflow still running`
    notice. P rows woke only on the workflow's own `subagent-notify`; their incremental notice
    carried `display: false` and woke nothing.
- **The worktree refusal is admission inside the workflow.** The workflow `admit` callback calls
  `preflightWorkflowWorktrees` (`subagent-executor.js:4337–4359`), which calls
  `worktree.js::probeWorktreeSource` (`:195–204`). That throws `worktree isolation requires a
  clean git working tree. Commit or stash changes first.`, wrapped as `Worktree admission failed
  for '<key>' at <cwd>: … Select the correct cwd or arrange an operator-approved commit/stash.`
  Confirmed: R1/R2 show no child run id and fan-out `used: 0`.
- **Why turns can still run after dispose.** pi-agent-core 1.1.0 `dist/agent.js::abort`
  (`:218–220`) aborts only `this.activeRun?.abortController`. `runWithLifecycle` (`:341–350`)
  creates a fresh `AbortController` for every later run, and `AgentSession._runAgentPrompt`'s loop
  (`:1389–1403`) stops only on `_agentRunAbortRequested`, which `dispose()` never sets. So a run
  the session loop starts after dispose is not aborted by it. `_emitAgentSettled` reports
  `aborted: this._agentRunAbortRequested`. This explains why P1 and P3's post-dispose
  `agent_settled` reads `aborted: false`.
  - **What keeps the R-row loop going is NOT ESTABLISHED.** Repeated post-dispose `context`
    dispatches are observed below; no `agent_before_settle` handler exists in any loaded package.

## Instrument

**Setup.**

- **Watchdog.** `run-bounded.sh` was extracted byte for byte from
  [`pi-1.0.0-characterization.md`](pi-1.0.0-characterization.md) § "The watchdog added after A11"
  (lines 610–628). Its SHA-256,
  `1114155f63fdd2ecb8616dbdf9a890de09b693deb5f6f3cf4aa7bf6fd94b0843`, was verified before use.
  `GRACE=60`, `CAP=330` on every row.
- **Auth.** `AUTHED=$(mktemp -d -t perk-2660-authed)` held only a copy of the main checkout's
  `.pi/agent/auth.json` (`openai` and `anthropic`, both `api_key`).
- **Engine temp root.** `PI_SUBAGENTS_TEMP_ROOT=$SCRATCH/subagents-tmp`.
- **Process model.** Every row is a fresh host process, launched from the implement session's
  `bash` in `$WT` through `run-row.sh` (verbatim below).
- **Model preflight** (not a row; `cd /tmp`, perk and pi-subagents not loaded):
  `pi --no-extensions --no-skills --no-context-files --no-session --no-tools --mode json --model
  anthropic/claude-haiku-5-5 -p "Reply with exactly OK"` → `"stopReason":"stop"`, usage
  `input 4 / output 4 / cacheWrite 732`, cost `0.0000939`, exit 0.

**The scrub** (inside `run-row.sh`): `env -u PERK_RUN_ID -u PERK_PROFILE_HANDOFF -u PERK_SELFCHECK
-u PERK_DISABLE_NATIVE_SDK_BRIDGE -u PERK_CLI_VERSION -u PI_SUBAGENT_CHILD -u PI_SUBAGENT_CHILD_AGENT
-u PI_SUBAGENT_EXTENSION_BINDINGS -u PI_SESSION_FILE -u PI_SESSION_ID -u PI_MODEL -u PI_PROVIDER -u
PI_REASONING_LEVEL -u PI_CODING_AGENT`, then `PERK_SKIP_VERSION_CHECK=1 PI_CODING_AGENT_DIR=$AUTHED
PI_SUBAGENTS_TEMP_ROOT=$SCRATCH/subagents-tmp`.

**The launch line** (every row; `<row> <mode> <wait>` from `run-row.sh`'s arguments):

```text
$SCRATCH/run-bounded.sh $SCRATCH/<row>.log ~/.local/share/mise/installs/node/26.3.0/bin/pi --approve --mode json \
  --model anthropic/claude-haiku-5-5 --session-dir $SCRATCH/sessions/<row> -e $SCRATCH/probe-spawn.ts \
  -p "/probe-spawn script anthropic/claude-haiku-5-5 <mode> <wait>"
```

**The dirty-tree trigger.** `run-row.sh` runs `touch "$WT/PERK-2660-DIRTY-MARKER"` before every
`missingbase` row; the marker is untracked and never added. Every row's `git status --porcelain`
is quoted in its block. The tables commit `7f335793` left the tree otherwise clean, so the marker
is the only dirt in the perk arm. The no-perk arm adds the ` M .pi/settings.json` edit.

**The no-perk arm (X3).** One edit window, 20:11:18Z → 20:15:31Z, held R2, R2-r2, P3, P4, R2t and
the P4 re-run.

```text
=== X3 edit #1 2026-10-19T20:11:18Z
before: 7d9749d98ae1d94f41d64958b1e65ad646d44715175abe73bb0206fe2b0f0516  .pi/settings.json
after edit: c9f7d17efa9cc9bc43a8b451181219194dfe9c17436f742eb7bb1be6e4a3b889  .pi/settings.json
packages=["npm:@tombell/pi-diff","npm:pi-subagents@0.76.1","npm:@ff-labs/pi-fff","npm:pi-web-access",{"source":"npm:@plannotator/pi-extension"},{"source":"npm:@juicesharp/rpiv-todo"},{"source":"npm:@juicesharp/rpiv-ask-user-question"},{"source":"npm:@dietrichgebert/ponytail","extensions":[],"skills":[],"prompts":[],"themes":[]}]
=== restore #1 2026-10-19T20:15:31Z git checkout -- .pi/settings.json
after restore: 7d9749d98ae1d94f41d64958b1e65ad646d44715175abe73bb0206fe2b0f0516  .pi/settings.json
```

The edit was `sed -i '' '/^    "\.\.",$/d' .pi/settings.json`, which drops line 3, `"..",`. No
`/reload` was issued.

How the arms differ, read from every row's evidence:

- **Perk in the parent.** Perk-arm parents persist `perk:workflow-state` and `perk:agent-scratch`
  entries; no-perk parents have neither.
- **Perk in the child.** In the perk arm, the restricted child's `output-0.log` carries
  `[READ-ONLY MODE]`: `72a2b179…` (P1) and `f3e8ccb5…` (P1 re-run) each have 1 occurrence. In the
  no-perk arm the count is 0 (`18fd1be1…` P3, `aa6a1bd4…` P4), so perk is absent there too.
- **The agent still resolves without perk.** `perk.scout` resolves in the no-perk arm: pi-subagents
  discovers package agents from the project root's own `package.json` (`src/agents/agents.js`,
  `packageRoots = [{ root: projectRoot, scope: "root" }]`) as well as from settings packages.

**The probe** (`$SCRATCH/probe-spawn.ts`, SHA-256
`cfe598a7f1c1826b4bde4d1122d0b3ae8e5cd8e52c1050e5398c4cc90f1d3e16`, verbatim). Its base is the
0.75.0 record's probe, extracted byte for byte from
[`pi-subagents-0.75.0-reverify.md`](pi-subagents-0.75.0-reverify.md) § "The probe extension"
(base SHA-256 `72cb2372580b80137a727ae2a19430770d05a2211cfb78cb7346563bf7ec6d2d`). The additions
over the base are listed after the listing.

```ts
// .perk-characterization/probe-spawn.ts — throwaway; drives pi-subagents' v1 RPC exactly as
// extension/waves/rpcAdapter.ts does (same envelope; the run handle lives in data.details), with
// the spawn key, a pinned lane model and a lane mode, and waits for the run to settle so the
// in-process workflow host is not killed by print-mode exit.
//   /probe-spawn <script|workflowScript> <provider/model> [restricted|badmodel|missingbase]
// Auto-fire (SDK worker rows): PERK_PROBE_AUTO="<key> <model> [mode]" runs the same ping → spawn →
// settle from session_start and writes PERK_PROBE_DONE (a JSON file) when it finishes.
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const REQUEST = "subagents:rpc:v1:request";
const REPLY = "subagents:rpc:v1:reply:";
const log = (label: string, value: unknown) =>
  console.error(`probe: ${label} ${JSON.stringify(value, null, 2)}`);

interface Reply {
  success?: boolean;
  data?: { text?: string; details?: { asyncId?: string; asyncDir?: string } };
  error?: { code?: string; message?: string };
}

function call(pi: ExtensionAPI, method: string, params?: unknown, timeoutMs = 30_000): Promise<Reply> {
  const requestId = randomUUID();
  return new Promise((resolve) => {
    const off = pi.events.on(`${REPLY}${requestId}`, (data: unknown) => {
      clearTimeout(timer);
      off();
      resolve(data as Reply);
    });
    const timer = setTimeout(() => { off(); resolve({ error: { code: "probe-timeout", message: method } }); }, timeoutMs);
    pi.events.emit(REQUEST, { version: 1, requestId, method, ...(params === undefined ? {} : { params }), source: { extension: "perk-probe" } });
  });
}

const TERMINAL = new Set(["complete", "completed", "failed", "partial", "stopped", "cancelled", "error"]);
async function settle(asyncDir: string, timeoutMs = 180_000): Promise<unknown> {
  const statusPath = join(asyncDir, "status.json");
  const until = Date.now() + timeoutMs;
  let last: unknown = null;
  while (Date.now() < until) {
    if (existsSync(statusPath)) {
      last = JSON.parse(readFileSync(statusPath, "utf8"));
      const state = (last as { state?: string }).state ?? "";
      if (TERMINAL.has(state)) return last;
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  return { probeTimeout: "settle", last };
}

// --- node 2.4 additions (deviation from the verbatim base): lifecycle observers + the wake-wait ---
// One-line JSON for the added labels so every lifecycle reading is exactly one log line; the
// `probe: ` prefix keeps run-bounded.sh's terminal-line detection unchanged (none of these labels
// is `status`, `probe-error` or `spawn(`, and compact JSON never prints `"success": false`).
const log1 = (label: string, value: unknown) => console.error(`probe: ${label} ${JSON.stringify(value)}`);
const WAKE_TEXT = "Subagent updates above.";
const STALE_TEXT = "This extension ctx is stale";
const life = {
  shutdownSeen: false,
  wakeSeenAt: null as string | null,
  assistantStartedAt: null as string | null,
  agentStart: [] as string[],
  agentEnd: [] as string[],
  agentSettled: [] as Array<{ at: string; aborted: unknown }>,
};
function ctxStaleOf(ctx: unknown): boolean | string {
  if (ctx === undefined || ctx === null) return "n/a";
  try {
    void (ctx as { hasUI: unknown }).hasUI;
    return false;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return message.includes(STALE_TEXT) ? true : `other-throw: ${message.slice(0, 120)}`;
  }
}
function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content))
    return content.map((part) => (part && typeof part === "object" && (part as { type?: unknown }).type === "text" ? String((part as { text?: unknown }).text ?? "") : "")).join("");
  return "";
}
function usageOf(usage: unknown): unknown {
  if (!usage || typeof usage !== "object") return undefined;
  const u = usage as { input?: number; output?: number; cacheRead?: number; cacheWrite?: number; totalTokens?: number; cost?: { total?: number } };
  return { input: u.input, output: u.output, cacheRead: u.cacheRead, cacheWrite: u.cacheWrite, totalTokens: u.totalTokens, costTotal: u.cost?.total };
}
function censusOf(entries: unknown[]): unknown[] {
  return entries.map((raw) => {
    const entry = raw as { type?: string; customType?: string; message?: { role?: string; content?: unknown; stopReason?: string; usage?: unknown; errorMessage?: string } };
    const row: Record<string, unknown> = { type: entry.type };
    if (entry.customType !== undefined) row.customType = entry.customType;
    const message = entry.message;
    if (entry.type === "message" && message) {
      row.role = message.role;
      if (message.stopReason !== undefined) row.stopReason = message.stopReason;
      if (message.usage !== undefined) row.usage = usageOf(message.usage);
      if ((message.stopReason === "error" || message.stopReason === "aborted") && message.errorMessage)
        row.errorMessage = String(message.errorMessage).slice(0, 200);
      if (message.role === "user" && textOf(message.content) === WAKE_TEXT) row.text = WAKE_TEXT;
    }
    return row;
  });
}
function lifecycle(event: string, ctx: unknown, detail: unknown): void {
  log1("lifecycle", { event, at: new Date().toISOString(), afterShutdown: life.shutdownSeen, ctxStale: ctxStaleOf(ctx), detail });
}
function observeLifecycle(pi: ExtensionAPI): void {
  pi.on("session_shutdown", (event, ctx) => {
    lifecycle("session_shutdown", ctx, { reason: (event as { reason?: unknown }).reason });
    let census: unknown;
    try {
      census = censusOf(ctx.sessionManager.getBranch() as unknown[]);
    } catch (error) {
      census = { censusError: error instanceof Error ? error.message : String(error) };
    }
    log1("shutdown-census", census);
    life.shutdownSeen = true;
  });
  pi.on("agent_start", (_event, ctx) => {
    life.agentStart.push(new Date().toISOString());
    lifecycle("agent_start", ctx, {});
  });
  pi.on("agent_end", (event, ctx) => {
    life.agentEnd.push(new Date().toISOString());
    const messages = ((event as { messages?: Array<{ role?: string; stopReason?: string }> }).messages ?? []);
    lifecycle("agent_end", ctx, { messages: messages.length, assistantStopReasons: messages.filter((m) => m.role === "assistant").map((m) => m.stopReason) });
  });
  pi.on("agent_settled", (event, ctx) => {
    const aborted = (event as { aborted?: unknown }).aborted;
    life.agentSettled.push({ at: new Date().toISOString(), aborted });
    lifecycle("agent_settled", ctx, { aborted });
  });
  pi.on("message_start", (event, ctx) => {
    const message = (event as { message?: { role?: string; content?: unknown } }).message;
    const role = message?.role;
    const at = new Date().toISOString();
    const isWake = role === "user" && textOf(message?.content) === WAKE_TEXT;
    if (isWake && life.wakeSeenAt === null) life.wakeSeenAt = at;
    if (role === "assistant" && life.assistantStartedAt === null) life.assistantStartedAt = at;
    lifecycle("message_start", ctx, { role, ...(isWake ? { text: WAKE_TEXT } : {}) });
  });
  pi.on("context", (event, ctx) => {
    lifecycle("context", ctx, { messages: ((event as { messages?: unknown[] }).messages ?? []).length });
    return undefined;
  });
}
async function waitForWakeSettle(): Promise<void> {
  const started = Date.now();
  while (life.agentSettled.length === 0 && Date.now() - started < 120_000) await new Promise((r) => setTimeout(r, 250));
  log1("wake-wait", {
    wakeSeenAt: life.wakeSeenAt,
    assistantStartedAt: life.assistantStartedAt,
    agentStart: life.agentStart,
    agentEnd: life.agentEnd,
    agentSettled: life.agentSettled,
    waitedMs: Date.now() - started,
    timedOut: life.agentSettled.length === 0,
  });
}
// --- end of node 2.4 additions ---

async function probe(pi: ExtensionAPI, key: string, model: string, mode: string, wait = "return"): Promise<{ outcome: string; asyncDir?: string; reply?: Reply }> {
  const item = {
    key: "probe", agent: "perk.scout", label: "probe", worktree: false,
    model: mode === "badmodel" ? "perk-probe/does-not-exist" : model,
    task: "Reply with exactly the single word OK and nothing else. Do not read any file.",
    ...(mode === "restricted" ? { extensionBindings: { "perk.parent-restrictions/1": { readOnly: true } } } : {}),
    ...(mode === "missingbase" ? { worktree: true, baseRef: "refs/heads/perk-probe-missing" } : {}),
  };
  const script =
    `const reports = await runs.all(${JSON.stringify([item], null, 2)});\n` +
    "return reports.map(({key, ok, error, structuredOutput}) => ({key, ok, error: error ?? null, report: structuredOutput ?? null}));";
  log("env", Object.fromEntries(Object.entries(process.env).filter(([k]) => /^(PI_|PERK_)/.test(k))));
  log("ping", await call(pi, "ping"));
  let reply: Reply = {};
  for (let attempt = 1; attempt <= 10; attempt += 1) {
    reply = await call(pi, "spawn", {
      [key]: script, async: true, mission: false, context: "fresh", model,
      acceptance: { level: "none", reason: "characterization probe" },
      intercomBridge: { mode: "off" }, timeoutMs: 120_000,
    });
    if (reply.error?.code !== "no_active_session") break;
    log("spawn-retry", { attempt, reply });
    await new Promise((r) => setTimeout(r, 1000));
  }
  log(`spawn(${key}, ${model}${mode ? `, ${mode}` : ""})`, reply);
  if (reply.success !== true) return { outcome: "spawn-rejected", reply };
  const details = reply.data?.details;
  if (typeof details?.asyncId !== "string" || typeof details?.asyncDir !== "string") {
    log("probe-error", "success reply without data.details.asyncId/asyncDir — handle extraction wrong, fix the probe");
    process.exitCode = 2;
    return { outcome: "probe-error", reply };
  }
  const settled = await settle(details.asyncDir);
  log1("settled-at", { at: new Date().toISOString() });
  if (wait === "settle") await waitForWakeSettle();
  log("status", settled);
  return { outcome: "settled", asyncDir: details.asyncDir, reply };
}

export default function (pi: ExtensionAPI) {
  observeLifecycle(pi);
  pi.registerCommand("probe-spawn", {
    description: "characterization probe: ping + spawn one scout lane via the v1 RPC",
    handler: async (args) => {
      const [key = "script", model = "", mode = "", wait = "return"] = args.trim().split(/\s+/);
      if (!model) { log("probe-error", "usage: /probe-spawn <script|workflowScript> <provider/model> [restricted|badmodel|missingbase] [return|settle]"); process.exitCode = 2; return; }
      if (wait !== "return" && wait !== "settle") { log("probe-error", `wait must be return|settle, got ${wait}`); process.exitCode = 2; return; }
      await probe(pi, key, model, mode, wait);
    },
  });
  const auto = process.env.PERK_PROBE_AUTO;
  if (auto) {
    let fired = false;
    pi.on("session_start", () => {
      if (fired) return;
      fired = true;
      const [key = "script", model = "", mode = ""] = auto.trim().split(/\s+/);
      const done = process.env.PERK_PROBE_DONE ?? "probe-done.json";
      log("auto", { key, model, mode, done });
      setTimeout(() => {
        void probe(pi, key, model, mode).then(
          (result) => writeFileSync(done, JSON.stringify({ at: new Date().toISOString(), ...result }, null, 2)),
          (error: unknown) => writeFileSync(done, JSON.stringify({ at: new Date().toISOString(), outcome: "probe-threw", error: String(error) }, null, 2)),
        );
      }, 1000);
    });
  }
}
```

Additions over the verbatim base (each a deviation from it; the base `log` helper is untouched):

1. **Fourth argument.** A fourth positional argument `wait` ∈ {`return`, `settle`}, default
   `return`, validated, and threaded into `probe(…, wait)`.
2. **Lifecycle observers.** They are registered at load (`observeLifecycle`), one line each
   through a one-line JSON helper `log1`, all with the `probe: ` prefix:
   - `session_shutdown`, which also logs `probe: shutdown-census` — the branch reduced to
     `{type, role?, customType?, stopReason?, usage?, text?}`, plus a truncated `errorMessage` for
     error/aborted assistants;
   - `agent_start`, `agent_end`, `agent_settled` (with `aborted`);
   - `message_start` (sets `wakeSeenAt` / `assistantStartedAt`);
   - `context` (returns `undefined`).

   There is no `turn_end` handler. `ctxStale` reads `ctx.hasUI` in try/catch: `true` on the stale
   text, `false`, `"n/a"` without a ctx, or `other-throw: …` (never observed).
3. **After `settle(...)`.** The probe logs `probe: settled-at`. In `settle` mode it polls every
   250 ms until `agent_settled` was seen once or 120 s pass, then logs `probe: wake-wait`.
   `probe: status` (base `log`, pretty JSON) stays the last line before `probe()` returns.
4. **Lane items.** `missingbase` / `restricted` / `badmodel` are the base's items, unchanged.

`log1` prints compact JSON, so no added line can match the watchdog's terminal tests.
`^probe: status` and `^probe: probe-error` are base labels, and compact JSON never prints
`"success": false` with a space.

**`run-row.sh`** (SHA-256 `70a92cd1fd5d6dbd4eea638a7e522270a13c6b9ca67c6a4d1e8b966b8ca00f87`, verbatim):

```bash
#!/usr/bin/env bash
# run-row.sh <row> <restricted|badmodel|missingbase> <return|settle> — one fresh-process row (node 2.4).
S=$(cd "$(dirname "$0")" && pwd); WT=$(git -C "$S" rev-parse --show-toplevel); AUTHED=$(cat "$S/AUTHED.path")
row=$1; mode=$2; wait=$3; MODEL=${MODEL:?}
[ -e "$S/$row.log" ] && { echo "refusing: $S/$row.log exists"; exit 2; }
if [ "$mode" = missingbase ]; then touch "$WT/PERK-2660-DIRTY-MARKER"; fi
mkdir -p "$S/sessions/$row" "$S/subagents-tmp/async-subagent-runs"
ls "$S/subagents-tmp/async-subagent-runs" > "$S/$row.runs-before"
{
  echo "row=$row mode=$mode wait=$wait start=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "settings.json sha256: $(shasum -a 256 "$WT/.pi/settings.json" | cut -d' ' -f1)"
  echo "git status --porcelain:"; git -C "$WT" status --porcelain | sed 's/^/  /'
} > "$S/$row.meta"
cd "$WT" || exit 2
GRACE=60 CAP=330 env -u PERK_RUN_ID -u PERK_PROFILE_HANDOFF -u PERK_SELFCHECK -u PERK_DISABLE_NATIVE_SDK_BRIDGE \
  -u PERK_CLI_VERSION -u PI_SUBAGENT_CHILD -u PI_SUBAGENT_CHILD_AGENT -u PI_SUBAGENT_EXTENSION_BINDINGS \
  -u PI_SESSION_FILE -u PI_SESSION_ID -u PI_MODEL -u PI_PROVIDER -u PI_REASONING_LEVEL -u PI_CODING_AGENT \
  PERK_SKIP_VERSION_CHECK=1 PI_CODING_AGENT_DIR="$AUTHED" PI_SUBAGENTS_TEMP_ROOT="$S/subagents-tmp" \
  "$S/run-bounded.sh" "$S/$row.log" \
  "$(which pi)" --approve --mode json --model "$MODEL" --session-dir "$S/sessions/$row" \
  -e "$S/probe-spawn.ts" -p "/probe-spawn script $MODEL $mode $wait"
echo "end=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$S/$row.meta"
tail -1 "$S/$row.log"
```

**`read-row.sh`** (final form; SHA-256 `876a341a02a04e17bf735359f6f66f4aed4836b93e56c2a01af3ac04bc49bbd5`,
verbatim). Every reading below comes from this version, re-run over each row's preserved log, run
directories and session directory after the last row.

```bash
#!/usr/bin/env bash
# read-row.sh <scratch> <row> — the fixed per-row readings (node 2.4). Reads only: the row log,
# the row's async run dirs (keyed by the spawn reply's asyncId), and the row's --session-dir.
S=$1; row=$2; log="$S/$row.log"; runs="$S/subagents-tmp/async-subagent-runs"
echo "=== row $row"
echo "--- exit line:"; grep -E '^exit=[0-9]+ elapsed=' "$log" || echo "(none)"
echo "--- watchdog lines:"; grep '^watchdog:' "$log" || echo "(none)"
echo "--- counts:"
printf '  stale-ctx=%s (of which Extension-error lines=%s)\n' "$(grep -c 'This extension ctx is stale' "$log")" "$(grep -c '^Extension error (.*): This extension ctx is stale' "$log")"
printf '  boundary=%s\n' "$(grep -c 'turn_end could not resolve the persisted assistant entry ID' "$log")"
printf '  loadout-presentation-failed=%s\n' "$(grep -c 'perk: loadout presentation failed' "$log")"
printf '  assistant-message_start=%s\n' "$(grep '"type":"message_start"' "$log" | grep -c '"message":{"role":"assistant"')"
echo "--- trigger lines (first of each):"
grep -m1 -o 'Worktree admission failed[^"]*' "$log" || echo "  (no Worktree admission failed in log)"
grep -m1 -o "Unknown subagent model[^\"]*" "$log" || echo "  (no Unknown subagent model in log)"
echo "--- spawn reply (first lines):"; grep -A3 -m1 '^probe: spawn(' "$log" | tr -s ' ' | tr '\n' ' '; echo
echo "--- probe lifecycle / settled-at / wake-wait / shutdown-census (log order):"
grep -E '^probe: (lifecycle|settled-at|wake-wait|shutdown-census) ' "$log" || echo "(none)"
echo "--- Extension error lines (log order, deduped consecutive):"
grep -E '^Extension error|^perk: ' "$log" | uniq -c || echo "(none)"
echo "--- async run dirs of this row (workflow = the spawn reply's asyncId; children = its workflowChildren runIds):"
wf=$(grep -m1 -o '"asyncId": "[^"]*"' "$log" | cut -d'"' -f4)
kids=""; [ -n "$wf" ] && [ -f "$runs/$wf/status.json" ] && kids=$(node -e 'const s=JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")); console.log((s.workflowChildren?.children??[]).map(c=>c.runId).filter(Boolean).join(" "))' "$runs/$wf/status.json")
if [ -z "$wf" ]; then echo "(no asyncId in the spawn reply)"; fi
for d in $wf $kids; do
  if [ ! -d "$runs/$d" ]; then echo "  [$d] no directory"; continue; fi
  echo "  [$d] files: $(ls "$runs/$d" | tr '\n' ' ')"
  if [ -f "$runs/$d/status.json" ]; then
    node -e '
const s=JSON.parse(require("fs").readFileSync(process.argv[1],"utf8"));
const pick={mode:s.mode,state:s.state,pid:s.pid,totalCost:s.totalCost,runFanoutBudget:s.runFanoutBudget,steps:(s.steps??[]).map(x=>({agent:x.agent,status:x.status,async:x.async}))};
console.log("    status.json "+JSON.stringify(pick));
if(s.workflow?.value!==undefined) console.log("    lanes="+JSON.stringify(s.workflow.value));
if(s.workflowChildren) console.log("    workflowChildren="+JSON.stringify(s.workflowChildren.children));' "$runs/$d/status.json"
  fi
done
echo "--- session dir ($S/sessions/$row):"
f=$(ls "$S/sessions/$row"/*.jsonl 2>/dev/null | head -1)
if [ -z "$f" ]; then echo "  not flushed"; else
  node -e '
const lines=require("fs").readFileSync(process.argv[1],"utf8").split("\n").filter(Boolean).map(JSON.parse);
const counts={};
for(const e of lines){const k=e.type+(e.message?.role?":"+e.message.role:"")+(e.customType?":"+e.customType:"");counts[k]=(counts[k]??0)+1;}
console.log("  file "+process.argv[1].split("/").pop()+" counts="+JSON.stringify(counts));
const text=(c)=>typeof c==="string"?c:Array.isArray(c)?c.map(p=>p?.type==="text"?p.text:"").join(""):"";
for(const e of lines){
  if(e.type==="message"&&e.message.role==="user") console.log("  user: "+JSON.stringify(text(e.message.content).slice(0,120)));
  if(e.type==="custom_message") console.log("  custom_message "+e.customType+": "+JSON.stringify(text(e.content).slice(0,240)));
  if(e.type==="message"&&e.message.role==="assistant"){const u=e.message.usage??{};console.log("  assistant stopReason="+e.message.stopReason+" usage="+JSON.stringify({input:u.input,output:u.output,cacheRead:u.cacheRead,cacheWrite:u.cacheWrite,cost:u.cost?.total})+(e.message.errorMessage?" error="+JSON.stringify(String(e.message.errorMessage).slice(0,200)):""));}
}' "$f"
fi
echo "--- stderr tail (last 12 non-JSON lines):"
grep -v '^{' "$log" | tail -12
```

### Deviations from the plan's instrument

- **`$MODEL`.** It is `anthropic/claude-haiku-5-5`, not the 2.1 record's `claude-haiku-4-5`. The
  plan's rule is "the cheapest Anthropic model in the installed catalog", re-read at run time, and
  haiku-5-5 is ten times cheaper. A model preflight (above) confirmed the key could reach it before
  the first row.
- **`read-row.sh` was revised twice during the run.** Both fixes were mechanical; neither changes a
  log or a run directory.
  1. After R1, the lane rows moved from a non-existent `result.value` to `status.json`'s
     `workflow.value`.
  2. After the last row, the run directories are keyed by the spawn reply's `asyncId` and its
     `workflowChildren` run ids. The earlier "new since `<row>.runs-before`" listing is
     order-dependent once later rows add directories. The same revision added the split count of
     stale-ctx `Extension error` lines.

  `grep -c 'This extension ctx is stale'` also counts `perk: loadout presentation failed — Error:
  This extension ctx is stale …` lines, so the record quotes both numbers.
- **`run-row.sh` wraps the plan's launch line.** It adds the scrub, the marker, the per-row
  `.meta` (start/end, the `settings.json` hash, `git status --porcelain`) and a pre-row listing of
  the run directories. The listing is unused by the final `read-row.sh`.
- **One-line JSON for the added probe labels**, as described above.

## The fixed classification tables

These tables were committed to this record before the first live row ran. They are copied from
the plan (§2 and §3) without change. Later commits add readings; they never edit these tables.

### Exit class (evaluated in this order; the FIRST matching class is the row's class)

| Order | Class | Test |
| --- | --- | --- |
| 1 | `NOT STAGED` | the intended trigger did not fire: `missingbase` without the `Worktree admission failed` text; `badmodel` without `Unknown subagent model`; a runner started (`status.json` with `pid`) for a `missingbase`/`badmodel` row; `restricted` lane not `ok: true` or no runner; or the spawn reply `success: false` for a reason other than the trigger — re-run per the launch budget, never scored |
| 2 | `TRIGGER-ABSENT` | the trigger text is present AND the row has no wake evidence (none of the three wake signals below) |
| 3 | `LOOPS` | a `watchdog:` line is present (GRACE or CAP), whatever the exit code |
| 4 | `EXITS-NONZERO` | no `watchdog:` line, `exit≠0` |
| 5 | `EXITS` | no `watchdog:` line, `exit=0` |

**Wake evidence** for a row = any of: a `subagent-notify` / `subagent-incremental-child-notify`
custom entry in the shutdown census or the session file; a `message_start` for the user text
`Subagent updates above.`; or an `agent_start` lifecycle line.

### Arm class (R1 = perk, R2 = no-perk; each arm = its scored replicates)

`NOT STAGED` replicates never count. Precedence:

- (a) any `LOOPS` → arm `LOOPS` (annotated `INTERMITTENT` if another scored replicate is not
  `LOOPS`);
- (b) else every scored replicate `TRIGGER-ABSENT` → arm `TRIGGER-ABSENT`;
- (c) else any `EXITS`/`EXITS-NONZERO` → arm `EXITS` (annotated `TRIGGER-INTERMITTENT` when a
  replicate was `TRIGGER-ABSENT`; a non-zero code quoted);
- (d) fewer than two scored replicates after the budget → arm `UNSTAGED`.

Two replicates per arm. A third replicate runs only when the first two differ in class (budget
permitting).

### Post-terminal observables (P rows), per observable

| Class | Rule |
| --- | --- |
| `HOST` | present in the no-perk arm (whatever the perk arm shows) |
| `PERK-ADDITIVE` | present with perk, absent without |
| `ABSENT` | absent in both arms |

### P-row validity (checked in this order)

A failing row is re-run once per the launch budget; still failing → `INVALID`, its readings
recorded.

| Check | Rule |
| --- | --- |
| V1 staged | `restricted` lane `ok: true`, a runner started and `status.json` `complete` (else `NOT STAGED`) |
| V2 wake observed | `wakeSeenAt` set AND an `agent_start` lifecycle line (else `NO-WAKE`) |
| V3 (settle rows) settled | `wake-wait` has `timedOut: false` and `agentSettled.length ≥ 1` (else `WAKE-UNSETTLED`) |
| V4 (settle rows) SETTLED-OK | the shutdown census shows exactly one assistant entry after the wake user entry with `stopReason ∉ {error, aborted}`, provider-reported `usage.input + usage.output > 0`, and the last `agent_settled` has `aborted: false` (else `WAKE-FAILED` — provider request NOT ESTABLISHED on that row) |

### H predictions (P1/P3 = `return`, P2/P4 = `settle`)

- **Core.** C1: P1 and P3 each show `<boundary>` ≥ 1 and no non-aborted assistant entry in the
  census/file. C2: P2 and P4 each show `<boundary>` = 0 and stale-ctx = 0.
- **Secondary.** S1: P1 stale-ctx ≥ 1 and the probe's `context` and/or `agent_settled` lifecycle
  lines show `afterShutdown: true, ctxStale: true`. S2: P3 stale-ctx = 0. S3: P2 and P4 are
  SETTLED-OK with exactly one assistant entry. S4: P2 shows `loadout presentation failed` = 0 and
  no lifecycle line with `ctxStale: true`.

### H verdict (closed vocabulary; evaluated in this order)

1. `INCONCLUSIVE` — any P row `INVALID` or NOT RUN (the valid rows' readings are still recorded
   and classified `HOST`/`PERK-ADDITIVE`/`ABSENT` where both arms exist).
2. `FALSIFIED` — all rows valid and any core prediction fails.
3. `PARTIAL` — all rows valid, every core prediction holds, at least one secondary prediction
   fails (each failing cell named).
4. `CONFIRMED` — all rows valid, every prediction holds.

### The rows

| Row | Arm | Lane | Probe mode | Replicates | Required |
| --- | --- | --- | --- | --- | --- |
| R1 | perk loaded | `missingbase` (refused at worktree admission) | `return` | 2 (R1, R1-r2) | yes |
| R2 | no-perk (X3) | `missingbase` | `return` | 2 (R2, R2-r2) | yes |
| R3 | perk loaded | `badmodel` (the other pre-spawn failure) | `return` | 1 | no |
| R4 = P1 | perk loaded | `restricted` (`worktree: false` + packet) | `return` | 1 | yes |
| P2 | perk loaded | `restricted` | `settle` | 1 | yes |
| P3 | no-perk (X3) | `restricted` | `return` | 1 | yes |
| P4 | no-perk (X3) | `restricted` | `settle` | 1 | yes |
| R1t / R2t (conditional) | as R1 / R2 | `missingbase` | `settle` | 1 each, ONLY if the matching arm is `LOOPS`; never scored for the disposition | no |

**H predictions per P row (pre-registered):**

| Row | Prediction under H |
| --- | --- |
| P1 (= R4) | C1 + S1: stale-ctx ≥ 1, `<boundary>` = 1, assistant `message_start` = 0, census has the wake user entry and NO non-aborted assistant entry; lifecycle `context`/`agent_settled` lines after `session_shutdown` read `ctxStale: true`; `EXITS` |
| P2 | C2 + S3 + S4: `wake-wait` `timedOut: false`; stale-ctx = 0, `<boundary>` = 0, `loadout presentation failed` = 0, no `ctxStale: true` line; exactly one SETTLED-OK assistant entry after the wake user entry; `EXITS` |
| P3 | C1 + S2: stale-ctx = 0, `<boundary>` = 1, no non-aborted assistant entry; `EXITS` |
| P4 | C2 + S3: stale-ctx = 0, `<boundary>` = 0, one SETTLED-OK assistant entry; `EXITS` |

### Launch budget, retry priority and endpoint

9 mandatory launches (R1, R1-r2, R2, R2-r2, R3, R4/P1, P2, P3, P4), ≤ 2 conditional (R1t, R2t),
≤ 5 re-runs/third replicates — ≤ 16 parent launches and ≤ 60 min live wall in total. Re-runs are
allocated in this priority: the R1/R2 arms (staging, then a third replicate on disagreement) >
P2/P4 > P1/P3 > R3 > R1t/R2t. A row gets at most ONE re-run.

**Endpoint.** When the budget or wall is exhausted, unrun rows are `NOT RUN`. If a required row is
`NOT RUN`, an R arm is `UNSTAGED`, or a P row is `INVALID`, the record still lands with every
reading as measured. The #2660 disposition is then **`UNRESOLVED`** (no comment, no close, no
follow-up — the operator decides), and H is `INCONCLUSIVE`. The PR body names the unresolved items.
A missing R3, R1t or R2t never affects the disposition.

### Disposition rule (the two arm classes decide, nothing else)

| R1 (perk) | R2 (no-perk) | Disposition text (the record + the #2660 comment) | GitHub action |
| --- | --- | --- | --- |
| `LOOPS` | `LOOPS` | Persists on Pi 1.1.0 + pi-subagents 0.76.1 and reproduces without perk: an upstream limitation of the print-mode parent after a refused lane's wake; outside perk's report path (`worktree: false` on every lane); no perk regression, no repair | comment + close |
| `LOOPS` | `EXITS` | Perk-attributable on the exact pair (the no-perk control exits); NOT repaired here; follow-up issue filed | file the follow-up, then comment + close #2660 pointing at it |
| `LOOPS` | `TRIGGER-ABSENT` | A loop observed only with perk loaded; without perk the refused lane never woke the parent, so upstream-only cannot be shown — treated as perk-attributable; NOT repaired here; follow-up filed with the asymmetry quoted | file the follow-up, then comment + close #2660 pointing at it |
| `EXITS` | `LOOPS` | Reproduces only without perk: upstream limitation; perk's extension is not the cause and masks nothing perk-supported | comment + close |
| `EXITS` | `EXITS` | No longer reproduces on the exact pair (measured on every scored replicate; no release-note inference) | comment + close |
| `EXITS` | `TRIGGER-ABSENT` | No loop observed on the pair: with perk the refused lane wakes the parent, which exits; without perk it never woke the parent (quoted) | comment + close |
| `TRIGGER-ABSENT` | `LOOPS` | Reproduces only without perk (with perk the refused lane never woke the parent): upstream limitation | comment + close |
| `TRIGGER-ABSENT` | `EXITS` | No loop observed on the pair (asymmetric trigger presence quoted) | comment + close |
| `TRIGGER-ABSENT` | `TRIGGER-ABSENT` | The refused lane no longer wakes the print-mode parent on this pair in either arm (the measured refusal path quoted); #2660's shape is unreachable | comment + close |
| `UNSTAGED` in either arm | — | `UNRESOLVED` | none |

## R rows

Scored replicates use probe mode `return`, the 0.75.0/X1b method. R1t and R2t (mode `settle`) ran
because their arms classified `LOOPS`, and are never scored.

| Row | Arm | Lane / mode | Trigger text | Pre-spawn signature | Wake evidence | `watchdog:` | Exit | Class |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R1 | perk | `missingbase` / `return` | `Worktree admission failed …` | no child run id, fan-out `used: 0`, the workflow dir only | notice + wake user entry + `agent_start` | GRACE, at 67 s | `exit=143 elapsed=72s` | `LOOPS` |
| R1-r2 | perk | `missingbase` / `return` | same | same | same | GRACE, at 67 s | `exit=143 elapsed=72s` | `LOOPS` |
| R2 | no-perk | `missingbase` / `return` | same | same | same | GRACE, at 67 s | `exit=143 elapsed=72s` | `LOOPS` |
| R2-r2 | no-perk | `missingbase` / `return` | same | same | same | GRACE, at 74 s | `exit=143 elapsed=79s` | `LOOPS` |
| R3 | perk | `badmodel` / `return` | `Unknown subagent model 'perk-probe/does-not-exist' …` | child run id `761c09a2…` with **no directory**, fan-out `used: 1` | same | GRACE, at 65 s | `exit=143 elapsed=70s` | `LOOPS` |
| R1t | perk | `missingbase` / `settle` | `Worktree admission failed …` | as R1 | same; the wake turn settles before return | none | `exit=0 elapsed=12s` | `EXITS` (unscored) |
| R2t | no-perk | `missingbase` / `settle` | same | as R1 | same | none | `exit=0 elapsed=11s` | `EXITS` (unscored) |

No R row is `NOT STAGED`: every spawn reply was `"success": true`, every trigger text is present, and no child runner started (no child directory at all).

Error counts (the split from `read-row.sh`). "Post-shutdown `context`" is the probe's count of
`context` lifecycle lines with `afterShutdown: true`.

| Row | `<boundary>` `turn_end …` | perk `Extension error (…index.ts): … stale` | `perk: loadout presentation failed` | post-shutdown `context` | assistant `message_start` on stdout |
| --- | --- | --- | --- | --- | --- |
| R1 | 15 | 15 | 14 | 15 | 0 |
| R1-r2 | 20 | 20 | 19 | 20 | 0 |
| R2 | 13 | 0 | 0 | 13 | 0 |
| R2-r2 | 18 | 0 | 0 | 18 | 0 |
| R3 | 13 | 13 | 12 | 13 | 1 |
| R1t | 0 | 0 | 0 | 0 | 2 |
| R2t | 0 | 0 | 0 | 0 | 2 |

**Arm classes.**

- **R1 (perk) = `LOOPS`.** Two of two scored replicates are `LOOPS`, so there is no annotation.
- **R2 (no-perk) = `LOOPS`.** Two of two.

The replicates agree, so no third replicate ran.

**What the loop looks like.**

- **Dispatches.** After `session_shutdown`, the host dispatches `context` again and again: 13–20
  times before the watchdog's TERM. The first gap is 4.2–14.3 s, then dispatches come every
  2.2–5.8 s.
- **Context size.** The visible message count is constant: 3 in the perk arm (the child-failed
  notice, the wake user message, perk's scratch notice), 2 without perk (notice, wake).
- **Errors per dispatch.** `<boundary>` lines equal post-shutdown `context` dispatches in every R
  row; the first `<boundary>` comes from the in-flight wake turn ending, before the first
  post-shutdown `context`. In the perk arm, each dispatch also adds one perk stale-ctx line, and
  every dispatch but the last (cut off by TERM) adds one `loadout presentation failed` line.
- **Perk's share.** Perk's lines are symptoms of the loop, not its cause: R2/R2-r2 loop the same
  way with perk absent.
- **R3 ran further before dispose.** The wake turn's assistant message had started streaming
  before dispose (`message_start` `assistant` at 20:07:39.493Z; shutdown at 20:07:40.288Z), and R3
  still loops.

### R1

```text
row=R1 mode=missingbase wait=return start=2026-10-19T20:04:06Z
settings.json sha256: 7d9749d98ae1d94f41d64958b1e65ad646d44715175abe73bb0206fe2b0f0516
git status --porcelain:
  ?? PERK-2660-DIRTY-MARKER
end=2026-10-19T20:05:19Z
probe: spawn(script, anthropic/claude-haiku-5-5, missingbase) { … "success": true, … "asyncId": "d396b442-0820-4e4d-80cd-2f3946ce3f26",
probe: lifecycle {"event":"agent_start","at":"2026-10-19T20:04:10.176Z","afterShutdown":false,"ctxStale":false,"detail":{}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:04:10.176Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"system"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:04:10.177Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"user","text":"Subagent updates above."}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:04:10.178Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"custom"}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:04:10.193Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":3}}
probe: settled-at {"at":"2026-10-19T20:04:11.933Z"}
probe: lifecycle {"event":"session_shutdown","at":"2026-10-19T20:04:11.934Z","afterShutdown":false,"ctxStale":false,"detail":{"reason":"quit"}}
probe: shutdown-census [{"type":"model_change"},{"type":"thinking_level_change"},{"type":"custom","customType":"perk:workflow-state"},{"type":"custom","customType":"plannotator"},{"type":"custom_message","customType":"subagent-incremental-child-notify"},{"type":"message","role":"system"},{"type":"message","role":"user","text":"Subagent updates above."},{"type":"custom_message","customType":"perk:agent-scratch"}]
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
probe: lifecycle {"event":"context","at":"2026-10-19T20:04:11.956Z","afterShutdown":true,"ctxStale":true,"detail":{"messages":3}}
Extension error ($WT/extension/index.ts): This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after … [Pi's stale message; elided]
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
perk: loadout presentation failed — Error: This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after … [Pi's stale message; elided]
probe: lifecycle {"event":"context","at":"2026-10-19T20:04:26.236Z","afterShutdown":true,"ctxStale":true,"detail":{"messages":3}}
Extension error ($WT/extension/index.ts): This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after … [Pi's stale message; elided]
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
perk: loadout presentation failed — Error: This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after … [Pi's stale message; elided]
[… 48 lines elided: 12 more iterations of the same group (one post-shutdown `context` lifecycle line + its error lines) …]
probe: lifecycle {"event":"context","at":"2026-10-19T20:05:12.706Z","afterShutdown":true,"ctxStale":true,"detail":{"messages":3}}
Extension error ($WT/extension/index.ts): This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after … [Pi's stale message; elided]
watchdog: pi still running 60s after the probe's terminal line (elapsed 67s) — TERM pgid 18157
exit=143 elapsed=72s
```

Lane (`d396b442-0820-4e4d-80cd-2f3946ce3f26` `status.json`): `workflow` `complete`, lanes `[{"key":"probe","ok":false,"error":"Worktree admission failed for 'probe' at $WT: worktree isolation requires a clean git working tree. Commit or stash changes first. Select the correct cwd or arrange an operator-approved commit/stash.","report":null}]`, `totalCost.costUsd` 0, fan-out used 0. Children: none recorded (no child run id: refused before a child run existed).

Session file (`2026-10-19T20-04-07-511Z_01a155c3-a4d6-711a-a3a1-0bc54159f731.jsonl`), entry sequence: `model_change → thinking_level_change → custom:perk:workflow-state → custom:plannotator → custom_message:subagent-incremental-child-notify → system → user → custom_message:perk:agent-scratch`.
- `subagent-incremental-child-notify` (display true): "Workflow child failed: **probe**\nWorkflow run: d396b442-0820-4e4d-80cd-2f3946ce3f26\nError: Worktree admission failed for 'probe' at $WT: worktree isolation requires a clean git working tree. Commit or stash changes first. Select the correct cwd or arrange an operator-approved commit/stash.\nStatus: workflow still running"

### R1-r2

```text
row=R1-r2 mode=missingbase wait=return start=2026-10-19T20:06:17Z
settings.json sha256: 7d9749d98ae1d94f41d64958b1e65ad646d44715175abe73bb0206fe2b0f0516
git status --porcelain:
  ?? PERK-2660-DIRTY-MARKER
end=2026-10-19T20:07:29Z
probe: spawn(script, anthropic/claude-haiku-5-5, missingbase) { … "success": true, … "asyncId": "31cada10-ae6a-4169-9531-b17d46b71921",
probe: lifecycle {"event":"agent_start","at":"2026-10-19T20:06:20.163Z","afterShutdown":false,"ctxStale":false,"detail":{}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:06:20.164Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"system"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:06:20.165Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"user","text":"Subagent updates above."}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:06:20.166Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"custom"}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:06:20.179Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":3}}
probe: settled-at {"at":"2026-10-19T20:06:21.941Z"}
probe: lifecycle {"event":"session_shutdown","at":"2026-10-19T20:06:21.943Z","afterShutdown":false,"ctxStale":false,"detail":{"reason":"quit"}}
probe: shutdown-census [{"type":"model_change"},{"type":"thinking_level_change"},{"type":"custom","customType":"perk:workflow-state"},{"type":"custom","customType":"plannotator"},{"type":"custom_message","customType":"subagent-incremental-child-notify"},{"type":"message","role":"system"},{"type":"message","role":"user","text":"Subagent updates above."},{"type":"custom_message","customType":"perk:agent-scratch"}]
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
probe: lifecycle {"event":"context","at":"2026-10-19T20:06:21.966Z","afterShutdown":true,"ctxStale":true,"detail":{"messages":3}}
Extension error ($WT/extension/index.ts): This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after … [Pi's stale message; elided]
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
perk: loadout presentation failed — Error: This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after … [Pi's stale message; elided]
probe: lifecycle {"event":"context","at":"2026-10-19T20:06:26.155Z","afterShutdown":true,"ctxStale":true,"detail":{"messages":3}}
Extension error ($WT/extension/index.ts): This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after … [Pi's stale message; elided]
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
perk: loadout presentation failed — Error: This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after … [Pi's stale message; elided]
[… 68 lines elided: 17 more iterations of the same group (one post-shutdown `context` lifecycle line + its error lines) …]
probe: lifecycle {"event":"context","at":"2026-10-19T20:07:23.834Z","afterShutdown":true,"ctxStale":true,"detail":{"messages":3}}
Extension error ($WT/extension/index.ts): This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after … [Pi's stale message; elided]
watchdog: pi still running 60s after the probe's terminal line (elapsed 67s) — TERM pgid 18769
exit=143 elapsed=72s
```

Lane (`31cada10-ae6a-4169-9531-b17d46b71921` `status.json`): `workflow` `complete`, lanes `[{"key":"probe","ok":false,"error":"Worktree admission failed for 'probe' at $WT: worktree isolation requires a clean git working tree. Commit or stash changes first. Select the correct cwd or arrange an operator-approved commit/stash.","report":null}]`, `totalCost.costUsd` 0, fan-out used 0. Children: none recorded (no child run id: refused before a child run existed).

Session file (`2026-10-19T20-06-17-891Z_01a155c5-a223-75ef-99db-b0181ce72502.jsonl`), entry sequence: `model_change → thinking_level_change → custom:perk:workflow-state → custom:plannotator → custom_message:subagent-incremental-child-notify → system → user → custom_message:perk:agent-scratch`.
- `subagent-incremental-child-notify` (display true): "Workflow child failed: **probe**\nWorkflow run: 31cada10-ae6a-4169-9531-b17d46b71921\nError: Worktree admission failed for 'probe' at $WT: worktree isolation requires a clean git working tree. Commit or stash changes first. Select the correct cwd or arrange an operator-approved commit/stash.\nStatus: workflow still running"

### R2

```text
row=R2 mode=missingbase wait=return start=2026-10-19T20:11:26Z
settings.json sha256: c9f7d17efa9cc9bc43a8b451181219194dfe9c17436f742eb7bb1be6e4a3b889
git status --porcelain:
   M .pi/settings.json
  ?? PERK-2660-DIRTY-MARKER
end=2026-10-19T20:12:38Z
probe: spawn(script, anthropic/claude-haiku-5-5, missingbase) { … "success": true, … "asyncId": "f4a02767-87e5-44b2-9809-037db214161b",
probe: lifecycle {"event":"agent_start","at":"2026-10-19T20:11:29.505Z","afterShutdown":false,"ctxStale":false,"detail":{}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:11:29.505Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"system"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:11:29.506Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"user","text":"Subagent updates above."}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:11:29.508Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":2}}
probe: settled-at {"at":"2026-10-19T20:11:31.255Z"}
probe: lifecycle {"event":"session_shutdown","at":"2026-10-19T20:11:31.256Z","afterShutdown":false,"ctxStale":false,"detail":{"reason":"quit"}}
probe: shutdown-census [{"type":"model_change"},{"type":"thinking_level_change"},{"type":"custom","customType":"plannotator"},{"type":"custom_message","customType":"subagent-incremental-child-notify"},{"type":"message","role":"system"},{"type":"message","role":"user","text":"Subagent updates above."}]
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
probe: lifecycle {"event":"context","at":"2026-10-19T20:11:31.272Z","afterShutdown":true,"ctxStale":true,"detail":{"messages":2}}
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
probe: lifecycle {"event":"context","at":"2026-10-19T20:11:42.839Z","afterShutdown":true,"ctxStale":true,"detail":{"messages":2}}
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
[… 20 lines elided: 10 more iterations of the same group (one post-shutdown `context` lifecycle line + its error lines) …]
probe: lifecycle {"event":"context","at":"2026-10-19T20:12:29.214Z","afterShutdown":true,"ctxStale":true,"detail":{"messages":2}}
watchdog: pi still running 60s after the probe's terminal line (elapsed 67s) — TERM pgid 21416
exit=143 elapsed=72s
```

Lane (`f4a02767-87e5-44b2-9809-037db214161b` `status.json`): `workflow` `complete`, lanes `[{"key":"probe","ok":false,"error":"Worktree admission failed for 'probe' at $WT: worktree isolation requires a clean git working tree. Commit or stash changes first. Select the correct cwd or arrange an operator-approved commit/stash.","report":null}]`, `totalCost.costUsd` 0, fan-out used 0. Children: none recorded (no child run id: refused before a child run existed).

Session file (`2026-10-19T20-11-26-936Z_01a155ca-5957-72a5-9a59-fba980a59051.jsonl`), entry sequence: `model_change → thinking_level_change → custom:plannotator → custom_message:subagent-incremental-child-notify → system → user`.
- `subagent-incremental-child-notify` (display true): "Workflow child failed: **probe**\nWorkflow run: f4a02767-87e5-44b2-9809-037db214161b\nError: Worktree admission failed for 'probe' at $WT: worktree isolation requires a clean git working tree. Commit or stash changes first. Select the correct cwd or arrange an operator-approved commit/stash.\nStatus: workflow still running"

### R2-r2

```text
row=R2-r2 mode=missingbase wait=return start=2026-10-19T20:12:44Z
settings.json sha256: c9f7d17efa9cc9bc43a8b451181219194dfe9c17436f742eb7bb1be6e4a3b889
git status --porcelain:
   M .pi/settings.json
  ?? PERK-2660-DIRTY-MARKER
end=2026-10-19T20:14:03Z
probe: spawn(script, anthropic/claude-haiku-5-5, missingbase) { … "success": true, … "asyncId": "2720cb21-a440-4a23-97a2-8bcfc460874a",
probe: lifecycle {"event":"agent_start","at":"2026-10-19T20:12:53.880Z","afterShutdown":false,"ctxStale":false,"detail":{}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:12:53.880Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"system"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:12:53.881Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"user","text":"Subagent updates above."}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:12:53.882Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":2}}
probe: settled-at {"at":"2026-10-19T20:12:55.657Z"}
probe: lifecycle {"event":"session_shutdown","at":"2026-10-19T20:12:55.658Z","afterShutdown":false,"ctxStale":false,"detail":{"reason":"quit"}}
probe: shutdown-census [{"type":"model_change"},{"type":"thinking_level_change"},{"type":"custom","customType":"plannotator"},{"type":"custom_message","customType":"subagent-incremental-child-notify"},{"type":"message","role":"system"},{"type":"message","role":"user","text":"Subagent updates above."}]
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
probe: lifecycle {"event":"context","at":"2026-10-19T20:12:55.675Z","afterShutdown":true,"ctxStale":true,"detail":{"messages":2}}
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
probe: lifecycle {"event":"context","at":"2026-10-19T20:13:02.431Z","afterShutdown":true,"ctxStale":true,"detail":{"messages":2}}
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
[… 30 lines elided: 15 more iterations of the same group (one post-shutdown `context` lifecycle line + its error lines) …]
probe: lifecycle {"event":"context","at":"2026-10-19T20:13:57.507Z","afterShutdown":true,"ctxStale":true,"detail":{"messages":2}}
watchdog: pi still running 60s after the probe's terminal line (elapsed 74s) — TERM pgid 21944
exit=143 elapsed=79s
```

Lane (`2720cb21-a440-4a23-97a2-8bcfc460874a` `status.json`): `workflow` `complete`, lanes `[{"key":"probe","ok":false,"error":"Worktree admission failed for 'probe' at $WT: worktree isolation requires a clean git working tree. Commit or stash changes first. Select the correct cwd or arrange an operator-approved commit/stash.","report":null}]`, `totalCost.costUsd` 0, fan-out used 0. Children: none recorded (no child run id: refused before a child run existed).

Session file (`2026-10-19T20-12-45-074Z_01a155cb-8a92-72e0-8d39-95f38d65a744.jsonl`), entry sequence: `model_change → thinking_level_change → custom:plannotator → custom_message:subagent-incremental-child-notify → system → user`.
- `subagent-incremental-child-notify` (display true): "Workflow child failed: **probe**\nWorkflow run: 2720cb21-a440-4a23-97a2-8bcfc460874a\nError: Worktree admission failed for 'probe' at $WT: worktree isolation requires a clean git working tree. Commit or stash changes first. Select the correct cwd or arrange an operator-approved commit/stash.\nStatus: workflow still running"

### R3

```text
row=R3 mode=badmodel wait=return start=2026-10-19T20:07:36Z
settings.json sha256: 7d9749d98ae1d94f41d64958b1e65ad646d44715175abe73bb0206fe2b0f0516
git status --porcelain:
  ?? PERK-2660-DIRTY-MARKER
end=2026-10-19T20:08:46Z
probe: spawn(script, anthropic/claude-haiku-5-5, badmodel) { … "success": true, … "asyncId": "9459d260-bf83-4708-884f-c639069c219b",
probe: lifecycle {"event":"agent_start","at":"2026-10-19T20:07:38.391Z","afterShutdown":false,"ctxStale":false,"detail":{}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:07:38.391Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"system"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:07:38.392Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"user","text":"Subagent updates above."}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:07:38.393Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"custom"}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:07:38.418Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":3}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:07:39.493Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"assistant"}}
probe: settled-at {"at":"2026-10-19T20:07:40.286Z"}
probe: lifecycle {"event":"session_shutdown","at":"2026-10-19T20:07:40.288Z","afterShutdown":false,"ctxStale":false,"detail":{"reason":"quit"}}
probe: shutdown-census [{"type":"model_change"},{"type":"thinking_level_change"},{"type":"custom","customType":"perk:workflow-state"},{"type":"custom","customType":"plannotator"},{"type":"custom_message","customType":"subagent-incremental-child-notify"},{"type":"message","role":"system"},{"type":"message","role":"user","text":"Subagent updates above."},{"type":"custom_message","customType":"perk:agent-scratch"}]
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
probe: lifecycle {"event":"context","at":"2026-10-19T20:07:40.307Z","afterShutdown":true,"ctxStale":true,"detail":{"messages":3}}
Extension error ($WT/extension/index.ts): This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after … [Pi's stale message; elided]
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
perk: loadout presentation failed — Error: This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after … [Pi's stale message; elided]
probe: lifecycle {"event":"context","at":"2026-10-19T20:07:48.254Z","afterShutdown":true,"ctxStale":true,"detail":{"messages":3}}
Extension error ($WT/extension/index.ts): This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after … [Pi's stale message; elided]
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
perk: loadout presentation failed — Error: This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after … [Pi's stale message; elided]
[… 40 lines elided: 10 more iterations of the same group (one post-shutdown `context` lifecycle line + its error lines) …]
probe: lifecycle {"event":"context","at":"2026-10-19T20:08:36.144Z","afterShutdown":true,"ctxStale":true,"detail":{"messages":3}}
Extension error ($WT/extension/index.ts): This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after … [Pi's stale message; elided]
watchdog: pi still running 60s after the probe's terminal line (elapsed 65s) — TERM pgid 19554
exit=143 elapsed=70s
```

Lane (`9459d260-bf83-4708-884f-c639069c219b` `status.json`): `workflow` `complete`, lanes `[{"key":"probe","ok":false,"error":"Unknown subagent model 'perk-probe/does-not-exist' in the active Pi model registry.","report":null}]`, `totalCost.costUsd` 0, fan-out used 1. Children: `761c09a2-436f-4b5a-84cc-1e5dad5aaa4e: no directory`.

Session file (`2026-10-19T20-07-36-429Z_01a155c6-d4ec-77f8-9cbd-1a598e7ee287.jsonl`), entry sequence: `model_change → thinking_level_change → custom:perk:workflow-state → custom:plannotator → custom_message:subagent-incremental-child-notify → system → user → custom_message:perk:agent-scratch`.
- `subagent-incremental-child-notify` (display true): "Workflow child failed: **probe**\nWorkflow run: 9459d260-bf83-4708-884f-c639069c219b\nError: Unknown subagent model 'perk-probe/does-not-exist' in the active Pi model registry.\nStatus: workflow still running"

### R1t

```text
row=R1t mode=missingbase wait=settle start=2026-10-19T20:16:14Z
settings.json sha256: 7d9749d98ae1d94f41d64958b1e65ad646d44715175abe73bb0206fe2b0f0516
git status --porcelain:
  ?? PERK-2660-DIRTY-MARKER
end=2026-10-19T20:16:26Z
probe: spawn(script, anthropic/claude-haiku-5-5, missingbase) { … "success": true, … "asyncId": "fd244ba6-4dca-4c7f-a665-512068d47299",
probe: lifecycle {"event":"agent_start","at":"2026-10-19T20:16:16.181Z","afterShutdown":false,"ctxStale":false,"detail":{}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:16:16.181Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"system"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:16:16.182Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"user","text":"Subagent updates above."}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:16:16.183Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"custom"}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:16:16.219Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":3}}
probe: settled-at {"at":"2026-10-19T20:16:17.948Z"}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:16:18.111Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"assistant"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:16:19.535Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"toolResult"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:16:19.538Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"custom"}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:16:19.559Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":6}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:16:22.222Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"assistant"}}
probe: lifecycle {"event":"agent_end","at":"2026-10-19T20:16:25.417Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":7,"assistantStopReasons":["toolUse","stop"]}}
probe: lifecycle {"event":"agent_settled","at":"2026-10-19T20:16:25.441Z","afterShutdown":false,"ctxStale":false,"detail":{"aborted":false}}
probe: wake-wait {"wakeSeenAt":"2026-10-19T20:16:16.182Z","assistantStartedAt":"2026-10-19T20:16:18.111Z","agentStart":["2026-10-19T20:16:16.181Z"],"agentEnd":["2026-10-19T20:16:25.417Z"],"agentSettled":[{"at":"2026-10-19T20:16:25.441Z","aborted":false}],"waitedMs":7529,"timedOut":false}
probe: lifecycle {"event":"session_shutdown","at":"2026-10-19T20:16:25.477Z","afterShutdown":false,"ctxStale":false,"detail":{"reason":"quit"}}
probe: shutdown-census [{"type":"model_change"},{"type":"thinking_level_change"},{"type":"custom","customType":"perk:workflow-state"},{"type":"custom","customType":"plannotator"},{"type":"custom_message","customType":"subagent-incremental-child-notify"},{"type":"message","role":"system"},{"type":"message","role":"user","text":"Subagent updates above."},{"type":"custom_message","customType":"perk:agent-scratch"},{"type":"message","role":"assistant","stopReason":"toolUse","usage":{"input":2,"output":282,"cacheRead":20262,"cacheWrite":20851,"totalTokens":41397,"costTotal":0.002950195}},{"type":"message","role":"toolResult"},{"type":"custom_message","customType":"subagent-notify"},{"type":"message","role":"assistant","stopReason":"stop","usage":{"input":4,"output":482,"cacheRead":41113,"cacheWrite":1114,"totalTokens":42713,"costTotal":0.00079178}}]
exit=0 elapsed=12s
```

Lane (`fd244ba6-4dca-4c7f-a665-512068d47299` `status.json`): `workflow` `complete`, lanes `[{"key":"probe","ok":false,"error":"Worktree admission failed for 'probe' at $WT: worktree isolation requires a clean git working tree. Commit or stash changes first. Select the correct cwd or arrange an operator-approved commit/stash.","report":null}]`, `totalCost.costUsd` 0, fan-out used 0. Children: none recorded (no child run id: refused before a child run existed).

Session file (`2026-10-19T20-16-14-474Z_01a155ce-bc8a-77e8-9ca3-207ab6364d7b.jsonl`), entry sequence: `model_change → thinking_level_change → custom:perk:workflow-state → custom:plannotator → custom_message:subagent-incremental-child-notify → system → user → custom_message:perk:agent-scratch → assistant(toolUse) → toolResult → custom_message:subagent-notify → assistant(stop)`.
- `subagent-incremental-child-notify` (display true): "Workflow child failed: **probe**\nWorkflow run: fd244ba6-4dca-4c7f-a665-512068d47299\nError: Worktree admission failed for 'probe' at $WT: worktree isolation requires a clean git working tree. Commit or stash changes first. Select the correct cwd or arrange an operator-approved commit/stash.\nStatus: workflow still running"
- `subagent-notify` (display false): "Background task completed: **workflow**\nWorkflow receipt: $SCRATCH/subagents-tmp/async-subagent-runs/fd244ba6-4dca-4c7f-a665-512068d47299/workflow-receipt.json\n\nWorkflow completed with 1 child run(s). Return: [\n  {\n    \"key\": \"probe\",\n    \"ok\": false,\n    \"error\": \"Worktree admission failed for 'probe' at $WT: worktree isolation requires a clean git working tree. Commit or stash changes first. Sel" …
- assistant `stopReason: toolUse`, usage input 2 / output 282 / cacheRead 20262 / cacheWrite 20851, cost $0.002950
- assistant `stopReason: stop`, usage input 4 / output 482 / cacheRead 41113 / cacheWrite 1114, cost $0.000792

### R2t

```text
row=R2t mode=missingbase wait=settle start=2026-10-19T20:14:55Z
settings.json sha256: c9f7d17efa9cc9bc43a8b451181219194dfe9c17436f742eb7bb1be6e4a3b889
git status --porcelain:
   M .pi/settings.json
  ?? PERK-2660-DIRTY-MARKER
end=2026-10-19T20:15:06Z
probe: spawn(script, anthropic/claude-haiku-5-5, missingbase) { … "success": true, … "asyncId": "49a1b14b-891a-4cd0-be8f-9d1945fee3ff",
probe: lifecycle {"event":"agent_start","at":"2026-10-19T20:14:57.814Z","afterShutdown":false,"ctxStale":false,"detail":{}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:14:57.814Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"system"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:14:57.815Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"user","text":"Subagent updates above."}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:14:57.816Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":2}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:14:58.969Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"assistant"}}
probe: settled-at {"at":"2026-10-19T20:14:59.583Z"}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:15:00.796Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"toolResult"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:15:00.798Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"custom"}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:15:00.813Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":5}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:15:01.636Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"assistant"}}
probe: lifecycle {"event":"agent_end","at":"2026-10-19T20:15:05.023Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":6,"assistantStopReasons":["toolUse","stop"]}}
probe: lifecycle {"event":"agent_settled","at":"2026-10-19T20:15:05.052Z","afterShutdown":false,"ctxStale":false,"detail":{"aborted":false}}
probe: wake-wait {"wakeSeenAt":"2026-10-19T20:14:57.815Z","assistantStartedAt":"2026-10-19T20:14:58.969Z","agentStart":["2026-10-19T20:14:57.814Z"],"agentEnd":["2026-10-19T20:15:05.023Z"],"agentSettled":[{"at":"2026-10-19T20:15:05.052Z","aborted":false}],"waitedMs":5523,"timedOut":false}
probe: lifecycle {"event":"session_shutdown","at":"2026-10-19T20:15:05.108Z","afterShutdown":false,"ctxStale":false,"detail":{"reason":"quit"}}
probe: shutdown-census [{"type":"model_change"},{"type":"thinking_level_change"},{"type":"custom","customType":"plannotator"},{"type":"custom_message","customType":"subagent-incremental-child-notify"},{"type":"message","role":"system"},{"type":"message","role":"user","text":"Subagent updates above."},{"type":"message","role":"assistant","stopReason":"toolUse","usage":{"input":2,"output":260,"cacheRead":5325,"cacheWrite":11080,"totalTokens":16667,"costTotal":0.0015684499999999999}},{"type":"message","role":"toolResult"},{"type":"custom_message","customType":"subagent-notify"},{"type":"message","role":"assistant","stopReason":"stop","usage":{"input":4,"output":730,"cacheRead":16405,"cacheWrite":16325,"totalTokens":33464,"costTotal":0.002570075}}]
exit=0 elapsed=11s
```

Lane (`49a1b14b-891a-4cd0-be8f-9d1945fee3ff` `status.json`): `workflow` `complete`, lanes `[{"key":"probe","ok":false,"error":"Worktree admission failed for 'probe' at $WT: worktree isolation requires a clean git working tree. Commit or stash changes first. Select the correct cwd or arrange an operator-approved commit/stash.","report":null}]`, `totalCost.costUsd` 0, fan-out used 0. Children: none recorded (no child run id: refused before a child run existed).

Session file (`2026-10-19T20-14-55-944Z_01a155cd-89c8-7016-ad76-afafd9361ae0.jsonl`), entry sequence: `model_change → thinking_level_change → custom:plannotator → custom_message:subagent-incremental-child-notify → system → user → assistant(toolUse) → toolResult → custom_message:subagent-notify → assistant(stop)`.
- `subagent-incremental-child-notify` (display true): "Workflow child failed: **probe**\nWorkflow run: 49a1b14b-891a-4cd0-be8f-9d1945fee3ff\nError: Worktree admission failed for 'probe' at $WT: worktree isolation requires a clean git working tree. Commit or stash changes first. Select the correct cwd or arrange an operator-approved commit/stash.\nStatus: workflow still running"
- `subagent-notify` (display false): "Background task completed: **workflow**\nWorkflow receipt: $SCRATCH/subagents-tmp/async-subagent-runs/49a1b14b-891a-4cd0-be8f-9d1945fee3ff/workflow-receipt.json\n\nWorkflow completed with 1 child run(s). Return: [\n  {\n    \"key\": \"probe\",\n    \"ok\": false,\n    \"error\": \"Worktree admission failed for 'probe' at $WT: worktree isolation requires a clean git working tree. Commit or stash changes first. Sel" …
- assistant `stopReason: toolUse`, usage input 2 / output 260 / cacheRead 5325 / cacheWrite 11080, cost $0.001568
- assistant `stopReason: stop`, usage input 4 / output 730 / cacheRead 16405 / cacheWrite 16325, cost $0.002570

## P rows

The lane is `restricted`: `worktree: false` plus the restriction packet; the child runs and
completes. P1 is R4.

**Validity, checked in the fixed order:**

| Attempt | V1 staged | V2 wake observed | V3 settled (settle rows) | V4 SETTLED-OK (settle rows) | Row status |
| --- | --- | --- | --- | --- | --- |
| P1 | ✓ lane `ok: true`; child `72a2b179…` runner pid 20313, `complete` | ✗ `NO-WAKE`: no `agent_start`, no wake user entry; the census holds only the incremental notice | — | — | re-run |
| P1 re-run | ✓ child `f3e8ccb5…` pid 23904, `complete` | ✓ wake 20:16:03.279Z, `agent_start` 20:16:03.275Z | — | — | **valid** (P1 := this attempt) |
| P2 | ✓ child `0e3c3b8e…` pid 20952 | ✓ | ✓ `timedOut: false`, one `agent_settled` | ✗ two assistant entries after the wake user entry (`toolUse`, `stop`); usage > 0 on both; `aborted: false` | re-run |
| P2 re-run | ✓ child `3883e9db…` pid 23542 | ✓ | ✓ | ✗ two assistant entries (`toolUse` with two `read` calls, `stop`) | **`INVALID`** |
| P3 | ✓ child `18fd1be1…` pid 22466 | ✓ wake 20:14:15.201Z, `agent_start` 20:14:15.200Z | — | — | **valid** |
| P4 | ✓ child `aa6a1bd4…` pid 22709 | ✓ | ✓ | ✗ two assistant entries (`toolUse`, `stop`) | re-run |
| P4 re-run | ✓ child `5b3cad4a…` pid 23232 | ✓ | ✓ | ✗ two assistant entries (`toolUse`, `stop`) | **`INVALID`** |

- **Why V4 fails.** V4 reads "exactly one assistant entry after the wake user entry with
  `stopReason ∉ {error, aborted}` …". Every settle wake turn (P2, P4, both re-runs, and R1t/R2t)
  is two such entries: the model `read` the child's output artifact named in the notice, then
  answered. The table records the failure; per the operator decision it is not patched around.
- **P1's NO-WAKE is a staging race.** The workflow finished at 20:09:29.550Z (`events.jsonl`
  `subagent.workflow.completed`). The probe's 2-s status poll saw `complete` at 20:09:29.602Z, and
  shutdown followed at 29.604Z. The workflow's `subagent-notify` was not yet in the session, so no
  wake started. The re-run's poll landed after the notice.

### P1

```text
row=P1 mode=restricted wait=return start=2026-10-19T20:09:05Z
settings.json sha256: 7d9749d98ae1d94f41d64958b1e65ad646d44715175abe73bb0206fe2b0f0516
git status --porcelain:
  ?? PERK-2660-DIRTY-MARKER
end=2026-10-19T20:09:30Z
probe: spawn(script, anthropic/claude-haiku-5-5, restricted) { … "success": true, … "asyncId": "0b2b32b3-8889-4019-8c64-86d90ecc65c6",
probe: settled-at {"at":"2026-10-19T20:09:29.602Z"}
probe: lifecycle {"event":"session_shutdown","at":"2026-10-19T20:09:29.604Z","afterShutdown":false,"ctxStale":false,"detail":{"reason":"quit"}}
probe: shutdown-census [{"type":"model_change"},{"type":"thinking_level_change"},{"type":"custom","customType":"perk:workflow-state"},{"type":"custom","customType":"plannotator"},{"type":"custom_message","customType":"subagent-incremental-child-notify"}]
exit=0 elapsed=25s
```

Lane (`0b2b32b3-8889-4019-8c64-86d90ecc65c6` `status.json`): `workflow` `complete`, lanes `[{"key":"probe","ok":true,"error":null,"report":null}]`, `totalCost.costUsd` 0.0007096499999999999, fan-out used 1. Children: `72a2b179-7102-482a-b749-281b67ef1484: 13 files, status.json state=complete pid=20313`.

Session file: `not flushed`.

### P1-rerun

```text
row=P1-rerun mode=restricted wait=return start=2026-10-19T20:15:58Z
settings.json sha256: 7d9749d98ae1d94f41d64958b1e65ad646d44715175abe73bb0206fe2b0f0516
git status --porcelain:
  ?? PERK-2660-DIRTY-MARKER
end=2026-10-19T20:16:04Z
probe: spawn(script, anthropic/claude-haiku-5-5, restricted) { … "success": true, … "asyncId": "f13fa5a2-c70c-44d4-8f14-a91d757ddb52",
probe: lifecycle {"event":"agent_start","at":"2026-10-19T20:16:03.275Z","afterShutdown":false,"ctxStale":false,"detail":{}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:16:03.276Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"system"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:16:03.279Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"user","text":"Subagent updates above."}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:16:03.281Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"custom"}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:16:03.321Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":4}}
probe: settled-at {"at":"2026-10-19T20:16:03.788Z"}
probe: lifecycle {"event":"session_shutdown","at":"2026-10-19T20:16:03.790Z","afterShutdown":false,"ctxStale":false,"detail":{"reason":"quit"}}
probe: shutdown-census [{"type":"model_change"},{"type":"thinking_level_change"},{"type":"custom","customType":"perk:workflow-state"},{"type":"custom","customType":"plannotator"},{"type":"custom_message","customType":"subagent-incremental-child-notify"},{"type":"custom_message","customType":"subagent-notify"},{"type":"message","role":"system"},{"type":"message","role":"user","text":"Subagent updates above."},{"type":"custom_message","customType":"perk:agent-scratch"}]
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
probe: lifecycle {"event":"agent_settled","at":"2026-10-19T20:16:03.804Z","afterShutdown":true,"ctxStale":true,"detail":{"aborted":false}}
Extension error ($WT/extension/index.ts): This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after … [Pi's stale message; elided]
exit=0 elapsed=6s
```

Lane (`f13fa5a2-c70c-44d4-8f14-a91d757ddb52` `status.json`): `workflow` `complete`, lanes `[{"key":"probe","ok":true,"error":null,"report":null}]`, `totalCost.costUsd` 0.00005898, fan-out used 1. Children: `f3e8ccb5-93d6-4b24-88a9-1ed0d44b81d2: 13 files, status.json state=complete pid=23904`.

Session file (`2026-10-19T20-15-58-327Z_01a155ce-7d77-702d-9700-00d2643f74fc.jsonl`), entry sequence: `model_change → thinking_level_change → custom:perk:workflow-state → custom:plannotator → custom_message:subagent-incremental-child-notify → custom_message:subagent-notify → system → user → custom_message:perk:agent-scratch`.
- `subagent-incremental-child-notify` (display false): "Workflow child completed: **probe**\nWorkflow run: f13fa5a2-c70c-44d4-8f14-a91d757ddb52\nChild run: f3e8ccb5-93d6-4b24-88a9-1ed0d44b81d2\nOutput: $SCRATCH/sessions/P1-rerun/subagent-artifacts/f3e8ccb5-93d6-4b24-88a9-1ed0d44b81d2_perk.scout_output.md\nStatus: workflow still running"
- `subagent-notify` (display false): "Background task completed: **workflow**\nWorkflow receipt: $SCRATCH/subagents-tmp/async-subagent-runs/f13fa5a2-c70c-44d4-8f14-a91d757ddb52/workflow-receipt.json\n\nWorkflow completed with 1 child run(s). Return: [\n  {\n    \"key\": \"probe\",\n    \"ok\": true,\n    \"error\": null,\n    \"report\": null\n  }\n] Trace: 2 event(s).\n\nChild outputs:\n- key=probe run=f3e8ccb5-93d6-4b24-88a9-1ed0d44b81d2 status=completed\n" …

### P2

```text
row=P2 mode=restricted wait=settle start=2026-10-19T20:10:05Z
settings.json sha256: 7d9749d98ae1d94f41d64958b1e65ad646d44715175abe73bb0206fe2b0f0516
git status --porcelain:
  ?? PERK-2660-DIRTY-MARKER
end=2026-10-19T20:10:21Z
probe: spawn(script, anthropic/claude-haiku-5-5, restricted) { … "success": true, … "asyncId": "0ff8afb8-ea1d-4047-a6ee-0164e59441fa",
probe: lifecycle {"event":"agent_start","at":"2026-10-19T20:10:10.888Z","afterShutdown":false,"ctxStale":false,"detail":{}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:10:10.890Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"system"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:10:10.895Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"user","text":"Subagent updates above."}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:10:10.900Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"custom"}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:10:10.942Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":4}}
probe: settled-at {"at":"2026-10-19T20:10:11.219Z"}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:10:13.335Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"assistant"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:10:18.197Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"toolResult"}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:10:18.215Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":6}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:10:19.278Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"assistant"}}
probe: lifecycle {"event":"agent_end","at":"2026-10-19T20:10:19.876Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":6,"assistantStopReasons":["toolUse","stop"]}}
probe: lifecycle {"event":"agent_settled","at":"2026-10-19T20:10:19.889Z","afterShutdown":false,"ctxStale":false,"detail":{"aborted":false}}
probe: wake-wait {"wakeSeenAt":"2026-10-19T20:10:10.895Z","assistantStartedAt":"2026-10-19T20:10:13.335Z","agentStart":["2026-10-19T20:10:10.888Z"],"agentEnd":["2026-10-19T20:10:19.876Z"],"agentSettled":[{"at":"2026-10-19T20:10:19.889Z","aborted":false}],"waitedMs":8787,"timedOut":false}
probe: lifecycle {"event":"session_shutdown","at":"2026-10-19T20:10:20.006Z","afterShutdown":false,"ctxStale":false,"detail":{"reason":"quit"}}
probe: shutdown-census [{"type":"model_change"},{"type":"thinking_level_change"},{"type":"custom","customType":"perk:workflow-state"},{"type":"custom","customType":"plannotator"},{"type":"custom_message","customType":"subagent-incremental-child-notify"},{"type":"custom_message","customType":"subagent-notify"},{"type":"message","role":"system"},{"type":"message","role":"user","text":"Subagent updates above."},{"type":"custom_message","customType":"perk:agent-scratch"},{"type":"message","role":"assistant","stopReason":"toolUse","usage":{"input":2,"output":404,"cacheRead":20262,"cacheWrite":21589,"totalTokens":42257,"costTotal":0.0031034450000000002}},{"type":"message","role":"toolResult"},{"type":"message","role":"assistant","stopReason":"stop","usage":{"input":2,"output":109,"cacheRead":41851,"cacheWrite":411,"totalTokens":42373,"costTotal":0.000524585}}]
exit=0 elapsed=16s
```

Lane (`0ff8afb8-ea1d-4047-a6ee-0164e59441fa` `status.json`): `workflow` `complete`, lanes `[{"key":"probe","ok":true,"error":null,"report":null}]`, `totalCost.costUsd` 0.00005898, fan-out used 1. Children: `0e3c3b8e-1fed-4597-b20f-2f094a056873: 13 files, status.json state=complete pid=20952`.

Session file (`2026-10-19T20-10-05-663Z_01a155c9-1bdf-77e6-93df-43844504f575.jsonl`), entry sequence: `model_change → thinking_level_change → custom:perk:workflow-state → custom:plannotator → custom_message:subagent-incremental-child-notify → custom_message:subagent-notify → system → user → custom_message:perk:agent-scratch → assistant(toolUse) → toolResult → assistant(stop)`.
- `subagent-incremental-child-notify` (display false): "Workflow child completed: **probe**\nWorkflow run: 0ff8afb8-ea1d-4047-a6ee-0164e59441fa\nChild run: 0e3c3b8e-1fed-4597-b20f-2f094a056873\nOutput: $SCRATCH/sessions/P2/subagent-artifacts/0e3c3b8e-1fed-4597-b20f-2f094a056873_perk.scout_output.md\nStatus: workflow still running"
- `subagent-notify` (display false): "Background task completed: **workflow**\nWorkflow receipt: $SCRATCH/subagents-tmp/async-subagent-runs/0ff8afb8-ea1d-4047-a6ee-0164e59441fa/workflow-receipt.json\n\nWorkflow completed with 1 child run(s). Return: [\n  {\n    \"key\": \"probe\",\n    \"ok\": true,\n    \"error\": null,\n    \"report\": null\n  }\n] Trace: 2 event(s).\n\nChild outputs:\n- key=probe run=0e3c3b8e-1fed-4597-b20f-2f094a056873 status=completed\n" …
- assistant `stopReason: toolUse`, usage input 2 / output 404 / cacheRead 20262 / cacheWrite 21589, cost $0.003103
- assistant `stopReason: stop`, usage input 2 / output 109 / cacheRead 41851 / cacheWrite 411, cost $0.000525

### P2-rerun

```text
row=P2-rerun mode=restricted wait=settle start=2026-10-19T20:15:36Z
settings.json sha256: 7d9749d98ae1d94f41d64958b1e65ad646d44715175abe73bb0206fe2b0f0516
git status --porcelain:
  ?? PERK-2660-DIRTY-MARKER
end=2026-10-19T20:15:50Z
probe: spawn(script, anthropic/claude-haiku-5-5, restricted) { … "success": true, … "asyncId": "b617d832-3a79-4d13-857c-bbf1f9a63d5b",
probe: settled-at {"at":"2026-10-19T20:15:41.683Z"}
probe: lifecycle {"event":"agent_start","at":"2026-10-19T20:15:41.828Z","afterShutdown":false,"ctxStale":false,"detail":{}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:15:41.829Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"system"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:15:41.831Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"user","text":"Subagent updates above."}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:15:41.834Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"custom"}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:15:41.870Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":4}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:15:43.371Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"assistant"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:15:46.327Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"toolResult"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:15:46.353Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"toolResult"}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:15:46.375Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":7}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:15:47.369Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"assistant"}}
probe: lifecycle {"event":"agent_end","at":"2026-10-19T20:15:49.365Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":7,"assistantStopReasons":["toolUse","stop"]}}
probe: lifecycle {"event":"agent_settled","at":"2026-10-19T20:15:49.412Z","afterShutdown":false,"ctxStale":false,"detail":{"aborted":false}}
probe: wake-wait {"wakeSeenAt":"2026-10-19T20:15:41.831Z","assistantStartedAt":"2026-10-19T20:15:43.371Z","agentStart":["2026-10-19T20:15:41.828Z"],"agentEnd":["2026-10-19T20:15:49.365Z"],"agentSettled":[{"at":"2026-10-19T20:15:49.412Z","aborted":false}],"waitedMs":7782,"timedOut":false}
probe: lifecycle {"event":"session_shutdown","at":"2026-10-19T20:15:49.467Z","afterShutdown":false,"ctxStale":false,"detail":{"reason":"quit"}}
probe: shutdown-census [{"type":"model_change"},{"type":"thinking_level_change"},{"type":"custom","customType":"perk:workflow-state"},{"type":"custom","customType":"plannotator"},{"type":"custom_message","customType":"subagent-incremental-child-notify"},{"type":"custom_message","customType":"subagent-notify"},{"type":"message","role":"system"},{"type":"message","role":"user","text":"Subagent updates above."},{"type":"custom_message","customType":"perk:agent-scratch"},{"type":"message","role":"assistant","stopReason":"toolUse","usage":{"input":2,"output":614,"cacheRead":0,"cacheWrite":41844,"totalTokens":42460,"costTotal":0.0055377}},{"type":"message","role":"toolResult"},{"type":"message","role":"toolResult"},{"type":"message","role":"assistant","stopReason":"stop","usage":{"input":2,"output":377,"cacheRead":41844,"cacheWrite":1249,"totalTokens":43472,"costTotal":0.0007632650000000001}}]
exit=0 elapsed=14s
```

Lane (`b617d832-3a79-4d13-857c-bbf1f9a63d5b` `status.json`): `workflow` `complete`, lanes `[{"key":"probe","ok":true,"error":null,"report":null}]`, `totalCost.costUsd` 0.0001243, fan-out used 1. Children: `3883e9db-4a98-4654-a53b-2a454ff7dc70: 13 files, status.json state=complete pid=23542`.

Session file (`2026-10-19T20-15-36-267Z_01a155ce-274b-7298-9feb-529bd60c75d6.jsonl`), entry sequence: `model_change → thinking_level_change → custom:perk:workflow-state → custom:plannotator → custom_message:subagent-incremental-child-notify → custom_message:subagent-notify → system → user → custom_message:perk:agent-scratch → assistant(toolUse) → toolResult → toolResult → assistant(stop)`.
- `subagent-incremental-child-notify` (display false): "Workflow child completed: **probe**\nWorkflow run: b617d832-3a79-4d13-857c-bbf1f9a63d5b\nChild run: 3883e9db-4a98-4654-a53b-2a454ff7dc70\nOutput: $SCRATCH/sessions/P2-rerun/subagent-artifacts/3883e9db-4a98-4654-a53b-2a454ff7dc70_perk.scout_output.md\nStatus: workflow still running"
- `subagent-notify` (display false): "Background task completed: **workflow**\nWorkflow receipt: $SCRATCH/subagents-tmp/async-subagent-runs/b617d832-3a79-4d13-857c-bbf1f9a63d5b/workflow-receipt.json\n\nWorkflow completed with 1 child run(s). Return: [\n  {\n    \"key\": \"probe\",\n    \"ok\": true,\n    \"error\": null,\n    \"report\": null\n  }\n] Trace: 2 event(s).\n\nChild outputs:\n- key=probe run=3883e9db-4a98-4654-a53b-2a454ff7dc70 status=completed\n" …
- assistant `stopReason: toolUse`, usage input 2 / output 614 / cacheRead 0 / cacheWrite 41844, cost $0.005538
- assistant `stopReason: stop`, usage input 2 / output 377 / cacheRead 41844 / cacheWrite 1249, cost $0.000763

### P3

```text
row=P3 mode=restricted wait=return start=2026-10-19T20:14:09Z
settings.json sha256: c9f7d17efa9cc9bc43a8b451181219194dfe9c17436f742eb7bb1be6e4a3b889
git status --porcelain:
   M .pi/settings.json
  ?? PERK-2660-DIRTY-MARKER
end=2026-10-19T20:14:15Z
probe: spawn(script, anthropic/claude-haiku-5-5, restricted) { … "success": true, … "asyncId": "a6d2a9e7-713b-41c7-bdb9-9b2db05591b2",
probe: lifecycle {"event":"agent_start","at":"2026-10-19T20:14:15.200Z","afterShutdown":false,"ctxStale":false,"detail":{}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:14:15.200Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"system"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:14:15.201Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"user","text":"Subagent updates above."}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:14:15.204Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":3}}
probe: settled-at {"at":"2026-10-19T20:14:15.235Z"}
probe: lifecycle {"event":"session_shutdown","at":"2026-10-19T20:14:15.235Z","afterShutdown":false,"ctxStale":false,"detail":{"reason":"quit"}}
probe: shutdown-census [{"type":"model_change"},{"type":"thinking_level_change"},{"type":"custom","customType":"plannotator"},{"type":"custom_message","customType":"subagent-incremental-child-notify"},{"type":"custom_message","customType":"subagent-notify"},{"type":"message","role":"system"},{"type":"message","role":"user","text":"Subagent updates above."}]
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
probe: lifecycle {"event":"agent_settled","at":"2026-10-19T20:14:15.238Z","afterShutdown":true,"ctxStale":true,"detail":{"aborted":false}}
exit=0 elapsed=6s
```

Lane (`a6d2a9e7-713b-41c7-bdb9-9b2db05591b2` `status.json`): `workflow` `complete`, lanes `[{"key":"probe","ok":true,"error":null,"report":null}]`, `totalCost.costUsd` 0.0000648, fan-out used 1. Children: `18fd1be1-3403-46c7-a1a0-f03a0e5fca99: 13 files, status.json state=complete pid=22466`.

Session file (`2026-10-19T20-14-09-543Z_01a155cc-d487-73bf-a652-acae572daa0a.jsonl`), entry sequence: `model_change → thinking_level_change → custom:plannotator → custom_message:subagent-incremental-child-notify → custom_message:subagent-notify → system → user`.
- `subagent-incremental-child-notify` (display false): "Workflow child completed: **probe**\nWorkflow run: a6d2a9e7-713b-41c7-bdb9-9b2db05591b2\nChild run: 18fd1be1-3403-46c7-a1a0-f03a0e5fca99\nOutput: $SCRATCH/sessions/P3/subagent-artifacts/18fd1be1-3403-46c7-a1a0-f03a0e5fca99_perk.scout_output.md\nStatus: workflow still running"
- `subagent-notify` (display false): "Background task completed: **workflow**\nWorkflow receipt: $SCRATCH/subagents-tmp/async-subagent-runs/a6d2a9e7-713b-41c7-bdb9-9b2db05591b2/workflow-receipt.json\n\nWorkflow completed with 1 child run(s). Return: [\n  {\n    \"key\": \"probe\",\n    \"ok\": true,\n    \"error\": null,\n    \"report\": null\n  }\n] Trace: 2 event(s).\n\nChild outputs:\n- key=probe run=18fd1be1-3403-46c7-a1a0-f03a0e5fca99 status=completed\n" …

### P4

```text
row=P4 mode=restricted wait=settle start=2026-10-19T20:14:26Z
settings.json sha256: c9f7d17efa9cc9bc43a8b451181219194dfe9c17436f742eb7bb1be6e4a3b889
git status --porcelain:
   M .pi/settings.json
  ?? PERK-2660-DIRTY-MARKER
end=2026-10-19T20:14:38Z
probe: spawn(script, anthropic/claude-haiku-5-5, restricted) { … "success": true, … "asyncId": "9c84970f-537a-484a-90c0-61613399bea7",
probe: lifecycle {"event":"agent_start","at":"2026-10-19T20:14:32.164Z","afterShutdown":false,"ctxStale":false,"detail":{}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:14:32.165Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"system"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:14:32.166Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"user","text":"Subagent updates above."}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:14:32.170Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":3}}
probe: settled-at {"at":"2026-10-19T20:14:32.201Z"}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:14:33.747Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"assistant"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:14:36.150Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"toolResult"}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:14:36.154Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":5}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:14:37.004Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"assistant"}}
probe: lifecycle {"event":"agent_end","at":"2026-10-19T20:14:37.916Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":5,"assistantStopReasons":["toolUse","stop"]}}
probe: lifecycle {"event":"agent_settled","at":"2026-10-19T20:14:37.959Z","afterShutdown":false,"ctxStale":false,"detail":{"aborted":false}}
probe: wake-wait {"wakeSeenAt":"2026-10-19T20:14:32.166Z","assistantStartedAt":"2026-10-19T20:14:33.747Z","agentStart":["2026-10-19T20:14:32.164Z"],"agentEnd":["2026-10-19T20:14:37.916Z"],"agentSettled":[{"at":"2026-10-19T20:14:37.959Z","aborted":false}],"waitedMs":5785,"timedOut":false}
probe: lifecycle {"event":"session_shutdown","at":"2026-10-19T20:14:37.986Z","afterShutdown":false,"ctxStale":false,"detail":{"reason":"quit"}}
probe: shutdown-census [{"type":"model_change"},{"type":"thinking_level_change"},{"type":"custom","customType":"plannotator"},{"type":"custom_message","customType":"subagent-incremental-child-notify"},{"type":"custom_message","customType":"subagent-notify"},{"type":"message","role":"system"},{"type":"message","role":"user","text":"Subagent updates above."},{"type":"message","role":"assistant","stopReason":"toolUse","usage":{"input":2,"output":398,"cacheRead":5325,"cacheWrite":11802,"totalTokens":17527,"costTotal":0.0017277}},{"type":"message","role":"toolResult"},{"type":"message","role":"assistant","stopReason":"stop","usage":{"input":2,"output":180,"cacheRead":17127,"cacheWrite":989,"totalTokens":18298,"costTotal":0.000385095}}]
exit=0 elapsed=12s
```

Lane (`9c84970f-537a-484a-90c0-61613399bea7` `status.json`): `workflow` `complete`, lanes `[{"key":"probe","ok":true,"error":null,"report":null}]`, `totalCost.costUsd` 0.0000533, fan-out used 1. Children: `aa6a1bd4-407b-4a1b-9466-02b6a1dd290d: 13 files, status.json state=complete pid=22709`.

Session file (`2026-10-19T20-14-26-493Z_01a155cd-16bc-7563-b0da-2eb5a60e735c.jsonl`), entry sequence: `model_change → thinking_level_change → custom:plannotator → custom_message:subagent-incremental-child-notify → custom_message:subagent-notify → system → user → assistant(toolUse) → toolResult → assistant(stop)`.
- `subagent-incremental-child-notify` (display false): "Workflow child completed: **probe**\nWorkflow run: 9c84970f-537a-484a-90c0-61613399bea7\nChild run: aa6a1bd4-407b-4a1b-9466-02b6a1dd290d\nOutput: $SCRATCH/sessions/P4/subagent-artifacts/aa6a1bd4-407b-4a1b-9466-02b6a1dd290d_perk.scout_output.md\nStatus: workflow still running"
- `subagent-notify` (display false): "Background task completed: **workflow**\nWorkflow receipt: $SCRATCH/subagents-tmp/async-subagent-runs/9c84970f-537a-484a-90c0-61613399bea7/workflow-receipt.json\n\nWorkflow completed with 1 child run(s). Return: [\n  {\n    \"key\": \"probe\",\n    \"ok\": true,\n    \"error\": null,\n    \"report\": null\n  }\n] Trace: 2 event(s).\n\nChild outputs:\n- key=probe run=aa6a1bd4-407b-4a1b-9466-02b6a1dd290d status=completed\n" …
- assistant `stopReason: toolUse`, usage input 2 / output 398 / cacheRead 5325 / cacheWrite 11802, cost $0.001728
- assistant `stopReason: stop`, usage input 2 / output 180 / cacheRead 17127 / cacheWrite 989, cost $0.000385

### P4-rerun

```text
row=P4-rerun mode=restricted wait=settle start=2026-10-19T20:15:12Z
settings.json sha256: c9f7d17efa9cc9bc43a8b451181219194dfe9c17436f742eb7bb1be6e4a3b889
git status --porcelain:
   M .pi/settings.json
  ?? PERK-2660-DIRTY-MARKER
end=2026-10-19T20:15:25Z
probe: spawn(script, anthropic/claude-haiku-5-5, restricted) { … "success": true, … "asyncId": "6f84b595-0dd6-469b-8bac-47c42a555961",
probe: lifecycle {"event":"agent_start","at":"2026-10-19T20:15:19.147Z","afterShutdown":false,"ctxStale":false,"detail":{}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:15:19.148Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"system"}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:15:19.149Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"user","text":"Subagent updates above."}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:15:19.152Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":3}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:15:20.557Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"assistant"}}
probe: settled-at {"at":"2026-10-19T20:15:20.671Z"}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:15:22.497Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"toolResult"}}
probe: lifecycle {"event":"context","at":"2026-10-19T20:15:22.501Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":5}}
probe: lifecycle {"event":"message_start","at":"2026-10-19T20:15:23.506Z","afterShutdown":false,"ctxStale":false,"detail":{"role":"assistant"}}
probe: lifecycle {"event":"agent_end","at":"2026-10-19T20:15:24.837Z","afterShutdown":false,"ctxStale":false,"detail":{"messages":5,"assistantStopReasons":["toolUse","stop"]}}
probe: lifecycle {"event":"agent_settled","at":"2026-10-19T20:15:24.877Z","afterShutdown":false,"ctxStale":false,"detail":{"aborted":false}}
probe: wake-wait {"wakeSeenAt":"2026-10-19T20:15:19.149Z","assistantStartedAt":"2026-10-19T20:15:20.557Z","agentStart":["2026-10-19T20:15:19.147Z"],"agentEnd":["2026-10-19T20:15:24.837Z"],"agentSettled":[{"at":"2026-10-19T20:15:24.877Z","aborted":false}],"waitedMs":4268,"timedOut":false}
probe: lifecycle {"event":"session_shutdown","at":"2026-10-19T20:15:24.940Z","afterShutdown":false,"ctxStale":false,"detail":{"reason":"quit"}}
probe: shutdown-census [{"type":"model_change"},{"type":"thinking_level_change"},{"type":"custom","customType":"plannotator"},{"type":"custom_message","customType":"subagent-incremental-child-notify"},{"type":"custom_message","customType":"subagent-notify"},{"type":"message","role":"system"},{"type":"message","role":"user","text":"Subagent updates above."},{"type":"message","role":"assistant","stopReason":"toolUse","usage":{"input":2,"output":455,"cacheRead":5325,"cacheWrite":11821,"totalTokens":17603,"costTotal":0.001758575}},{"type":"message","role":"toolResult"},{"type":"message","role":"assistant","stopReason":"stop","usage":{"input":2,"output":275,"cacheRead":17146,"cacheWrite":1057,"totalTokens":18480,"costTotal":0.00044128500000000003}}]
exit=0 elapsed=13s
```

Lane (`6f84b595-0dd6-469b-8bac-47c42a555961` `status.json`): `workflow` `complete`, lanes `[{"key":"probe","ok":true,"error":null,"report":null}]`, `totalCost.costUsd` 0.0000533, fan-out used 1. Children: `5b3cad4a-7c22-4a85-bd83-8fe5a4f51071: 13 files, status.json state=complete pid=23232`.

Session file (`2026-10-19T20-15-12-994Z_01a155cd-cc62-7104-ab10-479eef931d52.jsonl`), entry sequence: `model_change → thinking_level_change → custom:plannotator → custom_message:subagent-incremental-child-notify → custom_message:subagent-notify → system → user → assistant(toolUse) → toolResult → assistant(stop)`.
- `subagent-incremental-child-notify` (display false): "Workflow child completed: **probe**\nWorkflow run: 6f84b595-0dd6-469b-8bac-47c42a555961\nChild run: 5b3cad4a-7c22-4a85-bd83-8fe5a4f51071\nOutput: $SCRATCH/sessions/P4-rerun/subagent-artifacts/5b3cad4a-7c22-4a85-bd83-8fe5a4f51071_perk.scout_output.md\nStatus: workflow still running"
- `subagent-notify` (display false): "Background task completed: **workflow**\nWorkflow receipt: $SCRATCH/subagents-tmp/async-subagent-runs/6f84b595-0dd6-469b-8bac-47c42a555961/workflow-receipt.json\n\nWorkflow completed with 1 child run(s). Return: [\n  {\n    \"key\": \"probe\",\n    \"ok\": true,\n    \"error\": null,\n    \"report\": null\n  }\n] Trace: 2 event(s).\n\nChild outputs:\n- key=probe run=5b3cad4a-7c22-4a85-bd83-8fe5a4f51071 status=completed\n" …
- assistant `stopReason: toolUse`, usage input 2 / output 455 / cacheRead 5325 / cacheWrite 11821, cost $0.001759
- assistant `stopReason: stop`, usage input 2 / output 275 / cacheRead 17146 / cacheWrite 1057, cost $0.000441

### Prediction versus observation, per cell

Valid rows (scored):

| Row | Cell | Predicted | Observed | Holds |
| --- | --- | --- | --- | --- |
| P1 (re-run) | stale-ctx | ≥ 1 | 1 (`Extension error ($WT/extension/index.ts): This extension ctx is stale …`) | ✓ |
| P1 | `<boundary>` | 1 | 1 | ✓ |
| P1 | assistant `message_start` (stdout) | 0 | 0 | ✓ |
| P1 | census: wake user entry, no non-aborted assistant entry | yes | wake user entry present, no assistant entry at all; the file agrees | ✓ |
| P1 | post-shutdown `context` / `agent_settled` lines read `ctxStale: true` | yes | `agent_settled` `afterShutdown: true, ctxStale: true` (no post-shutdown `context`) | ✓ |
| P1 | exit | `EXITS` | `exit=0 elapsed=6s` | ✓ |
| P3 | stale-ctx | 0 | 0 | ✓ |
| P3 | `<boundary>` | 1 | 1 | ✓ |
| P3 | no non-aborted assistant entry | yes | none; the file agrees | ✓ |
| P3 | exit | `EXITS` | `exit=0 elapsed=6s` | ✓ |

`INVALID` rows (recorded, not scored; both attempts read the same):

| Row | Cell | Predicted | Observed (attempt / re-run) |
| --- | --- | --- | --- |
| P2 | `wake-wait` `timedOut` | `false` | `false` (8787 ms) / `false` (7782 ms) |
| P2 | stale-ctx, `<boundary>`, `loadout presentation failed` | 0, 0, 0 | 0, 0, 0 / 0, 0, 0 |
| P2 | any `ctxStale: true` line | none | none / none |
| P2 | exactly one SETTLED-OK assistant entry | 1 | 2 (`toolUse` $0.003103, `stop` $0.000525) / 2 (`toolUse` $0.005538, `stop` $0.000763) |
| P2 | exit | `EXITS` | `exit=0` 16 s / `exit=0` 14 s |
| P4 | `wake-wait` `timedOut` | `false` | `false` (5785 ms) / `false` (4268 ms) |
| P4 | stale-ctx, `<boundary>` | 0, 0 | 0, 0 / 0, 0 |
| P4 | exactly one SETTLED-OK assistant entry | 1 | 2 (`toolUse` $0.001728, `stop` $0.000385) / 2 (`toolUse` $0.001759, `stop` $0.000441) |
| P4 | exit | `EXITS` | `exit=0` 12 s / `exit=0` 13 s |

**Core and secondary predictions.**

- **C1** (P1, P3) holds.
- **C2** (P2, P4) is not scorable: both rows are `INVALID`.
- **S1** holds. **S2** holds.
- **S3** and **S4** are not scorable.

**H verdict: `INCONCLUSIVE`.** The fixed order applies rule 1, because P2 and P4 are `INVALID`.

**Unscored: H under a multi-entry reading of V4.** The operator asked for this to be shown and not
scored. Suppose V4 read "every assistant entry after the wake user entry has `stopReason ∉ {error,
aborted}`, the last is `stop`, Σ usage > 0, and the last `agent_settled` has `aborted: false`".
All four settle attempts would then pass. C2 would hold: `<boundary>` = 0 and stale-ctx = 0 on P2
and P4. S4 would hold. S3 ("exactly one assistant entry") would still fail on P2 and P4. The
result would be `PARTIAL`, with S3 failing on P2 and P4. This is not a verdict.

**Provider reach.**

- **P1 and P3: NOT ESTABLISHED.** The aborted wake turn left no assistant entry, and stdout was
  already unsubscribed.
- **P2 and P4: established by usage.** Under the multi-entry reading, every attempt shows positive
  provider-reported usage. Under the literal V4 the rows are `INVALID`, and the fixed rule says
  "provider request NOT ESTABLISHED on that row". Both statements are kept.

## Attribution table

P1 (re-run, perk, `return`) against P3 (no-perk, `return`), both valid:

| Observable | P1 (perk) | P3 (no-perk) | Class |
| --- | --- | --- | --- |
| `Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID` | 1 | 1 | `HOST` |
| perk stale-ctx `Extension error ($WT/extension/index.ts): This extension ctx is stale …` | 1 | 0 | `PERK-ADDITIVE` |
| `perk: loadout presentation failed — …` | 0 | 0 | `ABSENT` |
| a handler dispatched after `session_shutdown` (the probe's `agent_settled` reads `afterShutdown: true, ctxStale: true`) | 1 | 1 | `HOST` |
| the wake turn ends with no persisted assistant entry (wake user entry present) | yes | yes | `HOST` |

**Which event the perk line came from.** In P1 the only post-shutdown dispatch the probe saw was
`agent_settled`. Its lifecycle line (`afterShutdown: true, ctxStale: true`, 20:16:03.804Z) is
followed in log order by the one perk stale-ctx line. The `context` event had fired before
shutdown, at 20:16:03.321Z. The perk line is therefore attributed to `agent_settled`, whose
SOURCE-DERIVED candidates are `extension/pi/v1/objective.ts:236` and
`extension/pi/v1/drivenCompaction.ts:134`. Which one threw is not observable.

- **In the R rows' loop the event is `context`.** Each post-shutdown `context` lifecycle line is
  followed by one perk stale-ctx line and one `loadout presentation failed` line. The candidates
  are `agentScratch.ts:132`, `bindingDelivery.ts:279`, `contextInjection.ts:200`, and
  `toolGating.ts:437` → `:535`.
- **Ordering caveat.** Pi's stderr lines and the probe's lines interleave on one log, so their
  relative order is log order, not event order. The probe's `at` timestamps order only
  probe-observed events.

### The loop: an observed pattern (post hoc, not pre-registered, untested)

| Rows | Wake in flight at dispose | Wake `agent_start` → `session_shutdown` | `subagent-notify` in the shutdown census | Outcome |
| --- | --- | --- | --- | --- |
| R1, R1-r2, R2, R2-r2, R3 | yes | 1751–1897 ms | absent (only the incremental child-failed notice) | `LOOPS` |
| P1 re-run, P3 | yes | 515 / 35 ms | present | `EXITS`: one `<boundary>`, one post-shutdown `agent_settled` |
| P1 (first attempt) | no wake | — | absent | `EXITS`, no error line |
| R1t, R2t, P2, P2 re-run, P4, P4 re-run | no: the wake settled before dispose | — | present | `EXITS`, no error line |

The two candidate discriminators co-vary in every row: the length of the in-flight window, and a
workflow completion notice still pending at dispose. This instrument cannot separate them. Why the
host keeps re-dispatching is NOT ESTABLISHED. Whether those turns reach the provider is NOT
ESTABLISHED: there is no network witness, and nothing is persisted after dispose.

## #2660 disposition

- **The rule row that fired.** R1 `LOOPS` (R1, R1-r2), R2 `LOOPS` (R2, R2-r2) → "Persists on Pi
  1.1.0 + pi-subagents 0.76.1 and reproduces without perk: an upstream limitation of the
  print-mode parent after a refused lane's wake; outside perk's report path (`worktree: false` on
  every lane); no perk regression, no repair" → comment + close. No follow-up issue, by the rule.
- **Operator deviation 1 — the endpoint coupling.** It was made in the implement session on
  2026-10-19, after the rows, on the question "How should the record treat this?". The answer was
  "Keep H literal, decide #2660 from R arms". The fixed endpoint ties a P row `INVALID` to an
  `UNRESOLVED` #2660. The operator decided #2660 from the two R arm classes alone, as the
  disposition table's own header says ("the two arm classes decide, nothing else"). H stays
  `INCONCLUSIVE`.
- **Operator deviation 2 — sequencing.** The plan posts the comment "at `/submit` time, after the
  PR exists", naming the PR number. The submit tool ends the implement turn as soon as it opens
  the PR. The operator chose to post before `/submit`, citing plan #2723 and branch `plan-2723`
  (the PR links to plan #2723) instead of a PR number.

**Executed on 2026-10-19, before `/submit` (operator deviation 2):**

- `gh issue comment 2660 --body-file …` → `https://github.com/mattgiles/perk/issues/2660#issuecomment-6276647008`, created 2026-10-19T20:30:15Z.
- `gh issue close 2660` → `✓ Closed issue mattgiles/perk#2660 (Headless print-mode parent loops after a worktree-admission-refused pi-subagents lane (not perk-attributable; Pi 0.99.2 and 1.0.0))`.
- State after (`gh issue view 2660 --json number,state,stateReason,closedAt`): `{"closedAt":"2026-10-19T20:30:16Z","number":2660,"state":"CLOSED","stateReason":"COMPLETED"}`.
- Follow-up issue: none (the rule row files none).

The comment as posted (verbatim):

```markdown
Measured on the exact pair, Pi 1.1.0 + pi-subagents 0.76.1, for Objective #2707 node 2.4.

- **Record:** `docs/design/archive/pi-1.1.0-headless-print-mode.md`
- **Where:** plan #2723, branch `plan-2723`. The PR is linked from plan #2723; the operator chose to post before the PR opened.

**Disposition (R1 perk = `LOOPS`, R2 no-perk = `LOOPS`).** Persists on Pi 1.1.0 + pi-subagents 0.76.1 and reproduces without perk: an upstream limitation of the print-mode parent after a refused lane's wake; outside perk's report path (`worktree: false` on every lane); no perk regression, no repair.

Scored readings. The probe used the `missingbase` lane (`Worktree admission failed …`, refused before any child run) in `return` mode, under the watchdog (GRACE 60 s / CAP 330 s):

- **R1 (perk):** the parent was woken (`Subagent updates above.`); `watchdog: pi still running 60s after the probe's terminal line (elapsed 67s)`; `exit=143 elapsed=72s`. **LOOPS**
- **R1-r2 (perk):** woken; watchdog at 67 s; `exit=143 elapsed=72s`. **LOOPS**
- **R2 (no-perk; `".."` dropped from `.pi/settings.json`):** woken; watchdog at 67 s; `exit=143 elapsed=72s`. **LOOPS**
- **R2-r2 (no-perk):** woken; watchdog at 74 s; `exit=143 elapsed=79s`. **LOOPS**

Also measured, outside the scored arms:

- A `badmodel` lane now loops too (R3, perk), unlike 0.75.0's X1.
- A probe that waits for the wake turn to settle before returning exits 0 in both arms (R1t, R2t).

Follow-up issue: none. This disposition files none.

H, the post-terminal attribution half of the node, is `INCONCLUSIVE` on its pre-registered wording. The operator decided that this does not hold the disposition, which comes from the two arm classes alone. The record has the details.

`[object Object]` formatting: fixed since #2671 (`formatExtensionError`), confirmed offline.
```

## Stop-and-confirm

This was done before any deletion, at 2026-10-19T20:20:18Z.

- **Every async run directory is terminal.** All 21 under `$SCRATCH/subagents-tmp/async-subagent-runs`
  are terminal (`state: complete`): 14 workflow dirs, one per row, plus 7 `single` child dirs, one
  per restricted-lane attempt:

  ```text
  0b2b32b3-8889-4019-8c64-86d90ecc65c6 workflow complete pid=20168
  0e3c3b8e-1fed-4597-b20f-2f094a056873 single complete pid=20952
  0ff8afb8-ea1d-4047-a6ee-0164e59441fa workflow complete pid=20819
  18fd1be1-3403-46c7-a1a0-f03a0e5fca99 single complete pid=22466
  2720cb21-a440-4a23-97a2-8bcfc460874a workflow complete pid=21944
  31cada10-ae6a-4169-9531-b17d46b71921 workflow complete pid=18769
  3883e9db-4a98-4654-a53b-2a454ff7dc70 single complete pid=23542
  49a1b14b-891a-4cd0-be8f-9d1945fee3ff workflow complete pid=22921
  5b3cad4a-7c22-4a85-bd83-8fe5a4f51071 single complete pid=23232
  6f84b595-0dd6-469b-8bac-47c42a555961 workflow complete pid=23140
  72a2b179-7102-482a-b749-281b67ef1484 single complete pid=20313
  9459d260-bf83-4708-884f-c639069c219b workflow complete pid=19554
  9c84970f-537a-484a-90c0-61613399bea7 workflow complete pid=22617
  a6d2a9e7-713b-41c7-bdb9-9b2db05591b2 workflow complete pid=22374
  aa6a1bd4-407b-4a1b-9466-02b6a1dd290d single complete pid=22709
  b617d832-3a79-4d13-857c-bbf1f9a63d5b workflow complete pid=23428
  d396b442-0820-4e4d-80cd-2f3946ce3f26 workflow complete pid=18157
  f13fa5a2-c70c-44d4-8f14-a91d757ddb52 workflow complete pid=23798
  f3e8ccb5-93d6-4b24-88a9-1ed0d44b81d2 single complete pid=23904
  f4a02767-87e5-44b2-9809-037db214161b workflow complete pid=21416
  fd244ba6-4dca-4c7f-a665-512068d47299 workflow complete pid=24111
  ```

- **No row process is alive.** `ps -p` on each of those 21 pids reports "not running" for all of
  them. The workflow pids are the parents, because the in-process workflow host shares the parent
  process. `pgrep -fl "probe-spawn|pi --approve"` finds nothing.
- **No `.pi/` settings or trust file changed.** The files outside `$AUTHED`/`$SCRATCH` hash
  identical before the first row (20:03:03Z) and after the last (`diff` empty):

  ```text
  7d9749d98ae1d94f41d64958b1e65ad646d44715175abe73bb0206fe2b0f0516  $WT/.pi/settings.json
  1f428b91b905790a68c78d191155b73da5d58005bd6b05a55f4d5ce996f6e4a8  $WT/.pi/agent/models.json
  7d9749d98ae1d94f41d64958b1e65ad646d44715175abe73bb0206fe2b0f0516  /Users/mattgiles/dev/github/mattgiles/perk/.pi/settings.json
  0d74559c8821972987a25432894cc30b74ccc3f10a883f00ba6e06cbe4eb5499  /Users/mattgiles/dev/github/mattgiles/perk/.pi/agent/auth.json
  1f428b91b905790a68c78d191155b73da5d58005bd6b05a55f4d5ce996f6e4a8  /Users/mattgiles/dev/github/mattgiles/perk/.pi/agent/models.json
  b9b76a8b05908ff008c1a7bbff1f39363c44bb2711edcb862148bd0591e263a7  ~/.pi/agent/settings.json
  47f6a8613621acad9acadfc4e7f277f7651c082e6f6cda7b3e63caa220e736d2  ~/.pi/agent/trust.json
  bd750912cd852c28adc567ccfab7ef05b51a1fe90705bbd8dad80b741602e039  ~/.pi/agent/auth.json
  ```

- **`.pi/settings.json` was restored hash-equal.** It reads `7d9749d9…0f0516` both before the X3
  edit and after `git checkout`.

## Teardown proof

```text
=== teardown 2026-10-19T20:30:56Z
pgrep -fl "probe-spawn|pi --approve" (before): (none)
rm PERK-2660-DIRTY-MARKER exit=0; ls: ls: $WT/PERK-2660-DIRTY-MARKER: No such file or directory
rm -rf $AUTHED exit=0; ls: ls: $AUTHED: No such file or directory
rm -rf $SCRATCH/subagents-tmp exit=0; ls: ls: $SCRATCH/subagents-tmp: No such file or directory
pgrep (after): (none)
settings.json: 7d9749d98ae1d94f41d64958b1e65ad646d44715175abe73bb0206fe2b0f0516
git status --porcelain:
   M CONTEXT.md
```

At teardown the record file was still the committed tables version (`7f335793`), so only
`CONTEXT.md` showed as modified. After the record was assembled from the preserved readings,
`git status --porcelain` shows exactly the two intended files:

```text
 M CONTEXT.md
 M docs/design/archive/pi-1.1.0-headless-print-mode.md
```

- **Kept:** `$SCRATCH` (gitignored) keeps the logs, `.meta` files, the readings and the session
  directories.
- **Removed:** the engine temp root (every async run directory), the auth copy and the marker.

## Planning-time facts

**Confirmed:**

- **The pair.** PATH `pi` 1.1.0, root SDK 1.1.0, `.pi/npm` pi-subagents 0.76.1, re-read before the
  first row.
- **The `[object Object]` fix.** `formatExtensionError` landed at `919c34dd` (#2671), is used by
  `headlessBinding().onError` (`sdkAdapter.ts:342`), and its named pin passes.
- **Print mode's error channel.** `onError` drops `event` and `stack`, matching every quoted
  `Extension error (<path>): <error>` line. No extension can see which event threw.
- **Shutdown order.** `session_shutdown` (reason `quit`) precedes `session.dispose()`. Every
  pre-shutdown probe line reads `ctxStale: false`, and every post-shutdown line reads `true`.
- **An unwoken row flushes no session file.** P1's first attempt (no wake): `not flushed`. Every
  woken row flushed, because the wake user message is conversational.
- **A command's `prompt()` returns at handler return**, and print mode disposes at once (≤ 2 ms
  in every `return` row).
- **After invalidation the runner still dispatches `context` and `agent_settled`.** The probe's
  own observers ran there and read `ctxStale: true`.
- **The wake shape.** The notice is a `custom_message`, then the `Subagent updates above.` user
  entry (every census). A failed child wakes the parent while its workflow still runs (R rows). A
  completed child does not; its notice is `display: false` (P rows).
- **The X1b shape is reachable on 0.76.1.** Worktree admission refuses inside the workflow: no
  child run id, fan-out `used: 0`, and the parent is woken.
- **`<boundary>` needs a `turn_end` handler from some loaded extension.** pi-subagents provides one
  in the no-perk arm (`src/watchdog/register-main.js:395`).

**Falsified, or narrowed:**

- **`$MODEL` = `claude-haiku-4-5`.** The installed catalog's cheapest Anthropic model is
  `claude-haiku-5-5`.
- **"The non-exit depends on the pre-spawn failure kind" (0.75.0 X1/X1b).** On this pair `badmodel`
  loops too (R3). `docs/learned/pi/headless-session-drive.md` § "Residual risks" is stale.
- **V4's "exactly one assistant entry".** The wake turn was `toolUse` then `stop` in all six settle
  attempts that woke (P2, P4, both re-runs, R1t, R2t).
- **`agent_settled.aborted` as a dispose witness.** A dispose-aborted wake turn's post-dispose
  `agent_settled` reads `aborted: false` (P1 re-run, P3). `dispose()` aborts the agent directly
  and never sets `_agentRunAbortRequested`, the flag `aborted` reports (SOURCE-DERIVED, above).
  V4's `aborted: false` clause can therefore not detect a dispose abort. It did not matter for
  P2/P4, which settled before dispose.
- **The P1 prediction assumed a `return` handler returns while the wake is in flight.** For a
  completed child the wake comes only from the workflow's own notice. That notice can arrive after
  the probe's status poll (P1's first attempt), so `return`-mode staging of P rows is racy.
- **"Print mode never turns an assistant error into a non-zero exit"** holds for `--mode json`
  only. `runPrintMode` returns 1 in `text` mode when the last assistant message is `error` or
  `aborted`. Not exercised here.

## Residuals / handoffs

- **To 7.1.**
  - Nothing deferred by this node. The P rows' matched readings corroborate 7.1's headless
    certification cells; they do not substitute for them.
  - A 7.1 cell that waits on a wake turn should expect a multi-message wake (`toolUse` then
    `stop`).
- **To 7.2.**
  - In the ledger's "Retained adaptations" paragraph, the #2660 sentence should become the
    measured disposition: LOOPS / LOOPS, upstream, closed. Include the `badmodel` widening and the
    `settle` escape.
  - `docs/learned/pi/headless-session-drive.md` § "Residual risks" ("CLI print-mode non-exit
    depends on the pre-spawn failure kind") is stale as of this record.
- **Operator residual (no issue filed, by decision).**
  - Perk's stale-ctx line is `PERK-ADDITIVE` on a valid row, from an `agent_settled` handler
    dispatched after `session_shutdown` (candidates `objective.ts:236`, `drivenCompaction.ts:134`).
    In the loop, `context` handlers add one more line each iteration (candidates above).
  - Whether perk's `context`/`agent_settled` handlers should guard against a post-shutdown ctx is
    the operator's call. The lines exit 0 and touch no supported path, and H is `INCONCLUSIVE`
    (not `CONFIRMED`/`PARTIAL`), so the plan's trigger for raising it is not met. It is listed
    here for completeness.
- **Upstream (not filed by this node).**
  - The print-mode host loops after `dispose()` when a wake turn is in flight. The loop is
    observed without perk (R2, R2-r2) and for both pre-spawn failure kinds.
  - The mechanism is NOT ESTABLISHED: what keeps re-dispatching, and whether those turns reach the
    provider.
  - The observed correlation table above is the starting point.
- **Not re-measured here.**
  - The SDK worker's exit after a pre-spawn lane failure on the new pair (last measured as 0.75.0's
    W1/W1d on Pi 1.0.0).
  - Whether a dispose-aborted wake turn reaches the provider (no network witness).
- **`/learn` candidates.**
  - `docs/learned/pi/headless-session-drive.md` § "Headless probe and dogfood-session craft":
    - a command's `prompt()` returns before a run the command triggered, and print mode disposes
      at once;
    - a probe that needs the wake turn must wait for `agent_settled`, which also avoids the
      post-dispose loop;
    - print mode's `onError` drops `event`, so a probe's own handlers reading `ctx.hasUI` are the
      staleness instrument;
    - a session file flushes only once a conversational message exists;
    - `agent_settled.aborted` does not witness a dispose abort;
    - wake turns are often `toolUse` + `stop`.
  - The same doc's § "Residual risks": replace the 0.75.0-era sentence with the measured classes.
  - `docs/learned/pi/subagents.md` § "Supervisor channel → Wakes": the 0.76.1 wake shape (notice
    with `triggerTurn: false`, then the `Subagent updates above.` steer); the abandoned-wake
    branch; a failed child wakes while its workflow runs, a completed child does not.
  - All of these go through `/learn`; none is edited here.

## Offline confirmations (verbatim pass lines)

```text
$ node --test --test-reporter=spec extension/worker/sdkAdapter.test.ts
✔ formatExtensionError: Pi's ExtensionError renders path, event and message; other values fall back (0.05775ms)
ℹ tests 38
ℹ pass 38
ℹ fail 0

$ node --test --test-reporter=spec extension/waves/reportWave.test.ts
✔ start: every report child carries the constant packet and caller-checkout placement (1.464667ms)
✔ run: every report child carries the constant packet and caller-checkout placement (1.374667ms)
✔ the renderer rejects hostile extra fields: the packet and placement cannot be overridden (1.426583ms)
ℹ tests 88
ℹ pass 88
ℹ fail 0
```

The live residual stays: the worker's exit after a pre-spawn lane failure was last measured on
0.75.0 + Pi 1.0.0 (W1/W1d). There is no live `[object Object]` row, by decision.
