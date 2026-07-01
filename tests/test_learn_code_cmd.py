"""hop-2 — `perk learn code`: the code-routing plan-factory cold door (sibling of `learn docs`).

`plans.list_learn_issues` + `launch.launch_stage` are stubbed (no GitHub, no `exec pi`), mirroring
test_learn_docs_cmd.py.
"""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, plan
from perk.backends.github import plans
from perk.cli.cli import cli
from perk.run import launch

_INBOX_REL = ".perk/workflow/scratch/learn-code-inbox.md"


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _learn_body(text: str, *, decision: str | None = None, target: str | None = None) -> str:
    header = plan.render_learn_header(
        run_id="01RID", created="t", plan=1, decision=decision, target=target
    )
    return f"{text}\n\n{header}"


def _mixed_issues():
    return (
        plans.LearnIssueSummary(number=45, title="L45", url="u/45", body="legacy unclassified"),
        plans.LearnIssueSummary(
            number=46, title="L46", url="u/46", body=_learn_body("doc one", decision="NEW_DOC")
        ),
        plans.LearnIssueSummary(
            number=47,
            title="L47",
            url="u/47",
            body=_learn_body("code one", decision="SHOULD_BE_CODE", target="perk/foo.py::bar"),
        ),
        plans.LearnIssueSummary(
            number=48,
            title="L48",
            url="u/48",
            body=_learn_body("code two", decision="SHOULD_BE_CODE"),
        ),
    )


def _stub_list(monkeypatch, issues=None) -> None:
    monkeypatch.setattr(
        plans, "list_learn_issues", lambda **k: _mixed_issues() if issues is None else issues
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


def test_code_factory_filters_in_only_should_be_code(monkeypatch):
    _authed(monkeypatch)
    _stub_list(monkeypatch)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["learn", "code", "--json"])
        assert result.exit_code == 0, result.output
    # Only the two SHOULD_BE_CODE issues are routed here.
    assert launched["handoff_extra"] == {"consumed_learn": ["47", "48"]}
    assert launched["binding_trigger"] == "command:learn-code"
    assert launched["stage"] == "plan"  # borrows the plan stage to launch
    prompt = launched["prompt"] or ""
    assert _INBOX_REL in prompt
    assert "consumed_learn: [47, 48]" in prompt


def test_code_inbox_carries_classification_target_no_scan(monkeypatch):
    _authed(monkeypatch)
    _stub_list(monkeypatch)

    def boom_launch(**k):
        raise AssertionError("--gather must not launch")

    monkeypatch.setattr(launch, "launch_stage", boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["learn", "code", "--gather", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["learn_numbers"] == ["47", "48"]
        text = (Path(d) / _INBOX_REL).read_text(encoding="utf-8")
        assert "Learning #47" in text and "Learning #48" in text
        assert "Learning #45" not in text and "Learning #46" not in text
        assert "**classification:** SHOULD_BE_CODE" in text
        assert "→ target: `perk/foo.py::bar`" in text
        # The code inbox stays lean — NO docs-scan section.
        assert "## Existing docs (scan)" not in text


def test_code_empty_inbox_cross_hints_docs(monkeypatch):
    """Only doc-destined issues present → the code factory has nothing → exit 1 + cross-hint."""
    _authed(monkeypatch)
    _stub_list(
        monkeypatch,
        issues=(
            plans.LearnIssueSummary(number=45, title="L45", url="u/45", body="legacy"),
            plans.LearnIssueSummary(
                number=46, title="L46", url="u/46", body=_learn_body("doc", decision="NEW_DOC")
            ),
        ),
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["learn", "code", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "no_learn_issues"
        assert "perk learn docs" in payload["message"]


def test_code_gather_narrates_without_docs_scan(monkeypatch):
    """The code factory narrates the listing wait but omits the docs-scan line (lean inbox)."""
    _authed(monkeypatch)
    _stub_list(monkeypatch)

    def boom_launch(**k):
        raise AssertionError("--gather must not launch")

    monkeypatch.setattr(launch, "launch_stage", boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["learn", "code", "--gather"])
        assert result.exit_code == 0, result.output
        err = result.stderr
        assert "listing open perk:learn issues" in err
        # The code factory omits the docs scan (kind.include_docs_scan is False).
        assert "scanning existing docs" not in err


def test_code_remote_blocked(monkeypatch):
    _authed(monkeypatch)
    _stub_list(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["learn", "code", "--remote", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "remote_blocked"


def test_code_not_a_repo_exit_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["learn", "code", "--json"])
        assert result.exit_code == 2
        assert json.loads(result.stdout)["error_type"] == "not_a_repo"
