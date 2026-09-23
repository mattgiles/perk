"""The ``perk`` CLI root group (the session *exterior*).

The one file where in-function imports are the norm (python-cli-guidelines §8.3, the
tiered-import rule; ``PLC0415`` is ignored for it in ``pyproject.toml``): the root keeps its
module-level imports cheap (stdlib, ``click``, the version SSOT, the sectioned group and the
report-only version surfaces) so bare ``perk``, a lone ``--`` and the eager ``--version`` pay
for none of the command surface. Every command import and registration lives in
:func:`_register_root_commands`, run by :class:`SectionedGroup` on Click's first subcommand
lookup or listing; the callback arms import what only they need.
"""

from pathlib import Path

import click

from perk import __version__
from perk.cli.alias import SectionedGroup
from perk.cli.version_check import maybe_notice_upgrade, maybe_warn_version_mismatch


def _register_root_commands(root: click.Group) -> None:
    """The deferred one-unit registration (python-cli-guidelines §8.3): every root command
    import and registration, run by SectionedGroup on Click's first subcommand lookup or
    listing — never by bare `perk`, a lone `--` or the eager `--version`."""
    from perk.cli.alias import register_flat_alias, register_with_aliases
    from perk.cli.commands.doctor import doctor_group
    from perk.cli.commands.gist import gist_group
    from perk.cli.commands.implement_cmd import implement
    from perk.cli.commands.init_cmd import init_perk
    from perk.cli.commands.learn import learn_group
    from perk.cli.commands.objective import objective_group
    from perk.cli.commands.plan import plan_group
    from perk.cli.commands.pr import (
        pr_address_command,
        pr_group,
        pr_land_command,
        pr_submit_command,
    )
    from perk.cli.commands.pr.ready_cmd import ready_continuation
    from perk.cli.commands.registry import registry_group
    from perk.cli.commands.release_notes_cmd import release_notes_cmd
    from perk.cli.commands.resume_session_cmd import resume_session
    from perk.cli.commands.run_worker_cmd import run_worker_cmd
    from perk.cli.commands.skills import skills_group
    from perk.cli.commands.state import state_group
    from perk.cli.commands.workflow import workflow_group
    from perk.cli.commands.worktree import worktree_group
    from perk.cli.stages import register_stage_commands

    root.add_command(init_perk)
    root.add_command(plan_group)
    # The `plan` group is hybrid: bare `perk plan` default-dispatches to the hidden
    # plan-stage launcher, while `save` (merged launcher+worker under --json), `resume`, and
    # `replan` are registered verbs. `plan` + `save` are in DEDICATED_STAGES, so
    # register_stage_commands skips generating flat `perk plan` / `perk save` launchers.
    root.add_command(pr_group)
    # Flat hot-path aliases: the SAME command objects registered at
    # the root under a flat name, so `perk submit` resolves to the merged `pr submit`, etc. `ready`
    # is the one split spelling: the flat name is the continuation WRAPPER (worker mechanics, then
    # the interactive ready-time reconcile launch — contracts.md §8.66), while `perk pr ready`
    # keeps the deterministic non-launching worker object. register_flat_alias
    # records each in FLAT_ALIAS_ATTR so SectionedGroup routes their rows into the launcher
    # section.
    register_flat_alias(root, pr_submit_command, "submit")
    register_flat_alias(root, pr_land_command, "land")
    register_flat_alias(root, pr_address_command, "address")
    register_flat_alias(root, ready_continuation, "ready")
    root.add_command(learn_group)
    # The `learn` group is hybrid: bare `perk learn` default-dispatches to the hidden
    # stage launcher, while `capture` and `docs` are the cold workers. `docs` is a dedicated cold
    # door but NOT a registry stage: it borrows the `plan` stage to launch.
    register_with_aliases(root, implement)
    root.add_command(doctor_group)
    # implement is registered above; register_stage_commands skips it (DEDICATED_STAGES).
    register_with_aliases(root, registry_group)
    register_with_aliases(root, state_group)
    register_with_aliases(root, worktree_group)
    register_with_aliases(root, objective_group)
    # The objective launchers (author/save/plan) now live inside the `objective` group beside its
    # workers; register_stage_commands skips all three objective stages (DEDICATED_STAGES).
    register_with_aliases(root, gist_group)
    # The gist launchers (author/save) live inside the `gist` group beside its workers;
    # register_stage_commands skips both gist stages (DEDICATED_STAGES).
    register_with_aliases(root, workflow_group)
    register_with_aliases(root, skills_group)
    root.add_command(release_notes_cmd)
    # `release-notes` is an informational command; it renders under the Other help bucket.
    root.add_command(resume_session)
    # `resume` opens Pi's native session picker in a checkout (contracts.md §8.71) — a session
    # reopen, not a stage launch (no registry stage, no launcher grammar); the Other help bucket.
    root.add_command(run_worker_cmd)
    # `resume` and `replan` now live under the `plan` group. `replan` is still a dedicated
    # cold door, not a registry stage: it borrows `plan` to re-launch with the target plan's
    # original run_id (in-place upsert).
    register_stage_commands(root)


# `invoke_without_command=True` flips Click's `no_args_is_help` off, so bare `perk` runs this
# callback (the plain-session arm below) instead of dumping help; `--help` / `--version` stay
# eager and short-circuit first, and an unknown first token still fails in `resolve_command`.
# `deferred_registration` hands the whole command surface to SectionedGroup, which registers it
# on Click's first subcommand lookup/listing — after `--version` has already exited.
@click.group(
    cls=SectionedGroup,
    invoke_without_command=True,
    deferred_registration=_register_root_commands,
)
@click.version_option(__version__, prog_name="perk", message="%(prog)s %(version)s")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Plan-oriented engineering workflow for Pi.

    Bare `perk` opens a plain Pi session in the current checkout with perk's configured
    launch environment (the [pi] agent_dir redirect and launch env defaults) — no stage prompt,
    no run id, no handoff. Run `perk --help` for the commands.
    """
    # Cheap by design (no I/O) for every SUBCOMMAND invocation: require_* resolves the
    # repo/config lazily, so non-repo commands work outside a git repo. Only the bare
    # interactive form pays the launch I/O, in the plain-session arm at the end. Tests inject
    # obj=PerkContext.for_test(...).
    if ctx.obj is None:
        from perk.cli.context import PerkContext

        ctx.obj = PerkContext(cwd=Path.cwd())
    # Report-only version surfaces (warning first, notice second; both may appear). Their
    # cheap gates (env/TTY/argv/subcommand) all short-circuit before any I/O, so the no-I/O
    # property still holds for tests, CI, pipes, and machine consumers; only an interactive
    # human invocation pays one `git rev-parse` + one file read for the warning, plus at most
    # one read + one write of the user-level last-seen-version store for the notice.
    maybe_warn_version_mismatch(ctx.invoked_subcommand, ctx.obj.cwd)
    maybe_notice_upgrade(ctx.invoked_subcommand)
    if ctx.invoked_subcommand is None:
        from perk.cli.plain_session import run_plain_session

        run_plain_session(ctx)  # bare `perk`: a session launch that is not a stage launch


def main() -> None:
    cli()
