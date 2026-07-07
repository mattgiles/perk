"""``perk learn docs`` — the learned-docs plan-factory cold door (hop-2).

The doc-destined consumer of the terminal ``perk:learn`` issues. A **plan factory** (mirroring
``objective-plan``, NOT a direct doc-writer): gather the open ``perk:learn`` issues, route the
**doc-destined** subset (every classification except a pre-stamped ``SHOULD_BE_CODE`` — those go to
``perk learn code``; legacy/unclassified default to docs) into an inbox, and launch a **read-only
plan-mode session** that synthesizes them into a normal ``perk:plan`` documentation plan whose steps
create/update ``docs/learned/<category>/*.md`` and regenerate the routing (``docs/learned/index.md``
+ ``.pi/APPEND_SYSTEM.md``) via ``perk learn docs-sync`` — never by hand. That docs plan then rides
``implement → submit → land`` unchanged; on land the consumed ``perk:learn`` issues close + get
``perk:consolidated``.

**Curator AND verifier.** The gather filter is the *default* route; the factory still applies the
knowledge-placement hierarchy and, when a doc-destined learning actually belongs in
code/comment/docstring/schema/user-docs, **emits a ``SHOULD_BE_CODE`` follow-up step** instead of
forcing a learned doc. The inbox is widened with each learning's captured classification + the
existing-docs scan (cleanup-first + UPDATE-vs-NEW).

The read-only factory session reads the materialized inbox via the ``read`` tool — the read-only
bash allowlist excludes ``gh``/``perk``, so this cold door performs every GitHub read up front.

A **dedicated** command (not a registry stage): it borrows the existing ``plan`` stage descriptor
for launch (``mode: read-only``, ``worktree: none``). Supervisor surface (cli-vs-pi §3.2):
``--json`` → stdout, human text → stderr, stable exits (``0`` ok · ``1`` op-failure/no-issues ·
``2`` not-a-repo).
"""

import click

from perk.cli.commands.learn.factory_common import DOCS_FACTORY, run_factory
from perk.cli.commands.seeded_door import seeded_door_options


@click.command("docs", context_settings={"ignore_unknown_options": True})
@click.option(
    "--gather",
    "gather_only",
    is_flag=True,
    help="Materialize the inbox + emit {inbox_path, learn_numbers}; launch nothing (warm path).",
)
@seeded_door_options(
    worktree_help="Worktree to position (learn-docs runs at repo root).",
    dry_run_help="Gather + print the inbox/seed; launch nothing.",
    remote_subject="learn-docs",
)
@click.pass_context
def docs_learn(
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
    """Consolidate doc-destined perk:learn issues into a docs/learned plan (read-only factory).

    \b
    Examples:
      perk learn docs               # gather + launch the read-only docs plan factory
      perk learn docs --gather --json   # materialize the inbox + emit numbers (no launch)
      perk learn docs --dry-run     # gather + print the inbox/seed, launch nothing
    """
    run_factory(
        ctx,
        kind=DOCS_FACTORY,
        gather_only=gather_only,
        worktree=worktree,
        dry_run=dry_run,
        remote=remote,
        as_json=as_json,
        no_sync=no_sync,
        pi_args=pi_args,
    )
