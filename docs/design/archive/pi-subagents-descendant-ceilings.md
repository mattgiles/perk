# Record: descendant ceilings and the bridge-off writer transport on Pi 1.1.0 + pi-subagents 0.76.1

**Status:** dated evidence record. Measured and authored 2026-10-10 (UTC) on branch `plan-2717`
(base `016f31ff`). It implements plan #2717 (Objective #2707, node 2.1): every perk leaf def gains a
blank `allowedAgents:` descendant ceiling, and the shared foreground writer transport
(`extension/pi/v1/foregroundDelegation.ts::dispatchForeground`, ridden by `perk.conflict-resolver`
and `perk.librarian`) carries `intercomBridge: {mode: "off"}` (`FOREGROUND_INTERCOM_BRIDGE`) as an
unconditional invariant. The precedent is [`pi-subagents-0.76.1-pin.md`](pi-subagents-0.76.1-pin.md)
§ "The in-process identity proof" (this record reuses its instrument shape and its watchdog).

**Verdict: all four legs measured; every leg PASS — L3 on its second run, after a recorded harness
failure.**

| Leg | Spawn path | Child def | Verdict |
| --- | --- | --- | --- |
| L1 background, actual def | perk's report-wave launcher (`runScoutWave`'s request) | `perk.scout` | **PASS** |
| L2 control (pre-edit transport) | `dispatchForeground` at `31b3542b` | `perk.scout` | **gap measured** — `contact_supervisor` + bridge template present |
| L2 treatment (post-edit transport) | `dispatchForeground` at `0fe1f1fe` | `perk.scout` | **PASS** |
| L3 foreground, nesting granted | `dispatchForeground` | throwaway `ceiling-probe` | run 1: **harness failure** (`structured_output_failed` — the bare project's validator could not load `typebox/compile`; the ceiling refusal is in the engine-written transcript); run 2 (`PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT` set): **PASS** |
| L4 background, nesting granted | the v1 RPC `spawn` | throwaway `ceiling-probe-bg` | **PASS** |

Descendant attempts fail in both launch paths with the engine's own refusal text —
`Capability ceiling from agent:<name> does not allow agent '<name>'. Allowed agents: (none).` — while
every parent launch succeeds and every child completes on a schema-valid `structured_output`
report (L3 run 2 onward). On perk's actual def no spawn tool exists at all, and the engine's
capability audit records the empty ceiling (`allowedAgents: []`, source `agent:perk.scout`) for
every perk child, foreground and background. The L2 pair measures the bridge gap and its closure on
the same transport: the pre-edit child's system prompt carried the `Intercom orchestration channel:`
marker and `contact_supervisor`; the post-edit child's carried neither.

## Versions

| Component | Version |
| --- | --- |
| PATH `pi` (`pi --version`) | `1.1.0` |
| Root SDK (`$WT/node_modules/@earendil-works/pi-coding-agent/package.json`) | `1.1.0` |
| Worktree engine (`$WT/.pi/npm/node_modules/pi-subagents/package.json`) | `0.76.1` |
| Throwaway project engine (`$PROJ/.pi/npm/node_modules/pi-subagents/package.json`, installed by Pi itself on first start: `added 7 packages in 1s`) | `0.76.1` |
| Node | `v26.3.0` |
| `$MODEL` | `anthropic/claude-haiku-4-5` (the precedent's choice: the cheapest Anthropic model in the installed catalog; `auth.json` carries `openai` and `anthropic`, both `api_key`) |

Total measured spend across the six child runs (engine `usage.cost`): ≈ $0.072.

## Instrument

**Inventory recount.** `ls agents/*.md .pi/agents/perk-dev/*.md` listed **14** files (13 shipped +
`session-auditor`), each with `systemPromptMode: replace` directly after `tools:`, none carrying
`allowedAgents`. All 14 gained the blank line (commit `31b3542b`). The installed engine's own
frontmatter parser (`src/agents/frontmatter.js`, read ad hoc from a scratch script — never from a
test) returned `allowedAgents: ""` → `parseFrontmatterList` → `[]` for all 14.

**Setup.** `$SCRATCH` = the run's gitignored scratch dir (`.perk/workflow/scratch/runs/<run>/agent/live`
under `$WT`). `run-bounded.sh` was extracted byte for byte from
[`pi-1.0.0-characterization.md`](pi-1.0.0-characterization.md) § "The watchdog added after A11"
(SHA-256 `1114155f63fdd2ecb8616dbdf9a890de09b693deb5f6f3cf4aa7bf6fd94b0843`, matching the precedent).
`AUTHED=$(mktemp -d -t perk-ceil-authed)` held only a copy of the main checkout's
`.pi/agent/auth.json`. `PI_SUBAGENTS_TEMP_ROOT="$SCRATCH/subagents-tmp"` (empty before L1).
`HOSTROOT` = the PATH `pi`'s package root (`…/lib/node_modules/@earendil-works/pi-coding-agent`,
version 1.1.0).

