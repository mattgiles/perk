"""Guard tests for repo-local (`perk-dev`-namespace) agent defs.

`.pi/agents/perk-dev/` holds committed, repo-local agent defs: outside the shipped `agents/`
directory (never in the `@mgiles/perk` npm package) and outside the legacy `.pi/agents/perk/`
the `doctor --fix` migration removes. The namespace's sole member today is `session-auditor`
(the perk-dev session-audit judgment wave's auditor). These tests pin only the safety-bearing
shape of the def — the read-only tool grant and the isolation/acceptance knobs — not the full
prose, plus the retirement of the former `analyst` def (promoted to the shipped `perk.scout`).
"""

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).parent.parent
_PERK_DEV_DIR = _REPO_ROOT / ".pi" / "agents" / "perk-dev"


def test_auditor_is_a_background_report_outside_delivery():
    path = _PERK_DEV_DIR / "session-auditor.md"
    fm = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
    assert not (_REPO_ROOT / "agents" / "session-auditor.md").exists()
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
    # pi-subagents >= 0.68.0 rejects any def carrying the removed `fallbackModels` field at load.
    assert "fallbackModels" not in fm
    # pi-subagents 0.70.1 removed the completion mutation guard, so (like the shipped reports)
    # the def carries no `completionGuard`; the auditor completes on its validated report, and
    # acceptance stays suppressed by the wave spawn, not by frontmatter.
    assert "completionGuard" not in fm
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
    # The analyst was promoted to the shipped `perk.scout`; no alias is left behind. This is
    # deliberately a single-file pin, not a closed census of the namespace, so unrelated
    # perk-dev agents can be added later without revisiting this test.
    assert not (_PERK_DEV_DIR / "analyst.md").exists()
