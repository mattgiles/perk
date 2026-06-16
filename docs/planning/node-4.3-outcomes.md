# Node 4.3 — phase→milestone sync seam + fail-open Project Updates (outcomes)

Part of Objective #548, Node 4.3. The plan body is the GitHub issue #604; this records what
*actually* landed.

## What shipped (matches the plan)

- **Op layer (`perk/backends/linear_backend.py`, `_LinearProjectOps`):**
  - `ensure_phase_milestone(*, project_id, name, known=None)` — the name-keyed lookup-or-create
    seam. `known is None` lists once via `project_milestones`; a supplied `known` map is used and
    updated in place (batch amortization). **Name is the deterministic key** (the 1.4 finding).
  - `create_project_update(*, project_id, body)` — the `projectUpdateCreate` mutation,
    `input = {projectId, body}` only (**no `health`**, D3). Flagged not-live-proven → Node 5.1.
- **Store (`LinearProjectObjectiveStore`):** `create_objective`'s milestone loop now routes through
  `ensure_phase_milestone` with a **seeded-empty `known`**, keeping the create path's network calls
  byte-identical (no extra `project_milestones` read — asserted in the happy-path test). Added
  `post_status_update(*, objective_id, body, dry_run=False) -> bool` (posts the Project Update;
  `dry_run` → `False`).
- **Protocol + other stores:** `ObjectiveStore` gained a **9th** method `post_status_update`.
  `GitHubObjectiveStore`, issue-backed `LinearObjectiveStore`, and the `_FakeObjectiveStore`
  conformance fake all `return False` (no update surface).
- **Transition sites (each fail-open, loud-but-non-fatal to stderr):**
  - `objective create` — posts on a fresh create only (`issue.existed is False`, non-dry-run).
  - `pr land` (`_reconcile_objective_on_land`) — posts once when ≥1 node was marked, via the new
    `_post_landed_update` helper; `complete=True` adds "Objective complete." Isolated like the
    existing close fail-open.
  - `objective reconcile` — posts on a real (non-dry-run, `result.updated`) update.
- **Pure body composers (`perk/objective.py`):** `objective_created_update_body`,
  `plan_landed_update_body` (pr normalized via `canonical_pr`), `reconciled_update_body`.
- **Contract:** `shared/contracts.md` §8.24 — method count eight→**nine**, Node 4.3 amendment added.
- **Docs:** `docs/linear-smoke-gate.md` gained a "Not-yet-live-proven Project ops (verify at Node
  5.1)" section with the `projectUpdateCreate` document; `providers-and-backends.md` notes the
  milestone grouping + Project Updates (additive / non-fatal).

## Deviations / refinements

- `ensure_phase_milestone` builds a local `table` (vs reassigning the `known` param) to satisfy ty's
  union narrowing; `_require_str` coerces the `dict[str, object]` milestone values to `str`.
- CLI fail-open tests assert against `result.stdout` (JSON) + `result.stderr` (non-fatal line)
  separately — Click 8.4.1's `CliRunner` keeps the streams distinct (`.output` is the combined
  stream; parsing it as JSON breaks on the appended stderr line).

## Forward role / boundaries (unchanged from the plan)

- **No node-add path built** — `objective.add_node` stays caller-less; the seam is the primitive a
  future `add_node`-to-an-existing-objective will reuse (`known=None`).
- **No phase-key→id registry** — name is the dedup key; **phase-header-text drift** producing a
  duplicate milestone is **Node 4.4's** repair surface.
- **No plan-save Project Update** (out of scope), **no `health` field** (D3).
- **Live verification** of `projectUpdateCreate` is deferred to the **Node 5.1** smoke gate
  (offline-covered here).
