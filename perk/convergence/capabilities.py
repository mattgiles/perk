"""The capability inventory — the single declared list of what ``perk init`` manages.

A **lightweight, code-level** capability system: Pi's package
model already covers most of "capabilities", so perk keeps only the load-bearing core — a
declared inventory with a required-vs-optional split and a self-vs-consumer scope. ``init``
reports against this list; **``doctor`` reuses the same tuple** and adds a ``verify()``
side (the registry-as-SSOT value, minus the ABC/lifecycle machinery).

The set deliberately ships all-``required``, all-``scope="both"``: the ``required`` /
``scope`` fields are the rail that optional capabilities + consumer-only pieces ride later.
The installed-optional **state file**, the ``Capability`` ABC, and a ``capability
add/remove`` CLI are **deferred** until the first *optional* capability exists.
"""

from dataclasses import dataclass
from typing import Literal

Scope = Literal["both", "self", "consumer"]


@dataclass(frozen=True)
class Capability:
    name: str
    summary: str
    required: bool
    scope: Scope


CAPABILITIES: tuple[Capability, ...] = (
    Capability("perk-extension", "perk's own Pi extension", required=True, scope="both"),
    Capability(
        "borrowed-packages",
        "crossover scaffolding (diff + subagents engine)",
        required=True,
        scope="both",
    ),
    Capability("settings-wiring", ".pi/settings.json package entries", required=True, scope="both"),
    Capability("workflow-dir", ".perk/workflow/ cache layout", required=True, scope="both"),
    Capability("config", ".pi/perk.toml + perk.local.toml", required=True, scope="both"),
    Capability("gitignore-block", "managed .gitignore entries", required=True, scope="both"),
    Capability("agents-block", "managed AGENTS.md conventions", required=True, scope="both"),
    Capability(
        "subagent-engine",
        "borrowed pi-subagents delegation engine + perk-owned agent defs",
        required=True,
        scope="both",
    ),
    Capability(
        "skills-manifest",
        "perk skills declared in .agents/manifest.d/perk.yaml for the skills CLI",
        required=True,
        scope="both",
    ),
    Capability(
        "runner-workflow",
        "managed GitHub Actions runner (.github/workflows/perk-run.yml + composite setup action)",
        required=True,
        scope="both",
    ),
)


def applicable(self_repo: bool) -> tuple[Capability, ...]:
    """Capabilities that apply to this repo kind (self-vs-consumer filter).

    Returns the full set either way (every capability is ``scope="both"``); the filter is the
    rail for future ``scope="self"`` / ``scope="consumer"`` pieces.
    """
    wanted: tuple[Scope, ...] = ("both", "self") if self_repo else ("both", "consumer")
    return tuple(cap for cap in CAPABILITIES if cap.scope in wanted)
