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
from perk.cli.commands.seeded_door import SeededLaunch, run_seeded_door, seeded_door_options
from perk.cli.context import PerkContext
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.github import auth as gh_auth
from perk.prompts import render
from perk.run import launch
from perk.state import cache
from perk.substrate import git
from perk.substrate.bindings import load_bindings
from perk.substrate.config import Config, load_config
from perk.substrate.git import repo_root
from perk.substrate.output import io_step, machine_output, user_output
from perk.substrate.registry import Stage
from perk_dev import build, bump, changelog, release
from perk_dev.audit import bounding, corpus, expectations, fold, runner, vintage


@click.group()
@click.version_option(_perk_version, prog_name="perk-dev", message="%(prog)s %(version)s")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """perk's internal maintainer/release tooling (dev-only; never published)."""
    # The seeded-door pipeline (`audit judge`) resolves the repo + config lazily through the
    # PerkContext on ctx.obj (require_repo/require_config); every other verb ignores it.
    ctx.obj = PerkContext(cwd=Path.cwd())


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
    """Session-audit tooling: the corpus census, the deterministic runner, evidence
    bundling, the judgment-wave door, and the judgment fold."""


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


def _audit_render_lines(
    report: runner.AuditReport, *, expectation_ids: tuple[str, ...]
) -> list[tuple[str, bool]]:
    """The pinned human summary as pure ``(text, warn)`` lines — UNSTYLED, so the same
    builder feeds the ``audit run``/``audit fold`` renders (the CLI colors at the emit
    edge) and the ``audit judge`` seed's injected deterministic summary (plain text).
    Tests assert substrings; wording tweaks stay cheap."""

    def counts(values: dict[str, int]) -> str:
        return " \u00b7 ".join(f"{key} {count}" for key, count in values.items())

    expectations_line = (
        f"expectations: {len(report.results)} "
        f"({report.deterministic_count} deterministic \u00b7 {report.judgment_count} judgment)"
    )
    if expectation_ids:
        expectations_line += f" \u00b7 filter: {', '.join(r.id for r in report.results)}"
    lines: list[tuple[str, bool]] = [
        (f"sessions root: {report.sessions_root}", False),
        (f"confirmed sessions: {report.confirmed_sessions}", False),
        (expectations_line, False),
        (f"verdicts: {counts(report.totals)}", False),
    ]
    for result in report.results:
        if result.not_exercised:
            lines.append((f"  {result.id}: not exercised", False))
        else:
            lines.append(
                (
                    f"  {result.id} [{result.tier}]: {result.exercising} exercising \u2014 "
                    f"{counts(result.status_counts)}",
                    False,
                )
            )
    violated = [
        (result.id, cell)
        for result in report.results
        for cell in result.cells
        if cell.status == "violated"
    ]
    if not violated:
        lines.append(("violations: none", False))
        return lines
    lines.append(("violations:", True))
    for expectation_id, cell in violated:
        entries = ", ".join(str(i) for i in cell.entries)
        vintage_text = f"{cell.vintage_version or 'unknown'}/{cell.vintage_basis}"
        lines.append(
            (
                f"  {expectation_id} \u00b7 {cell.session_basename} \u00b7 "
                f"entries {entries} \u00b7 vintage {vintage_text}",
                True,
            )
        )
        lines.append((f"    {cell.detail}", False))
    return lines


def _emit_render_lines(lines: list[tuple[str, bool]]) -> None:
    """Emit pure ``(text, warn)`` render lines, coloring warn lines at this edge."""
    for text, warn in lines:
        user_output(click.style(text, fg="yellow") if warn else text)


@audit.command("run")
@click.option(
    "--sessions-root",
    "sessions_root_opt",
    default=None,
    metavar="<dir>",
    help="Override the Pi session-history root (default: ~/.pi/agent/sessions).",
)
@click.option(
    "--expectation",
    "expectation_ids",
    multiple=True,
    metavar="<id>",
    help="Limit the report to the named expectation id(s) (repeatable; default: all).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit the verdict-matrix envelope to stdout.")
