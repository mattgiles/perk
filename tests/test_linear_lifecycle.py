"""The end-to-end offline Linear lifecycle suite.

A stateful in-memory Linear workspace (``FakeLinearWorkspace``, hosted in
``tests/_linear_fakes.py``) subclasses the GraphQL client
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

import json
import subprocess
from pathlib import Path
from typing import cast

import pytest
from _linear_fakes import _TEAM_KEY, FakeLinearWorkspace
from click.testing import CliRunner

from perk import github, objective, plan
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import attachments as linear_attachments
from perk.backends.linear import client as linear_client
from perk.backends.resolve import resolve_objective_store
from perk.cli.cli import cli
from perk.github import prs
from perk.objective.drift import DriftCode
from perk.run import run_report
from perk.state import cache

# --------------------------------------------------------------------------- harness


def _scaffold_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    cfg = root / ".perk"
    cfg.mkdir()
    (cfg / "config.toml").write_text(
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
    # `Delivery.land`'s production GitHub authority delegates to `perk.github.prs`, so the
    # PR-tier stubs target that module (the module-level `perk.github` aliases are unused here).
    calls: dict[str, object] = {"readied": False, "merged": False, "commit_message": None}
    monkeypatch.setattr(
        prs,
        "find_pr_for_branch",
        lambda **k: _pr(draft=draft, state="MERGED" if merged else "OPEN"),
    )

    def _ready(**k):
        calls["readied"] = True

    def _merge(**k):
        calls["merged"] = True
        calls["commit_message"] = k.get("commit_message")
        return _pr(state="MERGED")

    monkeypatch.setattr(prs, "mark_pr_ready", _ready)
    monkeypatch.setattr(prs, "merge_pr", _merge)
    return calls


_PLAN_MD = "# My linear plan\n\nSome prose.\n\n## Steps\n\n1. Do the thing\n"


def _att_payload(
    ws: FakeLinearWorkspace, issue: dict[str, object], kind: str
) -> dict[str, object] | None:
    """The decoded perk attachment payload of ``kind`` on a workspace issue (None when absent)."""
    att = linear_attachments.find_perk_attachment(ws.attachment_nodes_of(issue), kind=kind)
    return None if att is None else att.payload


def _sentinel_issue(ws: FakeLinearWorkspace, obj_id: str) -> dict[str, object]:
    """The project's metadata sentinel issue (carries the objective-header attachment)."""
    for issue in ws.issues.values():
        if issue.get("project_id") == obj_id and _att_payload(
            ws, issue, linear_attachments.OBJECTIVE_HEADER_KIND
        ):
            return issue
    raise AssertionError(f"no metadata sentinel on project {obj_id!r}")


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
        # ENG-* issue identifier; the roadmap is materialized as node-issues (1.1 → ENG-2).
        assert obj_id in ws.projects
        project = ws.project_by_id(obj_id)
        # Linear-safe storage: no HTML comments / <details> in the overview content — AND no
        # metadata blocks at all (the header + manifest ride the sentinel's attachments).
        overview = str(project["content"])
        assert "<!--" not in overview and "<details>" not in overview
        assert "perk:metadata-block" not in overview
        # sentinel: born canceled, empty body, carries the header + manifest attachments
        sentinel = _sentinel_issue(ws, obj_id)
        assert ws.state_type(sentinel) == "canceled"
        assert str(sentinel["description"]) == ""
        header = _att_payload(ws, sentinel, linear_attachments.OBJECTIVE_HEADER_KIND)
        assert header is not None and header["run_id"] == "01OBJRUN"
        assert _att_payload(ws, sentinel, linear_attachments.OBJECTIVE_MANIFEST_KIND) is not None
        # the best-effort Resources link points at the sentinel
        links = cast("list[dict[str, object]]", project.get("external_links", []))
        assert [link["label"] for link in links] == ["Perk metadata"]
        assert "roadmap-table" not in overview  # roadmap is node-issues, not an overview table
        node_issue = ws.issue_by_identifier("ENG-2")  # the single node 1.1 → node-issue ENG-2
        # node-issues carry the workspace `perk:objective-node` label (additive filterability)
        assert ws.label_names(node_issue) == {objective.OBJECTIVE_NODE_LABEL}
        assert str(node_issue["assignee_id"]) == "u1"  # assigned to the API-key user (viewer)
        # the node payload rides an attachment; the description is clean prose
        node_payload = _att_payload(ws, node_issue, linear_attachments.OBJECTIVE_NODE_KIND)
        assert node_payload is not None and node_payload["id"] == "1.1"
        assert "perk:metadata-block" not in str(node_issue["description"])
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
        assert issue_payload["id"] == "ENG-2"
        ref = cast("dict[str, object]", payload["plan_ref"])
        assert ref["provider"] == "linear" and ref["pr_id"] == "ENG-2"
        assert ref["labels"] == []  # the node-issue carries no perk:plan label
        node_link = cast("dict[str, object]", payload["objective_node"])
        assert node_link["linked"] is True and node_link["status"] == "in_progress"
        # no second plan issue was minted — only the sentinel (ENG-1) + the node-issue (ENG-2)
        assert [str(i["identifier"]) for i in ws.issues.values()] == ["ENG-1", "ENG-2"]
        node_issue = ws.issue_by_identifier("ENG-2")
        # the node-issue keeps its `perk:objective-node` label; no `perk:plan` label is added
        # (the node-issue IS the plan under unification)
        assert ws.label_names(node_issue) == {objective.OBJECTIVE_NODE_LABEL}
        desc = str(node_issue["description"])
        assert "<!--" not in desc and "perk:metadata-block" not in desc
        # two-envelope coexistence: the plan-header attachment joins the objective-node one
        assert _att_payload(ws, node_issue, linear_attachments.PLAN_HEADER_KIND) is not None
        assert _att_payload(ws, node_issue, linear_attachments.OBJECTIVE_NODE_KIND) is not None
        # the plan body STILL rides a node-issue comment (a structural sentinel, not metadata)
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
        assert issue_payload["id"] == "ENG-2" and issue_payload["existed"] is True
        assert payload["updated"] is True
        node_issue = ws.issue_by_identifier("ENG-2")
        [body_comment] = ws.comments_of(node_issue)  # patched in place, never duplicated
        assert "Edited prose." in str(body_comment["body"])
        plan_header = _att_payload(ws, node_issue, linear_attachments.PLAN_HEADER_KIND)
        assert plan_header is not None and plan_header["objective_id"] == obj_id
        # in-place upsert: the attachment count stays stable across the re-save
        assert len(ws.attachments_of(node_issue)) == 2

        # --- implement (dry-run): worktree name derives from the identifier -----------------
        result = runner.invoke(cli, ["implement", "ENG-2", "--dry-run"])
        assert result.exit_code == 0, result.output
        dry = json.loads(result.stdout)
        # The unified launch preview reports the resolved worktree PATH; the name still derives
        # from the backend-native identifier.
        assert Path(dry["worktree"]).name == "plan-ENG-2"
        assert dry["plan_ref"]["pr_id"] == "ENG-2"

        # --- submit: header fields merged into the node-issue description -------------------
        submit_calls = _patch_pr_tier_for_submit(monkeypatch)
        payload = _invoke(runner, ["pr", "submit", "--json"])
        assert payload["issue"] == "ENG-2"  # the node-issue IS the plan issue (D2)
        assert submit_calls["pushed"] == "plan-ENG-2"  # the branch-name auto-link shape (D3)
        plan_header = _att_payload(
            ws, ws.issue_by_identifier("ENG-2"), linear_attachments.PLAN_HEADER_KIND
        )
        assert plan_header is not None
        assert plan_header["branch"] == "plan-ENG-2"
        assert plan_header["pr"] == "51"
        assert plan_header["lifecycle_stage"] == "impl"

        # --- land: explicit close + node done + objective close-on-complete -----------------
        land_calls = _patch_pr_tier_for_land(monkeypatch, draft=True)
        payload = _invoke(runner, ["pr", "land", "--json"])
        assert payload["issue"] == "ENG-2"
        # the squash footer branches: non-github → `Plan: <id> — <url>` (NO `Closes #N`). The
        # title is the node-issue's own title (its roadmap identity “1.1: …”), since under the
        # unification model the plan rides the node-issue (whose title is NOT the plan H1).
        plan_url = str(ws.issue_by_identifier("ENG-2")["url"])
        assert land_calls["commit_message"] == f"1.1: Node one\n\nPlan: ENG-2 — {plan_url}"
        # the node-issue was explicitly closed in the workspace (no GitHub autoclose here)
        assert payload["plan_issue_closed"] is True
        assert ws.state_type(ws.issue_by_identifier("ENG-2")) == "completed"
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
        # the node-issue absorbed the plan, so learn is the next mint (plan_issue is the node)
        assert learn_payload["id"] == "ENG-3"
        assert payload["plan_issue"] == "ENG-2"
        assert payload["commented"] is True
        learn_issue = ws.issue_by_identifier("ENG-3")
        assert ws.label_names(learn_issue) == {"perk:learn"}
        # clean body + the learn-header attachment
        assert "perk:metadata-block" not in str(learn_issue["description"])
        assert "What we learned." in str(learn_issue["description"])
        learn_header = _att_payload(ws, learn_issue, linear_attachments.LEARN_HEADER_KIND)
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
        # a STANDALONE (non-objective) plan-save still mints a fresh perk:plan issue — ENG-4.
        assert issue_payload["id"] == "ENG-4"
        ref = cast("dict[str, object]", payload["plan_ref"])
        assert ref["consumed_learn"] == ["ENG-3"]
        assert ws.label_names(ws.issue_by_identifier("ENG-4")) == {"perk:plan"}
        _patch_pr_tier_for_land(monkeypatch, merged=True)  # already merged → idempotent land
        payload = _invoke(runner, ["pr", "land", "--json"])
        learn_update = cast("dict[str, object]", payload["learn"])
        assert learn_update["closed"] == ["ENG-3"] and learn_update["skipped_reason"] is None
        # a learn-docs plan is exempt from the land→learn cycle: the docs land does not re-set
        # the marker (it was cleared by the learn-capture arm above).
        assert payload["pending_learn"] is False
        assert not cache.has_marker(root, cache.PENDING_LEARN)
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

        # node: status update over the Project id (accepts the `#`-prefixed form too); the status
        # lands on the NODE-ISSUE's objective-node block (ENG-2), not the Project overview.
        payload = _invoke(
            runner,
            ["objective", "node", f"#{obj_id}", "--node", "1.1", "--status", "planning", "--json"],
        )
        assert payload["objective"] == obj_id and payload["node"] == "1.1"
        node_payload = _att_payload(
            ws, ws.issue_by_identifier("ENG-2"), linear_attachments.OBJECTIVE_NODE_KIND
        )
        assert node_payload is not None and node_payload["status"] == "planning"

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


