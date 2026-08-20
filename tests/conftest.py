import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import click
import pytest

from perk import __version__
from perk import github as gh_mod
from perk.convergence import env as env_mod
from perk.convergence import init as init_mod
from perk.convergence.init import extension_install as _ext_install
from perk.substrate import git as git_mod

_SOURCE_ROOTS = ("src", "extension", "tests", "shared", "docs", "skills", "agents", "prompts")
_SOURCE_SUFFIXES = frozenset({".py", ".ts", ".md", ".yaml", ".yml", ".json", ".jinja"})
_XDIST_AUTO_WORKER_CAP = 6

# The perk-dev prose suites (the Prose Review Workbench + the living prose map) are
# opt-in: they are heavy (Vite builds, real uvicorn servers, the Node selector helper)
# and guard a personal maintainer tool, so default runs and CI never collect them.
# Run them explicitly with `just prose-review-test` (which sets this variable).
if os.environ.get("PERK_PROSE_REVIEW_TESTS") != "1":
    collect_ignore_glob = ["test_prose_review_*.py", "test_prose_map*.py"]


@dataclass
class LaunchExecRecorder:
    """Calls made at the irreversible launch boundary."""

    agent_dir: Path
    chdirs: list[Path] = field(default_factory=list)
    calls: list[tuple[str, tuple[str, ...], dict[str, str]]] = field(default_factory=list)


type GitRepoFactory = Callable[[Path], Path]
type RemoteGitRepo = tuple[Path, Path, Callable[[], str]]
type RemoteGitRepoFactory = Callable[[Path], RemoteGitRepo]


@dataclass(frozen=True)
class _RemoteGitTemplate:
    root: Path
    advanced_sha: str


def pytest_xdist_auto_num_workers(config: pytest.Config) -> int:
    """Bound auto parallelism where Git-heavy subprocess contention outweighs more workers."""
    del config
    return min(os.process_cpu_count() or 1, _XDIST_AUTO_WORKER_CAP)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout


def _copy_template(source: Path, destination: Path) -> Path:
    """Copy an immutable repo template without sharing mutable files or following symlinks.

    Git lock files are excluded: a git command in a session-scoped template can spawn detached
    background maintenance whose transient `.git/objects/maintenance.lock` vanishes between
    copytree's scandir and the copy (`shutil.Error` — an observed CI flake); locks are runtime
    state that must never ride into a fresh fixture repo anyway.
    """
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        symlinks=True,
        ignore=shutil.ignore_patterns("*.lock"),
    )
    return destination


@pytest.fixture(autouse=True)
def _reset_launch_banner_guard():
    """Reset the process-global once-per-process banner guard before every test so the latched
    flag never leaks across tests (an emitter in one test must not no-op a later test)."""
    # Imported inside the fixture (not at module top) so resetting the private guard stays a
    # narrow test concern and conftest's import surface isn't widened for every collection.
    import perk.run.launch.materialize as _m

    _m._LAUNCH_BANNER_EMITTED = False
    yield


@pytest.fixture(autouse=True)
def _no_interactive_prompts(monkeypatch):
    """Fail fast with a clear message when a test reaches a real interactive prompt.

    Prompt reachability is host-dependent (e.g. init's guided installer fires only on a
    runner missing a tool), and the raw failure is pytest's cryptic stdin-capture OSError —
    or, under CliRunner, silent input consumption. Tests exercising prompts stub a seam
    (onboarding.user_confirm, click.confirm, ...), which overrides this guard.
    """

    def _refuse(*args, **kwargs):
        raise AssertionError(
            "interactive prompt reached in a test — stub the prompt seam "
            "(e.g. onboarding.user_confirm / click.confirm) or run the code path "
            "non-interactively (interactive=False)"
        )

    monkeypatch.setattr(click, "confirm", _refuse)
    monkeypatch.setattr(click, "prompt", _refuse)


@pytest.fixture
def stub_launch_extension_warm(monkeypatch):
    """Keep ordinary launch tests offline while dedicated warm tests install recorders."""
    from perk.run import launch

    monkeypatch.setattr(
        launch.init,
        "ensure_extension_install_present",
        lambda repo_root, *, self_repo: None,
    )


@pytest.fixture
def launch_context_factory(tmp_path):
    """Build a resolved launch context for direct phase tests."""
    from perk import plan
    from perk.run import launch
    from perk.run.launch import ResolvedWorktree
    from perk.run.launch.worktree import Disposition
    from perk.substrate.config import Config
    from perk.substrate.registry import Stage

    def build(
        *,
        stage: Stage,
        repo_root: Path | None = None,
        worktree: Path | None = None,
        config: Config | None = None,
        plan_ref: plan.PlanRef | None = None,
        disposition: "Disposition" = "reuse-local",
        base: str | None = None,
        rid: str = "01TESTLAUNCH",
        argv: tuple[str, ...] = ("pi",),
    ) -> launch._LaunchContext:
        root = repo_root if repo_root is not None else tmp_path
        resolved_path = worktree if worktree is not None else tmp_path / "worktree"
        resolved_path.mkdir(parents=True, exist_ok=True)
        resolved = ResolvedWorktree(
            path=resolved_path,
            plan_ref=plan_ref,
            disposition=disposition,
            base=base,
        )
        return launch._LaunchContext(
            repo_root=root,
            config=config if config is not None else Config(worktree_root=tmp_path / ".worktrees"),
            stage=stage,
            resolved=resolved,
            rid=rid,
            argv=argv,
        )

    return build