@click.pass_context
def audit_run(
    ctx: click.Context,
    *,
    sessions_root_opt: str | None,
    expectation_ids: tuple[str, ...],
    as_json: bool,
) -> None:
    """Run the deterministic audit over this repo's session corpus (report, never a gate).

    A successfully generated report exits 0 regardless of verdicts — violations are
    leads for human calibration, not CI failures.
    """
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
    known = {e.id for e in catalog.expectations}
    unknown = sorted(set(expectation_ids) - known)
    if unknown:
        known_ids = ", ".join(e.id for e in catalog.expectations)
        fail(
            ctx,
            as_json=as_json,
            error_type="bad_arguments",
            message=f"unknown expectation id(s): {', '.join(unknown)} (known: {known_ids})",
        )
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
    report = runner.run_audit(census=census, catalog=catalog, expectation_ids=expectation_ids)
    if as_json:
        machine_output(
            json.dumps(runner.AuditReportOut.from_domain(report).model_dump(mode="json"))
        )
    else:
        _emit_render_lines(_audit_render_lines(report, expectation_ids=expectation_ids))


def _evidence_summary_lines(report: bounding.EvidenceBundleReport) -> list[str]:
    """The pinned human summary (tests assert substrings; wording tweaks stay cheap)."""

    def counts(values: dict[str, int]) -> str:
        return " \u00b7 ".join(f"{key} {count}" for key, count in values.items())

    lines = [
        f"sessions root: {report.sessions_root}",
        f"main root: {report.main_root}",
        f"worktree root: {report.worktree_root}",
        f"bundle dir: {report.bundle_dir}",
        f"budget: {report.max_packet_tokens} tokens/packet \u00b7 "
        f"cap: {report.max_sessions} sessions/expectation \u00b7 "
        f"judgment expectations: {report.judgment_count}",
    ]
    for result in report.results:
        lines.append(
            f"  {result.id}: {result.exercising} exercising \u00b7 "
            f"{result.excluded_not_applicable} not-applicable-excluded \u2014 "
            f"{counts(result.status_counts)}"
        )
    lines.append(f"totals: {counts(report.totals)}")
    degraded = [
        pair for result in report.results for pair in result.pairs if pair.status != "packetized"
    ]
    if not degraded:
        lines.append("degradations: none")
        return lines
    lines.append(click.style("degradations:", fg="yellow"))
    for pair in degraded:
        lines.append(
            click.style(
                f"  {pair.expectation_id} \u00b7 {pair.session_basename} \u00b7 {pair.status}",
                fg="yellow",
            )
        )
        lines.append(f"    {pair.detail}")
    return lines


def _judgment_expectation_arm(
    catalog: expectations.ExpectationCatalog, expectation_ids: tuple[str, ...]
) -> str | None:
    """The shared ``--expectation`` judgment-tier-only validation: the failure message, or
    ``None`` when every id names a judgment expectation. ``audit evidence`` and ``audit
    judge`` fail with the same words by construction."""
    judgment_ids = [e.id for e in catalog.expectations if e.tier == "judgment"]
    known_judgment = ", ".join(judgment_ids)
    tier_by_id = {e.id: e.tier for e in catalog.expectations}
    unknown = sorted(set(expectation_ids) - set(tier_by_id))
    if unknown:
        return (
            f"unknown expectation id(s): {', '.join(unknown)} "
            f"(known judgment ids: {known_judgment})"
        )
    non_judgment = sorted({e for e in expectation_ids if tier_by_id[e] != "judgment"})
    if non_judgment:
        named = ", ".join(f"{e} (tier: {tier_by_id[e]})" for e in non_judgment)
        return (
            f"expectation id(s) not judgment-tier: {named} (known judgment ids: {known_judgment})"
        )
    return None


