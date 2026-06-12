# perk/ taxonomy decision record (Objective #349, Node 2.1)

This is the durable decision record for the feature-directory taxonomy of the flat `perk/`
Python package: the full file→subpackage mapping, the import-posture audit, the per-file split
verdicts (including the `perk/github.py` → `perk/github/` package conversion verdict that gates
node 2.2), the move-safety audit, and the tranche plan node 2.3 executes. **No source moves
happen in node 2.1** — nodes 2.2 and 2.3 implement against this doc.

Plan: github #426. Sibling: node 1.1 (extension/ taxonomy) had no recorded decision when this
was written; naming parity with 1.1's eventual choices is a node 3.1 reconciliation concern,
not enforced here.

## Status at decision time

- `perk/` has **32 Python files flat** at the package root plus one existing subpackage,
  `perk/cli/` (already feature-organized: `cli/commands/<group>/` per CLI group — the §8.1
  group-dir template).
- Sizes: `github.py` 2103 lines, `init.py` 1120, `doctor.py` 1095, `linear_backend.py` 989,
  `objective.py` 729, `launch.py` 643; everything else ≤ 375.

## Import-posture audit

Verified by a full `from perk` grep over `perk/`.

**Leaves (no intra-perk imports):** `output.py`, `_resources.py`, `env.py`, `capabilities.py`,
`run_id.py`, `git.py`, `plan.py`.

- `cache.py` imports **only** `perk.output` — the documented deliberate import-leaf
  (`docs/learned/workflow/cold-door-launch.md`); `github.py` lazily imports `cache`
  (`# noqa: PLC0415`, the only lazy intra-perk import in the package) to avoid the cycle.
- **Contract readers:** `registry.py` → `_resources`; `bindings.py`/`providers.py` →
  `_resources`, `registry`; `config.py` → `bindings`; `binding_delivery.py` → `bindings`,
  `registry`.
- **Gateway/domain:** `github.py` → `objective`, `plan`; `objective.py` → `plan`.
- **Issue tier:** `issue_backend.py` → `objective`, `github`; `linear.py` → `issue_backend`;
  `linear_backend.py` → `github`, `issue_backend`, `objective`, `plan`, `linear`;
  `linear_agent.py` → `cache`, `linear`; `issues.py` (the resolver) → `config`, `github`,
  `issue_backend`, `linear`, `linear_backend`, `objective`.
- **Run tier:** `runner.py` → `github`; `workflow_artifacts.py` → `runner`;
  `workflow_smoke.py` → `github`, `run_id`, `runner`; `resume.py` → `issue_backend`, `plan`;
  `launch.py` → `cache`, `git`, `github`, `issues`, `linear_agent`, `run_id`, `runner`,
  `binding_delivery`, `config`, `registry`, `output`, **`cli.ensure`**; `run_report.py` →
  `cache`, `issues`, `output`; `run_worker.py` → `cache`, `issues`, `launch`, `linear_agent`,
  `resume`, `run_report`, `registry`, `output`, **`init` (the `GIT_PACKAGE` constant only)**,
  **`cli.ensure`**.
- **Convergence:** `init.py` → `bindings`, `cache`, `capabilities`, `env`, `git`, `github`,
  `linear`, `linear_backend`, `workflow_artifacts`, `config`, `providers`, `output`,
  **`cli.ensure`**; `doctor.py` → those plus `gc`, `init`, `issues`, `registry`,
  `workflow_artifacts`, **`cli.ensure`**.
- **State:** `gc.py` → `cache`, `registry`, `run_id`, `output`.

### Inverted edges (warts recorded, not fixed here)

- `launch.py`, `init.py`, `doctor.py`, `run_worker.py` import `perk.cli.ensure`
  (`UserFacingCliError` / `Ensure`) — a core→cli edge. Out of scope for this objective (moves
  only, zero logic edits); recorded as a **flagged deferral**.
- `run_worker.py` → `init.GIT_PACKAGE` is an upward constant-only import (run→convergence).
  Not a Python import cycle (no module-level cycle exists); harmless as long as subpackage
  `__init__.py` files stay **empty** (see D2).

## Move-safety audit

