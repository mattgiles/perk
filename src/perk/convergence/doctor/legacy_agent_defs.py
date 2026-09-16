"""The retired file-delivered ``.pi/agents/perk/`` — one preflight shared by check and fix.

perk's ``perk.*`` agent defs ship inside the extension npm package as pi-subagents package agents
(contracts §8.3); the directory an older perk wrote into consumer repos is no longer managed. It
is not harmless either: pi-subagents ranks project defs above package defs, so a leftover copy
silently shadows the shipped def of the same name. The ``subagent-engine`` doctor check reports
it and the ``--fix`` migration removes it — both through this ONE classification, so the warn
detail, the stated remediation, and the fix's refusal never disagree.

The classification never follows a link and never trusts a shape perk did not produce: the
retired convergence wrote a FLAT directory of ``<name>.md`` files, so anything else (a symlink
anywhere on the path or inside it, a subdirectory, a non-``.md`` file) is an offender the fix
refuses to touch. A leaf module (``pathlib`` + the init facade), so ``checks`` and ``fixes`` can
both import it without importing each other.
"""

from dataclasses import dataclass
from pathlib import Path

from perk.convergence import init

# Repo-relative, as rendered in every human-facing line.
LEGACY_AGENT_DEFS_REL = ".pi/agents/perk"


@dataclass(frozen=True)
class LegacyAgentDefs:
    """What a leftover ``.pi/agents/perk/`` holds, classified without following any link.

    ``present`` is False when nothing sits at the path (not even a dangling link). ``symlink``
    names the first symlinked component on the way to (or at) the directory — ``.pi``,
    ``.pi/agents`` or ``.pi/agents/perk`` — in which case ``defs``/``offenders`` are empty
    (nothing behind a link is inspected). ``defs`` are the regular ``<name>.md`` files the fix
    may remove; ``offenders`` label every other entry.
    """

    present: bool
    symlink: str | None
    defs: tuple[Path, ...]
    offenders: tuple[str, ...]


def inspect_legacy_agent_defs(root: Path) -> LegacyAgentDefs:
    """Classify the leftover directory (read-only; an unreadable directory is one offender)."""
    legacy = root / ".pi" / "agents" / "perk"
    for component in (root / ".pi", root / ".pi" / "agents", legacy):
        if component.is_symlink():
            return LegacyAgentDefs(
                present=True,
                symlink=str(component.relative_to(root)),
                defs=(),
                offenders=(),
            )
    if not legacy.exists():
        return LegacyAgentDefs(present=False, symlink=None, defs=(), offenders=())
    defs: list[Path] = []
    offenders: list[str] = []
    try:
        entries = sorted(legacy.iterdir())
    except OSError as exc:
        return LegacyAgentDefs(
            present=True, symlink=None, defs=(), offenders=(f"unreadable directory ({exc})",)
        )
    for entry in entries:
        if entry.is_symlink():
            offenders.append(f"{entry.name} (symlink)")
        elif entry.is_dir():
            offenders.append(f"{entry.name}/ (directory)")
        elif entry.is_file() and entry.name.endswith(".md"):
            defs.append(entry)
        else:
            offenders.append(f"{entry.name} (not a .md file)")
    return LegacyAgentDefs(present=True, symlink=None, defs=tuple(defs), offenders=tuple(offenders))


def legacy_removal_refusal(root: Path, info: LegacyAgentDefs, *, self_repo: bool) -> str | None:
    """Why ``--fix`` must NOT remove the directory, or ``None`` when it may.

    Three refusals, each naming what the human must handle: a symlink perk never created; an
    entry outside the flat ``*.md`` shape; a def whose shipped replacement is not present (the
    extension not installed yet, or a legacy name the shipped set no longer carries) — removing
    it would leave that ``perk.*`` name with no def at all, whereas a stale shadow is never an
    outage.
    """
    if info.symlink is not None:
        return (
            f"{info.symlink}: is a symlink — perk never created one; remove the legacy defs "
            "manually"
        )
    if info.offenders:
        listing = ", ".join(info.offenders)
        return (
            f"{LEGACY_AGENT_DEFS_REL}/: not removed — unexpected entries ({listing}); remove the "
            "directory manually"
        )
    shipped = init.shipped_agent_defs_dir(root, self_repo=self_repo)
    missing = sorted(path.stem for path in info.defs if not (shipped / path.name).is_file())
    if missing:
        names = ", ".join(f"perk.{name}" for name in missing)
        return (
            f"{LEGACY_AGENT_DEFS_REL}/: not removed — no shipped replacement for {names} under "
            f"{shipped.relative_to(root)}/; run perk init to install the extension (or remove a "
            "retired def manually), then perk doctor --fix"
        )
    return None


def describe_legacy_agent_defs(info: LegacyAgentDefs) -> str:
    """The warn detail's parenthetical: what the directory holds, as classified above."""
    if info.symlink is not None:
        return f"{info.symlink} is a symlink"
    parts = [path.name for path in info.defs] + list(info.offenders)
    return ", ".join(parts) if parts else "empty"
