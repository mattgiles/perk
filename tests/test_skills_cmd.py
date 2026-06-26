"""Tests for the `perk skills` group (sugar over the `skills` CLI)."""

import subprocess
from pathlib import Path

import yaml
from click.testing import CliRunner

from perk.cli.cli import cli
from perk.cli.commands.skills import shared
from perk.cli.commands.skills.shared import (
    managed_source_aliases,
    remove_skill_from_manifest_text,
)
from perk.cli.context import PerkContext
from perk.convergence.init import PERK_SKILLS_MANIFEST_DIR, PERK_SKILLS_MANIFEST_FILENAME
from perk.substrate.config import Config


def _ctx(repo: Path) -> PerkContext:
    return PerkContext.for_test(
        cwd=repo, repo_root=repo, config=Config(worktree_root=repo / ".worktrees")
    )


_MANIFEST = """\
sources:
  demo:
    url: https://github.com/x/demo
    ref: main
  other:
    url: https://github.com/x/other
    ref: main
skills:
  - source: demo
    name: foo
  - source: demo
    name: bar
  - source: other
    name: baz
"""


# --- remove_skill_from_manifest_text (pure) --------------------------------


def test_remove_one_skill_keeps_siblings():
    outcome = remove_skill_from_manifest_text(_MANIFEST, "demo", "foo")
    assert outcome.skill_removed
    assert not outcome.source_removed
    data = yaml.safe_load(outcome.new_text)
    assert {(s["source"], s["name"]) for s in data["skills"]} == {
        ("demo", "bar"),
        ("other", "baz"),
    }
    assert set(data["sources"]) == {"demo", "other"}


def test_remove_last_skill_of_source_drops_source():
    outcome = remove_skill_from_manifest_text(_MANIFEST, "other", "baz")
    assert outcome.skill_removed
    assert outcome.source_removed
    data = yaml.safe_load(outcome.new_text)
    assert set(data["sources"]) == {"demo"}
    assert all(s["source"] != "other" for s in data["skills"])


def test_remove_nonmatching_skill_is_noop():
    outcome = remove_skill_from_manifest_text(_MANIFEST, "demo", "nope")
    assert not outcome.skill_removed
    assert not outcome.source_removed
    data = yaml.safe_load(outcome.new_text)
    assert len(data["skills"]) == 3


def test_remove_nonmatching_source_is_noop():
    outcome = remove_skill_from_manifest_text(_MANIFEST, "ghost", "foo")
    assert not outcome.skill_removed
    assert not outcome.source_removed


def test_remove_handles_empty_manifest():
    outcome = remove_skill_from_manifest_text("", "demo", "foo")
    assert not outcome.skill_removed
    assert not outcome.source_removed


def test_remove_handles_flow_manifest():
    text = "{sources: {demo: {url: u, ref: main}}, skills: [{source: demo, name: foo}]}"
    outcome = remove_skill_from_manifest_text(text, "demo", "foo")
    assert outcome.skill_removed
    assert outcome.source_removed
    data = yaml.safe_load(outcome.new_text)
    assert data.get("sources") in ({}, None) or "demo" not in data["sources"]


# --- managed_source_aliases ------------------------------------------------


def test_managed_source_aliases_reads_fragment(tmp_path: Path):
    fragment = tmp_path / PERK_SKILLS_MANIFEST_DIR / PERK_SKILLS_MANIFEST_FILENAME
    fragment.parent.mkdir(parents=True)
    fragment.write_text(
        yaml.safe_dump({"sources": {"perk": {}, "astral": {}}, "skills": []}), encoding="utf-8"
    )
    assert managed_source_aliases(tmp_path) == {"perk", "astral"}


def test_managed_source_aliases_empty_when_absent(tmp_path: Path):
    assert managed_source_aliases(tmp_path) == set()


# --- pass-through argv mapping ---------------------------------------------


class _FakeProc:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.stderr = ""


def _patch_skills(monkeypatch, *, returncode: int = 0):
    """Patch `shutil.which` + `subprocess.run` in the shared module; record the argv."""
    calls: list[list[str]] = []
    monkeypatch.setattr(shared.shutil, "which", lambda _name: "/usr/bin/skills")

    def fake_run(args, **_kwargs):
        calls.append(args)
        return _FakeProc(returncode)

    monkeypatch.setattr(shared.subprocess, "run", fake_run)
    return calls