- `pyproject.toml`: hatchling `packages = ["perk"]` auto-includes subpackages; sdist
  `only-include = ["perk", ...]` fine; `force-include "shared" = "perk/_shared"` unaffected;
  ruff `include = ["perk/**/*.py", ...]` and ty `include = ["perk", "tests"]` recursive — **no
  toolchain config changes needed for moves**.
- `perk/_resources.py` resolves the dev-mode `shared/` via
  `Path(__file__).resolve().parent.parent / "shared"` — **depth-sensitive**; moving it one
  level deeper silently breaks editable installs. Verdict: stays flat (it is
  package-root-anchored by design, paired with the wheel's `perk/_shared`).
- Source-scan guard tests anchor on module `__file__`:
  - `tests/test_cache_guard.py` scans `Path(cache.__file__).parent.rglob("*.py")` with
    `ALLOWED = {"cache.py"}` — if `cache.py` moves into a subpackage the scan root **narrows
    to that subpackage** (guard goes near-vacuous over the rest of `perk/`) and the allowlist
    path changes. 2.3 must re-anchor `_perk_dir()` to the `perk` package root (e.g. via
    `Path(perk.__file__).parent`) and update `ALLOWED` to the new relative path — a
    guard-anchor data fix, not test logic.
  - `tests/test_issues.py` `TestConsumerBoundary` scans `Path(issues.__file__).parent` with
    `allowed = {perk_dir/"issues.py", perk_dir/"github.py"}` — same re-anchor + allowlist
    update when `issues.py` moves and when `github.py` becomes a package.
  - `tests/test_issue_backend.py` `TestImportDirection` reads `Path(github.__file__)` — under
    a package that is `__init__.py` (near-empty), making the guard vacuous; 2.2 must scan the
    package directory instead.
  - `tests/test_tooling.py` sanctions `subprocess.run` wrappers by `(path.stem, func.name)` —
    directory moves don't change stems, but the github split renames the `_run` host file
    (key `("github", "_run")` → the new helpers module's stem, `("_exec", "_run")`).
- Test monkeypatch surface: tests patch `subprocess.run` globally (split/move-safe) or
  attributes on the imported module object (`monkeypatch.setattr(github, "check_auth", ...)`)
  — move-safe after the mechanical import sweep. Exactly **8 sites in 2 files** patch the
  private `github._run` (`tests/test_plan_save.py` ×1, `tests/test_pr_review_post_cmd.py` ×7)
  — these need a one-line patch-target update under the github split (see D3).
- `shared/contracts.md` cites `perk/<module>.py` paths 48 times; `docs/learned/` and skills
  cite more. All deferred to **node 3.1** (path-reference reconciliation) by design.

## D1 — The taxonomy (full file→home mapping)

Six homes (five new subpackages + the `github/` package), with five files deliberately flat.

**Target tree (end state after 2.2 + 2.3; every current file appears exactly once):**

```
perk/
├── __init__.py                  (flat — version anchor, hatch version path)
├── __main__.py                  (flat — entrypoint)
├── _resources.py                (flat — depth-sensitive shared/ resolver)
├── plan.py                      (flat — domain core: plan header/body engine)
├── objective.py                 (flat — domain core: objective storage + mechanics)
├── github/                      ← github.py converted in place (node 2.2)
│   ├── __init__.py              (re-exports every public name — perk.github paths preserved)
│   ├── _exec.py                 (helper family: GitHubError, _run, _run_json, _parse_json,
│   │                             _rest_args, _failed, _is_not_found, _body_file, timeouts)
│   ├── auth.py                  (AuthStatus, RepoAccess, check_auth, check_repo_access)
│   ├── plans.py                 (label + plan/learn issue ops)
│   ├── objectives.py            (objective issue ops)
│   ├── prs.py                   (PR lifecycle ops)
│   ├── reviews.py               (review-feedback GraphQL + review-context/post ops)
│   └── workflows.py             (workflow-run ops + permissions/secrets)
├── substrate/                   ← contract readers + bottom-layer primitives
│   ├── __init__.py              (empty)
│   ├── output.py
│   ├── git.py
│   ├── config.py
│   ├── registry.py
│   ├── bindings.py
│   ├── providers.py
│   └── binding_delivery.py
├── state/                       ← .pi/workflow/ state tier
│   ├── __init__.py              (empty)
│   ├── cache.py                 (stays the import-leaf: imports only substrate.output)
│   ├── gc.py
│   └── run_id.py
├── backends/                    ← the issue-tracking tier
│   ├── __init__.py              (empty)
│   ├── issue_backend.py         (the protocol/contract)
│   ├── issues.py                (the resolver / consumer boundary)
│   ├── linear.py
│   ├── linear_backend.py
│   └── linear_agent.py
├── run/                         ← launch/run: cold door + remote-runner seam
│   ├── __init__.py              (empty)
│   ├── launch.py
│   ├── resume.py
│   ├── runner.py
│   ├── run_worker.py
│   ├── run_report.py
│   ├── workflow_artifacts.py
│   └── workflow_smoke.py
├── convergence/                 ← init/doctor + their inputs
│   ├── __init__.py              (empty)
│   ├── init.py
│   ├── doctor.py
│   ├── env.py
│   └── capabilities.py
└── cli/                         (unchanged — already feature-organized)
    ├── __init__.py
    ├── cli.py
    ├── alias.py
    ├── context.py
    ├── ensure.py
    ├── stages.py
    └── commands/…
```

Rationale anchors: `plan.py`/`objective.py` stay flat because `github`, `backends`, and `cli`
all import them — they are the domain core, not members of any one feature; placing them flat
avoids both a one-axis misfile and a two-file `domain/` dir. `_resources.py` stays flat for
the depth-sensitive resolver (above). `workflow_smoke.py` goes with the remote-runner family
(`run/`) rather than convergence: it imports `github`/`run_id`/`runner` and is the CI-dispatch
core; its doctor command wrapper stays in `cli/commands/doctor/`.

Layering that results (clean downward imports, with the two recorded warts):
`substrate` ← `state` ← (`plan`/`objective` flat) ← `github` ← `backends` ← `run` ←
`convergence`.

### File→home mapping (all 32 current `perk/*.py` files, exactly once)

| Current file | Home |
| --- | --- |
| `__init__.py` | flat (unchanged) |
| `__main__.py` | flat (unchanged) |
| `_resources.py` | flat (unchanged) |
| `plan.py` | flat (unchanged) |
| `objective.py` | flat (unchanged) |
| `github.py` | `github/` package (in-place conversion, node 2.2) |
| `output.py` | `substrate/` |
| `git.py` | `substrate/` |
| `config.py` | `substrate/` |
| `registry.py` | `substrate/` |
| `bindings.py` | `substrate/` |
| `providers.py` | `substrate/` |
| `binding_delivery.py` | `substrate/` |
| `cache.py` | `state/` |
| `gc.py` | `state/` |
| `run_id.py` | `state/` |
| `issue_backend.py` | `backends/` |
| `issues.py` | `backends/` |
| `linear.py` | `backends/` |
| `linear_backend.py` | `backends/` |
| `linear_agent.py` | `backends/` |
| `launch.py` | `run/` |
| `resume.py` | `run/` |
| `runner.py` | `run/` |
| `run_worker.py` | `run/` |
| `run_report.py` | `run/` |
| `workflow_artifacts.py` | `run/` |
| `workflow_smoke.py` | `run/` |
| `init.py` | `convergence/` |
| `doctor.py` | `convergence/` |
| `env.py` | `convergence/` |
| `capabilities.py` | `convergence/` |

## D2 — Subpackage `__init__.py` files stay empty (except `perk/github/`)

No re-export shims for moved modules: node 2.3 does `git mv` + a full mechanical import sweep
(production + tests), exactly like the extension tranches (1.2/1.3). Empty `__init__.py` files
also make the package-level `run`↔`convergence` edge pair (doctor→workflow_artifacts,
run_worker→init) harmless — no eager submodule imports, no initialization-order coupling.
`perk/github/__init__.py` is the **one** re-exporting init (D3).

## D3 — github.py → github/ verdict: YES (gates node 2.2)

Confirmed. 2103 lines fusing four tiers behind eight existing `# ===` section banners, with
the helper family and seams already documented
(`docs/learned/workflow/github-gateway.md`). The submodule mapping is the `github/` subtree in
the D1 tree above, split along those banners:

- `_exec.py` — the shared helper family + error type: `GitHubError`, `_run`, `_failed`,
  `_is_not_found`, `_parse_json`, `_run_json`, `_rest_args`, `_body_file`, the timeout
  constants.
- `auth.py` — Phase-0 reads: `AuthStatus`, `RepoAccess`, `check_auth`, `check_repo_access`,
  `_parse_scopes`.
- `plans.py` — label + plan/learn issue ops (mutations section): `Label`, `PlanIssue`,
  `CommentResult`, `PlanUpdate`, `LearnIssueSummary`, `create_label` … `add_issue_comment`.
- `objectives.py` — the objective ops section (`ObjectiveIssue` … `update_objective_body`).
- `prs.py` — the PR lifecycle section (`PullRequest`, `PlanState` … `merge_pr`,
  `validate_pr_body`).
- `reviews.py` — review-feedback (GraphQL, incl. `_graphql`/`_graphql_proc`) +
  review-context/post ops (`PrFeedback`, `resolve_review_threads`, `get_pr_review_context`,
  `post_pr_review`, `add_pr_reaction`).
- `workflows.py` — workflow-run ops + permissions/secrets (`WorkflowRun`, `trigger_workflow` …
  `WorkflowPermissions`, `secret_exists`, `get_repo_variable`).
- `__init__.py` — re-exports **every public name** (and `_exec` as a module attribute) so all
  existing `from perk.github import X` / `github.X(...)` call sites keep working unchanged.

**Intra-package call convention (the namespace-patching hazard):** submodules bind the
**module**, never the function — `from perk.github import _exec` (or `from . import _exec`)
and call `_exec._run(...)`. This keeps one canonical patch point; the 8 existing
`monkeypatch.setattr(github, "_run", …)` sites become
`monkeypatch.setattr(github._exec, "_run", …)` — a mechanical patch-target sweep, no test
logic. Known 2.2 collateral (from the move-safety audit above): `test_tooling.py` wrapper key
`("github", "_run")` → `("_exec", "_run")`; `test_issues.py` consumer-boundary allowlist
`github.py` → the `github/` dir; `test_issue_backend.py` import-direction scans switch from
`github.__file__` to scanning the package dir.

## D4 — No other file splits (per-file verdicts)

Mirror node 1.1's bias: long files are okay.

- `init.py` (1120) and `doctor.py` (1095): check/convergence registries with strong internal
  ordering (`GROUP_ORDER`, managed-convergence SSOT) — splitting them adds seams without
  consumers. **No split.**
- `linear_backend.py` (989): one adapter implementing one protocol. **No split.**
- `objective.py` (729) and `launch.py` (643): single-feature modules behind byte-exact test
  pins. **No split.**
- Everything else ≤ 375 lines. **No split.**

Verdict: `github.py` is the **only** split.

## D5 — Tranche plan for node 2.3 (two tranches, one PR each)

- **Tranche A — bottom layers**: `substrate/` + `state/` (10 files). The widest import sweep
  (`output`, `cache`, `config`, `registry` are the most-imported names) — isolating it keeps
  the diff reviewable. Includes the `test_cache_guard.py` re-anchor.
- **Tranche B — feature tiers**: `backends/` + `run/` + `convergence/` (16 files). Includes
  the `test_issues.py` consumer-boundary re-anchor.
- Each tranche: `git mv` in its own commit, then the import sweep commit (production + tests +
  monkeypatch-target strings), CI green, zero test-logic edits (guard re-anchors are
  sanctioned data/anchor fixes, called out in the tranche PR description).
- Node 2.2 (the github package) runs as its own PR, before or after 2.3 — it is independent
  (path-preserving, no import sweep outside the guard/patch collateral listed in D3).

## Flagged deferrals

- The `perk.cli.ensure` core→cli import inversion (`launch.py`, `init.py`, `doctor.py`,
  `run_worker.py`) — out of scope for this objective (moves only, zero logic edits).
- The `run_worker.py` → `init.GIT_PACKAGE` upward constant-only import — harmless under empty
  `__init__.py` files; left as-is.
- Path-reference reconciliation — `shared/contracts.md` (48 `perk/<module>.py` citations),
  `docs/learned/`, and skill docs — is **node 3.1**, including naming parity with node 1.1's
  eventual extension/ taxonomy choices.
