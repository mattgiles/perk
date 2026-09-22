# Re-verify: pi-subagents 0.70.1 — the host-builtin intersection gone, `completionGuard` removed, the fork-context repair unshipped

**Status:** dated evidence record (2026-09-22) — the guidance-baseline re-verify that moved
`_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` from `0.68.0` to `0.70.1`, retired perk's `PI_FFF_MODE`
launch injection and the `subagent-host-tools` doctor check, and dropped `completionGuard` from
every perk report definition. The template is
[`pi-subagents-0.68.0-reverify.md`](pi-subagents-0.68.0-reverify.md); the procedure is
`docs/developers/pi-subagents-reverify.md`.

## The matrix

| Component | Version | Provenance |
|---|---|---|
| perk | 3.5.0 @ branch `plan-2483` (this change, pre-merge) | the implementation this record trails |
| Pi (pinned dev toolchain + host) | `@earendil-works/pi-coding-agent` 0.87.0 | `package.json` devDependencies (moved from 0.85.1 in the same change); the host `pi --version` = 0.87.0 |
| pi-subagents (installed, unpinned) | 0.70.1 (npm latest) | `.pi/npm/node_modules/pi-subagents` — the package now ships **compiled JavaScript** (`pi.extensions: ["./index.js"]`, `src/**/*.js` + `.d.ts` + source maps; 282 modules), so every anchor below is a `src/**/*.js` path read in place — the how-to's compiled-JS arm |
| pi-fff (installed) | 0.11.0 | `.pi/npm/node_modules/@ff-labs/pi-fff` — its own default `tools-and-ui`; precedence CLI flag → `PI_FFF_MODE` → `pi-fff.json` → default |
| Plannotator (installed) | 0.27.17 | `.pi/npm/node_modules/@plannotator/pi-extension` |
| Previous baseline | 0.68.0 (last source re-read 0.68.0) | `docs/learned/pi/subagents.md` § Sources before this pass |

## Source facts (file/function anchors, verified in the installed compiled 0.70.1)

- **Parent-side `progress_update` still discarded** — `src/intercom/native-supervisor-channel.js`:
  the child sets `expectsReply = params.reason !== "progress_update"` and returns
  `"Supervisor progress update queued."` without waiting; on the parent side `requestLifecycle`
  only ever resolves/expires/inactivates a request `if (request.expectsReply && …)`, so a
  progress request has no reply lifecycle and no parent turn. Unchanged from 0.68.0 — every perk
  wave keeps `intercomBridge: {mode: "off"}` (`WAVE_INTERCOM_BRIDGE`).
- **Per-launch bridge override still spreads onto workflow children** —
  `src/runs/foreground/subagent-executor.js`: `resolveIntercomBridge({config:
  input.deps.config.intercomBridge, override: input.params.intercomBridge ?? recoveryDescriptor?.intercomBridge, …})`
  at the spawn site, and for every workflow child `const intercomBridge =
  childParams.intercomBridge ?? workflowDefaults.intercomBridge` (line ~4155);
  `src/intercom/intercom-bridge.js::resolveIntercomBridge` resolves the override before the
  config and returns `active: false` for `mode: "off"`. The RPC `SubagentParams` schema
  (`src/extension/schemas.js`) keeps `additionalProperties: true`;
  `normalizePublicSubagentExecution` (`src/extension/public-execution.js`) strips only the
  resource/permit fields.
- **Wake rules unchanged** — `src/runs/background/notify.js::incrementalChildCompletionTriggersTurn`:
  `if (child.workflowRunning && child.outcome === "completed") return false;` — a routine
  successful child completion does not wake the parent; failed/paused/stopped children and the
  workflow completion do (`scheduledCompletionTriggersTurn`).
- **v1 RPC envelope unchanged** — `src/extension/rpc.js`: `subagents:rpc:v1:request` /
  `subagents:rpc:v1:ready` / `subagents:rpc:v1:reply:` prefix.
- **Structured output** — `src/runs/shared/child-tool-plan.js`: `internalTools =
  (input.structuredOutput ? ["structured_output"] : [])` — the injected report call perk's
  `SUBAGENT_CHILD_TOOLS = ["structured_output"]` relies on.
