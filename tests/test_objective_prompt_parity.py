"""Cross-plane objective-prompt parity invariant.

The objective seed prompts are backend-aware via a single shared helper per plane:
``perk/cli/commands/objective/shared.py::objective_read_instruction`` (cold) and its byte-identical
TS twin ``extension/factories/objectivePlan.ts::objectiveReadInstruction`` (warm). These substrings
are the shared invariant — the SAME literals are asserted from the TS side in
``extension/factories/objectivePlan.test.ts`` (``OBJECTIVE_LINEAR_SUBSTRINGS``), so a drift in
EITHER plane fails CI here or there. Mirrors ``tests/test_worker_prompt_parity.py``.
"""

from perk import objective
from perk.cli.commands.objective.plan_cmd import _seed_prompt
from perk.cli.commands.objective.shared import objective_read_instruction

# Keep in lockstep with OBJECTIVE_LINEAR_SUBSTRINGS in extension/factories/objectivePlan.test.ts —
# the literal fragments of the shared linear arm.
OBJECTIVE_LINEAR_SUBSTRINGS = [
    "Linear Project",
    "linear_get_issue",
    "linear_list_comments",
    "inspect a node-issue",
    "if the linear tools are unavailable, open ",
]

_URL = "https://linear.app/acme/project/objective-7"


def _node() -> objective.ObjectiveNode:
    return objective.ObjectiveNode(
        id="1.2", description="B", status=objective.NodeStatus.PENDING, depends_on=()
    )


def test_read_instruction_linear_carries_substrings() -> None:
    clause = objective_read_instruction("linear", "7", _URL)
    for needle in OBJECTIVE_LINEAR_SUBSTRINGS:
        assert needle in clause, f"linear objective-read instruction drifted — missing: {needle!r}"
    assert _URL in clause


def test_read_instruction_linear_without_url_uses_indirect_form() -> None:
    clause = objective_read_instruction("linear", "7", "")
    assert "run `perk objective show 7` for its URL" in clause
    # The `open <url>` fallback is dropped when the url is unknown.
    assert "if the linear tools are unavailable, open " not in clause
    # The tool references survive.
    assert "linear_get_issue" in clause
    assert "linear_list_comments" in clause


def test_read_instruction_github_is_empty() -> None:
    assert objective_read_instruction("github", "7", _URL) == ""
    # Any non-linear backend → empty (no churn on the github prompt).
    assert objective_read_instruction("gitlab", "7", _URL) == ""


def test_seed_prompt_linear_carries_substrings() -> None:
    primed = _seed_prompt("7", _node(), "Ship it", backend="linear", url=_URL)
    for needle in OBJECTIVE_LINEAR_SUBSTRINGS:
        assert needle in primed, f"linear seed prompt drifted — missing: {needle!r}"
    assert _URL in primed


def test_seed_prompt_github_unchanged_no_linear_fragments() -> None:
    primed = _seed_prompt("7", _node(), "Ship it")
    for needle in OBJECTIVE_LINEAR_SUBSTRINGS:
        assert needle not in primed, f"github seed prompt leaked a linear fragment: {needle!r}"
    # The backend-agnostic objective-show step is still present.
    assert "perk objective show 7" in primed
