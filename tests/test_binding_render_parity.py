"""Live cross-plane byte parity for the skill-binding render (contracts.md §8.9, §8.38).

The delivered guidance CONTENT is rendered by two mechanisms: the cold-door prompt suffix
(Python `render_cold_bindings`) and the warm/worker Mechanism-A in-session injection (TS
`renderBindings`, via a one-shot `node` subprocess). The delivery *mechanism* is a named
intentional difference (§8.38); this test pins the rendered *content* byte-identical per
trigger across the three render arms: an installed-skill nudge, a transclude, and the shipped
default nudge for `stage:implement`.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from perk.substrate.binding_delivery import render_cold_bindings
from perk.substrate.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
_RENDER_BINDINGS_LIVE = REPO_ROOT / "extension" / "testing" / "renderBindingsLive.ts"

_SKILL_MD = textwrap.dedent(
    """\
    ---
    name: {name}
    description: a test skill
    ---

    # {name}

    Body guidance for `{name}` — with unicode (—) and backticks.
    """
)

_CONFIG = textwrap.dedent(
    """\
    [[bindings]]
    trigger = "command:alpha"
    skill = "alpha-installed"
    mode = "nudge"

    [[bindings]]
    trigger = "command:beta"
    skill = "beta-inline"
    mode = "transclude"
    """
)

# The three render arms: a user-overlay nudge to an installed skill, a user-overlay transclude
# (body inlined), and the shipped default nudge for stage:implement (skill NOT installed in the
# scaffold — the pointer is still emitted, warning aside).
_TRIGGERS = ["command:alpha", "command:beta", "stage:implement"]


def _pointer(skill: str) -> str:
    """The path-carrying nudge pointer line both renderers emit for ``skill``."""
    return f"Follow the `{skill}` skill (read `.agents/skills/{skill}/SKILL.md`)."


def _scaffold(root: Path) -> None:
    for skill in ("alpha-installed", "beta-inline"):
        skill_dir = root / ".agents" / "skills" / skill
        skill_dir.mkdir(parents=True)
        content = _SKILL_MD.format(name=skill)
        if skill == "beta-inline":
            # The transclude target is written with CRLF line endings on purpose: Python's
            # read_text() normalizes universal newlines while Node's readFileSync does not, so
            # this arm pins the TS-side normalization in readSkillBody (a CRLF checkout must
            # neither defeat frontmatter stripping nor break the byte parity).
            (skill_dir / "SKILL.md").write_bytes(content.replace("\n", "\r\n").encode("utf-8"))
            continue
        (skill_dir / "SKILL.md").write_text(_SKILL_MD.format(name=skill), encoding="utf-8")
    perk_dir = root / ".perk"
    perk_dir.mkdir()
    (perk_dir / "config.toml").write_text(_CONFIG, encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_binding_render_cross_plane_byte_parity(tmp_path) -> None:
    _scaffold(tmp_path)
    user_bindings = load_config(tmp_path).user_bindings

    py_outputs = [
        render_cold_bindings(user_bindings, tmp_path, trigger).text for trigger in _TRIGGERS
    ]
    # Guard against a vacuous None == None comparison: every arm must actually render.
    assert all(isinstance(text, str) and text for text in py_outputs), py_outputs
    assert _pointer("alpha-installed") in str(py_outputs[0])
    assert "Body guidance for `beta-inline`" in str(py_outputs[1])  # transclusion inlines the body
    assert _pointer("perk-implement") in str(py_outputs[2])  # the shipped default

    proc = subprocess.run(
        ["node", str(_RENDER_BINDINGS_LIVE), str(tmp_path), *_TRIGGERS],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    ts_outputs = json.loads(proc.stdout)

    assert len(ts_outputs) == len(py_outputs)
    for trigger, py, ts in zip(_TRIGGERS, py_outputs, ts_outputs, strict=True):
        assert py == ts, f"cross-plane binding render mismatch for {trigger!r}"
