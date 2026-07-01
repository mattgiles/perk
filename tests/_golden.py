"""Minimal golden-snapshot harness for the ``--json`` OUTPUT envelopes.

Each in-scope envelope is pinned to a committed ``tests/golden/json/<name>.json`` snapshot
generated from the *pre-swap* hand-rolled builder, so swapping the builder to a Pydantic
``OutputModel`` is proven byte-identical: a green post-swap run IS the proof.

Regen by running a golden test with ``PERK_UPDATE_GOLDEN`` set in the environment. The helper
**always** re-reads the committed file and asserts equality afterward, so a regen of a
non-roundtrippable value still fails loudly rather than silently pinning garbage.
"""

import json
import os
from pathlib import Path

GOLDEN_DIR = Path(__file__).parent / "golden" / "json"
TEXT_GOLDEN_DIR = Path(__file__).parent / "golden"


def assert_golden(name: str, actual: object) -> None:
    """Assert ``actual`` equals the committed ``<name>.json`` snapshot.

    When ``PERK_UPDATE_GOLDEN`` is set, (re)write the snapshot from ``actual`` first — then
    still re-read and assert, so a regen against a non-roundtrippable value fails loudly.
    """
    path = GOLDEN_DIR / f"{name}.json"
    if os.environ.get("PERK_UPDATE_GOLDEN"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert actual == expected, f"golden mismatch for {name}: regen with PERK_UPDATE_GOLDEN=1"


def assert_text_golden(name: str, actual: str, *, suffix: str) -> None:
    """Assert ``actual`` equals the committed ``<name><suffix>`` raw-text snapshot.

    The raw-text sibling of ``assert_golden`` (byte compare, no JSON round-trip); ``name`` may
    carry a subdirectory (e.g. ``changelog/apply-multi.expected``). Same ``PERK_UPDATE_GOLDEN``
    regen + always-reread-and-assert discipline.
    """
    path = TEXT_GOLDEN_DIR / f"{name}{suffix}"
    if os.environ.get("PERK_UPDATE_GOLDEN"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    expected = path.read_text(encoding="utf-8")
    assert actual == expected, f"golden mismatch for {name}: regen with PERK_UPDATE_GOLDEN=1"
