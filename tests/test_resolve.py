"""Tests for the backend-tier resolvers + the consumer-boundary scans.

The resolver (``perk/backends/resolve.py``) is the only door every backend consumer goes through:
``resolve_issue_backend`` / ``resolve_objective_store`` validate the committed ``[issues]``
selection and construct the matching backend; the local overlay is never read. The
``TestConsumerBoundary`` scans are the source-scan companions proving no production module reaches
the GitHub substrate modules (``perk/backends/github/{plans,objectives}.py``) directly — both
express "the resolver is the only door"; the live scan and its synthetic controls share the same
discovery and rule helpers, so the guard proves it inspected a live corpus and that its rule bites.
(The objective-store tests folded in here from the retired ``test_objective_stores.py``.)
"""

import re
from pathlib import Path

import pytest

import perk
from perk.backends import resolve
from perk.backends.github.backend import GitHubIssueBackend
from perk.backends.github.objective_store import GitHubObjectiveStore
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import LinearIssueBackend, LinearProjectObjectiveStore
from perk.backends.resolve import (
    publish_dream_artifact,
    resolve_issue_backend,
    resolve_issue_backend_id,
    resolve_objective_store,
    resolve_objective_store_id,
)

# Map the legacy config filenames callers still pass to the `.perk/` target locations.
_NAME_MAP = {"perk.toml": "config.toml", "perk.local.toml": "local.toml"}


def _write_config(repo_root: Path, name: str, text: str) -> None:
    cfg = repo_root / ".perk"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / _NAME_MAP.get(name, name)).write_text(text, encoding="utf-8")


