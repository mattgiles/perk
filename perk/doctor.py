"""`perk doctor` — `init`'s diagnostic twin (the verify/repair engine).

Where `init` converges a repo *forward*, `doctor` **reports** coherence and `--fix`
**repairs** drift. The managed-piece checks reuse `init`'s convergence helpers in **dry-run**
mode (`apply=False`) — so init and doctor share one desired-state SSOT (D2) — and `--fix` runs
the same helpers with `apply=True`. Everything downstream of the group *builders* is **pure**
over a `list[Check]` (report / exit-code / json / render), so that layer tests without any
monkeypatch.

Principles (T6, from `phase-0-plan.md` §T6 + the erk prior-art pass):
- **No silent pass:** a check that cannot be evaluated reports `warn`/`info` *with the reason*,
  never a silent `ok`.
- **GitHub is non-fatal** (D3): unauthed / no-access / `gh` errored ⇒ `warn`, never `fail`.
- **Report, don't refuse** (D5): a missing required tool is a failing check (exit 1); only
  `not_a_repo` blocks (exit 2).
"""

import json
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from perk import cache, capabilities, env, github, init, registry
from perk.cli.ensure import UserFacingCliError
from perk.config import CONFIG_FILENAME, LOCAL_CONFIG_FILENAME, load_config
from perk.github import GitHubError

Status = Literal["ok", "warn", "info", "fail"]

# Render groups for the managed convergences: settings under "package", the workflow-dir/cache
# layout under "state", the rest under "repository".
_MANAGED_GROUP: dict[str, str] = {"settings-wiring": "package", "workflow-dir": "state"}


@dataclass(frozen=True)
class Check:
    """A single health finding — pure data, so the report/render layer needs no monkeypatch."""

    name: str
    group: str
    status: Status
    message: str
    detail: str = ""
    remediation: str = ""


@dataclass(frozen=True)
class DoctorReport:
    """Structured result of a ``run_doctor`` (rendered human or ``--json`` by the command)."""

    checks: list[Check]
    fixed: list[str]
    self_repo: bool
    error_type: str | None = None
    message: str | None = None

    @property
    def healthy(self) -> bool:
        return self.error_type is None and not any(c.status == "fail" for c in self.checks)

    @property
    def exit_code(self) -> int:
        if self.error_type == "not_a_repo":
            return 2
        return 1 if any(c.status == "fail" for c in self.checks) else 0

    @classmethod
    def not_repo(cls) -> Self:
        return cls(
            checks=[],
            fixed=[],
            self_repo=False,
            error_type="not_a_repo",
            message="Not a git repository — run 'perk doctor' inside a git repository.",
        )


# --- group builders (impure: shells / file reads) -------------------------------------------


def _env_checks() -> list[Check]:
    checks: list[Check] = []
    for c in env.check_environment():
        checks.append(
            Check(
                name=c.name,
                group="environment",
                status="ok" if c.ok else "fail",
                message=f"{c.name} {'ok' if c.ok else 'missing/outdated'}",
                detail=c.detail,
                remediation="" if c.ok else c.remediation,
            )
        )
    return checks


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


def _managed_checks(root: Path, self_repo: bool) -> list[Check]:
    """The structural managed pieces, as converge dry-runs (`apply=False`); filtered by scope."""
    applicable = {cap.name for cap in capabilities.applicable(self_repo)}
    checks: list[Check] = []
    for mc in init.managed_convergences(root, self_repo):
        if not any(name in applicable for name in mc.covers):
            continue
        group = _MANAGED_GROUP.get(mc.name, "repository")
        try:
            drift = mc.converge(False)
        except (UserFacingCliError, OSError) as exc:
            # No silent pass: an unverifiable managed piece (malformed file, or one we cannot
            # even read) fails loudly with the reason in `detail`, never reads as a silent ok.
            detail = exc.format_message() if isinstance(exc, UserFacingCliError) else str(exc)
            checks.append(
                Check(
                    mc.name,
                    group,
                    "fail",
                    f"{mc.name} unverifiable",
                    detail,
                    "Fix the file, then re-run 'perk init'.",
                )
            )
            continue
        if drift:
            checks.append(
                Check(
                    mc.name,
                    group,
                    "fail",
                    f"{mc.name} drift",
                    "; ".join(drift),
                    "perk doctor --fix",
                )
            )
        else:
            checks.append(Check(mc.name, group, "ok", f"{mc.name} converged"))
    return checks


