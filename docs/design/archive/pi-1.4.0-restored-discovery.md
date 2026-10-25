# Characterization: perk's startup discovery deferral vs Pi 1.4.0's restored loadouts (as-is vs guarded)

**Status:** dated evidence record, characterization-only. Plan #2787 (Objective #2767, node 4.3).
Snapshot taken 2026-10-25T15:28:27Z; decision rule pinned 2026-10-25T15:33:24Z, before any row was
measured; measured 2026-10-25 15:37–15:42Z (evidence logs written 15:38:31Z–15:42:04Z); drift gate
15:42:23Z; authored 2026-10-25. One sitting, one worktree (`$IMPL`), no second host.

- **Revision.** `H0` = `504a47276256ae2216f0564e28f4a3038134d0a0` (`git merge-base HEAD origin/main`
  = `HEAD` = `origin/main` at the snapshot and again at the drift gate). Blob hashes at `H0`:
  `extension/pi/activation.ts` `81631355ed229be70177a51a0b72891de2e492ec`,
  `extension/pi/perkTool.ts` `bd011740ec15a11b95da6e7f28923f3b7432ca5e`,
  `extension/substrate/toolGating.ts` `d3df6a19ddd2a8e014b3c022fb8d91c0cbf21e12`,
  `extension/substrate/toolPolicy.ts` `a04fd83a85ee121261ebfdd43c6da85ccb4034f6`,
  `extension/testing/harness.ts` `a95915bbe0aeddd09185321df1a5fc83e341c46a`,
  `extension/substrate/discoveryPilot.test.ts` `e060df4ef1d156abf73d315fedf73555c42e1699`,
  `extension/substrate/restorationWindow.test.ts` `279e89302a6b963561c497e955a265f3a8ce49bb`.
- **perk** 4.1.0. **Pi** 1.4.0, the dev pin
  (`$IMPL/node_modules/@earendil-works/pi-coding-agent/package.json`; pi-mcp 1.4.0 hoisted beside
  it). **Supplier** pi-subagents 0.81.0 (`$IMPL/.pi/npm/node_modules/pi-subagents/package.json`;
  background only — not loaded by the harness). **node** v26.12.1. `pi --version` was not
  consulted: the harness is the host.
- **`ROOT`** = `join(os.tmpdir(), "perk-char-restored-discovery")` =
  `/var/folders/90/b55dzd451137c93rcngpgdh00000gp/T/perk-char-restored-discovery`.
- **Provenance of the variants:** `H0` plus the throwaway patch quoted verbatim in
  [The patch](#the-patch-verbatim), SHA-256
  `b156006451d7504be56c8c56b5ec3a812d5bfcc63135ce6d516d2258719446a4`. It was applied uncommitted and
  reverted at teardown; nothing from it lands.

**Path abbreviations in quotes:** `$IMPL` = `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2787`.
`$ROOT` = the `ROOT` above. `$SCRATCH` = `$IMPL/.perk-characterization` (untracked, deleted at
teardown). Quotes are verbatim apart from these substitutions.

## Verdict

**GO (G2)**

- **The premise holds.** Pi 1.4.0 restores a resumed or forked session's recorded loadout before
  any extension runs: `R0-OPEN` and `R0-FORK` read `restore-performed=yes` with a valid checkpoint
  (`calls-before-perk=0`). Under AS-IS perk's first install then resets the restored selection:
  `R1`/`K1` read `active-before-perk:objective_stack_status=yes` and
  `active-after-startup:objective_stack_status=no`. So neither `NO-GO (premise false)` nor
  `NO-GO (nothing to fix)` applies.
- **A new perk-induced loss at 1.4.0 is demonstrated.** `M1` (resume with a late deferred MCP tool)
  reads AS-IS `LOST`, CONTROL `KEPT`: perk's deactivating startup install clears the
  pending-restoration set Pi now populates on resume.
- **Both variants are GO-eligible** (every clause holds; equality clauses at **T1**). G1 keeps the
  restored member but still loses the late MCP tool (`M1 G1 LOST`). G2 keeps both: the late-MCP
  preservation claim is made for G2 (`M1`: G2 `KEPT`, AS-IS `LOST`, CONTROL `KEPT`).
- **D4 picks G2.** The prefix residual G2 adds to AS-IS is a first-request miss on restored
  startups only (`R1`, `K1`; and, recorded-not-scored, `E1`, `B1`, `N1`). Each is confined to
  request 1 (`steady=yes`), and from request 2 on G2's prefix hash equals G1's. The other
  `first-miss` rows (`L1`, `T1`) miss in AS-IS too; `T1` is byte-identical in all three arms.
- **Pins to re-pin** in the follow-up: `discoveryPilot.test.ts` "priming resets (A)". It failed
  under both variants on its `starts without it` assertion, a D6-tolerated reset; the title stops
  there, so its later assertions were not observed under a variant. The planning-time prediction
  that "reload (A)" fails too is **falsified**: it stays green under both variants, because its
  primed member never reaches the transcript before the reload.
- **Recorded, never scored:** `L1` survival (D5): a transcript-recorded member survives `/reload`
  under G1/G2. `N2`: under G1/G2 `objective_stack_status` is kept though Pi restored nothing
  (allowlist session). `F1`'s `active-before-perk=yes` is registration activation, as predicted.
- A GO is a recommendation to author a follow-up plan. It is not permission to land this patch.

## Snapshot matrix

| Component | Value | Provenance |
|---|---|---|
| perk | 4.1.0 @ `H0` `504a4727` (clean tree at the snapshot) | `package.json`, `git rev-parse HEAD`, `git status --porcelain` |
| `VERSION` (printed by the script) | `HEADER VERSION=1.4.0 node=v26.12.1` | script header |
| pi-coding-agent | `$IMPL/node_modules/@earendil-works/pi-coding-agent/package.json version=1.4.0` | script header |
| pi-mcp (`./testing` export) | `$IMPL/node_modules/@earendil-works/pi-mcp/package.json version=1.4.0` (hoisted; no nested copy under pi-coding-agent) | script header |
| pi-subagents (supplier) | 0.81.0 at `$IMPL/.pi/npm/node_modules/pi-subagents` — not loaded | `package.json` |
| Extension order, PERK arm | `HEADER perk-order=["$IMPL/extension/index.ts","builtin:tool-search","builtin:mcp"]` (every PERK session asserts perk precedes `builtin:tool-search`/`builtin:mcp`) | script header |
| Extension order, CONTROL arm | `HEADER control-order=["builtin:tool-search","builtin:mcp"]` | script header |
| Discovery family | `HEADER discoveryFamily=["objective_stack_status","collect_review_wave","collect_draft_review_wave","push_annotations"]` | script header |
| Agent dir | `PI_CODING_AGENT_DIR=$ROOT/agent`, set before Pi loads; PERK sessions get the harness's own `perk-agent-*` mkdtemp dir; CONTROL sessions `$ROOT/control-agent/<row>` | script |
| `node` | v26.12.1 | `node --version` |

## The restore at 1.4.0 (source-derived)

Everything in this section was read in the installed dist
(`$IMPL/node_modules/@earendil-works/pi-coding-agent/dist/`), anchored by symbol. None of it is a
measurement; the measured rows below test it.

- **The constructor restores before any extension runs.** `core/agent-session.js`: `AgentSession`'s
  constructor calls `_buildRuntime({ activeToolNames: initialActiveToolNames, includeAllExtensionTools: true })`.
  `_refreshToolRegistry` then activates every extension tool for which `_isActivatedOnRegistration`
  holds (`direct`/`model-only` exposure, `defaultActive !== false`). That includes perk's family,
  which registers `direct` at factory time. Then, `if (this._usesDefaultTools)`, the constructor
  calls `_restoreToolsFromTranscript(this._defaultToolModifiers)`. All of this happens before
  `bindExtensions` emits `session_start`.
- **`_restoreToolsFromTranscript`.** It reads the branch's system messages (`getBranch()` entries
  with `message.role === "system"`). With none it keeps the current tools. Otherwise the restored
  loadout is `getCurrentTools(systemMessages)` (the `toolsAdded`/`toolsRemoved` replay). To that it
  adds the "new tools": registered extension tools that the branch never mentioned and that are
  activated on registration. A tool the branch recorded as removed is mentioned, so it stays
  inactive although registration activated it. That is the `R0` discriminator. Recorded names
  that are not registered yet go into `_pendingToolNames` (excluded names never do), and
  `_setActiveTools(names)` replaces the active set.
