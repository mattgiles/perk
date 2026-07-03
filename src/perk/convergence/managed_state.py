"""The managed-artifact version+hash state library (`.perk/managed-state.toml`).

Three layers over the existing managed set:

- **Hash functions** for file / directory / managed-block content — every digest is the house
  ``sha256:<hex>`` convention (contracts.md §8.1).
- **Artifact descriptors** (:func:`managed_artifacts`): one :class:`ArtifactDescriptor` per
  committed managed piece, each carrying a stable state-file key, a display path, a
  ``kind`` (``file`` / ``directory`` / ``block``), a scope, and its current *desired* payload —
  kind-normalized to one uniform ``bytes`` shape so a single hash backs every kind.
- **The state store**: the committed ``[managed]`` + ``[managed.artifacts.<key>]`` TOML format,
  read via a lenient parse model into frozen domain dataclasses
  (:func:`load_managed_state`) and written as deterministic hand-rendered TOML
  (:func:`render_managed_state` / :func:`save_managed_state`). The file is machine-written as a
  side effect of convergence and is **excluded from its own artifact/hash set** (no descriptor
  names it — the no-recursive-churn rule). No secrets by construction: only paths, kinds,
  versions, and digests are ever serialized.

Import rule: only *leaf* submodules of ``perk.convergence.init`` are imported (never the package
root), so the init orchestration can import this module without a cycle.
"""

import hashlib
import json
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from perk import __version__, _resources
from perk.boundary import LenientParseModel, translate_validation_errors
from perk.convergence.capabilities import Scope
from perk.convergence.init.agents import PERK_AGENTS
from perk.convergence.init.blocks import GITIGNORE_BODY, _agents_inner
from perk.convergence.init.settings import (
    _converge_compaction,
    _converge_linear_package,
    _converge_provider_packages,
    _desired_packages,
    _merge_static_packages,
)
from perk.convergence.init.skills import (
    PERK_SKILLS_MANIFEST_DIR,
    PERK_SKILLS_MANIFEST_FILENAME,
    _desired_skills_manifest,
)
from perk.convergence.init.version_pin import render_version_pin
from perk.run.workflow_artifacts import (
    PERK_RUN_WORKFLOW,
    REMOTE_SETUP_ACTION_PATH,
    RUNNER_WORKFLOW_PATH,
    remote_setup_action,
)
from perk.substrate import paths

# --- Hash functions -------------------------------------------------------------------------


def hash_bytes(data: bytes) -> str:
    """The file-content hash: ``"sha256:" + hexdigest`` over the exact bytes."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def directory_manifest(files: Mapping[str, bytes]) -> bytes:
    """The canonical directory encoding: per sorted name, ``"{name}\\n{sha256 hex}\\n"``.

    Sorting makes :func:`hash_directory` insertion-order-independent by construction.
    """
    lines = "".join(
        f"{name}\n{hashlib.sha256(files[name]).hexdigest()}\n" for name in sorted(files)
    )
    return lines.encode("utf-8")


def hash_directory(files: Mapping[str, bytes]) -> str:
    """Hash a directory's name→content mapping via its canonical manifest."""
    return hash_bytes(directory_manifest(files))


def _canonical_block_payload(inner: str) -> bytes:
    """The kind-normalized ``block`` payload: ``inner.rstrip("\\n") + "\\n"``, UTF-8.

    Matches ``_apply_managed_block``'s embedding (``{begin}\\n{inner.rstrip()}\\n{end}\\n``)
    so trailing-newline drift never changes the hash.
    """
    return (inner.rstrip("\n") + "\n").encode("utf-8")


def hash_block(inner: str) -> str:
    """Hash a managed block's inner text (canonicalized — trailing newlines never matter)."""
    return hash_bytes(_canonical_block_payload(inner))


def block_inner(text: str, *, begin: str, end: str) -> str | None:
    """Extract a managed block's inner text from a real file's text.

    ``None`` when either marker is absent. The inner is the text strictly between the ``begin``
    line and the ``end`` marker (the ``begin`` line's terminating newline is not part of it),
    mirroring ``_apply_managed_block``'s embedding — so ``hash_block(block_inner(...))`` equals
    ``hash_block(inner)`` for any file the applier wrote.
    """
    if begin not in text or end not in text:
        return None
    start = text.index(begin) + len(begin)
    stop = text.index(end)
    return text[start:stop].removeprefix("\n")


# --- Artifact descriptors -------------------------------------------------------------------

Kind = Literal["file", "directory", "block"]


