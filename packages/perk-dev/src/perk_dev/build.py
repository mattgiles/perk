"""The local artifact build + smoke engine for ``perk-dev release-build``.

The local equivalent of ``release.yml``'s build jobs: build both publish surfaces and smoke
them, without publishing anything. Artifacts go to a ``TemporaryDirectory`` — a validation
command, not a producer — so the tree stays clean and a user's ``dist/`` is never clobbered.
Each step narrates via ``io_step`` (stderr); an escaping ``BuildError`` leaves the step line
dangling on purpose (the error text the CLI boundary prints below is the resolution).
"""

import json
import tempfile
from pathlib import Path

from perk.substrate import npm
from perk.substrate.output import io_step
from perk.substrate.proc import ProcFailure, run_checked


class BuildError(Exception):
    """A recoverable build failure carrying a machine ``error_type`` + human message."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


def _run(args: list[str], *, cwd: Path, timeout: int = 600) -> str:
    """Run one build/smoke tool; any failure raises ``BuildError`` (``<tool>_failed``).

    A thin translation of ``perk.substrate.proc.run_checked``'s ``ProcFailure`` into the
    domain ``BuildError`` (generous timeout — builds and ``npm ci`` are slow). npm's
    quiet-env keys are layered for every call (uv/uvx ignore them harmlessly).
    """
    tool = args[0]
    try:
        return run_checked(args, cwd=cwd, timeout=timeout, env_overlay=npm._QUIET_ENV)
    except ProcFailure as exc:
        message = (
            f"{exc.cmd} failed: {exc.stderr.strip() or exc.returncode}"
            if exc.kind == "exit"
            else str(exc)
        )
        raise BuildError(f"{tool}_failed", message) from exc


# The npm tarball's shipped surface, mirroring what `release.yml` publishes as asserted by
# `tests/test_packaging.py::test_npm_pack_lists_shipped_and_excludes_dev` (which also runs
# `verify_tarball_files` against the real pack output, so these sets cannot silently drift).
NPM_TARBALL_EXPECTED: frozenset[str] = frozenset(
    {
        "extension/index.ts",
        "shared/registry.yaml",
        "shared/bindings.yaml",
        "shared/providers.yaml",
        "shared/contracts.md",
        "shared/contracts-history.md",
        "shared/README.md",
        "shared/schemas/contracts/registry.schema.json",
        "prompts/README.md",
    }
)
# Dev-only surfaces that must never ship: (prefix, suffix) rules over the packed paths.
# `docs/` covers the whole docs tree — the Starlight site workspace and canonical docs alike.
NPM_TARBALL_FORBIDDEN_PREFIXES: tuple[str, ...] = ("extension/testing/", "agents/", "docs/")
NPM_TARBALL_FORBIDDEN_SUFFIXES: tuple[str, ...] = (".test.ts",)


def verify_tarball_files(paths: set[str]) -> None:
    """Check a packed file set against the expected/forbidden rules (pure; raises on defect)."""
    missing = sorted(NPM_TARBALL_EXPECTED - paths)
    if missing:
        raise BuildError("tarball_missing_files", f"npm tarball is missing: {', '.join(missing)}")
    forbidden = sorted(
        p
        for p in paths
        if p.startswith(NPM_TARBALL_FORBIDDEN_PREFIXES)
        or p.endswith(NPM_TARBALL_FORBIDDEN_SUFFIXES)
    )
    if forbidden:
        raise BuildError(
            "tarball_forbidden_files",
            f"npm tarball ships dev-only files: {', '.join(forbidden)}",
        )


def run_build(root: Path) -> None:
    """Build + smoke both publish surfaces locally (no publishing, no tree mutation)."""
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        with io_step("uv build --package perk"):
            try:
                _run(["uv", "build", "--package", "perk", "--out-dir", str(out_dir)], cwd=root)
            except BuildError as exc:
                raise BuildError("uv_build_failed", exc.message) from exc
            wheels = sorted(out_dir.glob("*.whl"))
            sdists = sorted(out_dir.glob("*.tar.gz"))
            if len(wheels) != 1 or len(sdists) != 1:
                raise BuildError(
                    "uv_build_failed",
                    f"expected exactly one wheel + one sdist in {out_dir}, "
                    f"got {[p.name for p in wheels + sdists]}",
                )
        wheel, sdist = wheels[0], sdists[0]
        with io_step("twine check the wheel + sdist"):
            try:
                _run(["uvx", "twine", "check", str(wheel), str(sdist)], cwd=root)
            except BuildError as exc:
                raise BuildError("twine_check_failed", exc.message) from exc
        with io_step("smoke `perk --help` from the built wheel"):
            try:
                _run(["uvx", "--from", str(wheel), "perk", "--help"], cwd=root)
            except BuildError as exc:
                raise BuildError("wheel_smoke_failed", exc.message) from exc
    with io_step("npm ci"):
        try:
            _run(["npm", "ci"], cwd=root)
        except BuildError as exc:
            raise BuildError("npm_ci_failed", exc.message) from exc
    with io_step("npm pack --dry-run + tarball file check"):
        try:
            out = _run(["npm", "pack", "--dry-run", "--json"], cwd=root)
        except BuildError as exc:
            raise BuildError("npm_pack_failed", exc.message) from exc
        try:
            data = json.loads(out)
            paths = {f["path"] for f in data[0]["files"]}
        except (json.JSONDecodeError, LookupError, TypeError) as exc:
            raise BuildError(
                "npm_pack_failed", f"could not parse `npm pack --dry-run --json` output: {exc}"
            ) from exc
        verify_tarball_files(paths)
