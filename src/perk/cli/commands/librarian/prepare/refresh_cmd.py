"""``perk librarian prepare refresh`` — the docs-refresh door's pre-session half plus the staging
claim, emitted as the crawl plan (contracts.md §8.75(k)).

Documentation entries only (``entry_not_found`` for an absent slug or a source entry); the prior
crawl's scope is recovered advisorily (an unusable recorded value falls back to the default
scope with a warning); the seed probe over the entry's source refuses ``seed_redirect`` before the
claim; the publish command carries ``--replace``. Launches nothing.

Exit codes: 0 ok · 1 typed refusal / op failure · 2 not-a-repo.
"""

import click

from perk.cli.commands.librarian.prepare.shared import emit_plan, fail_prepare
from perk.cli.context import require_repo
from perk.cli.ensure import UserFacingCliError
from perk.library import LibraryError, plan_refresh_docs


@click.command("refresh")
@click.argument("slug")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable plan to stdout.")
@click.pass_context
def prepare_refresh_cmd(ctx: click.Context, *, slug: str, as_json: bool) -> None:
    """Claim a staging directory and print the re-crawl plan for a documentation entry.

    The run_librarian tool's worker: the plan re-uses the entry's source URL and recorded scope
    and publishes with --replace; it launches nothing.
    """
    try:
        repo_root = require_repo(ctx)
        plan = plan_refresh_docs(repo_root, slug=slug)
    except (LibraryError, UserFacingCliError) as exc:
        fail_prepare(ctx, exc, as_json=as_json)
        return
    emit_plan("refresh-docs", plan, as_json=as_json)
