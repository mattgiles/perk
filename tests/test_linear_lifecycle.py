"""The end-to-end offline Linear lifecycle suite.

A stateful in-memory Linear workspace (``FakeLinearWorkspace``) subclasses the GraphQL client
(``linear.client.LinearClient``) and is injected via a late-bound
``monkeypatch.setattr(linear_client, "client_from_env", …)`` — ``resolve_issue_backend``
resolves the client at call time, so the REAL ``LinearIssueBackend`` (identifier boundary ids,
transcoded
bodies, identifier-direct mutations) is exercised by the REAL CLI commands. Only the
GitHub **PR tier** (which is GitHub-universal for every backend) is monkeypatched, following
``test_pr_land.py``'s pattern.

One shared workspace threads the whole lifecycle in :func:`test_full_lifecycle`:
plan-save → implement (dry-run) → submit → land → learn capture → learn docs → docs-plan land
(consumed-learn), with the objective tier created up front so the node→plan backlink, the
auto-on-merge node-done, and the close-on-complete all run over ``ENG-*`` ids. Focused tests
cover the objective verbs, the supervisor's in-flight resolution over an ``ENG-*`` backlink,
run-report marker idempotency through the transcoder, and tolerance of foreign
(integration-style linkback) comments.
"""

import itertools
import json
import re
import subprocess
import uuid
from pathlib import Path
from typing import cast

import pytest
from click.testing import CliRunner

from perk import github, objective, plan
from perk.backends import resolve
from perk.backends.linear import client as linear_client
from perk.backends.linear.client import LinearClient, LinearGraphQLError
from perk.backends.resolve import resolve_objective_store
from perk.cli.cli import cli
from perk.objective.drift import DriftCode
from perk.run import run_report
from perk.state import cache

_PAGE = 2  # deliberately tiny so the suite exercises the cursor loop on real data

_TEAM_KEY = "ENG"
_TEAM_UUID = "team-uuid-1"

_STATES: list[dict[str, object]] = [
    {"id": "st-todo", "name": "Todo", "type": "unstarted", "position": 0},
    {"id": "st-done", "name": "Done", "type": "completed", "position": 1},
]


def _not_found() -> LinearGraphQLError:
    return LinearGraphQLError(
        "Linear GraphQL error: Entity not found: Issue", codes=("INPUT_ERROR",)
    )