- **Agent-definition parser** — `src/agents/agents.js` (~line 1860): the ONE removed-field throw
  is still `fallbackModels` (`uses removed frontmatter field 'fallbackModels'`). `completionGuard`
  appears NOWHERE in the artifact (`grep -rn completionGuard src/ index.js docs/` → 0) — the field
  is **ignored, not rejected**, so a def carrying it loads fine; perk dropped it anyway because it
  presents a policy the engine no longer reads.
- **Package agent discovery unchanged** — `src/agents/agents.js`:
  `collectPackageSubagentPaths` gathers `<project>/.pi/npm/node_modules` and
  `<agentDir>/npm/node_modules`; `extractSubagentPathsFromPackageRoot` reads the top-level
  `package.json` `"pi-subagents"` record; `src/agents/agent-selection.js::mergeAgentsForScope`
  sets `builtin` → `package` → `user` → `project` into one name-keyed map (later wins, so a
  same-named project def SHADOWS a package def). `skillPath` still resolves against
  `path.dirname(agent.filePath)` (`src/runs/foreground/execution.js` → `resolveSkillsWithFallback(…,
  agent.skillPath, agent.filePath ? path.dirname(agent.filePath) : skillCwd)`; same in
  `src/api/preflight.js`), and `src/agents/skills.js::collectFilesystemSkills` skips a missing
  entry (`if (!fs.existsSync(resolvedFile)) return;`) — the reviewer defs' two-candidate Ponytail
  `skillPath` keeps working.
