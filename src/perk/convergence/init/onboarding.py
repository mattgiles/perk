"""Interactive ``perk init`` onboarding gestures (contracts.md §8.5).

Every gesture lives here as one module-level function — one patch point each (the
``sync_skills`` facade discipline; ``run_init`` calls them as module globals so the conftest
stubs rebind them). All gestures are **gap-driven**: on a healthy host each returns
``([], [])`` (or ``False``) without prompting, preserving init idempotency. All prompts go to
**stderr** (``user_confirm``/``user_prompt``/``io_step``), so ``--json`` stdout stays clean —
and the command layer never passes ``interactive=True`` under ``--json`` anyway. Gestures
never raise: installs/identity/key writes ride the returned ``changes``; declines and
failures ride ``warnings`` carrying the manual remediation.
"""

import os
import re
import shutil
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from perk.backends import linear
from perk.backends.linear.client import LinearClient
from perk.convergence.env import EnvCheck
from perk.substrate import config, git, npm, proc
from perk.substrate.config import (
    ConfigError,
    load_committed_issues_backend,
    load_committed_issues_team,
    load_local_linear_api_key,
)
from perk.substrate.output import io_step, user_confirm, user_output, user_prompt

PI_NPM_SPEC = "@earendil-works/pi-coding-agent"
SKILLS_INSTALL_SCRIPT = (
    "curl -fsSL https://raw.githubusercontent.com/mattgiles/skills/main/scripts/install.sh | sh"
)
SKILLS_GO_SPEC = "github.com/mattgiles/skills/cmd/skills@latest"

# Generous: brew / the skills installer / go install download over the network.
_INSTALL_TIMEOUT = 600
# `gh auth login` waits on a human completing a browser flow.
_GH_LOGIN_TIMEOUT = 900

_MAX_KEY_ATTEMPTS = 3
# Conservative Linear-key charset — anything else counts as an invalid attempt. Doubles as the
# TOML-injection guard: no character in this set needs escaping inside a basic TOML string.
_LINEAR_KEY_RE = re.compile(r"^[A-Za-z0-9_\-.:]+$")

_LINEAR_KEY_MANUAL = (
    "export LINEAR_API_KEY or set [linear] api_key in .perk/local.toml "
    "(create a personal API key at linear.app Settings → Security & access)"
)

_GIT_IDENTITY_MANUAL = (
    'git config --global user.name "Your Name" && git config --global user.email "you@example.com"'
)


@dataclass(frozen=True)
class _Installer:
    """One offered install path: the confirm label, the change-line detail, and the runner
    (which raises ``ProcFailure``/``NpmError`` on failure)."""

    label: str
    detail: str
    run: Callable[[], None]


def _resolve_installer(name: str, *, node_ok: bool) -> _Installer | None:
    """The supported install path for a missing required tool, or ``None`` (guide-only).

    ``git``/``node`` are always guide-only (OS-owned — their remediation strings are the
    guidance); ``pi`` needs a working node (npm); ``gh`` needs brew; ``skills`` uses the
    official installer script on macOS and ``go install`` elsewhere (when go is present).
    """
    if name == "gh" and shutil.which("brew") is not None:
        return _Installer(
            label="brew install gh",
            detail="brew install gh",
            run=lambda: _run_install(["brew", "install", "gh"]),
        )
    if name == "pi" and node_ok:
        return _Installer(
            label=f"npm install -g {PI_NPM_SPEC}",
            detail=f"npm -g {PI_NPM_SPEC}",
            run=lambda: npm.install_global(PI_NPM_SPEC, timeout=_INSTALL_TIMEOUT),
        )
    if name == "skills":
        if sys.platform == "darwin":
            return _Installer(
                label="the official install script",
                detail="official install script",
                run=lambda: _run_install(["/bin/sh", "-c", SKILLS_INSTALL_SCRIPT]),
            )
        if shutil.which("go") is not None:
            return _Installer(
                label=f"go install {SKILLS_GO_SPEC}",
                detail=f"go install {SKILLS_GO_SPEC}",
                run=lambda: _run_install(["go", "install", SKILLS_GO_SPEC]),
            )
    return None


