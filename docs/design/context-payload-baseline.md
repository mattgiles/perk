# Context payload baseline (Objective #1263, Node 1.1)

**Status:** complete before/after record — the Phase-1 baseline (below) plus the Node 6.2 closing
audit (`## Closing audit (Phase 6)`), both gathered with the `/perk-selfcheck` per-surface payload
census (`extension/doors/selfcheck.ts`; contracts.md §8.7). *2026-08 note (Objective #1416): the
baseline was measured under the since-retired `juicesharp-todo`/`juicesharp-ask-user` provider
selections (the seams were retired to required borrows); the measurements stand as recorded.* The diet phases (2, 3, 4, 5, 6.1)
prove their deltas against the baseline; the closing audit reconciles the objective's three soft
targets against measured reality.

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

   Pinned-SHA gotcha: the sacrificial launch runs a guarded pre-launch fast-forward of the main
   checkout, so an audit that pins a single repo SHA can be silently invalidated by its own
   measurement procedure. Pass `--no-sync` on the sacrificial launch (and/or capture the subagent
   shape — step 3 — before any interactive launch); if main moved anyway, verify census-inertness
   (byte-identical census blocks and measured artifact inputs at both SHAs) and record both SHAs
   honestly, as the Closing audit's Repo-state bullet does.
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

Node 6.2's re-run of the recipe above, after every diet phase landed (2.1 injection dedup, 3.1/3.2
cue budget, 4.1/4.2 skills exposure, 5.1/5.2 stage-scoped tools, 6.1 ambient-prose sweep +
binding double-nudge fix). Same census code, same session shapes; tables read baseline / closing /
delta per surface.

- **Date:** 2026-07-10
- **perk:** 1.1.0 · **pi:** 0.80.6 (the baseline ran pi 0.80.3)
- **Repo state:** main @ `a9407f77` (post-6.1: every diet phase merged). The audit began with main
  @ `8c4a52c8` (the 6.1 merge); the sacrificial plan launch's pre-flight fast-forward pulled in
  `a9407f77` mid-audit. Verified census-inert: the subagent blocks are byte-identical at both
  SHAs, and `.pi/APPEND_SYSTEM.md` / `AGENTS.md` / `docs/learned/index.md` are byte-identical
  between them (the intervening commit is docs plus a footer-only surfaces change). The implement
  block was captured in this node's own implement session (worktree `plan-1328`, branched from
  `8c4a52c8`).
