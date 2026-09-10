"""Guard tests for repo-local (`perk-dev`-namespace) agent defs.

`.pi/agents/perk-dev/` holds committed, repo-local agent defs: outside `PERK_AGENTS`, never
delivered to consumer repos, and untouched by the `.pi/agents/perk/` pruning convergence. The
namespace's sole member today is `session-auditor` (the perk-dev session-audit judgment wave's
auditor). These tests pin only the safety-bearing shape of the def — the read-only tool grant
and the isolation/acceptance knobs — not the full prose, plus the retirement of the former
`analyst` def (promoted to the delivered `perk.scout`).
"""

from pathlib import Path

import yaml

from perk.convergence.init import PERK_AGENTS

_PERK_DEV_DIR = Path(__file__).parent.parent / ".pi" / "agents" / "perk-dev"


def test_auditor_is_a_background_report_outside_delivery():
    path = _PERK_DEV_DIR / "session-auditor.md"
    fm = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
    assert "session-auditor" not in PERK_AGENTS
    assert fm["name"] == "session-auditor"
    assert fm["package"] == "perk-dev"
    assert fm["async"] is True
    assert fm["inheritGlobalContext"] is False
    assert fm["inheritProjectContext"] is False
    assert fm["inheritSkills"] is False
    assert fm["systemPromptMode"] == "replace"
    assert [tool.strip() for tool in fm["tools"].split(",")] == [
        "read",
        "grep",
        "find",
        "ls",
        "bash",
    ]
    assert fm["model"] == "openai/gpt-5.6-luna"
    assert fm["fallbackModels"] == ["openai/gpt-5.6-terra"]
    # The report-only completion policy shared with the delivered reports: the engine's
    # mutation guard is disabled by literal false (the auditor never edits); acceptance stays
    # suppressed by the wave spawn, not by frontmatter.
    assert fm["completionGuard"] is False
    for absent in (
        "extensions",
        "subagentOnlyExtensions",
        "skills",
        "skillPath",
        "acceptance",
        "mission",
    ):
        assert absent not in fm


def test_analyst_def_is_retired():
    # The analyst was promoted to the delivered `perk.scout`; no alias is left behind. This is
    # deliberately a single-file pin, not a closed census of the namespace, so unrelated
    # perk-dev agents can be added later without revisiting this test.
    assert not (_PERK_DEV_DIR / "analyst.md").exists()
