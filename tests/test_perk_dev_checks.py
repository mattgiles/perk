"""Deterministic-checker tests (perk_dev.audit.checks).

Per-checker units over synthetic branch-threaded sessions: a local fixture builder writes
JSONL (entries carrying `id`/`parentId`/`toolCallId`) into tmp_path and parses through the
real read edge, so pairing and branch machinery are exercised end to end.
"""

import json
from pathlib import Path

import pytest
from perk_dev.audit.checks import CHECKERS, CheckResult
from perk_dev.audit.expectations import load_catalog

from perk.learn.session_jsonl import ParsedSession, parse_session_jsonl

# ------------------------------------------------------------------------- fixtures

BINDING_HEADER = "The following skill binding(s) apply here:"


def _nudge(skill: str) -> str:
    return f"Follow the `{skill}` skill (read `.agents/skills/{skill}/SKILL.md`)."


def _ws(eid: str, parent: str | None, **data: object) -> dict[str, object]:
    return {
        "type": "custom",
        "id": eid,
        "parentId": parent,
        "customType": "perk:workflow-state",
        "data": data,
    }


def _user(eid: str, parent: str | None, text: str) -> dict[str, object]:
    return {
        "type": "message",
        "id": eid,
        "parentId": parent,
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def _custom(
    eid: str, parent: str | None, content: str, custom_type: str = "perk:binding-context"
) -> dict[str, object]:
    return {
        "type": "custom_message",
        "id": eid,
        "parentId": parent,
        "customType": custom_type,
        "content": content,
    }


def _call(
    eid: str,
    parent: str | None,
    tool: str,
    args: dict[str, object],
    call_id: str | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {"type": "toolCall", "name": tool, "arguments": args}
    if call_id is not None:
        item["id"] = call_id
    return {
        "type": "message",
        "id": eid,
        "parentId": parent,
        "message": {"role": "assistant", "content": [item]},
    }


def _multi(
    eid: str, parent: str | None, specs: list[tuple[str, dict[str, object]]]
) -> dict[str, object]:
    """One assistant entry batching several tool calls (order = tool-call position)."""
    content: list[dict[str, object]] = [
        {"type": "toolCall", "id": f"c-{eid}-{n}", "name": tool, "arguments": args}
        for n, (tool, args) in enumerate(specs)
    ]
    return {
        "type": "message",
        "id": eid,
        "parentId": parent,
        "message": {"role": "assistant", "content": content},
    }


def _result(
    eid: str,
    parent: str | None,
    tool: str,
    *,
    call_id: str | None = None,
    is_error: bool = False,
    text: str = "ok",
) -> dict[str, object]:
    msg: dict[str, object] = {
        "role": "toolResult",
        "toolName": tool,
        "isError": is_error,
        "content": [{"type": "text", "text": text}],
    }
    if call_id is not None:
        msg["toolCallId"] = call_id
    return {"type": "message", "id": eid, "parentId": parent, "message": msg}


def _exec(
    prefix: str,
    parent: str | None,
    tool: str,
    args: dict[str, object],
    *,
    is_error: bool = False,
    result_text: str = "ok",
) -> list[dict[str, object]]:
    """One paired execution as a linear call+result pair; the result's id is `<prefix>r`."""
    call_id = f"c-{prefix}"
    return [
        _call(f"{prefix}a", parent, tool, args, call_id=call_id),
        _result(
            f"{prefix}r",
            f"{prefix}a",
            tool,
            call_id=call_id,
            is_error=is_error,
            text=result_text,
        ),
    ]


def _parse(tmp_path: Path, entries: list[dict[str, object]]) -> ParsedSession:
    lines = [json.dumps({"type": "session", "id": "s", "cwd": "/repo"})]
    lines.extend(json.dumps(e) for e in entries)
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return parse_session_jsonl(path)


def _index_of(parsed: ParsedSession, eid: str) -> int:
    matches = [e.index for e in parsed.entries if e.entry_id == eid]
    assert len(matches) == 1, f"{eid}: {len(matches)} entries"
    return matches[0]


WARM_CLAIM = CHECKERS["objective-plan.warm-claim-before-authoring"]
DRAFT_BEFORE_REVIEW = CHECKERS["plan.draft-before-review"]
NUDGE_READ = CHECKERS["bindings.nudge-skill-read"]
LEARNED_PLAN = CHECKERS["plan.learned-docs-first-stop"]
LEARNED_AUTHOR = CHECKERS["objective-author.learned-docs-first-stop"]
CLASSIFIER_FIRST = CHECKERS["address.classifier-child-first"]
NO_MUTATION = CHECKERS["read-only.no-worktree-mutation"]


def _assert_violated(result: CheckResult) -> None:
    assert result.status == "violated"
    assert result.entries != (), "a violated result must cite entries"


# ------------------------------------------------------------------ registry


def test_registry_matches_committed_deterministic_ids():
    deterministic = {e.id for e in load_catalog().expectations if e.tier == "deterministic"}
    assert set(CHECKERS) == deterministic
    assert deterministic == {
        "objective-plan.warm-claim-before-authoring",
        "plan.draft-before-review",
        "bindings.nudge-skill-read",
        "plan.learned-docs-first-stop",
        "objective-author.learned-docs-first-stop",
        "address.classifier-child-first",
        "read-only.no-worktree-mutation",
    }


# ------------------------------------------------------------------ warm claim


def test_warm_claim_satisfied_on_branch(tmp_path: Path):
    entries = [
        _user("u0", None, "plan node 2.1"),
        *_exec("n1", "u0", "objective_node", {"node": "2.1", "status": "planning"}),
        _call("d1", "n1r", "plan_draft", {"content": "# plan"}),
    ]
    result = WARM_CLAIM(_parse(tmp_path, entries))
    assert result.status == "satisfied"


def test_warm_claim_violated_without_claim(tmp_path: Path):
    parsed = _parse(
        tmp_path,
        [_user("u0", None, "go"), _call("d1", "u0", "plan_draft", {})],
    )
    result = WARM_CLAIM(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "d1"),)


def test_warm_claim_abandoned_fork_claim_does_not_count(tmp_path: Path):
    # The claim lives on a sibling fork off u0 — NOT an ancestor of the authoring call.
    entries = [
        _user("u0", None, "go"),
        *_exec("n1", "u0", "objective_node", {"node": "2.1", "status": "planning"}),
        _call("d1", "u0", "plan_draft", {}),
    ]
    parsed = _parse(tmp_path, entries)
    result = WARM_CLAIM(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "d1"),)


