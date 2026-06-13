"""Objective #252 Node 4.1 — the end-to-end offline Linear lifecycle suite.

A stateful in-memory Linear workspace (``FakeLinearWorkspace``) satisfies the GraphQL client seam
(``linear_backend.GraphQLClient``) and is injected via a late-bound
``monkeypatch.setattr(linear, "client_from_env", …)`` — ``resolve_issue_backend`` resolves the
client at call time, so the REAL ``LinearIssueBackend`` (identifier boundary ids, transcoded
bodies, ``_uuid_for`` mutation resolution) is exercised by the REAL CLI commands. Only the
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
import subprocess
import uuid
from pathlib import Path
from typing import cast

import pytest
from click.testing import CliRunner

from perk import github, plan
from perk.backends import issues, linear
from perk.backends.linear import LinearGraphQLError
from perk.cli.cli import cli
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
    return LinearGraphQLError("Linear GraphQL error: Entity not found", codes=())


class FakeLinearWorkspace:
    """A stateful in-memory Linear workspace satisfying ``linear_backend.GraphQLClient``.

    Routes requests by the same query-substring conventions the scripted ``_FakeLinear`` uses,
    but executes against state: create/update/comment/label mutations mutate it; reads paginate
    (page size ``_PAGE`` so the cursor loop runs). Unknown entity ids raise
    ``LinearGraphQLError("… Entity not found", codes=())`` — exercising the backend's documented
    ``"not found"``-substring tolerance. **Mutation ids must be UUIDs** (reads accept the human
    identifier interchangeably, mirroring the documented ``issue(id:)`` behavior; mutations are
    not documented to — passing an identifier here raises, pinning the ``_uuid_for``
    discipline).
    """

    def __init__(self) -> None:
        self.issues: dict[str, dict[str, object]] = {}  # uuid -> issue
        self.labels: dict[str, str] = {}  # name -> uuid
        self.requests: list[tuple[str, dict[str, object]]] = []
        self._seq = itertools.count(1)
        self._clock = itertools.count(1)

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

    def _issue_by_uuid(self, value: str) -> dict[str, object]:
        """Mutations accept ONLY the UUID — an identifier (or junk) is an unknown entity."""
        found = self.issues.get(value)
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
            "comments": [],
        }
        self.issues[str(issue["id"])] = issue
        return issue

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
        if "team(id" in query:
            assert v.get("teamId") == _TEAM_UUID
            return {"team": {"states": {"nodes": list(_STATES)}}}
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
        if "UuidForIssue" in query or "issue(id" in query:
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
            issue = self._issue_by_uuid(str(v.get("id", "")))
            payload = cast("dict[str, object]", v["input"])
            if "title" in payload:
                issue["title"] = payload["title"]
            if "description" in payload:
                issue["description"] = payload["description"]
            if "labelIds" in payload:
                issue["label_ids"] = list(cast("list[str]", payload["labelIds"]))
            if "stateId" in payload:
                issue["state_id"] = payload["stateId"]
            return {"issueUpdate": {"success": True}}
        if "commentCreate(" in query:
            payload = cast("dict[str, object]", v["input"])
            issue = self._issue_by_uuid(str(payload.get("issueId", "")))
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
    # Late-bound: resolve_issue_backend calls linear.client_from_env() at call time.
    monkeypatch.setattr(linear, "client_from_env", lambda: ws)
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
        assert obj_id == "ENG-1"  # the human identifier IS the boundary id (D3)
        obj_issue = ws.issue_by_identifier(obj_id)
        # Linear-safe storage: no HTML comments / <details> in the stored description.
        description = str(obj_issue["description"])
        assert "<!--" not in description and "<details>" not in description
        header = plan.find_metadata_block(description, "objective-header")
        assert header is not None and header["run_id"] == "01OBJRUN"
        # the comment-id backfill landed (the two-step create)
        assert isinstance(header["objective_comment_id"], str)
        assert ws.label_names(obj_issue) == {"perk:objective"}

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
        assert issue_payload["id"] == "ENG-2"  # string identifier in the envelope (D2)
        ref = cast("dict[str, object]", payload["plan_ref"])
        assert ref["provider"] == "linear" and ref["pr_id"] == "ENG-2"
        node_link = cast("dict[str, object]", payload["objective_node"])
        assert node_link["linked"] is True and node_link["status"] == "in_progress"
        plan_issue = ws.issue_by_identifier("ENG-2")
        assert "<!--" not in str(plan_issue["description"])
        assert ws.label_names(plan_issue) == {"perk:plan"}
        # the plan body rides the first comment, transcoded
        [body_comment] = ws.comments_of(plan_issue)
        assert "`perk:metadata-block:plan-body`" in str(body_comment["body"])
        assert "<details>" not in str(body_comment["body"])
        # the node→plan backlink uses the identifier
        obj_description = str(ws.issue_by_identifier(obj_id)["description"])
        assert "#ENG-2" in obj_description

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
        assert issue_payload["id"] == "ENG-2" and issue_payload["existed"] is True
        assert payload["updated"] is True
        plan_issue = ws.issue_by_identifier("ENG-2")
        [body_comment] = ws.comments_of(plan_issue)  # patched in place, never duplicated
        assert "Edited prose." in str(body_comment["body"])
        plan_header = plan.find_metadata_block(str(plan_issue["description"]), "plan-header")
        assert plan_header is not None and plan_header["objective_id"] == obj_id

        # --- implement (dry-run): worktree name derives from the identifier -----------------
        result = runner.invoke(cli, ["implement", "ENG-2", "--dry-run"])
        assert result.exit_code == 0, result.output
        dry = json.loads(result.stdout)
        assert dry["worktree"] == "plan-ENG-2"
        assert dry["plan_ref"]["pr_id"] == "ENG-2"

        # --- submit: header fields merged into the Linear description -----------------------
        submit_calls = _patch_pr_tier_for_submit(monkeypatch)
        payload = _invoke(runner, ["pr", "submit", "--json"])
        assert payload["issue"] == "ENG-2"  # string id at the machine boundary (D2)
        assert submit_calls["pushed"] == "plan-ENG-2"  # the branch-name auto-link shape (D3)
        plan_header = plan.find_metadata_block(
            str(ws.issue_by_identifier("ENG-2")["description"]), "plan-header"
        )
        assert plan_header is not None
        assert plan_header["branch"] == "plan-ENG-2"
        assert plan_header["pr"] == "51"
        assert plan_header["lifecycle_stage"] == "impl"

        # --- land: explicit close + node done + objective close-on-complete -----------------
        land_calls = _patch_pr_tier_for_land(monkeypatch, draft=True)
        payload = _invoke(runner, ["pr", "land", "--json"])
        assert payload["issue"] == "ENG-2"
        # the squash footer branches: non-github → `Plan: <id> — <url>` (NO `Closes #N`)
        plan_url = str(ws.issue_by_identifier("ENG-2")["url"])
        assert land_calls["commit_message"] == f"My linear plan\n\nPlan: ENG-2 — {plan_url}"
        # the plan issue was explicitly closed in the workspace (no GitHub autoclose here)
        assert payload["plan_issue_closed"] is True
        assert ws.state_type(ws.issue_by_identifier("ENG-2")) == "completed"
        assert cache.has_marker(root, cache.PENDING_LEARN)
        objective_update = cast("dict[str, object]", payload["objective"])
        assert objective_update["id"] == obj_id
        assert objective_update["nodes_marked"] == ["1.1"]
        assert objective_update["closed"] is True  # single-node roadmap → close-on-complete
        assert ws.state_type(ws.issue_by_identifier(obj_id)) == "completed"

        # --- learn capture: learn issue + plan-issue backlink comment -----------------------
        (root / "learn.md").write_text("What we learned.\n", encoding="utf-8")
        payload = _invoke(runner, ["learn", "capture", "--json", "--body", "learn.md"])
        learn_payload = cast("dict[str, object]", payload["learn_issue"])
        assert learn_payload["id"] == "ENG-3"
        assert payload["plan_issue"] == "ENG-2"
        assert payload["commented"] is True
        learn_issue = ws.issue_by_identifier("ENG-3")
        assert ws.label_names(learn_issue) == {"perk:learn"}
        learn_header = plan.find_metadata_block(str(learn_issue["description"]), "learn-header")
        assert learn_header is not None and learn_header["plan"] == "ENG-2"
        backlinks = [
            c for c in ws.comments_of(ws.issue_by_identifier("ENG-2")) if "ENG-3" in str(c["body"])
        ]
        assert len(backlinks) == 1
        assert not cache.has_marker(root, cache.PENDING_LEARN)

        # --- learn docs --gather: string ids in the envelope ---------------------------------
        payload = _invoke(runner, ["learn", "docs", "--gather", "--json"])
        assert payload["learn_numbers"] == ["ENG-3"]
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
                "ENG-3",
                "--json",
            ],
        )
        issue_payload = cast("dict[str, object]", payload["issue"])
        assert issue_payload["id"] == "ENG-4"
        ref = cast("dict[str, object]", payload["plan_ref"])
        assert ref["consumed_learn"] == ["ENG-3"]
        _patch_pr_tier_for_land(monkeypatch, merged=True)  # already merged → idempotent land
        payload = _invoke(runner, ["pr", "land", "--json"])
        learn_update = cast("dict[str, object]", payload["learn"])
        assert learn_update["closed"] == ["ENG-3"] and learn_update["skipped_reason"] is None
        learn_issue = ws.issue_by_identifier("ENG-3")
        assert ws.state_type(learn_issue) == "completed"
        assert ws.label_names(learn_issue) == {"perk:learn", "perk:consolidated"}
        assert ws.state_type(ws.issue_by_identifier("ENG-4")) == "completed"  # explicit close


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

        # node: status update over the identifier (accepts the `#`-prefixed form too)
        payload = _invoke(
            runner,
            ["objective", "node", f"#{obj_id}", "--node", "1.1", "--status", "planning", "--json"],
        )
        assert payload["objective"] == obj_id and payload["node"] == "1.1"
        assert "status: planning" in str(ws.issue_by_identifier(obj_id)["description"])

        # reconcile: the body-comment splice; string ids in the envelope
        (root / "prose.md").write_text("Reconciled prose.\n", encoding="utf-8")
        payload = _invoke(
            runner, ["objective", "reconcile", obj_id, "--json", "--body", "prose.md"]
        )
        assert payload["objective"] == obj_id and payload["updated"] is True
        assert isinstance(payload["comment_id"], str)  # comment ids stay UUIDs
        [obj_comment] = ws.comments_of(ws.issue_by_identifier(obj_id))
        assert "Reconciled prose." in str(obj_comment["body"])


def test_objective_run_resolves_in_flight_over_an_eng_backlink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Step-3 supervisor fix: a non-numeric `pr` backlink (`#ENG-2`) IS the plan id."""
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
        backend = issues.resolve_issue_backend(root)
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
