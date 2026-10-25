"""perk-written Pi configuration conforms to the adopted Pi's own published config schemas.

The producer is the real ``run_init`` convergence; the validator is TypeBox, reached through the
one-shot ``extension/testing/piConfigSchemasLive.ts`` subprocess. The schemas are read from the
exact-pinned dev ``@earendil-works/pi-coding-agent`` package's ``schemas/`` directory, so the pin
bump is the refresh (never vendored, never fetched). Documents are validated whole and unmodified,
so extension-owned keys (pi-subagents' ``subagents``) ride along as Pi's open root admits them.
With ``node`` absent the check is skipped — unexercised, not passed.
"""

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from perk import __version__
from perk.convergence.init import run_init
from perk.convergence.init.settings import (
    BORROWED_PACKAGES,
    LINEAR_PACKAGE,
    PACKAGE_RESOURCE_FILTERS,
    PONYTAIL_PACKAGE,
    SUBAGENTS_PACKAGE,
)
from perk.substrate.config import PI_THINKING_LEVEL_ORDER, PI_THINKING_LEVELS

REPO_ROOT = Path(__file__).resolve().parents[1]
_LIVE = REPO_ROOT / "extension" / "testing" / "piConfigSchemasLive.ts"
_PI_DEV_PACKAGE = "@earendil-works/pi-coding-agent"
_COMMITTED = "committed .pi/settings.json"
_CONTROL = "control-invalid-thinking"


@dataclass(frozen=True)
class _Case:
    """One converged repo: an optional seeded `.perk/config.toml`, `.pi/settings.json`, and the
    `[tool.perk] self = true` marker."""

    name: str
    config: str | None = None
    settings: dict[str, object] | None = None
    self_repo: bool = False


_CASES: tuple[_Case, ...] = (
    _Case("consumer-default"),
    _Case("self-repo", self_repo=True),
    _Case(
        "perk-owned-keys",
        config=(
            "[compaction]\nenabled = false\nreserve_tokens = 8192\nkeep_recent_tokens = 20000\n\n"
            '[models]\ndefault = "anthropic/claude-opus-4-1:high"\n'
        ),
    ),
    _Case(
        "foreign-selections",
        config=(
            '[providers]\nplan = "plannotator-plan"\nfooter = "powerline-footer"\n'
            'web = "ollama-web-search"\n\n[issues]\nbackend = "linear"\nteam = "ENG"\n'
        ),
    ),
    _Case(
        "operator-keys-preserved",
        config="[compaction]\nreserve_tokens = 8192\n",
        settings={
            "packages": [
                {"source": "npm:pi-subagents@0.70.0", "skills": []},
                "npm:@dietrichgebert/ponytail@1.2.3",
                {"source": "npm:@me/custom", "extensions": ["./ext.ts"]},
            ],
            "subagents": {
                "disableBuiltins": False,
                "agentOverrides": {"oracle": {"disabled": False}},
            },
            "compaction": {"reserveTokens": 999, "keepRecentTokens": 5000},
            "theme": "nightowl",
            "defaultTools": ["read", "bash"],
        },
    ),
    *(
        _Case(f"thinking-{level}", config=f'[models]\nthinking = "{level}"\n')
        for level in PI_THINKING_LEVEL_ORDER
    ),
)


def _converge(root: Path, case: _Case) -> Path:
    """Seed ``case`` under ``root``, converge it with the real ``run_init``, return its settings."""
    root.mkdir()
    if case.self_repo:
        (root / "pyproject.toml").write_text("[tool.perk]\nself = true\n", encoding="utf-8")
    if case.config is not None:
        (root / ".perk").mkdir()
        (root / ".perk" / "config.toml").write_text(case.config, encoding="utf-8")
    if case.settings is not None:
        (root / ".pi").mkdir()
        (root / ".pi" / "settings.json").write_text(
            json.dumps(case.settings, indent=2) + "\n", encoding="utf-8"
        )
    report = run_init(root, verify=False)
    assert report.ok, report.message
    return root / ".pi" / "settings.json"


def _filtered(source: str) -> dict[str, object]:
    """The filtered-object form perk converges a Ponytail entry into."""
    return {"source": source, **{key: [] for key in PACKAGE_RESOURCE_FILTERS}}


