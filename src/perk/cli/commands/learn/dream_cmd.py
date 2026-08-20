"""``perk learn dream`` — the whole-corpus curation-factory cold door over ``docs/learned/``.

An **objective factory** (the harvest posture, for curation): gather the COMPLETE learned corpus
into cluster lanes, write the run-scoped dream manifest, and launch a read-only
objective-authoring session that runs the two-level dream wave and curates ONE bounded curation
objective + dream report — or honestly reports a clean audit or an incomplete one. It never edits
the corpus and never writes code.

**Cold-only** (no warm ``/learn-dream`` door — an objective non-goal) and backend-light: no
``require_github``, ``backend_errors=()`` — the only backend read is the pre-launch active-origin
guard, wrapped explicitly and **fail-closed** (an unanswerable lookup refuses
``origin_lookup_failed``, never proceeds).

**The snapshot promise.** Dream audits an immutable snapshot: the preflight requires a resolvable
HEAD, a CLEAN checkout (untracked included), and every gathered doc TRACKED at the stamped commit
(``git status --porcelain`` omits gitignored files, so trackedness is checked separately); the one
guarded fast-forward runs BEFORE gather (suppressed on ``--dry-run``/``--no-sync``; the in-launch
sync is always suppressed — the harvest one-revision-boundary discipline), and HEAD is captured
exactly ONCE per invocation. The whole git preflight sits inside a ``GitError → git_error``
fail-closed boundary — an unprovable probe becomes a typed refusal, never a traceback. In-session,
the revalidation bracket (contracts.md §8.65) re-proves HEAD-unchanged + tree-clean against the
stamped ``commit_sha`` after the wave and again at draft-write/save — an END-STATE claim only
(never mid-wave byte immutability; no physically frozen checkout in v1 — the accepted residuals
are documented in §8.65).

**Whole-corpus only**: no ``--from`` option exists, and the door actively REJECTS the spelling in
the passthrough pi-args (a partial-corpus mine is ``perk learn harvest --from``).

A **dedicated** command (not a registry stage): it borrows the ``objective-author`` stage
descriptor for launch and overrides the binding trigger to ``command:learn-dream``. The curation
judgment lives in the ``perk-learn-dream`` skill.
"""

from pathlib import Path

import click

from perk import objective
from perk.backends import objective_store, resolve
from perk.backends.issue_backend import IssueBackendError
from perk.cli.commands.seeded_door import SeededLaunch, run_seeded_door, seeded_door_options
from perk.cli.ensure import UserFacingCliError
from perk.learn import dream
from perk.prompts import render
from perk.run import launch
from perk.state import run_id
from perk.substrate import git
from perk.substrate.config import Config
from perk.substrate.output import io_step
from perk.substrate.registry import Stage


