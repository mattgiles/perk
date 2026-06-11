"""Generate one ``perk <stage>`` launcher per registry stage (cli-vs-pi §4.2).

The registry is the single source of truth for which stage commands exist, so the two
entry planes (CLI launchers / extension transitions) cannot drift. Generation is
**defensive**: a registry that fails to load leaves the core commands working, and
``perk registry check`` diagnoses the break.
"""

import click

from perk.cli.context import require_config, require_repo
from perk.launch import launch_stage
from perk.registry import RegistryError, Stage, load_registry

# Stages with a dedicated, hand-written command (skipped by the generic generator below).
DEDICATED_STAGES: frozenset[str] = frozenset(
    {
        "implement",  # perk/cli/commands/implement_cmd.py
        "learn",  # perk/cli/commands/learn/__init__.py (hybrid group; hidden launcher, Node 2.2)
        "objective-author",  # perk/cli/commands/objective_author_cmd.py (P3.T2)
        "objective-plan",  # perk/cli/commands/objective_plan_cmd.py (P2.T10)
    }
)


def make_stage_launcher(stage: Stage) -> click.Command:
    """Build the generic launcher command for ``stage``.

    Used by the generator below for every non-dedicated stage, and reused by the ``learn``
    group for its hidden bare-invocation launcher (``commands/learn/__init__.py``).
    """

    @click.command(
        name=stage.id,
        help=stage.summary,
        context_settings={"ignore_unknown_options": True},
    )
    @click.option("--worktree", default=None, help="Worktree to position (create/reuse stages).")
    @click.option("--dry-run", is_flag=True, help="Print the launch plan without exec'ing pi.")
    @click.option(
        "--remote",
        type=str,
        default=None,
        is_flag=False,
        flag_value="",
        help="Local (default) or a remote runner (dispatch the stage to CI).",
    )
    @click.argument("pi_args", nargs=-1, type=click.UNPROCESSED)
    @click.pass_context
    def _cmd(
        ctx: click.Context,
        *,
        worktree: str | None,
        dry_run: bool,
        remote: str | None,
        pi_args: tuple[str, ...],
    ) -> None:
        launch_stage(
            repo_root=require_repo(ctx),
            config=require_config(ctx),
            stage=stage,
            worktree=worktree,
            dry_run=dry_run,
            remote=remote,
            pi_args=list(pi_args),
        )

    return _cmd


def register_stage_commands(cli: click.Group) -> None:
    """Add a launcher command per registry stage (no-op if the registry won't load)."""
    try:
        registry = load_registry()
    except (RegistryError, FileNotFoundError):
        return  # a broken registry must not brick the CLI; `registry check` diagnoses it
    for stage in registry.stages:
        if stage.id in DEDICATED_STAGES:
            continue  # a dedicated command is registered explicitly (e.g. `implement`)
        cli.add_command(make_stage_launcher(stage))
