---
title: "Objective commands"
description: "Exact reference for the perk objective group — authoring, workers, and the stacked delivery-train stack subgroup."
sidebar:
  order: 3013
---

# Objective commands

This page holds the exact reference for the `perk objective` group (alias `obj`) — the objective
launchers and workers, including the `objective stack` delivery-train subgroup. For the full
command map and shared conventions, start at the [CLI commands hub](../cli.md).

### `perk objective` (alias `obj`)

The objective group. Help renders **Launchers** (each opens a primed `pi` session: `author`,
`save`, `plan`, `replan`) and **Workers** (the deterministic dev/CI/T10 storage + mechanics surface, not an
agent affordance: `create` (`new`), `show` (`s`), `node`, `reconcile` (`rec`), `next` (`n`), `run`
(`r`), `stack`). Bare `perk objective` shows this group help.

### `perk objective author`

Draft a new objective and roadmap in a read-only authoring session. Local-only
(`cold_remote:false`); adds `--json`. Runs the hub's
[pre-launch fast-forward](../cli.md#pre-launch-fast-forward-read-only-planningauthoring) before
launch; `--no-sync` opts out.

With **`--from <source>`** it instead **adopts a pre-existing source IN PLACE** as the objective: a
Linear project UUID, a GitHub issue id, or the source's URL. perk reads the source's prose + existing issues (and any
human discussion) as untrusted seed DATA, authors an objective + roadmap over it in a read-only
session, and on save stamps the objective metadata **additively** into the *same* source — the
`objective-header` block (with `adopted_from` provenance), the `objective-manifest`, the
model-authored prose, and the original overview preserved verbatim in an `Adopted-from` Immutable
note — **never minting a second project/issue**. On Linear, a roadmap node's optional `adopt_issue`
field maps it to an existing project issue (reused in place, title/body verbatim); GitHub is bounded
to a single issue (no child mapping). `--dry-run` materializes the source and prints the seed
without launching. Refuses when the source is not found, not open (GitHub issues only), already a
perk objective, or (GitHub issues only) already a perk **plan** (`already_a_plan` — plans are not
adoptable as objectives; re-author with `perk plan replan <id>` or author a fresh objective). See
[Adopt an existing project as an objective](../../how-to/adopt-an-existing-project.md).

`--from <source>` may also be a path to a **local file** (relative or absolute). When it resolves to
an existing file, perk runs **seed-from-file** mode: it reads the file as untrusted seed DATA, primes
the read-only authoring session, and on save mints a **fresh** `perk:objective` issue (no in-place
adoption — the file is never modified). A non-existent path falls through to the source-id path.

### `perk objective save`

Persist the drafted objective to GitHub — the read-only → read-write objective boundary (the
`objective-save` stage). Local-only; adds `--json`.

### `perk objective plan [NUMBER]`

Select the next objective node and author a bounded plan (read-only). `NUMBER` is the objective
issue id, or the objective's **URL** (required — a cold session has no active objective); `--node`
plans a specific node id instead of the next actionable one. Local-only; adds `--json`. Runs the
hub's [pre-launch fast-forward](../cli.md#pre-launch-fast-forward-read-only-planningauthoring)
before launch; `--no-sync` opts out.

For a **stacked** objective, node selection is **build-readiness-derived** (a live
delivery-train reconstruction): the single plannable candidate is the next unpublished layer in
delivery order — which permits planning the next layer while its predecessor is
published-but-unmerged. A blocked train is a typed `node_not_build_ready` refusal carrying the
exact veto (check `perk objective stack status <N>`), and an explicit `--node` must name the
ready candidate. The plan seed then carries the layer's position and its verified predecessor
context (branch + remote head; the already-fetched `origin/<parent>` is locally inspectable) —
perk records no planning-time SHA. `--dry-run` skips the readiness check (offline) and says so
(`"build_readiness": "unchecked (dry-run)"`).

### `perk objective create` (alias `new`)

Mint a `run_id` and create the perk:objective issue from authored markdown. Reads the required
`--body` file; `--title`, `--roadmap` (a JSON array of nodes, preferred over embedding YAML),
`--base` (the target branch this objective's node plans inherit — else `[workflow] base`, else the
GitHub default; see
[Target a non-default base branch](../../how-to/target-a-non-default-base-branch.md)), `--run-id`,
`--adopt-from <source>` (adopt the named pre-existing source IN PLACE rather than minting a fresh
objective — normally set automatically via the run handoff by `objective author --from`),
`--delivery [incremental|stacked]` (the reviewed delivery choice; omitted ⇒ incremental),
`--dry-run`, and `--json` tune the create.

A **stacked** save (`--delivery stacked`) is validated (2–100 non-skipped nodes; duplicate-id /
unknown-dep / cycle errors; any DAG shape is fine), refused in combination with `--adopt-from`,
and capability-checked against the real Git/GitHub plane (native-stack API surface, squash
direct-merge + no merge queue on the base, a no-op atomic-push dry-run per push URL) before
anything is written — `--dry-run` stays offline and skips the probes. An explicit
`--delivery incremental` behaves exactly like omitting the flag. See
[Choose the delivery mode](../objectives.md#delivery) for when to pick stacked — and its current
limitations.

### `perk objective show NUMBER` (alias `s`)

Show an objective's header, roadmap, summary, and next actionable node.

### `perk objective node NUMBER`

Update one roadmap node (explicit-status-only). `--node` selects the node id (required); `--status`
sets its status (never inferred from `--pr`); `--pr` sets or clears the PR backlink;
`--description` updates the node description; `--dry-run` validates without writing.

### `perk objective node-add NUMBER`

Insert a **new** roadmap node into a phase (auto-assigned `<phase>.<n>`, appended after that phase's
last node). `--phase` (int, required) and `--description` (required) define the node; `--status`
sets its initial status (default `pending`); `--slug` overrides the auto-derived slug;
`--depends-on` (repeatable) adds a dependency edge; `--comment` attaches a note; `--dry-run`
validates without writing. Used **sparingly** during reconciliation, when a genuinely-new unit of
work emerged: a deferred follow-up the plan/PR flagged, an uncovered defect or gap, a missing
prerequisite for a later node, or human-requested work from the engagement block.

A successful **non-terminal** add (any `--status` other than `done`/`skipped`) also **reopens a
closed objective** (the reopen-on-incomplete invariant — roadmap incomplete ⇒ open, the mirror of
land's close-on-complete; human output adds `✓ Reopened #N (roadmap incomplete again)`). The one
exemption is a **superseded** objective (its header carries `superseded_by` — `objective replan`
closed it deliberately): the reopen is skipped with a stderr note, as policy, not an error. The
reopen is fail-open — a reopen failure never discards the add. The `--json` payload carries two
keys for it: `reopened` (bool — `false` on dry-run / terminal add / already-open / superseded-skip
/ failure) and `reopen_error` (string \| null — `null` on the superseded skip). Flipping an
existing node's status via `perk objective node` never auto-reopens — the invariant rides node
*insertion* only.

### `perk objective engagement NUMBER`

Read the **objective + its node-issues' human engagement** — comments + description edits on the
objective and every roadmap node-issue — as one untrusted-DATA `<untrusted_objective_engagement>`
block. `--json` emits the machine payload (`project_comments`, `project_description_edits`, and a
`nodes` list of per-node `comments` / `description_edits`). Read-only; the `/objective-reconcile`
pass uses it to weigh human feedback alongside the merged diff. **GitHub** surfaces the objective
issue's own comments + edits (no per-node sections); **Linear** surfaces the project's comments +
each node-issue's comments/edits (project description edits are an honest empty — node-issue edits
carry that signal). Empty → `no human engagement on objective <N>`.

### `perk objective node-engagement NUMBER`

Read a roadmap node-issue's **pre-planning human engagement** — comments + description edits left on
the node-issue *before* perk planned it — as an untrusted-DATA block. `--node` selects the node id
(required); `--json` emits the machine payload (`comments`, `description_edits`). Read-only; the
`/objective-plan` factory uses it to fold human feedback into the authored plan. **Linear-first** —
GitHub single-issue objectives (and the dormant issue-backed Linear store) report no engagement.

### `perk objective reconcile NUMBER` (alias `rec`)

Reconcile an objective's Reconcilable prose region against the merged diff — rewriting only the
marker-bounded region, never the roadmap table or Immutable notes. Reads the required `--body`
file; `--dry-run` composes without writing.

### `perk objective replan NUMBER`

Re-author an objective as a **net-new objective that supersedes and closes the old one** — the
objective analog of [`perk plan replan`](./plan.md#perk-plan-replan-plan), but close-old/create-new rather
than in-place (perk's `objective_save` is not an upsert). Carries forward only the **unfinished**
work (reshaped); already-`done` nodes stay as history on the closed old objective. Read-only,
local-only (`cold_remote:false`); `--dry-run` materializes the old objective + prints the seed
without launching; `--worktree` and `--json` are also accepted. Refuses when the objective is not
found, already superseded, or (GitHub) not open. The `supersedes` link rides the run handoff, the
new header gets `supersedes`, the old header gets `superseded_by`. It runs the hub's
[pre-launch fast-forward](../cli.md#pre-launch-fast-forward-read-only-planningauthoring) before
launch (`--no-sync` opts out). On **Linear** the unfinished
node-issues are **moved** into the new objective (identity / open PRs preserved) and dropped open
node-issues are Canceled; on **GitHub** carried nodes are authored as fresh roadmap rows and the
old issue is closed. See
[How to replan an objective](../../how-to/replan-an-objective.md).

### `perk objective next NUMBER` (alias `n`)

Print the next plannable node (pending, or a resumable `planning` claim). For a **stacked**
objective the selection is **build-readiness-derived** (a live delivery-train reconstruction;
the next unpublished layer in delivery order): `next_node` is constrained to that candidate
(or `null`), and the `--json` payload gains an additive `build_ready` block
(`{ready, reason}`); a blocked train prints `build blocked: <reason>`. Incremental payloads
are unchanged.

### `perk objective run NUMBER` (alias `r`)

Advance an objective's backlog one autonomously-safe step, then pause at the human gate.
`--remote` sets the runner ref for remote dispatches; `--wait` polls an in-flight run to
completion then re-evaluates; `--dry-run` resolves and reports the decision only. The `--json`
payload carries the classifier's verdict in a `next_action` field — for the same plan state it
matches what [`perk plan resume --dry-run`](./plan.md#perk-plan-resume-plan) reports (both surfaces share
one classifier). For a **stacked** objective the planning decision is build-readiness-derived
(replacing the dependency/terminal gating), and a readiness veto surfaces as an honest
`action: "build_blocked"` report (exit 0) carrying the exact reason plus a
`perk objective stack status <N>` remediation. Train vetoes are classified before every selection
kind: unresolved operations and operational drift yield `action: "repair_required"` with the
owning `stack recover`/`stack status` command, while structural blockers stay `build_blocked`.
With no veto, published layers are scanned bottom-to-top: actionable lower-layer feedback dispatches
`address` before upper planning/implementation, while draft-ready and awaiting-review layers are
waiting gates and do not outrank upper work. `--dry-run` keeps the offline graph classification,
never reconstructs the train, and says so in the payload
(`"build_readiness": "unchecked (dry-run)"`, stacked only).

### `perk objective doctor NUMBER` (alias `doc`)

Detect (and optionally repair) objective drift, in **two parts**. **Part 1 (manifest drift,
Linear only)**: divergence between a Linear-Project objective's persisted `objective-manifest`
and its live state (node-issues, blocking relations, milestones); GitHub objectives have no
divergence surface, so this part is always empty. **Part 2 (delivery-train diagnosis, every
backend)**: the exact `DeliveryTrain` findings — the same blockers/information `stack status`
reports — each annotated with a deterministic severity, repairability, and remediation (e.g.
"conclude via `stack recover`", "repair the PR on GitHub then rerun status", "restore the
contradicted authority, then optionally replan"). A superseded id follows `superseded_by`
forward: both parts target the **active** objective (`objective` reports it;
`redirected_from` preserves the requested id; the predecessor is never mutated).

Detect-only by default; `--fix` applies the **safe, unambiguous** repairs in a deterministic
order: the manifest repairs (a missing manifest is backfilled, a missing node-issue or phase
milestone is recreated, a missing blocking relation is re-added; stopping at the first failed
write) plus exactly ONE narrow train repair — persisting a **safely projected native
cancellation** (a Linear node canceled by a human, proven to be unpublished future work: a
clean plan backlink is acceptable, but any identity conflict, checkpoint/PR claim, completed
or unresolved publication, remote branch, or branch-owned PR is not) into the node attachment
as `skipped`, with a fresh proof immediately before
each conditional write, post-write verification, and a compensating rollback + loud abort on
observed drift. Doctor never repairs plan identity, checkpoints, journal history, branches,
PRs, or native stack membership — those findings carry explicit remediations instead.
`--dry-run` (with `--fix`) plans both repair batches without writing. Report-only conditions
perk has no authority to auto-resolve are surfaced but never touched.

A third, **report-only** check rides every report: the **both-headers corruption signature**.
Doctor resolves the objective's issue-tier carrier (on GitHub the objective issue itself; on a
Linear-Project objective the metadata **sentinel** issue) and reads it presence-only; a carrier
bearing BOTH `objective-header` and `plan-header` metadata yields one `both_headers` finding in
the `corruption` field — one header was stamped onto the wrong kind of carrier. The finding is
direction-neutral (the stray side is not provable from the carrier alone), never auto-repaired
(`--fix` has no repair arm for it), printed in the human report only when detected, and keeps
exit `0` (a detected finding is still a clean report).

`--json` emits the full
report (`drift`/`fix` plus the additive `redirected_from`/`train`/`train_fix`/`corruption`); the
exit code conveys an unavailable train or an aborted repair (`1`) while the assembled report stays
`success: true`. See
[How to check an objective for drift](../../how-to/check-an-objective-for-drift.md).

### `perk objective stack`

The stacked delivery-train worker subgroup: observe, synchronize, recover, and land an
objective's stacked delivery train — `status` (report the reconstructed train), `sync` (the
published-suffix cascade), `recover` (conclude-only recovery plus the orphaned-residue sweep),
and `land` (the atomic landing mutation and its `--dry-run` readiness preview). Each verb is
detailed below; for the operational repair flow see
[How to recover a stacked train](../../how-to/recover-a-stacked-train.md).

### `perk objective stack status [OBJECTIVE]`

Report an objective's **stacked delivery-train status** (worker; read-only end to end — works
from a fresh clone, no local worktree or branch is authoritative). Reconstructs the
`DeliveryTrain` projection from the durable authorities (objective store, plan issues, the
operation journal, Git refs, GitHub PR + native-stack state) and reports one line per layer
bottom→top plus classified **blockers** and **information** findings, each naming the exact
expected-vs-observed values. `OBJECTIVE` is the objective id/URL; omitted, it is inferred from
the current plan worktree's linked objective (neither → a typed `no_objective` failure).
`--json` emits the machine envelope (`objective{id,url,redirected_from}`, `delivery`
(`incremental` | `stacked`), `train` with per-layer axes + `blockers`/`information` + the
derived `next_build_ready` block (`{node_id, ready, reason}` — the first unpublished layer in
delivery order, buildable only when the train has no blockers and no unresolved operation), or
the `no_train` explanation). The per-layer axes include `handoff`, derived from **ready-stamp
journal events**: `unstamped` = no stamp names the layer's current verified published head
under this objective; `stale` = the head moved past the latest stamp; `suspended` = the PR is
currently draft while the stamp still matches (a transient hold); `ready` = the latest stamp
matches and the PR is ready-for-review; `not_applicable` for landed/unpublished/unverified
layers. The human render adds one line: `next build-ready: <id>` /
`build blocked: <reason>`. The report also carries **recovery visibility**: every unresolved
operation (`operations[]`, each with its id/kind/prepared time and an `active operation:` line
in the human render), this lineage's **pending continuation manifest** (`continuation` — an
unparseable manifest is reported as `parseable: false`, never hidden), and the machine-local
**orphaned-residue** observation (`orphaned_residue` — honest `observed: false` + reason when
the observation itself failed; `observed: true` with empty lists means genuinely clean).

Exit codes: **blockers found is still exit 0** (status is a successful *detection*, mirroring
`objective doctor`'s report-vs-abort split); `1` = a typed reconstruction failure (e.g.
`invalid_train`, `git_error`); `2` = not-a-repo. An **incremental** objective succeeds with the
no-train explanation ("this objective uses incremental delivery; no delivery train exists").
A superseded objective follows `superseded_by` forward to the active objective and reports
`redirected_from`. The status report additionally carries the live objective-base observation
(`observed_base_head_sha` + the `base_advanced`/`base_unobserved` information findings) — the
base having advanced is a notice with the `sync --base` remediation, never a blocker. The
landing **readiness preview** lives on `perk objective stack land --dry-run`; bare
`perk objective stack land` runs the atomic landing mutation.

### `perk objective stack sync [OBJECTIVE]`

Synchronize an objective's **published suffix** — the transactional cascade (worker). After a
published stacked layer's branch is amended locally (or the objective base advances —
`--base`), this rewrites every published layer from the lowest changed one upward: candidate
heads are computed by rebase in one **isolated, disposable worktree** (user worktrees and
local branches are never touched — affected local branches are deliberately left stale), the
full cascade is rendered for **confirmation** (per-ref `before → after`, node ids, PR
numbers, the base line when cascading), journaled, pushed as **ONE atomic multi-ref push**
under exact per-ref leases (either every ref moves or none does), verified (with a bounded
settle poll for GitHub's PR-head propagation), and checkpointed bottom→top.

Flags: `--base` re-anchors the whole train onto the advanced objective base (refused when the
base cannot be positively observed); `--dry-run` previews the exact would-be cascade and
stops before anything is journaled, pushed, or retained (no confirmation needed — nothing
mutates; composes with `--base` and `--adopt`); `--adopt NODE` accepts one layer's
**manually-pushed remote head** as the intended state and cascades the layers above it
(refused as `adopt_blocked` when there is nothing to adopt, the remote edit rewrote the
layer's ancestry, or the layer is also locally changed; `--adopt` × `--base` is refused);
`--continue` resumes a conflict-stopped cascade **after you finish the rebase yourself** in
the retained worktree (`git rebase --continue`) — perk never drives conflict resolution —
revalidating every captured input (any mismatch is `continuation_stale` with the discard
direction) and concluding the original interrupted operation; `--abort` discards the
retained continuation (confirmation-gated — the prompt names exactly what will be deleted;
an unparseable or invalid manifest deletes the manifest file only, leaving residue for
`recover`'s sweep; a partial contained-residue cleanup succeeds with loud `notes` naming
each leftover and the recover remedy); `--run-id` overrides the objective header's run id
for a fresh sync/adopt, but BOTH control modes ignore it (`--continue` journals under the
interrupted operation's manifest identity; `--abort` journals nothing);
`--yes` approves the rendered cascade (or abort) without asking — **non-interactive runs
without `--yes` refuse** with `confirmation_required` (never a hang, never a silent push);
`--json` emits the machine envelope (`objective{…}`, `operation_id`,
`abandoned_operation_id`, `no_op`, `declined`, `resumed`, `base_cascaded`, `base_advanced`,
`affected[]` with per-layer `before_sha`/`after_sha`, loud `notes[]`, plus `dry_run`,
`adopted_node`, `continued`, `aborted`). `--continue`/`--abort` take no cascade flags. The confirmation
prompt and all human output stay on stderr. All mutating stack operations on one machine
share a lock — a concurrent invocation refuses as `operation_in_progress`.

A normal committed rewrite of a published layer no longer needs a plain explicit sync: re-run
`/submit` (or finish `/address` through `finalize_address`) and perk automatically cascades the
claimed suffix, using only the invoking plan's local committed head and verified published heads
for successors. The explicit sync command remains the owner of `--base`, `--adopt`, `--dry-run`,
`--continue`, and `--abort`, and remains available for operator-driven repair.

What it refuses (typed, before anything is pushed): out-of-band branch/PR/stack drift
(`remote_drift`/`pr_drift`/`membership_drift` — accept a deliberate out-of-band edit with
`--adopt`), a
dirty claimed worktree, an **active remote writer** on a claimed plan (checked against the
live queued/in-progress run listing; an unreadable listing fails closed), a locally-changed
layer that no longer contains its recorded parent (`stale_parent` — rebase it first),
multiple configured push URLs, and a repository without atomic-push support. A **rebase
conflict** stops the cascade with the conflicted worktree deliberately **retained** under a
continuation manifest (`.perk/workflow/sync-continuations/<lineage>.json`); nothing was
pushed or journaled at that point, and a fresh sync refuses (`sync_conflict_pending`) until
you resume it (`--continue`) or discard it (`--abort`). A dry-run conflict retains nothing.

Exit codes: `0` = success — including the honest **no-op** ("nothing to synchronize", with a
`--base` hint when the base has advanced), a **declined** confirmation, a `--dry-run`
preview, and the continued/aborted arms; `1` = the typed refusals/failures above; `2` =
not-a-repo.

### `perk objective stack recover [OBJECTIVE]`

**Conclude-only recovery** for unresolved stack operations, plus the orphaned-residue sweep
(worker). Classifies every unresolved operation against fresh authority — `all_after` (every
recorded effect verified at its prepared after state), `all_before` (proven never-applied),
`external_prefix` (LAND only: a bottom-contiguous prefix of the recorded layers merged
outside the operation while every remaining layer stayed open at its recorded head),
`in_flight` (LAND only: a live or unexcludable merge request — report-only, rerun later), or
`mixed` (needs human investigation; only ever reported) —
then: rolls an `all_after` SYNC/ADOPT forward automatically (deterministic, never asks
twice); rolls an `all_after` TRANSFER (an interrupted objective-replan transfer whose
successor exists and corroborates) forward to completion — ownership stamped, projection
verified, predecessor finalized; rolls an `all_after` LAND forward automatically (the
completed record journaled, every layer finalized bottom→top, the objective closed when
every node is terminal); reports PUBLISH operations (their retry lives in
`/submit`); and, under `--abandon`,
appends the abandoned conclusion for a **proven all-before** target (confirmation-gated,
re-classified after you confirm — a change during the pause blocks the abandon). Retry is
never recover's verb — the report's detail names the owning command. For an interrupted
transfer, run recover against the **predecessor** objective id (the id the refusal names).

An interrupted LAND is classified from its **recorded operation identity** — the journaled
merge-request handle (one probe per classification pass) or, when the crash predates the
handle, the prepared mode plus a 24-hour margin (the merge request's own lifetime) —
combined with strict per-PR observation. `--accept-prefix` records an `external_prefix`
classification as a **degraded-atomicity breach**: confirmation-gated (the prompt renders
exactly the merged prefix + the remainder proof; re-classified after you confirm), it
journals a completed record covering ONLY the merged prefix (`external_prefix: true`),
finalizes those layers, and leaves the remainder re-landable — cascade it with
`perk objective stack sync --base`, then land it with `perk objective stack land`. One
caveat: an external merge often skips deleting the merged head branch, and an undeleted
merged-prefix branch can leave the remainder's lowest PR still targeting it — the sync
cascade reports that as `pr_drift` until you delete the merged branch (GitHub then
retargets the PR) or retarget the PR manually. Merged
PRs with **no** LAND journal coverage are never adopted; non-prefix, closed-PR, and
drifted-remainder states only ever report.

Every invocation (zero unresolved operations included) also runs the **finalization
convergence pass**: every journal-covered, freshly corroborated merged layer gets the
idempotent finalizer re-run (learn-state stamp, plan-issue close, node marked done), and
the objective is closed once every node is terminal — the envelope's `landed_layers`,
`objective_closed`, and journal-assembled `reconcile_evidence` report it; the human render
prints the `/objective-reconcile` hint on a close. Recover is also the **repair surface
for a reconcile drive lost to a crash**: when the objective is already closed and the
journal is complete (no unresolved LAND), it re-emits the fresh-fold `reconcile_evidence`
with a loud note while `objective_closed` stays honestly `false` — process death between
the close and the evidence step would otherwise suppress the drive permanently.
Deliberately at-least-once: every recover on such an objective re-emits (the reconcile
pass is idempotent); `--dry-run` never emits.

After concluding, it sweeps **orphaned sync residue** (leftover `sync-*` worktrees — on disk
or stale in git's worktree inventory — and `refs/perk/sync/*` temp refs no parseable
continuation manifest claims, e.g. after a killed sync process). Any unparseable manifest skips the whole sweep (`sweep_skipped` — an
unreadable claim could be protecting anything); per-item failures are reported as
`sweep_failures`, never silent.

Flags: `--dry-run` classifies and reports only (no roll-forward, no accept, no abandon, no
sweep; refused with `--abandon`/`--accept-prefix` — an `external_prefix` row still carries
its structured preview on a dry run); `--operation ULID` selects the target when several operations are
unresolved (without it, a multi-operation report succeeds with `selection_required: true`;
acting ambiguously refuses as `operation_ambiguous`); `--accept-prefix` accepts an
externally merged LAND prefix as a recorded breach (refused with `--abandon`); `--yes` approves the
rendered abandon/accept without asking (same non-interactive discipline as sync); `--json` emits
the machine envelope (`operations[]` rows with `classification` and the taken `action` —
`reported | rolled_forward | abandoned | accepted_prefix | declined` — plus
`merged_layers[]`/`remainder[]` on external-prefix rows, the swept lists, `landed_layers[]`,
`objective_closed`, `reconcile_evidence`, and loud `notes[]`). There is no
`--run-id`: concluding an existing operation needs no run identity.

Exit codes: `0` = successful classification/report/actions (including declined and
`selection_required`); `1` = typed refusals (`abandon_blocked`, `accept_blocked`,
`operation_not_found`,
`operation_in_progress`, …) and infra failures; `2` = not-a-repo.

### `perk objective stack land [OBJECTIVE]`

Land an objective's remaining delivery train **atomically** — one merge for the whole train
— or preview its readiness with `--dry-run` (worker).

`--dry-run` assesses the objective's **landing readiness** and renders the complete dry-run
land plan (read-only end to end — no remote mutation, no confirmation). It composes the typed readiness projection from the
reconstructed delivery train plus **fresh GitHub observations**: per-PR exact refs,
mergeability, review decision, required-check state, GitHub's aggregate rule verdict
(`mergeStateStatus`), base merge rules (squash allowed / merge queue), and the host's
native-stack API capability (host-schema evidence only — per-repo enrollment and merge-async
availability are observable only at mutation time). Unresolved review threads are reported as
**information**, never a perk-invented gate. Any train blocker, unresolved operation, dirty
worktree, active remote writer, or failed enrichment read is a fail-closed blocker
(can't-verify ⇒ not-ready); a clean checked-out worktree is information only (landing merges
remote PRs and never touches local worktrees).

The verdict is one of `ready` (a `plan` block names the merge mode — `stack_merge_async`, or
`singleton_squash` for a dynamic singleton — plus per-layer PR numbers and exact base/head
SHAs bottom→top), `blocked` (every blocker rendered), or `nothing_to_land` (a **clean**
all-skipped train). `--json` emits the machine envelope (`objective{…}`, `dry_run`,
`disposition`, `base`, `delivery_lineage`, `rules`, `native_stack_capability`, per-layer
`layers[]` rows with expected-vs-observed refs/SHAs, `blockers[]`, `information[]`,
`plan|null`, plus the mutation fields — null/empty on a dry run).

Bare `land` runs the **journaled atomic landing mutation**. It requires GitHub auth,
resolves the run id (`--run-id`, else the active objective header's `run_id`), assesses
readiness fresh, and **confirms** the rendered land plan on stderr — layers bottom→top with
PRs and exact SHAs, the merge mode, and the top-of-train head pin (`--yes` auto-approves; a
non-interactive session without `--yes` refuses typed as `confirmation_required` before any
prompt). After approval every layer PR is **re-observed** (any drift refuses as
`land_drift` with nothing journaled), the LAND operation is journaled first, and then the
train merges: a multi-layer train through GitHub's atomic async stack merge (submitted with
the exact top head pin, the returned merge-request options verified, then polled to a
terminal state), a **dynamic singleton** through an ordinary SHA-pinned direct squash merge.
Every merged PR is verified individually before the operation records `completed`; each
layer is then finalized (learn-state stamp, plan-issue close where autoclose cannot fire,
objective node marked done) and the objective is **closed** once every roadmap node is
terminal. A `NOTHING_TO_LAND` train (every layer skipped) completes the objective without a
merge — also confirmed.

Outcomes are honest, and every one is exit `0`: `merged`, `completed_without_merge`,
`declined`, and the two **unresolved** arms — `pending` (the merge submission or poll did
not conclude) and `unexpected_enqueued` (a merge queue took the request). An unresolved
LAND operation blocks further landing until it concludes: once the merge settles (or its
request expires), `perk objective stack recover` classifies it against fresh authority and
concludes it — an `all_after` rolls forward automatically. On a close the envelope carries
the journal-assembled `reconcile_evidence` (per-layer PR + base/head/merge-commit SHAs —
diff identities, never stored patches) and the human render prints the
`/objective-reconcile` hint; a partially-landed train's remainder re-lands via
`stack sync --base` then `land`.

Exit codes: a **blocked** verdict under `--dry-run` is a successful detection ⇒ exit `0`
(the `stack status` split), and every mutation outcome above is exit `0`; `1` = typed
failures (`land_blocked` — the readiness report rides the failure, `land_failed`,
`merge_async_unavailable` — the repo has no merge-async access, `merge_request_conflict` — a
foreign merge request exists for the top PR, `land_drift`, `confirmation_required`,
`operation_in_progress`, `plan_not_found`, an incremental objective as `not_stacked`,
reconstruction failures, `no_objective`); `2` = not-a-repo.

## Related

- **Do:** [How to author an objective roadmap](../../how-to/author-a-roadmap.md) — stand up the objective these commands drive.
- **Look up:** [Objectives — the roadmap model](../objectives.md) — the node model and delivery policies behind the commands.
- **Understand:** [Gists, plans, and objectives](../../explanation/gists-plans-and-objectives.md) — why objectives emit plans instead of being implemented.
