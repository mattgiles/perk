"""`perk doctor` — `init`'s diagnostic twin (the verify/repair engine).

Where `init` converges a repo *forward*, `doctor` **reports** coherence and `--fix`
**repairs** drift. The managed-piece checks reuse `init`'s convergence helpers in **dry-run**
mode (`apply=False`) — so init and doctor share one desired-state SSOT (D2) — and `--fix` runs
the same helpers with `apply=True`. Everything downstream of the group *builders* is **pure**
over a `list[Check]` (report / exit-code / json / render), so that layer tests without any
monkeypatch.

Principles:
- **No silent pass:** a check that cannot be evaluated reports `warn`/`info` *with the reason*,
  never a silent `ok`.
- **GitHub is non-fatal**: unauthed / no-access / `gh` errored ⇒ `warn`, never `fail`.
- **Report, don't refuse**: a missing required tool is a failing check (exit 1); only
  `not_a_repo` blocks (exit 2).

**Package layout.** This ``__init__`` keeps the orchestration (``_build_checks``,
``workflow_checks``, ``run_doctor``, ``report_to_dict``) and re-exports every submodule symbol
behind a sorted ``__all__``, preserving the ``doctor.X`` attribute-access path.
The orchestrators reference the group *builders* as bare facade
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
from perk.boundary import OutputModel
from perk.convergence import env, init, managed_state
from perk.convergence.doctor.checks import (
    _artifact_health_check,
    _bad_handoffs,
    _bindings_check,
    _cache_check,
    _cli_version_check,
    _config_check,
    _env_checks,
    _extension_install_check,
    _gc_check,
    _issues_check,
    _legacy_workflow_check,
    _managed_checks,
    _models_check,
    _providers_check,
    _registry_check,
    _repo_skills_check,
    _review_cli_check,
    _skills_delivery_check,
    _stage_models_check,
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
    _untrack_subagent_artifacts,
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
from perk.convergence.managed_state import ArtifactHealth, HealthStatus
from perk.github import GitHubError

__all__ = [
    "_LINEAR_KEY_REMEDIATION",
    "_MANAGED_GROUP",
    "_MIGRATIONS",
    "_MODEL_SECRETS",
    "ArtifactHealth",
    "ArtifactHealthOut",
    "Check",
    "CheckOut",
    "DoctorReport",
    "DoctorReportOut",
    "GitHubError",
    "HealthStatus",
    "Status",
    "SummaryOut",
    "_apply_fixes",
    "_artifact_health_check",
    "_bad_handoffs",
    "_bindings_check",
    "_build_checks",
    "_cache_check",
    "_cli_version_check",
    "_config_check",
    "_env_checks",
    "_extension_install_check",
    "_fix_config",
    "_fix_linear_labels",
    "_gc_check",
    "_github_checks",
    "_issues_check",
    "_legacy_workflow_check",
    "_linear_checks",
    "_linear_selected",
    "_managed_checks",
    "_models_check",
    "_providers_check",
    "_registry_check",
    "_repo_skills_check",
    "_review_cli_check",
    "_runner_checks",
    "_runner_enabled_check",
    "_runner_model_check",
    "_runner_pat_check",
    "_runner_permissions_check",
    "_runner_workflow_managed_check",
    "_skills_delivery_check",
    "_stage_models_check",
    "_strip_ungrouped_ignore_line",
    "_subagent_engine_check",
    "_untrack_materialized_plan_cache",
    "_untrack_subagent_artifacts",
    "env",
    "init",
    "linear",
    "report_to_dict",
    "run_doctor",
    "workflow_checks",
]


def workflow_checks(root: Path, self_repo: bool, *, verify: bool = True) -> list[Check]:
    """The workflow-focused static layer for ``perk doctor workflow`` (§8.19).

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
        # Verify-gated beside skills-delivery: the repo-authored-skills fragment health (a
        # GitHub read renders a valid fragment, so it cannot run as an offline managed check).
        checks.append(_repo_skills_check(root))
        # Verify-gated like _skills_delivery_check / github: shells `npm` (a network op).
        checks.append(_extension_install_check(root, self_repo))
        # Verify-gated: the hunk-CLI PATH probe depends on the host machine (keeps
        # verify=False unit-test check lists byte-stable).
        checks.append(_review_cli_check(root))
    checks.extend(_managed_checks(root, self_repo))
    # Offline (one file read) and report-only, so NOT verify-gated; appended right after the
    # managed checks so the two version-pin findings render adjacently in the `package` group.
    checks.append(_cli_version_check(root))
    checks.append(_config_check(root))
    checks.append(_registry_check())
    checks.append(_bindings_check(root))
    checks.append(_providers_check(root))
    checks.append(_issues_check(root))
    # Offline (reads config + the bundled registry), so NOT gated behind `if verify:`. Returns
    # None — and contributes nothing — when no per-stage models are configured (the common case).
    if (sm_check := _stage_models_check(root)) is not None:
        checks.append(sm_check)
    # Same offline/quiet-when-unconfigured posture as _stage_models_check: the model-string
    # thinking-suffix lens over [models]/[models.subagents]/[models.stages.<id>].
    if (models_check := _models_check(root)) is not None:
        checks.append(models_check)
    checks.append(_subagent_engine_check(root))
    checks.append(_cache_check(root))
    checks.append(_gc_check(root))
    checks.append(_legacy_workflow_check(root))
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
    artifact_rows, health = _artifact_health_check(root, self_repo)
    checks.append(health)
    fixed: list[str] = []
    fix_errors: list[str] = []
    if fix:
        fixed, fix_errors = _apply_fixes(root, self_repo, checks)
        # Materialize skills under the covers (the repair gesture) via the `skills` CLI —
        # load-bearing: a failure is carried loudly on `fix_errors` (rendered by the
        # command + serialized in --json), and the post-fix re-verify below then also shows the
        # failing `skills-delivery` check, so the exit code reflects the still-broken state.
        # Gated on `verify` so the external shell runs on real `--fix` runs but not in unit
        # tests; a sync that links missing skills clears the `bindings`/`skills-delivery`
        # findings on the post-fix re-verify.
        if verify:
            # Re-converge the repo-authored-skills fragment BEFORE the sync (so the skills CLI
            # sees the declared `.perk/skills/` source), mirroring init's order. Structural errors
            # ride loudly on `fix_errors`; the post-fix re-verify re-runs `_repo_skills_check` so
            # the exit code reflects the post-fix state.
            conv = init.converge_repo_skills_manifest(root, apply=True)
            fixed.extend(conv.changes)
            fix_errors.extend(conv.manifest.errors)
            sync_error = init.sync_skills(
                root,
                fixed,
                repo_skill_names=tuple(s.name for s in conv.manifest.skills),
            )
            if sync_error is not None:
                fix_errors.append(sync_error)
            # The Linear label repair gesture (verify-gated like sync_skills — network I/O;
            # `_apply_fixes`' check-keyed loop only acts on `fail` checks, and the linear group
            # is warn-level). Lookup-first idempotency: a converged workspace reports nothing.
            linear_fixed, linear_errors = _fix_linear_labels(root)
            fixed.extend(linear_fixed)
            fix_errors.extend(linear_errors)
            # The review-seam hunk-CLI repair gesture (verify-gated network op). An explicit
            # `--fix` failure is loud — the warning rides on `fix_errors` (the linear-labels
            # precedent). Called through the `init.` module attribute so the conftest stub
            # covers doctor too.
            review_fixed, review_errors = init.ensure_review_cli(root)
            fixed.extend(review_fixed)
            fix_errors.extend(review_errors)
        # Record `.perk/managed-state.toml` AFTER the repairs (repair through convergence first,
        # then record). Content-gated — a converged-and-recorded repo appends nothing, keeping
        # `--fix` idempotent (`fixed == []` on a second run). Not verify-gated (pure filesystem).
        try:
            state_change = managed_state.record_managed_state(root, self_repo=self_repo)
        except OSError as exc:
            fix_errors.append(f".perk/managed-state.toml: write failed: {exc}")
        else:
            if state_change is not None:
                fixed.append(state_change)
        if fixed or fix_errors:
            checks = _build_checks(root, self_repo, verify=verify)
            artifact_rows, health = _artifact_health_check(root, self_repo)
            checks.append(health)
    return DoctorReport(
        checks=checks,
        fixed=fixed,
        self_repo=self_repo,
        fix_errors=fix_errors,
        artifact_health=artifact_rows,
    )


