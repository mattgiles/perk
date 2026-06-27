"""``.perk/workflow/`` cache-tier I/O (contracts.md §8.1).

Free functions over an explicit repo ``root``. **Both
planes read and write the same files**; the TS twin is ``extension/substrate/cache.ts``. These are
state-tiering *primitives* — no workflow semantics (no ``pending-learn`` meaning, no GC
policy; the GC *policy* lives in ``perk/state/gc.py``, surfaced as ``perk state prune`` + the
``cache-gc`` doctor check). LBYL throughout; absence is a normal,
branchable condition (reads return ``None``, not an exception).
"""

import json
from pathlib import Path
from typing import Any

from pydantic import ConfigDict

from perk.boundary import StrictBoundaryModel, StrTuple, translate_validation_errors
from perk.substrate.output import user_output

# The canonical `.perk/workflow/` subtrees (public so `perk doctor` can verify the layout).
SUBDIRS: tuple[str, ...] = ("plans", "scratch/runs", "handoff", "markers")


class CacheError(ValueError):
    """A durable ``.perk/workflow/`` cache file failed schema validation.

    Subclasses ``ValueError`` (documented, deliberate) so the best-effort
    ``except (OSError, ValueError)`` cache readers across the codebase keep their
    fail-soft behavior (a malformed cache never blocks a save) without edits, and
    so it sits alongside ``json.JSONDecodeError`` (itself a ``ValueError``).
    """


class HandoffCache(StrictBoundaryModel):
    """The pre-session CLI->extension handoff blob (``handoff/<run_id>.json``).

    Open-ended (``extra="allow"``): the handoff carries arbitrary ``handoff_extra``
    keys (and whatever ``perk state new-run --handoff`` writes), recovered downstream
    by ``plan-save``/``objective create``. The known keys below are declared so those
    recovery sites get typed attribute access; undeclared keys still round-trip.
    """

    model_config = ConfigDict(frozen=True, extra="allow", strict=True)
    run_id: str
    consumed: bool
    mode: str | None = None
    stage: str | None = None
    pi_session_id: str | None = None
    objective_id: str | None = None
    node_id: str | None = None
    adopt_from: str | None = None
    supersedes: str | None = None
    consumed_learn: StrTuple = ()


class DispatchCache(StrictBoundaryModel):
    """The durable ``run_id -> plan`` dispatch record (``scratch/runs/*/dispatch.json``).

    ``plan_ref``/``run_handle`` stay opaque dicts here — their nested shape is owned by the
    ``DispatchRecord``/``RunHandle`` domain models, not validated at this tier.
    """

    run_id: str
    stage: str
    plan_ref: dict[str, Any]
    runner: str
    kind: str
    status: str
    dispatched_at: str
    run_handle: dict[str, Any] | None = None
    error: str | None = None


class PlanRefCache(StrictBoundaryModel):
    """The active plan->branch ref pointer (``plan-ref.json``, §8.4)."""

    provider: str
    pr_id: str
    url: str
    # StrTuple (not a strict ``tuple[str, ...]``): the on-disk shape is a JSON list.
    labels: StrTuple
    objective_id: str | None = None
    consumed_learn: StrTuple = ()
    base: str | None = None


class AgentSessionCache(StrictBoundaryModel):
    """The Linear ``AgentSession`` pointer for this worktree (``agent-session.json``, §8.22)."""

    session_id: str
    issue: str
    url: str | None = None


# The land->learn semaphore: `land` sets it, `learn` clears it; while present it
# signals the worktree is not yet releasable. Single source of the name across planes (the TS
# twin is `PENDING_LEARN` in extension/substrate/cache.ts).
PENDING_LEARN = "pending-learn"


def workflow_dir(root: Path) -> Path:
    """The ``.perk/workflow/`` directory under ``root``."""
    return root / ".perk" / "workflow"


