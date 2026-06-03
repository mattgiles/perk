# P2.T8 — Deepen submission & landing + the CLI plumbing slice

Implementation-level plan + outcomes for **P2.T8**. Give the Phase-1 thin `submit`/`land`/`learn`
their real depth, and land the phase's cross-cutting CLI/config wiring — all independent of the
gating arc (T1/T2/T5). Three seams, landed in order **a → b → c**. The canonical plan is GitHub
issue #17; this doc captures decisions and the as-built outcomes.

## Seams

- **T8a — PR-body craft.** `perk pr-submit` composes an HTML-enhanced GitHub PR body that embeds the
  full plan in a collapsible `<details>` (fed from the plan issue), with a **plain-backtick checkout
  footer carrying the real PR number** (create-then-update, because the PR number is unknown at
  create). This deepens the body *and* fixes a latent correctness bug (the Phase-1 footer used the
  **issue** number). A deterministic `perk pr-check` validates the footer. Submit keeps the PR
  **draft**; a new deliberate `/ready` (`perk pr-ready`) is the review gate.
- **T8b — deep `/land` + `/learn`.** Establish the reconciliation-typing vocabulary
  (Mechanical / Reconcilable / Immutable); apply only the deterministic **Mechanical** update on
  land (plain `title + Closes #N` squash commit). Graduate `/learn` from a thin marker-clear into a
  real knowledge-capture pass: a `perk:learn` labelled issue created from agent-captured learnings
  (idempotent via a **`perk:learn`-scoped** finder), then clear `pending-learn`.
- **T8c — the CLI plumbing slice.** Graduate the Phase-1-blocked `--remote` stub into a real
  **target resolver** threaded through `launch_stage`, and flip `doors.cold_remote: true` on the
  stages that can run remote (`implement`, `address`). Phase 2 *builds and resolves* the target;
  Phase 3 *drives* it.

## Decisions (resolved)

- **D0** — one turn doc, three verify gates (`verify-p2-t8a/b/c.sh`), three outcomes sub-sections;
  all gates run fully offline (`CliRunner` + subprocess-stubbed gateway + `--dry-run`; TS via the
  P1.T1 harness + `fakePerk`).
- **D1** — GitHub mutations stay canonical in the Python gateway; TS warm doors delegate via
  `pi.exec(..., "--json")` and never throw.
- **D2** — the PR body is composed via create-then-update (the chicken-and-egg footer); `github.
  update_pr_body` (REST `PATCH .../pulls/{n}`) re-writes the full body with the plain footer once
  the PR number is known. This fixes the issue-numbered-footer bug.
- **D3** — plan embedding is best-effort and graceful (`get_plan_body`; `None` → no embed, no raise;
  no model call).
- **D4** — the two-target split is explicit: HTML `<details>` + footer go only into the GitHub PR
  body; the squash commit message stays plain text (set at land, D8).
- **D5** — `pr check` = a pure `validate_pr_body` (footer-scoped: present, correct PR number with
  word-boundary, plain backtick not HTML) + a `perk pr-check` worker, run as a post-write self-check
  inside `pr-submit` (raises `pr_check_failed`).
- **D6** — submit keeps the PR draft; a new `/ready` (`perk pr-ready` + `extension/ready.ts`) is the
  deliberate review gate (idempotent). No plan-file-diff completion detector (perk plans are issues,
  not repo files).
- **D7** — `submit.ts` surfaces `plan_embedded` in the success message (no behavioral change).
- **D8** — squash commit message deepened to plain `"<plan title>\n\nCloses #<issue>"` (fallback to
  `Closes #<issue>` on empty title).
- **D9** — reconciliation typing established as vocabulary; only the **Mechanical** type applied this
  turn. Reconcilable / objective reconciliation deferred to T11.
- **D10** — `/learn` gains a real knowledge-capture pass with a **`perk:learn`-scoped** idempotency
  finder: `plan.LEARN_LABEL` + `LEARN_HEADER_KEY`; `github.find_learn_issue` (parameterized
  `find_plan_issue` by `label`/`header_key`); `github.create_learn_issue` (lazy label, idempotent
  via `find_learn_issue`, renders the `learn-header`); `perk learn-capture --json --body <file>`
  worker; deepened `extension/learn.ts` (optional `summary`).
