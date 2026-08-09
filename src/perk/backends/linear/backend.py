from pathlib import Path

from perk import github, plan
from perk.backends import engagement, issue_backend
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import attachments
from perk.backends.linear._helpers import (
    LinearIssueNodeModel,
    _agent_activity,
    _agent_session_read,
    _description_edit,
    _engagement_comment,
    _note,
    to_linear_markdown,
)
from perk.backends.linear.client import (
    LinearClient,
    _opt_dict,
    _opt_str,
    _require_dict,
    _require_list,
    _require_str,
)
from perk.backends.linear.issue_ops import _LinearIssueOps
from perk.boundary import ValidationError, translate_validation_errors
from perk.github import GitHubError

# The recurring issue selection (`get_plan` / `read_issue`): the 6-field node + the raw
# attachment nodes the perk-metadata decode reads. No attachment cursor loop (perk writes ≤2
# envelopes + the PR card per issue — 50 is a safe fixed bound).
_ISSUE_SELECTION = (
    "id identifier url title description state { type } "
    "attachments(first: 50) { nodes { id url metadata } }"
)


def _attachment_nodes_of(node: dict[str, object]) -> list[dict[str, object]]:
    """The raw attachment nodes off a raw issue row (``[]`` when absent/malformed)."""
    connection = _opt_dict(node.get("attachments"))
    nodes = connection.get("nodes") if connection is not None else None
    if not isinstance(nodes, list):
        return []
    result: list[dict[str, object]] = []
    for raw in nodes:
        node_dict = _opt_dict(raw)
        if node_dict is not None:
            result.append(node_dict)
    return result


def _learn_header_of(node: dict[str, object]) -> plan.LearnHeader | None:
    """Decode a learn issue row's learn-header attachment into the typed :class:`LearnHeader`.
    ``None`` when absent or invalid — mirroring ``plan.parse_learn_header``'s degrade-to-None
    (the gather-time default route never bricks on a stray header). Invalid covers BOTH a
    malformed envelope (``find_perk_attachment`` raising) and a well-formed envelope with
    off-schema fields (``ValidationError``) — one bad attachment must never brick the whole
    ``list_learn_issues`` gather."""
    try:
        found = attachments.find_perk_attachment(
            _attachment_nodes_of(node), kind=attachments.LEARN_HEADER_KIND
        )
    except IssueBackendError:
        return None
    if found is None:
        return None
    try:
        return plan.LearnHeaderModel.model_validate(found.payload).to_domain()
    except ValidationError:
        return None


