"""`perk objective stack review` — the stacked-PR browser-review cold launcher.

Resolution and the checkout are stubbed on the command module (no GitHub, no git fetch);
`launch.launch_stage` is stubbed on its defining module (no `exec pi`) — the test_from_cmd.py
sink pattern. The dry-run tests additionally prove the side-effect-free contract with negative
stubs (a fetch/checkout/launch call raises) and a handoff-dir scan.
"""

import json
from pathlib import Path
from typing import Literal

import pytest
from click.testing import CliRunner

import perk.cli.commands.objective.stack.review_cmd as review_cmd
from perk.cli.cli import cli
from perk.cli.commands.pr.review.checkout_cmd import ReviewCheckoutResult, StackCheckoutMember
from perk.cli.commands.pr.review.stack_resolve import ResolvedStack, StackMember
from perk.run import launch


def _member(pr: int, head: str, base: str) -> StackMember:
    return StackMember(
        pr_number=pr,
        url=f"https://github.com/o/r/pull/{pr}",
        head_ref=head,
        base_ref=base,
        node_id="1.1" if pr == 1 else None,
        plan_id="301" if pr == 1 else None,
    )


def _stack(
    *,
    kind: Literal["objective", "chain"] = "objective",
    objective_id: str | None = "77",
    notes: tuple[str, ...] = (),
) -> ResolvedStack:
    return ResolvedStack(
        members=(_member(1, "plan-301", "main"), _member(2, "feat-b", "plan-301")),
        base_ref="main",
        kind=kind,
        objective_id=objective_id,
        notes=notes,
    )


def _checkout_result(root: Path, *, notes: tuple[str, ...] = ()) -> ReviewCheckoutResult:
    return ReviewCheckoutResult(
        path=root / ".worktrees" / "review-2",
        pr_number=2,
        url="https://github.com/o/r/pull/2",
        head_sha="b" * 40,
        base_sha="0" * 40,
        base_ref="main",
        state="OPEN",
        stack=(
            StackCheckoutMember(
                pr_number=1,
                url="https://github.com/o/r/pull/1",
                branch="plan-301",
                head_sha="a" * 40,
                base_ref="main",
                node_id="1.1",
                plan_id="301",
            ),
            StackCheckoutMember(
                pr_number=2,
                url="https://github.com/o/r/pull/2",
                branch="feat-b",
                head_sha="b" * 40,
                base_ref="plan-301",
                node_id=None,
                plan_id=None,
            ),
        ),
        stack_notes=notes,
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
            worktree=k.get("worktree"),
            pi_args=k.get("pi_args"),
        ),
    )


def _forbid_side_effects(monkeypatch) -> None:
    """The dry-run negative stubs: a fetch, a checkout, or a launch is a test failure."""

    def boom(what):
        def _raise(*a, **k):
            raise AssertionError(f"--dry-run must not {what}")

        return _raise

    monkeypatch.setattr(review_cmd, "stack_checkout", boom("materialize the checkout"))
    monkeypatch.setattr(launch, "launch_stage", boom("launch"))
    monkeypatch.setattr(review_cmd.launch, "_sync_main_checkout", boom("sync"), raising=False)


# --- target parsing / flag combinations ----------------------------------------------------------