- **D11** — registry: add `github.learn` to the vocabulary; `learn` reads `[cache.markers,
  cache.plan-ref]`, writes `[cache.markers, github.learn, github.comments]`. The earlier P1.T5b gate
  is relaxed from equality to membership.
- **D12** — the `--remote` stub graduates to `launch.resolve_target(stage, remote) -> Target` (pure):
  `None` → local; `cold_remote:false` + remote → `remote_blocked`; `cold_remote:true` + remote →
  `RemoteTarget` descriptor surfaced in `--dry-run`/`--json`, then `remote_not_driven` exit (no
  persisted intent, no runner trigger).
- **D13** — flip `doors.cold_remote: true` on `implement` and `address` only.
- **D14** — reconcile the `--remote` help text on `cli/stages.py`, `implement_cmd.py`,
  `resume_cmd.py`.

## Test plan

- `verify-p2-t8a.sh` — `update_pr_body`/`validate_pr_body` units (incl. the issue-number regression
  + word-boundary + HTML-wrapped cases), `_compose_pr_body` embed/omit, `pr-submit`/`pr-check`/
  `pr-ready` `CliRunner`, the `/ready` TS harness, contract amendments.
- `verify-p2-t8b.sh` — `find_learn_issue` label-scoping regression (the plan issue is NOT matched),
  `create_learn_issue` idempotency + lazy label, the deepened land commit message, `learn-capture`
  `CliRunner`, the deepened `/learn` TS harness, registry `github.learn` + `learn` I/O.
- `verify-p2-t8c.sh` — the `resolve_target` matrix, `perk implement --remote --dry-run`
  resolves+exits `remote_not_driven`, the local path unchanged, the registry `cold_remote` flips +
  self-check.

`just verify` runs t1…t7 + p1-t1…p1-t5c + p2-t1…p2-t7 + **p2-t8a + p2-t8b + p2-t8c**; `just ci`
green. The live PR-body render / draft→ready / learn-issue creation are a dogfood/manual gate
(recorded in outcomes when exercised) — CI covers the deterministic Python + TS delegation.

## Outcomes (as built)

### T8a — PR-body craft

Built as planned. `perk/github.py` gained `update_pr_body` + `PrBodyUpdate`, `get_pr_body`, and the
pure `validate_pr_body` (footer-scoped, three checks). `pr_submit_cmd._compose_pr_body` now takes
`plan_body`/`pr_number`, embeds the verbatim plan in a `<details>` when available, and appends the
plain-backtick PR-numbered footer; the false "No HTML `<details>`" docstring line was deleted. Submit
fetches the plan body best-effort, creates the draft PR, re-writes the body with the footer via
`update_pr_body`, then runs `validate_pr_body` as a self-check (`pr_check_failed`). New workers
`perk pr-check` / `perk pr-ready` + `extension/ready.ts` (`ready` tool + `/ready`) landed;
`submit.ts` surfaces `plan_embedded`. Ships `verify-p2-t8a.sh`.

### T8b — deep `/land` + `/learn`

Built as planned. `plan.py` gained `LEARN_LABEL`/`LEARN_HEADER_KEY` and a generalized
`extract_run_id(header_key=...)`. `github.py` generalized `find_plan_issue(label=, header_key=)` and
added `find_learn_issue` (perk:learn-scoped) + `create_learn_issue` (lazy label, idempotent via
`find_learn_issue`, renders the `learn-header`). `pr_land_cmd` deepened the squash commit to plain
`title + Closes #N` (fallback on empty title). New `perk learn-capture --json --body <file>` worker;
`extension/learn.ts` deepened (optional `summary` → scratch → delegate → mirror marker-clear; thin
fallback when absent). Registry: `github.learn` vocabulary + `learn` I/O filled; the P1.T5b gate
relaxed to membership. Ships `verify-p2-t8b.sh`.

### T8c — the CLI plumbing slice

Built as planned. `launch.py` added `resolve_target` + `Target`/`RemoteTarget`; the hard
`remote is not None` raise was replaced with the resolver + `_surface_remote_target` (emits the
`--json` descriptor, exits `remote_not_driven`). Registry flips `cold_remote: true` on
`implement` + `address` (top comment updated). `--remote` help text reconciled on the three
launchers. Contracts §8.4 + docs/cli-vs-pi.md §4.5 record the flip. Ships `verify-p2-t8c.sh`.