def test_warm_claim_is_args_validated(tmp_path: Path):
    # A successful objective_node execution with a non-planning status is NOT a claim.
    entries = [
        _user("u0", None, "go"),
        *_exec("n1", "u0", "objective_node", {"node": "2.1", "status": "done"}),
        _call("d1", "n1r", "plan_draft", {}),
    ]
    _assert_violated(WARM_CLAIM(_parse(tmp_path, entries)))


def test_warm_claim_failed_claim_does_not_count(tmp_path: Path):
    entries = [
        _user("u0", None, "go"),
        *_exec("n1", "u0", "objective_node", {"status": "planning"}, is_error=True),
        _call("d1", "n1r", "plan_draft", {}),
    ]
    _assert_violated(WARM_CLAIM(_parse(tmp_path, entries)))


def test_warm_claim_pending_execution_is_unchecked(tmp_path: Path):
    # The claim call has no paired result (a live session mid-claim): the absence verdict
    # is blocked — unchecked, never a definitive violation.
    entries = [
        _user("u0", None, "go"),
        _call("n1a", "u0", "objective_node", {"node": "2.1", "status": "planning"}, "c-n1"),
        _call("d1", "n1a", "plan_draft", {}),
    ]
    result = WARM_CLAIM(_parse(tmp_path, entries))
    assert result.status == "unchecked"
    assert "in flight" in result.detail


def test_warm_claim_mismatched_result_id_is_unchecked(tmp_path: Path):
    # The only objective_node result carries a foreign toolCallId: the call stays
    # unpaired (pending), the stray result is dropped — not satisfied, not violated.
    entries = [
        _user("u0", None, "go"),
        _call("n1a", "u0", "objective_node", {"status": "planning"}, "c-n1"),
        _result("n1r", "n1a", "objective_node", call_id="c-other"),
        _call("d1", "n1r", "plan_draft", {}),
    ]
    result = WARM_CLAIM(_parse(tmp_path, entries))
    assert result.status == "unchecked"


def test_warm_claim_not_exercised_without_authoring(tmp_path: Path):
    entries = [
        _user("u0", None, "hi"),
        *_exec("n1", "u0", "objective_node", {"status": "planning"}),
    ]
    result = WARM_CLAIM(_parse(tmp_path, entries))
    assert result.status == "not-exercised"
    assert "no authoring" in result.detail


# ---------------------------------------------------------- draft before review


def test_draft_before_review_satisfied(tmp_path: Path):
    entries = [
        _user("u0", None, "plan it"),
        _call("d1", "u0", "plan_draft", {}),
        _call("r1", "d1", "plan_review", {}),
    ]
    assert DRAFT_BEFORE_REVIEW(_parse(tmp_path, entries)).status == "satisfied"


def test_review_without_any_draft_violates(tmp_path: Path):
    parsed = _parse(tmp_path, [_user("u0", None, "go"), _call("r1", "u0", "plan_review", {})])
    result = DRAFT_BEFORE_REVIEW(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "r1"),)


def test_denied_review_rereviewed_without_redraft_violates(tmp_path: Path):
    entries = [
        _user("u0", None, "go"),
        _call("d1", "u0", "plan_draft", {}),
        *_exec(
            "r1",
            "d1",
            "plan_review",
            {},
            result_text="plan DENIED — revise per this feedback and call plan_review again.",
        ),
        _call("r2", "r1r", "plan_review", {}),
    ]
    parsed = _parse(tmp_path, entries)
    result = DRAFT_BEFORE_REVIEW(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "r2"),)


def test_denied_review_with_redraft_between_satisfies(tmp_path: Path):
    entries = [
        _user("u0", None, "go"),
        _call("d1", "u0", "plan_draft", {}),
        *_exec("r1", "d1", "plan_review", {}, result_text="plan DENIED — revise."),
        _call("d2", "r1r", "plan_draft", {}),
        _call("r2", "d2", "plan_review", {}),
    ]
    assert DRAFT_BEFORE_REVIEW(_parse(tmp_path, entries)).status == "satisfied"


