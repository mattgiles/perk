"""perk-owned dot-path construction regression guard (contracts.md §8.1).

Production Python code may construct the **perk-owned** dot-path families — workflow, skills,
the two config files, and the required-perk-version pin — only inside their seams:
``perk/substrate/paths.py`` (config + skills + the version pin) and ``perk/state/cache.py``
(workflow). Everything else goes through those helpers
(``paths.config_file``/``paths.local_config_file``/``paths.repo_skills_dir``,
``cache.workflow_dir``, …).

The workflow, skills, and config families now live at ``.perk/``. The legacy
``.pi/perk.toml`` / ``.pi/perk.local.toml`` config paths are constructed only via the allowlisted
``paths.py`` ``legacy_*`` helpers (for the doctor migration). The scan therefore flags a quoted
segment adjacent to a ``/`` operator in either of two shapes:

- ``".pi"`` adjacent to a legacy config follow-segment (``"perk.toml"`` /
  ``"perk.local.toml"`` or the legacy filename constants); or
- ``".perk"`` adjacent to a current perk-owned follow-segment (``"workflow"`` / ``"skills"`` /
  ``"config.toml"`` / ``"local.toml"`` / ``"required-perk-version"`` or the filename constants).

**Pi-native** ``.pi/...`` paths (``".pi" / "npm"``, ``".pi" / "agents"``, ``".pi" /
"settings.json"``) and prose mentioning ``.pi/workflow`` therefore never false-positive. The TS
twin is ``extension/pathsGuard.test.ts``.
"""

import re
from pathlib import Path

import perk

# A legacy config follow-segment. Legacy config construction stays confined to the allowlisted seam.
_PI_FOLLOW = (
    r'("perk\.toml"|"perk\.local\.toml"'
    r"|LEGACY_CONFIG_FILENAME|LEGACY_LOCAL_CONFIG_FILENAME)"
)

# A `.perk`-adjacent current perk-owned follow-segment.
_PERK_FOLLOW = (
    r'("workflow"|"skills"|"config\.toml"|"local\.toml"|"required-perk-version"'
    r"|CONFIG_FILENAME|LOCAL_CONFIG_FILENAME|REQUIRED_VERSION_FILENAME)"
)

# A quoted `".pi"` segment in path construction (adjacent to a `/`) followed by a legacy config
# follow-segment.
PI_PATTERN = re.compile(r"""["']\.pi["']\s*/\s*""" + _PI_FOLLOW)

# A quoted `".perk"` segment in path construction (adjacent to a `/`) followed by a current
# perk-owned follow-segment.
PERK_PATTERN = re.compile(r"""["']\.perk["']\s*/\s*""" + _PERK_FOLLOW)


def _matches(line: str) -> bool:
    return bool(PI_PATTERN.search(line) or PERK_PATTERN.search(line))


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
                if _matches(line):
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
        (cache.py carries `".perk" / "workflow"`; paths.py carries `".perk" / "skills"` and the
        legacy `.pi` config helpers)."""
        cache_src = (_perk_dir() / "state" / "cache.py").read_text(encoding="utf-8")
        paths_src = (_perk_dir() / "substrate" / "paths.py").read_text(encoding="utf-8")
        assert any(_matches(line) for line in cache_src.splitlines()), (
            "cache.py no longer matches the banned pattern — guard is vacuous"
        )
        assert any(_matches(line) for line in paths_src.splitlines()), (
            "paths.py no longer matches the banned pattern — guard is vacuous"
        )

    def test_positive_each_family_arm_matches(self) -> None:
        """Per-arm positive asserts on synthetic strings — keeps the config/local arms honest even
        though the seam derives them from `config_dir`."""
        # Legacy `.pi` config arms.
        assert PI_PATTERN.search('root / ".pi" / "perk.toml"')
        assert PI_PATTERN.search('root / ".pi" / "perk.local.toml"')
        assert PI_PATTERN.search('root / ".pi" / LEGACY_CONFIG_FILENAME')
        assert PI_PATTERN.search('root / ".pi" / LEGACY_LOCAL_CONFIG_FILENAME')
        # Current `.perk` arms.
        assert PERK_PATTERN.search('root / ".perk" / "workflow"')
        assert PERK_PATTERN.search('root / ".perk" / "skills"')
        assert PERK_PATTERN.search('root / ".perk" / CONFIG_FILENAME')
        assert PERK_PATTERN.search('root / ".perk" / LOCAL_CONFIG_FILENAME')
        assert PERK_PATTERN.search('root / ".perk" / "config.toml"')
        assert PERK_PATTERN.search('root / ".perk" / "local.toml"')
        assert PERK_PATTERN.search('root / ".perk" / "required-perk-version"')
        assert PERK_PATTERN.search('root / ".perk" / REQUIRED_VERSION_FILENAME')

    def test_negative_pi_native_paths_do_not_match(self) -> None:
        """Pi-native `.pi/...` construction is out of scope and must not false-positive; and a
        config filename is no longer `.pi`-adjacent (it moved to `.perk`)."""
        assert not _matches('root / ".pi" / "npm"')
        assert not _matches('root / ".pi" / "agents"')
        assert not _matches('root / ".pi" / "settings.json"')
        # Current families are `.perk`-adjacent, not `.pi`-adjacent.
        assert not PI_PATTERN.search('root / ".pi" / CONFIG_FILENAME')
        assert not PI_PATTERN.search('root / ".pi" / "config.toml"')
        assert not PI_PATTERN.search('root / ".pi" / "workflow"')
        assert not PI_PATTERN.search('root / ".pi" / "skills"')
