"""The PATH ``pi`` host probe and its pure admission decision (contracts.md §8.76).

One home for both consumers of the Pi floor: the launch preflight in ``perk.run.pi_exec``
(refuses a non-admitted host before any exec-phase side effect) and the ``pi`` environment row in
``perk.convergence.env`` (reports the same requirement through ``perk init`` / ``perk doctor``).

The decision is split from the I/O so it is testable without a process:

- ``admit_pi_version`` is **pure** — the ``pi --version`` stdout against the floor →
  ``admitted`` / ``unsupported`` (parses, below the floor — a prerelease of the floor triple
  included) / ``unverifiable`` (not a version).
- ``probe_pi_host`` is the **only** I/O — one bounded ``pi --version`` spawn through
  ``run_captured``; a timeout, a spawn failure, a non-zero exit or undecodable output are
  ``unverifiable``. It never
  raises, never touches the network, never installs, never mutates the environment.

The admission reads only the PATH CLI's own answer: it never consults ``package.json``,
``node_modules`` or a loaded SDK — those are independent observations, and equality between them
is never required (a CLI ``1.0.0`` beside a ``0.99.2`` dev SDK pin is admitted on the CLI's own
reading).
"""

from dataclasses import dataclass
from typing import Literal

from perk.substrate.host_floor import load_host_floor, required_pi_version
from perk.substrate.proc import ProcFailure, run_captured
from perk.substrate.semver import Semver, parse_semver, satisfies_floor

PI_NPM_SPEC = "@earendil-works/pi-coding-agent"
PI_INSTALL_COMMAND = f"npm install -g {PI_NPM_SPEC}"
# `pi --version` answers before any extension/settings load (well under a second measured); the
# generous bound only catches a wedged binary, which reads as unverifiable.
PI_VERSION_PROBE_TIMEOUT = 20

_DETAIL_PREVIEW_CHARS = 80

PiHostOutcome = Literal["admitted", "unsupported", "unverifiable"]
PiRefusalErrorType = Literal["pi_version_unsupported", "pi_version_unverifiable"]


@dataclass(frozen=True)
class PiHost:
    """One admission decision about the PATH ``pi`` executable.

    ``observed`` is the parsed version's canonical text (``None`` when unverifiable);
    ``required`` is the floor's text; ``detail`` is the unverifiable reason (``""`` otherwise).
    """

    executable: str
    outcome: PiHostOutcome
    observed: str | None
    required: str
    detail: str


def admit_pi_version(executable: str, stdout: str, floor: Semver) -> PiHost:
    """Decide admission from ``pi --version``'s stdout (pure)."""
    stripped = stdout.strip()
    observed = parse_semver(stripped)
    if observed is None:
        preview = stripped[:_DETAIL_PREVIEW_CHARS]
        return PiHost(
            executable=executable,
            outcome="unverifiable",
            observed=None,
            required=str(floor),
            detail=f"pi --version printed {preview!r} instead of a version",
        )
    return PiHost(
        executable=executable,
        outcome="admitted" if satisfies_floor(observed, floor) else "unsupported",
        observed=str(observed),
        required=str(floor),
        detail="",
    )


def _unverifiable(executable: str, floor: Semver, detail: str) -> PiHost:
    return PiHost(
        executable=executable,
        outcome="unverifiable",
        observed=None,
        required=str(floor),
        detail=detail,
    )


def probe_pi_host(executable: str, floor: Semver | None = None) -> PiHost:
    """Run ``<executable> --version`` once (bounded) and decide admission. Never raises.

    ``floor`` defaults to the bundled host floor's Pi entry (a corrupt bundle raises
    ``HostFloorError`` from the accessor — that is a broken install, not a host verdict).
    """
    if floor is None:
        floor = required_pi_version(load_host_floor())
    try:
        result = run_captured([executable, "--version"], timeout=PI_VERSION_PROBE_TIMEOUT)
    except ProcFailure as exc:
        if exc.kind == "timeout":
            detail = f"pi --version timed out after {PI_VERSION_PROBE_TIMEOUT} s"
        else:
            detail = f"pi --version could not run: {exc.cause_text}"
        return _unverifiable(executable, floor, detail)
    except UnicodeDecodeError:
        # The capture wrapper decodes both streams strictly; a broken binary's undecodable output
        # is a host verdict, not a crash of the launch / init / doctor paths.
        return _unverifiable(executable, floor, "pi --version printed output that is not UTF-8")
    if result.returncode != 0:
        stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
        last = stderr_lines[-1].strip() if stderr_lines else "(no output)"
        return _unverifiable(executable, floor, f"pi --version exited {result.returncode}: {last}")
    return admit_pi_version(executable, result.stdout, floor)


def format_pi_refusal(host: PiHost) -> str:
    """The human refusal text for a non-admitted host (executable, version, floor, repair)."""
    if host.outcome == "unsupported":
        return (
            f"pi at {host.executable} is version {host.observed}; perk requires Pi >= "
            f"{host.required}. Upgrade it: {PI_INSTALL_COMMAND} — perk init and perk doctor "
            "report the same requirement."
        )
    return (
        f"could not verify the Pi version of {host.executable} ({host.detail}); perk requires "
        f"Pi >= {host.required}. Reinstall it: {PI_INSTALL_COMMAND}."
    )


def pi_refusal_error_type(host: PiHost) -> PiRefusalErrorType:
    """The typed error code for a non-admitted host."""
    if host.outcome == "unsupported":
        return "pi_version_unsupported"
    return "pi_version_unverifiable"
