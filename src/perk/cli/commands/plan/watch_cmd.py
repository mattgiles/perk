"""``perk plan watch PLAN`` — live-watch a plan's implementation diff in hunk.

Positions plan ``PLAN``'s implementation worktree through the shared reuse positioner
(``launch.resolve_worktree`` — ``plan-<id>`` under the **main checkout's** worktree root,
correct from anywhere in the repo, including from inside a linked worktree): an already-valid
bound worktree stays offline-capable; a **missing** checkout triggers the canonical lookup +
non-destructive restore from ``origin/plan-<id>`` (then the marker-gated ``[worktree] setup``);
an existing-unbound checkout refuses ``worktree_unbound`` exactly like every other consumer —
watch never silently rebinds. It then computes the diff base (the stacked layer's recorded
parent when one resolves — exact after restoration via the restored ``layer-context.json`` —
else the since-base merge-base: the plan's full growing changeset, commits included), chdirs
into the worktree and **execs** ``hunk diff <sha12> --watch --extension <bundled publisher>
[HUNK_ARGS…]`` — the terminal becomes a live, auto-reloading view of what the plan has
changed, and saving a human note in it queues feedback for the live implement session (the
watch feedback bridge, contracts §8.58: the bundled extension appends records to the
worktree's ``.perk/workflow/hunk-watch/`` outbox; the Pi-side receiver drains them).

``--dry-run`` is mutation-free: for an existing worktree the hunk command composes from local
refs only (no fetch — degrading to the working-tree-only fallback with a note when the base is
unresolvable offline); for a missing worktree it reports the planned restore + setup plus an
explicit "command/base unavailable until restoration" status and composes no hunk argv. Real
runs keep the fetch behavior; canonical/backend network reads happen only on a real run with no
valid local checkout.

Exit contract: dry-run success → 0 · pre-exec perk refusals → 1 (``not_a_repo`` → 2, via the
shared ``EXIT_FOR_TYPE``) · a failed ``chdir``/``exec`` (``OSError``) → 1 · a **successful
exec never returns** — perk becomes hunk and the terminal ultimately receives *hunk's* exit
status (whatever it is). All human-facing command text renders via ``shlex.join`` so
spaced/metacharacter args stay paste-safe.
"""

import os
import re
import shlex
from pathlib import Path

import click
from ulid import ULID

from perk._resources import hunk_feedback_extension_path
from perk.cli.context import require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.cli.plan_selection import load_main_config, main_repo_root, parse_plan_id
from perk.convergence.init import HUNK_INSTALL_HINT, hunk_cli_path
from perk.run.launch import WorktreeRequest, resolve_worktree, run_pending_setup
from perk.state import cache
from perk.substrate import git
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
    "appended to the hunk argv after --watch and perk's bundled --extension, in order. The "
    "first bare `--` is consumed as the end-of-options marker: to hand hunk its own pathspec "
    "separator, type it twice (perk plan watch 42 -- -- src/ui); to pass a perk-owned token "
    "to hunk (e.g. a literal --dry-run), put it after the first `--`. One token is refused "
    "outright wherever it appears: --no-extensions (hunk's hard-off switch for on-disk "
    "extensions — it would silently disable the feedback bridge; run hunk directly in the "
    "worktree for an extension-free watch)."
)


