# Dogfood: the stamped stacked lifecycle (Objective #1951, Node 4.1)

**Status: PASSED 2026-08-22.** This validation record (the
`stacked-publication-dogfood` genre — Part A the repeatable protocol, Part B the dated captured
evidence + defect log) proves the **stamped** stacked lifecycle live in the designated durable
dogfood repository (`mattgiles/perk`): publish → handoff stamp → gated planning → ready-time
reconcile → stale/suspend/re-ready repair → objective land — driven same-day on the real
2-layer docs train **#1980** (PRs #1982/#1984, merged atomically as operation
`01M0NVZKKZ0MZCVPJH8TZ3B5W9`). **Overall verdict: PASS** (the § Verdict matrix's
all-arms-pass row; **zero defects** — the defect log holds only two named non-defect
observations; unfired capture-if-fired arms stand as named residuals pinned to their hermetic
suites). Part B and the Verdicts section are complete; per § Sequencing this record's PR
leaves draft only at the explicit review gate.

**Prior vs current coverage.** The prior lifecycle record
[`stacked-delivery-dogfood.md`](./stacked-delivery-dogfood.md) (objective #1698, PASSED
2026-08-13) **predates the ready stamp**: its Step-6 "ready" evidence is three
`perk pr ready --json` draft flips with no stamp, no gate, and no continuation. Per the
record-supersession craft (`docs/learned/workflow/doc-reconciliation.md`), the changed flow gets
this NEW record, cross-annotated both ways at evidence-fill. **This record covers what the prior
one structurally could not** (the behavior landed by nodes 1.1–3.1 of objective #1951 — merge
PRs #1960, #1969, #1975, #1977):

- the **handoff stamp as a journal fact** — the ready-stamp journal event, head-bound and
  reconstructable from durable authority;
- the **direct-dependency planning gate** — the typed `node_not_handoff_ready` refusal and every
  next-action surface naming the same blocker;
- the **ready-time reconcile continuation**, both carriers — warm `/ready` (in-session drive)
  and the flat `perk ready <PLAN>` wrapper (seeded-door launch);
- the **suspend hold** (`gh pr ready --undo` → `handoff suspended`) and its idempotent resume;
- **staleness both ways** — self-rewrite AND cascade rewrite — with the idempotent re-ready
  repair; and
- the **stamped train's atomic land** (the stamp is a planning control, never a landing
  prerequisite — proven by omission at S10).