def test_review_batched_before_draft_in_same_entry_violates(tmp_path: Path):
    # One assistant entry can batch several tool calls: a plan_draft at a LATER position
    # than the plan_review in the same entry is not a preceding draft.
    entries = [
        _user("u0", None, "go"),
        _multi("m1", "u0", [("plan_review", {}), ("plan_draft", {})]),
    ]
    parsed = _parse(tmp_path, entries)
    result = DRAFT_BEFORE_REVIEW(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "m1"),)


def test_draft_batched_before_review_in_same_entry_satisfies(tmp_path: Path):
    entries = [
        _user("u0", None, "go"),
        _multi("m1", "u0", [("plan_draft", {}), ("plan_review", {})]),
    ]
    assert DRAFT_BEFORE_REVIEW(_parse(tmp_path, entries)).status == "satisfied"


def test_sibling_draft_does_not_satisfy_review(tmp_path: Path):
    # The draft lives on an abandoned sibling fork — not on the review's ancestor chain.
    entries = [
        _user("u0", None, "go"),
        _call("d1", "u0", "plan_draft", {}),
        _call("r1", "u0", "plan_review", {}),
    ]
    parsed = _parse(tmp_path, entries)
    result = DRAFT_BEFORE_REVIEW(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "r1"),)


def test_sibling_denial_does_not_poison_surviving_branch(tmp_path: Path):
    # The denied review lives on an abandoned fork off the draft; the surviving branch's
    # review sees the draft ancestor with no denial in between.
    entries = [
        _user("u0", None, "go"),
        _call("d1", "u0", "plan_draft", {}),
        *_exec("r1", "d1", "plan_review", {}, result_text="plan DENIED — revise."),
        _call("r2", "d1", "plan_review", {}),
    ]
    assert DRAFT_BEFORE_REVIEW(_parse(tmp_path, entries)).status == "satisfied"


def test_approved_review_result_is_not_a_denial(tmp_path: Path):
    entries = [
        _user("u0", None, "go"),
        _call("d1", "u0", "plan_draft", {}),
        *_exec("r1", "d1", "plan_review", {}, result_text="plan APPROVED by reviewer."),
        _call("r2", "r1r", "plan_review", {}),
    ]
    assert DRAFT_BEFORE_REVIEW(_parse(tmp_path, entries)).status == "satisfied"


def test_draft_before_review_not_exercised(tmp_path: Path):
    entries = [_user("u0", None, "hi"), _call("d1", "u0", "plan_draft", {})]
    assert DRAFT_BEFORE_REVIEW(_parse(tmp_path, entries)).status == "not-exercised"


# -------------------------------------------------------------------- nudge read


def _delivery(eid: str, parent: str | None, skill: str) -> dict[str, object]:
    return _user(eid, parent, f"{BINDING_HEADER}\n\n{_nudge(skill)}")


def test_nudge_read_tool_uptake(tmp_path: Path):
    entries = [
        _delivery("u0", None, "perk-implement"),
        *_exec("e1", "u0", "read", {"path": "/repo/.agents/skills/perk-implement/SKILL.md"}),
    ]
    assert NUDGE_READ(_parse(tmp_path, entries)).status == "satisfied"


def test_nudge_failed_read_is_not_uptake(tmp_path: Path):
    entries = [
        _delivery("u0", None, "perk-implement"),
        *_exec(
            "e1",
            "u0",
            "read",
            {"path": "/repo/.agents/skills/perk-implement/SKILL.md"},
            is_error=True,
        ),
    ]
    parsed = _parse(tmp_path, entries)
    result = NUDGE_READ(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "u0"),)
    assert "perk-implement" in result.detail


def test_nudge_bak_suffix_is_not_uptake(tmp_path: Path):
    entries = [
        _delivery("u0", None, "perk-implement"),
        *_exec("e1", "u0", "read", {"path": "/x/.agents/skills/perk-implement/SKILL.md.bak"}),
    ]
    _assert_violated(NUDGE_READ(_parse(tmp_path, entries)))


def test_nudge_bash_reader_uptake(tmp_path: Path):
    entries = [
        _delivery("u0", None, "perk-implement"),
        *_exec("e1", "u0", "bash", {"command": "cat .agents/skills/perk-implement/SKILL.md"}),
    ]
    assert NUDGE_READ(_parse(tmp_path, entries)).status == "satisfied"


def test_nudge_sed_n_reader_uptake(tmp_path: Path):
    entries = [
        _delivery("u0", None, "perk-implement"),
        *_exec(
            "e1",
            "u0",
            "bash",
            {"command": "sed -n '1,40p' .agents/skills/perk-implement/SKILL.md"},
        ),
    ]
    assert NUDGE_READ(_parse(tmp_path, entries)).status == "satisfied"


def test_nudge_mention_only_bash_is_not_uptake(tmp_path: Path):
    entries = [
        _delivery("u0", None, "perk-implement"),
        *_exec("e1", "u0", "bash", {"command": "ls .agents/skills/perk-implement/SKILL.md"}),
        *_exec("e2", "e1r", "bash", {"command": "echo .agents/skills/perk-implement/SKILL.md"}),
    ]
    _assert_violated(NUDGE_READ(_parse(tmp_path, entries)))


