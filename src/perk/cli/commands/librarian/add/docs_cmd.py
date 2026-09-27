"""``perk librarian add docs`` — the door that launches a session to mirror a documentation site
(contracts.md §8.75(k)).

Mirroring a site is judgment work (scoping, pruning, artifact fixes), so there is no session-free
add: the door validates the inputs, refuses before any session when the slug is taken, the
``librarian`` skill's crawl script is not installed or a converter is missing, runs the cache-only
preflight, claims an empty staging directory, and launches a curating session in the main checkout
seeded with the exact crawl and publish commands. ``--dry-run`` runs the crawl script's own
dry-run instead — the URL → file map, no session, nothing written.

No ``--json``: the door's success is an exec, its dry-run payload is the script's human map, and
the read-only gate never admits it. Trailing arguments pass through to ``pi``.

Exit codes: 0 ok (dry-run: every page discoverable) · 1 typed refusal / op failure (dry-run: a
discovery fetch failed) · 2 not-a-repo.
"""

import click

from perk.cli.commands.librarian.door import launch_docs_session, relay_dry_run, render_add_seed
from perk.cli.commands.librarian.shared import fail_library_error, validate_source_url
from perk.cli.context import require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.library import LibraryError, plan_add_docs


@click.command("docs", context_settings={"ignore_unknown_options": True})
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
@click.option(
    "--dry-run", is_flag=True, help="Preview the URL → file map; launch nothing, write nothing."
)
@click.argument("pi_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def add_docs_cmd(
    ctx: click.Context,
    *,
    url: str,
    slug: str | None,
    scope_prefix: str | None,
    dry_run: bool,
    pi_args: tuple[str, ...],
) -> None:
    """Launch a session that mirrors a documentation site into the library.

    The door creates the empty `docs/library/.staging/<slug>` directory the session crawls into
    (a fresh `<slug>-2`, … when that name is taken) and never deletes one. Trailing arguments
    pass through to `pi`.

    \b
    Examples:
      perk librarian add docs https://pi.dev/docs --dry-run   # the URL → file map, no session
      perk librarian add docs https://pi.dev/docs             # slug pi; launch the session
      perk librarian add docs https://docs.astro.build/en/install/ --scope-prefix /en/
    """
    try:
        repo_root = require_repo(ctx)
        url = validate_source_url(url, label="URL")
        plan = plan_add_docs(
            repo_root, url=url, slug=slug, scope_prefix=scope_prefix, dry_run=dry_run
        )
        if dry_run:
            relay_dry_run(ctx, plan)
            return
        launch_docs_session(
            ctx,
            plan=plan,
            seed=render_add_seed(plan),
            trigger="command:librarian-add",
            pi_args=pi_args,
            note=(
                f"adding documentation entry {plan.slug} from {plan.url} — staging "
                f"{plan.staging_dir}; launching session"
            ),
        )
    except LibraryError as exc:
        fail_library_error(ctx, exc, as_json=False)
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=False,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
