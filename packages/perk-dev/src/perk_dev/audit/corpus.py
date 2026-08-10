"""Session-corpus enumeration + the perk-session census (the audit corpus substrate).

Enumerates the machine's Pi session history for this repo (main checkout + worktrees,
including deleted ones), parses each session through perk's lenient ``session_jsonl``
read edge, classifies each session best-effort by layered signals (``perk:workflow-state``
payloads, skill-binding / read-only markers, session-pointer joins), and builds a
census — including per-expectation not-exercised accounting against the committed
catalog. No verdicts are computed here; the census is the corpus-identification
substrate the deterministic runner runs on.

Pure/injectable throughout (mirroring ``expectations.py``'s discipline): every
enumeration/classification input is an explicit parameter (``sessions_root``,
``main_root``, ``worktree_root``, ``catalog``, ``bindings``) so unit tests never touch
the real home dir. Enumeration never raises — an absent sessions root is an empty
census, an unreadable file is a count, a malformed line is the read edge's problem.

Pi session storage (verified against pi's ``session-manager``): one dir per encoded
cwd under ``~/.pi/agent/sessions/``, named ``--<cwd with / \\ : → ->--``. The encoding
is **lossy** (a literal ``-`` in a path segment is indistinguishable from a separator),
so encoded dir names are only a cheap prefilter; the header ``cwd`` inside each file is
the membership authority.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from perk.boundary import OutputModel
from perk.learn.session_jsonl import ParsedSession, parse_session_jsonl
from perk.state.cache import list_run_ids
from perk.state.session_pointers import read_session_pointers
from perk.substrate.binding_delivery import _HEADER as BINDING_HEADER
from perk.substrate.bindings import Binding
from perk_dev.audit.expectations import ExpectationCatalog
from perk_dev.audit.vintage import ReleaseHistory, SessionVintage, applicability, reckon_vintage

# The read-only mode marker injected by the warm gate (extension/substrate/toolGating.ts);
# scanned as a substring of user text / custom-entry content.
READ_ONLY_MARKER = "[READ-ONLY MODE]"
# The workflow-state custom-entry type (contracts.md §8.3).
WORKFLOW_STATE_TYPE = "perk:workflow-state"

# The two rendered skill-pointer forms (perk/substrate/binding_delivery.py): the nudge
# pointer line and the transclude header. Both capture the skill name. Public: the
# deterministic checkers (checks.py) reuse the same delivered-pointer grammar.
NUDGE_PATTERN = re.compile(r"Follow the `([^`]+)` skill")
TRANSCLUDE_PATTERN = re.compile(r"Skill `([^`]+)` \(inlined for ")

# The session-identity vocabulary (strongest signal wins, in this order).
IDENTITIES: tuple[str, ...] = ("perk-stage", "perk-warm", "marker-only", "non-perk")


def default_sessions_root() -> Path:
    """Pi's session-history root on this machine (overridable via ``--sessions-root``)."""
    return Path.home() / ".pi" / "agent" / "sessions"


# --------------------------------------------------------------------------- encoding


def encode_session_dir(cwd: str) -> str:
    """Pi's exact session-dir encoding of a cwd (lossy — prefilter only, never authority).

    Verified against pi's ``session-manager``: strip ONE leading ``/`` or ``\\``, replace
    every ``/``, ``\\``, ``:`` with ``-``, wrap in ``--…--``.
    """
    stripped = re.sub(r"^[/\\]", "", cwd, count=1)
    return f"--{re.sub(r'[/\\:]', '-', stripped)}--"


# ------------------------------------------------------------------ membership/location


@dataclass(frozen=True)
class SessionLocation:
    """Where a confirmed session's recorded cwd sits relative to the repo.

    ``kind`` is ``main`` (the main checkout itself), ``worktree`` (under the worktree
    root — ``worktree_name`` is the first segment, ``worktree_exists`` whether that dir
    still exists, the deleted-worktree accounting), or ``subpath`` (a repo subdir).
    """

    kind: str
    worktree_name: str | None = None
    worktree_exists: bool | None = None


