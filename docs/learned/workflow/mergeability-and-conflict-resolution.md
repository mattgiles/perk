---
title: "/submit mergeability gate + the conflict-resolver subagent"
read_when: /submit mergeability gate, the code-owned conflict-resolver dispatch (resolve_submit_conflicts, the retained /objective-sync drive), the worktree resolver lock, the attempt cap, or rebase analysis.
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
- Both dispatch paths are code-owned native foreground delegation over a strict TypeBox record
  schema (no prose parsing); the submit tool is single-use and re-guards at every await; the
  worktree lock is manual-recovery-only — "The resolver record schema + the two code-owned
  dispatch modes", "The transport", "The worktree-scoped execution lock", "Two authorization
  gaps only review caught".
- Check the native worktree-default config-compat gate BEFORE the first `/submit` on a
  conflicted PR (refusals spend the attempt cap; a fix is invisible until Pi restarts); after a
  resolver rebase, diff intended-vs-rebased per file and re-gate the rebased head — "Native
  worktree default + the attempt cap", "Live conflict-loop findings".
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
command line, not a prose description of where to work. The session no longer authors the task at
all: `conflictResolutionGuidance` (`extension/pi/v1/delivery/submit.ts`) renders **parent
guidance only**, and the code-owned dispatch authors the child task with the concrete worktree
(`extension/delivery/conflictResolution.ts::conflictResolutionTask` /
`retainedConflictResolutionTask`, both refusing a worktree string they cannot safely quote).

## The resolver record schema + the two code-owned dispatch modes

The closed 5-class outcome vocabulary (`completed` / `verification-failed` /
`stopped-before-mutation` / `unresolvable-conflict` / `aborted`) survives as a **strict TypeBox
terminal schema** in `extension/delivery/conflictResolution.ts`: `pr-rebase` records carry
`mode/outcome/verification/push/summary`; `retained-continuation` records omit `push` and the
`aborted` outcome; unknown fields are rejected (`additionalProperties: false`); the JSON-serialized
schema is the native delegation `outputSchema`. **No prose parsing survives on either path** —
`agents/conflict-resolver.md` completes through `structured_output` when a schema is supplied, and
only its legacy first line otherwise. The design rule stands: every dispatcher gate maps every
branch to an emittable class — add a class, never soften a gate.

`resolved` requires ALL of: native `completed` + a schema-valid record + outcome `completed` +
verification `passed` + push `succeeded` (PR mode) + a successful lock release. Every other
combination withholds. The **mode is selected by the discriminated `ConflictResolutionRequest` the
caller builds**, not by a task-text sentinel — the retained sentinel line in the task survives only
as the worktree-naming carrier the agent def reads (it corroborates against concrete rebase state
before mutating, as before).

- **The submit path**: a parameterless, single-use, non-terminating `resolve_submit_conflicts`
  tool (`extension/pi/v1/delivery/submitConflict.ts`), primed only by a verified
  `ConflictFollowUp.kind === "drive"`, bound to session/run/cwd/attempt, and consumed
  synchronously before any await. On `resolved` the parent still calls canonical `submit` again —
  publication, cap, and mergeability authority are unchanged.
- **The retained path** (`extension/pi/v1/delivery/stackConflictResolver.ts`, the
  `/objective-sync` drive) reuses the same engine with the `continuation-ready` success kind.

Cross-cutting rule: a schema-valid child record is NOT proof of tests or remote mergeability.
Native status, domain outcome, and the parent's canonical re-submit stay separate authorities;
receipts are output-free and diagnostic only.

## The transport: pi-subagents' structured foreground delegation, not RPC/ReportWave

Both obvious "call the engine synchronously" routes are dead ends: Pi's `getAllTools()` returns
tool *metadata*, not callables, and the engine's RPC `spawn` rejects `async: false`. The working
path is the engine's structured foreground delegation interface (`src/api/delegation.ts` publishes
the event constants; the adapter fixes `async: false`, `foregroundOnly: true`, `clarify: false`,
`acceptance: false`), driven by the `prompt-template:subagent:{request,started,update,response,
cancel}` event family with exact `(requestId, ownerRunId, nodeId)` correlation
(`extension/pi/v1/delivery/conflictResolverEngine.ts::DELEGATION_EVENTS`). The confined
source-bound loader — walk the registered `subagent` tool's `sourceInfo.path` up to the
`pi-subagents` manifest and load only its `./preflight` export — is a tested narrow exception to
`bareImportGuard`, not a general escape hatch. The role split this implies (report roles
background, the writer foreground) is in `pi/subagents.md` § "Native child execution profiles".

