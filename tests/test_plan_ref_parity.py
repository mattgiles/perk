"""Plan-ref save→reconstruct parity (contracts.md §8.4, §8.38).

The `cache.plan-ref` a `perk plan save` writes locally must be byte-recoverable from the
canonical `plan-header` it persists on the plan issue — the "cache reconstructable from
canonical state" exemplar, enforced end-to-end. All four reconstruction sites converge on
`resume.reconstruct_plan_ref`, so pinning save→reconstruct here pins them all.
"""

import dataclasses
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, plan
from perk.backends import issue_backend
from perk.backends.github import objectives, plans
from perk.cli.commands.plan.save_cmd import plan_save
from perk.cli.context import PerkContext
from perk.run import resume
from perk.state import cache

PLAN = "# My Feature\n\nDo the thing.\n"


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _stub_writes(monkeypatch) -> dict[str, object]:
    """Stub every canonical write; capture the created issue BODY (it carries the header)."""
    calls: dict[str, object] = {"body": None}
    monkeypatch.setattr(plans, "create_label", lambda *a, **k: plans.Label("perk:plan", False))

    def _create(**k):
        calls["body"] = k["body"]
        return plans.PlanIssue(number=123, url="https://gh/o/r/issues/123", existed=False)

    monkeypatch.setattr(plans, "create_plan_issue", _create)
    monkeypatch.setattr(plans, "add_issue_comment", lambda **k: plans.CommentResult(posted=True))
    monkeypatch.setattr(plans, "prepend_plan_callout", lambda **k: True)
    monkeypatch.setattr(
        objectives,
        "get_objective",
        lambda **k: objectives.ObjectiveState(
            number=63, url="u/63", title="O", header={"base": "release"}, nodes=()
        ),
    )
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        ),
    )
    return calls


def test_save_then_reconstruct_round_trips_every_field(monkeypatch):
    # Save with EVERY optional PlanRef field populated: an objective-plan handoff carrying
    # objective_id + node_id, consumed_learn, and an objective base (winning over config base).
    _authed(monkeypatch)
    calls = _stub_writes(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cfg = Path(d) / ".perk"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "config.toml").write_text('[workflow]\nbase = "develop"\n', encoding="utf-8")
        (Path(d) / "plan.md").write_text(PLAN, encoding="utf-8")
        cache.write_handoff(
            Path(d),
            "RID63",
            {
                "stage": "objective-plan",
                "mode": "read-only",
                "objective_id": "63",
                "node_id": "1.1",
                "consumed_learn": ["45", "50"],
            },
        )
        result = runner.invoke(
            plan_save,
            ["--plan-file", "plan.md", "--run-id", "RID63", "--json"],
            obj=PerkContext(cwd=Path(d)),
        )
        assert result.exit_code == 0, result.output
        written_ref = cache.read_plan_ref(Path(d))

    assert written_ref is not None
    # Precondition: every optional field is actually populated (a vacuous round trip proves
    # nothing).
    assert written_ref.objective_id == "63"
    assert written_ref.consumed_learn == ("45", "50")
    assert written_ref.base == "release"  # the objective's base, winning over config "develop"

    # Rebuild the ref from ONLY what save persisted canonically: the plan-header block embedded
    # in the created issue body.
    body = calls["body"]
    assert isinstance(body, str)
    header = plan.find_metadata_block(body, plan.PLAN_HEADER_KEY)
    assert header is not None
    state = issue_backend.PlanState(
        id="123",
        url="https://gh/o/r/issues/123",
        title="My Feature",
        header=header,
        pr=None,
        state="OPEN",
    )
    assert resume.reconstruct_plan_ref(state, provider="github") == written_ref


def test_reconstructed_ref_survives_a_serialization_round_trip(monkeypatch, tmp_path):
    # The reconstructed ref written through the cache boundary reads back equal — the
    # PlanRef → PlanRefModel(JSON) → PlanRef trio stays lossless for a fully-populated ref.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    ref = plan.PlanRef(
        provider="github",
        pr_id="123",
        url="https://gh/o/r/issues/123",
        labels=(plan.PLAN_LABEL,),
        objective_id="63",
        consumed_learn=("45", "50"),
        base="release",
    )
    cache.write_plan_ref(tmp_path, ref)
    assert cache.read_plan_ref(tmp_path) == ref


def test_plan_ref_field_census():
    # Tripwire: growing PlanRef requires extending BOTH the save-populate arm (the plan-header
    # fields `perk plan save` persists) and `resume.reconstruct_plan_ref` — and the round-trip
    # test above — in the same change. If this census fails, do all three together.
    assert {f.name for f in dataclasses.fields(plan.PlanRef)} == {
        "provider",
        "pr_id",
        "url",
        "labels",
        "objective_id",
        "consumed_learn",
        "base",
    }