class FakeLinearWorkspace(LinearClient):
    """A stateful in-memory Linear workspace subclassing ``linear.LinearClient``.

    Routes requests by the same query-substring conventions the scripted ``_FakeLinear`` uses,
    but executes against state: create/update/comment/label mutations mutate it; reads paginate
    (page size ``_PAGE`` so the cursor loop runs). Unknown entity ids raise
    ``LinearGraphQLError("… Entity not found", codes=())`` — exercising the backend's documented
    ``"not found"``-substring tolerance. **Mutations accept the identifier OR the UUID** (the
    Mode 2 live finding, 2026-06-15: ``issueUpdate``/``commentCreate`` take the bare ``PER-<n>``
    identifier interchangeably with the UUID, same as the read path), so there is no
    identifier→UUID resolution layer to pin.
    """

    def __init__(self) -> None:
        self.issues: dict[str, dict[str, object]] = {}  # uuid -> issue
        self.labels: dict[str, str] = {}  # name -> uuid
        self.projects: dict[str, dict[str, object]] = {}  # uuid -> project
        self.milestones: dict[str, dict[str, object]] = {}  # uuid -> {id, name, project_id}
        self.relations: list[tuple[str, str]] = []  # (blocker_uuid, blocked_uuid)
        # idempotent-by-URL attachments: (issue_uuid, url) -> {title, subtitle}
        self.attachments: dict[tuple[str, str], dict[str, object]] = {}
        self.requests: list[tuple[str, dict[str, object]]] = []
        self._seq = itertools.count(1)
        self._clock = itertools.count(1)
        # Subclasses LinearClient (no super().__init__) to inherit the shared team_id/paginate
        # machinery driven by this scripted request; init the id caches directly.
        self._team_id_cache: dict[str, str] = {}
        self._viewer_id_cache: str | None = None

    # ------------------------------------------------------------------ state helpers

    def _issue_by_any_id(self, value: str) -> dict[str, object] | None:
        """Reads accept the identifier OR the UUID (the documented `issue(id:)` tolerance)."""
        found = self.issues.get(value)
        if found is not None:
            return found
        for issue in self.issues.values():
            if issue["identifier"] == value:
                return issue
        return None

    def _issue_for_mutation(self, value: str) -> dict[str, object]:
        """Mutations accept the identifier OR the UUID (the Mode 2 live finding) — junk is an
        unknown entity."""
        found = self._issue_by_any_id(value)
        if found is None:
            raise _not_found()
        return found

    def issue_by_identifier(self, identifier: str) -> dict[str, object]:
        found = self._issue_by_any_id(identifier)
        assert found is not None, f"no workspace issue {identifier!r}"
        return found

    def state_type(self, issue: dict[str, object]) -> str:
        state_id = issue["state_id"]
        return str(next(s["type"] for s in _STATES if s["id"] == state_id))

    def label_names(self, issue: dict[str, object]) -> set[str]:
        ids = cast("list[str]", issue["label_ids"])
        return {name for name, label_id in self.labels.items() if label_id in ids}

    def attachments_of(self, issue: dict[str, object]) -> list[dict[str, object]]:
        """Attachment cards on an issue (by its UUID)."""
        return [v for (iid, _url), v in self.attachments.items() if iid == issue["id"]]

    def comments_of(self, issue: dict[str, object]) -> list[dict[str, object]]:
        return cast("list[dict[str, object]]", issue["comments"])

    def add_foreign_comment(self, identifier: str, body: str) -> None:
        """Simulate a Linear GitHub-integration linkback comment (a foreign writer)."""
        issue = self.issue_by_identifier(identifier)
        self.comments_of(issue).append(
            {"id": f"cmt-{uuid.uuid4().hex[:8]}", "body": body, "createdAt": self._now()}
        )

    def _now(self) -> str:
        return f"2026-06-12T00:00:{next(self._clock):02d}Z"

    def _create_issue(self, payload: dict[str, object]) -> dict[str, object]:
        number = next(self._seq)
        identifier = f"{_TEAM_KEY}-{number}"
        issue: dict[str, object] = {
            "id": f"iss-{uuid.uuid4().hex[:8]}",
            "identifier": identifier,
            "url": f"https://linear.app/test/issue/{identifier}",
            "title": payload.get("title", ""),
            "description": payload.get("description", ""),
            "state_id": "st-todo",
            "label_ids": list(cast("list[str]", payload.get("labelIds", []))),
            # Every perk-created issue is assigned to the API-key user (the viewer).
            "assignee_id": payload.get("assigneeId"),
            # node-issues (project-backed objectives) carry a projectId; plan/learn issues None.
            "project_id": payload.get("projectId"),
            "milestone_id": payload.get("projectMilestoneId"),
            "comments": [],
        }
        self.issues[str(issue["id"])] = issue
        return issue

    # ------------------------------------------------------------------ project helpers

    def project_by_id(self, project_id: str) -> dict[str, object]:
        found = self.projects.get(project_id)
        assert found is not None, f"no workspace project {project_id!r}"
        return found

    def project_state(self, project_id: str) -> str:
        return str(self.project_by_id(project_id)["state"])

    def _milestone_node_of(self, issue: dict[str, object]) -> dict[str, object] | None:
        mid = issue.get("milestone_id")
        if mid is None:
            return None
        milestone = self.milestones.get(str(mid))
        return None if milestone is None else {"id": milestone["id"], "name": milestone["name"]}

    def _project_issue_node(
        self, issue: dict[str, object], *, with_milestone: bool = False
    ) -> dict[str, object]:
        node: dict[str, object] = {
            "id": issue["id"],
            "identifier": issue["identifier"],
            "url": issue["url"],
            "description": issue["description"],
        }
        if with_milestone:
            node["projectMilestone"] = self._milestone_node_of(issue)
        return node

    # ------------------------------------------------------------------ wire shapes

    def _page_of(self, nodes: list[dict[str, object]], cursor: object) -> dict[str, object]:
        start = int(str(cursor)) if isinstance(cursor, str) and cursor else 0
        chunk = nodes[start : start + _PAGE]
        has_next = start + _PAGE < len(nodes)
        return {
            "nodes": chunk,
            "pageInfo": {"hasNextPage": has_next, "endCursor": str(start + _PAGE)},
        }

    def _issue_node(self, issue: dict[str, object]) -> dict[str, object]:
        """Every field any production selection reads (extra keys are harmless)."""
        return {
            "id": issue["id"],
            "identifier": issue["identifier"],
            "url": issue["url"],
            "title": issue["title"],
            "description": issue["description"],
            "state": {"type": self.state_type(issue)},
            "labels": {"nodes": [{"id": i} for i in cast("list[str]", issue["label_ids"])]},
        }

    # ------------------------------------------------------------------ the client seam

    def request(self, query: str, variables: dict[str, object] | None = None) -> dict[str, object]:
        v = variables or {}
        self.requests.append((query, v))
        if "viewer" in query:
            return {"viewer": {"id": "u1", "name": "Fake User", "email": "f@x.io"}}
        if "teams(filter" in query:
            if v.get("key") == _TEAM_KEY:
                return {"teams": {"nodes": [{"id": _TEAM_UUID}]}}
            return {"teams": {"nodes": []}}
        if "projects(first" in query:  # team's project list (find_objective scan) — before team(id
            assert v.get("teamId") == _TEAM_UUID
            nodes = [
                {"id": p["id"], "url": p["url"], "content": p["content"]}
                for p in self.projects.values()
            ]
            return {"team": {"projects": self._page_of(nodes, v.get("cursor"))}}
        if "team(id" in query:
            assert v.get("teamId") == _TEAM_UUID
            return {"team": {"states": {"nodes": list(_STATES)}}}
        if "project(id" in query:  # project reads — before the generic issues(first/issue(id arms
            project = self.projects.get(str(v.get("id", "")))
            if project is None:
                raise _not_found()
            if "issues(first" in query:
                with_milestone = "projectMilestone" in query
                nodes = [
                    self._project_issue_node(issue, with_milestone=with_milestone)
                    for issue in self.issues.values()
                    if issue.get("project_id") == project["id"]
                ]
                return {"project": {"issues": self._page_of(nodes, v.get("cursor"))}}
            if "projectMilestones" in query:
                nodes = [
                    {"id": m["id"], "name": m["name"]}
                    for m in self.milestones.values()
                    if m["project_id"] == project["id"]
                ]
                return {"project": {"projectMilestones": self._page_of(nodes, v.get("cursor"))}}
            return {
                "project": {
                    "id": project["id"],
                    "url": project["url"],
                    "name": project["name"],
                    "content": project["content"],
                }
            }
        if "issueLabels(filter" in query:
            label_id = self.labels.get(str(v.get("name")))
            return {"issueLabels": {"nodes": [{"id": label_id}] if label_id else []}}
        if "issueLabelCreate(" in query:
            payload = cast("dict[str, object]", v["input"])
            name = str(payload["name"])
            if name in self.labels:
                raise LinearGraphQLError("Linear GraphQL error: duplicate label name", codes=())
            label_id = f"lbl-{uuid.uuid4().hex[:8]}"
            self.labels[name] = label_id
            return {"issueLabelCreate": {"success": True, "issueLabel": {"id": label_id}}}
        if "issues(first" in query:
            assert v.get("teamId") == _TEAM_UUID
            label_id = self.labels.get(str(v.get("label")))
            nodes = [
                self._issue_node(issue)
                for issue in self.issues.values()
                if label_id is not None
                and label_id in cast("list[str]", issue["label_ids"])
                and self.state_type(issue) not in ("completed", "canceled")
            ]
            return {"issues": self._page_of(nodes, v.get("cursor"))}
        if "comments(first" in query:  # before the generic issue(id arm — same prefix
            issue = self._issue_by_any_id(str(v.get("id", "")))
            if issue is None:
                raise _not_found()
            return {"issue": {"comments": self._page_of(self.comments_of(issue), v.get("cursor"))}}
        if "comment(id" in query:
            for issue in self.issues.values():
                for comment in self.comments_of(issue):
                    if comment["id"] == v.get("id"):
                        return {"comment": {"body": comment["body"]}}
            raise _not_found()
        if "inverseRelations(" in query:  # blockers of this issue (depends_on sources)
            issue = self._issue_by_any_id(str(v.get("id", "")))
            if issue is None:
                raise _not_found()
            blockers: list[dict[str, object]] = [
                {"type": "blocks", "issue": {"identifier": self.issues[bk]["identifier"]}}
                for bk, bl in self.relations
                if bl == issue["id"]
            ]
            return {"issue": {"inverseRelations": self._page_of(blockers, v.get("cursor"))}}
        if "relations(" in query:  # issues this one blocks
            issue = self._issue_by_any_id(str(v.get("id", "")))
            if issue is None:
                raise _not_found()
            blocked: list[dict[str, object]] = [
                {"type": "blocks", "relatedIssue": {"identifier": self.issues[bl]["identifier"]}}
                for bk, bl in self.relations
                if bk == issue["id"]
            ]
            return {"issue": {"relations": self._page_of(blocked, v.get("cursor"))}}
        if "issue(id" in query:
            issue = self._issue_by_any_id(str(v.get("id", "")))
            if issue is None:
                raise _not_found()
            return {"issue": self._issue_node(issue)}
        if "issueCreate(" in query:
            payload = cast("dict[str, object]", v["input"])
            assert payload.get("teamId") == _TEAM_UUID
            issue = self._create_issue(payload)
            return {
                "issueCreate": {
                    "success": True,
                    "issue": {
                        "id": issue["id"],
                        "identifier": issue["identifier"],
                        "url": issue["url"],
                    },
                }
            }
        if "issueUpdate(" in query:
            issue = self._issue_for_mutation(str(v.get("id", "")))
            payload = cast("dict[str, object]", v["input"])
            if "title" in payload:
                issue["title"] = payload["title"]
            if "description" in payload:
                issue["description"] = payload["description"]
            if "labelIds" in payload:
                issue["label_ids"] = list(cast("list[str]", payload["labelIds"]))
            if "stateId" in payload:
                issue["state_id"] = payload["stateId"]
            if "projectMilestoneId" in payload:
                issue["milestone_id"] = payload["projectMilestoneId"]
            return {"issueUpdate": {"success": True}}
        if "commentCreate(" in query:
            payload = cast("dict[str, object]", v["input"])
            issue = self._issue_for_mutation(str(payload.get("issueId", "")))
            comment = {
                "id": f"cmt-{uuid.uuid4().hex[:8]}",
                "body": payload["body"],
                "createdAt": self._now(),
            }
            self.comments_of(issue).append(comment)
            return {"commentCreate": {"success": True, "comment": {"id": comment["id"]}}}
        if "commentUpdate(" in query:
            for issue in self.issues.values():
                for comment in self.comments_of(issue):
                    if comment["id"] == v.get("id"):
                        payload = cast("dict[str, object]", v["input"])
                        comment["body"] = payload["body"]
                        return {"commentUpdate": {"success": True}}
            raise _not_found()
        if "projectCreate(" in query:
            payload = cast("dict[str, object]", v["input"])
            assert payload.get("teamIds") == [_TEAM_UUID]
            pid = f"proj-{uuid.uuid4().hex[:8]}"
            project: dict[str, object] = {
                "id": pid,
                "url": f"https://linear.app/test/project/{pid}",
                "name": payload.get("name", ""),
                "content": payload.get("content", ""),
                # Default "planned": create sets no live state; the started nudge moves it on work.
                "state": "planned",
                "lead_id": payload.get("leadId"),
                "start_date": payload.get("startDate"),
            }
            self.projects[pid] = project
            return {
                "projectCreate": {
                    "success": True,
                    "project": {"id": pid, "url": project["url"]},
                }
            }
        if "projectUpdate(" in query:
            project = self.project_by_id(str(v.get("id", "")))
            payload = cast("dict[str, object]", v["input"])
            if "content" in payload:
                project["content"] = payload["content"]
            if "state" in payload:
                project["state"] = payload["state"]
            return {"projectUpdate": {"success": True}}
        if "projectMilestoneCreate(" in query:
            payload = cast("dict[str, object]", v["input"])
            mid = f"ms-{uuid.uuid4().hex[:8]}"
            self.milestones[mid] = {
                "id": mid,
                "name": payload.get("name", ""),
                "project_id": payload.get("projectId"),
            }
            return {
                "projectMilestoneCreate": {
                    "success": True,
                    "projectMilestone": {"id": mid, "name": payload.get("name", "")},
                }
            }
        if "attachmentCreate(" in query:
            payload = cast("dict[str, object]", v["input"])
            issue = self._issue_for_mutation(str(payload.get("issueId", "")))
            key = (str(issue["id"]), str(payload["url"]))  # idempotent by (issue, url)
            self.attachments[key] = {
                "title": payload.get("title"),
                "subtitle": payload.get("subtitle"),
            }
            return {"attachmentCreate": {"success": True}}
        if "issueRelationCreate(" in query:
            payload = cast("dict[str, object]", v["input"])
            blocker = str(payload["issueId"])
            blocked = str(payload["relatedIssueId"])
            # ids are issue UUIDs captured at issue-create time (issueRelationCreate is UUID-only)
            assert blocker in self.issues and blocked in self.issues
            rid = f"rel-{uuid.uuid4().hex[:8]}"
            self.relations.append((blocker, blocked))
            return {
                "issueRelationCreate": {
                    "success": True,
                    "issueRelation": {"id": rid, "type": "blocks"},
                }
            }
        raise AssertionError(f"unrouted Linear query: {query}")


