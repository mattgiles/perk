"""``perk plan watch PLAN`` — live-watch a plan's implementation diff in hunk.

Resolves plan ``PLAN``'s implementation worktree (``plan-<id>`` under the **main checkout's**
worktree root — correct from anywhere in the repo, including from inside a linked worktree),
computes the diff base (the stacked layer's recorded parent when one resolves, else the
since-base merge-base — the plan's full growing changeset, commits included), then chdirs into
the worktree and **execs** ``hunk diff <sha12> --watch [HUNK_ARGS…]`` — the terminal becomes a
live, auto-reloading view of what the plan has changed. Entirely offline-capable: no
issue-backend read; the only network op is a best-effort ``git fetch``.

Exit contract: dry-run success → 0 · pre-exec perk refusals → 1 (``not_a_repo`` → 2, via the
shared ``EXIT_FOR_TYPE``) · a failed ``chdir``/``exec`` (``OSError``) → 1 · a **successful
exec never returns** — perk becomes hunk and the terminal ultimately receives *hunk's* exit
status (whatever it is). All human-facing command text renders via ``shlex.join`` so
spaced/metacharacter args stay paste-safe.
"""

import os
import re
import shlex
import tomllib
from pathlib import Path

import click

from perk.cli.commands.plan.resume_cmd import parse_plan_id
from perk.cli.context import require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.convergence.init import HUNK_INSTALL_HINT, hunk_cli_path
from perk.state import cache
from perk.substrate import git
from perk.substrate.config import Config, ConfigError, load_config
from perk.substrate.git import GitError
from perk.substrate.output import log_warn, user_output

# A full 40-hex commit object id — the only shape the stacked arm accepts for the recorded
# parent. Anything else (a movable ref like `HEAD`, an abbreviation, a tag) would silently
# re-resolve later and is degraded to the since-base arm instead.
_FULL_SHA_RE = re.compile(r"[0-9a-f]{40}")

# The pass-through grammar (the decided contract — deliberately not "verbatim"): perk owns
# exactly two tokens, recognized only before the first bare `--`; Click consumes that `--`.
_EPILOG = (
    "Pass-through grammar: perk owns exactly two tokens — --dry-run and --help — recognized "
    "only before the first bare `--`. Every other token (unknown options and positionals) is "
    "appended to the hunk argv after --watch, in order. The first bare `--` is consumed as the "
    "end-of-options marker: to hand hunk its own pathspec separator, type it twice "
    "(perk plan watch 42 -- -- src/ui); to pass a perk-owned token to hunk (e.g. a literal "
    "--dry-run), put it after the first `--`."
)


def _load_main_config(main_root: Path) -> Config:
    """Load config against the **main checkout's** root.

    A small local twin of ``PerkContext.config()``'s error translation — ``require_config`` is
    deliberately not used because it binds config to the *invocation* root, which would rebase
    a relative ``[worktree] root`` under a linked worktree.
    """
    try:
        return load_config(main_root)
    except tomllib.TOMLDecodeError as exc:
        raise UserFacingCliError(
            f".perk/config.toml is not valid TOML ({exc})\nFix it, then re-run."
        ) from exc
    except ConfigError as exc:
        raise UserFacingCliError(
            f".perk config invalid: {exc}\nFix it, then re-run (perk doctor pinpoints the field)."
        ) from exc


