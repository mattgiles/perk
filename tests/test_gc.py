"""GC policy unit tests (`perk/gc.py`, contracts.md §8.1, Objective #339 Node 1.4).

Builds tmp_path repos with ``cache.ensure_layout`` + the cache helpers. Backdated ULIDs are
minted with ``ULID.from_datetime``; mtime-fallback cases backdate via ``os.utime``.
"""

import os
import shutil
from datetime import UTC, datetime, timedelta

import pytest
from ulid import ULID

from perk.state import cache, gc
from perk.substrate import registry


def _repo(tmp_path):
    cache.ensure_layout(tmp_path)
    return tmp_path


def _ulid_at(days_ago: float) -> str:
    return str(ULID.from_datetime(datetime.now(UTC) - timedelta(days=days_ago)))


def _now() -> datetime:
    return datetime.now(UTC)


# --- terminal-stage rule --------------------------------------------------------------------


def test_consumed_terminal_stage_is_eligible_regardless_of_age(tmp_path):
    repo = _repo(tmp_path)
    rid = _ulid_at(0)  # young
    cache.write_handoff(repo, rid, {"stage": "learn"})
    cache.mark_handoff_consumed(repo, rid)
    plan = gc.plan_prune(repo)
    assert [c.run_id for c in plan.eligible] == [rid]
    assert plan.eligible[0].reason == "terminal stage completed"


def test_unconsumed_terminal_handoff_kept_until_age(tmp_path):
    repo = _repo(tmp_path)
    rid = _ulid_at(0)
    cache.write_handoff(repo, rid, {"stage": "learn"})  # not consumed
    plan = gc.plan_prune(repo)
    assert plan.eligible == [] and plan.kept == 1


def test_non_terminal_consumed_young_kept_old_eligible(tmp_path):
    repo = _repo(tmp_path)
    young = _ulid_at(0)
    cache.write_handoff(repo, young, {"stage": "plan"})
    cache.mark_handoff_consumed(repo, young)
    assert gc.plan_prune(repo).eligible == []

    old = _ulid_at(15)
    cache.write_handoff(repo, old, {"stage": "plan"})
    cache.mark_handoff_consumed(repo, old)
    plan = gc.plan_prune(repo)
    assert [c.run_id for c in plan.eligible] == [old]
    assert plan.eligible[0].reason == "older than 14d"


# --- age rule (warm dirs + orphan handoffs) -------------------------------------------------


def test_warm_run_dir_young_kept_old_eligible(tmp_path):
    repo = _repo(tmp_path)
    young = _ulid_at(0)
    cache.write_scratch(repo, young, "x", "y")
    assert gc.plan_prune(repo).eligible == []

    old = _ulid_at(20)
    cache.write_scratch(repo, old, "x", "y")
    plan = gc.plan_prune(repo)
    assert [c.run_id for c in plan.eligible] == [old]
    assert plan.eligible[0].run_dir is not None and plan.eligible[0].handoff is None


def test_old_orphan_handoff_no_run_dir(tmp_path):
    repo = _repo(tmp_path)
    rid = _ulid_at(30)
    cache.write_handoff(repo, rid, {})  # not consumed; no run dir
    plan = gc.plan_prune(repo)
    assert [c.run_id for c in plan.eligible] == [rid]
    cand = plan.eligible[0]
    assert cand.run_dir is None and cand.handoff is not None


def test_non_ulid_name_uses_mtime_fallback(tmp_path):
    repo = _repo(tmp_path)
    cache.write_scratch(repo, "stray-dir", "x", "y")
    run_dir = cache.run_scratch_dir(repo, "stray-dir")
    # young by mtime → kept
    assert gc.plan_prune(repo).eligible == []
    # backdate 20d → eligible
    old = (datetime.now(UTC) - timedelta(days=20)).timestamp()
    os.utime(run_dir, (old, old))
    plan = gc.plan_prune(repo)
    assert [c.run_id for c in plan.eligible] == ["stray-dir"]


def test_fork_child_ages_by_base_ulid(tmp_path):
    repo = _repo(tmp_path)
    base = _ulid_at(20)
    child = f"{base}.2"
    cache.write_scratch(repo, child, "x", "y")
    plan = gc.plan_prune(repo)
    assert [c.run_id for c in plan.eligible] == [child]


