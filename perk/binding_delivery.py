"""Cold-door (Python-plane) delivery of the resolved skill-binding overlay (§8.9, Node 2.1).

When `perk` launches a `pi` session, this renders the **user-originated** resolved bindings
whose trigger matches the launch into the session's initial prompt — `nudge` as a pointer
line, `transclude` as the inlined skill body. **Additive only:** perk's own hardcoded "Follow
the … skill" strings are unchanged (their removal is Node 2.3), and bindings value-equal to a
shipped default are NOT re-delivered (avoiding double-delivery — perk still hardcodes those
nudges). The warm door (the TS extension) is Node 2.2; target-existence validation (is
`stage:x` a real stage? is the skill installed?) stays `doctor` (Node 3.1).

LBYL throughout (dignified-python): a missing/unreadable transclude target is surfaced as a
loud-but-non-fatal warning and degrades to the nudge pointer — never raises, never blocks a
launch.
"""

from dataclasses import dataclass
from pathlib import Path

from perk.bindings import Binding, load_bindings, resolve_bindings
from perk.registry import Issue

SKILLS_SUBDIR = Path(".agents/skills")
SKILL_FILENAME = "SKILL.md"

_HEADER = "The following skill binding(s) apply here (configured via .pi/perk.toml):"


@dataclass(frozen=True)
class ColdBindingDelivery:
    """The rendered cold-door delivery for one launch trigger.

    ``text`` is the prompt fragment to append (``None`` when nothing user-originated matches);
    ``issues`` carries the resolver's shape/duplicate findings; ``warnings`` carries delivery
    warnings (e.g. a missing transclude target) — both surfaced loud-but-non-fatal by the caller.
    """

    text: str | None
    issues: list[Issue]
    warnings: list[str]


def render_cold_bindings(
    user_bindings: list[Binding],
    repo_root: Path,
    trigger: str,
    *,
    defaults: list[Binding] | None = None,
) -> ColdBindingDelivery:
    """Render the user-originated bindings matching ``trigger`` into a prompt fragment.

    ``user-originated`` = the resolved set minus the shipped defaults (a ``Binding`` is a frozen
    dataclass, so set membership is the exact value-equality test). Only bindings whose trigger
    equals ``trigger`` are delivered — additively. Resolver issues and delivery warnings are
    collected (never raised) for the caller to surface loud-but-non-fatal.
    """
    if defaults is None:
        defaults = load_bindings().bindings
    resolved = resolve_bindings(user_bindings, defaults=defaults)
    default_set = set(defaults)
    mine = [b for b in resolved.bindings if b not in default_set and b.trigger == trigger]

    warnings: list[str] = []
    parts: list[str] = []
    for binding in mine:
        if binding.mode == "transclude":
            body = _read_skill_body(repo_root, binding.skill)
            if body is not None:
                parts.append(
                    f"Skill `{binding.skill}` (inlined for `{binding.trigger}`):\n\n{body}"
                )
                continue
            warnings.append(
                f"skill binding: transclude target for `{binding.skill}` not found under "
                f"{SKILLS_SUBDIR}/{binding.skill}/{SKILL_FILENAME} — falling back to a pointer."
            )
        parts.append(f"Follow the `{binding.skill}` skill.")

    text = "\n\n".join([_HEADER, *parts]) if parts else None
    return ColdBindingDelivery(text=text, issues=list(resolved.issues), warnings=warnings)


def _read_skill_body(repo_root: Path, skill: str) -> str | None:
    """Read ``.agents/skills/<skill>/SKILL.md`` (frontmatter stripped); ``None`` if absent."""
    path = repo_root / SKILLS_SUBDIR / skill / SKILL_FILENAME
    if not path.is_file():
        return None
    return _strip_frontmatter(path.read_text(encoding="utf-8"))


def _strip_frontmatter(text: str) -> str:
    """Drop a leading ``---``-delimited YAML frontmatter block; return the body stripped.

    If the text does not open with a frontmatter block, it is returned unchanged.
    """
    if not text.startswith("---\n"):
        return text
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i] == "---":
            return "\n".join(lines[i + 1 :]).strip()
    return text  # no closing delimiter — leave the text unchanged
