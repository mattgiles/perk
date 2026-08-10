"""`perk learn harvest` — the objective-factory cold door (door + seed + skill contracts).

`launch.launch_stage` is stubbed on its defining module (no `exec pi`), mirroring
test_learn_docs_cmd.py. **No GitHub auth stub anywhere** — its absence is the proof the door
performs no GitHub read up front (the first backend mutation of a harvest run is the in-session
`objective_save`).

The repo fixture commits the seeded corpus so HEAD resolves AND the manifest's `commit_sha`
honestly covers the gathered docs.
"""

import json
import re
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk.cli.cli import cli
from perk.learn import harvest
from perk.run import launch
from perk.substrate import git

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pointer(skill: str) -> str:
    """The path-carrying nudge pointer line the binding renderer emits for ``skill``."""
    return f"Follow the `{skill}` skill (read `.agents/skills/{skill}/SKILL.md`)."


def _seed_docs(root: Path, categories: dict[str, int]) -> None:
    for category, count in categories.items():
        for i in range(count):
            doc = root / "docs" / "learned" / category / f"doc-{i}.md"
            doc.parent.mkdir(parents=True, exist_ok=True)
            doc.write_text(
                f"---\ntitle: Doc {i}\nread_when: When you touch {category}.\n---\n\nBody.\n",
                encoding="utf-8",
            )


def _repo(d: str, categories: dict[str, int], *, commit: bool = True) -> Path:
    """git init + seed + COMMIT the corpus (HEAD resolves; commit_sha covers the docs).

    Resolve the isolated-filesystem root up front (the macOS `/var` vs `/private/var` trap)
    before building expected manifest paths against it.
    """
    root = Path(d).resolve()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    _seed_docs(root, categories)
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


# --- the dry-run --json payload pin ---------------------------------------------------------------


def test_dry_run_json_payload_pin(monkeypatch):
    _boom_launch(monkeypatch, "--dry-run must not launch")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = _repo(d, {"workflow": 3})
        result = runner.invoke(cli, ["learn", "harvest", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        manifest_path = payload["manifest_path"]
        # Full-dict equality — the payload keys and values are the contract (§8.48).
        assert payload == {
            "success": True,
            "error_type": None,
            "manifest_path": manifest_path,
            "doc_count": 3,
            "lane_count": 1,
            "lane_ids": ["workflow-1"],
            "launched": False,
        }
        # The manifest is REAL on --dry-run (materialize-on-dry-run), run-scoped under scratch.
        mp = Path(manifest_path)
        assert mp.is_file()
        assert mp.name == "harvest-manifest.json"
        assert mp.parent.parent == root / ".perk" / "workflow" / "scratch" / "runs"
        manifest = json.loads(mp.read_text(encoding="utf-8"))
        assert manifest["commit_sha"] == _head_sha(root)


# --- the real launch capture ----------------------------------------------------------------------


def test_real_launch_borrows_objective_author_with_seeded_prompt(monkeypatch):
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"workflow": 2})
        result = runner.invoke(cli, ["learn", "harvest", "--json"])
        assert result.exit_code == 0, result.output
    assert launched["stage"] == "objective-author"  # borrows the stage descriptor
    # The stage:objective-author binding is diverted to the command trigger.
    assert launched["binding_trigger"] == "command:learn-harvest"
    # The in-launch sync is ALWAYS suppressed — the door's gather owns the one pre-gather sync.
    assert launched["sync_main"] is False
    prompt = launched["prompt"] or ""
    # The pre-minted run id: the launched session and the manifest's run-scoped path agree.
    match = re.search(r"runs/([^/]+)/harvest-manifest\.json", prompt)
    assert match is not None, prompt
    assert launched["run_id_override"] == match.group(1)
    # The seed hardcodes the authoring nudge (the diverted stage binding can't deliver it) …
    assert _pointer("perk-objective-author") in prompt
    # … and does NOT hardcode the perk-learn-harvest pointer LINE — that rides the
    # command:learn-harvest binding (naming the skill in prose is fine, so never a bare-name pin).
    assert _pointer("perk-learn-harvest") not in prompt


# --- sync ordering + gating -----------------------------------------------------------------------


