"""`perk replan <plan>`: the in-place plan re-authoring cold door.

`plans.get_plan`, `plans.get_plan_body`, and `launch.launch_stage` are stubbed (no GitHub, no
`exec pi`), mirroring test_learn_docs_cmd.py.
"""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github
from perk.backends.github import engagement as gh_engagement
from perk.backends.github import plans
from perk.cli.cli import cli
from perk.run import launch

_SCRATCH_REL = ".perk/workflow/scratch/replan-42.md"
_RUN_ID = "01ABCDEF0123456789ABCDEFGH"


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _plan_state(*, state: str = "OPEN", run_id: str | None = _RUN_ID) -> plans.PlanState:
    header: dict[str, object] = {}
    if run_id is not None:
        header["run_id"] = run_id
    return plans.PlanState(
        number=42, url="u/42", title="The plan", header=header, pr=None, state=state
    )


def _comment_row(body: str, *, is_bot: bool = False) -> gh_engagement.IssueCommentRow:
    return gh_engagement.IssueCommentRow(
        id="c1",
        body=body,
        created_at="2026-03-01T10:00:00Z",
        edited_at=None,
        author_login="ada",
        author_id="u-1",
        author_is_bot=is_bot,
    )


def _stub_plan(
    monkeypatch, *, plan_state=None, body="EXISTING PLAN BODY", comments=None, edits=None
) -> None:
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: _plan_state() if plan_state is None else plan_state,
    )
    monkeypatch.setattr(plans, "get_plan_body", lambda **k: body)
    monkeypatch.setattr(gh_engagement, "read_issue_comments", lambda **k: list(comments or []))
    monkeypatch.setattr(gh_engagement, "read_description_edits", lambda **k: list(edits or []))


def _stub_launch(monkeypatch, sink: dict) -> None:
    monkeypatch.setattr(
        launch,
        "launch_stage",
        lambda **k: sink.update(
            stage=k["stage"].id,
            prompt=k.get("prompt_override"),
            run_id_override=k.get("run_id_override"),
            binding_trigger=k.get("binding_trigger"),
        ),
    )


def test_dry_run_json_materializes_and_does_not_launch(monkeypatch):
    _authed(monkeypatch)
    _stub_plan(monkeypatch)

    def boom_launch(**k):
        raise AssertionError("--dry-run must not launch")

    monkeypatch.setattr(launch, "launch_stage", boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "replan", "42", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["success"] is True
        assert payload["plan"] == "42"
        assert payload["run_id"] == _RUN_ID
        scratch = (Path(d) / _SCRATCH_REL).resolve()
        assert Path(payload["scratch_path"]).resolve() == scratch
        assert payload["scratch_path"].endswith(_SCRATCH_REL)
        # The scratch file wraps the prior body as untrusted DATA.
        assert scratch.is_file()
        text = scratch.read_text(encoding="utf-8")
        assert "<untrusted_plan>" in text and "EXISTING PLAN BODY" in text
        assert "looking up" not in result.stderr  # the lookup line is gated off the dry-run path


def test_real_launch_threads_run_id_override_and_seed(monkeypatch):
    _authed(monkeypatch)
    _stub_plan(monkeypatch)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "replan", "42", "--json"])
        assert result.exit_code == 0, result.output
        assert "looking up plan #42" in result.stderr  # narrates the backend lookup wait
    assert launched["stage"] == "plan"  # borrows the plan stage
    assert launched["run_id_override"] == _RUN_ID  # re-enters the existing plan's run
    assert launched["binding_trigger"] == "command:replan"
    prompt = launched["prompt"] or ""
    assert _SCRATCH_REL in prompt
    assert "perk-replan" in prompt
    assert "plan_save" in prompt


def test_empty_engagement_scratch_and_seed_byte_unchanged(monkeypatch):
    # No comments/edits → no <untrusted_plan_engagement> block, no engagement clause in the seed.
    _authed(monkeypatch)
    _stub_plan(monkeypatch)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "replan", "42", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
    assert "<untrusted_plan_engagement>" not in text
    assert "<untrusted_plan_engagement>" not in (launched["prompt"] or "")


def test_with_engagement_appends_block_and_points_seed(monkeypatch):
    _authed(monkeypatch)
    _stub_plan(monkeypatch, comments=[_comment_row("please rescope this plan")])
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "replan", "42", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
    assert "<untrusted_plan_engagement>" in text
    assert "please rescope this plan" in text
    assert "<untrusted_plan_engagement>" in (launched["prompt"] or "")


def test_engagement_read_failure_is_fail_soft(monkeypatch):
    # A backend hiccup on the engagement read must never abort the launch — the block is omitted.
    _authed(monkeypatch)
    _stub_plan(monkeypatch)

    def boom(**k):
        raise github.GitHubError("gh exploded")

    monkeypatch.setattr(gh_engagement, "read_issue_comments", boom)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "replan", "42", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
    assert "<untrusted_plan_engagement>" not in text


def test_refuses_non_open_plan(monkeypatch):
    _authed(monkeypatch)
    _stub_plan(monkeypatch, plan_state=_plan_state(state="CLOSED"))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "replan", "42", "--json"])
        assert result.exit_code == 1
        # Parse stdout: the real-path `looking up #42` line is on stderr (combined .output).
        assert json.loads(result.stdout)["error_type"] == "plan_not_open"


def test_refuses_missing_plan(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "replan", "42", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "plan_not_found"


def test_refuses_plan_without_run_id(monkeypatch):
    _authed(monkeypatch)
    _stub_plan(monkeypatch, plan_state=_plan_state(run_id=None))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "replan", "42", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "no_run_id"


def test_refuses_empty_body(monkeypatch):
    _authed(monkeypatch)
    _stub_plan(monkeypatch, body="")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "replan", "42", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "no_plan_body"


def test_remote_blocked(monkeypatch):
    _authed(monkeypatch)
    _stub_plan(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "replan", "42", "--remote", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "remote_blocked"


def test_invalid_plan_id_rejected(monkeypatch):
    # Ids are opaque strings now — only empty / path-unsafe ids are rejected up front.
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "replan", "bad/id", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "invalid_input"


def test_accepts_hash_prefixed_plan_id(monkeypatch):
    _authed(monkeypatch)
    _stub_plan(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "replan", "#42", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["plan"] == "42"


def test_not_a_repo_exit_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["plan", "replan", "42", "--json"])
        assert result.exit_code == 2
        assert json.loads(result.output)["error_type"] == "not_a_repo"