def ensure_layout(root: Path) -> Path:
    """Idempotently create the four ``.perk/workflow/`` subtrees; return the dir."""
    wd = workflow_dir(root)
    for sub in SUBDIRS:
        (wd / sub).mkdir(parents=True, exist_ok=True)
    return wd


# --- scratch: per-run inter-process files (scratch/runs/<run_id>/<name>) ---------------
#
# This module is the EXTERIOR accessor seam for scratch/session-data paths (contracts.md §8.1):
# production code never hand-builds the `scratch`/`runs` path segments
# outside this module (guard-tested by tests/test_cache_guard.py; the interior twins are
# extension/substrate/cache.ts + extension/substrate/sessionData.ts).


def scratch_dir(root: Path) -> Path:
    """The ``.perk/workflow/scratch/`` directory under ``root``."""
    return workflow_dir(root) / "scratch"


def run_scratch_dir(root: Path, run_id: str) -> Path:
    """The scratch directory for a run."""
    return scratch_dir(root) / "runs" / run_id


def list_run_ids(root: Path) -> list[str]:
    """Names of all run scratch dirs under ``scratch/runs/`` (sorted; ``[]`` when absent).

    Twin of the TS ``listRunIds`` (extension/substrate/cache.ts). Stray non-directory entries
    are ignored.
    """
    runs_root = scratch_dir(root) / "runs"
    if not runs_root.is_dir():
        return []
    return sorted(p.name for p in runs_root.iterdir() if p.is_dir())