def test_list_argv(monkeypatch, tmp_path):
    calls = _patch_skills(monkeypatch)
    result = CliRunner().invoke(cli, ["skills", "list"], obj=_ctx(tmp_path))
    assert result.exit_code == 0
    assert calls == [["skills", "skill", "list"]]


def test_status_argv(monkeypatch, tmp_path):
    calls = _patch_skills(monkeypatch)
    result = CliRunner().invoke(cli, ["skills", "status"], obj=_ctx(tmp_path))
    assert result.exit_code == 0
    assert calls == [["skills", "status"]]


def test_sync_argv(monkeypatch, tmp_path):
    calls = _patch_skills(monkeypatch)
    result = CliRunner().invoke(cli, ["skills", "sync"], obj=_ctx(tmp_path))
    assert result.exit_code == 0
    assert calls == [["skills", "update", "--sync"]]


def test_add_argv_full(monkeypatch, tmp_path):
    calls = _patch_skills(monkeypatch)
    result = CliRunner().invoke(
        cli,
        [
            "skills",
            "add",
            "--source",
            "SRC",
            "--skill",
            "SK",
            "--source-url",
            "URL",
            "--ref",
            "REF",
        ],
        obj=_ctx(tmp_path),
    )
    assert result.exit_code == 0
    assert calls == [["skills", "add", "SRC", "SK", "--url", "URL", "--ref", "REF"]]


