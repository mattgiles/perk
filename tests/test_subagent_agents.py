"""Convergence tests for `_converge_subagent_agents` (the `subagent-agents` capability).

perk delivers its agent defs (`PERK_AGENTS`) into the consumer-owned `.pi/agents/perk/`
subdir, byte-for-byte from the bundled `agents/` sources, as a committed managed convergence:
fresh delivery, idempotency, drift rewrite, stray pruning, and `apply=False` dry-run parity.
"""

import re

import yaml

from perk import _resources
from perk.convergence.init import PERK_AGENTS, _converge_subagent_agents


def _source_bytes(name):
    return (_resources.agents_dir() / f"{name}.md").read_bytes()


def test_fresh_delivery_writes_all_defs_byte_identical(tmp_path):
    changes = _converge_subagent_agents(tmp_path, apply=True)
    perk_dir = tmp_path / ".pi" / "agents" / "perk"
    for name in PERK_AGENTS:
        target = perk_dir / f"{name}.md"
        assert target.is_file()
        assert target.read_bytes() == _source_bytes(name)
        assert f".pi/agents/perk/{name}.md: created" in changes
    # The committed `.gitkeep` keeps `.pi/agents/` present.
    assert (tmp_path / ".pi" / "agents" / ".gitkeep").is_file()
    assert ".pi/agents/: created" in changes


def test_reviewer_defs_source_bind_only_the_exact_ponytail_skill_paths():
    package_skills = "../../npm/node_modules/@dietrichgebert/ponytail/skills"
    expected = {
        "draft-reviewer": (
            f"{package_skills}/ponytail/SKILL.md",
            ".pi/npm/node_modules/@dietrichgebert/ponytail/skills/ponytail/SKILL.md",
            "ponytail",
        ),
        "pr-reviewer": (
            f"{package_skills}/ponytail-review/SKILL.md",
            ".pi/npm/node_modules/@dietrichgebert/ponytail/skills/ponytail-review/SKILL.md",
            "ponytail-review",
        ),
        "adversarial-reviewer": (
            f"{package_skills}/ponytail-review/SKILL.md",
            ".pi/npm/node_modules/@dietrichgebert/ponytail/skills/ponytail-review/SKILL.md",
            "ponytail-review",
        ),
    }
    for name, (skill_path, runtime_path, skill_name) in expected.items():
        text = _source_bytes(name).decode()
        frontmatter = yaml.safe_load(text.split("---", 2)[1])
        assert frontmatter["inheritSkills"] is False
        assert frontmatter["skillPath"] == [skill_path]
        assert "skills" not in frontmatter
        assert "**Source-bound Ponytail check.**" in text
        assert runtime_path in text
        assert f"frontmatter name is `{skill_name}`" in text
        compact = " ".join(text.split())
        assert "checking the exact package file is your **first action**" in compact
        assert "terminate without calling `structured_output`" in compact
        assert "never resolve a same-named project/user skill" in compact
        assert "Package files are assumed stable only for the short review pass" in compact
        assert "this recheck leaves Ponytail uncovered" in compact
        assert "exclusive owner of standalone findings" in compact
        assert "Ordinary lanes may mention simplification only when it is inseparable" in compact
        assert "must lead with that angle-specific harm" in compact
        assert "must not emit a second, standalone Ponytail finding" in compact


def test_review_angle_selector_treats_required_ponytail_as_already_present():
    compact = " ".join(_source_bytes("review-angle-selector").decode().split())
    assert "exactly one required automatic Ponytail lane regardless of your selection" in compact
    assert "Never select or duplicate Ponytail" in compact
    assert "never solely for simplification/YAGNI" in compact
    assert "Never propose a custom angle solely for simplification, YAGNI" in compact


def test_committed_mirrors_are_byte_identical_for_all_perk_agents():
    root = _resources.agents_dir().parent
    for name in PERK_AGENTS:
        mirror = root / ".pi" / "agents" / "perk" / f"{name}.md"
        assert mirror.read_bytes() == _source_bytes(name)


