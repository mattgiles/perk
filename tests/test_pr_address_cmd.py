"""``perk pr address`` — the launcher-only address door + its flat alias.

``address`` has a launcher half + the warm review flow but no deterministic worker, so it is a
dedicated launcher (not a ``MergedCommand``) carrying the new cold ``--preview`` flag. These tests
cover the dry-run launch, the ``--preview`` seed shaping, and the ``perk address`` flat alias.
"""

import json
from pathlib import Path

from click.testing import CliRunner

from perk.cli.cli import cli
from perk.cli.commands.pr import pr_address_command
from perk.cli.context import PerkContext
from perk.state import cache
from perk.substrate.config import Config


def _ctx(repo: Path) -> PerkContext:
    return PerkContext.for_test(
        cwd=repo, repo_root=repo, config=Config(worktree_root=repo / ".worktrees")
    )


def _seed(repo: Path) -> Path:
    """Seed the active plan-ref and create the derived ``plan-42`` worktree (address reuses it)."""
    cache.write_plan_ref(
        repo,
        {
            "provider": "github",
            "pr_id": "42",
            "url": "u/42",
            "labels": ["perk:plan"],
            "objective_id": None,
        },
    )
    wt = repo / ".worktrees" / "plan-42"
    wt.mkdir(parents=True)
    return wt


def test_pr_address_dry_run_launches(git_repo):
    _seed(git_repo)
    result = CliRunner().invoke(cli, ["pr", "address", "--dry-run"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert "would launch stage 'address'" in result.output


def test_pr_address_preview_seeds_classification_only(git_repo):
    _seed(git_repo)
    result = CliRunner().invoke(
        cli, ["pr", "address", "--preview", "--dry-run"], obj=_ctx(git_repo)
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    seed = "\n".join(payload["argv"])
    assert "PREVIEWING" in seed and "take NO action" in seed
    # The fix→resolve→land tail is absent in the preview seed.
    assert "resolve_review_threads" not in seed


def test_pr_address_non_preview_seeds_full_loop(git_repo):
    _seed(git_repo)
    result = CliRunner().invoke(cli, ["pr", "address", "--dry-run"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    seed = "\n".join(payload["argv"])
    assert "resolve_review_threads" in seed
    assert "PREVIEWING" not in seed


def test_flat_address_alias_resolves_to_same_launcher(git_repo):
    # `perk address` (flat alias) is the SAME command object as `perk pr address`.
    assert cli.commands["address"] is pr_address_command
    _seed(git_repo)
    result = CliRunner().invoke(cli, ["address", "--dry-run"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert "would launch stage 'address'" in result.output
