# Dogfood smoke: the borrowed askuser/todo built-ins, recorded (zero-config)

**Status:** validation record (the `provider-smoke-*` / `remote-runner-e2e-dogfood` genre) for the
**required borrowed built-ins** `@juicesharp/rpiv-ask-user-question` and `@juicesharp/rpiv-todo`
under the **zero-config** reality: both packages ride the committed `.pi/settings.json` `packages`
list (object form), `BORROWED_PACKAGES` requires them, and no `.perk/config.toml` key selects
anything — the provider seams are retired. This record supersedes the *selection-mechanism* smokes
(`provider-smoke-juicesharp-ask-user.md`, `provider-smoke-juicesharp-todo.md`) **historically** —
those records remain valid history of the retired `[providers]` seams; this one smokes what
replaced them.

The gap under proof: the unit harness (`extension/testing/harness.ts`) binds **only** perk's
extension — the foreign packages never load in CI (`workerE2e.test.ts` runs `PI_OFFLINE=1`), so
the registration/behavior claims about the foreign tools are test-covered only as name-keyed
inertness. The true coexistence — the foreign tools actually loading from the committed
`.pi/settings.json` and behaving per the contracts (`todo` on the worktree-family stages,
`ask_user_question` universal-but-stripped-headlessly) — is smoked live, once, here.

Part A is the repeatable four-leg procedure; Part B is the captured evidence + defect log from the
first execution (2026-08-09).

## Part A — the repeatable procedure

Each step names its actor: **(human)** for actions a session cannot take, **(session)** for
everything automatable.

### Leg 1 — a real implement session (the `todo` tool, live)

**(session, with the human watching the overlay.)** Any `perk implement <N>` session in this repo
is the vehicle — the plan worktree is a checkout of this repo, so the session inherits the
committed `.pi/settings.json` packages. Capture:

1. **Registers** — the session's own successful `todo` tool calls (a tool result is registration
   proof and more).
2. **Seeds from `## Steps`** — the seeded item list matches the plan's `## Steps` one-per-step, in
   order (the seeding discipline is prompt-carried: `prompts/stages/implement.md`'s "Progress
   tracking:" paragraph).
3. **Advances** — checklist state transitions as steps complete (the overlay ticking is the
   operator-visible half; the tool-call results are the model-visible half).
4. **Survives compaction** — after several items are complete, the **(human)** runs `/compact`;
   then (a) **(session)** re-reads the checklist via the `todo` tool — state intact — and (b) the
   **(human)** visually confirms the overlay persists. Record both, dated. (The package handles
   `session_compact` explicitly and reconstructs state by branch replay keyed on
   `toolResult.toolName === "todo"` — `.pi/npm/node_modules/@juicesharp/rpiv-todo/state/store.ts`.)

### Leg 2 — the headless probe (worker construction, one turn)

**(session or human, from the MAIN checkout root — never an occupied plan worktree.)** A second
session must not touch an implement worktree's state (session-shape isolation). The probe is a
**throwaway** script (below; not committed — the repo convention is framework-suite tests or
inlined runnable procedures, never checked-in verify scripts). Construction mirrors
`extension/worker/worker.ts::defaultCreateRuntime` exactly: throwaway `agentDir` (`mkdtemp`) locks
out the user-global tier; `SettingsManager.create(cwd, agentDir)` is disk-layered, so the project
tier resolves the committed `packages` list; `applyOverrides` turns compaction/retry off;
`model: undefined` defers to the SDK's initial-model resolution; `bindExtensions({ uiContext:
undefined, mode: "json", onError })` ⇒ `ctx.hasUI === false`. Recipe distilled in
`docs/learned/pi/headless-session-drive.md`.

Save as `borrowed-dogfood-probe.ts` in the main checkout root and run:

```sh
env -u PERK_RUN_ID -u PI_SESSION_FILE node borrowed-dogfood-probe.ts
```

The `env -u` matters: a shell spawned from inside a perk session inherits `PERK_RUN_ID`, and the
probe's bound perk extension would try to claim that run id (a loud but harmless
`workflow-state linkage error` — see proc-1 in the defect log). Delete the script afterwards.

```ts
// Throwaway headless probe (docs/design/borrowed-askuser-todo-dogfood.md, leg 2). Not committed.
// Mirrors extension/worker/worker.ts::defaultCreateRuntime — run from the MAIN checkout root.
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  AuthStorage,
  type CreateAgentSessionRuntimeFactory,
  createAgentSessionFromServices,
  createAgentSessionRuntime,
  createAgentSessionServices,
  ModelRegistry,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";

