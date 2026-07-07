"""The managed-artifact version+hash state library (`.perk/managed-state.toml`).

Three layers over the existing managed set:

- **Hash functions** for file / directory / managed-block content — every digest is the house
  ``sha256:<hex>`` convention (contracts.md §8.1).
- **Artifact descriptors** (:func:`managed_artifacts`): one :class:`ArtifactDescriptor` per
  committed managed piece, each carrying a stable state-file key, a display path, a
  ``kind`` (``file`` / ``directory`` / ``block``), a scope, its current *desired* payload, and
  its *observed* payload (the kind-normalized live content, ``None`` when not installed) —
  kind-normalized to one uniform ``bytes`` shape so a single hash backs every kind.
- **Artifact health** (:func:`artifact_health` / :func:`classify_artifact`): the report-only
  diagnostic lens over the three signals (observed / desired / recorded), classifying each
  artifact ``up-to-date`` / ``not-installed`` / ``locally-modified`` / ``changed-upstream`` /
  ``state-missing``. Diagnostic only — the dry-run managed convergence stays authoritative for
  pass/fail.
- **The state store**: the committed ``[managed]`` + ``[managed.artifacts.<key>]`` TOML format,
  read via a lenient parse model into frozen domain dataclasses
  (:func:`load_managed_state`) and written as deterministic hand-rendered TOML
  (:func:`render_managed_state` / :func:`save_managed_state`). The file is machine-written as a
  side effect of convergence (:func:`record_managed_state`, called by ``perk init`` and
  ``perk doctor --fix``) and is **excluded from its own artifact/hash set** (no descriptor
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
from perk.convergence.init.blocks import (
    AGENTS_BEGIN,
    AGENTS_END,
    GITIGNORE_BEGIN,
    GITIGNORE_BODY,
    GITIGNORE_END,
    _agents_inner,
)
from perk.convergence.init.settings import (
    BORROWED_PACKAGES,
    LINEAR_PACKAGE,
    NPM_PACKAGE,
    _converge_compaction,
    _converge_linear_package,
    _converge_provider_packages,
    _desired_packages,
    _managed_identities,
    _merge_static_packages,
    _npm_name,
    _package_identity,
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
from perk.substrate.config import ConfigError, load_committed_compaction
from perk.substrate.providers import load_providers

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
    """One committed managed artifact: identity, shape, and its desired + observed payloads.

    ``desired`` is private plumbing (``(root, self_repo) -> bytes``; positional ``bool`` only
    because ``Callable[...]`` cannot express keyword-only parameters) — consumers go through
    :meth:`desired_payload` / :meth:`desired_hash`. ``observed`` is its live twin
    (``root -> bytes | None``; ``None`` = not installed) behind :meth:`observed_payload` /
    :meth:`observed_hash`. An ``OSError`` while observing propagates (loud at the caller — the
    artifact-health check layer guards it).
    """

    key: str  # stable state-file key (bare-TOML-safe, [a-z0-9-])
    path: str  # repo-relative display path; directory paths end with "/"
    kind: Kind
    scope: Scope
    desired: Callable[[Path, bool], bytes]
    observed: Callable[[Path], bytes | None]

    def desired_payload(self, root: Path, *, self_repo: bool) -> bytes:
        """The kind-normalized desired payload (file bytes / directory manifest / block inner)."""
        return self.desired(root, self_repo)

    def desired_hash(self, root: Path, *, self_repo: bool) -> str:
        """The digest of the desired payload."""
        return hash_bytes(self.desired_payload(root, self_repo=self_repo))

    def observed_payload(self, root: Path) -> bytes | None:
        """The kind-normalized live payload, or ``None`` when the artifact is not installed."""
        return self.observed(root)

    def observed_hash(self, root: Path) -> str | None:
        """The digest of the observed payload (``None`` when not installed)."""
        payload = self.observed_payload(root)
        return None if payload is None else hash_bytes(payload)


def _canonical_package_order(entries: list[object]) -> list[object]:
    """Identity-sorted canonical order for a ``packages`` portion (JSON canon tie-break).

    Convergence is merge-based, so a legitimately converged repo's live entry *order* is
    history-dependent (a pre-existing borrowed entry keeps its original position). Both the
    desired and observed settings portions therefore canonicalize order before hashing, so they
    compare order-insensitively — without this, a converged repo could classify
    ``locally-modified`` forever.
    """
    return sorted(
        entries, key=lambda e: (_package_identity(e) or "", json.dumps(e, sort_keys=True))
    )


def _settings_portion(root: Path, *, self_repo: bool) -> bytes:
    """Canonical JSON of perk's desired `.pi/settings.json` *portion* (never the live file).

    Rebuilt from scratch out of the convergence SSOT helpers — perk's own pinned entry plus the
    borrowed set, the provider/linear selections, and the committed ``[compaction]`` table. The
    hash therefore moves exactly when perk's desired wiring moves (version bump, borrowed-set
    change, provider/linear/compaction selection change) and never encodes user-owned settings
    keys. The reused helpers each treat a malformed committed TOML as empty (defer-to-config-check),
    so this inherits that posture. Package order is canonicalized (identity-sorted) so the
    observed twin compares order-insensitively — see :func:`_canonical_package_order`.
    """
    packages, _, _ = _merge_static_packages([], _desired_packages(self_repo))
    packages, _ = _converge_provider_packages(root, packages)
    packages, _ = _converge_linear_package(root, packages)
    stub: dict[str, object] = {}
    _converge_compaction(root, stub)
    portion: dict[str, object] = {"packages": _canonical_package_order(packages)}
    if "compaction" in stub:
        portion["compaction"] = stub["compaction"]
    return json.dumps(portion, indent=2, sort_keys=True).encode("utf-8")


def _manageable_identities() -> set[str]:
    """Every package identity perk itself may write into `.pi/settings.json`.

    The observed-settings filter: live entries outside this set are user-owned and invisible to
    the health lens. Both the self (``..``) and consumer (``@mgiles/perk``) own-entry identities
    are included unconditionally so the helper needs no ``self_repo``.
    """
    identities: set[str] = {".."}
    own = _npm_name(NPM_PACKAGE)
    if own is not None:
        identities.add(own)
    for borrowed in BORROWED_PACKAGES:
        identity = _package_identity(borrowed)
        if identity is not None:
            identities.add(identity)
    identities.update(_managed_identities(load_providers()))
    linear_identity = _package_identity(LINEAR_PACKAGE)
    if linear_identity is not None:
        identities.add(linear_identity)
    return identities


def _observed_settings(root: Path) -> bytes | None:
    """The live `.pi/settings.json`, reduced to perk's portion in the exact desired canon.

    ``None`` (not installed) when the file is absent, unparseable, or not a JSON object — the
    perk-owned portion is unobservable; the ``settings-wiring`` managed check separately fails
    loud/unverifiable and stays authoritative. Honest limitation: a merge-equivalent but
    shape-different entry (e.g. a hand-written string-form provider entry where perk writes
    object form) classifies ``locally-modified`` even though the merge convergence is clean —
    convergence stays authoritative; the intentionally-forked-files allowlist is the deferred
    refinement.
    """
    settings_path = root / ".pi" / "settings.json"
    if not settings_path.is_file():
        return None
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(settings, dict):
        return None
    raw_packages = settings.get("packages")
    packages = raw_packages if isinstance(raw_packages, list) else []
    manageable = _manageable_identities()
    mine = [entry for entry in packages if _package_identity(entry) in manageable]
    portion: dict[str, object] = {"packages": _canonical_package_order(mine)}
    try:
        desired_compaction = load_committed_compaction(root)
    except (tomllib.TOMLDecodeError, ConfigError):
        desired_compaction = {}
    live_compaction = settings.get("compaction")
    if desired_compaction and isinstance(live_compaction, dict):
        portion["compaction"] = {
            key: value for key, value in live_compaction.items() if key in desired_compaction
        }
    return json.dumps(portion, indent=2, sort_keys=True).encode("utf-8")


def _observed_file(rel: str) -> Callable[[Path], bytes | None]:
    """Observed-payload builder for ``file`` artifacts (missing file → not installed)."""

    def observe(root: Path) -> bytes | None:
        target = root / rel
        return target.read_bytes() if target.is_file() else None

    return observe


def _observed_block(rel: str, *, begin: str, end: str) -> Callable[[Path], bytes | None]:
    """Observed-payload builder for ``block`` artifacts (missing file/markers → not installed).

    The inner text goes through the same canon as the desired payload
    (:func:`_canonical_block_payload`), so trailing-newline drift never differs.
    """

    def observe(root: Path) -> bytes | None:
        target = root / rel
        if not target.is_file():
            return None
        inner = block_inner(target.read_text(encoding="utf-8"), begin=begin, end=end)
        return None if inner is None else _canonical_block_payload(inner)

    return observe


def _observed_agents_dir(root: Path) -> bytes | None:
    """The live `.pi/agents/perk/` directory manifest (``*.md`` only — the convergence's owned
    scope; stray non-md files are invisible to health exactly as they are to convergence).
    Missing dir or zero ``.md`` files → not installed."""
    agents_dir = root / ".pi" / "agents" / "perk"
    if not agents_dir.is_dir():
        return None
    files = {p.name: p.read_bytes() for p in agents_dir.glob("*.md")}
    if not files:
        return None
    return directory_manifest(files)


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
            observed=_observed_settings,
        ),
        ArtifactDescriptor(
            key="runner-workflow",
            path=RUNNER_WORKFLOW_PATH,
            kind="file",
            scope="both",
            desired=_runner_workflow_payload,
            observed=_observed_file(RUNNER_WORKFLOW_PATH),
        ),
        ArtifactDescriptor(
            key="remote-setup-action",
            path=REMOTE_SETUP_ACTION_PATH,
            kind="file",
            scope="both",
            desired=_remote_setup_action_payload,
            observed=_observed_file(REMOTE_SETUP_ACTION_PATH),
        ),
        ArtifactDescriptor(
            key="subagent-agents",
            path=".pi/agents/perk/",
            kind="directory",
            scope="both",
            desired=_subagent_agents_payload,
            observed=_observed_agents_dir,
        ),
        ArtifactDescriptor(
            key="skills-manifest",
            path=f"{PERK_SKILLS_MANIFEST_DIR}/{PERK_SKILLS_MANIFEST_FILENAME}",
            kind="file",
            scope="both",
            desired=_skills_manifest_payload,
            observed=_observed_file(f"{PERK_SKILLS_MANIFEST_DIR}/{PERK_SKILLS_MANIFEST_FILENAME}"),
        ),
        ArtifactDescriptor(
            key="gitignore-block",
            path=".gitignore",
            kind="block",
            scope="both",
            desired=_gitignore_block_payload,
            observed=_observed_block(".gitignore", begin=GITIGNORE_BEGIN, end=GITIGNORE_END),
        ),
        ArtifactDescriptor(
            key="agents-block",
            path="AGENTS.md",
            kind="block",
            scope="both",
            desired=_agents_block_payload,
            observed=_observed_block("AGENTS.md", begin=AGENTS_BEGIN, end=AGENTS_END),
        ),
        ArtifactDescriptor(
            key="required-perk-version",
            path=".perk/required-perk-version",
            kind="file",
            scope="both",
            desired=_version_pin_payload,
            observed=_observed_file(".perk/required-perk-version"),
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


def record_managed_state(root: Path, *, self_repo: bool) -> str | None:
    """Record the current desired state to `.perk/managed-state.toml` (content-gated).

    Returns ``None`` when the file already holds the exact rendered bytes (the no-op arm both
    idempotency suites pin), a ``": recorded"`` change line when the file was created, or a
    ``": updated"`` line when existing content differed — that arm is also the repair for a
    malformed state file (any unparseable text simply differs and is rewritten). ``OSError``
    propagates (loud at the caller).
    """
    state = desired_state(root, self_repo=self_repo)
    rendered = render_managed_state(state)
    path = paths.managed_state_file(root)
    existing = path.read_text(encoding="utf-8") if path.is_file() else None
    if existing == rendered:
        return None
    save_managed_state(root, state)
    verb = "updated" if existing is not None else "recorded"
    return f".perk/managed-state.toml: {verb}"


# --- Artifact health (the report-only diagnostic lens) ---------------------------------------

HealthStatus = Literal[
    "up-to-date", "not-installed", "locally-modified", "changed-upstream", "state-missing"
]


@dataclass(frozen=True)
class ArtifactHealth:
    """One artifact's classified health row (diagnostic only — never drives pass/fail)."""

    key: str
    path: str
    kind: str
    status: HealthStatus
    recorded_version: str | None
    recorded_hash: str | None
    desired_hash: str
    observed_hash: str | None


