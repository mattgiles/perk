"""Repo-authored-skills substrate: render the skills-CLI manifest fragment for a repo's *own*
``.perk/skills/*/SKILL.md`` skills under a self-referential GitHub source.

Pure helpers (parse/validate/render) are deterministic and offline; the orchestrator is the only
impure surface — filesystem discovery, the sanctioned ``git`` wrappers, and exactly one GitHub
gateway read (``github.repo_identity``). Every boundary that raises (``GitHubError`` / ``GitError``)
is caught and turned into a structured error string; nothing is silently swallowed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from perk import github
from perk.convergence.init.skills import MANAGED_HEADER, PERK_SKILLS_MANIFEST_DIR
from perk.github import GitHubError
from perk.substrate import git, paths
from perk.substrate.git import GitError
from perk.substrate.paths import REPO_SKILLS_REL
from perk.substrate.skill_exposure import StagesField, parse_skill_frontmatter, parse_stages_field

# The repo's own skills live under `.perk/skills/<name>/SKILL.md` (path construction via the
# `paths.repo_skills_dir` seam; `REPO_SKILLS_REL` is the display string). The rendered fragment
# lives beside the perk-managed fragment in the standard `.d/` convention.
REPO_SKILLS_MANIFEST_FILENAME = "perk-repo-skills.yaml"


@dataclass(frozen=True)
class RepoSkill:
    """One validated repo-authored skill.

    ``stages_field`` is the parsed ``stages:`` frontmatter (contracts.md §8.39) or ``None`` when
    the key is absent — doctor's `repo-skills` check nudges undeclared skills (exposed to every
    stage launch) and unknown stage ids. Advisory only: it never gates manifest rendering.
    """

    name: str
    description: str
    dir_name: str
    rel_path: str
    stages_field: StagesField | None = None


@dataclass(frozen=True)
class RepoSkillSource:
    """The derived self-referential manifest source for the repo's own skills."""

    alias: str
    url: str
    ref: str