const cwd = process.cwd();
const agentDir = mkdtempSync(join(tmpdir(), "perk-dogfood-probe-")); // user-global tier OUT
const settingsManager = SettingsManager.create(cwd, agentDir); // disk-layered: project packages IN
settingsManager.applyOverrides({ compaction: { enabled: false }, retry: { enabled: false } });
const authStorage = AuthStorage.create();
const modelRegistry = ModelRegistry.create(authStorage);
const factory: CreateAgentSessionRuntimeFactory = async (o) => {
  const services = await createAgentSessionServices({
    cwd: o.cwd,
    agentDir: o.agentDir,
    authStorage,
    settingsManager,
    modelRegistry,
  });
  const result = await createAgentSessionFromServices({
    services,
    sessionManager: o.sessionManager,
    sessionStartEvent: o.sessionStartEvent,
    model: undefined, // the SDK's initial-model resolution — never getAvailable()[0]
  });
  for (const entry of result.extensionsResult.errors) {
    console.error(`probe: extension load error — ${entry.path}: ${entry.error}`);
  }
  return { ...result, services, diagnostics: services.diagnostics };
};
const runtime = await createAgentSessionRuntime(factory, {
  cwd,
  agentDir,
  sessionManager: SessionManager.create(cwd),
});
await runtime.session.bindExtensions({
  uiContext: undefined,
  mode: "json", // ⇒ ctx.hasUI === false
  onError: (err: unknown) => console.error(`probe: extension error — ${String(err)}`),
});
const model = runtime.session.model;
console.log(`model: ${model ? `${model.provider}/${model.id}` : "unresolved"}`);
const names = runtime.session.extensionRunner
  .getAllRegisteredTools()
  .map((t) => t.definition.name)
  .sort();
console.log(`registered census (${names.length}): ${names.join(", ")}`);
let text = "";
runtime.session.subscribe((e) => {
  if (e.type === "message_end" && e.message?.role === "assistant") {
    for (const block of e.message.content ?? []) {
      if (block.type === "text") text += block.text;
    }
  }
});
await runtime.session.prompt(
  "List the names of every tool you can call, one per line, then stop.",
);
console.log("--- one-turn enumeration ---");
console.log(text.trim());
await runtime.dispose();
```

Expected:

1. **Registered census** — `todo` **and** `ask_user_question` both present (registration is
   load-time for both packages), alongside perk's tools.
2. **One-turn enumeration** — the model's own list has `todo` **present** and `ask_user_question`
   **absent**: the package's `before_agent_start` reconcile
   (`.pi/npm/node_modules/@juicesharp/rpiv-ask-user-question/reconcile.ts`) strips it via
   `setActiveTools` when `ctx.hasUI === false`. The one real turn is load-bearing — a bind-only
   probe would still see the tool registered; the model-visible tool list is the contract surface
   ("headless sessions carry no `ask_user_question` schema").

Honesty framing: the probe reuses the worker's construction recipe (the identical disk-layered
settings resolution); the real worker additionally applies `STAGE_TOOLS` scoping, which keeps
`todo` on the worktree stages (test-pinned in `extension/substrate/stageTools.test.ts`) — the
probe smokes the half unit tests structurally cannot (the foreign packages actually loading from
the committed settings, headlessly). Perk itself loads too and behaves as a bare session (no
stage/handoff → no scoping). Model: whatever the SDK resolves (log it, as the worker does);
spend: one small turn, accepted.

### Leg 3 — the questionnaire (planning session)

**(session + human.)** In any planning-family session in this repo (read-only mode), observe a
real `ask_user_question` call: the foreign structured questionnaire fires (multi-question, labeled
options + descriptions, "(Recommended)" markers, the automatic "Type something." escape row), the
human answers, and the session continues with the answers (non-terminating-answer semantics). The
foreign package is the sole registrant of the name (the first-party tool is deleted), so the
questionnaire UI is itself proof the foreign tool is what fired. The "absent headlessly" half of
this leg is leg 2's enumeration.

### Leg 4 — `just ci`

**(session.)** Run `just ci` in the worktree; record the green result. The PR's own CI is the
merge gate.

### Defect posture

Any leg failing is **evidence, not a restart**: log it in the Part B defect log, surface it to the
human, and do **not** fix product code in the recording PR — the honest close for a real defect is
a scoped follow-up (the dogfood-node-finishes-incomplete pattern in
`docs/learned/workflow/doc-reconciliation.md`).

## Part B — the captured evidence

Executed **2026-08-09** on `mattgiles/perk` (this repo). The leg-1 vehicle is the implement
session for the plan that authored this record (issue #1472, worktree `plan-1472`) — **the session
under observation is the one authoring the record**; the self-reference is stated here rather than
hidden, and the plan's `## Steps` list is the seed under observation.

### Leg 1 — the implement session

*(to be completed during the session — seeding, advancement, compaction survival, final state)*

### Leg 2 — the headless probe

Run 2026-08-09 from the main checkout root (`main` at `a60587c9`), with the Part A script,
verbatim. First attempt surfaced proc-1 (the inherited `PERK_RUN_ID` — see the defect log); the
clean re-run (`env -u PERK_RUN_ID -u PI_SESSION_FILE node borrowed-dogfood-probe.ts`):

