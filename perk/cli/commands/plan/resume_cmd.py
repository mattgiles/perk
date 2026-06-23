"""`perk resume <plan>` — the cross-stage resume verb.

The one genuinely-new CLI command this phase: resolve any plan to its current actionable stage and
launch it. Reads the plan from the issue backend (`IssueBackend.get_plan`), reconstructs the
`cache.plan-ref`, derives the stage (`perk.run.resume`), then reuses the `launch_stage`
(idempotent worktree + materialize + exec pi). Supervisor surface: `--json` to
stdout, stable exit codes.

Exit codes: 0 resumed / nothing-to-resume · 1 invalid input / unauthed / plan-not-found / op
failure · 2 not-a-repo.
"""

import json

import click

from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.cli.context import require_config, require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.run import launch, resume
from perk.state import cache
from perk.substrate.output import machine_output, user_output
from perk.substrate.registry import load_registry

_EXIT_FOR_TYPE = {"not_a_repo": 2}


@click.command("resume", context_settings={"ignore_unknown_options": True})
@click.argument("plan")
@click.option("--dry-run", is_flag=True, help="Resolve + print the stage without launching.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.option(
    "--remote",
    type=str,
    default=None,
    is_flag=False,
    flag_value="",
    help="Local (default) or a remote runner (dispatch the stage to CI).",
)
@click.argument("pi_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def resume_cmd(
    ctx: click.Context,
    *,
    plan: str,
    dry_run: bool,
    as_json: bool,
    remote: str | None,
    pi_args: tuple[str, ...],
) -> None:
    """Resume PLAN (a plan issue id) at its current stage.

    \b
    Examples:
      perk plan resume 42            # resolve #42's stage and launch it (fresh context)
      perk plan resume 42 --dry-run  # print the resolved stage + launch plan, launch nothing
    """
    try:
        repo_root = require_repo(ctx)
        require_github(ctx)  # resume always reads GitHub (the dry run resolves via a read)
        config = require_config(ctx)
        plan_id = parse_plan_id(plan)
        backend = resolve.resolve_issue_backend(repo_root)
        state = backend.get_plan(issue_id=plan_id)
        if state is None:
            raise UserFacingCliError(
                f"Plan issue #{plan_id} not found", error_type="plan_not_found"
            )
        ref = resume.reconstruct_plan_ref(state, provider=backend.backend_id)
        stage_id = resume.resolve_resume_stage(
            state, has_pending_learn=cache.has_marker(repo_root, cache.PENDING_LEARN)
        )
    except IssueBackendError as exc:
        _fail(ctx, as_json=as_json, error_type="github_error", message=f"resume failed\n{exc}")
        return
    except UserFacingCliError as exc:
        _fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    if stage_id is None:
        _render_done(plan_id, as_json=as_json)
        return

    worktree_name = launch.resolve_plan_worktree_name(ref)
    if dry_run:
        _render_dry_run(plan_id, stage_id, worktree_name, ref, as_json=as_json)
        return

    # Real run: materialize the ref at the repo root, then launch the stage (execs pi).
    cache.write_plan_ref(repo_root, ref)
    stage = next(s for s in load_registry().stages if s.id == stage_id)
    launch.launch_stage(
        repo_root=repo_root,
        config=config,
        stage=stage,
        worktree=None,  # derive plan-<pr_id> from the just-written ref (+ materialize)
        dry_run=False,
        remote=remote,
        pi_args=list(pi_args),
    )


def parse_plan_id(plan: str, *, what: str = "plan") -> str:
    """Validate an opaque issue id — accept ``42``, ``#42``, or a backend-native string id like
    Linear's ``ENG-123``.

    Strips ``#``/whitespace; rejects empty ids and anything unusable as a ``plan-<id>`` worktree
    name (the ``launch.resolve_plan_worktree_name`` rule: no ``/``, never ``.``/``..``). The id
    is otherwise opaque — the issue backend is the authority on whether it resolves.
    """
    cleaned = plan.strip().lstrip("#").strip()
    if not cleaned or "/" in cleaned or cleaned in (".", ".."):
        raise UserFacingCliError(
            f"Invalid {what} id {plan!r} — expected an issue id (e.g. 42 or ENG-123).",
            error_type="invalid_input",
        )
    return cleaned


def _render_done(plan_id: str, *, as_json: bool) -> None:
    message = f"plan #{plan_id} is merged and learned — nothing to resume"
    if as_json:
        machine_output(
            json.dumps(
                {"success": True, "plan": plan_id, "resumed_stage": None, "message": message}
            )
        )
    else:
        user_output(message)


def _render_dry_run(
    plan_id: str, stage_id: str, worktree: str, ref: dict[str, object], *, as_json: bool
) -> None:
    if as_json:
        machine_output(
            json.dumps(
                {
                    "success": True,
                    "plan": plan_id,
                    "resumed_stage": stage_id,
                    "worktree": worktree,
                    "plan_ref": ref,
                    "dry_run": True,
                }
            )
        )
    else:
        user_output(click.style("resume --dry-run (resolve only, no launch)", dim=True))
        user_output(f"  plan=#{plan_id}  resumed_stage={stage_id}  worktree={worktree}")


def _fail(ctx: click.Context, *, as_json: bool, error_type: str, message: str) -> None:
    if as_json:
        machine_output(json.dumps({"success": False, "error_type": error_type, "message": message}))
    else:
        user_output(click.style("Error: ", fg="red") + message)
    ctx.exit(_EXIT_FOR_TYPE.get(error_type, 1))
