---
title: Pi context system — no transclusion, ambient index split, the scan-timeout guard, gate engagement
read_when: You are surfacing info to a session (the ambient index), debugging a timed-out bash scan, touching the scan-timeout guard or the gate engagement latch, or a worktree session's AGENTS.md load.
cluster: pi-extension
---

# Pi context system

## Distillation

- Pi context files load verbatim — no `@`-transclusion; the ambient index is a two-layer split
  (compressed routing in `.pi/APPEND_SYSTEM.md`, the full catalog on demand) — "No in-file
  `@`-transclusion", "Ambient index must be a real two-layer split".
- Pi suppresses the main checkout's `AGENTS.md` for a nested linked worktree (one load, not two);
  the rule keys on a same-basename context file under the main root and does not cover sibling
  worktrees, bare layouts, submodules, or the `.pi/` prompt kinds — "Which AGENTS.md a
  linked-worktree session loads".
- The read-only bash gate (walker, veto view, row craft, bypass checklist) lives in
  `pi/read-only-bash-gate.md` — "The read-only bash gate lives in its own doc".
- The second always-on `tool_call` hook injects `timeout = 30` onto gitignore-blind scans and
  fails OPEN (a performance guard, the opposite of the gate); pure policy under `substrate/`, Pi
  glue under `pi/v1/`; match rules loose, exemption rules tight — "The bash scan-timeout guard".
- Latch the fail-closed gate state BEFORE any new fallible read in `apply()`; transitions return a
  typed `GateTransition` and never throw; a latch ahead of a fallible persist creates a "latched
  but not persisted" state every flag reader must handle — "Gate engagement: latch the
  fail-closed state BEFORE any new fallible read".

## No in-file `@`-transclusion

Pi context files load **verbatim** — `AGENTS.md` plus the `SYSTEM.md` (replaces the system prompt)
/ `APPEND_SYSTEM.md` (appends to it) kinds Pi's resource loader reads from a project `.pi/` dir or
the global `~/.pi/agent/` — this repo carries only the append kind, `.pi/APPEND_SYSTEM.md` (the
live ambient carrier). `@file` is only a CLI message-arg prefix, not interpreted inside context
files. Consequence: you cannot `@`-reference a catalog from `.pi/APPEND_SYSTEM.md`; the reference
would appear as literal text.

## Ambient index must be a real two-layer split

Because transclusion doesn't work, an "ambient index" of durable learnings requires a genuine split:

1. **Compressed routing index** — inline in `.pi/APPEND_SYSTEM.md`, appended to every session's
   system prompt. Project-scoped, committed, NOT gitignored, NOT `init`-managed (maintained only by
   `/learn-docs` plans). One terse routing line per cluster (rollup cue + member doc slugs) —
   keeps the system-prompt append small.
2. **Full on-demand catalog** — `docs/learned/index.md`, read by the model when the routing cue
   matches. Lists every doc with its category, cluster, and full per-doc `read_when` cue.

Don't try to compress the full catalog into the ambient context. The two-layer split is the right
architecture.

## Which AGENTS.md a linked-worktree session loads

**Current rule** (verified at the 1.4.0 pin, `dist/core/resource-loader.js::findShadowedContextFile`
/ `loadProjectContextFiles`). Pi's ancestor walk skips the main checkout's context file when all
three hold:

1. the cwd's worktree root sits **under** the main repo root — exactly perk's `.worktrees/<name>`
   layout from `[worktree] root`;
2. the main root's `.git` is the common git dir — so not a bare `proj/.bare` layout and not a
   submodule;
3. the worktree carries its own context file of the **same basename** — the loader compares the
   canonicalized directory + basename, so a worktree `AGENTS.md` symlinked to main's still counts
   as the worktree's own.