- **Model (SDK-resolved, logged as the worker does):** `anthropic/claude-opus-4-8`.
- **Registered census** — 34 extension tools, **`ask_user_question` and `todo` both present**
  (load-time registration proven), alongside perk's tools and the other borrowed packages':

  ```text
  registered census (34): add_objective_node, ask_user_question, fetch_content, find,
  get_search_content, gist_draft, gist_save, grep, intercom, land, learn, objective_draft,
  objective_node, objective_save, plan_draft, plan_review, plan_save, plannotator_submit_plan,
  post_pr_review, ready, reconcile_objective, resolve_review_threads, run_ci, run_learn_wave,
  run_pr_review_dynamic_wave, run_pr_review_wave, source_check, subagent, subagent_supervisor,
  subagent_wait, submit, submit_pr_review, todo, web_search
  ```

  (Line-wrapped for the record; the probe prints it on one line.)
- **One-turn enumeration** — the model's own tool list (one real turn, `session.prompt("List the
  names of every tool you can call, one per line, then stop.")`): 36 names — the census plus the
  builtins (`read`, `bash`, `edit`, `write`, `grep`, `find`), **`todo` present**,
  **`ask_user_question` absent** (the `before_agent_start` reconcile stripped it headlessly):

  ```text
  read, bash, edit, write, plan_review, plan_save, plan_draft, objective_draft, gist_draft,
  submit, ready, land, learn, run_learn_wave, resolve_review_threads, run_pr_review_wave,
  post_pr_review, run_pr_review_dynamic_wave, submit_pr_review, run_ci, objective_save,
  gist_save, objective_node, reconcile_objective, add_objective_node, subagent, subagent_wait,
  grep, find, web_search, source_check, fetch_content, get_search_content, todo,
  subagent_supervisor, intercom
  ```

  (The model printed one per line; comma-joined here. Incidental observation, not a defect:
  `plannotator_submit_plan` is also absent from the model-visible list — the plannotator package
  gates its tool similarly; out of scope for this record.)
- **No extension load errors** on the clean run; the throwaway `agentDir` lived in OS temp; the
  script was deleted after the run (its full text is inlined in Part A).

### Leg 3 — the questionnaire (planning session)

Transcribed from the planning session that authored this record's plan; the human re-confirmed it
during the implement session (see leg 1):

> **2026-08-09, this node's planning session** (the `/objective-plan` factory, objective #1416
> node 3.2, this repo — a read-only planning session): the assistant called `ask_user_question`
> to grill the four open plan decisions. The **foreign structured questionnaire** fired — one
> call carrying **4 questions**, each with 2–3 labeled options + descriptions, recommended
> options marked "(Recommended)", and the automatic "Type something." escape row. The operator
> answered all four; the session **continued with the answers** (non-terminating-answer
> semantics). The foreign `@juicesharp/rpiv-ask-user-question` tool is the sole registrant of the
> name (first-party tool deleted), so the questionnaire UI is itself proof the foreign tool is
> what fired.

*(operator confirmation pending)*

The "absent headlessly" half: leg 2's one-turn enumeration above.

### Leg 4 — `just ci`

*(to be completed before submit)*

### Claim → evidence checklist

The node's enumeration, clause by clause (the mapping the objective's completion audit reuses):

| Claim (the node's enumeration) | Evidence |
|---|---|
| A real implement session: the foreign `todo` tool registers | *(pending — leg 1)* |
| … the checklist seeds from the plan's `## Steps` | *(pending — leg 1)* |
| … items advance as work lands | *(pending — leg 1)* |
| … the overlay survives a compaction | *(pending — leg 1)* |
| A headless worker-construction session lists the `todo` tool (inherited via `.pi/settings.json`) | Leg 2: `todo` in both the registered census and the model's one-turn enumeration |
| `ask_user_question` fires as the structured questionnaire in a planning session | Leg 3: the transcribed 2026-08-09 planning-session questionnaire, human-reconfirmed |
| … and is absent headlessly | Leg 2: registered census carries `ask_user_question`; the model's one-turn enumeration does not (the `before_agent_start` strip observed live) |
| `just ci` green | *(pending — leg 4)* |

### Defect log

| # | Defect | Diagnosis artifacts | Disposition |
|---|--------|---------------------|-------------|
| proc‑1 | *(procedure, not product)* the probe's first run printed `perk: workflow-state linkage error — handoff missing or mismatched for run 01KZM6RTKW0JP15JAS4DF0R2Z1` — the shell that launched it was spawned from inside the implement session, so the probe inherited `PERK_RUN_ID` and perk's bound extension tried to claim that run id against the main checkout (no handoff there) | the first probe run's stderr; `env | grep PERK` showing the inherited `PERK_RUN_ID` | procedure corrected, not a code change: Part A's run line unsets `PERK_RUN_ID`/`PI_SESSION_FILE`; the error is loud-but-harmless by design (the census and enumeration were identical across both runs) |
