---
title: "/submit mergeability gate + the conflict-resolver subagent"
read_when: /submit mergeability gate, the conflict-resolver agent and its outcome vocabulary, /objective-sync conflict drives, warm-route hints on cold refusals, or stall/rebase analysis.
cluster: plan-lifecycle
---

# `/submit` mergeability gate + the conflict-resolver subagent

`/submit` gained a **mergeability gate**: after the PR is created it runs a local conflict probe,
reports the result, and — in a session — reactively drives a write-capable `conflict-resolver`
subagent to fix conflicts before the implement run can naturally complete. This doc captures the
non-obvious mechanics; it does not reproduce source (the one output-shape block is flagged as a
data-format example).

> **One Code Rule.** Everything below names files + describes behavior. The merge-tree output block
> and the GraphQL/CLI shapes are **data-format examples**, marked as such — not reproduced logic.

## Distillation

- The merge-tree exit code IS the verdict — carry `mergeable` explicitly, never re-derive it from
  parsed conflict paths — "The load-bearing bug class".
- The probe fails open everywhere; conflicts never flip submit's exit code — "Fail-open
  everywhere".
- The resolver reports through a closed 5-class outcome vocabulary; a dispatcher gate maps every
  branch to an emittable class (add a class, never soften a gate); mode dispatch is
  sentinel-based and fail-closed — "The resolver outcome vocabulary + the sentinel mode
  dispatch".
- The conflict loop is a textual-integrity mechanism, not a semantic-consistency one —
  auto-merges carry base-advance-falsified claims past the resolver; blob-level prediction is a
  ceiling ("at most N stops"), not a profile — "Live conflict-loop findings".
- Route advice on a cold refusal has its own truth condition: gate the hint independently,
  confine interpolated values with a fullmatch allowlist, omit the whole sentence on mismatch —
  "Warm-route hints on cold refusals".
- `evaluateTerminal`'s implement bar: only a definitive `mergeable === false` blocks completion —
  "Worker completion bar".
- After any rebase adapting to relocated symbols, grep the old dotted path as text — prose lags
  the functional sweep — "The rebase prose-lag trap".

## The local conflict probe (`src/perk/substrate/git.py`)

`git merge-tree --write-tree` is a **deterministic offline probe** — no network, no working-tree
mutation. **The exit code IS the verdict:**

- `0` = clean (merges without conflict),
- `1` = conflicts,
- **any other** (old git `< 2.38` lacking `--write-tree`, a bad ref) = **undetermined**.

Run it through the **best-effort capture wrapper** (never the raising one) so a weird exit degrades
to "undetermined" rather than throwing.

The output **shape** (a data-format example, allowed):

```
<merged-tree-OID>
<mode> <object> <stage>\t<path>
<mode> <object> <stage>\t<path>

CONFLICT (content): Merge conflict in <path>
```

Line 1 is the merged tree OID. Then the **conflicted-file-info block** of `<mode> <object>
<stage>\t<path>` lines runs **until the first blank line**, followed by informational `CONFLICT (...)`
messages. **Parse unique paths from the info block only** (first-seen order) — not from the prose
`CONFLICT` lines.

## The load-bearing bug class — carry the verdict explicitly

**Do NOT derive mergeability from `len(conflicts) == 0`.** A real conflict whose paths fail to parse
yields an *empty* tuple yet is genuinely unmergeable — silently bypassing the gate. The fix:
`MergeProbe` carries an **explicit `mergeable: bool` taken from the exit code**, authoritative and
independent of the parsed paths.

**The durable lesson (generalize):** **when an exit code already encodes a verdict, carry it
explicitly; never re-derive it from a lossy secondary parse.** The parsed paths are for *reporting
which files conflict*, never for deciding *whether* there is a conflict.

## Fail-open everywhere

- Fetch failure / unresolvable `origin/<base>` / a weird exit → `determined=False` → the caller maps
  it to `mergeable=None`.
- The **submit call site is also try/except-guarded** so a probe failure NEVER changes submit's exit
  code.