# ----------------------------------------------------------------------- supersede


def test_supersede_objective_moves_carried_cancels_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        old_id = _seed_objective(
            runner,
            root,
            nodes=[
                {"id": "1.1", "description": "Done node"},
                {"id": "1.2", "description": "Carried node"},
                {"id": "1.3", "description": "Dropped node"},
            ],
        )
        store = _project_store(root)
        # node 1.1 (ENG-2) is finished history; node 1.2 (ENG-3) carries; node 1.3 (ENG-4) drops.
        store.update_objective_node(
            objective_id=old_id, node_id="1.1", status=objective.NodeStatus.DONE
        )

        new_nodes = [
            objective.ObjectiveNode(
                id="1.1", description="Carried forward", status=objective.NodeStatus.PENDING
            ),
            objective.ObjectiveNode(
                id="1.2", description="Brand new", status=objective.NodeStatus.PENDING
            ),
        ]
        ref = store.supersede_objective(
            old_objective_id=old_id,
            title="Successor objective",
            prose="# Successor\n\nPhases 1 shipped under the old objective.",
            run_id="01NEWOBJ",
            roadmap_nodes=new_nodes,
            carry_map={"1.1": "ENG-3"},  # new node 1.1 carries old node-issue ENG-3
        )
        assert ref is not None and ref.existed is False
        new_id = ref.id

        # the new project's sentinel header carries supersedes=<old>
        new_header = _att_payload(
            ws, _sentinel_issue(ws, new_id), linear_attachments.OBJECTIVE_HEADER_KIND
        )
        assert new_header is not None and new_header["supersedes"] == old_id

        # the carried node-issue (ENG-3) was MOVED into the new project + re-stamped to node 1.1
        # via a SAME-URL upsert (issue-identifier-keyed — no orphaned stale attachment)
        carried = ws.issue_by_identifier("ENG-3")
        assert carried["project_id"] == new_id
        carried_block = _att_payload(ws, carried, linear_attachments.OBJECTIVE_NODE_KIND)
        assert carried_block is not None and carried_block["id"] == "1.1"
        node_atts = [
            n
            for n in ws.attachment_nodes_of(carried)
            if str(n["url"]).startswith("https://perk.invalid/node/")
        ]
        assert len(node_atts) == 1  # upserted in place, never a second node card

        # the new node 1.2 was minted fresh (a new node-issue, still on the new project)
        new_state = store.get_objective(objective_id=new_id)
        assert new_state is not None
        assert sorted(n.id for n in new_state.nodes) == ["1.1", "1.2"]

        # the dropped, still-open node-issue (ENG-4) is Canceled; the done one (ENG-2) untouched
        assert ws.state_type(ws.issue_by_identifier("ENG-4")) == "canceled"
        assert ws.state_type(ws.issue_by_identifier("ENG-2")) == "completed"

        # the old project is completed + back-stamped superseded_by=<new> (on its sentinel)
        assert ws.project_state(old_id) == "completed"
        old_header = _att_payload(
            ws, _sentinel_issue(ws, old_id), linear_attachments.OBJECTIVE_HEADER_KIND
        )
        assert old_header is not None and old_header["superseded_by"] == new_id


