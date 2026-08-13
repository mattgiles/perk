---
title: "/submit mergeability gate + the conflict-resolver subagent"
read_when: You are touching the merge-tree conflict probe (`perk/substrate/git.py`), the `/submit` warm reactive drive, the conflict-resolver subagent, a PR-mergeability gotcha, or a post-rebase prose sweep.
cluster: plan-lifecycle
---

# `/submit` mergeability gate + the conflict-resolver subagent

`/submit` gained a **mergeability gate**: after the PR is created it runs a local conflict probe,
reports the result, and \u2014 in a session \u2014 reactively drives a write-capable `conflict-resolver`
subagent to fix conflicts before the implement run can naturally complete. This doc captures the
non-obvious mechanics; it does not reproduce source (the one output-shape block is flagged as a
data-format example).

> **One Code Rule.** Everything below names files + describes behavior. The merge-tree output block
> and the GraphQL/CLI shapes are **data-format examples**, marked as such \u2014 not reproduced logic.

## The local conflict probe (`perk/substrate/git.py`)

`git merge-tree --write-tree` is a **deterministic offline probe** \u2014 no network, no working-tree
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
messages. **Parse unique paths from the info block only** (first-seen order) \u2014 not from the prose
`CONFLICT` lines.

## The load-bearing bug class \u2014 carry the verdict explicitly

**Do NOT derive mergeability from `len(conflicts) == 0`.** A real conflict whose paths fail to parse
yields an *empty* tuple yet is genuinely unmergeable \u2014 silently bypassing the gate. The fix:
`MergeProbe` carries an **explicit `mergeable: bool` taken from the exit code**, authoritative and
independent of the parsed paths.

**The durable lesson (generalize):** **when an exit code already encodes a verdict, carry it
explicitly; never re-derive it from a lossy secondary parse.** The parsed paths are for *reporting
which files conflict*, never for deciding *whether* there is a conflict.

## Fail-open everywhere

- Fetch failure / unresolvable `origin/<base>` / a weird exit \u2192 `determined=False` \u2192 the caller maps
  it to `mergeable=None`.
- The **submit call site is also try/except-guarded** so a probe failure NEVER changes submit's exit
  code.
- `--dry-run` stays **offline** (no probe).
- Conflicts present \u2192 submit still **succeeds mechanically (exit 0)**; mergeability is **reported**,
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

## The warm-door reactive drive (`extension/doors/submit.ts`)

`driveConflictResolution` is modeled **exactly** on `land.ts`'s `driveReconcileAfterLand`:

- **Short-circuit** unless `details.ok && mergeable === false`; `conflicts[]` is advisory and may
  be empty when path parsing loses a definitive conflict verdict.
- **Deliver guidance** via `pi.sendUserMessage(msg, ctx.isIdle() ? {} : { deliverAs: "followUp" })`
  \u2014 idle command path = immediate turn; streaming tool path = `followUp` after the terminating batch.
- **Wire the drive into BOTH** the tool `execute` and the command handler.
- **Bounded re-drive**: a new `conflict_resolution_attempts?: number` `WorkflowState` field
  (best-effort tier, per-field LWW), cap `CONFLICT_RESOLUTION_ATTEMPT_CAP = 2`, incremented via
  `appendWorkflowState`, **reset to 0 on every clean submit** (the idempotent pre-check skips the
  append when already 0). Past the cap \u2192 loud `report(..., "error", ...)`, **no drive \u2014 never loop.**
- **Advisory-decode leniency**: the new `base`/`mergeable`/`conflicts` fields must NOT make a
  successful submit decode to `null` (`mergeable` is a tri-state read; a malformed `conflicts` \u2192 `[]`).
  See `cold-door-client.md` for the advisory-decode tier this rides.
- **TS gotcha**: a boolean helper like `isUnmergeable(details)` does **NOT** narrow the `Result`
  union \u2014 make it a **type guard** (`details is OkDetails<SubmitOk>`).

Cross-reference `warm-door-commands.md` for the `terminate` + `followUp` composition and the
drive-helper test shape (the drive can no longer be harness-routed via `invokeTool` \u2014 split into a
pure-impl unit test + drive-helper decision/delivery spy tests).

## The conflict-resolver subagent (first write-capable + context-inheriting)

