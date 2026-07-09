"""The layered skills-exposure model for cold stage launches (contracts.md §8.39).

Every cold stage launch used to inherit pi's full skill discovery. This module composes the
``--no-skills`` + ``--skill <path>`` argv fragment that scopes a launch to the skills relevant to
its stage, resolved per skill through three layers:

1. a ``[skills.stages]`` config row (by skill name) — wins when present;
2. the skill's ``stages:`` SKILL.md frontmatter (``all`` or a list of registry stage ids);
3. undeclared → ``all`` (fail-open; existing skills behave like today).

Bound skills trump every layer: any skill referenced by a resolved binding on the launch trigger
is exposed even when a config row or frontmatter excludes it — and even when not installed (pi
then emits its own missing-path diagnostic, the existing dangling-binding symptom).

**Engagement (zero-change rollout):** the composition returns ``[]`` unless the model is in use —
at least one enumerated skill declares ``stages:`` or any ``[skills]`` config content exists — so
an untouched repo's launch argv stays byte-identical to unscoped discovery.

**Fail-open ladder:** per-skill soft issues (unreadable/malformed SKILL.md or ``stages:``) default
that skill to ``all`` + a warning; a package-tier failure (a listed ``npm:`` package absent from
``.pi/npm``, an unreadable ``.pi/settings.json``) degrades the *whole* composition to unscoped +
a warning (argv is built before the warm-install phase, so per-package skips would silently drop
whole packages); the caller wraps the composition so any unexpected exception also degrades to
unscoped. The launch is never blocked.

Lives beside ``bindings.py`` (the binding model the exposure layer sits beside); deliberately does
NOT import ``config.py`` (the caller passes the parsed ``SkillsPolicy``), avoiding a cycle —
``config.py`` imports :class:`SkillsPolicy` from here (the ``Binding`` precedent).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from perk.substrate.bindings import Binding, resolve_bindings

# The project skills root every launch enumerates — the exact set `materialize_skills` mirrors
# into worktrees. First-party skills come from here full stop: local-path (`..`) and `git:`
# settings packages are deliberately not enumerated (no committed-`skills/` fallback).
PROJECT_SKILLS_REL = ".agents/skills"

# Where pi installs `npm:` settings packages (`getManagedNpmInstallPath`); the worktree `.pi/npm`
# clone from `materialize_extensions` makes repo-relative paths under it resolve in worktree
# sessions.
NPM_PACKAGES_REL = ".pi/npm/node_modules"

SKILL_FILENAME = "SKILL.md"

# Glob metacharacters pi's `pi.skills` entries may carry; an entry containing one is a *pattern*,
# not a plain path, and cannot be per-skill enumerated here.
_GLOB_CHARS = ("*", "?", "[")

type StagesField = frozenset[str] | Literal["all", "malformed"]
"""A parsed ``stages:`` frontmatter value: ``"all"`` (undeclared or the literal ``all``), a
declared stage-id set (possibly empty = exposed nowhere), or ``"malformed"`` (the caller warns
and treats as ``all``)."""


@dataclass(frozen=True)
class SkillsPolicy:
    """The `[skills]` config namespace as a frozen domain object (parsed by ``config.py``).

    ``include_dirs`` is the wholesale ``--skill <dir>`` whitelist (default: global/user skill
    dirs are dropped from scoped launches). ``include_packages`` is the package-tier toggle
    (``None`` = unset = participate — but "explicitly set" counts toward engagement).
    ``stages`` maps skill name → a stage-id tuple, or ``None`` for the ``"all"`` re-widening row.
    """

    include_dirs: tuple[str, ...] = ()
    include_packages: bool | None = None
    stages: dict[str, tuple[str, ...] | None] = field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        """Any of the three knobs set — one of the engagement signals (§8.39)."""
        return bool(self.include_dirs) or self.include_packages is not None or bool(self.stages)


def parse_skill_frontmatter(text: str) -> tuple[dict, str | None]:
    """Parse a ``SKILL.md``'s leading ``---``-delimited YAML frontmatter mapping.

    Returns ``(mapping, None)`` on a well-formed mapping, else ``({}, "<reason>")`` when: no
    opening ``---\\n``, no closing ``---``, a YAML parse error, or a non-mapping body. Never raises.
    """
    if not text.startswith("---\n"):
        return {}, "missing opening `---` frontmatter delimiter"
    lines = text.split("\n")
    end = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    if end is None:
        return {}, "missing closing `---` frontmatter delimiter"
    block = "\n".join(lines[1:end])
    try:
        parsed = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        return {}, f"malformed frontmatter YAML: {exc}"
    if not isinstance(parsed, dict):
        return {}, "frontmatter is not a mapping"
    return parsed, None


def parse_stages_field(frontmatter: dict) -> StagesField:
    """Read the ``stages:`` frontmatter field through the pinned vocabulary.

    Absent or the literal ``all`` → ``"all"``; a list of non-blank strings → the declared
    frozenset (each entry stripped; an explicit ``[]`` means exposed nowhere); anything else
    (wrong type, blank/non-string entries) → ``"malformed"`` — the caller warns and treats it as
    ``all`` (fail-open, loud-but-non-fatal). Registry-free: unknown stage ids are kept, inert
    (mirroring `[models.stages.<id>]`; doctor's `repo-skills` check warns on unknown ids in
    repo-authored skills).
    """
    if "stages" not in frontmatter:
        return "all"
    value = frontmatter["stages"]
    if isinstance(value, str):
        return "all" if value.strip() == "all" else "malformed"
    if isinstance(value, list):
        entries: list[str] = []
        for entry in value:
            if not isinstance(entry, str) or not entry.strip():
                return "malformed"
            entries.append(entry.strip())
        return frozenset(entries)
    return "malformed"


@dataclass(frozen=True)
class _EnumeratedSkill:
    """One per-skill enumeration result (project or package tier).

    ``name`` is the frontmatter ``name`` else the directory name (pi's naming rule);
    ``rel_path`` is the repo-relative ``--skill`` arg; ``stages`` is the resolved frontmatter
    tier (malformed already warned → ``"all"``); ``declared`` records whether a ``stages:`` key
    was present at all (the engagement signal, independent of well-formedness).
    """

    name: str
    rel_path: str
    stages: frozenset[str] | Literal["all"]
    declared: bool


class _PackageTierUnavailable(Exception):
    """The package tier cannot be enumerated right now (cold ``.pi/npm``, unreadable
    ``.pi/settings.json``) — the whole composition degrades to unscoped (§8.39 fail-open)."""


def skill_exposure_argv(
    repo_root: Path,
    *,
    stage_id: str,
    trigger: str,
    policy: SkillsPolicy,
    user_bindings: list[Binding],
    defaults: list[Binding] | None = None,
) -> tuple[list[str], list[str]]:
    """Compose the scoped-launch ``(argv_fragment, warnings)`` for one cold stage launch.

    The single public composition seam: enumeration (project dirs, ``npm:`` settings packages,
    whitelist dirs), per-skill three-layer resolution, the bound-skill union (bindings on
    ``trigger``, resolved shipped-defaults ⊕ ``user_bindings``), the engagement check,
    deterministic ordering (whitelist → packages → project, fixing first-wins collisions), and
    the fail-open ladder. An unengaged repo returns ``([], [])`` — argv AND stderr stay
    byte-identical to today. ``defaults`` overrides the shipped binding defaults (tests).
    """
    warnings: list[str] = []
    project = _enumerate_project_skills(repo_root, warnings)
    package_items: list[_EnumeratedSkill | str] = []
    degraded: str | None = None
    if policy.include_packages is not False:
        try:
            package_items = _enumerate_package_skills(repo_root, warnings)
        except _PackageTierUnavailable as exc:
            degraded = str(exc)

    declared = any(s.declared for s in project) or any(
        isinstance(item, _EnumeratedSkill) and item.declared for item in package_items
    )
    if not policy.is_configured and not declared:
        # Unengaged: the exposure model is not in use — no flags AND no warnings, so the launch
        # (argv + stderr) is byte-identical to unscoped discovery.
        return [], []
    if degraded is not None:
        return [], [*warnings, degraded]

    resolved = resolve_bindings(user_bindings, defaults=defaults)
    bound = {b.skill for b in resolved.bindings if b.trigger == trigger and b.skill}

    args: list[str] = ["--no-skills"]
    for entry in policy.include_dirs:
        path = Path(entry).expanduser()
        if not path.is_absolute():
            # Relative entries resolve against the MAIN repo root and are passed absolute —
            # relative would silently break in worktree sessions (pi's cwd is the worktree).
            path = repo_root / path
        args += ["--skill", str(path)]
    for item in package_items:
        if isinstance(item, str):  # a wholesale root (not per-skill enumerable) — never narrowed
            args += ["--skill", item]
        elif _is_exposed(item, stage_id=stage_id, policy=policy, bound=bound):
            args += ["--skill", item.rel_path]
    enumerated_names = {s.name for s in project} | {
        item.name for item in package_items if isinstance(item, _EnumeratedSkill)
    }
    exposed_project = [
        (skill.rel_path.rsplit("/", 1)[-1], skill.rel_path)
        for skill in project
        if _is_exposed(skill, stage_id=stage_id, policy=policy, bound=bound)
    ]
    # Bound-but-unenumerated skills still get the delivery-path entry (pi emits its own
    # missing-path diagnostic when it dangles; remediation `perk init`).
    exposed_project += [(name, f"{PROJECT_SKILLS_REL}/{name}") for name in bound - enumerated_names]
    for _, rel_path in sorted(exposed_project):
        args += ["--skill", rel_path]
    return args, warnings


def _is_exposed(
    skill: _EnumeratedSkill, *, stage_id: str, policy: SkillsPolicy, bound: set[str]
) -> bool:
    """Resolve one skill through the three layers (+ the bound-skill trump)."""
    if skill.name in bound:
        return True
    if skill.name in policy.stages:
        row = policy.stages[skill.name]
        return row is None or stage_id in row
    return skill.stages == "all" or stage_id in skill.stages


def _enumerate_project_skills(repo_root: Path, warnings: list[str]) -> list[_EnumeratedSkill]:
    """Enumerate each child dir of ``repo_root/.agents/skills/`` (the exposure path reads ONLY
    this — no self-repo ``skills/`` fallback; a just-landed un-synced skill is softly absent)."""
    root = repo_root / PROJECT_SKILLS_REL
    if not root.is_dir():
        return []
    return [
        _read_skill(entry, rel_path=f"{PROJECT_SKILLS_REL}/{entry.name}", warnings=warnings)
        for entry in sorted(root.iterdir(), key=lambda p: p.name)
        if entry.is_dir()
    ]


def _read_skill(skill_dir: Path, *, rel_path: str, warnings: list[str]) -> _EnumeratedSkill:
    """Read one skill dir's ``SKILL.md`` into an :class:`_EnumeratedSkill` (never raises).

    Per-skill soft issues (unreadable file, malformed frontmatter, malformed ``stages:``) default
    the skill to ``all`` + one warning. A dir without a ``SKILL.md`` is silently undeclared
    (→ ``all``): pi may still discover nested skills under it.
    """
    name = skill_dir.name
    skill_md = skill_dir / SKILL_FILENAME
    if not skill_md.is_file():
        return _EnumeratedSkill(name=name, rel_path=rel_path, stages="all", declared=False)
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        warnings.append(
            f"skills: could not read {rel_path}/{SKILL_FILENAME} ({exc}) — exposing to all stages"
        )
        return _EnumeratedSkill(name=name, rel_path=rel_path, stages="all", declared=False)
    frontmatter, reason = parse_skill_frontmatter(text)
    if reason is not None:
        warnings.append(f"skills: {rel_path}/{SKILL_FILENAME}: {reason} — exposing to all stages")
        return _EnumeratedSkill(name=name, rel_path=rel_path, stages="all", declared=False)
    fm_name = frontmatter.get("name")
    if isinstance(fm_name, str) and fm_name.strip():
        name = fm_name.strip()
    declared = "stages" in frontmatter
    stages = parse_stages_field(frontmatter)
    if stages == "malformed":
        warnings.append(
            f"skills: {rel_path}/{SKILL_FILENAME}: malformed `stages:` (expected `all` or a "
            "list of stage ids) — exposing to all stages"
        )
        stages = "all"
    return _EnumeratedSkill(name=name, rel_path=rel_path, stages=stages, declared=declared)


def _enumerate_package_skills(repo_root: Path, warnings: list[str]) -> list[_EnumeratedSkill | str]:
    """Enumerate the ``npm:`` settings packages' skills (per-skill where possible).

    Returns an ordered mix of per-skill :class:`_EnumeratedSkill` entries and wholesale
    ``--skill`` root strings (a root with no one-level ``SKILL.md`` children, or a pattern
    ``pi.skills`` entry → the package dir). Raises :class:`_PackageTierUnavailable` when a listed
    package's install dir is absent (cold ``.pi/npm``) — the honest whole-composition degrade
    (per-package skips would silently drop pi-subagents/librarian).
    """
    items: list[_EnumeratedSkill | str] = []
    for pkg in _settings_npm_package_names(repo_root):
        pkg_rel = f"{NPM_PACKAGES_REL}/{pkg}"
        pkg_dir = repo_root / NPM_PACKAGES_REL / pkg
        if not pkg_dir.is_dir():
            raise _PackageTierUnavailable(
                f"skills: package {pkg} is not installed under {NPM_PACKAGES_REL} — "
                "launching with pi's full skill discovery (self-heals once installed)"
            )
        roots, whole_package = _package_skill_roots(pkg_dir, pkg_rel, warnings)
        if whole_package:
            items.append(pkg_rel)
            continue
        for root in roots:
            root_dir = pkg_dir / root
            if not root_dir.is_dir():
                continue  # a declared-but-absent root contributes nothing (pi's behavior)
            children = sorted(
                entry
                for entry in root_dir.iterdir()
                if entry.is_dir() and (entry / SKILL_FILENAME).is_file()
            )
            if not children:
                items.append(f"{pkg_rel}/{root}")  # wholesale root (recursively scanned by pi)
                continue
            items += [
                _read_skill(child, rel_path=f"{pkg_rel}/{root}/{child.name}", warnings=warnings)
                for child in children
            ]
    return items


def _package_skill_roots(
    pkg_dir: Path, pkg_rel: str, warnings: list[str]
) -> tuple[list[str], bool]:
    """The package's skill roots: ``pi.skills`` plain-path entries when declared, else the
    conventional ``skills/`` dir.

    Returns ``(roots, whole_package)``: ``whole_package`` is True when any ``pi.skills`` entry is
    not a plain relative path (a glob pattern, absolute, or ``..``-escaping) — un-enumerable, so
    the package degrades to one wholesale ``--skill <package dir>`` arg. A missing/malformed
    ``package.json`` warns and falls back to the conventional dir.
    """
    package_json = pkg_dir / "package.json"
    data: object = None
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            warnings.append(
                f"skills: unreadable {pkg_rel}/package.json — using the conventional skills/ dir"
            )
    pi_section = data.get("pi") if isinstance(data, dict) else None
    entries = pi_section.get("skills") if isinstance(pi_section, dict) else None
    if not isinstance(entries, list) or not entries:
        return (["skills"] if (pkg_dir / "skills").is_dir() else []), False
    roots: list[str] = []
    for entry in entries:
        if not isinstance(entry, str):
            return [], True
        normalized = entry.removeprefix("./")
        if (
            not normalized
            or Path(normalized).is_absolute()
            or ".." in Path(normalized).parts
            or any(ch in normalized for ch in _GLOB_CHARS)
        ):
            return [], True
        roots.append(normalized.rstrip("/"))
    return roots, False


def _settings_npm_package_names(repo_root: Path) -> list[str]:
    """The ``npm:`` package names from ``.pi/settings.json`` ``packages`` (strings or
    ``{source}`` rows), in declaration order.

    Local-path sources (the self-repo's ``".."``) and ``git:`` sources are deliberately not
    enumerated — first-party skills come from ``.agents/skills`` full stop. A missing file yields
    ``[]`` (no packages); an unreadable/malformed file raises :class:`_PackageTierUnavailable`
    (the whole-composition degrade while the package tier is enabled).
    """
    settings = repo_root / ".pi" / "settings.json"
    if not settings.is_file():
        return []
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _PackageTierUnavailable(
            f"skills: could not read .pi/settings.json ({exc}) — "
            "launching with pi's full skill discovery"
        ) from exc
    packages = data.get("packages") if isinstance(data, dict) else None
    if packages is None:
        return []
    if not isinstance(packages, list):
        raise _PackageTierUnavailable(
            "skills: .pi/settings.json `packages` is not a list — "
            "launching with pi's full skill discovery"
        )
    names: list[str] = []
    for entry in packages:
        if isinstance(entry, dict):
            source: object = next((v for key, v in entry.items() if key == "source"), None)
        else:
            source = entry
        if not isinstance(source, str) or not source.startswith("npm:"):
            continue
        name = _npm_package_name(source)
        if name:
            names.append(name)
    return names


def _npm_package_name(spec: str) -> str:
    """``npm:@scope/name@1.2.3`` → ``@scope/name`` (a version pin is stripped; a scope's leading
    ``@`` is not a version separator)."""
    bare = spec.removeprefix("npm:")
    at = bare.rfind("@")
    return bare[:at] if at > 0 else bare