- **The host-builtin intersection is gone (0.70.0)** — `src/runs/shared/child-tool-plan.js` has
  no `getHostBuiltinToolNames` / `PI_BUILTIN_TOOL_NAMES` (`grep -rn` over `src/` → 0); children
  use the tools their own agent configuration declares (the 0.70.0 CHANGELOG "Let children use
  the tools declared by their own agent configuration instead of incorrectly narrowing them to
  the parent's `--tools` selection"). pi-fff's mode is therefore irrelevant to a report lane's
  tool plan — the 0.67.x hazard `subagent-host-tools` guarded is unreachable.
- **The completion contract (0.70.1)** — CHANGELOG: "Stop guessing whether task wording requires
  file edits. Successful tasks now follow their process result and explicitly configured output
  and acceptance checks. The `completionGuard` setting and `PI_SUBAGENTS_LLM_INTENT_ARBITER`
  switch have been removed." `src/runs/shared/acceptance.js::inferLevel` infers `checked` for a
  declared `acceptanceRole: "writer"`, `none` for `"read-only"`, else `attested` — perk's waves
  bypass inference with the explicit `WAVE_ACCEPTANCE = {level: "none"}` workflow default, and a
  report lane completes on its validated `structured_output` report.
- **The Pi 0.87 fork-context repair is NOT in the artifact** — `grep -rln
  'context_edit|buildSessionProjection|contextEdit' src/` → 0; `src/shared/pruned-fork.js` still
  reads raw `compaction`/`branch_summary` entries with no context-edit handling (the checkout's
  `a10ba079` is two commits past the 0.70.1 tag — `docs/planning/pi-subagents-assessment-2026-09-21.md`).
  perk's waves (`extension/waves/transport.ts`) and the conflict resolver
  (`extension/pi/v1/delivery/conflictResolverEngine.ts`) spawn with `context: "fresh"`; fork
  context stays unsupported for perk children (`docs/design/pi-subagents-child-execution-policy.md`
  § Not claimed).
- **Foreground child SDK resolution (0.70.1)** — the package resolves the host `pi-coding-agent`
  from the Pi installation that owns the session (CHANGELOG #2348) — relevant to the
  `.worktrees/*` layouts perk runs in; no perk-side change.

## Decisions

- **`PI_FFF_MODE` launch injection retired** (`src/perk/run/launch/__init__.py`,
  `src/perk/run/run_worker.py`): perk injects nothing; pi-fff runs under its own precedence. An
  operator's `pi-fff.json` `override` now wins in perk-launched sessions — their own configuration
  — and cannot affect report lanes on ≥ 0.70.0.
- **`subagent-host-tools` doctor check retired** (`src/perk/convergence/doctor/checks.py`,
  `doctor/__init__.py`): the range it guarded (`0.67.0 ≤ v < 0.68.0`) is history and the hazard is
  structurally gone; `subagent-package-scope` now follows `subagent-compat` directly. A future
  release reintroducing a host-side intersection is a NEW hazard to name.
- **`completionGuard: false` dropped** from the ten shipped report defs and the repo-local
  `perk-dev.session-auditor`; the tests assert absence; the completion contract is the validated
  `structured_output` report + perk's restriction floor + the rubric.
- **Fork context recorded as a support boundary**, not certified: perk children stay
  `context: "fresh"` until a release containing the repair is installed and re-verified.
- **Minimum host versions documented, not gated** (owner decision): Pi ≥ 0.87.0, pi-subagents
  0.70.1 as the verified baseline, Plannotator ≥ 0.27.16 for the stack browser
  (`docs/user-docs/reference/requirements-and-compatibility.md`).

## The live leg

Run from the implement session in this worktree (a read-write session on the 0.87.0 host with
the worktree-local `.pi/npm` at pi-subagents 0.70.1), after sections E/F landed.

**Doctor half — PASS.** `uv run perk doctor --verbose` (package group, before the stamp moved):

```
⚠ subagent-compat: pi-subagents 0.70.1 installed — perk's guidance was verified against 0.68.0 — the package is unpinned; …
✓ subagent-package-scope: pi-subagents configured in project scope only — report-only — the user-scope file is operator-owned
✓ ponytail-compat: Ponytail review skills compatible — exact package identity, ./skills advertisement, and both source-bound skills verified
```

No `subagent-host-tools` row (retired). After the stamp moved:
`✓ subagent-compat: pi-subagents 0.70.1 — the guidance-verified version — report-only — the package stays unpinned`.

**Scout lane — PASS.** One `perk.scout` lane (a foreground spawn from this session on 0.70.1)
was tasked to use ONLY `grep` and `find`: it listed the eleven `agents/*.md` defs with `find`,
found 0 `completionGuard` matches with `grep`, read the three
`_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` lines in `checks.py`, and reported "Invoked: `find`,
`grep`. Refused, blocked, or unavailable calls: none." — and completed on its report without
editing any file (the 0.70.1 completion contract). **Caveat:** this session was launched by the
pre-change perk, so its environment still carried `PI_FFF_MODE=tools-and-ui`; the lane proves
`grep`/`find` on 0.70.1 but not the "no `PI_FFF_MODE` set" half — that half rests on the source
fact that the host-builtin intersection is gone (pi-fff's mode cannot reach a child's tool plan)
and is owed from a session launched by the post-change perk (Step 14's live gates).

**Conflict delegation — offline engine test.** No conflict was at hand;
`extension/pi/v1/delivery/conflictResolverEngine.test.ts` (18 cases: the `context: "fresh"`
spawn shape, the structured result decode, the bounded attempts) passes on the 0.87.0 dist.

**Browser-door half — OWED (not exercised in this pass).** The `/plan-review-browser` and
`/pr-review-browser` waves are `hasUI`-gated human-in-the-loop doors (the plannotator decision is
the human's), so the implementing agent could not drive them. The owner elected (as for 0.68.0)
to move the stamp on the source re-read + the doctor/scout/offline halves rather than block
submission; the completion-only wave mechanics — every spawn's `intercomBridge` and `acceptance`
in the adapter-contract / fake-RPC suites, the `perk:wave` marker at launch and collect, the def ↔
schema lockstep, the door-prompt pins — are pinned offline and green. **Residual:** the first live
0.70.1 browser waves — the marker visible at launch, cleared at collect, N/N final annotations
after `collect_*`, with defs lacking `completionGuard` — are owed from the owner's
`/pr-review-browser` run on this change's PR; append the outcome here. A FAIL there is a new
re-verify pass, not a stamp rollback by itself.

## Falsified planning-time assumptions

- The reverify how-to's step 2 said the package "ships its TypeScript sources … if a future
  release publishes compiled JS instead, read the matching tag". 0.70.1 IS that release
  (CHANGELOG 0.70.0: "Prevent publishing the TypeScript source checkout directly to npm; only the
  compiled package is publishable") — but the compiled `src/**/*.js` carries the same
  module/function anchors, so reading in place still works; the how-to now says so.
- `completionGuard` was expected to be a removed-field throw candidate; it is silently ignored.
