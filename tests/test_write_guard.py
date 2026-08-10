"""Atomic-write regression guard (contracts.md §8.1).

Production Python code writes files through ``perk.substrate.fs.atomic_write_text`` (temp file in
the same directory + atomic replace) so a concurrent writer can never tear a ``.perk/workflow/``
file. Bare ``.write_text(``/``.write_bytes(`` is banned repo-wide; genuinely non-workflow writers
(tracked repo files, committed ``.perk`` files, user-global caches — single-process,
human-invoked, never raced) get a justified ``ALLOWED`` entry, so every new write site forces the
workflow-vs-not decision consciously. A textual backstop, not a completeness proof (see
``docs/learned/workflow/source-scan-guards.md``). The TS twin is ``extension/writeGuard.test.ts``.
"""

import re
from pathlib import Path

import perk

# A leading-dot write call: `<expr>.write_text(` / `<expr>.write_bytes(`. The leading dot keeps
# the seam itself clean — `atomic_write_text(path, content)` is a free function, never a match.
PATTERN = re.compile(r"\.write_(text|bytes)\(")

# Non-workflow writers, by justification group. `substrate/fs.py` is deliberately absent: the
# atomic helper writes via `os.fdopen`, so the seam stays clean under this scan.
ALLOWED = frozenset(
    {
        # Convergence: `perk init` / `perk doctor --fix` write tracked repo files + committed
        # `.perk` config — single-process, human-invoked, never raced.
        "convergence/managed_state.py",
        "convergence/init/__init__.py",
        "convergence/init/settings.py",
        "convergence/init/templates.py",
        "convergence/init/skills.py",
        "convergence/init/agents.py",
        "convergence/init/blocks.py",
        "convergence/init/repo_skills.py",
        "convergence/init/version_pin.py",
        "convergence/doctor/fixes.py",
        # Docs sync: rewrites tracked docs/AGENTS blocks in the main checkout (human-invoked).
        "learn/docs_sync.py",
        # Skills lifecycle: writes tracked, repo-authored skill files (human-invoked).
        "cli/commands/skills/shared.py",
        "cli/commands/skills/rm_cmd.py",
        # Version check: a user-global (per-user, not per-repo) cache file.
        "cli/version_check.py",
        # Remote runner: writes tracked `.github/` workflow artifacts (human-invoked).
        "run/workflow_artifacts.py",
    }
)


def _perk_dir() -> Path:
    return Path(perk.__file__).parent


class TestAtomicWriteGuard:
    def test_no_production_module_writes_files_directly(self) -> None:
        """Source scan: outside the justified ``ALLOWED`` set, no module under perk/ may call
        ``.write_text(``/``.write_bytes(`` — `.perk/workflow/` writes go through the atomic
        seam."""
        perk_dir = _perk_dir()
        offenders: list[str] = []
        files = sorted(perk_dir.rglob("*.py"))
        # Self-checks: a layout change that empties the scan must fail loudly, not vacuously.
        assert files, "production-file scan came up empty — guard is vacuous"
        assert any(p.name == "cache.py" for p in files), "scan missed cache.py — guard is misaimed"
        stale = ALLOWED - {str(p.relative_to(perk_dir)) for p in files}
        assert not stale, f"stale ALLOWED entries (files no longer exist): {sorted(stale)}"
        for path in files:
            if str(path.relative_to(perk_dir)) in ALLOWED:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if PATTERN.search(line):
                    offenders.append(
                        f"{path.relative_to(perk_dir.parent)}:{lineno}: {line.strip()}"
                    )
        assert not offenders, (
            "bare .write_text/.write_bytes call outside the justified ALLOWED set — writes under "
            ".perk/workflow/ go through cache.atomic_write_text (torn-write-proof); a genuinely "
            "non-workflow writer gets a justified ALLOWED entry in tests/test_write_guard.py:\n"
            + "\n".join(offenders)
        )

    def test_pattern_matches_an_allowlisted_writer(self) -> None:
        """Non-vacuous self-check: at least one ALLOWED file really carries the banned call."""
        source = (_perk_dir() / "convergence" / "init" / "blocks.py").read_text(encoding="utf-8")
        matches = [line for line in source.splitlines() if PATTERN.search(line)]
        assert matches, "convergence/init/blocks.py no longer matches — guard may be vacuous"

    def test_pattern_ignores_the_atomic_seam_call_shape(self) -> None:
        """Call-shape sanity: the atomic helper's own call sites never match (no leading dot)."""
        assert not PATTERN.search("atomic_write_text(path, content)")
        assert not PATTERN.search("cache.atomic_write_text(path, content)")
        assert PATTERN.search('path.write_text(content, encoding="utf-8")')
        assert PATTERN.search("target.write_bytes(desired[name])")