def _gist_scope_of(attachment_nodes: list[dict[str, object]]) -> str | None:
    """Decode a gist issue row's gist-header attachment into the stored ``scope`` string.
    ``None`` when the attachment is absent/malformed or the stored scope is unknown — the
    lenient posture of :func:`_learn_header_of` (one bad attachment never bricks the gather)."""
    try:
        found = attachments.find_perk_attachment(
            attachment_nodes, kind=attachments.GIST_HEADER_KIND
        )
    except IssueBackendError:
        return None
    if found is None:
        return None
    try:
        header = plan.GistHeaderModel.model_validate(found.payload).to_domain()
    except ValidationError:
        return None
    return None if header.scope is None else header.scope.value


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
        return self._find_by_attachment_url(attachments.plan_header_url(run_id))

    def _find_by_attachment_url(self, url: str) -> issue_backend.IssueRef | None:
        """The run_id-keyed save-time idempotency find over ``attachmentsForURL``. Parity guard:
        the legacy scan listed **open** issues only, but ``attachmentsForURL`` is
        state-independent — a hit in a terminal state (``completed``/``canceled``) is treated as
        not-found, so a landed plan's run_id never resurrects the closed issue on a re-save."""
        issue = self._ops.find_issue_by_attachment_url(url)
        if issue is None:
            return None
        state = _opt_dict(issue.get("state"))
        state_type = _opt_str(state.get("type")) if state is not None else None
        if state_type in ("completed", "canceled"):
            return None
        return issue_backend.IssueRef(
            id=_require_str(issue.get("identifier"), "issue identifier"),
            url=_require_str(issue.get("url"), "issue url"),
            existed=True,
        )

    def create_plan_issue(
        self,
        *,
        title: str,
        header_fields: dict[str, object],
        run_id: str | None,
        dry_run: bool = False,
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
        # Clean-body create: the description carries no machine state — the plan-header rides a
        # native attachment (URL keyed on run_id, else the identifier for a run-id-less plan).
        # Two writes = an accepted one-round-trip crash window (the sentinel-create precedent):
        # a failure between issueCreate and the attachment upsert orphans a header-less issue
        # invisible to find_plan_issue (a retry mints a fresh one; the orphan is human-visible
        # garbage to close, never silently corrupting).
        ref = self._ops._create_issue(title=title, description="", label_id=label_id)
        self._ops.upsert_perk_attachment(
            ref.id,
            kind=attachments.PLAN_HEADER_KIND,
            url=attachments.plan_header_url(run_id or ref.id),
            fields=header_fields,
        )
        return ref

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
        nodes = self._ops.issue_attachments(issue_id)
        found = attachments.find_perk_attachment(nodes, kind=attachments.PLAN_HEADER_KIND)
        merged = {**(found.payload if found is not None else {}), **fields}
        if found is not None:
            # Reuse the found attachment's URL — the upsert identity (never re-derive it, which
            # would orphan the existing card on an identifier-keyed plan).
            url = found.url
        else:
            # Under the clean break a Linear plan issue always got its attachment at create; an
            # absent attachment with no run_id to key a fresh URL is a loud invariant violation.
            run_id = merged.get("run_id")
            if not isinstance(run_id, str) or not run_id:
                raise IssueBackendError(
                    f"Linear plan issue {issue_id!r} has no plan-header attachment and no run_id "
                    "to key one"
                )
            url = attachments.plan_header_url(run_id)
        if dry_run:
            return issue_backend.PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=True)
        self._ops.upsert_perk_attachment(
            issue_id, kind=attachments.PLAN_HEADER_KIND, url=url, fields=merged
        )
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
        issue = self._ops._issue_or_none(issue_id, _ISSUE_SELECTION)
        if issue is None:
            return None
        with translate_validation_errors(IssueBackendError, source=f"read plan issue {issue_id!r}"):
            node = LinearIssueNodeModel.model_validate(issue)
        found = attachments.find_perk_attachment(
            node.attachment_nodes(), kind=attachments.PLAN_HEADER_KIND
        )
        header = found.payload if found is not None else {}
        pr_field = header.get("pr")
        pr = (
            self._get_pr(int(pr_field))
            if isinstance(pr_field, str | int) and str(pr_field).strip() and str(pr_field) != "None"
            else None
        )
        return issue_backend.PlanState(
            id=node.identifier,
            url=node.url,
            title=node.title,
            header=header,
            pr=pr,
            state=node.normalized_state(),
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

    # ------------------------------------------------------------------ in-place adoption

    def read_issue(self, *, issue_id: str) -> issue_backend.AdoptableIssue | None:
        issue = self._ops._issue_or_none(issue_id, _ISSUE_SELECTION)
        if issue is None:
            return None
        with translate_validation_errors(IssueBackendError, source=f"read issue {issue_id!r}"):
            node = LinearIssueNodeModel.model_validate(issue)
        return issue_backend.AdoptableIssue(
            id=node.identifier,
            url=node.url,
            title=node.title,
            body=node.description or "",
            state=node.normalized_state(),
            # Presence-only + tolerant (the GitHub twin is `has_metadata_block`): a plan
            # attachment with a corrupt payload still means "already a plan" — the adoption
            # refusal must refuse, not crash.
            already_plan=attachments.has_perk_attachment(
                node.attachment_nodes(), kind=attachments.PLAN_HEADER_KIND
            ),
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
        identifier = _require_str(issue.get("identifier"), "issue identifier")
        # (b) upsert the plan-header attachment — the human body is preserved VERBATIM (adoption
        # fidelity: no metadata splice into the description). URL keyed on the header's run_id,
        # else the identifier (a run-id-less plan is never found by run_id anyway).
        run_id = header_fields.get("run_id")
        key = run_id if isinstance(run_id, str) and run_id else identifier
        self._ops.upsert_perk_attachment(
            issue_id,
            kind=attachments.PLAN_HEADER_KIND,
            url=attachments.plan_header_url(key),
            fields=header_fields,
        )
        # (c) idempotently prepend the callout above the (otherwise untouched) human body.
        description = issue.get("description")
        body = _opt_str(description) or ""
        new_desc = plan.prepend_callout(body, callout, command=command)
        if new_desc != body:
            self._ops._update_issue(
                issue_id, {"description": new_desc}, what="prepend plan callout"
            )
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
            id=identifier,
            url=_require_str(issue.get("url"), "issue url"),
            existed=True,
        )

    # ------------------------------------------------------------------ learn issues

    def find_learn_issue(self, *, run_id: str) -> issue_backend.IssueRef | None:
        return self._find_by_attachment_url(attachments.learn_header_url(run_id))

    def create_learn_issue(
        self,
        *,
        title: str,
        body: str,
        run_id: str | None,
        plan_id: str,
        decision: str | None = None,
        target: str | None = None,
        dry_run: bool = False,
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
        # Clean-body create: the description is the transcoded learning prose only — the
        # learn-header rides a native attachment (same accepted create→attachment crash window
        # as create_plan_issue). The header `plan` field stores the boundary `plan_id` string
        # verbatim (headers are backend-owned opaque values); the optional captured
        # `decision`/`target` classification rides it too (contracts.md §8.35).
        ref = self._ops._create_issue(
            title=title,
            description=f"{to_linear_markdown(body.strip())}\n",
            label_id=label_id,
        )
        fields: dict[str, object] = {
            "run_id": run_id,
            "created": plan.now_iso(),
            "plan": plan_id,
        }
        if decision is not None:
            fields["decision"] = decision
        if target is not None:
            fields["target"] = target
        self._ops.upsert_perk_attachment(
            ref.id,
            kind=attachments.LEARN_HEADER_KIND,
            url=attachments.learn_header_url(run_id or ref.id),
            fields=fields,
        )
        return ref

    def list_learn_issues(self) -> tuple[issue_backend.LearnIssueSummary, ...]:
        summaries: list[issue_backend.LearnIssueSummary] = []
        selection = (
            "id identifier title url description "
            "attachments(first: 50) { nodes { id url metadata } }"
        )
        for node in self._ops._list_label_issues(plan.LEARN_LABEL, selection):
            description = node.get("description")
            identifier = _require_str(node.get("identifier"), "issue identifier")
            summaries.append(
                issue_backend.LearnIssueSummary(
                    id=identifier,
                    title=_require_str(node.get("title"), "issue title"),
                    url=_require_str(node.get("url"), "issue url"),
                    body=_opt_str(description) or "",
                    header=_learn_header_of(node),
                )
            )
        return tuple(summaries)

    def list_plans_pending_learn(
        self, *, limit: int = 50
    ) -> tuple[issue_backend.PendingLearnPlan, ...]:
        selection = (
            "id identifier title url completedAt canceledAt "
            "attachments(first: 50) { nodes { id url metadata } }"
        )
        rows: list[issue_backend.PendingLearnPlan] = []
        for node in self._ops._list_label_issues(plan.PLAN_LABEL, selection, terminal=True):
            if not self._is_pending_learn(node):
                continue
            closed_at = _opt_str(node.get("completedAt")) or _opt_str(node.get("canceledAt"))
            rows.append(
                issue_backend.PendingLearnPlan(
                    id=_require_str(node.get("identifier"), "issue identifier"),
                    title=_require_str(node.get("title"), "issue title"),
                    url=_require_str(node.get("url"), "issue url"),
                    closed_at=closed_at,
                )
            )
        # Most-recently-closed first (None last — "" sorts below every ISO timestamp under
        # reverse); Linear paginates fully, so `limit` is a pure result truncation.
        rows.sort(key=lambda r: r.closed_at or "", reverse=True)
        return tuple(rows[:limit])

    @staticmethod
    def _is_pending_learn(node: dict[str, object]) -> bool:
        """True when the row's plan-header attachment reads ``learn_state: pending`` (§8.36).
        An absent or malformed attachment is silently not-pending — a list surface must never
        brick on a stray header (the ``_learn_header_of`` posture). Malformed covers BOTH a
        bad payload (``find_perk_attachment`` raising ``IssueBackendError``) and a bad envelope
        shape (its lenient envelope parse raising ``ValidationError``)."""
        try:
            found = attachments.find_perk_attachment(
                _attachment_nodes_of(node), kind=attachments.PLAN_HEADER_KIND
            )
        except (IssueBackendError, ValidationError):
            return False
        if found is None:
            return False
        return found.payload.get("learn_state") == plan.LearnState.PENDING

    # ------------------------------------------------------------------ gist issues (§8.41)

    def find_gist_issue(self, *, run_id: str) -> issue_backend.IssueRef | None:
        return self._find_by_attachment_url(attachments.gist_header_url(run_id))

    def create_gist_issue(
        self,
        *,
        title: str,
        body: str,
        run_id: str | None,
        scope: str,
        dry_run: bool = False,
    ) -> issue_backend.IssueRef:
        if dry_run:
            return issue_backend.IssueRef(id="0", url="(dry-run)", existed=False)
        if run_id:
            existing = self.find_gist_issue(run_id=run_id)
            if existing is not None:
                return existing
        label_id, _ = self._ops._ensure_label_id(
            plan.GIST_LABEL,
            color=plan.GIST_LABEL_COLOR,
            description=plan.GIST_LABEL_DESCRIPTION,
        )
        # Clean-body create: the description is the transcoded intent prose only — the
        # gist-header rides a native attachment (same accepted create→attachment crash window
        # as create_plan_issue).
        ref = self._ops._create_issue(
            title=title,
            description=f"{to_linear_markdown(body.strip())}\n",
            label_id=label_id,
        )
        self._ops.upsert_perk_attachment(
            ref.id,
            kind=attachments.GIST_HEADER_KIND,
            url=attachments.gist_header_url(run_id or ref.id),
            fields={"run_id": run_id, "created": plan.now_iso(), "scope": scope},
        )
        return ref

    def list_gist_issues(self) -> tuple[issue_backend.GistSummary, ...]:
        summaries: list[issue_backend.GistSummary] = []
        selection = (
            "id identifier title url description "
            "attachments(first: 50) { nodes { id url metadata } }"
        )
        for node in self._ops._list_label_issues(plan.GIST_LABEL, selection):
            attachment_nodes = _attachment_nodes_of(node)
            summaries.append(
                issue_backend.GistSummary(
                    id=_require_str(node.get("identifier"), "issue identifier"),
                    title=_require_str(node.get("title"), "issue title"),
                    url=_require_str(node.get("url"), "issue url"),
                    body=_opt_str(node.get("description")) or "",
                    scope=_gist_scope_of(attachment_nodes),
                    # Adopted = `plan from` stamped a plan-header attachment beside the
                    # gist-header (a Linear issue-gist can only be adopted as a plan).
                    adopted=attachments.has_perk_attachment(
                        attachment_nodes, kind=attachments.PLAN_HEADER_KIND
                    ),
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
    # The honest READ surface. All returned `body`/`diff`/activity
    # `body` is untrusted DATA; author identity is distinguishable.

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