@click.command("dream", context_settings={"ignore_unknown_options": True})
@seeded_door_options(
    worktree_help="Worktree to position (learn dream runs at repo root).",
    dry_run_help="Gather + write the manifest, print the report; launch nothing.",
    remote_subject="learn dream",
    no_sync_help="Skip the pre-gather fast-forward of the checkout you run dream from.",
)
@click.pass_context
def dream_learn(
    ctx: click.Context,
    *,
    worktree: str | None,
    dry_run: bool,
    remote: str | None,
    as_json: bool,
    no_sync: bool,
    pi_args: tuple[str, ...],
) -> None:
    """Audit the WHOLE learned corpus and curate ONE bounded curation objective + dream report.

    \b
    Examples:
      perk learn dream                    # gather, preflight, launch the factory
      perk learn dream --dry-run --json   # gather + write the manifest, no launch
    """

    def gather(repo_root: Path, config: Config, stage: Stage) -> SeededLaunch:
        # `--from` is rejected FIRST — before the banner, the sync, or any other side effect.
        # `ignore_unknown_options` + UNPROCESSED pi_args would otherwise silently pass `--from x`
        # through to pi after a full-corpus gather; every other unknown token keeps the family's
        # passthrough semantics.
        for token in pi_args:
            if token == "--from" or token.startswith("--from="):
                raise UserFacingCliError(
                    "`perk learn dream` audits the whole corpus — there is no `--from`; for a "
                    "partial-corpus mine run `perk learn harvest --from …`.",
                    error_type="invalid_input",
                )

        # Resolve the run target up front so `--remote` on this local-only stage is rejected
        # before any side effect (objective-author is cold_remote:false).
        launch.resolve_target(stage, remote)

        # Head a real local launch with the banner BEFORE the sync/gather narration streams
        # beneath it (mirrors the sibling learn factories).
        launch.print_launch_banner_gated(repo_root, dry_run=dry_run, remote=remote)

        # The GitError-bounded preflight: every git probe below (the sync's internal probes, the
        # HEAD capture, the clean check, and the post-gather tracked-corpus check) fails CLOSED —
        # a probe that cannot run becomes a typed `git_error` refusal, never a traceback and
        # never a silently-assumed-clean snapshot. (`gather_dream`'s own `UserFacingCliError`
        # refusals propagate untouched — they are not `GitError`s.)
        try:
            # Pre-gather sync — THE one revision boundary: one guarded fast-forward of the
            # invocation checkout before gather, none after (`run_seeded_door` gets
            # `no_sync=True` below, so `launch_stage` never syncs again). Skipped on --dry-run
            # and on --no-sync; `_sync_main_checkout` narrates itself and is best-effort.
            if not dry_run and not no_sync:
                launch._sync_main_checkout(repo_root)

            # The SINGLE SHA capture — HEAD is resolved exactly once per invocation; the
            # manifest's commit_sha and the in-session revalidation bracket both anchor to it.
            sha = git.resolve_commit(repo_root, "HEAD")
            if sha is None:
                raise UserFacingCliError(
                    "The repository has no resolvable HEAD commit — commit once before dreaming.",
                    error_type="invalid_input",
                )

            # The clean-checkout requirement (untracked included) — dream stamps an immutable
            # snapshot: the audited corpus must be exactly reproducible from `commit_sha`, so a
            # dirty tree (which the gather would read) refuses. Runs on --dry-run too (dry-run
            # validates every local precondition).
            if git.is_dirty(repo_root):
                raise UserFacingCliError(
                    "The working tree has uncommitted changes (untracked files included) — "
                    "`perk learn dream` audits an immutable snapshot, so the corpus must be "
                    "clean and committed at one revision. Commit or stash, then re-run.",
                    error_type="dirty_checkout",
                )

            with io_step("gathering the learned corpus") as s:
                gathered = dream.gather_dream(repo_root)
                s.done(f"gathered {gathered.doc_count} doc(s) into {len(gathered.lanes)} lane(s)")

            # The tracked-corpus check: `git status --porcelain` omits gitignored files, so an
            # IGNORED docs/learned doc could be gathered while the tree reports clean — but it
            # is not reproducible from the stamped commit. Every gathered doc must be tracked.
            # (Plain-untracked docs already refused at the clean check; only ignored members
            # reach this.)
            tracked = set(git.tracked_paths(repo_root, ["docs/learned"]))
            untracked = [doc.path for doc in gathered.docs if doc.path not in tracked]
            if untracked:
                raise UserFacingCliError(
                    "gathered learned doc(s) are not tracked at the stamped commit (gitignored "
                    "or otherwise untracked) — the dream snapshot is not reproducible from "
                    f"commit {sha}: " + ", ".join(untracked),
                    error_type="invalid_input",
                )
        except git.GitError as exc:
            raise UserFacingCliError(
                f"a git probe failed during the dream preflight ({exc}) — the snapshot "
                "preconditions cannot be proven, refusing to dream.",
                error_type="git_error",
            ) from exc

        # The pre-launch active-origin guard (real launch only — --dry-run stays offline):
        # one open learn-dream objective per repo. Fail-closed: an unanswerable lookup (the
        # store resolution included) refuses rather than risking a duplicate dream objective.
        # Runs BEFORE the run id is minted and before any scratch write.
        if not dry_run:
            try:
                store = resolve.resolve_objective_store(repo_root)
                conflict = store.find_open_objective_by_origin(
                    origin=objective.ObjectiveOrigin.LEARN_DREAM, exclude_run_id=None
                )
            except (objective_store.ObjectiveStoreError, IssueBackendError) as exc:
                raise UserFacingCliError(
                    f"could not verify the open learn-dream objective guard ({exc}) — "
                    "refusing to dream over an unanswerable lookup.",
                    error_type="origin_lookup_failed",
                ) from exc
            if conflict is not None:
                raise UserFacingCliError(
                    f"an open learn-dream objective already exists: #{conflict.id} "
                    f"({conflict.url}) — complete or close it before dreaming again.",
                    error_type="origin_conflict",
                )

        # Pre-mint the run id so the run-scoped manifest path and the launched session agree
        # (run_id_override carries it to launch_stage).
        rid = run_id.mint()
        # The one expected-I/O boundary in the gather: a manifest that cannot be written must
        # leave through the door's JSON envelope, not as a traceback.
        try:
            manifest_path = dream.write_manifest(repo_root, rid, gathered, commit_sha=sha)
        except OSError as exc:
            raise UserFacingCliError(
                f"could not write the dream manifest: {exc}",
                error_type="manifest_write_failed",
            ) from exc

        doc_count = gathered.doc_count
        lane_count = len(gathered.lanes)
        # The seed interpolates only door-derived values (the run-scoped path, the doc count,
        # the lane count). Lane ids and cluster names are repository-derived — interpolating
        # them into instruction text would be a prompt-injection surface — so they stay DATA
        # in the manifest the session reads.
        seed = render(
            "stages/learn-dream.md",
            {
                "manifest_path": str(manifest_path),
                "doc_count": str(doc_count),
                "lane_count": str(lane_count),
            },
        )
        return SeededLaunch(
            seed=seed,
            launch_note=(
                f"gathered {doc_count} learned doc(s) into {lane_count} lane(s); "
                "launching the learn-dream factory"
            ),
            dry_run_label="learn-dream --dry-run (gather only; no launch)",
            dry_run_fields=(
                f"  manifest={manifest_path}"
                f"  lanes={', '.join(lane.id for lane in gathered.lanes)}"
                f"  docs={doc_count}",
                "  origin guard: NOT evaluated (--dry-run is offline)",
            ),
            dry_run_payload={
                "success": True,
                "error_type": None,
                "manifest_path": str(manifest_path),
                "commit_sha": sha,
                "registry_mode": gathered.registry_mode,
                "doc_count": doc_count,
                "lane_count": lane_count,
                "lane_ids": [lane.id for lane in gathered.lanes],
                "total_bytes": gathered.total_bytes,
                "origin_guard": "not-evaluated",
                "launched": False,
            },
            # The factory borrows `objective-author`, so its binding trigger is the command —
            # the stage:objective-author binding must not fire (the perk-objective-author read
            # path rides the perk-learn-dream skill's explicit cross-reference, §8.57).
            binding_trigger="command:learn-dream",
            run_id_override=rid,
        )

    run_seeded_door(
        ctx,
        stage_id="objective-author",
        worktree=worktree,
        dry_run=dry_run,
        remote=remote,
        as_json=as_json,
        # `no_sync=True` UNCONDITIONALLY: the gather closure above owns the one pre-gather sync
        # (gated on the user's --no-sync), so launch_stage's in-launch sync is always suppressed —
        # nothing moves the tree between gather and session.
        no_sync=True,
        pi_args=pi_args,
        # No generic backend boundary: the only backend read is the origin guard above, wrapped
        # explicitly (fail-closed as `origin_lookup_failed`).
        backend_errors=(),
        gather=gather,
    )