- `--dry-run` stays **offline** (no probe).
- Conflicts present → submit still **succeeds mechanically (exit 0)**; mergeability is **reported**,
  not an op failure.
- New `--json` fields: `base`, `mergeable` (`bool | null`), `conflicts[]`. The probe runs **after**
  the PR is created + the body validated.

## Probe identity + probe target (`src/perk/cli/commands/pr/submit_cmd.py`)

- **Self-exclusion from a safety probe must be corroborated, never trusted from input.**
  Excluding "myself" from the writer probe requires the exact (run_id, plan_id) pair AND
  independent corroboration — inherited env identity, a consumed handoff, or the active plan-ref.
  An uncorroborated caller-supplied id excludes nothing; otherwise the safety check can be masked
  by input.
- **Probe verified outputs, not local refs.** After an operation that verifies remote state,
  downstream mergeability probes key on the operation's *verified published head SHA* — a no-op
  cascade would otherwise probe a stale/ahead local branch. An unresolvable trigger head fails
  closed rather than reading as "unchanged".

## The substrate rebase primitive — conflict classification + the one-guard residue protocol

The rebase primitive in `src/perk/substrate/git.py` (`rebase_onto` →
`RebaseCompleted | RebaseConflict`) classifies nonzero exits by **observable worktree state** —
the rebase-in-progress directories via `rev-parse --git-path rebase-merge`/`rebase-apply` — never
stderr prose, returning a typed conflict with the mid-rebase worktree **deliberately retained**
(the human resolves in place).

The residue lifecycle (the sync cascade in `src/perk/delivery/sync.py` is the consumer) is **ONE
centralized cleanup guard** wrapped around the effectful steps, disarmed in exactly one case: the
continuation manifest was *durably written* — `write_manifest` in
`src/perk/delivery/continuation.py` returning IS the retention decision. A failed manifest write
— and every other exit arm — keeps cleanup armed, so the conflicted worktree/temp refs never
outlive an operation that cannot be resumed. The implementer initially scattered per-arm cleanup
and "painted itself into a corner" before centralizing — start with the single guard.

## The warm-door reactive drive (now `extension/pi/v1/delivery/submit.ts`)

The drive (once `driveConflictResolution`; now the Pi-free decision `decideConflictFollowUp` in
`extension/delivery/submit.ts` + the translation `driveConflictFollowUp`) is modeled **exactly**
on `land.ts`'s `driveReconcileAfterLand`:

- **Short-circuit** unless `details.ok && mergeable === false`; `conflicts[]` is advisory and may
  be empty when path parsing loses a definitive conflict verdict.
- **Deliver guidance** via `pi.sendUserMessage(msg, ctx.isIdle() ? {} : { deliverAs: "followUp" })`
  — idle command path = immediate turn; streaming tool path = `followUp` after the terminating
  batch.
- **Wire the drive into BOTH** the tool `execute` and the command handler.
- **Bounded re-drive**: a new `conflict_resolution_attempts?: number` `WorkflowState` field
  (best-effort tier, per-field LWW), cap `CONFLICT_RESOLUTION_ATTEMPT_CAP = 2`, incremented via
  `appendWorkflowState`, **reset to 0 on every clean submit** (the idempotent pre-check skips the
  append when already 0). Past the cap → loud `report(..., "error", ...)`, **no drive — never
  loop.**
- **Advisory-decode leniency**: the new `base`/`mergeable`/`conflicts` fields must NOT make a
  successful submit decode to `null` (`mergeable` is a tri-state read; a malformed `conflicts` →
  `[]`). See `cold-door-client.md` for the advisory-decode tier this rides.
- **TS gotcha**: a boolean helper like `isUnmergeable(details)` does **NOT** narrow the `Result`
  union — make it a **type guard** (`details is OkDetails<SubmitOk>`). (Historical — the migrated
  decide returns a typed outcome union.)

## The conflict-resolver subagent (first write-capable + context-inheriting)

