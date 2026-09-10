# Dogfood: `perk.scout` delivery (Objective #2353, Node 1.1)

**Status:** validation record (the `borrowed-askuser-todo-dogfood` / `remote-runner-consumer-dogfood`
genre) — the **phase-1 delivery gate** of Objective #2353: the repo-local `perk-dev.analyst` promoted
into the delivered `perk.scout` read-only analysis lane. Two legs: one dev-session `perk.scout`
spawn through the direct `subagent` leniency (no perk-owned launcher exists yet — that is node 2.1),
and one fresh-consumer `perk init` / idempotent re-init / clean `perk doctor` transcript in a scratch
repo converged by the dev checkout's CLI. Part A is the repeatable procedure; Part B is the captured
evidence. Both legs **PASSED** on the first attempt; the one deviation (the engine's artifact
location) is a plan-text expectation mismatch, not a defect.

## Context

| | |
| --- | --- |
| Date | 2026-09-10 |
| perk version (`pyproject.toml`) | 3.2.0 |
| pi-subagents (`.pi/npm/node_modules/pi-subagents/package.json`) | 0.66.0 |
| Worktree revision the legs ran at | `c81f4ac3` (branch HEAD) + this PR's not-yet-committed implementation diff (the `agents/scout.md` def, the `PERK_AGENTS` entry, the reconverged `.pi/agents/perk/scout.md` mirror) |
| Dev host | macOS, `uv`-managed CPython 3.13, node v26.3.0 |

## Part A — the repeatable procedure

Each step names its actor: **(session)** for what the implement session runs itself, **(human)**
for what a session cannot take. Both legs are session-driven; the human's part is reading the
verdicts.

### Leg 1 — the dev-session spawn

Run inside the implement session **after** the mirror has been reconverged (`uv run perk init`;
`cmp agents/scout.md .pi/agents/perk/scout.md` silent). Agent discovery is live-filesystem, so the
freshly delivered def is spawnable in the same session.

1. **(session)** `subagent({ action: "list", capabilities: true })` — the `perk.scout` row must
   appear under *Project agents* as executable (not disabled).
2. **(session)** One direct spawn — `async` **omitted** (the def's `async: true` selects the
   background runner-hosted profile), `context: "fresh"`, `acceptance: { level: "none", reason:
   "report-only scout lane" }` (the sanctioned disable), `agent: "perk.scout"`, and this task
   verbatim:
   > Verify these claims against this checkout and report. (1) `src/perk/convergence/init/agents.py::PERK_AGENTS` contains `scout` and the tuple is sorted. (2) `.pi/agents/perk/scout.md` is byte-identical to `agents/scout.md` (compare with `cmp` or `git hash-object`). (3) No file exists at `.pi/agents/perk-dev/analyst.md`. Report format — a markdown list, one line per claim: `<n>. <verified|refuted|inferred> — <pointer> — <one-line rationale>`, then a final line `open questions: <none|…>`. Nothing else.
3. **(session)** On the native completion notice, record from the run's `_meta.json` artifact
   (installed 0.66.0 layout: `<pi session dir>/subagent-artifacts/<runId>_perk.scout_{input,meta,output,transcript}.*`;
   the run dir named by `subagent({ action: "status", id })` carries `status.json` with
   `steps[0].durationMs`): the run id, the agent name, the model, the duration; from the output
   artifact: the returned report verbatim; note whether it matched the requested shape.
4. **(session)** If the background launch fails on the dev host, record the failure verbatim (NOT
   PASSED for the background arm), then retry once with `async: false` as a labelled deviation
   (foreground — no ambient perk, no floor) and record that arm separately. The foreground retry
   never counts as a PASS for the background arm.

### Leg 2 — the fresh consumer

