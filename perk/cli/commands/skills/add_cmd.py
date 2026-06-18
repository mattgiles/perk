"""`perk skills add` — add a skill (and its source) to this repo and sync (pass-through)."""

import click

from perk.cli.commands.skills.shared import run_skills
from perk.cli.context import require_repo


@click.command("add")
@click.option("--source", required=True, help="The source alias to add the skill under.")
@click.option("--skill", required=True, help="The skill name to add.")
@click.option(
    "--source-url",
    help="The source's git URL. Required for a new source; optional when already declared.",
)
@click.option(
    "--ref",
    help="Pin the source to a git ref (defaults to the remote's default branch).",
)
@click.pass_context
def add_skill(
    ctx: click.Context, *, source: str, skill: str, source_url: str | None, ref: str | None
) -> None:
    """Add a skill (and its source) to this repo and sync.

    A pass-through to `skills add <source> <skill> [--url URL] [--ref REF]`. `skills` owns all the
    source logic: reuse-existing-alias when ``--source-url`` is omitted, require-url for a new
    source, sync, and rollback on a sync failure.
    """
    argv = ["add", source, skill]
    if source_url is not None:
        argv += ["--url", source_url]
    if ref is not None:
        argv += ["--ref", ref]
    run_skills(ctx, argv, cwd=require_repo(ctx))