def _run_install(argv: list[str]) -> None:
    """Run one installer command captured (``ProcFailure`` on any failure)."""
    proc.run_checked(argv, timeout=_INSTALL_TIMEOUT)


def guide_missing_tools(checks: list[EnvCheck]) -> tuple[list[str], list[str]]:
    """The confirm-then-install pass over the failing **required** checks.

    Per tool with a supported installer: confirm (default yes) → run under an ``io_step``
    narration → re-probe just that tool. Success → one change line; a decline, an install
    failure, or a still-absent binary → one warning carrying the manual remediation. A missing
    ``pi`` whose ``node`` gate fails gets the "install Node first" note instead of an offer.
    Guide-only tools (``git``/``node``) produce nothing here — their remediation strings in the
    failure report are the guidance. Never raises; never prompts on a healthy host.
    """
    changes: list[str] = []
    warnings: list[str] = []
    node_ok = any(c.name == "node" and c.ok for c in checks)
    for check in checks:
        if check.ok or check.optional:
            continue
        installer = _resolve_installer(check.name, node_ok=node_ok)
        if installer is None:
            if check.name == "pi" and not node_ok:
                warnings.append(f"pi: install Node >= 22 first, then: npm install -g {PI_NPM_SPEC}")
            continue
        if not user_confirm(f"Install {check.name} via {installer.label}?", default=True):
            warnings.append(f"{check.name} not installed; install manually: {check.remediation}")
            continue
        failure: str | None = None
        with io_step(f"Installing {check.name} ({installer.label})") as step:
            try:
                installer.run()
            except (proc.ProcFailure, npm.NpmError) as exc:
                failure = str(exc)
                step.warn(f"{check.name} install failed")
            else:
                step.done(f"{check.name} installed")
        if failure is not None:
            warnings.append(
                f"{check.name} install failed ({failure}); install manually: {check.remediation}"
            )
            continue
        if shutil.which(check.name) is None:
            hint = check.remediation
            if check.name == "skills" and installer.detail.startswith("go install"):
                hint = "add $(go env GOPATH)/bin to your PATH"
            warnings.append(f"{check.name} installed but not on PATH; {hint}")
            continue
        changes.append(f"tool {check.name}: installed ({installer.detail})")
    return (changes, warnings)


def offer_gh_login() -> bool:
    """Offer to run the interactive ``gh auth login`` when gh is present but unauthenticated.

    Returns ``True`` when the login was spawned (the caller re-probes ``check_auth`` — the
    re-probe is the authority, not the login's exit code); ``False`` on a decline or a
    ``ProcFailure`` (the non-fatal unauthed report + next-steps line carry the remediation).
    """
    if not user_confirm(
        "GitHub CLI (gh) is not authenticated. Run 'gh auth login' now?", default=True
    ):
        return False
    try:
        proc.run_interactive(["gh", "auth", "login"], timeout=_GH_LOGIN_TIMEOUT)
    except proc.ProcFailure:
        return False
    return True