**The throwaway project (L3, L4).** `PROJ=$(mktemp -d -t perk-ceil-proj)`, `git init`,
`.pi/settings.json` = `{"packages": ["npm:pi-subagents@0.76.1"]}` only — no perk extension, no perk
defs. Its two defs (`.pi/agents/<name>.md`):

```markdown
---
name: ceiling-probe            # ceiling-probe-bg for L4
description: Throwaway engine probe for the descendant ceiling (nesting granted, ceiling blank).
model: anthropic/claude-haiku-4-5
tools: read, subagent
allowedAgents:
systemPromptMode: replace
                               # L4 only: async: true
---

You are a probe. Follow the task exactly and report through structured_output.
```

(the `#` annotations are this record's, not file content). `description:` is required by the
engine's def loader (`frontmatter.name && frontmatter.description`) — the plan's sketch omitted it.

**Deviations from the plan's instrument, all recorded:**

- **Env scrub widened.** Besides the precedent's list (`PERK_RUN_ID`, `PERK_PROFILE_HANDOFF`,
  `PERK_SELFCHECK`, `PI_SUBAGENT_*`), the implementing session's own Pi identity (`PI_SESSION_FILE`,
  `PI_SESSION_ID`, `PI_MODEL`, `PI_PROVIDER`, `PI_REASONING_LEVEL`, `PI_CODING_AGENT`) was unset so no
  probe inherited it. `PERK_DISABLE_NATIVE_SDK_BRIDGE` was not set in the environment.
- **L1's start/collect split.** `runScoutWave` is the blocking form, so the run handle would only
  surface after completion. The probe calls `runScoutWave` once against a capturing stub to obtain
  the exact request it builds (one `perk.scout` assignment, `SCOUT_REPORT_SCHEMA`, `strict`, the
  model, `timeoutMs: 180000`), then launches that request through the production
  `createReportWave(pi.events)`'s `start` and drains it with `collect` — so the handle is printed
  before awaiting, and the spawn is byte-for-byte the launcher's.
- **L2 control ran after the def edit.** The control ran at `31b3542b` (defs already carrying the
  ceiling, transport unedited — `git diff --quiet HEAD -- extension/pi/v1/foregroundDelegation.ts`,
  file SHA-256 `433c514c…`); the bridge is independent of the ceiling, and the control's capability
  audit shows the ceiling already in force. The treatment ran at `0fe1f1fe` (file SHA-256
  `8ac0ef9b…`).
- **L3 run 2 sets `PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT="$HOSTROOT"`** — the engine's own knob,
  named in run 1's validator error. Same def, same spawn path, same pin; only the in-process
  validator's `typebox/compile` lookup is given the host root. Run 1 stays recorded as a harness
  failure (below).
- **L4's probe-side structured read hit `EISDIR`** (the engine nests the record one directory
  deeper: `structured-output/pi-subagent-structured-*/output.json`); the record file was read by
  hand before teardown (quoted below).

**The probe** (`$SCRATCH/probe-ceilings.ts`, SHA-256
`c6a58cc2dc21153cc6b27b32bbb72722252add7049a0737a51e78b13dce45afd`; verbatim except that the
absolute worktree path in the imports is written `$WT` here; never committed):

```ts
// $SCRATCH/probe-ceilings.ts — throwaway; drives ONE child per leg through perk's own spawn
// surfaces (or the engine's v1 RPC spawn) and prints what the child reports about its loadout.
//   /probe-foreground <provider/model> <agent> <spawn-target> <requestId>   (L2, L3)
//   /probe-scout <provider/model>                                            (L1)
//   /probe-rpc-bg <provider/model> <agent> <spawn-target>                    (L4)
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { dispatchForeground } from "$WT/extension/pi/v1/foregroundDelegation.ts";
import { createReportWave } from "$WT/extension/waves/reportWave.ts";
import { runScoutWave } from "$WT/extension/waves/scoutWave.ts";

const log = (label: string, value: unknown) =>
  console.error(`probe: ${label} ${JSON.stringify(value, null, 2)}`);

const PROBE_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["tools", "spawn_attempt", "contact_supervisor", "bridge_template"],
  properties: {
    tools: { type: "array", items: { type: "string" } },
    spawn_attempt: { type: "string" },
    contact_supervisor: { type: "boolean" },
    bridge_template: { type: "string" },
  },
};

const probeBrief = (target: string) =>
  "Do not read files or run commands. Report through `structured_output` exactly once: " +
  "`tools` (every tool name you have, verbatim), " +
  `\`spawn_attempt\` (call \`subagent({agent: "${target}", task: "reply hi"})\` ONCE if any such tool exists and quote its exact error/result; else the literal \`no spawn tool\`), ` +
  "`contact_supervisor` (boolean: whether a tool named contact_supervisor is available to you), " +
  "`bridge_template` (quote up to 200 chars of any supervisor/progress-update instruction in your system prompt, else `none`).";