def _root_forms(root: Path) -> tuple[str, ...]:
    """The comparison forms of a root: as given plus ``resolve()``d (the macOS
    ``/private`` symlink family). String forms — the recorded cwd may no longer exist."""
    forms = [str(root)]
    resolved = str(root.resolve())
    if resolved not in forms:
        forms.append(resolved)
    return tuple(forms)


def _strictly_under(path: str, root: str) -> bool:
    return path.startswith(root.rstrip("/") + "/")


def classify_cwd(cwd: str, *, main_root: Path, worktree_root: Path) -> SessionLocation | None:
    """Classify a recorded header cwd against the repo anchors (``None`` == foreign).

    Pure string comparison (the path may have been deleted), against both the given and
    resolved root forms. The worktree check precedes the subpath check because the
    default worktree root lives under the main checkout.
    """
    main_forms = _root_forms(main_root)
    if any(cwd == form for form in main_forms):
        return SessionLocation(kind="main")
    for form in _root_forms(worktree_root):
        if _strictly_under(cwd, form):
            name = cwd[len(form.rstrip("/")) + 1 :].split("/", 1)[0]
            return SessionLocation(
                kind="worktree",
                worktree_name=name,
                worktree_exists=(worktree_root / name).exists(),
            )
    if any(_strictly_under(cwd, form) for form in main_forms):
        return SessionLocation(kind="subpath")
    return None


# ------------------------------------------------------------------------- enumeration


def enumerate_candidate_dirs(
    sessions_root: Path, *, main_root: Path, worktree_root: Path
) -> tuple[Path, ...]:
    """The candidate session dirs: the exact encoded main dirs plus every prefix match.

    A cheap prefilter only — the encoding is lossy, so a sibling-repo lookalike
    (``…-perk-foo--``) survives to the header check. Both the given and resolved root
    spellings are encoded (pi records the *resolved* cwd, so a symlinked configured root
    — the macOS ``/private`` family — must not filter its own sessions out). When the
    worktree root is not under the main checkout (custom absolute config), its encoded
    prefixes join the filter. Never raises: an absent or unlistable ``sessions_root`` is
    an empty corpus.
    """
    main_forms = _root_forms(main_root)
    exacts = {encode_session_dir(form) for form in main_forms}
    prefixes = {exact[:-2] + "-" for exact in exacts}
    worktree_forms = _root_forms(worktree_root)
    external = not any(_strictly_under(w, m) for w in worktree_forms for m in main_forms)
    if external:
        prefixes.update(encode_session_dir(w)[:-2] + "-" for w in worktree_forms)
    try:
        children = sorted(sessions_root.iterdir())
    except OSError:
        return ()
    return tuple(
        child
        for child in children
        if child.is_dir()  # pathlib swallows OSError here (→ False)
        and (child.name in exacts or any(child.name.startswith(p) for p in prefixes))
    )


def _read_header(path: Path) -> tuple[str, dict[str, object] | None]:
    """Read + parse ONLY the first line (never raises).

    Returns ``("ok", header_obj)`` for a parseable ``type:"session"`` header carrying a
    string ``cwd``; ``("unconfirmed", None)`` for a readable file whose first line is
    missing/unparseable/header-less/cwd-less; ``("unreadable", None)`` on an OS error.
    """
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            line = fh.readline()
    except OSError:
        return ("unreadable", None)
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return ("unconfirmed", None)
    if not isinstance(obj, dict) or obj.get("type") != "session":
        return ("unconfirmed", None)
    if not isinstance(obj.get("cwd"), str):
        return ("unconfirmed", None)
    return ("ok", obj)


# ----------------------------------------------------------------------------- signals


