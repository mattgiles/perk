"""`perk learn dream` — the whole-corpus curation-factory cold door (door + seed + skill).

`launch.launch_stage` is stubbed on its defining module (no `exec pi`), mirroring
test_learn_harvest_cmd.py. Every non-dry-run success test monkeypatches
`resolve.resolve_objective_store` to a recording fake (no test performs a real backend read);
dedicated origin tests override the fake. The repo fixture commits the seeded corpus so HEAD
resolves, the tree is clean, and the manifest's `commit_sha` honestly stamps the snapshot.
"""

import json
import re
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import objective
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveRef, ObjectiveStoreError
from perk.cli.cli import cli
from perk.run import launch
from perk.substrate import git

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pointer(skill: str) -> str:
    """The path-carrying nudge pointer line the binding renderer emits for ``skill``."""
    return f"Follow the `{skill}` skill (read `.agents/skills/{skill}/SKILL.md`)."


def _seed_corpus(root: Path, clusters: dict[str, int]) -> None:
    """Seed a cluster-frontmattered corpus plus a valid registry naming every cluster."""
    for cluster_id, count in clusters.items():
        for i in range(count):
            doc = root / "docs" / "learned" / cluster_id / f"doc-{i}.md"
            doc.parent.mkdir(parents=True, exist_ok=True)
            doc.write_text(
                f"---\ntitle: Doc {i}\nread_when: When you touch {cluster_id}.\n"
                f"cluster: {cluster_id}\n---\n\nBody.\n",
                encoding="utf-8",
            )
    if clusters:
        registry = root / "docs" / "learned" / "clusters.yaml"
        lines = ["clusters:"]
        for cluster_id in clusters:
            lines.append(f"  - id: {cluster_id}")
            lines.append(f"    rollup: Rollup for {cluster_id}.")
        registry.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _repo(d: str, clusters: dict[str, int], *, commit: bool = True) -> Path:
    """git init + seed + COMMIT the corpus (HEAD resolves; the tree is clean).

    Mirrors a real perk repo: `/.perk/workflow/` is gitignored, so run-scratch writes (a prior
    invocation's manifest) never dirty the tree between invocations. Resolve the
    isolated-filesystem root up front (the macOS `/var` vs `/private/var` trap) before building
    expected manifest paths against it.
    """
    root = Path(d).resolve()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    (root / ".gitignore").write_text("/.perk/workflow/\n", encoding="utf-8")
    _seed_corpus(root, clusters)
    if commit:
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(
            ["git", "commit", "-q", "--allow-empty", "-m", "corpus"], cwd=root, check=True
        )
    return root


def _head_sha(root: Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def _stub_launch(monkeypatch, sink: dict) -> None:
    monkeypatch.setattr(
        launch,
        "launch_stage",
        lambda **k: sink.update(
            stage=k["stage"].id,
            prompt=k.get("prompt_override"),
            binding_trigger=k.get("binding_trigger"),
            sync_main=k.get("sync_main"),
            run_id_override=k.get("run_id_override"),
        ),
    )


def _boom_launch(monkeypatch, why: str) -> None:
    def boom(**k):
        raise AssertionError(why)

    monkeypatch.setattr(launch, "launch_stage", boom)


class _RecordingStore:
    """A hermetic ObjectiveStore fake: records the origin-guard lookup, returns/raises."""

    def __init__(self, ref: ObjectiveRef | None = None, raises: Exception | None = None):
        self.calls: list[tuple[object, object]] = []
        self._ref = ref
        self._raises = raises

    def find_open_objective_by_origin(self, *, origin, exclude_run_id=None):
        self.calls.append((origin, exclude_run_id))
        if self._raises is not None:
            raise self._raises
        return self._ref


def _fake_store(
    monkeypatch, *, ref: ObjectiveRef | None = None, raises: Exception | None = None
) -> _RecordingStore:
    """Patch the door's store seam (`resolve.resolve_objective_store` — the module reference
    dream_cmd calls through) to a recording fake; no test performs a real backend read."""
    store = _RecordingStore(ref=ref, raises=raises)
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda repo_root: store)
    return store


def _scratch_runs(root: Path) -> Path:
    return root / ".perk" / "workflow" / "scratch" / "runs"


# --- the dry-run --json payload pin ----------------------------------------------------------


