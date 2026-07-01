"""The ``perk-dev`` CLI root group (dev-only maintainer tooling; never published).

The bare group + one ``smoke`` verb prove the cross-package dependency on ``perk``
resolves and that both reuse seams — perk's version-reading and its git/LBYL helpers —
are importable. Later nodes hang real ``changelog-*`` / ``release-*`` verbs off this group.
"""

import json
from pathlib import Path

import click

from perk import __version__ as _perk_version
from perk.substrate.git import repo_root
from perk.substrate.output import machine_output, user_output
from perk_dev import changelog

_EXIT_FOR_TYPE = {"not_a_repo": 2}


def _fail(ctx: click.Context, *, as_json: bool, error_type: str, message: str) -> None:
    if as_json:
        machine_output(json.dumps({"success": False, "error_type": error_type, "message": message}))
    else:
        user_output(click.style("Error: ", fg="red") + message)
    ctx.exit(_EXIT_FOR_TYPE.get(error_type, 1))


@click.group()
@click.version_option(_perk_version, prog_name="perk-dev", message="%(prog)s %(version)s")
def cli() -> None:
    """perk's internal maintainer/release tooling (dev-only; never published)."""


@cli.command("smoke")
def smoke() -> None:
    """Smoke-check that perk-dev can reach perk's reused version + git helpers."""
    root = repo_root(Path.cwd())
    where = str(root) if root is not None else "(not a git repo)"
    click.echo(f"perk-dev smoke: perk {_perk_version} @ {where}")


@cli.command("changelog-commits")
@click.option(
    "--since",
    default=None,
    metavar="<commit>",
    help="Override the since-commit (skip changelog marker discovery).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def changelog_commits(ctx: click.Context, *, since: str | None, as_json: bool) -> None:
    """Report first-parent commits between the changelog cursor (or --since) and HEAD."""
    root = repo_root(Path.cwd())
    if root is None:
        _fail(ctx, as_json=as_json, error_type="not_a_repo", message="not inside a git repository")
        return
    try:
        result = changelog.gather(root, since_flag=since)
    except changelog.ChangelogError as exc:
        _fail(ctx, as_json=as_json, error_type=exc.error_type, message=exc.message)
        return
    if as_json:
        machine_output(
            json.dumps(changelog.ChangelogCommitsOut.from_domain(result).model_dump(mode="json"))
        )
    else:
        user_output(
            f"since {result.since_commit[:7]} ({result.since_source}) → "
            f"{result.head_commit[:7]} (HEAD)  ·  {len(result.commits)} commits"
        )
        for c in result.commits:
            pr = f" (PR #{c.pr})" if c.pr is not None else ""
            user_output(f"  {c.hash[:7]}  {c.subject}{pr}")


@cli.command("changelog-apply")
@click.option(
    "--proposal",
    "proposal_path",
    required=True,
    metavar="<file>",
    help="Path to the approved proposal JSON.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the intended new [Unreleased] section; write nothing.",
)
@click.pass_context
def changelog_apply(ctx: click.Context, *, proposal_path: str, dry_run: bool) -> None:
    """Apply an approved changelog proposal: append its entries and advance the marker."""
    root = repo_root(Path.cwd())
    if root is None:
        _fail(ctx, as_json=False, error_type="not_a_repo", message="not inside a git repository")
        return
    try:
        proposal = changelog.load_proposal(Path(proposal_path))
        changelog_path = root / "CHANGELOG.md"
        if not changelog_path.exists():
            raise changelog.ChangelogError("changelog_not_found", f"{changelog_path} not found")
        text = changelog_path.read_text(encoding="utf-8")
        new_text = changelog.apply_to_text(text, proposal)
    except changelog.ChangelogError as exc:
        _fail(ctx, as_json=False, error_type=exc.error_type, message=exc.message)
        return
    if dry_run:
        machine_output(changelog.extract_unreleased(new_text), nl=False)
        user_output("(dry run — no changes written)")
    else:
        changelog_path.write_text(new_text, encoding="utf-8")
        n = len(proposal.entries)
        entries = "entry" if n == 1 else "entries"
        user_output(f"Applied {n} {entries}; marker now {proposal.head_commit[:7]}")


@cli.command("changelog-check")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def changelog_check(ctx: click.Context, *, as_json: bool) -> None:
    """Validate CHANGELOG.md structure (markers, headers, categories, hash tokens)."""
    root = repo_root(Path.cwd())
    if root is None:
        _fail(ctx, as_json=as_json, error_type="not_a_repo", message="not inside a git repository")
        return
    try:
        result = changelog.check(root)
    except changelog.ChangelogError as exc:
        _fail(ctx, as_json=as_json, error_type=exc.error_type, message=exc.message)
        return
    if as_json:
        machine_output(
            json.dumps(changelog.ChangelogCheckOut.from_domain(result).model_dump(mode="json"))
        )
    else:
        for f in result.findings:
            colour = "red" if f.severity == "error" else "yellow"
            where = f"line {f.line}: " if f.line is not None else ""
            user_output(
                click.style(f"{f.severity}: ", fg=colour) + f"{where}{f.code} — {f.message}"
            )
        if not result.has_errors():
            user_output("CHANGELOG.md OK")
    if result.has_errors():
        ctx.exit(1)


def main() -> None:
    cli()