class TestResolver:
    def test_returns_github_backend_bound_to_root(self, tmp_path: Path) -> None:
        backend = resolve_issue_backend(tmp_path)
        assert isinstance(backend, GitHubIssueBackend)
        assert backend._repo_root == tmp_path

    def test_explicit_github_selection_returns_github_backend(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "github"\n')
        assert isinstance(resolve_issue_backend(tmp_path), GitHubIssueBackend)

    def test_resolve_id_accepts_linear(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\n')
        assert resolve_issue_backend_id(tmp_path) == resolve.LINEAR_BACKEND_ID

    def test_linear_selection_missing_api_key_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\nteam = "ENG"\n')
        with pytest.raises(IssueBackendError, match="LINEAR_API_KEY"):
            resolve_issue_backend(tmp_path)

    def test_linear_selection_missing_team_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\n')
        with pytest.raises(IssueBackendError, match=r"\[issues\] team is required"):
            resolve_issue_backend(tmp_path)

    def test_linear_selection_returns_linear_backend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\nteam = "ENG"\n')
        backend = resolve_issue_backend(tmp_path)
        assert isinstance(backend, LinearIssueBackend)
        assert backend.backend_id == "linear"
        # Construction is lazy — the team key is bound, no network call issued.
        assert backend._team_key == "ENG"

    def test_unknown_selection_raises(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "jira"\n')
        with pytest.raises(IssueBackendError, match="unknown issue backend"):
            resolve_issue_backend(tmp_path)

    def test_local_overlay_selection_is_ignored(self, tmp_path: Path) -> None:
        # Committed-only read: a perk.local.toml [issues] selection never fragments the store.
        _write_config(tmp_path, "perk.local.toml", '[issues]\nbackend = "linear"\n')
        assert isinstance(resolve_issue_backend(tmp_path), GitHubIssueBackend)

    def test_malformed_committed_toml_raises_backend_error(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "perk.toml", "[issues\nbackend =")
        with pytest.raises(IssueBackendError, match="not valid TOML"):
            resolve_issue_backend(tmp_path)

    def test_illtyped_committed_value_raises_backend_error(self, tmp_path: Path) -> None:
        # An ill-typed `[issues]` value maps to IssueBackendError via the ConfigError arm
        # (mirrors the malformed-TOML pin), carrying the field path + the doctor hint.
        _write_config(tmp_path, "perk.toml", "[issues]\nbackend = 7\n")
        with pytest.raises(IssueBackendError, match="backend: Input should be a valid string"):
            resolve_issue_backend(tmp_path)

    def test_resolve_id_defaults_to_github(self, tmp_path: Path) -> None:
        assert resolve_issue_backend_id(tmp_path) == resolve.GITHUB_BACKEND_ID


class TestObjectiveResolver:
    """The objective-store resolver pair (folded in from the retired test_objective_stores.py)."""

    def test_default_returns_github_store_bound_to_root(self, tmp_path: Path) -> None:
        store = resolve_objective_store(tmp_path)
        assert isinstance(store, GitHubObjectiveStore)
        assert store._repo_root == tmp_path

    def test_explicit_github_selection_returns_github_store(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "github"\n')
        assert isinstance(resolve_objective_store(tmp_path), GitHubObjectiveStore)

    def test_resolve_id_single_sources_off_issue_backend(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\n')
        assert resolve_objective_store_id(tmp_path) == resolve.LINEAR_BACKEND_ID

    def test_resolve_id_defaults_to_github(self, tmp_path: Path) -> None:
        assert resolve_objective_store_id(tmp_path) == resolve.GITHUB_BACKEND_ID

    def test_linear_selection_returns_project_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The linear arm is project-backed (LinearProjectObjectiveStore), not the
        # dormant issue-backed LinearObjectiveStore.
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\nteam = "ENG"\n')
        store = resolve_objective_store(tmp_path)
        assert isinstance(store, LinearProjectObjectiveStore)
        assert store.backend_id == "linear"
        # Construction is lazy — the team key is bound on the shared ops, no network call issued.
        assert store._issue_ops._team_key == "ENG"
        assert store._projects._team_key == "ENG"

    def test_linear_selection_missing_team_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\n')
        with pytest.raises(IssueBackendError, match=r"\[issues\] team is required"):
            resolve_objective_store(tmp_path)

    def test_linear_selection_missing_api_key_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\nteam = "ENG"\n')
        with pytest.raises(IssueBackendError, match="LINEAR_API_KEY"):
            resolve_objective_store(tmp_path)

    def test_unknown_selection_raises(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "jira"\n')
        with pytest.raises(IssueBackendError, match="unknown issue backend"):
            resolve_objective_store(tmp_path)


class TestPublishDreamArtifact:
    """The dream-artifact publish function (contracts.md §8.64) — keyed off the same committed
    ``[issues]`` selection as the store/backend resolvers."""

    def test_default_github_arm_is_an_immediate_no_op(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _no_client(**_: object) -> object:
            raise AssertionError("the GitHub arm must never construct a Linear client")

        monkeypatch.setattr(resolve.linear_client, "client_from_env", _no_client)
        assert publish_dream_artifact(tmp_path, objective_id="7", run_id="01R", parts=["p"]) is None

    def test_linear_selection_routes_to_the_linear_flow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\nteam = "ENG"\n')
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            resolve.linear,
            "publish_dream_artifact",
            lambda _client, **kwargs: calls.append(kwargs),
        )
        publish_dream_artifact(tmp_path, objective_id="proj-1", run_id="01R", parts=["p"])
        [call] = calls
        assert call["team_key"] == "ENG"
        assert call["objective_id"] == "proj-1" and call["run_id"] == "01R"

    def test_linear_selection_missing_team_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\n')
        with pytest.raises(IssueBackendError, match=r"\[issues\] team is required"):
            publish_dream_artifact(tmp_path, objective_id="proj-1", run_id="01R", parts=["p"])

    def test_linear_selection_missing_api_key_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\nteam = "ENG"\n')
        with pytest.raises(IssueBackendError, match="LINEAR_API_KEY"):
            publish_dream_artifact(tmp_path, objective_id="proj-1", run_id="01R", parts=["p"])


# The GitHub plan/issue + objective substrate modules. Production code must reach them through the
# resolvers in perk.backends.resolve (resolve_issue_backend / resolve_objective_store), never by
# importing the substrate module directly. The only legitimate importers are the GitHub backend
# package's own modules (the adapters + the sibling substrate) under perk/backends/github/.
SUBSTRATE_MODULES: tuple[str, ...] = (
    "perk.backends.github.plans",
    "perk.backends.github.objectives",
)

# The package-level from-import shape production actually uses (`from perk.backends.github import
# plans`), invisible to the dotted substring above. Single line only — a parenthesised multi-line
# import list, a relative import, or attribute access through `from perk.backends import github`
# all escape. A textual backstop, not a completeness proof
# (docs/learned/workflow/source-scan-guards.md).
SUBSTRATE_FROM_IMPORT = re.compile(
    r"^\s*from\s+perk\.backends\.github\s+import\s+.*\b(plans|objectives)\b"
)

# Files the live scan must inspect: the door itself, a sibling backend package (the exclusion must
# not swallow all of `backends/`), and the gateway package that shares the `github` name.
LIVE_ANCHORS: tuple[Path, ...] = (
    Path("backends/resolve.py"),
    Path("backends/linear/backend.py"),
    Path("github/__init__.py"),
)

# Exists on disk, must never be scanned — proves the exclusion is live.
EXCLUDED_ANCHOR = Path("backends/github/plans.py")


def _reaches_substrate(line: str) -> bool:
    """The textual rule, one line at a time: the dotted module path anywhere on the line (the
    original rule, kept verbatim) OR a package-level from-import naming a substrate module."""
    return any(mod in line for mod in SUBSTRATE_MODULES) or bool(SUBSTRATE_FROM_IMPORT.search(line))


def _production_files(perk_dir: Path) -> list[Path]:
    """Package-root recursive discovery minus the GitHub backend package, evaluated at call time so
    a newly created module is inspected on the next run. Fails closed: an empty walk raises rather
    than yielding a vacuously clean scan."""
    github_backend_dir = perk_dir / "backends" / "github"
    files = [p for p in sorted(perk_dir.rglob("*.py")) if not p.is_relative_to(github_backend_dir)]
    if not files:
        raise AssertionError("production-file scan came up empty — guard is vacuous")
    return files


def _substrate_offenders(perk_dir: Path) -> list[str]:
    """The checker the live guard and the synthetic controls share; the diagnostic format is
    unchanged (`<path from the package parent>:<lineno>: <stripped line>`)."""
    offenders: list[str] = []
    for path in _production_files(perk_dir):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _reaches_substrate(line):
                offenders.append(f"{path.relative_to(perk_dir.parent)}:{lineno}: {line.strip()}")
    return offenders


class TestConsumerBoundary:
    def test_no_production_module_imports_the_substrate_directly(self) -> None:
        """Source scan: no module under perk/ OUTSIDE the GitHub backend package
        (perk/backends/github/) may import the substrate modules
        perk.backends.github.{plans,objectives} directly — production reaches plan/issue and
        objective ops through resolve.resolve_issue_backend(...) / resolve.resolve_objective_store(
        ...). The adapters (backend.py, objective_store.py) and the sibling substrate
        (objectives.py importing plans) legitimately import it, so the whole perk/backends/github/
        package is allowed. The anchors prove the scan inspected the intended corpus — and skipped
        the excluded package — before cleanliness means anything."""
        perk_dir = Path(perk.__file__).parent
        scanned = {p.relative_to(perk_dir) for p in _production_files(perk_dir)}
        missing = [str(a) for a in LIVE_ANCHORS if a not in scanned]
        assert not missing, f"scan missed live anchors {missing} — guard is misaimed"
        assert (perk_dir / EXCLUDED_ANCHOR).is_file(), (
            f"{EXCLUDED_ANCHOR} no longer exists — re-aim EXCLUDED_ANCHOR"
        )
        assert EXCLUDED_ANCHOR not in scanned, (
            f"{EXCLUDED_ANCHOR} was scanned — the GitHub-package exclusion is broken"
        )
        offenders = _substrate_offenders(perk_dir)
        assert not offenders, (
            "substrate imports must go through perk.backends.resolve (resolve_issue_backend / "
            "resolve_objective_store); only perk/backends/github/ may import "
            "perk.backends.github.{plans,objectives}:\n" + "\n".join(offenders)
        )

    def test_rule_matches_the_adapters_own_substrate_imports(self) -> None:
        """Liveness: the rule must bite a real import *statement* in the allowed package (docstring
        mentions are deliberately excluded), else the rule has rotted or the adapters moved."""
        perk_dir = Path(perk.__file__).parent
        for rel in (
            "backends/github/backend.py",
            "backends/github/objective_store.py",
            "backends/github/objectives.py",
        ):
            source = (perk_dir / rel).read_text(encoding="utf-8")
            import_lines = [
                line
                for line in source.splitlines()
                if line.lstrip().startswith(
                    ("from perk.backends.github import", "import perk.backends.github.")
                )
            ]
            assert any(_reaches_substrate(line) for line in import_lines), (
                f"{rel}: no real substrate import statement matches the rule — "
                "the rule has rotted or the adapter moved"
            )

    def test_checker_flags_prohibited_and_permits_neighbouring_synthetic_imports(
        self, tmp_path: Path
    ) -> None:
        """The same helpers, over a planted tree: the from-import hole and the dotted shape are
        flagged; the resolver, the adapter, a non-substrate sibling, and the excluded package are
        not. Exact payload — path, line number, stripped line, sorted-file order."""
        root = tmp_path / "perk"
        (root / "cli").mkdir(parents=True)
        (root / "cli" / "consumer.py").write_text(
            '"""Reaches the substrate only through the resolver."""\n'
            "from perk.backends.resolve import resolve_issue_backend\n"
            "from perk.backends.github.backend import GitHubIssueBackend\n"
            "from perk.backends.github import engagement as gh_engagement\n"
            "from perk.backends.github import plans\n",
            encoding="utf-8",
        )
        (root / "learn").mkdir(parents=True)
        (root / "learn" / "exporter.py").write_text(
            "import perk.backends.github.objectives\n", encoding="utf-8"
        )
        (root / "backends" / "github").mkdir(parents=True)
        (root / "backends" / "github" / "backend.py").write_text(
            "from perk.backends.github import plans\n", encoding="utf-8"
        )
        assert _substrate_offenders(root) == [
            "perk/cli/consumer.py:5: from perk.backends.github import plans",
            "perk/learn/exporter.py:1: import perk.backends.github.objectives",
        ]

    def test_checker_fails_closed_on_empty_discovery(self, tmp_path: Path) -> None:
        """A walk where everything found was excluded is just as vacuous as finding nothing."""
        root = tmp_path / "perk"
        (root / "backends" / "github").mkdir(parents=True)
        (root / "backends" / "github" / "plans.py").write_text("GITHUB = True\n", encoding="utf-8")
        with pytest.raises(AssertionError, match="came up empty"):
            _substrate_offenders(root)