Facts NOT re-proven (reused from the prior gates' records by reference): native-stack host
schema + live per-repository enrollment, merge-async availability, atomic push,
fresh-checkout/durable-authority independence, and deliberate landing interruption → recovery.
All sessions run from the dev checkout; no second clone this time (a deliberate scope note, not
a gap).

**The substrate is the deliverable** (the #1698 pattern). The train under proof is a real
2-layer docs objective whose merged layer PRs ARE node 4.1's documentation deliverables — the
drive-a-stacked-objective tutorial refresh, the stacked how-to extensions (including the new
handoff-repair table), and the perk-expert stacked-delivery mirror (§ Train spec). This record's
own PR carries only the protocol + the coherence-audit matrix + the evidence + the annotations;
the two deliverables touch disjoint files by construction (§ File-ownership boundary).

## Part A — the repeatable protocol

### Train spec (Deliverable B, pinned)

Authored live at S1 through `perk objective author`, delivery answered **stacked** past the
reviewed choice. **2 nodes, node 2 depends on node 1** — one dependency edge is all the gate
needs (stack create/append breadth and fresh-checkout independence are #1698's proven facts, not
re-proven). Cosmetic authoring drift (title/slug/id shape) is tolerated and recorded, as in the
prior gate; the material pins must hold. The node descriptions below are the layer planning
sessions' only scope input; each names this record's § Coherence-audit matrix (already committed
on this record's branch by then) as the fix census source:

**Node 1 — user-docs (bottom layer).** Docs-only.
(a) `docs/user-docs/tutorials/drive-a-stacked-objective.md`: teach the ready-time reconcile
continuation where the reader first meets `/ready` (Step 5: after the stamp, the same session is
driven into the ready-time reconcile pass over the pinned `parent_checkpoint..stamped_head`
range — Reconcilable prose / node descriptions / guarded tail-appends only, never status/PR; the
flat `perk ready <PLAN>` does the same from a terminal); refresh every `stack status` excerpt
from REAL captured output (the `handoff <state>` layer suffix, the `planning gated` shape); keep
Step 7's stale-re-stamp teaching and add one sentence on the draft-conversion hold (pointing to
the how-tos for repair detail).
(b) `docs/user-docs/how-to/review-a-stacked-train.md`: extend step 4 — the stamp continues into
the ready-time reconcile pass; converting a stamped PR back to draft is a transient hold (any
un-draft resumes); address commits stale the stamp naturally and the author re-readies.
(c) `docs/user-docs/how-to/recover-a-stacked-train.md`: a new **Handoff repair** table — rows
for: planning refuses `node_not_handoff_ready` / next-action names a handoff blocker (→ the
copyable `perk ready <PLAN>` on the blocking dependency); `handoff stale` after a rewrite or
cascade (→ re-review the new head, then re-ready); `handoff suspended` (a draft-converted hold;
→ any return to non-draft resumes, e.g. the idempotent `/ready` re-run); the stamp succeeded but
the reconcile session failed to launch (→ the stamp stands; re-run `perk ready <PLAN>`);
`stacked_append_refused` from the ready-time pass's tail-append guard (→
`perk objective replan`).
(d) Conditional: any user-docs fixes the § audit matrix surfaced (may legitimately no-op;
`advance-an-objective-headlessly.md` expected no-op).
No new pages — no sidebar registration; satisfy `tests/test_user_docs_metadata.py` and the docs
gate.

**Node 2 — the perk-expert mirror (top layer).** Docs-only, self-contained.
`skills/perk-expert/references/stacked-delivery.md`: mirror node 1's canonical content — add the
handoff-repair routing rows to "Recovery routing", verify the "Daily work" stamp/continuation
narrative against the landed behavior, and keep the canonical-source footer current. Touch
`skills/perk-expert/SKILL.md` / `references/mental-model.md` only if a routing cue actually
changed (expected no-op).

### File-ownership boundary

The train owns `docs/user-docs/` and `skills/perk-expert/`. This node's PR owns
`docs/design/archive/stacked-ready-handoff-dogfood.md` (this record), the evidence-fill annotation files
(`docs/design/archive/stacked-delivery-dogfood.md`'s Status line;
`docs/learned/workflow/objective-delivery.md` conditionally — a stated no-op is legitimate),
`docs/planning/archive/stamp-stacked-objective-nodes-ready.md` (the A4 seed annotation, committed with
this scaffold), `docs/index.md`, and `CHANGELOG.md`. No overlap. The train's layers add no
CHANGELOG entries; this PR's ONE `[Unreleased]` entry is written at evidence-fill time to match
the actual verdict (never pre-claimed).

### Provenance (the pinned binary)

One pinned binary from the **main checkout at a recorded SHA**:

```bash
uv tool install --force --from <main-checkout-path> perk
```

Record `which perk` + `git -C <main-checkout-path> rev-parse HEAD` at every phase boundary (a
provenance row in Part B). The driving (dev) checkout runs `npm ci` before driving (extension
parity — in-session doors run the checkout's extension source). The restart boundary after any
perk code fix is in § Failure policy. Never drive with an unpinned `perk`.

### Evidence sources (pinned per fact)

Machine facts, per source — never warm-envelope fields alone (the journal comments are the
durable authority):

- **PR facts:**
  `gh pr view <n> --json number,state,isDraft,baseRefName,headRefName,headRefOid,mergedAt`
- **Journal events** — the PUBLISH/SYNC/LAND operation transitions AND the **ready-stamp
  events** (the §8.43 non-operation journal event kind; its deterministic marker names the
  stamped head: `<!-- perk:stack-ready-stamp:<objective-id>:<plan-id>:<node-id>:<head-sha> -->`):
  `gh issue view <N> --comments` on the docs objective's issue.
- **Train facts:** `perk objective stack status <N> --json` — the `handoff` axis per layer,
  `planning_gate`, the blocker rows, `next_build_ready`.
- **Ready facts:** the `perk pr ready --json` envelope — `stacked`, `objective`, `node`,
  `stamped_head`, `stamp_advanced`, `reconcile_notice`, `reconcile_retry`, `plan`,
  `parent_checkpoint`.
- **Next-action facts:** `perk objective next <N> --json` / `perk objective show <N>` /
  `perk objective plan <N> --dry-run`.

Warm-session facts (the in-session `/ready` continuation, the seeded-session launch) are dated
operator attestations paired with their durable machine halves — the evidence-gap honesty
pattern (a category distinct from named residuals). Every decisive excerpt is inlined in this
record; scratch logs are deleted at the S11 sweep.

### The coherence-audit matrix (source-verified 2026-08-22, pre-run)

One row per surface: the exact phrase/vocabulary → source anchor → agrees? → disposition
(`agrees` / `doc fix → train layer N` / `runtime follow-up #<issue>`). Source-verified against
this branch (main @ `7d90db1c` + this record's scaffold) **before** the live run; the live
captures cite back into these rows as Part B fills (e.g. the S3 refusal, the S8 stale rows).
Expected audit outcome, verified below: **runtime surfaces agree; every finding is doc-side.**
The shared source of truth is `handoff_blocker_phrase`
(`src/perk/cli/commands/objective/shared.py`):
`<dep> (plan #<p>, PR #<pr>) — <state>[; stamped <sha12> ≠ head <sha12>]; record the handoff:
perk ready <p>`.

#### Family 1 — status

| Surface | Phrase/vocabulary | Source anchor | Agrees? | Disposition |
|---|---|---|---|---|
| `stack status` layer line | `handoff <state>` suffix appended for every non-`not_applicable` layer (vocabulary `ready`/`stale`/`suspended`/`unstamped` from `LayerHandoff`) | `status_cmd.py::_layer_line`; `src/perk/delivery/train.py::LayerHandoff` | yes | agrees |
| `stack status` gate lines | `planning gated: <node> waits on <dep> (plan #<p>, PR #<pr>) — <state>[; stamped <sha12> ≠ head <sha12>]; record the handoff: perk ready <p>` — recomposed fields-only from the §8.46 rows, byte-matching `handoff_blocker_phrase`'s shape | `status_cmd.py::_gate_row_phrase` + `_render_human` | yes | agrees |
| stale disclosure | `stamped <sha12> ≠ head <sha12>` — identical in all four renders | `shared.py::handoff_blocker_phrase`; `status_cmd.py::_gate_row_phrase`; `facade.py::_handoff_blocker_detail`; `objectiveStack.ts::renderStackStatus` | yes | agrees |
| `TrainOut` envelope | `LayerOut.handoff` (declared last — additive §8.44 growth); `planning_gate` = `PlanningGateOut{node_id, ready, blockers}`; handoff rows fields-only with `remediation: "perk ready <p>"` | `status_cmd.py::LayerOut/TrainOut`; `shared.py::GateBlockerOut/PlanningGateOut` | yes | agrees |
| warm `renderStackStatus` | layer suffix `handoff <state>` (non-`not_applicable` only); `planning gated: … record the handoff: <remediation>` from the pinned row fields; same stale disclosure | `extension/doors/objectiveStack.ts::renderStackStatus` | yes | agrees (the warm layer line composes branch-first by design — a lenient-decoder render; the handoff vocabulary and gate line are identical) |

#### Family 2 — next-action

| Surface | Phrase/vocabulary | Source anchor | Agrees? | Disposition |
|---|---|---|---|---|
| shared phrase | `record the handoff: perk ready <p>` — the one composed source every gate consumer renders | `shared.py::handoff_blocker_phrase` / `handoff_blocked_summary` | yes | agrees (the source row) |
| `objective next` | human: `handoff blocked: node <id> waits on <phrase>` per blocking layer; JSON: `build_ready.blockers` carrying the `kind: "handoff"` rows (`dependency_node_id`, `plan`, `pr`, `handoff_state`, `stamped_head`, `current_head`, `remediation`) | `next_cmd.py` | yes | agrees |
| `objective show` | `next: — (handoff blocked: <summary>)`; JSON `stacked_readiness {checked, ready, reason, blockers}`; live-read degrade: `readiness unchecked (<error>) — check: perk objective next <N>` | `show_cmd.py` | yes | agrees |
| run supervisor | `handoff required — <reason> (run: <remediation>; a human records the handoff — never auto-run)`; payload `action: "handoff_required"` + the shared blocker rows; lower-layer address attention deliberately runs first | `run_cmd.py` (the `handoff_required` arm + `_render_run`) | yes | agrees |
| run supervisor `ready_for_review` | names both orderings: `incremental: /ready opens the draft for review, then /land; stacked: review + address on the draft, then /ready records the handoff (the train lands via /objective-land); never auto-run` | `run_cmd.py::_render_run` | yes | agrees |
| plan resume | `draft layer PR — review proceeds on the draft; when review + address are done, record the handoff with perk ready <p> (this also unblocks planning of dependent nodes); the train lands whole via /objective-land` | `resume_cmd.py::_gate_message` | yes | agrees |
| `objective plan` refusal | `Node <id> is not handoff-ready: it waits on <detail>` + `Inspect the train: perk objective stack status <N>`, typed `node_not_handoff_ready` | `plan_cmd.py::_planning_node_choice` | yes | agrees |
| implement fresh-start refusal | `layer <node> (plan #<p>) cannot fresh-start: it waits on the handoff of <detail>`, typed `node_not_handoff_ready`; resumes stay ungated by construction | `facade.py` (execution-Prepare gate) + `_handoff_blocker_detail` | yes | agrees |
| submit/address completion | the stacked submit result reports publication + cascade facts only (`stacked layer → targets <branch>`, `cascaded N layer(s)`, stack suffix) and makes **no next-action claim**; the handoff cue rides `perk resume`, the supervisor, and the `/ready` surfaces | `submit_cmd.py::_render_human`; `extension/doors/submit.ts` | yes | agrees (silence, not disagreement — no surface says a node is next that another would refuse to plan) |

#### Family 3 — dry-run

| Surface | Phrase/vocabulary | Source anchor | Agrees? | Disposition |
|---|---|---|---|---|
| `objective plan --dry-run` | payload `build_readiness: "unchecked (dry-run)"` (stacked only) — the dry run skips the live train reconstruction and SAYS so | `plan_cmd.py` | yes | agrees — *live S3 note (2026-08-22): the payload composes only when the offline selection resolves a candidate; on this train's shape the offline graph refuses `objective_in_flight` first (still honest — nothing claims the live check ran); the payload capture landed via `run --dry-run` instead* |
| `objective run --dry-run` | same `build_readiness: "unchecked (dry-run)"` honesty | `run_cmd.py` | yes | agrees |
| `perk pr ready --dry-run` | offline selection-validation only: "no backend or GitHub read, no delivery classification, so it cannot predict which arm a real run would take. Nothing is resolved, marked, or stamped"; human render mirrors it | `ready_cmd.py` (worker `--dry-run` help + `_render_human`) | yes | agrees |
| `perk ready --dry-run` | the wrapper adds "no launch" to the same offline honesty; never launches | `ready_cmd.py::ready_continuation` | yes | agrees |
| `stack land --dry-run` | the LIVE read-only readiness verdict + complete land plan ("Assess landing readiness and render the complete dry-run land plan (read-only)") | `stack/land_cmd.py` | yes | agrees — each dry-run surface honestly names what it did and did not check; `show`'s `readiness unchecked (<error>)` degrade uses the same "unchecked" vocabulary for a failed live read |
| the design seed | `docs/planning/archive/stamp-stacked-objective-nodes-ready.md` asks dry-runs to "perform the required live, read-only projection" — shipped behavior deliberately reports `unchecked (dry-run)` (objective #1951's human-approved cut) | the seed's Cold-door ergonomics bullet | **no** (a superseded design claim, not a runtime defect) | keep-and-annotate → the A4 dated Status note (this PR) |

#### Family 4 — warm-door

| Surface | Phrase/vocabulary | Source anchor | Agrees? | Disposition |
|---|---|---|---|---|
| `/ready` tool guidelines | "For a STACKED plan, /ready is the deliberate HUMAN handoff made AFTER review + address: it stamps the exact verified published head … the recorded stamp unblocks planning of the layer's direct dependents … Idempotent: an already-ready PR is success, and a re-run converges on the same stamp"; `ready_stamp_failed` names its remediation | `extension/doors/ready.ts` (guidelines) | yes | agrees |
| `markReady` result | `Handoff stamped` / `Handoff already stamped`: objective #N node <id> at <head> — mirroring the cold render verbatim | `extension/doors/ready.ts` vs `ready_cmd.py::_render_human` | yes | agrees |
| `driveReadyReconcile` | fires on EVERY successful stacked stamp (`existed=true` re-stamps included); announces `continuing into the ready-time reconcile pass — objective #<N>, pinned range <parent_checkpoint>..<stamped_head>`; the refusal arms (read-only session, malformed cohort, strict-validation failure) all warn LOUDLY and skip — "The handoff stamp stands; re-run `perk ready <plan>` to enter the pass" | `extension/doors/ready.ts::driveReadyReconcile` | yes | agrees |
| `/objective-stack` door | the warm render (family 1) + read-only-safe discipline | `extension/doors/objectiveStack.ts` | yes | agrees |
| `/land` stacked refusal | "land refuses a stacked-delivery plan (`delivery_lineage`): stacked layers land as one atomic train, never individually" | `extension/doors/land.ts` (guideline) vs `land_plan.py::_stacked_refusal` | yes | agrees |

#### Family 5 — cold-door

| Surface | Phrase/vocabulary | Source anchor | Agrees? | Disposition |
|---|---|---|---|---|
| `perk pr ready` (worker) | the two-spellings/one-worker §8.66 split: the worker never launches; `reconcile_notice`: "the ready-time reconcile pass was not launched — perk pr ready is the deterministic, non-launching worker; run perk ready <plan> in an interactive terminal to launch it"; `reconcile_retry`: `perk ready <plan>` | `ready_cmd.py` (module docstring, `_reconcile_notice`/`_reconcile_retry`/`_worker_tail`) | yes | agrees |
| `perk ready` (wrapper) | worker mechanics first, then the seeded launch (interactive TTY only; borrowed `objective-save` descriptor, binding trigger `command:objective-reconcile`); launch failure = the second reported outcome: "The handoff stamp already stands (nothing was rolled back); re-run to retry the pass: perk ready <plan>", exit 1 | `ready_cmd.py::ready_continuation` + `_second_outcome_exit` | yes | agrees |
| `perk pr land` refusal | "stacked layers land only as one atomic train, never individually … record the post-review handoff with /ready (perk ready <p>); the train lands whole via /objective-land (perk objective stack land)", typed `stacked_plan`, pre-mutation | `land_plan.py::_stacked_refusal` | yes | agrees |
| `stack` subcommand family | `status` renders family 1; `sync`/`recover` make no handoff claims (correct — repair paths are never handoff-gated); `land --dry-run` per family 3; landing carries **no stamp requirement** (verified: neither `land.py` nor `landing.py` consults the ready stamp — the stamp is planning control, not merge policy) | `stack/{status,sync,recover,land}_cmd.py`; `src/perk/delivery/{land,landing}.py` | yes | agrees |

#### Doc-side census (the fix routing — Decision 3: the train stays docs-only)

| Surface | Finding (verified 2026-08-22) | Disposition |
|---|---|---|
| `docs/user-docs/tutorials/drive-a-stacked-objective.md` | Teaches the gate (Step 5) and the stale re-stamp (Step 7), but has **no ready-time reconcile continuation story** and no suspend/draft-conversion-hold mention; its `stack status` excerpts predate the handoff axis — no `handoff <state>` suffix anywhere, and the Step-5 excerpt still shows layer 1 `pr #<pr-1> (draft)` after that step's own `/ready` flipped it | doc fix → train layer 1 (refresh excerpts from REAL captured output) |
| `docs/user-docs/how-to/review-a-stacked-train.md` | Step 4 names the stamp but not the continuation, the draft-conversion hold, or stale-after-address | doc fix → train layer 1 |
| `docs/user-docs/how-to/recover-a-stacked-train.md` | **No handoff-repair rows at all** (untouched by the gate PRs) | doc fix → train layer 1 (the new Handoff repair table) |
| `docs/user-docs/how-to/advance-an-objective-headlessly.md` | Already coherent: `ready_for_review` distinguishes incremental vs stacked; `handoff_required` names the printed `perk ready <PLAN>` and "the supervisor never auto-runs it" | agrees — expected no-op |
| `skills/perk-expert/references/stacked-delivery.md` | The most current teaching surface — the Daily-work stamp/continuation narrative and the `stack status` handoff-axis vocabulary (`unstamped`/`stale`/`suspended`/`ready`/`not_applicable`) match landed behavior; its **Recovery-routing table lacks handoff rows** | doc fix → train layer 2 (mirror node 1's repair table) |
| `docs/user-docs/reference/` stacked sections (`cli/objective.md`, `cli/plan.md`, `in-session/workflow-commands.md`, `objectives.md`) | Carry the gate/stamp/continuation vocabulary landed with nodes 1.1–3.1 (each PR shipped its reference-level updates) | agrees |

No genuine runtime wording change surfaced at source-verification time — the
`runtime follow-up #<issue>` disposition column stays empty unless a live leg falsifies a row
(any such finding routes to a named follow-up issue; the train stays docs-only).

### Steps (each pinned with expected-vs-observed capture in Part B)

All sessions from the dev checkout of `mattgiles/perk`; no second clone (fresh-checkout
independence is #1698's proven fact — a scope note, not a residual).

- **S0 — preconditions.** Pinned binary provenance row (`uv tool install --force --from
  <main-checkout> perk`; record `which perk` + the main SHA); `npm ci` in the dev checkout;
  capability rows REUSED from the prior gates by reference (same repo/base) with ONE fresh
  re-check: `gh api repos/{owner}/{repo}/rules/branches/main`; verify `gh pr ready --undo` is
  available (`gh pr ready --help`).
- **S1 — warm authoring.** `perk objective author` → the § Train spec roadmap, delivery
  `stacked` → save. Record: objective `<N>`, `delivery_lineage`, roadmap-vs-spec deviations
  (named, operator-accepted or re-authored).
- **S2 — layer 1 publish.** `perk objective plan <N>` → save; `perk implement <plan-1>` →
  in-session `run_ci` → `/submit` (draft PR onto `main`). Record: the plan header trio, PR
  facts, the PUBLISH journal pair, `stack status` (`handoff unstamped` on the published layer).
- **S3 — gated planning (the refusal, BEFORE any stamp).** Capture: `perk objective plan <N>`
  refusing typed `node_not_handoff_ready` (bare and/or `--node`); `perk objective next <N>
  --json` (the `kind: "handoff"` blocker row: `dependency_node_id`, `plan`, `pr`,
  `handoff_state: "unstamped"`, `remediation`); `perk objective show <N>`
  (`stacked_readiness`); `stack status` (`planning gated: … record the handoff: perk ready
  <plan-1>`); `perk objective plan <N> --dry-run` (`build_readiness: "unchecked (dry-run)"` —
  the dry-run-language capture).
- **S4 — stamp layer 1, warm carrier.** `/ready` in layer 1's session. Record: the stamp report
  facts; the journal's ready-stamp event (the marked comment, its deterministic key naming the
  stamped head); the announced in-session ready-time reconcile pass and its writes (Reconcilable
  prose / node descriptions / guarded tail-append) or its honest no-op; `stack status` →
  `handoff ready`.
- **S5 — suspend/resume.** `gh pr ready --undo <pr-1>` → `stack status`: `handoff suspended`
  (and next-action surfaces name the suspended blocker); `/ready` re-run in layer 1's session →
  PR non-draft again, envelope `stamp_advanced: false` (an `existed=true` re-stamp at the same
  head), `handoff ready`. The continuation fires again on the re-stamp (per design) — record it.
- **S6 — layer 2 publish.** `perk objective plan <N>` now selects node 2 (the gate passes —
  record the contrast with S3); implement → `run_ci` → `/submit` (stack CREATE; PR onto the
  layer-1 branch). Record the same fact set as S2.
- **S7 — stamp layer 2, warm carrier.** `/ready` in layer 2's session; record stamp + pass
  (writes or no-op). `stack status`: both layers `handoff ready`.
- **S8 — staleness, both arms.** The operator reviews layer 1's diff and leaves real feedback
  (primary), else the editorial-commit fallback (with the no-feedback attestation recorded —
  the leg still fires with real work). `/address` (or commit + re-`/submit`) finishing through
  `finalize_address` → the trigger-scoped cascade rewrites BOTH heads. Record: the SYNC journal
  record's before/after table; `stack status`: layer 1 `handoff stale` (self-rewrite) AND
  layer 2 `handoff stale` (cascade rewrite — the no-mechanical-carry fact live), each with the
  `stamped <sha12> ≠ head <sha12>` disclosure.
- **S9 — re-ready, wrapper carrier.** From an interactive terminal at the repo root:
  `perk ready <plan-1>` — the worker mechanics (fresh stamp, `stamp_advanced: true`) then the
  seeded reconcile session (borrowed `objective-save` descriptor, cwd = the main repo root);
  record the launch and the pass outcome. Then `perk ready <plan-2>` likewise. A launch failure
  after a successful stamp is the designed second outcome — record it and re-run (the stamp
  stands). `stack status`: both `handoff ready` at the post-cascade heads.
- **S10 — objective land.** `perk objective stack land <N> --dry-run` (typed readiness + land
  plan; nothing in the readiness consults the stamp — the by-omission capture) → confirmed
  `perk objective stack land <N>` → per-layer finalization, nodes done, objective closed; run
  the printed `/objective-reconcile` gesture (the post-land whole-train pass — commonly a
  no-op; record either way). No deliberate interruption this time (proven by the prior gate).
- **S11 — census + residue sweep.** PRs merged; docs live on main; objective closed; terminal
  `stack status`; scoped `perk worktree wipe` of the train worktrees + branch deletion +
  absence census; `just docs-check` green on updated main.
- **S12 — evidence-fill (this record's PR).** Part B complete; verdicts from the § Verdict
  matrix; the A3 cross-annotations + the `docs/index.md` row + the ONE actual-verdict
  CHANGELOG entry; final `run_ci`; `perk pr ready` this PR (incremental); finish with warm
  `/land`.

### Failure policy

The prior gate's, unchanged: every incident gets a defect-log row. Docs-content defects fix
through the train's own machinery (feedback → address → cascade). **perk code defects that
block the acceptance path** fix via an ordinary incremental PR to main, then the **restart
boundary**: reinstall the pinned binary from main @ the new recorded SHA (a fresh provenance
row), `npm ci` refresh, re-driven legs use freshly created sessions/worktrees, and each defect
row states which earlier evidence remains valid versus re-run. Non-blocking findings →
follow-up issues. Era-drift in pinned command shapes is corrected in place with a named
deviation, never silently. While a LAND operation is unresolved, no other train mutation runs.

### Verdict matrix (arm → overall)

| Arm | Pass condition |
|---|---|
| Gated-planning refusal (S3) | typed `node_not_handoff_ready` + every next-action surface naming the same blocker |
| Warm stamp + in-session continuation (S4/S7) | stamp journaled at the exact head; the pass entered (writes or honest no-op — either passes) |
| Suspend hold + idempotent resume (S5) | `handoff suspended` observed; re-`/ready` converges (`stamp_advanced: false`) and resumes `ready` |
| Stale via self-rewrite (S8, layer 1) | `handoff stale` + the `stamped ≠ head` disclosure after the address publish |
| Stale via cascade (S8, layer 2) | `handoff stale` on the mechanically rewritten successor — the no-mechanical-carry fact live |
| Wrapper re-ready + seeded-session launch (S9) | fresh stamps (`stamp_advanced: true`) + the seeded reconcile session launched (or the designed second outcome recorded and retried clean) |
| Ready-time pass behavior | writes or honest no-op — either passes; a fired `stacked_append_refused` is capture-if-fired |
| Atomic land + close + post-land reconcile (S10) | whole-train merge under one journaled operation; finalization/close converge; the post-land pass runs (a no-op is legitimate) |
| Audit coherence | every § matrix row dispositioned (agrees / landed doc fix / named follow-up) |

All arms pass → **PASS**. A wrapper-launch failure that retries clean → still PASS (the
designed outcome). Unfired capture-if-fired arms (the append-guard refusal, the
`ReadyStampError` arms, a retained sync conflict) → named residuals pinned to their hermetic
suites, no verdict degrade. A blocked landing or an unresolvable leg → BLOCKED/FAIL stated
honestly with the disposition, and the node finishes incomplete with a named follow-up (the
operator calls it). The CHANGELOG entry and the Verdicts section are written from this matrix
after the evidence exists — never before.

### Sequencing (what merges when)

1. **This record's implement session (front-loaded, pre-submit):** this file (Status: IN
   PROGRESS + full Part A + the Part B skeleton) + the source-verified § audit matrix + the A4
   seed-doc annotation (evidence-independent); one `run_ci`; `/submit`. **The PR stays DRAFT
   until Part B is complete.**
2. **Live legs (post-submit, operator-driven follow-up turns):** S0–S11, including authoring
   and driving the train; evidence lands as docs-only commits on this record's branch after
   each phase. The TRAIN lands (S10) before this record's PR does.
3. **Evidence-fill close (S12):** Part B + verdicts + the A3 cross-annotations + the
   index/CHANGELOG rows; ready + warm `/land`. On merge, node 4.1 completes (auto node-done),
   closing objective #1951 once terminal.

Split-eligibility: the record scaffold + audit matrix + A4 may land without the live legs ONLY
under the operator's explicit incomplete-finish call (§ Verdict matrix honesty rules); the
default is draft-until-filled.

### Out of scope

Re-proving stack create/append breadth, fresh-checkout/second-clone independence, deliberate
landing interruption + recovery, and the remote-runner arms — all proven by
[`stacked-publication-dogfood.md`](./stacked-publication-dogfood.md) /
[`stacked-delivery-dogfood.md`](./stacked-delivery-dogfood.md) and referenced, not repeated.
Runtime wording changes (Decision 3 — named follow-up issues only). New tests: the gate's
automatable preconditions are the ordinary suites landed with nodes 1.1–3.1
(`tests/test_objective_stack_cmd.py`, `test_objective_plan_cmd.py`, `test_objective_run_cmd.py`,
`test_pr_ready_cmd.py`, `test_resume.py`, `extension/doors/ready.test.ts`,
`objectiveStack.test.ts`). Contract changes: none expected (no behavior changes); a live leg
exposing a contract inaccuracy amends from shipped code in the fixing PR, not this one.
Linear-backend arms (the dogfood repo is GitHub).

## Part B — the captured evidence

> **Execution COMPLETE (2026-08-22).** Every live leg (S0–S11) ran the same day, the evidence
> landing here as docs-only commits phase by phase; S12 (this evidence-fill close) finalizes
> the verdicts and annotations.

### Provenance rows

| Phase boundary | Main-checkout SHA | `which perk` | Notes |
|---|---|---|---|
| S0–S1 (2026-08-22) | `e2cb9e5de3b9eb37668b9ad31fea449979b56fc7` | `/Users/mattgiles/.local/bin/perk` (`perk 3.1.0`, the uv tool shim) | operator-installed via `uv tool install --force --from ~/dev/github/mattgiles/perk perk` from the dev (main) checkout at that SHA; `npm ci` refreshed in the same driving checkout (operator-attested 2026-08-22) |

### S0 — preconditions

Captured 2026-08-22 (operator, dev checkout root).

| Check | Expected | Observed |
|---|---|---|
| provenance | pinned binary from main @ recorded SHA; `npm ci` in the dev checkout | `git rev-parse HEAD` → `e2cb9e5de3b9eb37668b9ad31fea449979b56fc7`; `which perk` → `/Users/mattgiles/.local/bin/perk`; `perk --version` → `perk 3.1.0`; `npm ci` run (attested — the provenance row above is the machine half) |
| branch rules re-check | `gh api repos/mattgiles/perk/rules/branches/main` → no required-review / merge-queue rule | `[]` — no branch rules of any type on `main` |
| suspend gesture available | `gh pr ready --help` documents `--undo` | present: `--undo   Convert a pull request to "draft"` (help caveats "If supported by your plan" — moot here: this public repo's draft layer PRs are already proven live by the prior gates) |
| prior capability rows | reused by reference (`stacked-publication-dogfood.md` Step 0, `stacked-delivery-dogfood.md` Step 0) — same repo/base | reused as pinned; the one fresh re-check is the rules read above (`[]` also re-confirms no merge-queue rule) |

### S1 — warm authoring

Executed 2026-08-22 (`perk objective author`, dev checkout, pinned binary). The docs objective:
**#1980** — "Stacked ready-handoff docs train: teach the ready→reconcile continuation + handoff
repair", created `2026-08-22T20:21:28Z`, `run_id: 01M0NHNAADZY64319WAGWZQVG0`. Header excerpt
(the machine facts for the delivery choice):

```yaml
status: active
base: null
delivery: stacked
delivery_lineage: 01M0NJ5ASVYS4VMBEWXXVJNXRA
```

- **Material pins — all hold:** `delivery: stacked`; `delivery_lineage` minted; default base
  (`base: null`); **2 nodes with the explicit dependency edge** (`1.2` → `depends_on: ['1.1']`);
  the descriptions carry the § Train spec verbatim-in-spirit — every file path, boundary, and
  scope guard intact (backticks and the `handoff <state>` token survived YAML rendering);
  node 1.1(d) names "the design record's § Coherence-audit matrix" as the fix census source.
- **Named deviations (cosmetic, recorded):** node ids `1.1`/`1.2` (one phase) vs the spec's flat
  "node 1 / node 2" — the same id-shape drift the prior gate accepted; slugs
  `user-docs-ready-continuation` / `perk-expert-mirror` (the spec pinned none). Two findability
  nits: the census pointer in 1.1(d) names the matrix but not its file path
  (`docs/design/archive/stacked-ready-handoff-dogfood.md` — and NOTE: the record lives on this PR's
  branch `plan-1978`, not yet on main, so the train's planning sessions must be pointed at
  PR #1979 to read it); and node 1.2's description does not itself name the census source —
  acceptable: 1.2 mirrors "node 1.1's canonical content", so the census reaches it
  transitively. Mitigation pinned for S2/S6: the operator names the record's branch/PR when
  driving each planning session.
- **Delivery-choice UX (dated operator attestation, 2026-08-22):** the authoring session asked
  the stacked-vs-incremental delivery question BEFORE the plannotator review, answered
  `stacked`. The header excerpt above is the machine half.
- **Capability preflight:** the save succeeded and created #1980, so the §8.45 preflight
  necessarily passed (it runs before the store mutation).
- **Post-save train read** (`perk objective stack status 1980`, operator capture, verbatim):

  ```text
  Objective #1980: stacked delivery train (base main, published prefix 0/2)
    lineage 01M0NJ5ASVYS4VMBEWXXVJNXRA
    1. 1.1 unplanned [unpublished] no pr
    2. 1.2 unplanned [unpublished] no pr
    next build-ready: 1.1
  no findings
  ```

  Both layers `unplanned [unpublished]` with **no `handoff` suffix** — the axis is
  `not_applicable` below verified publication, exactly as § matrix family 1 pins.

### S2 — layer 1 publish

Executed 2026-08-22 (dev checkout, pinned binary).

- **Warm planning** (`perk objective plan 1980` → plannotator review → save): plan issue
  **#1981** — "Document ready→reconcile continuation and handoff repair in user docs", created
  `2026-08-22T21:00:56Z`, with a fresh per-session run id (`01M0NJGBFVXGS4T5QR7PC0VJH1` ≠ the
  authoring session's `01M0NHNAAD…`). The saved header trio:

  ```yaml
  objective_id: '1980'
  objective_node_id: '1.1'
  delivery_lineage: 01M0NJ5ASVYS4VMBEWXXVJNXRA
  ```

- **Interactive implement** (`perk implement 1981`; operator-attested 2026-08-22): the implement
  run id journaled on the plan header (`impl_run_ids: [01M0NMFGS3K8H3K1J5S7ZQQQBG]`).
- **`run_ci`** (operator-pasted excerpt, 2026-08-22 — the in-session run-all report before
  `/submit`): `perk CI: all checks passed.` — `✓ docs-check`; lint/typecheck/test rows and
  `changelog-check` glob-skipped (a `docs/user-docs/`-only diff); terminal line "Full gate
  green — the change is verified …".
- **Publish (warm `/submit` — draft):**
  - PR facts: `gh pr view` → `{"number": 1982, "state": "OPEN", "isDraft": true,
    "baseRefName": "main", "headRefName": "plan-1981",
    "headRefOid": "f7f25f9d65577f0cb7df8fc0d8a440cfd5c4d5d1", "mergedAt": null}` — draft,
    base = the objective base (`main`).
  - Journal (issue #1980 comments): operation **01M0NMZ5VA370YA788SZMKJBCH**, `prepared`
    (comment 5382616947, 21:10:34Z) → `completed` (comment 5382617735, 21:10:46Z;
    `observed: {branch_sha: f7f25f9d…, pr: 1982, stack: null}`). The bottom layer creates no
    stack membership — expected and recorded.
  - The header's publish-written checkpoint pair: `parent_checkpoint_sha: e2cb9e5d…` (= the S0
    main SHA exactly) / `published_head_sha: f7f25f9d…`.
- **Train read** (`perk objective stack status 1980 --json`): `published_prefix_len: 1`;
  layer 1.1 `publication: "published"`, `pr: "draft"`, `membership: "not_applicable"`,
  **`handoff: "unstamped"`**, `observed_pr_base` = `expected_pr_base` = `main`; layer 1.2
  `unpublished`, `handoff: "not_applicable"`, `expected_pr_base: "plan-1981"`;
  `next_build_ready: {node_id: "1.2", ready: true}` (technical readiness) while
  `planning_gate: {node_id: "1.2", ready: false}` carries the one `kind: "handoff"` row
  (`handoff_state: "unstamped"`, `stamped_head: null`, `current_head: f7f25f9d…`,
  `remediation: "perk ready 1981"`); `blockers: []`; `unresolved_operation: null`. The human
  render, verbatim:

  ```text
  Objective #1980: stacked delivery train (base main, published prefix 1/2)
    lineage 01M0NJ5ASVYS4VMBEWXXVJNXRA
    1. 1.1 plan #1981 [published] pr #1982 (draft) writer active handoff unstamped
    2. 1.2 unplanned [unpublished] no pr
    next build-ready: 1.2
    planning gated: 1.2 waits on 1.1 (plan #1981, PR #1982) — unstamped; record the handoff: perk ready 1981
  no findings
  ```

  (`writer active` on layer 1 is the implement worktree's live writer claim — expected while
  the session's worktree exists; not a blocker.) The `handoff unstamped` suffix and the
  `planning gated` line match § matrix family 1 byte-for-byte.

### S3 — gated planning (the refusal)

Executed 2026-08-22 (pinned binary; the deterministic reads/refusals run from the record
branch's worktree — repo-root resolution is checkout-independent and every capture is
durable-authority-derived). All BEFORE any stamp exists.

- **The typed refusal** (`perk objective plan 1980 --json`, bare AND `--node 1.2` — identical
  envelopes, exit 1):

  ```json
  {"success": false, "error_type": "node_not_handoff_ready", "message": "Node 1.2 is not
  handoff-ready: it waits on 1.1 (plan #1981, PR #1982) — unstamped; record the handoff:
  perk ready 1981\nInspect the train: perk objective stack status 1980"}
  ```

- **`perk objective next 1980 --json`**: `next_node: null`; `build_ready.ready: false`;
  `build_ready.reason: "node 1.2 waits on 1.1 (plan #1981, PR #1982) — unstamped; record the
  handoff: perk ready 1981"`; `build_ready.blockers` = exactly one `kind: "handoff"` row
  (`dependency_node_id: "1.1"`, `plan: "1981"`, `pr: 1982`, `handoff_state: "unstamped"`,
  `stamped_head: null`, `current_head: f7f25f9d…`, `remediation: "perk ready 1981"`). Human
  render: `handoff blocked: node 1.2 waits on …` — the same composed phrase.
- **`perk objective show 1980`**: `next: — (handoff blocked: node 1.2 waits on 1.1 (plan
  #1981, PR #1982) — unstamped; record the handoff: perk ready 1981)`; `--json` carries
  `stacked_readiness: {checked: true, ready: false, reason: <same>, blockers: [<the same
  handoff row>]}` while `selection_kind: "in_flight"` stays the offline graph-derived
  observational fact — exactly the §8.46 split the matrix pins.
- **`stack status`**: the `planning gated:` line captured verbatim at S2 (above).
- **Dry-run language — a named in-place recipe deviation (not a defect):**
  `perk objective plan 1980 --dry-run --json` refused typed `objective_in_flight` ("No new
  node to plan: node 1.1 has a plan in flight (pr #1981, status in_progress)…") — the plan
  door's dry run keeps the OFFLINE graph classification, and on this train shape the offline
  graph (1.1 `in_progress`, 1.2 dep-gated) refuses before the seed composes, so the
  `build_readiness: "unchecked (dry-run)"` payload structurally cannot appear on the plan door
  here. Both surfaces stay honest: neither pretends the live check ran. The pinned capture
  routes to the supervisor instead — `perk objective run 1980 --dry-run --json` →
  `"build_readiness": "unchecked (dry-run)"` in the payload, with `action:
  "ready_for_review"` and the delivery-neutral human line rendered verbatim: "PR #1982 is at
  the human boundary — incremental: /ready opens the draft for review, then /land; stacked:
  review + address on the draft, then /ready records the handoff (the train lands via
  /objective-land); never auto-run" — live-verifying two § matrix rows (family 3's
  `run --dry-run` and family 2's `ready_for_review`) in one capture.

### S4 — stamp layer 1 (warm carrier)

Executed 2026-08-22 — `/ready` in layer 1's implement session (operator-driven, pinned
checkout extension).

- **Warm continuation announcement (operator capture, verbatim — the session's terminal
  output; the earlier `Marked ready` / `Handoff stamped` report lines were ephemeral and are
  covered by the durable halves below):**

  ```text
  perk: ready — continuing into the ready-time reconcile pass —
  objective #1980, pinned range
  e2cb9e5de3b9eb37668b9ad31fea449979b56fc7..f7f25f9d65577f0cb7df8fc0d8a440cfd5c4d5d1
  ```

  The pinned range endpoints equal the plan header's `parent_checkpoint_sha` /
  `published_head_sha` pair exactly (S2) — the §8.66 continuation contract observed live.
- **The PR flip (durable half):** `gh pr view 1982` → `isDraft: false`, `OPEN`, head unchanged
  at `f7f25f9d…`.
- **The ready-stamp journal event (durable half):** issue #1980 comment **5382684660**, created
  `2026-08-22T21:26:53Z` — the deterministic marker
  `<!-- perk:stack-ready-stamp:1980:1981:1.1:f7f25f9d65577f0cb7df8fc0d8a440cfd5c4d5d1 -->`
  carrying the full §8.43 record (`event: ready_stamp`, `objective_id: '1980'`,
  `delivery_lineage: 01M0NJ5ASVYS4VMBEWXXVJNXRA`, `plan_id: '1981'`, `node_id: '1.1'`,
  `head_sha: f7f25f9d…`).
- **Train read after the stamp:** layer 1.1 `pr #1982 (ready) … handoff ready`; the S3
  `planning gated` line is GONE — `planning_gate: {node_id: "1.2", ready: true, blockers: []}`
  (the S3→S4 gate contrast, captured both sides).
- **The in-session ready-time reconcile pass (completed 2026-08-22):** the pass judged
  exactly the pinned range (3 user-docs files, +71/−14) plus the engagement block, verified
  liveness (live head = stamped head, no drift), and made **one correctly-bounded write**: the
  Reconcilable prose now records the operator-approved two-phase excerpt-capture sequencing
  the accepted layer refined (phase-1 renderer-derived shapes — the Step-2 excerpt verified
  against this record's real S1 capture — with real-capture replacement on the same layer
  before the train lands, judged at land time). Durable half: objective comment 5382411634
  `updated_at: 2026-08-22T21:28:28Z`; the excerpt-discipline paragraph present in the
  marker-bounded Reconcilable region; the Mechanical roadmap table, Immutable region, node
  descriptions, and statuses/PR fields byte-untouched; no node adds (the pass judged the
  phase-2 refresh layer 1's own completion discipline, not a new unit of work — so the
  `stacked_append_refused` capture-if-fired arm did not fire here). Session report tail
  (operator capture): "The handoff stamp stands; planning of node 1.2 is now unblocked."
  **The warm-carrier arm's full sequence — stamp → announced continuation → bounded judgment
  pass → real write — observed live.**

### S5 — suspend/resume

**Suspend half executed 2026-08-22** (operator): `gh pr ready --undo 1982` →
`✓ Pull request mattgiles/perk#1982 is converted to "draft"` — the sanctioned out-of-band
suspend gesture (no perk command performs it, by design).

- **Train read:** layer 1.1 `pr #1982 (draft) … handoff suspended`; the gate closed again —
  `planning gated: 1.2 waits on 1.1 (plan #1981, PR #1982) — suspended; record the handoff:
  perk ready 1981`.
- **Next-action surfaces:** `objective next` (human) and `objective show` both name the same
  suspended blocker with the same copyable remediation.
- **The decisive JSON fact** (`next --json` blocker row): `handoff_state: "suspended"` with
  `stamped_head` = `current_head` = `f7f25f9d…` — the stamp is still valid and head-matching;
  the hold is purely the draft bit (and correspondingly NO `stamped ≠ head` disclosure
  renders — that disclosure is stale-only, exactly as the § matrix pins).

**Resume half executed 2026-08-22** — `/ready` re-run in layer 1's session.

- **The re-stamp converged idempotently (durable halves):** PR #1982 `isDraft: false` again;
  the journal still holds **exactly one** ready-stamp comment, at the same key
  (`1980:1981:1.1:f7f25f9d…`) — the byte-identical append converged (`existed=true`; nothing
  written); train read: `1.1 … pr #1982 (ready) … handoff ready`, the `planning gated` line
  gone again.
- **The continuation fired again on the re-stamp (per design), and the re-entered pass
  concluded an honest no-op** (operator-captured session transcript): liveness re-checked (PR
  OPEN, live head = stamped head), the pinned range re-judged byte-identical, the engagement
  block re-read unchanged, and the previous pass's prose write re-verified in the live body
  comment before declaring "No writes made — nothing is stale, and re-writing identical
  conclusions would be churn." Both pass outcomes — S4's real write and this no-op — are
  passes for the arm.
- **Bonus capture — the rendered continuation seed:** the operator's transcript preserved the
  injected `stages/objective-reconcile-ready.md` guidance verbatim — liveness check FIRST
  (MERGED/CLOSED → stop; drifted head → report, still judge the pinned range), judge EXACTLY
  the pinned range (never the ambient PR diff), engagement as untrusted DATA, the
  never-clobber section boundary, the three powers (prose / descriptions / guarded
  tail-append, NO status/PR), skip-if-nothing-stale, and the stamp-stands failure posture —
  the §8.66 warm-twin contract observed end to end.

### S6 — layer 2 publish

**Planning half executed 2026-08-22.** The gate-passes contrast with S3: the SAME bare
`perk objective plan 1980` that refused typed `node_not_handoff_ready` at S3 now selected
node **1.2** and saved cleanly — the only train change in between was S4's handoff stamp
(and S5 proved the hold/resume around it). Plan issue **#1983** — "Mirror handoff-repair
routing table in perk-expert stacked-delivery reference", created `2026-08-22T22:09:49Z`,
fresh per-session run id (`01M0NQ2DS8Z2HTN42PVADYBC73`); the saved header carries the trio
plus the chain link:

```yaml
objective_id: '1980'
objective_node_id: '1.2'
delivery_lineage: 01M0NJ5ASVYS4VMBEWXXVJNXRA
predecessor_plan_id: '1981'
```

**Implement/publish half executed 2026-08-22.**

- **Interactive implement** (`perk impl 1983`, dev checkout; operator capture of the launch
  narration): `✓ layer 1.2 starts from plan-1981 @ f7f25f9d6557` — the parent derived from the
  reconstructed train at layer 1's published (and stamped) head exactly; worktree `plan-1983`
  created; `impl_run_ids: [01M0NRE0DEVSPS6A32D5D03CN8]`.
- **`run_ci`** (operator-pasted, 2026-08-22): `perk CI: all checks passed.` — `✓ docs-check`,
  every code-suffix row glob-skipped (this layer's own files are `skills/perk-expert/**`;
  the branch's cumulative diff also carries layer 1's user-docs files — the conservative
  over-checking the prior gate recorded, still honest).
- **Publish (warm `/submit` — the stack CREATE):** submit result (operator capture):
  `Opened draft PR #1984 … (stack #1985, layer 2/2)`.
  - PR facts: `{"number": 1984, "state": "OPEN", "isDraft": true, "baseRefName":
    "plan-1981", "headRefName": "plan-1983", "headRefOid": "29d4375d5bf125b871c196bd5cb2672653438d77",
    "mergedAt": null}` — base = the layer-1 branch.
  - Journal (issue #1980): operation **01M0NRP6XWAHG4S00SZSGNDV7A**, `prepared` (22:15:35Z) →
    `completed` (22:15:49Z; `observed: {branch_sha: 29d4375d…, pr: 1984, stack: […]}`).
  - **Native stack registered:** `gh api 'repos/mattgiles/perk/stacks?pull_request=1984'` →
    stack **#1985** (`base: {ref: "main"}`, `open: true`, created 22:15:42Z), members
    bottom→top `[#1982 @ plan-1981 f7f25f9d… (non-draft), #1984 @ plan-1983 29d4375d…
    (draft)]`.
  - Checkpoint pair on the #1983 header: `parent_checkpoint_sha: f7f25f9d…` (= layer 1's
    published head exactly), `published_head_sha: 29d4375d…`.
- **Train read** (`perk objective stack status 1980`): `published prefix 2/2`; layer 1.1
  `pr #1982 (ready) stack exact … handoff ready`, layer 1.2 `pr #1984 (draft) stack exact …
  handoff unstamped`; `observed_pr_base` = `expected_pr_base` ×2 (`main` / `plan-1981`);
  `build blocked: all layers published or landed` (the honest technical no-candidate) with
  `planning_gate: {node_id: null, ready: false, blockers: []}` — the §8.46 no-candidate arm
  rendered exactly as pinned (no gate rows without a candidate).

### S7 — stamp layer 2 (warm carrier)

Executed 2026-08-22 — `/ready` in layer 2's implement session (operator-driven; the session
transcript captured the full rendered continuation seed again, now with layer 2's identities).

- **Continuation announcement (operator capture):** pinned range
  `f7f25f9d…..29d4375d…` — layer 2's own incremental diff exactly (its
  `parent_checkpoint_sha..published_head_sha` pair from S6).
- **The ready-stamp journal event (durable half):** the journal now holds **two** stamp
  comments — the new key `1980:1983:1.2:29d4375d5bf125b871c196bd5cb2672653438d77` (created
  `2026-08-22T22:21:39Z`) beside S4's untouched layer-1 stamp.
- **PR flip:** #1984 `isDraft: false`, OPEN.
- **Train read:** BOTH layers `(ready) stack exact … handoff ready` — the fully-stamped
  train S8 deliberately breaks. (`perk objective show 1980` now renders the graph-fallback
  `next: — (in flight: node 1.1 pr #1981)` — the §8.46 no-candidate fall-through; no surface
  claims a plannable node.)
- **The re-entered pass concluded an honest no-op with full re-verification** (operator
  transcript): liveness (live head = stamped head), the pinned-range diff recovered via
  `git fetch origin refs/pull/1984/head`, the accepted diff judged point-for-point against
  node 1.2's description (the five-row handoff-repair block added to Recovery routing; the
  Daily-work verification no-op the plan expected; the footer refresh; SKILL.md/mental-model
  untouched with cues confirmed), engagement folded (authoring-time description edits only),
  the new-node check explicitly empty — "skip — nothing is stale … no writes". Correctly
  bounded: no status/PR mutations; nodes stay `in_progress`.
- **Era note (recorded, not a defect):** `perk address [PLAN]` now accepts the positional
  plan id — the prior gate's d1 ergonomics follow-up (#1709) landed between gates; S8 uses
  the current shape `perk address 1981` (the prior record's `--worktree` shape remains valid
  but is no longer the ergonomic path).

### S8 — staleness (both arms)

Executed 2026-08-22 — the primary arm fired: real operator review feedback on layer 1, then
`perk address 1981` (the current-era positional shape) finishing through `finalize_address`.

- **The feedback (operator review on PR #1982, COMMENT review, one thread):** true up the
  tutorial's phase-1 renderer-derived `stack status` excerpts against the REAL captures from
  this gate's own train — the review comment carried the three verbatim renders (post-
  authoring, published-before-stamp with the `planning gated` line, both-published) as DATA.
  Honest, actionable, and it completes layer 1's own phase-2 excerpt obligation (the
  discipline S4's pass recorded on the objective).
- **The cascade journal record** (issue #1980): ONE trigger-scoped SYNC operation
  **01M0NTT5DZFNEX6CXBQV1GB4V2**, `prepared` (22:52:48Z) → `completed` (22:52:58Z; record
  created 22:52:56Z), observing the address publish rewriting layer 1 AND republishing the
  successor atomically:

  | Branch | Before | After |
  |---|---|---|
  | `plan-1981` | `f7f25f9d65577f0cb7df8fc0d8a440cfd5c4d5d1` | `ca046b8b06e44f5002333c3c349ab2f72ce63612` |
  | `plan-1983` | `29d4375d5bf125b871c196bd5cb2672653438d77` | `149a8dcfe4160ae7fb98a0644a4d4bc9c90eb010` |

- **PR settle:** #1982 and #1984 both `OPEN`, non-draft, bases unchanged (`main` /
  `plan-1981`), heads = the after-table SHAs exactly.
- **Thread resolution** (GraphQL `reviewThreads` on #1982): `isResolved: true`, the
  finalize-posted reply ("Regenerated all three stack-status excerpts byte-faithfully from
  the live renderer (_render_human/_layer_line), placeholder…") preceding the resolve —
  reply-then-resolve observed.
- **Both staleness arms, one read** (`stack status`): layer 1.1 `handoff stale`
  (self-rewrite) AND layer 1.2 `handoff stale` (cascade rewrite — **the no-mechanical-carry
  fact live**: the journal's two stamps still name `f7f25f9d…`/`29d4375d…` while the
  observed heads are `ca046b8b…`/`149a8dcf…`).
- **Named in-place observation (not a defect): the rendered `stamped <sha12> ≠ head <sha12>`
  disclosure is candidate-scoped by design** — it rides the gate/blocker rows
  (`handoff_blocker_phrase` / `_gate_row_phrase` / the §8.46 rows), and this fully-published
  2-layer train has no planning candidate, so no surface composes a gate row to carry it
  (`next`/`show` render the honest technical `build blocked: all layers published or
  landed`). The machine disclosure stands as the journal-stamp-keys-vs-current-heads
  comparison above; on a train with an unplanned dependent the gate row would render it (the
  S3/S5 captures show exactly that composition). The protocol's pinned "each with the
  `stamped ≠ head` disclosure" expectation is era-corrected to this candidate-scoped truth.

### S9 — re-ready (wrapper carrier)

Executed 2026-08-22 — `perk ready 1981` then `perk ready 1983`, each from an interactive
terminal at the dev checkout root (the flat wrapper spelling, positional plan selection).

- **Wrapper pre-session output (operator captures, both runs, same shape):** `✓ found plan
  #<p>` → `✓ Already ready: PR #<pr> is open for review` (the cascade preserved non-draft —
  the stamp still lands on a non-draft PR, per design) → `Handoff stamped: objective #1980
  node <id> at <post-cascade head>` (fresh stamps at `ca046b8b…` / `149a8dcf…`) →
  `launching the ready-time reconcile session…` → the pi banner (the seeded session opened
  in the main checkout). **The designed launch-failure second outcome did NOT fire** — both
  launches were clean (the arm stays capture-if-fired; § Named residuals).
- **The journal (durable half):** now **four** append-only stamp comments — the two
  superseded keys at `f7f25f9d…`/`29d4375d…` retained as history beside the two fresh keys
  `1980:1981:1.1:ca046b8b…` and `1980:1983:1.2:149a8dcf…`; the handoff axis derives from the
  LATEST stamp per plan, so the train reads both layers `handoff ready` at the post-cascade
  heads.
- **Seeded pass, layer 1 (operator transcript): honest no-op with a full divergence audit** —
  liveness (live head = stamped head `ca046b8b…`), the pinned range `e2cb9e5d…..ca046b8b…`
  judged (3 files, +81/−14, inside the train's ownership boundary), node 1.1's description
  matched point-by-point ((a)–(d), the conditional no-op included), the excerpt-discipline
  refinement confirmed already-recorded, engagement folded, "clean skip — nothing is stale."
  Plus the pass's own forward-looking note: a real-capture refresh would re-stale the stamp —
  "the documented repair is re-review + re-ready, exactly as the layer's own new docs teach."
- **Seeded pass, layer 2 (operator transcript): evidence-bound writes** — the pass found two
  real divergences in the accepted mirror (the handoff-repair guidance shipped as a distinct
  stamp-axis "Handoff repair" table rather than appended routing rows; the canonical-source
  footer re-pointed at the reorganized reference paths) and applied exactly its two
  in-bounds powers: `objective_node` description reconcile for 1.2 (no status/PR) and
  `reconcile_objective` prose rewrite (a layer-2 accepted-revision note in "accepted"
  language + the Why bullet reshaped). Durable halves verified: the 1.2 roadmap description
  now carries the accepted table shape; objective comment updated `2026-08-22T23:06:54Z`.
- **The land-time excerpt judgment — settled with evidence (2026-08-22):** the tutorial at
  the current layer-1 head `ca046b8b…` carries all three `stack status` excerpts
  **byte-faithful to this record's real captured renders modulo exactly the placeholder
  substitutions** (`1980→<N>`, `1981→<plan-1>`, `1982→<pr-1>`, `1983→<plan-2>`,
  `1984→<pr-2>`, lineage→01XXXX…) — the `handoff <state>` suffixes, `writer active`, the
  `planning gated:` line, and the 2/2 mixed state (`ready`+`ready` / `draft`+`unstamped`)
  all match the live renders. The two-phase discipline's land-time requirement is satisfied
  at the current heads; no further refresh commit is owed before landing.

Across S4/S5/S9 the ready-time pass has now exhibited its full designed behavior envelope
live: a real prose write, a verified no-op re-entry, a no-op with full audit, and a
descriptions+prose write — with the guarded tail-append the one power never exercised
(nothing warranted it; capture-if-fired, § Named residuals).

### S10 — objective land

**Readiness half executed 2026-08-22** (`perk objective stack land 1980 --dry-run`, run from
the record worktree — read-only): **`disposition: "ready"`**, `blockers: []`.

- `rules: {squash_allowed: true, merge_queue_required: false}`; native stack API surface
  present (host-schema evidence only).
- The exact bottom→top **LandPlan**: `mode: "stack_merge_async"`, `merge_method: "squash"`,
  `top_pr_number: 1984`, `top_head_sha: 149a8dcf…`; layers `[1982: e2cb9e5d… → ca046b8b…,
  1984: ca046b8b… → 149a8dcf…]` — each layer's `base_sha` = its predecessor's head; layer 1's
  = the S0 main head exactly (**main never advanced — the base-advancement cascade arm did
  not fire**; § Named residuals).
- Per-layer observations: `OPEN ready … MERGEABLE/CLEAN` ×2; information rows: two
  `active_worktree` advisories (landing merges remote PRs; local branches untouched) + one
  `optional_check_failed` on #1984 ("lint · typecheck · test") — diagnosed benign: the GHA
  run on `plan-1983` at 22:52:55Z was **CANCELLED** (superseded by the cascade push's
  concurrency cancel) and the current run on the same head is SUCCESS; the rollup reports
  both (the prior gate's d2 "duplicate check-run reporting on cascade-rewritten heads"
  sibling observation, recurring; optional either way — no required checks).
- **By-omission capture:** the readiness verdict consulted PR state, drafts, bases, checks,
  and mergeability — never the ready stamps (the stamp is planning control, not merge
  policy; § matrix family 5).

**Confirmed-land half executed 2026-08-22** (operator, dev checkout root; consent = the
recorded dry-run above + the rendered consent plan approved `y`).

- **The consent plan** (operator capture) rendered the identical two-layer table + `top pin:
  pr #1984 at 149a8dcf…` — byte-consistent with the dry-run LandPlan.
- **The atomic land:** `landed 2 layer(s) atomically (operation 01M0NVZKKZ0MZCVPJH8TZ3B5W9)`
  — `1.1 (pr #1982): merged as 9d1733b6b195`, `1.2 (pr #1984): merged as b5bded35b071`;
  `objective #1980 complete — closed`; `reconcile evidence: 2 layer(s), final base
  b5bded35b071 … /objective-reconcile`.
- **The LAND journal triple (durable half):** operation `01M0NVZKKZ0MZCVPJH8TZ3B5W9` —
  `prepared` 23:13:09Z → `accepted` 23:13:14Z → `completed` 23:13:20Z (≈11 s end to end; no
  interruption this gate, by design — the interruption→recovery arm is the prior gate's
  proven fact).
- **Merge facts:** #1982 `MERGED` 23:13:14Z as `9d1733b6b1950a657bdf5eddd91c66dec1f614f2`;
  #1984 `MERGED` 23:13:15Z as `b5bded35b0714099343efb17e0e3d51fbff474b0`; remote `main` =
  `b5bded35…` (= the reconcile evidence's final base exactly).
- **Bookkeeping converged:** issues #1980/#1981/#1983 all `CLOSED`; `objective show` →
  `done: 2` of 2, `next: — (complete)`.
- **Terminal train read:** `published prefix 2/2, landed 2`; both layers `[landed] pr
  (merged)`; the `handoff` suffix GONE — the axis exists only over verified PUBLISHED layers
  (`not_applicable` once landed), as pinned. The one information row is the expected
  post-landing truth: `base_advanced` (main moved from the recorded objective base
  `e2cb9e5d…` to the train's final merged base `b5bded35…`; a landed train is never
  re-synced — the row's generic sync hint is advisory vocabulary, not an instruction).
- **The post-land whole-train pass (operator transcript): a near-no-op with exactly the
  land-scoped residue** — one targeted `reconcile_objective` write resolving the
  forward-looking excerpt-sequencing commitment into its recorded outcome (satisfiable only
  at land time, by construction) plus tense-shifts on the now-fixed gaps; node descriptions
  deliberately skipped ("already reconciled at ready time; the merged diffs match them
  exactly"); no new nodes; no status/PR mutations ("the cold land path already marked both
  nodes done and closed the objective"). **The design thesis observed live: ready-time
  reconciliation kept future intent current, leaving the post-land pass only what could not
  exist earlier.**

### S11 — census + residue sweep

**Durable census executed 2026-08-22** (read-only, from the record worktree):

- **PR census:** #1982/#1984 both `MERGED` (23:13:14/15Z) at `9d1733b6…`/`b5bded35…`.
- **Issue census:** objective #1980 and plan issues #1981/#1983 all `CLOSED`; nodes `done`
  ×2.
- **Main census (at `b5bded35…`, via the contents API):** all four deliverable surfaces
  carry the new content — the tutorial (23 continuation/handoff mentions), both stacked
  how-tos (the Handoff repair table present), and the perk-expert mirror (the handoff-repair
  routing rows present).
- **Terminal train read:** recorded at S10 (landed 2; the expected `base_advanced` row; no
  unresolved operations, no continuation, no orphaned residue).

**Local-side sweep executed 2026-08-22** (operator, dev checkout on updated main):

- **Docs gate on updated main (`b5bded35…`):** `just docs-check` GREEN — 74 pytest
  metadata/reference/gate tests; Biome clean; docs-site TypeScript clean; node tests clean;
  Astro build **77 pages** (the stacked tutorial + both stacked how-tos routed); all 22
  rendered-site checks pass (axe: low-impact advisories only).
- **Worktree sweep:** `perk worktree wipe` removed `plan-1981` + `plan-1983` (and 3 unrelated
  merged worktrees), deleting their local AND remote branches itself ("deleted 5 remote
  branch(es) on origin") — the operator's manual `git push origin --delete` then found
  `remote ref does not exist` ×2, itself absence evidence. The guard held for this record's
  own worktree: `skip plan-1978: PR is OPEN, not merged`; unmerged/pending-learn worktrees
  all skipped.
- **Absence census (independent verification):** `git ls-remote` empty for both train refs;
  no `plan-1981`/`plan-1983` entry in `git worktree list`; no local branches remain.

### Evidence-fill reconciliation sweep (S12, 2026-08-22)

- **A3 — the prior record annotated:** a dated keep-and-annotate supersession note on
  [`stacked-delivery-dogfood.md`](./stacked-delivery-dogfood.md)'s Status block — its Step-6
  ready evidence predates the stamp; the stamped lifecycle is proven here; everything else
  there stands (committed with this fill).
- **A3 — `docs/learned/workflow/objective-delivery.md`: a stated no-op.** Its
  ready/stamp-adjacent passages concern learn-stamp effects, layer-identity stamping, and
  readiness-enrichment fail-closed arms — no claim this gate settles; annotating would
  manufacture scope.
- **Doc-side census closure:** every `doc fix → train layer N` disposition in the § matrix
  landed via the train itself (PR #1982 for the three user-docs rows, PR #1984 for the
  perk-expert row; both MERGED); the two `agrees` doc rows held; the one keep-and-annotate
  (A4, the seed doc) was committed with this record's scaffold. Every runtime row was
  additionally exercised live during S2–S10 with zero divergences — the
  `runtime follow-up #<issue>` column ends EMPTY.
- **A5:** the `docs/index.md` row and the ONE actual-verdict `[Unreleased]` CHANGELOG entry
  ride this fill commit.

### Defect log

**No defects.** Every arm ran clean on the first attempt — no perk code defect, no
docs-content defect routed through the train's machinery, no restart boundary. Two named
**non-defect observations** were recorded in place:

1. **The plan-door dry-run recipe deviation (S3):** on a train whose offline graph holds no
   plannable candidate, `objective plan --dry-run` refuses `objective_in_flight` before the
   seed composes, so the `build_readiness: "unchecked (dry-run)"` payload capture routes to
   `objective run --dry-run` (both surfaces honest; the § matrix row carries the dated note).
2. **Duplicate check-run reporting on cascade-rewritten heads (S10):** the landing dry-run's
   `optional_check_failed` row reflected a CANCELLED superseded GHA run (concurrency cancel
   from the cascade push) beside the SUCCESS run on the same head — the prior gate's d2
   sibling observation recurring, optional and non-blocking; no new follow-up (the shape is
   GitHub-side reporting, already on record).

### Evidence gaps (dated operator attestations)

Accepted inline gaps, each with its durable machine half in this record — not residuals, not
verdict degradations:

- **S1 delivery-question UX (2026-08-22):** operator-attested (asked before the plannotator
  review, answered `stacked`); the saved header is the machine half.
- **S2 implement-launch narration (2026-08-22):** not captured for layer 1 (S6's layer-2
  narration WAS captured verbatim); the header checkpoint pair + PUBLISH journal record are
  the durable half.
- **S4/S5/S7 ephemeral warm report lines (2026-08-22):** the `Marked ready`/`Handoff stamped`
  lines scrolled out of the session buffers; the continuation announcements and full pass
  conclusions WERE captured, and the journal stamps + PR flips are the durable halves
  throughout.

### Named residuals (final)

Unfired capture-if-fired arms — each pinned to its hermetic suite; none degrades the verdict:

- **The tail-append guard refusal never fired** (`stacked_append_refused`): all four
  ready-time passes judged no new unit of work, so the guard was never exercised live —
  pinned by `tests/test_objective_cmd.py` (the stacked node-add guard suites).
- **The `ReadyStampError` arms never fired:** every stamp append succeeded first-try — the
  ambiguous/transient and deterministic-refusal arms stay pinned by
  `tests/test_pr_ready_cmd.py` + `tests/test_delivery_facade.py`.
- **The wrapper launch-failure second outcome never fired** (both S9 launches were clean) —
  pinned by the wrapper arms in `tests/test_pr_ready_cmd.py`.
- **No retained sync conflict** (the S8 cascade rebased clean — disjoint file ownership by
  construction) — pinned by the §8.49 conflict suites in `tests/test_delivery_sync.py`.
- **The base-advancement cascade never fired** (main never advanced during the gate) — the
  staleness arms fired via the real feedback cascade instead, so no cascade-coverage gap.
- **No second clone / no remote-runner arm (deliberate, pre-authored).**
  Fresh-checkout/durable-authority independence and the interruption→recovery conclusion are
  the prior gates' proven facts, reused by reference — this gate re-proved neither.

### Verdicts

Derived by the § Verdict matrix from the evidence above.

| Arm | Verdict | Surviving evidence |
|---|---|---|
| Gated-planning refusal | **PASS** | S3: typed `node_not_handoff_ready` (bare + `--node`, exit 1); the same blocker + `perk ready 1981` remediation on `next`/`show`/`stack status`; the JSON handoff row |
| Warm stamp + in-session continuation | **PASS** | S4/S7: journal stamps at the exact heads; PR flips; announced pinned ranges = the checkpoint pairs; S4's bounded prose write |
| Suspend hold + idempotent resume | **PASS** | S5: `handoff suspended` with `stamped_head` = `current_head`; re-`/ready` → one unchanged journal comment (`existed=true`), `handoff ready`, the pass re-entered |
| Stale via self-rewrite | **PASS** | S8: layer 1 `handoff stale` after the address publish (stamp at `f7f25f9d…` vs head `ca046b8b…`) |
| Stale via cascade | **PASS** | S8: layer 2 `handoff stale` off the trigger-scoped SYNC (`01M0NTT5…`) — no mechanical stamp carry |
| Wrapper re-ready + seeded launch | **PASS** | S9: fresh stamps at both post-cascade heads (4 journal comments total); both seeded sessions launched clean in the main checkout |
| Ready-time pass behavior | **PASS** | S4 write / S5 audited no-op / S9 audited no-op + descriptions-and-prose write — all bounded (no status/PR, no node adds); the post-land pass left only land-scoped residue |
| Atomic land + close + post-land reconcile | **PASS** | S10: one journaled operation (`prepared→accepted→completed`), sequential merges to main `b5bded35…`, nodes done ×2, objective closed, the near-no-op post-land pass |
| Audit coherence | **PASS** | every § matrix row dispositioned: runtime rows all held live; doc fixes landed via the train; A4 keep-and-annotate committed; the follow-up column empty |

**Overall: PASS.** Every planned arm passed on the first attempt — the § Verdict matrix's
all-arms-pass row — with zero defects, both continuation carriers proven live, both staleness
arms fired by real work, and the audit's expected outcome ("runtime surfaces agree; findings
are doc-side") confirmed end to end. Unfired arms stand honestly in § Named residuals.