- **Who restores.** `core/sdk.js::createAgentSession` passes
  `usesDefaultTools: (options.tools === undefined || toolModifiers !== undefined) && !options.noTools`.
  So an explicit allowlist (`tools: [...]`, as in `N2`) skips the restore, but every allowlisted
  declarable name is activated (`_refreshToolRegistry`'s `allowedTools` arm). `navigateTree` calls
  `_restoreToolsFromTranscript()` before emitting `session_tree`. `reload()` never calls it: it
  adds every active name to `_pendingToolNames` and rebuilds with `includeAllExtensionTools: true`,
  so every registration-activated extension tool is active again.
- **The pending set is cleared.** `setActiveToolsByName` clears it whenever a previously active name
  is absent afterwards ("A loadout that deactivates a tool replaces the restored one, whose pending
  tools are dropped"). `_startRun` clears it before `agent.prompt`. Pi's own restore and registry
  refreshes go through `_setActiveTools`, never the public method. The script relies on this to
  attribute calls.
- **The lifecycle reasons.** The CLI `--resume`/`--session`/`--fork` build the initial runtime,
  so extensions see `session_start` with `reason: "startup"`. The harness's
  `SessionManager.open`/`forkFrom` + `createAgentSession` are this shape. In-process
  `switchSession`, `newSession` and `fork` (`core/agent-session-runtime.js`) construct the same
  `AgentSession` with `sessionStartEvent` reason `"resume"`, `"new"` or `"fork"`. At `H0`, perk's
  only `event.reason` branch in `extension/substrate/toolGating.ts` is `reason === "reload"`; the
  one in `extension/pi/activation.ts` forwards a shutdown reason. So the in-process reasons are
  perk-equivalent to `startup`. **Not measured** (D3).
- **The prompt carries the cwd.** `core/system-prompt.js::buildSystemPromptSections` writes
  `promptSections.cwd`, and no date was found there. So a request-prefix hash reproduces across runs
  only over an identical cwd, which is why the row cwds are pinned (D7). The determinism proof below
  confirms it.
- **perk's join** (at `H0`). In `extension/pi/activation.ts`, the `session_start` handler's
  "PHASE 1" runs `deferDiscoveryFamily(pi)` when the session is not yet in the cohort and
  `isDiscoveryHost(...)` holds. That function (`extension/pi/perkTool.ts`) re-registers each
  catalogued `declared: "deferred"` member with `exposure: "deferred"`. Then
  `gating.joinDiscoveryCohort(deferred)` sets `pendingDeferral = deferred`. The next `apply`
  removes the pending names unless `restorationWindow` is open, which only a `reload`
  `session_start` or a `session_tree` opens. The controller's comment still reads
  "startup/resume/new/fork never open it: Pi restores nothing there".
- **The supplier** (pi-subagents 0.81.0, background). `src/extension/declaration-pinning.js`
  re-registers the supplier's own recorded declaration fields from the transcript at
  `session_start`/`session_tree`. `src/extension/tool-activation.js::setSelection`, called from
  `applyRecordedSelection` on both events, starts from `pi.getActiveTools()` and filters out its
  own subagent/supervisor/loader/wait names per its flags before `pi.setActiveTools`. So it can
  deactivate supplier tools, which would itself clear Pi's pending set; only its later
  `before_agent_start` call is additive. It registers no `exposure: "deferred"` or
  `defaultActive: false` tool and never touches perk's names, and perk classifies every
  `npm:pi-subagents` tool `delegation`. It was not loaded in this harness and is not a measured
  subject.

## The decision rule (verbatim, as pinned 2026-10-25T15:33:24Z)

Rows are classified from RESULT/DIAG lines only; the script asserts fixture liveness, never outcomes. Arms: `AS-IS`, `G1`, `G2` (PERK sessions) and `CONTROL` (no perk; M rows only). Equality gates use D8's NORM/T1/T2 projection.

**Instrument validity.** The `active-before-perk` checkpoint is the `before` set of the FIRST `setActiveToolsByName` call perk makes (stack contains `substrate/toolGating.ts`) in the resumed/forked session; it is VALID iff no non-perk `setActiveToolsByName` call precedes it (DIAG `calls-before-perk=0`). An invalid checkpoint in R0 makes the premise **NOT MEASURED (premise instrument)** — classification is blocked and the record is authored with that verdict; no replay, transcript inference or expected-state substitute may stand in for the observation.

**Premise check (AS-IS; R0 is the discriminator).** R0-open and R0-fork must read `restore-performed=yes` (P registered yet INACTIVE at the valid checkpoint — registration activated it, the restore removed it because the transcript recorded it removed; a no-restore host leaves it active) and R1/K1 must read `active-before-perk:P=yes` with `active-after-startup:P=no` (perk's first install reset the restored selection). `restore-performed=no` ⇒ **NO-GO (premise false)**. `active-after-startup:P=yes` under AS-IS ⇒ **NO-GO (nothing to fix)**. Either way the record is still authored with the measured truth.

A variant `X ∈ {G1, G2}` is **GO-eligible** iff every clause holds:

1. **Preserved selection.** R1, K1: `P` active after startup, declared in request 1, still active after request 2.
2. **Cohort savings.** In F1, R1, K1, L1, T1: each of the three other family members (`U`) is undeclared in request 1 and inactive after request 1.
3. **Preservation rows equal AS-IS.** E1 (`P` undeclared in request 1, inactive after request 1 in `objective-author`); B1 (`B` undeclared in request 1, `emitToolCall` blocked under the gate, inactive after request 1); N1 (`P` unregistered, never active). Each row's NORM lines equal AS-IS's (T1, or T2 with the nondeterminism recorded).
4. **No regression on the untouched paths.** F1, T1, M2 NORM lines equal AS-IS's (same tiers).
5. **Late MCP.** M1 PERK outcome ≥ AS-IS (`KEPT ≥ LOST`). The late-MCP preservation claim is made for `X` only when M1 reads `X KEPT`, `AS-IS LOST`, `CONTROL KEPT`. If AS-IS already reads `KEPT`, the pending-set-clearing prediction is falsified and recorded; clause 5 then holds vacuously.
6. **Prefix.** `steady` true in every row; the set of rows with `first-miss` is recorded per arm (no threshold; D4 uses it).
7. **Suites.** Under `X`, the five suites' failing titles ⊆ the D6 tolerated set.

**Verdict vocabulary (closed):** `GO (G2)`, `GO (G1)`, `NO-GO (premise false)`, `NO-GO (nothing to fix)`, `NO-GO (no eligible variant)`, `NOT MEASURED (premise instrument)`. `GO` names the variant per D4 and lists the pins to re-pin; L1 survival (D5), the N2 observation and F1's `active-before-perk` are recorded, never scored. A GO is a recommendation to author a follow-up plan, not permission to land the patch.

The decisions the rule references, verbatim from the plan:

- **D4 — Tie-break** (operator): when both variants are GO-eligible the record recommends G2 iff its prefix residual is confined to request 1 of restored startups (R1, K1, L1, N2 rows), else G1.
- **D6 — Suite tolerance** (operator): under a variant, only failing titles whose failing assertion IS the as-is reset ("priming resets (A)" `starts without it` / `perk never installs it`; "reload (A)" primed-member-gone) are tolerated; any other failing title is NO-GO for that variant and is listed with its assertion text.
- **D8 — The prefix hash and the comparison projection (pinned now).** `H = sha256(request.prompt + "\0" + JSON.stringify(request.declared))`, first 12 hex chars, from `RecordedRequest`. Per row: `Hprev` (the seed session's last request, or the pre-reload / pre-navigation request), `H1..H3` (the resumed/reloaded/restored session's first three census requests). Within-run metrics: `steady = (H2 == H3)`, `first-miss = (H1 != H2)`, `cross = (H1 == Hprev)`. **Cross-run/cross-arm equality** (the inert gate, clauses 3–4) compares `NORM` lines: `sed -E 's/^(RESULT|DIAG) ([A-Z0-9-]+) (AS-IS|G1|G2|CONTROL) /\1 \2 ARM /'` over the RESULT/DIAG lines, in two pinned tiers — **T1** (strict): NORM lines byte-equal including every `H*=` field; **T2**: NORM lines byte-equal after `sed -E 's/ H(prev|[123])=[0-9a-f]{12}//g'` (hash fields stripped; the boolean `steady/first-miss/cross` fields stay). A gate passes at T1, or at T2 with the differing hash fields recorded as "hash nondeterminism" (the paths are pinned, so a T1 miss with a T2 pass is itself a finding); a T2 failure fails the gate. Hashes are a prefix proxy over Pi's canonical projection (system prompt text + ordered declarations), not provider wire bytes; the record says so.

## The matrix (measured)

**Arms.** `AS-IS` is the patched tree with both env vars unset; it behaves exactly as `H0`, which
the inert gate below proves. `G1` sets `PERK_CHAR_SKIP_RECORDED=1`. `G2` sets
`PERK_CHAR_SKIP_RECORDED=1 PERK_CHAR_WINDOW_ON_RESTORE=1`. Each PERK session is harness Mode B
(`packages: []`: perk by path, before `builtin:*`, the production order), with `toolSearch()` +
`COHORT_SETTINGS` (`defaultTools: ["+tool_search"]`), `headful: false`,
`env: { PERK_RUN_ID: undefined }` and the recording faux runtime. `CONTROL` (M rows only) is a raw
`createAgentSession` session without perk: the same `toolSearch()` + MCP factories, the same
settings, `bindExtensions({ mode: "print" })`, over its own `plantSession(cwd, [])` file.

**Seed (D7).** Each row plants
`plantSession(cwd, [{ stage: "implement", mode: "read-write" }])` in its own cwd and opens it with
`SessionManager.open(file)`, a fresh startup. That asserts the stage and the extension order. It
then makes the selection with `session.setActiveToolsByName([...active, P])`, runs two census
prompts, asserts `P` is declared in the last request and active, and keeps that request as `Hprev`.
The selection is `P` = `objective_stack_status`, or `B` = `collect_review_wave` for `B1`. A row
that resumes emits `session_shutdown` (`quit`), disposes the seed, and opens a NEW session over
`SessionManager.open(file)` (`R`, `E1`, `B1`, `N1`, `N2`) or `SessionManager.forkFrom(file, cwd)`
(`K1`, `R0-FORK`) with the same options. `L1`/`T1` stay in the seed session. A seed session's
transcript carries no system message before its own first request, so G1's recorded set is empty
there and G2's opener stays shut. The seeds are therefore identical across arms, and so is every
`Hprev`. Three rows seed differently:

- `R0-*` runs one census with `P` active, then `setActiveToolsByName(active − P)` and a second
  census, so the transcript records `P` removed.
- `F1` measures the fresh startup itself, with no seed.
- The M rows seed the MCP tool (below).

**Deterministic paths.** `rmSync($ROOT)` runs at script start. `PI_CODING_AGENT_DIR=$ROOT/agent`
is set before the dynamic Pi import. Each row's cwd is `$ROOT/rows/<row>` (the M rows use
`…/<row>/perk` and `…/<row>/control`), with the `.perk/workflow/handoff` scaffold `scaffoldRepo`
would create. The arm name never enters a PERK path, so a row's cwd (and hence its system prompt)
is byte-identical across the AS-IS, inert, G1 and G2 runs. MCP logs go to
`$ROOT/mcp-logs/<row>-<side>-<n>.log`.

**Observation plumbing.** `t.mock.method(AgentSession.prototype, "setActiveToolsByName", …)`
records every call as `{ names, before: getActiveToolNames(), perk }`, where `perk` means the stack
(captured with `Error.stackTraceLimit = 100`) contains `substrate/toolGating.ts`. The record is
reset just before the measured session is constructed.

- `calls-before-perk` is the number of calls before perk's first.
- `active-before-perk:<name>` is membership in the `before` of perk's first call, or `n/a` when perk
  made no call.
- `restore-performed` = registered ∧ ¬active-before-perk.
- `active-after-startup` is `getActiveToolNames()` right after `loadAt` returns.
- `declared(1)` is the first census request's declared tools.
- `active-after-1`/`-2` are read after the first/second census.
- `H1..H3` come from three censuses.

The MCP rows' fake server is Pi's own `createInMemoryTransportPair` from
`@earendil-works/pi-mcp/testing` behind a hand-written responder whose `initialize` can be held
(the 1.0.0 record's shape). The server has `exposure: "deferred"` and the tool is
`mcp__docs__search`. The seed loads the tool with a real `tool_search` call
(`callThenStop("tool_search", { query: "search the docs" })`) plus a census; the fixture asserts the
session file names it. Next comes `holdNext()` and then the resume (M1) or `reload()` (M2), and
the row prints `DIAG in-window-registered`. Then the script awaits `held()` (asserting exactly one
new connection and the tool unregistered), calls `release()` and awaits the registration. `KEPT`
means the tool is active once registered; `declared=` comes from the next census.

**Line types.** `RESULT`/`DIAG` lines are the classified surface. `OBS` lines are additional,
recorded and never classified (see the deviations): `perk-calls`, the startup activity of `E1`/`B1`,
the prefix fields of the rows whose matrix fields carry no hashes (`E1`, `B1`, `N1`), and per-row
diagnostics of why one hash differs from another.

**Liveness.** Every run ended with `ℹ tests 14` / `ℹ pass 14` / `ℹ fail 0`. That covers both AS-IS
runs, the inert run, G1 and G2 (each a separate `node --test` process; durations 8.5–9.8 s).

### RESULT/DIAG lines — AS-IS (`$SCRATCH/as-is.log`)

```
HEADER VERSION=1.4.0 node=v26.12.1
HEADER pi-coding-agent=$IMPL/node_modules/@earendil-works/pi-coding-agent/package.json version=1.4.0
HEADER pi-mcp=$IMPL/node_modules/@earendil-works/pi-mcp/package.json version=1.4.0
HEADER PERK_CHAR_SKIP_RECORDED=unset PERK_CHAR_WINDOW_ON_RESTORE=unset arm=AS-IS
HEADER ROOT=$ROOT
HEADER discoveryFamily=["objective_stack_status","collect_review_wave","collect_draft_review_wave","push_annotations"]
HEADER perk-order=["$IMPL/extension/index.ts","builtin:tool-search","builtin:mcp"]
HEADER control-order=["builtin:tool-search","builtin:mcp"]
RESULT R0-OPEN AS-IS registered:objective_stack_status=yes calls-before-perk=0 active-before-perk:objective_stack_status=no restore-performed=yes
RESULT R0-FORK AS-IS registered:objective_stack_status=yes calls-before-perk=0 active-before-perk:objective_stack_status=no restore-performed=yes
DIAG F1 AS-IS calls-before-perk=0
RESULT F1 AS-IS active-before-perk:objective_stack_status=yes active-after-startup:objective_stack_status=no declared(1):objective_stack_status=no declared(1):collect_review_wave=no active-after-1:collect_review_wave=no declared(1):collect_draft_review_wave=no active-after-1:collect_draft_review_wave=no declared(1):push_annotations=no active-after-1:push_annotations=no H1=b6360afe6ea9 H2=b6360afe6ea9 H3=b6360afe6ea9 steady=yes first-miss=no
RESULT R1 AS-IS calls-before-perk=0 active-before-perk:objective_stack_status=yes active-after-startup:objective_stack_status=no declared(1):objective_stack_status=no active-after-2:objective_stack_status=no declared(1):collect_review_wave=no active-after-1:collect_review_wave=no declared(1):collect_draft_review_wave=no active-after-1:collect_draft_review_wave=no declared(1):push_annotations=no active-after-1:push_annotations=no Hprev=ead546d8294e H1=10c2f2de5f53 H2=10c2f2de5f53 H3=10c2f2de5f53 steady=yes first-miss=no cross=no
RESULT K1 AS-IS calls-before-perk=0 active-before-perk:objective_stack_status=yes active-after-startup:objective_stack_status=no declared(1):objective_stack_status=no active-after-2:objective_stack_status=no declared(1):collect_review_wave=no active-after-1:collect_review_wave=no declared(1):collect_draft_review_wave=no active-after-1:collect_draft_review_wave=no declared(1):push_annotations=no active-after-1:push_annotations=no Hprev=cbe9211fd723 H1=f54ae55434a9 H2=f54ae55434a9 H3=f54ae55434a9 steady=yes first-miss=no cross=no
RESULT L1 AS-IS active-before-reload:objective_stack_status=yes active-after-reload:objective_stack_status=yes declared(1):objective_stack_status=no active-after-1:objective_stack_status=no declared(1):collect_review_wave=no active-after-1:collect_review_wave=no declared(1):collect_draft_review_wave=no active-after-1:collect_draft_review_wave=no declared(1):push_annotations=no active-after-1:push_annotations=no Hprev=49e25a50a69e H1=72354f871800 H2=08247ec0cbf2 H3=08247ec0cbf2 steady=yes first-miss=yes cross=no
RESULT T1 AS-IS active-before-tree:objective_stack_status=yes active-after-tree:objective_stack_status=yes declared(1):objective_stack_status=yes active-after-1:objective_stack_status=yes declared(1):collect_review_wave=no active-after-1:collect_review_wave=no declared(1):collect_draft_review_wave=no active-after-1:collect_draft_review_wave=no declared(1):push_annotations=no active-after-1:push_annotations=no Hprev=aad309aafb97 H1=aad309aafb97 H2=591c17f3326c H3=591c17f3326c steady=yes first-miss=yes cross=yes
RESULT E1 AS-IS declared(1):objective_stack_status=no active-after-1:objective_stack_status=no
RESULT B1 AS-IS declared(1):collect_review_wave=no blocked:collect_review_wave=yes active-after-1:collect_review_wave=no
RESULT N1 AS-IS registered:objective_stack_status=no active-after-startup:objective_stack_status=no active-after-1:objective_stack_status=no exposure:collect_review_wave=deferred exposure:collect_draft_review_wave=deferred exposure:push_annotations=deferred
DIAG N2 AS-IS calls-before-perk=0
RESULT N2 AS-IS active-before-perk:objective_stack_status=yes active-after-startup:objective_stack_status=no declared(1):objective_stack_status=no Hprev=0d6ec643f661 H1=92fc8350508c H2=92fc8350508c H3=92fc8350508c steady=yes first-miss=no cross=no
DIAG M1 AS-IS in-window-registered=no
RESULT M1 AS-IS LOST declared=no
DIAG M1 CONTROL in-window-registered=no
RESULT M1 CONTROL KEPT declared=yes
DIAG M2 AS-IS in-window-registered=no
RESULT M2 AS-IS KEPT declared=yes
DIAG M2 CONTROL in-window-registered=no
RESULT M2 CONTROL KEPT declared=yes
```

`OBS` lines from the same run (the per-row diagnostics are summarized under
[Prefix stability](#prefix-stability)):

```
OBS R0-OPEN AS-IS perk-calls=1 active-after-startup:objective_stack_status=no
OBS R0-FORK AS-IS perk-calls=1 active-after-startup:objective_stack_status=no
OBS E1 AS-IS active-after-startup:objective_stack_status=no Hprev=e462748bb5bf H1=a911d9038f25 H2=a911d9038f25 H3=a911d9038f25 steady=yes first-miss=no cross=no
OBS B1 AS-IS active-after-startup:collect_review_wave=no Hprev=49f8a9b4d9a5 H1=8f306056a8ab H2=8f306056a8ab H3=8f306056a8ab steady=yes first-miss=no cross=no
OBS N1 AS-IS Hprev=896e3e7b9e93 H1=fb6da0c45997 H2=fb6da0c45997 H3=fb6da0c45997 steady=yes first-miss=no cross=no
OBS N2 AS-IS perk-calls=1
```

### RESULT/DIAG lines — G1 (`$SCRATCH/g1.log`)

```
HEADER VERSION=1.4.0 node=v26.12.1
HEADER pi-coding-agent=$IMPL/node_modules/@earendil-works/pi-coding-agent/package.json version=1.4.0
HEADER pi-mcp=$IMPL/node_modules/@earendil-works/pi-mcp/package.json version=1.4.0
HEADER PERK_CHAR_SKIP_RECORDED=1 PERK_CHAR_WINDOW_ON_RESTORE=unset arm=G1
HEADER ROOT=$ROOT
HEADER discoveryFamily=["objective_stack_status","collect_review_wave","collect_draft_review_wave","push_annotations"]
HEADER perk-order=["$IMPL/extension/index.ts","builtin:tool-search","builtin:mcp"]
HEADER control-order=["builtin:tool-search","builtin:mcp"]
RESULT R0-OPEN G1 registered:objective_stack_status=yes calls-before-perk=0 active-before-perk:objective_stack_status=no restore-performed=yes
RESULT R0-FORK G1 registered:objective_stack_status=yes calls-before-perk=0 active-before-perk:objective_stack_status=no restore-performed=yes
DIAG F1 G1 calls-before-perk=0
RESULT F1 G1 active-before-perk:objective_stack_status=yes active-after-startup:objective_stack_status=no declared(1):objective_stack_status=no declared(1):collect_review_wave=no active-after-1:collect_review_wave=no declared(1):collect_draft_review_wave=no active-after-1:collect_draft_review_wave=no declared(1):push_annotations=no active-after-1:push_annotations=no H1=b6360afe6ea9 H2=b6360afe6ea9 H3=b6360afe6ea9 steady=yes first-miss=no
RESULT R1 G1 calls-before-perk=0 active-before-perk:objective_stack_status=yes active-after-startup:objective_stack_status=yes declared(1):objective_stack_status=yes active-after-2:objective_stack_status=yes declared(1):collect_review_wave=no active-after-1:collect_review_wave=no declared(1):collect_draft_review_wave=no active-after-1:collect_draft_review_wave=no declared(1):push_annotations=no active-after-1:push_annotations=no Hprev=ead546d8294e H1=b0b74c39329a H2=b0b74c39329a H3=b0b74c39329a steady=yes first-miss=no cross=no
RESULT K1 G1 calls-before-perk=0 active-before-perk:objective_stack_status=yes active-after-startup:objective_stack_status=yes declared(1):objective_stack_status=yes active-after-2:objective_stack_status=yes declared(1):collect_review_wave=no active-after-1:collect_review_wave=no declared(1):collect_draft_review_wave=no active-after-1:collect_draft_review_wave=no declared(1):push_annotations=no active-after-1:push_annotations=no Hprev=cbe9211fd723 H1=e36241627cb8 H2=e36241627cb8 H3=e36241627cb8 steady=yes first-miss=no cross=no
RESULT L1 G1 active-before-reload:objective_stack_status=yes active-after-reload:objective_stack_status=yes declared(1):objective_stack_status=yes active-after-1:objective_stack_status=yes declared(1):collect_review_wave=no active-after-1:collect_review_wave=no declared(1):collect_draft_review_wave=no active-after-1:collect_draft_review_wave=no declared(1):push_annotations=no active-after-1:push_annotations=no Hprev=49e25a50a69e H1=ede031744656 H2=f94d4032ab1b H3=f94d4032ab1b steady=yes first-miss=yes cross=no
RESULT T1 G1 active-before-tree:objective_stack_status=yes active-after-tree:objective_stack_status=yes declared(1):objective_stack_status=yes active-after-1:objective_stack_status=yes declared(1):collect_review_wave=no active-after-1:collect_review_wave=no declared(1):collect_draft_review_wave=no active-after-1:collect_draft_review_wave=no declared(1):push_annotations=no active-after-1:push_annotations=no Hprev=aad309aafb97 H1=aad309aafb97 H2=591c17f3326c H3=591c17f3326c steady=yes first-miss=yes cross=yes
RESULT E1 G1 declared(1):objective_stack_status=no active-after-1:objective_stack_status=no
RESULT B1 G1 declared(1):collect_review_wave=no blocked:collect_review_wave=yes active-after-1:collect_review_wave=no
RESULT N1 G1 registered:objective_stack_status=no active-after-startup:objective_stack_status=no active-after-1:objective_stack_status=no exposure:collect_review_wave=deferred exposure:collect_draft_review_wave=deferred exposure:push_annotations=deferred
DIAG N2 G1 calls-before-perk=0
RESULT N2 G1 active-before-perk:objective_stack_status=n/a active-after-startup:objective_stack_status=yes declared(1):objective_stack_status=yes Hprev=0d6ec643f661 H1=41f30a351735 H2=41f30a351735 H3=41f30a351735 steady=yes first-miss=no cross=no
DIAG M1 G1 in-window-registered=no
RESULT M1 G1 LOST declared=no
DIAG M1 CONTROL in-window-registered=no
RESULT M1 CONTROL KEPT declared=yes
DIAG M2 G1 in-window-registered=no
RESULT M2 G1 KEPT declared=yes
DIAG M2 CONTROL in-window-registered=no
RESULT M2 CONTROL KEPT declared=yes
```

```
OBS R0-OPEN G1 perk-calls=1 active-after-startup:objective_stack_status=no
OBS R0-FORK G1 perk-calls=1 active-after-startup:objective_stack_status=no
OBS E1 G1 active-after-startup:objective_stack_status=no Hprev=e462748bb5bf H1=a911d9038f25 H2=a911d9038f25 H3=a911d9038f25 steady=yes first-miss=no cross=no
OBS B1 G1 active-after-startup:collect_review_wave=no Hprev=49f8a9b4d9a5 H1=8f306056a8ab H2=8f306056a8ab H3=8f306056a8ab steady=yes first-miss=no cross=no
OBS N1 G1 Hprev=896e3e7b9e93 H1=fb6da0c45997 H2=fb6da0c45997 H3=fb6da0c45997 steady=yes first-miss=no cross=no
OBS N2 G1 perk-calls=0
```

### RESULT/DIAG lines — G2 (`$SCRATCH/g2.log`)

```
HEADER VERSION=1.4.0 node=v26.12.1
HEADER pi-coding-agent=$IMPL/node_modules/@earendil-works/pi-coding-agent/package.json version=1.4.0
HEADER pi-mcp=$IMPL/node_modules/@earendil-works/pi-mcp/package.json version=1.4.0
HEADER PERK_CHAR_SKIP_RECORDED=1 PERK_CHAR_WINDOW_ON_RESTORE=1 arm=G2
HEADER ROOT=$ROOT
HEADER discoveryFamily=["objective_stack_status","collect_review_wave","collect_draft_review_wave","push_annotations"]
HEADER perk-order=["$IMPL/extension/index.ts","builtin:tool-search","builtin:mcp"]
HEADER control-order=["builtin:tool-search","builtin:mcp"]
RESULT R0-OPEN G2 registered:objective_stack_status=yes calls-before-perk=0 active-before-perk:objective_stack_status=no restore-performed=yes
RESULT R0-FORK G2 registered:objective_stack_status=yes calls-before-perk=0 active-before-perk:objective_stack_status=no restore-performed=yes
DIAG F1 G2 calls-before-perk=0
RESULT F1 G2 active-before-perk:objective_stack_status=yes active-after-startup:objective_stack_status=no declared(1):objective_stack_status=no declared(1):collect_review_wave=no active-after-1:collect_review_wave=no declared(1):collect_draft_review_wave=no active-after-1:collect_draft_review_wave=no declared(1):push_annotations=no active-after-1:push_annotations=no H1=b6360afe6ea9 H2=b6360afe6ea9 H3=b6360afe6ea9 steady=yes first-miss=no
RESULT R1 G2 calls-before-perk=0 active-before-perk:objective_stack_status=yes active-after-startup:objective_stack_status=yes declared(1):objective_stack_status=yes active-after-2:objective_stack_status=yes declared(1):collect_review_wave=no active-after-1:collect_review_wave=no declared(1):collect_draft_review_wave=no active-after-1:collect_draft_review_wave=no declared(1):push_annotations=no active-after-1:push_annotations=no Hprev=ead546d8294e H1=31fea3b63273 H2=b0b74c39329a H3=b0b74c39329a steady=yes first-miss=yes cross=no
RESULT K1 G2 calls-before-perk=0 active-before-perk:objective_stack_status=yes active-after-startup:objective_stack_status=yes declared(1):objective_stack_status=yes active-after-2:objective_stack_status=yes declared(1):collect_review_wave=no active-after-1:collect_review_wave=no declared(1):collect_draft_review_wave=no active-after-1:collect_draft_review_wave=no declared(1):push_annotations=no active-after-1:push_annotations=no Hprev=cbe9211fd723 H1=1c236defbdfe H2=e36241627cb8 H3=e36241627cb8 steady=yes first-miss=yes cross=no
RESULT L1 G2 active-before-reload:objective_stack_status=yes active-after-reload:objective_stack_status=yes declared(1):objective_stack_status=yes active-after-1:objective_stack_status=yes declared(1):collect_review_wave=no active-after-1:collect_review_wave=no declared(1):collect_draft_review_wave=no active-after-1:collect_draft_review_wave=no declared(1):push_annotations=no active-after-1:push_annotations=no Hprev=49e25a50a69e H1=ede031744656 H2=f94d4032ab1b H3=f94d4032ab1b steady=yes first-miss=yes cross=no
RESULT T1 G2 active-before-tree:objective_stack_status=yes active-after-tree:objective_stack_status=yes declared(1):objective_stack_status=yes active-after-1:objective_stack_status=yes declared(1):collect_review_wave=no active-after-1:collect_review_wave=no declared(1):collect_draft_review_wave=no active-after-1:collect_draft_review_wave=no declared(1):push_annotations=no active-after-1:push_annotations=no Hprev=aad309aafb97 H1=aad309aafb97 H2=591c17f3326c H3=591c17f3326c steady=yes first-miss=yes cross=yes
RESULT E1 G2 declared(1):objective_stack_status=no active-after-1:objective_stack_status=no
RESULT B1 G2 declared(1):collect_review_wave=no blocked:collect_review_wave=yes active-after-1:collect_review_wave=no
RESULT N1 G2 registered:objective_stack_status=no active-after-startup:objective_stack_status=no active-after-1:objective_stack_status=no exposure:collect_review_wave=deferred exposure:collect_draft_review_wave=deferred exposure:push_annotations=deferred
DIAG N2 G2 calls-before-perk=0
RESULT N2 G2 active-before-perk:objective_stack_status=n/a active-after-startup:objective_stack_status=yes declared(1):objective_stack_status=yes Hprev=0d6ec643f661 H1=41f30a351735 H2=41f30a351735 H3=41f30a351735 steady=yes first-miss=no cross=no
DIAG M1 G2 in-window-registered=no
RESULT M1 G2 KEPT declared=yes
DIAG M1 CONTROL in-window-registered=no
RESULT M1 CONTROL KEPT declared=yes
DIAG M2 G2 in-window-registered=no
RESULT M2 G2 KEPT declared=yes
DIAG M2 CONTROL in-window-registered=no
RESULT M2 CONTROL KEPT declared=yes
```

```
OBS R0-OPEN G2 perk-calls=2 active-after-startup:objective_stack_status=no
OBS R0-FORK G2 perk-calls=2 active-after-startup:objective_stack_status=no
OBS E1 G2 active-after-startup:objective_stack_status=yes Hprev=e462748bb5bf H1=1b8605070e37 H2=a911d9038f25 H3=a911d9038f25 steady=yes first-miss=yes cross=no
OBS B1 G2 active-after-startup:collect_review_wave=yes Hprev=49f8a9b4d9a5 H1=bcb3671b8a49 H2=8f306056a8ab H3=8f306056a8ab steady=yes first-miss=yes cross=no
OBS N1 G2 Hprev=896e3e7b9e93 H1=78b109029f09 H2=fb6da0c45997 H3=fb6da0c45997 steady=yes first-miss=yes cross=no
OBS N2 G2 perk-calls=0
```

### The determinism proof and the inert gate

- **Determinism (a fixture precondition).** A second unpatched AS-IS run (`$SCRATCH/as-is-2.log`)
  equals the first at **T1** through `norm.sh`: `cmp` of the two `norm.sh t1` projections exited 0
  (21 NORM lines). Every `HEADER` and `OBS` line was equal as well.
- **The inert gate.** The patched tree with both env vars unset (`$SCRATCH/inert.log`, header
  `PERK_CHAR_SKIP_RECORDED=unset PERK_CHAR_WINDOW_ON_RESTORE=unset arm=AS-IS`) equals the unpatched
  AS-IS run at **T1**, with every `OBS` line equal too. The patch is inert with the env unset. Before
  any G run, `npm run typecheck` (`tsc --noEmit`) passed on the patched tree.

### Classification

Each equality clause compares one row's `norm.sh` projection of the variant's log against AS-IS's
(`$SCRATCH/equality.txt`). Every comparison passed at **T1**, so no hash nondeterminism was
observed.

| Row | Scored by | AS-IS | G1 | G2 | CONTROL |
|---|---|---|---|---|---|
| R0-OPEN | premise | registered `yes`, `calls-before-perk=0`, active-before-perk `no`, **`restore-performed=yes`** | identical (consistency only) | identical | — |
| R0-FORK | premise | identical to R0-OPEN | identical | identical | — |
| R1 | premise; 1; 2 | `P`: before-perk `yes`, **after-startup `no`**, declared(1) `no`, after-2 `no`; each `U` `no`/`no` | `P` `yes`/`yes`/`yes` — **1 holds**; `U` `no`/`no` — **2 holds** | `P` `yes`/`yes`/`yes` — **1 holds**; `U` `no`/`no` — **2 holds** | — |
| K1 | premise; 1; 2 | identical shape to R1 | **1, 2 hold** | **1, 2 hold** | — |
| F1 | 2; 4 | `P` after-startup `no`, declared(1) `no`; each `U` `no`/`no` | **2 holds**; NORM = AS-IS at **T1** — **4 holds** | **2 holds**; **T1** — **4 holds** | — |
| L1 | 2 (D5 recorded) | `P` declared(1) `no`, after-1 `no`; each `U` `no`/`no` | `P` kept (`yes`/`yes`) — D5, recorded; **2 holds** | identical to G1 | — |
| T1 | 2; 4 | `P` kept; each `U` `no`/`no` | **2 holds**; **T1** — **4 holds** | **2 holds**; **T1** — **4 holds** | — |
| E1 | 3 | `P` declared(1) `no`, after-1 `no` | **T1** — **3 holds** | **T1** — **3 holds** | — |
| B1 | 3 | `B` declared(1) `no`, blocked `yes`, after-1 `no` | **T1** — **3 holds** | **T1** — **3 holds** | — |
| N1 | 3 | `P` unregistered, never active; the other three `deferred` | **T1** — **3 holds** | **T1** — **3 holds** | — |
| N2 | recorded | `P` before-perk `yes`, after-startup `no`, declared(1) `no` | before-perk `n/a` (perk made no install), after-startup `yes`, declared(1) `yes` | identical to G1 | — |
| M1 | 5 | `LOST`, declared `no` | `LOST` — **5 holds** (LOST ≥ LOST); no preservation claim | **`KEPT`** — **5 holds**; preservation claim made | `KEPT`, declared `yes` |
| M2 | 4 | `KEPT`, declared `yes` | **T1** — **4 holds** | **T1** — **4 holds** | `KEPT`, declared `yes` |

| Clause | G1 | G2 |
|---|---|---|
| Instrument validity | valid (R0 `calls-before-perk=0`) | valid |
| Premise (AS-IS) | holds: R0 `restore-performed=yes`; R1/K1 before `yes`, after `no` | — |
| 1. Preserved selection | holds | holds |
| 2. Cohort savings | holds | holds |
| 3. Preservation rows equal AS-IS | holds (E1, B1, N1 at T1) | holds (T1) |
| 4. Untouched paths | holds (F1, T1, M2 at T1) | holds (T1) |
| 5. Late MCP | holds (G1 `LOST` ≥ AS-IS `LOST`); no preservation claim | holds; claim made (G2 `KEPT`, AS-IS `LOST`, CONTROL `KEPT`) |
| 6. Prefix | `steady=yes` in every row; `first-miss` rows {L1, T1} | `steady=yes` in every row; `first-miss` rows {R1, K1, L1, T1} |
| 7. Suites | one failing title, its failing assertion D6-tolerated | same |
| **GO-eligible** | **yes** | **yes** |

**D4.** Both variants are GO-eligible. AS-IS's own `first-miss` set is {L1, T1}. G2 adds {R1, K1}.
Both are restored startups, and each miss is confined to request 1. G2's `H2` equals G1's `H1` (R1
`b0b74c39329a`, K1 `e36241627cb8`), so from the second request on G2 presents exactly G1's prefix.
The recorded-only `E1`/`B1`/`N1` rows show the same shape: a G2 request-1 miss, then G2's `H2`
equals AS-IS's (= G1's) `H1`. `L1`'s miss exists in every arm (the reload window's
already-documented residual), with G1's and G2's L1 hashes identical. `T1`'s miss is byte-identical
in all three arms, a pre-existing snippet reorder at the `/tree` window's close (below). Neither
is a residual G2 introduces. So the residual is confined to request 1 of restored startups, and the
record recommends **G2**.

**Falsified or refined row predictions** (the matrix's planning-time predictions vs the
measurement):

- `R1`/`K1` G1 `cross=yes` was **falsified**: G1 reads `cross=no`. The only difference from `Hprev`
  is the system prompt's snippet order. The seed appended `objective_stack_status` last; after the
  restore and perk's first install its snippet sits at line index 18, before
  `classify_review_feedback`. Same lines, same declared list, same declared order
  (`OBS R1 G1 Hprev->H1 -lines=[] +lines=[] -declared=[] +declared=[] reorder@18=…`). No arm
  achieves `cross=yes` on resume.
- `N2` "before=yes in all arms" was **refined**: under G1/G2 perk made no install at all
  (`perk-calls=0`; the allowlist registers only `objective_stack_status` from the family, and G1
  keeps it), so the checkpoint is `n/a`. The rest of N2's prediction held (AS-IS `no`, G1/G2 `yes`).
- `T1` "identical in all arms: P kept" held. **Not anticipated:** `first-miss=yes` with
  `cross=yes` in every arm. Request 1 equals the pre-navigation request, and request 2 moves
  `objective_stack_status`'s snippet to line index 18 (`OBS T1 AS-IS H1->H2 -lines=[] +lines=[] … reorder@18=…`),
  the same reorder as above.
- `G2` R1/K1 "first-miss=yes (U snippets/guidelines in request 1)" **held**. In request 1,
  `collect_review_wave` and `push_annotations` carry snippets and all three `U` carry guidelines.
  `collect_draft_review_wave`, which is not eligible in `implement`, carries only its guideline.
  That is the shape §8.40 already documents for the reload residual (see
  [Prefix stability](#prefix-stability)).
- Every other row prediction (R0, F1, R1/K1 AS-IS and G2, L1, E1, B1, N1, M1, M2 per arm) **held**.

## Prefix stability

`H = sha256(prompt + "\0" + JSON.stringify(declared))`, first 12 hex characters, computed from the
harness's `RecordedRequest`. It is a prefix proxy over Pi's canonical projection (system prompt text
plus ordered declarations), not provider wire bytes, and says nothing about provider cache hits.
`Hprev` is the seed's last request, or the pre-reload/pre-navigation request. `H1..H3` are the
first three census requests after the resume, reload or restore. Rows marked † come from `OBS`
lines (recorded, not scored).

| Row | Arm | Hprev | H1 | H2 | H3 | steady | first-miss | cross |
|---|---|---|---|---|---|---|---|---|
| F1 | AS-IS / G1 / G2 | — | `b6360afe6ea9` | `b6360afe6ea9` | `b6360afe6ea9` | yes | no | — |
| R1 | AS-IS | `ead546d8294e` | `10c2f2de5f53` | `10c2f2de5f53` | `10c2f2de5f53` | yes | no | no |
| R1 | G1 | `ead546d8294e` | `b0b74c39329a` | `b0b74c39329a` | `b0b74c39329a` | yes | no | no |
| R1 | G2 | `ead546d8294e` | `31fea3b63273` | `b0b74c39329a` | `b0b74c39329a` | yes | **yes** | no |
| K1 | AS-IS | `cbe9211fd723` | `f54ae55434a9` | `f54ae55434a9` | `f54ae55434a9` | yes | no | no |
| K1 | G1 | `cbe9211fd723` | `e36241627cb8` | `e36241627cb8` | `e36241627cb8` | yes | no | no |
| K1 | G2 | `cbe9211fd723` | `1c236defbdfe` | `e36241627cb8` | `e36241627cb8` | yes | **yes** | no |
| L1 | AS-IS | `49e25a50a69e` | `72354f871800` | `08247ec0cbf2` | `08247ec0cbf2` | yes | yes | no |
| L1 | G1 / G2 | `49e25a50a69e` | `ede031744656` | `f94d4032ab1b` | `f94d4032ab1b` | yes | yes | no |
| T1 | AS-IS / G1 / G2 | `aad309aafb97` | `aad309aafb97` | `591c17f3326c` | `591c17f3326c` | yes | yes | yes |
| N2 | AS-IS | `0d6ec643f661` | `92fc8350508c` | `92fc8350508c` | `92fc8350508c` | yes | no | no |
| N2 | G1 / G2 | `0d6ec643f661` | `41f30a351735` | `41f30a351735` | `41f30a351735` | yes | no | no |
| E1† | AS-IS / G1 | `e462748bb5bf` | `a911d9038f25` | `a911d9038f25` | `a911d9038f25` | yes | no | no |
| E1† | G2 | `e462748bb5bf` | `1b8605070e37` | `a911d9038f25` | `a911d9038f25` | yes | yes | no |
| B1† | AS-IS / G1 | `49f8a9b4d9a5` | `8f306056a8ab` | `8f306056a8ab` | `8f306056a8ab` | yes | no | no |
| B1† | G2 | `49f8a9b4d9a5` | `bcb3671b8a49` | `8f306056a8ab` | `8f306056a8ab` | yes | yes | no |
| N1† | AS-IS / G1 | `896e3e7b9e93` | `fb6da0c45997` | `fb6da0c45997` | `fb6da0c45997` | yes | no | no |
| N1† | G2 | `896e3e7b9e93` | `78b109029f09` | `fb6da0c45997` | `fb6da0c45997` | yes | yes | no |

The per-row `OBS` diagnostics explain each difference. They are summarized here because the full
lines quote whole guideline texts:

- **R1/K1 AS-IS, `Hprev→H1` = both.** `objective_stack_status`'s snippet and guideline leave the
  prompt, and its declaration leaves the request: the reset.
- **R1/K1 G1, `Hprev→H1` = prompt (reorder only).** The lines, the declared list and the declared
  order are all equal. `objective_stack_status`'s snippet moves to line index 18, ahead of
  `classify_review_feedback`.
- **R1/K1 G2, `H1→H2` = prompt.** Request 1's system prompt additionally carries the snippets of
  `collect_review_wave` and `push_annotations` and the guidelines of all three `U`. Their
  declarations are hidden (`declared(1)=no`). Request 2 drops them.
- **L1 (every arm), `H1→H2` = prompt.** Request 1 carries the family's eligible snippets and every
  member's guidelines, the reload residual §8.40 already documents. Under AS-IS that includes
  `objective_stack_status`, which the close then removes. Under G1/G2 it is kept, so its snippet
  stays in request 2 as well.
- **T1 (every arm), `H1→H2` = prompt (reorder only).** `objective_stack_status`'s snippet moves to
  line index 18 after the `/tree` window's close.
- **N2, `Hprev→H1` = both (every arm).** The allowlist drops every unlisted perk tool from the
  registry, so their snippets leave the prompt. Under AS-IS `objective_stack_status` goes too.

## The suites under each arm

`node --test extension/substrate/restorationWindow.test.ts extension/substrate/ownNamesActivation.test.ts
extension/substrate/discoveryPilot.test.ts extension/substrate/toolGating.test.ts
extension/substrate/stageTools.test.ts` on the patched tree:

| Arm | `ℹ tests` | `ℹ pass` | `ℹ fail` | Failing titles (failing assertion) |
|---|---|---|---|---|
| AS-IS (env unset) | 95 | 95 | 0 | — |
| G1 | 95 | 94 | 1 | "priming resets (A): resume and fork from the primed leaf start without it and perk never installs it; /tree restores it and perk keeps it, or drops it in an ineligible stage" — `AssertionError [ERR_ASSERTION]: starts without it` (`discoveryPilot.test.ts:552:14`, `actual: false, expected: true`) |
| G2 | 95 | 94 | 1 | the same title, the same assertion (`discoveryPilot.test.ts:552:14`) |

The AS-IS run is all-pass, so the baseline is green. Under both variants the one failing title's
failing assertion is "priming resets (A)" `starts without it`, in D6's tolerated set, so clause 7
holds. The title aborts at that assertion, so its later assertions ("perk never installs it", the
`/tree` half) were **not observed** under either variant. "reload (A)" passed under both variants,
against the planning-time prediction: it primes `objective_stack_status` through `/objective-sync`
and reloads before any request records the prime, so the transcript does not record it and the
recorded-and-live keep set is empty.

## Falsified planning-time claims

Each claim's **host** fact (what Pi does, measured by R0's `restore-performed` and M1's CONTROL
arm, never by a member merely being active) is kept apart from its **perk** fact (what the user
sees, measured by `active-after-startup`). A user-visible sentence can stay true at `H0` while its
host rationale is false. Quotes are from `H0`. Verdicts are falsified, still true, or not measured.

| Where | Quote | Host fact at 1.4.0 | Perk fact at `H0` (AS-IS) |
|---|---|---|---|
| `shared/contracts.md` §8.40 **Restoration window** | "SDK/CLI resume populates nothing at 1.0.0 (`createAgentSession` always passes an initial active set — measured, row S1 of `docs/design/archive/pi-1.0.0-mcp-restoration.md`)" | **Falsified for the pinned host.** At 1.4.0 the CLI-shaped resume restores (`R0-OPEN`/`R0-FORK restore-performed=yes`) and populates the pending set (`M1 CONTROL KEPT`). The "at 1.0.0" qualifier keeps it historically true but stale. | — |
| §8.40 **Restoration window** | "`startup`, `resume`, `new` and `fork` open no window." | — (a statement of perk's rule) | **Still true** as perk's rule. Its unstated premise (nothing to restore there) is false, which is the gap `M1 AS-IS LOST` shows and G2 closes. `resume`/`new`/`fork` reasons not measured (D3). |
| §8.40 **Resets** | "resume and fork start from the host's defaults and re-join (a primed or searched member is gone until re-primed or re-searched)" | **Falsified**: they start from the transcript's restored loadout (`R0`). | **Still true**: `R1`/`K1 active-after-startup:objective_stack_status=no`, but perk's join removes it, not the host. |
| `extension/substrate/toolGating.ts` header | "Resets: resume/fork start from the host's defaults (a primed or searched member is gone)" | **Falsified** (as above) | **Still true** (as above) |
| `extension/substrate/toolGating.ts` `restorationWindow` comment | "startup/resume/new/fork never open it: Pi restores nothing there." | "Pi restores nothing there": **falsified** (`R0`, `M1 CONTROL KEPT`) | "never open it": **still true** at `H0` |
| `docs/learned/pi/tool-loadout.md` § "Pi host facts" | "**Resume and fork never restore a transcript's declared loadout** — `createAgentSession` always passes `initialActiveToolNames`; only `/tree` (`navigateTree`) restores. A `tool_search` activation does not survive resume or fork." | First sentence **falsified** (`R0`) | Second sentence **still true** at `H0`, by perk's deferral (`R1`/`K1`). The family seed here used `setActiveToolsByName`, not a family `tool_search` hit; `M1` used a real `tool_search` hit for the MCP tool. |
| `docs/learned/pi/tool-loadout.md` § "The pending-restoration set and the restoration window" | "populated by `/reload` (every active name) and by a `/tree` restore (…) — not by SDK/CLI resume." | **Falsified**: `M1 CONTROL KEPT` (the late tool came back on resume without perk) | — |
| `docs/user-docs/reference/in-session/model-tools.md` | "Pi restores such activations only when you navigate the session tree, not on resume or fork; perk keeps what Pi restored and adds nothing." | "only when you navigate the session tree": **falsified** (`R0`) | "perk keeps what Pi restored": **falsified on resume/fork**. Pi restored it (`active-before-perk=yes`) and perk removed it (`active-after-startup=no`). |
| `docs/user-docs/reference/in-session/model-tools.md` | "Resume and fork start without it (re-run the door or search again)" | — | **Still true** at `H0` (`R1`/`K1`). It would become false under G1/G2. |

The plan's own predictions falsified by the measurement are listed under
[Classification](#classification) and [The suites](#the-suites-under-each-arm): G1 `cross=yes`,
"reload (A)" failing, and N2's G1/G2 checkpoint.

## Residuals and design questions for the follow-up

- **N2's transcript-shape guard.** Under G1/G2, `objective_stack_status` survives an allowlist
  resume where Pi restored nothing (`_usesDefaultTools` false). It was allowlist-activated and the
  transcript records it. `recordedLive` and `restoredLoadout(ctx)` read the transcript's shape, not
  whether Pi actually restored. The follow-up must decide whether that is acceptable or needs a
  host signal.
- **The G2 residual.** On every restored startup with a cohort (R1, K1; recorded E1, B1, N1),
  request 1's system prompt carries the deferred members' guidelines and their eligible snippets,
  with declarations hidden. That is one request of prefix miss, the same mechanism as the
  documented reload residual. From request 2 on, G2 equals G1.
- **No arm keeps the prefix across a resume.** `cross=no` in R1/K1 under every arm. Under G1 the
  only difference is the snippet order: the seed appended the member, and the restored install
  puts it in registry order. The same reorder produces T1's request-2 miss in every arm. A
  follow-up that cares about prefix reuse across resume would look at ordering, not at the
  deferral.
- **The in-process reasons.** `switchSession`/`fork`/`newSession` (`reason` `resume`/`fork`/`new`)
  were not measured. By source reading, G2's opener keys on `restoredLoadout(ctx)`, not the reason,
  so an in-process resume or fork over a recorded transcript would open the window too, and `new`
  (no transcript) would not.
- **Reload survival (D5).** Under G1/G2 a transcript-recorded member survives `/reload` (`L1`),
  while a member primed after the last request does not ("reload (A)" stays green). The follow-up
  has to decide whether "recorded in the transcript" is the intended criterion on `/reload`.
- **"priming resets (A)" was only partly observed** under the variants (it stops at
  `starts without it`).
- **Foreign deactivations.** The supplier's `setSelection` can deactivate its own tools at
  `session_start`, which clears Pi's pending set whatever perk does. G2 removes only perk's
  contribution. Not measured (the supplier is not loaded here).
- **G3 is not designed here.** That would re-activate recorded-but-late foreign tools after a
  deactivating install, without the window. It stays a question for the follow-up.

## Consumers

- **The follow-up plan** that would land G2 (or another guard). It re-pins "priming resets (A)",
  decides the N2 and reload-survival questions above, and amends the prose below.
- **`shared/contracts.md` §8.40** (**Restoration window**, **Resets**, **Native discovery**): the
  binding consumer once a guard lands.
- **`docs/learned/pi/tool-loadout.md`** ("Pi host facts", "The pending-restoration set and the
  restoration window") and **`docs/user-docs/reference/in-session/model-tools.md`**: the
  falsified sentences above.

**`/learn` candidates:**

- Pi 1.4.0 restores a resumed/forked session's recorded loadout in the constructor, before any
  `session_start`. A member active before an extension's first install proves nothing about
  restoration, because registration activates it. R0's "recorded removed, so inactive" shape is
  the discriminator.
- At 1.4.0, resume populates the pending-restoration set, so any deactivating startup install
  drops a late MCP tool (`M1`).
- A request-prefix hash is only reproducible over an identical cwd (the prompt carries it). A
  deterministic `ROOT` made T1 equality hold across five runs.
- Snippet order follows the active-set order, so an append (`tool_search`, a prime) and a restore
  present the same tools in different prompt bytes.
- A failing `ls -d <glob> | wc -l` with stderr suppressed reports `0` when the glob overflows the
  argument list (see the deviations).

## Deviations from the plan's procedure

- **`OBS` lines were added** (recorded, never classified): `perk-calls`, E1/B1 startup activity,
  the prefix fields of E1/B1/N1 (whose matrix fields carry no hashes, so their RESULT lines stay as
  the matrix lists them), and per-row hash-difference diagnostics.
- **The script was amended twice after its first AS-IS run.** Both amendments added only OBS
  diagnostics (the line diff, then the reorder detail); no RESULT/DIAG field or fixture changed.
  Every evidence log (`as-is`, `as-is-2`, `inert`, `g1`, `g2`) comes from the final script, SHA-256
  `9608666cbf0bc5823bf9aa11b24beafde1cd6a48b1a29586c83f91313030b2f2`, quoted below.
- **R0 ran under every arm** (the plan scopes it to AS-IS). The checkpoint precedes any patched
  code, and G1/G2 read identically. The premise is scored from AS-IS only.
- **Row ids are upper-case** (`R0-OPEN`, `R0-FORK`) so D8's NORM pattern `[A-Z0-9-]+` matches them.
  The M rows print `RESULT <row> <arm> KEPT|LOST declared=…` (the 1.0.0 record's shape).
- **The Step 0 residue baseline was wrong.** `ls -d "$TMPDIR"/perk-agent-* 2>/dev/null | wc -l`
  printed `0` because the glob overflowed `ls`'s argument list (`Argument list too long`, hidden by
  the redirect). Recounted with `find`: 31 238 `perk-agent-*` dirs predate the sitting (newest mtime
  2026-10-25 14:09Z, before the 15:28:27Z snapshot). Teardown removed only entries newer than the
  sitting's start stamp; counts are under [Teardown proof](#teardown-proof).
- **Drift gate.** `git fetch origin && git diff --name-only H0 origin/main` was empty at 15:42:23Z
  (`origin/main` = `H0`). The measurement is source-equivalent to `H0` with nothing to recover.

## The script (verbatim)

Run from the worktree root as `node --test .perk-characterization/restored-discovery.test.ts`
(SHA-256 `9608666cbf0bc5823bf9aa11b24beafde1cd6a48b1a29586c83f91313030b2f2`; the same bytes for every
evidence run).

```ts
// Throwaway measurement script (record-only): does perk's startup discovery deferral reset a loadout
// Pi 1.4.0 restored from the transcript (resume / fork), and does it clear Pi's pending-restoration
// set there — as-is vs two env-toggled guarded variants (G1: PERK_CHAR_SKIP_RECORDED=1; G2: G1 +
// PERK_CHAR_WINDOW_ON_RESTORE=1)? Each matrix row is one `test()`; the script PRINTS
// `RESULT <row> <arm> …` / `DIAG <row> <arm> …` lines (the classified surface) and `OBS <row> <arm> …`
// lines (recorded, never classified), and asserts only fixture liveness. Classification is the
// record's, never the script's.
//
// Run from the worktree root: `node --test .perk-characterization/restored-discovery.test.ts`.

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { before, type TestContext, test } from "node:test";
import { fileURLToPath } from "node:url";

// Deterministic paths (the system prompt carries the cwd) and global-tier isolation BEFORE Pi
// loads: `getAgentDir()` must never resolve the operator's agent dir.
const ROOT = join(tmpdir(), "perk-char-restored-discovery");
rmSync(ROOT, { recursive: true, force: true });
process.env.PI_CODING_AGENT_DIR = join(ROOT, "agent");
mkdirSync(process.env.PI_CODING_AGENT_DIR, { recursive: true });

const pca = await import("@earendil-works/pi-coding-agent");
const { createInMemoryTransportPair } = await import("@earendil-works/pi-mcp/testing");
const harness = await import("../extension/testing/harness.ts");
const { ensureToolCatalog } = await import("../extension/testing/toolCatalog.ts");
const { discoveryFamily } = await import("../extension/substrate/toolPolicy.ts");
const {
  AgentSession,
  createAgentSession,
  createMcpExtension,
  DefaultResourceLoader,
  SessionManager,
  SettingsManager,
  VERSION,
} = pca;
const { COHORT_SETTINGS, loadAt, PERK_EXTENSION_PATH, plantSession, recordingRuntime, toolSearch } =
  harness;

type Session = InstanceType<typeof AgentSession>;
type InlineExtension = import("@earendil-works/pi-coding-agent").InlineExtension;
type SessionManagerT = InstanceType<typeof SessionManager>;
type PerkSession = import("../extension/testing/harness.ts").PerkSession;
type RecordedRequest = import("../extension/testing/harness.ts").RecordedRequest;
type Recorder = Awaited<ReturnType<typeof recordingRuntime>>;

before(ensureToolCatalog);

const skip = process.env.PERK_CHAR_SKIP_RECORDED === "1";
const windowOnRestore = process.env.PERK_CHAR_WINDOW_ON_RESTORE === "1";
if (windowOnRestore && !skip) throw new Error("fixture: G2 is G1 + the window opener");
const ARM = skip ? (windowOnRestore ? "G2" : "G1") : "AS-IS";

const P = "objective_stack_status";
const B = "collect_review_wave";
const TOOL = "mcp__docs__search";
const TOOL_SEARCH_PATH = "builtin:tool-search";
const MCP_PATH = "builtin:mcp";

// --- output -----------------------------------------------------------------------------------------

const yn = (b: boolean) => (b ? "yes" : "no");
type Fields = [string, string][];
const fmt = (fields: Fields) => fields.map(([k, v]) => `${k}=${v}`).join(" ");
function result(row: string, fields: Fields, arm: string = ARM): void {
  console.log(`RESULT ${row} ${arm} ${fmt(fields)}`);
}
function diag(row: string, key: string, value: string, arm: string = ARM): void {
  console.log(`DIAG ${row} ${arm} ${key}=${value}`);
}
function obs(row: string, fields: Fields): void {
  console.log(`OBS ${row} ${ARM} ${fmt(fields)}`);
}

// --- the prefix hash (D8) ---------------------------------------------------------------------------

const hash = (r: RecordedRequest) =>
  createHash("sha256")
    .update(`${r.prompt}\0${JSON.stringify(r.declared)}`)
    .digest("hex")
    .slice(0, 12);

/** `Hprev`? H1..H3, steady, first-miss, cross? — the D8 fields for one row. */
function prefix(prev: RecordedRequest | undefined, rs: readonly RecordedRequest[]): Fields {
  assert.equal(rs.length, 3, "fixture: three census requests");
  const [h1, h2, h3] = rs.map(hash) as [string, string, string];
  const out: Fields = [];
  if (prev !== undefined) out.push(["Hprev", hash(prev)]);
  out.push(["H1", h1], ["H2", h2], ["H3", h3], ["steady", yn(h2 === h3)], ["first-miss", yn(h1 !== h2)]);
  if (prev !== undefined) out.push(["cross", yn(h1 === hash(prev))]);
  return out;
}

/** Which half of the hash input differs between two requests (recorded, never classified). */
function part(a: RecordedRequest, b: RecordedRequest): string {
  const prompt = a.prompt !== b.prompt;
  const declared = JSON.stringify(a.declared) !== JSON.stringify(b.declared);
  return prompt && declared ? "both" : prompt ? "prompt" : declared ? "declared" : "none";
}

/** Snippet / guideline presence of every family member in a request's system prompt. */
function presence(h: PerkSession, r: RecordedRequest, tag: string): Fields {
  return discoveryFamily().flatMap((name): Fields => {
    const guidelines = h.registeredTool(name)?.promptGuidelines ?? [];
    return [
      [`snippet(${tag}):${name}`, yn(r.prompt.includes(`- ${name}: `))],
      [`guideline(${tag}):${name}`, yn(guidelines.some((g) => r.prompt.includes(g)))],
    ];
  });
}

/** The system-prompt lines one request carries and the other does not (each cut to 100 chars). */
function lineDiff(a: RecordedRequest, b: RecordedRequest): string {
  const al = a.prompt.split("\n");
  const bl = b.prompt.split("\n");
  const cut = (l: string) => (l.length > 100 ? `${l.slice(0, 100)}…` : l);
  const minus = al.filter((l) => !bl.includes(l)).map(cut);
  const plus = bl.filter((l) => !al.includes(l)).map(cut);
  const names = (r: RecordedRequest) => r.tools;
  const dropped = names(a).filter((n) => !names(b).includes(n));
  const added = names(b).filter((n) => !names(a).includes(n));
  let order = "";
  if (minus.length === 0 && plus.length === 0 && a.prompt !== b.prompt) {
    const i = al.findIndex((l, k) => l !== bl[k]);
    order = ` reorder@${i}=${JSON.stringify([cut(al[i] ?? ""), cut(bl[i] ?? "")])}`;
  }
  const declaredOrder =
    dropped.length === 0 && added.length === 0 && JSON.stringify(a.tools) !== JSON.stringify(b.tools)
      ? ` declared-order=${JSON.stringify([a.tools, b.tools])}`
      : "";
  return `-lines=${JSON.stringify(minus)} +lines=${JSON.stringify(plus)} -declared=${JSON.stringify(dropped)} +declared=${JSON.stringify(added)}${order}${declaredOrder}`;
}

/** The OBS diagnostics for a hash-bearing row (why H1 differs from H2 / Hprev). */
function prefixObs(row: string, h: PerkSession, prev: RecordedRequest | undefined, rs: RecordedRequest[]): void {
  const [r1, r2] = rs as [RecordedRequest, RecordedRequest];
  const fields: Fields = [["diff(H1,H2)", part(r1, r2)]];
  if (prev !== undefined) fields.push(["diff(Hprev,H1)", part(prev, r1)]);
  obs(row, [...fields, ...presence(h, r1, "1"), ...presence(h, r2, "2")]);
  if (part(r1, r2) !== "none") console.log(`OBS ${row} ${ARM} H1->H2 ${lineDiff(r1, r2)}`);
  if (prev !== undefined && part(prev, r1) !== "none") console.log(`OBS ${row} ${ARM} Hprev->H1 ${lineDiff(prev, r1)}`);
}

// --- observation plumbing ---------------------------------------------------------------------------

type Call = { names: string[]; before: string[]; perk: boolean };

/**
 * Record every `setActiveToolsByName` call (Pi's constructor restore and registration refreshes use
 * `_setActiveTools`, never this method) with the live set it replaced and whether perk's gating
 * module made it (by stack).
 */
function observe(t: TestContext): Call[] {
  const calls: Call[] = [];
  const original = AgentSession.prototype.setActiveToolsByName;
  t.mock.method(AgentSession.prototype, "setActiveToolsByName", function (this: Session, names: string[]) {
    const limit = Error.stackTraceLimit;
    Error.stackTraceLimit = 100;
    const stack = new Error().stack ?? "";
    Error.stackTraceLimit = limit;
    calls.push({ names: [...names], before: this.getActiveToolNames(), perk: stack.includes("substrate/toolGating.ts") });
    return original.call(this, names);
  });
  return calls;
}

/** The instrument: non-perk calls before perk's first, and the live set perk's first call replaced. */
function checkpoint(calls: readonly Call[]): { callsBeforePerk: number; before: string[] | undefined } {
  const first = calls.findIndex((c) => c.perk);
  if (first === -1) return { callsBeforePerk: calls.length, before: undefined };
  return { callsBeforePerk: first, before: calls[first]?.before };
}

const beforePerk = (cp: { before: string[] | undefined }, name: string) =>
  cp.before === undefined ? "n/a" : yn(cp.before.includes(name));

// --- sessions ---------------------------------------------------------------------------------------

/** A row's deterministic cwd (D7), with the `.perk/workflow/` scaffold `scaffoldRepo` would make. */
function rowDir(...parts: string[]): string {
  const dir = join(ROOT, "rows", ...parts);
  mkdirSync(join(dir, ".perk", "workflow", "handoff"), { recursive: true });
  return dir;
}

const plantImplement = (cwd: string) => plantSession(cwd, [{ stage: "implement", mode: "read-write" }]);

/** A PERK session (Mode B: perk by path, before `builtin:*`) over `manager`. */
async function perk(
  cwd: string,
  rt: Recorder,
  manager: SessionManagerT,
  more: { extras?: InlineExtension[]; tools?: string[]; excludeTools?: string[] } = {},
): Promise<PerkSession> {
  const h = await loadAt(cwd, {
    packages: [],
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    extraExtensions: [toolSearch(), ...(more.extras ?? [])],
    settings: COHORT_SETTINGS,
    env: { PERK_RUN_ID: undefined },
    sessionManager: manager,
    ...(more.tools !== undefined ? { tools: more.tools } : {}),
    ...(more.excludeTools !== undefined ? { excludeTools: more.excludeTools } : {}),
  });
  const paths = h.session.extensionRunner.getExtensionPaths();
  const perkAt = paths.indexOf(PERK_EXTENSION_PATH);
  assert.ok(perkAt !== -1, `fixture: perk bound by path (${paths.join(", ")})`);
  assert.ok(perkAt < paths.indexOf(TOOL_SEARCH_PATH), `fixture: perk precedes ${TOOL_SEARCH_PATH} (${paths.join(", ")})`);
  if (paths.includes(MCP_PATH)) assert.ok(perkAt < paths.indexOf(MCP_PATH), "fixture: perk precedes builtin:mcp");
  return h;
}

/** A CONTROL session: the same factories and settings, no perk (raw `createAgentSession`). */
async function control(
  cwd: string,
  rt: Recorder,
  manager: SessionManagerT,
  agentDir: string,
  extensions: InlineExtension[],
): Promise<Session> {
  mkdirSync(agentDir, { recursive: true });
  const resourceLoader = new DefaultResourceLoader({ cwd, agentDir, extensionFactories: extensions });
  await resourceLoader.reload();
  const { session } = await createAgentSession({
    cwd,
    agentDir,
    model: rt.reg.getModel() as never,
    modelRuntime: rt.reg.modelRuntime,
    resourceLoader,
    sessionManager: manager,
    settingsManager: SettingsManager.inMemory({
      compaction: { enabled: false },
      retry: { enabled: false },
      ...COHORT_SETTINGS,
    }),
  });
  await session.bindExtensions({
    mode: "print",
    onError: (err) => console.error(`control: extension error in ${err.event}: ${err.error}`),
  });
  assert.ok(!session.extensionRunner.getExtensionPaths().includes(PERK_EXTENSION_PATH), "fixture: no perk");
  return session;
}

async function shutdown(session: Session): Promise<void> {
  try {
    await session.extensionRunner.emit({ type: "session_shutdown", reason: "quit" } as never);
  } catch {}
}

async function closePerk(h: PerkSession): Promise<void> {
  await shutdown(h.session);
  h.dispose();
}

async function closeControl(session: Session): Promise<void> {
  await shutdown(session);
  session.dispose();
}

const isActive = (s: Session, name: string) => s.getActiveToolNames().includes(name);
const isRegistered = (s: Session, name: string) => s.getAllTools().some((t) => t.name === name);

/** One census prompt; returns its (single) request. */
async function census(s: Session, rt: Recorder): Promise<RecordedRequest> {
  const before = rt.requests.length;
  rt.census();
  await s.prompt("census");
  assert.equal(rt.requests.length, before + 1, "fixture: one request per census");
  const request = rt.requests[before];
  assert.ok(request !== undefined, "fixture: the census made a request");
  return request;
}

/** The common seed (D7): a fresh startup over the planted file; `member` activated; census ×2. */
async function seed(
  cwd: string,
  rt: Recorder,
  member: string,
): Promise<{ h: PerkSession; file: string; prev: RecordedRequest }> {
  const file = plantImplement(cwd);
  const h = await perk(cwd, rt, SessionManager.open(file));
  assert.equal(h.workflowState().stage, "implement", "fixture: the seed's stage");
  h.session.setActiveToolsByName([...h.session.getActiveToolNames(), member]);
  await census(h.session, rt);
  await census(h.session, rt);
  assert.ok(rt.last().tools.includes(member), `fixture: ${member} declared in the seed`);
  assert.ok(isActive(h.session, member), `fixture: ${member} active at the seed's end`);
  return { h, file, prev: rt.last() };
}

const others = () => discoveryFamily().filter((name) => name !== P);

/** Each U member's declared(1) / active-after-1. */
function uFields(r1: RecordedRequest, after1: readonly string[]): Fields {
  return others().flatMap((name): Fields => [
    [`declared(1):${name}`, yn(r1.tools.includes(name))],
    [`active-after-1:${name}`, yn(after1.includes(name))],
  ]);
}

// --- the fake MCP server (Pi's own in-memory transport pair; only the responder is hand-written) ---

type McpTransport = ReturnType<typeof createInMemoryTransportPair>["client"];
type McpTool = { name: string; description: string; inputSchema: Record<string, unknown> };
const SEARCH: McpTool = {
  name: "search",
  description: "Search the docs index for pages matching a query.",
  inputSchema: { type: "object", properties: { query: { type: "string" } }, required: ["query"] },
};

type Fake = {
  connections: number;
  /** Hold the NEXT connection's `initialize`. */
  holdNext(): void;
  /** Resolves when the held `initialize` has arrived at the server. */
  held(): Promise<void>;
  /** Answer the held `initialize`. */
  release(): void;
  client(): McpTransport;
};

function fakeServer(tools: readonly McpTool[]): Fake {
  let holdArmed = false;
  let arrived: Promise<void> = Promise.resolve();
  let markArrived: (() => void) | undefined;
  let releaseHeld: (() => void) | undefined;
  const fake: Fake = {
    connections: 0,
    holdNext() {
      holdArmed = true;
      arrived = new Promise((r) => {
        markArrived = r;
      });
    },
    held: () => arrived,
    release() {
      const release = releaseHeld;
      releaseHeld = undefined;
      assert.ok(release !== undefined, "fixture: a held initialize to release");
      release();
    },
    client() {
      fake.connections += 1;
      const { client, server } = createInMemoryTransportPair();
      let gate: Promise<void> | undefined;
      if (holdArmed) {
        holdArmed = false;
        gate = new Promise((r) => {
          releaseHeld = r;
        });
      }
      const signal = markArrived;
      markArrived = undefined;
      server.onMessage(async (raw) => {
        const message = raw as { id?: number | string; method?: string; params?: { protocolVersion?: string } };
        if (message.id === undefined || typeof message.method !== "string") return;
        let result: unknown = {};
        if (message.method === "initialize") {
          if (gate !== undefined) {
            signal?.();
            await gate;
          }
          result = {
            protocolVersion: message.params?.protocolVersion,
            capabilities: { tools: {} },
            serverInfo: { name: "docs", version: "1.0.0" },
          };
        } else if (message.method === "tools/list") {
          result = { tools };
        } else if (message.method === "tools/call") {
          result = { content: [{ type: "text", text: "ok" }] };
        }
        await server.send({ jsonrpc: "2.0", id: message.id, result } as never).catch(() => {});
      });
      void server.start();
      return client;
    },
  };
  return fake;
}

let logSeq = 0;
function mcp(fake: Fake, label: string): InlineExtension {
  const logs = join(ROOT, "mcp-logs");
  mkdirSync(logs, { recursive: true });
  return {
    name: "mcp",
    factory: createMcpExtension({
      loadConfig: () => ({
        servers: [
          { name: "docs", config: { url: "http://unused.invalid", exposure: "deferred" }, source: "scratch" },
        ],
        errors: [],
      }),
      createTransport: () => fake.client() as never,
      logPath: join(logs, `${label}-${++logSeq}.log`),
    }),
    builtin: true,
  } as InlineExtension;
}

async function registration(s: Session): Promise<void> {
  const deadline = Date.now() + 5000;
  while (!isRegistered(s, TOOL)) {
    if (Date.now() > deadline) throw new Error(`fixture: ${TOOL} never registered`);
    await new Promise((r) => setTimeout(r, 5));
  }
}

/** Load the MCP tool through `tool_search` into the active set and the transcript, then a census. */
async function seedMcp(s: Session, rt: Recorder): Promise<void> {
  await registration(s);
  rt.callThenStop("tool_search", { query: "search the docs" });
  await s.prompt("load");
  assert.ok(isActive(s, TOOL), "fixture: the MCP tool is active after the search");
  await census(s, rt);
  assert.ok(rt.last().tools.includes(TOOL), "fixture: the MCP tool is declared (recorded)");
}

/** After the held connection arrived: release it, await the registration, report KEPT/LOST. */
async function finishLate(row: string, s: Session, rt: Recorder, fake: Fake, connections: number, arm: string): Promise<void> {
  await fake.held();
  assert.equal(fake.connections, connections + 1, "fixture: exactly one new connection");
  assert.ok(!isRegistered(s, TOOL), "fixture: unregistered immediately before release");
  fake.release();
  await registration(s);
  assert.equal(fake.connections, connections + 1, "fixture: the held connection registered it");
  const kept = isActive(s, TOOL);
  const r1 = await census(s, rt);
  console.log(`RESULT ${row} ${arm} ${kept ? "KEPT" : "LOST"} declared=${yn(r1.tools.includes(TOOL))}`);
}

// --- HEADER -----------------------------------------------------------------------------------------

function packageRoot(specifier: string): string {
  let dir = dirname(fileURLToPath(import.meta.resolve(specifier)));
  while (!existsSync(join(dir, "package.json"))) dir = dirname(dir);
  return dir;
}

test("HEADER", async () => {
  const version = (root: string) => (JSON.parse(readFileSync(join(root, "package.json"), "utf8")) as { version: string }).version;
  const pcaRoot = packageRoot("@earendil-works/pi-coding-agent");
  const mcpRoot = packageRoot("@earendil-works/pi-mcp/testing");
  console.log(`HEADER VERSION=${VERSION} node=${process.version}`);
  console.log(`HEADER pi-coding-agent=${join(pcaRoot, "package.json")} version=${version(pcaRoot)}`);
  console.log(`HEADER pi-mcp=${join(mcpRoot, "package.json")} version=${version(mcpRoot)}`);
  console.log(
    `HEADER PERK_CHAR_SKIP_RECORDED=${process.env.PERK_CHAR_SKIP_RECORDED ?? "unset"} PERK_CHAR_WINDOW_ON_RESTORE=${process.env.PERK_CHAR_WINDOW_ON_RESTORE ?? "unset"} arm=${ARM}`,
  );
  console.log(`HEADER ROOT=${ROOT}`);
  console.log(`HEADER discoveryFamily=${JSON.stringify(discoveryFamily())}`);
  const fp = fakeServer([SEARCH]);
  const pcwd = rowDir("HEADER", "perk");
  const rtp = await recordingRuntime();
  const h = await perk(pcwd, rtp, SessionManager.open(plantImplement(pcwd)), { extras: [mcp(fp, "header-perk")] });
  console.log(`HEADER perk-order=${JSON.stringify(h.session.extensionRunner.getExtensionPaths())}`);
  await closePerk(h);
  const fc = fakeServer([SEARCH]);
  const ccwd = rowDir("HEADER", "control");
  const rtc = await recordingRuntime();
  const c = await control(ccwd, rtc, SessionManager.open(plantSession(ccwd, [])), join(ROOT, "control-agent", "HEADER"), [
    toolSearch(),
    mcp(fc, "header-control"),
  ]);
  console.log(`HEADER control-order=${JSON.stringify(c.extensionRunner.getExtensionPaths())}`);
  await closeControl(c);
});

// --- R0: the restore discriminator (premise) --------------------------------------------------------

async function r0(t: TestContext, row: string, how: "open" | "fork"): Promise<void> {
  const calls = observe(t);
  const cwd = rowDir(row);
  const rt = await recordingRuntime();
  const file = plantImplement(cwd);
  const s = await perk(cwd, rt, SessionManager.open(file));
  try {
    assert.equal(s.workflowState().stage, "implement", "fixture: the seed's stage");
    s.session.setActiveToolsByName([...s.session.getActiveToolNames(), P]);
    await census(s.session, rt);
    assert.ok(rt.last().tools.includes(P), "fixture: P declared (recorded added)");
    s.session.setActiveToolsByName(s.session.getActiveToolNames().filter((n) => n !== P));
    await census(s.session, rt);
    assert.ok(!rt.last().tools.includes(P), "fixture: P undeclared (recorded removed)");
    assert.ok(!isActive(s.session, P), "fixture: P inactive at the seed's end");
  } finally {
    await closePerk(s);
  }
  calls.length = 0;
  const manager = how === "open" ? SessionManager.open(file) : SessionManager.forkFrom(file, cwd);
  const h = await perk(cwd, rt, manager);
  try {
    assert.equal(h.workflowState().stage, "implement", "fixture: the resumed stage");
    const cp = checkpoint(calls);
    const registered = isRegistered(h.session, P);
    const performed = cp.before === undefined ? "n/a" : yn(registered && !cp.before.includes(P));
    result(row, [
      [`registered:${P}`, yn(registered)],
      ["calls-before-perk", String(cp.callsBeforePerk)],
      [`active-before-perk:${P}`, beforePerk(cp, P)],
      ["restore-performed", performed],
    ]);
    obs(row, [
      ["perk-calls", String(calls.filter((c) => c.perk).length)],
      [`active-after-startup:${P}`, yn(isActive(h.session, P))],
    ]);
  } finally {
    await closePerk(h);
  }
}

test("R0-OPEN", (t) => r0(t, "R0-OPEN", "open"));
test("R0-FORK", (t) => r0(t, "R0-FORK", "fork"));

// --- F1: fresh startup ------------------------------------------------------------------------------

test("F1", async (t) => {
  const calls = observe(t);
  const cwd = rowDir("F1");
  const rt = await recordingRuntime();
  const file = plantImplement(cwd);
  calls.length = 0;
  const h = await perk(cwd, rt, SessionManager.open(file));
  try {
    assert.equal(h.workflowState().stage, "implement", "fixture: the stage");
    const cp = checkpoint(calls);
    assert.ok(cp.before !== undefined, "fixture: the recorder sees perk's startup install (non-vacuous)");
    const afterStartup = isActive(h.session, P);
    const r1 = await census(h.session, rt);
    const after1 = h.session.getActiveToolNames();
    const r2 = await census(h.session, rt);
    const r3 = await census(h.session, rt);
    diag("F1", "calls-before-perk", String(cp.callsBeforePerk));
    result("F1", [
      [`active-before-perk:${P}`, beforePerk(cp, P)],
      [`active-after-startup:${P}`, yn(afterStartup)],
      [`declared(1):${P}`, yn(r1.tools.includes(P))],
      ...uFields(r1, after1),
      ...prefix(undefined, [r1, r2, r3]),
    ]);
    prefixObs("F1", h, undefined, [r1, r2, r3]);
  } finally {
    await closePerk(h);
  }
});

// --- R1 / K1: resume and fork from a leaf whose transcript records P active -------------------------

async function resumed(t: TestContext, row: string, how: "open" | "fork"): Promise<void> {
  const calls = observe(t);
  const cwd = rowDir(row);
  const rt = await recordingRuntime();
  const { h: s, file, prev } = await seed(cwd, rt, P);
  await closePerk(s);
  calls.length = 0;
  const manager = how === "open" ? SessionManager.open(file) : SessionManager.forkFrom(file, cwd);
  const h = await perk(cwd, rt, manager);
  try {
    assert.equal(h.workflowState().stage, "implement", "fixture: the resumed stage");
    const cp = checkpoint(calls);
    const afterStartup = isActive(h.session, P);
    const r1 = await census(h.session, rt);
    const after1 = h.session.getActiveToolNames();
    const r2 = await census(h.session, rt);
    const after2 = h.session.getActiveToolNames();
    const r3 = await census(h.session, rt);
    result(row, [
      ["calls-before-perk", String(cp.callsBeforePerk)],
      [`active-before-perk:${P}`, beforePerk(cp, P)],
      [`active-after-startup:${P}`, yn(afterStartup)],
      [`declared(1):${P}`, yn(r1.tools.includes(P))],
      [`active-after-2:${P}`, yn(after2.includes(P))],
      ...uFields(r1, after1),
      ...prefix(prev, [r1, r2, r3]),
    ]);
    prefixObs(row, h, prev, [r1, r2, r3]);
  } finally {
    await closePerk(h);
  }
}

test("R1", (t) => resumed(t, "R1", "open"));
test("K1", (t) => resumed(t, "K1", "fork"));

// --- L1 / T1: /reload and /tree restore in the seed session -----------------------------------------

async function gesture(row: string, kind: "reload" | "tree"): Promise<void> {
  const cwd = rowDir(row);
  const rt = await recordingRuntime();
  const { h, prev } = await seed(cwd, rt, P);
  try {
    const before = isActive(h.session, P);
    if (kind === "reload") {
      await h.reload();
    } else {
      const [first] = h.entryIds() as [string];
      const leaf = h.session.sessionManager.getLeafId();
      assert.ok(leaf !== null, "fixture: a leaf");
      await h.navigateTo(first);
      await h.navigateTo(leaf);
    }
    const after = isActive(h.session, P);
    const r1 = await census(h.session, rt);
    const after1 = h.session.getActiveToolNames();
    const r2 = await census(h.session, rt);
    const r3 = await census(h.session, rt);
    result(row, [
      [`active-before-${kind}:${P}`, yn(before)],
      [`active-after-${kind}:${P}`, yn(after)],
      [`declared(1):${P}`, yn(r1.tools.includes(P))],
      [`active-after-1:${P}`, yn(after1.includes(P))],
      ...uFields(r1, after1),
      ...prefix(prev, [r1, r2, r3]),
    ]);
    prefixObs(row, h, prev, [r1, r2, r3]);
  } finally {
    await closePerk(h);
  }
}

test("L1", () => gesture("L1", "reload"));
test("T1", () => gesture("T1", "tree"));

// --- E1 / B1: resume into an ineligible stage / into the gate ---------------------------------------

test("E1", async () => {
  const cwd = rowDir("E1");
  const rt = await recordingRuntime();
  const { h: s, file, prev } = await seed(cwd, rt, P);
  s.session.sessionManager.appendCustomEntry("perk:workflow-state", { stage: "objective-author" });
  await closePerk(s);
  const h = await perk(cwd, rt, SessionManager.open(file));
  try {
    assert.equal(h.workflowState().stage, "objective-author", "fixture: the resumed stage");
    const afterStartup = isActive(h.session, P);
    const r1 = await census(h.session, rt);
    const after1 = h.session.getActiveToolNames();
    const r2 = await census(h.session, rt);
    const r3 = await census(h.session, rt);
    result("E1", [
      [`declared(1):${P}`, yn(r1.tools.includes(P))],
      [`active-after-1:${P}`, yn(after1.includes(P))],
    ]);
    obs("E1", [[`active-after-startup:${P}`, yn(afterStartup)], ...prefix(prev, [r1, r2, r3])]);
  } finally {
    await closePerk(h);
  }
});

test("B1", async () => {
  const cwd = rowDir("B1");
  const rt = await recordingRuntime();
  const { h: s, file, prev } = await seed(cwd, rt, B);
  s.session.sessionManager.appendCustomEntry("perk:workflow-state", { stage: "plan", mode: "read-only" });
  await closePerk(s);
  const h = await perk(cwd, rt, SessionManager.open(file));
  try {
    assert.equal(h.workflowState().stage, "plan", "fixture: the resumed stage");
    assert.equal(h.workflowState().mode, "read-only", "fixture: the resumed mode");
    const afterStartup = isActive(h.session, B);
    const verdict = await h.emitToolCall(B, {});
    const r1 = await census(h.session, rt);
    const after1 = h.session.getActiveToolNames();
    const r2 = await census(h.session, rt);
    const r3 = await census(h.session, rt);
    result("B1", [
      [`declared(1):${B}`, yn(r1.tools.includes(B))],
      [`blocked:${B}`, yn(verdict?.block === true)],
      [`active-after-1:${B}`, yn(after1.includes(B))],
    ]);
    obs("B1", [[`active-after-startup:${B}`, yn(afterStartup)], ...prefix(prev, [r1, r2, r3])]);
  } finally {
    await closePerk(h);
  }
});

// --- N1 / N2: Pi's registry filters on resume -------------------------------------------------------

test("N1", async () => {
  const cwd = rowDir("N1");
  const rt = await recordingRuntime();
  const { h: s, file, prev } = await seed(cwd, rt, P);
  await closePerk(s);
  const h = await perk(cwd, rt, SessionManager.open(file), { excludeTools: [P] });
  try {
    assert.equal(h.workflowState().stage, "implement", "fixture: the resumed stage");
    const afterStartup = isActive(h.session, P);
    const r1 = await census(h.session, rt);
    const after1 = h.session.getActiveToolNames();
    const r2 = await census(h.session, rt);
    const r3 = await census(h.session, rt);
    result("N1", [
      [`registered:${P}`, yn(isRegistered(h.session, P))],
      [`active-after-startup:${P}`, yn(afterStartup)],
      [`active-after-1:${P}`, yn(after1.includes(P))],
      ...others().map((name): [string, string] => [`exposure:${name}`, h.toolInfo(name)?.exposure ?? "unregistered"]),
    ]);
    obs("N1", prefix(prev, [r1, r2, r3]));
  } finally {
    await closePerk(h);
  }
});

test("N2", async (t) => {
  const calls = observe(t);
  const cwd = rowDir("N2");
  const rt = await recordingRuntime();
  const { h: s, file, prev } = await seed(cwd, rt, P);
  await closePerk(s);
  calls.length = 0;
  const h = await perk(cwd, rt, SessionManager.open(file), {
    tools: ["read", "bash", "edit", "write", "tool_search", "perk_stage", P],
  });
  try {
    assert.equal(h.workflowState().stage, "implement", "fixture: the resumed stage");
    const cp = checkpoint(calls);
    const afterStartup = isActive(h.session, P);
    const r1 = await census(h.session, rt);
    const r2 = await census(h.session, rt);
    const r3 = await census(h.session, rt);
    diag("N2", "calls-before-perk", String(cp.callsBeforePerk));
    result("N2", [
      [`active-before-perk:${P}`, beforePerk(cp, P)],
      [`active-after-startup:${P}`, yn(afterStartup)],
      [`declared(1):${P}`, yn(r1.tools.includes(P))],
      ...prefix(prev, [r1, r2, r3]),
    ]);
    obs("N2", [["perk-calls", String(calls.filter((c) => c.perk).length)]]);
    prefixObs("N2", h, prev, [r1, r2, r3]);
  } finally {
    await closePerk(h);
  }
});

// --- M1 / M2: a late deferred MCP tool on resume / on /reload (PERK + CONTROL) ----------------------

test("M1", async () => {
  {
    const cwd = rowDir("M1", "perk");
    const fake = fakeServer([SEARCH]);
    const rt = await recordingRuntime();
    const file = plantImplement(cwd);
    const s = await perk(cwd, rt, SessionManager.open(file), { extras: [mcp(fake, "M1-perk")] });
    try {
      assert.equal(s.workflowState().stage, "implement", "fixture: the seed's stage");
      await seedMcp(s.session, rt);
    } finally {
      await closePerk(s);
    }
    assert.ok(readFileSync(file, "utf8").includes(TOOL), "fixture: the session file names the tool");
    const connections = fake.connections;
    fake.holdNext();
    const h = await perk(cwd, rt, SessionManager.open(file), { extras: [mcp(fake, "M1-perk")] });
    try {
      diag("M1", "in-window-registered", yn(isRegistered(h.session, TOOL)));
      await finishLate("M1", h.session, rt, fake, connections, ARM);
    } finally {
      await closePerk(h);
    }
  }
  {
    const cwd = rowDir("M1", "control");
    const agentDir = join(ROOT, "control-agent", "M1");
    const fake = fakeServer([SEARCH]);
    const rt = await recordingRuntime();
    const file = plantSession(cwd, []);
    const s = await control(cwd, rt, SessionManager.open(file), agentDir, [toolSearch(), mcp(fake, "M1-control")]);
    try {
      await seedMcp(s, rt);
    } finally {
      await closeControl(s);
    }
    assert.ok(readFileSync(file, "utf8").includes(TOOL), "fixture: the session file names the tool");
    const connections = fake.connections;
    fake.holdNext();
    const c = await control(cwd, rt, SessionManager.open(file), agentDir, [toolSearch(), mcp(fake, "M1-control")]);
    try {
      diag("M1", "in-window-registered", yn(isRegistered(c, TOOL)), "CONTROL");
      await finishLate("M1", c, rt, fake, connections, "CONTROL");
    } finally {
      await closeControl(c);
    }
  }
});

test("M2", async () => {
  {
    const cwd = rowDir("M2", "perk");
    const fake = fakeServer([SEARCH]);
    const rt = await recordingRuntime();
    const h = await perk(cwd, rt, SessionManager.open(plantImplement(cwd)), { extras: [mcp(fake, "M2-perk")] });
    try {
      assert.equal(h.workflowState().stage, "implement", "fixture: the seed's stage");
      await seedMcp(h.session, rt);
      const connections = fake.connections;
      fake.holdNext();
      await h.reload();
      diag("M2", "in-window-registered", yn(isRegistered(h.session, TOOL)));
      await finishLate("M2", h.session, rt, fake, connections, ARM);
    } finally {
      await closePerk(h);
    }
  }
  {
    const cwd = rowDir("M2", "control");
    const fake = fakeServer([SEARCH]);
    const rt = await recordingRuntime();
    const c = await control(cwd, rt, SessionManager.open(plantSession(cwd, [])), join(ROOT, "control-agent", "M2"), [
      toolSearch(),
      mcp(fake, "M2-control"),
    ]);
    try {
      await seedMcp(c, rt);
      const connections = fake.connections;
      fake.holdNext();
      await c.reload();
      diag("M2", "in-window-registered", yn(isRegistered(c, TOOL)), "CONTROL");
      await finishLate("M2", c, rt, fake, connections, "CONTROL");
    } finally {
      await closeControl(c);
    }
  }
});
```

### `norm.sh` (verbatim)

SHA-256 `42ad9f23ab2ad32c009b9b96c99356a98b13f1e7b7ec205a3b1939588b142a86`. Usage: `norm.sh t1|t2 <log> [row]`.

```sh
#!/bin/sh
# D8's comparison projection over a script log: the NORM lines (T1, strict) or the NORM lines with
# the hash fields stripped (T2). An optional row id restricts the output to that row's lines.
# usage: norm.sh t1|t2 <log> [row]
set -eu
tier=$1
log=$2
row=${3:-[A-Z0-9-]+}
lines() {
  grep -E "^(RESULT|DIAG) ${row} " "$log" |
    sed -E 's/^(RESULT|DIAG) ([A-Z0-9-]+) (AS-IS|G1|G2|CONTROL) /\1 \2 ARM /'
}
case $tier in
  t1) lines ;;
  t2) lines | sed -E 's/ H(prev|[123])=[0-9a-f]{12}//g' ;;
  *)
    echo "usage: norm.sh t1|t2 <log> [row]" >&2
    exit 2
    ;;
esac
```

## The patch (verbatim)

`git diff -- extension/ > .perk-characterization/guarded.patch` on `H0`;
`shasum -a 256 .perk-characterization/guarded.patch` →
`b156006451d7504be56c8c56b5ec3a812d5bfcc63135ce6d516d2258719446a4`. With both env vars unset it is
inert (the inert gate). G1 = `PERK_CHAR_SKIP_RECORDED=1`; G2 adds `PERK_CHAR_WINDOW_ON_RESTORE=1`.
`restoredLoadout(ctx)` read the branch projection at a `startup` `session_start` (it returned true
there: `M1 G2 KEPT` and the R1/K1 G2 window residual), so the plan's G2 fallback opener was not
needed; this text is what was measured.

```diff
diff --git a/extension/pi/activation.ts b/extension/pi/activation.ts
index 81631355..982e29ed 100644
--- a/extension/pi/activation.ts
+++ b/extension/pi/activation.ts
@@ -16,6 +16,7 @@
 import { existsSync, mkdirSync } from "node:fs";
 import * as nodeModule from "node:module";
 import { basename, join } from "node:path";
+import { getCurrentTools } from "@earendil-works/pi-ai";
 import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
 import { createDraftReviewWaveState } from "../authoring/review/draftContext.ts";
 import { createHunkFeedbackReceiver, type HunkFeedbackReceiver } from "../hunkFeedback/receiver.ts";
@@ -158,6 +159,31 @@ function installProductionBridge(): BridgeStatus {
   });
 }
 
+/**
+ * The family members the branch's transcript records active AND that are live now: the branch's
+ * system messages replayed by `getCurrentTools`, intersected with the active set, filtered to
+ * `deferred`. Empty on any throw.
+ */
+function recordedLive(
+  ctx: { sessionManager: { getBranch(): readonly unknown[] } },
+  pi: ExtensionAPI,
+  deferred: readonly string[],
+): string[] {
+  try {
+    const messages = ctx.sessionManager.getBranch().flatMap((entry) => {
+      const e = entry as { type?: string; message?: { role?: string } };
+      return e.type === "message" && e.message?.role === "system"
+        ? [e.message as { role: string }]
+        : [];
+    });
+    const recorded = new Set(getCurrentTools(messages).map((tool) => tool.name));
+    const live = new Set(pi.getActiveTools());
+    return deferred.filter((name) => recorded.has(name) && live.has(name));
+  } catch {
+    return [];
+  }
+}
+
 function writeT3Sentinel(
   cwd: string,
   source: string,
@@ -572,7 +598,9 @@ export function activatePerk(
           // Join with what actually deferred: a member whose re-registration failed stays
           // always-declared, and nothing deferred means nothing to join.
           const deferred = deferDiscoveryFamily(pi);
-          if (deferred.length > 0) gating.joinDiscoveryCohort(deferred);
+          const keep =
+            process.env.PERK_CHAR_SKIP_RECORDED === "1" ? recordedLive(ctx, pi, deferred) : [];
+          if (deferred.length > 0) gating.joinDiscoveryCohort(deferred, keep);
         }
       }
     } catch (error) {
diff --git a/extension/substrate/toolGating.ts b/extension/substrate/toolGating.ts
index d3df6a19..719afec7 100644
--- a/extension/substrate/toolGating.ts
+++ b/extension/substrate/toolGating.ts
@@ -225,7 +225,7 @@ export interface ToolGating {
    * one install, and only they are treated as deferred from then on. Idempotent per activation
    * (a second call is a no-op); installs nothing itself.
    */
-  joinDiscoveryCohort(family: readonly string[]): void;
+  joinDiscoveryCohort(family: readonly string[], keep?: readonly string[]): void;
   /**
    * Primed activation: activate the members deferred in this session among `names` that are registered,
    * eligible in the presented landing and not yet active, in catalog order; returns them. A primed
@@ -395,8 +395,12 @@ export function registerToolGating(
   // The restoration window opens where Pi restores a loadout (`/reload`, a `/tree` restore). These
   // handlers are registered before pi/activation.ts subscribes its own, so the flag is set before that
   // event's `syncFromState` reconciles.
-  pi.on("session_start", async (event) => {
-    if (event.reason === "reload") restorationWindow = true;
+  pi.on("session_start", async (event, ctx) => {
+    if (
+      event.reason === "reload" ||
+      (process.env.PERK_CHAR_WINDOW_ON_RESTORE === "1" && restoredLoadout(ctx))
+    )
+      restorationWindow = true;
   });
   pi.on("session_tree", async (_event, ctx) => {
     restorationWindow = true;
@@ -599,12 +603,12 @@ export function registerToolGating(
       return settle("read-write", "install", () => apply(false, stageId));
     },
     isActive,
-    joinDiscoveryCohort(family: readonly string[]): void {
+    joinDiscoveryCohort(family: readonly string[], keep: readonly string[] = []): void {
       if (cohort) return;
       const named = new Set(family);
       cohort = true;
       deferred = discoveryFamily().filter((name) => named.has(name));
-      pendingDeferral = [...deferred];
+      pendingDeferral = deferred.filter((name) => !keep.includes(name));
     },
     primeDeferred(names: readonly string[]): string[] {
       if (!cohort) return [];
```

## Teardown proof

D10's commands, run from `$IMPL` after the record was copied out of `$SCRATCH`
(`teardown.log`, kept in the run's gitignored agent scratch):

```
== git checkout -- extension/substrate/toolGating.ts extension/pi/activation.ts
exit=0
== git diff --stat HEAD -- extension/
(end)
== perk-agent-* in $TMPDIR: total / created during the sitting (newer than the start stamp)
31753 / 0
== perk-cwd-* / perk-fake-subagents-* created during the sitting (the suite runs' scaffolds)
0 / 0
== remove the sitting's harness residue (newer than the start stamp only)
exit=0
== after: perk-agent-* total / newer than the start stamp
31753 / 0
== rm -rf "$ROOT"
exit=0
absent
== rm -rf .perk-characterization
exit=0
absent
== git status --porcelain
?? docs/design/archive/pi-1.4.0-restored-discovery.md
```

That first pass removed no temp-dir residue. The start stamp had been copied out of `$SCRATCH` with
`cp`, which gave the copy a fresh mtime, so nothing was newer than it (`31753 / 0`). The original
stamp was deleted with `$SCRATCH`. The copy was reset to the snapshot second, and the removal re-ran
(`teardown-2.log`). The sitting's entries fall in 15:37–15:42Z; the newest pre-existing
`perk-agent-*` is 14:09Z, so any reference instant between those selects the same set:

```
== (re-run) the copied start stamp had taken cp's mtime; reset to the snapshot second: touch -t 202610251128.27 (local EDT) = 2026-10-25T15:28:27Z
== perk-agent-* in $TMPDIR: total / created during the sitting (newer than the start stamp)
31753 / 515
== mtime range of the sitting's entries (local EDT)
  29 11:37
  71 11:38
   6 11:39
  69 11:40
 603 11:41
  92 11:42
== perk-cwd-* / perk-fake-subagents-* created during the sitting (the suite runs' scaffolds)
352 / 3
== remove the sitting's harness residue (newer than the start stamp only)
exit=0
== after: perk-agent-* total / newer than the start stamp; perk-cwd-* / perk-fake-subagents-* newer
31238 / 0; 0 / 0
== git status --porcelain
?? docs/design/archive/pi-1.4.0-restored-discovery.md
```

- **Removed:** the sitting's 515 `perk-agent-*` dirs, one per `loadPerkSession`: 23 per script
  run × 7 runs = 161, and the remaining 354 from the three suite runs. Also removed: the 352
  `perk-cwd-*` and 3 `perk-fake-subagents-*` scaffolds the suite runs created. 31 238
  pre-existing `perk-agent-*` dirs from earlier harness runs remain, as they were before the
  sitting. The Step 0 count of `0` was the overflowed `ls` (see the deviations).
- **Not proven deleted:** nothing else. `$ROOT` and `$SCRATCH` are absent, and the two patched
  files are back at `H0` (`git diff --stat HEAD -- extension/` is empty).
- **Porcelain:** only this record, as quoted above.
