# Phase 3 · Turn 8 — remote-runner prerequisites: credential + permission health-checks (`perk doctor`)

GitHub plan **#184** (Objective #137, Node 2.4). Node 2.2 (#171) shipped the managed runner workflow
whose `Validate required secrets` step enforces the runner's credentials **at execution time** — it
fails the CI job fast when `PERK_GH_PAT` is empty, or when **both** `ANTHROPIC_API_KEY` and
`OPENAI_API_KEY` are empty (contracts.md §8.14, defect-fix B5). But there was **no pre-flight check**:
nothing surfaced "your runner is missing `PERK_GH_PAT`" until a real `--remote` dispatch reached CI
and the validate step failed.

This turn builds the **diagnostic twin**: a `perk doctor` `runner` check group that health-checks the
runner's prerequisites (checkout/push PAT, model credential, repo workflow-permissions) ahead of time
— perk's analogue of erk's `erk-queue-pat-secret` / `anthropic-api-secret` / `workflow-permissions`
doctor checks, adapted to Pi (multi-provider model keys) and perk's `{owner}/{repo}` gateway
convention.

It does **not** build the `perk doctor workflow` subcommand + live-spawn CI smoke (Node 3.3), any
GitHub **mutation** (Decision D2 — perk init/doctor never mutate GitHub), or the supervisor command
surfaces (Nodes 3.1/3.2).

## Decisions

- **Three verification-only gateway reads (`perk/github.py`, new "Runner-prerequisite reads" section
  near the workflow-dispatch ops).** All mirror `check_auth`/`check_repo_access`: `cwd=repo_root` +
  gh's `{owner}/{repo}` placeholder (no remote-URL parsing); routed through `_run`; a gh-missing/
  timeout raises `GitHubError`. None mutate.
  - `secret_exists(*, name, repo_root) -> bool | None` — 200→`True`, 404→`False`, else→`None`
    (unknown, e.g. 403). Never reads the value.
  - `get_workflow_permissions(*, repo_root) -> WorkflowPermissions | None` — new frozen dataclass
    (`default_workflow_permissions: str`, `can_approve_pull_request_reviews: bool`); non-zero→`None`,
    unparseable→`GitHubError`.
  - `get_repo_variable(*, name, repo_root) -> str | None` — `--jq .value`; value on 0, `None` on
    404/non-zero/empty. Reads `PERK_ENABLED`.
- **Report-only `runner` check group (`perk/doctor.py::_runner_checks`), non-fatal.** Present→`ok`;
  actionable-absent→`warn`; unverifiable→`info`; **never `fail`** (a `warn` keeps exit 0). Wired into
  `_build_checks` inside `if verify:` after `_github_checks`, wrapped in `try/except GitHubError` → a
  single `info` degrade. `_apply_fixes` is untouched — a pure validation with no converge/`--fix`
  side legitimately appends directly to `_build_checks` (the `bindings`/`providers` precedent; the
  "report-only check is not a hand-authored managed check" exception in `init-doctor.md`).
- **Gating ("check only what's enabled," D4).** Auth gate first (unauthed → single `runner-prereqs`
  `info`, no further `gh`); always emit `runner-enabled`; `PERK_ENABLED=false` → stop (don't nag a
  deliberately-disabled runner); else run the three probes.
- **The three probes (D5).** `runner-pat-secret` (`RUNNER_PAT_SECRET`), `runner-model-secret` (both
  `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`, "either" logic), `runner-workflow-permissions` (advisory
  `info` in all non-error cases — perk pushes with a PAT, not `github.token`). Constants imported from
  `perk.workflow_artifacts` (no hardcoded literals).
- **Self-vs-consumer dual mode (D6).** Identical check *set* (the `runner-workflow` capability is
  `scope="both"`); only the actionable-absent `detail` wording adapts. No new capability → the
  coherence guard is unaffected.
- **Human-render visibility (D7).** `runner` added to `doctor_cmd._GROUP_ORDER` after `github` (the
  `_GROUP_ORDER` trap — a group absent from that tuple is invisible in human text).
- **No mutation (D2).** Each actionable finding carries an exact `gh` remediation string; perk does
  not adopt erk's mutating `admin gh-actions-api-key`.

## Contract

`shared/contracts.md` §8.16 added (the three reads, the `runner` group + names + non-fatal posture,
the `PERK_ENABLED` gating, the init-manages/doctor-health-checks division, the Node-3.3 reuse note);
`runner` added to §8.6's groups list; §8.14/§8.15's "Node 2.4" forward references reconciled.

## Outcomes

_(implemented as planned)_

- `perk/github.py` — added `WorkflowPermissions` + `secret_exists` / `get_workflow_permissions` /
  `get_repo_variable`.
- `perk/doctor.py` — added `_runner_checks` (free function; constants imported lazily from
  `perk.workflow_artifacts` to avoid a top-level import cycle concern) + the `try/except` degrade in
  `_build_checks`. `_apply_fixes` untouched.
- `perk/cli/commands/doctor_cmd.py` — `runner` inserted into `_GROUP_ORDER` after `github`.
- Tests: `tests/test_github.py` covers the three reads (present/404/403/unparseable/gh-missing);
  `tests/test_doctor.py` drives `_runner_checks` directly (unauthed, disabled, all-present,
  PAT-absent-stays-healthy, unverifiable, model-either, workflow-permissions advisory, self-vs-
  consumer detail), the `GitHubError` degrade via `run_doctor(verify=True)`, and the render-visibility
  of the `runner` group. The `test_every_required_capability_has_a_doctor_check` guard stays green
  unchanged.
