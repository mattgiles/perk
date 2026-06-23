"""`perk doctor` — `init`'s diagnostic twin (the verify/repair engine).

Where `init` converges a repo *forward*, `doctor` **reports** coherence and `--fix`
**repairs** drift. The managed-piece checks reuse `init`'s convergence helpers in **dry-run**
mode (`apply=False`) — so init and doctor share one desired-state SSOT (D2) — and `--fix` runs
the same helpers with `apply=True`. Everything downstream of the group *builders* is **pure**
over a `list[Check]` (report / exit-code / json / render), so that layer tests without any
monkeypatch.

Principles (T6, from the erk prior-art pass):
- **No silent pass:** a check that cannot be evaluated reports `warn`/`info` *with the reason*,
  never a silent `ok`.
- **GitHub is non-fatal** (D3): unauthed / no-access / `gh` errored ⇒ `warn`, never `fail`.
- **Report, don't refuse** (D5): a missing required tool is a failing check (exit 1); only
  `not_a_repo` blocks (exit 2).

**Package layout (Node 2.2 module->package split).** The single-file ``doctor`` module was
decomposed into a package along its natural seams — a pure verbatim relocation (no logic edits,
beyond the audit decomposition of ``_linear_checks`` into per-phase sub-builders in
``linear_checks``). This ``__init__`` keeps the orchestration (``_build_checks``,
``workflow_checks``, ``run_doctor``, ``report_to_dict``) and re-exports every submodule symbol
behind a sorted ``__all__``, preserving the ``doctor.X`` attribute-access path verbatim (zero
consumer/test import churn). The orchestrators reference the group *builders* as bare facade
globals, so the existing ``doctor._env_checks`` / ``doctor._github_checks`` /
``doctor._runner_checks`` monkeypatches keep rebinding the names the orchestrators read; the
module-attribute patches
(``doctor_mod.linear.X`` / ``doctor_mod.init.X`` / ``doctor_mod.env``) mutate the shared
imported modules and are seen regardless of which submodule the builder lives in. Submodules:
``data`` (the leaf ``Check``/``Status``/``DoctorReport``), ``checks``, ``github_checks``,
``linear_checks``, ``fixes``.
"""

from pathlib import Path

from perk.backends import linear
from perk.convergence import env, init
from perk.convergence.doctor.checks import (
    _bad_handoffs,
    _bindings_check,
    _cache_check,
    _config_check,
    _env_checks,
    _extension_clone_check,
    _gc_check,
    _issues_check,
    _managed_checks,
    _providers_check,
    _registry_check,
    _skills_delivery_check,
    _subagent_engine_check,
)
from perk.convergence.doctor.data import _MANAGED_GROUP, Check, DoctorReport, Status
from perk.convergence.doctor.fixes import (
    _MIGRATIONS,
    _apply_fixes,
    _fix_config,
    _fix_linear_labels,
    _strip_ungrouped_ignore_line,
    _untrack_materialized_plan_cache,
)
from perk.convergence.doctor.github_checks import (
    _MODEL_SECRETS,
    _github_checks,
    _runner_checks,
    _runner_enabled_check,
    _runner_model_check,
    _runner_pat_check,
    _runner_permissions_check,
    _runner_workflow_managed_check,
)
from perk.convergence.doctor.linear_checks import (
    _LINEAR_KEY_REMEDIATION,
    _linear_checks,
    _linear_selected,
)
from perk.github import GitHubError

__all__ = [
    "_LINEAR_KEY_REMEDIATION",
    "_MANAGED_GROUP",
    "_MIGRATIONS",
    "_MODEL_SECRETS",
    "Check",
    "DoctorReport",
    "GitHubError",
    "Status",
    "_apply_fixes",
    "_bad_handoffs",
    "_bindings_check",
    "_build_checks",
    "_cache_check",
    "_config_check",
    "_env_checks",
    "_extension_clone_check",
    "_fix_config",
    "_fix_linear_labels",
    "_gc_check",
    "_github_checks",
    "_issues_check",
    "_linear_checks",
    "_linear_selected",
    "_managed_checks",
    "_providers_check",
    "_registry_check",
    "_runner_checks",
    "_runner_enabled_check",
    "_runner_model_check",
    "_runner_pat_check",
    "_runner_permissions_check",
    "_runner_workflow_managed_check",
    "_skills_delivery_check",
    "_strip_ungrouped_ignore_line",
    "_subagent_engine_check",
    "_untrack_materialized_plan_cache",
    "env",
    "init",
    "linear",
    "report_to_dict",
    "run_doctor",
    "workflow_checks",
]