def test_supersede_objective_idempotent_on_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        old_id = _seed_objective(runner, root)
        store = _project_store(root)
        new_nodes = [
            objective.ObjectiveNode(id="1.1", description="X", status=objective.NodeStatus.PENDING)
        ]
        first = store.supersede_objective(
            old_objective_id=old_id,
            title="S",
            prose="# S\n\nprose",
            run_id="01NEWOBJ",
            roadmap_nodes=new_nodes,
            carry_map={},
        )
        assert first is not None and first.existed is False
        # a re-run on the same run_id finds the existing successor (no second project)
        before = len(ws.projects)
        again = store.supersede_objective(
            old_objective_id=old_id,
            title="S",
            prose="# S\n\nprose",
            run_id="01NEWOBJ",
            roadmap_nodes=new_nodes,
            carry_map={},
        )
        assert again is not None and again.existed is True and again.id == first.id
        assert len(ws.projects) == before


def _seed_deferred_supersede(runner: CliRunner, root: Path, ws: FakeLinearWorkspace):
    """Seed an objective (nodes 1.1/1.2/1.3 → ENG-2/3/4) and run a DEFERRED-CLOSE supersede
    carrying ENG-3 into new node 1.1 with a dependent fresh node 1.2. Returns
    (store, old_id, new_ref, new_nodes, carry_map)."""
    old_id = _seed_objective(
        runner,
        root,
        nodes=[
            {"id": "1.1", "description": "Done node"},
            {"id": "1.2", "description": "Carried node"},
            {"id": "1.3", "description": "Dropped node"},
        ],
    )
    store = _project_store(root)
    store.update_objective_node(
        objective_id=old_id, node_id="1.1", status=objective.NodeStatus.DONE
    )
    new_nodes = [
        objective.ObjectiveNode(
            id="1.1", description="Carried forward", status=objective.NodeStatus.PENDING
        ),
        objective.ObjectiveNode(
            id="1.2",
            description="Brand new",
            status=objective.NodeStatus.PENDING,
            depends_on=("1.1",),
        ),
    ]
    carry_map = {"1.1": "ENG-3"}
    ref = store.supersede_objective(
        old_objective_id=old_id,
        title="Successor objective",
        prose="# Successor\n\nprose",
        run_id="01NEWOBJ",
        roadmap_nodes=new_nodes,
        carry_map=carry_map,
        close_predecessor=False,
    )
    assert ref is not None
    return store, old_id, ref, new_nodes, carry_map


