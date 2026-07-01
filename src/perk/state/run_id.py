"""Mint and parse perk run ids (contracts.md §8.2).

A ``run_id`` is a canonical **ULID** (26-char Crockford base32) — time-sortable and
self-dating, so GC-by-age and chronological ordering need no sidecar. Mint doctrine
(contracts.md §8.2): the CLI mints at **cold launch** (handing off via ``PERK_RUN_ID``);
a warm transition keeps the id; a fork derives a child by suffix (``<ulid>.<n>``); and a
**warm session with no identity** mints its own ULID in the TS plane
(``extension/substrate/runId.ts``) — the extension otherwise claims, restores, and derives.
"""

from datetime import datetime

from ulid import ULID


def mint() -> str:
    """Mint a fresh ``run_id`` (a new ULID) — the cold-launch mint site (§8.2)."""
    return str(ULID())


def derive_child(parent: str, n: int) -> str:
    """Derive a fork-child ``run_id`` by suffixing the parent (``<parent>.<n>``).

    Nested forks fall out naturally: ``derive_child("<ulid>.1", 2) == "<ulid>.1.2"``,
    and :func:`base_ulid` still recovers the root ULID.
    """
    return f"{parent}.{n}"


def base_ulid(run_id: str) -> str:
    """The root ULID of a ``run_id``, stripping any ``.<n>`` fork suffixes."""
    return run_id.split(".", 1)[0]


def is_run_id(value: str) -> bool:
    """True when ``value``'s base is a parseable ULID.

    Parsing is the authoritative test for ULID validity (there is no cheap LBYL
    pre-check for length + Crockford base32), so EAFP is correct here.
    """
    if not value:
        return False
    try:
        ULID.from_str(base_ulid(value))
    except ValueError:
        return False
    return True


def timestamp(run_id: str) -> datetime:
    """The mint time embedded in a ``run_id``'s base ULID (raises on a non-ULID)."""
    return ULID.from_str(base_ulid(run_id)).datetime