def workflow_checks(root: Path, self_repo: bool, *, verify: bool = True) -> list[Check]:
    """The workflow-focused static layer for ``perk doctor workflow`` (Node 3.3, §8.19).

    Reuses the same builders as bare ``perk doctor`` (doctor's SSOT): the GitHub readiness +
    remote-runner prereq checks (under ``verify``) ⊕ the ``runner-workflow``
    managed-artifact-present check (always). A ``GitHubError`` while probing the runner prereqs
    degrades to a single ``info``
    ``runner-prereqs`` (mirrors ``_build_checks``).
    """
    checks: list[Check] = []
    if verify:
        checks.extend(_github_checks(root))
        try:
            checks.extend(_runner_checks(root, self_repo))
        except GitHubError as exc:
            checks.append(
                Check("runner-prereqs", "runner", "info", f"runner prereqs not checked: {exc}")
            )
    checks.append(_runner_workflow_managed_check(root, self_repo))
    return checks


def _build_checks(root: Path, self_repo: bool, *, verify: bool) -> list[Check]:
    """Assemble all groups. ``verify=False`` skips only the external shells (env/github)."""
    checks: list[Check] = []
    if verify:
        checks.extend(_env_checks())
        checks.extend(_github_checks(root))
        try:
            checks.extend(_runner_checks(root, self_repo))
        except GitHubError as exc:
            checks.append(
                Check("runner-prereqs", "runner", "info", f"runner prereqs not checked: {exc}")
            )
        # Verify-gated like env/github (network readiness); only when linear is selected.
        if _linear_selected(root):
            checks.extend(_linear_checks(root))
        # Verify-gated like env/github: it shells git + validates external-CLI outcomes.
        checks.append(_skills_delivery_check(root, self_repo))
        # Verify-gated like _skills_delivery_check / github: a network op (ls-remote).
        checks.append(_extension_clone_check(root, self_repo))
    checks.extend(_managed_checks(root, self_repo))
    checks.append(_config_check(root))
    checks.append(_registry_check())
    checks.append(_bindings_check(root, self_repo))
    checks.append(_providers_check(root))
    checks.append(_issues_check(root))
    checks.append(_subagent_engine_check(root))
    checks.append(_cache_check(root))
    checks.append(_gc_check(root))
    return checks


# --- entry point + pure serialization -------------------------------------------------------


def run_doctor(root: Path, *, fix: bool = False, verify: bool = True) -> DoctorReport:
    """Diagnose (and optionally repair) a perk-managed repo.

    ``verify=False`` skips the external shells (env/github), leaving the pure
    managed/config/registry/cache checks deterministic for unit tests. ``fix`` applies known
    repairs, then re-verifies so the exit code reflects the *post-fix* state. doctor's fixes are
    non-destructive (re-converge managed blocks; seed *missing* config only) so it never prompts.
    """
    self_repo = init.is_self_repo(root)
    checks = _build_checks(root, self_repo, verify=verify)
    fixed: list[str] = []
    fix_errors: list[str] = []
    if fix:
        fixed, fix_errors = _apply_fixes(root, self_repo, checks)
        # Materialize skills under the covers (the repair gesture) via the `skills` CLI —
        # load-bearing (#289): a failure is carried loudly on `fix_errors` (rendered by the
        # command + serialized in --json), and the post-fix re-verify below then also shows the
        # failing `skills-delivery` check, so the exit code reflects the still-broken state.
        # Gated on `verify` so the external shell runs on real `--fix` runs but not in unit
        # tests; a sync that links missing skills clears the `bindings`/`skills-delivery`
        # findings on the post-fix re-verify.
        if verify:
            sync_error = init.sync_skills(root, fixed, self_repo=self_repo)
            if sync_error is not None:
                fix_errors.append(sync_error)
            # The Linear label repair gesture (verify-gated like sync_skills — network I/O;
            # `_apply_fixes`' check-keyed loop only acts on `fail` checks, and the linear group
            # is warn-level). Lookup-first idempotency: a converged workspace reports nothing.
            linear_fixed, linear_errors = _fix_linear_labels(root)
            fixed.extend(linear_fixed)
            fix_errors.extend(linear_errors)
        if fixed or fix_errors:
            checks = _build_checks(root, self_repo, verify=verify)
    return DoctorReport(checks=checks, fixed=fixed, self_repo=self_repo, fix_errors=fix_errors)


def report_to_dict(report: DoctorReport) -> dict[str, object]:
    """Serialize for the ``--json`` supervisor surface (contracts §8.6)."""
    passed = sum(1 for c in report.checks if c.status == "ok")
    warnings = sum(1 for c in report.checks if c.status in ("warn", "info"))
    failed = sum(1 for c in report.checks if c.status == "fail")
    return {
        "success": report.error_type is None,
        "healthy": report.healthy,
        "self_repo": report.self_repo,
        "error_type": report.error_type,
        "message": report.message,
        "checks": [
            {
                "name": c.name,
                "group": c.group,
                "status": c.status,
                "message": c.message,
                "detail": c.detail,
                "remediation": c.remediation,
            }
            for c in report.checks
        ],
        "summary": {"passed": passed, "warnings": warnings, "failed": failed},
        "fixed": report.fixed,
        "fix_errors": report.fix_errors,
    }
