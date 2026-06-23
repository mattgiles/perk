"""Init-time report dataclasses + the ``--json`` serialization (Node 2.2 split — verbatim)."""

from dataclasses import dataclass

from perk.backends import linear
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

    @property
    def exit_code(self) -> int:
        if self.ok:
            return 0
        if self.error_type in (
            "not_a_repo",
            "missing_tool",
            "skills_conflict",
            "skills_sync_failed",
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


def _env_to_dict(check: EnvCheck) -> dict[str, object]:
    return {
        "name": check.name,
        "ok": check.ok,
        "detail": check.detail,
        "remediation": check.remediation,
    }


def report_to_dict(report: InitReport) -> dict[str, object]:
    """Serialize an ``InitReport`` for the ``--json`` supervisor surface (cli-vs-pi §3.2)."""
    gh = report.github
    return {
        "success": report.ok,
        "mode": report.mode,
        "error_type": report.error_type,
        "message": report.message,
        "env": [_env_to_dict(c) for c in report.env],
        "github": None
        if gh is None
        else {
            "auth": {
                "ok": gh.auth.ok,
                "user": gh.auth.user,
                "scopes": list(gh.auth.scopes),
                "error": gh.auth.error,
            },
            "repo": {
                "ok": gh.repo.ok,
                "repo": gh.repo.repo,
                "can_push": gh.repo.can_push,
                "error": gh.repo.error,
            },
        },
        "linear": _linear_to_dict(report.linear),
        "capabilities": list(report.capabilities),
        "changes": report.changes,
        "handoff": report.handoff,
    }


def _linear_to_dict(report: LinearReport | None) -> dict[str, object] | None:
    """Serialize the nullable ``LinearReport`` (§8.5: a `linear` key parallel to `github`)."""
    if report is None:
        return None
    r = report.readiness
    p = report.project
    return {
        "ok": report.ok,
        "team": report.team,
        "error": report.error,
        "readiness": None
        if r is None
        else {
            "auth_ok": r.auth_ok,
            "user": r.user,
            "team_ok": r.team_ok,
            "missing_labels": list(r.missing_labels),
            "created_labels": list(r.created_labels),
            "error": r.error,
        },
        "project": None
        if p is None
        else {
            "projects_ok": p.projects_ok,
            "projects_error": p.projects_error,
            "missing_state_types": list(p.missing_state_types),
            "states_error": p.states_error,
        },
    }
