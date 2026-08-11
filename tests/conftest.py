import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from perk import __version__
from perk import github as gh_mod
from perk.convergence import env as env_mod
from perk.convergence import init as init_mod
from perk.convergence.init import extension_install as _ext_install

_SOURCE_ROOTS = ("src", "extension", "tests", "shared", "docs", "skills", "agents", "prompts")
_SOURCE_SUFFIXES = frozenset({".py", ".ts", ".md", ".yaml", ".yml", ".json", ".jinja"})


@dataclass
class LaunchExecRecorder:
    """Calls made at the irreversible launch boundary."""

    agent_dir: Path
    chdirs: list[Path] = field(default_factory=list)
    calls: list[tuple[str, tuple[str, ...], dict[str, str]]] = field(default_factory=list)


@pytest.fixture(autouse=True)
def _reset_launch_banner_guard():
    """Reset the process-global once-per-process banner guard before every test so the latched
    flag never leaks across tests (an emitter in one test must not no-op a later test)."""
    # Imported inside the fixture (not at module top) so resetting the private guard stays a
    # narrow test concern and conftest's import surface isn't widened for every collection.
    import perk.run.launch.materialize as _m

    _m._LAUNCH_BANNER_EMITTED = False
    yield


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
    from perk.substrate.config import Config
    from perk.substrate.registry import Stage

    def build(
        *,
        stage: Stage,
        repo_root: Path | None = None,
        worktree: Path | None = None,
        config: Config | None = None,
        plan_ref: plan.PlanRef | None = None,
        created: bool = False,
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
            base=base,
            created=created,
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


@pytest.fixture
def git_repo(tmp_path):
    """A throwaway initialized git repo with one commit."""

    def g(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True)

    g("init", "-q")
    g("config", "user.email", "t@example.com")
    g("config", "user.name", "perk tests")
    (tmp_path / "f.txt").write_text("hi\n", encoding="utf-8")
    g("add", ".")
    g("commit", "-qm", "init")
    return tmp_path


@pytest.fixture
def git_repo_with_remote(tmp_path):
    """A clone with a local **bare** remote (``origin``), offline-testable.

    Returns ``(clone, remote, advance_origin)`` where ``advance_origin()`` pushes a fresh
    commit to ``origin/<trunk>`` from a side checkout so the clone falls behind until it
    fetches. The clone has ``origin/HEAD`` set so ``detect_trunk_branch`` resolves the trunk.
    """
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    clone = tmp_path / "clone"

    def g(cwd, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        ).stdout

    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
    )
    # Seed the remote's main with one commit.
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True, capture_output=True)
    g(seed, "config", "user.email", "t@example.com")
    g(seed, "config", "user.name", "perk tests")
    (seed / "f.txt").write_text("hi\n", encoding="utf-8")
    g(seed, "add", ".")
    g(seed, "commit", "-qm", "init")
    g(seed, "remote", "add", "origin", str(remote))
    g(seed, "push", "-q", "-u", "origin", "main")

    # Clone it (origin + origin/HEAD set automatically).
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)
    g(clone, "config", "user.email", "t@example.com")
    g(clone, "config", "user.name", "perk tests")

    def advance_origin() -> str:
        """Push a new commit to origin/main (from the seed checkout); returns its sha."""
        g(seed, "pull", "-q", "origin", "main")
        (seed / "f.txt").write_text("advanced\n", encoding="utf-8")
        g(seed, "add", ".")
        g(seed, "commit", "-qm", "advance")
        g(seed, "push", "-q", "origin", "main")
        return g(seed, "rev-parse", "HEAD").strip()

    return clone, remote, advance_origin
