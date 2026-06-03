"""Minimal, idempotent ``perk init`` — the init spine begins here (T1).

`init` is **declarative and convergent**: it edits files toward a desired state and
is safe to re-run (re-running on a converged repo is a no-op). It owns *all* Pi
wiring from the first turn (the init-spine principle, docs/phase-0-plan.md).

T1 scope: wire ``.pi/settings.json`` (perk's own extension + the borrowed default
set), create the base ``.pi/workflow/`` dir, manage ``.gitignore``, and write a
managed ``AGENTS.md`` block. Env/GitHub verification, capability tracking, flags,
``--json``, and the post-init handoff are T5; the TOML config scaffold is T4.
"""

import json
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from perk import __version__, cache, capabilities, env, git, github
from perk.cli.ensure import UserFacingCliError
from perk.config import CONFIG_FILENAME, LOCAL_CONFIG_FILENAME
from perk.env import EnvCheck
from perk.github import AuthStatus, GitHubError, RepoAccess
from perk.output import user_confirm

NPM_PACKAGE = "@perk/pi"

# Borrowed default set (the crossover scaffolding). Independent npm: entries; Pi
# auto-installs them on the next launch. `@tombell/pi-plan` was retired in P2.T2a
# (perk now owns plan mode end-to-end via the tool-gating primitive + `/plan`).
# `pi-subagents` is the borrowed *spawned delegation engine* (P2.T6): perk takes the
# engine (the `subagent` tool + spawn/handoff machinery) and owns the workflow-specific
# agent definitions itself (in `.pi/agents/`, scaffolded by init); the engine is
# `ctx.hasUI`-clean (children run `--mode json -p`).
BORROWED_PACKAGES = [
    "npm:@juicesharp/rpiv-todo",
    "npm:@tombell/pi-diff",
    "npm:@tombell/pi-status",
    "npm:pi-subagents",
]

GITIGNORE_BEGIN = "# BEGIN perk managed"
GITIGNORE_END = "# END perk managed"
# Pi install caches + perk's transient tier-2 cache subtrees + per-user config +
# worktrees. The `.pi/workflow/` dir itself stays tracked (via .gitkeep); only the
# transient subtrees/sentinels are ignored (contracts.md §8.1).
GITIGNORE_BODY = "\n".join(
    [
        "/.pi/npm/",
        "/.pi/git/",
        f"/.pi/{LOCAL_CONFIG_FILENAME}",
        "/.worktrees/",
        "/.pi/workflow/.perk-loaded",
        "/.pi/workflow/.perk-t3.json",
        "/.pi/workflow/post-init.md",
        "/.pi/workflow/plan-ref.json",
        "/.pi/workflow/handoff/",
        "/.pi/workflow/scratch/",
        "/.pi/workflow/markers/",
    ]
)

PERK_TOML_TEMPLATE = """\
# perk project config (committed). Edit freely; per-user overrides go in
# .pi/perk.local.toml (gitignored). The schema grows as perk does.

[worktree]
# Where `perk worktree create` and cold-door stages place worktrees.
# Relative paths resolve against the repo root.
root = ".worktrees"
"""

PERK_LOCAL_TOML_TEMPLATE = """\
# perk per-user local overrides (gitignored). Mirrors .pi/perk.toml's shape; values
# here win over the committed config. Example:
#   [worktree]
#   root = "/abs/path/to/worktrees"
"""

# The post-init handoff — an agent-readable markdown on-ramp (distinct from the T3/T4
# machine run-handoff JSON). Regenerated each init; kept true to what's built.
POST_INIT_TEMPLATE = """\
# perk is initialized ({mode})

This repo follows the **perk** plan-oriented workflow on Pi. Conventions live in `AGENTS.md`
(the perk-managed block). `perk init` owns all Pi wiring and is safe to re-run.

The spine `plan -> save -> implement -> submit -> land -> learn` is being built (Phase 1).

**Cold-door launchers already exist:** `perk <stage> -- <pi args>` positions a worktree,
mints a `run_id`, and launches a primed `pi` session (e.g. `perk plan`). The in-session
stage *handlers* land in Phase 1.

**Next:** when the Phase-1 spine lands, start a plan here — this repo is the dogfood
substrate. Until then, `perk doctor` (T6) will report on this setup.
"""


