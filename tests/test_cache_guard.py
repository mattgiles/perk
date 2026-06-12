"""Scratch-path construction regression guard (Objective #339 Node 1.2, contracts.md §8.1).

Production Python code may build the ``scratch``/``runs`` path segments only inside the cache
seam (``perk/cache.py``); everything else goes through its helpers (``scratch_dir``,
``run_scratch_dir``, ``session_data_dir``, ``list_run_ids``, …). The pattern is scoped to *path
construction* — a quoted segment adjacent to a ``/`` operator — so plain dict keys like
``"runs"`` (e.g. in ``objective/run_cmd.py``) never false-positive. The TS twin is
``extension/cacheGuard.test.ts``.
"""

import re
from pathlib import Path

from perk import cache

# A quoted scratch/runs segment used in path construction (adjacent to a `/` operator).
PATTERN = re.compile(r"""(/\s*["'](scratch|runs)["'])|(["'](scratch|runs)["']\s*/)""")

ALLOWED = frozenset({"cache.py"})


def _perk_dir() -> Path:
    return Path(cache.__file__).parent


class TestCachePathGuard:
    def test_no_production_module_builds_scratch_paths_directly(self) -> None:
        """Source scan: outside perk/cache.py (the seam), no module under perk/ may construct
        a path with the `scratch`/`runs` segment literals."""
        perk_dir = _perk_dir()
        offenders: list[str] = []
        files = sorted(perk_dir.rglob("*.py"))
        # Self-checks: a layout change that empties the scan must fail loudly, not vacuously.
        assert files, "production-file scan came up empty — guard is vacuous"
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
            "manual scratch/runs path construction outside perk/cache.py — go through the "
            "cache seam (scratch_dir/run_scratch_dir/session_data_dir):\n" + "\n".join(offenders)
        )

    def test_pattern_matches_the_seam_itself(self) -> None:
        """Non-vacuous self-check: cache.py's own construction lines DO match the pattern."""
        source = (_perk_dir() / "cache.py").read_text(encoding="utf-8")
        matches = [line for line in source.splitlines() if PATTERN.search(line)]
        assert matches, "cache.py no longer matches the banned pattern — guard is vacuous"

    def test_pattern_ignores_plain_dict_keys(self) -> None:
        """A `"runs"` dict key (no adjacent `/`) must not false-positive."""
        assert not PATTERN.search('return {"runs": runs, "turns": turns}')
        assert PATTERN.search('workflow_dir(root) / "scratch" / "runs"')
