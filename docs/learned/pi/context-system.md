---
title: Pi context system — no transclusion, ambient index split, bash allowlist
read_when: You are designing how to surface information to a plan session, building a plan factory, debugging why a bash command is blocked in a read-only session, or extending the read-only bash allowlist (incl. the subcommand-shaped gh entries) — which is a five-surface lockstep, not a one-line edit.
---

# Pi context system

## No in-file `@`-transclusion

Pi context files (`AGENTS.md`, `.pi/SYSTEM.md`, `.pi/APPEND_SYSTEM.md`) load **verbatim** — `@file`
is only a CLI message-arg prefix, not interpreted inside context files. Consequence: you cannot
`@`-reference a catalog from `.pi/APPEND_SYSTEM.md`; the reference would appear as literal text.

## Ambient index must be a real two-layer split

Because transclusion doesn't work, an "ambient index" of durable learnings requires a genuine split:

1. **Compressed routing index** — inline in `.pi/APPEND_SYSTEM.md`, appended to every session's
   system prompt. Project-scoped, committed, NOT gitignored, NOT `init`-managed (maintained only by
   `/learn-docs` plans). One terse routing line per category — keeps the system-prompt append small.
2. **Full on-demand catalog** — `docs/learned/index.md`, read by the model when the routing cue
   matches. Lists every doc with `Category`, `Document`, `Read when`.

Don't try to compress the full catalog into the ambient context. The two-layer split is the right
architecture.

## Bash allowlist in read-only plan sessions

`extension/substrate/toolGating.ts` `SAFE_PATTERNS` restricts bash in read-only (`mode: read-only`) sessions
to:

```
cd / cat / head / tail / grep / find / ls
git status | git log | git diff
jq
curl
gh <issue|pr|repo|run|release|label> <view|list|diff|status|checks> | gh search … | gh auth status
```

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

Excluded: `gh` mutating subcommands (create/edit/merge/close/comment/clone/…) **and `gh api`**
(it can POST/PATCH — GET-vs-mutation by regex is fragile), `perk` (mutating subcommands), `npm`,
`uv`, any write command. This is **intentional** — plan sessions must not mutate state.
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

Fix the **allowlist**, not cold-door seed-injection: the cold door injects only minimal context
(e.g. an objective's title + one node description), so an agent legitimately needs the read-only
query to read the rest.

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
4. **`docs/user-docs/reference/in-session.md`** — the **two** read-only-allowlist notes (near the
   top + the later `READ_ONLY_TOOLS` note); both need updating.
5. **This learned doc** — record the new entry as a command-keyed precedent.

**Mechanism-choice lesson:** perk **cannot own `grep`** — it's a Pi builtin, not a perk-registered
tool, so there is no tool to swap or remove. Steering toward a structural-search tool is therefore
the managed `AGENTS.md` bullet (ambient every session) + a bundled ambient skill + the read-only
allowlist entry — **no** custom tool, no `READ_ONLY_TOOLS`/active-tools change, no default binding.

## Cross-references

- `extension/substrate/toolGating.ts` — `SAFE_PATTERNS` implementation
- `docs/learned/workflow/plan-factories.md` — inbox-over-gh pattern using this constraint
- `.pi/APPEND_SYSTEM.md` — the live ambient routing index
- `docs/learned/index.md` — the full on-demand catalog
