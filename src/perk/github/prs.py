import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import AliasChoices, Field

from perk.boundary import LenientParseModel, translate_validation_errors
from perk.github import _exec

# ===========================================================================
# PR lifecycle ops (submit/land/resume; contracts.md §8.4).
#
# Same conventions as the plan write: REST `gh api` over porcelain (the lone exception is
# `mark_pr_ready` — there is no REST endpoint for draft->ready, so it shells `gh pr ready`,
# which is GraphQL), bodies via file, idempotency via the list endpoint + find-then-return,
# mutations raise / lookups return `... | None`.
# ===========================================================================


@dataclass(frozen=True)
class PullRequest:
    """A pull request. ``existed`` is True when found (idempotent), False when freshly created."""

    number: int
    url: str
    is_draft: bool
    state: str  # "OPEN" | "MERGED" | "CLOSED" (normalized)
    existed: bool
    base_ref: str = ""  # the PR's actual base branch (from REST `base.ref`); "" when synthetic
    head_ref: str = ""  # the PR's head branch name (from REST `head.ref`); "" when synthetic
    # or projected away (e.g. `create_pr`'s --jq projection omits `head`)


@dataclass(frozen=True)
class PrBodyUpdate:
    """The result of a PR-body re-write (the create-then-update footer write)."""

    number: int
    dry_run: bool


def _owner(repo_root: Path) -> str:
    """The repo owner login (for the ``head=<owner>:<branch>`` PR list filter)."""
    proc = _exec._run(["repo", "view", "--json", "owner", "--jq", ".owner.login"], cwd=repo_root)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise _exec._failed(proc, "failed to resolve repo owner")
    return proc.stdout.strip()


class _RefObject(LenientParseModel):
    """A nested ref-carrying object (``base`` / ``head``) of a REST PR payload.

    Only ``ref`` is consumed.
    """

    ref: str = ""


class PullRequestModel(LenientParseModel):
    """Lenient parse of a REST PR payload (the ``_pull_request`` boundary).

    Crosses the ``gh api pulls`` boundary into the frozen :class:`PullRequest`. ``number`` is
    the PR identity and is required — a malformed/absent number raises a ``ValidationError`` that
    the call site maps to a labelled ``GitHubError``. Every other field keeps a tolerant default
    so the happy path is byte-identical to the prior hand-rolled converter.
    """

    number: int
    url: str = Field("", validation_alias=AliasChoices("html_url", "url"))
    draft: bool = False
    raw_state: str = Field("", validation_alias=AliasChoices("state"))
    merged: bool | None = None
    merged_at: str | None = None
    base: _RefObject | None = None
    head: _RefObject | None = None

    def _normalized_state(self) -> str:
        """Normalize the REST state into OPEN | MERGED | CLOSED."""
        if self.merged is True or self.merged_at:
            return "MERGED"
        return "OPEN" if self.raw_state == "open" else "CLOSED"

    def to_domain(self, *, existed: bool) -> PullRequest:
        return PullRequest(
            number=self.number,
            url=self.url,
            is_draft=self.draft,
            state=self._normalized_state(),
            existed=existed,
            base_ref=(self.base.ref if self.base else ""),
            head_ref=(self.head.ref if self.head else ""),
        )


def _pull_request(pr: object, *, existed: bool) -> PullRequest:
    return PullRequestModel.model_validate(pr).to_domain(existed=existed)


