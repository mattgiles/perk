import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import AliasChoices, Field

from perk.boundary import LenientParseModel, translate_validation_errors
from perk.github import _exec

# ===========================================================================
# Workflow-dispatch ops (the remote drive; contracts.md §8.13).
#
# Same conventions as the rest of the gateway (REST `gh api` / porcelain `gh run`, routed through
# `_run`, mutations raise `GitHubError`). `trigger_workflow` triggers a `workflow_dispatch` and
# then VERIFIES the run by discovering it via the perk `run_id` embedded in the run-name.
# The `sleep` injection + `max_attempts` keep the poll fully unit-testable with no real delay.
# ===========================================================================


@dataclass(frozen=True)
class WorkflowRun:
    """A GitHub Actions workflow run (the runner-native handle behind a `runner.RunHandle`)."""

    id: str  # the numeric run id, as a string
    url: str
    status: str  # "queued" | "in_progress" | "completed" | …
    conclusion: str | None  # "success" | "failure" | "cancelled" | … | None


class WorkflowRunModel(LenientParseModel):
    """Lenient parse of a GitHub Actions run payload, shared by both producers.

    ``get_workflow_run`` (``gh run view`` — camelCase ``databaseId``/``url``) and
    ``trigger_workflow`` (REST list — ``id``/``html_url``) feed the same frozen
    :class:`WorkflowRun` via ``AliasChoices``. ``id`` is the run identity and is required; a
    present-but-malformed payload raises a ``ValidationError`` the call site labels.
    """

    id: int = Field(validation_alias=AliasChoices("databaseId", "id"))
    url: str = Field("", validation_alias=AliasChoices("url", "html_url"))
    status: str = ""
    conclusion: str | None = None

    def to_domain(self) -> WorkflowRun:
        return WorkflowRun(
            id=str(self.id),
            url=self.url,
            status=self.status,
            conclusion=self.conclusion or None,
        )


def trigger_workflow(
    *,
    repo_root: Path,
    workflow: str,
    inputs: dict[str, str],
    ref: str,
    match_token: str,
    sleep: Callable[[float], None] = time.sleep,
    max_attempts: int = 11,
) -> WorkflowRun:
    """Trigger a ``workflow_dispatch`` and return the **verified** run (discovered by matching
    ``match_token`` in the run's ``display_title``/``name`` — the run-name embeds the perk
    ``run_id``). Raises ``GitHubError`` on a trigger failure, a job-level skip/cancel, or
    discovery exhaustion. Backoff is ``min(2**attempt, 8)`` via the injected ``sleep``.
    """
    args = ["workflow", "run", workflow, "--ref", ref]
    for key, value in inputs.items():
        args += ["-f", f"{key}={value}"]
    proc = _exec._run(args, cwd=repo_root, timeout=_exec._WRITE_TIMEOUT)
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to dispatch workflow {workflow!r}")

    titles: list[str] = []
    for attempt in range(max_attempts):
        runs = _exec._run(
            [
                "api",
                f"repos/{{owner}}/{{repo}}/actions/workflows/{workflow}/runs?per_page=20",
                "--jq",
                ".workflow_runs",
            ],
            cwd=repo_root,
        )
        if runs.returncode == 0:
            workflow_runs = _exec._parse_json(runs, source="`gh api workflow runs`", default="[]")
            titles = []
            for run in workflow_runs if isinstance(workflow_runs, list) else []:
                if not isinstance(run, dict):
                    continue
                title = str(run.get("display_title") or run.get("name") or "")
                titles.append(title)
                if match_token not in title:
                    continue
                conclusion = run.get("conclusion")
                if conclusion in ("skipped", "cancelled"):
                    raise _exec.GitHubError(
                        f"workflow {workflow!r} run was {conclusion} (run {run.get('id')!r}, "
                        f"title {title!r}) — a job-level condition was likely not met"
                    )
                with translate_validation_errors(
                    _exec.GitHubError, source=f"discover workflow run for {workflow!r}"
                ):
                    return WorkflowRunModel.model_validate(run).to_domain()
        if attempt < max_attempts - 1:
            sleep(min(2**attempt, 8))
    recent = ", ".join(repr(t) for t in titles[:10]) or "(none)"
    raise _exec.GitHubError(
        f"dispatched workflow {workflow!r} but no run matched token {match_token!r} after "
        f"{max_attempts} attempts; recent run titles: {recent}"
    )


