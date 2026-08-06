"""``perk gist author`` — the gist-authoring cold door.

Opens a **read-only** plan-mode session seeded to draft a *new* gist — a rough,
problem-space-focused statement of intent (contracts.md §8.41). The lightest authoring stage:
no roadmap, no steps, no estimates — the lightness lives in the artifact, not the machinery
(the flow is the full review-first mirror: ``gist_draft`` → ``plan_review`` → approval
auto-saves via ``perk gist create``).

A **dedicated** command (in ``DEDICATED_STAGES``), not the generic registry launcher, so it can
seed the authoring prompt and stash the ``--scope`` default in the run handoff (``gist_scope`` —
the ``adopt_from`` handoff pattern; an explicit save-time scope wins). Mirrors
``objective/author_cmd.py``'s bare path.

Supervisor surface: ``--json`` → stdout, human text → stderr, stable exits
(``0`` ok · ``1`` invalid/op-failure · ``2`` not-a-repo). The judgment (what makes a good gist)
lives in the ``perk-gist-author`` skill.
"""

import click

from perk.cli.commands.seeded_door import seeded_door_options
from perk.cli.context import require_config, require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.prompts import render
from perk.run import launch
from perk.substrate.registry import stage_by_id


def _seed_prompt() -> str:
    """The authoring-seed initial prompt for the read-only gist-author session."""
    return render("stages/gist-author/seed.md", {})


@click.command("author", context_settings={"ignore_unknown_options": True})
@click.option(
    "--scope",
    type=click.Choice(["plan", "objective"]),
    default=None,
    help="Pre-seed the gist's consumption tier (plan-sized vs objective-sized); the save-time "
    "scope wins when given explicitly.",
)
@seeded_door_options(
    worktree_help="Worktree to position (gist author runs at repo root).",
    dry_run_help="Resolve + print; launch nothing.",
    remote_subject="gist author",
)
@click.pass_context
def author_gist(
    ctx: click.Context,
    *,
    scope: str | None,
    worktree: str | None,
    dry_run: bool,
    remote: str | None,
    as_json: bool,
    no_sync: bool,
    pi_args: tuple[str, ...],
) -> None:
    """Draft a new gist (a rough statement of intent) in a read-only authoring session.

    \b
    Examples:
      perk gist author                     # open a read-only authoring session
      perk gist author --scope objective    # pre-seed the objective consumption tier
      perk gist author --dry-run            # resolve + print, launch nothing
    """
    try:
        repo_root = require_repo(ctx)
        config = require_config(ctx)
        stage = stage_by_id("gist-author")
        # Reject --remote on this local-only stage before any launch (mirrors launch_stage).
        launch.resolve_target(stage, remote)
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    # launch_stage exec's pi with the authoring-seed prompt (becomes the session — nothing after
    # runs). A dry run prints the launch plan and returns. The `gist_scope` handoff key lets the
    # later `perk gist create` recover the pre-seeded scope from every save surface.
    launch.launch_stage(
        repo_root=repo_root,
        config=config,
        stage=stage,
        worktree=worktree,
        dry_run=dry_run,
        remote=remote,
        pi_args=list(pi_args),
        prompt_override=_seed_prompt(),
        handoff_extra={"gist_scope": scope} if scope is not None else None,
        sync_main=not no_sync,
    )