def classify_artifact(*, observed: str | None, desired: str, recorded: str | None) -> HealthStatus:
    """The pure two-signal classifier (first match wins).

    1. no observed payload → ``not-installed``;
    2. observed == desired → ``up-to-date`` (a stale/absent recorded row never demotes a
       converged artifact — the next init/``--fix`` refreshes state);
    3. drift with no recorded hash to arbitrate → ``state-missing``;
    4. observed == recorded → ``changed-upstream`` (untouched since perk last wrote it; perk's
       desired moved — version upgrade / config change);
    5. else → ``locally-modified`` (the user changed it since perk last wrote it).
    """
    if observed is None:
        return "not-installed"
    if observed == desired:
        return "up-to-date"
    if recorded is None:
        return "state-missing"
    if observed == recorded:
        return "changed-upstream"
    return "locally-modified"


def artifact_health(
    root: Path, *, self_repo: bool, state: ManagedState | None
) -> tuple[ArtifactHealth, ...]:
    """One classified row per registry descriptor, in sorted-key order.

    Unfiltered by capability scope, mirroring :func:`desired_state` — one artifact set
    everywhere (every descriptor is scope ``"both"`` today). ``state=None`` covers both an
    absent and a malformed state file (the caller decides which); recorded rows for keys no
    descriptor names are ignored (and dropped by the next state write).
    """
    recorded_by_key = {a.key: a for a in state.artifacts} if state is not None else {}
    rows: list[ArtifactHealth] = []
    for descriptor in sorted(managed_artifacts(), key=lambda d: d.key):
        recorded = recorded_by_key.get(descriptor.key)
        desired = descriptor.desired_hash(root, self_repo=self_repo)
        observed = descriptor.observed_hash(root)
        rows.append(
            ArtifactHealth(
                key=descriptor.key,
                path=descriptor.path,
                kind=descriptor.kind,
                status=classify_artifact(
                    observed=observed,
                    desired=desired,
                    recorded=recorded.hash if recorded is not None else None,
                ),
                recorded_version=recorded.version if recorded is not None else None,
                recorded_hash=recorded.hash if recorded is not None else None,
                desired_hash=desired,
                observed_hash=observed,
            )
        )
    return tuple(rows)