def ensure_git_identity(root: Path, *, interactive: bool) -> tuple[list[str], list[str]]:
    """Probe git commit identity (``user.name``/``user.email``) and offer to set it.

    Both present → ``([], [])``. An unverifiable probe (``GitError``) → one warning, never a
    raise. Missing and non-interactive → one warning carrying the manual commands (a
    deliberate new non-interactive value). Missing and interactive → prompt for each missing
    key, then one scope confirm (global default; No = this repository only) and write via
    ``git.config_set``. A blank answer or a write ``GitError`` degrades to the manual-commands
    warning.
    """
    try:
        current = {key: git.config_get(root, key) for key in ("user.name", "user.email")}
    except git.GitError as exc:
        return ([], [f"git identity unverifiable: {exc}"])
    missing = [key for key, value in current.items() if value is None]
    if not missing:
        return ([], [])
    if not interactive:
        return (
            [],
            [
                f"git identity not set ({', '.join(missing)}) — perk sessions create git "
                f"commits as you; set it: {_GIT_IDENTITY_MANUAL}"
            ],
        )
    user_output("perk sessions create git commits as you — git needs your identity.")
    prompts = {
        "user.name": "Your name (git user.name)",
        "user.email": "Your email (git user.email)",
    }
    values: dict[str, str] = {}
    for key in missing:
        answer = user_prompt(prompts[key]).strip()
        if not answer:
            return ([], [f"git identity not set; set it manually: {_GIT_IDENTITY_MANUAL}"])
        values[key] = answer
    scope: Literal["global", "local"] = (
        "global"
        if user_confirm("Set globally (~/.gitconfig)? (No = this repository only)", default=True)
        else "local"
    )
    changes: list[str] = []
    for key, value in values.items():
        try:
            git.config_set(root, key, value, scope=scope)
        except git.GitError as exc:
            return (
                changes,
                [f"git identity: {key} not set ({exc}); set it manually: {_GIT_IDENTITY_MANUAL}"],
            )
        changes.append(f"git identity: {key} set ({scope})")
    return (changes, [])


def prompt_linear_api_key(root: Path) -> tuple[list[str], list[str]]:
    """Prompt for, validate, and persist a Linear API key when the repo needs one.

    Silently a no-op unless ALL guards hold: the committed backend is ``"linear"`` (a config
    error defers to the config check), the committed ``[issues] team`` is present (the
    ``LinearReport`` error owns that gap — and validation needs the team), and no key resolves
    (env blank AND the local file reads ``None`` — a blank/ill-typed stored value reads as
    ``None`` and therefore prompts; the writer replaces that assignment). The entered key must
    match a conservative charset and pass an ``auth_ok`` readiness probe (max 3 attempts); a
    valid key is saved regardless of ``team_ok`` (a team failure is a config problem — the
    readiness probe right after reports it). ``ConfigError``/``OSError`` from the save degrade
    to one warning — an optional onboarding step must never crash init after convergence.
    """
    try:
        if load_committed_issues_backend(root) != "linear":
            return ([], [])
    except (tomllib.TOMLDecodeError, ConfigError):
        return ([], [])
    team = load_committed_issues_team(root)
    if team is None:
        return ([], [])
    if os.environ.get("LINEAR_API_KEY", "").strip():
        return ([], [])
    if load_local_linear_api_key(root) is not None:
        return ([], [])
    user_output(
        "This repo uses the Linear issue backend, but no LINEAR_API_KEY is set. Create a "
        "personal API key at linear.app → Settings → Security & access."
    )
    for _ in range(_MAX_KEY_ATTEMPTS):
        key = user_prompt("Linear API key (Enter to skip)", hide_input=True).strip()
        if not key:
            return ([], [f"Linear API key not set; {_LINEAR_KEY_MANUAL}"])
        if not _LINEAR_KEY_RE.match(key):
            user_output("That doesn't look like a Linear API key (unexpected characters).")
            continue
        readiness = linear.check_readiness(
            LinearClient(api_key=key), team_key=team, ensure_labels=False
        )
        if not readiness.auth_ok:
            user_output(f"Key rejected: {readiness.error or 'authentication failed'}")
            continue
        try:
            config.save_local_linear_api_key(root, key)
        except (ConfigError, OSError) as exc:
            return (
                [],
                [f"could not store the Linear API key ({exc}); {_LINEAR_KEY_MANUAL}"],
            )
        return ([".perk/local.toml: [linear] api_key set"], [])
    return (
        [],
        [f"Linear API key not saved after {_MAX_KEY_ATTEMPTS} attempts; {_LINEAR_KEY_MANUAL}"],
    )