@dataclass(frozen=True)
class RepoSkillsManifest:
    """The orchestrator result.

    ``fragment`` is the deterministic manifest YAML, or ``None`` whenever there is nothing to
    render (no skills) OR any fatal ``errors`` occurred — a non-empty ``errors`` always implies
    ``fragment is None``. ``warnings`` never suppress rendering (they nudge, e.g. committing an
    untracked skill).
    """

    fragment: str | None
    skills: tuple[RepoSkill, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def validate_skill(dir_name: str, frontmatter: dict) -> tuple[RepoSkill | None, str | None]:
    """Validate a parsed skill's frontmatter into a :class:`RepoSkill`.

    Requires a non-empty string ``name`` and ``description``, and ``name == dir_name`` (the
    manifest entry carries ``dir_name``, so a mismatch would make the skill's identity ambiguous).
    ``stages_field`` is populated from the ``stages:`` key (``None`` when absent) — advisory,
    never a validation failure. Returns ``(RepoSkill(...), None)`` or ``(None, "<reason>")``.
    """
    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or not name.strip():
        return None, f"{dir_name}: frontmatter `name` is missing or empty"
    if not isinstance(description, str) or not description.strip():
        return None, f"{dir_name}: frontmatter `description` is missing or empty"
    if name != dir_name:
        return None, (
            f"{dir_name}: frontmatter `name` ({name!r}) must equal the skill directory name"
        )
    return (
        RepoSkill(
            name=name,
            description=description,
            dir_name=dir_name,
            rel_path=f"{REPO_SKILLS_REL}/{dir_name}/SKILL.md",
            stages_field=parse_stages_field(frontmatter) if "stages" in frontmatter else None,
        ),
        None,
    )


def render_repo_skills_manifest(source: RepoSkillSource, skills: Sequence[RepoSkill]) -> str:
    """Render the deterministic manifest fragment (mirrors ``_desired_skills_manifest``'s format).

    Skills are sorted by ``name`` for byte-stability. Assumes a non-empty ``skills`` (the
    orchestrator never renders an empty set).
    """
    ordered = sorted(skills, key=lambda s: s.name)
    skills_block = "\n".join(f"  - source: {source.alias}\n    name: {s.name}" for s in ordered)
    return (
        f"{MANAGED_HEADER}"
        "sources:\n"
        f"  {source.alias}:\n"
        f"    url: {source.url}\n"
        f"    ref: {source.ref}\n"
        "skills:\n"
        f"{skills_block}\n"
    )


# ---------------------------------------------------------------------------
# Impure helpers
# ---------------------------------------------------------------------------


def discover_repo_skills(root: Path) -> tuple[list[tuple[str, dict]], list[str]]:
    """Discover + parse each ``.perk/skills/<name>/SKILL.md`` frontmatter (filesystem only).

    Returns ``(parsed, errors)`` where ``parsed`` is ``[(dir_name, frontmatter), …]`` sorted by
    ``dir_name`` and ``errors`` accumulates each frontmatter-parse reason. An absent
    ``.perk/skills/`` yields ``([], [])``.
    """
    skills_root = paths.repo_skills_dir(root)
    if not skills_root.is_dir():
        return [], []
    parsed: list[tuple[str, dict]] = []
    errors: list[str] = []
    for entry in sorted(skills_root.iterdir(), key=lambda p: p.name):
        skill_md = entry / "SKILL.md"
        if not entry.is_dir() or not skill_md.is_file():
            continue
        frontmatter, reason = parse_skill_frontmatter(skill_md.read_text(encoding="utf-8"))
        if reason is not None:
            errors.append(f"{entry.name}: {reason}")
            continue
        parsed.append((entry.name, frontmatter))
    return parsed, errors


def derive_repo_source(root: Path) -> RepoSkillSource:
    """Derive the self-referential manifest source from the repo's GitHub identity.

    Propagates ``GitHubError`` (the orchestrator catches it as the no-GitHub-remote fatal).
    """
    identity = github.repo_identity(root)
    return RepoSkillSource(
        alias=f"perk-{identity.name}",
        url=identity.url,
        ref=identity.default_branch,
    )


def effective_manifest_source_keys(root: Path) -> set[str]:
    """Collect the ``sources:`` keys declared across the effective manifest inputs.

    Reads ``.agents/manifest.yaml`` and every ``.agents/manifest.d/*.yaml`` **except our own
    fragment** (so a re-render never self-collides). Working-tree read (the effective inputs, not
    git-tracked-only); missing files / non-mapping ``sources`` are skipped silently.
    """
    keys: set[str] = set()
    candidates = [root / ".agents" / "manifest.yaml"]
    manifest_d = root / PERK_SKILLS_MANIFEST_DIR
    if manifest_d.is_dir():
        candidates += sorted(
            p for p in manifest_d.glob("*.yaml") if p.name != REPO_SKILLS_MANIFEST_FILENAME
        )
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        sources = data.get("sources")
        if isinstance(sources, dict):
            keys.update(str(k) for k in sources)
    return keys


def other_tracked_skill_names(root: Path) -> set[str]:
    """The frontmatter ``name``s of every *other* tracked ``SKILL.md`` (outside ``.perk/skills/``).

    Used for the duplicate-name check. ``GitError`` propagates (the orchestrator treats a failed
    probe as fatal-by-exception → an error string).
    """
    names: set[str] = set()
    for rel in git.tracked_paths(root, ["*SKILL.md"]):
        if rel.startswith(f"{REPO_SKILLS_REL}/"):
            continue
        path = root / rel
        if not path.is_file():
            continue
        frontmatter, reason = parse_skill_frontmatter(path.read_text(encoding="utf-8"))
        if reason is not None:
            continue
        name = frontmatter.get("name")
        if isinstance(name, str) and name.strip():
            names.add(name)
    return names


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def build_repo_skills_manifest(root: Path) -> RepoSkillsManifest:
    """Produce the deterministic ``perk-repo-skills.yaml`` fragment + structured diagnostics.

    A non-empty ``errors`` always yields ``fragment is None``. The GitHub read is skipped whenever
    there is nothing to render (no skills) or an offline failure (frontmatter / duplicate) already
    made the result fatal — so those paths stay testable offline.
    """
    parsed, fm_errors = discover_repo_skills(root)
    if not parsed and not fm_errors:
        return RepoSkillsManifest(None, (), (), ())

    errors: list[str] = list(fm_errors)
    warnings: list[str] = []
    skills: list[RepoSkill] = []
    for dir_name, frontmatter in parsed:
        skill, reason = validate_skill(dir_name, frontmatter)
        if reason is not None:
            errors.append(reason)
            continue
        assert skill is not None
        skills.append(skill)
        if not git.is_tracked(root, skill.rel_path):
            warnings.append(
                f"{skill.rel_path} is not committed — commit it so the skills CLI can "
                "resolve it from the repo's ref"
            )

    if skills:
        try:
            dupes = {s.name for s in skills} & other_tracked_skill_names(root)
        except GitError as exc:
            errors.append(f"failed to probe tracked skills for duplicate names: {exc}")
        else:
            for name in sorted(dupes):
                errors.append(
                    f"repo-authored skill {name!r} collides with another tracked skill of the "
                    "same name"
                )

    if errors:
        return RepoSkillsManifest(None, tuple(skills), tuple(errors), tuple(warnings))

    try:
        source = derive_repo_source(root)
    except GitHubError as exc:
        errors.append(
            f"repo-authored skills require a GitHub origin (gh could not resolve this repo): {exc}"
        )
        return RepoSkillsManifest(None, tuple(skills), tuple(errors), tuple(warnings))

    if source.alias in effective_manifest_source_keys(root):
        errors.append(
            f"derived manifest source alias {source.alias!r} already exists in the effective "
            "manifest — rename the colliding source"
        )
        return RepoSkillsManifest(None, tuple(skills), tuple(errors), tuple(warnings))

    fragment = render_repo_skills_manifest(source, skills)
    return RepoSkillsManifest(fragment, tuple(skills), (), tuple(warnings))


# ---------------------------------------------------------------------------
# Convergence gesture (the init / doctor --fix wiring)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoSkillsConvergence:
    """The result of converging ``.agents/manifest.d/perk-repo-skills.yaml``.

    ``changes`` lists genuine filesystem deltas (``created``/``updated``/``removed``); it is empty
    on a converged tree. ``manifest`` is the underlying :func:`build_repo_skills_manifest` result,
    carrying the structured ``errors``/``warnings``/``skills`` for the init + doctor surfaces.
    """

    changes: list[str]
    manifest: RepoSkillsManifest


def converge_repo_skills_manifest(root: Path, *, apply: bool = True) -> RepoSkillsConvergence:
    """Converge the repo-authored-skills manifest fragment (a verify-gated network gesture).

    NOT a ``ManagedConvergence``: rendering a valid fragment does a GitHub read, and managed
    convergences run unconditionally in offline unit tests. So this mirrors the *skills-delivery*
    gesture instead — ``init`` / ``doctor --fix`` call it under ``verify`` only. Idempotent:
    ``apply=True``/``False`` compute the same change list. **Never touches**
    ``.agents/manifest.yaml`` — only the ``.d/`` fragment.

    Three branches on :func:`build_repo_skills_manifest`'s result:

    - **valid skills** (``fragment is not None``): write on a byte-difference (``apply``); a change
      line ``"<path>: created|updated"`` only on a real delta.
    - **no skills, no errors** (``fragment is None`` and no ``errors``): remove a stale fragment if
      present (``apply``); a ``"<path>: removed"`` change line only when it existed. (Absent
      ``.perk/skills/`` → no fragment; this also prunes a fragment left behind after the last skill
      was deleted.)
    - **errors present** (``fragment is None`` and ``errors``): **never** write or remove — a
      transient bad edit must not clobber a previously-good fragment. The errors ride on
      ``manifest.errors`` for the caller to surface.
    """
    manifest = build_repo_skills_manifest(root)
    path = root / PERK_SKILLS_MANIFEST_DIR / REPO_SKILLS_MANIFEST_FILENAME
    if manifest.fragment is not None:
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current == manifest.fragment:
            return RepoSkillsConvergence([], manifest)
        if apply:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(manifest.fragment, encoding="utf-8")
        verb = "created" if current is None else "updated"
        return RepoSkillsConvergence(
            [f"{PERK_SKILLS_MANIFEST_DIR}/{REPO_SKILLS_MANIFEST_FILENAME}: {verb}"], manifest
        )
    if manifest.errors:
        return RepoSkillsConvergence([], manifest)
    if path.is_file():
        if apply:
            path.unlink()
        return RepoSkillsConvergence(
            [f"{PERK_SKILLS_MANIFEST_DIR}/{REPO_SKILLS_MANIFEST_FILENAME}: removed"], manifest
        )
    return RepoSkillsConvergence([], manifest)
