"""The shared **seeded cold-door** pipeline.

A *seeded cold door* is a launcher command with one orchestration shape: parse inputs, resolve
backend state up front (the read-only session it launches cannot be trusted to), materialize
untrusted DATA into a scratch/inbox file, support a ``--dry-run``/``--json`` supervisor report,
and end by ``exec``-ing pi via ``launch_stage`` with a seeded prompt. ``plan from``,
``plan replan``, ``objective plan``, ``objective replan``, ``objective author --from``, and the
three learn doors (``learn docs`` / ``learn code`` / ``learn harvest``) all share it.

Three exports:

- :func:`seeded_door_options` — the parameterized decorator factory for the shared trailing
  option block (``--worktree/--dry-run/--remote/--json/--no-sync`` + the ``pi_args`` argument).
- :class:`SeededLaunch` — the frozen contract between a door's local ``gather`` policy and the
  shared tail (the seed, the report shapes, the launch extras).
- :func:`run_seeded_door` — the driver: boundary → dry-run report → launch.

**Per-command policy stays in the door's ``gather`` closure**: ``require_github`` placement,
id parsing, ``launch.resolve_target`` ordering, backend/store resolution, the gated launch
banner, the ``io_step`` narration blocks, validation raises, fail-soft engagement reads, scratch
writes, and seed rendering. The pipeline owns only the shape those closures share.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import click

from perk.cli.context import require_config, require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.run import launch
from perk.substrate.config import Config
from perk.substrate.output import machine_output, user_output
from perk.substrate.registry import Stage, stage_by_id


def seeded_door_options[F: Callable[..., object]](
    *, worktree_help: str, dry_run_help: str, remote_subject: str
) -> Callable[[F], F]:
    """The shared trailing option block for a seeded cold door, parameterized by the three
    phrases that vary across the family (the ``--worktree`` parenthetical, the ``--dry-run``
    phrasing, the ``--remote`` subject clause).

    Applies ``--worktree``, ``--dry-run``, ``--remote``, ``--json``, ``--no-sync``, and the
    trailing ``pi_args`` argument — in that ``--help`` order. Leading arguments and per-command
    extras (``--node``, ``--from``, ``--gather``) stay declared locally above the factory.
    """
    decorators: tuple[Callable[[F], F], ...] = (
        click.option("--worktree", help=worktree_help),
        click.option("--dry-run", is_flag=True, help=dry_run_help),
        click.option(
            "--remote",
            type=str,
            default=None,
            is_flag=False,
            flag_value="",
            help=f"Local (default) or a remote runner; {remote_subject} is local-only "
            "(cold_remote:false).",
        ),
        click.option(
            "--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout."
        ),
        click.option(
            "--no-sync",
            "no_sync",
            is_flag=True,
            help="Skip the pre-launch fast-forward of the main checkout.",
        ),
        click.argument("pi_args", nargs=-1, type=click.UNPROCESSED),
    )

    def decorator(f: F) -> F:
        # Applied in reverse so Click's ``__click_params__`` reversal renders ``--help`` in the
        # canonical order above (decorators stack bottom-up).
        for deco in reversed(decorators):
            f = deco(f)
        return f

    return decorator


@dataclass(frozen=True)
class SeededLaunch:
    """The contract between a door's local ``gather`` policy and the shared pipeline tail.

    ``dry_run_payload`` is the FULL ``--json`` dry-run payload — the door owns its keys and their
    order. ``dry_run_shows_seed`` gates the human dry-run's seed section (``objective plan`` and
    the learn factories' ``--gather`` suppress it).
    """

    seed: str  # the prompt_override
    launch_note: str  # stderr note printed under --json on a real launch
    dry_run_label: str  # the dim header line of the human dry-run report
    dry_run_fields: tuple[str, ...]  # the indented detail line(s)
    dry_run_payload: dict[str, object]  # the FULL --json dry-run payload (policy-owned keys/order)
    dry_run_shows_seed: bool = True
    handoff_extra: dict[str, object] | None = None
    binding_trigger: str | None = None
    run_id_override: str | None = None


def run_seeded_door(
    ctx: click.Context,
    *,
    stage_id: str,
    worktree: str | None,
    dry_run: bool,
    remote: str | None,
    as_json: bool,
    no_sync: bool,
    pi_args: tuple[str, ...],
    backend_errors: tuple[type[Exception], ...],
    gather: Callable[[Path, Config, Stage], SeededLaunch],
) -> None:
    """Drive one seeded cold door: boundary → dry-run report → launch.

    ``gather`` runs inside the exception boundary — a raise from ``backend_errors`` maps to
    ``github_error``, a ``UserFacingCliError`` to its ``error_type`` (default ``invalid_input``);
    both route through :func:`perk.cli.emit.fail` (stable exits: ``2`` not-a-repo, else ``1``).
    On ``--dry-run`` the spec's report is emitted (a single ``--json`` payload — no launch
    fall-through); otherwise ``launch.launch_stage`` exec's pi with the seeded prompt (the module
    attribute stays the test seam).
    """
    try:
        repo_root = require_repo(ctx)
        config = require_config(ctx)
        stage = stage_by_id(stage_id)
        spec = gather(repo_root, config, stage)
    except backend_errors as exc:
        fail(ctx, as_json=as_json, error_type="github_error", message=str(exc))
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    if dry_run:
        if as_json:
            machine_output(json.dumps(spec.dry_run_payload))
        else:
            user_output(click.style(spec.dry_run_label, dim=True))
            for line in spec.dry_run_fields:
                user_output(line)
            if spec.dry_run_shows_seed:
                user_output(click.style("── seed prompt ──", fg="bright_black"))
                user_output(spec.seed)
        return

    if as_json:
        user_output(spec.launch_note)
    # launch_stage exec's pi with the seeded prompt (becomes the session — nothing after runs).
    launch.launch_stage(
        repo_root=repo_root,
        config=config,
        stage=stage,
        worktree=worktree,
        dry_run=False,
        remote=remote,
        pi_args=list(pi_args),
        prompt_override=spec.seed,
        handoff_extra=spec.handoff_extra,
        binding_trigger=spec.binding_trigger,
        run_id_override=spec.run_id_override,
        sync_main=not no_sync,
    )
