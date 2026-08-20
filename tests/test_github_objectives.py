import json
import subprocess

import pytest
from _github_fakes import ROOT, _GhDispatch, _GhRecorder, _has, _Proc

from perk import github, objective, plan
from perk.backends.github import objectives, plans

# --------------------------------------------------------------- objective ops


def _obj_header(run_id: str, comment_id=None, *, origin=None) -> str:
    return plan.render_metadata_block(
        objective.OBJECTIVE_HEADER_KEY,
        objective.render_header_block(
            objective.ObjectiveHeader(
                run_id=run_id, created="t", objective_comment_id=comment_id, origin=origin
            )
        ),
    )


def _obj_roadmap(nodes) -> str:
    return plan.render_metadata_block(
        objective.OBJECTIVE_ROADMAP_KEY, objective.render_roadmap_block(nodes)
    )


def _obj_body(run_id, nodes, comment_id=None, *, origin=None) -> str:
    return f"{_obj_header(run_id, comment_id, origin=origin)}\n\n{_obj_roadmap(nodes)}\n"


def _lists_comments(issue: int):
    endpoint = f"issues/{issue}/comments"
    return lambda gh: "POST" not in gh and any(endpoint in token for token in gh)


class _Once:
    """A dispatch predicate that matches only its FIRST hit — for scripting two different
    responses to byte-identical calls (e.g. supersede's origin-carry read of the old issue body
    vs the close path's later re-read of the same endpoint)."""

    def __init__(self, pred) -> None:
        self._pred = pred
        self._used = False

    def __call__(self, gh) -> bool:
        if self._used or not self._pred(gh):
            return False
        self._used = True
        return True


def test_find_objective_issue_label_scoped(monkeypatch):
    # The parameterized find_plan_issue read is exhaustive: gh --paginate --slurp returns an
    # array of page arrays, so the fake feeds one page wrapping the issue list.
    issues = [{"number": 5, "html_url": "u/5", "body": _obj_header("01RID")}]
    rec = _GhRecorder(get=_Proc(0, stdout=json.dumps([issues])))
    monkeypatch.setattr(subprocess, "run", rec)
    found = objectives.find_objective_issue(run_id="01RID", repo_root=ROOT)
    assert found is not None and found.number == 5 and found.existed is True
    assert any("labels=perk:objective" in tok for c in rec.calls for tok in c)


def test_list_open_objective_issues_maps_rows_and_skips_prs(monkeypatch):
    issues = [
        {"number": 5, "title": "O5", "html_url": "u/5", "body": "b"},
        "not-a-dict",  # skipped defensively
        {"number": 6, "title": "PR", "html_url": "u/6", "body": "b", "pull_request": {}},
        {"number": 7, "title": "O7", "html_url": "u/7", "body": "b"},
    ]
    rec = _GhRecorder(get=_Proc(0, stdout=json.dumps(issues)))
    monkeypatch.setattr(subprocess, "run", rec)
    rows = objectives.list_open_objective_issues(repo_root=ROOT)
    # The list endpoint's default created-descending order is preserved verbatim (no re-sort).
    assert [(r.number, r.title) for r in rows] == [(5, "O5"), (7, "O7")]
    [call] = rec.calls
    assert any("labels=perk:objective" in tok for tok in call)
    assert any("state=open" in tok for tok in call)


def test_list_open_objective_issues_raises_on_infra_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(1, stderr="HTTP 500")))
    with pytest.raises(github.GitHubError):
        objectives.list_open_objective_issues(repo_root=ROOT)


def test_list_open_objective_issues_stays_a_bounded_one_page_read(monkeypatch):
    # The bounded browse contract, pinned: exactly one GET with NO pagination argv — membership
    # beyond GitHub's default page is deliberately not promised (unlike the full-census readers).
    rec = _GhRecorder(get=_Proc(0, stdout="[]"))
    monkeypatch.setattr(subprocess, "run", rec)
    objectives.list_open_objective_issues(repo_root=ROOT)
    [call] = rec.calls
    for token in ("--paginate", "--slurp", "per_page"):
        assert not any(token in tok for tok in call), token


def test_create_objective_issue_idempotent(monkeypatch):
    existing = [{"number": 5, "html_url": "u/5", "body": _obj_header("01RID")}]
    rec = _GhRecorder(get=_Proc(0, stdout=json.dumps([existing])))
    monkeypatch.setattr(subprocess, "run", rec)
    issue = objectives.create_objective_issue(
        title="Obj", body="# Obj\n\nprose", repo_root=ROOT, run_id="01RID"
    )
    assert issue.number == 5 and issue.existed is True
    assert not rec.posted()  # dedup short-circuits before any write


def test_create_objective_issue_rejects_empty_roadmap(monkeypatch):
    # Storage backstop: a node-less objective (no embedded roadmap, no roadmap_nodes) raises
    # GitHubError after the idempotency lookup (returns []) and before any issue POST.
    rec = _GhRecorder(get=_Proc(0, stdout="[]"))
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(github.GitHubError):
        objectives.create_objective_issue(
            title="Obj", body="# Obj\n\nprose", repo_root=ROOT, run_id="01EMPTY"
        )
    assert not rec.posted()  # no issue created