# --- the ``--json`` serialization boundary (OutputModel edge of DoctorReport) --------------
#
# Field declaration order is load-bearing on every model below: ``model_dump(mode="json")``
# emits in declaration order, so the order must stay byte-stable to avoid churning the
# ``--json`` supervisor surface (contracts §8.6).


class CheckOut(OutputModel):
    """The serialization boundary of one :class:`Check` (field order load-bearing)."""

    name: str
    group: str
    status: Status
    message: str
    detail: str
    remediation: str

    @classmethod
    def from_domain(cls, c: Check) -> "CheckOut":
        return cls(
            name=c.name,
            group=c.group,
            status=c.status,
            message=c.message,
            detail=c.detail,
            remediation=c.remediation,
        )


class SummaryOut(OutputModel):
    """The computed status tally (field order load-bearing)."""

    passed: int
    warnings: int
    failed: int


class ArtifactHealthOut(OutputModel):
    """The serialization boundary of one :class:`ArtifactHealth` row (field order load-bearing)."""

    key: str
    path: str
    kind: str
    status: HealthStatus
    recorded_version: str | None
    recorded_hash: str | None
    desired_hash: str
    observed_hash: str | None

    @classmethod
    def from_domain(cls, row: ArtifactHealth) -> "ArtifactHealthOut":
        return cls(
            key=row.key,
            path=row.path,
            kind=row.kind,
            status=row.status,
            recorded_version=row.recorded_version,
            recorded_hash=row.recorded_hash,
            desired_hash=row.desired_hash,
            observed_hash=row.observed_hash,
        )


class DoctorReportOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`DoctorReport` (field order load-bearing)."""

    success: bool
    healthy: bool
    self_repo: bool
    error_type: str | None
    message: str | None
    checks: tuple[CheckOut, ...]
    summary: SummaryOut
    fixed: tuple[str, ...]
    fix_errors: tuple[str, ...]
    # Declared after `fix_errors` (appended last) so every pre-existing key stays byte-stable.
    artifact_health: tuple[ArtifactHealthOut, ...]

    @classmethod
    def from_domain(cls, report: DoctorReport) -> "DoctorReportOut":
        return cls(
            success=report.error_type is None,
            healthy=report.healthy,
            self_repo=report.self_repo,
            error_type=report.error_type,
            message=report.message,
            checks=tuple(CheckOut.from_domain(c) for c in report.checks),
            summary=SummaryOut(
                passed=sum(1 for c in report.checks if c.status == "ok"),
                warnings=sum(1 for c in report.checks if c.status in ("warn", "info")),
                failed=sum(1 for c in report.checks if c.status == "fail"),
            ),
            fixed=tuple(report.fixed),
            fix_errors=tuple(report.fix_errors),
            artifact_health=tuple(
                ArtifactHealthOut.from_domain(row) for row in report.artifact_health
            ),
        )


def report_to_dict(report: DoctorReport) -> dict[str, object]:
    """Serialize for the ``--json`` supervisor surface (contracts §8.6)."""
    return DoctorReportOut.from_domain(report).model_dump(mode="json")
