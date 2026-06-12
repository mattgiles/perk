"""`perk state prune` command tests (CliRunner).

Click 8.4.1 has no ``mix_stderr`` (human lines go to stderr, the ``--json`` payload to stdout):
the runner mixes streams, so parse the *last* stdout line for the JSON payload.
"""

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from click.testing import CliRunner
from ulid import ULID

from perk.cli.cli import cli
from perk.state import cache


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _ulid_at(days_ago: float) -> str:
    return str(ULID.from_datetime(datetime.now(UTC) - timedelta(days=days_ago)))


def _last_json(result):
    return json.loads(result.output.strip().splitlines()[-1])


def test_dry_run_leaves_files_and_reports_would_prune():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        root = Path(d)
        rid = _ulid_at(20)
        cache.write_scratch(root, rid, "x", "y")
        result = runner.invoke(cli, ["state", "prune", "--dry-run", "--json"])
        assert result.exit_code == 0
        payload = _last_json(result)
        assert payload["dry_run"] is True
        assert [c["run_id"] for c in payload["pruned"]] == [rid]
        assert cache.run_scratch_dir(root, rid).is_dir()  # nothing deleted


def test_real_run_deletes_and_payload_shape():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        root = Path(d).resolve()  # git repo_root resolves symlinks (/var → /private/var)
        rid = _ulid_at(0)
        cache.write_scratch(root, rid, "x", "y")
        cache.write_handoff(root, rid, {"stage": "learn"})
        cache.mark_handoff_consumed(root, rid)
        result = runner.invoke(cli, ["state", "prune", "--json"])
        assert result.exit_code == 0
        payload = _last_json(result)
        assert payload == {
            "success": True,
            "error_type": None,
            "dry_run": False,
            "max_age_days": 14,
            "pruned": [
                {
                    "run_id": rid,
                    "reason": "terminal stage completed",
                    "run_dir": str(cache.run_scratch_dir(root, rid)),
                    "handoff": str(cache.handoff_path(root, rid)),
                }
            ],
            "kept": 0,
            "errors": [],
        }
        assert not cache.run_scratch_dir(root, rid).exists()
        assert not cache.handoff_path(root, rid).exists()


def test_max_age_zero_prunes_fresh_warm_dir():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        root = Path(d)
        rid = _ulid_at(0)
        cache.write_scratch(root, rid, "x", "y")
        result = runner.invoke(cli, ["state", "prune", "--max-age-days", "0", "--json"])
        assert result.exit_code == 0
        payload = _last_json(result)
        assert [c["run_id"] for c in payload["pruned"]] == [rid]
        assert not cache.run_scratch_dir(root, rid).exists()


def test_outside_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["state", "prune", "--json"])
        assert result.exit_code == 2
        assert _last_json(result)["error_type"] == "not_a_repo"


def test_alias_gc_dispatches():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["state", "gc", "--dry-run", "--json"])
        assert result.exit_code == 0
        assert _last_json(result)["dry_run"] is True
