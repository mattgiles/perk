"""The GitHub issue backend: the adapter + its engagement substrate.

``GitHubIssueBackend`` (in ``.backend``) is the late-bound delegation adapter over
``perk.github``'s issue-tier module functions; the human-engagement substrate (the read-only
``gh api graphql`` queries + github-native result rows) lives in the explicit submodule
``perk.backends.github.engagement``. The resolver every issue-tier consumer goes through lives in
``perk/backends/resolve.py``.

This ``__init__`` re-exports only ``GitHubIssueBackend`` (mirroring
``perk.backends.linear.__init__``'s selective re-export); the engagement substrate is reached via
the explicit submodule, and the engagement mappers via ``perk.backends.github.backend``.
"""

from perk.backends.github.backend import GitHubIssueBackend

__all__ = ["GitHubIssueBackend"]