def test_supersede_deferred_close_leaves_the_old_project_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        store, old_id, ref, _nodes, _carry = _seed_deferred_supersede(runner, root, ws)
        assert ref.existed is False

        # The carried move + fresh mint ran…
        assert ws.issue_by_identifier("ENG-3")["project_id"] == ref.id
        new_state = store.get_objective(objective_id=ref.id)
        assert new_state is not None and sorted(n.id for n in new_state.nodes) == ["1.1", "1.2"]
        # …but NO old-side effect: no stamp, no cancel, project state untouched (§8.53).
        old_header = _att_payload(
            ws, _sentinel_issue(ws, old_id), linear_attachments.OBJECTIVE_HEADER_KIND
        )
        assert old_header is not None and not old_header.get("superseded_by")
        assert ws.project_state(old_id) != "completed"
        assert ws.state_type(ws.issue_by_identifier("ENG-4")) != "canceled"

        # D14 ordering invariant: the sentinel header attachment (the run-id discovery write)
        # precedes the carried node-issue's move into the new project.
        header_url = linear_attachments.objective_header_url("01NEWOBJ")
        carried_uuid = str(ws.issue_by_identifier("ENG-3")["id"])
        header_idx = next(
            i
            for i, (q, v) in enumerate(ws.requests)
            if "attachmentCreate" in q and _input_url(v) == header_url
        )
        move_idx = next(
            i
            for i, (q, v) in enumerate(ws.requests)
            if "issueUpdate" in q
            and v.get("id") in (carried_uuid, "ENG-3")
            and "projectId" in _input_dict(v)
        )
        assert header_idx < move_idx