Ancestor inheritance is otherwise unchanged. Residuals worth knowing: a worktree whose only context
file has a different basename (e.g. `CLAUDE.md` vs main's `AGENTS.md`) is not shadowed and both
load; a sibling worktree never double-loaded in the first place (main is not an ancestor). The
`SYSTEM.md` / `APPEND_SYSTEM.md` prompt kinds are discovered separately in the cwd's `.pi/` dir
(project-trust gated, global fallback) and are not part of the ancestor/shadow walk,
so a worktree session's ambient carrier is the worktree's own `.pi/APPEND_SYSTEM.md`.

**Dated history.** At pi 0.80.3 the walk loaded **both** the main-checkout and worktree
`AGENTS.md` — two identical 6,628-char files in every worktree session, measured by the
`/perk-selfcheck` payload census (`docs/design/archive/context-payload-baseline.md`). By pi 0.84.1
the double-load was gone (`docs/design/archive/context-payload-baseline-2.md` records `files=1`).
The payload diet that ran alongside it (the ambient-tier diet plus the `AGENTS.md` "Developing
perk" sweep, compressed in place) stays as recorded there.

**Re-check at a pin bump** with the selfcheck census line `agents=… (files=N)`
(`extension/pi/v1/selfcheck.ts`) — `files=1` inside a `.worktrees/` session is the expected
reading.

## The read-only bash gate lives in its own doc

The read-only gate is an allowlist at **every command position** AND a not-destructive check over a
lexer-built **veto view**; destructive wins. The inventory is `SAFE_PATTERNS`
(`extension/substrate/readOnlyBash.ts`) — never mirrored into prose. Everything about extending or
reviewing it — the command-position walker, the veto view, allowlist/veto row craft, the
bypass-class checklist, the lockstep list — is `docs/learned/pi/read-only-bash-gate.md`. Plan
factories still prefer the materialized inbox over ad-hoc `gh` queries
(`docs/learned/workflow/plan-factories.md`).

## The bash scan-timeout guard (the second always-on `tool_call` hook)

Recursive `grep -r…` and `find` without `-maxdepth` are gitignore-blind: from a checkout carrying
`node_modules/`, `.venv/`, `.worktrees/` they walk everything and were observed running for minutes
to the better part of an hour with no `timeout` on the call. The guard (contracts §8.69) is two
modules following the reusable convention **Pi-event glue under `extension/pi/v1/`, pure logic under
`extension/substrate/`**:

- `extension/substrate/bashScanTimeout.ts` — `SCAN_TIMEOUT_SECONDS` (= 30, the ONE source of the
  number), `classifyScanCommand` (→ `recursive-grep` | `unbounded-find` | `null`),
  `expiredAfterSeconds` (matches only Pi's **terminal** `Command timed out after N seconds` status
  line, never a line the command printed), `scanTimeoutNote`.
- `extension/pi/v1/bashScanTimeout.ts::registerBashScanTimeout` — the `tool_call` hook injects
  `timeout = 30` onto a classified scan that carries no explicit `timeout` (an explicit value of ANY
  size is the model's override, never rewritten or capped); the `tool_result` hook appends a steer
  note when the terminal status appears.

Facts worth carrying:

- **Fail-OPEN.** A throwing `tool_call` handler would escape Pi's dispatch and abort the call, so the
  hook catches, reports, and lets the call proceed unmodified — correct for a *performance* guard and
  the exact opposite of the read-only gate's fail-closed posture. Decide which a new hook is before
  writing its catch.
- **One lexer for both hooks.** The classifier's splitter is
  `commandPositions.ts::splitTopLevelSegments` — lexing only, always covering the whole input (a gate
  refusal never truncates it), so a flag in a later pipeline stage (`grep -n foo f | sort -r`) is
  never attributed to the grep. The gate itself no longer consumes segments (it reads `commands`);
  only the classifier does. Every heredoc body is its own segment. With no physical-line pre-split,
  the classifier's `INNER_OPERATOR` includes `\n`, so a quoted-in newline cuts the `-maxdepth`
  exemption window, and `blankQuoted` is escape-aware.
- **In an over-match-tolerant classifier, match rules may be loose but exemption rules must be
  tight.** A grep's recursion flag is searched over its full tail (an over-match costs a harmless 30 s
  cap on a fast command — the accepted over-matches are pinned as such in the tests); a find's
  `-maxdepth` exemption is searched only inside that find's **own** quote-blanked window, cut at the
  next command word or a quoted-in sequencing operator — because a wider exemption search could only
  wrongly *remove* a cap from an unbounded find.
- **The cross-plane pin.** The managed `AGENTS.md` bullet the Python plane renders mirrors the 30 s
  literal verbatim; `tests/test_init_idempotent.py::test_managed_agents_scan_timeout_matches_extension_constant`
  reads the extension source and pins the mirror — lighter than a `shared/` data file for one
  integer, and the right weight for a single constant two planes must agree on.

## Gate engagement: latch the fail-closed state BEFORE any new fallible read

`toolGating.ts::apply()`'s first-engagement path once grew a second fallible read (a since-retired
tool census) placed *before* the trailing `active = nextActive` assignment. A throw there left
`active === false`; the startup `resources_discover` re-apply then re-ran the same path and the
`tool_call` backstop **failed open under read-only** for the whole session. The fix, which survives
in today's `apply()`, is one line at its top: `if (nextActive) active = true` — engage the
in-memory gate before any read or install, released only by the trailing assignment. The current
fail postures (presentation fails open, enforcement fails closed) are in
`docs/learned/pi/tool-loadout.md` § "perk's activation design". Deliberately NOT over-corrected to "set the
desired state first" unconditionally: a failing read-only→read-write sync must keep the gate
closed, so only the engaging direction is latched early. The test lesson: the failure-path fixture
had hard-coded the new read as infallible — every new fallible read inside a fail-closed path needs
its own failure-mode case.

**The typed transition result.** `enter`/`exit`/`syncFromState` never throw; each returns a
`GateTransition` (`extension/substrate/toolPolicy.ts`): `applied | restricted | failed{step:
persist|install}`, carrying the effective access — callers report the effective access, never
their intent (`reportGateTransition` in `extension/pi/v1/gateTransitions.ts`;
`pi/extension-seams.md` § report()-rollout gotchas).

**Latched but not persisted.** `enter` sets the in-memory gate active *before* appending
`mode: read-only`, so a held append leaves the gate on in memory while the branch says read-write.
A "skip if already active" retry then never writes the mode, and `syncFromState` never does either
— so `gateEntryNeeded` (`gateTransitions.ts`) requires active in memory AND the rebuilt branch mode
before a warm door may skip entry. Rule: when adding a fail-closed latch ahead of a fallible
persist, audit every reader of the in-memory flag that assumes persistence — idempotence guards
included. Pi's append is not transactional (`pi/extension-api.md` § `setSessionName` …), so a
`persist` failure never proves the branch lacks the entry. Documented residual: a persist-failed
`enter` that leaves no entry re-opens the gate at the next rebuild point; `/plan` re-enters.
Contracts §8.3 was narrowed accordingly.

## Cross-references

- `extension/substrate/toolGating.ts` — `apply()`'s engagement latch
- `docs/design/archive/context-payload-baseline-2.md` — the `files=1` record (worktree double-load gone)
- `extension/pi/v1/selfcheck.ts` — the context-file census line (`agents=… (files=N)`)
- `extension/substrate/commandPositions.ts` — `splitTopLevelSegments`, the lexer both hooks share
- `docs/learned/pi/read-only-bash-gate.md` — the read-only bash gate (walker, veto view, row craft)
- `extension/substrate/bashScanTimeout.ts` + `extension/pi/v1/bashScanTimeout.ts` — the scan-timeout guard (policy + Pi glue)
- `shared/contracts.md` §8.69 — the bash scan-timeout contract
- `docs/learned/pi/tool-loadout.md` — the gate's fail postures and reconciliation points
- `docs/learned/workflow/plan-factories.md` — inbox-over-gh pattern using this constraint
- `.pi/APPEND_SYSTEM.md` — the live ambient routing index
- `docs/learned/index.md` — the full on-demand catalog
