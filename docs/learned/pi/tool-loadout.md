---
title: Pi tool loadout — activation vs presentation vs enforcement, the registerPerkTool catalog, provenance postures, deferred discovery, the restoration window, nested execution
read_when: Changing which tools a session sees or calls — registerPerkTool policies, foreign/MCP postures, deferred discovery, resume, /reload or /tree restore, codemode/nested calls under the gate, tool tests
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
- Hiding ≠ deactivation; snippets rebuild only at install and hidden tools' snippets AND
  `promptGuidelines` leave the prompt; resume and fork restore the recorded loadout in the
  constructor; registration activates iff declarable ∧ `defaultActive !== false`; an allowlist is
  never an MCP exclusion — "Pi host facts".
- `defaultTools` resolution (plain names replace, modifiers append, non-strings dropped; the
  opt-out is a committed project `-tool_search`, never `[]`) — "`defaultTools` resolution".
- Pi keeps a pending-restoration set from `/reload`, `/tree` and resume/fork until the run
  starts; any deactivating install drops it, so perk's window opens on every restored startup and
  its removals wait for `agent_start`; window removals are policy-owned, never read from the
  transcript — "The pending-restoration set and the restoration window".
- Own-names-only activation, once per prompt; foreign tools by registrant provenance; codemode
  lifted in registry read-only stages (`on`, or `only` with no stranded writer); presentation
  fails open, enforcement fails closed — "perk's activation design".
- Nested calls are classified twice from one posture — the gate arm and the narrowing nested arm;
  only a gate-allowed perk `query` runs nested — "Nested execution under the gate".
- One `registerPerkTool(pi, definition, policy)` call per tool; `kind` rules; `gated` is per tool;
  regenerate `tool-matrix.json`; sweep flipped pins — "How to add or change a perk tool".
- A single-word tool name is checkable in carriers only when backtick-quoted — "The prompt guard".
- The discovery family registers deferred; a nonparticipant re-registers it direct; the registry
  is what each item became; carriers prime what they name — "Native discovery and priming".
- Harness mode A loads builtin extras BEFORE perk; late-bound failure knobs; recording fakes prove
  wiring, not outcome — "Test craft". Open risks — "Residual risks". Stamps are per section
  (1.4.0 / 1.1.0 / 0.99.2); history lives in the archive records cited in "Sources".

## Three levers

- **Activation** — the session's active set (`pi.setActiveTools`). An inactive tool contributes no
  snippet and no guidelines to the system prompt and cannot be declared to the model.
- **Presentation** — the loadout host's `prepareLoadout` hook returns `hiddenDeclarations`; a
  hidden tool is not declared in the request but stays **active and callable** (nested
  `ctx.executeTool`, codemode).
- **Enforcement** — the read-only `tool_call` handler, the only lever that refuses a call.

Every perk decision is a choice of lever. §8.40 states which lever does what; this doc carries why.

## Pi host facts (verified 1.4.0)

- **Hiding is not deactivation.** Pi's `_applyToolLoadout` runs the `prepareLoadout` of every
  ACTIVE tool, hidden ones included; every hook sees the same unfiltered loadout; hidden names are
  unioned (no hook can un-hide a name); `descriptions` are last-writer-wins in active-tool order.
  So a tool whose hook rewrites how OTHER tools are presented (codemode) must be *deactivated*, not
  hidden.
- **Snippets rebuild only at install.** `_rebuildSystemPrompt` runs on every install and the
  per-request pass only filters further, never re-adding a snippet. `buildSystemPromptSections`
  computes `declaredTools = selected − hidden` and filters hidden tools out of BOTH the snippets
  and the per-tool guidelines. The *global* `promptGuidelines` session option is a different
  thing and stays unconditional.