def test_nudge_skill_invocation_uptake(tmp_path: Path):
    entries = [
        _delivery("u0", None, "perk-implement"),
        _user(
            "u1",
            "u0",
            '<skill name="perk-implement" location="/x/SKILL.md">procedure body</skill>',
        ),
    ]
    assert NUDGE_READ(_parse(tmp_path, entries)).status == "satisfied"


def test_transclude_delivery_is_uptake(tmp_path: Path):
    entries = [
        _custom("c0", None, "Skill `perk-implement` (inlined for `stage:implement`):\n\nbody")
    ]
    assert NUDGE_READ(_parse(tmp_path, entries)).status == "satisfied"


def test_nudge_pending_read_is_unchecked(tmp_path: Path):
    # The exact-path read has no paired result yet (a live session mid-read): the
    # absence verdict is blocked.
    entries = [
        _delivery("u0", None, "perk-implement"),
        _call("e1", "u0", "read", {"path": "/repo/.agents/skills/perk-implement/SKILL.md"}, "c-1"),
    ]
    result = NUDGE_READ(_parse(tmp_path, entries))
    assert result.status == "unchecked"
    assert "perk-implement" in result.detail


def test_nudge_pending_unrelated_read_still_violates(tmp_path: Path):
    # A pending read of some OTHER path cannot flip the verdict — still violated.
    entries = [
        _delivery("u0", None, "perk-implement"),
        _call("e1", "u0", "read", {"path": "/repo/README.md"}, "c-1"),
    ]
    _assert_violated(NUDGE_READ(_parse(tmp_path, entries)))


def test_nudge_sibling_uptake_counts_file_wide(tmp_path: Path):
    # Uptake evidence is presence-anywhere: a read on an abandoned sibling fork counts.
    entries = [
        _delivery("u0", None, "perk-implement"),
        *_exec("e1", "u0", "read", {"path": "/repo/.agents/skills/perk-implement/SKILL.md"}),
        _user("u1", "u0", "carry on"),  # the surviving branch
    ]
    assert NUDGE_READ(_parse(tmp_path, entries)).status == "satisfied"


def test_nudge_not_exercised_without_delivery(tmp_path: Path):
    entries = [_user("u0", None, "hello")]
    result = NUDGE_READ(_parse(tmp_path, entries))
    assert result.status == "not-exercised"
    assert result.detail == "no nudge delivered"


def test_nudge_unread_skill_named_among_several(tmp_path: Path):
    entries = [
        _delivery("u0", None, "perk-implement"),
        _user("u1", "u0", f"{BINDING_HEADER}\n\n{_nudge('perk-plan')}"),
        *_exec("e1", "u1", "read", {"path": "/repo/.agents/skills/perk-plan/SKILL.md"}),
    ]
    parsed = _parse(tmp_path, entries)
    result = NUDGE_READ(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "u0"),)
    assert "perk-implement" in result.detail and "perk-plan" not in result.detail


# ------------------------------------------------- docs/learned first-stop consult


@pytest.mark.parametrize(
    ("skill", "tool", "args"),
    [
        # Every consult route satisfies; a corpus grep/find is a legitimate walk. The
        # absolute form must resolve under the session header's cwd (/repo in fixtures);
        # the gate accepts either graded plan skill.
        pytest.param("perk-plan", "read", {"path": "docs/learned/index.md"}, id="read-relative"),
        pytest.param(
            "perk-objective-plan",
            "read",
            {"path": "/repo/docs/learned/workflow/plan-ref-lifecycle.md"},
            id="read-absolute-under-cwd",
        ),
        pytest.param("perk-plan", "bash", {"command": "cat docs/learned/index.md"}, id="bash-cat"),
        pytest.param(
            "perk-plan",
            "bash",
            {"command": "sed -n '1,40p' docs/learned/index.md"},
            id="bash-sed-n",
        ),
        pytest.param(
            "perk-plan", "grep", {"pattern": "plan-ref", "path": "docs/learned/"}, id="grep-path"
        ),
        pytest.param(
            "perk-plan",
            "find",
            {"pattern": "lifecycle", "path": "docs/learned/**"},
            id="find-path",
        ),
    ],
)
def test_learned_plan_satisfied_consult_routes(
    tmp_path: Path, skill: str, tool: str, args: dict[str, object]
):
    entries = [
        _delivery("u0", None, skill),
        *_exec("e1", "u0", tool, args),
        _call("r1", "e1r", "plan_review", {}),
    ]
    assert LEARNED_PLAN(_parse(tmp_path, entries)).status == "satisfied"


def test_learned_plan_pattern_mention_does_not_count(tmp_path: Path):
    # The fuzzy pattern argument never counts — only a path argument targets the corpus.
    entries = [
        _delivery("u0", None, "perk-plan"),
        *_exec("e1", "u0", "grep", {"pattern": "docs/learned"}),
        _call("r1", "e1r", "plan_review", {}),
    ]
    _assert_violated(LEARNED_PLAN(_parse(tmp_path, entries)))