@dataclass(frozen=True)
class SessionSignals:
    """The layered per-session signals the identity + evidence derivations run on.

    The workflow-state values are **sets** (sorted tuples), not last-write-wins: a
    session file can carry multiple branches/forks, and the census is honest about
    multiplicity.
    """

    workflow_state_seen: bool
    run_ids: tuple[str, ...]
    stages: tuple[str, ...]
    modes: tuple[str, ...]
    perk_versions: tuple[str, ...]
    binding_header_seen: bool
    binding_skills: tuple[str, ...]
    read_only_marker: bool


def extract_signals(parsed: ParsedSession) -> SessionSignals:
    """Extract the workflow-state + marker signals from a fully parsed session.

    Markers are scanned ONLY in user-role ``message`` text and custom entries'
    ``content`` — assistant/toolResult text is excluded because sessions in this repo
    routinely quote perk's own source (the false-positive family this scope kills).
    """
    workflow_state_seen = False
    run_ids: set[str] = set()
    stages: set[str] = set()
    modes: set[str] = set()
    perk_versions: set[str] = set()
    binding_header_seen = False
    skills: set[str] = set()
    read_only = False

    for entry in parsed.entries:
        if entry.kind == "custom" and entry.custom_type == WORKFLOW_STATE_TYPE:
            workflow_state_seen = True
            data = entry.data or {}
            # `perk_version` is the pinned stamp key the workflow-state writer records when
            # run identity is established (the claim/fork/adopt/mint arms) — the vintage
            # layer's exact basis (see `vintage.py`).
            for key, into in (
                ("run_id", run_ids),
                ("stage", stages),
                ("mode", modes),
                ("perk_version", perk_versions),
            ):
                value = data.get(key)
                if isinstance(value, str) and value:
                    into.add(value)
            continue
        texts: list[str] = []
        if entry.kind == "message" and entry.role == "user" and entry.text:
            texts.append(entry.text)
        if entry.kind in ("custom", "custom_message") and entry.content:
            texts.append(entry.content)
        for text in texts:
            if BINDING_HEADER in text:
                binding_header_seen = True
            if READ_ONLY_MARKER in text:
                read_only = True
            skills.update(NUDGE_PATTERN.findall(text))
            skills.update(TRANSCLUDE_PATTERN.findall(text))

    return SessionSignals(
        workflow_state_seen=workflow_state_seen,
        run_ids=tuple(sorted(run_ids)),
        stages=tuple(sorted(stages)),
        modes=tuple(sorted(modes)),
        perk_versions=tuple(sorted(perk_versions)),
        binding_header_seen=binding_header_seen,
        binding_skills=tuple(sorted(skills)),
        read_only_marker=read_only,
    )


# ----------------------------------------------------------------------- pointer joins


@dataclass(frozen=True)
class PointerJoin:
    """One session-pointer hit: the run that recorded this session file, at which slot
    (``session_class`` ∈ {planning, implementation} x ``site`` ∈ {main, worker})."""

    run_id: str
    session_class: str
    site: str


def build_pointer_index(main_root: Path) -> dict[str, tuple[PointerJoin, ...]]:
    """Prebuild the ``pi_session_id`` basename → pointer-join index for the whole run
    cache (``list_run_ids`` x ``read_session_pointers``; both never raise)."""
    index: dict[str, list[PointerJoin]] = {}
    try:
        run_ids = list_run_ids(main_root)
    except OSError:  # an unreadable run cache degrades to no joins, never a crash
        return {}
    for run_id in run_ids:
        record = read_session_pointers(main_root, run_id)
        if record is None:
            continue
        for session_class, slots in (
            ("planning", record.planning),
            ("implementation", record.implementation),
        ):
            for site, pointer in (("main", slots.main), ("worker", slots.worker)):
                if pointer is None:
                    continue
                index.setdefault(pointer.pi_session_id, []).append(
                    PointerJoin(run_id=run_id, session_class=session_class, site=site)
                )
    return {key: tuple(joins) for key, joins in index.items()}