## The worktree-scoped execution lock

`extension/substrate/worktreeResolverLock.ts` keys on the canonical **per-worktree** git dir
(`git rev-parse --absolute-git-dir`, realpath'd — `extension/substrate/git.ts::worktreeGitDir`),
NOT `--git-common-dir`, the run id, the branch, or the raw cwd — so symlink/subdirectory aliases
collapse to one lock while distinct linked worktrees never serialize against each other. It fails
closed: `worktreeGitDir` returns null on any probe failure (joining `revalidationBracket` as
`git.ts`'s second deliberate fail-closed exception). Acquisition is an atomic exclusive create; an
existing file is busy even for the same PID/session and even if dead, empty, or malformed — **no
heartbeat, expiry, same-PID bypass, or automatic reclaim**; reload and process exit are not unlock
gestures; recovery is manual-only (`docs/user-docs/how-to/recover-a-dirty-worktree.md`). Contrast
`extension/substrate/resolverLease.ts`, a session *claim* permitting same-PID reacquire and
dead-PID reclamation; the primitive decision table is in `workflow/lease-outbox-delivery.md`.

## Two authorization gaps only review caught

1. **The mode floor.** Gating on `state.mode !== "read-write"` refused ordinary warm sessions: the
   warm-mint arm of `establishSessionIdentity` (`extension/session/lifecycle.ts`) leaves `mode`
   undefined, and `toolGating` treats undefined as writable. Deny only the explicit
   `state.mode === "read-only"` floor (generalized in `workflow/warm-door-commands.md`).
2. **Re-guard at the synchronous mutation port.** A currency/cancellation check before an `await`
   is not sound for a claim or counter write after it. The retained resolver's `isCurrent()` check
   runs at the actual claim acquisition and attempt-counter increment, so a revoked invocation
   cannot mutate budget or claim. Any single-use authorization spanning awaits must be revalidated
   after every await boundary (preflight + lock acquisition), each with its own regression test
   (the revocation-race tests).

## Native worktree default + the attempt cap — fix config BEFORE spending an attempt

pi-subagents' delegation has no per-request `worktree` field, so the engine applies
`<agent dir>/extensions/subagent/config.json`'s `worktree` default; `true` ⇒ the resolver child
would run in a separate managed worktree, so the engine refuses with
`incompatible-worktree-default`. Every such refusal — at all four gates (pre- and post-preflight,
post-lock, and the pre-emit gate inside `waitForTerminal`, which settles with its own reason rather
than collapsing to `unauthorized`) — stamps `receipt.nativeWorktreeConfig {path, observed,
atActivation}` through one `worktreeRefusal()` closure, and the submit diagnostic renders the exact
path plus `perk doctor --fix` (or `perk init`) plus a restart. Post-lock precedence: a lock-finish
failure wins, then `cancelled` → the stamped worktree refusal → `unauthorized`. The repair is
Python-owned (the `subagent-worktree-default` convergence, `workflow/init-doctor.md`), never the
adapter's.

Two traps: the effective agent dir is `getAgentDir()` — perk redirects it to the **project-local**
`.pi/agent`, not `~/.pi/agent` (time was lost editing the wrong file); and `configCompatible()`
requires the current state `===` the value pinned at extension activation, so a fix is invisible
until the Pi process is quit and the session resumed (`pi --session <file>` with
`PI_CODING_AGENT_DIR` exported; resuming is the lifecycle `keep` arm, so `PERK_RUN_ID` need not be
re-exported) — `/reload` is not enough. The cap counts pre-dispatch refusals: two config refusals
(no child ever launched) consumed `CONFLICT_RESOLUTION_ATTEMPT_CAP = 2`, and because the counter is
rebuilt only when the session file is opened, resetting it required in-place edits of persisted
entries in the live session JSONL — unsafe surgery not to normalize. Rule: check the config-compat
gate before the first `/submit` on a conflicted PR; treat a spent budget as "fresh session /
explicit recovery", never "edit the JSONL".

Test note: to hit the pre-emit gate there is no async seam — mutate state from the `authorized`
callback on its Nth read (the post-lock gate reads the native config before re-reading
authorization, so poisoning on the third read leaves the pre-emit gate as the first observer;
assert the read count) and use the `acquire` wrapper to hit the post-lock gate.

## Live conflict-loop findings (first retained-mode dogfood)

First live evidence from the retained-continuation loop (the `/objective-sync` conflict drive):

- **Blob-level conflict prediction gives a ceiling, not a profile.** Only overlapping-line edits
  actually stop a rebase, so a blob-overlap census reads as "at most N stops" — budget attempt
  caps from it as an upper bound, never an expected count.
- **The loop is a textual-integrity mechanism, not a semantic-consistency one.** Auto-merges
  carry base-advance-falsified claims (prose the base's advance made wrong) straight past the
  resolver — nothing conflicts textually. The content workflow owns semantic reconciliation;
  don't expect the conflict loop to catch it. The sharper instance: a resolver rebase reported
  `completed / verification passed / push succeeded` and was genuinely green, yet had dropped
  main's newly landed contract sections wholesale, bolted an early return ahead of gate checks,
  and introduced a circular import — nothing caught it until `/pr-review`. The recipe: compare
  intended vs rebased diffs per file (`git diff <old-base> <pre-rebase-head> --numstat` against
  `git diff <new-base> <rebased-head> --numstat`; post-rebase deletions exceeding the intended
  deletions are suspect), then `comm -12` the lines main ADDED against the lines the rebased diff
  REMOVES to pinpoint dropped content; restore prose by three-way merge (`git merge-file` with
  base = old base, ours = the pre-rebase intended file, theirs = main). **The green run-all gate on
  the pre-rebase head is void after a rebase** — re-gate the rebased head as a distinct
  checkpoint. Enumerated-stage policies also go stale mid-flight: a closed enumeration over
  registry vocabulary must be re-checked against main's registry at rebase time
  (`objective-refine` landed mid-implementation).
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

## Manual rebase-recovery recipes

- **The delete/edit conflict (main edited lines your branch moved).** Keep the deletion, then
  verify the moved copy already carries main's fix (grep the new file for the fixed shape). When a
  payload shape changes, grep ALL test fixtures repo-wide, not just the owning module's suite
  (`workflow/cold-door-client.md`'s merge-race fixture sweep).
- **Interrupted mid-pick rebase** (e.g. a killed process leaves `.git/rebase-merge` behind):
  **never start another rebase.** Read `git status` first — it shows the done list and the staged
  pick's content — then `git commit -C <pick-sha>` the staged step and `git rebase --continue`.

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
- `extension/pi/v1/delivery/submitConflict.ts` / `stackConflictResolver.ts` / `conflictResolverEngine.ts` — the two code-owned dispatch paths over the native foreground delegation engine
- `extension/delivery/conflictResolution.ts` — the strict record schema + the code-authored child tasks
- `extension/substrate/worktreeResolverLock.ts` — the manual-recovery-only per-worktree lock
- `docs/learned/workflow/lease-outbox-delivery.md` — the exclusion-primitive decision table
- `docs/learned/workflow/warm-door-commands.md` — the effective-writability mode floor
- `docs/user-docs/how-to/recover-a-dirty-worktree.md` — the manual lock/worktree recovery exit
- `docs/learned/workflow/warm-door-commands.md` — the terminate+followUp composition, the
  reactive-sub-result drive, the drive-helper test shape
- `docs/learned/pi/subagents.md` — the widening-lockstep census, project-vs-builtin agents
- `docs/learned/workflow/cold-door-client.md` — the advisory-decode leniency the new fields ride
- `docs/learned/workflow/linear-backend.md` — the live-smoke source for the #554 gotchas