def _input_dict(variables: dict[str, object]) -> dict[str, object]:
    payload = variables.get("input")
    if not isinstance(payload, dict):
        return {}
    return {str(k): v for k, v in payload.items()}  # the ty-friendly cast-free rebuild


def _input_url(variables: dict[str, object]) -> str | None:
    url = _input_dict(variables).get("url")
    return url if isinstance(url, str) else None


def test_finalize_supersession_cancels_drops_completes_and_converges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        store, old_id, ref, _nodes, _carry = _seed_deferred_supersede(runner, root, ws)

        assert store.finalize_supersession(old_objective_id=old_id, new_objective_id=ref.id)
        old_header = _att_payload(
            ws, _sentinel_issue(ws, old_id), linear_attachments.OBJECTIVE_HEADER_KIND
        )
        assert old_header is not None and old_header["superseded_by"] == ref.id
        assert ws.project_state(old_id) == "completed"
        # The dropped still-open node-issue Canceled; done history untouched.
        assert ws.state_type(ws.issue_by_identifier("ENG-4")) == "canceled"
        assert ws.state_type(ws.issue_by_identifier("ENG-2")) == "completed"

        # Idempotent rerun: no re-stamp conflict, no second completion transition.
        transitions_before = len(_queries_named(ws, "projectUpdateCreate"))
        assert store.finalize_supersession(old_objective_id=old_id, new_objective_id=ref.id)
        assert len(_queries_named(ws, "projectUpdateCreate")) == transitions_before

        # A conflicting stamp refuses.
        with pytest.raises(Exception, match="already superseded"):
            store.finalize_supersession(old_objective_id=old_id, new_objective_id="proj-other")


