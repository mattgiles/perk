"""``perk gist save`` — the gist read-write hand-off cold door.

Opens a session for the ``gist-save`` stage: it flips a read-only gist-authoring session to
read-write and points the model back at the ``gist_save`` tool (which persists the gist via
``perk gist create``). A thin launcher — it seeds **no** prompt of its own (the authoring
judgment lives in the ``perk-gist-author`` skill); it only resolves the run target and exec's pi.

A **dedicated** command (in ``DEDICATED_STAGES``), byte-mirroring ``objective save``.
Supervisor surface: ``--json`` → stdout, human text → stderr, stable exits
(``0`` ok · ``1`` invalid/op-failure · ``2`` not-a-repo).
"""

import click

from perk.cli.context import require_config, require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.run import launch
from perk.substrate.registry import Stage, stage_by_id


def _gist_save_stage() -> Stage:
    return stage_by_id("gist-save")


@click.command("save", context_settings={"ignore_unknown_options": True})
@click.option("--worktree", help="Worktree to position (gist save runs at repo root).")
@click.option("--dry-run", is_flag=True, help="Resolve + print; launch nothing.")
@click.option(
    "--remote",
    type=str,
    default=None,
    is_flag=False,
    flag_value="",
    help="Local (default) or a remote runner; gist save is local-only (cold_remote:false).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.argument("pi_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def save_gist(
    ctx: click.Context,
    *,
    worktree: str | None,
    dry_run: bool,
    remote: str | None,
    as_json: bool,
    pi_args: tuple[str, ...],
) -> None:
    """Flip a gist-authoring session to read-write to save (no seed prompt).

    \b
    Examples:
      perk gist save              # open the read-write hand-off session
      perk gist save --dry-run    # resolve + print, launch nothing
    """
    try:
        repo_root = require_repo(ctx)
        config = require_config(ctx)
        stage = _gist_save_stage()
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

    # launch_stage exec's pi (becomes the session — nothing after runs). A dry run prints the
    # launch plan and returns.
    launch.launch_stage(
        repo_root=repo_root,
        config=config,
        stage=stage,
        worktree=worktree,
        dry_run=dry_run,
        remote=remote,
        pi_args=list(pi_args),
    )