def test_learned_plan_impostor_paths_do_not_satisfy(tmp_path: Path):
    # The predicate anchors to the session repository: word-impostor segments, a foreign
    # tree's docs/learned, a `..` escape out of the corpus, and a climb above the repo
    # root are all rejected.
    entries = [
        _delivery("u0", None, "perk-plan"),
        *_exec("e1", "u0", "read", {"path": "/tmp/notdocs/learned/x.md"}),
        *_exec("e2", "e1r", "read", {"path": "docs/learnedness/y.md"}),
        *_exec("e3", "e2r", "read", {"path": "/tmp/docs/learned/index.md"}),
        *_exec("e4", "e3r", "read", {"path": "docs/learned/../design/x.md"}),
        *_exec("e5", "e4r", "read", {"path": "../docs/learned/x.md"}),
        _call("r1", "e5r", "plan_review", {}),
    ]
    parsed = _parse(tmp_path, entries)
    result = LEARNED_PLAN(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "r1"),)


def test_learned_plan_mention_only_bash_does_not_satisfy(tmp_path: Path):
    # A non-reader command naming the path is a mention, not a consult.
    entries = [
        _delivery("u0", None, "perk-plan"),
        *_exec("e1", "u0", "bash", {"command": "echo docs/learned/x.md"}),
        *_exec("e2", "e1r", "bash", {"command": "ls docs/learned"}),
        _call("r1", "e2r", "plan_review", {}),
    ]
    _assert_violated(LEARNED_PLAN(_parse(tmp_path, entries)))


def test_learned_plan_failed_consult_does_not_satisfy(tmp_path: Path):
    entries = [
        _delivery("u0", None, "perk-plan"),
        *_exec("e1", "u0", "read", {"path": "docs/learned/index.md"}, is_error=True),
        _call("r1", "e1r", "plan_review", {}),
    ]
    _assert_violated(LEARNED_PLAN(_parse(tmp_path, entries)))


def test_learned_plan_same_entry_batched_consult_violates(tmp_path: Path):
    # A consult batched in the review's own assistant entry informed nothing: its result
    # is a descendant of the review call, never an ancestor.
    entries = [
        _delivery("u0", None, "perk-plan"),
        _multi("m1", "u0", [("read", {"path": "docs/learned/index.md"}), ("plan_review", {})]),
        _result("mr", "m1", "read", call_id="c-m1-0"),
    ]
    parsed = _parse(tmp_path, entries)
    result = LEARNED_PLAN(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "m1"),)


def test_learned_plan_post_review_result_violates(tmp_path: Path):
    # The consult call precedes the review on its branch but its RESULT lands after —
    # it could not have informed the reviewed plan.
    entries = [
        _delivery("u0", None, "perk-plan"),
        _call("e1a", "u0", "read", {"path": "docs/learned/index.md"}, "c-e1"),
        _call("r1", "e1a", "plan_review", {}),
        _result("e1r", "r1", "read", call_id="c-e1"),
    ]
    _assert_violated(LEARNED_PLAN(_parse(tmp_path, entries)))


def test_learned_plan_sibling_fork_consult_violates(tmp_path: Path):
    # The consult lives on an abandoned sibling fork — not on the review's ancestor chain.
    entries = [
        _delivery("u0", None, "perk-plan"),
        *_exec("e1", "u0", "read", {"path": "docs/learned/index.md"}),
        _call("r1", "u0", "plan_review", {}),
    ]
    _assert_violated(LEARNED_PLAN(_parse(tmp_path, entries)))


def test_learned_plan_pending_consult_on_chain_is_unchecked(tmp_path: Path):
    # A qualifying consult call with no paired result blocks the absence verdict. Not
    # because a future result could join the chain (the file is append-only; it cannot)
    # but because pairing itself can fail on quirky data — a violation must stay
    # proof-grade (see the mismatched-id test below for the concrete false-verdict risk).
    entries = [
        _delivery("u0", None, "perk-plan"),
        _call("e1a", "u0", "read", {"path": "docs/learned/index.md"}, "c-e1"),
        _call("r1", "e1a", "plan_review", {}),
    ]
    result = LEARNED_PLAN(_parse(tmp_path, entries))
    assert result.status == "unchecked"
    assert "in flight" in result.detail


def test_learned_plan_mismatched_result_id_is_unchecked(tmp_path: Path):
    # The consult's result entry physically precedes the review on its branch but
    # carries a foreign toolCallId, so the call stays unpaired: the consult genuinely
    # happened and could have informed the plan — violating here would be a false
    # verdict. This pairing quirk is why the pending arm exists (mirrors warm-claim).
    entries = [
        _delivery("u0", None, "perk-plan"),
        _call("e1a", "u0", "read", {"path": "docs/learned/index.md"}, "c-e1"),
        _result("e1r", "e1a", "read", call_id="c-other"),
        _call("r1", "e1r", "plan_review", {}),
    ]
    result = LEARNED_PLAN(_parse(tmp_path, entries))
    assert result.status == "unchecked"


def test_learned_plan_pending_unrelated_read_still_violates(tmp_path: Path):
    entries = [
        _delivery("u0", None, "perk-plan"),
        _call("e1a", "u0", "read", {"path": "/repo/README.md"}, "c-e1"),
        _call("r1", "e1a", "plan_review", {}),
    ]
    _assert_violated(LEARNED_PLAN(_parse(tmp_path, entries)))


def test_learned_plan_not_exercised_without_review(tmp_path: Path):
    entries = [
        _delivery("u0", None, "perk-plan"),
        *_exec("e1", "u0", "read", {"path": "docs/learned/index.md"}),
    ]
    result = LEARNED_PLAN(_parse(tmp_path, entries))
    assert result.status == "not-exercised"
    assert "no plan_review" in result.detail


