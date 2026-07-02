"""The committed `.perk/required-perk-version` pin — read/render/converge.

A version-stamped managed piece (like the AGENTS `perk version:` stamp): the desired content is
always the **running CLI's** version, so the file drifts after a version bump and reconverges in
**both** directions via `perk init` / `perk doctor --fix` — the same bidirectional
reconcile-to-my-version semantics as the settings npm pin (contracts.md §8.6a). The runtime
CLI-vs-repo comparison consuming `read_version_pin` is a separate report-only surface.
"""

from pathlib import Path

from perk import __version__
from perk.substrate import paths

_LABEL = ".perk/required-perk-version"


def render_version_pin() -> str:
    """The desired file content: the version SSOT plus one trailing newline."""
    return f"{__version__}\n"


def read_version_pin(root: Path) -> str | None:
    """The pinned version string (stripped), or ``None`` when the file is missing.

    ``OSError`` propagates: doctor's ``_managed_checks`` maps an unreadable managed piece to a
    loud "unverifiable" fail, never a silent pass.
    """
    path = paths.required_version_file(root)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip()


def converge_version_pin(root: Path, *, apply: bool = True) -> list[str]:
    """Converge the pin **byte-exactly** to ``render_version_pin()``.

    Any difference (missing file, stale/newer version, whitespace garbage) is drift. Dry-run
    (``apply=False``) and apply compute the identical change list (the init/doctor idempotency
    rule).
    """
    path = paths.required_version_file(root)
    desired = render_version_pin()
    current = path.read_text(encoding="utf-8") if path.is_file() else None
    if current == desired:
        return []
    verb = "created" if current is None else "updated"
    if apply:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(desired, encoding="utf-8")
    return [f"{_LABEL}: {verb}"]
