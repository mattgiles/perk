"""Tests for the ``IssueBackend`` protocol module.

The real conformance check is **static**: ``_FakeBackend`` is assigned to an
``issue_backend.IssueBackend``-annotated binding, so ty fails the suite if the fake and the
protocol drift. The runtime tests are smoke proofs that the contract is satisfiable with string
ids, plus value-type/error-type sanity and the one-way import-direction guard.
"""

import dataclasses
from pathlib import Path

import pytest

from perk import github
from perk.backends import engagement, issue_backend


@dataclasses.dataclass
class _FakeIssue:
    title: str
    body: str
    run_id: str | None
    state: str = "OPEN"
    comments: dict[str, str] = dataclasses.field(default_factory=dict)
    labels: set[str] = dataclasses.field(default_factory=set)


class _FakeBackend:
    """A minimal in-memory ``IssueBackend`` (the seed of the Fake layer)."""

    backend_id = "fake"

    def __init__(self) -> None:
        self._issues: dict[str, _FakeIssue] = {}
        self._labels: set[str] = set()
        self._next_id = 1
        self._next_comment_id = 1

    def _mint(self, *, title: str, body: str, run_id: str | None) -> issue_backend.IssueRef:
        issue_id = str(self._next_id)
        self._next_id += 1
        self._issues[issue_id] = _FakeIssue(title=title, body=body, run_id=run_id)
        return issue_backend.IssueRef(id=issue_id, url=f"fake://issue/{issue_id}", existed=False)

    def _find_by_run_id(self, run_id: str) -> issue_backend.IssueRef | None:
        for issue_id, issue in self._issues.items():
            if issue.run_id == run_id and issue.state == "OPEN":
                return issue_backend.IssueRef(
                    id=issue_id, url=f"fake://issue/{issue_id}", existed=True
                )
        return None

    # --- labels ---

    def ensure_label(
        self, name: str, *, color: str, description: str, dry_run: bool = False
    ) -> issue_backend.Label:
        if dry_run or name in self._labels:
            return issue_backend.Label(name=name, created=False)
        self._labels.add(name)
        return issue_backend.Label(name=name, created=True)

    # --- plan issues ---

    def find_plan_issue(self, *, run_id: str) -> issue_backend.IssueRef | None:
        return self._find_by_run_id(run_id)

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
        return self._mint(title=title, body="", run_id=run_id)

    def update_plan_issue(
        self, *, issue_id: str, title: str, body_comment: str, dry_run: bool = False
    ) -> issue_backend.PlanUpdate:
        if dry_run:
            return issue_backend.PlanUpdate(
                issue_id=issue_id, body_updated=False, title_updated=False, dry_run=True
            )
        issue = self._issues[issue_id]
        issue.title = title
        issue.comments["plan-body"] = body_comment
        return issue_backend.PlanUpdate(
            issue_id=issue_id, body_updated=True, title_updated=True, dry_run=False
        )

    def update_plan_header(
        self, *, issue_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> issue_backend.PlanHeaderUpdate:
        return issue_backend.PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=dry_run)

    def prepend_plan_callout(
        self, *, issue_id: str, callout: str, command: str, dry_run: bool = False
    ) -> bool:
        from perk import plan

        issue = self._issues[issue_id]
        new_body = plan.prepend_callout(issue.body, callout, command=command)
        if new_body == issue.body or dry_run:
            return False
        issue.body = new_body
        return True

    def get_plan(self, *, issue_id: str) -> issue_backend.PlanState | None:
        issue = self._issues.get(issue_id)
        if issue is None:
            return None
        return issue_backend.PlanState(
            id=issue_id,
            url=f"fake://issue/{issue_id}",
            title=issue.title,
            header={},
            pr=None,
            state=issue.state,
        )

    def get_plan_body(self, *, issue_id: str) -> str | None:
        issue = self._issues.get(issue_id)
        if issue is None:
            return None
        return issue.comments.get("plan-body")

    # --- in-place issue adoption (§8.29) ---

    def read_issue(self, *, issue_id: str) -> issue_backend.AdoptableIssue | None:
        issue = self._issues.get(issue_id)
        if issue is None:
            return None
        return issue_backend.AdoptableIssue(
            id=issue_id,
            url=f"fake://issue/{issue_id}",
            title=issue.title,
            body=issue.body,
            state=issue.state,
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
        from perk import plan

        issue = self._issues[issue_id]
        if not dry_run:
            issue.labels.add(plan.PLAN_LABEL)
            issue.body = plan.prepend_callout(
                plan.replace_metadata_block(issue.body, plan.PLAN_HEADER_KEY, header_fields),
                callout,
                command=command,
            )
            issue.comments["plan-body"] = plan.render_plan_body(plan_markdown)
        return issue_backend.IssueRef(id=issue_id, url=f"fake://issue/{issue_id}", existed=True)

    # --- learn issues ---

    def find_learn_issue(self, *, run_id: str) -> issue_backend.IssueRef | None:
        return self._find_by_run_id(run_id)

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
        return self._mint(title=title, body=body, run_id=run_id)

    def list_learn_issues(self) -> tuple[issue_backend.LearnIssueSummary, ...]:
        return tuple(
            issue_backend.LearnIssueSummary(
                id=issue_id, title=issue.title, url=f"fake://issue/{issue_id}", body=issue.body
            )
            for issue_id, issue in self._issues.items()
            if issue.state == "OPEN"
        )

    def list_plan_completion_candidates(self) -> tuple[issue_backend.PlanSummary, ...]:
        return tuple(
            issue_backend.PlanSummary(id=issue_id, title=issue.title)
            for issue_id, issue in self._issues.items()
            if issue.state == "OPEN"
        )

    def list_plans_pending_learn(
        self, *, limit: int = 50
    ) -> tuple[issue_backend.PendingLearnPlan, ...]:
        from perk import plan

        rows: list[issue_backend.PendingLearnPlan] = []
        for issue_id, issue in self._issues.items():
            if issue.state != "CLOSED":
                continue
            header = plan.find_metadata_block(issue.body, plan.PLAN_HEADER_KEY)
            if header is None or header.get("learn_state") != plan.LearnState.PENDING:
                continue
            rows.append(
                issue_backend.PendingLearnPlan(
                    id=issue_id, title=issue.title, url=f"fake://issue/{issue_id}"
                )
            )
        return tuple(rows[:limit])

    # --- gist issues (§8.41) ---

    def find_gist_issue(self, *, run_id: str) -> issue_backend.IssueRef | None:
        return self._find_by_run_id(run_id)

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
        return self._mint(title=title, body=body, run_id=run_id)

    def list_gist_issues(self) -> tuple[issue_backend.GistSummary, ...]:
        return tuple(
            issue_backend.GistSummary(
                id=issue_id, title=issue.title, url=f"fake://issue/{issue_id}", body=issue.body
            )
            for issue_id, issue in self._issues.items()
            if issue.state == "OPEN"
        )

    def close_and_label_consolidated(self, *, issue_id: str, dry_run: bool = False) -> bool:
        if dry_run:
            return True
        issue = self._issues[issue_id]
        issue.labels.add("perk:consolidated")
        issue.state = "CLOSED"
        return True

    # --- generic issue ops ---

    def close_issue(self, *, issue_id: str, dry_run: bool = False) -> bool:
        if dry_run:
            return False
        self._issues[issue_id].state = "CLOSED"
        return True

    def add_issue_comment(
        self, *, issue_id: str, body: str, dry_run: bool = False
    ) -> issue_backend.CommentResult:
        if dry_run:
            return issue_backend.CommentResult(posted=False)
        comment_id = str(self._next_comment_id)
        self._next_comment_id += 1
        self._issues[issue_id].comments[comment_id] = body
        return issue_backend.CommentResult(posted=True)

    def find_comment_id_by_marker(self, *, issue_id: str, marker: str) -> str | None:
        for comment_id, body in self._issues[issue_id].comments.items():
            if marker in body:
                return comment_id
        return None

    def upsert_marked_comment(
        self, *, issue_id: str, marker: str, body: str, dry_run: bool = False
    ) -> issue_backend.CommentResult:
        if dry_run:
            return issue_backend.CommentResult(posted=False)
        comment_id = self.find_comment_id_by_marker(issue_id=issue_id, marker=marker)
        if comment_id is not None:
            self._issues[issue_id].comments[comment_id] = body
            return issue_backend.CommentResult(posted=True)
        return self.add_issue_comment(issue_id=issue_id, body=body)

    # --- human-engagement reads ---

    def read_comments(self, *, issue_id: str) -> tuple[engagement.EngagementComment, ...]:
        return ()

    def read_description_edits(self, *, issue_id: str) -> tuple[engagement.DescriptionEdit, ...]:
        return ()

    def read_agent_session(self, *, issue_id: str) -> engagement.AgentSessionRead:
        return engagement.EMPTY_AGENT_SESSION


def _make_backend() -> issue_backend.IssueBackend:
    """The static conformance check: ty verifies ``_FakeBackend`` satisfies the protocol."""
    backend: issue_backend.IssueBackend = _FakeBackend()
    return backend


class TestFakeBackendConformance:
    def test_plan_create_find_round_trip_on_run_id(self) -> None:
        backend = _make_backend()
        created = backend.create_plan_issue(title="t", header_fields={}, run_id="RUN1")
        assert isinstance(created.id, str)
        assert created.existed is False
        found = backend.find_plan_issue(run_id="RUN1")
        assert found is not None
        assert found.id == created.id
        assert found.existed is True
        # idempotent re-create returns the existing issue
        again = backend.create_plan_issue(title="t", header_fields={}, run_id="RUN1")
        assert again.id == created.id
        assert again.existed is True

    def test_create_plan_issue_dry_run_shape(self) -> None:
        backend = _make_backend()
        ref = backend.create_plan_issue(title="t", header_fields={}, run_id="RUN1", dry_run=True)
        assert ref == issue_backend.IssueRef(id="0", url="(dry-run)", existed=False)

    def test_upsert_marked_comment_post_then_patch(self) -> None:
        backend = _make_backend()
        ref = backend.create_plan_issue(title="t", header_fields={}, run_id="RUN2")
        marker = "<!-- run-report -->"
        backend.upsert_marked_comment(issue_id=ref.id, marker=marker, body=f"{marker}\nstarted")
        first = backend.find_comment_id_by_marker(issue_id=ref.id, marker=marker)
        assert isinstance(first, str)
        backend.upsert_marked_comment(issue_id=ref.id, marker=marker, body=f"{marker}\ndone")
        second = backend.find_comment_id_by_marker(issue_id=ref.id, marker=marker)
        assert second == first  # patched in place, not re-posted

    def test_prepend_plan_callout_idempotent(self) -> None:
        backend = _make_backend()
        ref = backend.create_plan_issue(title="t", header_fields={}, run_id="RUNC")
        callout = "**Implement this plan:**\n\n```\nperk impl 1\n```\n\n_hint_"
        wrote = backend.prepend_plan_callout(
            issue_id=ref.id, callout=callout, command="perk impl 1"
        )
        assert wrote is True
        state = backend.get_plan(issue_id=ref.id)
        assert state is not None
        # second call is a no-op (already present)
        again = backend.prepend_plan_callout(
            issue_id=ref.id, callout=callout, command="perk impl 1"
        )
        assert again is False

    def test_prepend_plan_callout_dry_run_writes_nothing(self) -> None:
        backend = _make_backend()
        ref = backend.create_plan_issue(title="t", header_fields={}, run_id="RUND")
        wrote = backend.prepend_plan_callout(
            issue_id=ref.id, callout="CALLOUT", command="perk impl 1", dry_run=True
        )
        assert wrote is False
        again = backend.prepend_plan_callout(
            issue_id=ref.id, callout="CALLOUT", command="perk impl 1"
        )
        assert again is True  # the dry run did not persist the callout

    def test_string_ids_everywhere(self) -> None:
        backend = _make_backend()
        ref = backend.create_plan_issue(title="t", header_fields={}, run_id="RUN3")
        state = backend.get_plan(issue_id=ref.id)
        assert state is not None
        assert isinstance(state.id, str)
        assert state.state == "OPEN"
        update = backend.update_plan_issue(issue_id=ref.id, title="t2", body_comment="body")
        assert isinstance(update.issue_id, str)


class TestValueTypes:
    def test_issue_ref_is_frozen_with_string_id(self) -> None:
        ref = issue_backend.IssueRef(id="42", url="u", existed=False)
        assert ref.id == "42"
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.id = "43"  # ty: ignore[invalid-assignment]

    def test_plan_state_is_frozen_with_string_id(self) -> None:
        state = issue_backend.PlanState(
            id="7", url="u", title="t", header={}, pr=None, state="OPEN"
        )
        assert state.id == "7"
        with pytest.raises(dataclasses.FrozenInstanceError):
            state.state = "CLOSED"  # ty: ignore[invalid-assignment]


class TestErrorType:
    def test_issue_backend_error_is_raisable_exception(self) -> None:
        assert issubclass(issue_backend.IssueBackendError, Exception)
        with pytest.raises(issue_backend.IssueBackendError, match="boom"):
            raise issue_backend.IssueBackendError("boom")


def _github_package_source() -> str:
    """Every ``*.py`` under the ``perk/github/`` package, concatenated.

    ``github.__file__`` is the near-empty ``__init__.py``; the guard must scan the whole
    package or it goes vacuous.
    """
    package_dir = Path(github.__file__).parent
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(package_dir.rglob("*.py")))