def _resolve_diff_base(worktree: Path) -> str | None:
    """The diff-base ladder (first match wins); ``None`` ⇒ working-tree-only fallback.

    a. **Stacked layer arm**: the worktree's ``layer-context.json`` ``parent_sha`` (the
       offline, session-scoped record of the sha the layer was cut from — the layer's own
       delta), taken only when it resolves locally; no fetch, no merge-base. A
       recorded-but-unresolvable sha degrades to (b) with a warning (the record is never
       authoritative).
    b. **Since-base arm** (the Python mirror of the extension's ``sinceBaseSha``): pinned
       plan-ref base → else the detected trunk; best-effort fetch (offline keeps the
       last-known ref); ``merge-base(HEAD, origin/<branch>)``.
    c. ``None`` — the caller composes a bare watch (uncommitted changes only), warned here.
    """
    parent_sha = cache.read_layer_parent_sha(worktree)
    if parent_sha:
        # Immutable full object id only, and it must resolve to ITSELF locally: a movable ref
        # (`HEAD`), an abbreviation, or a tag in the (never-authoritative) record would pin the
        # watch to whatever it resolves to later — degrade to the since-base arm instead.
        if (
            _FULL_SHA_RE.fullmatch(parent_sha)
            and git.resolve_commit(worktree, parent_sha) == parent_sha
        ):
            return parent_sha
        log_warn(
            f"recorded layer parent {parent_sha[:12]} is not a locally-resolvable full "
            "commit id — falling back to the since-base merge-base"
        )
    ref = None
    try:
        ref = cache.read_plan_ref(worktree)
    except cache.CacheError as exc:
        log_warn(f"unreadable plan-ref ({exc}) — resolving the base from the detected trunk")
    pinned = ref.base if ref is not None and ref.base is not None and ref.base.strip() else None
    branch = pinned or git.detect_trunk_branch(worktree)
    try:
        git.fetch(worktree)
    except GitError as exc:
        log_warn(
            f"could not fetch origin ({exc}) — using the last-known origin/{branch} ref, "
            "which may be STALE"
        )
    sha = git.merge_base(worktree, "HEAD", f"origin/{branch}")
    if sha is None:
        log_warn(
            "could not resolve a diff base — watching the working tree only (uncommitted changes)"
        )
    return sha


@click.command("watch", context_settings={"ignore_unknown_options": True}, epilog=_EPILOG)
@click.argument("plan")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Resolve + print the worktree and the composed hunk command without launching.",
)
@click.argument("hunk_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def watch_plan(ctx: click.Context, *, plan: str, dry_run: bool, hunk_args: tuple[str, ...]) -> None:
    """Live-watch PLAN's implementation diff in hunk (watch mode).

    Annotated ``-> None`` (not ``NoReturn``): tests stub ``os.execv`` and control returns
    (mirroring ``launch._exec_pi``).

    \b
    Examples:
      perk plan watch 42                 # the plan's full changeset, live (commits included)
      perk plan watch 42 --theme dark    # extra tokens pass through to hunk
      perk plan watch 42 -- -- src/ui    # hand hunk its own pathspec separator
    """
    try:
        repo_root = require_repo(ctx)
        main_root = git.main_worktree_root(repo_root) or repo_root
        config = _load_main_config(main_root)
        plan_id = parse_plan_id(plan)
        # Inline composition: `parse_plan_id` already enforces the single-path-segment rule
        # `resolve_plan_worktree_name` checks (that helper takes a PlanRef we don't need).
        worktree_path = config.worktree_root / f"plan-{plan_id}"
        if not worktree_path.is_dir():
            raise UserFacingCliError(
                f"Worktree not found: {worktree_path}\n"
                f"Run `perk implement {plan_id}` (or `perk plan resume {plan_id}`) first.",
                error_type="worktree_not_found",
            )
        # Resolve the ABSOLUTE hunk path before the chdir below: re-resolving the bare name
        # after entering the worktree would let a relative `PATH` entry (e.g. `.`) pick up an
        # executable inside the code-under-watch tree.
        hunk_path = hunk_cli_path()
        if hunk_path is None:
            raise UserFacingCliError(
                f"hunk CLI not found on PATH — install it: {HUNK_INSTALL_HINT}",
                error_type="review_cli_missing",
            )
        base_sha = _resolve_diff_base(worktree_path)
        argv = ["hunk", "diff", *([base_sha[:12]] if base_sha else []), "--watch", *hunk_args]
        if dry_run:
            user_output(click.style("watch --dry-run (resolve only, no launch)", dim=True))
            user_output(f"  worktree: {worktree_path}")
            user_output(f"  command:  {shlex.join(argv)}")
            return
        user_output(f"watching plan #{plan_id} in {worktree_path}: {shlex.join(argv)}")
        # The presence probe does not eliminate the exec race — a failed chdir/exec is an
        # ordinary OSError arm, not a crash.
        try:
            os.chdir(worktree_path)
            os.execv(hunk_path, argv)  # perk BECOMES hunk — nothing after this runs
        except OSError as exc:
            raise UserFacingCliError(
                f"could not launch hunk in {worktree_path}: {exc}",
                error_type="launch_failed",
            ) from exc
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=False,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
