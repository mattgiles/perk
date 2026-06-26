"""hop-2 — `perk learn docs`: the learned-docs plan-factory cold door.

`plans.list_learn_issues` + `launch.launch_stage` are stubbed (no GitHub, no `exec pi`), mirroring
test_objective_plan_cmd.py.
"""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github
from perk.backends.github import plans
from perk.cli.cli import cli
from perk.run import launch

_INBOX_REL = ".perk/workflow/scratch/learn-docs-inbox.md"


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _issues():
    return (
        plans.LearnIssueSummary(number=45, title="L45", url="u/45", body="learned forty-five"),
        plans.LearnIssueSummary(number=50, title="L50", url="u/50", body="learned fifty"),
    )


def _stub_list(monkeypatch, issues=None) -> None:
    monkeypatch.setattr(
        plans, "list_learn_issues", lambda **k: _issues() if issues is None else issues
    )


def _stub_launch(monkeypatch, sink: dict) -> None:
    monkeypatch.setattr(
        launch,
        "launch_stage",
        lambda **k: sink.update(
            stage=k["stage"].id,
            prompt=k.get("prompt_override"),
            binding_trigger=k.get("binding_trigger"),
            handoff_extra=k.get("handoff_extra"),
        ),
    )


def test_gather_writes_inbox_and_emits_numbers(monkeypatch):
    _authed(monkeypatch)
    _stub_list(monkeypatch)

    def boom_launch(**k):
        raise AssertionError("--gather must not launch")

    monkeypatch.setattr(launch, "launch_stage", boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["learn", "docs", "--gather", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["success"] is True and payload["launched"] is False
        assert payload["learn_numbers"] == ["45", "50"]  # opaque string ids (contracts §8.21)
        inbox = Path(d) / _INBOX_REL
        assert inbox.is_file()
        text = inbox.read_text(encoding="utf-8")
        assert "Learning #45" in text and "Learning #50" in text
        assert "<untrusted_learning>" in text and "learned forty-five" in text


def test_dry_run_gathers_prints_seed_and_does_not_launch(monkeypatch):
    _authed(monkeypatch)
    _stub_list(monkeypatch)

    def boom_launch(**k):
        raise AssertionError("--dry-run must not launch")

    monkeypatch.setattr(launch, "launch_stage", boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["learn", "docs", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert (Path(d) / _INBOX_REL).is_file()
        # The seed names the inbox path + the gathered numbers.
        assert _INBOX_REL in result.output
        assert "consumed_learn: [45, 50]" in result.output


def test_launches_with_inbox_seeded_prompt(monkeypatch):
    _authed(monkeypatch)
    _stub_list(monkeypatch)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["learn", "docs", "--json"])
        assert result.exit_code == 0, result.output
    assert launched["stage"] == "plan"  # borrows the plan stage to launch
    # learn-docs borrows `plan` but overrides the binding trigger to its command — so a
    # stage:plan user binding does NOT bleed into the learn-docs launch.
    assert launched["binding_trigger"] == "command:learn-docs"
    # The gathered perk:learn numbers ride the handoff so `perk plan-save` recovers
    # `consumed_learn` even when the read-only factory saves via the /plan-save command.
    assert launched["handoff_extra"] == {"consumed_learn": ["45", "50"]}
    prompt = launched["prompt"] or ""
    assert _INBOX_REL in prompt
    assert "consumed_learn: [45, 50]" in prompt
    # The perk-learn-docs skill pointer is no longer hardcoded in the seed — it rides the
    # skill-binding mechanism (command:learn-docs).
    assert "perk-learn-docs" not in prompt


def test_no_learn_issues_exits_1(monkeypatch):
    _authed(monkeypatch)
    _stub_list(monkeypatch, issues=())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["learn", "docs", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "no_learn_issues"


def test_remote_blocked(monkeypatch):
    _authed(monkeypatch)
    _stub_list(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["learn", "docs", "--remote", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "remote_blocked"


def test_not_a_repo_exit_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["learn", "docs", "--json"])
        assert result.exit_code == 2
        assert json.loads(result.output)["error_type"] == "not_a_repo"