@dataclass(frozen=True)
class ArtifactDescriptor:
    """One committed managed artifact: identity, shape, and its desired payload.

    ``desired`` is private plumbing (``(root, self_repo) -> bytes``; positional ``bool`` only
    because ``Callable[...]`` cannot express keyword-only parameters) — consumers go through
    :meth:`desired_payload` / :meth:`desired_hash`.
    """

    key: str  # stable state-file key (bare-TOML-safe, [a-z0-9-])
    path: str  # repo-relative display path; directory paths end with "/"
    kind: Kind
    scope: Scope
    desired: Callable[[Path, bool], bytes]

    def desired_payload(self, root: Path, *, self_repo: bool) -> bytes:
        """The kind-normalized desired payload (file bytes / directory manifest / block inner)."""
        return self.desired(root, self_repo)

    def desired_hash(self, root: Path, *, self_repo: bool) -> str:
        """The digest of the desired payload."""
        return hash_bytes(self.desired_payload(root, self_repo=self_repo))


def _settings_portion(root: Path, *, self_repo: bool) -> bytes:
    """Canonical JSON of perk's desired `.pi/settings.json` *portion* (never the live file).

    Rebuilt from scratch out of the convergence SSOT helpers — perk's own pinned entry plus the
    borrowed set, the provider/linear selections, and the committed ``[compaction]`` table. The
    hash therefore moves exactly when perk's desired wiring moves (version bump, borrowed-set
    change, provider/linear/compaction selection change) and never encodes user-owned settings
    keys. The reused helpers each treat a malformed committed TOML as empty (defer-to-config-check),
    so this inherits that posture.
    """
    packages, _, _ = _merge_static_packages([], _desired_packages(self_repo))
    packages, _ = _converge_provider_packages(root, packages)
    packages, _ = _converge_linear_package(root, packages)
    stub: dict[str, object] = {}
    _converge_compaction(root, stub)
    portion: dict[str, object] = {"packages": packages}
    if "compaction" in stub:
        portion["compaction"] = stub["compaction"]
    return json.dumps(portion, indent=2, sort_keys=True).encode("utf-8")


def _settings_payload(root: Path, self_repo: bool) -> bytes:
    return _settings_portion(root, self_repo=self_repo)


def _runner_workflow_payload(root: Path, self_repo: bool) -> bytes:
    return PERK_RUN_WORKFLOW.encode("utf-8")


def _remote_setup_action_payload(root: Path, self_repo: bool) -> bytes:
    return remote_setup_action(self_repo).encode("utf-8")


def _subagent_agents_payload(root: Path, self_repo: bool) -> bytes:
    source_dir = _resources.agents_dir()
    files = {f"{name}.md": (source_dir / f"{name}.md").read_bytes() for name in PERK_AGENTS}
    return directory_manifest(files)


def _skills_manifest_payload(root: Path, self_repo: bool) -> bytes:
    return _desired_skills_manifest(self_repo).encode("utf-8")


def _gitignore_block_payload(root: Path, self_repo: bool) -> bytes:
    return _canonical_block_payload(GITIGNORE_BODY)


def _agents_block_payload(root: Path, self_repo: bool) -> bytes:
    return _canonical_block_payload(_agents_inner())


def _version_pin_payload(root: Path, self_repo: bool) -> bytes:
    return render_version_pin().encode("utf-8")


def managed_artifacts() -> tuple[ArtifactDescriptor, ...]:
    """The pinned artifact registry over the committed managed set.

    Keys align with the ``ManagedConvergence`` names where 1:1; the runner convergence splits
    into its two files. Deliberate exclusions: the state file itself (no descriptor may name
    ``.perk/managed-state.toml`` — the no-recursive-churn rule, asserted in tests);
    ``workflow-dir`` (gitignored cache, not committed state); the repo-skills fragment
    (``perk-repo-skills.yaml`` — network-derived and user-content-derived, not
    offline-computable); ``.perk/config.toml`` (seeded once, user-owned after);
    ``.agents/skills/`` symlinks + the ``.pi/npm`` extension install (gitignored,
    skills-CLI/npm-managed); the ``.pi/agents/.gitkeep`` (trivial presence marker outside the
    perk-owned ``perk/`` subdir).
    """
    return (
        ArtifactDescriptor(
            key="settings-wiring",
            path=".pi/settings.json",
            kind="block",
            scope="both",
            desired=_settings_payload,
        ),
        ArtifactDescriptor(
            key="runner-workflow",
            path=RUNNER_WORKFLOW_PATH,
            kind="file",
            scope="both",
            desired=_runner_workflow_payload,
        ),
        ArtifactDescriptor(
            key="remote-setup-action",
            path=REMOTE_SETUP_ACTION_PATH,
            kind="file",
            scope="both",
            desired=_remote_setup_action_payload,
        ),
        ArtifactDescriptor(
            key="subagent-agents",
            path=".pi/agents/perk/",
            kind="directory",
            scope="both",
            desired=_subagent_agents_payload,
        ),
        ArtifactDescriptor(
            key="skills-manifest",
            path=f"{PERK_SKILLS_MANIFEST_DIR}/{PERK_SKILLS_MANIFEST_FILENAME}",
            kind="file",
            scope="both",
            desired=_skills_manifest_payload,
        ),
        ArtifactDescriptor(
            key="gitignore-block",
            path=".gitignore",
            kind="block",
            scope="both",
            desired=_gitignore_block_payload,
        ),
        ArtifactDescriptor(
            key="agents-block",
            path="AGENTS.md",
            kind="block",
            scope="both",
            desired=_agents_block_payload,
        ),
        ArtifactDescriptor(
            key="required-perk-version",
            path=".perk/required-perk-version",
            kind="file",
            scope="both",
            desired=_version_pin_payload,
        ),
    )