def test_learned_plan_not_exercised_for_borrower(tmp_path: Path):
    # A borrowed-stage factory session (binding_trigger override): some other skill is
    # delivered, never a graded authoring binding — exempt, even with a plan_review.
    entries = [
        _delivery("u0", None, "perk-learn-dream"),
        _call("r1", "u0", "plan_review", {}),
    ]
    result = LEARNED_PLAN(_parse(tmp_path, entries))
    assert result.status == "not-exercised"
    assert "borrowed-stage" in result.detail


def test_learned_plan_transcluded_binding_is_gated_in(tmp_path: Path):
    # Transclude-delivered authoring bindings count as delivered for the guard.
    entries = [
        _custom("c0", None, "Skill `perk-plan` (inlined for `stage:plan`):\n\nbody"),
        _call("r1", "c0", "plan_review", {}),
    ]
    _assert_violated(LEARNED_PLAN(_parse(tmp_path, entries)))


def test_learned_author_satisfied(tmp_path: Path):
    entries = [
        _delivery("u0", None, "perk-objective-author"),
        *_exec("e1", "u0", "read", {"path": "docs/learned/index.md"}),
        _call("r1", "e1r", "plan_review", {}),
    ]
    assert LEARNED_AUTHOR(_parse(tmp_path, entries)).status == "satisfied"


def test_learned_author_violated_without_consult(tmp_path: Path):
    entries = [
        _delivery("u0", None, "perk-objective-author"),
        _call("r1", "u0", "plan_review", {}),
    ]
    parsed = _parse(tmp_path, entries)
    result = LEARNED_AUTHOR(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "r1"),)


def test_learned_checkers_gate_on_their_own_population(tmp_path: Path):
    # Each id grades only its own skill set: a plan binding leaves the objective-author
    # checker not-exercised, and vice versa.
    entries = [
        _delivery("u0", None, "perk-plan"),
        _call("r1", "u0", "plan_review", {}),
    ]
    parsed = _parse(tmp_path, entries)
    assert LEARNED_AUTHOR(parsed).status == "not-exercised"
    _assert_violated(LEARNED_PLAN(parsed))
    entries = [
        _delivery("u0", None, "perk-objective-author"),
        _call("r1", "u0", "plan_review", {}),
    ]
    parsed = _parse(tmp_path, entries)
    assert LEARNED_PLAN(parsed).status == "not-exercised"
    _assert_violated(LEARNED_AUTHOR(parsed))


# ------------------------------------------------------------- classifier first


CLASSIFIER_ARGS: dict[str, object] = {
    "workflowScript": "return runs.run('main', {agent:'perk.review-classifier', task:'…'})"
}


def test_classifier_satisfied(tmp_path: Path):
    entries = [
        _user("u0", None, "/address"),
        *_exec("s1", "u0", "subagent", CLASSIFIER_ARGS),
    ]
    assert CLASSIFIER_FIRST(_parse(tmp_path, entries)).status == "satisfied"


def test_raw_fetch_violates_even_with_classifier(tmp_path: Path):
    entries = [
        _user("u0", None, "/address"),
        *_exec("f1", "u0", "bash", {"command": "gh api repos/o/r/pulls/7/reviews"}),
        *_exec("s1", "f1r", "subagent", CLASSIFIER_ARGS),
    ]
    parsed = _parse(tmp_path, entries)
    result = CLASSIFIER_FIRST(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "f1r"),)


def test_gh_pr_view_json_comments_is_a_raw_fetch(tmp_path: Path):
    entries = [
        _user("u0", None, "/address"),
        *_exec("f1", "u0", "bash", {"command": "gh pr view 7 --json reviews,comments"}),
        *_exec("s1", "f1r", "subagent", CLASSIFIER_ARGS),
    ]
    _assert_violated(CLASSIFIER_FIRST(_parse(tmp_path, entries)))


def test_failed_classifier_run_violates(tmp_path: Path):
    entries = [
        _user("u0", None, "/address"),
        *_exec("s1", "u0", "subagent", CLASSIFIER_ARGS, is_error=True),
    ]
    parsed = _parse(tmp_path, entries)
    result = CLASSIFIER_FIRST(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "s1a"),)  # the first assistant toolCall
    assert "no successful perk.review-classifier" in result.detail


def test_missing_classifier_violates_citing_first_call(tmp_path: Path):
    entries = [
        _user("u0", None, "/address"),
        *_exec("b1", "u0", "bash", {"command": "git status"}),
    ]
    parsed = _parse(tmp_path, entries)
    result = CLASSIFIER_FIRST(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "b1a"),)


def test_innocent_gh_view_is_not_a_raw_fetch(tmp_path: Path):
    entries = [
        _user("u0", None, "/address"),
        *_exec("b1", "u0", "bash", {"command": "gh pr view 7 --json title"}),
        *_exec("s1", "b1r", "subagent", CLASSIFIER_ARGS),
    ]
    assert CLASSIFIER_FIRST(_parse(tmp_path, entries)).status == "satisfied"


def test_classifier_not_exercised_without_tool_calls(tmp_path: Path):
    entries = [_user("u0", None, "hello")]
    assert CLASSIFIER_FIRST(_parse(tmp_path, entries)).status == "not-exercised"