- **Recipe deltas vs Phase 1 — vantage only.** The plan and subagent shapes were captured from the
  post-merge self-repo root (the recipe's own stated vantage), so they see **1** AGENTS.md context
  file where the baseline's worktree vantage double-counted 2 — the post-merge re-run the
  baseline's subagent note anticipated. The implement shape still runs from a linked worktree
  (2 files) and is directly comparable. The census code is unchanged since the baseline landed,
  so the line grammar is byte-comparable.
- **Registry footnote for reading the tables:** `open_plannotator_review` was retired along with
  the `/review` command between the two measurements, so every closing block shows 33 registered
  tools vs the baseline's 34 (and headless perk-owned active tools 17 → 16). A real tool
  retirement, not census drift.

### Closing: fresh plan session

Skills-exposure evidence — `perk plan --dry-run` at the measurement state composes 10 skills:

```
pi --no-skills --skill .pi/npm/node_modules/pi-web-access/skills/librarian --skill .agents/skills/ast-grep --skill .agents/skills/codebase-design --skill .agents/skills/dignified-pydantic --skill .agents/skills/dignified-python --skill .agents/skills/domain-modeling --skill .agents/skills/grill-with-docs --skill .agents/skills/mastering-typescript --skill .agents/skills/perk-expert --skill .agents/skills/perk-plan
```

Measured in a sacrificial `perk plan` session launched from the self-repo root (abandoned unsaved;
`perk worktree wipe` cleaned residue). Capture-timing note: this block 1 was taken **after the
seed turn completed** (this node's procedure), so the seed turn's injected contexts are already
visible at ×1; the baseline's block 1 ran `/perk-selfcheck` as the literal first input (branch
surface pre-seed: no contexts). Prompt-construction surfaces are comparable either way; the
like-for-like growth pair is block 2 vs block 2.

Block 1 — after the seed turn:

```
perk: selfcheck — 1.1.0: ok; shared=ok; ambient=reached (append=13408c); agents=reached (files=1)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 13408c
  context-files: 1 file(s), 6307c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=6307c
  skills: 8 visible + 2 hidden; prompt-section=5440c
  tools: 15 active / 33 registered; schemas=17447c; guidelines=3118c; snippets=943c
    per source: ..=4 (4235c); builtin=5 (3198c); npm:@juicesharp/rpiv-ask-user-question=1 (3930c); npm:pi-subagents=2 (830c); npm:pi-web-access=3 (5254c)
  branch: 10 entries; binding-header-copies=1
    perk contexts: perk:binding-context ×1 (116c); perk:mode-context ×1 (515c); perk:plan-adapter-plannotator ×1 (452c); perk:plan-context ×1 (2001c); other custom_message ×0 (0c)
```

Block 2 — after two trivial completed turns (no-tool prompts, staying clear of 2.1's documented
dedup false positive):

```
perk: selfcheck — 1.1.0: ok; shared=ok; ambient=reached (append=13408c); agents=reached (files=1)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 13408c
  context-files: 1 file(s), 6307c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=6307c
  skills: 8 visible + 2 hidden; prompt-section=5440c
  tools: 15 active / 33 registered; schemas=17447c; guidelines=3118c; snippets=943c
    per source: ..=4 (4235c); builtin=5 (3198c); npm:@juicesharp/rpiv-ask-user-question=1 (3930c); npm:pi-subagents=2 (830c); npm:pi-web-access=3 (5254c)
  branch: 14 entries; binding-header-copies=1
    perk contexts: perk:binding-context ×1 (116c); perk:mode-context ×1 (515c); perk:plan-adapter-plannotator ×1 (452c); perk:plan-context ×1 (2001c); other custom_message ×0 (0c)
```

The plan-shape headline: block 2 is identical to block 1 on every perk context — **×1 each** after
two more turns (baseline: ×2 and growing per turn). Branch entries grew 10 → 14 (the turns
themselves); injected-context copies stayed flat.

| Surface                      | Phase-1 baseline (block 2)         | Closing (block 2)                  | Delta                                            |
| ---------------------------- | ---------------------------------- | ---------------------------------- | ------------------------------------------------ |
| append-system-prompt         | 33,481c                            | 13,408c                            | −20,073c (−60%)                                  |
| context files                | 2 files, 13,256c                   | 1 file, 6,307c                     | vantage (2 → 1 files); per-file 6,628c → 6,307c  |
| skills prompt section        | 14 visible + 16 hidden, 9,082c     | 8 visible + 2 hidden, 5,440c       | −3,642c (−40%); full catalog → composed list     |
| tool schemas (active)        | 15 active / 34 registered, 17,447c | 15 active / 33 registered, 17,447c | unchanged (the read-only set was already tight)  |
| tool guidelines / snippets   | 3,118c / 943c                      | 3,118c / 943c                      | unchanged                                        |
| perk contexts after 2 turns  | 4 types, 7 copies, 10,690c         | 4 types, 4 copies, 3,084c          | −7,606c (−71%)                                   |
| binding-header copies        | 1                                  | 1                                  | unchanged                                        |

Two independent effects compound in the contexts row: 2.1's dedup holds every context at ×1
(baseline: mode/plan/adapter each ×2 after two turns), and 6.1's template diet shrank the
per-copy payloads (mode-context 1,223c → 515c; plan-context 2,952c → 2,001c;
plan-adapter-plannotator 1,112c → 452c per copy). The skills line matches the composed dry-run
list exactly: 8 visible + 2 hidden = the 10 `--skill` entries.

### Closing: implement session

Measured live inside this node's own implement session (no `/reload` needed — the census code is
unchanged on main). Worktree vantage → the 2-file AGENTS.md double-count, directly comparable to
baseline. Same provider selections as baseline (`juicesharp-todo`, hence
`perk:todo-adapter-juicesharp`).

```
perk: selfcheck — 1.1.0: ok; shared=ok; ambient=reached (append=13408c); agents=reached (files=2)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 13408c
  context-files: 2 file(s), 12614c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=6307c, /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-1328/AGENTS.md=6307c
  skills: 9 visible + 1 hidden; prompt-section=5426c
  tools: 21 active / 33 registered; schemas=41033c; guidelines=6831c; snippets=1182c
    per source: ..=8 (6362c); builtin=4 (2711c); npm:@juicesharp/rpiv-ask-user-question=1 (3930c); npm:@juicesharp/rpiv-todo=1 (1839c); npm:pi-subagents=4 (20937c); npm:pi-web-access=3 (5254c)
  branch: 33 entries; binding-header-copies=1
    perk contexts: perk:todo-adapter-juicesharp ×1 (552c); other custom_message ×0 (0c)
```