def test_add_argv_minimal(monkeypatch, tmp_path):
    calls = _patch_skills(monkeypatch)
    result = CliRunner().invoke(
        cli, ["skills", "add", "--source", "SRC", "--skill", "SK"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 0
    assert calls == [["skills", "add", "SRC", "SK"]]


def test_passthrough_propagates_exit_code(monkeypatch, tmp_path):
    _patch_skills(monkeypatch, returncode=2)
    result = CliRunner().invoke(cli, ["skills", "list"], obj=_ctx(tmp_path))
    assert result.exit_code == 2


def test_passthrough_errors_when_skills_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(shared.shutil, "which", lambda _name: None)
    result = CliRunner().invoke(cli, ["skills", "list"], obj=_ctx(tmp_path))
    assert result.exit_code == 1
    assert "not on PATH" in result.output


def test_passthrough_maps_timeout_to_cli_error(monkeypatch, tmp_path):
    monkeypatch.setattr(shared.shutil, "which", lambda _name: "/usr/bin/skills")

    def fake_run(args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=shared.SKILLS_TIMEOUT_S)

    monkeypatch.setattr(shared.subprocess, "run", fake_run)
    result = CliRunner().invoke(cli, ["skills", "list"], obj=_ctx(tmp_path))
    assert result.exit_code == 1
    assert "timed out" in result.output


def test_passthrough_maps_oserror_to_cli_error(monkeypatch, tmp_path):
    monkeypatch.setattr(shared.shutil, "which", lambda _name: "/usr/bin/skills")

    def fake_run(args, **_kwargs):
        raise OSError("exec format error")

    monkeypatch.setattr(shared.subprocess, "run", fake_run)
    result = CliRunner().invoke(cli, ["skills", "status"], obj=_ctx(tmp_path))
    assert result.exit_code == 1
    assert "could not run `skills`" in result.output


# --- remove -----------------------------------------------------------------


def _write_main_manifest(repo: Path, text: str = _MANIFEST) -> Path:
    manifest = repo / ".agents" / "manifest.yaml"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(text, encoding="utf-8")
    return manifest


def test_remove_refuses_managed_source(monkeypatch, tmp_path):
    fragment = tmp_path / PERK_SKILLS_MANIFEST_DIR / PERK_SKILLS_MANIFEST_FILENAME
    fragment.parent.mkdir(parents=True)
    fragment.write_text(yaml.safe_dump({"sources": {"perk": {}}, "skills": []}), encoding="utf-8")
    manifest = _write_main_manifest(tmp_path)
    before = manifest.read_text(encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["skills", "remove", "--source", "perk", "--skill", "x"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 1
    assert "perk init" in result.output
    assert manifest.read_text(encoding="utf-8") == before


def test_remove_errors_on_absent_manifest(tmp_path):
    result = CliRunner().invoke(
        cli, ["skills", "remove", "--source", "demo", "--skill", "foo"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 1
    assert "manifest.yaml" in result.output


def test_remove_errors_on_undeclared_skill(tmp_path):
    manifest = _write_main_manifest(tmp_path)
    before = manifest.read_text(encoding="utf-8")
    result = CliRunner().invoke(
        cli, ["skills", "remove", "--source", "demo", "--skill", "nope"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 1
    assert "not declared" in result.output
    assert manifest.read_text(encoding="utf-8") == before


def test_remove_happy_path_writes_and_syncs(monkeypatch, tmp_path):
    manifest = _write_main_manifest(tmp_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(shared.shutil, "which", lambda _name: "/usr/bin/skills")

    def fake_run(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("perk.cli.commands.skills.rm_cmd.subprocess.run", fake_run)

    result = CliRunner().invoke(
        cli, ["skills", "remove", "--source", "demo", "--skill", "foo"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 0, result.output
    assert calls == [["skills", "sync"]]
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert {(s["source"], s["name"]) for s in data["skills"]} == {
        ("demo", "bar"),
        ("other", "baz"),
    }


def test_remove_last_skill_drops_source_and_reports(monkeypatch, tmp_path):
    # Removing the only skill under `other` must drop the source on disk AND emit both messages.
    manifest = _write_main_manifest(tmp_path)
    monkeypatch.setattr(shared.shutil, "which", lambda _name: "/usr/bin/skills")
    monkeypatch.setattr(
        "perk.cli.commands.skills.rm_cmd.subprocess.run",
        lambda args, **_kwargs: subprocess.CompletedProcess(args, 0, stdout="", stderr=""),
    )

    result = CliRunner().invoke(
        cli, ["skills", "remove", "--source", "other", "--skill", "baz"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 0, result.output
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert "other" not in data["sources"]
    assert all(s["source"] != "other" for s in data["skills"])
    assert "removed skill `baz` from source `other`" in result.output
    assert "removed source `other`" in result.output


def test_remove_restores_on_sync_failure(monkeypatch, tmp_path):
    manifest = _write_main_manifest(tmp_path)
    before = manifest.read_text(encoding="utf-8")
    monkeypatch.setattr(shared.shutil, "which", lambda _name: "/usr/bin/skills")

    def fake_run(args, **_kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")

    monkeypatch.setattr("perk.cli.commands.skills.rm_cmd.subprocess.run", fake_run)

    result = CliRunner().invoke(
        cli, ["skills", "remove", "--source", "demo", "--skill", "foo"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 1
    assert "boom" in result.output
    assert manifest.read_text(encoding="utf-8") == before


def test_remove_restores_when_skills_missing(monkeypatch, tmp_path):
    # `remove` has its own PATH check + rollback, independent of the pass-through verbs.
    manifest = _write_main_manifest(tmp_path)
    before = manifest.read_text(encoding="utf-8")
    monkeypatch.setattr(shared.shutil, "which", lambda _name: None)

    result = CliRunner().invoke(
        cli, ["skills", "remove", "--source", "demo", "--skill", "foo"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 1
    assert "not on PATH" in result.output
    assert manifest.read_text(encoding="utf-8") == before


def test_remove_restores_on_sync_timeout(monkeypatch, tmp_path):
    manifest = _write_main_manifest(tmp_path)
    before = manifest.read_text(encoding="utf-8")
    monkeypatch.setattr(shared.shutil, "which", lambda _name: "/usr/bin/skills")

    def fake_run(args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=shared.SKILLS_TIMEOUT_S)

    monkeypatch.setattr("perk.cli.commands.skills.rm_cmd.subprocess.run", fake_run)

    result = CliRunner().invoke(
        cli, ["skills", "remove", "--source", "demo", "--skill", "foo"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 1
    assert "timed out" in result.output
    assert manifest.read_text(encoding="utf-8") == before


def test_remove_restores_on_sync_oserror(monkeypatch, tmp_path):
    manifest = _write_main_manifest(tmp_path)
    before = manifest.read_text(encoding="utf-8")
    monkeypatch.setattr(shared.shutil, "which", lambda _name: "/usr/bin/skills")

    def fake_run(args, **_kwargs):
        raise OSError("exec format error")

    monkeypatch.setattr("perk.cli.commands.skills.rm_cmd.subprocess.run", fake_run)

    result = CliRunner().invoke(
        cli, ["skills", "remove", "--source", "demo", "--skill", "foo"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 1
    assert "could not run `skills sync`" in result.output
    assert manifest.read_text(encoding="utf-8") == before


# --- scaffold / delete (repo-authored skills) -------------------------------

import json  # noqa: E402
import types  # noqa: E402

from perk.cli.commands.skills import create_cmd, delete_cmd, refine_cmd  # noqa: E402
from perk.convergence.init.repo_skills import (  # noqa: E402
    RepoSkill,
    RepoSkillsConvergence,
    RepoSkillsManifest,
    parse_skill_frontmatter,
    validate_skill,
)


def _fake_conv(
    *, changes: list[str], errors: tuple[str, ...] = (), warnings: tuple[str, ...] = ()
) -> RepoSkillsConvergence:
    """A canned convergence so scaffold/delete tests stay offline (no `github.repo_identity`)."""
    manifest = RepoSkillsManifest(fragment="...", skills=(), errors=errors, warnings=warnings)
    return RepoSkillsConvergence(changes=list(changes), manifest=manifest)


_DEFAULT_CHANGE = ".agents/manifest.d/perk-repo-skills.yaml: created"


def _patch_repo_skills(monkeypatch, *, changes=None, errors=(), warnings=()):
    """Pin the main checkout to tmp_path and stub the (network) reconvergence. Returns call log."""
    monkeypatch.setattr(shared.git, "main_worktree_root", lambda _root: None)
    resolved_changes = [_DEFAULT_CHANGE] if changes is None else changes
    calls: list[bool] = []

    def fake_converge(root, *, apply=True):
        calls.append(apply)
        return _fake_conv(changes=resolved_changes, errors=errors, warnings=warnings)

    # `scaffold`/`create` reconverge via `shared.perform_scaffold`, which reads the convergence
    # through the `shared` namespace; `delete` keeps its own import.
    monkeypatch.setattr(shared, "converge_repo_skills_manifest", fake_converge)
    monkeypatch.setattr(delete_cmd, "converge_repo_skills_manifest", fake_converge)
    return calls


def test_scaffold_happy_path(monkeypatch, tmp_path):
    calls = _patch_repo_skills(monkeypatch)
    result = CliRunner().invoke(cli, ["skills", "scaffold", "foo"], obj=_ctx(tmp_path))
    assert result.exit_code == 0, result.output

    skill_md = tmp_path / ".pi" / "skills" / "foo" / "SKILL.md"
    assert skill_md.is_file()
    mapping, reason = parse_skill_frontmatter(skill_md.read_text(encoding="utf-8"))
    assert reason is None
    skill, vreason = validate_skill("foo", mapping)
    assert vreason is None
    assert isinstance(skill, RepoSkill)
    assert calls == [True]


def test_scaffold_refuses_existing(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch)
    target = tmp_path / ".pi" / "skills" / "foo"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("preexisting", encoding="utf-8")

    result = CliRunner().invoke(cli, ["skills", "scaffold", "foo", "--json"], obj=_ctx(tmp_path))
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "skills_exists"
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "preexisting"


def test_scaffold_invalid_names(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch)
    for bad in ("foo/bar", "", ".", "..", ".hidden"):
        result = CliRunner().invoke(cli, ["skills", "scaffold", bad, "--json"], obj=_ctx(tmp_path))
        assert result.exit_code == 1, bad
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "skills_invalid_name", bad
    assert not (tmp_path / ".pi" / "skills").exists()


def test_scaffold_json_success_shape(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch)
    result = CliRunner().invoke(cli, ["skills", "scaffold", "foo", "--json"], obj=_ctx(tmp_path))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {
        "success": True,
        "error_type": None,
        "name": "foo",
        "path": ".pi/skills/foo",
        "fragment": "created",
        "warnings": [],
        "errors": [],
    }


def test_scaffold_reconverge_errors_nonfatal(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch, changes=[], errors=("boom",))
    result = CliRunner().invoke(cli, ["skills", "scaffold", "foo", "--json"], obj=_ctx(tmp_path))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["errors"] == ["boom"]
    assert payload["fragment"] == "none"
    assert (tmp_path / ".pi" / "skills" / "foo" / "SKILL.md").is_file()


def test_delete_yes_removes(monkeypatch, tmp_path):
    calls = _patch_repo_skills(
        monkeypatch, changes=[".agents/manifest.d/perk-repo-skills.yaml: removed"]
    )
    target = tmp_path / ".pi" / "skills" / "foo"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("x", encoding="utf-8")

    result = CliRunner().invoke(cli, ["skills", "delete", "foo", "--yes"], obj=_ctx(tmp_path))
    assert result.exit_code == 0, result.output
    assert not target.exists()
    assert calls == [True]


def _fake_isatty(monkeypatch, *, value: bool):
    """Swap delete_cmd's `sys` for a fake (CliRunner clobbers the real `sys.stdin` mid-invoke)."""
    monkeypatch.setattr(
        delete_cmd, "sys", types.SimpleNamespace(stdin=types.SimpleNamespace(isatty=lambda: value))
    )


def test_delete_non_interactive_refuses(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch)
    _fake_isatty(monkeypatch, value=False)
    target = tmp_path / ".pi" / "skills" / "foo"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("x", encoding="utf-8")

    result = CliRunner().invoke(cli, ["skills", "delete", "foo"], obj=_ctx(tmp_path))
    assert result.exit_code == 1
    assert ".pi/skills/foo" in result.output
    assert target.exists()


def test_delete_json_refuses_without_yes(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch)
    target = tmp_path / ".pi" / "skills" / "foo"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("x", encoding="utf-8")

    result = CliRunner().invoke(cli, ["skills", "delete", "foo", "--json"], obj=_ctx(tmp_path))
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "confirmation_required"
    assert target.exists()


def test_delete_interactive_declined(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch)
    _fake_isatty(monkeypatch, value=True)
    monkeypatch.setattr("perk.cli.commands.skills.delete_cmd.user_confirm", lambda *a, **k: False)
    target = tmp_path / ".pi" / "skills" / "foo"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("x", encoding="utf-8")

    result = CliRunner().invoke(cli, ["skills", "delete", "foo"], obj=_ctx(tmp_path))
    assert result.exit_code == 1
    assert "aborted" in result.output
    assert target.exists()


def test_delete_absent_dir(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch)
    result = CliRunner().invoke(
        cli, ["skills", "delete", "foo", "--yes", "--json"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "skills_not_found"


def test_delete_unlinks_dangling_symlink(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch)
    target = tmp_path / ".pi" / "skills" / "foo"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("x", encoding="utf-8")
    links = tmp_path / ".agents" / "skills"
    links.mkdir(parents=True)
    (links / "foo").symlink_to(target)

    result = CliRunner().invoke(
        cli, ["skills", "delete", "foo", "--yes", "--json"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["symlink_removed"] is True
    assert not (links / "foo").exists()
    assert not (links / "foo").is_symlink()


def test_delete_json_success_shape(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch, changes=[".agents/manifest.d/perk-repo-skills.yaml: removed"])
    target = tmp_path / ".pi" / "skills" / "foo"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("x", encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["skills", "delete", "foo", "--yes", "--json"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {
        "success": True,
        "error_type": None,
        "name": "foo",
        "path": ".pi/skills/foo",
        "fragment": "removed",
        "warnings": [],
        "errors": [],
        "symlink_removed": False,
    }


# --- create (authoring cold door) -------------------------------------------


def _stub_launch(monkeypatch):
    """Stub `launch.launch_stage` into a sink so create records kwargs without exec'ing pi."""
    calls: list[dict] = []

    def fake_launch(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(create_cmd.launch, "launch_stage", fake_launch)
    return calls


def test_create_dry_run_does_not_scaffold_or_launch(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch)
    calls = _stub_launch(monkeypatch)
    result = CliRunner().invoke(
        cli, ["skills", "create", "foo", "--dry-run", "--json"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {
        "success": True,
        "error_type": None,
        "name": "foo",
        "path": ".pi/skills/foo",
        "dry_run": True,
    }
    assert not (tmp_path / ".pi" / "skills" / "foo").exists()
    assert calls == []


def test_create_real_run_scaffolds_then_launches(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch)
    calls = _stub_launch(monkeypatch)
    result = CliRunner().invoke(cli, ["skills", "create", "foo"], obj=_ctx(tmp_path))
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".pi" / "skills" / "foo" / "SKILL.md").is_file()
    assert len(calls) == 1
    kwargs = calls[0]
    assert kwargs["binding_trigger"] == "command:skills-create"
    assert kwargs["stage"].id == "save"
    assert kwargs["worktree"] is None
    assert kwargs["remote"] is None


def test_create_refuses_existing(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch)
    calls = _stub_launch(monkeypatch)
    target = tmp_path / ".pi" / "skills" / "foo"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("preexisting", encoding="utf-8")

    result = CliRunner().invoke(cli, ["skills", "create", "foo", "--json"], obj=_ctx(tmp_path))
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "skills_exists"
    assert "refine" in payload["message"]
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "preexisting"
    assert calls == []


def test_create_invalid_names(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch)
    _stub_launch(monkeypatch)
    for bad in ("foo/bar", "", ".", "..", ".hidden"):
        result = CliRunner().invoke(cli, ["skills", "create", bad, "--json"], obj=_ctx(tmp_path))
        assert result.exit_code == 1, bad
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "skills_invalid_name", bad
    assert not (tmp_path / ".pi" / "skills").exists()


def test_create_refuses_existing_dry_run(monkeypatch, tmp_path):
    # The existence-refusal runs on every path, including --dry-run.
    _patch_repo_skills(monkeypatch)
    calls = _stub_launch(monkeypatch)
    target = tmp_path / ".pi" / "skills" / "foo"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("preexisting", encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["skills", "create", "foo", "--dry-run", "--json"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "skills_exists"
    assert calls == []


# --- refine (refine cold door) ----------------------------------------------


def _stub_refine_launch(monkeypatch):
    """Stub `launch.launch_stage` into a sink so refine records kwargs without exec'ing pi."""
    calls: list[dict] = []

    def fake_launch(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(refine_cmd.launch, "launch_stage", fake_launch)
    return calls


def _write_skill(tmp_path: Path, name: str = "foo", body: str = "existing") -> Path:
    target = tmp_path / ".pi" / "skills" / name
    target.mkdir(parents=True)
    skill_md = target / "SKILL.md"
    skill_md.write_text(body, encoding="utf-8")
    return skill_md


def test_refine_dry_run_does_not_launch(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch)
    calls = _stub_refine_launch(monkeypatch)
    _write_skill(tmp_path)
    result = CliRunner().invoke(
        cli, ["skills", "refine", "foo", "--dry-run", "--json"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {
        "success": True,
        "error_type": None,
        "name": "foo",
        "path": ".pi/skills/foo",
        "dry_run": True,
    }
    assert calls == []


def test_refine_real_run_launches(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch)
    calls = _stub_refine_launch(monkeypatch)
    skill_md = _write_skill(tmp_path)
    result = CliRunner().invoke(cli, ["skills", "refine", "foo"], obj=_ctx(tmp_path))
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    kwargs = calls[0]
    assert kwargs["binding_trigger"] == "command:skills-refine"
    assert kwargs["stage"].id == "save"
    assert kwargs["worktree"] is None
    assert kwargs["remote"] is None
    # The door is read-only on the filesystem until the launched session edits.
    assert skill_md.read_text(encoding="utf-8") == "existing"


def test_refine_refuses_absent(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch)
    calls = _stub_refine_launch(monkeypatch)
    result = CliRunner().invoke(cli, ["skills", "refine", "foo", "--json"], obj=_ctx(tmp_path))
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "skills_not_found"
    assert "create" in payload["message"]
    assert calls == []


def test_refine_refuses_absent_dry_run(monkeypatch, tmp_path):
    # The absent-skill refusal runs on every path, including --dry-run.
    _patch_repo_skills(monkeypatch)
    calls = _stub_refine_launch(monkeypatch)
    result = CliRunner().invoke(
        cli, ["skills", "refine", "foo", "--dry-run", "--json"], obj=_ctx(tmp_path)
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "skills_not_found"
    assert calls == []


def test_refine_invalid_names(monkeypatch, tmp_path):
    _patch_repo_skills(monkeypatch)
    _stub_refine_launch(monkeypatch)
    for bad in ("foo/bar", "", ".", "..", ".hidden"):
        result = CliRunner().invoke(cli, ["skills", "refine", bad, "--json"], obj=_ctx(tmp_path))
        assert result.exit_code == 1, bad
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "skills_invalid_name", bad
