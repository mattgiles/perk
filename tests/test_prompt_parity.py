"""Tier-B live cross-engine parity for the prompt render seam.

Every *real* prompt template is rendered by BOTH planes — jinja2 (Python, the reference engine
here) and the vendored mini-jinja (TS, via a one-shot `node` subprocess) — and the two outputs are
asserted byte-equal per template. There are NO committed goldens: editing a real prompt's prose
touches no fixture, and the engines are still held in lockstep. A coverage guard asserts every real
template is listed in the manifest so a newly-added prompt can't silently skip this tier.

(`prompts/_fixtures/cases.yaml` + committed goldens remain the Tier-A *contract* snapshots — the
sui-generis per-feature fixtures that pin the frozen render semantics; see `tests/test_prompts.py`.)
"""

import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
import yaml

from perk._resources import prompts_dir
from perk.prompts import render

REPO_ROOT = Path(__file__).resolve().parents[1]
_RENDER_LIVE = REPO_ROOT / "extension" / "testing" / "renderLive.ts"


def _load_live_cases() -> list[dict[str, object]]:
    text = (prompts_dir() / "_fixtures" / "live.yaml").read_text()
    return yaml.safe_load(text)


def _real_templates() -> set[str]:
    root = prompts_dir()
    rels: set[str] = set()
    for path in root.rglob("*.md"):
        rel = path.relative_to(root).as_posix()
        if rel == "README.md" or rel.startswith("_fixtures/"):
            continue
        rels.add(rel)
    return rels


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_live_cross_engine_parity() -> None:
    cases = _load_live_cases()
    py_outputs: list[str] = []
    for case in cases:
        raw_vars = case["vars"]
        assert isinstance(raw_vars, dict)
        variables = cast(Mapping[str, object], raw_vars)
        py_outputs.append(render(str(case["template"]), variables))

    proc = subprocess.run(
        ["node", str(_RENDER_LIVE)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    js_outputs = json.loads(proc.stdout)

    assert len(py_outputs) == len(js_outputs), (
        f"manifest length mismatch: jinja2 rendered {len(py_outputs)}, "
        f"mini-jinja rendered {len(js_outputs)}"
    )
    for case, py, js in zip(cases, py_outputs, js_outputs, strict=True):
        assert py == js, f"cross-engine mismatch for {case['template']!r}"


def test_live_manifest_covers_every_real_template() -> None:
    listed = {str(case["template"]) for case in _load_live_cases()}
    missing = _real_templates() - listed
    assert not missing, (
        "real prompt template(s) absent from prompts/_fixtures/live.yaml "
        f"(they would silently skip the live cross-engine parity tier): {sorted(missing)}"
    )