def test_finalize_supersession_status_update_is_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        store, old_id, ref, _nodes, _carry = _seed_deferred_supersede(runner, root, ws)

        def _fail_update(*, project_id: str, body: str) -> str:
            raise IssueBackendError(f"status feed unavailable for {project_id}: {body[:8]}")

        monkeypatch.setattr(store._projects, "create_project_update", _fail_update)
        assert store.finalize_supersession(old_objective_id=old_id, new_objective_id=ref.id)
        assert ws.project_state(old_id) == "completed"
        old_header = _att_payload(
            ws, _sentinel_issue(ws, old_id), linear_attachments.OBJECTIVE_HEADER_KIND
        )
        assert old_header is not None and old_header["superseded_by"] == ref.id


def _queries_named(ws: FakeLinearWorkspace, needle: str) -> list[tuple[str, dict[str, object]]]:
    return [(q, v) for q, v in ws.requests if needle in q]


def test_supersede_deferred_close_found_arm_converges_partial_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Emulate every interruptible window AFTER the sentinel header attachment (D10) by
    # damaging the successor's subordinate state, then rerun the same-run_id deferred
    # supersede: the found-arm re-materializes exactly what is missing, without duplicates.
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)
        store, old_id, ref, new_nodes, carry_map = _seed_deferred_supersede(runner, root, ws)
        new_id = ref.id

        # Damage: drop the manifest attachment, strip the overview callout, move the carried
        # issue back to the old project, interrupt the fresh node between issueCreate and its
        # objective-node attachment, and drop the relation.
        sentinel = _sentinel_issue(ws, new_id)
        sentinel_uuid = str(sentinel["id"])
        manifest_url = linear_attachments.objective_manifest_url("01NEWOBJ")
        del ws.attachments[(sentinel_uuid, manifest_url)]
        ws.projects[new_id]["content"] = "bare overview without the callout"
        ws.issue_by_identifier("ENG-3")["project_id"] = old_id
        fresh = next(
            i
            for i in ws.issues.values()
            if i.get("project_id") == new_id
            and (block := _att_payload(ws, i, linear_attachments.OBJECTIVE_NODE_KIND)) is not None
            and block.get("id") == "1.2"
        )
        fresh_uuid = str(fresh["id"])
        fresh_identifier = str(fresh["identifier"])
        del ws.attachments[(fresh_uuid, linear_attachments.node_url(fresh_identifier))]
        ws.relations.clear()
        issue_count_before_recovery = len(ws.issues)

        again = store.supersede_objective(
            old_objective_id=old_id,
            title="Successor objective",
            prose="# Successor\n\nprose",
            run_id="01NEWOBJ",
            roadmap_nodes=new_nodes,
            carry_map=carry_map,
            close_predecessor=False,
        )
        assert again is not None and again.existed is True and again.id == new_id

        # Every damaged write re-materialized…
        assert (sentinel_uuid, manifest_url) in ws.attachments
        content = str(ws.projects[new_id]["content"])
        assert content.startswith("**Plan the next node:**")
        carried = ws.issue_by_identifier("ENG-3")
        assert carried["project_id"] == new_id
        state = store.get_objective(objective_id=new_id)
        assert state is not None and sorted(n.id for n in state.nodes) == ["1.1", "1.2"]
        assert len(ws.relations) == 1  # the 1.1 → 1.2 blocking edge, exactly once
        # The issueCreate/attachment recovery reused the original UUID rather than minting a
        # second visible node-issue.
        assert len(ws.issues) == issue_count_before_recovery
        recovered = _att_payload(ws, ws.issues[fresh_uuid], linear_attachments.OBJECTIVE_NODE_KIND)
        assert recovered is not None and recovered["id"] == "1.2"

        # …and NO duplicates: one node attachment on the carried issue, one milestone per
        # phase name, one node-issue per roadmap node.
        node_atts = [
            n
            for n in ws.attachment_nodes_of(carried)
            if str(n["url"]).startswith("https://perk.invalid/node/")
        ]
        assert len(node_atts) == 1
        names = [m["name"] for m in ws.milestones.values() if m.get("project_id") == new_id]
        assert len(names) == len(set(names))

        # A third run over the HEALTHY state is a pure no-op on relations + issues.
        issues_before = len(ws.issues)
        relations_before = list(ws.relations)
        third = store.supersede_objective(
            old_objective_id=old_id,
            title="Successor objective",
            prose="# Successor\n\nprose",
            run_id="01NEWOBJ",
            roadmap_nodes=new_nodes,
            carry_map=carry_map,
            close_predecessor=False,
        )
        assert third is not None and third.existed is True
        assert len(ws.issues) == issues_before
        assert ws.relations == relations_before