def write_scratch(root: Path, run_id: str, name: str, content: str) -> Path:
    """Write a scratch file for a run (creating the run dir); return its path."""
    directory = run_scratch_dir(root, run_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


def read_scratch(root: Path, run_id: str, name: str) -> str | None:
    """Read a scratch file, or ``None`` if it does not exist."""
    path = run_scratch_dir(root, run_id) / name
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


# --- session data: run-scoped session artifacts (scratch/runs/<run_id>/data/<name>) ------
#
# The session data dir — a dedicated `data/` subdir so run-scoped
# session artifacts never overlap perk machine records (dispatch.json, events.ndjson, ci-*.md)
# living directly in the run dir. Created lazily on first write; helpers degrade gracefully
# (absence and I/O failure -> ``None`` + a stderr warning, never an exception).


def session_data_dir(root: Path, run_id: str) -> Path:
    """The session data dir for a run (pure path; created lazily by ``write_session_data``)."""
    return run_scratch_dir(root, run_id) / "data"


def write_session_data(root: Path, run_id: str, name: str, content: str) -> Path | None:
    """Write a session-data file (creating the dir); return its path, or ``None`` on failure.

    Never raises: an ``OSError`` is reported loudly to stderr and yields ``None`` (a broken
    disk must not wedge a session).
    """
    directory = session_data_dir(root, run_id)
    path = directory / name
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        user_output(f"warning: could not write session data {path}: {exc}")
        return None
    return path


def read_session_data(root: Path, run_id: str, name: str) -> str | None:
    """Read a session-data file; ``None`` when absent (normal, branchable) or unreadable.

    Absence is silent; an OS/decode error warns to stderr and yields ``None`` (never raises).
    """
    path = session_data_dir(root, run_id) / name
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        user_output(f"warning: could not read session data {path}: {exc}")
        return None


# --- handoff: pre-session CLI->extension cold-door blob (handoff/<run_id>.json) ---------


def handoff_path(root: Path, run_id: str) -> Path:
    """The handoff file path for a run."""
    return workflow_dir(root) / "handoff" / f"{run_id}.json"


def list_handoff_run_ids(root: Path) -> list[str]:
    """Stems of all handoff blobs under ``handoff/`` (sorted; ``[]`` when absent).

    Mirrors :func:`list_run_ids` so ``perk/state/gc.py`` collects orphan handoffs (no run dir) too.
    Exterior-only — there is no TS twin (GC is CLI-owned).
    """
    handoff_root = workflow_dir(root) / "handoff"
    if not handoff_root.is_dir():
        return []
    return sorted(p.stem for p in handoff_root.glob("*.json") if p.is_file())


def write_handoff(root: Path, run_id: str, data: dict[str, Any]) -> Path:
    """Write a fresh (un-consumed) handoff blob for a run; return its path.

    ``run_id`` and ``consumed: False`` are authoritative (they override anything in
    ``data``). The extension marks it consumed on claim (§8.2).
    """
    path = handoff_path(root, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**data, "run_id": run_id, "consumed": False}
    with translate_validation_errors(CacheError, source=str(path)):
        model = HandoffCache.model_validate(payload)
    path.write_text(
        json.dumps(model.model_dump(mode="json", exclude_unset=True), indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def read_handoff(root: Path, run_id: str) -> HandoffCache | None:
    """Read + validate a handoff blob, or ``None`` if it does not exist."""
    path = handoff_path(root, run_id)
    if not path.is_file():
        return None
    with translate_validation_errors(CacheError, source=str(path)):
        return HandoffCache.model_validate(json.loads(path.read_text(encoding="utf-8")))


def mark_handoff_consumed(root: Path, run_id: str, *, pi_session_id: str | None = None) -> None:
    """Mark a handoff consumed (idempotent); a no-op if the handoff is absent.

    Keeps the file (audit + GC signal); never deletes it (the GC pitfall, §8.1).
    """
    data = read_handoff(root, run_id)
    if data is None:
        return
    update: dict[str, Any] = {"consumed": True}
    if pi_session_id is not None:
        update["pi_session_id"] = pi_session_id
    updated = data.model_copy(update=update)
    handoff_path(root, run_id).write_text(
        json.dumps(updated.model_dump(mode="json", exclude_unset=True), indent=2) + "\n",
        encoding="utf-8",
    )


# --- dispatch: the durable run_id->plan linkage for a remote drive (§8.13) -----


def dispatch_path(root: Path, run_id: str) -> Path:
    """The dispatch-record path for a remote drive (under the run's scratch dir)."""
    return run_scratch_dir(root, run_id) / "dispatch.json"


def write_dispatch(root: Path, run_id: str, data: dict[str, Any]) -> Path:
    """Write the durable ``run_id -> plan`` dispatch record (creating the run dir); return its
    path. ``run_id`` is authoritative (it overrides anything in ``data``), mirroring
    ``write_handoff``. The supervisor enumerates ``scratch/runs/*/dispatch.json``
    to correlate ``run_id <-> plan <-> PR`` (§8.13).
    """
    directory = run_scratch_dir(root, run_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "dispatch.json"
    payload = {**data, "run_id": run_id}
    with translate_validation_errors(CacheError, source=str(path)):
        model = DispatchCache.model_validate(payload)
    path.write_text(
        json.dumps(model.model_dump(mode="json", exclude_unset=True), indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def read_dispatch(root: Path, run_id: str) -> DispatchCache | None:
    """Read + validate a dispatch record, or ``None`` if it does not exist."""
    path = dispatch_path(root, run_id)
    if not path.is_file():
        return None
    with translate_validation_errors(CacheError, source=str(path)):
        return DispatchCache.model_validate(json.loads(path.read_text(encoding="utf-8")))


def list_dispatch_records(root: Path) -> list[DispatchCache]:
    """All dispatch records under ``scratch/runs/*/dispatch.json``, newest-first.

    Reads every run's ``dispatch.json``; skips a missing/unparseable file (loud-but-non-fatal
    to stderr, never raises — a corrupt record must not break the supervisor read). Sorted by
    ``dispatched_at`` descending (empty/missing timestamps sort last). An absent ``scratch/runs/``
    dir is the normal pre-dispatch state and yields ``[]``.
    """
    records: list[DispatchCache] = []
    for run_id in list_run_ids(root):
        path = run_scratch_dir(root, run_id) / "dispatch.json"
        if not path.is_file():
            continue
        try:
            with translate_validation_errors(CacheError, source=str(path)):
                records.append(
                    DispatchCache.model_validate(json.loads(path.read_text(encoding="utf-8")))
                )
        except (OSError, json.JSONDecodeError, CacheError) as exc:
            user_output(f"warning: skipping unreadable dispatch record {path}: {exc}")
            continue
    records.sort(key=lambda d: d.dispatched_at, reverse=True)
    return records


# --- plan-ref: the active plan->branch ref pointer (plan-ref.json) -----------------------


def plan_ref_path(root: Path) -> Path:
    """The ``cache.plan-ref`` pointer file (the local mirror of the canonical GitHub plan)."""
    return workflow_dir(root) / "plan-ref.json"


def write_plan_ref(root: Path, data: dict[str, Any]) -> Path:
    """Write the provider-agnostic plan ref (§8.4) to ``plan-ref.json``; return its path.

    ``exclude_unset`` preserves the input key set verbatim (the full real 7-key shape and the
    synthetic partial shape alike) — the on-disk shape is unchanged.
    """
    path = plan_ref_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with translate_validation_errors(CacheError, source=str(path)):
        model = PlanRefCache.model_validate(data)
    path.write_text(
        json.dumps(model.model_dump(mode="json", exclude_unset=True), indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def read_plan_ref(root: Path) -> PlanRefCache | None:
    """Read + validate the plan ref, or ``None`` if it does not exist."""
    path = plan_ref_path(root)
    if not path.is_file():
        return None
    with translate_validation_errors(CacheError, source=str(path)):
        return PlanRefCache.model_validate(json.loads(path.read_text(encoding="utf-8")))


def plan_body_path(root: Path) -> Path:
    """The ``cache.plan`` materialized plan-body file (twin of the TS ``planBodyPath``)."""
    return workflow_dir(root) / "plan.md"


def write_plan_body(root: Path, body: str) -> Path:
    """Materialize the plan body markdown to ``plan.md`` (so in-session checkpoints can seed from
    its ``## Steps`` list); return its path."""
    path = plan_body_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
    return path


# --- agent-session: the Linear AgentSession pointer for this worktree (agent-session.json) ---


def agent_session_path(root: Path) -> Path:
    """The ``cache.agent-session`` pointer file (the Linear ``AgentSession`` mirror, §8.22)."""
    return workflow_dir(root) / "agent-session.json"


def write_agent_session(root: Path, data: dict[str, Any]) -> Path:
    """Write the Linear agent-session pointer (§8.22) to ``agent-session.json``; return its path.

    Shape: ``{"session_id": str, "issue": str, "url": str | None}`` — mirrors the
    ``write_plan_ref``/``read_plan_ref`` conventions.
    """
    path = agent_session_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with translate_validation_errors(CacheError, source=str(path)):
        model = AgentSessionCache.model_validate(data)
    path.write_text(
        json.dumps(model.model_dump(mode="json", exclude_unset=True), indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def read_agent_session(root: Path) -> AgentSessionCache | None:
    """Read + validate the agent-session pointer, or ``None`` if it does not exist."""
    path = agent_session_path(root)
    if not path.is_file():
        return None
    with translate_validation_errors(CacheError, source=str(path)):
        return AgentSessionCache.model_validate(json.loads(path.read_text(encoding="utf-8")))


# --- markers: existence-based friction semaphores (markers/<name>) ----------------------


def marker_path(root: Path, name: str) -> Path:
    """The path of an existence-only marker file."""
    return workflow_dir(root) / "markers" / name


def set_marker(root: Path, name: str) -> Path:
    """Create an (empty) marker file; return its path."""
    path = marker_path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def has_marker(root: Path, name: str) -> bool:
    """True when the marker exists."""
    return marker_path(root, name).is_file()


def clear_marker(root: Path, name: str) -> None:
    """Remove a marker if present (idempotent)."""
    marker_path(root, name).unlink(missing_ok=True)