# ---------------------------------------------------------------- identity + evidence


def classify_identity(signals: SessionSignals, joins: tuple[PointerJoin, ...]) -> str:
    """The perk-session identity (strongest layered signal wins)."""
    if signals.stages:
        return "perk-stage"
    if signals.workflow_state_seen:
        return "perk-warm"
    if signals.binding_header_seen or signals.binding_skills or signals.read_only_marker or joins:
        return "marker-only"
    return "non-perk"


@dataclass(frozen=True)
class TriggerEvidence:
    """One evidenced ``applies_to`` trigger with its signal provenance.

    ``signal`` is ``workflow-state`` (an observed cold-claimed stage) or
    ``binding-marker`` (derived from a delivered skill pointer via the shipped default
    bindings — ``skill`` names it; ``ambiguous`` flags a skill bound to multiple
    triggers, each of which is evidenced).
    """

    trigger: str
    signal: str
    skill: str | None = None
    ambiguous: bool = False


def derive_evidence(
    signals: SessionSignals, bindings: list[Binding]
) -> tuple[TriggerEvidence, ...]:
    """The session's ``applies_to``-joinable trigger evidence.

    Each observed workflow-state stage evidences ``stage:<s>``. Each marker skill maps
    through the **shipped default** bindings (deliberate: the user overlay is
    vintage-unstable; the defaults are the shipped contract): a ``command:<x>`` binding
    evidences ``command:x``; a ``stage:<x>`` binding with ``x`` NOT among the observed
    stages evidences ``command:x`` — the warm-slash-command derivation (the
    kind-selection rule delivers a 1:1 command's nudge under its stage trigger, and a
    warm command never cold-claims a stage); a ``stage:<x>`` binding with ``x`` observed
    is corroboration only (already evidenced).
    """
    evidence: list[TriggerEvidence] = []
    stages = set(signals.stages)
    for stage in signals.stages:
        evidence.append(TriggerEvidence(trigger=f"stage:{stage}", signal="workflow-state"))

    by_skill: dict[str, list[Binding]] = {}
    for binding in bindings:
        by_skill.setdefault(binding.skill, []).append(binding)
    for skill in signals.binding_skills:
        skill_bindings = by_skill.get(skill, [])
        ambiguous = len(skill_bindings) > 1
        for binding in skill_bindings:
            if binding.kind not in ("command", "stage"):
                continue
            if binding.kind == "stage" and binding.target_id in stages:
                continue  # an observed stage:<x> binding corroborates, never re-evidences
            evidence.append(
                TriggerEvidence(
                    trigger=f"command:{binding.target_id}",
                    signal="binding-marker",
                    skill=skill,
                    ambiguous=ambiguous,
                )
            )
    return tuple(evidence)


# ------------------------------------------------------------------------------ census


@dataclass(frozen=True)
class SessionRecord:
    """One confirmed session's full census row."""

    path: str
    basename: str
    location: str
    worktree_name: str | None
    worktree_exists: bool | None
    session_id: str | None
    cwd: str
    timestamp: str | None
    run_ids: tuple[str, ...]
    stages: tuple[str, ...]
    modes: tuple[str, ...]
    perk_versions: tuple[str, ...]
    vintage_version: str | None
    vintage_basis: str
    binding_header_seen: bool
    binding_skills: tuple[str, ...]
    read_only_marker: bool
    pointer_joins: tuple[PointerJoin, ...]
    identity: str
    evidence: tuple[TriggerEvidence, ...]
    entry_count: int
    malformed_lines: int

    def vintage(self) -> SessionVintage:
        """The record's reckoned vintage, reassembled for the applicability gate."""
        return SessionVintage(version=self.vintage_version, basis=self.vintage_basis)