class TestImportDirection:
    def test_github_module_never_imports_issue_backend(self) -> None:
        # The one-way import decision: issue_backend imports github (PullRequest), never the
        # reverse — must not invert the dependency from inside the github package.
        source = _github_package_source()
        assert "issue_backend" not in source

    def test_github_module_never_imports_the_backend_tier(self) -> None:
        # The pure-gateway rule (Principle 1): the adapter (perk/backends/github/backend.py) is the
        # only module importing both sides; the github package must never reach up into the backend
        # tier at all. A dotted `perk.backends` import is the violation (docstrings reference the
        # backend tier in slash form, which is fine).
        source = _github_package_source()
        assert "perk.backends" not in source

    def test_github_module_never_imports_the_delivery_module(self) -> None:
        # contracts §8.43/§8.44: nothing in `perk/github/` imports `perk.delivery` — the delivery
        # module's wiring leaf imports the gateway, never the reverse (covers `stacks.py` too:
        # the package-wide scan picks up every new gateway module).
        source = _github_package_source()
        assert "perk.delivery" not in source

    def test_backends_package_never_imports_the_delivery_module(self) -> None:
        # The same one-way rule for the backend tier: `perk.delivery` imports the
        # `perk.backends.*` contracts one-directionally; nothing imports back.
        package_dir = Path(issue_backend.__file__).parent
        source = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(package_dir.rglob("*.py"))
        )
        assert "perk.delivery" not in source

    def test_issue_backend_module_never_imports_the_resolver(self) -> None:
        # The contract stays implementation-free: the protocol module never references the
        # concrete backend/resolver modules.
        source = Path(issue_backend.__file__).read_text(encoding="utf-8")
        assert "perk.backends.resolve" not in source
        assert "perk.backends.github" not in source


class TestParsePlanPr:
    """The shared tolerant plan-PR parser at the issue read boundary (§8.54): both production
    ``get_plan`` adapters route through it, so its vocabulary is pinned once here."""

    @pytest.mark.parametrize("value", [None, "", "   ", "None"])
    def test_no_claim_vocabulary(self, value) -> None:
        assert issue_backend.parse_plan_pr(value) is None

    @pytest.mark.parametrize(
        ("value", "expected"), [(55, 55), ("55", 55), ("#55", 55), (" 55 ", 55), (1, 1)]
    )
    def test_positive_claims_resolve(self, value, expected) -> None:
        assert issue_backend.parse_plan_pr(value) == expected

    @pytest.mark.parametrize(
        "value", ["garbage", "12.5", "#", 0, -3, "0", "-3", "#0", True, False, ["55"], {"pr": 1}]
    )
    def test_malformed_or_non_positive_resolves_no_number(self, value) -> None:
        # Read-side tolerance only: the raw header value is never rewritten (the caller keeps
        # it); writers remain strict.
        assert issue_backend.parse_plan_pr(value) is None
