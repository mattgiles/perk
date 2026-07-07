"""Click context DI.

The context is built **cheaply** (cwd only) by the root group, so non-repo commands
(``--version``, ``init``, ``registry``, ``state``) work outside a git repo; ``require_*``
resolves and caches lazily and raises a clean ``UserFacingCliError`` when a dependency is
missing. (git ops are stateless module functions over the repo root, so ``require_repo``
*is* the git binding — there is no separate ``require_git``.)
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import click

from perk import github
from perk.cli.ensure import UserFacingCliError
from perk.github import AuthStatus
from perk.substrate import git
from perk.substrate.config import Config, ConfigError, load_config


@dataclass
class PerkContext:
    """Lazily-resolved CLI dependencies, hung off ``ctx.obj``."""

    cwd: Path
    _repo_root: Path | None = None
    _config: Config | None = None
    _repo_resolved: bool = False

    @classmethod
    def for_test(
        cls,
        *,
        cwd: Path | None = None,
        repo_root: Path | None = None,
        config: Config | None = None,
    ) -> Self:
        """Construct a context with injected fakes (tests). Marks the repo as resolved."""
        return cls(
            cwd=cwd or Path.cwd(),
            _repo_root=repo_root,
            _config=config,
            _repo_resolved=True,
        )

    def repo_root(self) -> Path:
        """The git repo root (discovered + cached lazily). Raises outside a repo.

        A method, not a property: the first call shells ``git`` (does I/O).
        """
        if not self._repo_resolved:
            self._repo_root = git.repo_root(self.cwd)
            self._repo_resolved = True
        if self._repo_root is None:
            raise UserFacingCliError(
                "Not a git repository\nRun this command from inside a git repository.",
                error_type="not_a_repo",
            )
        return self._repo_root

    def config(self) -> Config:
        """The loaded perk config (lazily). Translates malformed TOML and an ill-typed value
        (``ConfigError``, carrying the pydantic field path) to clean errors."""
        if self._config is None:
            try:
                self._config = load_config(self.repo_root())
            except tomllib.TOMLDecodeError as exc:
                raise UserFacingCliError(
                    f".perk/config.toml is not valid TOML ({exc})\nFix it, then re-run."
                ) from exc
            except ConfigError as exc:
                raise UserFacingCliError(
                    f".perk config invalid: {exc}\n"
                    "Fix it, then re-run (perk doctor pinpoints the field)."
                ) from exc
        return self._config


def _perk(ctx: click.Context) -> PerkContext:
    if not isinstance(ctx.obj, PerkContext):
        raise UserFacingCliError("internal error: CLI context not initialized")
    return ctx.obj


def require_repo(ctx: click.Context) -> Path:
    """The git repo root for this invocation (narrowed + checked)."""
    return _perk(ctx).repo_root()


def require_config(ctx: click.Context) -> Config:
    """The loaded perk config for this invocation."""
    return _perk(ctx).config()


def require_github(ctx: click.Context) -> AuthStatus:
    """Strict GitHub binding for commands that *need* a working GitHub.

    ``init``/``doctor`` instead call ``github.check_*`` directly to *report* (non-fatal).
    """
    _perk(ctx)  # ensure this is a properly-initialized perk command context
    auth = github.check_auth()
    if not auth.ok:
        raise UserFacingCliError(
            "GitHub not authenticated\nRun: gh auth login",
            error_type="github_unauthed",
        )
    return auth