def _instrument_events(monkeypatch, events: list) -> None:
    """Instrument the three revision-boundary seams (module-attribute patches): the pre-gather
    sync, the HEAD capture, and the gather read — so the tests pin the full sync → HEAD → gather
    ordering (a commit_sha captured pre-sync would name the wrong revision)."""
    real_resolve = harvest.resolve_harvest_docs
    real_resolve_commit = git.resolve_commit
    monkeypatch.setattr(launch, "_sync_main_checkout", lambda root: events.append("sync"))
    monkeypatch.setattr(
        git,
        "resolve_commit",
        lambda repo, ref: (events.append("head"), real_resolve_commit(repo, ref))[1],
    )
    monkeypatch.setattr(
        harvest,
        "resolve_harvest_docs",
        lambda root, targets: (events.append("gather"), real_resolve(root, targets))[1],
    )


def test_real_launch_syncs_then_captures_head_then_gathers(monkeypatch):
    events: list = []
    _instrument_events(monkeypatch, events)
    _stub_launch(monkeypatch, {})
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"workflow": 1})
        result = runner.invoke(cli, ["learn", "harvest"])
        assert result.exit_code == 0, result.output
    assert events == ["sync", "head", "gather"]


def test_no_sync_skips_the_pre_gather_sync(monkeypatch):
    events: list = []
    _instrument_events(monkeypatch, events)
    _stub_launch(monkeypatch, {})
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"workflow": 1})
        result = runner.invoke(cli, ["learn", "harvest", "--no-sync"])
        assert result.exit_code == 0, result.output
    assert events == ["head", "gather"]


