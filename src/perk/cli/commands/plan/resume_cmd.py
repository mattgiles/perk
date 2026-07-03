"""`perk resume <plan>` — the cross-stage resume verb.

Resolve any plan to its next action and act on it. Reads the plan from the issue backend
(`IssueBackend.get_plan`), reconstructs the `cache.plan-ref`, classifies via the shared
`resume.resolve_next_action` (contracts.md §8.37), then either launches the verdict's stage
(reusing `launch_stage` — idempotent worktree + materialize + exec pi) or names the human gate
without launching. Supervisor surface: `--json` to stdout, stable exit codes.

Exit codes: 0 resumed / nothing-to-resume · 1 invalid input / unauthed / plan-not-found / op
failure · 2 not-a-repo.
"""

import json
import re
from urllib.parse import urlsplit

import click

from perk import github, plan
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.cli.context import require_config, require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.run import launch, resume
from perk.state import cache
from perk.substrate.output import io_step, machine_output, user_output
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
      perk plan resume https://github.com/o/r/issues/42   # paste the plan's URL instead of the id
    """
    try:
        repo_root = require_repo(ctx)
        require_github(ctx)  # resume always reads GitHub (the dry run resolves via a read)
        config = require_config(ctx)
        plan_id = parse_plan_id(plan)
        backend = resolve.resolve_issue_backend(repo_root)
        # Banner first: head a real local launch with the banner BEFORE narrating the lookup wait.
        launch.print_launch_banner_gated(repo_root, dry_run=dry_run, remote=remote)
        # Narrate the backend lookup wait. The lookup runs on the dry-run path too (dry-run
        # resolves the stage via this same read), so the narration is NOT gated on `dry_run`; the
        # line goes to stderr, leaving the `--json` stdout payload byte-unchanged. The not-found
        # raise escapes the step (dangling + the error text below).
        with io_step(f"looking up plan #{plan_id}") as s:
            state = backend.get_plan(issue_id=plan_id)
            if state is None:
                raise UserFacingCliError(
                    f"Plan issue #{plan_id} not found", error_type="plan_not_found"
                )
            ref = resume.reconstruct_plan_ref(state, provider=backend.backend_id)
            next_action = resume.resolve_next_action(
                state,
                has_pending_learn=cache.has_marker(repo_root, cache.PENDING_LEARN),
                get_feedback=lambda n: github.get_pr_feedback(pr_number=n, repo_root=repo_root),
            )
            s.done(f"found plan #{plan_id}")
    except (IssueBackendError, GitHubError) as exc:
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

    stage_id = next_action.stage_id
    if stage_id is None:
        # Gate/terminal verdicts NEVER launch (real and dry-run alike): report the human gate
        # (or done) and exit 0 — a benign decision, matching the supervisor's exit posture.
        if next_action is resume.NextAction.DONE:
            _render_done(plan_id, as_json=as_json)
            return
        pr = state.pr
        assert pr is not None  # gate verdicts only arise from a resolved PR
        _render_gate(plan_id, next_action, pr.number, as_json=as_json)
        return

    worktree_name = launch.resolve_plan_worktree_name(ref)
    if dry_run:
        _render_dry_run(plan_id, next_action, worktree_name, ref, as_json=as_json)
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


_LINEAR_IDENT = re.compile(r"^[A-Za-z0-9]+-\d+$")


def _id_from_url(raw: str) -> str | None:
    """Peel a recognized GitHub/Linear issue or objective URL down to its opaque id.

    Pure and offline — returns ``None`` when ``raw`` is not an http(s) URL we recognize, leaving
    the caller to treat it as a bare id (or reject it). The extracted token stays opaque: the
    backend remains the sole authority on whether it resolves.

    Recognized shapes:

    - Linear issue ``.../issue/IDENT/...`` → the ``IDENT`` segment (e.g. ``SAV-888``), verbatim.
    - Linear project ``.../project/SLUG/...`` → the ``SLUG`` segment (the project id), verbatim.
    - GitHub/GHES ``.../issues/N`` → the digits ``N``. A ``/pull/N`` URL is a different object
      than the plan-issue, so it is deliberately **not** matched (returns ``None``).
    """
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"}:
        return None
    segments = [s for s in parts.path.split("/") if s]
    host = parts.hostname or ""
    if host == "linear.app" or host.endswith(".linear.app"):
        for keyword, accept in (("issue", _LINEAR_IDENT.match), ("project", lambda _s: True)):
            for i, seg in enumerate(segments[:-1]):
                if seg == keyword and accept(segments[i + 1]):
                    return segments[i + 1]
        return None
    # GitHub / GHES (any other host): /issues/<digits>, keyed on the path shape (covers GHES too).
    for i, seg in enumerate(segments[:-1]):
        if seg == "issues" and segments[i + 1].isdigit():
            return segments[i + 1]
    return None


def parse_plan_id(plan: str, *, what: str = "plan") -> str:
    """Validate an opaque issue id — accept ``42``, ``#42``, a backend-native string id like
    Linear's ``ENG-123``, or the issue/objective **URL** it was pasted from.

    A pasted URL is peeled to its id first: GitHub ``.../issues/N``, Linear ``.../issue/IDENT``,
    or Linear ``.../project/SLUG`` (a ``/pull/N`` URL is rejected — it is a different object).

    Strips ``#``/whitespace; rejects empty ids and anything unusable as a ``plan-<id>`` worktree
    name (the ``launch.resolve_plan_worktree_name`` rule: no ``/``, never ``.``/``..``). The id
    is otherwise opaque — the issue backend is the authority on whether it resolves.
    """
    value = plan
    if urlsplit(plan.strip()).scheme.lower() in {"http", "https"}:
        extracted = _id_from_url(plan.strip())
        if extracted is None:
            raise UserFacingCliError(
                f"Could not extract a {what} id from URL {plan!r} — paste a GitHub issue URL "
                "(.../issues/N) or a Linear issue/project URL.",
                error_type="invalid_input",
            )
        value = extracted
    cleaned = value.strip().lstrip("#").strip()
    if not cleaned or "/" in cleaned or cleaned in (".", ".."):
        raise UserFacingCliError(
            f"Invalid {what} id {plan!r} — expected an issue id (e.g. 42 or ENG-123).",
            error_type="invalid_input",
        )
    return cleaned


def _gate_message(plan_id: str, next_action: resume.NextAction, pr_number: int) -> str:
    """The human gate line for a non-launchable verdict (contracts.md §8.37)."""
    prefix = f"plan #{plan_id} (PR #{pr_number}): "
    if next_action is resume.NextAction.READY_FOR_REVIEW:
        return prefix + (
            "draft PR — mark it ready (perk pr ready from the plan worktree) "
            "and /land when satisfied"
        )
    if next_action is resume.NextAction.AWAITING_REVIEW:
        return prefix + "no actionable feedback — awaiting the human review/land gate"
    return prefix + "PR closed unmerged — needs human attention (reopen it or replan)"


def _render_gate(
    plan_id: str, next_action: resume.NextAction, pr_number: int, *, as_json: bool
) -> None:
    message = _gate_message(plan_id, next_action, pr_number)
    if as_json:
        machine_output(
            json.dumps(
                {
                    "success": True,
                    "plan": plan_id,
                    "next_action": next_action.value,
                    "resumed_stage": None,
                    "pr": pr_number,
                    "message": message,
                }
            )
        )
    else:
        user_output(message)


def _render_done(plan_id: str, *, as_json: bool) -> None:
    message = f"plan #{plan_id} is merged and learned — nothing to resume"
    if as_json:
        machine_output(
            json.dumps(
                {
                    "success": True,
                    "plan": plan_id,
                    "next_action": resume.NextAction.DONE.value,
                    "resumed_stage": None,
                    "message": message,
                }
            )
        )
    else:
        user_output(message)


def _render_dry_run(
    plan_id: str,
    next_action: resume.NextAction,
    worktree: str,
    ref: plan.PlanRef,
    *,
    as_json: bool,
) -> None:
    stage_id = next_action.stage_id
    if as_json:
        machine_output(
            json.dumps(
                {
                    "success": True,
                    "plan": plan_id,
                    "next_action": next_action.value,
                    "resumed_stage": stage_id,
                    "worktree": worktree,
                    "plan_ref": plan.PlanRefOut.from_domain(ref).model_dump(mode="json"),
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