def test_objective_and_pr_are_mutually_exclusive(git_repo, monkeypatch):
    monkeypatch.chdir(git_repo)
    result = CliRunner().invoke(cli, ["objective", "stack", "review", "77", "--pr", "2", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["error_type"] == "invalid_input"
    assert "mutually exclusive" in data["message"]


def test_pr_target_accepts_number_and_url(git_repo, monkeypatch):
    seen: list[int] = []

    def fake_resolve(repo_root, pr):
        seen.append(pr)
        raise review_cmd.UserFacingCliError("stop here", error_type="not_a_stack")

    monkeypatch.setattr(review_cmd, "resolve_stack_from_pr", fake_resolve)
    monkeypatch.chdir(git_repo)
    runner = CliRunner()
    r1 = runner.invoke(cli, ["objective", "stack", "review", "--pr", "148", "--json"])
    r2 = runner.invoke(
        cli,
        ["objective", "stack", "review", "--pr", "https://github.com/o/r/pull/9", "--json"],
    )
    assert r1.exit_code == 1 and r2.exit_code == 1
    assert seen == [148, 9]
    assert json.loads(r1.stdout)["error_type"] == "not_a_stack"


def test_malformed_pr_target_is_invalid_input(git_repo, monkeypatch):
    monkeypatch.setattr(
        review_cmd,
        "resolve_stack_from_pr",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not resolve")),
    )
    monkeypatch.chdir(git_repo)
    result = CliRunner().invoke(cli, ["objective", "stack", "review", "--pr", "abc", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["error_type"] == "invalid_input"
    assert "--pr expects a PR number or PR URL" in data["message"]


def test_no_objective_anywhere_is_the_typed_refusal(git_repo, monkeypatch):
    # No positional, no --pr, no plan-ref in the invocation checkout → `no_objective`.
    monkeypatch.chdir(git_repo)
    result = CliRunner().invoke(cli, ["objective", "stack", "review", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "no_objective"


def test_remote_is_refused_before_resolution(git_repo, monkeypatch):
    monkeypatch.setattr(
        review_cmd,
        "resolve_stack_from_objective",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("resolution ran after --remote")),
    )
    monkeypatch.chdir(git_repo)
    result = CliRunner().invoke(
        cli, ["objective", "stack", "review", "77", "--remote", "runner", "--json"]
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "remote_blocked"


# --- the side-effect-free dry run -----------------------------------------------------------------


def test_dry_run_json_preview_pins_the_nulls_argv_and_handoff(git_repo, monkeypatch):
    monkeypatch.setattr(
        review_cmd, "resolve_stack_from_objective", lambda root, oid: _stack(notes=("[w] slow",))
    )
    _forbid_side_effects(monkeypatch)
    monkeypatch.chdir(git_repo)

    result = CliRunner().invoke(
        cli,
        ["objective", "stack", "review", "77", "--focus", "dig in", "--dry-run", "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["success"] is True
    assert data["kind"] == "objective"
    assert data["objective_id"] == "77"
    assert data["stage"] == "stack-review"
    assert data["top_pr"] == 2
    assert data["checkout_path"].endswith("review-2")
    assert data["base_ref"] == "main"
    assert data["base_sha"] is None
    assert [row["pr"] for row in data["stack"]] == [1, 2]
    assert all(row["head_sha"] is None for row in data["stack"])
    assert data["stack"][0]["node_id"] == "1.1"
    assert data["notes"] == ["[w] slow"]
    assert data["launched"] is False
    # The argv vector is the build-once launch argv: pi + the seeded prompt last.
    assert data["argv"][0] == "pi"
    assert "open_stack_review" in data["argv"][-1]
    # The handoff blob preview: the real binding's four keys plus the dry_run marker — the
    # top PR / stack base are derived from the rows in-session, never carried redundantly.
    blob = data["handoff"]["stack_review"]
    assert set(blob) == {"stack", "checkout_path", "notes", "focus", "dry_run"}
    assert blob["dry_run"] is True
    assert all(row["head_sha"] is None for row in blob["stack"])
    assert blob["focus"] == "dig in"
    assert blob["checkout_path"] == data["checkout_path"]
    # Nothing was written: no handoff file exists anywhere under the workflow dir.
    assert not list(Path(git_repo).glob(".perk/workflow/handoff/*")), "no handoff on a dry run"


def test_dry_run_human_render_shows_the_stack_table_and_seed(git_repo, monkeypatch):
    monkeypatch.setattr(review_cmd, "resolve_stack_from_objective", lambda root, oid: _stack())
    _forbid_side_effects(monkeypatch)
    monkeypatch.chdir(git_repo)

    result = CliRunner().invoke(cli, ["objective", "stack", "review", "77", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "1. PR #1 plan-301 ← main" in result.stderr
    assert "2. PR #2 feat-b ← plan-301" in result.stderr
    assert "would check out review-2" in result.stderr
    assert "would launch stage 'stack-review'" in result.stderr
    assert "open_stack_review" in result.stderr  # the seed section renders


# --- the real launch ------------------------------------------------------------------------------


def test_real_run_checks_out_then_launches_with_the_pinned_snapshot(git_repo, monkeypatch):
    root = Path(git_repo)
    monkeypatch.setattr(
        review_cmd,
        "resolve_stack_from_objective",
        lambda r, oid: _stack(notes=("[w] blocker",)),
    )
    checked_out: dict = {}

    def fake_checkout(*, repo_root, worktree_root, stack):
        checked_out.update(stack=stack)
        return _checkout_result(root, notes=("[w] blocker", "drift: PR #1 head moved"))

    monkeypatch.setattr(review_cmd, "stack_checkout", fake_checkout)
    sink: dict = {}
    _stub_launch(monkeypatch, sink)
    monkeypatch.chdir(root)

    result = CliRunner().invoke(
        cli, ["objective", "stack", "review", "77", "--focus", "dig in", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert checked_out["stack"].kind == "objective"
    assert sink["stage"] == "stack-review"
    assert sink["binding_trigger"] == "command:stack-review-browser"
    # The seed names the resolved stack and the ONE tool call.
    assert "objective #77's delivery train" in sink["prompt"]
    assert "2 member PRs topped by PR #2" in sink["prompt"]
    assert "open_stack_review" in sink["prompt"]
    # The handoff snapshot is the CHECKOUT envelope (hydrated SHAs), not the wire facts —
    # exactly the four keys the in-session decoder requires (top/base derive from the rows).
    blob = sink["handoff_extra"]["stack_review"]
    assert set(blob) == {"stack", "checkout_path", "notes", "focus"}
    assert blob["checkout_path"].endswith("review-2")
    assert [row["pr"] for row in blob["stack"]] == [1, 2]
    assert [row["head_sha"] for row in blob["stack"]] == ["a" * 40, "b" * 40]
    assert [row["base_ref"] for row in blob["stack"]] == ["main", "plan-301"]
    assert blob["notes"] == ["[w] blocker", "drift: PR #1 head moved"]
    assert blob["focus"] == "dig in"
    # Notes render to stderr and proceed (resolution + checkout-time drift).
    assert "note: [w] blocker" in result.stderr
    assert "note: drift: PR #1 head moved" in result.stderr


def test_chain_arm_routes_via_resolve_stack_from_pr(git_repo, monkeypatch):
    root = Path(git_repo)
    seen: dict = {}

    def fake_resolve(repo_root, pr):
        seen["pr"] = pr
        return _stack(kind="chain", objective_id=None)

    monkeypatch.setattr(review_cmd, "resolve_stack_from_pr", fake_resolve)
    monkeypatch.setattr(
        review_cmd,
        "stack_checkout",
        lambda *, repo_root, worktree_root, stack: _checkout_result(root),
    )
    sink: dict = {}
    _stub_launch(monkeypatch, sink)
    monkeypatch.chdir(root)

    result = CliRunner().invoke(cli, ["objective", "stack", "review", "--pr", "2", "--json"])
    assert result.exit_code == 0, result.output
    assert seen["pr"] == 2
    blob = sink["handoff_extra"]["stack_review"]
    assert set(blob) == {"stack", "checkout_path", "notes", "focus"}
    assert blob["focus"] is None
    assert "the base-ref chain around PR #2" in sink["prompt"]


def test_typed_resolution_refusals_pass_through(git_repo, monkeypatch):
    monkeypatch.setattr(
        review_cmd,
        "resolve_stack_from_objective",
        lambda r, oid: (_ for _ in ()).throw(
            review_cmd.UserFacingCliError("too deep", error_type="stack_too_deep")
        ),
    )
    monkeypatch.chdir(git_repo)
    result = CliRunner().invoke(cli, ["objective", "stack", "review", "77", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "stack_too_deep"


@pytest.mark.parametrize("raw,expected", [("148", 148), ("https://x/o/r/pull/9?tab=files", 9)])
def test_parse_pr_target(raw, expected):
    assert review_cmd._parse_pr_target(raw) == expected