| Surface                      | Phase-1 baseline                   | Closing                            | Delta                                        |
| ---------------------------- | ---------------------------------- | ---------------------------------- | -------------------------------------------- |
| append-system-prompt         | 33,481c                            | 13,408c                            | −20,073c (−60%)                              |
| context files                | 2 files, 13,256c                   | 2 files, 12,614c                   | −642c (AGENTS.md diet ×2 files)              |
| skills prompt section        | 14 visible + 16 hidden, 9,082c     | 9 visible + 1 hidden, 5,426c       | −3,656c (−40%)                               |
| tool schemas (active)        | 30 active / 34 registered, 50,752c | 21 active / 33 registered, 41,033c | −9,719c (−19%)                               |
| tool guidelines / snippets   | 11,375c / 1,808c                   | 6,831c / 1,182c                    | −4,544c / −626c                              |
| perk-injected branch context | 2 types, 2 copies, 1,009c          | 1 type, 1 copy, 552c               | binding nudge no longer warm re-delivered    |
| binding-header copies        | 3                                  | 1                                  | the 6.1 double-nudge fix, measured live      |

Branch-entry depth (baseline 124, closing 33) is load-bearing context for reading the block —
session depth at the moment the human typed the command — not a comparable number (as the baseline
noted). The tools delta decomposes on the per-source line: perk-owned active tools 17 (16,023c) →
8 (6,362c) — 5.1's eight dropped authoring schemas plus the `open_plannotator_review` retirement —
while the borrowed pi-subagents/pi-web-access placement (5.2) is unchanged in this read-write
shape.

### Closing: subagent shape (headless print-mode)

Both variants re-run from the self-repo root — 1 AGENTS.md file, the post-merge re-run the
baseline's worktree-artifact note anticipated. Byte-identical blocks were captured at both
`8c4a52c8` and `a9407f77` (the census-inert verification in the header).

Default variant:

```
perk: selfcheck — 1.1.0: ok; shared=ok; ambient=reached (append=13408c); agents=reached (files=1)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 13408c
  context-files: 1 file(s), 6307c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=6307c
  skills: 14 visible + 17 hidden; prompt-section=8782c
  tools: 29 active / 33 registered; schemas=50101c; guidelines=10916c; snippets=1763c
    per source: ..=16 (15430c); builtin=4 (2711c); npm:@juicesharp/rpiv-ask-user-question=1 (3930c); npm:@juicesharp/rpiv-todo=1 (1839c); npm:pi-subagents=4 (20937c); npm:pi-web-access=3 (5254c)
  branch: 4 entries; binding-header-copies=0
    perk contexts: none; other custom_message ×0 (0c)
```

`--no-skills` variant (only the skills surface changes):

```
perk: selfcheck — 1.1.0: ok; shared=ok; ambient=reached (append=13408c); agents=reached (files=1)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 13408c
  context-files: 1 file(s), 6307c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=6307c
  skills: 0 visible + 0 hidden; prompt-section=0c
  tools: 29 active / 33 registered; schemas=50101c; guidelines=10916c; snippets=1763c
    per source: ..=16 (15430c); builtin=4 (2711c); npm:@juicesharp/rpiv-ask-user-question=1 (3930c); npm:@juicesharp/rpiv-todo=1 (1839c); npm:pi-subagents=4 (20937c); npm:pi-web-access=3 (5254c)
  branch: 4 entries; binding-header-copies=0
    perk contexts: none; other custom_message ×0 (0c)
```

| Surface                      | Phase-1 baseline (default)         | Closing (default)                  | Delta                                          |
| ---------------------------- | ---------------------------------- | ---------------------------------- | ---------------------------------------------- |
| append-system-prompt         | 33,481c                            | 13,408c                            | −20,073c (−60%)                                |
| context files                | 2 files, 13,256c                   | 1 file, 6,307c                     | vantage (2 → 1 files); per-file 6,628c → 6,307c |
| skills prompt section        | 14 visible + 16 hidden, 9,082c     | 14 visible + 17 hidden, 8,782c     | −300c; headless is deliberately unscoped       |
| tool schemas (active)        | 30 active / 34 registered, 50,752c | 29 active / 33 registered, 50,101c | −651c (the tool retirement)                    |
| tool guidelines / snippets   | 11,375c / 1,808c                   | 10,916c / 1,763c                   | −459c / −45c                                   |
| perk-injected branch context | none                               | none                               | —                                              |

