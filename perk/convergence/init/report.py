"""Init-time report dataclasses + the ``--json`` serialization."""

from dataclasses import dataclass, field

from perk.backends import linear
from perk.boundary import OutputModel
from perk.convergence.env import EnvCheck
from perk.github import AuthStatus, RepoAccess


@dataclass(frozen=True)
class GitHubReport:
    """The init-time GitHub readiness snapshot (verification-only)."""

    auth: AuthStatus
    repo: RepoAccess


@dataclass(frozen=True)
class LinearReport:
    """The init-time Linear readiness snapshot (verify-gated; only when linear is selected).

    Wraps a ``LinearReadiness`` probe result, or carries the degrade ``error`` when the probe
    could not even be attempted (missing ``LINEAR_API_KEY`` / missing ``[issues] team``) —
    non-fatal either way (the GitHub D3 discipline: file convergence already succeeded).
    """

    readiness: linear.LinearReadiness | None
    team: str | None = None
    error: str | None = None
    project: linear.LinearProjectReadiness | None = None

    @property
    def ok(self) -> bool:
        # Project readiness is non-fatal — it deliberately does NOT participate here (file
        # convergence already succeeded; mirrors the issue-tier non-fatal posture).
        r = self.readiness
        return self.error is None and r is not None and r.auth_ok and r.team_ok and r.error is None


@dataclass(frozen=True)
class InitReport:
    """Structured result of a ``run_init`` (rendered human or ``--json`` by the command)."""

    ok: bool
    mode: str
    env: list[EnvCheck]
    changes: list[str]
    github: GitHubReport | None
    handoff: str | None
    capabilities: tuple[str, ...] = ()
    error_type: str | None = None
    message: str | None = None
    linear: LinearReport | None = None
    # Non-fatal clear-report lines (e.g. repo-authored-skills structural errors / untracked
    # warnings). Kept separate from `changes` so `changes` stays a pure delta list (the
    # idempotency invariant: a converged re-run reports no changes).
    warnings: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if self.ok:
            return 0
        if self.error_type in (
            "not_a_repo",
            "missing_tool",
            "skills_conflict",
            "skills_sync_failed",
            "legacy_config",
        ):
            return 2  # environment-not-ready (§3.2 supervisor taxonomy)
        return 1

    @classmethod
    def env_failure(cls, error_type: str, message: str, checks: list[EnvCheck]) -> "InitReport":
        return cls(
            ok=False,
            mode="unknown",
            env=checks,
            changes=[],
            github=None,
            handoff=None,
            error_type=error_type,
            message=message,
        )


# --- the ``--json`` serialization boundary (OutputModel edge of InitReport) ----------------
#
# Field declaration order is load-bearing on every model below: ``model_dump(mode="json")``
# emits in declaration order, so the order must stay byte-stable to avoid churning the
# ``--json`` supervisor surface (§3.2 / §8.5).


class EnvCheckOut(OutputModel):
    """The serialization boundary of one :class:`EnvCheck`. Field order is load-bearing."""

    name: str
    ok: bool
    detail: str
    remediation: str

    @classmethod
    def from_domain(cls, check: EnvCheck) -> "EnvCheckOut":
        return cls(name=check.name, ok=check.ok, detail=check.detail, remediation=check.remediation)


class AuthOut(OutputModel):
    """The serialization boundary of the picked :class:`AuthStatus` subset (order load-bearing)."""

    ok: bool
    user: str | None
    scopes: tuple[str, ...]
    error: str | None

    @classmethod
    def from_domain(cls, auth: AuthStatus) -> "AuthOut":
        return cls(ok=auth.ok, user=auth.user, scopes=auth.scopes, error=auth.error)


class RepoOut(OutputModel):
    """The serialization boundary of the picked :class:`RepoAccess` subset (order load-bearing)."""

    ok: bool
    repo: str | None
    can_push: bool
    error: str | None

    @classmethod
    def from_domain(cls, repo: RepoAccess) -> "RepoOut":
        return cls(ok=repo.ok, repo=repo.repo, can_push=repo.can_push, error=repo.error)


class GitHubReportOut(OutputModel):
    """The serialization boundary of :class:`GitHubReport`. Field order is load-bearing."""

    auth: AuthOut
    repo: RepoOut

    @classmethod
    def from_domain(cls, report: GitHubReport) -> "GitHubReportOut":
        return cls(auth=AuthOut.from_domain(report.auth), repo=RepoOut.from_domain(report.repo))


class LinearReadinessOut(OutputModel):
    """The serialization boundary of :class:`linear.LinearReadiness`. Order is load-bearing."""

    auth_ok: bool
    user: str | None
    team_ok: bool
    missing_labels: tuple[str, ...]
    created_labels: tuple[str, ...]
    error: str | None

    @classmethod
    def from_domain(cls, r: linear.LinearReadiness) -> "LinearReadinessOut":
        return cls(
            auth_ok=r.auth_ok,
            user=r.user,
            team_ok=r.team_ok,
            missing_labels=r.missing_labels,
            created_labels=r.created_labels,
            error=r.error,
        )


class LinearProjectOut(OutputModel):
    """Serialization boundary of :class:`linear.LinearProjectReadiness` (order load-bearing)."""

    projects_ok: bool
    projects_error: str | None
    missing_state_types: tuple[str, ...]
    states_error: str | None

    @classmethod
    def from_domain(cls, p: linear.LinearProjectReadiness) -> "LinearProjectOut":
        return cls(
            projects_ok=p.projects_ok,
            projects_error=p.projects_error,
            missing_state_types=p.missing_state_types,
            states_error=p.states_error,
        )


class LinearReportOut(OutputModel):
    """The serialization boundary of the nullable :class:`LinearReport`. Order is load-bearing."""

    ok: bool
    team: str | None
    error: str | None
    readiness: LinearReadinessOut | None
    project: LinearProjectOut | None

    @classmethod
    def from_domain(cls, report: LinearReport) -> "LinearReportOut":
        return cls(
            ok=report.ok,
            team=report.team,
            error=report.error,
            readiness=None
            if report.readiness is None
            else LinearReadinessOut.from_domain(report.readiness),
            project=None
            if report.project is None
            else LinearProjectOut.from_domain(report.project),
        )


class InitReportOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`InitReport`. Field order is load-bearing."""

    success: bool
    mode: str
    error_type: str | None
    message: str | None
    env: tuple[EnvCheckOut, ...]
    github: GitHubReportOut | None
    linear: LinearReportOut | None
    capabilities: tuple[str, ...]
    changes: tuple[str, ...]
    warnings: tuple[str, ...]
    handoff: str | None

    @classmethod
    def from_domain(cls, report: InitReport) -> "InitReportOut":
        return cls(
            success=report.ok,
            mode=report.mode,
            error_type=report.error_type,
            message=report.message,
            env=tuple(EnvCheckOut.from_domain(c) for c in report.env),
            github=None if report.github is None else GitHubReportOut.from_domain(report.github),
            linear=None if report.linear is None else LinearReportOut.from_domain(report.linear),
            capabilities=report.capabilities,
            changes=tuple(report.changes),
            warnings=tuple(report.warnings),
            handoff=report.handoff,
        )


def report_to_dict(report: InitReport) -> dict[str, object]:
    """Serialize an ``InitReport`` for the ``--json`` supervisor surface (cli-vs-pi §3.2)."""
    return InitReportOut.from_domain(report).model_dump(mode="json")