@dataclass(frozen=True)
class GitHubReport:
    """The init-time GitHub readiness snapshot (verification-only)."""

    auth: AuthStatus
    repo: RepoAccess


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

    @property
    def exit_code(self) -> int:
        if self.ok:
            return 0
        if self.error_type in ("not_a_repo", "missing_tool"):
            return 2
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
        "capabilities": list(report.capabilities),
        "changes": report.changes,
        "handoff": report.handoff,
    }


AGENTS_BEGIN = "<!-- BEGIN perk managed -->"
AGENTS_END = "<!-- END perk managed -->"


def _agents_inner() -> str:
    return f"""## perk conventions (managed by `perk init` — do not edit between these markers)

This repo is wired for the **perk** plan-oriented workflow on Pi.

- **`perk init` owns all Pi wiring.** Every managed piece — `.pi/settings.json`
  package entries, `.pi/workflow/` dirs, `.gitignore` entries, this block — is
  written by `perk init`. Converge any repo by (re-)running `perk init`; it is
  idempotent (a no-op on an already-converged repo).
- **`init` converges *forward*; `doctor --fix` repairs oddities.** Do not bake
  backwards-compat migrations into `init`.
- **Headless-fail-safe.** In extensions, guard every rich-UI call with `ctx.hasUI`
  and block dangerous operations when `!ctx.hasUI`.
- **State tiers:** GitHub (canonical) / `.pi/workflow/` (cache) / session entries
  (transient). Cross-plane contracts live in `shared/`.

perk version: {__version__}"""


