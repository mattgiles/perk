# Dogfood: stacked delivery delivered as a live train (Objective #1431, Node 6.2)

**Status:** validation record (the `stacked-publication-dogfood` genre — Part A the repeatable
protocol, Part B the dated captured evidence + defect log) for the full stacked-delivery
**lifecycle**, driven live in the designated durable dogfood repository (`mattgiles/perk`).
**Part B is IN PROGRESS** — the protocol below is authored; the live legs run as post-submit
follow-up phases, each landing its evidence as docs-only commits on this record's PR branch.
This record's PR stays **draft** until Part B and the Verdict section are complete (the
"what merges when" discipline in § Sequencing).

**Prior vs current coverage.** The prior gate record
[`stacked-publication-dogfood.md`](./stacked-publication-dogfood.md) (node 2.4, PASSED
2026-08-10) proved **authoring persistence + publication only**, on a sacrificial train driven
through scripted cold saves and headless implement drives: the §8.45 stacked save path, §8.46
parent-aware layer execution (including a fresh-clone layer), the native stack **create** and
**append** REST mutations, and pristine-clone train reconstruction. Its scope notes explicitly
defer the rest of the lifecycle to this gate. **This record covers the arms 2.4 deliberately did
not:**

- the **warm authoring UX** — the reviewed `delivery: stacked` choice through
  `perk objective author` (delivery question + plannotator review), not a scripted cold save;
- **warm build-readiness planning** per node (`perk objective plan <N>`);
- **second-clone interactive implementation** of one layer (fresh-checkout independence);
- live **review feedback on a lower layer + the trigger-scoped suffix cascade** via
  `perk address` / `finalize_address`;