def test_create_objective_issue_two_step(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    roadmap = _obj_roadmap(nodes)
    body = f"# My objective\n\n{roadmap}\n"
    rec = _GhDispatch(
        [
            (_has("repos/{owner}/{repo}/labels", "POST"), _Proc(0)),  # lazy label create
            (_has("comments", "POST"), _Proc(0, json.dumps({"id": 555}))),  # body comment
            (
                _has("repos/{owner}/{repo}/issues", "POST"),
                _Proc(0, json.dumps({"number": 200, "url": "u/200"})),
            ),
            (
                _has("issues/200", ".body"),
                _Proc(0, _obj_body("01RID", nodes)),
            ),  # header backfill read
            (_has("issues/200", "PATCH"), _Proc(0, "{}")),
            (_has("issues", "GET"), _Proc(0, "[]")),  # idempotency find -> none
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    issue = objectives.create_objective_issue(
        title="My objective", body=body, repo_root=ROOT, run_id="01RID"
    )
    assert issue.number == 200 and issue.existed is False
    # the perk:objective label was lazily created
    assert any("name=perk:objective" in tok for c in rec.calls for tok in c)
    # the comment-id backfill PATCHed the header with objective_comment_id=555
    patched = rec.body_files[-1]
    header = plan.find_metadata_block(patched, objective.OBJECTIVE_HEADER_KEY)
    assert header is not None and header["objective_comment_id"] == 555
    # the objective-body comment leads with the copyable `perk objective plan 200` callout, above
    # the rendered roadmap table
    comment = next(b for b in rec.body_files if "perk objective plan 200" in b)
    assert comment.startswith("**Plan the next node:**")
    assert comment.index("perk objective plan 200") < comment.index(
        objective.ROADMAP_TABLE_MARKER_START
    )


def _two_step_dispatch(nodes) -> _GhDispatch:
    return _GhDispatch(
        [
            (_has("repos/{owner}/{repo}/labels", "POST"), _Proc(0)),
            (_has("comments", "POST"), _Proc(0, json.dumps({"id": 555}))),
            (
                _has("repos/{owner}/{repo}/issues", "POST"),
                _Proc(0, json.dumps({"number": 200, "url": "u/200"})),
            ),
            (_has("issues/200", ".body"), _Proc(0, _obj_body("01RID", nodes))),
            (_has("issues/200", "PATCH"), _Proc(0, "{}")),
            (_has("issues", "GET"), _Proc(0, "[]")),
        ]
    )


def test_create_objective_issue_emits_delivery_pair_when_passed(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING),
        objective.ObjectiveNode(id="1.2", description="B", status=objective.NodeStatus.PENDING),
    ]
    rec = _two_step_dispatch(nodes)
    monkeypatch.setattr(subprocess, "run", rec)
    objectives.create_objective_issue(
        title="Obj",
        body="# Obj\n\nprose",
        repo_root=ROOT,
        run_id="01RID",
        roadmap_nodes=nodes,
        delivery="stacked",
        delivery_lineage="01LINEAGE",
    )
    issue_body = next(b for b in rec.body_files if objective.OBJECTIVE_ROADMAP_KEY in b)
    header = plan.find_metadata_block(issue_body, objective.OBJECTIVE_HEADER_KEY)
    assert header is not None
    assert header["delivery"] == "stacked" and header["delivery_lineage"] == "01LINEAGE"


def test_create_objective_issue_absent_delivery_keeps_header_byte_identity(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    rec = _two_step_dispatch(nodes)
    monkeypatch.setattr(subprocess, "run", rec)
    objectives.create_objective_issue(
        title="Obj", body="# Obj\n\nprose", repo_root=ROOT, run_id="01RID", roadmap_nodes=nodes
    )
    issue_body = next(b for b in rec.body_files if objective.OBJECTIVE_ROADMAP_KEY in b)
    # The stored header block is byte-identical to the pre-delivery shape (the §8.42 rule).
    assert "delivery" not in issue_body
    header = plan.find_metadata_block(issue_body, objective.OBJECTIVE_HEADER_KEY)
    assert header is not None and "delivery" not in header


def test_create_objective_issue_emits_origin_when_passed(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    rec = _two_step_dispatch(nodes)
    monkeypatch.setattr(subprocess, "run", rec)
    objectives.create_objective_issue(
        title="Obj",
        body="# Obj\n\nprose",
        repo_root=ROOT,
        run_id="01RID",
        roadmap_nodes=nodes,
        origin="learn-dream",
    )
    issue_body = next(b for b in rec.body_files if objective.OBJECTIVE_ROADMAP_KEY in b)
    header = plan.find_metadata_block(issue_body, objective.OBJECTIVE_HEADER_KEY)
    assert header is not None and header["origin"] == "learn-dream"


def test_create_objective_issue_absent_origin_keeps_header_byte_identity(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    rec = _two_step_dispatch(nodes)
    monkeypatch.setattr(subprocess, "run", rec)
    objectives.create_objective_issue(
        title="Obj", body="# Obj\n\nprose", repo_root=ROOT, run_id="01RID", roadmap_nodes=nodes
    )
    issue_body = next(b for b in rec.body_files if objective.OBJECTIVE_ROADMAP_KEY in b)
    # The stored header block is byte-identical to the pre-origin shape (the §8.42 rule).
    assert "origin" not in issue_body
    header = plan.find_metadata_block(issue_body, objective.OBJECTIVE_HEADER_KEY)
    assert header is not None and "origin" not in header


def test_create_objective_issue_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    issue = objectives.create_objective_issue(
        title="t", body="# t", repo_root=ROOT, run_id="01RID", dry_run=True
    )
    assert issue.number == 0 and issue.existed is False


def test_adopt_issue_as_objective_stamps_in_place(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    rec = _GhDispatch(
        [
            (_has("issues", "GET"), _Proc(0, "[]")),  # find_objective_issue -> none
            (
                _has("view", "number,title,body,state,url"),
                _Proc(
                    0,
                    json.dumps(
                        {
                            "number": 7,
                            "title": "Human title",
                            "body": "HUMAN OBJECTIVE OVERVIEW",
                            "state": "OPEN",
                            "url": "u7",
                        }
                    ),
                ),
            ),
            (_has("{repo}/labels", "POST"), _Proc(0, "{}")),  # create_label
            (_has("issues/7/labels", "POST"), _Proc(0, "{}")),  # additive label add
            (_has("issues/7/comments", "POST"), _Proc(0, json.dumps({"id": 555}))),  # body comment
            (_has("issues/7", ".body"), _Proc(0, "HUMAN OBJECTIVE OVERVIEW")),  # _get_issue_body
            (_has("issues/7", "PATCH"), _Proc(0, "{}")),  # body stamp PATCH + header backfill PATCH
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    adopted = objectives.adopt_issue_as_objective(
        number=7,
        title="Human title",
        prose="MODEL-AUTHORED PROSE",
        repo_root=ROOT,
        run_id="01RID",
        roadmap_nodes=nodes,
    )
    assert adopted == objectives.ObjectiveAdoption(number=7, url="u7", existed=False, dry_run=False)
    # body_files[0] = the stamped issue body: human overview verbatim + header(adopted_from=#7) +
    # roadmap block; title is NEVER PATCHed.
    stamped = rec.body_files[0]
    assert "HUMAN OBJECTIVE OVERVIEW" in stamped
    header = plan.find_metadata_block(stamped, objective.OBJECTIVE_HEADER_KEY)
    assert header is not None and header["adopted_from"] == "#7"
    assert plan.find_metadata_block(stamped, objective.OBJECTIVE_ROADMAP_KEY) is not None
    assert not any("title=" in tok for c in rec.calls for tok in c)
    # body_files[1] = the objective-body comment: callout + table + MODEL prose + the verbatim
    # `Adopted-from` Immutable archive note.
    comment = rec.body_files[1]
    assert "perk objective plan 7" in comment
    assert "MODEL-AUTHORED PROSE" in comment
    assert objective.ADOPTED_OVERVIEW_MARKER in comment
    assert "HUMAN OBJECTIVE OVERVIEW" in comment
    # the perk:objective label was lazily created + added additively (never replaced)
    assert any("name=perk:objective" in tok for c in rec.calls for tok in c)


def test_adopt_issue_as_objective_idempotent(monkeypatch):
    existing = [{"number": 7, "html_url": "u/7", "body": _obj_header("01RID")}]
    rec = _GhDispatch([(_has("issues", "GET"), _Proc(0, json.dumps([existing])))])
    monkeypatch.setattr(subprocess, "run", rec)
    adopted = objectives.adopt_issue_as_objective(
        number=7,
        title="t",
        prose="p",
        repo_root=ROOT,
        run_id="01RID",
        roadmap_nodes=[
            objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
        ],
    )
    assert adopted.number == 7 and adopted.existed is True
    # the idempotent short-circuit never PATCHes / posts a comment
    assert not any("PATCH" in c for c in rec.calls)


def test_adopt_issue_as_objective_refuses_a_plan_carrier(monkeypatch):
    # Wrong-kind writer guard (§8.30): a plan-header'd body refuses BEFORE any mutation —
    # closes the `objective create --adopt-from` direct-save bypass at the writer.
    plan_body = plan.render_metadata_block(plan.PLAN_HEADER_KEY, {"run_id": "01P", "created": "t"})
    rec = _GhDispatch(
        [
            (_has("issues", "GET"), _Proc(0, "[]")),  # find_objective_issue -> none
            (
                _has("view", "number,title,body,state,url"),
                _Proc(
                    0,
                    json.dumps(
                        {
                            "number": 7,
                            "title": "Plan issue",
                            "body": plan_body,
                            "state": "OPEN",
                            "url": "u7",
                        }
                    ),
                ),
            ),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(github.GitHubError, match="wrong kind for objective adoption"):
        objectives.adopt_issue_as_objective(
            number=7,
            title="t",
            prose="p",
            repo_root=ROOT,
            run_id="01RID",
            roadmap_nodes=[
                objective.ObjectiveNode(
                    id="1.1", description="A", status=objective.NodeStatus.PENDING
                )
            ],
        )
    assert rec.method_calls("POST") == 0 and rec.method_calls("PATCH") == 0


def test_adopt_issue_as_objective_rejects_empty_roadmap(monkeypatch):
    rec = _GhDispatch([(_has("issues", "GET"), _Proc(0, "[]"))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(github.GitHubError, match="roadmap is empty"):
        objectives.adopt_issue_as_objective(
            number=7, title="t", prose="p", repo_root=ROOT, run_id="01RID", roadmap_nodes=[]
        )


def test_adopt_issue_as_objective_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    adopted = objectives.adopt_issue_as_objective(
        number=7,
        title="t",
        prose="p",
        repo_root=ROOT,
        run_id="01RID",
        roadmap_nodes=[
            objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
        ],
        dry_run=True,
    )
    assert adopted.dry_run is True and adopted.existed is False


def test_supersede_objective_issue_creates_new_and_closes_old(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    rec = _GhDispatch(
        [
            (_has("issues", "GET"), _Proc(0, "[]")),  # find_objective_issue (twice) -> none
            (_has("{repo}/labels", "POST"), _Proc(0, "{}")),  # lazy label create
            (_has("comments", "POST"), _Proc(0, json.dumps({"id": 555}))),  # body comment
            (
                _has("repos/{owner}/{repo}/issues", "POST"),
                _Proc(0, json.dumps({"number": 200, "url": "u/200"})),
            ),
            (_has("issues/200", ".body"), _Proc(0, _obj_body("01RID", nodes))),  # backfill read
            (_has("issues/200", "PATCH"), _Proc(0, "{}")),  # header backfill PATCH
            (_has("issues/42", ".body"), _Proc(0, _obj_body("01OLD", nodes))),  # old header read
            (_has("issues/42", "PATCH"), _Proc(0, "{}")),  # superseded_by stamp + close
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    created = objectives.supersede_objective_issue(
        old_number=42,
        title="New objective",
        prose="# New objective\n\nprose",
        repo_root=ROOT,
        run_id="01RID",
        roadmap_nodes=nodes,
    )
    assert created.number == 200 and created.existed is False
    # the new issue body carries supersedes=#42
    new_body = next(
        b
        for b in rec.body_files
        if (h := plan.find_metadata_block(b, objective.OBJECTIVE_HEADER_KEY)) is not None
        and h.get("supersedes") == "#42"
    )
    assert plan.find_metadata_block(new_body, objective.OBJECTIVE_ROADMAP_KEY) is not None
    # the old issue header gets superseded_by=#200
    old_patch = next(
        b
        for b in rec.body_files
        if (h := plan.find_metadata_block(b, objective.OBJECTIVE_HEADER_KEY)) is not None
        and h.get("superseded_by") == "#200"
    )
    assert old_patch is not None
    # the old issue was closed (state=closed PATCH on issues/42)
    assert any("issues/42" in " ".join(c) and "state=closed" in " ".join(c) for c in rec.calls)


def test_supersede_objective_issue_idempotent(monkeypatch):
    existing = [{"number": 200, "html_url": "u/200", "body": _obj_header("01RID")}]
    rec = _GhDispatch([(_has("issues", "GET"), _Proc(0, json.dumps([existing])))])
    monkeypatch.setattr(subprocess, "run", rec)
    created = objectives.supersede_objective_issue(
        old_number=42,
        title="t",
        prose="p",
        repo_root=ROOT,
        run_id="01RID",
        roadmap_nodes=[
            objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
        ],
    )
    assert created.number == 200 and created.existed is True
    # the idempotent short-circuit never closes the old objective (no PATCH at all)
    assert not any("PATCH" in c for c in rec.calls)


def test_supersede_objective_issue_close_failure_is_fail_open(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    rec = _GhDispatch(
        [
            (_has("issues", "GET"), _Proc(0, "[]")),
            (_has("{repo}/labels", "POST"), _Proc(0, "{}")),
            (_has("comments", "POST"), _Proc(0, json.dumps({"id": 555}))),
            (
                _has("repos/{owner}/{repo}/issues", "POST"),
                _Proc(0, json.dumps({"number": 200, "url": "u/200"})),
            ),
            (_has("issues/200", ".body"), _Proc(0, _obj_body("01RID", nodes))),
            (_has("issues/200", "PATCH"), _Proc(0, "{}")),
            # the create arm's origin-carry read of the old body succeeds (origin-less)…
            (_Once(_has("issues/42", ".body")), _Proc(0, _obj_body("01OLD", nodes))),
            # …then the OLD-side close's re-read fails — must be swallowed fail-open
            (_has("issues/42", ".body"), _Proc(1, stderr="boom")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    created = objectives.supersede_objective_issue(
        old_number=42,
        title="t",
        prose="p",
        repo_root=ROOT,
        run_id="01RID",
        roadmap_nodes=nodes,
    )
    # the new objective still exists despite the close failure
    assert created.number == 200 and created.existed is False
    assert not any("state=closed" in " ".join(c) for c in rec.calls)


def test_supersede_objective_issue_rejects_empty_roadmap(monkeypatch):
    rec = _GhDispatch([(_has("issues", "GET"), _Proc(0, "[]"))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(github.GitHubError, match="roadmap is empty"):
        objectives.supersede_objective_issue(
            old_number=42, title="t", prose="p", repo_root=ROOT, run_id="01RID", roadmap_nodes=[]
        )


def test_supersede_deferred_close_never_touches_the_old_issue(monkeypatch):
    # §8.53's deferred-close arm: the create runs WITHOUT any old-side stamp/close (those
    # move to finalize_supersession_issue, called only after the projection verifies).
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    rec = _GhDispatch(
        [
            (_has("issues", "GET"), _Proc(0, "[]")),
            (_has("{repo}/labels", "POST"), _Proc(0, "{}")),
            (_has("comments", "POST"), _Proc(0, json.dumps({"id": 555}))),
            (
                _has("repos/{owner}/{repo}/issues", "POST"),
                _Proc(0, json.dumps({"number": 200, "url": "u/200"})),
            ),
            (_has("issues/200", ".body"), _Proc(0, _obj_body("01RID", nodes))),
            (_has("issues/200", "PATCH"), _Proc(0, "{}")),
            (_has("issues/42", ".body"), _Proc(0, _obj_body("01OLD", nodes))),  # the carry read
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    created = objectives.supersede_objective_issue(
        old_number=42,
        title="t",
        prose="p",
        repo_root=ROOT,
        run_id="01RID",
        roadmap_nodes=nodes,
        close_predecessor=False,
    )
    assert created.number == 200 and created.existed is False
    # The origin-carry READ is the only old-side touch — never a mutation (no PATCH, no close).
    assert not any("issues/42" in " ".join(c) and ("PATCH" in c or "POST" in c) for c in rec.calls)
    assert not any("state=closed" in " ".join(c) for c in rec.calls)
    # The successor still records the supersedes backlink.
    assert any(
        (h := plan.find_metadata_block(b, objective.OBJECTIVE_HEADER_KEY)) is not None
        and h.get("supersedes") == "#42"
        for b in rec.body_files
    )


def test_supersede_deferred_close_found_arm_heals_a_missing_body_comment(monkeypatch):
    # D9: found-by-run_id with a null header objective_comment_id → repost the objective-body
    # comment from the supplied prose and backfill the header.
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    existing = [{"number": 200, "html_url": "u/200", "body": _obj_header("01RID")}]
    rec = _GhDispatch(
        [
            (_has("issues", "GET"), _Proc(0, json.dumps([existing]))),
            (_has("issues/200", ".body"), _Proc(0, _obj_body("01RID", nodes))),
            (_lists_comments(200), _Proc(0, "[]")),
            (_has("comments", "POST"), _Proc(0, json.dumps({"id": 777}))),
            (_has("issues/200", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    created = objectives.supersede_objective_issue(
        old_number=42,
        title="t",
        prose="replan prose",
        repo_root=ROOT,
        run_id="01RID",
        roadmap_nodes=nodes,
        close_predecessor=False,
    )
    assert created.number == 200 and created.existed is True
    # The reposted comment is the create-path compose: callout + roadmap table + prose.
    comment = next(b for b in rec.body_files if "perk objective plan 200" in b)
    assert objective.ROADMAP_TABLE_MARKER_START in comment and "replan prose" in comment
    # The header backfill recorded the fresh comment id.
    patched = rec.body_files[-1]
    header = plan.find_metadata_block(patched, objective.OBJECTIVE_HEADER_KEY)
    assert header is not None and header["objective_comment_id"] == 777


def test_supersede_deferred_close_found_arm_recovers_post_before_backfill(monkeypatch):
    # Exact D9 interruption: comment POST succeeded, then objective_comment_id backfill failed.
    # The rerun discovers marker-bearing comment 777 and backfills that id without another POST.
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    existing = [{"number": 200, "html_url": "u/200", "body": _obj_header("01RID")}]
    prior_comment = objective.render_body_comment(nodes, prose="replan prose")
    rec = _GhDispatch(
        [
            (_has("issues", "GET"), _Proc(0, json.dumps([existing]))),
            (_has("issues/200", ".body"), _Proc(0, _obj_body("01RID", nodes))),
            (
                _lists_comments(200),
                _Proc(0, json.dumps([{"id": 777, "body": prior_comment}])),
            ),
            (_has("issues/200", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    created = objectives.supersede_objective_issue(
        old_number=42,
        title="t",
        prose="replan prose",
        repo_root=ROOT,
        run_id="01RID",
        roadmap_nodes=nodes,
        close_predecessor=False,
    )
    assert created.number == 200 and created.existed is True
    assert not any("POST" in call for call in rec.calls)
    patched = rec.body_files[-1]
    header = plan.find_metadata_block(patched, objective.OBJECTIVE_HEADER_KEY)
    assert header is not None and header["objective_comment_id"] == 777


def test_supersede_deferred_close_found_arm_heals_a_vanished_comment(monkeypatch):
    # A recorded comment id whose comment no longer resolves is the same healable window.
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    existing = [{"number": 200, "html_url": "u/200", "body": _obj_header("01RID", 9)}]
    rec = _GhDispatch(
        [
            (_has("issues", "GET"), _Proc(0, json.dumps([existing]))),
            (_has("issues/200", ".body"), _Proc(0, _obj_body("01RID", nodes, comment_id=9))),
            (_has("comments/9"), _Proc(1, stderr="Not Found (404)")),
            (_lists_comments(200), _Proc(0, "[]")),
            (_has("comments", "POST"), _Proc(0, json.dumps({"id": 778}))),
            (_has("issues/200", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    created = objectives.supersede_objective_issue(
        old_number=42,
        title="t",
        prose="p",
        repo_root=ROOT,
        run_id="01RID",
        roadmap_nodes=nodes,
        close_predecessor=False,
    )
    assert created.existed is True
    patched = rec.body_files[-1]
    header = plan.find_metadata_block(patched, objective.OBJECTIVE_HEADER_KEY)
    assert header is not None and header["objective_comment_id"] == 778


def test_supersede_deferred_close_found_arm_converges_as_a_noop(monkeypatch):
    # A resolvable recorded comment → nothing to heal: no comment POST, no header PATCH.
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    existing = [{"number": 200, "html_url": "u/200", "body": _obj_header("01RID", 9)}]
    rec = _GhDispatch(
        [
            (_has("issues", "GET"), _Proc(0, json.dumps([existing]))),
            (_has("issues/200", ".body"), _Proc(0, _obj_body("01RID", nodes, comment_id=9))),
            (_has("comments/9"), _Proc(0, "the body comment")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    created = objectives.supersede_objective_issue(
        old_number=42,
        title="t",
        prose="p",
        repo_root=ROOT,
        run_id="01RID",
        roadmap_nodes=nodes,
        close_predecessor=False,
    )
    assert created.existed is True
    assert not any("POST" in c for c in rec.calls)
    assert not any("PATCH" in c for c in rec.calls)


def test_finalize_supersession_issue_stamps_then_closes(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    rec = _GhDispatch(
        [
            (_has("issues/42", ".body"), _Proc(0, _obj_body("01OLD", nodes))),
            (_has("issues/42", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    objectives.finalize_supersession_issue(old_number=42, new_number=200, repo_root=ROOT)
    stamped = next(
        b
        for b in rec.body_files
        if (h := plan.find_metadata_block(b, objective.OBJECTIVE_HEADER_KEY)) is not None
        and h.get("superseded_by") == "#200"
    )
    assert stamped is not None
    assert any("state=closed" in " ".join(c) for c in rec.calls)


def test_finalize_supersession_issue_converges_on_rerun(monkeypatch):
    # A present matching stamp skips the header PATCH; the close still converges (idempotent).
    body_with_stamp = _obj_header("01OLD").replace("superseded_by: null", "superseded_by: '#200'")
    rec = _GhDispatch(
        [
            (_has("issues/42", ".body"), _Proc(0, body_with_stamp)),
            (_has("issues/42", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    objectives.finalize_supersession_issue(old_number=42, new_number=200, repo_root=ROOT)
    # ONE PATCH: the close (state=closed) — no header re-stamp.
    patches = [c for c in rec.calls if "PATCH" in c]
    assert len(patches) == 1 and "state=closed" in " ".join(patches[0])


def test_finalize_supersession_issue_refuses_a_conflicting_stamp(monkeypatch):
    body = _obj_header("01OLD").replace("superseded_by: null", "superseded_by: '#999'")
    rec = _GhDispatch([(_has("issues/42", ".body"), _Proc(0, body))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(github.GitHubError, match="already superseded"):
        objectives.finalize_supersession_issue(old_number=42, new_number=200, repo_root=ROOT)
    assert not any("PATCH" in c for c in rec.calls)


def test_supersede_objective_issue_carries_stored_origin(monkeypatch):
    # The §8.24 origin carry: an ordinary replan keeps the successor inside the guarded
    # origin population — store-side, no new parameter.
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    rec = _GhDispatch(
        [
            (_has("issues", "GET"), _Proc(0, "[]")),
            (_has("{repo}/labels", "POST"), _Proc(0, "{}")),
            (_has("comments", "POST"), _Proc(0, json.dumps({"id": 555}))),
            (
                _has("repos/{owner}/{repo}/issues", "POST"),
                _Proc(0, json.dumps({"number": 200, "url": "u/200"})),
            ),
            (_has("issues/200", ".body"), _Proc(0, _obj_body("01RID", nodes))),
            (_has("issues/200", "PATCH"), _Proc(0, "{}")),
            (
                _has("issues/42", ".body"),
                _Proc(0, _obj_body("01OLD", nodes, origin="learn-dream")),
            ),
            (_has("issues/42", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    created = objectives.supersede_objective_issue(
        old_number=42,
        title="t",
        prose="p",
        repo_root=ROOT,
        run_id="01RID",
        roadmap_nodes=nodes,
    )
    assert created.number == 200
    new_body = next(
        b
        for b in rec.body_files
        if (h := plan.find_metadata_block(b, objective.OBJECTIVE_HEADER_KEY)) is not None
        and h.get("supersedes") == "#42"
    )
    header = plan.find_metadata_block(new_body, objective.OBJECTIVE_HEADER_KEY)
    assert header is not None and header["origin"] == "learn-dream"


def test_supersede_objective_issue_absent_origin_stays_absent(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    rec = _GhDispatch(
        [
            (_has("issues", "GET"), _Proc(0, "[]")),
            (_has("{repo}/labels", "POST"), _Proc(0, "{}")),
            (_has("comments", "POST"), _Proc(0, json.dumps({"id": 555}))),
            (
                _has("repos/{owner}/{repo}/issues", "POST"),
                _Proc(0, json.dumps({"number": 200, "url": "u/200"})),
            ),
            (_has("issues/200", ".body"), _Proc(0, _obj_body("01RID", nodes))),
            (_has("issues/200", "PATCH"), _Proc(0, "{}")),
            (_has("issues/42", ".body"), _Proc(0, _obj_body("01OLD", nodes))),
            (_has("issues/42", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    objectives.supersede_objective_issue(
        old_number=42,
        title="t",
        prose="p",
        repo_root=ROOT,
        run_id="01RID",
        roadmap_nodes=nodes,
    )
    new_body = next(
        b
        for b in rec.body_files
        if (h := plan.find_metadata_block(b, objective.OBJECTIVE_HEADER_KEY)) is not None
        and h.get("supersedes") == "#42"
    )
    # The successor header is byte-identical to the pre-origin shape (the §8.42 rule).
    assert "origin" not in new_body


def test_supersede_objective_issue_junk_stored_origin_raises(monkeypatch):
    # Fail-closed BEFORE the successor POST: a junk stored origin never orphans a half-made
    # successor issue.
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    junk_body = _obj_header("01OLD").replace("superseded_by: null", "origin: weird")
    rec = _GhDispatch(
        [
            (_has("issues", "GET"), _Proc(0, "[]")),
            (_has("issues/42", ".body"), _Proc(0, junk_body)),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(github.GitHubError, match="unknown objective origin"):
        objectives.supersede_objective_issue(
            old_number=42,
            title="t",
            prose="p",
            repo_root=ROOT,
            run_id="01RID",
            roadmap_nodes=nodes,
        )
    assert rec.method_calls("POST") == 0  # no successor issue was created


def test_supersede_objective_issue_malformed_old_header_raises(monkeypatch):
    # Absent vs malformed (the lookup's own discrimination): a present-yet-unparseable old
    # header is genuine uncertainty about the predecessor's origin — raise BEFORE any
    # successor POST, never silently carry nothing.
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    broken = "<!-- perk:metadata-block:objective-header -->\nno closing marker"
    rec = _GhDispatch(
        [
            (_has("issues", "GET"), _Proc(0, "[]")),
            (_has("issues/42", ".body"), _Proc(0, broken)),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(github.GitHubError, match="present but malformed"):
        objectives.supersede_objective_issue(
            old_number=42,
            title="t",
            prose="p",
            repo_root=ROOT,
            run_id="01RID",
            roadmap_nodes=nodes,
        )
    assert rec.method_calls("POST") == 0  # no successor issue was created


def test_supersede_objective_issue_header_less_old_body_carries_nothing(monkeypatch):
    # A header-LESS old body (no block at all) is the tolerated carry-nothing arm — the
    # successor is still created, origin-less.
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    rec = _GhDispatch(
        [
            (_has("issues", "GET"), _Proc(0, "[]")),
            (_has("{repo}/labels", "POST"), _Proc(0, "{}")),
            (_has("comments", "POST"), _Proc(0, json.dumps({"id": 555}))),
            (
                _has("repos/{owner}/{repo}/issues", "POST"),
                _Proc(0, json.dumps({"number": 200, "url": "u/200"})),
            ),
            (_has("issues/200", ".body"), _Proc(0, _obj_body("01RID", nodes))),
            (_has("issues/200", "PATCH"), _Proc(0, "{}")),
            (_has("issues/42", ".body"), _Proc(0, "just human prose, no perk blocks")),
            (_has("issues/42", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    created = objectives.supersede_objective_issue(
        old_number=42,
        title="t",
        prose="p",
        repo_root=ROOT,
        run_id="01RID",
        roadmap_nodes=nodes,
    )
    assert created.number == 200
    new_body = next(
        b
        for b in rec.body_files
        if (h := plan.find_metadata_block(b, objective.OBJECTIVE_HEADER_KEY)) is not None
        and h.get("supersedes") == "#42"
    )
    assert "origin" not in new_body


def test_get_objective_parses_header_and_nodes(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.DONE),
        objective.ObjectiveNode(id="1.2", description="B", status=objective.NodeStatus.PENDING),
    ]
    issue = {
        "number": 5,
        "title": "Obj",
        "body": _obj_body("01RID", nodes, comment_id=9),
        "url": "u/5",
        "state": "OPEN",
    }
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issue", "view"), _Proc(0, json.dumps(issue)))])
    )
    state = objectives.get_objective(number=5, repo_root=ROOT)
    assert state is not None and state.title == "Obj"
    assert [n.id for n in state.nodes] == ["1.1", "1.2"]
    assert state.header["objective_comment_id"] == 9
    assert state.state == "open"


def test_get_objective_reads_the_closed_lifecycle_state(monkeypatch):
    issue = {
        "number": 5,
        "title": "Obj",
        "body": _obj_body("01RID", []),
        "url": "u/5",
        "state": "CLOSED",
    }
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issue", "view"), _Proc(0, json.dumps(issue)))])
    )
    state = objectives.get_objective(number=5, repo_root=ROOT)
    assert state is not None and state.state == "closed"


def test_get_objective_not_found(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issue", "view"), _Proc(1, stderr="not found"))])
    )
    assert objectives.get_objective(number=404, repo_root=ROOT) is None


def test_update_objective_node_updates_body_and_comment(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING),
        objective.ObjectiveNode(id="1.2", description="B", status=objective.NodeStatus.PENDING),
    ]
    issue_body = _obj_body("01RID", nodes, comment_id=555)
    comment_body = objective.render_body_comment(nodes, prose="prose here")
    rec = _GhDispatch(
        [
            (_has("issues/comments/555", ".body"), _Proc(0, comment_body)),
            (_has("issues/comments/555", "PATCH"), _Proc(0, "{}")),
            (_has("issues/123", "PATCH"), _Proc(0, "{}")),
            (_has("issues/123", ".body"), _Proc(0, issue_body)),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    result = objectives.update_objective_node(
        number=123, node_id="1.2", status=objective.NodeStatus.IN_PROGRESS, pr="#9", repo_root=ROOT
    )
    assert result.comment_updated is True and result.dry_run is False
    # the PATCHed roadmap shows 1.2 in_progress with pr #9 (explicit status, not inferred)
    body_patch = rec.body_files[0]
    parsed, _ = objective.parse_roadmap_nodes(body_patch)
    n = next(x for x in parsed if x.id == "1.2")
    assert n.status is objective.NodeStatus.IN_PROGRESS and n.pr == "#9"


def test_update_objective_node_not_found_raises(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    issue_body = _obj_body("01RID", nodes, comment_id=555)
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issues/123", ".body"), _Proc(0, issue_body))])
    )
    with pytest.raises(github.GitHubError, match="not found"):
        objectives.update_objective_node(
            number=123, node_id="9.9", status=objective.NodeStatus.DONE, repo_root=ROOT
        )


def test_update_objective_node_dry_run_does_not_patch(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    issue_body = _obj_body("01RID", nodes, comment_id=555)
    rec = _GhDispatch([(_has("issues/123", ".body"), _Proc(0, issue_body))])
    monkeypatch.setattr(subprocess, "run", rec)
    result = objectives.update_objective_node(
        number=123, node_id="1.1", status=objective.NodeStatus.DONE, repo_root=ROOT, dry_run=True
    )
    assert result.dry_run is True and rec.method_calls("PATCH") == 0


def test_add_objective_node_inserts_and_rerenders(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING),
        objective.ObjectiveNode(id="1.2", description="B", status=objective.NodeStatus.PENDING),
    ]
    issue_body = _obj_body("01RID", nodes, comment_id=555)
    comment_body = objective.render_body_comment(nodes, prose="prose here")
    rec = _GhDispatch(
        [
            (_has("issues/comments/555", ".body"), _Proc(0, comment_body)),
            (_has("issues/comments/555", "PATCH"), _Proc(0, "{}")),
            (_has("issues/123", "PATCH"), _Proc(0, "{}")),
            (_has("issues/123", ".body"), _Proc(0, issue_body)),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    result = objectives.add_objective_node(number=123, phase=1, description="Gamma", repo_root=ROOT)
    assert result.node_id == "1.3"
    assert result.comment_updated is True and result.dry_run is False
    body_patch = rec.body_files[0]
    parsed, _ = objective.parse_roadmap_nodes(body_patch)
    assert [n.id for n in parsed] == ["1.1", "1.2", "1.3"]
    assert next(n for n in parsed if n.id == "1.3").description == "Gamma"


def test_add_objective_node_dry_run_does_not_patch(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    issue_body = _obj_body("01RID", nodes, comment_id=555)
    rec = _GhDispatch([(_has("issues/123", ".body"), _Proc(0, issue_body))])
    monkeypatch.setattr(subprocess, "run", rec)
    result = objectives.add_objective_node(
        number=123, phase=1, description="Gamma", repo_root=ROOT, dry_run=True
    )
    assert result.node_id == "1.2"
    assert result.dry_run is True and rec.method_calls("PATCH") == 0


def test_add_objective_node_collision_raises(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    issue_body = _obj_body("01RID", nodes, comment_id=555)
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issues/123", ".body"), _Proc(0, issue_body))])
    )
    # Force the defensive id-collision branch.
    monkeypatch.setattr(objective, "add_node", lambda *a, **k: None)
    with pytest.raises(github.GitHubError, match="collision"):
        objectives.add_objective_node(number=123, phase=1, description="Gamma", repo_root=ROOT)


def test_add_objective_node_bad_roadmap_raises(monkeypatch):
    # A body whose roadmap block is present but fails to parse.
    broken = "<!-- perk:metadata-block:objective-roadmap -->\n```yaml\nnodes: [oops\n```\n"
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issues/123", ".body"), _Proc(0, broken))])
    )
    with pytest.raises(github.GitHubError, match="invalid objective roadmap"):
        objectives.add_objective_node(number=123, phase=1, description="Gamma", repo_root=ROOT)


def test_update_objective_body_splices_reconcilable_region(monkeypatch):
    nodes = [objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.DONE)]
    issue_body = _obj_body("01RID", nodes, comment_id=777)
    comment_body = objective.render_body_comment(nodes, prose="Old prose.")
    rec = _GhDispatch(
        [
            (_has("issues/comments/777", "PATCH"), _Proc(0, "{}")),
            (_has("issues/comments/777", ".body"), _Proc(0, comment_body)),
            (_has("issues/123", ".body"), _Proc(0, issue_body)),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    result = objectives.update_objective_body(number=123, prose="New prose.", repo_root=ROOT)
    assert result.updated is True and result.comment_id == 777 and result.dry_run is False
    patched = rec.body_files[-1]
    assert "New prose." in patched and "Old prose." not in patched
    # the Mechanical table block is preserved
    assert objective.ROADMAP_TABLE_MARKER_START in patched


def test_update_objective_body_dry_run_does_not_patch(monkeypatch):
    nodes = [objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.DONE)]
    issue_body = _obj_body("01RID", nodes, comment_id=777)
    comment_body = objective.render_body_comment(nodes, prose="Old prose.")
    rec = _GhDispatch(
        [
            (_has("issues/comments/777", ".body"), _Proc(0, comment_body)),
            (_has("issues/123", ".body"), _Proc(0, issue_body)),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    result = objectives.update_objective_body(
        number=123, prose="New prose.", repo_root=ROOT, dry_run=True
    )
    assert result.updated is False and result.dry_run is True
    assert rec.method_calls("PATCH") == 0


def test_update_objective_body_no_comment_raises(monkeypatch):
    nodes = [objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.DONE)]
    issue_body = _obj_body("01RID", nodes, comment_id=None)  # no objective_comment_id
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issues/123", ".body"), _Proc(0, issue_body))])
    )
    with pytest.raises(github.GitHubError, match="no body comment"):
        objectives.update_objective_body(number=123, prose="x", repo_root=ROOT)


def test_update_objective_body_no_region_raises(monkeypatch):
    nodes = [objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.DONE)]
    issue_body = _obj_body("01RID", nodes, comment_id=777)
    # a legacy comment with no reconcilable markers
    legacy_comment = "<!-- perk:roadmap-table -->\ntable\n<!-- /perk:roadmap-table -->\n\nprose"
    monkeypatch.setattr(
        subprocess,
        "run",
        _GhDispatch(
            [
                (_has("issues/comments/777", ".body"), _Proc(0, legacy_comment)),
                (_has("issues/123", ".body"), _Proc(0, issue_body)),
            ]
        ),
    )
    with pytest.raises(github.GitHubError, match="no reconcilable region"):
        objectives.update_objective_body(number=123, prose="x", repo_root=ROOT)


def test_update_objective_header_rejects_unknown_field(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(0, _obj_header("01RID")))
    with pytest.raises(github.GitHubError, match="unknown objective-header field"):
        objectives.update_objective_header(number=5, fields={"bogus": "x"}, repo_root=ROOT)


def test_update_objective_header_rejects_origin_merge(monkeypatch):
    # `origin` is deliberately OUTSIDE OBJECTIVE_HEADER_FIELDS: create/supersede-only by
    # structure — the existing LBYL check rejects any post-create origin write.
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(0, _obj_header("01RID")))
    with pytest.raises(github.GitHubError, match="unknown objective-header field"):
        objectives.update_objective_header(
            number=5, fields={"origin": "learn-dream"}, repo_root=ROOT
        )


def test_update_objective_header_merges_dream_report(monkeypatch):
    # `dream_report` (§8.64) is merge-writable by design (recorded AFTER create — the
    # activation-last ordering), unlike `origin`; the write merges into the parsed existing
    # mapping, preserving a stored origin untouched.
    stored = _obj_header("01RID", origin="learn-dream")
    rec = _GhDispatch(
        [
            (_has("issues/5", ".body"), _Proc(0, stored)),
            (_has("issues/5", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    objectives.update_objective_header(number=5, fields={"dream_report": "5"}, repo_root=ROOT)
    patched = rec.body_files[-1]
    header = plan.find_metadata_block(patched, objective.OBJECTIVE_HEADER_KEY)
    assert header is not None
    assert header["dream_report"] == "5" and header["origin"] == "learn-dream"


def test_update_objective_header_unrelated_merge_preserves_stored_origin(monkeypatch):
    # The round-trip regression: the writers merge into the PARSED existing mapping, so a
    # stored origin survives unrelated header merges untouched.
    stored = _obj_header("01RID", origin="learn-dream")
    rec = _GhDispatch(
        [
            (_has("issues/5", ".body"), _Proc(0, stored)),
            (_has("issues/5", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    objectives.update_objective_header(number=5, fields={"status": "complete"}, repo_root=ROOT)
    patched = rec.body_files[-1]
    header = plan.find_metadata_block(patched, objective.OBJECTIVE_HEADER_KEY)
    assert header is not None
    assert header["status"] == "complete" and header["origin"] == "learn-dream"


# --------------------------------------------------- the open-by-origin lookup (§8.24)


def _origin_row(number: int, run_id: str, *, origin: str | None = None) -> dict:
    return {
        "number": number,
        "html_url": f"u/{number}",
        "body": _obj_header(run_id, origin=origin),
    }


def _slurped(*pages: list) -> str:
    """A ``gh api --paginate --slurp`` payload: an array of per-page row arrays."""
    return json.dumps(list(pages))


def test_list_label_issues_all_pages_flattens_slurped_pages(monkeypatch):
    page_one = [_origin_row(i, f"01R{i}") for i in range(3)]
    page_two = [_origin_row(200, "01R200")]
    rec = _GhRecorder(get=_Proc(0, stdout=_slurped(page_one, page_two)))
    monkeypatch.setattr(subprocess, "run", rec)
    rows = plans._list_label_issues_all_pages(
        objective.OBJECTIVE_LABEL, repo_root=ROOT, what="failed"
    )
    assert [r["number"] for r in rows] == [0, 1, 2, 200]
    # ONE argv: gh owns the page loop (native --paginate --slurp), per_page=100 per request.
    [call] = rec.calls
    assert "--paginate" in call and "--slurp" in call
    assert "per_page=100" in call


def test_list_label_issues_all_pages_raises_on_request_failure(monkeypatch):
    # A failed request raises — a partial scan is never reported as complete.
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(1, stderr="HTTP 500")))
    with pytest.raises(github.GitHubError):
        plans._list_label_issues_all_pages(objective.OBJECTIVE_LABEL, repo_root=ROOT, what="failed")


def test_list_label_issues_all_pages_raises_on_empty_output(monkeypatch):
    # Fail-closed: empty stdout is NOT an empty population (no "[]" default — only a genuinely
    # parsed empty page reads as empty).
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(0, stdout="")))
    with pytest.raises(github.GitHubError):
        plans._list_label_issues_all_pages(objective.OBJECTIVE_LABEL, repo_root=ROOT, what="failed")


def test_list_label_issues_all_pages_raises_on_non_list_payload(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(0, stdout='{"oops": 1}')))
    with pytest.raises(github.GitHubError, match="expected an array of pages"):
        plans._list_label_issues_all_pages(objective.OBJECTIVE_LABEL, repo_root=ROOT, what="failed")


def test_list_label_issues_all_pages_raises_on_non_list_page(monkeypatch):
    # A flat row array (e.g. --slurp silently dropped) is an unexpected shape — raise, never
    # misread rows as pages.
    monkeypatch.setattr(
        subprocess, "run", _GhRecorder(get=_Proc(0, stdout=json.dumps([_origin_row(1, "01R1")])))
    )
    with pytest.raises(github.GitHubError, match="expected a page array"):
        plans._list_label_issues_all_pages(objective.OBJECTIVE_LABEL, repo_root=ROOT, what="failed")


def test_find_objective_issue_by_origin_matches_on_a_later_page(monkeypatch):
    # The pagination integration check: the authoritative scan finds a match beyond the first
    # slurped page.
    page_one = [_origin_row(i, f"01R{i}") for i in range(100)]
    page_two = [_origin_row(200, "01R200", origin="learn-dream")]
    monkeypatch.setattr(
        subprocess, "run", _GhRecorder(get=_Proc(0, stdout=_slurped(page_one, page_two)))
    )
    found = objectives.find_objective_issue_by_origin(
        origin="learn-dream", exclude_run_id=None, repo_root=ROOT
    )
    assert found is not None
    assert found.number == 200 and found.url == "u/200" and found.existed is True


def test_find_objective_issue_by_origin_row_guards_skip(monkeypatch):
    rows = [
        "not-a-dict",
        {"html_url": "u/no-number", "body": _obj_header("01A", origin="learn-dream")},
        {
            "number": 2,
            "html_url": "u/2",
            "body": _obj_header("01B", origin="learn-dream"),
            "pull_request": {},
        },
        {"number": 3, "html_url": "u/3", "body": None},  # non-str body → header-absent
        {"number": 4, "html_url": "u/4", "body": "no header block here"},  # header-less → skip
        _origin_row(5, "01C"),  # origin absent → non-match
        _origin_row(6, "01D", origin="learn-dream"),  # the surviving match
    ]
    rec = _GhRecorder(get=_Proc(0, stdout=_slurped(rows)))
    monkeypatch.setattr(subprocess, "run", rec)
    found = objectives.find_objective_issue_by_origin(
        origin="learn-dream", exclude_run_id=None, repo_root=ROOT
    )
    assert found is not None and found.number == 6


def test_find_objective_issue_by_origin_skips_a_different_known_origin(monkeypatch):
    # A known-but-different origin is a non-match (skip), never a raise.
    rows = [_origin_row(5, "01C", origin="learn-dream")]
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(0, stdout=_slurped(rows))))
    assert (
        objectives.find_objective_issue_by_origin(
            origin="some-other-origin", exclude_run_id=None, repo_root=ROOT
        )
        is None
    )


def test_find_objective_issue_by_origin_malformed_header_raises(monkeypatch):
    # Present-but-malformed = genuine uncertainty about a real objective — never
    # authoritatively-none.
    broken = "<!-- perk:metadata-block:objective-header -->\nno closing marker"
    rows = [{"number": 5, "html_url": "u/5", "body": broken}]
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(0, stdout=_slurped(rows))))
    with pytest.raises(github.GitHubError, match="present but malformed"):
        objectives.find_objective_issue_by_origin(
            origin="learn-dream", exclude_run_id=None, repo_root=ROOT
        )


def test_find_objective_issue_by_origin_unknown_origin_raises(monkeypatch):
    rows = [_origin_row(5, "01C", origin=None)]
    rows[0]["body"] = _obj_header("01C").replace("superseded_by: null", "origin: weird")
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(0, stdout=_slurped(rows))))
    with pytest.raises(github.GitHubError, match="unknown objective origin"):
        objectives.find_objective_issue_by_origin(
            origin="learn-dream", exclude_run_id=None, repo_root=ROOT
        )


def test_find_objective_issue_by_origin_honors_exclude_run_id(monkeypatch):
    # The caller-exclusion: the consumer's own run is skipped; a FOREIGN match is still found.
    rows = [
        _origin_row(5, "01MINE", origin="learn-dream"),
        _origin_row(6, "01FOREIGN", origin="learn-dream"),
    ]
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(0, stdout=_slurped(rows))))
    found = objectives.find_objective_issue_by_origin(
        origin="learn-dream", exclude_run_id="01MINE", repo_root=ROOT
    )
    assert found is not None and found.number == 6


@pytest.mark.parametrize(
    ("mutate", "exclude"),
    [
        # run_id line removed entirely → a missing run_id is never treated as excluded
        (lambda body: body.replace("run_id: 01CAND\n", ""), "01CAND"),
        # a non-str run_id whose string form EQUALS exclude_run_id → still never excluded
        (lambda body: body.replace("run_id: 01CAND", "run_id: 42"), "42"),
    ],
)
def test_find_objective_issue_by_origin_never_excludes_missing_or_non_str_run_id(
    monkeypatch, mutate, exclude
):
    # The fail-closed exclusion branch: only a string run_id equal to exclude_run_id is the
    # caller's own run — malformed metadata must surface as a conflict, never self-exclude.
    body = mutate(_obj_header("01CAND", origin="learn-dream"))
    rows = [{"number": 5, "html_url": "u/5", "body": body}]
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(0, stdout=_slurped(rows))))
    found = objectives.find_objective_issue_by_origin(
        origin="learn-dream", exclude_run_id=exclude, repo_root=ROOT
    )
    assert found is not None and found.number == 5


def test_find_objective_issue_by_origin_none_on_no_match(monkeypatch):
    rows = [_origin_row(5, "01A"), _origin_row(6, "01B")]
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(0, stdout=_slurped(rows))))
    assert (
        objectives.find_objective_issue_by_origin(
            origin="learn-dream", exclude_run_id=None, repo_root=ROOT
        )
        is None
    )


def test_find_objective_issue_by_origin_raises_on_infra_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(1, stderr="HTTP 500")))
    with pytest.raises(github.GitHubError):
        objectives.find_objective_issue_by_origin(
            origin="learn-dream", exclude_run_id=None, repo_root=ROOT
        )
