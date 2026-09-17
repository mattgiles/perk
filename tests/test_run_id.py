import time
from datetime import datetime

import pytest

from perk.state.run_id import (
    base_ulid,
    derive_child,
    is_canonical_run_id,
    is_run_id,
    mint,
    timestamp,
)


def test_mint_is_unique_and_parseable():
    ids = {mint() for _ in range(100)}
    assert len(ids) == 100
    assert all(is_run_id(i) and len(i) == 26 for i in ids)


def test_mint_is_time_sortable():
    a = mint()
    time.sleep(0.005)
    b = mint()
    assert a < b  # ULID lexical order == chronological order


def test_derive_child_and_base_round_trip():
    u = mint()
    child = derive_child(u, 3)
    assert child == f"{u}.3"
    assert base_ulid(child) == u
    grandchild = derive_child(child, 1)  # nested fork
    assert grandchild == f"{u}.3.1"
    assert base_ulid(grandchild) == u


def test_is_run_id_rejects_junk():
    assert not is_run_id("")
    assert not is_run_id("not-a-ulid")
    assert not is_run_id("lowercase-bad!!")
    assert is_run_id(mint())
    assert is_run_id(derive_child(mint(), 2))


# --- is_canonical_run_id: the STRICT full-match grammar (selector / path gate) -------------


def test_is_canonical_run_id_accepts_a_ulid_and_nested_fork_suffixes():
    u = mint()
    assert is_canonical_run_id(u)
    assert is_canonical_run_id(derive_child(u, 1))
    assert is_canonical_run_id(derive_child(derive_child(u, 1), 2))
    assert is_canonical_run_id(f"{u}.10")


_ULID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


@pytest.mark.parametrize(
    "value",
    [
        "",
        _ULID.lower(),
        _ULID[:25],  # 25 chars
        _ULID + "A",  # 27 chars
        "01ARZ3NDEKTSV4RRFFQ69G5FAI",  # `I` is not Crockford
        "01ARZ3NDEKTSV4RRFFQ69G5FAL",
        "01ARZ3NDEKTSV4RRFFQ69G5FAO",
        "01ARZ3NDEKTSV4RRFFQ69G5FAU",
        f"{_ULID}.",
        f"{_ULID}.x",
        f"{_ULID}./../x",
        f"{_ULID}/x",
        f"{_ULID}\n",  # the fullmatch guard: `$` alone would admit this
        f"{_ULID}\r\n",
        "42",
        "#42",
        "ENG-1",
        "https://github.com/o/r/issues/42",
        f"{_ULID}.\u0661",  # an Arabic-Indic digit: `re.ASCII` keeps `\\d` at [0-9]
    ],
)
def test_is_canonical_run_id_rejects_everything_off_grammar(value: str):
    assert not is_canonical_run_id(value)


def test_is_run_id_stays_permissive_for_a_junk_suffix():
    # The parse-based test gc/runner keep is deliberately NOT tightened: `.junk` still parses
    # (its base is a ULID) while the canonical grammar refuses it.
    value = f"{mint()}.junk"
    assert is_run_id(value)
    assert not is_canonical_run_id(value)


def test_timestamp_parses_embedded_time():
    ts = timestamp(mint())
    assert isinstance(ts, datetime)
    assert ts.year >= 2026
