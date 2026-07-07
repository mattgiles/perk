"""A thin ``npm``-shelling gateway — the install operation the extension-install lifecycle needs.

One implementation per plane (cli-vs-pi §3); shells ``npm`` via subprocess, never with
``shell=True``. Failures raise ``NpmError``; callers (the extension-install lifecycle) swallow it
as best-effort + non-fatal (an install failure never crashes init/doctor/launch). Mirrors
``perk.substrate.git``'s shape.
"""

from pathlib import Path

from perk.substrate.proc import ProcFailure, run_checked

# Quiet perk-managed npm installs (funding nags, audit advisories). loglevel=error keeps real
# install failures visible. perk's keys win (these are perk-managed installs, not a user's), so
# `_QUIET_ENV` is layered AFTER `os.environ`.
_QUIET_ENV = {
    "npm_config_loglevel": "error",
    "npm_config_fund": "false",
    "npm_config_audit": "false",
}


class NpmError(Exception):
    """An npm command exited non-zero or timed out (callers swallow it as best-effort)."""


def _run(args: list[str], *, cwd: Path | None = None, timeout: int = 300) -> str:
    # Generous timeout: `npm install` is slow on a cold cache. Any failure (timeout, npm
    # absent/unspawnable, non-zero exit) surfaces as a domain NpmError so the best-effort
    # callers swallow it, never a raw traceback.
    try:
        return run_checked(["npm", *args], cwd=cwd, timeout=timeout, env_overlay=_QUIET_ENV)
    except ProcFailure as exc:
        raise NpmError(str(exc)) from exc


def install(spec: str, *, prefix: Path, timeout: int = 300) -> None:
    """Install ``spec`` into the project-scope npm root ``prefix`` (a **network** op; ``NpmError``).

    Runs ``npm install <spec> --prefix <prefix> --legacy-peer-deps``, mirroring pi's default
    ``getNpmInstallArgs`` for the ``npm`` package manager. The install is **additive** — it adds
    ``spec`` to the shared ``<prefix>/package.json`` without disturbing other entries.
    """
    _run(["install", spec, "--prefix", str(prefix), "--legacy-peer-deps"], timeout=timeout)
