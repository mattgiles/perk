# Dogfood record: ts-decomposition Phase 1 gate (config / gating / provider selection)

**Status:** validation record (the `*-dogfood.md` archive genre) for the objective's Phase-1
close: *a normal perk workflow with default and locally-overridden configuration — config, tool
gating, and provider selection behave as before* — after the config↔bindings cycle break
(`bindings.ts` no longer imports config vocabulary) and the first import-direction guards.

Executed **2026-08-24** in the implementation worktree, against the branch under test:

- **Worktree:** `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2091`
- **Tested commit:** `28e8cacd6aeeab6e8d5233c8ecb8934e12a8c6e3` (the cycle break + guards +
  phase-spec reconciliation all committed; the evidence-record commit follows it)
- **Session shapes:** each arm ran TWO fresh sessions in that worktree — one **headless SDK
  probe** (the `defaultCreateRuntime` mirror from `docs/learned/pi/headless-session-drive.md`:
  disk-layered `SettingsManager.create(worktree, throwawayAgentDir)`, `ModelRuntime.create()`,
  `bindExtensions({ mode: "json" })` ⇒ `ctx.hasUI === false`, launched with
  `env -u PERK_RUN_ID -u PI_SESSION_FILE`; model SDK-resolved to `anthropic/claude-opus-4-8`;
  warm `/plan` dispatched via `session.prompt("/plan")` — pi print/SDK prompt handles
  `/`-commands before any provider call) plus one **interactive `pi` launch by the human**
  (`cd .worktrees/plan-2091 && pi`) for the TUI-only footer-render observable. Fresh sessions
  per arm — the footer provider installs at `session_start`, so restarts between arms were
  mandatory, and each probe/launch was a new process.
- **cwd confirmation:** each probe logged
  `probe cwd: /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2091` (the self-repo
  loads the perk extension from the invoking checkout via the worktree's `.pi/settings.json`
  `".."` package entry, so every session ran this branch's extension).

**Honesty framing (the headless/interactive split):** the plan's recipe prescribes interactive
sessions for both arms. The automatable observables (the `perk:plan-context` injection bytes,
the overlay read, tool gating, provider *resolution*) were captured by the headless probes —
which bind the identical extension from the identical checkout through the identical
`session_start` path; the one `hasUI`-gated observable (the footer actually *rendering* /
vacating, `extension/index.ts`'s `ctx.hasUI && isPerkFooterReferenceSelected(ctx.cwd)` install
site) was observed by the human in the three interactive launches recorded below. No arm was
skipped; no observation is inferred-only.

## Preflight (step 0)

The worktree's `.perk/local.toml` was **absent** before the gate (fresh worktree — verified
`ls .perk/local.toml` → no such file), so there were no local bytes to snapshot; cleanup =
delete the override file written for arm 2. The main checkout's `.perk/local.toml` was never
touched, read, or written.

## Arm 1 — default (no worktree `local.toml`)

Headless probe (fresh session, `local.toml present: false` logged):

- **Config — the `perk:plan-context` injection reflects committed config only.** After warm
  `/plan` (stderr: `perk: plan-mode — plan mode ON — read-only exploration; …`) and one real
  agent turn, the branch carried exactly one `perk:plan-context` custom message: **1688 chars**,
  first line `[PLAN AUTHORING]`, **no** local addendum (`carries DOGFOOD-1.2 local override
  marker: false`), ending `…the human runs /plan-save (the manual failsafe).` — the committed
  config has no `[workflow] plan_authoring`, so the injection is the bare
  `PLAN_AUTHORING_CONTEXT`. The gate's `perk:mode-context` (read-only context) was also present.
- **Tool gating — plan mode blocks edit/write and restricts bash.** The model's own
  enumeration of its callable tools (one real turn — the model-visible set, not the registered
  census) contained `read, grep, find, ls, bash` plus the plan-family tools and **no `edit`, no
  `write`** (the `setActiveTools` allowlist observed live). The structural bash sub-allowlist was
  then exercised: the model called `bash` with `touch .perk-dogfood-blocked-probe` and the gate
  blocked it before execution — tool result verbatim:

  ```text
  perk read-only mode: command blocked (not allowlisted).
  Command: touch .perk-dogfood-blocked-probe
  ```

  `blocked file created: false` (the file never appeared).
