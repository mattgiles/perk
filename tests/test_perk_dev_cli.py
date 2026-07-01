"""`perk-dev` CLI regression tests.

`perk-dev` is a dev-only workspace member that reuses perk's version-reading (`perk.__version__`)
and git/LBYL helpers. These drive its CLI through Click's `CliRunner` to prove the cross-package
reuse wiring resolves: both `smoke` and `--version` report perk's own version.
"""

from click.testing import CliRunner
from perk_dev.cli import cli

from perk import __version__


def test_smoke_reports_perk_version():
    result = CliRunner().invoke(cli, ["smoke"])
    assert result.exit_code == 0, result.output
    assert __version__ in result.output


def test_version_reuses_perk_version():
    # `perk-dev --version` reuses `perk.__version__` (the version-reading reuse seam).
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0, result.output
    assert __version__ in result.output


def test_smoke_is_registered():
    assert "smoke" in cli.commands
