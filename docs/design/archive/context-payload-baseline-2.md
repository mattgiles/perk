# Context payload baseline 2 (Objective #1610, Node 1.1)

**Status:** closed before/after record — the Phase-1 baseline (below), gathered with the pinned
#1263 census recipe (`/perk-selfcheck`; `extension/doors/selfcheck.ts`, contracts.md §8.7)
**plus** the new transcript-composition attribution (`perk-dev audit attribution`,
`packages/perk-dev/src/perk_dev/audit/attribution.py`), and node 6.1's closing audit
(`## Closing audit (Phase 6)` below), which re-ran the identical protocol after every diet node
landed. Predecessor: the complete, closed #1263 before/after record in
[`context-payload-baseline.md`](./context-payload-baseline.md). Report-only: no gates, no diet
edits in either bracket.

- **Date:** 2026-08-11/12
- **perk:** 2.3.0 · **pi:** 0.84.1
- **Repo state:** the perk self-repo, main @ `cf60175e` (the base of the attribution-introducing
  plan branch `plan-1611`). The census instrument is unchanged by this plan, so the headless and
  sacrificial-plan shapes run main's extension verbatim (`--no-sync` held main at that SHA); the
  implement shape is this node's own implement session (worktree `plan-1611`, branched from
  `cf60175e`).