const scoutBrief =
  "Do not read files or run commands. Report exactly four findings, each with basis \"verified\", and open_questions []. " +
  "Finding 1: pointer \"tool-loadout\", claim = every tool name you have, verbatim, comma-separated. " +
  "Finding 2: pointer \"descendant-attempt\", claim = the exact error/result of ONE call subagent({agent: \"perk.scout\", task: \"reply hi\"}) if any subagent/spawn tool exists, else the literal \"no subagent/spawn tool is present in this child\". " +
  "Finding 3: pointer \"contact-supervisor\", claim = \"contact_supervisor present: true\" or \"contact_supervisor present: false\" (whether a tool named contact_supervisor is available to you). " +
  "Finding 4: pointer \"bridge-template\", claim = a quote of up to 200 characters of any supervisor/progress-update instruction in your system prompt, else the literal \"no bridge template present\". " +
  "Each rationale is one short sentence. scope: \"own tool loadout and system prompt; no files read\".";

const RPC_REQUEST = "subagents:rpc:v1:request";
const RPC_REPLY = "subagents:rpc:v1:reply:";
function rpc(pi: ExtensionAPI, method: string, params?: unknown, timeoutMs = 30_000): Promise<Record<string, unknown>> {
  const requestId = `probe-${method}-${Date.now()}`;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { off(); reject(new Error(`rpc ${method} timed out`)); }, timeoutMs);
    const off = pi.events.on(RPC_REPLY + requestId, (data) => {
      const reply = data as Record<string, unknown>;
      // A context-less duplicate responder answers no_active_session first; keep waiting.
      if (reply.success === false && (reply.error as { code?: string })?.code === "no_active_session") return;
      clearTimeout(timer); off(); resolve(reply);
    });
    pi.events.emit(RPC_REQUEST, { version: 1, requestId, method, ...(params !== undefined ? { params } : {}) });
  });
}

function readJson(path: string): unknown {
  try { return JSON.parse(readFileSync(path, "utf8")); } catch (error) { return { unreadable: String(error) }; }
}

export default function (pi: ExtensionAPI) {
  pi.registerCommand("probe-foreground", {
    description: "one blocking child via perk's dispatchForeground",
    handler: async (args) => {
      const [model, agent, target, requestId] = args.trim().split(/\s+/);
      if (!model || !agent || !target || !requestId) { log("probe-error", "usage"); process.exitCode = 2; return; }
      log("launch", { pid: process.pid, cwd: process.cwd(), model, agent, target, requestId });
      const seen: unknown[] = [];
      const offs = ["started", "update"].map((k) => pi.events.on(`prompt-template:subagent:${k}`, (d) => {
        const r = d as Record<string, unknown>;
        if (r?.requestId === requestId) seen.push({ event: k, runId: r.runId, status: r.status });
      }));
      try {
        const outcome = await dispatchForeground(
          pi.events,
          { agent, task: probeBrief(target), cwd: process.cwd(), schema: PROBE_SCHEMA, model },
          { requestId, ownerRunId: "probe", nodeId: "ceiling" },
          new AbortController().signal,
        );
        log("lifecycle", { events: seen.length, first: seen[0], last: seen.at(-1) });
        log("status", outcome);
      } catch (error) {
        log("probe-error", String(error)); process.exitCode = 2;
      } finally { for (const off of offs) off(); }
    },
  });

  pi.registerCommand("probe-scout", {
    description: "one perk.scout lane via perk's own report-wave launcher",
    handler: async (args) => {
      const model = args.trim();
      if (!model) { log("probe-error", "usage"); process.exitCode = 2; return; }
      log("launch", { pid: process.pid, cwd: process.cwd(), model, tempRoot: process.env.PI_SUBAGENTS_TEMP_ROOT });
      try {
        const wave = createReportWave(pi.events);
        // runScoutWave is the blocking form; the start/collect split below is the same request
        // so the run handle is printed BEFORE awaiting completion.
        const request = { briefs: [{ key: "descendant-ceiling", task: scoutBrief }], model, timeoutMs: 180_000 };
        let captured: Parameters<typeof wave.run>[0] | undefined;
        await runScoutWave({ run: async (r) => { captured = r; return undefined as never; } } as never, request);
        const started = await wave.start(captured!);
        log("start", started.ok ? { ok: true, runId: started.runId, asyncDir: started.asyncDir, launch: started.launch } : started);
        if (!started.ok) { log("status", started.result); return; }
        for (;;) {
          const collected = await wave.collect(started.ref);
          if (collected.kind === "settled") { log("status", collected.result); break; }
          if (collected.kind === "none") { log("probe-error", "collect none"); break; }
        }
      } catch (error) {
        log("probe-error", String(error)); process.exitCode = 2;
      }
    },
  });

  pi.registerCommand("probe-rpc-bg", {
    description: "one background child via the v1 RPC spawn",
    handler: async (args) => {
      const [model, agent, target] = args.trim().split(/\s+/);
      if (!model || !agent || !target) { log("probe-error", "usage"); process.exitCode = 2; return; }
      log("launch", { pid: process.pid, cwd: process.cwd(), model, agent, target, tempRoot: process.env.PI_SUBAGENTS_TEMP_ROOT });
      try {
        const ping = await rpc(pi, "ping", undefined, 5_000);
        const asyncComplete = ((ping.data as Record<string, unknown>)?.events as Record<string, string>)?.asyncComplete;
        log("ping", { success: ping.success, asyncComplete });
        const completions: Record<string, unknown>[] = [];
        let wake: (() => void) | undefined;
        const off = pi.events.on(asyncComplete, (d) => { completions.push(d as Record<string, unknown>); wake?.(); });
        const params = {
          agent, task: probeBrief(target), async: true, context: "fresh", model,
          outputSchema: PROBE_SCHEMA, intercomBridge: { mode: "off" }, timeoutMs: 180_000,
        };
        const reply = await rpc(pi, "spawn", params);
        const data = (reply.data ?? {}) as Record<string, unknown>;
        const details = (data.details ?? {}) as Record<string, unknown>;
        const asyncId = (details.asyncId ?? data.asyncId) as string | undefined;
        const asyncDir = (details.asyncDir ?? data.asyncDir) as string | undefined;
        log(`spawn(${agent})`, { success: reply.success, error: reply.error, asyncId, asyncDir, dataKeys: Object.keys(data), detailKeys: Object.keys(details) });
        if (!reply.success || !asyncId) { log("probe-error", "spawn failed"); off(); return; }
        const deadline = Date.now() + 250_000;
        const match = () => completions.find((c) => c.asyncId === asyncId || c.id === asyncId || c.runId === asyncId || c.asyncDir === asyncDir);
        while (!match() && Date.now() < deadline) await new Promise<void>((r) => { wake = r; setTimeout(r, 5_000); });
        off();
        const completion = match();
        log("completion", completion ? { keys: Object.keys(completion), state: completion.state, success: completion.success } : "none within 250s");
        const status = asyncDir ? readJson(join(asyncDir, "status.json")) : null;
        let structured: unknown = null;
        if (asyncDir) {
          try {
            const dir = join(asyncDir, "structured-output");
            structured = Object.fromEntries(readdirSync(dir).map((f) => [f, readJson(join(dir, f))]));
          } catch (error) { structured = { unreadable: String(error) }; }
        }
        log("status", { completion: Boolean(completion), state: (status as Record<string, unknown>)?.state, structured });
      } catch (error) {
        log("probe-error", String(error)); process.exitCode = 2;
      }
    },
  });
}
```

**Commands** (each a fresh process; L1/L2 from `$WT`, L3/L4 from `$PROJ`):

```bash
SCRUB=(-u PERK_RUN_ID -u PERK_PROFILE_HANDOFF -u PERK_SELFCHECK -u PI_SUBAGENT_CHILD
       -u PI_SUBAGENT_CHILD_AGENT -u PI_SUBAGENT_EXTENSION_BINDINGS -u PI_SESSION_FILE -u PI_SESSION_ID
       -u PI_MODEL -u PI_PROVIDER -u PI_REASONING_LEVEL -u PI_CODING_AGENT)
