"""hop-2 — `perk learn docs`: the learned-docs plan-factory cold door.

`plans.list_learn_issues` + `launch.launch_stage` are stubbed (no GitHub, no `exec pi`), mirroring
test_objective_plan_cmd.py.
"""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, plan
from perk.backends.github import plans
from perk.cli.cli import cli
from perk.run import launch


def _learn_body(text: str, *, decision: str | None = None, target: str | None = None) -> str:
    """A learn-issue body with a stamped learn-header (the gather-time classification route)."""
    header = plan.render_learn_header(
        run_id="01RID", created="t", plan=1, decision=decision, target=target
    )
    return f"{text}\n\n{header}"


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
        payload = json.loads(result.stdout)
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


def test_gather_narrates_waits_without_banner(monkeypatch):
    """`--gather` (a warm sub-call) narrates each real wait on stderr but heads no banner."""
    _authed(monkeypatch)
    _stub_list(monkeypatch)

    def boom_launch(**k):
        raise AssertionError("--gather must not launch")

    monkeypatch.setattr(launch, "launch_stage", boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["learn", "docs", "--gather"])
        assert result.exit_code == 0, result.output
        err = result.stderr
        assert "listing open perk:learn issues" in err
        assert "scanning existing docs" in err
        assert "materialized inbox" in err
        # --gather is banner-free (the warm path feeds JSON to a warm door).
        assert "skills \u00b7" not in err


def test_real_launch_banner_precedes_narration(monkeypatch):
    """A real local launch heads stderr with the banner BEFORE the gather narration."""
    _authed(monkeypatch)
    _stub_list(monkeypatch)
    _stub_launch(monkeypatch, {})
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["learn", "docs"])
        assert result.exit_code == 0, result.output
        err = result.stderr
        assert err.index("skills \u00b7") < err.index("listing open perk:learn issues")


def test_no_learn_issues_exits_1(monkeypatch):
    _authed(monkeypatch)
    _stub_list(monkeypatch, issues=())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["learn", "docs", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "no_learn_issues"


def test_remote_blocked(monkeypatch):
    _authed(monkeypatch)
    _stub_list(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["learn", "docs", "--remote", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "remote_blocked"


def test_not_a_repo_exit_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["learn", "docs", "--json"])
        assert result.exit_code == 2
        assert json.loads(result.stdout)["error_type"] == "not_a_repo"


def test_docs_factory_filters_out_should_be_code(monkeypatch):
    """The docs factory pre-routes (filters out) pre-stamped SHOULD_BE_CODE issues; everything
    else (incl. legacy/unclassified) is doc-destined and consumed here."""
    _authed(monkeypatch)
    issues = (
        plans.LearnIssueSummary(number=45, title="L45", url="u/45", body="legacy unclassified"),
        plans.LearnIssueSummary(
            number=46,
            title="L46",
            url="u/46",
            body=_learn_body("doc one", decision="NEW_DOC"),
        ),
        plans.LearnIssueSummary(
            number=47,
            title="L47",
            url="u/47",
            body=_learn_body("code one", decision="SHOULD_BE_CODE", target="perk/foo.py"),
        ),
    )
    _stub_list(monkeypatch, issues=issues)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["learn", "docs", "--json"])
        assert result.exit_code == 0, result.output
        # 47 (SHOULD_BE_CODE) is filtered out; 45 (legacy) + 46 (NEW_DOC) stay.
        assert launched["handoff_extra"] == {"consumed_learn": ["45", "46"]}
        text = (Path(d) / _INBOX_REL).read_text(encoding="utf-8")
        assert "Learning #45" in text and "Learning #46" in text
        assert "Learning #47" not in text


def test_docs_inbox_carries_classification_and_scan(monkeypatch):
    """The inbox renders the per-issue classification line + the existing-docs scan section
    (with a finding seeded into the corpus)."""
    _authed(monkeypatch)
    issues = (
        plans.LearnIssueSummary(
            number=46,
            title="L46",
            url="u/46",
            body=_learn_body("doc one", decision="NEW_DOC", target="docs/learned/x/y.md"),
        ),
    )
    _stub_list(monkeypatch, issues=issues)

    def boom_launch(**k):
        raise AssertionError("--gather must not launch")

    monkeypatch.setattr(launch, "launch_stage", boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        # Seed a learned doc with a stale source pointer so scan_docs_richly emits a finding.
        doc = Path(d) / "docs" / "learned" / "cat" / "slug.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(
            "---\ntitle: T\nread_when: when\n---\n\n"
            "See `perk/totally_missing.py::ghost` for the detail.\n",
            encoding="utf-8",
        )
        result = runner.invoke(cli, ["learn", "docs", "--gather", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _INBOX_REL).read_text(encoding="utf-8")
        # The perk-derived classification line + target above the verbatim block.
        assert "**classification:** NEW_DOC" in text
        assert "→ target: `docs/learned/x/y.md`" in text
        # The existing-docs scan section + the stale-pointer finding.
        assert "## Existing docs (scan)" in text
        assert "docs/learned/cat/slug.md" in text
        assert "perk/totally_missing.py::ghost" in text


def test_docs_seed_retains_verifier_and_cleanup_language(monkeypatch):
    """The docs seed keeps the cleanup-first / docs-sync language AND the retained
    SHOULD_BE_CODE follow-up + placement-hierarchy verifier language."""
    _authed(monkeypatch)
    _stub_list(monkeypatch)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["learn", "docs", "--json"])
        assert result.exit_code == 0, result.output
    prompt = launched["prompt"] or ""
    assert "docs-sync" in prompt
    assert "cleanup-first" in prompt.lower()
    assert "SHOULD_BE_CODE" in prompt
    assert "placement hierarchy" in prompt.lower()