@dataclass(frozen=True)
class CensusTotals:
    """The corpus accounting: every candidate file lands in exactly one of
    confirmed / unconfirmed / foreign / unreadable."""

    candidate_files: int
    confirmed: int
    unconfirmed: int
    foreign: int
    unreadable: int
    malformed_lines: int


@dataclass(frozen=True)
class ExpectationCoverage:
    """One catalog expectation's exercised-session count against the corpus.

    ``applicable_sessions`` / ``not_applicable_sessions`` / ``vintage_unknown_sessions``
    partition ``exercising_sessions`` by the vintage gate
    (``vintage.applicability`` against the expectation's ``vintage_floor``).
    ``exercising_sessions`` itself stays vintage-independent — "zero
    evidence-intersecting sessions" keeps meaning exactly that.
    """

    id: str
    applies_to: tuple[str, ...]
    exercising_sessions: int
    applicable_sessions: int
    not_applicable_sessions: int
    vintage_unknown_sessions: int


@dataclass(frozen=True)
class Census:
    """The full census: roots, totals, per-session records, aggregates, and the
    per-expectation not-exercised accounting."""

    sessions_root: str
    main_root: str
    worktree_root: str
    candidate_dirs: tuple[str, ...]
    totals: CensusTotals
    sessions: tuple[SessionRecord, ...]
    identity_counts: dict[str, int]
    stage_counts: dict[str, int]
    mode_counts: dict[str, int]
    trigger_counts: dict[str, int]
    pointer_join_counts: dict[str, int]
    release_count: int
    vintage_basis_counts: dict[str, int]
    expectations: tuple[ExpectationCoverage, ...]
    not_exercised: tuple[str, ...]