- **Caveat (machine-free numbers do not exist):** every count varies with the repo's config,
  selected providers, installed packages, skills, and pi version. This baseline is a *record of
  one real configuration*, not a normative target — the census and the attribution are
  report-only and never gates (the objective's posture). Re-measure before comparing.

## Units

Two `c` suffixes with two definitions — identical for BMP text (this corpus is near-100% ASCII);
the divergence is stated, not engineered around:

- **Census `c`** (the `/perk-selfcheck` blocks): JS `string.length` — UTF-16 code units.
- **Attribution `c`** (the `perk-dev audit attribution` blocks): Python code points of the raw
  JSONL line (the decoded line, newline excluded). Complete per line — unknown fields and
  unprojected payloads (`message.details`) included — with exact reconciliation: per-kind rows
  sum to the entry total (`chars`), and entry chars + header chars + malformed chars cover the
  whole file.

Rough token intuition: ~4 chars/token for English/code.

## Measurement protocol (pinned; node 6.1 re-runs this verbatim)

Three session shapes; the #1263 census recipe restated self-contained, plus the freeze and
attribution steps new to this objective. The census reads the branch as of the last completed
turn (a slash command does not fire `before_agent_start`).

1. **Fresh plan session** — from the self-repo root:

   ```
   perk plan --no-sync
   ```

   (sacrificial; `--no-sync` guards the pinned-SHA gotcha: the launch's pre-flight fast-forward
   of the main checkout can otherwise silently invalidate a single-SHA audit — if main moved
   anyway, verify census-inertness and record both SHAs honestly, as the #1263 closing did).
   **Era note:** at perk 2.3.0 a bare `perk plan` opens idle — there is no auto-run seed turn
   (the #1263-closing procedure's "after the seed turn" step no longer exists); the injected
   contexts arrive with the *first* user turn. So: type `/perk-selfcheck` as the **first input**
   and transcribe the block (block 1 — fresh at launch, matching the #1263 *baseline*'s block-1
   semantics). Then send two growth prompts, each **exactly**:

   ```
   Reply with only the word: ok
   ```

   (no-tool prompts, staying clear of the documented dedup false positive: a tool result quoting
   perk's own source can suppress a re-inject in the self-repo). Let each turn complete, type
   `/perk-selfcheck` again (block 2), abandon the plan unsaved, and clean residue:

   ```
   perk worktree wipe
   ```

2. **Implement session** — this node's own implement session (as #1263 did): the human types
   `/perk-selfcheck` and pastes the block.

3. **Headless (subagent proxy) shape** — from the self-repo root:

   ```
   env -u PERK_RUN_ID pi --mode json -p "/perk-selfcheck"
   ```

   stderr carries the report; pi print mode executes the command **before any provider call**, so
   the run is fully offline. Record BOTH variants: default, and with `--no-skills` (pi-subagents
   passes `--no-skills` for non-skill-inheriting agents). `env -u PERK_RUN_ID` avoids the run-id
   env leak from the invoking session (`docs/learned/pi/extension-api.md`).

4. **Freeze step (new):** immediately after each shape's final census capture, copy that
   session's JSONL (the newest file in `~/.pi/agent/sessions/<encoded-cwd>/` for that vantage) to
   `.perk/workflow/scratch/context-baseline-2/<shape>.jsonl`; record source path, entry count,
   and sha256 below — the frozen copies are the attribution inputs and the closing audit's
   comparability anchor.

5. **Attribution step (new):**

   ```
   uv run perk-dev audit attribution <frozen copies...>
   ```

   Transcribe each report block below.

**Print-mode persistence, recorded honestly (the Decision-10 arm):** the headless shape does
**not** persist a session file. Pi's session manager defers the first flush until an *assistant*
message lands (`_persist`'s `hasAssistant` gate in pi's `session-manager`), and a print-mode
`/perk-selfcheck` run completes before any provider call — so no assistant message ever arrives
and no JSONL is written (`--no-session` exists but is irrelevant here; the session dir's file
count was verified unchanged across both headless runs). The headless census blocks are captured
from stderr as pinned; the attribution section covers only the shapes that persist (plan,
implement).

## Baseline: fresh plan session

Measured in a sacrificial `perk plan --no-sync` session launched from the self-repo root
(abandoned unsaved; `perk worktree wipe` cleaned residue). The plan stage is **read-only** (the
smaller active-tool set); this repo selects the plannotator plan provider, hence
`perk:plan-adapter-plannotator`. **Deviation, recorded honestly:** the recipe pins two growth
turns; across the operator-driven captures the recorded transcript carries *one* completed
`Reply with only the word: ok` turn before block 2 (10 entries: the 4 launch entries, 1 user
turn, the 4 injected contexts, 1 assistant reply). The ×1-per-context reading below is therefore
the injection-time state, not a proof of per-turn flatness (turn 1 is when the contexts first
inject; only a second completed turn discriminates a healthy dedup from per-turn re-injection —
#1263's closing established that flatness; node 6.1 should attempt the two-turn form again). The
frozen copy below is the 6.1 comparison anchor.

Block 1 — fresh at launch (`/perk-selfcheck` as the first input; no contexts injected yet):

```
perk: selfcheck — 2.3.0: ok; shared=ok; ambient=reached (append=14945c); agents=reached (files=1)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 14945c
  context-files: 1 file(s), 7218c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=7218c
  skills: 8 visible + 1 hidden; prompt-section=5474c
  tools: 24 active / 52 registered; schemas=52666c; guidelines=8231c; snippets=1431c
    per source: ..=11 (10393c); builtin=3 (1605c); npm:@ff-labs/pi-fff=2 (3123c); npm:@juicesharp/rpiv-ask-user-question=1 (3761c); npm:pi-subagents=4 (26422c); npm:pi-web-access=3 (7362c)
  branch: 4 entries; binding-header-copies=0
    perk contexts: none; other custom_message ×0 (0c)
```

Block 2 — after trivial completed no-tool growth prompting (one recorded turn; see the deviation
note above):

```
perk: selfcheck — 2.3.0: ok; shared=ok; ambient=reached (append=14945c); agents=reached (files=1)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 14945c
  context-files: 1 file(s), 7218c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=7218c
  skills: 8 visible + 1 hidden; prompt-section=5474c
  tools: 24 active / 52 registered; schemas=52666c; guidelines=8231c; snippets=1431c
    per source: ..=11 (10393c); builtin=3 (1605c); npm:@ff-labs/pi-fff=2 (3123c); npm:@juicesharp/rpiv-ask-user-question=1 (3761c); npm:pi-subagents=4 (26422c); npm:pi-web-access=3 (7362c)
  branch: 10 entries; binding-header-copies=1
    perk contexts: perk:binding-context ×1 (116c); perk:mode-context ×1 (515c); perk:plan-adapter-plannotator ×1 (818c); perk:plan-context ×1 (1542c); other custom_message ×0 (0c)
```

Headline numbers:

| Surface                      | Fresh (block 1)                    | After growth turn (block 2)                  |
| ---------------------------- | ---------------------------------- | -------------------------------------------- |
| append-system-prompt         | 14,945c                            | 14,945c                                      |
| context files                | 1 file, 7,218c                     | same                                         |
| skills prompt section        | 8 visible + 1 hidden, 5,474c       | same                                         |
| tool schemas (active)        | 24 active / 52 registered, 52,666c | same                                         |
| tool guidelines / snippets   | 8,231c / 1,431c                    | same                                         |
| perk-injected branch context | none (4 entries)                   | 4 types, 4 copies, 2,991c (10 entries)       |
| binding-header copies        | 0                                  | 1                                            |

Every context sits at ×1 at injection time (per-turn flatness not re-proven here — see the
deviation note; #1263's closing is the standing flatness evidence).

## Baseline: implement session

Measured inside this node's own implement session (the human typed `/perk-selfcheck` and pasted
the block; branch depth 175 at capture — load-bearing context, not a comparable number).
**Vantage note:** pi 0.84.1 loads only the *worktree's* `AGENTS.md` (1 file) — the #1263-era
double-load (main checkout + worktree, 2 identical files) is gone; comparisons against the #1263
implement rows must normalize for it.

```
perk: selfcheck — 2.3.0: ok; shared=ok; ambient=reached (append=14945c); agents=reached (files=1)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 14945c
  context-files: 1 file(s), 7218c — /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-1611/AGENTS.md=7218c
  skills: 9 visible + 1 hidden; prompt-section=5391c
  tools: 38 active / 52 registered; schemas=66608c; guidelines=16093c; snippets=2263c
    per source: ..=22 (19713c); builtin=4 (2711c); npm:@ff-labs/pi-fff=2 (3123c); npm:@juicesharp/rpiv-ask-user-question=1 (3761c); npm:@juicesharp/rpiv-todo=1 (1936c); npm:pi-subagents=4 (26422c); npm:pi-web-access=4 (8942c)
  branch: 175 entries; binding-header-copies=3
    perk contexts: none; other custom_message ×0 (0c)
```

Headline numbers:

| Surface                      | Value                                    |
| ---------------------------- | ---------------------------------------- |
| append-system-prompt         | 14,945c                                  |
| context files                | 1 file, 7,218c (worktree AGENTS.md only) |
| skills prompt section        | 9 visible + 1 hidden, 5,391c             |
| tool schemas (active)        | 38 active / 52 registered, 66,608c       |
| tool guidelines / snippets   | 16,093c / 2,263c                         |
| perk-injected branch context | none (175 entries)                       |
| binding-header copies        | 3                                        |

Two observations worth naming (leads, not verdicts — this record is report-only):
`binding-header-copies=3` where the #1263 closing measured 1 (the 6.1-era double-nudge fix);
and `perk contexts: none` at depth 175 — no live perk context copies on the working branch at
capture (this session ran under the `juicesharp-todo` provider selection; no todo-adapter bridge
context appears in this era).

## Baseline: subagent shape (headless print-mode)

Both variants run from the self-repo root (main checkout — 1 AGENTS.md file). No session file is
persisted for this shape (see the persistence record above).

Default variant:

```
perk: selfcheck — 2.3.0: ok; shared=ok; ambient=reached (append=14945c); agents=reached (files=1)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 14945c
  context-files: 1 file(s), 7218c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=7218c
  skills: 14 visible + 20 hidden; prompt-section=8831c
  tools: 50 active / 52 registered; schemas=77925c; guidelines=22433c; snippets=3075c
    per source: ..=34 (31030c); builtin=4 (2711c); npm:@ff-labs/pi-fff=2 (3123c); npm:@juicesharp/rpiv-ask-user-question=1 (3761c); npm:@juicesharp/rpiv-todo=1 (1936c); npm:pi-subagents=4 (26422c); npm:pi-web-access=4 (8942c)
  branch: 4 entries; binding-header-copies=0
    perk contexts: none; other custom_message ×0 (0c)
```

`--no-skills` variant (only the skills surface changes):

```
perk: selfcheck — 2.3.0: ok; shared=ok; ambient=reached (append=14945c); agents=reached (files=1)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 14945c
  context-files: 1 file(s), 7218c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=7218c
  skills: 0 visible + 0 hidden; prompt-section=0c
  tools: 50 active / 52 registered; schemas=77925c; guidelines=22433c; snippets=3075c
    per source: ..=34 (31030c); builtin=4 (2711c); npm:@ff-labs/pi-fff=2 (3123c); npm:@juicesharp/rpiv-ask-user-question=1 (3761c); npm:@juicesharp/rpiv-todo=1 (1936c); npm:pi-subagents=4 (26422c); npm:pi-web-access=4 (8942c)
  branch: 4 entries; binding-header-copies=0
    perk contexts: none; other custom_message ×0 (0c)
```

Headline numbers:

| Surface                      | Default                            | `--no-skills` |
| ---------------------------- | ---------------------------------- | ------------- |
| append-system-prompt         | 14,945c                            | 14,945c       |
| context files                | 1 file, 7,218c                     | same          |
| skills prompt section        | 14 visible + 20 hidden, 8,831c     | 0 + 0, 0c     |
| tool schemas (active)        | 50 active / 52 registered, 77,925c | same          |
| tool guidelines / snippets   | 22,433c / 3,075c                   | same          |
| perk-injected branch context | none (4 entries)                   | none          |

## Informational comparison vs the #1263 closing

The #1263 closing audit (2026-07-10; perk 1.1.0, pi 0.80.6) is the nearest prior measurement.
Per-shape prompt-construction totals (append-system-prompt + context files + skills section +
active schemas + guidelines + snippets) — informational only; perk 1.1.0 → 2.3.0 and
pi 0.80.6 → 0.84.1 separate the two records:

| Shape              | #1263 closing | This baseline | Delta             |
| ------------------ | ------------- | ------------- | ----------------- |
| Fresh plan session | 46,663c       | 89,965c       | +43,302c (+93%)   |
| Implement session  | 80,494c       | 112,518c      | +32,024c (+40%)   |
| Subagent (default) | 91,277c       | 134,427c      | +43,150c (+47%)   |

Decomposition, per surface:

- **The tool surface dominates the growth.** Registered tools 33 → 52; active: plan 15
  (17,447c) → 24 (52,666c), implement 21 (41,033c) → 38 (66,608c), headless 29 (50,101c) → 50
  (77,925c). Guidelines likewise: implement 6,831c → 16,093c, headless 10,916c → 22,433c. A year
  of feature surface (the wave tools, stacked delivery, learn-harvest, the `@ff-labs/pi-fff`
  borrow, pi-subagents growth 20,937c → 26,422c) — real capability, measured honestly.
- **Ambient index:** 13,408c → 14,945c (+11%; `docs/learned/` corpus growth — the #1263 closing
  predicted this scaling).
- **AGENTS.md:** 6,307c → 7,218c per file; the implement shape's 2-file worktree double-count is
  gone (pi-era change), so the implement context-files row *fell* 12,614c → 7,218c on vantage.
- **Skills prompt section:** stage scoping holds (plan 5,440c → 5,474c; implement
  5,426c → 5,391c); the headless full catalog grew 14+17 (8,782c) → 14+20 (8,831c).
- **Injected-context steady state:** still ×1 per context; plan block 2 total 3,084c → 2,991c.
- **Binding-header copies (implement):** 1 → 3 — a regression lead vs the #1263-closing
  double-nudge fix, left for triage (this record is report-only).

## Frozen session copies

Frozen under `.perk/workflow/scratch/context-baseline-2/` in the main checkout (gitignored
scratch — local comparability anchors, not repo artifacts). Entry counts are parsed entries,
header excluded.

| Shape | Frozen copy | Source session | Entries | sha256 |
|---|---|---|---|---|
| plan | `plan.jsonl` | `~/.pi/agent/sessions/--Users-mattgiles-dev-github-mattgiles-perk--/2026-08-12T02-55-37-807Z_019ff3e5-974f-7f21-ab5a-d1d100a29be0.jsonl` | 10 | `d1708605c182958d66a3c41dda4704d4386525c95c1fa749f12b057abc130519` |
| implement | `implement.jsonl` | `~/.pi/agent/sessions/--Users-mattgiles-dev-github-mattgiles-perk-.worktrees-plan-1611--/2026-08-11T21-58-46-911Z_019ff2d5-d17f-7d36-a5dd-508df45ca33d.jsonl` | 179 | `01cfe7cc4baefc4c97eb4babcc2fc9eae948b04b5edaa5a1c8ce473ef4de18b7` |
| headless default | *(none — print mode persisted no session; see the persistence record)* | — | — | — |
| headless `--no-skills` | *(none — same)* | — | — | — |

The implement freeze was taken immediately after the census capture + block paste, so the frozen
transcript (179 entries) trails the census's branch reading (175) by the paste turn's entries —
recorded, not hidden.

## Attribution reports

`uv run perk-dev audit attribution .perk/workflow/scratch/context-baseline-2/plan.jsonl .perk/workflow/scratch/context-baseline-2/implement.jsonl`
(all `c` here = Python code points of raw JSONL lines; see Units):

```
session: /Users/mattgiles/dev/github/mattgiles/perk/.perk/workflow/scratch/context-baseline-2/plan.jsonl
  entries 10 · chars 5301 · header 164c · malformed 0 line(s) (0c) · off-branch 0 entries (0c)
  kinds:
    custom_message:perk:plan-context: 1 · 1729c
    custom_message:perk:plan-adapter-plannotator: 1 · 1004c
    custom_message:perk:mode-context: 1 · 688c
    message:assistant: 1 · 577c
    custom:perk:workflow-state: 1 · 319c
    custom_message:perk:binding-context: 1 · 285c
    message:user: 1 · 213c
    custom:plannotator: 1 · 209c
    model_change: 1 · 144c
    thinking_level_change: 1 · 133c
  tools:
  read paths:
    docs/learned/: 0 · 0c
    skills/: 0 · 0c
    prompts/: 0 · 0c
    other: 0 · 0c
    unresolved: 0 · 0c
  top 10 results:
session: /Users/mattgiles/dev/github/mattgiles/perk/.perk/workflow/scratch/context-baseline-2/implement.jsonl
  entries 179 · chars 642487 · header 185c · malformed 0 line(s) (0c) · off-branch 0 entries (0c)
  kinds:
    message:toolResult: 99 · 398379c
    message:assistant: 73 · 238680c
    message:user: 2 · 4269c
    custom:perk:workflow-state: 2 · 673c
    custom:plannotator: 1 · 209c
    model_change: 1 · 144c
    thinking_level_change: 1 · 133c
  tools:
    read: 11 · 228604c
    bash: 48 · 75293c
    edit: 13 · 61381c
    todo: 24 · 32058c
    write: 3 · 1043c
  read paths:
    docs/learned/: 0 · 0c
    skills/: 1 · 2008c
    prompts/: 0 · 0c
    other: 10 · 226596c
    unresolved: 0 · 0c
  top 10 results:
    entry 26 · read · 49717c · packages/perk-dev/src/perk_dev/cli.py
    entry 28 · read · 32824c · tests/test_perk_dev_checks.py
    entry 24 · read · 31442c · packages/perk-dev/src/perk_dev/audit/checks.py
    entry 40 · read · 30874c · docs/design/context-payload-baseline.md
    entry 22 · read · 25441c · src/perk/learn/normalize.py
    entry 7 · bash · 15935c
    entry 38 · read · 15456c · docs/developers/session-audit.md
    entry 45 · edit · 14277c
    entry 30 · read · 12616c · packages/perk-dev/src/perk_dev/audit/runner.py
    entry 21 · read · 11447c · src/perk/learn/session_jsonl.py
```

Reading the transcript-composition headline (the objective's new axis, complementing the
prompt-construction census above):

- **Plan (sacrificial, 10 entries, 5,301c):** the four injected perk contexts (3,706c) are ~70%
  of this near-empty transcript — the floor a plan session starts from.
- **Implement (working session, 179 entries, 642,487c ≈ 160k tokens accumulated):** toolResult
  entries carry 398,379c (62%) and assistant entries (thinking + tool calls) 238,680c (37%);
  everything else is noise-level. Within tool results, `read` alone is 228,604c (36% of the whole
  transcript), and the top five file reads account for ~170k chars — single large source files
  dominate accumulation. `docs/learned/` reads: 0 this session; `skills/`: one read (2,008c —
  the delivered `perk-implement` SKILL.md, post-diet). Off-branch: 0 in both shapes (linear
  protocol sessions, as predicted).

## Closing audit (Phase 6)

Node 6.1's re-run of the pinned protocol above, after every diet node landed (2.1–2.4 corpus
curation + the two-tier cluster index, 3.1–3.4 §8.57 single-carrier migrations, 4.1
distillation, 5.1/5.2 committed gates). Same census + attribution instruments, same three
session shapes, same vantages; tables read baseline / closing / delta per surface.

- **Date:** 2026-08-13
- **perk:** 2.3.0 · **pi:** 0.84.1 — both unchanged since the baseline (re-checked at capture).
- **Repo state:** main @ `5a027ca7` for every capture — re-checked after the sacrificial plan
  launch (`--no-sync` held it; main did not move mid-audit, so no dual-SHA census-inertness
  comparison was needed). The implement shape is this node's own implement session (worktree
  `plan-1725`, branched from `5a027ca7`); `.pi/APPEND_SYSTEM.md` and `AGENTS.md` verified
  byte-identical between the main checkout and the worktree, so the main-vantage and
  worktree-vantage blocks read the same ambient + context-file surfaces.
- **Instrument stability, re-verified at the implement SHA:** zero commits touch
  `extension/doors/selfcheck.ts` or the attribution stack (`attribution.py`,
  `session_jsonl.py`, `normalize.py`) since `80913a9a` (the baseline-introducing commit); the
  identical-inputs attribution proof is recorded in the closing manifest below.
- **Recipe deltas: none.** Same shapes, prompts, freeze, and attribution steps; same vantages
  (plan + headless from the self-repo root, 1 AGENTS.md; implement from its linked worktree —
  pi 0.84.1's single-file vantage in both brackets, directly comparable). Capture order was
  headless → sacrificial plan → implement census last (the protocol pins no inter-shape order;
  the shapes are independent sessions). The baseline's recorded one-turn deviation is closed:
  this closing's plan shape captured the pinned **two** completed growth turns.
- **Registry footnote for reading the tables:** one perk-owned tool was added between the
  brackets (`objective_stack_land`; +1,167c of schema) — registered 52 → 53; it is
  write-capable, so the plan shape's active set is unchanged (24) while implement (38 → 39)
  and headless (50 → 51) each gain it. Borrowed-package movement, recorded not engineered
  around: the pi-subagents npm package's schemas shrank 26,422c → 21,286c (same 4 tools — an
  upstream update), and pi-web-access grew slightly (+61c plan, +77c implement/headless). Real
  environment movement, not census drift.

### Closing: fresh plan session

Measured in a sacrificial `perk plan --no-sync` session launched from the self-repo root
(abandoned unsaved; the session JSONL was frozen first, then `perk worktree wipe` cleaned
residue). `/perk-selfcheck` was the literal first input (block 1 — matching the baseline's
block-1 semantics), followed by **two** growth prompts, each exactly
`Reply with only the word: ok`, each turn completing — the two-turn form the baseline flagged
for this node.

Block 1 — fresh at launch (no contexts injected yet):

```
perk: selfcheck — 2.3.0: ok; shared=ok; ambient=reached (append=4808c); agents=reached (files=1)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 4808c
  context-files: 1 file(s), 6140c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=6140c
  skills: 8 visible + 1 hidden; prompt-section=5577c
  tools: 24 active / 53 registered; schemas=47591c; guidelines=8231c; snippets=1431c
    per source: ..=11 (10393c); builtin=3 (1605c); npm:@ff-labs/pi-fff=2 (3123c); npm:@juicesharp/rpiv-ask-user-question=1 (3761c); npm:pi-subagents=4 (21286c); npm:pi-web-access=3 (7423c)
  branch: 4 entries; binding-header-copies=0
    perk contexts: none; other custom_message ×0 (0c)
```

Block 2 — after two trivial completed no-tool growth turns:

```
perk: selfcheck — 2.3.0: ok; shared=ok; ambient=reached (append=4808c); agents=reached (files=1)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 4808c
  context-files: 1 file(s), 6140c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=6140c
  skills: 8 visible + 1 hidden; prompt-section=5577c
  tools: 24 active / 53 registered; schemas=47591c; guidelines=8231c; snippets=1431c
    per source: ..=11 (10393c); builtin=3 (1605c); npm:@ff-labs/pi-fff=2 (3123c); npm:@juicesharp/rpiv-ask-user-question=1 (3761c); npm:pi-subagents=4 (21286c); npm:pi-web-access=3 (7423c)
  branch: 12 entries; binding-header-copies=1
    perk contexts: perk:binding-context ×1 (116c); perk:mode-context ×1 (515c); perk:plan-adapter-plannotator ×1 (696c); perk:plan-context ×1 (1542c); other custom_message ×0 (0c)
```

The plan-shape headline: block 2 is identical to block 1 on every prompt-construction surface,
and every perk context sits at **×1** after two completed growth turns — branch entries grew
4 → 12 (the four launch entries, the four injected contexts, and the two turns themselves);
injected-context copies stayed flat. The discrimination the baseline could not make (its
one-completed-turn deviation) is made here: marker-dedup holds each context at one live copy
across turns, re-proving per-turn flatness at this era (the #1263 closing's finding).

| Surface                      | Baseline (block 2)                 | Closing (block 2)                   | Delta                                          |
| ---------------------------- | ---------------------------------- | ----------------------------------- | ---------------------------------------------- |
| append-system-prompt         | 14,945c                            | 4,808c                              | −10,137c (−68%; the ambient-tier diet)         |
| context files                | 1 file, 7,218c                     | 1 file, 6,140c                      | −1,078c (−15%; the AGENTS.md sweep)            |
| skills prompt section        | 8 visible + 1 hidden, 5,474c       | 8 visible + 1 hidden, 5,577c        | +103c (+2%)                                    |
| tool schemas (active)        | 24 active / 52 registered, 52,666c | 24 active / 53 registered, 47,591c  | −5,075c (−10%; pi-subagents upstream −5,136c)  |
| tool guidelines / snippets   | 8,231c / 1,431c                    | 8,231c / 1,431c                     | unchanged                                      |
| perk contexts after growth   | 4 types, 4 copies, 2,991c (1 turn) | 4 types, 4 copies, 2,869c (2 turns) | −122c (adapter 818c → 696c per copy)           |
| binding-header copies        | 1                                  | 1                                   | unchanged                                      |

### Closing: implement session

Measured live inside this node's own implement session (the human typed `/perk-selfcheck` and
pasted the block; branch depth 61 at capture — load-bearing context, not a comparable number).
Same vantage as the baseline: pi 0.84.1 loads only the worktree's `AGENTS.md` (1 file), so the
rows compare directly — no normalization needed.

```
perk: selfcheck — 2.3.0: ok; shared=ok; ambient=reached (append=4808c); agents=reached (files=1)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 4808c
  context-files: 1 file(s), 6140c — /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-1725/AGENTS.md=6140c
  skills: 9 visible + 1 hidden; prompt-section=5391c
  tools: 39 active / 53 registered; schemas=62716c; guidelines=16967c; snippets=2325c
    per source: ..=23 (20880c); builtin=4 (2711c); npm:@ff-labs/pi-fff=2 (3123c); npm:@juicesharp/rpiv-ask-user-question=1 (3761c); npm:@juicesharp/rpiv-todo=1 (1936c); npm:pi-subagents=4 (21286c); npm:pi-web-access=4 (9019c)
  branch: 61 entries; binding-header-copies=1
    perk contexts: none; other custom_message ×0 (0c)
```

| Surface                      | Baseline                           | Closing                            | Delta                                               |
| ---------------------------- | ---------------------------------- | ---------------------------------- | --------------------------------------------------- |
| append-system-prompt         | 14,945c                            | 4,808c                             | −10,137c (−68%)                                     |
| context files                | 1 file, 7,218c                     | 1 file, 6,140c                     | −1,078c (−15%)                                      |
| skills prompt section        | 9 visible + 1 hidden, 5,391c       | 9 visible + 1 hidden, 5,391c       | unchanged (byte-identical)                          |
| tool schemas (active)        | 38 active / 52 registered, 66,608c | 39 active / 53 registered, 62,716c | −3,892c (−6%; the registry footnote decomposes it)  |
| tool guidelines / snippets   | 16,093c / 2,263c                   | 16,967c / 2,325c                   | +874c / +62c (the added tool's prose)               |
| perk-injected branch context | none (175 entries)                 | none (61 entries)                  | —                                                   |
| binding-header copies        | 3                                  | 1                                  | see below                                           |

The baseline's two leads re-observed (report-only, left for triage): `binding-header-copies`
reads **1** here (depth 61) where the baseline read 3 (depth 175) — the baseline's regression
lead did not reproduce at this depth/flow; whether it was flow-dependent or fixed between the
brackets is not investigated here. And `perk contexts: none` again at working depth — this
session also ran under the `juicesharp-todo` provider selection, with no todo-adapter bridge
context in this era.

### Closing: subagent shape (headless print-mode)

Both variants re-run from the self-repo root (main checkout — 1 AGENTS.md file). The
persistence constraint re-verified, not assumed (the Decision-10 arm): the sessions directory's
file count was identical before and after both runs (877 → 877) — print mode still persists no
session file, so this shape carries census blocks only.

Default variant:

```
perk: selfcheck — 2.3.0: ok; shared=ok; ambient=reached (append=4808c); agents=reached (files=1)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 4808c
  context-files: 1 file(s), 6140c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=6140c
  skills: 14 visible + 20 hidden; prompt-section=8934c
  tools: 51 active / 53 registered; schemas=74033c; guidelines=23307c; snippets=3137c
    per source: ..=35 (32197c); builtin=4 (2711c); npm:@ff-labs/pi-fff=2 (3123c); npm:@juicesharp/rpiv-ask-user-question=1 (3761c); npm:@juicesharp/rpiv-todo=1 (1936c); npm:pi-subagents=4 (21286c); npm:pi-web-access=4 (9019c)
  branch: 4 entries; binding-header-copies=0
    perk contexts: none; other custom_message ×0 (0c)
```

`--no-skills` variant (only the skills surface changes):

```
perk: selfcheck — 2.3.0: ok; shared=ok; ambient=reached (append=4808c); agents=reached (files=1)
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 4808c
  context-files: 1 file(s), 6140c — /Users/mattgiles/dev/github/mattgiles/perk/AGENTS.md=6140c
  skills: 0 visible + 0 hidden; prompt-section=0c
  tools: 51 active / 53 registered; schemas=74033c; guidelines=23307c; snippets=3137c
    per source: ..=35 (32197c); builtin=4 (2711c); npm:@ff-labs/pi-fff=2 (3123c); npm:@juicesharp/rpiv-ask-user-question=1 (3761c); npm:@juicesharp/rpiv-todo=1 (1936c); npm:pi-subagents=4 (21286c); npm:pi-web-access=4 (9019c)
  branch: 4 entries; binding-header-copies=0
    perk contexts: none; other custom_message ×0 (0c)
```

| Surface                      | Baseline (default)                 | Closing (default)                  | Delta            |
| ---------------------------- | ---------------------------------- | ---------------------------------- | ---------------- |
| append-system-prompt         | 14,945c                            | 4,808c                             | −10,137c (−68%)  |
| context files                | 1 file, 7,218c                     | 1 file, 6,140c                     | −1,078c (−15%)   |
| skills prompt section        | 14 visible + 20 hidden, 8,831c     | 14 visible + 20 hidden, 8,934c     | +103c            |
| tool schemas (active)        | 50 active / 52 registered, 77,925c | 51 active / 53 registered, 74,033c | −3,892c (−5%)    |
| tool guidelines / snippets   | 22,433c / 3,075c                   | 23,307c / 3,137c                   | +874c / +62c     |
| perk-injected branch context | none (4 entries)                   | none (4 entries)                   | —                |

The `--no-skills` control behaves exactly as at baseline: skills 0 + 0, 0c; every other surface
identical to the default variant. The headless shape remains the near-control — not a perk
stage session, so no stage scoping applies — and its rows isolate the global diet: the ambient
tier's −10,137c and the AGENTS.md sweep's −1,078c reach every shape whole, because both are
prompt-construction surfaces, not stage-scoped ones.

### Frozen session copies (closing)

Frozen under `.perk/workflow/scratch/context-baseline-2/` beside the baseline anchors
(gitignored local scratch — comparability anchors, not repo artifacts). Entry counts are parsed
entries, header excluded.

| Shape | Frozen copy | Source session | Entries | sha256 |
|---|---|---|---|---|
| plan | `plan-closing.jsonl` | `~/.pi/agent/sessions/--Users-mattgiles-dev-github-mattgiles-perk--/2026-08-13T18-03-16-398Z_019ffc4a-ec2e-7aea-892f-214d53612202.jsonl` | 12 | `cbd707611adbb11af5d14500860917604a06cbc478008059350b0425d452105f` |
| implement | `implement-closing.jsonl` | `~/.pi/agent/sessions/--Users-mattgiles-dev-github-mattgiles-perk-.worktrees-plan-1725--/2026-08-13T17-58-51-970Z_019ffc46-e342-75e4-acec-95df7efd9e00.jsonl` | 65 | `ec489443a945867a31e65ee988f7ce685d0a75f3c9bba193c5fcefaf9ddeba33` |
| headless default | *(none — print mode persisted no session; the persistence record above)* | — | — | — |
| headless `--no-skills` | *(none — same)* | — | — | — |

Baseline-anchor verification at capture time: `plan.jsonl` and `implement.jsonl` re-hashed to
exactly the baseline manifest's sha256s, and re-running `perk-dev audit attribution` over those
identical inputs reproduced the transcribed baseline reports exactly — the instrument-stability
proof over identical inputs.

The implement freeze was taken immediately after the census capture + block paste, so the
frozen transcript (65 entries) trails the census's branch reading (61) by the paste turn's
entries — recorded, not hidden (the baseline's 179-vs-175 precedent).

### Attribution reports (closing)

`uv run perk-dev audit attribution .perk/workflow/scratch/context-baseline-2/plan-closing.jsonl .perk/workflow/scratch/context-baseline-2/implement-closing.jsonl`
(attribution `c` = Python code points of raw JSONL lines; see Units):

```
session: /Users/mattgiles/dev/github/mattgiles/perk/.perk/workflow/scratch/context-baseline-2/plan-closing.jsonl
  entries 12 · chars 6026 · header 164c · malformed 0 line(s) (0c) · off-branch 0 entries (0c)
  kinds:
    custom_message:perk:plan-context: 1 · 1729c
    message:assistant: 2 · 1187c
    custom_message:perk:plan-adapter-plannotator: 1 · 881c
    custom_message:perk:mode-context: 1 · 688c
    message:user: 2 · 426c
    custom:perk:workflow-state: 1 · 319c
    custom_message:perk:binding-context: 1 · 285c
    custom:plannotator: 1 · 234c
    model_change: 1 · 144c
    thinking_level_change: 1 · 133c
  tools:
  read paths:
    docs/learned/: 0 · 0c
    skills/: 0 · 0c
    prompts/: 0 · 0c
    other: 0 · 0c
    unresolved: 0 · 0c
  top 10 results:
session: /Users/mattgiles/dev/github/mattgiles/perk/.perk/workflow/scratch/context-baseline-2/implement-closing.jsonl
  entries 65 · chars 142131 · header 185c · malformed 0 line(s) (0c) · off-branch 0 entries (0c)
  kinds:
    message:toolResult: 33 · 83330c
    message:assistant: 24 · 53048c
    message:user: 3 · 4569c
    custom:perk:workflow-state: 2 · 673c
    custom:plannotator: 1 · 234c
    model_change: 1 · 144c
    thinking_level_change: 1 · 133c
  tools:
    todo: 15 · 32360c
    bash: 16 · 28224c
    read: 2 · 22746c
  read paths:
    docs/learned/: 0 · 0c
    skills/: 1 · 1412c
    prompts/: 0 · 0c
    other: 1 · 21334c
    unresolved: 0 · 0c
  top 10 results:
    entry 10 · read · 21334c · docs/design/context-payload-baseline-2.md
    entry 7 · bash · 13914c
    entry 33 · bash · 3450c
    entry 59 · todo · 2576c
    entry 46 · todo · 2513c
    entry 58 · todo · 2462c
    entry 38 · todo · 2461c
    entry 19 · todo · 2420c
    entry 45 · todo · 2411c
    entry 24 · todo · 2410c
```

Before/after transcript-composition reading (the objective's new axis):

- **Plan (sacrificial, 12 entries, 6,026c):** the four injected perk contexts sum 3,583c —
  ~59% of the near-empty transcript (baseline: 3,706c, ~70% of 5,301c). The injected floor a
  plan session starts from shrank −123c (the plannotator adapter's raw line 1,004c → 881c),
  and the two completed growth-turn pairs total only 1,613c of user + assistant lines — after
  which the floor still dominates. Per-turn flatness is the census's finding above; here it
  reads as: two growth turns added **zero** context re-injections.
- **Implement (working session, 65 entries, 142,131c ≈ 36k tokens accumulated):** the
  composition split is unchanged from the baseline — toolResult 83,330c (59% vs 62%) and
  assistant 53,048c (37% vs 37%); everything else noise-level. Depth (65 vs 179 entries) is
  workload, not protocol: the two audit sessions did different amounts of work; the ratios,
  not the totals, are the comparable reading. Read-path classes: `docs/learned/` 0 reads
  again; `skills/` one read — 1,412c, the delivered `perk-implement` SKILL.md, vs 2,008c at
  baseline (the skill diet visible from the transcript side); `other` one read (21,334c —
  this baseline doc itself). Off-branch: 0 in both shapes (linear protocol sessions, again).

### Soft-target reconciliation

One verdict per objective soft target, each citing measured evidence from the closing blocks.

| # | Soft target | Verdict | Measured evidence |
| - | ----------- | ------- | ----------------- |
| 1 | Ambient routing tier ≤ ~8KB; per-new-doc ambient cost = one slug token | **Met** | `append-system-prompt=4808c` in all five closing blocks (baseline 14,945c; −68%); `.pi/APPEND_SYSTEM.md` = 4,873 bytes at the capture state (`wc -c`); the routing block itself measures 3,821 bytes (`perk learn docs-check --json` → `ambient_routing_bytes`) against the committed `AMBIENT_ROUTING_BLOCK_MAX_BYTES = 5,120` gate (`src/perk/learn/docs_sync.py`, enforced in `tests/test_learned_docs_cues.py`) — the whole ambient file sits at ~60% of the ~8KB target. The per-new-doc half reconciles structurally (the landed two-tier renderer contract — no throwaway-doc experiment): the registry-mode routing block renders **one line per cluster** (`- **<id>** — <rollup> (<category>/<slug>, …)`), so a new doc joining an existing cluster contributes exactly one `category/slug` member token; only a genuinely new cluster adds a line — and the block stays under the same CI-gated ceiling either way. |
| 2 | One statement per stage contract per session shape | **Met** | §8.57 (contracts.md) is the canonical layering rule — one carrier per contract statement per stage; the 3.2/3.3/3.4 migrations landed it across the stage families, and gates #2/#3 (`tests/test_prompt_surface_budgets.py`: `SKILL_AMBIENT_DESCRIPTION_MAX_BYTES = 896`; `SEED_TEMPLATE_MAX_BYTES = 9,088` + `INJECTED_CONTEXT_TEMPLATE_MAX_BYTES = 1,984`) are the standing enforcement that keeps carrier regression loud. Measured corroboration from the closing blocks: the plan shape's per-context payloads — mode 515c, plan 1,542c, adapter 696c (baseline 818c), binding 116c — each at **×1** after two completed growth turns, and the skills prompt sections held flat (plan 5,474c → 5,577c; implement 5,391c → 5,391c): the migrations moved prose between carriers without growing the injected surfaces. |
| 3 | Attribution recorded baseline and closing | **Met** | Four attribution report blocks stand in this doc — plan + implement at each bracket ("Attribution reports" above; "Attribution reports (closing)" here) — plus the identical-inputs re-run recorded in the closing manifest. The pinned headless persistence constraint restated: pi print mode persists no session file (the assistant-gated flush), so attribution structurally covers the two persisting shapes at both brackets; the headless shape carries census blocks only. |

### Closing headline deltas

Per-shape prompt-construction totals (append-system-prompt + context files + skills section +
active schemas + guidelines + snippets) — this objective's bottom line, closing vs its own
baseline (the informational #1263 comparison lives in the baseline section above and is not
recomputed):

| Shape              | Baseline | Closing  | Delta            |
| ------------------ | -------- | -------- | ---------------- |
| Fresh plan session | 89,965c  | 73,778c  | −16,187c (−18%)  |
| Implement session  | 112,518c | 98,347c  | −14,171c (−13%)  |
| Subagent (default) | 134,427c | 120,359c | −14,068c (−10%)  |

- **The ambient + context-file diet is the whole story:** −10,137c (append-system-prompt) and
  −1,078c (AGENTS.md) land in every shape — −11,215c of each row's delta; the rest is
  tool-surface movement (pi-subagents upstream −5,136c against the added perk tool's
  +1,167c/+874c/+62c of schema/guidelines/snippets in the write shapes) and +103c of
  skills-section drift in the plan/headless shapes.
- **The tool surface remains the dominant absolute component** (47,591–74,033c of schemas per
  shape) — the baseline's decomposition still holds; this objective's diet deliberately did
  not target it (the leads stand, report-only).
- **Injected-context steady state:** ×1 per context, now re-proven across two completed growth
  turns; the plan shape's four-context total reads 2,869c (baseline 2,991c) and no longer
  carries an unproven-flatness caveat.
