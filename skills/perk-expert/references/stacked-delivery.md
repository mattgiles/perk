# perk stacked delivery (the atomic PR train)

An objective's reviewed **delivery** choice is how its node plans land (see
[Mental model](./mental-model.md) for the objective itself). This reference is the stacked
half: the train model, the daily workflow, the command surface, recovery routing, and the
current limitations.

## The delivery choice

- **`incremental`** (the default, and the recommended choice) — each node plan lands as its
  own independent PR against the objective's base. Omitting the choice means incremental;
  nothing is written to the header.
- **`stacked`** — all non-skipped roadmap nodes land as **ONE atomic pull-request train**.
  The reviewed choice is recorded at save as `delivery: stacked` plus a stable
  `delivery_lineage` (the train's identity); absence means incremental. The authoring review
  surface shows the choice as a prominent `**Delivery:**` line so it cannot be approved by
  accident.

Choosing stacked is validated at save (2–100 non-skipped nodes, no duplicate ids / unknown
deps / cycles) and **capability-checked against the real Git/GitHub plane** — the
native-stack API surface, squash direct-merge allowed and no merge queue on the base, and an
atomic-push dry-run — *before* anything is written. A repository that can't take a train gets
an honest typed `capability_unsupported` refusal naming the exact expected-vs-observed facts
(nothing was written); the fallback is authoring the same roadmap with incremental delivery.

## The train mental model

- **One layer per non-skipped node**, in the roadmap's **canonical delivery order**
  (bottom→top). Each layer's branch starts from its predecessor's branch, and each draft PR
  targets the **parent layer's branch** — so every PR's diff is exactly that layer's work,
  nothing beneath it. The layers are registered together in a **native GitHub stack**.
- **The published prefix.** Publication proceeds bottom→top; `perk objective stack status`
  renders it as `published prefix k/n`. Publication **checkpoints** are written only after
  every remote postcondition verifies.
- **The operation journal.** Every mutating stack operation (publish, sync, adopt, land,
  transfer) is journaled on the objective *first* — a crashed operation stays
  recoverable/concludable rather than lost.
- **Node selection is build-readiness- and handoff-derived.** Planning selects the next
  **build-ready** layer in delivery order — not merely the next pending node — which permits
  planning the next layer while its predecessor is published-but-unmerged — AND requires each
  of the candidate's **direct dependencies** to be done/skipped, landed, or a
  verified-published layer whose handoff stamp is `ready`. An explicit `--node` naming the
  wrong layer refuses typed `node_not_build_ready`; a candidate whose dependency lacks a
  `ready` stamp refuses typed `node_not_handoff_ready` — the remediation is the copyable
  `perk ready <PLAN>` on the blocking dependency's plan. `stack status` carries the
  `next build-ready:` line (or `build blocked: <reason>`) plus the `planning_gate` block and
  the `planning gated: …` lines when handoff-blocked. Publication, submit, address
  finalization, sync, recover, and re-ready are never handoff-gated; in-flight work resumes
  ungated (only a fresh layer start refuses).
- **The PR body is presentation, not authority.** perk inserts a `### This layer` section and
  a `### Train context` table into each layer PR's body; both are **non-authoritative** and
  refresh only at publication — the delivery train itself is the authority.

## Daily work: submit, address, ready — and the cascade

- **Publish through the ordinary `/submit`.** A stacked layer's `/submit` opens the draft PR
  onto the parent layer's branch, registers it in the native stack, and writes the
  publication checkpoints only after verifying the remote state. A failed stacked submit
  leaves a recoverable journaled operation — re-running `/submit` resumes it.
- **A committed rewrite of a published lower layer needs no explicit sync.** Re-run `/submit`
  (or finish `/address` through `finalize_address`) and perk **automatically cascades** the
  claimed published suffix: only the invoking plan's committed head is a local source, and
  every successor is rewritten from its verified published head. The result says how many
  layers moved (or that the suffix was already in sync).
- **`/ready` is the deliberate post-review human handoff.** Review happens on the **draft**
  layer PR; after review + address, `/ready` stamps the exact verified published head into
  the delivery journal — on draft AND non-draft PRs alike (mark-ready mechanics first, then
  the journal append) — and flips a draft ready-for-review. It is never routine post-submit
  choreography. A failed/ambiguous stamp exits `ready_stamp_failed` with the truthful
  `pr`/`was_draft`; the ambiguous/transient arms converge on an idempotent re-run (the
  deterministic stamp key), deterministic failures name their own repair. The recorded stamp
  **unblocks planning of the layer's direct dependents** (the handoff gate above); the run
  supervisor pauses as `handoff_required` — naming the same `perk ready <PLAN>` — rather than
  ever auto-running it. Readying still
  never merges anything — a fully-ready train waits, whole, for its landing.
- **The stamp continues into the ready-time reconcile pass.** Every successful stacked stamp
  (an `existed=true` re-stamp included) immediately reconciles the objective against the
  accepted layer's pinned diff range `parent_checkpoint..stamped_head` — while future work is
  still fluid, without pretending the layer landed. Warm (`/ready` in a session): the same
  session is driven into the pass; a read-only (gated) session or a malformed envelope refuses
  LOUDLY and skips — the stamp stands. Cold: `perk ready <PLAN>` (the flat spelling) is the
  **continuation wrapper** — the exact `perk pr ready` worker mechanics, then, in an
  interactive terminal (stdin+stdout TTYs, no `--json`/`--dry-run`), a seeded reconcile
  session launched in the main checkout (borrowing the `objective-save` stage descriptor,
  binding trigger `command:objective-reconcile`). `--json`, `--dry-run`, non-TTY, and headless
  runs emit **facts only** — the worker envelope (now also carrying `plan` +
  `parent_checkpoint`), never a session. A launch failure after a successful stamp is a second
  reported outcome (exit 1, loud stderr): the stamp is never rolled back; re-run
  `perk ready <PLAN>` to retry the pass. The pass's powers: Reconcilable prose, node
  **descriptions**, and guarded `pending` **tail-appends** only — no status/PR mutations
  (nodes stay `in_progress` until the train lands).
- **The stacked node-add guard.** On a stacked objective, `add_objective_node` /
  `perk objective node-add` is validated by the store against its own fresh read as a strict
  tail-append (one new `pending` node ordering strictly last; no mode flip, no edge or
  delivery-order change to existing nodes; dry-run included). A refusal is typed
  `stacked_append_refused` and routes structural changes to `perk objective replan`.
- **`perk pr land` / `/land` refuse a stacked layer** typed `stacked_plan` before any
  mutation: a layer PR targets its parent's branch, so landing one alone would merge into the
  wrong target and tear the train. Landing is objective-scoped and atomic (below).

## The command surface

Four cold commands under `perk objective stack`; `OBJECTIVE` is inferred from the current
plan worktree's linked objective when omitted.

- **`perk objective stack status [OBJECTIVE]`** — read-only end to end: reconstructs the
  delivery train from the durable authorities (objective store, plan issues, the operation
  journal, Git refs, GitHub PR + native-stack state) and reports one line per layer
  bottom→top, classified **blockers** and **information** findings (each naming
  expected-vs-observed), and the `next build-ready:` line. The per-layer axes include
  `handoff`, derived from **ready-stamp journal events** (a non-operation journal event kind:
  objective-identity-scoped and bound to the exact published head it was made at) —
  `unstamped` = no stamp names the layer's current verified published head under this
  objective; `stale` = the head moved past the latest stamp; `suspended` = the PR is currently
  draft while the stamp still matches (a transient hold); `ready` = the latest stamp matches
  and the PR is ready-for-review; `not_applicable` for landed/unpublished/unverified layers.
  The report also carries **recovery
  visibility**: every unresolved operation, the pending conflict-continuation manifest, and
  the orphaned-residue observation. Blockers found is still exit 0 — status is a successful
  *detection*.
- **`perk objective stack sync [OBJECTIVE]`** — the explicit transactional cascade. Owner of
  `--base` (re-anchor the train onto the advanced objective base), `--adopt NODE` (accept one
  layer's manually-pushed remote head and cascade above it), `--dry-run` (preview, nothing
  mutates), and `--continue`/`--abort` (resume or discard a retained rebase-conflict
  continuation — you finish the rebase yourself; perk never drives conflict resolution). The
  cascade is computed in an isolated disposable worktree, rendered for **confirmation**,
  journaled, and pushed as **ONE atomic multi-ref push** under exact per-ref leases (every
  ref moves or none does). Typed refusals before anything is pushed: out-of-band drift
  (`remote_drift` / `pr_drift`), a dirty claimed worktree, an active remote writer on a
  claimed plan, and more.
- **`perk objective stack recover [OBJECTIVE]`** — **conclude-only** recovery. Classifies
  every unresolved operation against fresh authority: `all_after` (every effect verified)
  rolls forward automatically; a proven `all_before` (never applied) is abandoned under
  confirmed `--abandon`; an `external_prefix` (LAND only: a bottom-contiguous prefix merged
  outside the operation) is accepted under confirmed `--accept-prefix`; `in_flight` and
  `mixed` only ever report. Every invocation also runs the finalization convergence pass
  (idempotent re-finalization of corroborated merged layers) and sweeps orphaned sync
  residue.
- **`perk objective stack land [OBJECTIVE]`** — `--dry-run` is the typed **ready/blocked**
  readiness verdict with the exact per-PR facts and the would-be land plan (read-only, no
  confirmation). Bare `land` is the confirmed, journaled **atomic** merge of the WHOLE
  remaining train, then per-layer finalization (plan issues closed, nodes marked done) and
  the objective close once every node is terminal. The honest unresolved outcomes —
  `pending` (the merge submission or poll did not conclude) and `unexpected_enqueued` (a
  merge queue took the request) — block further landing and conclude via `stack recover`.

In-session, the same surface is four warm doors plus five tools (mutations stay canonical in
the Python CLI — every tool delegates to the cold workers; the objective is inferred
everywhere: explicit argument → the session's active objective → the plan-ref's linked
objective):

- **`/objective-stack [N]`** — the direct read door: render the train, build readiness,
  blockers, unresolved operations, any pending continuation, and the residue observation.
  Works in every session, including read-only ones.
- **`/objective-sync [N]`**, **`/objective-recover [N]`**, **`/objective-land [N]`** —
  preview first (`dry_run: true`), present the cascade/classification/land plan, act only on
  your explicit approval. In a **read-only session all three soft-refuse** — finish or exit
  the gated session first.
- The paired tools are **`objective_stack_status`**, **`objective_stack_sync`**,
  **`objective_stack_adopt`**, **`objective_stack_recover`**, and **`objective_stack_land`**.
  Mutations run only on explicit approval: `objective_stack_sync`'s modes are mutually
  exclusive (mirroring the CLI's flag matrix), and the mutating `objective_stack_adopt` /
  `objective_stack_land` calls — and `objective_stack_recover`'s `abandon` / `accept_prefix`
  — **require `confirm: true`** (preview first).

## Recovery routing

The first move is always **read-only visibility**: `perk objective stack status` shows
unresolved operations, the pending continuation, and orphaned residue;
`perk objective stack recover --dry-run` classifies without acting. Then pick the matching
row:

| Symptom | First move | Conclusion |
|---|---|---|
| A fresh sync refuses `sync_conflict_pending` (a rebase conflict stopped a cascade; the refusal names the retained worktree + manifest) | Finish the rebase yourself in the retained worktree (`git rebase --continue`) — perk never drives conflict resolution | `stack sync --continue` revalidates the captured inputs and concludes the cascade; `stack sync --abort` discards the retained continuation (confirmation-gated) |
| An unresolved PUBLISH operation (a crashed `/submit`) | `stack recover --dry-run` | Recover only **reports** PUBLISH — re-run `/submit`; publish's own resume owns the conclusion |
| An unresolved SYNC or ADOPT operation | `stack recover` | `all_after` rolls forward automatically; a proven `all_before` is abandoned under confirmed `--abandon`; `mixed` only reports — investigate by hand |
| An unresolved TRANSFER (an interrupted stacked replan — planning refuses and names the predecessor) | `stack recover <old-objective-id>` — run it against the **predecessor** objective id the refusal names | A corroborating successor rolls forward to completion; an absent successor is abandoned under confirmed `--abandon`; `mixed` reports |
| An interrupted LAND (`pending` / `unexpected_enqueued`; further landing is blocked) | `stack recover --dry-run` — the journaled merge-request handle is probed against fresh per-PR observation | `all_after` rolls forward (layers finalized, objective closed); a proven `all_before` is abandoned under confirmed `--abandon`, then re-land; `in_flight` waits — rerun recover once the merge request settles; `mixed` reports |
| A prefix of the train was merged outside perk (someone pressed GitHub's merge button) | `stack recover --dry-run` | `external_prefix` → confirmed `--accept-prefix` records the breach and finalizes the merged layers; then `stack sync --base`, then `stack land` for the remainder. Caveat: an undeleted merged branch can leave the remainder's lowest PR reported as `pr_drift` until you delete it (GitHub retargets the PR) or retarget manually |
| A published branch was edited out-of-band — sync refuses `remote_drift` / `pr_drift` | `stack status` | A deliberate edit: adopt it with `stack sync --adopt NODE`; an edit you can't explain: investigate before adopting anything |
| The objective base advanced (`base_advanced` notice in the status report — a notice, never a blocker) | `stack status` | `stack sync --base` re-anchors the whole train onto the advanced base |
| Leftover `sync-*` worktrees or `refs/perk/sync/*` refs (a killed sync process) | `stack recover` | The **orphan sweep** collects residue no parseable continuation manifest claims; an unparseable manifest skips the whole sweep (`sweep_skipped` — an unreadable claim could be protecting anything) |

**Retry is never recover's verb.** Recover *concludes* — it rolls a verified `all_after`
forward, abandons a proven `all_before` under confirmation, or reports; when a retry is the
right move, the report names the **owning command** (`/submit` for PUBLISH, `stack sync` for
a cascade, `stack land` for a landing). Two classifications never act at all: `mixed` needs
human investigation, and `in_flight` needs the live merge request to settle or expire first.

## Current limitations

- **Merge-queue bases are unsupported.** The save-time capability check requires squash
  direct-merge and no merge queue on the base; at landing a queue-required base is a
  readiness blocker, and a queue seizing the merge request is the unresolved
  `unexpected_enqueued` outcome.
- **One train per objective.** All non-skipped nodes form ONE atomic train under a single
  `delivery_lineage`; there is no splitting a roadmap into independent trains or landing a
  subset. Exclude work from the train by skipping its nodes.
- **Delivery policy and base are immutable after first publication.** Base *advancement*
  stays normal (`stack sync --base` moves the base's head, not its identity). Replanning is
  transfer-based and preserves both — the published prefix is carried exactly, and the old
  objective closes only after the successor verifies; an interrupted transfer concludes via
  `stack recover <old-objective-id>`.
- **In-place adoption is incremental-only.** `perk objective author --adopt-from` refuses
  stacked delivery — author a fresh stacked objective instead.
- **Never land layers individually.** `perk pr land` / `/land` refuse a stacked plan
  (`stacked_plan`) before any mutation — but GitHub's merge button will not refuse for you;
  the discipline is yours.
- **GitHub-native stacks are preview-quality.** The stacked-PR and atomic-merge APIs are a
  public preview; per-repo enrollment and merge-async availability are observable only at
  mutation time (`merge_async_unavailable`).

## Discover the live surface

The shape is here; the exact current flags and outputs come from perk itself:
`perk objective stack <cmd> --help` for each command's live flag set, and
`perk objective stack status` for the live train in front of you.

---

*Canonical source: `docs/user-docs/reference/objectives.md` (Delivery) + the stacked sections of
`docs/user-docs/reference/{cli,in-session}.md`; the teaching pages
`docs/user-docs/tutorials/drive-a-stacked-objective.md`,
`docs/user-docs/how-to/review-a-stacked-train.md`, and
`docs/user-docs/how-to/recover-a-stacked-train.md`.*