- **Provider selection.** Resolved live in-process against the worktree config via the same
  helpers the install/registration sites call:
  `resolved [providers] footer: perk-footer`, `resolved [providers] plan: plannotator-plan`
  (the committed `[providers]` table). Warm `/plan` being perk's command while the session runs
  under the plannotator selection is the augment posture behaving as before.
- **Footer render (human, interactive launch 1, 2026-08-24):** perk's own footer rendered at
  the bottom of the session — **"Perk footer rendered (as expected)"**.

## Arm 2 — override (worktree `.perk/local.toml` written)

The override file written for this arm:

```toml
[workflow]
plan_authoring = "DOGFOOD-1.2 local override marker"

[providers]
footer = "pi-default"
```

Headless probe (NEW fresh session, `local.toml present: true` logged):

- **Overlay read, local wins.** The `perk:plan-context` injection grew to **1723 chars** and
  now **ends with the marker** — last bytes:
  `…the human runs /plan-save (the manual failsafe).\n\nDOGFOOD-1.2 local override marker`
  (`carries DOGFOOD-1.2 local override marker: true`). 1723 = 1688 + `"\n\n"` + the 33-char
  marker — the addendum appended exactly as `planContextContent` specifies.
- **Provider selection honors the overlay.** `resolved [providers] footer: pi-default` (the
  local override), `resolved [providers] plan: plannotator-plan` (unchanged — the overlay only
  set `footer`).
- **Tool gating unchanged.** Identical model-visible tool set (no `edit`/`write`), identical
  verbatim bash block on `touch .perk-dogfood-blocked-probe`, `blocked file created: false`.
- **Footer render (human, interactive launch 2, 2026-08-24):** pi's stock footer rendered —
  perk vacated its footer under the override — **"Stock pi footer rendered (as expected)"**.

## Cleanup (step 3) + revert confirmation

The override `.perk/local.toml` was **deleted** (restoring the preflight state: absent). An
offline revert check (no model turn — the same live-imported helpers) confirmed:
`local.toml present: false`, `resolved [providers] footer: perk-footer`,
`plan-context length: 1688`, `carries override marker: false`. The human launched once more
briefly (interactive launch 3, 2026-08-24): **"Perk footer rendered again (as expected)"**.

## Skipped arms

None. (The footer-render halves were executed interactively by the human rather than headlessly —
recorded above — because the footer install site is `hasUI`-gated; that is a session-shape split
within each arm, not a skipped arm.)

## Defect log

Empty — every observation matched the expected behavior; no product defects surfaced.

## Claim → evidence checklist

| Claim (the node's gate enumeration) | Evidence |
|---|---|
| Default arm: injection reflects committed config only | Arm 1: 1688-char `perk:plan-context`, no addendum marker |
| Default arm: plan mode blocks edit/write, restricts bash | Arm 1: model-visible tool set without `edit`/`write`; verbatim gate block on `touch`; file never created |
| Default arm: perk footer renders (`footer = "perk-footer"`) | Arm 1: resolution logged live + human-observed perk footer (launch 1) |
| Plan-provider resolution noted (`plan = "plannotator-plan"`) | Both arms: `resolved [providers] plan: plannotator-plan`; warm `/plan` live under the augment posture |
| Override arm: marker appears in the injected plan-authoring context | Arm 2: 1723-char injection ending with `DOGFOOD-1.2 local override marker` |
| Override arm: footer vacates to pi's stock footer | Arm 2: `resolved [providers] footer: pi-default` + human-observed stock footer (launch 2) |
| Override arm: tool gating unchanged | Arm 2: identical tool set + identical verbatim block |
| Cleanup + revert | `local.toml` deleted; offline revert check (1688 chars, `perk-footer`) + human-observed perk footer (launch 3) |
