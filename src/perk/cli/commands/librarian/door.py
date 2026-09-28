"""The docs doors' CLI glue: seed rendering, the session launch, and the dry-run relay
(contracts.md §8.75(k)).

``perk librarian add docs`` and the human ``perk librarian refresh <slug>`` of a documentation
entry are write-capable cold doors in the ``perk skills create`` shape: each borrows the ``save``
stage descriptor for launch (``mode: read-write``, ``worktree: none`` → the main checkout; the
borrow is otherwise inert) and overrides ``binding_trigger`` so the ``librarian`` skill is
delivered instead of ``stage:save``'s. The deterministic half — checks, the staging claim, the
command construction — is :mod:`perk.library.docs_session`; this module only presents it.

There is no structural sandbox: "write only under the gitignored library" is a soft scope the
seed carries.
"""

from collections.abc import Sequence

import click

from perk.cli.commands.librarian.shared import fail_library_error
from perk.cli.context import require_config
from perk.cli.emit import fail
from perk.library import (
    SEED_REDIRECT_EXIT,
    DocsCrawlPlan,
    parse_seed_redirect,
    run_dry_run,
    seed_redirect_error,
)
from perk.prompts import render
from perk.run import launch
from perk.substrate.output import user_output
from perk.substrate.registry import stage_by_id


def _seed_vars(plan: DocsCrawlPlan) -> dict[str, str]:
    # `scope_prefix` is always passed ("" when defaulted) so the conditional stays byte-stable;
    # only the pre-quoted command strings are ever presented as something to run.
    return {
        "url": plan.url,
        "slug": plan.slug,
        "scope_prefix": plan.scope_prefix,
        "staging_dir": str(plan.staging_dir),
        "crawl_command": plan.crawl_command,
        "publish_command": plan.publish_command,
    }


def render_add_seed(plan: DocsCrawlPlan) -> str:
    return render("stages/librarian/add-docs.md", _seed_vars(plan))


def render_refresh_seed(plan: DocsCrawlPlan) -> str:
    return render(
        "stages/librarian/refresh-docs.md",
        {**_seed_vars(plan), "current_dir": str(plan.current_dir)},
    )


def launch_docs_session(
    ctx: click.Context,
    *,
    plan: DocsCrawlPlan,
    seed: str,
    trigger: str,
    pi_args: Sequence[str],
    note: str,
) -> None:
    """Head the launch with the banner, narrate the door's resolution, then exec pi."""
    config = require_config(ctx)
    launch.print_launch_banner_gated(plan.main_root, dry_run=False, remote=None)
    user_output(note)
    for warning in plan.warnings:
        user_output(f"warning: {warning}")
    launch.launch_stage(
        repo_root=plan.main_root,
        config=config,
        # The borrowed write-capable launch descriptor (``mode: read-write``, ``worktree: none``).
        stage=stage_by_id("save"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=list(pi_args),
        prompt_override=seed,
        binding_trigger=trigger,
    )


def relay_dry_run(ctx: click.Context, plan: DocsCrawlPlan) -> None:
    """Run the crawl script's dry-run, relay its URL → file map, and map its exit code.

    ``0`` / ``1`` (a discovery fetch failed) are relayed; ``3`` (the seed is only an HTML redirect
    page) is ``seed_redirect``, its blocker line re-validated before the reissue is named; ``2``
    is ``crawl_refused``; any other code (a signal's negative code included) is ``io_error`` —
    nothing falls through as success. A ``LibraryError`` from the run propagates to the command's
    failure boundary.
    """
    user_output(click.style("librarian add docs --dry-run (no session)", dim=True))
    scope = plan.scope_prefix or "(default)"
    user_output(f"  slug={plan.slug}  staging={plan.staging_dir}  scope={scope}")
    completed = run_dry_run(plan)
    for line in (*completed.stdout.splitlines(), *completed.stderr.splitlines()):
        user_output(line)
    code = completed.returncode
    if code in (0, 1):
        ctx.exit(code)
    if code == SEED_REDIRECT_EXIT:
        blocker = parse_seed_redirect(completed.stdout)
        fail_library_error(ctx, seed_redirect_error(plan, blocker), as_json=False)
        return
    stderr = completed.stderr.strip()
    if code == 2:
        fail(
            ctx,
            as_json=False,
            error_type="crawl_refused",
            message=stderr or "the crawl script refused the dry-run",
        )
        return
    tail = stderr.splitlines()[-1] if stderr else "(no stderr)"
    fail(
        ctx,
        as_json=False,
        error_type="io_error",
        message=f"the crawl script's dry-run exited {code} unexpectedly: {tail}",
    )