def is_self_repo(root: Path) -> bool:
    """True if ``root`` is perk's own source tree (``[tool.perk] self = true``)."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return False
    # No LBYL check exists for TOML validity, so parsing may raise; an unparseable
    # pyproject simply means "can't confirm self" -> consumer. A read error (OSError)
    # is genuinely exceptional and is allowed to bubble.
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return False
    return data.get("tool", {}).get("perk", {}).get("self") is True


def _npm_name(entry: str) -> str | None:
    """``npm:@scope/name@1.2.3`` -> ``@scope/name`` (identity for dedup)."""
    if not entry.startswith("npm:"):
        return None
    spec = entry[len("npm:") :]
    at = spec.rfind("@")
    return spec[:at] if at > 0 else spec  # at == 0 is a scope's leading @


def _desired_packages(self_repo: bool) -> list[str]:
    own = ".." if self_repo else f"npm:{NPM_PACKAGE}@{__version__}"
    return [own, *BORROWED_PACKAGES]


def _converge_settings(root: Path, self_repo: bool, *, apply: bool = True) -> list[str]:
    settings_path = root / ".pi" / "settings.json"

    old_text = settings_path.read_text(encoding="utf-8") if settings_path.is_file() else None
    try:
        settings = json.loads(old_text) if old_text else {}
    except json.JSONDecodeError as exc:
        raise UserFacingCliError(
            f".pi/settings.json is not valid JSON ({exc})\n"
            "Fix or remove it, then re-run 'perk init'.",
            error_type="invalid_settings",
        ) from exc
    if not isinstance(settings, dict):
        raise UserFacingCliError(
            ".pi/settings.json must contain a JSON object\n"
            "Fix or remove it, then re-run 'perk init'.",
            error_type="invalid_settings",
        )

    packages = settings.get("packages")
    if not isinstance(packages, list):
        packages = []

    have_local = {p for p in packages if isinstance(p, str) and not p.startswith("npm:")}
    have_npm = {n for n in (_npm_name(p) for p in packages if isinstance(p, str)) if n}

    added: list[str] = []
    for want in _desired_packages(self_repo):
        if want.startswith("npm:"):
            name = _npm_name(want)
            if name is None or name in have_npm:
                continue
            packages.append(want)
            have_npm.add(name)
        else:
            if want in have_local:
                continue
            packages.append(want)
            have_local.add(want)
        added.append(want)

    settings["packages"] = packages
    new_text = json.dumps(settings, indent=2) + "\n"
    if new_text == old_text:
        return []
    if apply:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(new_text, encoding="utf-8")
    return [
        f".pi/settings.json: added {', '.join(added)}" if added else ".pi/settings.json: normalized"
    ]


def _converge_workflow_dir(root: Path, *, apply: bool = True) -> list[str]:
    """Converge the full `.pi/workflow/` cache layout: the committed `.gitkeep` + the four
    (gitignored, on-demand) cache subtrees. This *is* the ``workflow-dir`` capability, so
    init creates it and ``perk doctor`` verifies the very same shape (D2)."""
    workflow = root / ".pi" / "workflow"
    gitkeep = workflow / ".gitkeep"
    need_gitkeep = not gitkeep.is_file()
    missing_subdirs = [sub for sub in cache.SUBDIRS if not (workflow / sub).is_dir()]
    if not need_gitkeep and not missing_subdirs:
        return []
    if apply:
        workflow.mkdir(parents=True, exist_ok=True)
        if need_gitkeep:
            gitkeep.write_text("", encoding="utf-8")
        for sub in missing_subdirs:
            (workflow / sub).mkdir(parents=True, exist_ok=True)
    return [".pi/workflow/: created"]


def _converge_subagent_agents(root: Path, *, apply: bool = True) -> list[str]:
    """Converge the perk-owned agent-definitions home (`.pi/agents/`) for the borrowed
    `pi-subagents` engine (P2.T6). perk *owns and commits* its agent defs, so the dir ships
    with a committed `.gitkeep`; T7 drops the first real def in it. This is substrate only —
    no perk agent definition is authored here."""
    agents = root / ".pi" / "agents"
    gitkeep = agents / ".gitkeep"
    if gitkeep.is_file():
        return []
    if apply:
        agents.mkdir(parents=True, exist_ok=True)
        gitkeep.write_text("", encoding="utf-8")
    return [".pi/agents/: created"]


def _converge_config(
    root: Path, changes: list[str], *, force: bool = False, interactive: bool = True
) -> None:
    """Scaffold the committed + local TOML config.

    Seeded once; never overwritten — *unless* ``force`` re-seeds it back to the template
    (confirmed when ``interactive``). This is the one mildly-destructive init op.
    """
    pi_dir = root / ".pi"
    pi_dir.mkdir(parents=True, exist_ok=True)
    for name, template in (
        (CONFIG_FILENAME, PERK_TOML_TEMPLATE),
        (LOCAL_CONFIG_FILENAME, PERK_LOCAL_TOML_TEMPLATE),
    ):
        path = pi_dir / name
        if not path.is_file():
            path.write_text(template, encoding="utf-8")
            changes.append(f".pi/{name}: created")
        elif force and path.read_text(encoding="utf-8") != template:
            if interactive and not user_confirm(f"Re-seed .pi/{name} to defaults?", default=False):
                continue
            path.write_text(template, encoding="utf-8")
            changes.append(f".pi/{name}: re-seeded")


def _write_post_init(root: Path, self_repo: bool) -> str:
    """Write the agent-readable post-init handoff; return its repo-relative path."""
    path = root / ".pi" / "workflow" / "post-init.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "self" if self_repo else "consumer"
    path.write_text(POST_INIT_TEMPLATE.format(mode=mode), encoding="utf-8")
    return str(path.relative_to(root))


def _apply_managed_block(
    path: Path,
    *,
    begin: str,
    end: str,
    inner: str,
    label: str,
    header_if_new: str = "",
    apply: bool = True,
) -> list[str]:
    block = f"{begin}\n{inner.rstrip(chr(10))}\n{end}\n"
    old = path.read_text(encoding="utf-8") if path.is_file() else None

    if old is not None and begin in old and end in old:
        start = old.index(begin)
        stop = old.index(end) + len(end)
        new = old[:start] + block.rstrip("\n") + old[stop:]
        verb = "updated"
    else:
        base = old if old is not None else header_if_new
        if base and not base.endswith("\n"):
            base += "\n"
        if base and not base.endswith("\n\n"):
            base += "\n"
        new = base + block
        verb = "created"

    if new == old:
        return []
    if apply:
        path.write_text(new, encoding="utf-8")
    return [f"{label}: {verb}"]


@dataclass(frozen=True)
class ManagedConvergence:
    """One structural managed piece, as a dry-run/apply convergence (the D2 SSOT).

    ``run_init`` applies these (``apply=True``); ``perk doctor`` calls them with
    ``apply=False`` to verify drift and ``apply=True`` to fix it. ``covers`` lists the
    capability names this convergence verifies (the coherence guard asserts full coverage).
    """

    name: str
    covers: tuple[str, ...]
    converge: Callable[[bool], list[str]]


def managed_convergences(root: Path, self_repo: bool) -> list[ManagedConvergence]:
    """The shared structural convergences: ``init`` applies, ``doctor`` verifies/fixes."""
    return [
        ManagedConvergence(
            "settings-wiring",
            ("perk-extension", "borrowed-packages", "settings-wiring"),
            lambda apply: _converge_settings(root, self_repo, apply=apply),
        ),
        ManagedConvergence(
            "workflow-dir",
            ("workflow-dir",),
            lambda apply: _converge_workflow_dir(root, apply=apply),
        ),
        ManagedConvergence(
            "subagent-agents",
            ("subagent-engine",),
            lambda apply: _converge_subagent_agents(root, apply=apply),
        ),
        ManagedConvergence(
            "gitignore-block",
            ("gitignore-block",),
            lambda apply: _apply_managed_block(
                root / ".gitignore",
                begin=GITIGNORE_BEGIN,
                end=GITIGNORE_END,
                inner=GITIGNORE_BODY,
                label=".gitignore",
                apply=apply,
            ),
        ),
        ManagedConvergence(
            "agents-block",
            ("agents-block",),
            lambda apply: _apply_managed_block(
                root / "AGENTS.md",
                begin=AGENTS_BEGIN,
                end=AGENTS_END,
                inner=_agents_inner(),
                label="AGENTS.md",
                header_if_new="# AGENTS\n",
                apply=apply,
            ),
        ),
    ]


def run_init(
    root: Path | None = None,
    *,
    force: bool = False,
    interactive: bool = True,
    verify: bool = True,
) -> InitReport:
    """Converge the repo and return a structured report (rendered by the command layer).

    Pipeline: verify env -> converge managed pieces -> verify GitHub (never mutate) ->
    write the post-init handoff. Environment-not-ready short-circuits before convergence.

    ``verify=False`` skips the **external** verification (repo/tooling/GitHub shells) and
    runs pure convergence — the seam unit tests use so they don't depend on an installed,
    authenticated toolchain. The CLI always verifies (default).
    """
    root = (root or Path.cwd()).resolve()
    checks: list[EnvCheck] = []
    if verify:
        checks = env.check_environment()
        if git.repo_root(root) is None:
            return InitReport.env_failure(
                "not_a_repo",
                "Not a git repository — run 'perk init' inside a git repository.",
                checks,
            )
        if not env.required_tools_ok(checks):
            missing = ", ".join(c.name for c in checks if not c.ok)
            return InitReport.env_failure(
                "missing_tool", f"Missing or outdated required tool(s): {missing}.", checks
            )

    self_repo = is_self_repo(root)
    changes: list[str] = []
    for mc in managed_convergences(root, self_repo):
        changes.extend(mc.converge(True))
    _converge_config(root, changes, force=force, interactive=interactive)

    github_report: GitHubReport | None = None
    if verify:
        # GitHub readiness is non-fatal (D3): a flaky/slow/broken `gh` (timeout or
        # unparseable output -> GitHubError) must not crash init — file convergence has
        # already succeeded. Degrade to an unauthed report and continue.
        try:
            auth = github.check_auth()
            repo = github.check_repo_access(root) if auth.ok else RepoAccess.skipped()
        except GitHubError as exc:
            auth = AuthStatus(ok=False, user=None, scopes=(), error=str(exc))
            repo = RepoAccess.skipped()
        github_report = GitHubReport(auth=auth, repo=repo)
    handoff = _write_post_init(root, self_repo)
    managed = tuple(cap.name for cap in capabilities.applicable(self_repo))

    return InitReport(
        ok=True,
        mode="self" if self_repo else "consumer",
        env=checks,
        changes=changes,
        github=github_report,
        handoff=handoff,
        capabilities=managed,
    )
