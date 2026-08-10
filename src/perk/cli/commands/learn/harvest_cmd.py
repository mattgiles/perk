"""``perk learn harvest`` — the objective-factory cold door over ``docs/learned/``.

An **objective factory** (mirroring ``/objective-plan``'s "factory, not writer" posture, but for
objectives): resolve the selected learned docs, partition them into lanes, write the run-scoped
harvest manifest, and launch a **read-only objective-authoring session** that reads the docs as
*lenses into the code* and curates ONE bounded improvement objective — or honestly reports a
zero-opportunity outcome. It never edits the corpus and never writes code.

**Cold-only** (no warm ``/learn-harvest`` door — deferred by the objective) and **GitHub-free**:
no ``require_github``, ``backend_errors=()`` — the first backend mutation of a harvest run is the
in-session ``objective_save``.

**One revision boundary** (contracts.md §8.48): the guarded fast-forward runs on the invocation
checkout BEFORE gather (suppressed on ``--dry-run``/``--no-sync``), the manifest's ``commit_sha``
is HEAD captured immediately post-sync, and the in-launch sync is suppressed (``sync_main=False``)
— nothing perk does moves the tree between gather and session. Best-effort revision *context*, not
a clean-tree attestation: the gather reads the working tree and a dirty tree may diverge (the sync
already warns loudly).

A **dedicated** command (not a registry stage): it borrows the ``objective-author`` stage
descriptor for launch (``mode: read-only``, ``worktree: none``) and overrides the binding trigger
to ``command:learn-harvest``. The curation judgment lives in the ``perk-learn-harvest`` skill.
"""

from pathlib import Path

import click

from perk.cli.commands.seeded_door import SeededLaunch, run_seeded_door, seeded_door_options
from perk.cli.ensure import UserFacingCliError
from perk.learn import harvest
from perk.prompts import render
from perk.run import launch
from perk.state import run_id
from perk.substrate import git
from perk.substrate.config import Config
from perk.substrate.output import io_step
from perk.substrate.registry import Stage


@click.command("harvest", context_settings={"ignore_unknown_options": True})
@click.option(
    "--from",
    "from_targets",
    multiple=True,
    help="A file or directory inside docs/learned/ (repo-root-relative or absolute); "
    "repeatable; default = the full corpus.",
)
@seeded_door_options(
    worktree_help="Worktree to position (learn harvest runs at repo root).",
    dry_run_help="Gather + write the manifest, print the report; launch nothing.",
    remote_subject="learn harvest",
)
@click.pass_context
def harvest_learn(
    ctx: click.Context,
    *,
    from_targets: tuple[str, ...],
    worktree: str | None,
    dry_run: bool,
    remote: str | None,
    as_json: bool,
    no_sync: bool,
    pi_args: tuple[str, ...],
) -> None:
    """Mine docs/learned into ONE bounded improvement objective (a read-only objective factory).

    \b
    Examples:
      perk learn harvest --from docs/learned/workflow   # harvest one category
      perk learn harvest --dry-run --json               # gather + write the manifest, no launch
    """

    def gather(repo_root: Path, config: Config, stage: Stage) -> SeededLaunch:
        # Resolve the run target up front so `--remote` on this local-only stage is rejected
        # before any side effect (objective-author is cold_remote:false).
        launch.resolve_target(stage, remote)

        # Head a real local launch with the banner BEFORE the sync/gather narration streams
        # beneath it (mirrors the sibling learn factories).
        launch.print_launch_banner_gated(repo_root, dry_run=dry_run, remote=remote)

        # Pre-gather sync — THE one revision boundary: one guarded fast-forward of the invocation
        # checkout before gather, none after (`run_seeded_door` gets `no_sync=True` below, so
        # `launch_stage` never syncs again). Skipped on --dry-run (mirroring launch_stage's
        # dry-run-inert sync) and on --no-sync. `_sync_main_checkout` narrates itself and is
        # best-effort + loud (warns and skips on no-remote/detached/dirty/diverged).
        if not dry_run and not no_sync:
            launch._sync_main_checkout(repo_root)

        # Capture the revision context immediately post-sync, before any gather read. Honest
        # best-effort: the gather reads the working tree, which may diverge from HEAD on a dirty
        # checkout (the sync warned) — commit_sha is context, not a clean-tree attestation.
        sha = git.resolve_commit(repo_root, "HEAD")
        if sha is None:
            raise UserFacingCliError(
                "The repository has no resolvable HEAD commit — commit once before harvesting.",
                error_type="invalid_input",
            )

        with io_step("gathering learned docs") as s:
            docs = harvest.resolve_harvest_docs(repo_root, from_targets)
            lanes = harvest.partition_lanes(docs)
            # The phase-1 ceiling gates on the LANE count — never a doc-count check (the lane is
            # the per-group analyst-context contract; see the core's docstring).
            if len(lanes) > 1:
                raise UserFacingCliError(
                    f"The selection partitions to {len(lanes)} lanes "
                    f"({', '.join(lane.id for lane in lanes)}); the phase-1 door accepts exactly "
                    "one. Multi-lane harvests arrive with the phase-2 analyst wave — narrow the "
                    "selection with --from (a file or directory inside docs/learned/).",
                    error_type="selection_too_large",
                )
            # Pre-mint the run id so the run-scoped manifest path and the launched session agree
            # (run_id_override carries it to launch_stage).
            rid = run_id.mint()
            manifest_path = harvest.write_manifest(repo_root, rid, lanes, commit_sha=sha)
            s.done(f"gathered {len(docs)} doc(s) into {len(lanes)} lane → {manifest_path.name}")

        seed = render(
            "stages/learn-harvest.md",
            {
                "manifest_path": str(manifest_path),
                "lane_id": lanes[0].id,
                "doc_count": str(len(docs)),
            },
        )
        return SeededLaunch(
            seed=seed,
            launch_note=(
                f"gathered {len(docs)} learned doc(s) into 1 lane; "
                "launching the learn-harvest factory"
            ),
            dry_run_label="learn-harvest --dry-run (gather only; no launch)",
            dry_run_fields=(f"  manifest={manifest_path}  lane={lanes[0].id}  docs={len(docs)}",),
            dry_run_payload={
                "success": True,
                "error_type": None,
                "manifest_path": str(manifest_path),
                "doc_count": len(docs),
                "lane_count": len(lanes),
                "lane_ids": [lane.id for lane in lanes],
                "launched": False,
            },
            # The factory borrows `objective-author`, so its binding trigger is the command —
            # the stage:objective-author binding must not fire (the seed hardcodes the
            # perk-objective-author pointer instead).
            binding_trigger="command:learn-harvest",
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
        # No GitHub anywhere in this door: an empty tuple never matches (the first backend
        # mutation of a harvest run is the in-session objective_save).
        backend_errors=(),
        gather=gather,
    )
