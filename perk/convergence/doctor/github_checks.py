"""GitHub readiness + remote-runner prereq group builders (Node 2.2 split — verbatim)."""

from pathlib import Path

from perk import github
from perk.cli.ensure import UserFacingCliError
from perk.convergence import init
from perk.convergence.doctor.data import Check
from perk.github import GitHubError
from perk.run.workflow_artifacts import RUNNER_ENABLED_VAR, RUNNER_PAT_SECRET


def _github_checks(root: Path) -> list[Check]:
    """GitHub readiness — always non-fatal (`warn`); never mutates; no silent pass."""
    try:
        auth = github.check_auth()
    except GitHubError as exc:
        return [
            Check(
                "github-auth",
                "github",
                "warn",
                "GitHub auth not verified",
                str(exc),
                "Run: gh auth login",
            )
        ]
    if not auth.ok:
        return [
            Check(
                "github-auth",
                "github",
                "warn",
                "GitHub not authenticated",
                auth.error or "",
                "Run: gh auth login",
            )
        ]
    checks = [Check("github-auth", "github", "ok", f"authenticated as {auth.user or '?'}")]
    try:
        repo = github.check_repo_access(root)
    except GitHubError as exc:
        checks.append(Check("github-repo", "github", "warn", "repo access not verified", str(exc)))
        return checks
    if repo.ok and repo.can_push:
        checks.append(Check("github-repo", "github", "ok", f"push access to {repo.repo}"))
    elif repo.ok:
        checks.append(
            Check(
                "github-repo", "github", "warn", f"no push access to {repo.repo}", repo.error or ""
            )
        )
    else:
        checks.append(Check("github-repo", "github", "warn", "no GitHub repo", repo.error or ""))
    return checks


def _runner_enabled_check(root: Path) -> tuple[Check, bool]:
    """D4.2 — always report the enabled state; ``disabled=True`` is the D4.3 early-stop."""
    enabled = github.get_repo_variable(name=RUNNER_ENABLED_VAR, repo_root=root)
    if enabled is None:
        return (
            Check(
                "runner-enabled",
                "runner",
                "info",
                f"remote runner enabled ({RUNNER_ENABLED_VAR} unset → default-on)",
            ),
            False,
        )
    if enabled == "false":
        return (
            Check(
                "runner-enabled",
                "runner",
                "info",
                f"remote runner disabled ({RUNNER_ENABLED_VAR}=false)",
            ),
            True,
        )
    return (
        Check(
            "runner-enabled",
            "runner",
            "info",
            f"remote runner enabled ({RUNNER_ENABLED_VAR}={enabled})",
        ),
        False,
    )


def _runner_pat_check(root: Path, absent_detail: str) -> Check:
    """D5.1 — the checkout/push PAT."""
    pat = github.secret_exists(name=RUNNER_PAT_SECRET, repo_root=root)
    if pat is True:
        return Check("runner-pat-secret", "runner", "ok", f"{RUNNER_PAT_SECRET} configured")
    if pat is False:
        return Check(
            "runner-pat-secret",
            "runner",
            "warn",
            f"{RUNNER_PAT_SECRET} not configured",
            absent_detail,
            f"gh secret set {RUNNER_PAT_SECRET}",
        )
    return Check(
        "runner-pat-secret",
        "runner",
        "info",
        f"could not verify {RUNNER_PAT_SECRET} (insufficient permission?)",
    )


# Model credentials the runner accepts (the workflow's "either" validate logic — §8.14).
_MODEL_SECRETS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")


def _runner_model_check(root: Path, absent_detail: str) -> Check:
    """D5.2 — the model credential (either ANTHROPIC_API_KEY or OPENAI_API_KEY)."""
    model_results = {
        name: github.secret_exists(name=name, repo_root=root) for name in _MODEL_SECRETS
    }
    present = [name for name, ok in model_results.items() if ok is True]
    if present:
        return Check(
            "runner-model-secret",
            "runner",
            "ok",
            f"model credential configured ({', '.join(present)})",
        )
    if all(ok is False for ok in model_results.values()):
        return Check(
            "runner-model-secret",
            "runner",
            "warn",
            "no model credential configured",
            absent_detail,
            "gh secret set ANTHROPIC_API_KEY   # or OPENAI_API_KEY",
        )
    return Check(
        "runner-model-secret",
        "runner",
        "info",
        "could not verify model credential",
    )


