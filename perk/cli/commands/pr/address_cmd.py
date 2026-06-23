"""``perk pr address`` — the launcher-only address door.

``address`` has **both** a launcher half (opens a primed pi session that runs the classify→fix→
resolve loop) and the warm ``/address`` review flow, but **no deterministic worker** — so it is
**launcher-only (L)**, not a :class:`~perk.cli.stages.MergedCommand`. This dedicated launcher
mirrors ``make_stage_launcher``'s option set (``--worktree`` / ``--dry-run`` / ``--remote`` /
``pi_args``) **plus** a new cold ``--preview`` flag (previously warm-only).

``--preview`` is a **local-launch concept**: it shapes the cold seed prompt only (the warm
``/address --preview`` gesture). On ``--remote`` (address is ``cold_remote: true``) the dispatch
path builds no seed prompt, so ``--preview`` is inert there (mirrors how the seed prompt is
local-only).
"""

import click

from perk.cli.context import require_config, require_repo
from perk.run.launch import launch_stage
from perk.substrate.registry import Stage, load_registry


def _address_stage() -> Stage:
    return next(s for s in load_registry().stages if s.id == "address")


# Click takes the first paragraph as short help, so the root-listing row renders the bare registry
# summary; the second paragraph disambiguates the launcher (per the cli-command-groups playbook).
_ADDRESS_HELP = (
    "Classify PR review feedback (isolated child) and resolve the threads.\n\n"
    "Opens a primed pi session for the 'address' stage (use --dry-run to print the launch plan "
    "without exec'ing pi). Pass --preview to classify the feedback only and take no action (the "
    "warm /address --preview gesture); --preview is local-only (inert on --remote)."
)


@click.command(
    "address",
    help=_ADDRESS_HELP,
    context_settings={"ignore_unknown_options": True},
)
@click.option("--worktree", help="Worktree to position (address reuses an existing worktree).")
@click.option("--dry-run", is_flag=True, help="Print the launch plan without exec'ing pi.")
@click.option(
    "--remote",
    type=str,
    default=None,
    is_flag=False,
    flag_value="",
    help="Local (default) or a remote runner (dispatch the stage to CI).",
)
@click.option(
    "--preview",
    is_flag=True,
    help="Classify the PR feedback only — take no action (the warm /address --preview gesture).",
)
@click.argument("pi_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def address_launcher(
    ctx: click.Context,
    *,
    worktree: str | None,
    dry_run: bool,
    remote: str | None,
    preview: bool,
    pi_args: tuple[str, ...],
) -> None:
    launch_stage(
        repo_root=require_repo(ctx),
        config=require_config(ctx),
        stage=_address_stage(),
        worktree=worktree,
        dry_run=dry_run,
        remote=remote,
        pi_args=list(pi_args),
        preview=preview,
    )
