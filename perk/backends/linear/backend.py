from pathlib import Path

from perk import github, plan
from perk.backends import engagement, issue_backend
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear._helpers import (
    _agent_activity,
    _agent_session_read,
    _description_edit,
    _engagement_comment,
    _note,
    _require_issue_node,
    to_linear_markdown,
)
from perk.backends.linear.client import (
    LinearClient,
    _opt_str,
    _require_dict,
    _require_list,
    _require_str,
)
from perk.backends.linear.issue_ops import _LinearIssueOps
from perk.github import GitHubError


class LinearIssueBackend:
    """``IssueBackend`` over Linear — constructor-bound ``team_key`` (lazily resolved + cached),
    human **identifiers** (``ENG-123``) as boundary issue ids (the verified mutations take the
    identifier directly; comment ids stay UUIDs), Linear-safe-encoded
    bodies, and the GitHub-twin behavior shapes for every plan/learn/label/comment op. A thin
    facade over the shared :class:`_LinearIssueOps` substrate."""

    # The `[issues] backend` vocabulary id — a module-level literal (never imported from the
    # resolver module, which will import us at wiring time).
    backend_id = "linear"

    def __init__(self, client: LinearClient, *, team_key: str, repo_root: Path) -> None:
        # The shared substrate (caches + every issue-op helper), also owned by
        # ``LinearObjectiveStore``. `repo_root` lives on `_ops` (the PR-tier `_get_pr` reads it).
        self._ops = _LinearIssueOps(client, team_key=team_key, repo_root=repo_root)
        # Re-exposed for the resolver tests that assert the bound team key.
        self._team_key = team_key

    # ------------------------------------------------------------------ labels

    def ensure_label(
        self, name: str, *, color: str, description: str, dry_run: bool = False
    ) -> issue_backend.Label:
        if dry_run:
            return issue_backend.Label(name=name, created=False)
        _, created = self._ops._ensure_label_id(name, color=color, description=description)
        return issue_backend.Label(name=name, created=created)

    # ------------------------------------------------------------------ plan issues

    def find_plan_issue(self, *, run_id: str) -> issue_backend.IssueRef | None:
        return self._ops._find_issue_by_run_id(
            label=plan.PLAN_LABEL, header_key=plan.PLAN_HEADER_KEY, run_id=run_id
        )

    def create_plan_issue(
        self, *, title: str, body: str, run_id: str | None, dry_run: bool = False
    ) -> issue_backend.IssueRef:
        if dry_run:
            return issue_backend.IssueRef(id="0", url="(dry-run)", existed=False)
        if run_id:
            existing = self.find_plan_issue(run_id=run_id)
            if existing is not None:
                return existing
        label_id, _ = self._ops._ensure_label_id(
            plan.PLAN_LABEL,
            color=plan.PLAN_LABEL_COLOR,
            description=plan.PLAN_LABEL_DESCRIPTION,
        )
        return self._ops._create_issue(
            title=title, description=to_linear_markdown(body), label_id=label_id
        )

    def update_plan_issue(
        self, *, issue_id: str, title: str, body_comment: str, dry_run: bool = False
    ) -> issue_backend.PlanUpdate:
        if dry_run:
            return issue_backend.PlanUpdate(
                issue_id=issue_id, body_updated=False, title_updated=False, dry_run=True
            )
        transcoded = to_linear_markdown(body_comment)
        comment_id: str | None = None
        for comment in self._ops._comments(issue_id):
            comment_body = comment.get("body")
            if isinstance(comment_body, str) and plan.extract_plan_body(comment_body) is not None:
                comment_id = _require_str(comment.get("id"), "comment id")
                break
        if comment_id is not None:
            self._ops._update_comment(comment_id, transcoded)
            body_updated = True
        else:
            self._ops._create_comment(issue_id, transcoded)
            body_updated = False
        self._ops._update_issue(issue_id, {"title": title}, what="update title")
        return issue_backend.PlanUpdate(
            issue_id=issue_id, body_updated=body_updated, title_updated=True, dry_run=False
        )

    def update_plan_header(
        self, *, issue_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> issue_backend.PlanHeaderUpdate:
        unknown = set(fields) - plan.PLAN_HEADER_FIELDS
        if unknown:
            raise IssueBackendError(f"unknown plan-header field(s): {sorted(unknown)}")
        issue = self._ops._get_issue(issue_id, "id description")
        description = issue.get("description")
        body = _opt_str(description) or ""
        header = plan.find_metadata_block(body, plan.PLAN_HEADER_KEY) or {}
        new_body = plan.replace_metadata_block(body, plan.PLAN_HEADER_KEY, {**header, **fields})
        if dry_run:
            return issue_backend.PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=True)
        self._ops._update_issue(issue_id, {"description": new_body}, what="update plan-header")
        # Best-effort native PR attachment: when this stamp carries a `pr` that resolves to a
        # GitHub PR, post (idempotently-by-URL) a sidebar card linking it. Bookkeeping, never
        # load-bearing — a Linear hiccup or a PR-lookup miss must never fail the header stamp.
        self._post_pr_attachment(issue_id, fields.get("pr"))
        return issue_backend.PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=False)

    def _post_pr_attachment(self, issue_id: str, pr_field: object) -> None:
        """Best-effort, fail-open PR attachment. ``pr_field`` is the header `pr` value (a GitHub
        PR number as str/int, or ``None``). No-op when absent/unresolvable; the single seam covers
        both a standalone Linear plan issue and a unified node-issue (both stamp `pr` here)."""
        if not (
            isinstance(pr_field, str | int) and str(pr_field).strip() and str(pr_field) != "None"
        ):
            return
        try:
            pr = self._get_pr(int(pr_field))
            if pr is None:
                return
            self._ops.create_attachment(
                issue_id,
                url=pr.url,
                title=f"GitHub PR #{pr.number}",
                subtitle=pr.state,
            )
        except (IssueBackendError, GitHubError, ValueError) as exc:
            _note(f"PR attachment skipped (non-fatal): {exc}")

    def prepend_plan_callout(
        self, *, issue_id: str, callout: str, command: str, dry_run: bool = False
    ) -> bool:
        issue = self._ops._get_issue(issue_id, "id description")
        description = issue.get("description")
        body = _opt_str(description) or ""
        new_body = plan.prepend_callout(body, callout, command=command)
        if new_body == body:
            return False
        if dry_run:
            return False
        self._ops._update_issue(issue_id, {"description": new_body}, what="prepend plan callout")
        return True

    def get_plan(self, *, issue_id: str) -> issue_backend.PlanState | None:
        issue = self._ops._issue_or_none(
            issue_id, "id identifier url title description state { type }"
        )
        if issue is None:
            return None
        node = _require_issue_node(issue)
        body = node["description"] or ""
        header = plan.find_metadata_block(body, plan.PLAN_HEADER_KEY) or {}
        pr_field = header.get("pr")
        pr = (
            self._get_pr(int(pr_field))
            if isinstance(pr_field, str | int) and str(pr_field).strip() and str(pr_field) != "None"
            else None
        )
        state_type = node["state"]["type"]
        return issue_backend.PlanState(
            id=node["identifier"],
            url=node["url"],
            title=node["title"],
            header=header,
            pr=pr,
            state="CLOSED" if state_type in ("completed", "canceled") else "OPEN",
        )

    def _get_pr(self, number: int) -> github.PullRequest | None:
        """The PR tier is GitHub-universal for every backend (the protocol docstring). Late-bound
        module-attribute access (the adapter discipline) so test monkeypatches keep working."""
        try:
            return github.get_pr(number=number, repo_root=self._ops.repo_root)
        except GitHubError as exc:
            raise IssueBackendError(str(exc)) from exc

    def get_plan_body(self, *, issue_id: str) -> str | None:
        issue = self._ops._issue_or_none(issue_id, "id description")
        if issue is None:
            return None
        description = issue.get("description")
        candidates = [_opt_str(description) or ""]
        candidates.extend(
            comment_body
            for comment in self._ops._comments(issue_id)
            if isinstance(comment_body := comment.get("body"), str)
        )
        for text in candidates:
            body = plan.extract_plan_body(text)
            if body:
                return body
        return None

    # ------------------------------------------------------------------ in-place adoption (#706)

    def read_issue(self, *, issue_id: str) -> issue_backend.AdoptableIssue | None:
        issue = self._ops._issue_or_none(
            issue_id, "id identifier url title description state { type }"
        )
        if issue is None:
            return None
        node = _require_issue_node(issue)
        state_type = node["state"]["type"]
        return issue_backend.AdoptableIssue(
            id=node["identifier"],
            url=node["url"],
            title=node["title"],
            body=node["description"] or "",
            state="CLOSED" if state_type in ("completed", "canceled") else "OPEN",
        )

    def adopt_issue_as_plan(
        self,
        *,
        issue_id: str,
        header_fields: dict[str, object],
        plan_markdown: str,
        callout: str,
        command: str,
        dry_run: bool = False,
    ) -> issue_backend.IssueRef:
        if dry_run:
            return issue_backend.IssueRef(id=issue_id, url="(dry-run)", existed=True)
        # (a) ensure + additively add the perk:plan label (issueUpdate's labelIds REPLACES the
        # set, so read the existing ids and union the plan label in — never clobber them).
        label_id, _ = self._ops._ensure_label_id(
            plan.PLAN_LABEL,
            color=plan.PLAN_LABEL_COLOR,
            description=plan.PLAN_LABEL_DESCRIPTION,
        )
        issue = self._ops._get_issue(
            issue_id, "id identifier url description labels { nodes { id } }"
        )
        labels = _require_dict(issue.get("labels"), "issue.labels")
        existing = [
            _require_str(_require_dict(raw, "label").get("id"), "label id")
            for raw in _require_list(labels.get("nodes"), "issue.labels.nodes")
        ]
        label_ids = existing if label_id in existing else [*existing, label_id]
        self._ops._update_issue(issue_id, {"labelIds": label_ids}, what="add perk:plan label")
        # (b)+(c) stamp the plan-header (Linear-safe inline-code) + prepend the callout into the
        # description (title untouched). Adoption only runs on an issue with NO plan-header (the
        # `already_a_plan` refusal guards it), so the absent branch composes inline-code — NEVER
        # the bare replace_metadata_block append path (it appends in lossy HTML form).
        description = issue.get("description")
        body = _opt_str(description) or ""
        if plan.has_metadata_block(body, plan.PLAN_HEADER_KEY):
            new_desc = plan.replace_metadata_block(body, plan.PLAN_HEADER_KEY, header_fields)
        else:
            header_block = plan.render_metadata_block(
                plan.PLAN_HEADER_KEY, header_fields, style="inline-code"
            )
            new_desc = f"{body.rstrip()}\n\n{header_block}\n"
        new_desc = plan.prepend_callout(new_desc, callout, command=command)
        self._ops._update_issue(issue_id, {"description": new_desc}, what="stamp plan-header")
        # (d) upsert the plan-body comment (inline-code), title untouched.
        body_comment = plan.render_plan_body(plan_markdown, style="inline-code")
        existing_comment_id: str | None = None
        for comment in self._ops._comments(issue_id):
            comment_body = comment.get("body")
            if isinstance(comment_body, str) and plan.extract_plan_body(comment_body):
                existing_comment_id = _require_str(comment.get("id"), "comment id")
                break
        if existing_comment_id is not None:
            self._ops._update_comment(existing_comment_id, body_comment)
        else:
            self._ops._create_comment(issue_id, body_comment)
        return issue_backend.IssueRef(
            id=_require_str(issue.get("identifier"), "issue identifier"),
            url=_require_str(issue.get("url"), "issue url"),
            existed=True,
        )

    # ------------------------------------------------------------------ learn issues

    def find_learn_issue(self, *, run_id: str) -> issue_backend.IssueRef | None:
        return self._ops._find_issue_by_run_id(
            label=plan.LEARN_LABEL, header_key=plan.LEARN_HEADER_KEY, run_id=run_id
        )

    def create_learn_issue(
        self, *, title: str, body: str, run_id: str | None, plan_id: str, dry_run: bool = False
    ) -> issue_backend.IssueRef:
        if dry_run:
            return issue_backend.IssueRef(id="0", url="(dry-run)", existed=False)
        if run_id:
            existing = self.find_learn_issue(run_id=run_id)
            if existing is not None:
                return existing
        label_id, _ = self._ops._ensure_label_id(
            plan.LEARN_LABEL,
            color=plan.LEARN_LABEL_COLOR,
            description=plan.LEARN_LABEL_DESCRIPTION,
        )
        # Rendered directly in the inline-code style (no transcoding needed). The header `plan`
        # field stores the boundary `plan_id` string verbatim (headers are backend-owned opaque
        # values — GitHub stores its int issue number; Linear stores its string id).
        header = plan.render_metadata_block(
            plan.LEARN_HEADER_KEY,
            {"run_id": run_id, "created": plan.now_iso(), "plan": plan_id},
            style="inline-code",
        )
        full_body = f"{header}\n\n{to_linear_markdown(body.strip())}\n"
        return self._ops._create_issue(title=title, description=full_body, label_id=label_id)

    def list_learn_issues(self) -> tuple[issue_backend.LearnIssueSummary, ...]:
        summaries: list[issue_backend.LearnIssueSummary] = []
        selection = "id identifier title url description"
        for node in self._ops._list_label_issues(plan.LEARN_LABEL, selection):
            description = node.get("description")
            identifier = _require_str(node.get("identifier"), "issue identifier")
            summaries.append(
                issue_backend.LearnIssueSummary(
                    id=identifier,
                    title=_require_str(node.get("title"), "issue title"),
                    url=_require_str(node.get("url"), "issue url"),
                    body=_opt_str(description) or "",
                )
            )
        return tuple(summaries)

    def close_and_label_consolidated(self, *, issue_id: str, dry_run: bool = False) -> bool:
        if dry_run:
            return True
        label_id, _ = self._ops._ensure_label_id(
            plan.CONSOLIDATED_LABEL,
            color=plan.CONSOLIDATED_LABEL_COLOR,
            description=plan.CONSOLIDATED_LABEL_DESCRIPTION,
        )
        # Additive labelling: read the existing label ids, union in the consolidated label
        # (issueUpdate's labelIds REPLACES the set — never write it without the existing ids).
        issue = self._ops._get_issue(issue_id, "id labels { nodes { id } }")
        labels = _require_dict(issue.get("labels"), "issue.labels")
        existing = [
            _require_str(_require_dict(raw, "label").get("id"), "label id")
            for raw in _require_list(labels.get("nodes"), "issue.labels.nodes")
        ]
        label_ids = existing if label_id in existing else [*existing, label_id]
        self._ops._update_issue(issue_id, {"labelIds": label_ids}, what="label consolidated")
        self._ops._update_issue(issue_id, {"stateId": self._ops._done_state_id()}, what="close")
        return True

    # ------------------------------------------------------------------ generic issue ops

    def close_issue(self, *, issue_id: str, dry_run: bool = False) -> bool:
        if dry_run:
            return False
        self._ops._update_issue(issue_id, {"stateId": self._ops._done_state_id()}, what="close")
        return True

    def add_issue_comment(
        self, *, issue_id: str, body: str, dry_run: bool = False
    ) -> issue_backend.CommentResult:
        if dry_run:
            return issue_backend.CommentResult(posted=False)
        self._ops._create_comment(issue_id, to_linear_markdown(body))
        return issue_backend.CommentResult(posted=True)

    def find_comment_id_by_marker(self, *, issue_id: str, marker: str) -> str | None:
        # The incoming marker is GitHub-encoded (e.g. the run-report HTML comment); transcode it
        # so it matches the transcoded comment this backend previously wrote.
        needle = to_linear_markdown(marker)
        for comment in self._ops._comments(issue_id):
            comment_body = comment.get("body")
            if isinstance(comment_body, str) and needle in comment_body:
                return _require_str(comment.get("id"), "comment id")
        return None

    def upsert_marked_comment(
        self, *, issue_id: str, marker: str, body: str, dry_run: bool = False
    ) -> issue_backend.CommentResult:
        if dry_run:
            return issue_backend.CommentResult(posted=False)
        transcoded = to_linear_markdown(body)
        comment_id = self.find_comment_id_by_marker(issue_id=issue_id, marker=marker)
        if comment_id is not None:
            self._ops._update_comment(comment_id, transcoded)
        else:
            self._ops._create_comment(issue_id, transcoded)
        return issue_backend.CommentResult(posted=True)

    # ------------------------------------------------------------------ human-engagement reads
    # The honest READ surface (Objective #682, Node 1.2). All returned `body`/`diff`/activity
    # `body` is untrusted DATA; author identity is distinguishable. No flow consumers in 1.2.

    def read_comments(self, *, issue_id: str) -> tuple[engagement.EngagementComment, ...]:
        return tuple(
            _engagement_comment(node) for node in self._ops._comments_with_authors(issue_id)
        )

    def read_description_edits(self, *, issue_id: str) -> tuple[engagement.DescriptionEdit, ...]:
        return tuple(_description_edit(node) for node in self._ops._description_edits(issue_id))

    def read_agent_session(self, *, issue_id: str) -> engagement.AgentSessionRead:
        activities = [
            _agent_activity(node) for node in self._ops._agent_session_activities(issue_id)
        ]
        return _agent_session_read(activities)
