"""The ``perk-dev`` CLI root group (dev-only maintainer tooling; never published).

The bare group + one ``smoke`` verb prove the cross-package dependency on ``perk``
resolves and that both reuse seams — perk's version-reading and its git/LBYL helpers —
are importable. Later nodes hang real ``changelog-*`` / ``release-*`` verbs off this group.
"""

import datetime
import json
from pathlib import Path

import click

from perk import __version__ as _perk_version
from perk.cli.emit import fail
from perk.github import GitHubError
from perk.github import auth as gh_auth
from perk.substrate import git
from perk.substrate.bindings import load_bindings
from perk.substrate.config import load_config
from perk.substrate.git import repo_root
from perk.substrate.output import io_step, machine_output, user_output
from perk_dev import build, bump, changelog, release
from perk_dev.audit import corpus, expectations, vintage


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
        fail(ctx, as_json=as_json, error_type="not_a_repo", message="not inside a git repository")
        return
    try:
        result = changelog.gather(root, since_flag=since)
    except changelog.ChangelogError as exc:
        fail(ctx, as_json=as_json, error_type=exc.error_type, message=exc.message)
        return
    except git.GitError as exc:
        fail(ctx, as_json=as_json, error_type="git_error", message=str(exc))
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


def _release_summary_lines(info: release.ReleaseInfo) -> list[str]:
    """The pinned human summary (tests assert substrings; wording tweaks stay cheap)."""
    mismatch = " (\u2260 pyproject)"
    package = info.package_json_version or "none"
    if info.package_json_version is not None and info.package_json_version != info.current_version:
        package += mismatch
    runtime = info.runtime_version
    if runtime != info.current_version:
        runtime += mismatch
    versions = (
        f"pyproject {info.current_version} \u00b7 package.json {package} \u00b7 runtime {runtime}"
    )

    if info.tag_commit is None:
        tag = f"tag {info.tag_name}: missing"
    elif info.tag_at_head:
        tag = f"tag {info.tag_name}: at HEAD"
    else:
        tag = f"tag {info.tag_name}: at {info.tag_commit[:7]} (not HEAD)"
    origin = {True: "yes", False: "no", None: "unknown"}[info.tag_on_remote]
    tag += f" \u00b7 origin: {origin}"

    if info.latest_release_version is not None:
        latest = f"latest release: {info.latest_release_version} ({info.latest_release_date})"
    else:
        latest = "latest release: none"

    if info.marker_hash is None:
        marker = "marker: none"
    elif info.marker_commit is None:
        marker = f"marker: {info.marker_hash} (unresolvable)"
    elif info.marker_at_head:
        marker = f"marker: at HEAD ({info.marker_commit[:7]})"
    else:
        marker = f"marker: {info.marker_commit[:7]} behind HEAD ({info.head_commit[:7]})"

    return [versions, tag, latest, marker]


@cli.command("release-info")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def release_info(ctx: click.Context, *, as_json: bool) -> None:
    """Report machine-readable release state (versions, tag, latest release, changelog marker)."""
    root = repo_root(Path.cwd())
    if root is None:
        fail(ctx, as_json=as_json, error_type="not_a_repo", message="not inside a git repository")
        return
    try:
        info = release.gather(root)
    except release.ReleaseError as exc:
        fail(ctx, as_json=as_json, error_type=exc.error_type, message=exc.message)
        return
    if as_json:
        machine_output(json.dumps(release.ReleaseInfoOut.from_domain(info).model_dump(mode="json")))
    else:
        for line in _release_summary_lines(info):
            user_output(line)


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
        fail(ctx, as_json=False, error_type="not_a_repo", message="not inside a git repository")
        return
    try:
        proposal = changelog.load_proposal(Path(proposal_path))
        changelog_path = root / "CHANGELOG.md"
        if not changelog_path.exists():
            raise changelog.ChangelogError("changelog_not_found", f"{changelog_path} not found")
        text = changelog_path.read_text(encoding="utf-8")
        new_text = changelog.apply_to_text(text, proposal)
    except changelog.ChangelogError as exc:
        fail(ctx, as_json=False, error_type=exc.error_type, message=exc.message)
        return
    if dry_run:
        machine_output(changelog.extract_unreleased(new_text), nl=False)
        user_output("(dry run — no changes written)")
    else:
        changelog_path.write_text(new_text, encoding="utf-8")
        n = len(proposal.entries)
        entries = "entry" if n == 1 else "entries"
        user_output(f"Applied {n} {entries}; marker now {proposal.head_commit[:7]}")