def _config_check(root: Path) -> Check:
    """Config is user-editable: present + parses + (defaulted) keys — never a content diff."""
    pi = root / ".pi"
    missing = [n for n in (CONFIG_FILENAME, LOCAL_CONFIG_FILENAME) if not (pi / n).is_file()]
    if missing:
        return Check(
            "config",
            "repository",
            "fail",
            "config missing",
            ", ".join(f".pi/{n}" for n in missing),
            "perk doctor --fix",
        )
    try:
        load_config(root)
    except tomllib.TOMLDecodeError as exc:
        return Check(
            "config",
            "repository",
            "fail",
            "config invalid (bad TOML)",
            str(exc),
            "Fix .pi/perk.toml by hand (perk will not overwrite your edits).",
        )
    return Check("config", "repository", "ok", "config present + valid")


def _registry_check() -> Check:
    try:
        reg = registry.load_registry()
    except registry.RegistryError as exc:
        return Check(
            "registry", "registry", "fail", "registry not loadable", str(exc), "Reinstall perk."
        )
    issues = registry.validate(reg)
    errors = [i for i in issues if i.severity is registry.Severity.ERROR]
    if errors:
        return Check(
            "registry",
            "registry",
            "fail",
            "registry invalid",
            "; ".join(str(i) for i in errors[:3]),
            "Reinstall perk.",
        )
    warnings = [i for i in issues if i.severity is registry.Severity.WARNING]
    if warnings:
        return Check(
            "registry",
            "registry",
            "warn",
            f"registry: {len(warnings)} warning(s)",
            "; ".join(str(i) for i in warnings[:3]),
        )
    return Check("registry", "registry", "ok", f"registry valid ({len(reg.stages)} stages)")


def _bad_handoffs(workflow_dir: Path) -> list[str]:
    handoff_dir = workflow_dir / "handoff"
    if not handoff_dir.is_dir():
        return []
    bad: list[str] = []
    for path in sorted(handoff_dir.glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            bad.append(path.name)
    return bad


def _cache_check(root: Path) -> Check:
    """Handoff-blob integrity. (The `.pi/workflow/` *layout* is the workflow-dir convergence.)"""
    bad = _bad_handoffs(cache.workflow_dir(root))
    if bad:
        return Check("cache-handoff", "state", "warn", "unreadable handoff blob(s)", ", ".join(bad))
    return Check("cache-handoff", "state", "ok", "handoff blobs valid")


def _build_checks(root: Path, self_repo: bool, *, verify: bool) -> list[Check]:
    """Assemble all groups. ``verify=False`` skips only the external shells (env/github)."""
    checks: list[Check] = []
    if verify:
        checks.extend(_env_checks())
        checks.extend(_github_checks(root))
    checks.extend(_managed_checks(root, self_repo))
    checks.append(_config_check(root))
    checks.append(_registry_check())
    checks.append(_cache_check(root))
    return checks


# --- fixes ----------------------------------------------------------------------------------

# The legacy/one-off migration seam (erk's `init --upgrade` repairs, perk's home for them).
# Empty in Phase 0: perk has no prior versions to migrate, and we author no fictional repairs.
_MIGRATIONS: tuple[Callable[[Path], list[str]], ...] = ()


def _fix_config(root: Path) -> list[str]:
    """Re-seed *missing* config files only (never overwrite a present/edited one)."""
    changes: list[str] = []
    init._converge_config(root, changes, force=False, interactive=False)
    return changes


def _apply_fixes(root: Path, self_repo: bool, checks: list[Check]) -> list[str]:
    fixed: list[str] = []
    mc_by_name = {mc.name: mc for mc in init.managed_convergences(root, self_repo)}
    for check in [c for c in checks if c.status == "fail"]:
        if check.name in mc_by_name:
            fixed.extend(mc_by_name[check.name].converge(True))
        elif check.name == "config":
            fixed.extend(_fix_config(root))
    for migration in _MIGRATIONS:
        fixed.extend(migration(root))
    return fixed


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
    if fix:
        fixed = _apply_fixes(root, self_repo, checks)
        if fixed:
            checks = _build_checks(root, self_repo, verify=verify)
    return DoctorReport(checks=checks, fixed=fixed, self_repo=self_repo)


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
    }
