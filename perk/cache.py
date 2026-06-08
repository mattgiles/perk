"""``.pi/workflow/`` cache-tier I/O (Q2 / contracts.md §8.1).

Free functions over an explicit repo ``root`` (erk's scratch/markers style). **Both
planes read and write the same files**; the TS twin is ``extension/cache.ts``. These are
state-tiering *primitives* — no workflow semantics (no ``pending-learn`` meaning, no GC
policy; those land in Phase 1 / `doctor`). LBYL throughout; absence is a normal,
branchable condition (reads return ``None``, not an exception).
"""

import json
from pathlib import Path
from typing import Any

from perk.output import user_output

# The canonical `.pi/workflow/` subtrees (public so `perk doctor` can verify the layout).
SUBDIRS: tuple[str, ...] = ("plans", "scratch/runs", "handoff", "markers")

# The land->learn semaphore (Q2 / Q5): `land` sets it, `learn` clears it; while present it
# signals the worktree is not yet releasable. Single source of the name across planes (the TS
# twin is `PENDING_LEARN` in extension/cache.ts).
PENDING_LEARN = "pending-learn"


def workflow_dir(root: Path) -> Path:
    """The ``.pi/workflow/`` directory under ``root``."""
    return root / ".pi" / "workflow"


def ensure_layout(root: Path) -> Path:
    """Idempotently create the four ``.pi/workflow/`` subtrees; return the dir."""
    wd = workflow_dir(root)
    for sub in SUBDIRS:
        (wd / sub).mkdir(parents=True, exist_ok=True)
    return wd


# --- scratch: per-run inter-process files (scratch/runs/<run_id>/<name>) ---------------


def run_scratch_dir(root: Path, run_id: str) -> Path:
    """The scratch directory for a run."""
    return workflow_dir(root) / "scratch" / "runs" / run_id


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


# --- handoff: pre-session CLI->extension cold-door blob (handoff/<run_id>.json) ---------


def handoff_path(root: Path, run_id: str) -> Path:
    """The handoff file path for a run."""
    return workflow_dir(root) / "handoff" / f"{run_id}.json"


def write_handoff(root: Path, run_id: str, data: dict[str, Any]) -> Path:
    """Write a fresh (un-consumed) handoff blob for a run; return its path.

    ``run_id`` and ``consumed: False`` are authoritative (they override anything in
    ``data``). The extension marks it consumed on claim (§8.2).
    """
    path = handoff_path(root, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**data, "run_id": run_id, "consumed": False}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def read_handoff(root: Path, run_id: str) -> dict[str, Any] | None:
    """Read a handoff blob, or ``None`` if it does not exist."""
    path = handoff_path(root, run_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def mark_handoff_consumed(root: Path, run_id: str, *, pi_session_id: str | None = None) -> None:
    """Mark a handoff consumed (idempotent); a no-op if the handoff is absent.

    Keeps the file (audit + GC signal); never deletes it (the erk GC pitfall, §8.1).
    """
    data = read_handoff(root, run_id)
    if data is None:
        return
    data["consumed"] = True
    if pi_session_id is not None:
        data["pi_session_id"] = pi_session_id
    handoff_path(root, run_id).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# --- dispatch: the durable run_id->plan linkage for a remote drive (Node 2.1, §8.13) -----


def dispatch_path(root: Path, run_id: str) -> Path:
    """The dispatch-record path for a remote drive (under the run's scratch dir)."""
    return run_scratch_dir(root, run_id) / "dispatch.json"


def write_dispatch(root: Path, run_id: str, data: dict[str, Any]) -> Path:
    """Write the durable ``run_id -> plan`` dispatch record (creating the run dir); return its
    path. ``run_id`` is authoritative (it overrides anything in ``data``), mirroring
    ``write_handoff``. The supervisor (Node 3.1) enumerates ``scratch/runs/*/dispatch.json``
    to correlate ``run_id <-> plan <-> PR`` (§8.13).
    """
    directory = run_scratch_dir(root, run_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "dispatch.json"
    payload = {**data, "run_id": run_id}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def read_dispatch(root: Path, run_id: str) -> dict[str, Any] | None:
    """Read a dispatch record, or ``None`` if it does not exist."""
    path = dispatch_path(root, run_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_dispatch_records(root: Path) -> list[dict[str, Any]]:
    """All dispatch records under ``scratch/runs/*/dispatch.json``, newest-first.

    Reads every run's ``dispatch.json``; skips a missing/unparseable file (loud-but-non-fatal
    to stderr, never raises — a corrupt record must not break the supervisor read). Sorted by
    ``dispatched_at`` descending (empty/missing timestamps sort last). An absent ``scratch/runs/``
    dir is the normal pre-dispatch state and yields ``[]``.
    """
    runs_root = workflow_dir(root) / "scratch" / "runs"
    if not runs_root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for run_dir in sorted(runs_root.iterdir()):
        path = run_dir / "dispatch.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            user_output(f"warning: skipping unreadable dispatch record {path}: {exc}")
            continue
        if not isinstance(data, dict):
            user_output(f"warning: skipping non-object dispatch record {path}")
            continue
        records.append(data)
    records.sort(key=lambda d: str(d.get("dispatched_at", "")), reverse=True)
    return records


# --- plan-ref: the active plan->branch ref pointer (plan-ref.json) -----------------------


def plan_ref_path(root: Path) -> Path:
    """The ``cache.plan-ref`` pointer file (the local mirror of the canonical GitHub plan)."""
    return workflow_dir(root) / "plan-ref.json"


def write_plan_ref(root: Path, data: dict[str, Any]) -> Path:
    """Write the provider-agnostic plan ref (§8.4) to ``plan-ref.json``; return its path."""
    path = plan_ref_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def read_plan_ref(root: Path) -> dict[str, Any] | None:
    """Read the plan ref, or ``None`` if it does not exist."""
    path = plan_ref_path(root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def plan_body_path(root: Path) -> Path:
    """The ``cache.plan`` materialized plan-body file (twin of the TS ``planBodyPath``)."""
    return workflow_dir(root) / "plan.md"


def write_plan_body(root: Path, body: str) -> Path:
    """Materialize the plan body markdown to ``plan.md`` (so in-session checkpoints can seed from
    its ``## Steps`` list, P2.T2c); return its path."""
    path = plan_body_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
    return path


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
