"""perk-owned dot-path construction regression guard (contracts.md §8.1).

Production Python code may construct the four **perk-owned** dot-path families — workflow, skills,
and the two config files — only inside their seams: ``perk/substrate/paths.py`` (config + skills)
and ``perk/state/cache.py`` (workflow). Everything else goes through those helpers
(``paths.config_file``/``paths.local_config_file``/``paths.repo_skills_dir``,
``cache.workflow_dir``, …).

The pattern is scoped to *path construction* — a quoted ``".pi"``/``".perk"`` segment immediately
adjacent to a ``/`` operator whose other segment is a perk-owned family follow-segment
(``"workflow"``/``"skills"``/``CONFIG_FILENAME``/``LOCAL_CONFIG_FILENAME``/``"perk.toml"``/
``"perk.local.toml"``).
**Pi-native** ``.pi/...`` paths (``".pi" / "npm"``, ``".pi" / "agents"``, ``".pi" /
"settings.json"``) and prose mentioning ``.pi/workflow`` therefore never false-positive. The TS
twin is
``extension/pathsGuard.test.ts``.
"""

import re
from pathlib import Path

import perk

# A perk-owned family follow-segment: a quoted family literal, the filename literals, or the
# imported filename constants.
_FOLLOW = (
    r'("workflow"|"skills"|"perk\.toml"|"perk\.local\.toml"'
    r"|CONFIG_FILENAME|LOCAL_CONFIG_FILENAME)"
)

# A quoted `".pi"`/`".perk"` segment in path construction (adjacent to a `/`) followed by a
# perk-owned family follow-segment. Both dot-dirs are guarded so a family stays guarded across its
# Objective #878 migration from `.pi/` to `.perk/`.
PATTERN = re.compile(r"""["']\.(pi|perk)["']\s*/\s*""" + _FOLLOW)

ALLOWED = frozenset({"substrate/paths.py", "state/cache.py"})


def _perk_dir() -> Path:
    return Path(perk.__file__).parent


class TestPerkOwnedPathGuard:
    def test_no_production_module_builds_perk_owned_paths_directly(self) -> None:
        """Source scan: outside the seams, no module under perk/ may construct a perk-owned
        dot-path family (workflow/skills/config)."""
        perk_dir = _perk_dir()
        offenders: list[str] = []
        files = sorted(perk_dir.rglob("*.py"))
        # Self-checks: a layout change that empties the scan must fail loudly, not vacuously.
        assert files, "production-file scan came up empty — guard is vacuous"
        assert any(p.name == "paths.py" for p in files), "scan missed paths.py — guard is misaimed"
        assert any(p.name == "cache.py" for p in files), "scan missed cache.py — guard is misaimed"
        for path in files:
            if str(path.relative_to(perk_dir)) in ALLOWED:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if PATTERN.search(line):
                    offenders.append(
                        f"{path.relative_to(perk_dir.parent)}:{lineno}: {line.strip()}"
                    )
        assert not offenders, (
            "manual perk-owned dot-path construction outside the seams — go through "
            "perk/substrate/paths.py (config/skills) or perk/state/cache.py (workflow):\n"
            + "\n".join(offenders)
        )

    def test_pattern_matches_the_seams_themselves(self) -> None:
        """Non-vacuous self-check: the seams' own construction lines DO match the pattern
        (cache.py carries `".pi" / "workflow"`; paths.py carries `".perk" / "skills"`)."""
        cache_src = (_perk_dir() / "state" / "cache.py").read_text(encoding="utf-8")
        paths_src = (_perk_dir() / "substrate" / "paths.py").read_text(encoding="utf-8")
        assert any(PATTERN.search(line) for line in cache_src.splitlines()), (
            "cache.py no longer matches the banned pattern — guard is vacuous"
        )
        assert any(PATTERN.search(line) for line in paths_src.splitlines()), (
            "paths.py no longer matches the banned pattern — guard is vacuous"
        )

    def test_positive_each_family_arm_matches(self) -> None:
        """Per-arm positive asserts on synthetic strings — keeps the config/local arms honest even
        though the seam derives them from `config_dir`."""
        assert PATTERN.search('root / ".pi" / "workflow"')
        assert PATTERN.search('root / ".pi" / "skills"')
        assert PATTERN.search('root / ".perk" / "skills"')
        assert PATTERN.search('root / ".pi" / CONFIG_FILENAME')
        assert PATTERN.search('root / ".pi" / LOCAL_CONFIG_FILENAME')
        assert PATTERN.search('root / ".pi" / "perk.toml"')
        assert PATTERN.search('root / ".pi" / "perk.local.toml"')

    def test_negative_pi_native_paths_do_not_match(self) -> None:
        """Pi-native `.pi/...` construction is out of scope and must not false-positive."""
        assert not PATTERN.search('root / ".pi" / "npm"')
        assert not PATTERN.search('root / ".pi" / "agents"')
        assert not PATTERN.search('root / ".pi" / "settings.json"')
        assert not PATTERN.search('root / ".perk" / "npm"')