def get_workflow_run(*, run_id: str, repo_root: Path) -> WorkflowRun | None:
    """Read a workflow run's state by its runner-native id (``gh run view``). ``None`` when the
    run is absent / the call is non-zero; raises ``GitHubError`` only on a gh-missing/timeout."""
    proc = _exec._run(
        ["run", "view", run_id, "--json", "databaseId,url,status,conclusion"], cwd=repo_root
    )
    if proc.returncode != 0:
        return None
    data = _exec._parse_json(proc, source="`gh run view`", default="{}")
    if not isinstance(data, dict) or "databaseId" not in data:
        return None
    with translate_validation_errors(_exec.GitHubError, source=f"read workflow run {run_id}"):
        return WorkflowRunModel.model_validate(data).to_domain()


def cancel_workflow_run(*, run_id: str, repo_root: Path) -> None:
    """Cancel a workflow run by its runner-native id (``gh run cancel``); raises on failure."""
    proc = _exec._run(["run", "cancel", run_id], cwd=repo_root, timeout=_exec._WRITE_TIMEOUT)
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to cancel workflow run {run_id}")


def rerun_workflow_run(*, run_id: str, repo_root: Path, failed_only: bool) -> None:
    """Re-run a workflow run by its runner-native id (``gh run rerun``); raises on failure.

    ``failed_only`` re-runs only the failed jobs (``gh run rerun --failed``). ``run_id`` is the
    runner-native id (the ``RunHandle.run_ref``), NOT the perk ``run_id``.
    """
    args = ["run", "rerun", run_id]
    if failed_only:
        args.append("--failed")
    proc = _exec._run(args, cwd=repo_root, timeout=_exec._WRITE_TIMEOUT)
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to re-run workflow run {run_id}")


# ===========================================================================
# Runner-prerequisite reads (contracts.md §8.16).
#
# Verification-only pre-flight reads for the remote-runner's prerequisites (the checkout/push
# PAT, the model credential, repo workflow-permissions). Same conventions as `check_auth` /
# `check_repo_access`: `cwd=repo_root` + gh's `{owner}/{repo}` placeholder auto-fill (no
# remote-URL parsing); routed through `_run`; a gh-missing/timeout raises `GitHubError`. None
# of these MUTATE GitHub (Decision D2 — perk init/doctor never write secrets/permissions).
# ===========================================================================


@dataclass(frozen=True)
class WorkflowPermissions:
    """`GET .../actions/permissions/workflow` result (§8.16 ``get_workflow_permissions`` shape)."""

    default_workflow_permissions: str
    can_approve_pull_request_reviews: bool


def secret_exists(*, name: str, repo_root: Path) -> bool | None:
    """Does an Actions repo secret named ``name`` exist? ``True`` (present) / ``False`` (404) /
    ``None`` (unknown — e.g. 403 insufficient permission). Never reads the secret value. A
    gh-missing/timeout raises ``GitHubError`` via ``_run`` (the doctor layer degrades it)."""
    proc = _exec._run(["api", f"repos/{{owner}}/{{repo}}/actions/secrets/{name}"], cwd=repo_root)
    if proc.returncode == 0:
        return True
    if _exec._is_not_found(proc):
        return False
    return None


def get_workflow_permissions(*, repo_root: Path) -> WorkflowPermissions | None:
    """Read the repo's default Actions workflow permissions. ``None`` on a non-zero call;
    raises ``GitHubError`` only on a gh-missing/timeout or unparseable JSON."""
    proc = _exec._run(["api", "repos/{owner}/{repo}/actions/permissions/workflow"], cwd=repo_root)
    if proc.returncode != 0:
        return None
    data = _exec._parse_json(proc, source="`gh api workflow permissions`", default="{}")
    if not isinstance(data, dict):
        raise _exec.GitHubError(f"unexpected `gh api workflow permissions` payload: {data!r}")
    return WorkflowPermissions(
        default_workflow_permissions=str(data.get("default_workflow_permissions", "")),
        can_approve_pull_request_reviews=bool(data.get("can_approve_pull_request_reviews", False)),
    )


def get_repo_variable(*, name: str, repo_root: Path) -> str | None:
    """Read an Actions repo variable's value (``gh api .../actions/variables/{name}``). ``None``
    when absent (404) / the call is non-zero / the value is empty. A gh-missing/timeout raises."""
    proc = _exec._run(
        ["api", f"repos/{{owner}}/{{repo}}/actions/variables/{name}", "--jq", ".value"],
        cwd=repo_root,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None
