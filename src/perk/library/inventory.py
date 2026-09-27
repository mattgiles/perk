"""The advisory read of a mirror's ``sources.json`` per-page inventory.

The inventory seeds a docs entry's per-page change markers (the probes a later ``check`` uses).
Its shape — ``{"pages": [{"source_url": …}, …]}`` at minimum — is the handshake the hardened
crawl script must write (contracts.md §8.74(b)); today only hand-built mirrors carry one. The
read is never a refusal: an absent inventory records no markers, a malformed one records no
markers plus a warning.
"""

import json
from pathlib import Path

from pydantic import ValidationError

from perk.boundary import LenientParseModel
from perk.library.catalog import PageMarker
from perk.library.layout import INVENTORY_FILENAME


class InventoryPageModel(LenientParseModel):
    source_url: str | None = None


class InventoryModel(LenientParseModel):
    pages: tuple[InventoryPageModel, ...] = ()


def read_inventory(mirror_dir: Path) -> tuple[tuple[PageMarker, ...], str | None]:
    """``(markers, warning)`` from ``<mirror_dir>/sources.json`` — one marker per distinct
    ``pages[].source_url`` in file order; ``warning`` names why an existing inventory was
    skipped."""
    path = mirror_dir / INVENTORY_FILENAME
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ((), None)
    except (OSError, UnicodeDecodeError) as exc:
        return ((), _skipped(path, f"unreadable ({exc})"))
    try:
        model = InventoryModel.model_validate(json.loads(text))
    except json.JSONDecodeError as exc:
        return ((), _skipped(path, f"not valid JSON ({exc})"))
    except ValidationError as exc:
        return ((), _skipped(path, f"unexpected shape ({exc.error_count()} validation errors)"))
    urls = dict.fromkeys(page.source_url for page in model.pages if page.source_url)
    return (tuple(PageMarker(url=url) for url in urls), None)


def _skipped(path: Path, reason: str) -> str:
    return f"{path}: {reason} — recorded with no per-page inventory"