@audit.command("evidence")
@click.option(
    "--sessions-root",
    "sessions_root_opt",
    default=None,
    metavar="<dir>",
    help="Override the Pi session-history root (default: ~/.pi/agent/sessions).",
)
@click.option(
    "--expectation",
    "expectation_ids",
    multiple=True,
    metavar="<id>",
    help="Limit the bundle to the named judgment expectation id(s) (repeatable; default: all).",
)
@click.option(
    "--out",
    "out_opt",
    default=None,
    metavar="<dir>",
    help="Bundle output dir (default: .perk/workflow/scratch/audit-evidence).",
)
@click.option(
    "--max-sessions",
    "max_sessions",
    type=int,
    default=bounding.DEFAULT_MAX_SESSIONS,
    show_default=True,
    metavar="<n>",
    help="Newest-first sampling cap per expectation.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit the bundle envelope to stdout.")
@click.pass_context
def audit_evidence(
    ctx: click.Context,
    *,
    sessions_root_opt: str | None,
    expectation_ids: tuple[str, ...],
    out_opt: str | None,
    max_sessions: int,
    as_json: bool,
) -> None:
    """Build the judgment-tier evidence bundle (packets + manifest) for the audit wave.

    A successfully built bundle exits 0 regardless of degradation counts \u2014 every
    non-packetized pair is recorded honestly in the manifest, never silently passed.
    """
    root = repo_root(Path.cwd())
    if root is None:
        fail(ctx, as_json=as_json, error_type="not_a_repo", message="not inside a git repository")
        return
    if max_sessions < 1:
        fail(
            ctx,
            as_json=as_json,
            error_type="bad_arguments",
            message=f"--max-sessions must be >= 1, got {max_sessions}",
        )
        return
    main_root = git.main_worktree_root(root) or root
    worktree_root = load_config(main_root).worktree_root
    try:
        catalog = expectations.load_catalog()
    except expectations.ExpectationsError as exc:
        fail(ctx, as_json=as_json, error_type="bad_catalog", message=str(exc))
        return
    arm = _judgment_expectation_arm(catalog, expectation_ids)
    if arm is not None:
        fail(ctx, as_json=as_json, error_type="bad_arguments", message=arm)
        return
    # Resolved ONCE so SessionRecord.path, re-parses, manifest paths, and packet
    # session= attributes all agree on one absolute spelling (the default root is
    # already absolute).
    sessions_root = (
        Path(sessions_root_opt).resolve()
        if sessions_root_opt is not None
        else corpus.default_sessions_root()
    )
    bundle_dir = (
        Path(out_opt) if out_opt is not None else cache.scratch_dir(main_root) / "audit-evidence"
    )
    census = corpus.build_census(
        sessions_root=sessions_root,
        main_root=main_root,
        worktree_root=worktree_root,
        catalog=catalog,
        bindings=load_bindings().bindings,
        history=vintage.load_release_history(main_root),
    )
    try:
        report = bounding.build_evidence_bundle(
            census=census,
            catalog=catalog,
            expectation_ids=expectation_ids,
            bundle_dir=bundle_dir,
            max_sessions=max_sessions,
        )
        # Self-contained bundle: the manifest is written unconditionally on a successful
        # build, independent of --json — the auditor children read files, not this
        # door's stdout.
        payload = bounding.write_manifest(bundle_dir, report)
    except OSError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="io_error",
            message=(
                f"bundle materialization failed: {exc} \u2014 stale packets were wiped "
                "first, so the bundle dir may hold a partial packets/ tree and a stale "
                "or absent manifest.json; the bundle is unusable until a successful re-run"
            ),
        )
        return
    if as_json:
        machine_output(json.dumps(payload))
    else:
        for line in _evidence_summary_lines(report):
            user_output(line)