# ----------------------------------------------------------------------- manifest + drift


def _manifest_of(ws: FakeLinearWorkspace, obj_id: str) -> objective.Manifest | None:
    payload = _att_payload(
        ws, _sentinel_issue(ws, obj_id), linear_attachments.OBJECTIVE_MANIFEST_KIND
    )
    if payload is None:
        return None
    manifest, _errors = objective.parse_manifest_data(payload)
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
        # delete the sentinel's manifest attachment (simulate a pre-manifest objective)
        sentinel = _sentinel_issue(ws, obj_id)
        manifest_key = next(
            (iid, url)
            for (iid, url) in ws.attachments
            if iid == sentinel["id"] and "/manifest/" in url
        )
        del ws.attachments[manifest_key]
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
        att = linear_attachments.find_perk_attachment(
            ws.attachment_nodes_of(iss), kind=linear_attachments.OBJECTIVE_NODE_KIND
        )
        return att is not None and att.payload.get("id") == node_id

    victim = next(iid for iid, iss in ws.issues.items() if _is(iss))
    # Linear cascade-deletes the issue's relations AND attachments when the issue is removed.
    ws.delete_issue(victim)


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


# ------------------------------------------------------------------- the gist round trip (§8.41)


def test_gist_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """The §8.41 consumption round trip over the stateful fake: create a gist on each tier, prove
    the unchanged adoption doors consume it in place, and that adoption is exactly what flips
    `adopted` in `perk gist list` (default view hides adopted; `--all` marks it)."""
    ws = FakeLinearWorkspace()
    _patch_linear(monkeypatch, ws)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        root = Path(d)
        _scaffold_repo(root)

        # --- issue-tier gist (plan scope, the default) ---------------------------------------
        (root / "gist.md").write_text("# Faster reviews\n\nWe want faster reviews.\n")
        payload = _invoke(
            runner, ["gist", "create", "--json", "--body", "gist.md", "--run-id", "01GISTRUN1"]
        )
        assert payload["scope"] == "plan"
        gist_payload = cast("dict[str, object]", payload["gist"])
        gist_id = str(gist_payload["id"])
        issue = ws.issue_by_identifier(gist_id)
        # Clean body: the prose only; the gist-header (with scope) rides a native attachment.
        assert "perk:metadata-block" not in str(issue["description"])
        header = _att_payload(ws, issue, linear_attachments.GIST_HEADER_KIND)
        assert header is not None and header["scope"] == "plan"

        # Idempotent on run_id: a re-create returns the same issue, no second gist.
        payload = _invoke(
            runner, ["gist", "create", "--json", "--body", "gist.md", "--run-id", "01GISTRUN1"]
        )
        assert cast("dict[str, object]", payload["gist"])["existed"] is True

        # Unconsumed: the default list shows it, not adopted.
        rows = cast("list[dict[str, object]]", _invoke(runner, ["gist", "list", "--json"])["gists"])
        assert [(r["id"], r["scope"], r["adopted"], r["kind"]) for r in rows] == [
            (gist_id, "plan", False, "issue")
        ]

        # --- consume via the UNCHANGED plan adoption door: plan save --adopt-from -------------
        (root / "plan.md").write_text(_PLAN_MD, encoding="utf-8")
        payload = _invoke(
            runner,
            [
                "plan",
                "save",
                "--plan-file",
                "plan.md",
                "--run-id",
                "01PLANRUN9",
                "--adopt-from",
                gist_id,
                "--json",
            ],
        )
        # Adopted in place — the gist issue IS the plan now; no second issue was minted.
        assert cast("dict[str, object]", payload["issue"])["id"] == gist_id
        issue = ws.issue_by_identifier(gist_id)
        # The plan-header attachment landed beside the gist-header one (distinct kinds).
        assert _att_payload(ws, issue, linear_attachments.PLAN_HEADER_KIND) is not None
        assert _att_payload(ws, issue, linear_attachments.GIST_HEADER_KIND) is not None

        # Adoption is what flips `adopted`: the default view hides it; --all marks it.
        assert _invoke(runner, ["gist", "list", "--json"])["gists"] == []
        rows = cast(
            "list[dict[str, object]]",
            _invoke(runner, ["gist", "list", "--all", "--json"])["gists"],
        )
        assert [(r["id"], r["adopted"]) for r in rows] == [(gist_id, True)]

        # --- project-tier gist (objective scope) ----------------------------------------------
        (root / "gist2.md").write_text("# Big goal\n\nA long-running desire.\n")
        payload = _invoke(
            runner,
            [
                "gist",
                "create",
                "--json",
                "--scope",
                "objective",
                "--body",
                "gist2.md",
                "--run-id",
                "01GISTRUN2",
            ],
        )
        assert payload["scope"] == "objective"
        proj_id = str(cast("dict[str, object]", payload["gist"])["id"])
        assert proj_id in ws.projects
        # Deliberately light: no sentinel/node issues joined the workspace for the gist project.
        assert all(i.get("project_id") != proj_id for i in ws.issues.values())

        rows = cast("list[dict[str, object]]", _invoke(runner, ["gist", "list", "--json"])["gists"])
        assert [(r["id"], r["kind"], r["adopted"]) for r in rows] == [(proj_id, "project", False)]

        # --- consume via the UNCHANGED objective adoption door: objective create --adopt-from --
        (root / "obj.md").write_text("# Big goal\n\nThe why.\n", encoding="utf-8")
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
                "--adopt-from",
                proj_id,
                "--run-id",
                "01OBJRUN2",
            ],
        )
        # Adopted in place — the gist project IS the objective now (no second project).
        assert cast("dict[str, object]", payload["objective"])["id"] == proj_id
        overview = str(ws.project_by_id(proj_id)["content"])
        # The original gist overview (with its gist-header) survives in the archive note.
        assert plan.has_metadata_block(overview, plan.GIST_HEADER_KEY)

        # Adoption flips `adopted` on the project tier too.
        assert _invoke(runner, ["gist", "list", "--json"])["gists"] == []
        rows = cast(
            "list[dict[str, object]]",
            _invoke(runner, ["gist", "list", "--all", "--json"])["gists"],
        )
        assert [(r["id"], r["kind"], r["adopted"]) for r in rows] == [
            (gist_id, "issue", True),
            (proj_id, "project", True),
        ]
