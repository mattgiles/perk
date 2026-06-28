"""Golden byte-identity tests for the nine in-scope ``--json`` OUTPUT envelopes.

Each test builds a fully-populated (or nullable-arm) domain result with the dataclass
constructor (trusted typed values — no Pydantic coercion), calls the envelope's ``--json``
builder, and asserts the result equals a committed snapshot. The snapshots were generated
from the *pre-swap* hand-rolled builders, so a green run after the swap to ``OutputModel``s
proves the serialized keys stayed byte-identical.

Regen all snapshots with ``PERK_UPDATE_GOLDEN=1 uv run pytest tests/test_json_goldens.py``.
"""

from tests._golden import assert_golden

# --- init report --------------------------------------------------------------------------


def _init_report_full():
    from perk.backends import linear
    from perk.convergence.env import EnvCheck
    from perk.convergence.init.report import GitHubReport, InitReport, LinearReport
    from perk.github import AuthStatus, RepoAccess

    return InitReport(
        ok=True,
        mode="github",
        env=[
            EnvCheck(name="node", ok=True, detail="v22.19.0", remediation=""),
            EnvCheck(name="gh", ok=False, detail="missing", remediation="brew install gh"),
        ],
        changes=["wrote .perk/config.toml", "wrote .gitignore"],
        github=GitHubReport(
            auth=AuthStatus(ok=True, user="mat", scopes=("repo", "read:org"), error=None),
            repo=RepoAccess(ok=True, repo="owner/repo", can_push=True, error=None),
        ),
        handoff=".perk/workflow/post-init.md",
        capabilities=("settings-wiring", "workflow-dir"),
        error_type=None,
        message=None,
        linear=LinearReport(
            readiness=linear.LinearReadiness(
                auth_ok=True,
                user="Mat",
                team_ok=True,
                missing_labels=("perk:learn",),
                created_labels=("perk:plan",),
                error=None,
            ),
            team="ENG",
            error=None,
            project=linear.LinearProjectReadiness(
                projects_ok=True,
                projects_error=None,
                missing_state_types=("canceled",),
                states_error=None,
            ),
        ),
        warnings=["untracked: docs/foo.md"],
    )


def _init_report_minimal():
    from perk.convergence.env import EnvCheck
    from perk.convergence.init.report import InitReport

    return InitReport(
        ok=False,
        mode="unknown",
        env=[EnvCheck(name="git", ok=False, detail="not a repo", remediation="git init")],
        changes=[],
        github=None,
        handoff=None,
        capabilities=(),
        error_type="not_a_repo",
        message="Not a git repository",
        linear=None,
        warnings=[],
    )


def test_golden_init_report_full() -> None:
    from perk.convergence.init.report import report_to_dict

    assert_golden("init_report", report_to_dict(_init_report_full()))


def test_golden_init_report_minimal() -> None:
    from perk.convergence.init.report import report_to_dict

    assert_golden("init_report_minimal", report_to_dict(_init_report_minimal()))


# --- doctor report ------------------------------------------------------------------------


def _doctor_report_full():
    from perk.convergence.doctor.data import Check, DoctorReport

    return DoctorReport(
        checks=[
            Check("settings-wiring", "package", "ok", "wired"),
            Check("github", "github", "warn", "unauthed", detail="gh not logged in"),
            Check("node", "env", "info", "optional", remediation="install node"),
            Check("registry", "repository", "fail", "drift", detail="d", remediation="r"),
        ],
        fixed=["re-converged settings-wiring"],
        self_repo=True,
        error_type=None,
        message=None,
        fix_errors=["skills sync failed"],
    )


def test_golden_doctor_report() -> None:
    from perk.convergence.doctor import report_to_dict

    assert_golden("doctor_report", report_to_dict(_doctor_report_full()))
