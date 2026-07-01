"""perk's ``@mgiles/perk`` npm-install lifecycle: status, lock, and pin-aware materialize.

pi installs a project-scope ``npm:`` package lazily and
**unlocked** at launch (``resolvePackageSources``) — a race window perk closes for its own
extension. perk owns the install end-to-end: init/doctor reconcile it
forward (install-if-absent / reinstall-if-version-mismatch, the pinned
``@mgiles/perk@{__version__}``) and the launch warms its presence pre-exec, all under an
``fcntl`` lock.
"""

import contextlib
import json
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Literal

from perk import __version__
from perk.convergence.init.settings import NPM_PACKAGE
from perk.substrate import npm

fcntl: ModuleType | None
try:
    import fcntl as _fcntl

    fcntl = _fcntl
except ImportError:  # pragma: no cover - non-POSIX (perk dev platforms are macOS/Linux)
    fcntl = None

# `@mgiles/perk`, derived from the `npm:@mgiles/perk` settings SSOT so a package-name change
# stays in lockstep with the wired entry.
_PERK_NPM_NAME = NPM_PACKAGE.removeprefix("npm:")


def _pinned_spec() -> str:
    """The exact npm spec perk installs, pinned to the running CLI."""
    return f"{_PERK_NPM_NAME}@{__version__}"


def consumer_npm_install_root(repo_root: Path) -> Path:
    """The project-scope npm install root for perk (``.pi/npm/``), matching pi's
    ``getNpmInstallRoot("project")`` = ``join(cwd, ".pi", "npm")``."""
    return repo_root / ".pi" / "npm"


def consumer_perk_package_dir(repo_root: Path) -> Path:
    """The installed location of perk's extension (``.pi/npm/node_modules/@mgiles/perk``), matching
    pi's ``getManagedNpmInstallPath`` (``<root>/node_modules/<name>``)."""
    package_dir = consumer_npm_install_root(repo_root) / "node_modules"
    for segment in _PERK_NPM_NAME.split("/"):
        package_dir = package_dir / segment
    return package_dir


def installed_perk_version(repo_root: Path) -> str | None:
    """The ``version`` of the installed ``@mgiles/perk``, or ``None``.

    Best-effort, never raises: ``None`` when the dir/file is absent or the JSON / ``version`` is
    unreadable. Mirrors pi's ``getInstalledNpmVersion``.
    """
    path = consumer_perk_package_dir(repo_root) / "package.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError, TypeError):
        # TypeError: valid JSON that is a non-dict (`[]`/`null`) — indexing it raises, but an
        # unparseable version still means "unverifiable", never a crash (the never-raises contract).
        return None


ExtensionInstallStatus = Literal["self", "absent", "present", "mismatch", "unverifiable"]


def extension_install_status(
    repo_root: Path, *, self_repo: bool
) -> tuple[ExtensionInstallStatus, str]:
    """Classify perk's ``@mgiles/perk`` npm install + a human detail string.

    pi loads perk's extension from ``consumer_perk_package_dir(repo_root)`` but installs a missing
    project-scope ``npm:`` package lazily and **unlocked** at launch. perk owns the install:

    - ``self`` — the self-repo wires the local ``..`` package, so there is no npm install.
    - ``absent`` — the package dir does not exist; pi would lazy-install it (the race window).
    - ``present`` — the installed version equals the pinned ``__version__``.
    - ``mismatch`` — the installed version differs from the pinned ``__version__``.
    - ``unverifiable`` — the dir is present but its ``version`` is unreadable; never a silent pass.
    """
    if self_repo:
        return "self", "self-repo uses the local '..' package — no npm install"
    if not consumer_perk_package_dir(repo_root).is_dir():
        return (
            "absent",
            "perk installs the pinned @mgiles/perk pre-launch (pi lazy-installs as fallback)",
        )
    installed = installed_perk_version(repo_root)
    if installed is None:
        return "unverifiable", "installed @mgiles/perk package.json version unreadable"
    if installed == __version__:
        return "present", installed
    return "mismatch", f"installed @mgiles/perk {installed} != pinned {__version__}"


