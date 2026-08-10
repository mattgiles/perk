# Dogfood: the three streaming browser doors (`/pr-review-browser` + `/plan-review-browser` + `/objective-review-browser`)

**Status:** validation record (the `pr-review-doors-dogfood.md` genre) for the three streaming
plannotator browser doors' **code-owned mechanics** — the flow-scoped wave tool pairs
(`start_review_wave`/`collect_review_wave` in `extension/doors/reviewWaveTools.ts`;
`start_draft_review_wave`/`collect_draft_review_wave` in
`extension/doors/draftReviewWaveTools.ts`), the mode-neutral `push_annotations`
(`extension/doors/annotationPush.ts`), and the model-held `subagent_wait` relay loop that is the
streaming cadence. Part A is the repeatable procedure; Part B is the captured evidence + defect
log.

**Supersession note:** this record **supersedes `pr-review-doors-dogfood.md`'s
streaming-mechanics claims**. That record's legs validated the retired mechanics generation —
the model-authored `workflowScript` fan-out skeleton with `status.json` report read-back, and
the browser door's model-composed curl annotation waves
(`POST /api/external-annotations` from a cheat sheet) — all replaced by the code-owned wave
modules (`extension/waves/adversarialReviewWave.ts`, `draftReviewWave.ts` over
`extension/waves/reportWave.ts`) behind the tool pairs above, with `push_annotations` owning the
annotation mechanics (mapping, dedupe ledger, hold-and-accumulate, `replace: true` reshape) and
the adversarial-reviewer completing via the engine-injected `structured_output` call instead of
a fenced-JSON block. That record's **standing non-streaming evidence is untouched and still
current**: the flipped browser posting contract (native platform-posting is THE GitHub path),
the `/pr-review-terminal` procedure (its migrated launch shares `start_review_wave` with the
browser door, but its hunk sink is out of this record's scope), and the formal-event/own-PR
residuals. Cross-annotated both ways — that record's Status block carries the dated
supersession-scope note.

The three doors under proof (all offline-pinned by their `*.test.ts` suites; this record is the
first live run of the streamed pipeline end-to-end):

- **`/pr-review-browser`** (`extension/doors/prReviewBrowser.ts`, contracts §8.4): the
  background plannotator open (guidance injected at port pick, readiness observed in a
  background task) → ONE `start_review_wave` launch (2–3 angles, `claimed-intent` mandatory;
  the tool renders and launches the wave itself — the model never authors workflowScripts) →
  the `subagent_wait({timeoutMs})` relay loop with per-angle `push_annotations` pushes as
  batches stream in → `collect_review_wave`'s typed aggregate
  `{complete, covered, reports, failures}` → reconcile with `replace: true` per reshaped
  angle → human browser triage; **no posting requirement** (the flipped contract stands).
- **`/plan-review-browser`** (`extension/doors/planReviewBrowser.ts`, contracts §8.23): from a
  plan-authoring session — stage gate (`{plan, save, objective-plan}`) + drafts-only resolve
  (the validated `plan-draft.md` artifact, no param/transcript tier) → the dual prime
  (`push_annotations` plan mode + `primeDraftReviewContext({draftType: "plan", …}`)) → ONE
  `start_draft_review_wave` call (`{angles}` only — inputs are door-primed module state; the
  door arg is the custom lane) → phrase-anchored streaming pushes → APPROVE (stale guard →
  Direct Edits apply → `approvalSave`) or DENY (delimited untrusted feedback → a `plan_draft`
  revise round).
- **`/objective-review-browser`** (`extension/doors/objectiveReviewBrowser.ts`, contracts
  §8.23): the objective twin — stage gate (`{objective-author, objective-save}`) + the
  validated `objective-draft.json` artifact rendered to markdown (the RENDERED draft is the
  reviewed/browsed/wave bytes, never raw JSON) → the same dual prime with
  `draftType: "objective"` → the same draft wave → APPROVE with the **Direct-Edits carve-out
  FIRST** (nothing saved; a model-mediated `objective_draft` revise round returns, gate
  untouched) or DENY (the same delimited revise round).