- **Registry filters vs startup preferences.** `tools`/`excludeTools` (`--tools`/`--exclude-tools`)
  filter the registry itself — a filtered tool is absent from `getAllTools()` and its hook never
  runs; pi-subagents forwards a child def's `tools:` this way. Exception: MCP tools stay
  registered under a `tools` allowlist unless the allowlist is empty or names an `mcp__` entry
  (`_allowlistFiltersMcp`) — they remain for codemode and `tool_search` — so an allowlist is never
  an MCP exclusion; the read-only `tool_call` backstop is the only control. `defaultTools` only
  shapes the startup set and is inert for extension tools (`includeAllExtensionTools: true`).
- **The callable set.** `_getCallableTools` = active `direct` tools ∪ every registered `codemode`
  or `deferred` tool, active or not; `model-only` tools are excluded (declared, never reachable
  through `ctx.executeTool`).
- **Resume and fork restore the recorded loadout.** The `AgentSession` constructor runs
  `_restoreToolsFromTranscript` iff `_usesDefaultTools` (no explicit `tools:` allowlist), before
  any extension event: it replays the branch's recorded declarations plus every registered
  registration-activated extension tool the branch never mentioned, so stage-ineligible perk tools
  return on every resume/fork and the diet reconciles at a restored startup. An explicit `tools:`
  allowlist skips the restore but activates every *named* entry regardless of exposure, while the
  `allowedTools` *pattern* arm activates only declarable names — the named-vs-pattern split.
- **Registration activation.** Registration activates a tool iff it is declarable (`direct` or
  `model-only`) ∧ `defaultActive !== false` (`_isActivatedOnRegistration`). A `deferred`
  registration is never activated by registration; a later flip to `direct` activates it like a
  new tool; any other re-registration keeps the prior active state. An inactive tool's snippet
  AND guidelines leave the prompt. Defer only self-guarding tools (an execute core that refuses
  outside its flow) — nested `ctx.executeTool` reaches inactive deferred members. `tool_search`
  activates every positive-scoring match up to its limit of 8, not only the top hit.
- **MCP's `ensureDiscoveryActive` exception.** At `session_start` and after reconnects, the MCP
  builtin activates `tool_search` when an enabled server has `deferred` exposure and `codemode`
  when one has `codemode` exposure (unless `autoEnableCodemode: false`); only `-builtin:<name>`
  keeps the discovery tool off.
- **Provenance** (`ToolInfo.sourceInfo`): a package tool's `source` is the settings spec verbatim;
  a named inline factory gets `path: "<inline:<name>>"`; a bare factory a positional `<inline:N>`
  (unknown provenance); `{ name, factory, builtin: true }` gets `source: "builtin"`.
- **Registry refreshes install privately.** `_refreshToolRegistry` (every registration) and the
  constructor restore reach the private `_setActiveTools`, not the public `setActiveToolsByName`,
  so a spy on the public method sees only extension installs — the pinned record used exactly
  that to attribute calls (`docs/design/archive/pi-1.4.0-restored-discovery.md`).
- **`registerTool` replaces by name only within the registering extension.** perk keeps its own
  definitions keyed by the activation's own `pi` (a `WeakMap` in `perkTool.ts`), never by name — a
  second session bound in the same process has its own `pi`.

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
- **Live-census gotcha (Anthropic).** Mid-conversation tool changes ride as
  `tool_addition`/`tool_removal` blocks, so `payload.tools` in `before_provider_request` is not
  the model-visible set in a long session — census the declared set, not the payload array.

perk's convergence of the `+tool_search` seed (seed-when-unnamed) is in
`docs/learned/workflow/init-doctor.md` § "Host-floor rows and the three settings-convergence shapes".

## The pending-restoration set and the restoration window (verified 1.4.0)