def _def_section(text, heading):
    """One `## <heading>` section of an agent def, whitespace-normalized.

    Section-scoping couples each pinned trigger/command to the mode that owns it — a
    whole-file token census would stay green if the mode mapping were reversed.
    """
    match = re.search(
        rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    assert match, f"missing section: {heading}"
    return " ".join(match.group(1).split())


def test_conflict_resolver_def_is_mode_aware():
    text = _source_bytes("conflict-resolver").decode()

    selection = _def_section(text, "Mode selection (fail-closed)")
    # Sentinel presence selects retained mode (the cross-file marker-prefix contract)...
    assert "Select **retained-continuation mode** iff a task-text line's" in selection
    assert "first non-whitespace content begins with the exact marker prefix" in selection
    assert "RETAINED-CONTINUATION SENTINEL:" in selection
    # ...and absence selects the legacy PR-rebase default (flagless, no PR number required).
    assert "Absence of the sentinel selects PR-rebase mode" in selection
    assert "PR mode never requires a PR number" in selection
    # The concrete corroboration probe guards the no-mutation branch.
    assert "stop and report without mutating anything" in selection
    assert "no rebase start, no push, no abort" in selection
    assert "**no rebase in progress**" in selection
    assert (
        'test -d "$(git rev-parse --git-path rebase-merge)" || '
        'test -d "$(git rev-parse --git-path rebase-apply)"' in selection
    )

    pr_mode = _def_section(text, "PR-rebase mode")
    # PR mode keeps flagless context inference, pushes, and owns abort.
    assert "perk pr review-context --json" in pr_mode
    assert "git push --force-with-lease" in pr_mode
    assert "git rebase --abort" in pr_mode
    assert "Abort is **PR-mode-only**" in pr_mode

    retained = _def_section(text, "Retained-continuation mode")
    # The two-rung context ladder over the existing review-context surface.
    assert "perk pr review-context --pr <N> --stack --json" in retained
    assert "perk pr review-context --pr <N> --json" in retained
    # Retained mode resumes (never restarts), never publishes, never discards.
    assert "Never start a fresh rebase" in retained
    assert "NEVER push in this mode" in retained
    assert "NEVER `git rebase --abort` in this mode" in retained
    assert "sync --continue" in retained
    assert "sync --abort" in retained

    report = _def_section(text, "Report")
    # The outcome-class vocabulary the dispatching session's gate keys on — and
    # completed requires *passing* verification, not merely a verification run.
    assert "Open with the terminal outcome class" in report
    assert "the rebase finished and verification **passed**" in report
    for outcome in (
        "completed",
        "verification-failed",
        "stopped-before-mutation",
        "unresolvable-conflict",
        "aborted",
    ):
        assert f"**{outcome}**" in report


def test_continuation_dispatch_template_agrees_on_the_sentinel():
    template_text = (
        _resources.prompts_dir() / "stages" / "conflict-resolution-continuation.md"
    ).read_text(encoding="utf-8")
    def_text = _source_bytes("conflict-resolver").decode()
    # Cross-file byte agreement on the sentinel marker prefix.
    marker = "RETAINED-CONTINUATION SENTINEL:"
    assert marker in template_text
    assert marker in def_text
    # The full rendered sentinel line starts a line (column zero), not mere substring presence.
    assert re.search(
        r"^RETAINED-CONTINUATION SENTINEL: resume the in-progress rebase in \{\{ worktree \}\}$",
        template_text,
        re.MULTILINE,
    )

    def step(n):
        # One numbered dispatch step, whitespace-normalized — pinning inside the step that
        # owns a token keeps the pin honest (the template's opening summary also names the
        # PR, which must not satisfy the child-task requirement).
        match = re.search(rf"^{n}\. (.*?)(?=^\d\. |\Z)", template_text, re.MULTILINE | re.DOTALL)
        assert match, f"missing step {n}"
        return " ".join(match.group(1).split())

    # Step 2 is the child task: it opens with the worktree cd, carries the sentinel line,
    # and names the PR number retained mode requires to proceed.
    task = step(2)
    assert "`cd {{ worktree }}`" in task
    assert "RETAINED-CONTINUATION SENTINEL: resume the in-progress rebase in {{ worktree }}" in task
    assert "PR #{{ pr }}" in task

    # Step 3 gates continuation on explicit human consent, requires passing verification,
    # and withholds on every non-completed outcome class (the def's vocabulary).
    gate = step(3)
    assert "ONLY a **completed** rebase (verification passed)" in gate
    assert "await the human's explicit consent" in gate
    assert "{ objective: {{ objective }}, continue: true }" in gate
    assert "EVERY other outcome" in gate
    assert "withholds continuation" in gate
    for withheld in ("stopped-before-mutation", "unresolvable-conflict", "verification-failed"):
        assert withheld in gate
    assert "{ objective: {{ objective }}, abort: true }" in gate


def test_second_run_is_idempotent(tmp_path):
    _converge_subagent_agents(tmp_path, apply=True)
    assert _converge_subagent_agents(tmp_path, apply=True) == []


def test_drifted_def_is_rewritten(tmp_path):
    _converge_subagent_agents(tmp_path, apply=True)
    drifted = tmp_path / ".pi" / "agents" / "perk" / f"{PERK_AGENTS[0]}.md"
    drifted.write_text("hand-edited drift\n", encoding="utf-8")
    changes = _converge_subagent_agents(tmp_path, apply=True)
    assert changes == [f".pi/agents/perk/{PERK_AGENTS[0]}.md: updated"]
    assert drifted.read_bytes() == _source_bytes(PERK_AGENTS[0])


def test_stray_in_perk_subdir_is_removed_but_user_agents_untouched(tmp_path):
    _converge_subagent_agents(tmp_path, apply=True)
    perk_dir = tmp_path / ".pi" / "agents" / "perk"
    stray = perk_dir / "stray.md"
    stray.write_text("not a perk agent\n", encoding="utf-8")
    # A user's own top-level agent must never be touched.
    mine = tmp_path / ".pi" / "agents" / "mine.md"
    mine.write_text("user agent\n", encoding="utf-8")

    changes = _converge_subagent_agents(tmp_path, apply=True)
    assert changes == [".pi/agents/perk/stray.md: removed"]
    assert not stray.exists()
    assert mine.read_text(encoding="utf-8") == "user agent\n"


def test_apply_false_returns_same_change_list_without_writing(tmp_path):
    # Fresh repo: dry-run reports every create but writes nothing.
    dry = _converge_subagent_agents(tmp_path, apply=False)
    assert not (tmp_path / ".pi" / "agents" / "perk").exists()
    assert not (tmp_path / ".pi" / "agents" / ".gitkeep").exists()
    # Applying yields the identical change list.
    assert _converge_subagent_agents(tmp_path, apply=True) == dry