Scope notes (what this record does *not* prove): `/pr-review-terminal` is out of scope (its hunk
sink is not one of the three plannotator browser doors; its launch path shares
`start_review_wave`, so the wave mechanics proven here cover its fan-out by construction, but
the hunk `comment apply` sink and the check-in-and-wait handshake stay on
`pr-review-doors-dogfood.md`'s evidence). Decision legs save nothing — the plan leg ends DENY,
the objective leg exercises the Direct-Edits carve-out (APPROVE, nothing saved); no junk plan
issues or objectives are minted. Degrade arms are **capture-if-fired**: no forced-degrade hooks
or test-only flags — an arm that never fires naturally is recorded as offline-pinned (naming
the exact test suites) plus a named residual.

## Part A — the repeatable procedure

Each step names its actor: **(human)** for actions a session cannot take, **(session)** for
everything automatable. Two sessions are involved: the **staging session** (any perk session —
here the node's implementation session) stages the scratch PR and captures evidence; each
**dogfood session** is a fresh interactive `pi` launched **from the implementation worktree** —
its `.pi/settings.json` includes `".."`, so it loads the branch's extension source (which for
the doors is main's code, unchanged by this docs branch; **restart the dogfood session after any
in-branch fix**). The plan and objective legs additionally need a scratch **authoring** session
(`perk plan` / `perk objective author`) because the draft doors are stage-gated.

### Preconditions (verified at execution time; recorded per-run in Part B)

- `node_modules` present in the implementation worktree (the dogfood session loads `..`).
- The plannotator extension loaded: `.pi/settings.json` packages carry
  `npm:@plannotator/pi-extension` (object-form entry — equivalent).
- Interactive UI (every door is `hasUI`-gated; the human is constitutive).
- Reviewer models: **no** `[models.subagents] adversarial-reviewer` or `draft-reviewer`
  override in `.perk/config.toml` / `.perk/local.toml` — the record validates the shipped
  defaults (`agents/adversarial-reviewer.md`: `anthropic/claude-fable-5`;
  `agents/draft-reviewer.md`: `openai/gpt-5.6-sol`).
- Version re-check (drift degrades loudly — readiness `timeout` / `push_rejected` — and
  becomes a D-row): `@plannotator/pi-extension` (0.26.4 verified at node 1.4) and
  `pi-subagents` (0.45.0 at node 1.1); record the installed versions in Part B.

### Common capture instruments (all legs)

- Session-jsonl timestamps (UTC) — the proof medium for "≥1 streamed push predates wave
  completion".
- The tools' typed results quoted verbatim: `push_annotations`'
  `{pushed, skipped, held, held_batches, deleted, ids}` vocabulary; the collect tools'
  `{complete, covered, reports, failures}` aggregate.
- Browser annotation badges (`perk:<angle>`, `perk:custom`) with the `[severity/confidence]`
  prefixes.
- The four live-run watch axes from `docs/learned/pi/subagents.md` ("the first live run is the
  integration test"): **(a)** batches deliver on each `subagent_wait` expiry, **(b)** the
  dedupe ledger holds across a long triage window, **(c)** the 30s cadence fit, **(d)** the
  parent holds its turn open while streaming.

### Staging (the scratch-PR recipe — Leg 1's target)

1. **Stage PR F (session).** A scratch branch off `origin/main` continuing the sacrificial
   series (`review-dogfood-a`…`-e` are spent): `review-dogfood-f`, staged via a throwaway
   detached worktree so the implementation branch is untouched. Shape: an honest body, a few
   genuine docs tweaks, **one fresh planted wrong-fact signal** (the shape-(b) recipe: a
   documented fact flipped, cross-verifiable elsewhere in the tree). **Fresh planted content
   every restage** — executed instances are described verbatim in the committed records the
   PR-head checkout contains; reusing one hands the children the answer key. Low-CI-noise
   paths (docs only); the PR never merges.

### Leg 0b — the cheap live refusal probe (before any door is opened)

2. **(human)** In any perk session with no door-primed flow, ask the session to call
   `push_annotations` (any small batch) and `start_draft_review_wave` (any angles) directly.
   Verification points → artifacts: the live `no_surface` refusal (unprimed annotation
   surface) and the live `no_draft_context` refusal (unprimed draft context), quoted verbatim.
   This is the one deliberate live probe of the refusal arms; every other degrade arm stays
   capture-if-fired.

### Leg 1 — `/pr-review-browser <F> <focus note>` (foreign mode, the scratch PR)

3. **Launch the dogfood session (human).** A fresh interactive `pi` from the implementation
   worktree root.
4. **Invoke the door (human).** `/pr-review-browser <F> <focus note>` with a **real** focus
   note. Verification points → artifacts:
   - **background open:** guidance injected immediately (the URL known at port pick, before
     readiness); both companions primed at port pick; the readiness info note arriving
     asynchronously; the browser opens on the PR;
   - **ONE `start_review_wave` launch** (2–3 angles, `claimed-intent` mandatory; the operator
     focus threaded as `directive`); children never receive the surface handle;
   - **the `subagent_wait({timeoutMs})` relay loop:** timestamps proving **≥1
     `push_annotations` push predates the wave completion**; the parent holds its turn open
     (axis d); batches deliver on wait expiries (axis a);
   - **dedupe via the tool's result counts:** `skipped` > 0 on a cross-angle duplicate anchor
     (axis b), or the honest "no duplicate anchors arose";
   - **`collect_review_wave` after completion** (a `wave_running` soft-fail = keep looping);
     the typed aggregate quoted verbatim;
   - **reconcile:** `replace: true` per reshaped angle, or the honest "nothing superseded";
   - **planted-signal scorecard row:** did the wave catch the one planted signal?;
   - **human triage in the browser; no posting requirement** (the flipped contract — perk
     composes nothing by default); degrade arms capture-if-fired.

### Leg 2 — `/plan-review-browser <custom angle text>` (the plan draft leg)

5. **Launch a scratch plan-authoring session (human).** `perk plan` from the implementation
   worktree. The operator dictates a scratch draft (the model writes it via `plan_draft`)
   planting **two signals**: a claim naming a nonexistent file/symbol (for `grounding`) and an
   explicitly unresolved decision (for `decision-completeness`).
6. **Invoke the door (human).** `/plan-review-browser <custom angle text>` with a real custom
   angle definition — the never-live-run custom lane. Verification points → artifacts:
   - **stage gate + drafts-only resolve** (the validated artifact; no param/transcript tier);
   - **the custom lane live:** its own `custom` lane in `covered`, browser badge
     `perk:custom`;
   - **2–3 standard angles by model judgment** (none mandatory on the draft wave);
   - **phrase-anchored pushes:** byte-exact spans anchoring in the browser; `phrase: null`
     globals landing in the sidebar;
   - **streaming cadence + dedupe as Leg 1** (timestamps; verbatim tool results);
   - **scorecard (2 planted signals);**
   - **DENY** → the feedback returns delimited as untrusted DATA
     (`<untrusted_reviewer_feedback>`) driving a `plan_draft` revise round → **abandon the
     session (nothing saved)**.

### Leg 3 — `/objective-review-browser` (the objective draft leg)

7. **Launch a scratch objective-authoring session (human).** `perk objective author` from the
   implementation worktree. The operator dictates a scratch draft (prose + a small roadmap)
   planting **one signal**.
8. **Invoke the door (human).** `/objective-review-browser` (custom lane optional — Leg 2
   carries the custom-lane evidence). Verification points → artifacts:
   - **the RENDERED draft is what the browser shows** (prose + the `**Delivery:**` line + the
     roadmap table, never raw JSON);
   - **wave context `draftType: "objective"`;**
   - **streaming cadence + dedupe as Leg 1;**
   - **scorecard (1 planted signal);**
   - **the Direct-Edits carve-out observed live:** the human makes a browser **Direct Edit +
     APPROVE** → **nothing saved**, one model-mediated `objective_draft` revise round returns,
     the gate untouched → **abandon the session (nothing saved)**.

### Degrade capture (all legs — capture-if-fired, never forced)

Recorded **if they fire**: hold-and-accumulate (`held`/`held_batches` > 0), readiness degrade
(plus the post-degrade `no_surface`/`no_draft_context` refusal and the ignored-late-decision
arm), and wave incompleteness (`complete: false`, uncovered lanes named). Any arm that never
fires is recorded as offline-pinned — naming `annotationPush.test.ts`,
`reviewWaveTools.test.ts`, `draftReviewWaveTools.test.ts`, `prReviewBrowser.test.ts`,
`planReviewBrowser.test.ts`, `objectiveReviewBrowser.test.ts` — and listed as a named residual,
never papered over.

### The bounded tuning pass (the loop, not the fixes)

No fix list is authored in advance — fixes emerge from the runs:

1. Every defect/friction hit during a leg becomes a `D<n>` row (diagnosis artifacts inlined).
2. **Bounded fixes** land in-branch, scoped to the doors/waves/tools surface, each pinned
   offline where deterministic (the six `*.test.ts` suites above are the pin surface).
3. A fix that invalidates an executed leg re-runs that leg (fresh dogfood session — restart
   after code changes).
4. Anything larger than a bounded fix is **deferred**: the row's disposition names a follow-up
   (surfaced at `/objective-reconcile`).
5. The operator may call the node **honest-incomplete** at any point — residuals named here,
   never ground to "complete"; the dogfood-dependent doc edits are then made only for legs
   that actually ran (an unrun leg leaves the corresponding learned-doc note standing,
   truthfully).

### Teardown (before the node's `/submit`)

9. **Close PR F unmerged, delete the branch (session).** `gh pr close <F>`;
   `git push origin --delete review-dogfood-f`; delete the local branch; remove the staging
   worktree; verify `git ls-remote origin 'refs/heads/review-dogfood-*'` empty and no
   `review-*` checkout anywhere. Scratch plan/objective sessions saved nothing — no issue
   cleanup exists by construction (verify: no new issues minted). Attest in Part B.

## Part B — captured evidence + defect log

*Filled during/after the live legs: the verification-point → artifact checklists with key
excerpts inlined (GitHub artifacts and sessions expire; a pointer alone rots), the
planted-signal scorecard (4 signals across legs 1–3), the `D`-row defect log, the
honest-residuals list, and the teardown evidence.*

### Execution-time preconditions

**Verified 2026-08-10 by the implementation session (before staging):** `node_modules`
present in the implementation worktree; `.pi/settings.json` packages carry `".."` and the
object-form `npm:@plannotator/pi-extension` entry; `[models.subagents]` in `.perk/config.toml`
carries **no** `adversarial-reviewer` or `draft-reviewer` key (no `.perk/local.toml` exists) —
the shipped defaults are what run (`agents/adversarial-reviewer.md`:
`anthropic/claude-fable-5`; `agents/draft-reviewer.md`: `openai/gpt-5.6-sol`). Installed
versions: `@plannotator/pi-extension` **0.26.5** (0.26.4 at the node-1.4 pin — a patch bump;
drift would degrade loudly as readiness `timeout` / `push_rejected` and become a D-row),
`pi-subagents` **0.45.1** (0.45.0 at node 1.1 — a patch bump; the doctor `subagent-compat`
probes are the drift tripwire).

### The staged target (PR F)

Staged **2026-08-10** by the implementation session (Part A step 1), from a throwaway detached
worktree (`.worktrees/review-dogfood-staging`) off `origin/main` at `2525af0d` (the `plan-1514`
implementation branch untouched), fresh planted content (the prior instances — the
`perk worktree create`→`new` and `--allow-project-ci`→`--allow-ci` flips — are described
verbatim in `pr-review-doors-dogfood.md`, which the PR-head checkout contains):

- **PR F — <https://github.com/mattgiles/perk/pull/1519>** (branch `review-dogfood-f`, head
  `a867d65a`), titled "docs: wording pass on the capture-a-gist how-to", an honest body
  (*"Three small wording touch-ups in the capture-a-gist how-to. Docs-only, no behavior
  change."*), no injection line. The diff (1 file, `docs/user-docs/how-to/capture-a-gist.md`):
  two genuine tweaks ("settle it during authoring" → "settle it while authoring", "adopt it in
  place with the normal doors" → "adopt it in place through the normal doors") plus **one
  planted wrong-fact "tidy"** — the `perk gist list` backlog flag renamed `--all` →
  `--include-adopted`, cross-verifiable against
  `docs/user-docs/reference/cli.md` ("`--all` shows everything with an adopted marker"), the
  CLI source (`src/perk/cli/commands/gist/list_cmd.py`'s `@click.option("--all", …)`), and
  `skills/perk-expert/references/cli.md`.

### Leg 0b — the live refusal probe

*Pending.*

### Leg 1 — `/pr-review-browser` (foreign mode, PR F)

*Pending.*

### Leg 2 — `/plan-review-browser` (the plan draft leg)

*Pending.*

### Leg 3 — `/objective-review-browser` (the objective draft leg)

*Pending.*

### The planted-signal scorecard

| leg | signal | planted as | caught? | by | notes |
|---|---|---|---|---|---|
| 1 (PR F) | subtle defect in claimed scope | `--all` → `--include-adopted` (`capture-a-gist.md`) | | | |
| 2 (plan) | ungrounded claim (nonexistent file/symbol) | *dictated at leg 2* | | | |
| 2 (plan) | unresolved decision | *dictated at leg 2* | | | |
| 3 (objective) | *one signal, dictated at leg 3* | | | | |

### Defect / friction log

Fresh `D`-numbered rows (the prior record's D-rows are the ancestors); every row carries
diagnosis artifacts + a disposition (`fixed-in-branch (commit …)` or `deferred (follow-up …)`).

| # | Defect / friction | Diagnosis artifacts | Disposition |
|---|---|---|---|

### Honest residuals

*To be settled with the legs.*

### Teardown evidence

*Pending.*