def _assert_matrix_coverage(docs: dict[str, dict]) -> None:
    """Non-vacuity: every case really carries the perk-written shape it exists to prove."""
    consumer = docs["consumer-default"]
    for entry in [
        f"npm:@mgiles/perk@{__version__}",
        *(p for p in BORROWED_PACKAGES if p != PONYTAIL_PACKAGE),
        _filtered(PONYTAIL_PACKAGE),
        {"source": "npm:pi-web-access"},
    ]:
        assert entry in consumer["packages"], f"consumer-default lacks {entry!r}"
    assert consumer["subagents"] == {"disableBuiltins": True}, "consumer-default subagents"
    assert consumer["defaultTools"] == ["+tool_search"], "consumer-default defaultTools"

    assert ".." in docs["self-repo"]["packages"], "self-repo lacks the '..' entry"

    owned = docs["perk-owned-keys"]
    assert owned["compaction"] == {
        "enabled": False,
        "reserveTokens": 8192,
        "keepRecentTokens": 20000,
    }, "perk-owned-keys compaction"
    assert owned["defaultProvider"] == "anthropic", "perk-owned-keys defaultProvider"
    assert owned["defaultModel"] == "claude-opus-4-1", "perk-owned-keys defaultModel"
    assert owned["defaultThinkingLevel"] == "high", "perk-owned-keys defaultThinkingLevel"

    foreign = docs["foreign-selections"]["packages"]
    for entry in [
        {"source": "npm:@plannotator/pi-extension"},
        {"source": "npm:pi-powerline-footer"},
        {"source": "npm:@ollama/pi-web-search"},
        LINEAR_PACKAGE,
    ]:
        assert entry in foreign, f"foreign-selections lacks {entry!r}"

    preserved = docs["operator-keys-preserved"]
    assert preserved["subagents"] == {
        "disableBuiltins": True,
        "agentOverrides": {"oracle": {"disabled": False}},
    }, "operator-keys-preserved subagents"
    for entry in [
        {"source": SUBAGENTS_PACKAGE, "skills": []},
        _filtered("npm:@dietrichgebert/ponytail@1.2.3"),
        {"source": "npm:@me/custom", "extensions": ["./ext.ts"]},
    ]:
        assert entry in preserved["packages"], f"operator-keys-preserved lacks {entry!r}"
    assert preserved["theme"] == "nightowl", "operator-keys-preserved theme"
    assert preserved["defaultTools"] == ["read", "bash", "+tool_search"], (
        "operator-keys-preserved defaultTools"
    )
    assert preserved["compaction"] == {"reserveTokens": 8192, "keepRecentTokens": 5000}, (
        "operator-keys-preserved compaction"
    )

    for level in PI_THINKING_LEVEL_ORDER:
        assert docs[f"thinking-{level}"]["defaultThinkingLevel"] == level, f"thinking-{level}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_perk_converged_settings_conform_to_the_pinned_pi_schemas(tmp_path):
    paths = {case.name: _converge(tmp_path / case.name, case) for case in _CASES}
    docs = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in paths.items()}
    _assert_matrix_coverage(docs)

    control = dict(docs["consumer-default"])
    control["defaultThinkingLevel"] = "bogus"
    control_path = tmp_path / f"{_CONTROL}.json"
    control_path.write_text(json.dumps(control), encoding="utf-8")

    labelled = {**paths, _COMMITTED: REPO_ROOT / ".pi" / "settings.json", _CONTROL: control_path}
    proc = subprocess.run(
        ["node", str(_LIVE), *map(str, labelled.values())],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)

    root_manifest = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    assert payload["version"] == root_manifest["devDependencies"][_PI_DEV_PACKAGE]

    pi_levels = set(payload["thinkingLevels"])
    pi_only = sorted(pi_levels - PI_THINKING_LEVELS)
    perk_only = sorted(PI_THINKING_LEVELS - pi_levels)
    assert not pi_only and not perk_only, (
        f"the adopted Pi's ModelThinkingLevel differs from PI_THINKING_LEVEL_ORDER "
        f"(Pi-only: {pi_only}; perk-only: {perk_only}) — widen/narrow it in "
        "src/perk/substrate/config.py, and the thinking rows in "
        "docs/user-docs/reference/configuration/models-and-compaction.md, "
        "skills/perk-expert/references/configuration.md and the seeded template comment "
        "(src/perk/convergence/init/templates.py)"
    )

    assert len(payload["results"]) == len(labelled)
    results = dict(zip(labelled, payload["results"], strict=True))
    control_errors = results.pop(_CONTROL)
    for label, errors in results.items():
        assert errors == [], f"{label} violates Pi's settings schema: {errors}"
    assert control_errors, "the invalid-thinking control was accepted"
    assert any(error.startswith("/defaultThinkingLevel") for error in control_errors), (
        control_errors
    )