def test_mention_only_gh_api_is_not_a_raw_fetch(tmp_path: Path):
    # The fetch signature requires an actually EXECUTED leading gh command per segment;
    # an echo/grep of an example string is not a fetch.
    entries = [
        _user("u0", None, "/address"),
        *_exec("b1", "u0", "bash", {"command": "echo 'gh api repos/o/r/pulls/7/reviews'"}),
        *_exec("b2", "b1r", "bash", {"command": "grep 'gh pr view 7 --json reviews' notes.md"}),
        *_exec("s1", "b2r", "subagent", CLASSIFIER_ARGS),
    ]
    assert CLASSIFIER_FIRST(_parse(tmp_path, entries)).status == "satisfied"


def test_cd_prefixed_gh_api_fetch_still_violates(tmp_path: Path):
    entries = [
        _user("u0", None, "/address"),
        *_exec("f1", "u0", "bash", {"command": "cd repo && gh api repos/o/r/pulls/1/comments"}),
        *_exec("s1", "f1r", "subagent", CLASSIFIER_ARGS),
    ]
    parsed = _parse(tmp_path, entries)
    result = CLASSIFIER_FIRST(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "f1r"),)


def test_sibling_raw_fetch_still_violates_file_wide(tmp_path: Path):
    # The raw payload entered the session even on an abandoned fork — presence-shaped.
    entries = [
        _user("u0", None, "/address"),
        *_exec("f1", "u0", "bash", {"command": "gh api repos/o/r/pulls/7/reviews"}),
        *_exec("s1", "u0", "subagent", CLASSIFIER_ARGS),  # sibling fork off u0
    ]
    parsed = _parse(tmp_path, entries)
    result = CLASSIFIER_FIRST(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "f1r"),)


def test_task_mention_without_agent_position_is_not_classifier(tmp_path: Path):
    # The launch signature matches agent position only — a task string mentioning the
    # classifier's name is not classifier evidence.
    args: dict[str, object] = {
        "workflowScript": (
            "return runs.run('x', {agent:'perk.objective-explorer', "
            "task:'summarize perk.review-classifier'})"
        )
    }
    entries = [_user("u0", None, "/address"), *_exec("s1", "u0", "subagent", args)]
    result = CLASSIFIER_FIRST(_parse(tmp_path, entries))
    _assert_violated(result)
    assert "no successful perk.review-classifier" in result.detail


def test_direct_execution_agent_args_are_classifier_evidence(tmp_path: Path):
    # The historical direct-execution form carried the agent name in the args proper.
    args: dict[str, object] = {"agent": "perk.review-classifier", "task": "classify"}
    entries = [_user("u0", None, "/address"), *_exec("s1", "u0", "subagent", args)]
    assert CLASSIFIER_FIRST(_parse(tmp_path, entries)).status == "satisfied"


def test_return_payload_ok_false_is_not_classifier_evidence(tmp_path: Path):
    # A completed workflow whose child failed (ok false / report null) is not evidence
    # of a typed report reaching the parent.
    failed_return = (
        "Workflow completed.\n\nReturn:\n"
        '{"key": "classify", "ok": false, "error": "boom", "output": "x", "report": null}'
    )
    entries = [
        _user("u0", None, "/address"),
        *_exec("s1", "u0", "subagent", CLASSIFIER_ARGS, result_text=failed_return),
    ]
    _assert_violated(CLASSIFIER_FIRST(_parse(tmp_path, entries)))


def test_return_payload_ok_true_without_report_field_is_era_evidence(tmp_path: Path):
    # The pre-structured-output workflowScript era returned {key, ok, error, output} — no
    # report field at all; the classification rode `output` prose. ok:true plus the string
    # output is that era's success shape: demanding the report field false-violated live
    # transition-window sessions (the dogfood find).
    era_return = (
        "Workflow completed.\n\nReturn:\n"
        '{"key": "classify", "ok": true, "error": null, "output": "### Classification"}'
    )
    entries = [
        _user("u0", None, "/address"),
        *_exec("s1", "u0", "subagent", CLASSIFIER_ARGS, result_text=era_return),
    ]
    assert CLASSIFIER_FIRST(_parse(tmp_path, entries)).status == "satisfied"


def test_return_payload_missing_report_and_output_is_not_evidence(tmp_path: Path):
    # The era arm is scoped to the documented legacy shape: with no report field AND no
    # string output, a truthy ok alone is not classifier evidence (a modern/malformed
    # workflow suppressing the child result must not pass as historical).
    bare_return = 'Workflow completed.\n\nReturn:\n{"key": "classify", "ok": true, "error": null}'
    entries = [
        _user("u0", None, "/address"),
        *_exec("s1", "u0", "subagent", CLASSIFIER_ARGS, result_text=bare_return),
    ]
    _assert_violated(CLASSIFIER_FIRST(_parse(tmp_path, entries)))


def test_return_payload_explicit_null_report_is_not_classifier_evidence(tmp_path: Path):
    # An explicit report: null under the modern `?? null` return shape means the child
    # produced no schema-valid report — distinct from the era shape with no field.
    null_return = (
        "Workflow completed.\n\nReturn:\n"
        '{"key": "classify", "ok": true, "error": null, "output": "x", "report": null}'
    )
    entries = [
        _user("u0", None, "/address"),
        *_exec("s1", "u0", "subagent", CLASSIFIER_ARGS, result_text=null_return),
    ]
    _assert_violated(CLASSIFIER_FIRST(_parse(tmp_path, entries)))