@cli.command("bump-version")
@click.argument("version", required=False, metavar="[X.Y.Z]")
@click.option(
    "--bump",
    "bump_part",
    type=click.Choice(["patch", "minor", "major"]),
    default=None,
    help="Bump the current version by one component.",
)
@click.option("--dry-run", is_flag=True, help="Print the intended changes; write nothing.")
@click.pass_context
def bump_version(
    ctx: click.Context, *, version: str | None, bump_part: str | None, dry_run: bool
) -> None:
    """Bump the version SSOT + mirrors and roll [Unreleased] to a release section."""
    root = repo_root(Path.cwd())
    if root is None:
        fail(ctx, as_json=False, error_type="not_a_repo", message="not inside a git repository")
        return
    if (version is None) == (bump_part is None):
        fail(
            ctx,
            as_json=False,
            error_type="bad_arguments",
            message="pass exactly one of X.Y.Z or --bump patch|minor|major",
        )
        return
    today = datetime.date.today().isoformat()
    try:
        plan = bump.plan_bump(root, explicit=version, bump=bump_part, today=today)
    except (bump.BumpError, changelog.ChangelogError, release.ReleaseError) as exc:
        fail(ctx, as_json=False, error_type=exc.error_type, message=exc.message)
        return
    if plan.marker_behind_head:
        user_output(
            click.style("warning: ", fg="yellow")
            + "the [Unreleased] marker is behind HEAD — commits since it are not covered by "
            "this release's notes"
        )
    n = plan.rolled.entries
    entries = "entry" if n == 1 else "entries"
    roll_line = f"roll [Unreleased] → [{plan.target_version}] - {plan.date} ({n} {entries})"
    if dry_run:
        machine_output(
            changelog.extract_roll_preview(plan.rolled.text, plan.target_version), nl=False
        )
        user_output(f"bump {plan.current_version} → {plan.target_version}")
        user_output(roll_line)
        user_output("(dry run — no changes written)")
        return
    try:
        bump.execute(root, plan)
    except bump.BumpError as exc:
        fail(ctx, as_json=False, error_type=exc.error_type, message=exc.message)
        return
    user_output(f"pyproject.toml + uv.lock → {plan.target_version}")
    user_output(f"package.json + package-lock.json → {plan.target_version}")
    user_output(
        f"CHANGELOG.md: rolled [Unreleased] → [{plan.target_version}] - {plan.date} "
        f"({n} {entries}); marker now {plan.head_short}"
    )


@cli.command("changelog-check")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def changelog_check(ctx: click.Context, *, as_json: bool) -> None:
    """Validate CHANGELOG.md structure (markers, headers, categories, hash tokens)."""
    root = repo_root(Path.cwd())
    if root is None:
        fail(ctx, as_json=as_json, error_type="not_a_repo", message="not inside a git repository")
        return
    try:
        result = changelog.check(root)
    except changelog.ChangelogError as exc:
        fail(ctx, as_json=as_json, error_type=exc.error_type, message=exc.message)
        return
    if as_json:
        machine_output(
            json.dumps(changelog.ChangelogCheckOut.from_domain(result).model_dump(mode="json"))
        )
    else:
        _print_findings(result.findings)
        if not result.has_errors():
            user_output("CHANGELOG.md OK")
    if result.has_errors():
        ctx.exit(1)


def _print_findings(findings: tuple[changelog.Finding, ...]) -> None:
    """Print lint findings to stderr (severity-colored; `line N:` prefix when present).

    Shared by ``changelog-check`` and ``release-check`` — the two findings-vocabulary
    reporters.
    """
    for f in findings:
        colour = "red" if f.severity == "error" else "yellow"
        where = f"line {f.line}: " if f.line is not None else ""
        user_output(click.style(f"{f.severity}: ", fg=colour) + f"{where}{f.code} — {f.message}")


