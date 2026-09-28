"""``perk librarian prepare docs`` — the ``add docs`` door's pre-session half plus the staging
claim, emitted as the crawl plan (contracts.md §8.75(k)).

Exactly the door's order — URL validation (a seed outside an explicit ``--scope-prefix`` is
``invalid_input``), the slug rule, eligibility (``slug_exists``), the skill and converter
prerequisites, the cache-only preflight, the seed probe (``seed_redirect``; any other probe outcome
is a ``warnings[]`` entry) — then the atomic claim of an empty ``.staging/<slug>[-N]`` directory.
Launches nothing.

Exit codes: 0 ok · 1 typed refusal / op failure · 2 not-a-repo.
"""

import click

from perk.cli.commands.librarian.prepare.shared import emit_plan, fail_prepare
from perk.cli.commands.librarian.shared import validate_source_url
from perk.cli.context import require_repo
from perk.cli.ensure import UserFacingCliError
from perk.library import LibraryError, plan_add_docs


@click.command("docs")
@click.argument("url")
@click.option(
    "--slug",
    default=None,
    help="The entry slug (defaults to the URL's first host label after dropping www./docs.).",
)
@click.option(
    "--scope-prefix",
    default=None,
    help="The URL path prefix to keep in scope, e.g. /docs/ (/ keeps the whole site; defaults "
    "to the seed URL's parent path).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable plan to stdout.")
@click.pass_context
def prepare_docs_cmd(
    ctx: click.Context, *, url: str, slug: str | None, scope_prefix: str | None, as_json: bool
) -> None:
    """Claim a staging directory and print the crawl plan for a new documentation entry.

    The run_librarian tool's worker: it creates the empty `docs/library/.staging/<slug>`
    directory (a fresh `<slug>-2`, … when taken) and launches nothing.
    """
    try:
        repo_root = require_repo(ctx)
        url = validate_source_url(url, label="URL")
        plan = plan_add_docs(
            repo_root, url=url, slug=slug, scope_prefix=scope_prefix, dry_run=False
        )
    except (LibraryError, UserFacingCliError) as exc:
        fail_prepare(ctx, exc, as_json=as_json)
        return
    emit_plan("add-docs", plan, as_json=as_json)
