import time
from datetime import datetime

from perk.state.run_id import base_ulid, derive_child, is_run_id, mint, timestamp


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


def test_timestamp_parses_embedded_time():
    ts = timestamp(mint())
    assert isinstance(ts, datetime)
    assert ts.year >= 2026
