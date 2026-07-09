"""The perk-owned subagent agent-definition convergence."""

from pathlib import Path

from perk import _resources

# The canonical perk subagent-definition names (file stems under `agents/`). This list is the
# SSOT for the delivered agent-def set; it is kept sorted — update it here when perk agents are
# added/removed. perk owns and overwrites the whole `.pi/agents/perk/` subdir from these.
PERK_AGENTS: tuple[str, ...] = (
    "adversarial-reviewer",
    "conflict-resolver",
    "learn-analyst",
    "objective-explorer",
    "pr-reviewer",
    "review-classifier",
)


def _converge_subagent_agents(root: Path, *, apply: bool = True) -> list[str]:
    """Converge the perk-owned agent definitions for the borrowed `pi-subagents` engine.

    perk delivers its three agent defs (``PERK_AGENTS``) into the perk-owned
    ``.pi/agents/perk/`` subdir — a committed managed convergence mirroring the skills /
    AGENTS-block design. Sources are bundled into the wheel as ``perk/_agents`` (force-include)
    + the editable repo sibling ``agents/``, resolved via :func:`_resources.agents_dir`. perk
    owns the *whole* ``perk/`` subdir: each ``<name>.md`` is written byte-for-byte from its
    source, and any stray ``*.md`` not in ``PERK_AGENTS`` is removed. Nothing outside
    ``.pi/agents/perk/`` is touched (user agents live elsewhere under ``.pi/agents/``). The
    committed ``.pi/agents/.gitkeep`` is still ensured so the dir exists when a consumer has no
    top-level agents.

    The would-be change list is computed identically for ``apply`` True/False, so the
    auto-generated ``subagent-agents`` managed doctor check reports drift (``apply=False``) and
    ``doctor --fix`` repairs it (``apply=True``). Returns the accumulated change list (empty on
    a converged repo → idempotent).
    """
    source_dir = _resources.agents_dir()
    desired = {name: (source_dir / f"{name}.md").read_bytes() for name in PERK_AGENTS}

    changes: list[str] = []
    agents = root / ".pi" / "agents"
    perk_dir = agents / "perk"

    # Deliver / refresh each managed def.
    for name in PERK_AGENTS:
        target = perk_dir / f"{name}.md"
        current = target.read_bytes() if target.is_file() else None
        if current == desired[name]:
            continue
        verb = "updated" if current is not None else "created"
        if apply:
            perk_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(desired[name])
        changes.append(f".pi/agents/perk/{name}.md: {verb}")

    # Prune strays — perk owns the whole `perk/` subdir.
    if perk_dir.is_dir():
        for stray in sorted(perk_dir.glob("*.md")):
            if stray.stem in desired:
                continue
            if apply:
                stray.unlink()
            changes.append(f".pi/agents/perk/{stray.name}: removed")

    # The committed `.gitkeep` keeps `.pi/agents/` present even with no top-level agents.
    gitkeep = agents / ".gitkeep"
    if not gitkeep.is_file():
        if apply:
            agents.mkdir(parents=True, exist_ok=True)
            gitkeep.write_text("", encoding="utf-8")
        changes.append(".pi/agents/: created")

    return changes
