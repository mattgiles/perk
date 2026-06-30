"""``perk learn code`` — the code-routing plan-factory cold door (hop-2 sibling of ``learn docs``).

The dedicated sweep for the **pre-stamped ``SHOULD_BE_CODE``** learnings: ``/learn`` classifies a
learning whose home is code/comment/docstring/schema/user-docs (not a learned doc) as
``SHOULD_BE_CODE`` on its ``perk:learn`` header; this factory gathers exactly those, materializes
them into a lean inbox (classification + ``target`` + no docs scan), and launches a **read-only
plan-mode session** that authors a normal ``perk:plan`` plan landing each insight in its real code
home. That plan rides ``implement → submit → land`` unchanged; on land the consumed ``perk:learn``
issues close + get ``perk:consolidated``.

Additive to ``learn docs`` (NOT a replacement): ``learn docs`` keeps its placement-hierarchy
verifier license and may still emit a ``SHOULD_BE_CODE`` follow-up step for a doc-stamped learning
that belongs in code. This factory just pre-routes the common, pre-classified code case.

The read-only factory session reads the materialized inbox via the ``read`` tool — the read-only
bash allowlist excludes ``gh``/``perk``, so this cold door performs every GitHub read up front.

A **dedicated** command (not a registry stage): it borrows the existing ``plan`` stage descriptor
for launch (``mode: read-only``, ``worktree: none``). Supervisor surface (cli-vs-pi §3.2):
``--json`` → stdout, human text → stderr, stable exits (``0`` ok · ``1`` op-failure/no-issues ·
``2`` not-a-repo).
"""

import click

from perk.cli.commands.learn.factory_common import CODE_FACTORY, run_factory


@click.command("code", context_settings={"ignore_unknown_options": True})
@click.option(
    "--gather",
    "gather_only",
    is_flag=True,
    help="Materialize the inbox + emit {inbox_path, learn_numbers}; launch nothing (warm path).",
)
@click.option("--worktree", help="Worktree to position (learn-code runs at repo root).")
@click.option("--dry-run", is_flag=True, help="Gather + print the inbox/seed; launch nothing.")
@click.option(
    "--remote",
    type=str,
    default=None,
    is_flag=False,
    flag_value="",
    help="Local (default) or a remote runner; learn-code is local-only (cold_remote:false).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.option(
    "--no-sync",
    "no_sync",
    is_flag=True,
    help="Skip the pre-launch fast-forward of the main checkout.",
)
@click.argument("pi_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def code_learn(
    ctx: click.Context,
    *,
    gather_only: bool,
    worktree: str | None,
    dry_run: bool,
    remote: str | None,
    as_json: bool,
    no_sync: bool,
    pi_args: tuple[str, ...],
) -> None:
    """Route pre-stamped SHOULD_BE_CODE perk:learn issues into a code plan (read-only factory).

    \b
    Examples:
      perk learn code               # gather + launch the read-only code plan factory
      perk learn code --gather --json   # materialize the inbox + emit numbers (no launch)
      perk learn code --dry-run     # gather + print the inbox/seed, launch nothing
    """
    run_factory(
        ctx,
        kind=CODE_FACTORY,
        gather_only=gather_only,
        worktree=worktree,
        dry_run=dry_run,
        remote=remote,
        as_json=as_json,
        no_sync=no_sync,
        pi_args=pi_args,
    )