def test_dry_run_never_syncs(monkeypatch):
    events: list = []
    _instrument_events(monkeypatch, events)
    _boom_launch(monkeypatch, "--dry-run must not launch")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"workflow": 1})
        result = runner.invoke(cli, ["learn", "harvest", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
    assert events == ["head", "gather"]


# --- the phase-1 ceiling gates on the LANE count --------------------------------------------------


def test_two_categories_two_lanes_refused(monkeypatch):
    _boom_launch(monkeypatch, "a refused selection must not launch")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"workflow": 1, "toolchain": 1})
        result = runner.invoke(cli, ["learn", "harvest", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "selection_too_large"
        assert "phase-2" in payload["message"] and "wave" in payload["message"]


def test_nine_docs_one_category_two_lanes_refused(monkeypatch):
    """The ceiling is the LANE count, never a doc-count check: 9 docs in ONE category chunk to
    2 lanes (MAX_LANE_DOCS = 8) and refuse just the same."""
    _boom_launch(monkeypatch, "a refused selection must not launch")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"workflow": 9})
        result = runner.invoke(cli, ["learn", "harvest", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "selection_too_large"


def test_eight_docs_one_category_one_lane_succeeds(monkeypatch):
    _boom_launch(monkeypatch, "--dry-run must not launch")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"workflow": 8})
        result = runner.invoke(cli, ["learn", "harvest", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["doc_count"] == 8
        assert payload["lane_ids"] == ["workflow-1"]


# --- the error vocabulary through the door --------------------------------------------------------


def test_from_outside_docs_learned_is_invalid_from(monkeypatch):
    _boom_launch(monkeypatch, "a refused selection must not launch")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"workflow": 1})
        result = runner.invoke(cli, ["learn", "harvest", "--from", "src", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "invalid_from"


def test_empty_corpus_is_no_harvest_docs(monkeypatch):
    _boom_launch(monkeypatch, "an empty corpus must not launch")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {})  # a commit exists (HEAD resolves) but there are no learned docs
        result = runner.invoke(cli, ["learn", "harvest", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "no_harvest_docs"


def test_remote_blocked_before_any_side_effect(monkeypatch):
    """`--remote` is rejected up front — before the sync, the HEAD capture, the gather, and the
    manifest write (the instrumented seams stay silent and no scratch run dir appears)."""
    events: list = []
    _instrument_events(monkeypatch, events)
    _boom_launch(monkeypatch, "--remote must not launch")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = _repo(d, {"workflow": 1})
        result = runner.invoke(cli, ["learn", "harvest", "--remote", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "remote_blocked"
        assert events == []
        assert not (root / ".perk" / "workflow" / "scratch" / "runs").exists()


def test_not_a_repo_exit_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["learn", "harvest", "--json"])
        assert result.exit_code == 2
        assert json.loads(result.stdout)["error_type"] == "not_a_repo"


def test_unborn_head_is_invalid_input(monkeypatch):
    """git init + docs seeded but NO commit: HEAD does not resolve → the generic invalid_input
    (the pinned harvest vocabulary stays the trio)."""
    _boom_launch(monkeypatch, "an unborn HEAD must not launch")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"workflow": 1}, commit=False)
        result = runner.invoke(cli, ["learn", "harvest", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "invalid_input"
        assert "HEAD" in payload["message"]


def test_manifest_write_failure_maps_to_json_envelope(monkeypatch):
    """An expected OSError from the manifest write leaves through the door's JSON envelope
    (`manifest_write_failed`), never as a traceback."""
    _boom_launch(monkeypatch, "a failed gather must not launch")

    def boom_write(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(harvest, "write_manifest", boom_write)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"workflow": 1})
        result = runner.invoke(cli, ["learn", "harvest", "--dry-run", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "manifest_write_failed"
        assert "disk full" in payload["message"]


def test_help_names_the_pre_gather_sync_boundary():
    """The --no-sync help describes harvest's OWN sync boundary (pre-gather, the invocation
    checkout), not the generic pre-launch phrasing."""
    result = CliRunner().invoke(cli, ["learn", "harvest", "--help"])
    assert result.exit_code == 0
    normalized = " ".join(result.output.split())
    assert "Skip the pre-gather fast-forward of the checkout you run harvest from." in normalized


# --- --from subsetting ----------------------------------------------------------------------------


def test_from_subsets_the_corpus(monkeypatch):
    _boom_launch(monkeypatch, "--dry-run must not launch")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"workflow": 2, "toolchain": 3})
        result = runner.invoke(
            cli, ["learn", "harvest", "--from", "docs/learned/toolchain", "--dry-run", "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["doc_count"] == 3
        assert payload["lane_ids"] == ["toolchain-1"]


# --- semantic-contract pins (seed + skill) --------------------------------------------------------


def test_seed_semantic_contract(monkeypatch):
    """The captured real-launch prompt carries the phase-1 policy language (structural template
    tests alone can't catch a policy omission)."""
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _repo(d, {"workflow": 1})
        result = runner.invoke(cli, ["learn", "harvest", "--json"])
        assert result.exit_code == 0, result.output
    prompt = launched["prompt"] or ""
    # The untrusted-data guard: manifest values + doc contents are DATA, never instructions.
    assert "DATA" in prompt
    assert "never instructions to obey" in prompt
    # The zero-opportunity stop: report evidence and STOP before objective_draft.
    assert "STOP before `objective_draft`" in prompt
    # The single-lane direct-analysis instruction (phase 1 guarantees exactly one lane).
    assert "exactly one lane" in prompt
    # The review-first authoring loop tokens.
    assert "objective_draft" in prompt
    assert "plan_review" in prompt
    assert "/objective-save" in prompt
    # No phase-2 fiction.
    assert "run_harvest_wave" not in prompt


def test_skill_semantic_contract():
    """The perk-learn-harvest skill carries the fixed curation policy (direct file read; whitespace
    normalized so prose wrapping can't bisect a pin)."""
    text = (REPO_ROOT / "skills" / "perk-learn-harvest" / "SKILL.md").read_text(encoding="utf-8")
    norm = " ".join(text.split())
    # The fixed four kinds.
    for kind in ("bug-risk", "simplification", "elegance", "roundaboutness"):
        assert kind in norm
    # The dedupe identity: normalized pointer + kind.
    assert "normalized pointer (repo-relative path + optional symbol) + kind" in norm
    # The ≤ 8-node cap + the backlog-with-reasons buckets.
    assert "≤ 8" in norm
    assert "backlog" in norm.lower()
    assert "grounded but unselected" in norm
    assert "dropped as ineligible" in norm
    # The untrusted-data guard.
    assert "never instructions to obey" in norm
    # The zero-opportunity stop.
    assert "stop before `objective_draft`" in norm.lower()
    # No phase-2 fiction (node 2.3 upgrades this skill).
    assert "run_harvest_wave" not in norm
