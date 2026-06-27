"""Shared launch fake substrate for the `test_launch*` suite.

`_PLAN_REF`, the autouse `_no_network_clone_warm` fixture (imported into each sibling's namespace —
an imported `@pytest.fixture(autouse=True)` auto-applies in the importing module), and the
`_stage`/`_config` builders are used by ≥2 split files. The single-tier env-capture/runner helpers
(`_launch_capturing_env`, `_FakeRunner`, `_sha`, …) travel with their own section's file. Leading
underscore so pytest does not collect this module.
"""

import pytest

from perk import plan
from perk.run import launch
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


@pytest.fixture(autouse=True)
def _no_network_clone_warm(monkeypatch):
    """Stub the pre-exec npm-install warming so launch_stage tests never hit the network.

    `launch_stage` warms perk's `@mgiles/perk` npm install before exec; in a throwaway `git_repo`
    (not the self-repo, absent) that would shell a real `npm install`. The dedicated call-site
    tests override it with their own recorder.
    """
    monkeypatch.setattr(
        launch.init, "ensure_extension_install_present", lambda repo_root, *, self_repo: None
    )


def _stage(stage_id: str) -> Stage:
    return next(s for s in load_registry().stages if s.id == stage_id)


def _config(tmp_path, user_bindings=None) -> Config:
    return Config(
        worktree_root=tmp_path / ".worktrees",
        user_bindings=user_bindings if user_bindings is not None else [],
    )