def test_dry_run_json_payload_pin(monkeypatch):
    _boom_launch(monkeypatch, "--dry-run must not launch")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = _repo(d, {"wf": 3})
        result = runner.invoke(cli, ["learn", "dream", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        manifest_path = payload["manifest_path"]
        total_bytes = sum(
            p.stat().st_size for p in (root / "docs" / "learned").rglob("*.md") if p.is_file()
        )
        # Full-dict equality — the payload keys and values are the contract (§8.65).
        assert payload == {
            "success": True,
            "error_type": None,
            "manifest_path": manifest_path,
            "commit_sha": _head_sha(root),
            "registry_mode": "clusters",
            "doc_count": 3,
            "lane_count": 1,
            "lane_ids": ["wf-1"],
            "total_bytes": total_bytes,
            "origin_guard": "not-evaluated",
            "launched": False,
        }
        # The manifest is REAL on --dry-run (materialize-on-dry-run), run-scoped under scratch.
        mp = Path(manifest_path)
        assert mp.is_file()
        assert mp.name == "dream-manifest.json"
        assert mp.parent.parent == _scratch_runs(root)
        manifest = json.loads(mp.read_text(encoding="utf-8"))
        assert manifest["commit_sha"] == _head_sha(root)


def test_dry_run_is_offline(monkeypatch):
    """--dry-run never evaluates the origin guard: the store seam raising proves it is never
    resolved, and the launch stub proves nothing launches."""
    _boom_launch(monkeypatch, "--dry-run must not launch")

    def boom_store(repo_root):
        raise AssertionError("--dry-run must not resolve the objective store")

    monkeypatch.setattr(resolve, "resolve_objective_store", boom_store)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"wf": 1})
        result = runner.invoke(cli, ["learn", "dream", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output


# --- the real launch capture ------------------------------------------------------------------


def test_real_launch_borrows_objective_author_with_seeded_prompt(monkeypatch):
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    store = _fake_store(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"wf": 2})
        result = runner.invoke(cli, ["learn", "dream", "--json"])
        assert result.exit_code == 0, result.output
    assert launched["stage"] == "objective-author"  # borrows the stage descriptor
    # The stage:objective-author binding is diverted to the command trigger.
    assert launched["binding_trigger"] == "command:learn-dream"
    # The in-launch sync is ALWAYS suppressed — the door's gather owns the one pre-gather sync.
    assert launched["sync_main"] is False
    prompt = launched["prompt"] or ""
    # The pre-minted run id: the launched session and the manifest's run-scoped path agree.
    match = re.search(r"runs/([^/]+)/dream-manifest\.json", prompt)
    assert match is not None, prompt
    assert launched["run_id_override"] == match.group(1)
    # The door-derived counts ride the seed.
    assert "2 doc(s)" in prompt
    assert "1 lane(s)" in prompt
    # The fail-closed origin guard ran with the pinned arguments (a fresh run has no stored
    # objective, so there is nothing to exclude at launch time).
    assert store.calls == [(objective.ObjectiveOrigin.LEARN_DREAM, None)]


def test_seed_hardcodes_no_skill_pointer(monkeypatch):
    """The seed hardcodes NO skill pointer (§8.57): the perk-learn-dream pointer LINE rides the
    command:learn-dream binding (naming the skill in prose is fine, so never a bare-name pin),
    and the perk-objective-author read path rides the skill's cross-reference."""
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    _fake_store(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"wf": 1})
        result = runner.invoke(cli, ["learn", "dream", "--json"])
        assert result.exit_code == 0, result.output
    prompt = launched["prompt"] or ""
    assert _pointer("perk-learn-dream") not in prompt
    assert _pointer("perk-objective-author") not in prompt


# --- the --from rejection ---------------------------------------------------------------------


def test_from_is_rejected_in_both_spellings(monkeypatch):
    _boom_launch(monkeypatch, "a refused --from must not launch")
    for args in (["--from", "docs/learned/x"], ["--from=docs/learned/x"]):
        runner = CliRunner()
        with runner.isolated_filesystem() as d:
            root = _repo(d, {"wf": 1})
            result = runner.invoke(cli, ["learn", "dream", "--json", *args])
            assert result.exit_code == 1, result.output
            payload = json.loads(result.stdout)
            assert payload["error_type"] == "invalid_input"
            # The cross-hint: partial-corpus mining is harvest's job.
            assert "perk learn harvest --from" in payload["message"]
            # The rejection fires FIRST — before any scratch write.
            assert not _scratch_runs(root).exists()


def test_benign_passthrough_token_still_launches(monkeypatch):
    """The family's pi passthrough is preserved: only the `--from` spelling is rejected."""
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    _fake_store(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"wf": 1})
        result = runner.invoke(cli, ["learn", "dream", "--json", "--some-pi-flag"])
        assert result.exit_code == 0, result.output
    assert launched["stage"] == "objective-author"


# --- the git preflight ------------------------------------------------------------------------


