---
title: Pi context system — no transclusion, ambient index split, bash allowlist, the scan-timeout guard
read_when: You are surfacing info to a session, debugging a blocked/timed-out bash call, extending the read-only bash allowlist or scan-timeout guard, or hit the worktree AGENTS.md double-load.
cluster: pi-extension
---

# Pi context system

## Distillation

- Pi context files load verbatim — no `@`-transclusion; the ambient index is a two-layer split
  (compressed routing in `.pi/APPEND_SYSTEM.md`, the full catalog on demand) — "No in-file
  `@`-transclusion", "Ambient index must be a real two-layer split".
- A linked worktree double-loads `AGENTS.md` (main + worktree) — "Linked-worktree AGENTS.md
  double-load".
- The read-only bash inventory is `SAFE_PATTERNS` in `toolGating.ts` (never mirror it into prose);
  the gate is allowlist-AND-not-destructive, applied per top-level segment; extending it is a
  five-surface lockstep and a def-taught shell recipe must be tested for gate admissibility AND
  byte semantics (`sed -n 'Np' | tail -c +<offset> | head -c`) — "Bash allowlist in read-only
  plan sessions" and its subsections.
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

## Bash allowlist in read-only plan sessions

The authoritative inventory of what bash passes in read-only (`mode: read-only`) sessions is
**`SAFE_PATTERNS` in `extension/substrate/toolGating.ts`** — a far larger allowlist than any
prose snapshot: read/inspect-only commands, scoped `git` and package-manager *metadata* queries,
structural-search tools, `perk objective` read verbs, and `gh` query subcommands. **Never mirror
the inventory into prose — it drifts** (this doc's own earlier snapshot did); extending it is the
five-surface lockstep (see §"Allowlisting a read-only bash gate command is a five-surface
lockstep" below).

Since #485 the safe check is applied **per top-level segment**, not just to the leading command:
`isReadOnlyBashCommand` splits the command into quote-aware top-level segments (on `;`/`&&`/`||`/`|`,
ignoring operators inside single/double quotes) and requires **every** segment's leading command to
match a `SAFE_PATTERNS` entry. This unblocks `cd`-prefixed chains (`cd repo && perk objective show …`)
and **tightens** the model: a non-safe command *anywhere* in a compound command is now blocked
(`git status && some-unknown-binary` no longer slips through on its safe leading token). Loops
(`for`/`while`) stay blocked — their leading segment matches no safe pattern.

**Redirect carve-outs (not destructive):** the destructive scan neutralizes FD duplications
(`2>&1`, `1>&2`) **and** redirects to the null device (`>/dev/null`, `2>/dev/null`, `&>/dev/null`,
`>>/dev/null`) before scanning — both discard output and write nothing to the filesystem. Redirects
to a **real path** (`> file`, `&> file`, `>> file`) are *not* carved out and stay destructive.

Excluded, in durable policy terms: mutating `gh` subcommands **and `gh api`** stay blocked
(GET-vs-mutation by regex is fragile), as do `perk`'s mutating subcommands and every write
command. This is **intentional** — plan sessions must not mutate state.
Read-only `gh` *query* subcommands were allowlisted in #416 so the ambient AGENTS guidance
("GitHub access goes through `gh`") is followable in read-only sessions.

Consequence for plan factories: the inbox pattern (cold door fetches via `gh` and materializes
into a file before the session launches) remains **preferred** — deterministic and token-cheap —
but since #416 it is no longer structurally forced: ad-hoc read-only `gh` queries pass the gate.
See `docs/learned/workflow/plan-factories.md` for the inbox-over-gh pattern.

### The gh allowlist is subcommand-shaped, never verb-inferred

`gh api` stays blocked even for GET-shaped calls — inferring GET-vs-mutation by regex is fragile,
so the allowlist names query *subcommands* instead (`view|list|diff|status|checks`, `gh search`,
`gh auth status`), which cover real read needs. Destructive-wins still blocks `gh issue view >
file` redirects for free. Extending the allowlist is a **deliberate per-subcommand act**: judge
each candidate by what it does, not by its verb shape — e.g. `gh release download` is NOT
read-only (it writes files).

### Allowlist policy when adding an entry

The gate is **allowlist-AND-not-destructive**: a command passes only if it matches a `SAFE_PATTERNS`
regex *and* is not destructive. **Destructive patterns always win** — a safe prefix on a compound
command (`git status && rm file`) is still blocked. To let a *new* command through you add a
`SAFE_PATTERNS` regex, observing two rules:

- **Scope to the genuinely non-mutating subcommands only.** When read-only `perk objective` queries
  were allowed (#67), the regex enumerated `show`/`next` (+ aliases `s`/`n`) explicitly rather than
  matching `perk objective .*`, leaving mutating `create`/`node`/`reconcile` and `perk init`
  blocked. Prefer enumerating allowed verbs over a broad wildcard.
- **Anchor short aliases with `\b`.** The trailing word boundary is load-bearing: without it the `n`
  alias (for `next`) would also match the mutating `node` subcommand. Add an explicit block-side test
  (e.g. `perk obj node 2.3` must be blocked) to prove an alias doesn't bleed into a sibling verb.

A perk-owned subcommand-shaped precedent: `perk objective node-engagement` (a non-mutating `--json`
engagement read) was added as a further alternative in the existing `perk objective` entry —
motivated by the objective-plan factory needing node-engagement reads in read-only planning
sessions. The `\b` after the `n` alternative already keeps bare `n`/`node` apart, so the new
alternative slots in without loosening the sibling `node` block; the block-side tests grew a
sibling-verb case (`perk objective node 2.3 --status done`) and a redirect veto case
(`node-engagement … > f`) alongside the positive.

Fix the **allowlist**, not cold-door seed-injection: the cold door injects only minimal context
(e.g. an objective's title + one node description), so an agent legitimately needs the read-only
query to read the rest.

### Destructive-wins can silently dead-end a SAFE_PATTERNS arm

Because destructive patterns always win, a too-broad destructive veto can make an allowlist entry
unreachable — a **dead allowlist arm**. Hit live: the editor veto `\b(vim?|nano|emacs|code|subl)\b`
matched the *word* `code` anywhere, so the allowlisted `gh search code` could never run. The
`code` veto is now command-position-anchored (see the inline comment in `toolGating.ts`).

Durable rule: when adding a word-boundary destructive pattern, check it against every
`SAFE_PATTERNS` arm whose text can contain that word — a bare `\bword\b` veto silently kills safe
entries.

### A command-keyed allowlist entry is language-agnostic (the `ast-grep` entry, #617)

The `ast-grep` allowlist entry (`/^\s*ast-grep\b/`) gates the **command itself**, not its `--lang`
argument — so it is equally allowed against any language (the `-` in `ast-grep` is a non-word char,
so `\b` after `grep` matches correctly). A test framing it as `--lang js` reads as language-specific
but isn't; pin the language-agnosticism with a second `--lang python` case rather than a
production-code change.

**A second command-keyed precedent (`agent-browser`, #663).** The browser-automation skill's
allowlist entries (`/^\s*agent-browser\b/` and `/^\s*npx\s+agent-browser\b/`) follow the same
command-keyed shape — they gate the command, not the args, and the `npx` form is anchored to
`agent-browser` so bare `npx <anything>` stays blocked. **Accepted write-leniency rationale:** the
leading-command model cannot inspect args, so `agent-browser`'s own output flags (screenshot/video
`--output`) can write files and its actions can mutate external sites — outside the gate's
granularity. This is accepted and documented (not arg-sniffed), consistent with the already-allowed
`curl` / `fetch_content` GitHub-clone cache-write precedent; the whole-string `>`-redirect
destructive veto still applies. No `READ_ONLY_TOOLS` / `READ_ONLY_CONTEXT` change — `agent-browser`
is a bash CLI already covered by the `bash` tool entry, and safe bash commands are not enumerated in
the injected context.

### Allowlisting a read-only bash gate command is a five-surface lockstep

Adding a command to the read-only `bash` sub-allowlist is **FIVE coordinated surfaces**, not a
one-line `SAFE_PATTERNS` edit — the `agent-browser` precedent above is an *instance* of this durable
shape (landed exactly as planned, zero deviations):

1. **Production** — the `SAFE_PATTERNS` regex(es) in `extension/substrate/toolGating.ts`.
2. **Tests** — the **paired allowed/blocked** case lists in `toolGating.test.ts`: add allowed cases
   (incl. a `cd repo && <cmd>` case proving per-segment acceptance) AND blocked cases pinning the
   anchoring (e.g. `npx some-other-pkg` stays blocked) and the destructive-`>`-redirect veto (a
   `<cmd> > file` stays blocked even though the leading command is now safe).
3. **`shared/contracts.md`** — amend the read-only-gate paragraph (same-turn contract discipline).
4. **`docs/user-docs/reference/in-session/model-tools.md`** — the §"Structural read-only gate"
   explanation (`docs/user-docs/reference/in-session.md` is only the surface-map page; the gate explanation
   lives in the model-tools reference).
5. **This learned doc** — record the new entry as a command-keyed precedent.

**Mechanism-choice lesson:** perk **cannot own `grep`** — it's a Pi builtin, not a perk-registered
tool, so there is no tool to swap or remove. Steering toward a structural-search tool is therefore
the managed `AGENTS.md` bullet (ambient every session) + a bundled ambient skill + the read-only
allowlist entry — **no** custom tool, no `READ_ONLY_TOOLS`/active-tools change, no default binding.

**A five-surface instance with a sixth carrier:** widening the reviewer children's
`perk pr review-context` entry to one anchored alternation admitting exactly `--expected-pr N --json`,
`--pr N --json` and `--pr N --stack --json` (`SAFE_PATTERNS` in `toolGating.ts`) walked the five
surfaces — and a **sixth** the plan missed: `docs/design/pi-subagents-child-execution-policy.md`
stated the old exact command form. Design records that quote a gated command are carriers too;
grep them for the old spelling.

### A def-taught shell recipe needs two tests — gate admissibility AND byte semantics

Pi's own oversized-line hint — `sed -n 'Np' <path> | head -c 51200` — is **not a slicer**: it
re-exposes the same first 51,200 bytes of the line on every call. The offset-capable, gate-admitted
form the review defs teach is `sed -n 'Np' <path> | tail -c +<offset> | head -c 51200` (offsets `+1`,
`+51201`, …). A `toolGating.test.ts` case pins that exact pipeline as allowed (and its
`> slice.txt` redirect as blocked), so the allowlist cannot silently drop a pipeline segment out from
under the defs. Rule: when an agent def teaches a shell recipe, test both that the gate admits it and
that it does what the prose claims byte-for-byte — a recipe that passes the gate but pages nothing
fails silently in every lane.

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
- **One splitter for both hooks.** The classifier reuses the gate's exported
  `toolGating.ts::splitTopLevelSegments`, so both hooks agree on segment boundaries and a flag in a
  later pipeline stage (`grep -n foo f | sort -r`) is never attributed to the grep.
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

- `extension/substrate/toolGating.ts` — `SAFE_PATTERNS`, `splitTopLevelSegments`, `apply()`'s engagement latch
- `extension/substrate/bashScanTimeout.ts` + `extension/pi/v1/bashScanTimeout.ts` — the scan-timeout guard (policy + Pi glue)
- `shared/contracts.md` §8.69 — the bash scan-timeout contract
- `docs/learned/workflow/borrowed-packages.md` — the late-tool admission model the census read serves
- `docs/learned/workflow/plan-factories.md` — inbox-over-gh pattern using this constraint
- `.pi/APPEND_SYSTEM.md` — the live ambient routing index
- `docs/learned/index.md` — the full on-demand catalog
