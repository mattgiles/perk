"""Generate one ``perk <stage>`` launcher per registry stage.

The registry is the single source of truth for which stage commands exist, so the two
entry planes (CLI launchers / extension transitions) cannot drift. Generation is
**defensive**: a registry that fails to load leaves the core commands working, and
``perk registry check`` diagnoses the break.
"""

import click

from perk.cli.context import require_repo
from perk.cli.plan_selection import load_main_config, main_repo_root
from perk.run.launch import launch_stage
from perk.substrate.registry import RegistryError, Stage, load_registry

# Stages with a dedicated, hand-written command (skipped by the generic generator below).
DEDICATED_STAGES: frozenset[str] = frozenset(
    {
        "implement",  # perk/cli/commands/implement_cmd.py
        "learn",  # perk/cli/commands/learn/__init__.py (hybrid group; hidden launcher)
        "gist-author",  # perk/cli/commands/gist/author_cmd.py
        "gist-save",  # perk/cli/commands/gist/save_cmd.py
        "objective-author",  # perk/cli/commands/objective/author_cmd.py
        "objective-save",  # perk/cli/commands/objective/save_cmd.py
        "objective-plan",  # perk/cli/commands/objective/plan_cmd.py
        # The pr group: submit/land are merged launcher+worker commands
        # and address is the launcher-only door, all under `perk pr` + flat aliases — so the
        # generic generator must not also build the flat `perk submit`/`address`/`land` launchers.
        "submit",
        "address",
        "land",
        "plan",  # perk/cli/commands/plan/__init__.py (hybrid group; hidden launcher)
        "save",  # perk/cli/commands/plan/__init__.py (merged save verb)
        # The audit stage's dedicated door is `perk-dev audit judge` (dev-only, in the perk-dev
        # package) — there is deliberately no generic `perk audit` launcher.
        "audit",
    }
)


def make_stage_launcher(stage: Stage) -> click.Command:
    """Build the generic launcher command for ``stage``.

    Used by the generator below for every non-dedicated stage, and reused by the ``learn``
    group for its hidden bare-invocation launcher (``commands/learn/__init__.py``).
    """

    # The `--remote` flag stays on local-only launchers (uniform launcher surface; the friendly
    # `remote_blocked` runtime rejection is the tested contract) — only the help states the scope.
    remote_help = (
        "Local (default) or a remote runner (dispatch the stage to CI)."
        if stage.doors.get("cold_remote") is True
        else f"Local (default) or a remote runner; '{stage.id}' is local-only (cold_remote:false)."
    )

    # Click takes the first paragraph as short help, so listing rows render the bare registry
    # summary; the second paragraph disambiguates the launcher from same-named worker verbs.
    launcher_help = (
        f"{stage.summary}\n\n"
        f"Opens a primed pi session for the '{stage.id}' stage (use --dry-run to print the "
        "launch plan without exec'ing pi)."
    )

    @click.command(
        name=stage.id,
        help=launcher_help,
        context_settings={"ignore_unknown_options": True},
    )
    @click.option("--worktree", help="Worktree to position (create/reuse stages).")
    @click.option("--dry-run", is_flag=True, help="Print the launch plan without exec'ing pi.")
    @click.option(
        "--remote",
        type=str,
        default=None,
        is_flag=False,
        flag_value="",
        help=remote_help,
    )
    @click.option(
        "--no-sync",
        "no_sync",
        is_flag=True,
        help="Skip the pre-launch fast-forward of the main checkout.",
    )
    @click.argument("pi_args", nargs=-1, type=click.UNPROCESSED)
    @click.pass_context
    def _cmd(
        ctx: click.Context,
        *,
        worktree: str | None,
        dry_run: bool,
        remote: str | None,
        no_sync: bool,
        pi_args: tuple[str, ...],
    ) -> None:
        # --no-sync is inert for stages that aren't read-only `worktree: none` (e.g. the hidden
        # `learn` launcher); launch_stage's gate ignores sync_main outside those stages.
        # Two-roots rule: config + positioning anchor to the MAIN checkout (a relative worktree
        # root must never resolve beneath a linked worktree); the invocation root is passed
        # separately for the no-argument cache-fallback read only.
        invocation_root = require_repo(ctx)
        main_root = main_repo_root(invocation_root)
        launch_stage(
            repo_root=main_root,
            config=load_main_config(main_root),
            stage=stage,
            worktree=worktree,
            dry_run=dry_run,
            remote=remote,
            pi_args=list(pi_args),
            sync_main=not no_sync,
            invocation_root=invocation_root,
        )

    return _cmd