def build_census(
    *,
    sessions_root: Path,
    main_root: Path,
    worktree_root: Path,
    catalog: ExpectationCatalog,
    bindings: list[Binding],
    history: ReleaseHistory,
) -> Census:
    """Enumerate, confirm, classify, and aggregate the repo's session corpus.

    Never raises: an absent/unlistable sessions root is an empty census; per-file and
    per-directory problems are counts/skips. Full-parsing the whole corpus through the
    pydantic read edge is minutes-scale on a large history — accepted for an on-demand
    dev census.
    """
    pointer_index = build_pointer_index(main_root)
    candidate_dirs = enumerate_candidate_dirs(
        sessions_root, main_root=main_root, worktree_root=worktree_root
    )

    candidate_files = 0
    unconfirmed = 0
    foreign = 0
    unreadable = 0
    records: list[SessionRecord] = []

    for directory in candidate_dirs:
        try:
            paths = sorted(directory.glob("*.jsonl"))
        except OSError:  # a candidate dir that becomes unlistable is skipped, never a crash
            continue
        for path in paths:
            candidate_files += 1
            status, header = _read_header(path)
            if status == "unreadable":
                unreadable += 1
                continue
            if header is None:
                unconfirmed += 1
                continue
            cwd = _opt_str(header.get("cwd"))
            if cwd is None:
                unconfirmed += 1
                continue
            location = classify_cwd(cwd, main_root=main_root, worktree_root=worktree_root)
            if location is None:
                foreign += 1
                continue

            parsed = parse_session_jsonl(path)
            if parsed.header is None:
                # The first-line read confirmed a header, so a header-less full parse means
                # the whole-file read failed (the read edge degrades an unreadable/undecodable
                # file to empty) — count it unreadable rather than a confirmed empty session.
                unreadable += 1
                continue
            signals = extract_signals(parsed)
            joins = pointer_index.get(path.name, ())
            identity = classify_identity(signals, joins)
            evidence = derive_evidence(signals, bindings)
            timestamp = _opt_str(header.get("timestamp"))
            vintage = reckon_vintage(
                perk_versions=signals.perk_versions, timestamp=timestamp, history=history
            )
            records.append(
                SessionRecord(
                    path=str(path),
                    basename=path.name,
                    location=location.kind,
                    worktree_name=location.worktree_name,
                    worktree_exists=location.worktree_exists,
                    session_id=_opt_str(header.get("id")),
                    cwd=cwd,
                    timestamp=timestamp,
                    run_ids=signals.run_ids,
                    stages=signals.stages,
                    modes=signals.modes,
                    perk_versions=signals.perk_versions,
                    vintage_version=vintage.version,
                    vintage_basis=vintage.basis,
                    binding_header_seen=signals.binding_header_seen,
                    binding_skills=signals.binding_skills,
                    read_only_marker=signals.read_only_marker,
                    pointer_joins=joins,
                    identity=identity,
                    evidence=evidence,
                    entry_count=len(parsed.entries),
                    malformed_lines=parsed.malformed_lines,
                )
            )

    identity_counts = Counter(r.identity for r in records)
    stage_counts = Counter(stage for r in records for stage in r.stages)
    mode_counts = Counter(mode for r in records for mode in r.modes)
    trigger_counts = Counter(
        trigger for r in records for trigger in sorted({e.trigger for e in r.evidence})
    )
    pointer_join_counts = Counter(
        f"{j.session_class}.{j.site}" for r in records for j in r.pointer_joins
    )
    vintage_basis_counts = Counter(r.vintage_basis for r in records)

    coverage: list[ExpectationCoverage] = []
    not_exercised: list[str] = []
    for expectation in catalog.expectations:
        applies = set(expectation.applies_to)
        exercising = [r for r in records if applies.intersection(e.trigger for e in r.evidence)]
        gates = Counter(applicability(expectation.vintage_floor, r.vintage()) for r in exercising)
        coverage.append(
            ExpectationCoverage(
                id=expectation.id,
                applies_to=expectation.applies_to,
                exercising_sessions=len(exercising),
                applicable_sessions=gates["applicable"],
                not_applicable_sessions=gates["not-applicable"],
                vintage_unknown_sessions=gates["vintage-unknown"],
            )
        )
        if not exercising:
            not_exercised.append(expectation.id)

    return Census(
        sessions_root=str(sessions_root),
        main_root=str(main_root),
        worktree_root=str(worktree_root),
        candidate_dirs=tuple(d.name for d in candidate_dirs),
        totals=CensusTotals(
            candidate_files=candidate_files,
            confirmed=len(records),
            unconfirmed=unconfirmed,
            foreign=foreign,
            unreadable=unreadable,
            malformed_lines=sum(r.malformed_lines for r in records),
        ),
        sessions=tuple(records),
        identity_counts=dict(sorted(identity_counts.items())),
        stage_counts=dict(sorted(stage_counts.items())),
        mode_counts=dict(sorted(mode_counts.items())),
        trigger_counts=dict(sorted(trigger_counts.items())),
        pointer_join_counts=dict(sorted(pointer_join_counts.items())),
        release_count=len(history.releases),
        vintage_basis_counts=dict(sorted(vintage_basis_counts.items())),
        expectations=tuple(coverage),
        not_exercised=tuple(not_exercised),
    )


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


# -------------------------------------------------------------------- serialize edge


class PointerJoinOut(OutputModel):
    run_id: str
    session_class: str
    site: str


class TriggerEvidenceOut(OutputModel):
    trigger: str
    signal: str
    skill: str | None
    ambiguous: bool