@audit.command("judge", context_settings={"ignore_unknown_options": True})
@click.option(
    "--sessions-root",
    "sessions_root_opt",
    default=None,
    metavar="<dir>",
    help="Override the Pi session-history root (default: ~/.pi/agent/sessions).",
)
@click.option(
    "--expectation",
    "expectation_ids",
    multiple=True,
    metavar="<id>",
    help="Limit the bundle to the named judgment expectation id(s) (repeatable; default: all).",
)
@click.option(
    "--max-sessions",
    "max_sessions",
    type=int,
    default=bounding.DEFAULT_MAX_SESSIONS,
    show_default=True,
    metavar="<n>",
    help="Newest-first sampling cap per expectation.",
)
@click.option(
    "--out",
    "out_opt",
    default=None,
    metavar="<dir>",
    help="Bundle output dir (default: .perk/workflow/scratch/audit-evidence).",
)
@seeded_door_options(
    worktree_help="Worktree to position (audit judge runs in the main checkout).",
    dry_run_help="Materialize the full bundle, print the report; launch nothing.",
    remote_subject="audit judge",
)
@click.pass_context
def audit_judge(
    ctx: click.Context,
    *,
    sessions_root_opt: str | None,
    expectation_ids: tuple[str, ...],
    max_sessions: int,
    out_opt: str | None,
    worktree: str | None,
    dry_run: bool,
    remote: str | None,
    as_json: bool,
    no_sync: bool,
    pi_args: tuple[str, ...],
) -> None:
    """Build the audit bundle fresh and launch the seeded judgment-wave session.

    One coherent pass (contracts.md §8.50): census → the FULL deterministic report → the
    evidence bundle over the SAME census — then a read-only `audit`-stage session whose one
    ``run_audit_wave`` call writes ``<bundle>/verdicts.json``; ``perk-dev audit fold`` folds
    it back into the deterministic report as leads, not proofs.

    \b
    Examples:
      perk-dev audit judge --max-sessions 1 --expectation plan.grill-before-review
      perk-dev audit judge --dry-run --json   # materialize the bundle, no launch
    """

    def gather(repo_root: Path, config: Config, stage: Stage) -> SeededLaunch:
        # Reject `--remote` up front (audit is cold_remote:false) before any side effect.
        launch.resolve_target(stage, remote)

        # Head a real local launch with the banner BEFORE the gather narration streams
        # beneath it (the seeded-door family shape).
        launch.print_launch_banner_gated(repo_root, dry_run=dry_run, remote=remote)

        if max_sessions < 1:
            raise UserFacingCliError(
                f"--max-sessions must be >= 1, got {max_sessions}", error_type="bad_arguments"
            )
        try:
            catalog = expectations.load_catalog()
        except expectations.ExpectationsError as exc:
            raise UserFacingCliError(str(exc), error_type="bad_catalog") from exc
        arm = _judgment_expectation_arm(catalog, expectation_ids)
        if arm is not None:
            raise UserFacingCliError(arm, error_type="bad_arguments")

        main_root = git.main_worktree_root(repo_root) or repo_root
        worktree_root = load_config(main_root).worktree_root
        # Resolved ONCE (the `audit evidence` posture) so SessionRecord.path, re-parses, and
        # packet session= attributes all agree on one absolute spelling.
        sessions_root = (
            Path(sessions_root_opt).resolve()
            if sessions_root_opt is not None
            else corpus.default_sessions_root()
        )
        # `--out` resolves ONCE to an absolute path BEFORE any write — launch_stage changes
        # cwd to the stage checkout before pi runs, so a relative spelling handed into the
        # seed vars / handoff / dry-run payload would silently dangle.
        bundle_dir = (
            Path(out_opt).expanduser().resolve()
            if out_opt is not None
            else (cache.scratch_dir(main_root) / "audit-evidence").resolve()
        )

        # The census is built ONCE; the deterministic report and the bundle both derive from
        # this one snapshot (coherence over iteration speed — judge always rebuilds).
        with io_step("censusing the session corpus") as s:
            census = corpus.build_census(
                sessions_root=sessions_root,
                main_root=main_root,
                worktree_root=worktree_root,
                catalog=catalog,
                bindings=load_bindings().bindings,
                history=vintage.load_release_history(main_root),
            )
            s.done(f"censused {census.totals.confirmed} confirmed session(s)")

        with io_step("materializing the evidence bundle") as s:
            # The deterministic report is always FULL (no filter): the folded report is the
            # complete report. The `--expectation` filter narrows only the bundle.
            report = runner.run_audit(census=census, catalog=catalog, expectation_ids=())
            try:
                bundle_report = bounding.build_evidence_bundle(
                    census=census,
                    catalog=catalog,
                    expectation_ids=expectation_ids,
                    bundle_dir=bundle_dir,
                    max_sessions=max_sessions,
                )
                # The pinned bundle-root sequence: manifest → deterministic.json → the
                # stale-verdicts unlink. Runs on --dry-run too — gather materializes the
                # full coherent bundle in every mode; only the launch is skipped.
                bounding.write_manifest(bundle_dir, bundle_report)
                cache.atomic_write_text(
                    bundle_dir / "deterministic.json",
                    json.dumps(runner.AuditReportOut.from_domain(report).model_dump(mode="json")),
                )
                # A rebuilt bundle must never let `audit fold` consume a prior snapshot's
                # verdicts — verdicts.json exists only after this launch's wave writes it.
                (bundle_dir / "verdicts.json").unlink(missing_ok=True)
            except OSError as exc:
                raise UserFacingCliError(
                    f"bundle materialization failed: {exc} \u2014 the bundle dir may hold a "
                    "partial packets/ tree and stale or absent bundle-root artifacts; the "
                    "bundle is unusable until a successful re-run",
                    error_type="io_error",
                ) from exc
            packetized = sum(
                1
                for result in bundle_report.results
                for pair in result.pairs
                if pair.status == "packetized"
            )
            s.done(
                f"{packetized} packet(s) across {len(bundle_report.results)} judgment "
                f"expectation(s) \u2192 {bundle_dir}"
            )

        # The injected summary is the SAME unstyled line builder `audit run`/`audit fold`
        # render through — the seed's data block and the CLI render cannot drift.
        summary = "\n".join(text for text, _ in _audit_render_lines(report, expectation_ids=()))
        seed = render(
            "stages/audit.md",
            {
                "bundle_dir": str(bundle_dir),
                "manifest_path": str(bundle_dir / "manifest.json"),
                "deterministic_path": str(bundle_dir / "deterministic.json"),
                "deterministic_summary": summary,
                "packet_count": str(packetized),
                "expectation_count": str(len(bundle_report.results)),
            },
        )
        return SeededLaunch(
            seed=seed,
            launch_note=(
                f"materialized the audit bundle ({packetized} packet(s), "
                f"{len(bundle_report.results)} judgment expectation(s)); "
                "launching the audit-judge session"
            ),
            dry_run_label="audit judge --dry-run (bundle materialized; no launch)",
            dry_run_fields=(
                f"  bundle={bundle_dir}  packets={packetized}  "
                f"expectations={len(bundle_report.results)}",
            ),
            dry_run_payload={
                "success": True,
                "error_type": None,
                "bundle_dir": str(bundle_dir),
                "deterministic_path": str(bundle_dir / "deterministic.json"),
                "manifest_path": str(bundle_dir / "manifest.json"),
                "packetized": packetized,
                "expectations": len(bundle_report.results),
                "launched": False,
            },
            # The structural write binding: `run_audit_wave` recovers this absolute dir from
            # the launch handoff — its SOLE write-target authority (contracts.md §8.3/§8.50).
            handoff_extra={"audit_bundle_dir": str(bundle_dir)},
            binding_trigger=None,
            run_id_override=None,
        )

    run_seeded_door(
        ctx,
        stage_id="audit",
        worktree=worktree,
        dry_run=dry_run,
        remote=remote,
        as_json=as_json,
        no_sync=no_sync,
        pi_args=pi_args,
        # No GitHub anywhere in this door: an empty tuple never matches (the audit wave
        # reads local session files; the fold prints only).
        backend_errors=(),
        gather=gather,
    )