ENV=(PERK_SKIP_VERSION_CHECK=1 PI_CODING_AGENT_DIR="$AUTHED" PI_SUBAGENTS_TEMP_ROOT="$SCRATCH/subagents-tmp")
run() { GRACE=60 CAP=330 "$SCRATCH/run-bounded.sh" "$SCRATCH/$1.log" env "${SCRUB[@]}" "${ENV[@]}" "${@:3}" \
          pi --approve --mode json -e "$SCRATCH/probe-ceilings.ts" -p "$2"; }

cd "$WT"
run L2-control   "/probe-foreground $MODEL perk.scout perk.scout probe-l2-control"     # at 31b3542b
run L2-treatment "/probe-foreground $MODEL perk.scout perk.scout probe-l2-treatment"   # at 0fe1f1fe
run L1           "/probe-scout $MODEL"
cd "$PROJ"
run L3           "/probe-foreground $MODEL ceiling-probe ceiling-probe probe-l3"
run L4           "/probe-rpc-bg $MODEL ceiling-probe-bg ceiling-probe-bg"
run L3b          "/probe-foreground $MODEL ceiling-probe ceiling-probe probe-l3b" \
                 PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT="$HOSTROOT"
```

(The `run` helper is this record's shorthand for the six literal invocations, which spelled the
same `env -u … pi …` line out in full.) **Bounding:** `GRACE=60 CAP=330` everywhere; the two
background legs set the engine deadline `timeoutMs: 180000` (L1 through the scout request, L4 in
the RPC params) — status files confirm `timeoutMs` 180000 (L1 workflow, L4) and 179904 (L1 child,
the inherited remainder). The foreground legs ran under the transport's fixed 30-minute deadline.
The watchdog never fired (no `watchdog:` line in any log).

## L2 — foreground, actual def: control then treatment

### Control (2026-10-10T23:28:14Z, transport at `31b3542b`)

```text
probe: launch {
  "pid": 76133,
  "cwd": "$WT",
  "model": "anthropic/claude-haiku-4-5",
  "agent": "perk.scout",
  "target": "perk.scout",
  "requestId": "probe-l2-control"
}
probe: lifecycle {
  "events": 5,
  "first": {
    "event": "started"
  },
  "last": {
    "event": "update",
    "runId": "808a9cb1-a01f-40a7-a1eb-6334bb84af18"
  }
}
probe: status {
  "terminal": {
    "status": "completed",
    "value": {
      "tools": [
        "read",
        "grep",
        "find",
        "ls",
        "bash",
        "structured_output",
        "contact_supervisor"
      ],
      "spawn_attempt": "no spawn tool",
      "contact_supervisor": true,
      "bridge_template": "Meaningful progress or unexpected discoveries that change the plan: contact_supervisor({ reason: \"progress_update\", message: \"UPDATE: <summary>\" })"
    },
    "runId": "808a9cb1-a01f-40a7-a1eb-6334bb84af18",
    "agent": "perk.scout",
    "exitCode": 0
  },
  "release": true,
  "termination": "confirmed",
  "observedRunId": "808a9cb1-a01f-40a7-a1eb-6334bb84af18"
}
exit=0 elapsed=32s
```

### Treatment (2026-10-10T23:33:22Z, transport at `0fe1f1fe`)

```text
probe: launch {
  "pid": 91839,
  "cwd": "$WT",
  "model": "anthropic/claude-haiku-4-5",
  "agent": "perk.scout",
  "target": "perk.scout",
  "requestId": "probe-l2-treatment"
}
probe: lifecycle {
  "events": 5,
  "first": {
    "event": "started"
  },
  "last": {
    "event": "update",
    "runId": "dfbea343-1c53-4943-bafd-c8693ba34ad5"
  }
}
probe: status {
  "terminal": {
    "status": "completed",
    "value": {
      "tools": [
        "read",
        "grep",
        "find",
        "ls",
        "bash",
        "structured_output"
      ],
      "spawn_attempt": "no spawn tool",
      "contact_supervisor": false,
      "bridge_template": "none"
    },
    "runId": "dfbea343-1c53-4943-bafd-c8693ba34ad5",
    "agent": "perk.scout",
    "exitCode": 0
  },
  "release": true,
  "termination": "confirmed",
  "observedRunId": "dfbea343-1c53-4943-bafd-c8693ba34ad5"
}
exit=0 elapsed=31s
```

**Engine-written corroboration** (the in-process child's own session file and artifact meta under
`$AUTHED/sessions/…`): the control child's `session.jsonl` carries the bridge marker
`Intercom orchestration channel:` (one matching line); the treatment child's carries none. The capability
audits (`subagent-artifacts/<runId>_perk.scout_0_meta.json`):

| Run | `ceiling.allowedAgents` / `sources` | `requestedTools` | `effectiveTools` |
| --- | --- | --- | --- |
| control `808a9cb1` | `[]` / `agent:perk.scout` | `read, grep, find, ls, bash, contact_supervisor` | `read, grep, find, ls, bash, contact_supervisor, structured_output` |
| treatment `dfbea343` | `[]` / `agent:perk.scout` | `read, grep, find, ls, bash` | `read, grep, find, ls, bash, structured_output` |

The control's `contact_supervisor` is the bridge's tool append onto the def's explicit allowlist
(`applyIntercomBridgeToAgent`), measured; the treatment's request carried `{mode: "off"}` and the
append is gone.

## L1 — background, actual def (2026-10-10T23:33:59Z)

```text
probe: launch {
  "pid": 92082,
  "cwd": "$WT",
  "model": "anthropic/claude-haiku-4-5",
  "tempRoot": "$SCRATCH/subagents-tmp"
}
probe: start {
  "ok": true,
  "runId": "e6c7e9fe-cf47-4823-b2b6-c9f66785ebdd",
  "asyncDir": "$SCRATCH/subagents-tmp/async-subagent-runs/e6c7e9fe-cf47-4823-b2b6-c9f66785ebdd",
  "launch": {
    "requested": [
      "descendant-ceiling"
    ],
    "runnable": [
      "descendant-ceiling"
    ],
    "preflightFailures": []
  }
}
probe: status {
  "complete": true,
  "reports": [
    {
      "key": "descendant-ceiling",
      "report": {
        "scope": "Own tool loadout and system prompt; no files read.",
        "findings": [
          {
            "pointer": "tool-loadout",
            "claim": "read, grep, find, ls, bash, structured_output",
            "basis": "verified",
            "rationale": "These six tools are defined in my function schema at session initialization."
          },
          {
            "pointer": "descendant-attempt",
            "claim": "no subagent/spawn tool is present in this child",
            "basis": "verified",
            "rationale": "My tool schema contains only read, grep, find, ls, bash, and structured_output; no spawn or subagent invocation tool is available."
          },
          {
            "pointer": "contact-supervisor",
            "claim": "contact_supervisor present: false",
            "basis": "verified",
            "rationale": "contact_supervisor does not appear in my available tool definitions."
          },
          {
            "pointer": "bridge-template",
            "claim": "no bridge template present",
            "basis": "verified",
            "rationale": "No supervisor/progress-update instruction template or bridge instruction exists in my system prompt."
          }
        ],
        "open_questions": []
      }
    }
  ],
  "failures": [],
  "receipt": {
    "runId": "e6c7e9fe-cf47-4823-b2b6-c9f66785ebdd",
    "asyncDir": "$SCRATCH/subagents-tmp/async-subagent-runs/e6c7e9fe-cf47-4823-b2b6-c9f66785ebdd",
    "state": "complete",
    "children": [
      {
        "key": "descendant-ceiling",
        "runId": "951a541e-cb8b-408e-9f56-610d8f9d3bef",
        "success": true,
        "outputState": "present",
        "artifactPaths": {
          "outputPath": "$AUTHED/sessions/--<WT-slug>--/subagent-artifacts/951a541e-cb8b-408e-9f56-610d8f9d3bef_perk.scout_output.md"
        },
        "agent": "perk.scout"
      }
    ]
  }
}
Extension error ($WT/extension/index.ts): This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after ctx.newSession(), ctx.fork(), ctx.switchSession(), or ctx.reload(). For newSession, fork, and switchSession, move post-replacement work into withSession and use the ctx passed to withSession. For reload, do not use the old ctx after await ctx.reload().
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
Extension error ($WT/extension/index.ts): This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after ctx.newSession(), ctx.fork(), ctx.switchSession(), or ctx.reload(). For newSession, fork, and switchSession, move post-replacement work into withSession and use the ctx passed to withSession. For reload, do not use the old ctx after await ctx.reload().
exit=0 elapsed=25s
```

The four claims by pointer: `tool-loadout` = `read, grep, find, ls, bash, structured_output`;
`descendant-attempt` = `no subagent/spawn tool is present in this child`; `contact-supervisor` =
`contact_supervisor present: false`; `bridge-template` = `no bridge template present`.

**The child's run dir** (`$SCRATCH/subagents-tmp/async-subagent-runs/951a541e-cb8b-408e-9f56-610d8f9d3bef/`):

- `recovery-descriptor.json`: `"agentFilePath": "$WT/agents/scout.md"`, `"tools": ["read", "grep",
  "find", "ls", "bash"]`, `"allowedAgents": []`, `"intercomBridge": {"mode": "off"}`.
- `status.json`: `state` `complete`, runner `pid` 92191, `timeoutMs` 179904,
  `parentWorkflowRunId` `e6c7e9fe-…`, `capabilityCeiling` `{"version": 1, "allowedAgents": [],
  "denyExtensions": false, "sources": ["agent:perk.scout"]}`, `capabilityAudit.effectiveTools`
  `read, grep, find, ls, bash, structured_output`, `agentAllowed: true`.
- No file in the run dir carries the bridge marker.

The three `Extension error` lines after the probe's terminal line are post-terminal (see
"Observed side effects").

## L3 — foreground, nesting granted

### Run 1 — harness failure (2026-10-10T23:35:12Z)

```text
added 7 packages in 1s
probe: launch {
  "pid": 92491,
  "cwd": "$PROJ",
  "model": "anthropic/claude-haiku-4-5",
  "agent": "ceiling-probe",
  "target": "ceiling-probe",
  "requestId": "probe-l3"
}
probe: lifecycle {
  "events": 12,
  "first": {
    "event": "started"
  },
  "last": {
    "event": "update",
    "runId": "f90972a2-b695-4ae2-a694-552ee3d87878"
  }
}
probe: status {
  "terminal": {
    "status": "structured_output_failed",
    "runId": "f90972a2-b695-4ae2-a694-552ee3d87878",
    "agent": "ceiling-probe",
    "exitCode": 1
  },
  "release": false,
  "termination": "unconfirmed",
  "observedRunId": "f90972a2-b695-4ae2-a694-552ee3d87878"
}
exit=0 elapsed=53s
```

`added 7 packages in 1s` is Pi installing `pi-subagents@0.76.1` into `$PROJ/.pi/npm` on first
start. The child's engine-written transcript (`$AUTHED/sessions/…/f90972a2-…/run-0/session.jsonl`),
tool calls and results in order:

```text
toolCall   subagent          {"agent":"ceiling-probe","task":"reply hi"}
toolResult subagent          "Run fan-out: 2/64 used, 62 remaining\nCapability ceiling from agent:ceiling-probe does not allow agent 'ceiling-probe'. Allowed agents: (none)."
toolCall   structured_output {"value":{"tools":["read","subagent","structured_output"],"spawn_attempt":"Capability ceiling from agent:ceiling-probe does not allow agent 'ceiling-probe'. All…
toolResult structured_output "Cannot load typebox/compile for structured output validation (direct import failed: Cannot find package 'typebox' imported from $PROJ/.pi/npm/node_modules/pi-subagents/src/runs/shared/structured-output.js; PI_SUBAGENTS_PI_C…"
(the structured_output call and its error repeat once more; the child then ends in prose)
```

**Classification: harness failure, not an engine measurement.** The leg's criterion — `completed`
with a valid report — is unmet because the bare project's in-process structured-output validator
cannot resolve `typebox` (Pi installs managed npm packages with peer installation suppressed, and
this project has no perk extension whose native SDK bridge would serve it). The ceiling refusal
itself is engine-written in the transcript, and the parent's launch succeeded (started + 12
lifecycle events, `observedRunId`); the transport correctly withheld release
(`release: false, termination: unconfirmed`) on a non-`completed` terminal.

### Run 2 — PASS (2026-10-10T23:37:39Z, `PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT="$HOSTROOT"`)

```text
probe: launch {
  "pid": 93203,
  "cwd": "$PROJ",
  "model": "anthropic/claude-haiku-4-5",
  "agent": "ceiling-probe",
  "target": "ceiling-probe",
  "requestId": "probe-l3b"
}
probe: lifecycle {
  "events": 8,
  "first": {
    "event": "started"
  },
  "last": {
    "event": "update",
    "runId": "cdd628bc-67ce-4299-a41b-af0335a6b374"
  }
}
probe: status {
  "terminal": {
    "status": "completed",
    "value": {
      "tools": [
        "read",
        "subagent",
        "structured_output"
      ],
      "spawn_attempt": "Capability ceiling from agent:ceiling-probe does not allow agent 'ceiling-probe'. Allowed agents: (none).",
      "contact_supervisor": false,
      "bridge_template": "none"
    },
    "runId": "cdd628bc-67ce-4299-a41b-af0335a6b374",
    "agent": "ceiling-probe",
    "exitCode": 0
  },
  "release": true,
  "termination": "confirmed",
  "observedRunId": "cdd628bc-67ce-4299-a41b-af0335a6b374"
}
exit=0 elapsed=15s
```

The transcript's `subagent` tool result is again `Run fan-out: 2/64 used, 62 remaining\nCapability
ceiling from agent:ceiling-probe does not allow agent 'ceiling-probe'. Allowed agents: (none).`, and
`structured_output` answered `Structured output captured.` Capability audit (`…_meta.json`):
ceiling `[]` / `agent:ceiling-probe`, requested `read, subagent`, effective `read, subagent,
structured_output` — the ceiling leaves the child's own tools untouched.

## L4 — background, nesting granted (2026-10-10T23:36:50Z)

```text
probe: launch {
  "pid": 92947,
  "cwd": "$PROJ",
  "model": "anthropic/claude-haiku-4-5",
  "agent": "ceiling-probe-bg",
  "target": "ceiling-probe-bg",
  "tempRoot": "$SCRATCH/subagents-tmp"
}
probe: ping {
  "success": true,
  "asyncComplete": "subagent:async-complete"
}
probe: spawn(ceiling-probe-bg) {
  "success": true,
  "asyncId": "100f899b-dc0b-4609-a78c-7ca1e018d31d",
  "asyncDir": "$SCRATCH/subagents-tmp/async-subagent-runs/100f899b-dc0b-4609-a78c-7ca1e018d31d",
  "dataKeys": [
    "text",
    "details"
  ],
  "detailKeys": [
    "mode",
    "runId",
    "results",
    "asyncId",
    "asyncDir",
    "launchContractDigest",
    "launchResolvedExtensions",
    "context",
    "timeoutMs",
    "deadlineAt",
    "runFanoutBudget",
    "missionId",
    "missionPath",
    "mission"
  ]
}
probe: completion {
  "keys": [
    "lifecycleArtifactVersion",
    "id",
    "agent",
    "mode",
    "success",
    "state",
    "summary",
    "timeoutMs",
    "deadlineAt",
    "results",
    "outputs",
    "capabilityCeiling",
    "capabilityAudit",
    "exitCode",
    "timestamp",
    "durationMs",
    "totalTokens",
    "totalCost",
    "truncated",
    "artifactsDir",
    "cwd",
    "asyncDir",
    "launchContractDigest",
    "launchResolvedExtensions",
    "sessionId",
    "completionOwnerId",
    "sessionFile",
    "runId",
    "notificationDeliveredAt",
    "triggerTurn",
    "intercomDelivered"
  ],
  "state": "complete",
  "success": true
}
probe: status {
  "completion": true,
  "state": "complete",
  "structured": {
    "pi-subagent-structured-uEIhxW": {
      "unreadable": "Error: EISDIR: illegal operation on a directory, read"
    }
  }
}
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
exit=0 elapsed=25s
```

**The run dir** (`$SCRATCH/subagents-tmp/async-subagent-runs/100f899b-dc0b-4609-a78c-7ca1e018d31d/`):

- `structured-output/pi-subagent-structured-uEIhxW/output.json` (read by hand):

  ```json
  {"tools":["read","subagent","structured_output"],"spawn_attempt":"Capability ceiling from agent:ceiling-probe-bg does not allow agent 'ceiling-probe-bg'. Allowed agents: (none).","contact_supervisor":false,"bridge_template":"You are a child subagent with explicit fanout responsibility for this assigned task. The parent session owns final orchestration, acceptance, and follow-up implementation launches."}
  ```

  The quoted `bridge_template` is pi-subagents' fanout-child instruction (present because nesting
  is granted), not the intercom bridge: no file in the run dir carries the
  `Intercom orchestration channel:` marker.
- `output-0.log` carries the refusal line once; `events.jsonl` repeats it in its tool events.
- `recovery-descriptor.json`: `"agentFilePath": "$PROJ/.pi/agents/ceiling-probe-bg.md"`,
  `"tools": ["read", "subagent"]`, `"allowedAgents": []`, `"intercomBridge": {"mode": "off"}`,
  `"maxSubagentDepth": 2`.
- `status.json`: `state` `complete`, runner `pid` 93005, `timeoutMs` 180000, `capabilityCeiling`
  `{"allowedAgents": [], "sources": ["agent:ceiling-probe-bg"]}`, `effectiveTools`
  `read, subagent, structured_output`, `agentAllowed: true`.

## Stop-and-confirm (before any deletion)

| Run dir | Kind | `status.json` `state` | `process-terminal.json` | pid (`kill -0`) |
| --- | --- | --- | --- | --- |
| `951a541e-…` (L1 child) | runner | `complete` | `observed`, runner `exitCode: 0`, `signal: null`, `closeObservedAt` 1791675261867 | 92191 gone |
| `e6c7e9fe-…` (L1 workflow) | workflow orchestrator in the parent | `complete` | absent by construction — no runner process (status `pid` is the parent's) | 92082 (the parent) gone |
| `100f899b-…` (L4) | runner | `complete` | `observed`, runner `exitCode: 0`, `signal: null`, `closeObservedAt` 1791675427209 | 93005 gone |

No run needed `kill -TERM`; nothing was harness-terminated. Every probe parent (pids 76133, 91839,
92082, 92491, 92947, 93203) was gone; `pgrep -fl 'subagent-runner|pi-subagents|probe-ceilings'`
matched nothing, and the only `pi` processes left were sessions the probe did not start.

**Teardown (2026-10-10T23:40:13Z).** `rm -rf "$PROJ" "$AUTHED" "$SCRATCH/subagents-tmp"` (each
verified gone), then the rest of `$SCRATCH`'s live instrument (probe, watchdog, raw logs) after this
record was written. `git status --porcelain` in `$WT` was empty after the legs (the scratch dir is
gitignored).

## Observed side effects (not measurements)

- **Post-terminal extension errors in print mode.** After L1's terminal line, perk's extension
  logged `This extension ctx is stale after session replacement or reload…` twice and the
  `<boundary>` logged `turn_end could not resolve the persisted assistant entry ID` once; after
  L4's, the `<boundary>` line appeared once (no perk extension loaded there). Both are the
  background legs (L4's async-complete payload carries a `triggerTurn` key); the errors arrive after the
  probe's command returned and did not change any exit code (`exit=0`). Not investigated here.
- **Fan-out accounting.** Each refused attempt's tool result leads with `Run fan-out: 2/64 used,
  62 remaining`; whether the refused attempt itself is one of the two counted was not determined.

## Planning-time facts

- **Confirmed:** the default global `intercomBridge.mode` activates the bridge for a fresh-context
  foreground writer (L2 control); a background lane spawned bridge-off has no `subagent`,
  `contact_supervisor` or template (L1, matching the planning baseline); the def's blank
  `allowedAgents:` reaches the recovery descriptor as `[]` and the child runtime as the ceiling
  `{allowedAgents: [], sources: ["agent:<name>"]}` in both launch paths; the ceiling bites only where
  a nesting grant exists and leaves the child's own tools untouched (L3/L4 effective tools keep
  `subagent`); the refusal text is exactly the planned string.
- **Falsified:** none.
- **New (engine environment, exact pin):** a Pi-installed `pi-subagents@0.76.1` in a bare project
  cannot validate `structured_output` in an **in-process foreground** child unless
  `typebox/compile` is resolvable from its root or `PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT` names
  the host; the **background runner** validated without the variable (L4). Under perk the native
  SDK bridge serves `typebox`, so perk's own writers are unaffected (L2 completed both times).

## Residuals

- **For node 7.1's certification:** no leg is NOT MEASURED. L3's PASS rests on run 2 with the
  engine's package-root variable set (run 1 is a harness failure, recorded above). The two real
  writers (`perk.conflict-resolver`, `perk.librarian`) were not driven live — L2 measures their
  shared transport with `perk.scout` as the def; a certification run may drive a real writer
  dispatch. The post-terminal print-mode extension errors are unexplained.
- **`/learn` candidates (not edited here):** `docs/learned/pi/subagents.md` § "Native child
  execution" (the writer profile now bridge-off) and § "Supervisor channel";
  `docs/learned/workflow/mergeability-and-conflict-resolution.md` § "The transport"; the
  bare-project `typebox` gap above.
- **Node 7.2 (not edited here):** `docs/design/pi-subagents-child-execution-policy.md` gains the
  descendant ceiling and the writer bridge-off invariant as policy facts.