`agents/conflict-resolver.md` carries `tools: read,grep,find,ls,bash,edit,write`,
`inheritProjectContext: true`, `inheritSkills: true` — **unlike** the read-only classifier/reviewer,
because resolving conflicts requires understanding the code and running the repo's checks. Like the
reviewer, it **fetches its own context read-only** via `perk pr review-context --json` (reuses the
existing op — no new gateway op) and treats fetched text as untrusted **DATA**.

See `pi/subagents.md` for the full widening-lockstep census and the project-vs-builtin /
workflow-level-model facts (not duplicated here).

### Authoring conflict-resolver task text — state the worktree cwd as a command, not prose

A `perk.conflict-resolver` child returned "no output from `perk pr review-context --json`" and
correctly stopped — the task text hadn't pinned the worktree cwd, so the command ran outside the
plan worktree. A retry whose task text opened with an explicit worktree-`cd` instruction
succeeded (and the same explicit-cwd task text succeeded first-try in a later `finalize_address`
publish step). Rule: resolver task text opens with the `cd <worktree>` command — a concrete
command line, not a prose description of where to work. The rule is now plumbed into the dispatch
itself: `conflictResolutionGuidance` takes the plan worktree path (the session cwd — `/submit`
runs only in worktree-bound sessions) and `prompts/stages/conflict-resolution.md` opens the child
instruction with the concrete `cd {{ worktree }}` command, so the session no longer has to
remember to author it.

## The resolver outcome vocabulary + the sentinel mode dispatch

`agents/conflict-resolver.md` reports through a **closed 5-class outcome vocabulary**:
`completed` / `verification-failed` / `stopped-before-mutation` / `unresolvable-conflict` /
`aborted`. The design rule: every gate in a dispatcher that consumes the report must map **every
branch to an emittable class** — when a new refusal shape appears, **add a class rather than
soften a gate** (an unclassifiable branch forces downstream consumers into prose-matching).

