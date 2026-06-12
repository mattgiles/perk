---
title: Pi context system — no transclusion, ambient index split, bash allowlist
read_when: You are designing how to surface information to a plan session, building a plan factory, or debugging why a bash command is blocked in a read-only session.
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

`extension/toolGating.ts` `SAFE_PATTERNS` restricts bash in read-only (`mode: read-only`) sessions
to:

```
cat / head / tail / grep / find / ls
git status | git log | git diff
jq
curl
gh <issue|pr|repo|run|release|label> <view|list|diff|status|checks> | gh search … | gh auth status
```

Excluded: `gh` mutating subcommands (create/edit/merge/close/comment/clone/…) **and `gh api`**
(it can POST/PATCH — GET-vs-mutation by regex is fragile), `perk` (mutating subcommands), `npm`,
`uv`, any write command. This is **intentional** — plan sessions must not mutate state.
Read-only `gh` *query* subcommands were allowlisted in #416 so the ambient AGENTS guidance
("GitHub access goes through `gh`") is followable in read-only sessions.

Consequence for plan factories: the inbox pattern (cold door fetches via `gh` and materializes
into a file before the session launches) remains **preferred** — deterministic and token-cheap —
but since #416 it is no longer structurally forced: ad-hoc read-only `gh` queries pass the gate.
See `docs/learned/workflow/plan-factories.md` for the inbox-over-gh pattern.

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

## Cross-references

- `extension/toolGating.ts` — `SAFE_PATTERNS` implementation
- `docs/learned/workflow/plan-factories.md` — inbox-over-gh pattern using this constraint
- `.pi/APPEND_SYSTEM.md` — the live ambient routing index
- `docs/learned/index.md` — the full on-demand catalog