- **Pi's set.** `AgentSession._pendingToolNames` is populated by `/reload` (every active name), by
  a `/tree` restore (before `session_tree` handlers run) and by the resume/fork constructor
  restore — the recorded tools that are not registered yet (a reconnecting MCP server's). It is
  cleared by any `setActiveTools` that deactivates a previously active name (an identical or
  purely additive call keeps it) and when the next run starts. Practical rule: removing tools at
  `session_start`/`session_tree`/`before_agent_start` drops what a reconnecting MCP server would
  get back.
- **Every run start goes through `_prepareRun`.** `_startRun → _prepareRun →
  emitBeforeAgentStart` runs for prompted runs and for `sendMessage(…, {triggerTurn: true})` runs
  alike — `before_agent_start` is no longer skipped for triggered turns (see
  `pi/extension-api.md` for the user-vs-custom start union). `agent_start` is the first event
  after Pi's clear, but `createContextSnapshot()` and `declareToolChanges` run before the emit, so
  only the hidden-declaration mask can shape the first request.
- **The first request's declarations are persisted unfiltered.** `declareToolChanges` is computed
  from the active set before `agent_start` and written to the transcript as-is — the
  hidden-declarations projection filters only provider-facing messages. Anything live inside the
  window is therefore recorded and returns on the next resume. Window removals must be
  policy-owned and re-removable by the next sync, never read from the transcript.
- **The mask.** `hiddenDeclarations` is rebuilt on every loadout application, unioned across
  hooks, never filtered by the declared list, and applied by name to the whole transcript. A mask
  derived from `loadout.declared` forgets exactly the names removed in that same install → hide by
  name over registered tools; masking an undeclared name is a no-op.
- **The MCP builtin** has no `session_tree` handler, restarts its connections on every
  `session_start` (a test re-emitting `session_start` invalidates a held connection), and its
  `deferred` exposure is restored only by the pending set.

**perk's rule.** The window opens on a `reload` `session_start`, on `session_tree`, AND on any
`session_start` whose branch projection records a loadout (`restoredLoadout` in `toolGating.ts` —
Pi restores exactly when the projection carries a `role: "system"` message; re-verify at every pin
bump). Until the next `agent_start` a removal-bearing reconciliation only adds; the removals — now
only the stage diet and the codemode suspension (with its `suspended` memo) — land at
`agent_start`. Priming an inactive pending member inside the window is preserved at the close.
Tests: `extension/substrate/restorationWindow.test.ts` and
`extension/substrate/restoredDiscovery.test.ts` (Mode B rows: resume/fork keep, consecutive
resume, late-MCP keep, allowlist resume, nonparticipant resume, fresh-startup control). Record:
`docs/design/archive/pi-1.4.0-restored-discovery.md` (its G2 patch was a measurement instrument
only; the shipped design is "Native discovery and priming").

**Design lesson.** Deferring an effect turns memos into window state. Enumerate everything that can
interleave inside the window — tree restore, resume, prime, gate/stage gesture, triggered turn,
failing install, a second reload — and pin each; sweep pins that assert immediacy by running the
whole suite, not the plan's file list. Record: `docs/design/archive/pi-1.0.0-mcp-restoration.md`.

## perk's activation design (why, not what — verified 0.99.2; the lift at 1.1.0)

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
- **The codemode lift.** In mode `only`, codemode's own `prepareLoadout` hides every direct tool,
  so a hidden-but-active codemode once left a gated model with no `read`/`bash`/`plan_draft`. The
  builtin-sourced `codemode` row (`suspendedUnderGate`) is now *lifted* in every registry
  `mode: read-only` stage (`READ_ONLY_STAGES`, derived from the registry) when the landing's
  codemode setting is `on`, or `only` with no stranded writer (`GateLanding`, `strandedWriters`).
  Unscoped sessions, a read-write stage's `/plan` toggle, child floors and an unreadable setting
  never lift — there the row is suspended while presenting read-only and restored at release
  (`suspensionStep`; the memo updates only after a successful install). A lift keeps a
  user-enabled codemode or restores one the gate memo'd, and a lifted landing *consumes* the memo
  (the memo-as-window-state recurrence). The one non-perk exception to own-names-only.
- **Pi facts behind the lift (stamped 1.1.0; re-verify at the next bump).** Codemode `only` hides
  direct declared tools, so a direct tool the nested policy refuses is a *stranded writer*;
  `model-only` is Pi's own exposure for "declared, never callable through another tool" and the
  honest exposure for bounded writers (a `deferred` tool cannot also be model-only); two refusal
  oracles fire before the `tool_call` hook (the codemode prelude `TypeError` vs agent-core's
  `Tool <name> not found`); the factory `mode` option shadows the setting and perk cannot see it;
  `DEFAULT_TOOL_NAMES` is read/bash/edit/write and `grep`/`find`/`ls` register inactive.
- **Design lesson (lift).** Compute candidate sets over *registered* names, never the catalog
  (§8.40 exclusion contract); derive per-stage censuses from `shared/fixtures/tool-matrix.json`,
  never from stage names (modeOverStage writers are live in every gated stage — a recurrence).
  Record: `docs/design/archive/pi-1.1.0-codemode-lift.md`.
- **Flip-only reinstall.** When only the presented mode flips, perk still installs the live set
  (gated on the host being active), because Pi rebuilds snippets only at install — this brings
  `edit`/`write` snippets back at gate exit. Skipped when the host is absent, keeping the
  zero-install guarantee for allowlisted children.
- **Fail postures.** Presentation fails open (a hook throw hides only the host); enforcement fails
  closed (the latch `if (nextActive) active = true` before any read; an unregistered name is
  blocked before classification). `presentedMode`/`stageId` are set before the install so the hook
  inside it sees the settled landing; a failed install rolls `presentedMode` back via the
  floor-aware `isActive()`. The typed transition result is in `pi/context-system.md` § Gate
  engagement.
- **The loadout host** (`perk_stage`, `registerLoadoutHost`): a literal-named, model-only tool whose
  only job is `prepareLoadout`. Its return type `LoadoutPresentation` has `descriptions?: never`, so
  no request-time description rewrite can bypass prose governance (see
  `docs/learned/workflow/prose-review-workbench.md`).

## Nested execution under the gate

- **Two arms from one classification.** The gate arm (`isEligible(…, "read-only")`) and the
  nested arm (`nestedPostureFor(postureFor(…))`), which only narrows: a perk tool runs nested only
  as a gate-allowed `query`; builtins keep their gate posture only for `registrar: "core"` (every
  `registrar: "extension"` row — `tool_search`, `codemode` — is blocked nested); foreign tools keep
  their `POSTURE_ROWS` posture; unknown is blocked. No name, annotation or `readOnlyHint` grants a
  nested call.
- **The layered refusal order** — gate inactive → edit/write → unregistered → ineligible → nested →
  bash verdict (the `tool_call` handler in `toolGating.ts`; `nestedDenialClass` words the nested
  arm) — decides the wording a user sees.
- **Pi rejects model-only tools first.** Terminal, interactive, orchestration, host perk tools,
  carve-out writers and Pi's own `tool_search` are refused in `prepareToolCall` before any
  `tool_call` event — the backstop arms for them are defense in depth only the fake host reaches.
- **Security limit.** A foreign `delegation` tool admitted under the gate is admitted nested — the
  policy is not a sandbox for its children.
- **Codemode behaviour.** A nested *action* tool called from a codemode script is refused per call
  (the model falls back to direct calls); under `codemode.mode: "only"` the declared set drops the
  direct read tools.
- **Golden-matrix facts.** `tools` rows in `shared/fixtures/tool-matrix.json` carry `nested`; only
  `objective_stack_status` is a perk row with `nested: "allowed"`.
- **Pi facts (stamped 1.1.0).** `parentToolCallId` is set only when present; `NestedToolCallRunner`
  passes the *immediate* caller's id.
- Cross-reference `pi/read-only-bash-gate.md` (the bash verdict the last arm consumes).

## How to add or change a perk tool

- **One call:** `registerPerkTool(pi, definition, policy)` with
  `{ stages, gated: allowed | blocked | { carveOut }, modeOverStage?, kind, declared?, result? }`.
  Never hand-set `exposure`/`annotations`/`defaultActive`/`prepareLoadout`/`outputSchema` —
  `validateToolPolicy` throws (`POLICY_OWNED_FIELDS`).
- **`kind` rules:** can return `terminate: true` ⇒ `terminal`; opens a human surface ⇒
  `interactive`; spawns a wave/child/resolver ⇒ `orchestration`; pure read ⇒ `query`; else
  `action`. A trust/confirm dialog does not make a tool interactive. `terminal`, `interactive`,
  `orchestration` and the `host` kind become model-only (never reachable through
  `ctx.executeTool`), and so does every object-valued `gated: { carveOut }` policy.
- **`gated` is per tool, not per stage.** Admitting a tool under the gate admits it in every
  landing it is staged in. A gate-allowed cold-door tool's side effects are whatever its Python
  path does under hostile git config (the cold door runs via `pi.exec`, outside the bash verdict),
  so read that path before calling a tool read-only (`workflow/git-substrate.md` § A gated fetch).
- **Changing an existing descriptor's `gated`/`stages` flips pins beyond the plan's file list** —
  sweep `toolGating.test.ts`, the primed-activation / `/tree`-restore / census-S1 rows in
  `discoveryPilot.test.ts` (slow tier), `discoveryNested.test.ts`, the golden matrix and the
  docs-site "Under the gate" cell; re-express a flipped pin with a sibling still-blocked member
  rather than deleting it. The census-S1 three-arm rule: ≥ 4096 bytes net; the "wash" band; no
  eligible member ⇒ −fixedCost — with the wash stage pinned by value.
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

## Native discovery and priming (Law 4 corollary; verified 1.4.0)

- **Deferral at registration.** The discovery family registers `exposure: "deferred"` from the
  start (`derivePiMetadata` defaults a `declared: deferred` member to deferred; `declareDirect` is
  the opt-in). A cohort host keeps that registration with zero installs; a nonparticipant
  re-registers the family direct at `session_start` (`declareDiscoveryFamily`) and Pi activates it
  like a new tool. "Deferred" is read from the registry (`readRegistry`), never memoed;
  `joinDiscoveryCohort` only records membership for `/perk-selfcheck`, which reports
  `nonparticipant (still deferred: …)` on a failed flip. A failed flip leaves a member deferred
  (primable/searchable), not always-declared.
- **Restore survival.** A primed or searched member survives `/reload` and comes back on
  resume/fork once a request recorded it (Pi's own restore — see "Pi host facts").
- **The registry is what each item became.** After a per-item best-effort transform, key
  downstream state on what each item became — read it back from the registry rather than keeping
  a parallel flag (a session-wide flag caused the pilot's one real bug).
- **Design lesson — use the host primitive instead of scaffolding around a fight with it.** The
  register-direct / re-register-deferred / deactivate-once design was the root of every measured
  defect; registering deferred from the start deleted machinery (the family deferral and its
  `pendingDeferral` memo are gone). Corollary: when a deferred effect needs memos, ask whether the
  effect is necessary before enumerating window interleavings.
- **Prime before the carrier lands.** A carrier naming a `declared: deferred` tool primes it via
  an exported `*_PRIMES` constant (`DRAFT_REVIEW_DOOR_PRIMES`, `DRAFT_LAUNCH_PRIMES`,
  `REVIEW_BROWSER_PRIMES`, `REVIEW_TERMINAL_PRIMES`, `REVIEW_LAUNCH_PRIMES`, `STACK_STATUS_PRIMES`)
  passed to `gating.primeDeferred` — doors at their surface-prime moment, wave launchers on their
  success arm. Priming is fail-open presentation.
- **Guards.** `DRIVE_COVERAGE.primes` is two-way (every named deferred tool primed; every prime a
  named deferred tool). A carrier census forbids any catalogued tool's description/guidelines
  naming another tool's deferred member except the two launchers — reword, don't widen. The Python
  rule covers cold seeds, common fragments and stage-bound skills.
- **The headless worker** joins the cohort and has no doors, so its deferred members return only
  via `tool_search` or launcher priming.
- **Measured savings:** ≈5.5 KB (worktree stages), 4.8 KB (plan/objective), 4.8 KB (stack-review)
  per request vs a 693 B fixed cost; snippets + guidelines were 58 % of the family's bytes. Record:
  `docs/design/archive/native-discovery-pilot-dogfood.md`; `docs/design/native-discovery-pilot.md`
  describes the retired mechanism as measured (historical; §8.40 is current). Law 4 itself:
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
- **Late-bound failure injection through public methods** (`extension/testing/harness.ts`):
  `failToolInstall` replaces `setActiveToolsByName`; `failModeAppend`/`failEntryAppend` replace
  `appendCustomEntry`, and `when: "after"` reproduces Pi's non-transactional append;
  `fakeGating(active, {enter, exit})` stubs the gate. After a signature change sweep
  `extension/testing/*.ts` (not only `*.test.ts`) for inline fakes.
- **`h.toolInfo()` for annotations** — the `registeredTool()` projection omits them.
- **Discriminate host behaviour from perk filtering** — resume/fork from a leaf where perk would
  keep the tool. Check fail-open/closed immediately after the failing call (before a reconciling
  hook repairs it) and mutation-check the rollback.
- **Registration activation confounds restore detection** — record the tool as REMOVED, resume,
  then check registered-yet-inactive at the first install.
- **Nested execution.** A fabricated `parentToolCallId` is fine in the fake-host unit test; real
  `ctx.executeTool` drives (`discoveryNested.test.ts`, `ownNamesActivation.test.ts`) prove the
  path. Pin every nested denial next to its admitted direct twin. Register `structured_output`
  through the named `pi-subagents:prompt-runtime` factory.
- **Window guarantees live in the fake host.** A prompted live probe can never observe
  enforcement inside the window (`agent_start` closes it before any tool runs).
- **Catalog vs production pins.** `toolPolicy.test.ts` runs on a synthetic `tt_*` catalog;
  production-name pins belong in `toolMatrix.test.ts`. `apply` stores the raw `stageId` and
  `isEligible` normalizes it — pin a `bogus` stage row.
- **Codemode scripts.** Load codemode like the CLI (no factory `mode`; drive via
  `settings.codemode.mode`), one try/catch per nested call returning one JSON record, census every
  `tool_call` by the codemode call's `parentToolCallId`; QuickJS loads ≈1 s per session (a
  slow-tier signal).
- **Request-prefix hashes.** The system prompt embeds `cwd` and no date, so hashes reproduce only
  over a byte-identical deterministic root (wipe `tmpdir()/<fixed>` at start; prove determinism
  with two baseline runs).
- **A recording fake proves wiring, not outcome** — the draft-review door's prime needed a real
  cohort session. `h.emitSessionStart()` proves idempotence; `h.reload()` proves reload semantics.
  Don't mock Pi's private internals or attribute installs from stack traces in new tests.
- **Characterize with matched controls** before alleging a regression: a CONTROL session without
  perk; Pi-deactivating and Pi-additive controls for gesture rows; a classification table fixed
  before measuring; a throwaway detached worktree pinned to the subject version.
- Files: `extension/substrate/ownNamesActivation.test.ts`, `restorationWindow.test.ts`,
  `restoredDiscovery.test.ts`, `discoveryPilot.test.ts`, `discoveryNested.test.ts`,
  `stageTools.test.ts`, `toolMatrix.test.ts`.

## Residual risks

- The gate-eligible query set is exactly `objective_stack_status` (CONTEXT.md "Gate-eligible
  query").
- Read-write sessions still have no call-time backstop — a nested call reaches inactive deferred
  members; unknown-provenance tools pass read-write diets.
- A cohort-deferred direct tool is still callable from codemode's `ALL_TOOLS`.
- Discovery nonparticipants keep `only` suspended in every gated stage; the stranded-writer rule
  depends on a truthful registry-read deferred set.
- `perkToolsFor(stage, mode, cohort)` still carries the "cohort excludes the whole family" boolean
  with no production caller (routed code follow-up).
- A foreign deactivating install inside the window (a supplier's `setSelection`) still clears Pi's
  pending set and drops late MCP tools on resume.
- Restore detection depends on Pi's projection shape (a checkpoint-less compaction reads no
  restore and the removals land at once).
- Snippet order follows active-set order, so a primed member sits last while a restored one sits in
  registry order — prefix-cache work across resume is an ordering problem, not a deferral problem.
- A `tool_search` hit is switched off at the next prompt start, which since 1.4.0 includes
  subagent wake turns (unmeasured; re-verify at certification). Broad `tool_search` queries
  over-activate.
- Presentation-only leaks: codemode's description can list diet-hidden or gate-blocked tools.
- The `@tombell/pi-plan` `/plan` restriction (`setActiveTools`) is undone by policy-owned
  activation while contracts §8.10 still describes it as hiding `plan_draft`/`plan_review` (owner
  decision owed; routed follow-up).

## Sources

- Pi dist read: `core/agent-session`, `core/system-prompt`, `core/extensions/{runner,loader}`,
  `core/tools`, the MCP builtin (`extensions/mcp`), `core/settings-manager`. Host facts, the
  restoration window and deferred discovery at `1.4.0`; codemode and nested facts at `1.1.0`;
  own-names activation and `defaultTools` at `0.99.2`. Every 1.4.0 fact decays at the next pin
  bump (`PI_ADOPTED_VERSION`); `restoredDiscovery.test.ts` is the behavioural pin.
- **Offline MCP fixture.** `@earendil-works/pi-mcp/testing` is hoisted top-level at ≥ 1.0.1 (no
  nested copy under pi-coding-agent). The proven shape is
  `createMcpExtension({loadConfig, createTransport, logPath})` loaded as
  `{name: "mcp", factory, builtin: true}` with `PI_CODING_AGENT_DIR` scratch; registration is
  asynchronous — poll with a bounded `until`; MCP's default `codemode` exposure registers as tool
  exposure `deferred`; count `tools/call` on the responder as the escape oracle.
- Records: `docs/design/archive/pi-1.4.0-restored-discovery.md`,
  `docs/design/archive/pi-1.1.0-codemode-lift.md`,
  `docs/design/archive/pi-1.1.0-collection-and-mcp-floor.md`,
  `docs/design/archive/pi-1.0.0-mcp-restoration.md`,
  `docs/design/archive/native-discovery-pilot-dogfood.md`.

## Cross-references

- `shared/contracts.md` §8.40 — the normative loadout contract
- `docs/learned/workflow/warm-door-commands.md` — Law 1 (gated tools) and Law 4 (guidance-named tools)
- `docs/learned/pi/read-only-bash-gate.md` — the bash verdict the gate consumes
- `docs/learned/pi/context-system.md` — the gate-engagement latch lesson and `GateTransition`
- `docs/learned/workflow/borrowed-packages.md` — borrowed engines and their package rows
- `docs/learned/workflow/init-doctor.md` — the `defaultTools` seed convergence
- `docs/learned/pi/extension-api.md` — the structured-result contract, the custom start, harness facts
- `docs/learned/pi/subagents.md` — the child-engine row and allowlisted report children
- `docs/user-docs/reference/in-session/model-tools.md` — the user-facing posture table
