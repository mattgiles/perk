"""Subjects: the ``LABEL=CHECKOUT`` specs, their preflight, Pi's project trust, and the
provenance stamp.

A subject is a prepared perk checkout measured through its OWN console script
(``CHECKOUT/.venv/bin/perk`` — the executable a user pays for; ``uv run`` adds resolver/sync
overhead nobody pays and stays the provisioning step). Every refusal is decided before any
sample is spawned: ``bad_arguments`` (label syntax / duplicates), ``subject_missing`` (no
checkout or console script), ``subject_not_converged`` (no ``.pi/npm`` install),
``subject_probe_failed`` (not a git repo, or a ``--version`` probe failed), ``subject_untrusted``
(Pi would stop at its trust prompt — a benchmark session cannot answer it).

:func:`check_trust` mirrors Pi's ``ProjectTrustStore`` (``dist/core/trust-manager.js``):
``<agent_dir>/trust.json`` keyed by canonical path → ``true | false | null``, the nearest
ancestor holding a boolean wins; a malformed store is refused by Pi too, so it is refused here;
then the global ``settings.json``'s ``defaultProjectTrust == "always"``. Perk's own worktree
launches pass ``--approve`` (no ``trust.json`` write), which is why the how-to asks for one
interactive ``pi`` run in each subject.
"""

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from perk.cli.ensure import UserFacingCliError
from perk.substrate import git
from perk.substrate.config import ConfigError, launch_pi_agent_dir
from perk.substrate.proc import ProcFailure, run_captured
from perk_dev.profile_startup.census import SDK_PACKAGE_NAMES

LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PROBE_TIMEOUT_S = 60


@dataclass(frozen=True)
class Subject:
    """One measured checkout: its label, root, console script, and interpreter."""

    label: str
    checkout: Path
    executable: Path
    python: Path


@dataclass(frozen=True)
class SdkCopy:
    """One installed copy of an SDK package found under a subject's ``node_modules`` roots."""

    name: str
    root: str
    version: str | None


@dataclass(frozen=True)
class SubjectStamp:
    """Per-subject provenance recorded before any sample runs (field order is the JSON order).

    ``sdk_copies`` records every SDK package copy under BOTH ``.pi/npm/node_modules`` and the
    checkout-root ``node_modules`` (native resolution walks up, so a package declaring the SDK
    as an optional peer may load the root copy); the census — not this probe — is the authority
    for what actually loaded.
    """

    head: str
    dirty: bool
    perk_version: str
    pi_version: str
    pi_path: str
    node_version: str
    packages: dict[str, str | None]
    sdk_copies: tuple[SdkCopy, ...]
    agent_dir: str | None
    agent_dir_source: str | None
    trusted_by: str


def _refuse(error_type: str, message: str) -> UserFacingCliError:
    return UserFacingCliError(message, error_type=error_type)