def _fold_extra_lines(report: runner.AuditReport) -> list[tuple[str, bool]]:
    """The judgment-fold section appended to the shared render: the per-lane leads
    ("lead, not proof" framing) and the unchecked breakdown by reason — pure
    ``(text, warn)`` lines (the CLI colors at the emit edge)."""
    lines: list[tuple[str, bool]] = []
    leads = [
        (result.id, cell)
        for result in report.results
        if result.tier == "judgment"
        for cell in result.cells
        if cell.status in ("satisfied", "violated") and cell.detail.startswith("judgment lead")
    ]
    if leads:
        lines.append(("judgment leads (leads, not proofs \u2014 human triage):", False))
        for expectation_id, cell in leads:
            entries = ", ".join(str(i) for i in cell.entries) or "none"
            lines.append(
                (
                    f"  {expectation_id} \u00b7 {cell.session_basename} \u00b7 {cell.status} "
                    f"\u00b7 entries {entries}",
                    cell.status == "violated",
                )
            )
            lines.append((f"    {cell.detail}", False))
    else:
        lines.append(("judgment leads: none", False))
    reasons = dict.fromkeys(runner.UNCHECKED_REASONS, 0)
    for result in report.results:
        if result.tier != "judgment":
            continue
        for cell in result.cells:
            if cell.status == "unchecked" and cell.reason is not None:
                reasons[cell.reason] += 1
    breakdown = " \u00b7 ".join(f"{key} {count}" for key, count in reasons.items() if count > 0)
    lines.append((f"unchecked breakdown: {breakdown or 'none'}", False))
    return lines