def _resolve_diff_base(worktree: Path, *, fetch: bool = True) -> str | None:
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

    ``fetch=False`` is the mutation-free dry-run mode: the since-base arm skips the network
    fetch entirely and resolves from local refs only (the stacked arm never fetched anyway).
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
    if fetch:
        try:
            git.fetch(worktree)
        except GitError as exc:
            log_warn(
                f"could not fetch origin ({exc}) — using the last-known origin/{branch} ref, "
                "which may be STALE"
            )
    sha = git.merge_base(worktree, "HEAD", f"origin/{branch}")
    if sha is None:
        detail = " (unresolvable offline — no fetch on a dry run)" if not fetch else ""
        log_warn(
            "could not resolve a diff base — watching the working tree only "
            f"(uncommitted changes){detail}"
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

    A valid local plan-<id> worktree is reused offline; a missing one is restored from
    origin/plan-<id> (then [worktree] setup runs, marker-gated). Typed refusals
    (worktree_unbound, worktree_branch_mismatch, worktree_plan_mismatch,
    worktree_restore_failed) exit 1 before any launch — watch never rebinds or resets an
    existing checkout. --dry-run mutates nothing (no fetch, no restore).

    Annotated ``-> None`` (not ``NoReturn``): tests stub ``os.execve`` and control returns
    (mirroring ``launch._exec_pi``).

    \b
    Examples:
      perk plan watch 42                 # the plan's full changeset, live (commits included)
      perk plan watch 42 --theme dark    # extra tokens pass through to hunk
      perk plan watch 42 -- -- src/ui    # hand hunk its own pathspec separator
    """
    try:
        repo_root = require_repo(ctx)
        main_root = main_repo_root(repo_root)
        config = load_main_config(main_root)
        plan_id = parse_plan_id(plan)
        # `--no-extensions` is hunk's hard-off switch for on-disk extensions: passed through, it
        # would silently disable the bundled feedback publisher while perk claims feedback is
        # active. Refused wherever it appears in the pass-through args (before or after the
        # escaped `--`), dry-run included.
        if "--no-extensions" in hunk_args:
            raise UserFacingCliError(
                "--no-extensions would silently disable the watch feedback bridge (the bundled "
                "hunk extension that sends saved notes to the implementation session), so perk "
                "refuses to pass it through.\n"
                "For an extension-free watch, run hunk directly in the worktree: "
                "hunk diff <base> --watch --no-extensions",
                error_type="conflicting_hunk_arg",
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
        # Resolve the bundled feedback publisher from the INSTALLED artifact before the chdir
        # below (the same shadowing defense as the absolute hunk path above) — never from the
        # worktree, PATH, or any config. A missing asset refuses even under --dry-run: a
        # dry-run must not print an unlaunchable command.
        try:
            ext_path = hunk_feedback_extension_path()
        except FileNotFoundError as exc:
            raise UserFacingCliError(
                "perk's bundled hunk feedback extension is missing — this installation is "
                "broken.\nReinstall perk (e.g. 'uv tool install --force perk'), then re-run.",
                error_type="watch_extension_missing",
            ) from exc
        # Position the plan checkout through the shared reuse positioner (validated local
        # reuse; restore-on-missing — the canonical/backend read happens only on a real run
        # with no local checkout; typed fail-closed refusals otherwise). A dry run mutates
        # nothing: a missing worktree is only REPORTED as a planned restore.
        resolved = resolve_worktree(
            repo_root=main_root,
            config=config,
            request=WorktreeRequest(policy="reuse", consumer="plan watch"),
            worktree=None,
            materialize=not dry_run,
            plan_id=plan_id,
        )
        worktree_path = resolved.path
        if dry_run and resolved.disposition == "restore-remote":
            user_output(click.style("watch --dry-run (resolve only, no launch)", dim=True))
            user_output(
                f"  worktree: {worktree_path} (missing — would restore from {resolved.base})"
            )
            if config.worktree_setup:
                user_output(f"  would run setup: {'; '.join(config.worktree_setup)}")
            user_output("  command:  unavailable until restoration (base unresolved — no fetch)")
            return
        if not dry_run:
            # Marker-gated `[worktree] setup`: runs after a restoration (or a reuse still
            # carrying the marker from a previously failed setup); a no-op otherwise.
            run_pending_setup(worktree_path, config.worktree_setup)
        base_sha = _resolve_diff_base(worktree_path, fetch=not dry_run)
        # perk-owned args stay ahead of user pass-through; hunk's --extension is repeatable,
        # so a user-supplied --extension composes after (never displaces) the bundled one.
        argv = [
            "hunk",
            "diff",
            *([base_sha[:12]] if base_sha else []),
            "--watch",
            "--extension",
            str(ext_path),
            *hunk_args,
        ]
        if dry_run:
            user_output(click.style("watch --dry-run (resolve only, no launch)", dim=True))
            user_output(f"  worktree: {worktree_path}")
            user_output(f"  command:  {shlex.join(argv)}")
            return
        user_output(f"watching plan #{plan_id} in {worktree_path}: {shlex.join(argv)}")
        # The watch INSTANCE id (§8.58): a fresh ULID naming this watch process so feedback
        # identities stay stable — deliberately NOT a workflow run_id (no handoff, no scratch,
        # no claim). Minted only on a real launch; dry-run mints nothing.
        watch_id = str(ULID())
        # A COPIED environment — the launcher's own os.environ is never mutated. The three
        # PERK_HUNK_* vars are internal launch plumbing (§8.58), not user-facing controls.
        env = os.environ.copy()
        env["PERK_HUNK_WATCH_ID"] = watch_id
        env["PERK_HUNK_PLAN_ID"] = str(plan_id)
        env["PERK_HUNK_WORKTREE_ROOT"] = str(worktree_path.resolve())
        # The presence probe does not eliminate the exec race — a failed chdir/exec is an
        # ordinary OSError arm, not a crash.
        try:
            os.chdir(worktree_path)
            os.execve(hunk_path, argv, env)  # perk BECOMES hunk — nothing after this runs
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