def _runner_permissions_check(root: Path) -> Check:
    """D5.3 — workflow permissions (advisory ``info`` in all non-error cases — perk pushes with
    a PAT, not github.token, so this is not blocking for the runner).
    """
    perms_detail = "advisory — perk's runner pushes with a PAT, not github.token"
    perms = github.get_workflow_permissions(repo_root=root)
    if perms is None:
        return Check(
            "runner-workflow-permissions",
            "runner",
            "info",
            "could not verify workflow permissions",
            perms_detail,
        )
    if perms.can_approve_pull_request_reviews:
        return Check(
            "runner-workflow-permissions",
            "runner",
            "info",
            "Actions may create PRs",
            perms_detail,
        )
    return Check(
        "runner-workflow-permissions",
        "runner",
        "info",
        "Actions cannot create PRs",
        perms_detail,
        "gh api --method PUT repos/{owner}/{repo}/actions/permissions/workflow "
        "-F can_approve_pull_request_reviews=true",
    )


def _runner_checks(root: Path, self_repo: bool) -> list[Check]:
    """Pre-flight health-checks for the remote-runner's prerequisites (§8.16, Node 2.4).

    Report-only and **non-fatal** (never ``fail``): present → ``ok``; actionable-absent → ``warn``;
    unverifiable → ``info``. A ``warn`` keeps exit 0 (``report.healthy`` keys off ``fail`` only),
    matching erk's always-passes posture and §8.6's GitHub-non-fatal rule. Shells ``gh``, so it
    runs only under ``verify=True``; a ``GitHubError`` is degraded by ``_build_checks`` to a single
    ``info``. Kept a free function so Node 3.3's ``perk doctor workflow`` can compose it directly.
    """
    # D6 — same check set for both repo kinds (the runner-workflow capability is scope="both");
    # only the `detail` wording adapts.
    if self_repo:
        absent_detail = "expected on perk's own repo (perk dogfoods `--remote` drives)"
    else:
        absent_detail = "required only if you use `perk … --remote` drives"

    # D4.1 — auth gate: re-probe auth; unauthed ⇒ a single info, no further gh calls.
    auth = github.check_auth()
    if not auth.ok:
        return [
            Check(
                "runner-prereqs",
                "runner",
                "info",
                "runner prereqs not checked (GitHub not authenticated)",
                auth.error or "",
            )
        ]

    # Composition: enabled → (if deliberately disabled, stop — don't nag about credentials,
    # D4.3) → pat → model → permissions.
    enabled_check, disabled = _runner_enabled_check(root)
    checks: list[Check] = [enabled_check]
    if disabled:
        return checks
    checks.append(_runner_pat_check(root, absent_detail))
    checks.append(_runner_model_check(root, absent_detail))
    checks.append(_runner_permissions_check(root))
    return checks


def _runner_workflow_managed_check(root: Path, self_repo: bool) -> Check:
    """The ``runner-workflow`` managed-artifact-present check (same shape as ``_managed_checks``).

    Locates the ``runner-workflow`` ``ManagedConvergence`` and dry-runs it: drift ⇒ ``fail`` (the
    runner cannot work without the managed workflow), converged ⇒ ``ok``. Wrapped so an
    unverifiable file (``UserFacingCliError``/``OSError``) is a loud ``fail``, never a silent pass.
    Group ``"repository"`` (mirrors ``_MANAGED_GROUP``). Kept free so ``workflow_checks`` composes
    it without duplicating the convergence wiring.
    """
    mc = next(
        (m for m in init.managed_convergences(root, self_repo) if m.name == "runner-workflow"),
        None,
    )
    if mc is None:  # defensive: the convergence list always carries it (capability scope="both")
        return Check(
            "runner-workflow",
            "repository",
            "fail",
            "runner-workflow convergence missing",
            "no runner-workflow ManagedConvergence registered",
            "Reinstall perk.",
        )
    try:
        drift = mc.converge(False)
    except (UserFacingCliError, OSError) as exc:
        detail = exc.format_message() if isinstance(exc, UserFacingCliError) else str(exc)
        return Check(
            "runner-workflow",
            "repository",
            "fail",
            "runner-workflow unverifiable",
            detail,
            "Fix the file, then re-run 'perk init'.",
        )
    if drift:
        return Check(
            "runner-workflow",
            "repository",
            "fail",
            "runner-workflow drift",
            "; ".join(drift),
            "perk doctor --fix",
        )
    return Check("runner-workflow", "repository", "ok", "runner-workflow converged")