def default_branch(repo_root: Path) -> str:
    """The repo's default branch (the PR base). Raises ``GitHubError`` on failure."""
    proc = _exec._run(
        ["repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"],
        cwd=repo_root,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise _exec._failed(proc, "failed to resolve the default branch")
    return proc.stdout.strip()


def find_pr_for_branch(*, branch: str, repo_root: Path) -> PullRequest | None:
    """Find a PR whose head is ``branch`` (idempotency lookup; list endpoint, all states).

    Prefers an open PR (the submit-reuse case); raises on an infra failure, never masks it.
    """
    items = _exec._run_json(
        _exec._rest_args(
            "repos/{owner}/{repo}/pulls",
            method="GET",
            fields={"head": f"{_owner(repo_root)}:{branch}", "state": "all"},
        ),
        what=f"failed to list PRs for {branch!r}",
        source="`gh api pulls`",
        cwd=repo_root,
        default="[]",
    )
    if not isinstance(items, list) or not items:
        return None
    chosen = next((p for p in items if p.get("state") == "open"), items[0])
    with translate_validation_errors(_exec.GitHubError, source=f"list PRs for {branch!r}"):
        return _pull_request(chosen, existed=True)


def list_prs_for_branch(*, branch: str, repo_root: Path) -> tuple[PullRequest, ...]:
    """List **all** PRs whose head is ``branch`` (its own ``head=<owner>:<branch>&state=all``
    query, all states), parsed via the shared converter.

    Distinct from :func:`find_pr_for_branch` (which collapses to one) so a consumer can detect
    multi-candidate ambiguity (``perk learn evidence``). ``find_pr_for_branch`` is left unchanged
    (its many call sites want exactly one). Raises ``GitHubError`` on an infra failure.
    """
    items = _exec._run_json(
        _exec._rest_args(
            "repos/{owner}/{repo}/pulls",
            method="GET",
            fields={"head": f"{_owner(repo_root)}:{branch}", "state": "all"},
        ),
        what=f"failed to list PRs for {branch!r}",
        source="`gh api pulls`",
        cwd=repo_root,
        default="[]",
    )
    if not isinstance(items, list) or not items:
        return ()
    with translate_validation_errors(_exec.GitHubError, source=f"list PRs for {branch!r}"):
        return tuple(_pull_request(item, existed=True) for item in items)


def create_pr(
    *,
    head: str,
    base: str,
    title: str,
    body: str,
    repo_root: Path,
    draft: bool = True,
    dry_run: bool = False,
) -> PullRequest:
    """Open a PR (REST, body via file). Idempotent: an existing PR for ``head`` is returned."""
    if dry_run:
        return PullRequest(number=0, url="(dry-run)", is_draft=draft, state="OPEN", existed=False)
    existing = find_pr_for_branch(branch=head, repo_root=repo_root)
    if existing is not None:
        return existing
    with _exec._body_file(body) as body_path:
        args = _exec._rest_args(
            "repos/{owner}/{repo}/pulls",
            method="POST",
            fields={"title": title, "head": head, "base": base},
            body_path=body_path,
        )
        args += [
            "-F",
            f"draft={'true' if draft else 'false'}",
            "--jq",
            "{number: .number, html_url: .html_url, draft: .draft, state: .state, "
            "base: {ref: .base.ref}}",
        ]
        data = _exec._run_json(
            args,
            what="failed to create PR",
            source="`gh api pulls` create",
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )
    with translate_validation_errors(_exec.GitHubError, source="create PR"):
        return _pull_request(data, existed=False)


def get_pr(*, number: int, repo_root: Path) -> PullRequest | None:
    """Fetch a PR by number (REST). ``None`` if it does not exist; raises on infra failure."""
    data = _exec._run_json(
        ["api", f"repos/{{owner}}/{{repo}}/pulls/{number}"],
        what=f"failed to read PR #{number}",
        source=f"`gh api pulls/{number}`",
        cwd=repo_root,
        none_on_not_found=True,
    )
    if data is None:
        return None
    with translate_validation_errors(_exec.GitHubError, source=f"read PR #{number}"):
        return _pull_request(data, existed=True)


def get_pr_author(*, number: int, repo_root: Path) -> str | None:
    """Fetch a PR author's login (REST, ``user.login``). ``None`` if the PR does not exist;
    raises on infra failure. Feeds `review-submit --dry-run`'s own-PR prediction for formal
    events (a formal review from the PR author is a guaranteed GitHub 422)."""
    proc = _exec._run(
        ["api", f"repos/{{owner}}/{{repo}}/pulls/{number}", "--jq", ".user.login"],
        cwd=repo_root,
    )
    if proc.returncode != 0:
        if _exec._is_not_found(proc):
            return None
        raise _exec._failed(proc, f"failed to read PR #{number} author")
    return proc.stdout.strip() or None


def get_pr_body(*, number: int, repo_root: Path) -> str | None:
    """Fetch a PR's body markdown (REST). ``None`` if the PR does not exist; raises on infra
    failure. Used by ``perk pr check`` to re-validate the live checkout footer."""
    proc = _exec._run(
        ["api", f"repos/{{owner}}/{{repo}}/pulls/{number}", "--jq", ".body"], cwd=repo_root
    )
    if proc.returncode != 0:
        if _exec._is_not_found(proc):
            return None
        raise _exec._failed(proc, f"failed to read PR #{number} body")
    return proc.stdout


def update_pr_body(
    *, number: int, body: str, repo_root: Path, dry_run: bool = False
) -> PrBodyUpdate:
    """Re-write a PR's body (REST ``PATCH .../pulls/{n}``, body via file; mirrors
    :func:`update_plan_header`). The create-then-update footer write: the checkout footer
    needs the **PR** number, unknown until ``create_pr`` returns. Idempotent (overwrites). The PR
    body is distinct from the issue body -- no collision with ``update_plan_header``."""
    if dry_run:
        return PrBodyUpdate(number=number, dry_run=True)
    with _exec._body_file(body) as body_path:
        proc = _exec._run(
            _exec._rest_args(
                f"repos/{{owner}}/{{repo}}/pulls/{number}", method="PATCH", body_path=body_path
            ),
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to update PR #{number} body")
    return PrBodyUpdate(number=number, dry_run=False)


_CHECKOUT_RE = re.compile(r"gh pr checkout\s+(\d+)")
_PLAIN_FOOTER_RE = re.compile(r"`gh pr checkout\s+(\d+)`")
_HTML_FOOTER_RE = re.compile(r"<code>[^<]*gh pr checkout", re.IGNORECASE)


def validate_pr_body(body: str, *, pr_number: int) -> tuple[str, ...]:
    """Validate the PR body's checkout footer (D5). Empty tuple == valid.

    **Footer-scoped only** -- the ``<details>`` plan embed is explicitly fine; the footer must be
    a plain-backtick `` `gh pr checkout <pr_number>` `` line carrying the **PR** number (not the
    issue number -- the single most common agent mistake). The three checks:

    1. the checkout footer is present,
    2. it carries the correct PR number (word-boundary: ``#12`` != ``...checkout 123``),
    3. it is plain backtick, not wrapped in HTML (``<code>...</code>`` breaks supervisor copy).
    """
    all_numbers = _CHECKOUT_RE.findall(body)
    if not all_numbers:
        return (f"checkout footer missing (expected `gh pr checkout {pr_number}`)",)
    errors: list[str] = []
    html_wrapped = bool(_HTML_FOOTER_RE.search(body))
    if html_wrapped:
        errors.append("checkout footer must be a plain-backtick line, not HTML-wrapped")
    plain_numbers = _PLAIN_FOOTER_RE.findall(body)
    if str(pr_number) not in plain_numbers:
        if str(pr_number) not in all_numbers:
            errors.append(f"checkout footer carries the wrong number (expected PR #{pr_number})")
        elif not html_wrapped:
            errors.append("checkout footer is present but not a plain-backtick line")
    return tuple(errors)


def mark_pr_ready(*, number: int, repo_root: Path, dry_run: bool = False) -> None:
    """Mark a draft PR ready for review (the lone GraphQL op — there is no REST endpoint).

    Called only on a draft PR (the worker checks `is_draft` first); raises on failure.
    """
    if dry_run:
        return
    proc = _exec._run(["pr", "ready", str(number)], cwd=repo_root, timeout=_exec._WRITE_TIMEOUT)
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to mark PR #{number} ready")


def merge_pr(
    *, number: int, repo_root: Path, commit_message: str | None = None, dry_run: bool = False
) -> PullRequest:
    """Squash-merge a PR (REST `PUT .../merge`). Idempotent: an already-merged PR is success.

    The caller checks `state != MERGED` before merging; the ``already merged`` net guards a race.
    """
    if dry_run:
        return PullRequest(number=number, url="", is_draft=False, state="MERGED", existed=True)
    args = [
        "api",
        f"repos/{{owner}}/{{repo}}/pulls/{number}/merge",
        "-X",
        "PUT",
        "-f",
        "merge_method=squash",
    ]
    if commit_message:
        args += ["-f", f"commit_message={commit_message}"]
    proc = _exec._run(args, cwd=repo_root, timeout=_exec._WRITE_TIMEOUT)
    if proc.returncode == 0:
        return PullRequest(number=number, url="", is_draft=False, state="MERGED", existed=True)
    if "already merged" in (proc.stderr + proc.stdout).lower():
        return PullRequest(number=number, url="", is_draft=False, state="MERGED", existed=True)
    raise _exec._failed(proc, f"failed to merge PR #{number}")
