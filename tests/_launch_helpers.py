"""Shared values and builders for the `test_launch*` suite.

`_PLAN_REF` and the cached `_stage`/`_config` builders are used by both split files. Cross-file
fixtures live in ``conftest.py`` so pytest always registers them. Single-tier helpers
(`_FakeRunner`, `_sha`, …) stay with their own section's file. Leading underscore so pytest does
not collect this module.
"""

from functools import cache

from perk import plan
from perk.run.launch.worktree import WorktreeRequest
from perk.substrate.config import Config
from perk.substrate.registry import Stage, load_registry

_PLAN_REF = plan.PlanRef(
    provider="github",
    pr_id="42",
    url="https://gh/o/r/issues/42",
    labels=("perk:plan",),
    objective_id=None,
)

# Backwards-compat alias: the durable plan-ref domain object is now a frozen `plan.PlanRef`
# dataclass everywhere (the seams the dict-→model thread retyped accept it directly).
_PLAN_REF_MODEL = _PLAN_REF

# The plan-ref as the on-disk / `--json` dict (the full 7-key PlanRefOut shape), for asserting
# the dry-run JSON payload.
_PLAN_REF_JSON = plan.PlanRefOut.from_domain(_PLAN_REF).model_dump(mode="json")


@cache
def _stage(stage_id: str) -> Stage:
    return next(s for s in load_registry().stages if s.id == stage_id)


@cache
def _request(stage_id: str) -> WorktreeRequest:
    """The stage's positioner request (the `resolve_worktree` policy+consumer input)."""
    return WorktreeRequest.for_stage(_stage(stage_id))


def _config(tmp_path, user_bindings=None) -> Config:
    return Config(
        worktree_root=tmp_path / ".worktrees",
        user_bindings=user_bindings if user_bindings is not None else [],
    )
