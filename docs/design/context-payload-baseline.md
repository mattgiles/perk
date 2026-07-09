# Context payload baseline (Objective #1263, Node 1.1)

**Status:** measured record — the committed baseline the payload-diet phases (2, 3, 4, 5, 6.2)
prove their deltas against. Numbers were gathered with the `/perk-selfcheck` per-surface payload
census (`extension/doors/selfcheck.ts`; contracts.md §8.7).

- **Date:** 2026-07-09
- **perk:** 1.1.0 · **pi:** 0.80.3
- **Repo state:** the perk self-repo at the census-introducing plan branch (`plan-1265`,
  measurements taken pre-merge from the plan's worktree — the only checkout carrying the census
  code at measurement time; the recipe below is written against the post-merge self-repo root).
- **Caveat (machine-free numbers do not exist):** every count varies with the repo's config,
  selected providers, installed packages, skills, and pi version. This baseline is a *record of one
  real configuration* (the self-repo, default selections plus the `juicesharp-todo` /
  `juicesharp-ask-user` providers), not a normative target — which is exactly why the census is
  report-only and never a gate (the objective's non-goal). Re-measure before comparing.
- All counts are `string.length` char counts (the census's `c` suffix). Rough token intuition:
  ~4 chars/token for English/code, so e.g. a 33k-char append prompt is on the order of 8k tokens.

## Measurement recipe

Three session shapes, one command. The census reads the branch as of the last completed turn (a
slash command does not fire `before_agent_start`), so a fresh session shows 0–1 copies per
injected context; the run-again-later step is what captures per-turn re-injection growth.

1. **Fresh plan session** — from the self-repo root, launch a sacrificial `perk plan` session and
   let the seed turn complete. Type `/perk-selfcheck` and transcribe the census block. Then send a
   couple of trivial prompts (letting each turn complete) and run `/perk-selfcheck` again to
   capture injected-context copy growth (today's per-turn re-injection). Abandon the scratch plan
   — no save; `perk worktree wipe` cleans up any residue.
2. **Implement session** — inside a real `perk implement` session, the human types
   `/perk-selfcheck` and pastes the block.
3. **Subagent shape** — from the self-repo root:

   ```
   env -u PERK_RUN_ID pi --mode json -p "/perk-selfcheck"
   ```

   stderr carries the report; pi print mode executes the command **before any provider call**, so
   the run is fully offline. Record BOTH variants: default, and with `--no-skills` (pi-subagents
   passes `--no-skills` for non-skill-inheriting agents). Provenance: pi-subagents spawns children
   with baseArgs `--mode json -p` (its `src/runs/shared/pi-args.ts`); known delta vs a real child:
   its prompt-runtime `--extension` is absent here, so this is a faithful *proxy*, not a byte-exact
   replica. `env -u PERK_RUN_ID` avoids the run-id env leak from the invoking session
   (`docs/learned/pi/extension-api.md`).

## Baseline: fresh plan session

Measured in a sacrificial `perk plan` session launched from the plan worktree (so it loaded the
census-carrying extension; abandoned unsaved). The plan stage is **read-only**, which shows up as
the smaller active-tool set; this repo selects the plannotator plan provider, hence
`perk:plan-adapter-plannotator`. The same worktree AGENTS.md double-count applies (see the
subagent note).

Block 1 — fresh at launch (`/perk-selfcheck` as the first input; the census reads the branch as
of the last completed turn, so the injected contexts are not yet visible):

```
perk: selfcheck — 1.1.0: ok; shared=ok; ambient=reached (append=33481c); agents=reached (files=2)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 33481c
  context-files: 2 file(s), 13256c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=6628c, /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-1265/AGENTS.md=6628c
  skills: 14 visible + 16 hidden; prompt-section=9082c
  tools: 15 active / 34 registered; schemas=17447c; guidelines=3118c; snippets=943c
    per source: ..=4 (4235c); builtin=5 (3198c); npm:@juicesharp/rpiv-ask-user-question=1 (3930c); npm:pi-subagents=2 (830c); npm:pi-web-access=3 (5254c)
  branch: 4 entries; binding-header-copies=0
    perk contexts: none; other custom_message ×0 (0c)
```

Block 2 — after two trivial completed turns (the copy-growth capture):

```
perk: selfcheck — 1.1.0: ok; shared=ok; ambient=reached (append=33481c); agents=reached (files=2)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 33481c
  context-files: 2 file(s), 13256c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=6628c, /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-1265/AGENTS.md=6628c
  skills: 14 visible + 16 hidden; prompt-section=9082c
  tools: 15 active / 34 registered; schemas=17447c; guidelines=3118c; snippets=943c
    per source: ..=4 (4235c); builtin=5 (3198c); npm:@juicesharp/rpiv-ask-user-question=1 (3930c); npm:pi-subagents=2 (830c); npm:pi-web-access=3 (5254c)
  branch: 15 entries; binding-header-copies=1
    perk contexts: perk:binding-context ×1 (116c); perk:mode-context ×2 (2446c); perk:plan-adapter-plannotator ×2 (2224c); perk:plan-context ×2 (5904c); other custom_message ×0 (0c)
```

Headline numbers:

| Surface                      | Fresh (block 1)                          | After 2 turns (block 2)                       |
| ---------------------------- | ---------------------------------------- | --------------------------------------------- |
| append-system-prompt         | 33,481c                                  | 33,481c                                       |
| context files                | 2 files, 13,256c (worktree double-count) | same                                          |
| skills prompt section        | 14 visible + 16 hidden, 9,082c           | same                                          |
| tool schemas (active)        | 15 active / 34 registered, 17,447c       | same                                          |
| tool guidelines / snippets   | 3,118c / 943c                            | same                                          |
| perk-injected branch context | none (4 entries)                         | 4 customTypes, 7 copies, 10,690c (15 entries) |
| binding-header copies        | 0                                        | 1                                             |

The growth capture is the plan-shape headline: `perk:mode-context`, `perk:plan-context`, and
`perk:plan-adapter-plannotator` each reached ×2 after two turns — today's per-turn re-injection
(Phase 2's dedup target) measured directly. Read-only gating also pays off visibly on the tools
surface: 17,447c of active schemas vs 50,752c in the read-write shapes.

## Baseline: implement session

Measured inside this plan's own implement session (the census-introducing plan, dogfooded live:
`/reload` to pick up the just-committed census code, then the human typed `/perk-selfcheck` and
pasted the block). The same worktree AGENTS.md double-count applies (see the subagent note).

```
perk: selfcheck — 1.1.0: ok; shared=ok; ambient=reached (append=33481c); agents=reached (files=2)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 33481c
  context-files: 2 file(s), 13256c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=6628c, /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-1265/AGENTS.md=6628c
  skills: 14 visible + 16 hidden; prompt-section=9082c
  tools: 30 active / 34 registered; schemas=50752c; guidelines=11375c; snippets=1808c
    per source: ..=17 (16023c); builtin=4 (2769c); npm:@juicesharp/rpiv-ask-user-question=1 (3930c); npm:@juicesharp/rpiv-todo=1 (1839c); npm:pi-subagents=4 (20937c); npm:pi-web-access=3 (5254c)
  branch: 124 entries; binding-header-copies=3
    perk contexts: perk:binding-context ×1 (126c); perk:todo-adapter-juicesharp ×1 (883c); other custom_message ×0 (0c)
```

Headline numbers:

| Surface                      | Value                                         |
| ---------------------------- | --------------------------------------------- |
| append-system-prompt         | 33,481c                                       |
| context files                | 2 files, 13,256c (worktree double-count)      |
| skills prompt section        | 14 visible + 16 hidden, 9,082c                |
| tool schemas (active)        | 30 active / 34 registered, 50,752c            |
| tool guidelines / snippets   | 11,375c / 1,808c                              |
| perk-injected branch context | 2 customTypes, 2 copies, 1,009c (124 entries) |
| binding-header copies        | 3                                             |

The prompt-construction surfaces are identical to the subagent shape (same repo, same extension
set) — what distinguishes a working implement session is the **branch**: 124 entries deep at
measurement, with the binding nudge present 3× (the cold launch prompt plus warm re-delivery —
node 6.1's target) and the todo-adapter bridge context injected. This session ran under the
`juicesharp-todo` provider selection, so `perk:todo-adapter-juicesharp` appears in place of perk's
own checkpoint seeding; a default-selection implement session would show `perk:steps-context`
instead.

## Baseline: subagent shape (headless print-mode)

Measured from the plan worktree root (see repo-state note above). Worktree artifact: pi walks up
from a linked worktree under the main repo and loads **both** `AGENTS.md` files (main checkout +
worktree — identical content, double-counted); a post-merge re-run from the self-repo root shows
1 file at half the total chars.

Default variant:

```
perk: selfcheck — 1.1.0: ok; shared=ok; ambient=reached (append=33481c); agents=reached (files=2)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 33481c
  context-files: 2 file(s), 13256c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=6628c, /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-1265/AGENTS.md=6628c
  skills: 14 visible + 16 hidden; prompt-section=9082c
  tools: 30 active / 34 registered; schemas=50752c; guidelines=11375c; snippets=1808c
    per source: ..=17 (16023c); builtin=4 (2769c); npm:@juicesharp/rpiv-ask-user-question=1 (3930c); npm:@juicesharp/rpiv-todo=1 (1839c); npm:pi-subagents=4 (20937c); npm:pi-web-access=3 (5254c)
  branch: 4 entries; binding-header-copies=0
    perk contexts: none; other custom_message ×0 (0c)
```

`--no-skills` variant (only the skills surface changes):

```
perk: selfcheck — 1.1.0: ok; shared=ok; ambient=reached (append=33481c); agents=reached (files=2)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 33481c
  context-files: 2 file(s), 13256c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=6628c, /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-1265/AGENTS.md=6628c
  skills: 0 visible + 0 hidden; prompt-section=0c
  tools: 30 active / 34 registered; schemas=50752c; guidelines=11375c; snippets=1808c
    per source: ..=17 (16023c); builtin=4 (2769c); npm:@juicesharp/rpiv-ask-user-question=1 (3930c); npm:@juicesharp/rpiv-todo=1 (1839c); npm:pi-subagents=4 (20937c); npm:pi-web-access=3 (5254c)
  branch: 4 entries; binding-header-copies=0
    perk contexts: none; other custom_message ×0 (0c)
```

Headline numbers:

| Surface                      | Default                      | `--no-skills`   |
| ---------------------------- | ---------------------------- | --------------- |
| append-system-prompt         | 33,481c                      | 33,481c         |
| context files                | 2 files, 13,256c (worktree double-count) | same |
| skills prompt section        | 14 visible + 16 hidden, 9,082c | 0 + 0, 0c     |
| tool schemas (active)        | 30 active / 34 registered, 50,752c | same      |
| tool guidelines / snippets   | 11,375c / 1,808c             | same            |
| perk-injected branch context | none (4 entries)             | none            |

Even a "bare" headless run carries ~110k chars (~27k tokens) of perk-adjacent payload before the
first model call — the append prompt (ambient index), tool schemas, and skills catalog dominate.

## Closing audit (Phase 6)

_Placeholder — node 6.2 re-runs the recipe above after the diet phases land and records the
before/after per surface here._