def _read_json_object(path: Path) -> dict[str, object] | None:
    """A JSON object read from ``path``; ``None`` when missing, unreadable, or not an object."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def _executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def preflight_subject(label: str, checkout: Path) -> Subject:
    """The filesystem preflight for one spec: ``subject_missing`` then ``subject_not_converged``."""
    if not checkout.is_dir():
        raise _refuse("subject_missing", f"subject {label}: {checkout} is not a directory")
    executable = checkout / ".venv" / "bin" / "perk"
    python = checkout / ".venv" / "bin" / "python"
    for tool in (executable, python):
        if not _executable(tool):
            raise _refuse(
                "subject_missing",
                f"subject {label}: {tool} is missing or not executable — prepare the checkout "
                f"with `uv sync --all-packages --project {checkout}`",
            )
    npm_dir = checkout / ".pi" / "npm"
    if not (npm_dir / "node_modules").is_dir():
        raise _refuse(
            "subject_not_converged",
            f"subject {label}: {npm_dir / 'node_modules'} is missing — run `perk doctor --fix` "
            f"in {checkout}",
        )
    if _read_json_object(npm_dir / "package.json") is None:
        raise _refuse(
            "subject_not_converged",
            f"subject {label}: {npm_dir / 'package.json'} is missing or not a JSON object — run "
            f"`perk doctor --fix` in {checkout}",
        )
    return Subject(label=label, checkout=checkout, executable=executable, python=python)


def parse_subject_specs(specs: Sequence[str]) -> tuple[Subject, ...]:
    """``LABEL=CHECKOUT`` specs → subjects, in the given order.

    Label syntax and uniqueness are ``bad_arguments`` (decided for EVERY spec before any
    filesystem check); then each subject runs :func:`preflight_subject` in order. Uniqueness is
    case-INsensitive: labels name run-directory paths (``subjects/<label>``, ``samples/<label>``,
    ``profiles/<label>``), and on a case-insensitive filesystem (the macOS default) ``foo`` and
    ``Foo`` would silently share — and overwrite — one another's artifacts.
    """
    parsed: list[tuple[str, Path]] = []
    seen: dict[str, str] = {}
    for spec in specs:
        label, sep, raw_checkout = spec.partition("=")
        if not sep or not raw_checkout:
            raise _refuse("bad_arguments", f"--subject expects LABEL=CHECKOUT, got {spec!r}")
        if LABEL_RE.match(label) is None:
            raise _refuse(
                "bad_arguments",
                f"--subject label {label!r} must match {LABEL_RE.pattern}",
            )
        folded = label.casefold()
        if folded in seen:
            earlier = seen[folded]
            detail = "is given twice" if earlier == label else f"collides with {earlier!r} by case"
            raise _refuse(
                "bad_arguments",
                f"--subject label {label!r} {detail} — labels name run-directory paths, which "
                "collide on a case-insensitive filesystem",
            )
        seen[folded] = label
        parsed.append((label, Path(raw_checkout).expanduser().resolve()))
    return tuple(preflight_subject(label, checkout) for label, checkout in parsed)


def check_trust(checkout: Path, agent_dir: Path) -> str:
    """Pi's project-trust lookup for ``checkout`` against ``agent_dir``'s store.

    Returns ``trusted_by=<path>`` for the nearest ``trust.json`` ancestor entry holding ``true``
    (the exact key or an ancestor), ``trusted_by=defaultProjectTrust`` when the store has no
    boolean entry on the walk and the global ``settings.json`` says ``"always"``; raises
    ``subject_untrusted`` otherwise — including a nearer ``false`` shadowing an outer ``true``
    (Pi's nearest-wins rule) and a malformed store (Pi refuses it as well).
    """
    trust_path = agent_dir / "trust.json"
    entries: dict[str, bool | None] = {}
    if trust_path.exists():
        try:
            raw = json.loads(trust_path.read_text(encoding="utf-8").lstrip("\ufeff"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _refuse(
                "subject_untrusted", f"{trust_path} is unreadable ({exc}) — Pi refuses it too"
            ) from exc
        if not isinstance(raw, dict) or not all(
            value is None or isinstance(value, bool) for value in raw.values()
        ):
            raise _refuse(
                "subject_untrusted",
                f"{trust_path} is not an object of true/false/null values — Pi refuses it too",
            )
        entries = raw
    current = checkout.resolve()
    nearest: bool | None = None
    while nearest is None:
        nearest = entries.get(str(current))
        if nearest is True:
            return f"trusted_by={current}"
        if current.parent == current:
            break
        current = current.parent
    if nearest is None:
        # No boolean on the walk: Pi consults the global default before prompting.
        settings = _read_json_object(agent_dir / "settings.json") or {}
        if settings.get("defaultProjectTrust") == "always":
            return "trusted_by=defaultProjectTrust"
    raise _refuse(
        "subject_untrusted",
        f"{checkout} is not trusted in {trust_path} — a benchmark session cannot answer Pi's "
        f"trust prompt. Run `pi` in the checkout once and choose Trust, or set "
        f'`"defaultProjectTrust": "always"` in {agent_dir / "settings.json"}',
    )


def _probe_version(argv: Sequence[str], *, cwd: Path, label: str) -> str:
    try:
        proc = run_captured(argv, cwd=cwd, timeout=_PROBE_TIMEOUT_S)
    except ProcFailure as exc:
        raise _refuse("subject_probe_failed", f"subject {label}: {exc}") from exc
    if proc.returncode != 0:
        raise _refuse(
            "subject_probe_failed",
            f"subject {label}: {' '.join(argv)} exited {proc.returncode}: "
            f"{proc.stderr.strip() or proc.stdout.strip()}",
        )
    return proc.stdout.strip()


def _installed_version(package_root: Path) -> str | None:
    """The ``version`` of an installed package's ``package.json`` (``None`` when absent or
    malformed — a best-effort read that never refuses)."""
    manifest = _read_json_object(package_root / "package.json")
    if manifest is None:
        return None
    version = manifest.get("version")
    return version if isinstance(version, str) else None


def consumer_packages(checkout: Path) -> dict[str, str | None]:
    """Each dependency name in ``.pi/npm/package.json`` → its installed version (or ``None``)."""
    manifest = _read_json_object(checkout / ".pi" / "npm" / "package.json") or {}
    dependencies = manifest.get("dependencies")
    if not isinstance(dependencies, dict):
        return {}
    node_modules = checkout / ".pi" / "npm" / "node_modules"
    return {
        name: _installed_version(node_modules / name)
        for name in dependencies
        if isinstance(name, str)
    }


def sdk_copies(checkout: Path) -> tuple[SdkCopy, ...]:
    """Every SDK package copy under ``.pi/npm/node_modules`` and the checkout-root
    ``node_modules`` (both roots probed for every name; only hits are recorded)."""
    roots = (checkout / ".pi" / "npm" / "node_modules", checkout / "node_modules")
    copies: list[SdkCopy] = []
    for name in SDK_PACKAGE_NAMES:
        for root in roots:
            package_root = root / name
            if package_root.is_dir():
                copies.append(
                    SdkCopy(
                        name=name, root=str(package_root), version=_installed_version(package_root)
                    )
                )
    return tuple(copies)


def stamp_subject(subject: Subject, *, pi_path: str, node_path: str) -> SubjectStamp:
    """Record a subject's provenance — every probe refuses before any sample is spawned.

    ``git.head_commit`` returning ``None`` (an unborn head) or raising (not a repository) and
    any failing version probe are ``subject_probe_failed``; the agent dir comes from
    ``launch_pi_agent_dir(checkout)`` (the ONE precedence implementation perk's own launches
    use); an unresolvable dir, a broken config, or no trust is ``subject_untrusted``.
    """
    checkout = subject.checkout
    try:
        head = git.head_commit(checkout)
        dirty = git.is_dirty(checkout)
    except git.GitError as exc:
        raise _refuse(
            "subject_probe_failed",
            f"subject {subject.label}: {checkout} is not a git checkout ({exc})",
        ) from exc
    if head is None:
        raise _refuse(
            "subject_probe_failed",
            f"subject {subject.label}: {checkout} has no commits (unborn HEAD)",
        )
    perk_version = _probe_version(
        (str(subject.executable), "--version"), cwd=checkout, label=subject.label
    )
    pi_version = _probe_version((pi_path, "--version"), cwd=checkout, label=subject.label)
    node_version = _probe_version((node_path, "--version"), cwd=checkout, label=subject.label)
    try:
        resolution = launch_pi_agent_dir(checkout)
    except (ConfigError, ValueError) as exc:  # tomllib.TOMLDecodeError is a ValueError
        raise _refuse(
            "subject_untrusted",
            f"subject {subject.label}: cannot resolve the Pi agent dir from {checkout} ({exc})",
        ) from exc
    if resolution is None:
        raise _refuse(
            "subject_untrusted",
            f"subject {subject.label}: no Pi agent dir is resolvable (no home directory)",
        )
    trusted_by = check_trust(checkout, resolution.path)
    return SubjectStamp(
        head=head,
        dirty=dirty,
        perk_version=perk_version,
        pi_version=pi_version,
        pi_path=os.path.realpath(pi_path),
        node_version=node_version,
        packages=consumer_packages(checkout),
        sdk_copies=sdk_copies(checkout),
        agent_dir=str(resolution.path),
        agent_dir_source=resolution.source,
        trusted_by=trusted_by,
    )
