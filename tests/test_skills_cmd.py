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