@pytest.fixture
def launch_exec_recorder(tmp_path, monkeypatch) -> LaunchExecRecorder:
    """Capture chdir/exec calls and isolate pi's global agent directory."""
    from perk.run import launch

    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    recorder = LaunchExecRecorder(agent_dir=agent_dir)
    monkeypatch.setattr(launch, "_pi_agent_dir", lambda: agent_dir)
    monkeypatch.setattr(launch.os, "chdir", lambda path: recorder.chdirs.append(Path(path)))
    monkeypatch.setattr(
        launch.os,
        "execvpe",
        lambda program, argv, env: recorder.calls.append((program, tuple(argv), dict(env))),
    )
    return recorder


@pytest.fixture(scope="session")
def source_corpus() -> dict[Path, str]:
    """Read relevant tracked and nonignored-untracked text files once on one xdist worker."""
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *_SOURCE_ROOTS,
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    corpus: dict[Path, str] = {}
    for item in result.stdout.split("\0"):
        if not item:
            continue
        relative = Path(item)
        path = repo_root / relative
        if path.is_file() and path.suffix in _SOURCE_SUFFIXES:
            corpus[relative] = path.read_text(encoding="utf-8", errors="ignore")
    return corpus


@pytest.fixture
def stub_env(monkeypatch):
    """Make `perk init`'s external verification pass without a real/authed toolchain.

    init.py references `env`/`github` as modules, so patching the module attributes is seen
    at call time. GitHub is stubbed *unauthed* (non-fatal) to keep the path realistic.
    """
    monkeypatch.setattr(
        env_mod,
        "check_environment",
        lambda: [
            env_mod.EnvCheck("git", True, "ok", ""),
            env_mod.EnvCheck("gh", True, "ok", ""),
            env_mod.EnvCheck("node", True, "v22.19.0", ""),
            env_mod.EnvCheck("pi", True, "ok", ""),
        ],
    )
    monkeypatch.setattr(
        gh_mod, "check_auth", lambda: gh_mod.AuthStatus(False, None, (), "stub: not authed")
    )
    monkeypatch.setattr(gh_mod, "check_repo_access", lambda root: gh_mod.RepoAccess.skipped())
    # The `skills init`/`skills sync` shells are external like env/github; stub them so verified
    # inits in tests never clone over the network.
    monkeypatch.setattr(init_mod, "sync_skills", lambda root, changes, **kw: None)
    # The review-seam hunk-CLI gesture probes PATH + shells `npm install -g` (verify-gated);
    # stub it so verified inits/doctor-fixes in tests stay offline and host-independent.
    monkeypatch.setattr(init_mod, "ensure_review_cli", lambda root: ([], []))
    # The interactive onboarding gestures (guided installs / gh login / git identity / the
    # Linear key prompt) prompt on stderr and shell externals; stub them so verified inits
    # (default interactive=True) stay prompt-free and host-independent. Defensive for
    # guide_missing_tools — check_environment is stubbed all-ok above, so it would not fire.
    monkeypatch.setattr(init_mod, "guide_missing_tools", lambda checks: ([], []))
    monkeypatch.setattr(init_mod, "offer_gh_login", lambda: False)
    monkeypatch.setattr(init_mod, "ensure_git_identity", lambda root, *, interactive: ([], []))
    monkeypatch.setattr(init_mod, "prompt_linear_api_key", lambda root: ([], []))
    # Doctor's `git-identity` check calls `git.config_get` directly (bypassing the gesture
    # stub); return a deterministic healthy identity so `run_doctor(..., verify=True)` tests
    # never read the developer/CI user's real git config. Dedicated tests override this.
    monkeypatch.setattr(
        git_mod,
        "config_get",
        lambda root, key: {"user.name": "perk tests", "user.email": "t@example.com"}.get(key),
    )

    # The @mgiles/perk npm-install primitive shells `npm install` over the network (init/doctor now
    # materialize the install); stub it so verified inits never reach the network. The fake lands
    # the pinned package.json so a second verified init sees the install present at __version__ →
    # status `present` → a no-op (idempotency preserved). Dedicated tests override it.
    def _fake_install(root):
        pkg = _ext_install.consumer_perk_package_dir(root)
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "package.json").write_text(json.dumps({"version": __version__}), encoding="utf-8")

    monkeypatch.setattr(_ext_install, "_install_perk_extension", _fake_install)