@contextlib.contextmanager
def _extension_install_lock(repo_root: Path) -> Iterator[None]:
    """Hold an exclusive cross-process lock while materializing perk's npm install.

    Acquires ``fcntl.flock(LOCK_EX)`` on ``<repo_root>/.pi/npm/.perk-npm-install.lock``. The lock
    lives in the install **root** (``.pi/npm/``, already gitignored) so a ``node_modules`` wipe
    never removes it. On a platform without ``fcntl`` (non-POSIX), degrades to a no-op lock
    (best-effort; perk's supported dev platforms are macOS/Linux).
    """
    root = consumer_npm_install_root(repo_root)
    root.mkdir(parents=True, exist_ok=True)
    if fcntl is None:  # pragma: no cover - non-POSIX
        yield
        return
    lock_path = root / ".perk-npm-install.lock"
    with lock_path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _install_perk_extension(repo_root: Path) -> None:
    """Install the pinned ``@mgiles/perk@{__version__}`` into ``.pi/npm/`` (raises ``NpmError``).

    The single install primitive both ``materialize_extension_install`` and
    ``ensure_extension_install_present`` drive (and the stub overrides in tests).
    """
    root = consumer_npm_install_root(repo_root)
    root.mkdir(parents=True, exist_ok=True)
    npm.install(_pinned_spec(), prefix=root)


def materialize_extension_install(repo_root: Path, *, self_repo: bool) -> str | None:
    """Materialize perk's ``@mgiles/perk`` npm install, under a cross-process lock.

    The full version used by init/doctor: re-checks ``extension_install_status`` under the lock and
    converges the install forward — install-if-``absent`` / reinstall-if-``mismatch`` (the pinned
    ``@mgiles/perk@{__version__}``), no-op otherwise. Best-effort + **non-fatal**: an ``NpmError``
    (network / not-yet-published pin) is swallowed and reported in the returned message, never
    raised — init/doctor and especially a launch must not fail on it. Returns a human-readable
    change line **only when it actually changed something**; ``None`` for a genuine no-op
    (``self`` / ``present`` / ``unverifiable``) so a converged re-run reports no change.
    """
    if self_repo:
        return None
    rel = consumer_perk_package_dir(repo_root).relative_to(repo_root)
    with _extension_install_lock(repo_root):
        status, _detail = extension_install_status(repo_root, self_repo=self_repo)
        try:
            if status == "absent":
                _install_perk_extension(repo_root)
                return f"{rel}: installed @mgiles/perk@{__version__} (perk-owned)"
            if status == "mismatch":
                old = installed_perk_version(repo_root)
                _install_perk_extension(repo_root)
                return f"{rel}: reinstalled @mgiles/perk@{__version__} (was {old})"
            # present / unverifiable: leave a present install for pi to load — a genuine no-op.
            return None
        except npm.NpmError as exc:
            return f"{rel}: @mgiles/perk install failed (non-fatal): {exc}"


def ensure_extension_install_present(repo_root: Path, *, self_repo: bool) -> str | None:
    """Cheap launch hot-path guarantee that perk's ``@mgiles/perk`` install **exists** (no version).

    ``self_repo`` → ``None``. If the package dir already exists → ``None`` fast (**no network, no
    version check**) — the norm after init/doctor. Else, under the lock, **re-check** ``is_dir()``
    (double-checked locking so concurrent launches install exactly once) and install if still
    absent. An ``NpmError`` is swallowed (returns ``None``, non-fatal). Returns a change line only
    when it actually installed. Shares the lock + install primitive with
    ``materialize_extension_install``.
    """
    if self_repo:
        return None
    pkg_dir = consumer_perk_package_dir(repo_root)
    if pkg_dir.is_dir():
        return None
    rel = pkg_dir.relative_to(repo_root)
    with _extension_install_lock(repo_root):
        if pkg_dir.is_dir():  # double-checked: a racing launch already installed it
            return None
        try:
            _install_perk_extension(repo_root)
        except npm.NpmError:
            return None
        return f"{rel}: installed @mgiles/perk@{__version__} pre-launch (perk-owned)"