# --------------------------------------------------------------------------- harness


def _scaffold_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    pi = root / ".pi"
    pi.mkdir()
    (pi / "perk.toml").write_text(
        f'[issues]\nbackend = "linear"\nteam = "{_TEAM_KEY}"\n', encoding="utf-8"
    )


def _patch_linear(monkeypatch: pytest.MonkeyPatch, ws: FakeLinearWorkspace) -> None:
    # Late-bound: resolve_issue_backend calls linear_client.client_from_env(repo_root=...) at call
    # time.
    monkeypatch.setattr(linear_client, "client_from_env", lambda *a, **k: ws)
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _pr(*, number: int = 51, state: str = "OPEN", draft: bool = False) -> github.PullRequest:
    return github.PullRequest(
        number=number, url=f"u/pr/{number}", is_draft=draft, state=state, existed=True
    )


def _patch_pr_tier_for_submit(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """The GitHub PR-tier fakes (the test_pr_land/test_pr_submit pattern): push/PR open."""
    calls: dict[str, object] = {"pushed": None, "pr_body": None}
    monkeypatch.setattr("perk.substrate.git.is_dirty", lambda root: False)

    def _push(root, branch, *, force=False):
        calls["pushed"] = branch

    monkeypatch.setattr("perk.substrate.git.push", _push)
    monkeypatch.setattr(github, "default_branch", lambda root: "main")
    monkeypatch.setattr(github, "create_pr", lambda **k: _pr(draft=True))

    def _update_body(*, number, body, repo_root):
        calls["pr_body"] = body

    monkeypatch.setattr(github, "update_pr_body", _update_body)
    monkeypatch.setattr(github, "get_pr", lambda **k: _pr(draft=True))
    return calls


def _patch_pr_tier_for_land(
    monkeypatch: pytest.MonkeyPatch, *, draft: bool = True, merged: bool = False
) -> dict[str, object]:
    calls: dict[str, object] = {"readied": False, "merged": False, "commit_message": None}
    monkeypatch.setattr(
        github,
        "find_pr_for_branch",
        lambda **k: _pr(draft=draft, state="MERGED" if merged else "OPEN"),
    )

    def _ready(**k):
        calls["readied"] = True

    def _merge(**k):
        calls["merged"] = True
        calls["commit_message"] = k.get("commit_message")
        return _pr(state="MERGED")

    monkeypatch.setattr(github, "mark_pr_ready", _ready)
    monkeypatch.setattr(github, "merge_pr", _merge)
    return calls


_PLAN_MD = "# My linear plan\n\nSome prose.\n\n## Steps\n\n1. Do the thing\n"


def _invoke(runner: CliRunner, args: list[str]) -> dict[str, object]:
    result = runner.invoke(cli, args)
    assert result.exit_code == 0, f"{args}: {result.output}"
    return cast("dict[str, object]", json.loads(result.stdout))


# --------------------------------------------------------------------------- the lifecycle


def test_full_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)

        # --- objective create: the two-step create with comment-id backfill -----------------
        (root / "obj.md").write_text("# Big objective\n\nThe why.\n", encoding="utf-8")
        roadmap = json.dumps([{"id": "1.1", "description": "Node one"}])
        payload = _invoke(
            runner,
            [
                "objective",
                "create",
                "--json",
                "--body",
                "obj.md",
                "--roadmap",
                roadmap,
                "--run-id",
                "01OBJRUN",
            ],
        )
        objective_payload = cast("dict[str, object]", payload["objective"])
        obj_id = str(objective_payload["id"])
        # The objective is a Linear PROJECT — its id is the opaque Project UUID, never an
        # ENG-* issue identifier; the roadmap is materialized as node-issues (1.1 → ENG-1).
        assert obj_id in ws.projects
        project = ws.project_by_id(obj_id)
        # Linear-safe storage: no HTML comments / <details> in the overview content.
        overview = str(project["content"])
        assert "<!--" not in overview and "<details>" not in overview
        header = plan.find_metadata_block(overview, "objective-header")
        assert header is not None and header["run_id"] == "01OBJRUN"
        assert "roadmap-table" not in overview  # roadmap is node-issues, not an overview table
        node_issue = ws.issue_by_identifier("ENG-1")  # the single node 1.1 → node-issue ENG-1
        # node-issues carry the workspace `perk:objective-node` label (additive filterability)
        assert ws.label_names(node_issue) == {objective.OBJECTIVE_NODE_LABEL}
        assert str(node_issue["assignee_id"]) == "u1"  # assigned to the API-key user (viewer)
        assert (
            plan.find_metadata_block(str(node_issue["description"]), "objective-node") is not None
        )
        # the project has the API-key user as lead and a startDate (Linear's graph prerequisite)
        assert project["lead_id"] == "u1"
        assert isinstance(project["start_date"], str) and project["start_date"]

        # --- plan-save: create + node link ---------------------------------------------------
        (root / "plan.md").write_text(_PLAN_MD, encoding="utf-8")
        payload = _invoke(
            runner,
            [
                "plan",
                "save",
                "--plan-file",
                "plan.md",
                "--run-id",
                "01PLANRUN",
                "--objective-id",
                obj_id,
                "--node-id",
                "1.1",
                "--json",
            ],
        )
        issue_payload = cast("dict[str, object]", payload["issue"])
        # Node/plan unification writes the plan INTO the node-issue — no second perk:plan issue.
        assert issue_payload["id"] == "ENG-1"
        ref = cast("dict[str, object]", payload["plan_ref"])
        assert ref["provider"] == "linear" and ref["pr_id"] == "ENG-1"
        assert ref["labels"] == []  # the node-issue carries no perk:plan label
        node_link = cast("dict[str, object]", payload["objective_node"])
        assert node_link["linked"] is True and node_link["status"] == "in_progress"
        # exactly one issue exists — the original node-issue (no second plan issue minted)
        assert [str(i["identifier"]) for i in ws.issues.values()] == ["ENG-1"]
        node_issue = ws.issue_by_identifier("ENG-1")
        # the node-issue keeps its `perk:objective-node` label; no `perk:plan` label is added
        # (the node-issue IS the plan under unification)
        assert ws.label_names(node_issue) == {objective.OBJECTIVE_NODE_LABEL}
        desc = str(node_issue["description"])
        assert "<!--" not in desc
        # the plan-header merged into the node-issue description; the objective-node block intact
        assert plan.find_metadata_block(desc, "plan-header") is not None
        assert plan.find_metadata_block(desc, "objective-node") is not None
        # the plan body rides a node-issue comment, transcoded
        [body_comment] = ws.comments_of(node_issue)
        assert "`perk:metadata-block:plan-body`" in str(body_comment["body"])
        assert "<details>" not in str(body_comment["body"])

        # --- re-save (same run_id): existed + comment patched + header merged ---------------
        (root / "plan.md").write_text(_PLAN_MD.replace("Some prose.", "Edited prose."))
        payload = _invoke(
            runner,
            [
                "plan",
                "save",
                "--plan-file",
                "plan.md",
                "--run-id",
                "01PLANRUN",
                "--objective-id",
                obj_id,
                "--node-id",
                "1.1",
                "--json",
            ],
        )
        issue_payload = cast("dict[str, object]", payload["issue"])
        assert issue_payload["id"] == "ENG-1" and issue_payload["existed"] is True
        assert payload["updated"] is True
        node_issue = ws.issue_by_identifier("ENG-1")
        [body_comment] = ws.comments_of(node_issue)  # patched in place, never duplicated
        assert "Edited prose." in str(body_comment["body"])
        plan_header = plan.find_metadata_block(str(node_issue["description"]), "plan-header")
        assert plan_header is not None and plan_header["objective_id"] == obj_id

        # --- implement (dry-run): worktree name derives from the identifier -----------------
        result = runner.invoke(cli, ["implement", "ENG-1", "--dry-run"])
        assert result.exit_code == 0, result.output
        dry = json.loads(result.stdout)
        assert dry["worktree"] == "plan-ENG-1"
        assert dry["plan_ref"]["pr_id"] == "ENG-1"

        # --- submit: header fields merged into the node-issue description -------------------
        submit_calls = _patch_pr_tier_for_submit(monkeypatch)
        payload = _invoke(runner, ["pr", "submit", "--json"])
        assert payload["issue"] == "ENG-1"  # the node-issue IS the plan issue (D2)
        assert submit_calls["pushed"] == "plan-ENG-1"  # the branch-name auto-link shape (D3)
        plan_header = plan.find_metadata_block(
            str(ws.issue_by_identifier("ENG-1")["description"]), "plan-header"
        )
        assert plan_header is not None
        assert plan_header["branch"] == "plan-ENG-1"
        assert plan_header["pr"] == "51"
        assert plan_header["lifecycle_stage"] == "impl"

        # --- land: explicit close + node done + objective close-on-complete -----------------
        land_calls = _patch_pr_tier_for_land(monkeypatch, draft=True)
        payload = _invoke(runner, ["pr", "land", "--json"])
        assert payload["issue"] == "ENG-1"
        # the squash footer branches: non-github → `Plan: <id> — <url>` (NO `Closes #N`). The
        # title is the node-issue's own title (its roadmap identity “1.1: …”), since under the
        # unification model the plan rides the node-issue (whose title is NOT the plan H1).
        plan_url = str(ws.issue_by_identifier("ENG-1")["url"])
        assert land_calls["commit_message"] == f"1.1: Node one\n\nPlan: ENG-1 — {plan_url}"
        # the node-issue was explicitly closed in the workspace (no GitHub autoclose here)
        assert payload["plan_issue_closed"] is True
        assert ws.state_type(ws.issue_by_identifier("ENG-1")) == "completed"
        assert cache.has_marker(root, cache.PENDING_LEARN)
        objective_update = cast("dict[str, object]", payload["objective"])
        assert objective_update["id"] == obj_id
        assert objective_update["nodes_marked"] == ["1.1"]
        assert objective_update["closed"] is True  # single-node roadmap → close-on-complete
        # the objective is a PROJECT: completion marks the Project complete (not an issue close)
        assert ws.project_state(obj_id) == "completed"

        # --- learn capture: learn issue + plan-issue backlink comment -----------------------
        (root / "learn.md").write_text("What we learned.\n", encoding="utf-8")
        payload = _invoke(runner, ["learn", "capture", "--json", "--body", "learn.md"])
        learn_payload = cast("dict[str, object]", payload["learn_issue"])
        # the node-issue absorbed the plan, so learn is ENG-2 (plan_issue is the node ENG-1)
        assert learn_payload["id"] == "ENG-2"
        assert payload["plan_issue"] == "ENG-1"
        assert payload["commented"] is True
        learn_issue = ws.issue_by_identifier("ENG-2")
        assert ws.label_names(learn_issue) == {"perk:learn"}
        learn_header = plan.find_metadata_block(str(learn_issue["description"]), "learn-header")
        assert learn_header is not None and learn_header["plan"] == "ENG-1"
        backlinks = [
            c for c in ws.comments_of(ws.issue_by_identifier("ENG-1")) if "ENG-2" in str(c["body"])
        ]
        assert len(backlinks) == 1
        assert not cache.has_marker(root, cache.PENDING_LEARN)

        # --- learn docs --gather: string ids in the envelope ---------------------------------
        payload = _invoke(runner, ["learn", "docs", "--gather", "--json"])
        assert payload["learn_numbers"] == ["ENG-2"]
        inbox = Path(str(payload["inbox_path"])).read_text(encoding="utf-8")
        assert "What we learned." in inbox

        # --- docs plan: consumed_learn string round-trip → consumed on land -----------------
        (root / "docs-plan.md").write_text("# Docs plan\n\nConsolidate.\n", encoding="utf-8")
        payload = _invoke(
            runner,
            [
                "plan",
                "save",
                "--plan-file",
                "docs-plan.md",
                "--run-id",
                "01DOCSRUN",
                "--consumed-learn",
                "ENG-2",
                "--json",
            ],
        )
        issue_payload = cast("dict[str, object]", payload["issue"])
        # a STANDALONE (non-objective) plan-save still mints a fresh perk:plan issue — ENG-3.
        assert issue_payload["id"] == "ENG-3"
        ref = cast("dict[str, object]", payload["plan_ref"])
        assert ref["consumed_learn"] == ["ENG-2"]
        assert ws.label_names(ws.issue_by_identifier("ENG-3")) == {"perk:plan"}
        _patch_pr_tier_for_land(monkeypatch, merged=True)  # already merged → idempotent land
        payload = _invoke(runner, ["pr", "land", "--json"])
        learn_update = cast("dict[str, object]", payload["learn"])
        assert learn_update["closed"] == ["ENG-2"] and learn_update["skipped_reason"] is None
        learn_issue = ws.issue_by_identifier("ENG-2")
        assert ws.state_type(learn_issue) == "completed"
        assert ws.label_names(learn_issue) == {"perk:learn", "perk:consolidated"}
        assert ws.state_type(ws.issue_by_identifier("ENG-3")) == "completed"  # explicit close


