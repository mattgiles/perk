"""Locate perk's bundled ``shared/`` contracts directory from either install mode.

The contracts in ``shared/`` are authored once (T2) and bundled into each build
artifact (``Q12``). This resolver is the Python plane's single "where is shared/?"
helper; the TS extension has its own twin (``extension/resources.ts``).
"""

from importlib import resources
from pathlib import Path


def shared_dir() -> Path:
    """Return the bundled ``shared/`` directory.

    - **Installed wheel:** carried as package data at ``perk/_shared`` (hatchling
      ``force-include``).
    - **Editable / dev install:** read the repo sibling ``<repo>/shared`` (the
      ``force-include`` copy does not exist in an editable checkout).
    """
    # Installed: package data alongside the perk package. `resources.files("perk")`
    # never raises here (the package is imported), and a missing dir is reported by
    # `.is_dir()` returning False — so check, don't catch (LBYL).
    candidate = Path(str(resources.files("perk"))) / "_shared"
    if candidate.is_dir():
        return candidate

    # Editable / dev: sibling of the perk/ package inside the repo.
    sibling = Path(__file__).resolve().parent.parent / "shared"
    if sibling.is_dir():
        return sibling

    raise FileNotFoundError(
        "perk: could not locate the bundled 'shared/' contracts directory "
        "(checked package data 'perk/_shared' and repo sibling 'shared/')."
    )
