"""perk — plan-oriented engineering workflow for Pi (CLI exterior).

The version SSOT is `pyproject.toml` `[project] version`, bumped via `uv version`.
Installed package metadata reflects it after `uv sync`/`uv version`, and `package.json`
is kept equal (guarded by tests/test_packaging.py::test_version_lockstep).
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

try:
    # Installed (incl. editable): the version recorded at install time from the
    # pyproject [project] version SSOT (bumped via `uv version`).
    __version__ = _dist_version("perk")
except PackageNotFoundError:  # raw, uninstalled source tree — read the SSOT directly.
    import tomllib
    from pathlib import Path

    _pp = Path(__file__).resolve().parent.parent / "pyproject.toml"
    __version__ = tomllib.loads(_pp.read_text(encoding="utf-8"))["project"]["version"]
