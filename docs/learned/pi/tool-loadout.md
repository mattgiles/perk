---
title: Pi tool loadout — activation vs presentation vs enforcement, the registerPerkTool catalog, provenance postures, deferred priming, the restoration window
read_when: Changing which tools a session sees or can call — registerPerkTool policies, foreign-tool postures, deferred priming/tool_search, /reload or /tree restoration, codemode under the gate, loadout tests
cluster: pi-extension
---

# Pi tool loadout

The reasons behind perk's tool loadout. The normative text is `shared/contracts.md` §8.40; the
code is `extension/pi/perkTool.ts` (the seam), `extension/substrate/toolPolicy.ts` (catalog,
formula, postures, derived views) and `extension/substrate/toolGating.ts` (the gate runtime).

## Distillation

- Three levers, never conflated: activation (the active set), presentation (`prepareLoadout` →
  `hiddenDeclarations`), enforcement (`tool_call`); a hidden tool stays active and callable —
  "Three levers".
- Hiding ≠ deactivation (a tool whose hook rewrites others' presentation must be deactivated);
  snippets rebuild only at install; `promptGuidelines` render for hidden tools; `defaultTools` is
  inert for extension tools; only `/tree` restores a declared loadout — "Pi host facts".
- `defaultTools` resolution (plain names replace, modifiers append, non-strings dropped; the
  opt-out is a committed project `-tool_search`, never `[]`) — "`defaultTools` resolution".
- Pi ≥ 1.0 keeps a pending-restoration set from `/reload`/`/tree` until the run starts; any
  deactivating install drops it, so perk's removals wait for `agent_start` — "The
  pending-restoration set and the restoration window".
- Own-names-only activation, once per prompt; foreign tools by registrant provenance; codemode
  suspended under the gate; presentation fails open, enforcement fails closed — "perk's
  activation design".
- One `registerPerkTool(pi, definition, policy)` call per tool; `kind` rules; regenerate
  `tool-matrix.json`; borrow-package checklist — "How to add or change a perk tool".
- A single-word tool name is checkable in carriers only when backtick-quoted — "The prompt guard".
- A carrier naming a `declared: deferred` tool primes it first (`*_PRIMES` →
  `primeDeferred`); key cohort state on what actually deferred — "Native discovery and priming".
- Harness mode A loads builtin extras BEFORE perk; recording fakes prove wiring, not outcome —
  "Test craft". Open risks — "Residual risks".

Version stamps are per section: own-names activation and the host facts were verified at Pi
`0.99.2`; the restoration window at `1.0.0`. History lives in the cited archive records.

## Three levers

- **Activation** — the session's active set (`pi.setActiveTools`). An inactive tool contributes no
  snippet and no guidelines to the system prompt and cannot be declared to the model.
- **Presentation** — the loadout host's `prepareLoadout` hook returns `hiddenDeclarations`; a
  hidden tool is not declared in the request but stays **active and callable** (nested
  `ctx.executeTool`, codemode).
- **Enforcement** — the read-only `tool_call` handler, the only lever that refuses a call.

Every perk decision is a choice of lever. §8.40 states which lever does what; this doc carries why.

## Pi host facts (verified 0.99.2; re-verify at 1.0.0 is owed)

- **Hiding is not deactivation.** Pi's `_applyToolLoadout` runs the `prepareLoadout` of every
  ACTIVE tool, hidden ones included; every hook sees the same unfiltered loadout; hidden names are
  unioned (no hook can un-hide a name); `descriptions` are last-writer-wins in active-tool order.
  So a tool whose hook rewrites how OTHER tools are presented (codemode) must be *deactivated*, not
  hidden.
- **Snippets rebuild only at install.** `_rebuildSystemPrompt` runs on `setActiveToolsByName` and
  builds `toolSnippets` without that install's hidden names; the per-request pass only filters
  further and never re-adds a snippet. `promptGuidelines` render even for hidden tools.
- **Registry filters vs startup preferences.** `tools`/`excludeTools` (`--tools`/`--exclude-tools`)
  filter the registry itself — a filtered tool is absent from `getAllTools()` and its hook never
  runs; pi-subagents forwards a child def's `tools:` this way. `defaultTools` only shapes the
  startup set and is inert for extension tools, because `createAgentSession` sets
  `includeAllExtensionTools: true`.
- **Resume and fork never restore a transcript's declared loadout** — `createAgentSession` always
  passes `initialActiveToolNames`; only `/tree` (`navigateTree`) restores. A `tool_search`
  activation does not survive resume or fork.
- **Provenance** (`ToolInfo.sourceInfo`): a package tool's `source` is the settings spec verbatim;
  a named inline factory gets `path: "<inline:<name>>"`; a bare factory a positional `<inline:N>`
  (unknown provenance); `{ name, factory, builtin: true }` gets `source: "builtin"`.
- **Every registration installs.** `_refreshToolRegistry` calls `setActiveToolsByName` on every
  registration, so spying on that method alone cannot count an extension's installs.
- **`registerTool` replaces by name only within the registering extension.** perk keeps its own
  definitions keyed by the activation's own `pi` (a `WeakMap` in `perkTool.ts`), never by name — a
  second session bound in the same process has its own `pi`.
- **Deferred exposure.** Re-registering as `exposure: "deferred"` leaves the tool active (the
  extension deactivates it once); an inactive tool's snippet AND guidelines leave the prompt.
  Pi's callable set includes every registered deferred tool, active or not — nested
  `ctx.executeTool` reaches inactive members — so defer only self-guarding tools (an execute core
  that refuses outside its flow). `tool_search` activates every positive-scoring match up to its
  limit of 8, not only the top hit.

## `defaultTools` resolution (0.99.2 settings-manager mirror; decays)

- `resolveDefaultTools`: `[]` → no builtin tools; plain names form the selection; a
  modifier-only list starts from the four defaults; `+`/`-` modifiers apply in list order.
- `mergeDefaultTools`: a modifier-only project list — `[]` included — appends to the user list;
  plain names replace it.
- `getDefaultTools` drops non-string entries and treats a non-array as `[]`.
- `/reload` turns on newly added names but keeps removed names active.
- Only the user and project layers exist, so a user-global `-tool_search` cannot override a
  project `+tool_search`; a project `[]` is NOT an opt-out — the opt-out is a committed project
  `-tool_search`.

perk's convergence of the `+tool_search` seed (seed-when-unnamed) is in
`docs/learned/workflow/init-doctor.md` § "Host-floor rows and the three settings-convergence shapes".

## The pending-restoration set and the restoration window (Pi ≥ 1.0, verified 1.0.0)

- **Pi's set.** `AgentSession._pendingToolNames` is populated by `/reload` (every active name) and
  by a `/tree` restore (the transcript's declared loadout, before `session_tree` handlers run) — not
  by SDK/CLI resume. It is cleared by any `setActiveTools` that deactivates a previously active
  name (an identical or purely additive call keeps it) and by `_runAgentPrompt` after every
  extension's `before_agent_start` (MCP's `waitForDirectServers` included). Practical rule: removing
  tools at `session_start`/`session_tree`/`before_agent_start` drops what a reconnecting MCP server
  would get back.
- **`agent_start` is the first event after Pi's clear.** It fires for prompted runs and for
  `pi.sendMessage(…, {triggerTurn: true})` runs (which skip `before_agent_start`). But
  `createContextSnapshot()` and `declareToolChanges` run before the emit, so only the
  hidden-declaration mask can shape the first request.
- **The mask.** `hiddenDeclarations` is rebuilt on every loadout application, unioned across
  hooks, never filtered by the declared list, and applied by name to the whole transcript. A mask
  derived from `loadout.declared` forgets exactly the names removed in that same install → hide by
  name over registered tools; masking an undeclared name is a no-op.
- **The MCP builtin** has no `session_tree` handler, restarts its connections on every
  `session_start` (a test re-emitting `session_start` invalidates a held connection), and its
  `deferred` exposure is restored only by the pending set.

**perk's rule.** Between a `reload` `session_start` (or a `session_tree`) and the next
`agent_start`, a removal-bearing reconciliation only adds; the removals — the cohort's family
deferral, the stage diet, the codemode suspension — land at `agent_start` (the `pendingDeferral`
and `suspended` memos in `toolGating.ts`). `session_tree` clears `pendingDeferral` when
`ctx.sessionManager.buildSessionProjection().messages` carries a `role: "system"` message — Pi's own
restore condition; re-verify it at every pin bump. Priming an inactive pending member inside the
window is preserved at the close. Tests: `extension/substrate/restorationWindow.test.ts`.

**Accepted residual.** The first request after a cohort `/reload` is built before the close: its
system prompt carries the deferred family's guidelines and snippets while the declarations are
hidden; clean from the second request. A fix inside `before_agent_start` is ruled out (it would
clear Pi's set early, and editing `selectedTools` there drops tools registering in a later wait).

**Design lesson.** Deferring an effect turns memos into window state. Enumerate everything that can
interleave inside the window — tree restore, prime, gate/stage gesture, triggered turn, failing
install, a second reload — and pin each; sweep pins that assert immediacy by running the whole
suite, not the plan's file list. Record: `docs/design/archive/pi-1.0.0-mcp-restoration.md`.

## perk's activation design (why, not what — verified 0.99.2)

- **Own-names-only** (`reconcileTarget`): perk installs
  `(live − perk) ∪ eligible-always-perk ∪ (live ∩ eligible-deferred-perk)`, over registered names
  only. A bare session (no stage, read-write, no floor) makes zero `setActiveTools` calls. perk's
  own activation is policy-owned — a foreign removal of an always-declared perk tool is undone at
  the next reconciliation — and perk never re-activates a deferred perk tool; only the host does.
- **Once per prompt.** Reconciliation runs at `before_agent_start` (plus `session_start`,
  `session_tree`, `resources_discover`, `enter`/`exit`, `agent_start`); only the host's hiding runs
  per request. A `tool_search` hit is hidden on the next request and switched off when the next
  prompt starts.
- **Foreign tools by registrant provenance** (`postureFor`): catalog by name → exact synthetic path
  (never a prefix rule) → builtin row → normalized package spec (+ its `except` names) →
  `unknown` (passes every read-write diet, blocked under the gate). Posture rows (`POSTURE_ROWS`):
  `research`, `universal`, `delegation`, `never`, `child-engine`; the
  `<inline:pi-subagents:prompt-runtime>` row in `SYNTHETIC_PATH_TOOL_POLICY` governs
  pi-subagents' in-child engine tools.
- **Codemode suspension.** In mode `only`, codemode's own `prepareLoadout` hides every direct tool,
  so a hidden-but-active codemode left a gated model with no `read`/`bash`/`plan_draft`. The
  builtin-sourced `codemode` row (`suspendedUnderGate`) is switched off while presenting read-only
  and restored at release (`suspensionStep`; the memo updates only after a successful install) —
  the one non-perk exception to own-names-only.
- **Flip-only reinstall.** When only the presented mode flips, perk still installs the live set
  (gated on the host being active), because Pi rebuilds snippets only at install — this brings
  `edit`/`write` snippets back at gate exit. Skipped when the host is absent, keeping the
  zero-install guarantee for allowlisted children.
- **Fail postures.** Presentation fails open (a hook throw hides only the host); enforcement fails
  closed (the latch `if (nextActive) active = true` before any read; an unregistered name is
  blocked before classification). `presentedMode`/`stageId` are set before the install so the hook
  inside it sees the settled landing; a failed install rolls `presentedMode` back via the
  floor-aware `isActive()`.
- **The loadout host** (`perk_stage`, `registerLoadoutHost`): a literal-named, model-only tool whose
  only job is `prepareLoadout`. Its return type `LoadoutPresentation` has `descriptions?: never`, so
  no request-time description rewrite can bypass prose governance (see
  `docs/learned/workflow/prose-review-workbench.md`).

## How to add or change a perk tool

- **One call:** `registerPerkTool(pi, definition, policy)` with
  `{ stages, gated: allowed | blocked | { carveOut }, modeOverStage?, kind, declared?, result? }`.
  Never hand-set `exposure`/`annotations`/`defaultActive`/`prepareLoadout`/`outputSchema` —
  `validateToolPolicy` throws (`POLICY_OWNED_FIELDS`).
- **`kind` rules:** can return `terminate: true` ⇒ `terminal`; opens a human surface ⇒
  `interactive`; spawns a wave/child/resolver ⇒ `orchestration`; pure read ⇒ `query`; else
  `action`. A trust/confirm dialog does not make a tool interactive. `terminal`, `interactive` and
  `orchestration` become model-only (never reachable through `ctx.executeTool`).
- **A new `terminal` tool** joins `TERMINATING_ENTRY_POINTS` in `extension/pi/perkTool.test.ts`
  (test-local, stale-armed).
- **Regenerate the golden matrix:** `PERK_UPDATE_TOOL_MATRIX=1 node --test extension/substrate/toolMatrix.test.ts`.
  `shared/fixtures/tool-matrix.json` feeds the Python prompt guard, the prose-map governed census
  and the docs-site `Kind`/`Under the gate` check.
- A `carveOut` string renders verbatim into the read-only context (`renderReadOnlyContext`).
- `kind: query` must declare `result` (closed success arm, `ok` forbidden inside, `required` ⊆
  properties); the structured-result contract is in `docs/learned/pi/extension-api.md`.
- **Audit `modeOverStage` writers.** A stage-blind `modeOverStage` writer is live in every gated
  stage — audit its execute path before calling it inert (`plan_draft` in `objective-refine` is
  "reachable but unsaveable").
- **New borrow or provider package:** a `PACKAGE_TOOL_POLICY` row, or the package in
  `ZERO_TOOL_PACKAGES` (`tests/test_tool_matrix_postures.py`, the cross-plane parity test); the
  marked posture-table region in `docs/user-docs/reference/in-session/model-tools.md` (checked by
  `docs/site/src/in-session-reference.test.mjs`); regenerate the matrix. New tools inside an
  existing package need no enumeration.
- **Retiring a vocabulary:** grep the perk-expert mirrors (`skills/perk-expert/references/`) and
  `providers.md` too — they carried "name-keyed" sentences a plan had called untouched.

## The prompt guard (both planes)

- **TS:** `extension/substrate/stageTools.test.ts::DRIVE_COVERAGE` — `{stage, mode}` landings
  (gated landings included), `primes`, and the tools each drive names.
- **Python:** `tests/test_tool_matrix_prompts.py` — `LANDINGS`, `TOOL_FREE_FRAGMENTS`,
  `WARM_ONLY`; it scans raw template source, Jinja tags included.
- **Match rule:** a name containing `_` matches as a bare word; a single-word name (`submit`,
  `ready`, `land`, …) only when backtick-quoted. To make a single-word reference checkable, backtick
  it; an unquoted single word is an accepted miss.
- Expect a new guard to find carriers the plan's census missed.

## Native discovery and priming (Law 4 corollary)

- **Key on what actually deferred.** `deferDiscoveryFamily` re-registers each member separately,
  best-effort; the cohort's deferred set is the members that actually deferred. A session-wide
  flag caused the pilot's one real bug: a member whose re-registration failed stayed `direct`
  (unsearchable) yet was dropped at gate entry. General rule: after a per-item best-effort
  transform, key downstream state on what each item became.
- **Prime before the carrier lands.** A carrier naming a `declared: deferred` tool primes it via
  an exported `*_PRIMES` constant (`DRAFT_REVIEW_DOOR_PRIMES`, `DRAFT_LAUNCH_PRIMES`,
  `REVIEW_BROWSER_PRIMES`, `REVIEW_TERMINAL_PRIMES`, `REVIEW_LAUNCH_PRIMES`, `STACK_STATUS_PRIMES`)
  passed to `gating.primeDeferred` — doors at their surface-prime moment, wave launchers on their
  success arm. Priming is fail-open presentation.
- **Guards.** `DRIVE_COVERAGE.primes` is two-way (every named deferred tool primed; every prime a
  named deferred tool). A carrier census forbids any catalogued tool's description/guidelines
  naming another tool's deferred member except the two launchers — reword, don't widen. The Python
  rule covers cold seeds, common fragments and stage-bound skills.
- **The headless worker** joins the cohort (since #2671) and has no doors, so its deferred members
  return only via `tool_search` or launcher priming.
- **Measured savings:** ≈5.5 KB (worktree stages), 4.8 KB (plan/objective), 4.8 KB (stack-review)
  per request vs a 693 B fixed cost; snippets + guidelines were 58 % of the family's bytes. Record:
  `docs/design/archive/native-discovery-pilot-dogfood.md`. Law 4 itself:
  `docs/learned/workflow/warm-door-commands.md`.

## Test craft

- **Extension order differs by harness mode.** Pi's `loadFinalExtensionSet` orders CLI
  `additionalExtensionPaths`, settings packages, `builtin:*`, then non-builtin inline factories
  last — so harness Mode A (inline perk) loads `builtin: true` extras BEFORE perk; Mode B
  (`packages: []`) matches production. Assert via `session.extensionRunner.getExtensionPaths()`.
- **Mode B fake packages:** `<agentDir>/npm/node_modules/<name>` + `PI_OFFLINE=1`; throw on
  `loader.getExtensions().errors`; perk runs in jiti's separate module instance, so assert only
  through the live session.
- **Attribute installs** with `recordPerkInstalls` (`extension/testing/harness.ts`) and assert the
  record is non-empty somewhere. "No install" is the default under own-names-only, so perturb state
  before claiming an ordering.
- **Discriminate host behaviour from perk filtering** — resume/fork from a leaf where perk would
  keep the tool. Check fail-open/closed immediately after the failing call (before a reconciling
  hook repairs it) and mutation-check the rollback.
- **Drive nested execution for real:** `ctx.executeTool("write", …)` from a gate-allowed probe plus
  a read-write control; never fabricate a `tool_call` with a `parentToolCallId`. Register
  `structured_output` through the named `pi-subagents:prompt-runtime` factory.
- **A recording fake proves wiring, not outcome** — the draft-review door's prime needed a real
  cohort session. `h.emitSessionStart()` proves idempotence; `h.reload()` proves reload semantics.
  Don't mock Pi's private internals or attribute installs from stack traces in new tests.
- **Offline MCP fixture:** `createInMemoryTransportPair` from `@earendil-works/pi-mcp/testing`
  (resolved nested under pi-coding-agent), `initialize` held behind a promise, `PI_CODING_AGENT_DIR`
  scratch, an explicit `logPath`, a re-armed `probe` builtin before the MCP factory.
- **Characterize with matched controls** before alleging a regression: a CONTROL session without
  perk; Pi-deactivating and Pi-additive controls for gesture rows; a classification table fixed
  before measuring; a throwaway detached worktree pinned to the subject version.
- Files: `extension/substrate/ownNamesActivation.test.ts`, `restorationWindow.test.ts`,
  `discoveryPilot.test.ts`, `stageTools.test.ts`, `toolMatrix.test.ts`.

## Residual risks

- An ineligible `tool_search` activation stays active and callable (hidden) until the next prompt.
- Read-write diets have no call-time backstop; unknown-provenance tools pass them.
- The codemode suspension is a builtin-name special case — any future hook that rewrites others'
  presentation reproduces the wedge under the gate.
- Presentation-only leaks: codemode's read-write description can list diet-hidden tools; a
  one-request lag on pre-change transcripts when a later handler edits `selectedTools`.
- The restoration window stays open until the user prompts; restore detection depends on Pi's
  projection shape; broad `tool_search` queries over-activate.
- `perkToolsFor`'s boolean `cohort` parameter keeps the pre-fix "cohort excludes the whole family"
  semantics with no production caller (routed follow-up, #2705 F7).
- The `@tombell/pi-plan` `/plan` restriction (`setActiveTools`) is undone by policy-owned
  activation while contracts §8.10 still describes it as hiding `plan_draft`/`plan_review` (owner
  decision owed; routed follow-up, #2705 F8).
- 0.99.2-stamped facts owe a 1.0.0 re-verify: hook semantics, snippet rebuild,
  `includeAllExtensionTools`, resume/fork non-restoration.

## Sources

- Pi dist read: `core/agent-session`, `core/extensions/{runner,loader}`, `core/tools`, the MCP
  builtin (`extensions/mcp`), `core/settings-manager` — own-names activation, host facts and
  `defaultTools` at `0.99.2`; the pending-restoration set, `agent_start` ordering and the MCP
  builtin at `1.0.0`.
- Records: `docs/design/archive/pi-1.0.0-mcp-restoration.md`,
  `docs/design/archive/native-discovery-pilot-dogfood.md`.

## Cross-references

- `shared/contracts.md` §8.40 — the normative loadout contract
- `docs/learned/workflow/warm-door-commands.md` — Law 1 (gated tools) and Law 4 (guidance-named tools)
- `docs/learned/pi/read-only-bash-gate.md` — the bash verdict the gate consumes
- `docs/learned/pi/context-system.md` — the gate-engagement latch lesson
- `docs/learned/workflow/borrowed-packages.md` — borrowed engines and their package rows
- `docs/learned/workflow/init-doctor.md` — the `defaultTools` seed convergence
- `docs/learned/pi/extension-api.md` — the structured-result contract and harness facts
- `docs/learned/pi/subagents.md` — the child-engine row and allowlisted report children
- `docs/user-docs/reference/in-session/model-tools.md` — the user-facing posture table
