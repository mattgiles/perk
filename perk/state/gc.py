"""GC policy for ``.pi/workflow/`` run state (contracts.md §8.1).

``scratch/runs/<run_id>/`` dirs and ``handoff/<run_id>.json`` blobs accumulate forever (the
pitfall §8.1 cites — ``mark_handoff_consumed`` keeps the file as an audit + GC signal). This
module is the *policy* home: pure-read
eligibility evaluation (:func:`plan_prune`) + destructive execution (:func:`execute_prune`),
surfaced by ``perk state prune`` and the ``cache-gc`` doctor check. Exterior-owned (the CLI);
there is no TS twin, consistent with ``perk/state/cache.py``'s "no GC policy here" note.

Two eligibility rules:

- **terminal-stage prune** — the run's handoff records a *consumed*, registry-terminal stage
  (a stage with empty ``successors``; currently exactly ``learn``, computed never hardcoded);
- **age-based prune** — anything else older than ``max_age_days`` (default 14). This is the
  rule that covers warm-minted run dirs which have no handoff/stage at all.

Degrade-graceful: an unreadable handoff contributes no stage (age rule only — never
terminal-prune on a guess); a broken registry degrades the terminal set to empty with a stderr
warning (the age rule still applies — GC must never crash on a broken install); deletion
failures are collected per item and reported loudly while the sweep continues.
"""

import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from perk.state import cache, run_id
from perk.substrate import registry
from perk.substrate.output import user_output

# The age threshold (days) below which a non-terminal candidate is kept. A module constant
# (the contract pins 14); a `[gc]` TOML table is deliberately deferred (premature).
DEFAULT_MAX_AGE_DAYS = 14


@dataclass(frozen=True)
class PruneCandidate:
    """A run-state item eligible for pruning. Either path may be ``None`` (orphan handoff with
    no run dir, or a warm run dir with no handoff)."""

    run_id: str
    reason: str
    run_dir: Path | None
    handoff: Path | None


@dataclass(frozen=True)
class PrunePlan:
    """The result of :func:`plan_prune`: the eligible candidates + a count of the kept ones."""

    eligible: list[PruneCandidate]
    kept: int


def terminal_stage_ids() -> frozenset[str]:
    """The registry's terminal stage ids (empty ``successors``; currently ``{learn}``).

    Degrades to ``frozenset()`` with a stderr warning on a ``RegistryError`` — GC must never
    crash on a broken install (the ``registry`` doctor check already fails loudly there).
    """
    try:
        reg = registry.load_registry()
    except registry.RegistryError as exc:
        user_output(
            f"warning: GC could not load the registry (terminal-stage rule disabled): {exc}"
        )
        return frozenset()
    return frozenset(s.id for s in reg.stages if not s.successors)


def _candidate_age_seconds(
    candidate: str, run_dir: Path | None, handoff: Path | None, now: datetime
) -> float | None:
    """Age in seconds: the ULID self-date when the name is a run_id, else the run dir's (or
    handoff file's) ``st_mtime`` fallback for stray non-ULID names. ``None`` if undeterminable.
    """
    if run_id.is_run_id(candidate):
        return (now - run_id.timestamp(candidate)).total_seconds()
    for path in (run_dir, handoff):
        if path is not None and path.exists():
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            return (now - mtime).total_seconds()
    return None


def plan_prune(
    root: Path,
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    now: datetime | None = None,
) -> PrunePlan:
    """Evaluate the prune policy (pure read). ``now`` is injectable for tests.

    Candidates are the union of run-dir names and handoff blob stems, so orphan handoffs with no
    run dir are collected too. Per candidate, in order: current-run protection (``PERK_RUN_ID``
    base-ULID match) → terminal-stage rule → age rule.
    """
    now = now or datetime.now(UTC)
    max_age_seconds = max_age_days * 86400
    terminals = terminal_stage_ids()

    env_run_id = os.environ.get("PERK_RUN_ID")
    protected_base = run_id.base_ulid(env_run_id) if env_run_id else None

    candidates = sorted(set(cache.list_run_ids(root)) | set(cache.list_handoff_run_ids(root)))

    eligible: list[PruneCandidate] = []
    kept = 0
    for candidate in candidates:
        run_dir = cache.run_scratch_dir(root, candidate)
        run_dir = run_dir if run_dir.is_dir() else None
        handoff = cache.handoff_path(root, candidate)
        handoff = handoff if handoff.is_file() else None

        # 1. Current-run protection: never delete the run a live session is keyed on (incl. its
        #    fork-children, matched on the base ULID).
        if protected_base is not None and run_id.base_ulid(candidate) == protected_base:
            kept += 1
            continue

        # 2. Terminal-stage rule: a consumed handoff whose stage has empty registry successors.
        stage = _consumed_terminal_stage(root, candidate, terminals)
        if stage is not None:
            eligible.append(PruneCandidate(candidate, "terminal stage completed", run_dir, handoff))
            continue

        # 3. Age rule.
        age = _candidate_age_seconds(candidate, run_dir, handoff, now)
        if age is not None and age > max_age_seconds:
            eligible.append(
                PruneCandidate(candidate, f"older than {max_age_days}d", run_dir, handoff)
            )
            continue
        kept += 1

    return PrunePlan(eligible=eligible, kept=kept)


def _consumed_terminal_stage(root: Path, candidate: str, terminals: frozenset[str]) -> str | None:
    """The candidate's stage if its handoff is consumed AND its stage is registry-terminal; else
    ``None``. An unreadable/unparseable handoff contributes no stage (conservative)."""
    try:
        data = cache.read_handoff(root, candidate)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("consumed") is not True:
        return None
    stage = data.get("stage")
    if isinstance(stage, str) and stage in terminals:
        return stage
    return None


def execute_prune(plan: PrunePlan) -> list[str]:
    """Delete each eligible candidate's run dir + handoff blob. Returns error strings (empty on
    full success); each ``OSError`` is reported loudly via stderr and never raises (the sweep
    continues, mirroring ``worktree wipe``'s per-item skip posture)."""
    errors: list[str] = []
    for candidate in plan.eligible:
        if candidate.run_dir is not None:
            try:
                shutil.rmtree(candidate.run_dir)
            except OSError as exc:
                msg = f"{candidate.run_id}: could not remove {candidate.run_dir}: {exc}"
                user_output(f"warning: {msg}")
                errors.append(msg)
        if candidate.handoff is not None:
            try:
                candidate.handoff.unlink(missing_ok=True)
            except OSError as exc:
                msg = f"{candidate.run_id}: could not remove {candidate.handoff}: {exc}"
                user_output(f"warning: {msg}")
                errors.append(msg)
    return errors