def test_return_payload_ok_true_with_report_satisfies(tmp_path: Path):
    ok_return = (
        "Workflow completed.\n\nReturn:\n"
        '{"key": "classify", "ok": true, "error": null, "report": {"pr": 7, "counts": {}}}'
        "\n\nCall trace:\n- run classify: completed"
    )
    entries = [
        _user("u0", None, "/address"),
        *_exec("s1", "u0", "subagent", CLASSIFIER_ARGS, result_text=ok_return),
    ]
    assert CLASSIFIER_FIRST(_parse(tmp_path, entries)).status == "satisfied"


def test_classifier_pending_launch_is_unchecked(tmp_path: Path):
    # The classifier subagent call has no paired result yet (a live /address session):
    # the absence verdict is blocked.
    entries = [
        _user("u0", None, "/address"),
        _call("s1", "u0", "subagent", CLASSIFIER_ARGS, "c-1"),
    ]
    result = CLASSIFIER_FIRST(_parse(tmp_path, entries))
    assert result.status == "unchecked"
    assert "in flight" in result.detail


def test_classifier_pending_other_subagent_still_violates(tmp_path: Path):
    # A pending NON-classifier launch cannot flip the verdict — still violated.
    entries = [
        _user("u0", None, "/address"),
        _call("s1", "u0", "subagent", {"workflowScript": "runs.run('x', {agent:'other'})"}, "c-1"),
    ]
    _assert_violated(CLASSIFIER_FIRST(_parse(tmp_path, entries)))


# -------------------------------------------------------------- read-only gate


def test_read_only_satisfied_under_gate(tmp_path: Path):
    entries = [
        _ws("w1", None, mode="read-only"),
        *_exec("b1", "w1", "bash", {"command": "cat README.md"}),
    ]
    assert NO_MUTATION(_parse(tmp_path, entries)).status == "satisfied"


def test_read_only_violated_by_write_and_bad_bash(tmp_path: Path):
    entries = [
        _ws("w1", None, mode="read-only"),
        *_exec("e1", "w1", "write", {"path": "f", "content": "x"}),
        *_exec("b1", "e1r", "bash", {"command": "touch f"}),
    ]
    parsed = _parse(tmp_path, entries)
    result = NO_MUTATION(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "e1r"), _index_of(parsed, "b1r"))


def test_read_write_ancestor_ends_engagement(tmp_path: Path):
    entries = [
        _ws("w1", None, mode="read-only"),
        _ws("w2", "w1", mode="read-write"),
        *_exec("e1", "w2", "edit", {"path": "f"}),
    ]
    assert NO_MUTATION(_parse(tmp_path, entries)).status == "satisfied"


def test_mode_flip_on_abandoned_fork_does_not_disengage(tmp_path: Path):
    entries = [
        _ws("w1", None, mode="read-only"),
        _ws("w2", "w1", mode="read-write"),  # abandoned fork
        *_exec("e1", "w1", "edit", {"path": "f"}),  # surviving branch, still gated
    ]
    parsed = _parse(tmp_path, entries)
    result = NO_MUTATION(parsed)
    _assert_violated(result)
    assert result.entries == (_index_of(parsed, "e1r"),)


def test_blocked_calls_do_not_count(tmp_path: Path):
    entries = [
        _ws("w1", None, mode="read-only"),
        *_exec("e1", "w1", "edit", {"path": "f"}, is_error=True),
        *_exec("b1", "e1r", "bash", {"command": "rm -rf x"}, is_error=True),
    ]
    assert NO_MUTATION(_parse(tmp_path, entries)).status == "satisfied"


def test_interleaved_bash_results_pair_by_tool_call_id(tmp_path: Path):
    # Call A (`touch f`) fails, call B (`cat f`) succeeds; the results arrive B-first.
    # FIFO-by-order would pair A with the success and report a violation — id pairing
    # must attribute the success to the harmless B.
    entries = [
        _ws("w1", None, mode="read-only"),
        _call("a1", "w1", "bash", {"command": "touch f"}, call_id="c-a"),
        _call("b1", "a1", "bash", {"command": "cat f"}, call_id="c-b"),
        _result("rb", "b1", "bash", call_id="c-b", is_error=False),
        _result("ra", "rb", "bash", call_id="c-a", is_error=True),
    ]
    assert NO_MUTATION(_parse(tmp_path, entries)).status == "satisfied"


def test_read_only_unpaired_destructive_call_does_not_violate(tmp_path: Path):
    # An unpaired (in-flight or blocked-without-result) destructive call has no
    # successful result to judge — presence-shaped clauses stay decisive-only.
    entries = [
        _ws("w1", None, mode="read-only"),
        _call("b1", "w1", "bash", {"command": "rm -rf x"}, "c-1"),
    ]
    assert NO_MUTATION(_parse(tmp_path, entries)).status == "satisfied"


def test_read_only_not_exercised_without_gate(tmp_path: Path):
    entries = [
        _user("u0", None, "hi"),
        *_exec("e1", "u0", "write", {"path": "f"}),
    ]
    result = NO_MUTATION(_parse(tmp_path, entries))
    assert result.status == "not-exercised"
    assert result.detail == "gate never engaged"