The `--no-skills` closing block matches the baseline shape exactly: skills 0 + 0, 0c; every other
surface identical to the default variant. The headless shape is the near-control: it is not a perk
stage session, so no stage scoping applies (full skill catalog — one hidden skill was added to the
corpus since baseline — and the full read-write tool set); its deltas isolate the global changes
(the ambient diet, the AGENTS.md diet, the tool retirement) from the stage-scoping wins visible
only in the plan/implement shapes.

### Soft-target reconciliation

One verdict per objective soft target, each citing measured evidence from the blocks above.

| # | Soft target | Verdict | Measured evidence |
| - | ----------- | ------- | ----------------- |
| 1 | Ambient index ≲10KB | **Near miss** (~13.4KB) | `append-system-prompt=13408c` in all five closing blocks; `.pi/APPEND_SYSTEM.md` = 13,549 bytes at the measurement state (baseline-era: 33,700 bytes / 33,481c). Structural explanation: the routing block carries 55 docs × (title line + ≤200-char cue) plus preamble; the per-cue ceiling holds and is CI-gated, but the total scales with corpus growth — and the corpus legitimately keeps growing. Exactly what 3.1's landing log predicted ("cues landed near the top of the band"). Recorded honestly; no further diet in this node — the census is report-only by objective design. |
| 2 | One live copy per injected context | **Met** | Plan block 2 after two turns: `perk:mode-context`, `perk:plan-context`, `perk:plan-adapter-plannotator`, `perk:binding-context` each **×1** (baseline: the first three each ×2 and growing per turn). Implement: `binding-header-copies` 3 → 1 (the 6.1 double-nudge fix) and `perk:todo-adapter-juicesharp` ×1. Caveat carried forward: 2.1's dedup has a documented false positive (a tool result quoting perk's own source can suppress a re-inject in the self-repo); the growth capture used trivial no-tool prompts to stay clear of it. |
| 3 | Stage sessions list only stage-relevant skills/tools | **Met, with one pinned residual** | Skills: the plan session reports 8 visible + 2 hidden = exactly the 10 entries `perk plan --dry-run` composes (baseline: the full catalog, 14 + 16); implement reports 9 + 1. Tools: plan 15 active (the read-only set, already tight at baseline); implement 21 active vs baseline 30 (5.1's eight dropped authoring schemas + the tool retirement), with the borrowed-tool placement per 5.2. Residual: the pi-subagents parent supervisor pair registers after perk's `session_start` sync and leaks past launch filtering in stage sessions — visible as `npm:pi-subagents=2 (830c)` in the plan blocks (test-pinned, accepted in 5.2). |

### Closing headline deltas

Per-shape prompt-construction totals (append-system-prompt + context files + skills section +
active schemas + guidelines + snippets) — the objective's bottom line:

| Shape                | Phase-1 baseline | Closing | Delta                                     |
| -------------------- | ---------------- | ------- | ----------------------------------------- |
| Fresh plan session   | 77,327c          | 46,663c | −30,664c (−40%)                           |
| Implement session    | 119,754c         | 80,494c | −39,260c (−33%)                           |
| Subagent (default)   | 119,754c         | 91,277c | −28,477c (−24% raw; −19% vantage-normalized) |

- The plan and subagent closing rows include the vantage change (1 AGENTS.md file vs the
  baseline's double-counted 2). Normalizing the baseline to one file (−6,628c) gives plan
  70,699c → 46,663c (−34%) and subagent 113,126c → 91,277c (−19%). The implement row is
  vantage-identical (worktree in both eras).
- The baseline's **bare headless payload** call-out — the perk-adjacent chars a subagent carries
  before its first model call — recomputes to **91,277c (~22k tokens)**, against the baseline's
  "~110k chars" (119,754c raw by the same component sum; 113,126c normalized to one AGENTS.md).
- Injected-context steady state (a branch surface, not part of the totals above): the plan shape
  after two turns dropped 10,690c → 3,084c (−71%) and no longer grows per turn; the implement
  shape's binding nudge went from three header copies to one.
