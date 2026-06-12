"""Auth + repo-access verification reads (contracts.md §8.4 — never mutates)."""

from dataclasses import dataclass
from pathlib import Path

from perk.github import _exec

_PUSH_PERMISSIONS = frozenset({"WRITE", "MAINTAIN", "ADMIN"})


@dataclass(frozen=True)
class AuthStatus:
    """`gh auth status` result (§8.4 ``check_auth`` shape)."""

    ok: bool
    user: str | None
    scopes: tuple[str, ...]
    error: str | None


@dataclass(frozen=True)
class RepoAccess:
    """`gh repo view` result (§8.4 ``check_repo_access`` shape)."""

    ok: bool
    repo: str | None
    can_push: bool
    error: str | None

    @classmethod
    def skipped(cls) -> "RepoAccess":
        """Used when auth failed, so repo access was not checked."""
        return cls(ok=False, repo=None, can_push=False, error="skipped (not authenticated)")


def _parse_scopes(text: str) -> tuple[str, ...]:
    """Pull scopes from a ``gh auth status`` "Token scopes:" line (best-effort)."""
    for line in text.splitlines():
        if "Token scopes:" in line:
            raw = line.split("Token scopes:", 1)[1]
            return tuple(s.strip().strip("'\"") for s in raw.split(",") if s.strip())
    return ()


def check_auth() -> AuthStatus:
    """Verify GitHub authentication. Never mutates."""
    status = _exec._run(["auth", "status"])
    if status.returncode != 0:
        return AuthStatus(
            ok=False, user=None, scopes=(), error=(status.stderr or status.stdout).strip()
        )
    scopes = _parse_scopes(status.stdout + status.stderr)
    user_proc = _exec._run(["api", "user", "--jq", ".login"])
    user = user_proc.stdout.strip() if user_proc.returncode == 0 else None
    return AuthStatus(ok=True, user=user or None, scopes=scopes, error=None)


def check_repo_access(repo_root: Path) -> RepoAccess:
    """Verify the repo is readable/pushable for the authed user. Never mutates."""
    proc = _exec._run(["repo", "view", "--json", "nameWithOwner,viewerPermission"], cwd=repo_root)
    if proc.returncode != 0:
        return RepoAccess(
            ok=False, repo=None, can_push=False, error=proc.stderr.strip() or "no GitHub repo"
        )
    data = _exec._parse_json(proc, source="`gh repo view`")
    if not isinstance(data, dict):
        raise _exec.GitHubError(f"unexpected `gh repo view` payload: {data!r}")
    permission = data.get("viewerPermission")
    return RepoAccess(
        ok=True,
        repo=data.get("nameWithOwner"),
        can_push=permission in _PUSH_PERMISSIONS,
        error=None,
    )