# --- current-run protection -----------------------------------------------------------------


def test_perk_run_id_protects_exact_and_fork_child(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    base = _ulid_at(30)  # old enough to otherwise be eligible
    child = f"{base}.2"
    cache.write_scratch(repo, base, "x", "y")
    cache.write_scratch(repo, child, "x", "y")
    monkeypatch.setenv("PERK_RUN_ID", base)
    plan = gc.plan_prune(repo)
    assert plan.eligible == [] and plan.kept == 2


# --- degrade-graceful postures --------------------------------------------------------------


def test_unreadable_handoff_never_terminal_pruned_but_age_prunable(tmp_path):
    repo = _repo(tmp_path)
    young = _ulid_at(0)
    cache.handoff_path(repo, young).write_text("{not json", encoding="utf-8")
    # young + unparseable → no stage, no age → kept
    assert gc.plan_prune(repo).eligible == []

    old = _ulid_at(20)
    cache.handoff_path(repo, old).write_text("{not json", encoding="utf-8")
    plan = gc.plan_prune(repo)
    assert [c.run_id for c in plan.eligible] == [old]
    assert plan.eligible[0].reason == "older than 14d"


def test_registry_failure_degrades_terminal_set(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    rid = _ulid_at(0)
    cache.write_handoff(repo, rid, {"stage": "learn"})
    cache.mark_handoff_consumed(repo, rid)

    def _boom(*_a, **_k):
        raise registry.RegistryError("broken")

    monkeypatch.setattr(registry, "load_registry", _boom)
    # terminal set empty → the consumed learn handoff is no longer terminal-pruned; young → kept
    plan = gc.plan_prune(repo)
    assert plan.eligible == []
    assert "could not load the registry" in capsys.readouterr().err

    # the age rule still applies
    old = _ulid_at(20)
    cache.write_handoff(repo, old, {"stage": "learn"})
    cache.mark_handoff_consumed(repo, old)
    assert [c.run_id for c in gc.plan_prune(repo).eligible] == [old]


def test_terminal_stage_ids_is_learn():
    assert gc.terminal_stage_ids() == frozenset({"learn"})


# --- execute_prune --------------------------------------------------------------------------


def test_execute_prune_deletes_run_dir_and_handoff(tmp_path):
    repo = _repo(tmp_path)
    rid = _ulid_at(0)
    cache.write_session_data(repo, rid, "nested.txt", "data")  # creates data/ subdir
    cache.write_handoff(repo, rid, {"stage": "learn"})
    cache.mark_handoff_consumed(repo, rid)
    plan = gc.plan_prune(repo)
    errors = gc.execute_prune(plan)
    assert errors == []
    assert not cache.run_scratch_dir(repo, rid).exists()
    assert not cache.handoff_path(repo, rid).exists()


def test_execute_prune_collects_per_item_errors(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    a = _ulid_at(20)
    b = _ulid_at(20)
    cache.write_scratch(repo, a, "x", "y")
    cache.write_scratch(repo, b, "x", "y")
    plan = gc.plan_prune(repo)
    assert {c.run_id for c in plan.eligible} == {a, b}

    real_rmtree = shutil.rmtree

    def _flaky(path, *args, **kwargs):
        if str(path).endswith(a):
            raise OSError("boom")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(gc.shutil, "rmtree", _flaky)
    errors = gc.execute_prune(plan)
    assert len(errors) == 1 and a in errors[0]
    # the other candidate still pruned
    assert not cache.run_scratch_dir(repo, b).exists()
    assert cache.run_scratch_dir(repo, a).exists()


@pytest.mark.parametrize("max_age", [0, 1])
def test_max_age_days_threshold(tmp_path, max_age):
    repo = _repo(tmp_path)
    rid = _ulid_at(0.5)  # half a day old
    cache.write_scratch(repo, rid, "x", "y")
    plan = gc.plan_prune(repo, max_age_days=max_age)
    if max_age == 0:
        assert [c.run_id for c in plan.eligible] == [rid]
    else:
        assert plan.eligible == []