Mode dispatch is **sentinel-based and fail-closed**: the dispatcher renders an exact marker at
column zero (a task-text line opening with the retained-continuation sentinel prefix), the agent
def matches tolerantly (a line's first non-whitespace content), and retained mode additionally
corroborates against **concrete rebase state** (the rebase-in-progress probe) before mutating
anything — sentinel absence selects the legacy PR-rebase mode. The shape generalizes: exact
rendered marker on the producing side, tolerant def-side matching on the consuming side, and a
concrete state probe as the fail-closed corroborator.

## Live conflict-loop findings (first retained-mode dogfood)

First live evidence from the retained-continuation loop (the `/objective-sync` conflict drive):

- **Blob-level conflict prediction gives a ceiling, not a profile.** Only overlapping-line edits
  actually stop a rebase, so a blob-overlap census reads as "at most N stops" — budget attempt
  caps from it as an upper bound, never an expected count.
- **The loop is a textual-integrity mechanism, not a semantic-consistency one.** Auto-merges
  carry base-advance-falsified claims (prose the base's advance made wrong) straight past the
  resolver — nothing conflicts textually. The content workflow owns semantic reconciliation;
  don't expect the conflict loop to catch it.
- The fail-closed retained-mode prompt produced **content-correct semantic resolution** on its
  first live conflict — the first evidence the prompt shape resolves well, not merely refuses
  safely.
- Mechanics worth remembering:
  - Preview and real sync runs each mint **fresh candidate SHAs** — compare *content*, never
    SHAs, when checking a preview against the real run.
  - A consumed sync operation deliberately leaves its `…json.resolver-lock` claim dir behind; it
    self-heals via the lease's reclaimability predicate (`extension/substrate/resolverLease.ts`).
    Never "clean it up" by hand and never report it as orphaned residue.
  - Evidence-chain bracketing tolerates timing slips — bracket the window, don't assert exact
    stamps.
  - Late supervisor progress echoes arriving after the workflow call returns are expected, not a
    stuck child.

## Warm-route hints on cold refusals — the hint has its own truth condition

A cold refusal that recommends a warm route is TWO claims: the refusal itself and the route
advice. Gate the *hint* on its own truth condition — an identity match proving the recommended
route really applies — independently of the refusal's correctness; a correct refusal with a wrong
hint sends the operator to a dead end.

- **Copyable-hint confinement** (`src/perk/delivery/sync.py::_warm_route_hint`): a value
  interpolated into a copyable command hint is confined by an allowlist regex that intersects
  EVERY downstream constraint (shell, unquoted argv, injected-guidance position) — which means an
  **alphanumeric first character** (an option-shaped or `.`-segment token can never render) —
  matched with `fullmatch`; on any mismatch the WHOLE sentence is omitted (fail-closed
  whole-sentence omission, never a partially-sanitized or value-less hint).
- **Suffix-tolerant corroboration tokens:** substring-keyed corroboration pins keep the
  **byte-identical prefix** load-bearing and pinned while tolerating suffix drift — pin the
  prefix, not the whole formatted token.

## The rebase prose-lag trap — relocated symbols leave stale prose behind

After any rebase that adapts to a relocated module/symbol, **grep the old dotted path as text**.
Type-checkers and tests prove the *functional* sweep (imports, call sites, guard allowlists);
nothing proves the *prose* sweep — docstrings, and especially assertion **remediation messages**,
which actively send developers to the wrong home when they name the old location.

Evidence shape: main relocated the canonical `fail()` from `perk.cli.ensure` to `perk.cli.emit`
mid-flight; the rebase fixed every functional reference (CI stayed green) while four prose
references — a `seeded_door.py` docstring plus three in `tests/test_seeded_door.py` (including the
guard's remediation message) — still named `perk.cli.ensure.fail`. Only PR review caught them.

## Worker completion bar (`extension/worker/stageExecution.ts`)

`evaluateTerminal`'s implement arm now requires `submitDetails.mergeable !== false` **in addition to**
`ok && pr`: `true` / `null` / absent all allow completion (fail-open); only a definitive `false`
blocks (→ `agent_idle_incomplete`). The resolver follow-up turns run inside the **same** `prompt()`
drive; the final clean re-submit overwrites the captured details so natural-idle then passes — and
the attempt cap prevents an infinite drive.

## GitHub mergeability gotchas (#554)

- **Force-pushing a rebased branch can leave the PR's `headRefOid` stale.** `gh pr view --json
  mergeable` keeps reporting `CONFLICTING` against the *old* head even though the branch API shows the
  new tip. **Fix**: push a fresh **fast-forward** commit (e.g. `git commit --allow-empty`) — the new
  push event unsticks the head and mergeability recomputes.
- **Throwaway smoke plans that all append to the same file collide on merge.** Use a **unique file
  per branch** to avoid rebase conflicts across sequential lands.

## Contracts / docs touched in-turn (the discipline held)

#556 amended `shared/contracts.md` §8.3 / §8.4 / §8.11 and the user docs **in the same turn** as the
mergeability gate — a pointer, not a reproduction (the "amend the contract / update the user docs,
don't drift" discipline).

## Sources

- #556 (PR #559) — the mergeability gate, `driveConflictResolution`, the conflict-resolver subagent,
  the worker bar
- #554 (PR #553) — the GitHub force-push `headRefOid` + unique-file-per-branch mergeability gotchas

## Cross-references

- `src/perk/substrate/git.py` — the `git merge-tree --write-tree` probe, `MergeProbe.mergeable`
- `extension/delivery/submit.ts` + `pi/v1/delivery/submit.ts` — decide + drive, the re-drive cap
- `extension/pi/v1/delivery/land.ts` — `driveReconcileAfterLand`, the shape the drive mirrors
- `extension/worker/stageExecution.ts` — `evaluateTerminal`'s `mergeable !== false` implement bar
- `agents/conflict-resolver.md` — the write-capable + context-inheriting agent def
- `docs/learned/workflow/warm-door-commands.md` — the terminate+followUp composition, the
  reactive-sub-result drive, the drive-helper test shape
- `docs/learned/pi/subagents.md` — the widening-lockstep census, project-vs-builtin agents
- `docs/learned/workflow/cold-door-client.md` — the advisory-decode leniency the new fields ride
- `docs/learned/workflow/linear-backend.md` — the live-smoke source for the #554 gotchas
