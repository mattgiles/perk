"""`perk plan from <issue>`: the in-place issue-adoption cold door (§8.29).

`plans.read_issue`, `gh_engagement.read_issue_comments`, `gh_engagement.read_description_edits`,
and `launch.launch_stage` are stubbed (no GitHub, no `exec pi`), mirroring test_replan_cmd.py.
"""

import json
from pathlib import Path

from click.testing import CliRunner

from perk import github, objective, plan
from perk.backends import issue_backend, resolve
from perk.backends.github import engagement as gh_engagement
from perk.backends.github import plans
from perk.cli.cli import cli
from perk.run import launch

_SCRATCH_REL = ".perk/workflow/scratch/adopt-7.md"


def _git_init(path, factory) -> None:
    factory(path)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _issue(*, state: str = "OPEN", body: str = "do the thing") -> plans.IssueRead:
    return plans.IssueRead(number=7, url="u/7", title="Human title", body=body, state=state)


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


def _stub_issue(monkeypatch, *, issue=None, comments=None, edits=None) -> None:
    monkeypatch.setattr(plans, "read_issue", lambda **k: _issue() if issue is None else issue)
    monkeypatch.setattr(gh_engagement, "read_issue_comments", lambda **k: list(comments or []))
    monkeypatch.setattr(gh_engagement, "read_description_edits", lambda **k: list(edits or []))


def _stub_launch(monkeypatch, sink: dict) -> None:
    monkeypatch.setattr(
        launch,
        "launch_stage",
        lambda **k: sink.update(
            stage=k["stage"].id,
            prompt=k.get("prompt_override"),
            handoff_extra=k.get("handoff_extra"),
            run_id_override=k.get("run_id_override"),
            binding_trigger=k.get("binding_trigger"),
            sync_main=k.get("sync_main"),
        ),
    )