From a shell, **never inside an occupied plan worktree's tree**, with `PERK` set to the absolute
path of the plan worktree (the dev checkout's CLI resolves the editable `agents/` for delivery):

```sh
SCRATCH="$(mktemp -d)" && cd "$SCRATCH" && git init -q && git commit --allow-empty -qm seed
uv run --project "$PERK" perk init --no-interactive; echo "exit=$?"        # first init
ls .pi/agents/perk/ && cmp .pi/agents/perk/scout.md "$PERK/agents/scout.md" && echo byte-identical
uv run --project "$PERK" perk init --no-interactive; echo "exit=$?"        # second init
uv run --project "$PERK" perk doctor --verbose; echo "exit=$?"
cd / && rm -rf "$SCRATCH"
```

Gate criteria: the first init's `Converged:` (or `Converged before failure:`) list contains
`.pi/agents/perk/scout.md: created` and `cmp` is silent; the second init reports no
`.pi/agents/perk/*` change; `perk doctor` exits 0 with the `subagent-agents` row `ok`. Every
`warn`/`info` row and every change line outside the `subagent-agents` capability is recorded
verbatim as environment noise. A `fail` row, a non-zero `doctor` exit, or a missing/mismatched
scout file is NOT PASSED. Close with the teardown proof: the scratch dir is gone and
`git status --porcelain` in the worktree shows only the intended files.

### Gate outcome policy

The record is authored and committed in every case, including NOT PASSED legs. Every NOT PASSED
leg is classified **perk-attributable** (this PR's edits or perk's own convergence/doctor/delivery
code — blocks `/submit`; fix, re-run that leg, append the re-run as a new dated attempt) or
**environment-attributable** (dev-host/network/credentials, the unpublished npm pin, an upstream
pi-subagents defect — does not block `/submit`; the Deviations section names the repair owner and
landing is the human reviewer's call). The node's `done` audit cites the per-leg verdicts below.

## Part B — the captured evidence

### Leg 1 — the dev-session spawn (attempt 1, 2026-09-10)

**Step 1 — capability listing.** The `perk.scout` row, verbatim from the tool's *Project agents*
section (twelve project rows: eleven `perk.*` + `perk-dev.session-auditor`; no `perk-dev.analyst`):

```
- perk.scout (project): Description: General-purpose read-only analysis lane with no fixed rubric — each spawn's task defines the entire scope (audit a file slice, verify claims against the checkout, census a pattern, summarize a subsystem). It explores read-only and report...; Tools: read, grep, find, ls, bash; Model: openai/gpt-5.6-terra; Thinking: default
```

**Step 2 — the spawn.** `subagent({ agent: "perk.scout", context: "fresh", acceptance: { level:
"none", reason: "report-only scout lane" }, task: <verbatim> })`. The launch reply:

```
Run fan-out: 1/64 used, 63 remaining
Async: perk.scout [1313ace3-9160-4c09-9c53-4b5d06d292d9]
The async run is detached and running in the background.
```

The definition-owned `async: true` selected the background runner-hosted profile without a
spawn-time `async` flag — the profile fact under proof.

**Step 3 — the completion.** The native completion notice arrived while leg 2's first init was
running (~14 s after launch). From `status.json` and the
`1313ace3-…_perk.scout_meta.json` artifact:

| Field | Value |
| --- | --- |
| `runId` | `1313ace3-9160-4c09-9c53-4b5d06d292d9` |
| `agent` | `perk.scout` |
| `model` / `attemptedModels` | `openai/gpt-5.6-terra` / `["openai/gpt-5.6-terra"]` (primary served; the luna fallback was never attempted) |
| duration (`status.json` → `steps[0].durationMs`; the `_meta.json` carries only `timestamp`) | `14006` ms (the subagent log renders it `14.0s`) |
| `steps[0].context` | `fresh` |
| `acceptance` | `status: not-required`, `effectiveAcceptance.level: none`, `explicit: true`, `reason: "report-only scout lane"`; the engine's own `inferredReason: ["read-only/reviewer-style agent"]` agreed |
| `exitCode` | `0` |
| `usage` | input 6 / output 235 / cacheRead 3433 / cacheWrite 4425 tokens, 2 turns, cost $0.0146 |
| `skills` | `[]` (no inherited skills — `inheritSkills: false`) |
| Tools the child ran (from `output-0.log`) | `read: src/perk/convergence/init/agents.py`; `bash: cmp -s .pi/agents/perk/scout.md agents/scout.md; …` (one read, one read-only bash — no edit, no write, no spawn) |

The returned report, verbatim (`…_perk.scout_output.md`, byte-identical to the tail of
`output-0.log` and to the completion notice's summary):

```
1. verified — `src/perk/convergence/init/agents.py::PERK_AGENTS` — contains `"scout"` and is lexicographically sorted.
2. verified — `.pi/agents/perk/scout.md` and `agents/scout.md` — `cmp -s` exited 0, confirming byte-identical contents.
3. verified — `.pi/agents/perk-dev/analyst.md` — path does not exist.
open questions: none
```

Shape check: exactly the requested markdown list (one `<n>. <verified|refuted|inferred> — <pointer>
— <rationale>` line per claim) plus the `open questions:` line, with nothing before or after — the
"final message is the report" protocol honored; all three claims independently true on the checkout.

**Step 4 — foreground retry:** not needed (the background arm passed).

**Verdict — Leg 1: PASSED** (background arm; no foreground arm run).

### Leg 2 — the fresh consumer (attempt 1, 2026-09-10)

Scratch repo: `/var/folders/…/T/tmp.ZdfONFi0c1` (a `mktemp -d` outside every checkout), seeded with
one empty commit, no remotes.

**First init**, verbatim (exit 0):

```
✓ perk init (consumer)
  ✓ git /usr/bin/git
  ✓ gh /opt/homebrew/bin/gh
  ✓ node v26.3.0
  ✓ pi /Users/mattgiles/.local/share/mise/installs/node/26.3.0/bin/pi
  ✓ skills /opt/homebrew/bin/skills
  ✓ ast-grep /Users/mattgiles/.local/bin/ast-grep
Converged:
  - .pi/settings.json: added npm:@mgiles/perk@3.2.0, npm:@tombell/pi-diff, npm:pi-subagents, npm:@ff-labs/pi-fff, npm:@juicesharp/rpiv-ask-user-question, npm:@juicesharp/rpiv-todo, npm:@dietrichgebert/ponytail, npm:pi-web-access; filtered npm:@dietrichgebert/ponytail; subagents: disableBuiltins=true; tuiMode: fullscreen
  - .perk/workflow/: created
  - .pi/agents/perk/adversarial-reviewer.md: created
  - .pi/agents/perk/conflict-resolver.md: created
  - .pi/agents/perk/draft-reviewer.md: created
  - .pi/agents/perk/dream-analyst.md: created
  - .pi/agents/perk/dream-reducer.md: created
  - .pi/agents/perk/harvest-analyst.md: created
  - .pi/agents/perk/learn-analyst.md: created
  - .pi/agents/perk/objective-explorer.md: created
  - .pi/agents/perk/pr-reviewer.md: created
  - .pi/agents/perk/review-classifier.md: created
  - .pi/agents/perk/scout.md: created
  - .pi/agents/: created
  - .agents/manifest.d/perk.yaml: created
  - .github/workflows/perk-run.yml: created
  - .github/actions/perk-remote-setup/action.yml: created
  - .perk/required-perk-version: created
  - .gitignore: created
  - AGENTS.md: created
  - .perk/config.toml: created
  - .perk/local.toml: created
  - .perk/managed-state.toml: recorded
  - .agents/skills/: synchronized via skills update --sync
  - .pi/npm/node_modules/@mgiles/perk: installed @mgiles/perk@3.2.0 (perk-owned)
✓ GitHub: mattgiles
exit=0
```

`ls .pi/agents/perk/` listed the eleven delivered defs (`adversarial-reviewer.md` …
`review-classifier.md`, `scout.md`); `cmp .pi/agents/perk/scout.md "$PERK/agents/scout.md"` was
silent (`byte-identical`, exit 0).

**Second init**, verbatim (exit 0) — no `.pi/agents/perk/*` line; the only change line is the
skills sync re-running, which is environment noise (the `skills` CLI re-synchronizes unconditionally):

```
Converged:
  - .agents/skills/: synchronized via skills update --sync
✓ GitHub: mattgiles
exit=0
```

**`perk doctor --verbose`** (exit 0, `✓ healthy (34 ok)`, zero `fail` rows). The gate rows:

```
   ✓ subagent-engine: … delivered defs: perk.adversarial-reviewer, perk.conflict-resolver, perk.draft-reviewer, perk.dream-analyst, perk.dream-reducer, perk.harvest-analyst, perk.learn-analyst, perk.objective-explorer, perk.pr-reviewer, perk.review-classifier, perk.scout; …
   ✓ subagent-agents: subagent-agents converged
   ✓ artifact-health: 8 managed artifacts up-to-date
```

Every non-`ok` row, verbatim — all environment noise for a remote-less scratch repo with no
pi launch yet:

```
   ⚠ github-repo: no GitHub repo — no git remotes found
   • runner-enabled: remote runner enabled (PERK_ENABLED unset → default-on)
   • runner-pat-secret: could not verify PERK_GH_PAT (insufficient permission?)
   • runner-model-secret: could not verify model credential
   • runner-workflow-permissions: could not verify workflow permissions — advisory — perk's runner pushes with a PAT, not github.token
   • subagent-compat: pi-subagents not installed — compatibility not evaluated — pi lazy-installs the unpinned npm:pi-subagents borrowed package at launch (.pi/npm/node_modules/pi-subagents)
   • ponytail-compat: Ponytail not installed — compatibility not evaluated — pi lazy-installs the all-disabled npm:@dietrichgebert/ponytail package at launch
```

Note: the unpublished-dev-pin concern the plan anticipated did not materialize — `@mgiles/perk@3.2.0`
resolved and installed (`extension-install: @mgiles/perk installed at the pinned version`), since
3.2.0 is the current published version.

**Teardown proof:**

```
$ cd / && rm -rf "$SCRATCH" && ls -d "$SCRATCH"
ls: /var/folders/90/b55dzd451137c93rcngpgdh00000gp/T/tmp.ZdfONFi0c1: No such file or directory
```

`git status --porcelain` in the worktree afterwards listed only this PR's intended files (the
`agents/scout.md` def, the `.pi/agents/perk/scout.md` mirror, the `.perk/managed-state.toml`
record, the deleted `.pi/agents/perk-dev/analyst.md`, and the source/test/docs edits) — no scratch
residue, no `.pi-subagents/` or `.perk/local.toml` staged (both gitignored).

**Verdict — Leg 2: PASSED.**

### Claim → evidence checklist

| Claim | Evidence |
| --- | --- |
| `perk.scout` is discoverable in a dev session after `perk init` | Leg 1 step 1 listing row |
| The def's `async: true` selects the background profile with no spawn-time flag | Leg 1 step 2 launch reply (`Async: perk.scout [1313ace3-…]`) |
| The lane runs fresh-context, read-only, acceptance-suppressed, on the pinned primary model | Leg 1 `status.json` / `_meta.json` table (`context: fresh`, tools read+bash only, `acceptance.level: none`, `openai/gpt-5.6-terra`) |
| The lane honors "final message is the report" in the task-specified shape | Leg 1 report verbatim + shape check |
| A fresh consumer receives `scout.md` byte-identical to the source | Leg 2 first init `created` line + silent `cmp` |
| Delivery is idempotent | Leg 2 second init (no `.pi/agents/perk/*` change) |
| `perk doctor` sees the delivery as converged, with `scout` in its census | Leg 2 doctor rows (`subagent-agents` ok; `subagent-engine` lists `perk.scout`) |

## Verdicts

| Leg | Verdict | Root-cause class |
| --- | --- | --- |
| 1 — dev-session spawn (background arm) | **PASSED** | — |
| 2 — fresh consumer (init / re-init / doctor) | **PASSED** | — |

## Deviations

- **Artifact location (plan-text expectation, not a defect; no repair owner).** The plan's Part A
  said the per-child artifacts land under the cwd's `.pi-subagents/artifacts/<runId>_<agent>_<i>_meta.json`.
  On the installed pi-subagents 0.66.0 a single async run writes them to
  `<pi session dir>/subagent-artifacts/<runId>_perk.scout_{input,meta,output,transcript}.*` (no `_<i>`
  index) and its run bookkeeping to `$TMPDIR/pi-subagents-uid-<uid>/async-subagent-runs/<runId>/`
  (`status.json`, `output-0.log`, `events.jsonl`); the worktree had no `.pi-subagents/` at all. The
  `_meta.json` carries no duration field — `status.json`'s `steps[0].durationMs` is the duration
  source. Part A step 3 above is written against the observed layout.
- **Skills sync re-runs on every init** (environment noise, pre-existing, outside the gate): the
  second init's sole change line was `.agents/skills/: synchronized via skills update --sync`, so
  "Already converged (no changes)." was not reached even though every perk-owned convergence was
  a no-op. Recorded, not chased.
- **Reconverging the dev worktree** hit the documented pre-existing skills-sync `conflict`
  (`skills_sync_failed`, exit 2) — the `subagent-agents` convergence and the managed-state record
  ran first (`Completed before failure: .pi/agents/perk/scout.md: created`, `.perk/managed-state.toml:
  updated`), `cmp` was silent and the self-repo `perk doctor` reported `✓ healthy (39 ok)` with
  `subagent-agents: subagent-agents converged`. Non-blocking per the learned doc's process note.

## Teardown proof

Scratch dir removed (the `ls -d` above fails with *No such file or directory*); no fixture is kept —
leg 2 is re-runnable from scratch at any revision. The dev-session spawn left only the engine's own
per-run bookkeeping under the pi session directory and `$TMPDIR` (outside the checkout), plus
nothing in the worktree.