@cli.command("release-check")
@click.option(
    "--for-publish",
    "for_publish",
    is_flag=True,
    help="Additionally require a clean worktree.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def release_check(ctx: click.Context, *, for_publish: bool, as_json: bool) -> None:
    """Validate release state (changelog structure, version lockstep, tag agreement)."""
    root = repo_root(Path.cwd())
    if root is None:
        fail(ctx, as_json=as_json, error_type="not_a_repo", message="not inside a git repository")
        return
    try:
        result = release.check_release(root, for_publish=for_publish)
    except (release.ReleaseError, changelog.ChangelogError) as exc:
        fail(ctx, as_json=as_json, error_type=exc.error_type, message=exc.message)
        return
    if as_json:
        machine_output(
            json.dumps(release.ReleaseCheckOut.from_domain(result).model_dump(mode="json"))
        )
    else:
        _print_findings(result.findings)
        if not result.has_errors():
            user_output("release-check OK")
    if result.has_errors():
        ctx.exit(1)


@cli.command("release-build")
@click.pass_context
def release_build(ctx: click.Context) -> None:
    """Build + smoke both publish artifacts locally (uv build/twine/wheel; npm ci/pack)."""
    root = repo_root(Path.cwd())
    if root is None:
        fail(ctx, as_json=False, error_type="not_a_repo", message="not inside a git repository")
        return
    try:
        build.run_build(root)
    except build.BuildError as exc:
        fail(ctx, as_json=False, error_type=exc.error_type, message=exc.message)
        return
    user_output("release-build OK (wheel + sdist + npm tarball built and smoked; no publish)")


@cli.command("publish-check")
@click.option(
    "--allow-dirty",
    "allow_dirty",
    is_flag=True,
    help="Skip the clean-worktree requirement.",
)
@click.pass_context
def publish_check(ctx: click.Context, *, allow_dirty: bool) -> None:
    """Publication preflight: release-check + gh auth + origin-tag probe + release-build.

    A pure composition of the existing verbs (cheap \u2192 expensive, fail-fast) plus two
    additions of its own: a ``gh auth status`` check and a best-effort origin-tag incident
    preflight (warn-only \u2014 a tag already on origin is a legitimate mid-release state;
    the incident runbook in docs/releasing.md owns the judgment).
    """
    root = repo_root(Path.cwd())
    if root is None:
        fail(ctx, as_json=False, error_type="not_a_repo", message="not inside a git repository")
        return

    # release-check composition: --allow-dirty maps onto the existing for_publish clean-tree arm.
    try:
        result = release.check_release(root, for_publish=not allow_dirty)
    except (release.ReleaseError, changelog.ChangelogError) as exc:
        fail(ctx, as_json=False, error_type=exc.error_type, message=exc.message)
        return
    _print_findings(result.findings)
    if result.has_errors():
        ctx.exit(1)

    try:
        with io_step("gh auth status"):
            status = gh_auth.check_auth()
    except GitHubError as exc:
        fail(
            ctx,
            as_json=False,
            error_type="gh_auth_failed",
            message=f"{exc} \u2014 run `gh auth login`",
        )
        return
    if not status.ok:
        fail(
            ctx,
            as_json=False,
            error_type="gh_auth_failed",
            message=f"{status.error or 'gh is not authenticated'} \u2014 run `gh auth login`",
        )
        return

    # Incident preflight: best-effort, never fails the command (tri-state probe).
    try:
        current = release.read_current_version(root)
    except release.ReleaseError as exc:
        fail(ctx, as_json=False, error_type=exc.error_type, message=exc.message)
        return
    tag_name = f"v{current}"
    with io_step(f"probe origin for tag {tag_name}") as step:
        on_remote, _remote_sha = release.probe_remote_tag(root, tag_name)
        if on_remote is None:
            step.warn(f"origin probe for tag {tag_name} skipped/failed \u2014 state unknown")
    if on_remote is True:
        user_output(
            click.style("warning: ", fg="yellow")
            + f"tag {tag_name} already exists on origin \u2014 mid-release or a publish "
            'incident; see docs/releasing.md \u2192 "Incident handling"'
        )

    try:
        build.run_build(root)
    except build.BuildError as exc:
        fail(ctx, as_json=False, error_type=exc.error_type, message=exc.message)
        return
    user_output("publish-check OK \u2014 ready to tag (see docs/releasing.md)")


@cli.command("release-tag")
@click.option("--push", "push", is_flag=True, help="Push the tag to origin after creating it.")
@click.option("--dry-run", is_flag=True, help="Validate and print intent; write/push nothing.")
@click.pass_context
def release_tag(ctx: click.Context, *, push: bool, dry_run: bool) -> None:
    """Create the annotated release tag v{version} derived from the pyproject SSOT."""
    root = repo_root(Path.cwd())
    if root is None:
        fail(ctx, as_json=False, error_type="not_a_repo", message="not inside a git repository")
        return
    try:
        plan = release.plan_release_tag(root)
    except release.ReleaseError as exc:
        fail(ctx, as_json=False, error_type=exc.error_type, message=exc.message)
        return
    short = plan.head_commit[:7]
    if dry_run:
        if plan.already_at_head:
            user_output(f"tag {plan.tag_name} already at HEAD — nothing to do")
        else:
            user_output(f"would create annotated tag {plan.tag_name} at {short}")
        if push:
            user_output(f"would push {plan.tag_name} to origin")
        user_output("(dry run — no changes written)")
        return
    release.execute_release_tag(root, plan)
    if plan.already_at_head:
        user_output(f"tag {plan.tag_name} already at HEAD — nothing to do")
    else:
        user_output(f"created annotated tag {plan.tag_name} at {short}")
    if push:
        if not git.has_remote(root):
            fail(
                ctx,
                as_json=False,
                error_type="no_remote",
                message="no `origin` remote configured",
            )
            return
        try:
            with io_step(f"push tag {plan.tag_name} to origin"):
                git.push_tag(root, plan.tag_name)
        except git.GitError as exc:
            fail(ctx, as_json=False, error_type="push_failed", message=str(exc))
            return


@cli.group("audit")
def audit() -> None:
    """Session-audit tooling: the expectation-catalog census (and later, the runner)."""


def _census_summary_lines(census: corpus.Census) -> list[str]:
    """The pinned human summary (tests assert substrings; wording tweaks stay cheap)."""

    def counts(values: dict[str, int]) -> str:
        if not values:
            return "none"
        return " \u00b7 ".join(f"{key} {count}" for key, count in values.items())

    totals = census.totals
    lines = [
        f"sessions root: {census.sessions_root}",
        f"main root: {census.main_root}",
        f"worktree root: {census.worktree_root}",
        f"candidate dirs: {len(census.candidate_dirs)} \u00b7 "
        f"candidate files: {totals.candidate_files}",
        f"confirmed {totals.confirmed} \u00b7 unconfirmed {totals.unconfirmed} \u00b7 "
        f"foreign {totals.foreign} \u00b7 unreadable {totals.unreadable} \u00b7 "
        f"malformed lines {totals.malformed_lines}",
        f"identity: {counts(census.identity_counts)}",
        f"stages: {counts(census.stage_counts)}",
        f"modes: {counts(census.mode_counts)}",
        f"triggers: {counts(census.trigger_counts)}",
        f"pointer joins: {counts(census.pointer_join_counts)}",
        f"release history: {census.release_count} releases",
        f"vintage: {counts(census.vintage_basis_counts)}",
        "expectations:",
    ]
    for coverage in census.expectations:
        applies = ", ".join(coverage.applies_to)
        lines.append(
            f"  {coverage.id} ({applies}): {coverage.exercising_sessions} exercising \u00b7 "
            f"{coverage.applicable_sessions} applicable \u00b7 "
            f"{coverage.not_applicable_sessions} not-applicable \u00b7 "
            f"{coverage.vintage_unknown_sessions} vintage-unknown"
        )
    if census.not_exercised:
        lines.append(click.style("not exercised: ", fg="yellow") + ", ".join(census.not_exercised))
    else:
        lines.append("not exercised: none")
    return lines


@audit.command("census")
@click.option(
    "--sessions-root",
    "sessions_root_opt",
    default=None,
    metavar="<dir>",
    help="Override the Pi session-history root (default: ~/.pi/agent/sessions).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit the full census envelope to stdout.")
@click.pass_context
def audit_census(ctx: click.Context, *, sessions_root_opt: str | None, as_json: bool) -> None:
    """Census this repo's Pi session corpus (identification + coverage; no verdicts)."""
    root = repo_root(Path.cwd())
    if root is None:
        fail(ctx, as_json=as_json, error_type="not_a_repo", message="not inside a git repository")
        return
    main_root = git.main_worktree_root(root) or root
    worktree_root = load_config(main_root).worktree_root
    try:
        catalog = expectations.load_catalog()
    except expectations.ExpectationsError as exc:
        fail(ctx, as_json=as_json, error_type="bad_catalog", message=str(exc))
        return
    sessions_root = (
        Path(sessions_root_opt) if sessions_root_opt is not None else corpus.default_sessions_root()
    )
    census = corpus.build_census(
        sessions_root=sessions_root,
        main_root=main_root,
        worktree_root=worktree_root,
        catalog=catalog,
        bindings=load_bindings().bindings,
        history=vintage.load_release_history(main_root),
    )
    if as_json:
        machine_output(json.dumps(corpus.CensusOut.from_domain(census).model_dump(mode="json")))
    else:
        for line in _census_summary_lines(census):
            user_output(line)


def main() -> None:
    cli()
