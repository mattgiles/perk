"""Shared launch fake substrate for the `test_launch*` suite.

`_PLAN_REF`, the autouse `_no_network_clone_warm` fixture (imported into each sibling's namespace —
an imported `@pytest.fixture(autouse=True)` auto-applies in the importing module), and the
`_stage`/`_config` builders are used by ≥2 split files. The single-tier env-capture/runner helpers
(`_launch_capturing_env`, `_FakeRunner`, `_sha`, …) travel with their own section's file. Leading
underscore so pytest does not collect this module.
"""

import pytest

from perk.run import launch
from perk.substrate.config import Config
from perk.substrate.registry import Stage, load_registry

_PLAN_REF = {
    "provider": "github",
    "pr_id": "42",
    "url": "https://gh/o/r/issues/42",
    "labels": ["perk:plan"],
    "objective_id": None,
}


@pytest.fixture(autouse=True)
def _no_network_clone_warm(monkeypatch):
    """Stub the pre-exec clone warming (#655) so launch_stage tests never `git clone` the network.

    `launch_stage` warms pi's git-package clone before exec; in a throwaway `git_repo` (not the
    self-repo, clone absent) that would shell a real `git clone`. The dedicated call-site test
    overrides this with its own recorder.
    """
    monkeypatch.setattr(
        launch.init, "ensure_extension_clone_present", lambda repo_root, *, self_repo: None
    )


def _stage(stage_id: str) -> Stage:
    return next(s for s in load_registry().stages if s.id == stage_id)


def _config(tmp_path, user_bindings=None) -> Config:
    return Config(
        worktree_root=tmp_path / ".worktrees",
        user_bindings=user_bindings if user_bindings is not None else [],
    )