# --- The state store ------------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactState:
    """One recorded artifact row (``kind`` stays plain ``str`` — recorded state from a newer
    perk may carry unknown kinds and must still load)."""

    key: str
    path: str
    kind: str
    version: str
    hash: str


@dataclass(frozen=True)
class ManagedState:
    """The whole recorded state (``artifacts`` kept sorted by key)."""

    version: str
    artifacts: tuple[ArtifactState, ...]


class ManagedStateError(Exception):
    """A present-but-malformed `.perk/managed-state.toml` (loud, never a silent pass)."""


class ArtifactEntryModel(LenientParseModel):
    """One ``[managed.artifacts.<key>]`` table (lenient: a newer perk may have extended it)."""

    path: str = ""
    kind: str = ""
    version: str = ""
    hash: str = ""

    def to_domain(self, key: str) -> ArtifactState:
        return ArtifactState(
            key=key, path=self.path, kind=self.kind, version=self.version, hash=self.hash
        )


class ManagedTableModel(LenientParseModel):
    """The ``[managed]`` table."""

    version: str = ""
    artifacts: dict[str, ArtifactEntryModel] = Field(default_factory=dict)


class ManagedStateFileModel(LenientParseModel):
    """The whole `.perk/managed-state.toml` shape."""

    managed: ManagedTableModel = Field(default_factory=ManagedTableModel)

    def to_domain(self) -> ManagedState:
        artifacts = tuple(
            self.managed.artifacts[key].to_domain(key) for key in sorted(self.managed.artifacts)
        )
        return ManagedState(version=self.managed.version, artifacts=artifacts)


def load_managed_state(root: Path) -> ManagedState | None:
    """The recorded managed state, or ``None`` when the file is absent (an expected state).

    A present-but-malformed file raises :class:`ManagedStateError` (TOML and schema errors
    alike). ``OSError`` propagates — an unreadable managed piece surfaces loud at the caller,
    never a silent pass.
    """
    path = paths.managed_state_file(root)
    if not path.is_file():
        return None
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ManagedStateError(f".perk/managed-state.toml is not valid TOML: {exc}") from exc
    with translate_validation_errors(ManagedStateError, source=".perk/managed-state.toml"):
        model = ManagedStateFileModel.model_validate(raw)
    return model.to_domain()


_STATE_HEADER = (
    "# Managed by perk convergence (perk init / perk doctor --fix) — do not edit by hand.\n"
)


def render_managed_state(state: ManagedState) -> str:
    """Deterministic hand-rendered TOML from the frozen domain (render → load → render identity).

    String values go through ``json.dumps`` (valid TOML basic-string escaping); every key is
    bare-key-safe by construction. No secrets by construction — only paths, kinds, versions,
    and digests are ever serialized.
    """
    lines = [_STATE_HEADER, "[managed]\n", f"version = {json.dumps(state.version)}\n"]
    for artifact in sorted(state.artifacts, key=lambda a: a.key):
        lines.append(f"\n[managed.artifacts.{artifact.key}]\n")
        lines.append(f"path = {json.dumps(artifact.path)}\n")
        lines.append(f"kind = {json.dumps(artifact.kind)}\n")
        lines.append(f"version = {json.dumps(artifact.version)}\n")
        lines.append(f"hash = {json.dumps(artifact.hash)}\n")
    return "".join(lines)


def save_managed_state(root: Path, state: ManagedState) -> None:
    """Write the rendered state to `.perk/managed-state.toml` (creating `.perk/` if needed)."""
    path = paths.managed_state_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_managed_state(state), encoding="utf-8")


def desired_state(root: Path, *, self_repo: bool) -> ManagedState:
    """The state convergence records after applying: every artifact at the running version's
    desired hash (the bridge the init/doctor write wiring calls)."""
    artifacts = tuple(
        ArtifactState(
            key=descriptor.key,
            path=descriptor.path,
            kind=descriptor.kind,
            version=__version__,
            hash=descriptor.desired_hash(root, self_repo=self_repo),
        )
        for descriptor in sorted(managed_artifacts(), key=lambda d: d.key)
    )
    return ManagedState(version=__version__, artifacts=artifacts)