class MergedCommand(click.Command):
    """One command that fronts a launcher half and a deterministic worker half.

    A ``MergedCommand`` holds two intact ``click.Command`` halves built elsewhere:

    - the **launcher** half (``make_stage_launcher(stage)``) — opens a primed pi session;
    - the **worker** half (an existing deterministic worker command, e.g. ``pr submit``) —
      runs offline and emits machine output under ``--json``.

    Neither half's option schema is unioned or duplicated. ``parse_args`` pre-dispatches on the
    presence of ``--json`` in argv (the proven ``LearnGroup`` argv-dispatch pattern): ``--json``
    anywhere routes to the worker, otherwise the launcher runs and the remaining argv is handed
    through to ``pi``.

    Accepted edge (mirroring ``LearnGroup``): because dispatch keys on the literal ``--json``
    token anywhere in argv, **passing ``--json`` through to ``pi`` as a launcher pi-arg is
    unsupported via the merged command** — use the explicit stage launcher when you need that.
    """

    def __init__(
        self,
        name: str,
        *,
        launcher: click.Command,
        worker: click.Command,
        help: str | None = None,  # Click's own param name
    ) -> None:
        super().__init__(
            name,
            help=help,
            context_settings={"ignore_unknown_options": True},
        )
        self._launcher = launcher
        self._worker = worker

    def _select(self, args: list[str]) -> click.Command:
        """The worker when ``--json`` is present in argv, else the launcher."""
        return self._worker if "--json" in args else self._launcher

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        # The MergedCommand's own auto `--help` fires only for the launcher-side help (no --json);
        # a `--json --help` would route to the worker and render the worker's own help instead.
        if ("--help" in args or "-h" in args) and "--json" not in args:
            return super().parse_args(ctx, args)
        chosen = self._select(args)
        ctx._merged_chosen = chosen  # ty: ignore[unresolved-attribute]  # stash for invoke()
        return chosen.parse_args(ctx, args)

    def invoke(self, ctx: click.Context) -> object:
        chosen = getattr(ctx, "_merged_chosen", self._launcher)
        return chosen.invoke(ctx)

    def get_help(self, ctx: click.Context) -> str:
        body = self._launcher.get_help(ctx)
        note = "Run with --json to execute the deterministic worker (machine output, no session)."
        return f"{body}\n\n{note}"


def make_merged_command(
    stage: Stage, worker: click.Command, *, name: str | None = None
) -> MergedCommand:
    """Build a :class:`MergedCommand` over ``stage``'s launcher and an existing ``worker``.

    The launcher half is
    ``make_stage_launcher(stage)`` (reused intact); the worker half is the caller's deterministic
    ``click.Command``.
    """
    launcher = make_stage_launcher(stage)
    merged_help = (
        f"{stage.summary}\n\n"
        f"Opens a primed pi session for the '{stage.id}' stage by default; run with --json to "
        "execute the deterministic worker instead."
    )
    return MergedCommand(
        name or worker.name or stage.id,
        launcher=launcher,
        worker=worker,
        help=merged_help,
    )


def register_stage_commands(cli: click.Group) -> None:
    """Add a launcher command per registry stage (no-op if the registry won't load)."""
    try:
        registry = load_registry()
    except (RegistryError, FileNotFoundError):
        return  # a broken registry must not brick the CLI; `registry check` diagnoses it
    for stage in registry.stages:
        if stage.id in DEDICATED_STAGES:
            continue  # a dedicated command is registered explicitly (e.g. `implement`)
        cli.add_command(make_stage_launcher(stage))
