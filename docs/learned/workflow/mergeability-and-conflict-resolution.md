---
title: "/submit mergeability gate + the conflict-resolver subagent"
read_when: You are touching the merge-tree conflict probe (`perk/substrate/git.py`), the carry-the-verdict-explicitly principle, the `/submit` warm reactive drive (`extension/doors/submit.ts`), the worker completion bar (`extension/worker/worker.ts`), the conflict-resolver subagent, or a PR-mergeability / force-push `headRefOid` gotcha.
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

## The warm-door reactive drive (`extension/doors/submit.ts`)

`driveConflictResolution` is modeled **exactly** on `land.ts`'s `driveReconcileAfterLand`:

- **Short-circuit** unless `details.ok && mergeable === false && conflicts.length > 0`.
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
per-call-inline-model facts (not duplicated here).

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