- per-layer **ready** (`perk pr ready`, bottom→top);
- the live **atomic merge-async landing** of the whole train;
- a **deliberate interruption** of that landing (SIGKILL after the journal's `accepted` event)
  and its **recovery conclusion from the second clone** (`perk objective stack recover`);
- the **finalization / node-done / objective-close / reconcile** bookkeeping.

Capability facts already proven live for `mattgiles/perk` by 2.4 and reused here: native-stack
host schema, live per-repository enrollment (stack #1548 create + append), `allow_squash_merge`,
no merge-queue rule, atomic push accepted. **Merge-async availability remains unproven until
this gate's landing** — there is no sacrificial pre-probe; the real train is the probe
(§ Landing-failure dispositions covers the terminal outcomes).

**The substrate is the deliverable.** The train under proof is not sacrificial: it is a real
3-layer docs objective ("Stacked delivery has a cohesive documented user experience", layers
reference → guides → perk-expert; § Train spec) whose merged layer PRs ARE node 6.2's
documentation deliverables. This record's own PR carries only the protocol + evidence + the
reconciliation sweep; the documentation content lands via the train's layer PRs. The two
deliverables touch disjoint files by construction (§ File-ownership boundary).

**Door discipline (plan #1693 Decision 8, quoted verbatim):**

> **Door discipline (per leg, no run-time reconciling)**: the four **agentic stages** run as
> warm sessions opened by their cold launchers — `perk objective author` (authoring, with the
> delivery question + plannotator review), `perk objective plan <N>` (the warm objective-plan
> factory per node), `perk implement <plan>` (interactive; ends in warm `/submit`),
> `perk address <plan>` (ends through `finalize_address`), and `perk objective reconcile <N>`
> (the warm reconcile session). The **deterministic gestures** run as cold workers —
> `perk pr ready <plan>` (bottom→top), `perk objective stack status|land|recover` — because the
> controlled kill and scripted evidence capture need directly-owned processes; the warm doors
> delegate to these same canonical workers. Node 6.2's own PR finishes with warm **`/land`**
> (§ Sequencing).

*(Era note, 2026-08-13: two of the quote's command shapes are fiction — `perk address` takes
no positional plan (the address leg runs `perk address --worktree plan-<id>`), and
`perk pr ready` takes no positional plan either (it reads the LOCAL `cache.plan-ref`; the
ready leg runs `perk pr ready` from inside each layer worktree, bottom→top). Defect row d1.)*

**Terminology note (fresh-checkout, not cross-machine).** The second-clone arm claims
**fresh-checkout / durable-authority independence**: a second `git clone` on the same host, with
no pre-existing worktrees, no local stack metadata, and no dispatch cache, driven purely from
durable authority (GitHub + the journal). It never claims host-level "cross-machine"
independence. The live stacked **remote-runner** arm is deliberately not run — a pre-authored
named residual (§ Named residuals), covered by node 6.1's hermetic positioning-parity suite
(`tests/test_run_worker.py`), the cross-machine lane (`tests/test_delivery_cross_machine.py`),
and the live non-stacked remote e2e dogfood records.

## Part A — the repeatable protocol

### Train spec (the authored roadmap, pinned)

Authored live at Step 1 through `perk objective author`. Pinned at authoring: **title**
"Stacked delivery has a cohesive documented user experience"; **delivery: stacked**; default
base; 3 nodes in a chain (1 → 2 → 3). Body prose: docs-only scope; content mirrors the stacked
contracts (`shared/contracts.md` §8.45–§8.47, §8.49, §8.51–§8.56) and landed behavior; no
product code. The node descriptions below are the authored roadmap **verbatim** — they are the
layer planning sessions' only scope input:

**Node 1 — slug `stacked-reference` (bottom):**
Reconcile the stacked-delivery reference quadrant against landed reality. (a) Verify every
`perk objective stack status|sync|recover|land` section in `docs/user-docs/reference/cli.md`
against live `--help` output and command-module behavior
(`src/perk/cli/commands/objective/stack/`); (b) verify the warm-door reference in
`docs/user-docs/reference/in-session.md` (`/objective-stack`, `/objective-sync`,
`/objective-recover`, `/objective-land`, the five `objective_stack_*` tools, consent/read-only
discipline) against `extension/doors/objectiveStack.ts`; (c) rewrite
`docs/user-docs/reference/objectives.md`'s stacked limitations block — retire the stale
"interrupted-landing recovery is deferred" bullet (node 5.4, merge PR #1664, landed `stack
recover`'s LAND arm: classification, roll-forward, `--accept-prefix`) and state the real current
limitations (merge-queue bases unsupported; one train per objective; delivery policy + base
immutable after first publication; in-place adoption incremental-only; never land layers
individually; GitHub-native stacks are preview-quality). Apply the doc-accuracy gate
(`docs/learned/workflow/doc-reconciliation.md`): grep every referenced symbol, render live
`--help` for every cited command. Docs-only; touch ONLY the three reference files.

**Node 2 — slug `stacked-guides` (middle):**
Add the teaching quadrant. (a) `docs/user-docs/tutorials/drive-a-stacked-objective.md`
(`sidebar.order: 1030`) — ONE end-to-end tutorial mirroring `drive-an-objective.md`'s voice:
authoring the reviewed delivery choice (validation + capability checks) → planning with
build-readiness-derived selection → implementing/publishing layers through ordinary sessions and
`/submit` → reviewing, lower-layer feedback and the automatic cascade → `/ready` per layer → the
atomic objective landing. (b) `docs/user-docs/how-to/review-a-stacked-train.md`
(`sidebarGroup: "Core workflow"`, `sidebar.order: 2045`) — reviewer guidance: review each layer
PR on its incremental diff; the PR body's non-authoritative "this layer"/"train context"
sections; feedback on lower layers is safe and flows through `/address` + the cascade;
approve/ready normally; **never** the GitHub merge button on an individual layer; see the whole
train via `perk objective stack status`. (c) `docs/user-docs/how-to/recover-a-stacked-train.md`
(`sidebarGroup: "Objectives & learnings"`, `sidebar.order: 2185`) — recovery decision tables:
symptom → first command → classification → action, sourced from contracts
§8.49/§8.51/§8.55/§8.56, with rows covering at least: retained sync conflict
(`--continue`/`--abort`); unresolved PUBLISH (re-run `/submit`); unresolved SYNC/ADOPT (recover:
all_after rolls forward / all_before abandons confirmed / mixed reports); unresolved TRANSFER
(`recover <predecessor>`); interrupted LAND (pending/unexpected_enqueued → recover: handle
probe, all_after roll-forward, proven all_before abandon + re-land, in_flight waits); externally
merged prefix (`recover --accept-prefix`, then `sync --base` + `land`); out-of-band branch edit
(`sync --adopt`); base advancement (`sync --base`); orphan residue (the recover sweep).
(d) Handoff links from `drive-an-objective.md`, `author-a-roadmap.md`,
`address-review-feedback.md`, and `objectives.md`'s delivery section (the ONLY `objectives.md`
edit in this node). (e) Register all three pages in `docs/site/src/sidebar.mjs` — the tutorial
appended after `tutorials/drive-an-objective`; `how-to/review-a-stacked-train` between
`review-a-foreign-pr` and `replan-an-open-plan`; `how-to/recover-a-stacked-train` between
`check-an-objective-for-drift` and `run-the-learn-docs-factory` — plus dated rows in
`docs/design/docs-site-blueprint.md`'s route/sidebar map and inventory; satisfy
`tests/test_user_docs_metadata.py`. Docs-only.

**Node 3 — slug `stacked-expert` (top):**
The self-contained perk-expert mirror. (a) `skills/perk-expert/references/stacked-delivery.md`:
the delivery choice + validation/capability checks; the train mental model (layers, canonical
order, published prefix, checkpoints, the journal); daily work (submit/address/ready, the
cascade); the four cold commands + four warm doors/five tools; recovery decision routing
(condensed from node 2's tables); current limitations. Self-contained — no links outside the
skill directory — ending with the canonical-source breadcrumb footer naming the matching
`docs/user-docs/` pages. (b) `skills/perk-expert/SKILL.md`: add the reference to the frontmatter
`references:` list + the Reference Index (with a read-when cue); extend the `description:`
routing cue to cover stacked-delivery questions. (c) `references/mental-model.md`: update the
short stacked overview to hand off to the new reference. Mirror the layer-1/-2 canonical content
faithfully. Docs-only.

### File-ownership boundary

The train owns `docs/user-docs/`, `docs/site/src/sidebar.mjs`,
`docs/design/docs-site-blueprint.md`, `skills/perk-expert/`. This node's PR owns
`docs/design/stacked-delivery-dogfood.md` (this record), the evidence-fill annotation files
(`docs/design/stacked-publication-dogfood.md` Status,
`docs/learned/workflow/objective-delivery.md`,
`docs/planning/stacked-prs/failure-hardening-audit.md`), `docs/index.md`, `CHANGELOG.md`.
No overlap. The train's layers add no CHANGELOG entries; this PR's ONE `[Unreleased]` entry is
written at evidence-fill time to match the actual verdict (never pre-claimed).

### Provenance (the pinned binary)

One pinned binary from the **main checkout at a recorded SHA** — the supported-path proof,
deliberately not the node branch (all required capability is on main):

```bash
uv tool install --force --from <main-checkout-path> perk
```

Record `which perk` + `git -C <main-checkout-path> rev-parse HEAD` at every phase boundary (a
provenance row in Part B). Driving checkouts (the dev checkout AND the second clone) run
`npm ci` before driving (extension parity — in-session doors run the checkout's extension
source). The restart boundary after any perk code fix is in § Failure policy. Never drive with
an unpinned `perk`.

### Evidence sources (pinned per fact)

Machine facts, per source — never warm-envelope fields (the warm decoders drop operation ids
and raw stdout; the journal comments are the durable authority):

- **PR facts:**
  `gh pr view <n> --json number,state,isDraft,baseRefName,headRefName,headRefOid,mergedAt`
- **Journal transitions (operation ids, `prepared|accepted|completed|abandoned` roles):**
  `gh issue view <N> --comments` — the §8.43 marked comments on the docs objective's issue
  (`<!-- perk:stack-operation-event:<operation_id>:<role> -->`,
  `src/perk/delivery/journal.py::render_marker`)
- **Train facts:** `perk objective stack status <N> --json`

**Fact-to-source matrix for the UX facts** (facts with no durable machine source are dated
operator attestations inline in Part B — the evidence-gap honesty pattern, distinct from named
residuals):

| UX fact | Durable source | Capture |
|---|---|---|
| delivery choice reviewed | objective header `delivery: stacked` (machine) + plannotator rendering | header excerpt + dated operator attestation |
| warm planning per node | plan-issue headers (`objective_id`/`objective_node_id`/`delivery_lineage`, fresh `run_id` per session) | header excerpts inlined |
| second-clone interactive implement | the clone worktree's `.perk/workflow/layer-context.json` + launch progress lines | excerpts inlined + attestation |
| `run_ci` per session | the session's run_ci report | excerpt inlined + attestation |
| `/address` via `finalize_address` | journal cascade records + resolved threads (`gh api`) | excerpts inlined + door attestation |
| ready | `gh pr view --json isDraft` before/after | excerpts inlined |

Retention: every decisive excerpt is inlined in this record; logs and clones are deleted at the
Step-11 sweep.

### The interruption mechanism (settled — no executor invention)

There is no in-CLI kill anchor: in `src/perk/delivery/landing.py` the `accepted` journal append
happens after the merge-async submit and **before** the bounded poll (`_POLL_TICKS = 60`,
`_POLL_DELAY_SECONDS = 1.0` — up to 60 ticks, one second apart), and
`src/perk/cli/commands/objective/stack/land_cmd.py` renders nothing between the consent plan and
the final outcome. The trigger is therefore the **durable journal itself**: the `accepted` event
is a marked comment on the docs objective's issue, appended before the poll begins — greppable
out-of-process. The watcher skeleton (substitute `<N>` = the docs objective's issue number,
recorded at Step 1):

```bash
JQ='[.comments[].body | select(test("perk:stack-operation-event:[^:]+:accepted"))] | length'
BASELINE=$(gh issue view <N> --json comments --jq "$JQ")
perk objective stack land <N> --yes > land.log 2>&1 & LAND_PID=$!
while kill -0 "$LAND_PID" 2>/dev/null; do
  NOW=$(gh issue view <N> --json comments --jq "$JQ")
  [ "$NOW" -gt "$BASELINE" ] && { kill -9 "$LAND_PID"; break; }
  sleep 1
done
```

**Consent** = the recorded `--dry-run` immediately before + the `--yes` invocation (the cold
sanctioned path). **Post-kill verification (both commands pinned — status alone does not expose
the handle or prove completed-absence):**

1. `perk objective stack status <N> --json` — the unresolved LAND row;
2. `gh issue view <N> --comments` — the journal's `prepared` + `accepted` markers present for
   the operation id, and **no terminal role** (`completed`/`abandoned`) for that operation id.

**Timing:** the watcher's ~1–2 s cadence (1 s sleep + `gh` API latency) sits inside the 60 s
poll and ahead of GitHub's multi-PR async merge in the expected case; the kill-miss fallback
(§ Verdict matrix) covers the race honestly.

### Steps (each pinned with expected-vs-observed capture in Part B)

**Step 0 — preconditions.** Record expected-vs-observed verbatim:

1. The four §8.45 capability rows, via direct commands (the exact recipes are pinned in
   [`stacked-publication-dogfood.md`](./stacked-publication-dogfood.md) Step 0 rows 1–4):
   native-stack host schema (GraphQL introspection: a `stack` field on `PullRequest`);
   merge-rules (`allow_squash_merge: true`; no `merge_queue` rule on `main`); remote base SHA
   (`git ls-remote origin refs/heads/main`); the exact atomic-push dry-run argv against the
   observed SHA and the configured push URL.
2. Provenance: the pinned binary installed from the main checkout at a recorded SHA;
   `which perk`; `npm ci` in the dev checkout.
3. The second clone created: `git clone`, **stays on `main`**, `npm ci`, pinned binary
   verified; fresh-checkout posture recorded (one `git worktree list` entry, no `.worktrees/`,
   no `.perk/workflow/`).
4. Re-verify no required-review branch rule on `main`
   (`gh api repos/{owner}/{repo}/rules/branches/main`).

**Step 1 — warm authoring.** `perk objective author` (dev checkout) → the delivery question
answered `stacked` → the plannotator review renders the choice → save. Record: the objective
issue number `<N>`, its `delivery_lineage` (from the issue's objective-header block), the
roadmap (must match § Train spec verbatim), and the capability-preflight behavior.

**Step 2 — layer 1 (dev checkout).** `perk objective plan <N>` (the warm planning factory;
build-readiness-derived selection must offer node 1) → plannotator review → save;
`perk implement <plan-1>` (interactive) → in-session `run_ci` → warm `/submit` (draft). Record:
the plan-header trio (`objective_id`/`objective_node_id`/`delivery_lineage` —
`src/perk/plan.py::STACKED_PLAN_HEADER_FIELDS`), PR facts (base = `main`), the journal PUBLISH
`prepared → completed` pair, `stack status` (`published_prefix_len: 1`, next build-ready =
node 2).

**Step 3 — layer 2 (the second-clone arm).** Plan locally as Step 2; **implement from the
second clone** (`perk implement <plan-2>`, interactive) → `run_ci` → `/submit` from the clone —
the native stack CREATE. Record: the clone's parent derivation (launch progress lines + the
clone worktree's `.perk/workflow/layer-context.json`, non-authoritative), PR facts (base = the
layer-1 branch), the journal pair, the native-stack observation (`membership: exact`).

**Step 4 — layer 3 (dev checkout).** As Step 2 — the stack APPEND. Record symmetric facts;
`published_prefix_len: 3`.

**Step 5 — review + the cascade.** The operator reviews all three incremental diffs; leaves
real feedback on **layer 1's PR only after layer 3 has published**, pinned to layer-1-only
files (`cli.md` / `in-session.md` — files no successor touches; node 2's one `objectives.md`
edit is the delivery-section handoff line only, and feedback avoids that file).
`perk address --worktree plan-<layer-1-id>` (era-corrected — see defect d1; there is no
positional plan argument) resolves it and finishes through `finalize_address` → the
trigger-scoped suffix cascade republishes layers 2–3. Record: cascade journal records, all
three new head SHAs, PR settle, thread resolution (`gh api`), `stack status` clean.
**No-feedback branch:** an editorial-polish pass is legitimate, wanted feedback on
agent-authored docs (near-certain to yield changes); if the operator honestly finds nothing
actionable, that attestation is recorded and the cascade arm instead runs via
`perk objective stack sync <N> --base` once main advances — verdict consequences in § Verdict
matrix. A retained rebase conflict (`sync --continue`/`--abort`) is a capture-if-fired arm
(unfired → the named pin in § Named residuals).

**Step 6 — ready.** `perk pr ready --json` run from inside each layer worktree, bottom→top
(era-corrected — see d1: no positional plan exists; the worker reads the local plan-ref) —
layer 2's worktree lives in the second clone, so its ready gesture runs from there; record the
`isDraft` flips (before/after `gh pr view --json isDraft` per layer).

**Step 7 — landing readiness.** `perk objective stack land <N> --dry-run --json` → the READY
verdict + the exact bottom→top LandPlan. Capture-if-fired: base-advancement blockers →
`perk objective stack sync <N> --base` (preview with `--dry-run`, then the confirmed run),
recorded as the explicit base-cascade arm.

**Step 8 — the interrupted landing.** The § interruption-mechanism skeleton (recorded
`--dry-run` immediately before; then the watched `--yes` run; SIGKILL on the `accepted`
marker). Post-kill verification via BOTH pinned commands (`stack status --json` AND the journal
comments).

**Step 9 — recovery conclusion from the second clone.** `perk objective stack recover <N>` run
in the second clone. Expected classifications and actions:

- `in_flight` (probe pending): report-only; re-run after GitHub settles;
- `all_after` (probe merged): automatic roll-forward — `completed` journaled, per-layer
  finalization, node statuses, the aggregate objective close, reconcile evidence emitted;
- `all_before` (probe `failed`/`expired`, every PR OPEN at its recorded head): report → the
  confirmed `perk objective stack recover <N> --abandon --operation <id>` records the proof →
  **re-run `land`** (a fresh operation; the second attempt is the landing evidence, the
  concluded abandon is live interrupted-landing recovery evidence);
- `mixed`: investigation only — stop and record.

Record every envelope + the journal's terminal record. Cold `recover` only prints a copyable
`/objective-reconcile` hint (never drives it) — the reconcile leg is Step 10, never assumed.

**Step 10 — reconcile.** `perk objective reconcile <N>` (dev checkout; the warm reconcile
session over the emitted evidence) — capture its writes (or the honest no-op).

**Step 11 — post-landing census + residue sweep.** All three layer PRs `MERGED`; the docs live
on main; the docs objective CLOSED with all nodes done; the `stack status` end-state;
`just docs-check` green on updated main; residue sweep — delete the second clone,
`perk worktree wipe` the merged layer worktrees, prune; census recorded.

### Landing-failure dispositions (there is no `--accept-prefix` fallback)

A terminal landing failure (`merge_async_unavailable`, `land_failed`, `merge_request_conflict`,
`land_drift`) journals `abandoned` **with proof** and leaves NO unresolved operation
(`landing._terminal_non_application`) — `recover` has nothing to conclude, and
`--accept-prefix` is structurally inapplicable (it requires an unresolved LAND classifying as a
strict bottom-contiguous merged prefix with an OPEN remainder). Dispositions:

- **Transient/remediable** (drift, conflict, a fixable rule): remediate (e.g. `sync --base`,
  repair the PR), then re-run `land` — a fresh operation on the same argv. Defect row recorded.
- **Genuine capability gap** (merge-async unavailable for this repository): the atomic-landing
  arm **FAILS** — it blocks the node's stated acceptance path. The docs content is not held
  hostage: merge the layer PRs externally bottom→top in the GitHub UI (recorded as external
  merges — no perk atomicity claim anywhere), then converge the bookkeeping by hand and record
  it: `perk objective node <N> --node X --status done` per node, close the plan issues + the
  objective with pointers to this record, run `perk objective doctor <N>` and inline its
  findings. Verdict consequences in § Verdict matrix.

### Verdict matrix (arm outcomes → overall verdict → consequences)

| Outcome | Arm verdict | Overall | This PR | Node 6.2 | Follow-up |
|---|---|---|---|---|---|
| All arms pass (incl. interruption→conclusion) | PASS ×all | **PASS** | ready + warm `/land` | done via `/land` | none |
| Kill-miss (merge completed before the kill) | landing PASS; interruption = named evidence gap (pinned to node 6.1's L3 suites: `tests/test_delivery_landing.py::test_poll_timeout_stays_pending_with_accepted_and_no_terminal`, `tests/test_delivery_recover.py::test_live_probe_is_in_flight_for_every_shape`, `tests/test_delivery_cross_machine.py::test_land_accepted_handle_concludes_from_a_fresh_clone`) | **PASS with named gap** | ready + `/land` | done | **mandatory** follow-up issue: live interrupted-landing proof on a future stacked objective |
| Kill fired; probe `failed`/`expired` → all_before → confirmed abandon → re-land merges | recovery PASS (live all_before conclusion); landing PASS (second attempt) | **PASS** | ready + `/land` | done | none |
| `in_flight` persists unconcludably (> the request's 24 h lifetime, repeated passes) | landing unresolved | **BLOCKED** | held draft | `blocked` (cold CLI) | required |
| Terminal capability failure (degraded external delivery) | landing **FAIL** | **FAIL** | ready + `/land` (the record + docs are real value) | `blocked` (cold CLI) | **mandatory** capability follow-up |
| Feedback arm: address-cascade fired | cascade PASS | — | — | — | — |
| Feedback arm: only `sync --base` cascade fired (honest no-feedback attestation) | cascade DEGRADED (named gap) | caps overall at **PASS with named gap** | ready + `/land` | done | follow-up noted in record |

The CHANGELOG entry and this record's Verdict section are written from this matrix after the
evidence exists — never before.

### Failure policy (general)

Every incident gets a defect-log row. Docs-content defects in train layers are fixed through the
train's own machinery (feedback → address → cascade). **perk code defects that block the
acceptance path**: fix via an ordinary incremental PR to main, then apply the **restart
boundary** — reinstall the pinned binary from main @ the new recorded SHA (a fresh provenance
row), `npm ci` refresh in every driving checkout, re-driven legs use freshly created
sessions/worktrees (existing layer worktrees carry pre-fix extension source), `sync --base` only
if the fix affects train content, and each defect row states which earlier evidence remains
valid (arms whose code path the fix did not touch) versus re-run. Non-blocking findings →
follow-up issues (the node's scope guard). Environmental transients: re-run, recorded as dated
attempts. While a LAND operation is unresolved, no other train mutation runs (one unresolved
per lineage).

### Sequencing (what merges when)

1. **This record's implement session (front-loaded):** the Status header + full Part A + the
   Part B skeleton + the pre-authored named residual + the `docs/index.md` row; one `run_ci`;
   `/submit`. **The PR stays DRAFT** until Part B is complete.
2. **Live legs** (post-submit follow-up turns, operator-driven): protocol Steps 0–11, evidence
   landing as docs-only commits on this record's branch after each phase.
3. **Evidence-fill close:** the cross-annotations (dated keep-and-annotate notes on
   `stacked-publication-dogfood.md`'s Status, `docs/learned/workflow/objective-delivery.md`,
   `docs/planning/stacked-prs/failure-hardening-audit.md`, plus the sweep re-grep — `6\.2`,
   "deferred", "live wire" — across `docs/learned/`, `docs/design/`,
   `docs/planning/stacked-prs/`, `shared/contracts.md`, `docs/user-docs/`, annotating every hit
   this gate settles; a no-op is a legitimate, stated outcome) + the CHANGELOG entry + the
   Verdict section; final `run_ci` attested in this record; `perk pr ready` this PR; finish
   with warm **`/land`** from this plan's session — `finalize_landed_plan` marks node 6.2 done
   and closes objective #1431 once all nodes are terminal, and `driveReconcileAfterLand`
   (`extension/doors/land.ts`) injects the reconcile turn. (Fallback: cold `perk pr land
   <plan>` + `perk objective reconcile 1431`.) A bare GitHub-UI merge is never the final step —
   it would skip the node/objective bookkeeping.

This record's PR lands only after the train has landed (or its degraded disposition concluded)
and Part B + the Verdict section are complete. The train's layer PRs merge only through the
atomic landing or the § dispositions — never individually by hand outside those dispositions.

## Part B — the captured evidence (IN PROGRESS)

> **Execution in progress.** The live legs run as post-submit follow-up phases; each phase
> lands its dated evidence here as docs-only commits. Unexecuted steps' tables remain
> skeletons — no cell pre-claims an outcome (Decision 10).

### Provenance rows

| Phase boundary | Main-checkout SHA | `which perk` | Notes |
|---|---|---|---|
| Steps 0–1 (2026-08-13) | `597cf1b56babca5ef61631e984d051af5c6a7d51` | `/Users/mattgiles/.local/bin/perk` (`perk 2.3.0`, the uv tool shim) | operator-installed from the dev (main) checkout at that SHA; equals the observed remote `main` head at capture |

### Step 0 — preconditions

Captured 2026-08-13. **Named timing deviation:** the capability rows were captured immediately
*after* Step 1 (the operator authored first) — every read is stateless, so the order swap is
harmless; recorded rather than silent.

| Check | Expected | Observed |
|---|---|---|
| native-stack (host schema) | `stack` field on `PullRequest` | `["stack","stackEntry"]` (GraphQL introspection, filtered) |
| merge-rules | squash allowed; no `merge_queue` rule | `allow_squash_merge: true`; `gh api repos/mattgiles/perk/rules/branches/main` → `[]` |
| remote-base | a real `refs/heads/main` SHA | `597cf1b56babca5ef61631e984d051af5c6a7d51\trefs/heads/main` |
| atomic-push | no-op `--atomic --dry-run` accepted | `= 597cf1b5…:refs/heads/main [up to date]` + `Done`, exit 0 (push URL `git@github.com:mattgiles/perk`, exact §8.45 argv) |
| required-review rule | none on `main` | the same `rules/branches/main` read → `[]` — no branch rules of any type |
| second clone | fresh posture (no worktrees / stack metadata / caches), on `main`, `npm ci`, pinned binary | census 2026-08-13: `~/temp/perk`, on `main` @ `597cf1b5`, ONE `git worktree list` entry, no `.worktrees/`, no `.perk/workflow/`, `node_modules` present (`npm ci`), `which perk` → `/Users/mattgiles/.local/bin/perk` (`perk 2.3.0`) |

### Step 1 — warm authoring

Executed 2026-08-13 (`perk objective author`, dev checkout, pinned binary). The docs objective:
**#1698** — "Stacked-delivery documentation: reconcile, teach, mirror", created
`2026-08-13T04:18:57Z`, `run_id: 01KZWN6RH4R1ATDM30WGSRES5W`. Header excerpt (the machine facts
for the delivery choice):

```yaml
status: active
base: null
delivery: stacked
delivery_lineage: 01KZWNGE6AC0SV30PBM8RGB3Y1
```

- **Roadmap-vs-spec check — named deviations (operator-accepted 2026-08-13, proceed):** the
  authored roadmap deviates *cosmetically* from § Train spec: the title (authored
  "Stacked-delivery documentation: reconcile, teach, mirror" vs the pinned "Stacked delivery
  has a cohesive documented user experience"); the node ids (`1.1`/`2.1`/`3.1`, one node per
  phase, vs the flat `1 → 2 → 3`); the slugs (`reconcile-stacked-reference` /
  `stacked-teaching-quadrant` / `perk-expert-stacked-mirror` vs `stacked-reference` /
  `stacked-guides` / `stacked-expert`); backticks stripped from the descriptions (YAML
  flow-scalar rendering); one paraphrase (`recover <old-objective-id>` for the spec's
  `recover <predecessor>` — same referent). **The material pins all hold:** `delivery:
  stacked`; `delivery_lineage` minted; default base (`base: null`); a 3-node chain via
  `depends_on` (1.1 → 2.1 → 3.1); the descriptions otherwise carry the spec verbatim — every
  file path, sidebar order, boundary and scope guard intact. The layer planning sessions'
  scope input is therefore materially the pinned one.
- **Delivery-choice UX (dated operator attestation, 2026-08-13):** the authoring session asked
  the delivery question (answered `stacked`) and rendered the choice for plannotator review
  before save — both observed by the operator. The header excerpt above is the machine half of
  this fact (per the fact-to-source matrix).
- **Capability-preflight behavior:** nothing visible rendered during the save (the operator
  observed no preflight output) — the designed silent-success behavior recorded by the prior
  gate ("the preflight-in-save prints nothing on success"). The save succeeded and created
  #1698, so the §8.45 preflight necessarily passed (it runs before the store mutation).
- Roadmap state at capture: node 1.1 `planning` (the layer-1 planning session underway), 2.1
  and 3.1 `pending`.

### Step 2 — layer 1

Executed 2026-08-13 (dev checkout, pinned binary).

- **Warm planning** (`perk objective plan 1698` → plannotator review → save): plan issue
  **#1699** — "Reconcile stacked-delivery reference docs with landed behavior", created
  `2026-08-13T04:28:28Z`. The saved plan header carries the layer-identity trio plus a **fresh
  per-session run id** (`01KZWNH9M85C1C11SWWFWQQXGF` ≠ the authoring session's
  `01KZWN6RH4…` — the d1 trap from the prior gate structurally avoided by the warm factory):

  ```yaml
  objective_id: '1698'
  objective_node_id: '1.1'
  delivery_lineage: 01KZWNGE6AC0SV30PBM8RGB3Y1
  ```

- **Interactive implement** (`perk implement 1699`, dev checkout; operator-attested
  2026-08-13, executed as pinned). The worktree's operational record
  (`.perk/workflow/layer-context.json`, non-authoritative): `parent_branch: "main"`,
  `parent_sha: "597cf1b56babca5ef61631e984d051af5c6a7d51"`, `branch: "plan-1699"`,
  `predecessor_plan_id: null`, `prepared_at: "2026-08-13T04:30:14Z"`; the implement run id
  journaled on the plan header (`impl_run_ids: [01KZWP54VW399NBWCBW3NAVM3H]`).
- **`run_ci`**: operator-attested (2026-08-13) — the in-session run-all `run_ci` reported green
  before `/submit`. *Report excerpt not captured from the session transcript — stands as a
  dated attestation (the evidence-gap honesty pattern).*
- **Publish (warm `/submit` — draft):**
  - PR facts: `gh pr view 1701` → `{"number": 1701, "state": "OPEN", "isDraft": true,
    "baseRefName": "main", "headRefName": "plan-1699",
    "headRefOid": "860ef57fb064f1415b90a8ad18022a45157f177f", "mergedAt": null}` — draft,
    base = the objective base (`main`).
  - Journal (issue #1698 comments): operation **01KZWPJJJHZV5JD4SPD7FFWSEM**, `prepared`
    (posted 04:37:37Z) → `completed` (created 04:37:47Z; `observed: {branch_sha: 860ef57f…,
    pr: 1701, stack: null}`). Layer 1 creates no stack membership — expected and recorded.
  - The plan header's publish-written checkpoint pair: `parent_checkpoint_sha: 597cf1b5…`,
    `published_head_sha: 860ef57f…`.
- **Train read** (`perk objective stack status 1698 --json`): `published_prefix_len: 1`;
  layer 1.1 `publication: "published"`, `git: "synced"`, `pr: "draft"`, `membership:
  "not_applicable"`, `observed_pr_base: "main"` = `expected_pr_base`; `unresolved_operation:
  null`; `blockers: []`; `next_build_ready: {"node_id": "2.1", "ready": true, "reason":
  null}`.
- **Layer-content note (a legitimate planned no-op):** the node-1.1 `cli.md` verification pass
  produced no edit — PR #1701 touches only `in-session.md` + `objectives.md` (`gh pr view 1701
  --json files`). Verified-accurate-with-no-diff is the doc-accuracy gate's honest no-op
  outcome; it also means later feedback structurally cannot anchor to `cli.md` (see Step 5's
  named deviation).

### Step 3 — layer 2 (the second-clone arm; the stack CREATE)

Executed 2026-08-13. Planned locally (dev checkout); **implemented + published from the second
clone** (`~/temp/perk`, census above).

- **Warm planning** (`perk objective plan 1698`, dev checkout): plan issue **#1704**, created
  `2026-08-13T05:06:30Z`; fresh per-session run id (`01KZWQD0A8BF7AYC5PYGSQCHPM`); the header
  trio (`objective_id: '1698'`, `objective_node_id: '2.1'`,
  `delivery_lineage: 01KZWNGE6A…`) plus `predecessor_plan_id: '1699'`.
- **Second-clone interactive implement** (`perk implement 1704` in `~/temp/perk`;
  operator-attested 2026-08-13, executed as pinned). The clone worktree's
  `.perk/workflow/layer-context.json` (non-authoritative) — the parent derived from the
  **reconstructed train** (nothing local to consult; fresh-checkout / durable-authority
  independence):

  ```json
  { "parent_branch": "plan-1699", "parent_sha": "860ef57fb064f1415b90a8ad18022a45157f177f",
    "predecessor_plan_id": "1699", "base": "main", "branch": "plan-1704",
    "prepared_at": "2026-08-13T05:06:55Z" }
  ```

  `parent_sha` = layer 1's `published_head_sha` exactly. Implement run id journaled on the
  header (`impl_run_ids: [01KZWR89S7NMZR6THGPV3QW1NH]`). *The launch's "reconstructing the
  delivery train" progress lines were not captured from the session — the layer-context
  record above stands as the durable half of this fact (evidence-gap noted).*
- **`run_ci`** (operator-pasted excerpt, 2026-08-13 — the in-session run-all report before
  `/submit`):

  ```text
  perk CI: all checks passed.
  ⊘ lint-py (skipped — no changed files match *.py)
  ✓ lint-js
  ⊘ typecheck-py (skipped) ⊘ typecheck-js (skipped) ⊘ test-py (skipped)
  ✓ test-js
  ✓ docs-check
  ⊘ changelog-check (skipped — no changed files match CHANGELOG.md)
  Full gate green — the change is verified …
  ```
- **Publish (warm `/submit` from the clone — the stack CREATE):**
  - PR facts: `gh pr view 1705` → `{"number": 1705, "state": "OPEN", "isDraft": true,
    "baseRefName": "plan-1699", "headRefName": "plan-1704",
    "headRefOid": "5234991b386b06f70c6572bdbb93911b4ef5d67e", "mergedAt": null}` — base = the
    layer-1 branch.
  - Journal (issue #1698): operation **01KZWSP0PEW1KK1GRFAAXVZJKR**, `prepared` (posted
    05:31:56Z) → `completed` (created 05:32:09Z; `observed: {branch_sha: 5234991b…, pr: 1705,
    stack: [1701, 1705]}`).
  - **Native stack registered:** `gh api 'repos/mattgiles/perk/stacks?pull_request=1705'` →
    stack **#1706** (`"base": {"ref": "main"}`, `"open": true`, created 05:32:05Z), members
    bottom→top `[#1701 @ plan-1699 860ef57f…, #1705 @ plan-1704 5234991b…]`.
  - Checkpoint pair on the #1704 header: `parent_checkpoint_sha: 860ef57f…`,
    `published_head_sha: 5234991b…`.
- **Train read** (`perk objective stack status 1698 --json`): `published_prefix_len: 2`;
  layers 1.1 and 2.1 both `publication: "published"`, **`membership: "exact"`**;
  `observed_pr_base` = `expected_pr_base` (`main` / `plan-1699`); `unresolved_operation:
  null`; `blockers: []`; `next_build_ready: {"node_id": "3.1", "ready": true, "reason":
  null}`.

### Step 4 — layer 3 (the APPEND)

Executed 2026-08-13 (dev checkout, pinned binary).

- **Warm planning**: plan issue **#1707**, created `2026-08-13T12:41:38Z`; fresh per-session
  run id (`01KZXHN03Q0QPWV7HJTYQXPD02`); header trio (`objective_id: '1698'`,
  `objective_node_id: '3.1'`, `delivery_lineage: 01KZWNGE6A…`) plus
  `predecessor_plan_id: '1704'`.
- **Interactive implement** (dev checkout; operator-attested 2026-08-13). The worktree's
  `layer-context.json`: `parent_branch: "plan-1704"`, `parent_sha: "5234991b…"` (= layer 2's
  published head exactly), `predecessor_plan_id: "1704"`, `prepared_at:
  "2026-08-13T12:42:11Z"`; `impl_run_ids: [01KZXJ9XZWXEQMXW0QTNGZ9DF1]`.
- **`run_ci`** (operator-pasted excerpt, 2026-08-13): line-identical to Step 3's report —
  `perk CI: all checks passed.` with `✓ lint-js ✓ test-js ✓ docs-check` and the same skips.
  *Observed behavior worth noting:* this layer's own files are `skills/perk-expert/**` only,
  yet the js/docs checks ran — a stacked layer's worktree carries its predecessors' commits,
  so scope-aware check globs resolve against the branch's cumulative diff, not the layer's own
  files. Honest, conservative over-checking; recorded as an observation, not a defect.
- **Publish (warm `/submit` — the stack APPEND):**
  - PR facts: `gh pr view 1708` → `{"number": 1708, "state": "OPEN", "isDraft": true,
    "baseRefName": "plan-1704", "headRefName": "plan-1707",
    "headRefOid": "fadca4533eb357971732b40cbe0f6661de436934", "mergedAt": null}` — base = the
    layer-2 branch.
  - Journal (issue #1698): operation **01KZXJR41RQT11ZJKXVKN0SVTQ**, `prepared` (posted
    12:50:00Z) → `completed` (created 12:50:12Z; `observed: {branch_sha: fadca453…,
    pr: 1708, stack: [1701, 1705, 1708]}`) — the exact missing suffix appended.
  - REST stack resource after the append: stack **#1706**, base `main`, `open: true`, members
    bottom→top `[#1701 @ plan-1699 860ef57f…, #1705 @ plan-1704 5234991b…, #1708 @ plan-1707
    fadca453…]`.
  - Checkpoint pair on the #1707 header: `parent_checkpoint_sha: 5234991b…`,
    `published_head_sha: fadca453…`.
- **Train read** (`perk objective stack status 1698 --json`): **`published_prefix_len: 3`**;
  all three layers `publication: "published"`, **`membership: "exact"`**, contiguous
  bottom→top bases (`main` → `plan-1699` → `plan-1704`), `observed_pr_base` =
  `expected_pr_base` ×3; `unresolved_operation: null`; `blockers: []`;
  `next_build_ready: {"node_id": null, "ready": false, "reason": "all layers published or
  landed"}`.

### Step 5 — review + the cascade

**Feedback half executed 2026-08-13; the address + cascade half is pending.**

- **Review pass + feedback (operator, 2026-08-13):** the operator reviewed the three layer
  diffs and left ONE actionable finding on **layer 1's PR #1701** — a `COMMENTED` review
  (submitted `12:51:53Z`) with one thread: review comment `3775479485`,
  `docs/user-docs/reference/objectives.md` line 146 (the merge-queue limitation bullet),
  "Let's add a link to relevant document, so readers can learn what a merge queue even is."
  **Decision-9 ordering held by machine timestamps:** feedback (12:51:53Z) landed after the
  layer-3 publish completed (12:50:12Z).
- **Named deviation (file pin):** Decision 9 pinned feedback to `cli.md` / `in-session.md` and
  avoided `objectives.md` (the one file node 2 also edits). The finding landed on
  `objectives.md` anyway — honest review found the real improvement there, and the pin's
  primary target was structurally unavailable (the `cli.md` no-op above left it out of the
  diff; review comments only anchor to diff lines). Hunk-adjacency analysis, recorded before
  the cascade: node 2's `objectives.md` edit inserts a handoff paragraph immediately above the
  "Current limitations" heading (patch anchor `@@ -141,6 +141,11 @@`); the feedback targets
  the merge-queue bullet two unchanged lines below — adjacent, non-overlapping hunks. Expected:
  a clean cascade rebase; if a conflict fires instead, it is the capture-if-fired
  retained-conflict arm (`sync --continue`/`--abort`) — either outcome is recorded.

**Address + cascade executed 2026-08-13** (`perk address --worktree plan-1699` from the dev
checkout, after the d1 correction; finished through `finalize_address`):

- **The cascade journal record** (issue #1698): ONE trigger-scoped SYNC operation
  **01KZXM50H9MWHS22TWD40RBM01** (`operation_kind: sync`, session run id
  `01KZXKZGD0RXXFRSB1SZYMK129`, `affected_plans: ['1699', '1704', '1707']`), `prepared`
  (posted 13:14:40Z) → `completed` (13:14:53Z), carrying the full before/after branch + PR
  tables — the address publish rewrote layer 1 AND republished both successors atomically:

  | Branch | Before | After |
  |---|---|---|
  | `plan-1699` | `860ef57f…` | `0c018ff6ae890e5fcab907f8a10d07cd87b8b98f` |
  | `plan-1704` | `5234991b…` | `3292033443824c4c4506d2d64bdc8fb810f539f8` |
  | `plan-1707` | `fadca453…` | `7ad1567d7e333cf6efc0c097bd090863be88adee` |

- **PR settle**: all three PRs `OPEN` + draft with bases unchanged
  (`main`/`plan-1699`/`plan-1704`) and heads = the after-table SHAs exactly.
- **Thread resolution** (GraphQL `reviewThreads` on #1701): `isResolved: true`, with the
  finalize-posted reply ("Linked the first \"merge queue\" mention in this bullet to GitHub's
  \"Managing a merge queue\" documentation…") preceding the resolve — the reply-then-resolve
  discipline observed.
- **Train read clean**: `published_prefix_len: 3`, `membership: "exact"` ×3,
  `observed_pr_base` unchanged ×3, `published_head_sha` ×3 = the after table,
  `unresolved_operation: null`, `blockers: []`.
- **The adjacency prediction held**: the cascade rebase was clean — the retained-conflict arm
  did not fire (the capture-if-fired pin in § Named residuals stands).

### Step 6 — ready

Executed 2026-08-13, bottom→top, `perk pr ready --json` from inside each layer worktree (the
operator's shell transcript shows the order and the cwd hops — layer 2's gesture ran from the
**second clone's** worktree):

| Layer | Worktree | Envelope | After (`gh pr view`) |
|---|---|---|---|
| 1.1 | dev `plan-1699` | `{"success": true, "pr": {"number": 1701}, "was_draft": true}` | `isDraft: false`, OPEN |
| 2.1 | clone `plan-1704` | `{"success": true, "pr": {"number": 1705}, "was_draft": true}` | `isDraft: false`, OPEN |
| 3.1 | dev `plan-1707` | `{"success": true, "pr": {"number": 1708}, "was_draft": true}` | `isDraft: false`, OPEN |

The before-state (draft ×3) was recorded at Step 5's PR settle; `was_draft: true` in each
envelope corroborates the flip.

### Step 7 — landing readiness

Executed 2026-08-13 (operator, dev checkout root): `perk objective stack land 1698 --dry-run
--json` → **`disposition: "ready"`**, `blockers: []`. Decisive excerpt:

- `rules: {squash_allowed: true, merge_queue_required: false}`; `native_stack_capability:
  true`.
- The exact bottom→top **LandPlan**: `mode: "stack_merge_async"`, `merge_method: "squash"`,
  `top_pr_number: 1708`, `top_head_sha: 7ad1567d…`; layers `[1701: 597cf1b5… → 0c018ff6…,
  1705: 0c018ff6… → 32920334…, 1708: 32920334… → 7ad1567d…]` (each layer's `base_sha` = its
  predecessor's head; layer 1's = the observed `main` head).
- Per-layer observations: `OPEN`, `isDraft: false`, `mergeable: MERGEABLE`,
  `observed_base_ref` = expected, `observed_head_sha` = the cascade heads,
  `unresolved_thread_count: 0` ×3; `merge_state_status: UNSTABLE` ×3 — solely the optional
  failed check (defect d2): `required_checks_failed: []`, `required_checks_pending: []`.
- `information`: two `active_worktree` advisories (layers 1.1/3.1 checked out locally —
  landing merges remote PRs; local branches untouched) + the three `optional_check_failed`
  rows.
- **The base-cascade arm did not fire**: `main` has not advanced past the pinned
  `597cf1b5…` (layer 1's `base_sha` still equals the Step-0 remote base), so no
  `sync --base` was needed — the capture-if-fired posture stands (§ Named residuals).

Consent linkage for Step 8: this recorded dry-run is the "immediately before" half; the
watched `--yes` invocation is the other half.

### Step 8 — the interrupted landing

Executed 2026-08-13 (operator, dev checkout root; the Part A watcher skeleton verbatim with
`<N>` = 1698). Consent: the Step-7 recorded `--dry-run` immediately before + the watched
`--yes` invocation.

- **The watched run**: `perk objective stack land 1698 --yes > land.log 2>&1 &` under the
  journal watcher — the watcher observed the `accepted` comment and SIGKILLed the process
  mid-poll. `land.log` ends at the rendered consent plan (the 3-layer table + `top pin: pr
  #1708 at 7ad1567d…`) with nothing after it — consistent with the kill landing inside the
  poll (`land_cmd` renders nothing between the consent plan and the final outcome).
- **Post-kill verification 1** (`perk objective stack status 1698 --json`): the unresolved
  LAND row — `unresolved_operation: {"operation_id": "01KZXNT314VQNJ9EWS1FZQWQHC", "kind":
  "land", "prepared_created": "2026-08-13T13:43:27Z"}`; `landed_prefix_len: 0` (no terminal
  event — the train does not count the layers landed).
- **Post-kill verification 2** (the journal, `gh issue view 1698 --comments`): for operation
  `01KZXNT314VQNJ9EWS1FZQWQHC` — `prepared` (posted 13:43:29Z) and **`accepted`** (posted
  13:43:33Z) present, **no `completed`/`abandoned`** — completed-absence proven from the
  journal, as pinned.
- **The server side kept going (expected — the merge request is GitHub's once accepted):**
  all three PRs merged seconds after the kill — #1701 `mergedAt: 13:43:35Z`, #1705
  `13:43:36Z`, #1708 `13:43:37Z`. The status read also shows `publication:
  "publication_drift"` ×3 (recorded published heads vs the post-merge remote) — honest
  unconcluded-state reporting, resolved by Step 9's classification, never by this read.
- **Timing observed**: accepted → kill inside ~≤4 s (the watcher's 1 s cadence + `gh`
  latency); the async merge concluded at +2–4 s. The kill-miss race did NOT occur — the
  interruption arm fired live; the process died before observing any terminal state.

The interrupted-LAND state now standing is exactly the Step-9 input: an unresolved operation
with a journaled `accepted` handle and every layer PR observably `MERGED`.

### Step 9 — recovery conclusion (second clone)

*(pending — classification envelope(s), actions taken, the journal's terminal record.)*

### Step 10 — reconcile

*(pending — the reconcile session's writes, or the honest no-op.)*

### Step 11 — post-landing census + residue sweep

*(pending — merged PRs, docs on main, objective closed, `stack status` end-state,
`just docs-check`, sweep census.)*

### Defect log

Every incident hit during the gate, its diagnosis artifacts, and its disposition (d-series).

| # | Incident | Diagnosis artifacts | Disposition |
|---|----------|---------------------|-------------|
| d1 | the address leg's pinned command shape was fiction: `perk address 1699` selects no plan — positional args are `PI_ARGS` forwarded to pi (so `1699` became the session's first user message) and positioning fell back to the ACTIVE cache plan-ref (plan-1707, the most recent implement session), opening an address session for the wrong plan in the plan-1707 worktree. Compounding finding from the sanctioned `--dry-run`: even with `--worktree plan-1699`, the seeded prompt names the active-cache plan (`…plan github #1707…`) — `_resolve_prompt` (`src/perk/run/launch/prompts.py`) falls back to `cache.read_plan_ref(repo_root)` when `--worktree` is given — while the session's real plan identity is the target worktree's materialized plan-ref (verified: `plan-1699/.perk/workflow/plan-ref.json` → `pr_id: "1699"`) | the stray session transcript (first user message `1699`, positioned in `…/.worktrees/plan-1707`); `perk address --dry-run --worktree plan-1699` rendering the `#1707` banner | **split**: the invocation half is an **execution-arm error** — the plan (and this record's first Part A revision) pinned a command shape that never existed; Part A Step 5 + the Decision-8 quote are era-corrected in place (the pinned-protocol-drift rule). The prompt-misnaming half is a **perk defect, non-blocking** (classification/finalize operate on the worktree's plan-ref; only the prompt banner lies) → follow-up issue per the failure policy. Stray session abandoned — **operator-confirmed (2026-08-13)**: no `finalize_address` ran, nothing committed. The corrected leg (`perk address --worktree plan-1699`) executed Step 5 successfully. **Operator verdict on scope (recorded verbatim in spirit):** the defect is not just the banner — the launcher's expected ergonomics don't work: the plan id should be sufficient (`perk address 1699`, parallel to `perk implement 1699`); `--worktree` is the wrong selector ergonomic. The same fiction-class was then caught **proactively** on the ready leg before execution: `perk pr ready <plan>` also takes no positional plan (the worker reads the LOCAL `cache.plan-ref` from inside the worktree) — Part A Step 6 era-corrected pre-run. ONE follow-up issue covering the launcher/worker plan-id selector ergonomics (address positional selector, the `--worktree` prompt-banner fallback, and the ready-from-worktree-only shape as one ergonomic surface) is deferred to the evidence-fill sweep, per the failure policy |
| d2 | all three layer PRs report `optional_checks_failed: ["lint · typecheck · test"]` (hence `merge_state_status: UNSTABLE` at Step 7) — the GHA CI job fails in `tests/test_init_t5.py::test_not_a_repo_is_exit_2` + `::test_missing_tool_is_exit_2`: PR #1692's interactive onboarding confirm (`Install pi via npm …? [Y/n]`, `src/perk/substrate/output.py::user_confirm`) fires inside pytest where stdin is captured → `OSError: pytest: reading from stdin while output is captured` | the GHA failed-log excerpt (run 31703952984); `gh run list --branch main --workflow CI` showing **main itself red** at 03:36 and 04:11 — both merges of #1692's era, BEFORE any layer published | **pre-existing main defect, not a train or landing-path defect** (the layers are docs-only; the failure reproduces on main without them). Non-blocking here: the checks are optional (`required_checks_failed: []`), landing readiness is `ready`, and the verdict matrix is unaffected. Fix routes as an ordinary incremental PR to main **outside this gate** (the failure policy's non-blocking arm — no restart boundary: the acceptance-path code is untouched by the defect). Minor sibling observation, undiagnosed by choice: layers 2/3 list the failed check name twice (duplicate check-run reporting on cascade-rewritten heads) |

### Evidence gaps (dated operator attestations)

*(none yet — facts with no durable machine source land here as dated inline attestations; a
category distinct from the named residuals below.)*

### Named residuals

- **The live stacked remote-runner arm (pre-authored; deliberate — no follow-up issue).** The
  node text sanctions "second clone **or** remote runner"; this gate runs the second clone.
  Coverage for the remote arm: node 6.1's hermetic positioning-parity suite
  (`tests/test_run_worker.py`), the cross-machine lane
  (`tests/test_delivery_cross_machine.py`), and the live non-stacked remote e2e dogfood records
  (`docs/design/remote-runner-e2e-dogfood.md`). Terminology discipline: this record claims
  fresh-checkout / durable-authority independence only — never host-level "cross-machine"
  independence.
- **Capture-if-fired arms** (recorded live if they fire; unfired → the named pin stands, plus a
  residual row here):
  - retained sync rebase conflict (`sync --continue` / `--abort`) — pin: the §8.49 conflict
    suites in `tests/test_delivery_sync.py`;
  - base-advancement cascade (`sync --base`, Step 7) — fires only if main advances into a
    landing blocker (near-certain over the run's days, per the no-feedback branch of
    Decision 9).

### Verdicts

Derived by § Verdict matrix from the evidence above — written only after the evidence exists.

| Arm | Verdict |
|---|---|
| Warm authoring UX | *(pending)* |
| Warm build-readiness planning | *(pending)* |
| Second-clone implementation (fresh-checkout independence) | *(pending)* |
| Feedback + suffix cascade | *(pending)* |
| Ready (bottom→top) | *(pending)* |
| Atomic merge-async landing | *(pending)* |
| Deliberate interruption → recovery conclusion | *(pending)* |
| Finalization / close / reconcile | *(pending)* |

**Overall: PENDING.**