class SessionRecordOut(OutputModel):
    path: str
    basename: str
    location: str
    worktree_name: str | None
    worktree_exists: bool | None
    session_id: str | None
    cwd: str
    timestamp: str | None
    run_ids: tuple[str, ...]
    stages: tuple[str, ...]
    modes: tuple[str, ...]
    perk_versions: tuple[str, ...]
    vintage_version: str | None
    vintage_basis: str
    binding_header_seen: bool
    binding_skills: tuple[str, ...]
    read_only_marker: bool
    pointer_joins: tuple[PointerJoinOut, ...]
    identity: str
    evidence: tuple[TriggerEvidenceOut, ...]
    entry_count: int
    malformed_lines: int

    @classmethod
    def from_domain(cls, r: SessionRecord) -> "SessionRecordOut":
        return cls(
            path=r.path,
            basename=r.basename,
            location=r.location,
            worktree_name=r.worktree_name,
            worktree_exists=r.worktree_exists,
            session_id=r.session_id,
            cwd=r.cwd,
            timestamp=r.timestamp,
            run_ids=r.run_ids,
            stages=r.stages,
            modes=r.modes,
            perk_versions=r.perk_versions,
            vintage_version=r.vintage_version,
            vintage_basis=r.vintage_basis,
            binding_header_seen=r.binding_header_seen,
            binding_skills=r.binding_skills,
            read_only_marker=r.read_only_marker,
            pointer_joins=tuple(
                PointerJoinOut(run_id=j.run_id, session_class=j.session_class, site=j.site)
                for j in r.pointer_joins
            ),
            identity=r.identity,
            evidence=tuple(
                TriggerEvidenceOut(
                    trigger=e.trigger, signal=e.signal, skill=e.skill, ambiguous=e.ambiguous
                )
                for e in r.evidence
            ),
            entry_count=r.entry_count,
            malformed_lines=r.malformed_lines,
        )


class CensusTotalsOut(OutputModel):
    candidate_files: int
    confirmed: int
    unconfirmed: int
    foreign: int
    unreadable: int
    malformed_lines: int


class ExpectationCoverageOut(OutputModel):
    id: str
    applies_to: tuple[str, ...]
    exercising_sessions: int
    applicable_sessions: int
    not_applicable_sessions: int
    vintage_unknown_sessions: int


class CensusOut(OutputModel):
    """The ``--json`` envelope for a successful census."""

    success: bool
    error_type: str | None
    sessions_root: str
    main_root: str
    worktree_root: str
    candidate_dirs: tuple[str, ...]
    totals: CensusTotalsOut
    identity_counts: dict[str, int]
    stage_counts: dict[str, int]
    mode_counts: dict[str, int]
    trigger_counts: dict[str, int]
    pointer_join_counts: dict[str, int]
    release_count: int
    vintage_basis_counts: dict[str, int]
    sessions: tuple[SessionRecordOut, ...]
    expectations: tuple[ExpectationCoverageOut, ...]
    not_exercised: tuple[str, ...]

    @classmethod
    def from_domain(cls, c: Census) -> "CensusOut":
        return cls(
            success=True,
            error_type=None,
            sessions_root=c.sessions_root,
            main_root=c.main_root,
            worktree_root=c.worktree_root,
            candidate_dirs=c.candidate_dirs,
            totals=CensusTotalsOut(
                candidate_files=c.totals.candidate_files,
                confirmed=c.totals.confirmed,
                unconfirmed=c.totals.unconfirmed,
                foreign=c.totals.foreign,
                unreadable=c.totals.unreadable,
                malformed_lines=c.totals.malformed_lines,
            ),
            identity_counts=c.identity_counts,
            stage_counts=c.stage_counts,
            mode_counts=c.mode_counts,
            trigger_counts=c.trigger_counts,
            pointer_join_counts=c.pointer_join_counts,
            release_count=c.release_count,
            vintage_basis_counts=c.vintage_basis_counts,
            sessions=tuple(SessionRecordOut.from_domain(r) for r in c.sessions),
            expectations=tuple(
                ExpectationCoverageOut(
                    id=e.id,
                    applies_to=e.applies_to,
                    exercising_sessions=e.exercising_sessions,
                    applicable_sessions=e.applicable_sessions,
                    not_applicable_sessions=e.not_applicable_sessions,
                    vintage_unknown_sessions=e.vintage_unknown_sessions,
                )
                for e in c.expectations
            ),
            not_exercised=c.not_exercised,
        )
