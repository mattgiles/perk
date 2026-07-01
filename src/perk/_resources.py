"""Locate perk's bundled ``shared/`` contracts directory from either install mode.

The contracts in ``shared/`` are authored once and bundled into each build
artifact. This resolver is the Python plane's single "where is shared/?"
helper; the TS extension has its own twin (``extension/substrate/resources.ts``).
"""

from importlib import resources
from pathlib import Path


def shared_dir() -> Path:
    """Return the bundled ``shared/`` directory.

    - **Installed wheel:** carried as package data at ``perk/_shared`` (hatchling
      ``force-include``).
    - **Editable / dev install:** read the repo-root ``shared/`` (two levels above the
      ``src/perk`` package; the ``force-include`` copy does not exist in an editable checkout).
    """
    # Installed: package data alongside the perk package. `resources.files("perk")`
    # never raises here (the package is imported), and a missing dir is reported by
    # `.is_dir()` returning False — so check, don't catch (LBYL).
    candidate = Path(str(resources.files("perk"))) / "_shared"
    if candidate.is_dir():
        return candidate

    # Editable / dev: the repo-root `shared/` (two levels above the `src/perk` package).
    sibling = Path(__file__).resolve().parents[2] / "shared"
    if sibling.is_dir():
        return sibling

    raise FileNotFoundError(
        "perk: could not locate the bundled 'shared/' contracts directory "
        "(checked package data 'perk/_shared' and repo sibling 'shared/')."
    )


def agents_dir() -> Path:
    """Return the bundled ``agents/`` directory (perk's subagent definition sources).

    Mirrors :func:`shared_dir`:

    - **Installed wheel:** carried as package data at ``perk/_agents`` (hatchling
      ``force-include``).
    - **Editable / dev install:** read the repo-root ``agents/`` (two levels above the
      ``src/perk`` package; the ``force-include`` copy does not exist in an editable checkout).
    """
    candidate = Path(str(resources.files("perk"))) / "_agents"
    if candidate.is_dir():
        return candidate

    sibling = Path(__file__).resolve().parents[2] / "agents"
    if sibling.is_dir():
        return sibling

    raise FileNotFoundError(
        "perk: could not locate the bundled 'agents/' definitions directory "
        "(checked package data 'perk/_agents' and repo sibling 'agents/')."
    )


def prompts_dir() -> Path:
    """Return the bundled ``prompts/`` directory (canonical cross-plane prompt templates).

    Mirrors :func:`shared_dir`:

    - **Installed wheel:** carried as package data at ``perk/_prompts`` (hatchling
      ``force-include``).
    - **Editable / dev install:** read the repo-root ``prompts/`` (two levels above the
      ``src/perk`` package; the ``force-include`` copy does not exist in an editable checkout).
    """
    candidate = Path(str(resources.files("perk"))) / "_prompts"
    if candidate.is_dir():
        return candidate

    sibling = Path(__file__).resolve().parents[2] / "prompts"
    if sibling.is_dir():
        return sibling

    raise FileNotFoundError(
        "perk: could not locate the bundled 'prompts/' templates directory "
        "(checked package data 'perk/_prompts' and repo sibling 'prompts/')."
    )