# --------------------------------------------------------------------------- objective verbs


def _seed_objective(
    runner: CliRunner, root: Path, *, nodes: list[dict[str, object]] | None = None
) -> str:
    (root / "obj.md").write_text("# Obj\n\nProse.\n", encoding="utf-8")
    roadmap = json.dumps(nodes or [{"id": "1.1", "description": "Node one"}])
    payload = _invoke(
        runner,
        [
            "objective",
            "create",
            "--json",
            "--body",
            "obj.md",
            "--roadmap",
            roadmap,
            "--run-id",
            "01OBJ",
        ],
    )
    return str(cast("dict[str, object]", payload["objective"])["id"])


def test_objective_verbs_over_linear(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(runner, root)

        # show: string ids in the envelope, identifier-keyed lookup
        payload = _invoke(runner, ["objective", "show", obj_id, "--json"])
        objective_payload = cast("dict[str, object]", payload["objective"])
        assert objective_payload["id"] == obj_id
        next_node = cast("dict[str, object]", payload["next_node"])
        assert next_node["id"] == "1.1"

        # next
        payload = _invoke(runner, ["objective", "next", obj_id, "--json"])
        assert cast("dict[str, object]", payload["next_node"])["id"] == "1.1"

        # node: status update over the Project id (accepts the `#`-prefixed form too); the status
        # lands on the NODE-ISSUE's objective-node block (ENG-1), not the Project overview.
        payload = _invoke(
            runner,
            ["objective", "node", f"#{obj_id}", "--node", "1.1", "--status", "planning", "--json"],
        )
        assert payload["objective"] == obj_id and payload["node"] == "1.1"
        assert "status: planning" in str(ws.issue_by_identifier("ENG-1")["description"])

        # reconcile: the project-OVERVIEW splice (no body comment in the project model)
        (root / "prose.md").write_text("Reconciled prose.\n", encoding="utf-8")
        payload = _invoke(
            runner, ["objective", "reconcile", obj_id, "--json", "--body", "prose.md"]
        )
        assert payload["objective"] == obj_id and payload["updated"] is True
        assert payload["comment_id"] is None  # the overview is project content, not a comment
        assert "Reconciled prose." in str(ws.project_by_id(obj_id)["content"])


def test_objective_run_resolves_in_flight_over_an_eng_backlink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Step-3 supervisor fix: a non-numeric `pr` backlink (the node-issue `#ENG-1`) IS the
    plan id — now self-referential under the node↔plan unification."""
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    monkeypatch.setattr(cache, "list_dispatch_records", lambda root: [])
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(runner, root)
        # save a plan linked to node 1.1 (marks it in_progress with pr "#ENG-2")
        (root / "plan.md").write_text(_PLAN_MD, encoding="utf-8")
        _invoke(
            runner,
            [
                "plan",
                "save",
                "--plan-file",
                "plan.md",
                "--run-id",
                "01PLANRUN",
                "--objective-id",
                obj_id,
                "--node-id",
                "1.1",
                "--json",
            ],
        )
        payload = _invoke(runner, ["objective", "run", obj_id, "--dry-run", "--json"])
        # the ENG backlink resolved to the plan (no PR yet → implement would be dispatched);
        # before the fix every Linear node degraded to plan_required.
        assert payload["action"] == "dispatched"
        assert payload["node"] == "1.1" and payload["stage"] == "implement"


# --------------------------------------------------------------------------- markers + foreigners


def test_run_report_marker_upsert_is_idempotent_through_the_transcoder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        (root / "plan.md").write_text(_PLAN_MD, encoding="utf-8")
        _invoke(
            runner, ["plan", "save", "--plan-file", "plan.md", "--run-id", "01PLANRUN", "--json"]
        )
        run_report.report_started(root, run_id="01RID", stage="implement", plan="ENG-1", environ={})
        run_report.report_terminal(
            root, run_id="01RID", stage="implement", plan="ENG-1", exit_code=0, environ={}
        )
        marker = "`perk:run-report:01RID`"  # the transcoded marker form
        marked = [
            c for c in ws.comments_of(ws.issue_by_identifier("ENG-1")) if marker in str(c["body"])
        ]
        assert len(marked) == 1  # updated in place, never duplicated
        assert "finished" in str(marked[0]["body"])  # the terminal note replaced the started note


def test_foreign_linkback_comment_does_not_perturb_marker_scans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        (root / "plan.md").write_text(_PLAN_MD, encoding="utf-8")
        _invoke(
            runner, ["plan", "save", "--plan-file", "plan.md", "--run-id", "01PLANRUN", "--json"]
        )
        # The Linear GitHub integration posts linkback comments on linked issues; perk's
        # marker-keyed scans must tolerate this foreign writer.
        ws.add_foreign_comment("ENG-1", "Linked to PR mattgiles/perk#51 by the GitHub sync.")
        backend = resolve.resolve_issue_backend(root)
        # get_plan_body still finds the plan-body comment, not the foreign one
        body = backend.get_plan_body(issue_id="ENG-1")
        assert body is not None and "My linear plan" in body
        # a marker upsert posts fresh, then patches ITS OWN comment (the foreign one untouched)
        marker = "<!-- perk:run-report:01X -->"
        backend.upsert_marked_comment(issue_id="ENG-1", marker=marker, body=f"{marker}\nstarted")
        backend.upsert_marked_comment(issue_id="ENG-1", marker=marker, body=f"{marker}\ndone")
        comments = ws.comments_of(ws.issue_by_identifier("ENG-1"))
        marked = [c for c in comments if "`perk:run-report:01X`" in str(c["body"])]
        assert len(marked) == 1 and "done" in str(marked[0]["body"])
        foreign = [c for c in comments if "GitHub sync" in str(c["body"])]
        assert len(foreign) == 1 and "done" not in str(foreign[0]["body"])


# ----------------------------------------------------------------------- manifest + drift


def _manifest_of(ws: FakeLinearWorkspace, obj_id: str) -> objective.Manifest | None:
    manifest, _errors = objective.parse_manifest(str(ws.project_by_id(obj_id)["content"]))
    return manifest


def _project_store(root: Path):
    store = resolve_objective_store(root)
    return store


def test_objective_create_writes_manifest_block(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(
            runner,
            root,
            nodes=[
                {"id": "1.1", "description": "Node one"},
                {"id": "1.2", "description": "Node two", "depends_on": ["1.1"]},
            ],
        )
        manifest = _manifest_of(ws, obj_id)
        assert manifest is not None
        assert [n.id for n in manifest.nodes] == ["1.1", "1.2"]
        # structural identity only — no status/pr persisted, the depends_on edge IS captured
        assert manifest.nodes[1].depends_on == ("1.1",)
        assert "1" in manifest.phase_names  # the phase pin is present


def test_add_node_syncs_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(runner, root)
        _invoke(
            runner,
            [
                "objective",
                "node-add",
                obj_id,
                "--phase",
                "1",
                "--description",
                "Node two",
                "--json",
            ],
        )
        manifest = _manifest_of(ws, obj_id)
        assert manifest is not None
        assert [n.id for n in manifest.nodes] == ["1.1", "1.2"]
        assert manifest.nodes[1].description == "Node two"


def test_update_node_description_syncs_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(runner, root)
        store = _project_store(root)
        store.update_objective_node(
            objective_id=obj_id, node_id="1.1", description="Reworded node one"
        )
        manifest = _manifest_of(ws, obj_id)
        assert manifest is not None
        assert manifest.nodes[0].description == "Reworded node one"
        # a status-only change does NOT touch the manifest description
        store.update_objective_node(
            objective_id=obj_id, node_id="1.1", status=objective.NodeStatus.DONE
        )
        manifest = _manifest_of(ws, obj_id)
        assert manifest is not None and manifest.nodes[0].description == "Reworded node one"


def test_reconcile_refreshes_manifest_phase_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(runner, root)
        store = _project_store(root)
        store.update_objective_body(
            objective_id=obj_id, prose="### Phase 1: Foundations\n\nReconciled."
        )
        manifest = _manifest_of(ws, obj_id)
        assert manifest is not None
        assert manifest.phase_names["1"] == "Foundations"


def test_detect_and_repair_missing_node_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(
            runner,
            root,
            nodes=[
                {"id": "1.1", "description": "Node one"},
                {"id": "1.2", "description": "Node two", "depends_on": ["1.1"]},
            ],
        )
        store = _project_store(root)
        _delete_node_issue(ws, "1.2")  # drift: node-issue 1.2 vanished from the live project

        report = store.detect_objective_drift(objective_id=obj_id)
        codes = [c.code for c in report.conditions]
        assert DriftCode.MISSING_NODE_ISSUE in codes

        result = store.repair_objective_drift(objective_id=obj_id)
        assert result.aborted is False and result.failed is None
        assert any(a.code == DriftCode.MISSING_NODE_ISSUE for a in result.applied)
        # the node-issue is back and its manifest blocking relation restored
        assert store.detect_objective_drift(objective_id=obj_id).conditions == ()


def test_repair_backfills_absent_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(runner, root)
        store = _project_store(root)
        # strip the manifest block (simulate a pre-manifest objective)
        project = ws.project_by_id(obj_id)
        stripped = re.sub(
            r"`perk:metadata-block:objective-manifest`.*?`/perk:metadata-block:objective-manifest`",
            "",
            str(project["content"]),
            flags=re.DOTALL,
        )
        project["content"] = stripped
        assert _manifest_of(ws, obj_id) is None

        report = store.detect_objective_drift(objective_id=obj_id)
        assert [c.code for c in report.conditions] == [DriftCode.MANIFEST_ABSENT]
        result = store.repair_objective_drift(objective_id=obj_id)
        assert result.aborted is False
        assert _manifest_of(ws, obj_id) is not None
        assert store.detect_objective_drift(objective_id=obj_id).conditions == ()


def test_repair_deleted_phase_milestone(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(runner, root)
        store = _project_store(root)
        # delete every milestone of the project (drift)
        ws.milestones.clear()
        report = store.detect_objective_drift(objective_id=obj_id)
        assert DriftCode.DELETED_PHASE_MILESTONE in [c.code for c in report.conditions]
        result = store.repair_objective_drift(objective_id=obj_id)
        assert result.aborted is False
        assert store.detect_objective_drift(objective_id=obj_id).conditions == ()


def test_dry_run_repair_plans_without_writing(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(runner, root)
        store = _project_store(root)
        ws.milestones.clear()
        result = store.repair_objective_drift(objective_id=obj_id, dry_run=True)
        assert result.dry_run is True
        assert any(a.code == DriftCode.DELETED_PHASE_MILESTONE for a in result.applied)
        # nothing written — the drift is still present
        assert ws.milestones == {}
        assert DriftCode.DELETED_PHASE_MILESTONE in [
            c.code for c in store.detect_objective_drift(objective_id=obj_id).conditions
        ]


def test_doctor_reports_clean_objective(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(runner, root)
        payload = _invoke(runner, ["objective", "doctor", obj_id, "--json"])
        assert payload["success"] is True
        assert payload["drift"] == []
        assert payload["fix"] is None


def test_doctor_detects_and_fixes_deleted_milestone(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(runner, root)
        ws.milestones.clear()  # drift: the phase milestone vanished

        payload = _invoke(runner, ["objective", "doctor", obj_id, "--json"])
        codes = [c["code"] for c in cast("list[dict[str, object]]", payload["drift"])]
        assert DriftCode.DELETED_PHASE_MILESTONE.value in codes
        assert payload["fix"] is None

        payload = _invoke(runner, ["objective", "doctor", obj_id, "--fix", "--json"])
        fix = cast("dict[str, object]", payload["fix"])
        assert fix["aborted"] is False and fix["failed"] is None
        applied = [a["code"] for a in cast("list[dict[str, object]]", fix["applied"])]
        assert DriftCode.DELETED_PHASE_MILESTONE.value in applied
        assert fix["remaining"] == []

        # idempotent: a re-run is clean
        payload = _invoke(runner, ["objective", "doctor", obj_id, "--json"])
        assert payload["drift"] == []


def test_doctor_fix_dry_run_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(runner, root)
        ws.milestones.clear()
        payload = _invoke(runner, ["objective", "doctor", obj_id, "--fix", "--dry-run", "--json"])
        fix = cast("dict[str, object]", payload["fix"])
        assert fix["dry_run"] is True
        applied = [a["code"] for a in cast("list[dict[str, object]]", fix["applied"])]
        assert DriftCode.DELETED_PHASE_MILESTONE.value in applied
        assert ws.milestones == {}  # nothing written


def test_repair_recreates_both_missing_nodes_and_their_edge_in_one_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Both endpoints of a manifest dependency edge are missing — detection raises no separate
    # DEPENDENCY_MISSING action for them, so the recreate path owns the edge. The deferred edge
    # sweep must restore it in a SINGLE --fix pass (no remaining drift).
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(
            runner,
            root,
            nodes=[
                {"id": "1.1", "description": "Node one"},
                {"id": "1.2", "description": "Node two", "depends_on": ["1.1"]},
            ],
        )
        store = _project_store(root)
        for node in ("1.1", "1.2"):
            _delete_node_issue(ws, node)

        result = store.repair_objective_drift(objective_id=obj_id)
        assert result.aborted is False and result.failed is None
        # one pass fully converges — both node-issues AND the 1.1→1.2 relation are restored
        assert store.detect_objective_drift(objective_id=obj_id).conditions == ()


def test_add_node_uses_manifest_pin_not_externally_edited_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The manifest is the phase-name authority for an EXISTING phase: an external overview edit
    # must not make node-add attach to a different/new milestone.
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(runner, root)  # phase 1 pinned to the default "Phase 1"
        # an external editor rewrites the phase header in the overview prose (manifest unchanged)
        project = ws.project_by_id(obj_id)
        project["content"] = str(project["content"]).replace(
            "Prose.", "### Phase 1: Externally Renamed\n\nProse."
        )
        milestones_before = {m["name"] for m in ws.milestones.values()}

        add_args = ["objective", "node-add", obj_id, "--phase", "1"]
        _invoke(runner, [*add_args, "--description", "Node two", "--json"])
        # no "Externally Renamed" milestone was minted — the node attached to the pinned one
        assert "Externally Renamed" not in {m["name"] for m in ws.milestones.values()}
        assert {m["name"] for m in ws.milestones.values()} == milestones_before
        manifest = _manifest_of(ws, obj_id)
        assert manifest is not None and manifest.phase_names["1"] == "Phase 1"


def test_reconcile_reverts_pin_to_default_when_header_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The overview is the authority on a reconcile — removing a custom header reverts the pin to
    # the default (never preserving a now-stale custom name).
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(runner, root)
        store = _project_store(root)
        store.update_objective_body(
            objective_id=obj_id, prose="### Phase 1: Foundations\n\nReconciled."
        )
        custom = _manifest_of(ws, obj_id)
        assert custom is not None and custom.phase_names["1"] == "Foundations"
        # a later reconcile drops the header — the pin reverts to the default
        store.update_objective_body(objective_id=obj_id, prose="Reconciled again, no header.")
        reverted = _manifest_of(ws, obj_id)
        assert reverted is not None and reverted.phase_names["1"] == "Phase 1"


def _delete_node_issue(ws: FakeLinearWorkspace, node_id: str) -> None:
    def _is(iss: dict[str, object]) -> bool:
        block = plan.find_metadata_block(str(iss["description"]), objective.OBJECTIVE_NODE_KEY)
        return block is not None and block.get("id") == node_id

    victim = next(iid for iid, iss in ws.issues.items() if _is(iss))
    del ws.issues[victim]
    # Linear cascade-deletes the issue's relations when the issue is removed.
    ws.relations[:] = [(bk, bl) for bk, bl in ws.relations if victim not in (bk, bl)]


def test_repair_restores_existing_dependent_edge_to_a_recreated_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The reviewer's edge: node 1.1 is missing, EXISTING node 1.2 depends on 1.1. Detection raises
    # only MISSING_NODE_ISSUE(1.1) (it cannot diff a dep to an absent endpoint), so the recreate
    # sweep must restore the dependent's 1.1→1.2 edge in ONE pass.
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(
            runner,
            root,
            nodes=[
                {"id": "1.1", "description": "Node one"},
                {"id": "1.2", "description": "Node two", "depends_on": ["1.1"]},
            ],
        )
        store = _project_store(root)
        _delete_node_issue(ws, "1.1")  # 1.2 survives but its blocker (1.1) is gone

        report = store.detect_objective_drift(objective_id=obj_id)
        assert [c.code for c in report.conditions] == [DriftCode.MISSING_NODE_ISSUE]

        result = store.repair_objective_drift(objective_id=obj_id)
        assert result.aborted is False and result.failed is None
        # one pass restores both the node-issue AND the existing dependent's edge to it
        assert store.detect_objective_drift(objective_id=obj_id).conditions == ()


def test_repair_creates_a_missing_blocking_relation_between_observed_nodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The explicit DEPENDENCY_MISSING_IN_LINEAR repair path (both endpoints observed): the manifest
    # declares 1.2 depends on 1.1, both node-issues exist, but the blocking relation was removed.
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        obj_id = _seed_objective(
            runner,
            root,
            nodes=[
                {"id": "1.1", "description": "Node one"},
                {"id": "1.2", "description": "Node two", "depends_on": ["1.1"]},
            ],
        )
        store = _project_store(root)
        ws.relations.clear()  # both node-issues survive; only the blocking relation is gone

        report = store.detect_objective_drift(objective_id=obj_id)
        assert DriftCode.DEPENDENCY_MISSING_IN_LINEAR in [c.code for c in report.conditions]

        result = store.repair_objective_drift(objective_id=obj_id)
        assert result.aborted is False and result.failed is None
        assert any(a.code == DriftCode.DEPENDENCY_MISSING_IN_LINEAR for a in result.applied)
        assert store.detect_objective_drift(objective_id=obj_id).conditions == ()