@audit.command("fold")
@click.option(
    "--bundle",
    "bundle_opt",
    default=None,
    metavar="<dir>",
    help="Bundle dir to fold (default: .perk/workflow/scratch/audit-evidence).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit the folded-report envelope to stdout.")
@click.pass_context
def audit_fold(ctx: click.Context, *, bundle_opt: str | None, as_json: bool) -> None:
    """Fold the audit wave's verdicts.json into the deterministic report (leads, not proofs).

    Reads the three bundle artifacts (deterministic.json + manifest.json + verdicts.json),
    replaces only the ``unchecked``/``judgment-tier`` cells, and renders/emits the SAME
    report shape as ``audit run``. Prints only; writes nothing.
    """
    root = repo_root(Path.cwd())
    if root is None:
        fail(ctx, as_json=as_json, error_type="not_a_repo", message="not inside a git repository")
        return
    main_root = git.main_worktree_root(root) or root
    bundle_dir = (
        Path(bundle_opt).expanduser().resolve()
        if bundle_opt is not None
        else (cache.scratch_dir(main_root) / "audit-evidence").resolve()
    )
    try:
        deterministic = fold.load_deterministic(bundle_dir)
        manifest = fold.load_manifest(bundle_dir)
        verdicts = fold.load_verdicts(bundle_dir)
    except fold.BundleError as exc:
        fail(ctx, as_json=as_json, error_type="bad_bundle", message=str(exc))
        return
    report, warnings = fold.fold_report(deterministic, manifest, verdicts)
    for warning in warnings:
        user_output(click.style("warning: ", fg="yellow") + warning)
    if as_json:
        machine_output(
            json.dumps(runner.AuditReportOut.from_domain(report).model_dump(mode="json"))
        )
    else:
        user_output(f"folded audit report \u2014 bundle: {bundle_dir}")
        _emit_render_lines(_audit_render_lines(report, expectation_ids=()))
        _emit_render_lines(_fold_extra_lines(report))


def main() -> None:
    cli()
