"""GitHub repo-identity read (verification-only; contracts.md §8.4).

One ``gh repo view`` read returning the repo's canonical GitHub identity (name + https url +
default branch) in a single shot — the inputs the repo-authored-skills substrate needs to declare
a self-referential manifest source. GitHub-only by construction: ``gh repo view`` resolves only a
GitHub remote.
"""

from dataclasses import dataclass
from pathlib import Path

from perk.github import _exec


@dataclass(frozen=True)
class RepoIdentity:
    """The repo's canonical GitHub identity (one ``gh repo view`` read)."""

    name: str
    url: str
    default_branch: str


def repo_identity(repo_root: Path) -> RepoIdentity:
    """Resolve the repo's GitHub identity (name + url + default branch). Raises ``GitHubError``.

    GitHub-only by construction: ``gh repo view`` only resolves a GitHub remote, so a non-GitHub
    (or remote-less) repo exits non-zero → ``GitHubError``. A successful payload missing any of
    the three required fields is also a ``GitHubError`` (a clear, structured failure rather than a
    silent partial identity).
    """
    proc = _exec._run(["repo", "view", "--json", "name,url,defaultBranchRef"], cwd=repo_root)
    if proc.returncode != 0:
        raise _exec._failed(proc, "failed to resolve the GitHub repo")
    data = _exec._parse_json(proc, source="`gh repo view`")
    if not isinstance(data, dict):
        raise _exec.GitHubError(f"unexpected `gh repo view` payload: {data!r}")
    name = _exec._opt_str(data.get("name"))
    url = _exec._opt_str(data.get("url"))
    branch_ref = _exec._opt_dict(data.get("defaultBranchRef"))
    default_branch = _exec._opt_str(branch_ref.get("name")) if branch_ref is not None else None
    if not name or not url or not default_branch:
        raise _exec.GitHubError(f"`gh repo view` returned an incomplete identity: {data!r}")
    return RepoIdentity(name=name, url=url, default_branch=default_branch)