def test_unborn_head_is_invalid_input(monkeypatch):
    _boom_launch(monkeypatch, "an unborn HEAD must not launch")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"wf": 1}, commit=False)
        result = runner.invoke(cli, ["learn", "dream", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "invalid_input"
        assert "HEAD" in payload["message"]


def test_modified_tracked_file_is_dirty_checkout(monkeypatch):
    _boom_launch(monkeypatch, "a dirty tree must not launch")
    _fake_store(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = _repo(d, {"wf": 1})
        doc = root / "docs" / "learned" / "wf" / "doc-0.md"
        doc.write_text(doc.read_text(encoding="utf-8") + "\nEdit.\n", encoding="utf-8")
        result = runner.invoke(cli, ["learn", "dream", "--no-sync", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "dirty_checkout"


def test_lone_untracked_file_is_dirty_checkout(monkeypatch):
    _boom_launch(monkeypatch, "a dirty tree must not launch")
    _fake_store(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = _repo(d, {"wf": 1})
        (root / "note.txt").write_text("untracked\n", encoding="utf-8")
        result = runner.invoke(cli, ["learn", "dream", "--no-sync", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "dirty_checkout"


def test_dirty_tree_refuses_on_dry_run_too(monkeypatch):
    """--dry-run validates every local precondition — the clean check included."""
    _boom_launch(monkeypatch, "--dry-run must not launch")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = _repo(d, {"wf": 1})
        (root / "note.txt").write_text("untracked\n", encoding="utf-8")
        result = runner.invoke(cli, ["learn", "dream", "--dry-run", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "dirty_checkout"


def test_git_probe_failure_is_git_error(monkeypatch):
    """An unprovable probe (`git status` cannot run) is the typed fail-closed refusal, never a
    traceback (the envelope parses and the exit is 1)."""
    _boom_launch(monkeypatch, "an unprovable probe must not launch")

    def boom(cwd):
        raise git.GitError("git status exploded")

    monkeypatch.setattr(git, "is_dirty", boom)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"wf": 1})
        result = runner.invoke(cli, ["learn", "dream", "--dry-run", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "git_error"
        assert "git status exploded" in payload["message"]


def test_ignored_corpus_doc_is_invalid_input(monkeypatch):
    """`git status --porcelain` omits gitignored files, so an ignored docs/learned doc leaves
    the tree clean while the filesystem gather still picks it up — the tracked-corpus check is
    the regression guard that refuses it (not reproducible from the stamped commit)."""
    _boom_launch(monkeypatch, "an ignored corpus member must not launch")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d).resolve()
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
        _seed_corpus(root, {"wf": 1})
        (root / ".gitignore").write_text("docs/learned/secret/\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "corpus + ignore rule"], cwd=root, check=True)
        # The ignored doc: present on disk, invisible to `git status`, gathered by the glob.
        secret = root / "docs" / "learned" / "secret" / "ignored.md"
        secret.parent.mkdir(parents=True)
        secret.write_text(
            "---\ntitle: S\nread_when: Never.\ncluster: wf\n---\n\nBody.\n", encoding="utf-8"
        )
        assert not git.is_dirty(root), "sanity: tree-clean alone would have passed"
        result = runner.invoke(cli, ["learn", "dream", "--dry-run", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "invalid_input"
        assert "docs/learned/secret/ignored.md" in payload["message"]


# --- sync ordering + the single SHA capture ---------------------------------------------------


def test_sync_runs_on_real_launch_only(monkeypatch):
    events: list = []
    monkeypatch.setattr(launch, "_sync_main_checkout", lambda root: events.append("sync"))
    _stub_launch(monkeypatch, {})
    _fake_store(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"wf": 1})
        assert runner.invoke(cli, ["learn", "dream"]).exit_code == 0
        assert events == ["sync"]
        assert runner.invoke(cli, ["learn", "dream", "--no-sync"]).exit_code == 0
        assert events == ["sync"], "--no-sync skips the pre-gather sync"
        assert runner.invoke(cli, ["learn", "dream", "--dry-run"]).exit_code == 0
        assert events == ["sync"], "--dry-run never syncs"


def test_head_is_captured_exactly_once(monkeypatch):
    calls: list = []
    real = git.resolve_commit
    monkeypatch.setattr(
        git, "resolve_commit", lambda repo, ref: (calls.append(ref), real(repo, ref))[1]
    )
    _stub_launch(monkeypatch, {})
    _fake_store(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"wf": 1})
        result = runner.invoke(cli, ["learn", "dream", "--json"])
        assert result.exit_code == 0, result.output
    assert calls == ["HEAD"], "the single SHA capture — exactly one resolve_commit per invocation"


# --- the origin guard -------------------------------------------------------------------------


def test_origin_conflict_names_the_open_objective(monkeypatch):
    _boom_launch(monkeypatch, "an origin conflict must not launch")
    _fake_store(
        monkeypatch, ref=ObjectiveRef(id="42", url="https://example.com/i/42", existed=True)
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = _repo(d, {"wf": 1})
        result = runner.invoke(cli, ["learn", "dream", "--no-sync", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "origin_conflict"
        assert "#42" in payload["message"]
        assert "https://example.com/i/42" in payload["message"]
        # The guard runs BEFORE the run id is minted — no run-scratch manifest was written.
        assert not _scratch_runs(root).exists()


def test_origin_lookup_failure_is_fail_closed(monkeypatch):
    """Both raise points — the lookup itself and the store resolution — share the fail-closed
    `origin_lookup_failed` envelope."""
    _boom_launch(monkeypatch, "an unanswerable guard must not launch")
    runner = CliRunner()
    # The store's lookup raises ObjectiveStoreError.
    with runner.isolated_filesystem() as d:
        _repo(d, {"wf": 1})
        _fake_store(monkeypatch, raises=ObjectiveStoreError("enumeration failed"))
        result = runner.invoke(cli, ["learn", "dream", "--no-sync", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "origin_lookup_failed"
        assert "enumeration failed" in payload["message"]
    # The store resolution itself raises IssueBackendError.
    with runner.isolated_filesystem() as d:
        _repo(d, {"wf": 1})

        def boom_resolve(repo_root):
            raise IssueBackendError("backend unavailable")

        monkeypatch.setattr(resolve, "resolve_objective_store", boom_resolve)
        result = runner.invoke(cli, ["learn", "dream", "--no-sync", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "origin_lookup_failed"
        assert "backend unavailable" in payload["message"]


# --- refusal passthrough + the family generics ------------------------------------------------


def test_empty_corpus_is_no_learned_docs(monkeypatch):
    _boom_launch(monkeypatch, "an empty corpus must not launch")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {})  # a commit exists (HEAD resolves) but there are no learned docs
        result = runner.invoke(cli, ["learn", "dream", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "no_learned_docs"


def test_remote_blocked_before_any_side_effect(monkeypatch):
    events: list = []
    monkeypatch.setattr(launch, "_sync_main_checkout", lambda root: events.append("sync"))
    _boom_launch(monkeypatch, "--remote must not launch")

    def boom_store(repo_root):
        raise AssertionError("--remote must refuse before the origin guard")

    monkeypatch.setattr(resolve, "resolve_objective_store", boom_store)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = _repo(d, {"wf": 1})
        result = runner.invoke(cli, ["learn", "dream", "--remote", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "remote_blocked"
        assert events == []
        assert not _scratch_runs(root).exists()


def test_not_a_repo_exit_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["learn", "dream", "--json"])
        assert result.exit_code == 2
        assert json.loads(result.stdout)["error_type"] == "not_a_repo"


# --- the skill semantic contract --------------------------------------------------------------


def test_skill_semantic_contract():
    """The perk-learn-dream skill carries the fixed curation policy (direct file read;
    whitespace normalized so prose wrapping can't bisect a pin). The flow/outcome rules live on
    the SEED — the skill carries judgment detail only (§8.57)."""
    text = (REPO_ROOT / "skills" / "perk-learn-dream" / "SKILL.md").read_text(encoding="utf-8")
    norm = " ".join(text.split())
    # The four closed dispositions — no fifth action.
    for disposition in ("`keep`", "`revise`", "`merge-into`", "`retire`"):
        assert disposition in norm
    assert "no fifth action" in norm
    # The destructive evidence bar: BOTH gate reducers endorse + no challenge from ANY reducer;
    # silence counts as non-endorsement.
    assert "`consolidation-preservation`" in norm
    assert "`currency-accuracy`" in norm
    assert "NO `challenge` from ANY reducer" in norm
    assert "Silence counts as non-endorsement" in norm
    # The disagreement rule: downgrade-only, never resolve upward.
    assert "downgrade" in norm
    assert "never resolve upward" in norm
    assert "fallback_reason" in norm
    # Ranking: truth first, then leverage.
    assert "truth first, then leverage" in norm
    # Selection: ≤ 12 distinct nodes; overflow stays ranked in the report.
    assert "12 distinct" in norm
    assert "ranked in the report's overflow" in norm
    # Harvest follow-ups are bounded and report-only, citing a surviving destination.
    assert "report-only" in norm
    assert "surviving" in norm
    # The perk-objective-author read path: the skill's cross-reference is the ONE carrier.
    assert ".agents/skills/perk-objective-author/SKILL.md" in norm