@pytest.fixture
def converge_skills_workspace():
    """Plant a healthy skills-delivery substrate: `.agents/manifest.yaml` + every
    MANAGED_SKILL_NAMES SKILL.md under `.agents/skills/` (what a successful `skills init` +
    `skills update --sync` leaves behind, minus the symlink indirection)."""

    def converge(root):
        manifest = root / ".agents" / "manifest.yaml"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("sources: {}\nskills: []\n", encoding="utf-8")
        for name in init_mod.MANAGED_SKILL_NAMES:
            skill = root / ".agents" / "skills" / name / "SKILL.md"
            skill.parent.mkdir(parents=True, exist_ok=True)
            skill.write_text("# skill\n", encoding="utf-8")

    return converge


@pytest.fixture(scope="session")
def _unborn_git_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("unborn-git-template")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "perk tests")
    # No detached background maintenance in fixture repos: an auto-spawned `git maintenance`/gc
    # mutates `.git` concurrently with the copytree fan-out (the transient-lock race above).
    # Set on the ROOT template so every derived copy inherits it via the copied `.git/config`.
    _git(root, "config", "maintenance.auto", "false")
    _git(root, "config", "gc.auto", "0")
    return root


@pytest.fixture(scope="session")
def _committed_git_template(
    tmp_path_factory: pytest.TempPathFactory, _unborn_git_template: Path
) -> Path:
    root = _copy_template(
        _unborn_git_template,
        tmp_path_factory.mktemp("committed-git-template"),
    )
    (root / "f.txt").write_text("hi\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    return root


@pytest.fixture(scope="session")
def _scaffolded_perk_template(
    tmp_path_factory: pytest.TempPathFactory, _committed_git_template: Path
) -> Path:
    root = _copy_template(
        _committed_git_template,
        tmp_path_factory.mktemp("scaffolded-perk-template"),
    )
    init_mod.run_init(root, verify=False)
    return root


@pytest.fixture(scope="session")
def _remote_git_template(tmp_path_factory: pytest.TempPathFactory) -> _RemoteGitTemplate:
    root = tmp_path_factory.mktemp("remote-git-template")
    remote = root / "remote.git"
    seed = root / "seed"
    clone = root / "clone"

    _git(root, "init", "-q", "--bare", "-b", "main", str(remote))
    _git(root, "init", "-q", "-b", "main", str(seed))
    _git(seed, "config", "user.email", "t@example.com")
    _git(seed, "config", "user.name", "perk tests")
    (seed / "f.txt").write_text("hi\n", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-qm", "init")
    _git(seed, "remote", "add", "origin", "../remote.git")
    _git(seed, "push", "-q", "-u", "origin", "main")

    _git(root, "clone", "-q", "remote.git", "clone")
    _git(clone, "remote", "set-url", "origin", "../remote.git")
    _git(clone, "config", "user.email", "t@example.com")
    _git(clone, "config", "user.name", "perk tests")

    (seed / "f.txt").write_text("advanced\n", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-qm", "advance")
    return _RemoteGitTemplate(root=root, advanced_sha=_git(seed, "rev-parse", "HEAD").strip())


@pytest.fixture(scope="session")
def unborn_git_repo_factory(_unborn_git_template: Path) -> GitRepoFactory:
    return lambda destination: _copy_template(_unborn_git_template, destination)


@pytest.fixture(scope="session")
def git_repo_factory(_committed_git_template: Path) -> GitRepoFactory:
    return lambda destination: _copy_template(_committed_git_template, destination)


@pytest.fixture(scope="session")
def remote_git_repo_factory(_remote_git_template: _RemoteGitTemplate) -> RemoteGitRepoFactory:
    def build(destination: Path) -> RemoteGitRepo:
        _copy_template(_remote_git_template.root, destination)
        remote = destination / "remote.git"
        seed = destination / "seed"
        clone = destination / "clone"

        def advance_origin() -> str:
            _git(seed, "push", "-q", "origin", "main")
            return _remote_git_template.advanced_sha

        return clone, remote, advance_origin

    return build


@pytest.fixture
def git_repo(tmp_path: Path, git_repo_factory: GitRepoFactory) -> Path:
    """An independent copy of a per-worker Git repository template with one commit."""
    return git_repo_factory(tmp_path)


@pytest.fixture
def scaffolded_perk_repo(tmp_path: Path, _scaffolded_perk_template: Path) -> Path:
    """An independent initialized consumer repo copied from a per-worker template."""
    return _copy_template(_scaffolded_perk_template, tmp_path)


@pytest.fixture
def git_repo_with_remote(
    tmp_path: Path, remote_git_repo_factory: RemoteGitRepoFactory
) -> RemoteGitRepo:
    """An independent clone/bare-origin world copied from a per-worker template."""
    return remote_git_repo_factory(tmp_path)
