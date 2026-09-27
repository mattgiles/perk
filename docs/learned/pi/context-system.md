---
title: Pi context system — no transclusion, ambient index split, the scan-timeout guard, gate engagement
read_when: You are surfacing info to a session (the ambient index), debugging a timed-out bash scan, touching the scan-timeout guard or the gate engagement latch, or hit the worktree AGENTS.md double-load.
cluster: pi-extension
---

# Pi context system

## Distillation

- Pi context files load verbatim — no `@`-transclusion; the ambient index is a two-layer split
  (compressed routing in `.pi/APPEND_SYSTEM.md`, the full catalog on demand) — "No in-file
  `@`-transclusion", "Ambient index must be a real two-layer split".
- A linked worktree double-loads `AGENTS.md` (main + worktree) — "Linked-worktree AGENTS.md
  double-load".
- The read-only bash gate (walker, veto view, row craft, bypass checklist) lives in
  `pi/read-only-bash-gate.md` — "The read-only bash gate lives in its own doc".
- The second always-on `tool_call` hook injects `timeout = 30` onto gitignore-blind scans and
  fails OPEN (a performance guard, the opposite of the gate); pure policy under `substrate/`, Pi
  glue under `pi/v1/`; match rules loose, exemption rules tight — "The bash scan-timeout guard".
- Latch the fail-closed gate state BEFORE any new fallible read in `apply()` — a throw after a
  census read left the gate open under read-only — "Gate engagement: latch the fail-closed
  state BEFORE any new fallible read".

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

## Linked-worktree AGENTS.md double-load

pi's context-file discovery walks up from a linked worktree under `.worktrees/` and loads
**both** the main-checkout and worktree `AGENTS.md` — identical content, double-counted (~6.6KB
of redundant payload in every worktree session at measurement time). Discovered by the
`/perk-selfcheck` payload census; the measured record is
`docs/design/archive/context-payload-baseline.md`. The ambient payload itself was dieted (Objective
#1610 Node 3.4 compressed the AGENTS.md "Developing perk" section in place); the structural
double-load is pi discovery behavior and remains.

## The read-only bash gate lives in its own doc

The read-only gate is an allowlist at **every command position** AND a not-destructive check over a
lexer-built **veto view**; destructive wins. The inventory is `SAFE_PATTERNS`
(`extension/substrate/toolGating.ts`) — never mirrored into prose. Everything about extending or
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

`toolGating.ts::apply()`'s first-engagement path grew a second fallible read — the `getAllTools()`
census that feeds late-tool admission (`workflow/borrowed-packages.md`) — placed *before* the
trailing `active = nextActive` assignment. A throw there left `active === false`; the startup
`resources_discover` re-apply then re-ran the same path, re-installed the census, and the
`tool_call` backstop **failed open under read-only** for the whole session. The fix is one line at the
top of `apply()`: `if (nextActive) active = true` — engage the in-memory gate before any read or
install, released only by the trailing assignment. Deliberately NOT over-corrected to "set the
desired state first" unconditionally: a failing read-only→read-write sync must keep the gate
closed, so only the engaging direction is latched early. The test lesson: the failure-path fixture
had hard-coded the new read as infallible — every new fallible read inside a fail-closed path needs
its own failure-mode case.

## Cross-references

- `extension/substrate/toolGating.ts` — `apply()`'s engagement latch
- `extension/substrate/commandPositions.ts` — `splitTopLevelSegments`, the lexer both hooks share
- `docs/learned/pi/read-only-bash-gate.md` — the read-only bash gate (walker, veto view, row craft)
- `extension/substrate/bashScanTimeout.ts` + `extension/pi/v1/bashScanTimeout.ts` — the scan-timeout guard (policy + Pi glue)
- `shared/contracts.md` §8.69 — the bash scan-timeout contract
- `docs/learned/workflow/borrowed-packages.md` — the late-tool admission model the census read serves
- `docs/learned/workflow/plan-factories.md` — inbox-over-gh pattern using this constraint
- `.pi/APPEND_SYSTEM.md` — the live ambient routing index
- `docs/learned/index.md` — the full on-demand catalog