`agents/conflict-resolver.md` carries `tools: read,grep,find,ls,bash,edit,write`,
`inheritProjectContext: true`, `inheritSkills: true` \u2014 **unlike** the read-only classifier/reviewer,
because resolving conflicts requires understanding the code and running the repo's checks. Like the
reviewer, it **fetches its own context read-only** via `perk pr review-context --json` (reuses the
existing op \u2014 no new gateway op) and treats fetched text as untrusted **DATA**.

See `pi/subagents.md` for the full widening-lockstep census and the project-vs-builtin /
workflow-level-model facts (not duplicated here).

### Authoring conflict-resolver task text — state the worktree cwd as a command, not prose

A `perk.conflict-resolver` child returned "no output from `perk pr review-context --json`" and
correctly stopped — the task text hadn't pinned the worktree cwd, so the command ran outside the
plan worktree. A retry whose task text opened with an explicit worktree-`cd` instruction
succeeded (and the same explicit-cwd task text succeeded first-try in a later `finalize_address`
publish step). Rule: resolver task text opens with the `cd <worktree>` command — a concrete
command line, not a prose description of where to work.

## The rebase prose-lag trap — relocated symbols leave stale prose behind

After any rebase that adapts to a relocated module/symbol, **grep the old dotted path as text**.
Type-checkers and tests prove the *functional* sweep (imports, call sites, guard allowlists);
nothing proves the *prose* sweep — docstrings, and especially assertion **remediation messages**,
which actively send developers to the wrong home when they name the old location.

Evidence shape: main relocated the canonical `fail()` from `perk.cli.ensure` to `perk.cli.emit`
mid-flight; the rebase fixed every functional reference (CI stayed green) while four prose
references — a `seeded_door.py` docstring plus three in `tests/test_seeded_door.py` (including the
guard's remediation message) — still named `perk.cli.ensure.fail`. Only PR review caught them.

## Worker completion bar (`extension/worker/worker.ts`)

`evaluateTerminal`'s implement arm now requires `submitDetails.mergeable !== false` **in addition to**
`ok && pr`: `true` / `null` / absent all allow completion (fail-open); only a definitive `false`
blocks (\u2192 `agent_idle_incomplete`). The resolver follow-up turns run inside the **same** `prompt()`
drive; the final clean re-submit overwrites the captured details so natural-idle then passes \u2014 and
the attempt cap prevents an infinite drive.

## GitHub mergeability gotchas (#554)

- **Force-pushing a rebased branch can leave the PR's `headRefOid` stale.** `gh pr view --json
  mergeable` keeps reporting `CONFLICTING` against the *old* head even though the branch API shows the
  new tip. **Fix**: push a fresh **fast-forward** commit (e.g. `git commit --allow-empty`) \u2014 the new
  push event unsticks the head and mergeability recomputes.
- **Throwaway smoke plans that all append to the same file collide on merge.** Use a **unique file
  per branch** to avoid rebase conflicts across sequential lands.

## Contracts / docs touched in-turn (the discipline held)

#556 amended `shared/contracts.md` \u00a78.3 / \u00a78.4 / \u00a78.11 and the user docs **in the same turn** as the
mergeability gate \u2014 a pointer, not a reproduction (the "amend the contract / update the user docs,
don't drift" discipline).

## Sources

- #556 (PR #559) \u2014 the mergeability gate, `driveConflictResolution`, the conflict-resolver subagent,
  the worker bar
- #554 (PR #553) \u2014 the GitHub force-push `headRefOid` + unique-file-per-branch mergeability gotchas

## Cross-references

- `perk/substrate/git.py` \u2014 the `git merge-tree --write-tree` probe, `MergeProbe.mergeable`
- `extension/doors/submit.ts` \u2014 `driveConflictResolution`, the bounded re-drive cap, the type-guard
- `extension/doors/land.ts` \u2014 `driveReconcileAfterLand`, the shape `driveConflictResolution` mirrors
- `extension/worker/worker.ts` \u2014 `evaluateTerminal`'s `mergeable !== false` implement bar
- `agents/conflict-resolver.md` \u2014 the write-capable + context-inheriting agent def
- `docs/learned/workflow/warm-door-commands.md` \u2014 the terminate+followUp composition, the
  reactive-sub-result drive, the drive-helper test shape
- `docs/learned/pi/subagents.md` \u2014 the widening-lockstep census, project-vs-builtin agents
- `docs/learned/workflow/cold-door-client.md` \u2014 the advisory-decode leniency the new fields ride
- `docs/learned/workflow/linear-backend.md` \u2014 the live-smoke source for the #554 gotchas