def test_no_sync_opts_out_of_main_checkout_sync(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    _stub_issue(monkeypatch)
    runner = CliRunner()
    for args, expected in ((), True), (("--no-sync",), False):
        launched: dict = {}
        _stub_launch(monkeypatch, launched)
        with runner.isolated_filesystem() as d:
            _git_init(d, unborn_git_repo_factory)
            result = runner.invoke(cli, ["plan", "from", "7", "--json", *args])
            assert result.exit_code == 0, result.output
        assert launched["sync_main"] is expected


def test_dry_run_json_materializes_and_does_not_launch(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    _stub_issue(monkeypatch)

    def boom_launch(**k):
        raise AssertionError("--dry-run must not launch")

    monkeypatch.setattr(launch, "launch_stage", boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["plan", "from", "7", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert payload["issue"] == "7"
        # The reads run on the dry-run path too, so the wait IS narrated — banner-free.
        assert "looking up issue #7" in result.stderr
        assert "skills \u00b7" not in result.stderr
        scratch = (Path(d) / _SCRATCH_REL).resolve()
        assert Path(payload["scratch_path"]).resolve() == scratch
        text = scratch.read_text(encoding="utf-8")
        assert "<untrusted_adopted_issue>" in text and "do the thing" in text
        assert "Human title" in text


def test_real_launch_threads_adopt_from_handoff_and_seed(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    _stub_issue(monkeypatch)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["plan", "from", "7", "--json"])
        assert result.exit_code == 0, result.output
        # The banner heads the pre-launch narration, then the gather narrates + resolves.
        err = result.stderr
        assert err.index("skills \u00b7") < err.index("looking up issue #7")
        assert "\u2713 materialized issue #7 \u2192 adopt-7.md" in err
    assert launched["stage"] == "plan"  # borrows the plan stage
    assert launched["handoff_extra"] == {"adopt_from": "7"}
    assert launched["run_id_override"] is None  # a FRESH run_id is minted (cold_local)
    # default binding_trigger (None → stage:plan) fires the perk-plan nudge
    assert launched["binding_trigger"] is None
    prompt = launched["prompt"] or ""
    assert _SCRATCH_REL in prompt
    # The skill pointer is binding-delivered (stage:plan), never hardcoded in the seed.
    assert ".agents/skills/perk-plan" not in prompt
    # Review-first seed: approval-save adopts in place, no autonomous plan_save instruction.
    assert "plan_review" in prompt
    assert "IN PLACE" in prompt
    assert "plan_save" not in prompt  # `/plan-save` (hyphen) doesn't match


def test_strips_hash_prefix(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    _stub_issue(monkeypatch)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["plan", "from", "#7", "--json"])
        assert result.exit_code == 0, result.output
    assert launched["handoff_extra"] == {"adopt_from": "7"}


def test_empty_engagement_scratch_and_seed_byte_unchanged(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    _stub_issue(monkeypatch)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["plan", "from", "7", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
    assert "<untrusted_adopted_issue_engagement>" not in text
    assert "<untrusted_adopted_issue_engagement>" not in (launched["prompt"] or "")


def test_with_engagement_appends_block_and_points_seed(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    _stub_issue(monkeypatch, comments=[_comment_row("please scope this tightly")])
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["plan", "from", "7", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
    assert "<untrusted_adopted_issue_engagement>" in text
    assert "please scope this tightly" in text
    assert "<untrusted_adopted_issue_engagement>" in (launched["prompt"] or "")


def test_engagement_read_failure_is_fail_soft(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    _stub_issue(monkeypatch)

    def boom(**k):
        raise github.GitHubError("gh exploded")

    monkeypatch.setattr(gh_engagement, "read_issue_comments", boom)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["plan", "from", "7", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
    assert "<untrusted_adopted_issue_engagement>" not in text


def test_linear_backend_skips_the_github_auth_gate(monkeypatch, unborn_git_repo_factory):
    # The auth gate is backend-conditional: a Linear-configured repo reaches backend resolution
    # without ever probing `gh` auth (Linear auth is enforced at client construction).
    def no_auth_probe():
        raise AssertionError("check_auth must not run on the Linear arm")

    monkeypatch.setattr(github, "check_auth", no_auth_probe)

    class _LinearBackend:
        backend_id = "linear"

        def read_issue(self, *, issue_id):
            return issue_backend.AdoptableIssue(
                id=str(issue_id), url="u", title="t", body="b", state="OPEN"
            )

        def read_comments(self, *, issue_id):
            return []

        def read_description_edits(self, *, issue_id):
            return []

    monkeypatch.setattr(resolve, "resolve_issue_backend", lambda _root: _LinearBackend())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        perk_dir = Path(d) / ".perk"
        perk_dir.mkdir(exist_ok=True)
        (perk_dir / "config.toml").write_text('[issues]\nbackend = "linear"\n', encoding="utf-8")
        result = runner.invoke(cli, ["plan", "from", "7", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["success"] is True


def test_github_backend_still_refuses_unauthed(monkeypatch, unborn_git_repo_factory):
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(False, None, (), "not logged in")
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["plan", "from", "7", "--dry-run", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["success"] is False and payload["error_type"] == "github_unauthed"


def test_refuses_not_found(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "read_issue", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["plan", "from", "7", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "adopt_not_found"


def test_refuses_non_open_issue(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    _stub_issue(monkeypatch, issue=_issue(state="CLOSED"))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["plan", "from", "7", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "adopt_not_open"


def test_refuses_issue_already_a_plan(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    header = plan.render_metadata_block(
        plan.PLAN_HEADER_KEY,
        plan.render_plan_header_fields(plan.PlanHeader(run_id="R", created="t")),
    )
    _stub_issue(monkeypatch, issue=_issue(body=f"prose\n\n{header}\n"))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["plan", "from", "7", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "already_a_plan"
        assert "replan" in payload["message"]


def test_refuses_an_objective_carrier(monkeypatch, unborn_git_repo_factory):
    # Wrong-kind door refusal (§8.29): an objective-header'd issue is never adoptable as a
    # plan; the GitHub message names the right door (perk objective plan <N>).
    _authed(monkeypatch)
    header = plan.render_metadata_block(
        objective.OBJECTIVE_HEADER_KEY, {"run_id": "01OBJ", "created": "t"}
    )
    _stub_issue(monkeypatch, issue=_issue(body=f"prose\n\n{header}\n"))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["plan", "from", "7", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "issue_kind_mismatch"
        assert "perk objective plan 7" in payload["message"]


# --- seed-from-file mode (§8.33) ---


def test_file_mode_launches_fresh_no_adopt_handoff(monkeypatch, unborn_git_repo_factory):
    # No `_authed` stub: file mode must NOT require GitHub auth.
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        Path(d, "notes.md").write_text("build the widget", encoding="utf-8")
        result = runner.invoke(cli, ["plan", "from", "notes.md", "--json"])
        assert result.exit_code == 0, result.output
    assert launched["stage"] == "plan"
    assert launched["handoff_extra"] is None  # FRESH issue — no adopt_from
    prompt = launched["prompt"] or ""
    assert "<untrusted_seed_file>" in prompt
    assert "seed-file-notes-" in prompt
    # The skill pointer is binding-delivered (stage:plan), never hardcoded in the seed.
    assert ".agents/skills/perk-plan" not in prompt
    # Review-first seed: approval-save creates the NEW issue, no autonomous plan_save instruction.
    assert "plan_review" in prompt
    assert "NEW perk plan issue" in prompt
    assert "plan_save" not in prompt  # `/plan-save` (hyphen) doesn't match


def test_file_mode_absolute_path(monkeypatch, unborn_git_repo_factory):
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        abs_path = Path(d, "notes.md")
        abs_path.write_text("build the widget", encoding="utf-8")
        result = runner.invoke(cli, ["plan", "from", str(abs_path), "--json"])
        assert result.exit_code == 0, result.output
    assert launched["stage"] == "plan"
    assert launched["handoff_extra"] is None


def test_file_mode_dry_run_json_emits_file_and_does_not_launch(
    monkeypatch, unborn_git_repo_factory
):
    def boom_launch(**k):
        raise AssertionError("--dry-run must not launch")

    monkeypatch.setattr(launch, "launch_stage", boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        Path(d, "notes.md").write_text("build the widget", encoding="utf-8")
        result = runner.invoke(cli, ["plan", "from", "notes.md", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert payload["dry_run"] is True
        assert payload["file"] == str(Path(d, "notes.md").resolve())
        scratch = Path(payload["scratch_path"])
        assert scratch.name.startswith("seed-file-notes-")
        assert "<untrusted_seed_file>" in scratch.read_text(encoding="utf-8")


def test_file_mode_empty_file_errors(monkeypatch, unborn_git_repo_factory):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        Path(d, "empty.md").write_text("   \n", encoding="utf-8")
        result = runner.invoke(cli, ["plan", "from", "empty.md", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "seed_file_error"


def test_file_mode_non_utf8_errors(monkeypatch, unborn_git_repo_factory):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        Path(d, "bin.md").write_bytes(b"\xff\xfe\x00bad")
        result = runner.invoke(cli, ["plan", "from", "bin.md", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "seed_file_error"
