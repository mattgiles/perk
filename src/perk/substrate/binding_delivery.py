"""Cold-door (Python-plane) delivery of the resolved skill-binding overlay (§8.9).

When `perk` launches a `pi` session, this renders the **full resolved** bindings whose trigger
matches the launch into the session's initial prompt — `nudge` as a pointer line carrying the
skill's read path (perk's stage skills are hidden from the ambient system prompt, so the pointer
must name where the body lives), `transclude` as the inlined skill body. The mechanism is perk's
**single delivery path** for its own nudges: the shipped defaults carry no hardcoded per-skill
nudge string and are delivered here.
The warm door (the TS extension) is the in-session twin; target-existence validation (is
`stage:x` a real stage? is the skill installed?) stays `doctor`.

LBYL throughout (dignified-python): a missing/unreadable transclude target is surfaced as a
loud-but-non-fatal warning and degrades to the nudge pointer — never raises, never blocks a
launch.
"""

from dataclasses import dataclass
from pathlib import Path

from perk.substrate.bindings import (
    SKILL_FILENAME,
    SKILLS_DIR,
    Binding,
    is_skill_installed,
    load_bindings,
    resolve_bindings,
)
from perk.substrate.registry import Issue

_HEADER = "The following skill binding(s) apply here:"


@dataclass(frozen=True)
class ColdBindingDelivery:
    """The rendered cold-door delivery for one launch trigger.

    ``text`` is the prompt fragment to append (``None`` when nothing matches the trigger);
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
    """Render the full resolved bindings matching ``trigger`` into a prompt fragment.

    The resolved set is the shipped defaults ⊕ the user overlay (perk's own nudges are not
    hardcoded — the defaults are delivered here too). Only bindings whose trigger equals
    ``trigger`` are delivered. Resolver issues and delivery warnings are collected (never raised)
    for the caller to surface loud-but-non-fatal.
    """
    if defaults is None:
        defaults = load_bindings().bindings
    resolved = resolve_bindings(user_bindings, defaults=defaults)
    mine = [b for b in resolved.bindings if b.trigger == trigger]

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
                f"{SKILLS_DIR}/{binding.skill}/{SKILL_FILENAME} — falling back to a pointer."
            )
        elif not is_skill_installed(repo_root, binding.skill):
            # The nudge mirror of the transclude warning (D6): a binding to a skill that
            # is not installed is reported loud-but-non-fatal, never silently delivered. The pointer
            # is still emitted so the model gets the nudge.
            warnings.append(
                f"skill binding: skill `{binding.skill}` for `{binding.trigger}` is not installed "
                f"under {SKILLS_DIR}/{binding.skill}/{SKILL_FILENAME} — the pointer may dangle."
            )
        parts.append(
            f"Follow the `{binding.skill}` skill "
            f"(read `{SKILLS_DIR}/{binding.skill}/{SKILL_FILENAME}`)."
        )

    text = "\n\n".join([_HEADER, *parts]) if parts else None
    return ColdBindingDelivery(text=text, issues=list(resolved.issues), warnings=warnings)


def _read_skill_body(repo_root: Path, skill: str) -> str | None:
    """Read ``.agents/skills/<skill>/SKILL.md`` (frontmatter stripped); ``None`` if absent or
    unreadable — an undecodable/unreadable file degrades to the same pointer fallback as
    absence (parity with ``bindingDelivery.ts::readSkillBody``), never a crashed launch."""
    path = repo_root / SKILLS_DIR / skill / SKILL_FILENAME
    if not path.is_file():
        return None
    try:
        return _strip_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


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
