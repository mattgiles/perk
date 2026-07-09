"""The hunk-CLI gesture (`ensure_review_cli`) + doctor's `review-cli` check.

The gesture is best-effort and unconditional: it installs the global `hunkdiff` binary whenever
the binary is absent — regardless of the `[providers] review` selection (it reads no config) —
and degrades an install failure to a warning carrying the manual hint. Patches land on the names
where they are looked up (`perk.convergence.init.review_cli`'s `hunk_cli_present` binding;
`perk.substrate.npm.install_global`, resolved via the `npm` module attribute at call time).
"""

from pathlib import Path

from perk.convergence import init as init_mod
from perk.convergence.doctor.checks import _review_cli_check
from perk.convergence.init import review_cli
from perk.substrate import npm

HINT = "npm i -g hunkdiff (or brew install hunk)"


def _seed_config(root: Path, body: str) -> None:
    cfg_dir = root / ".perk"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.toml").write_text(body, encoding="utf-8")


def _record_installs(monkeypatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(npm, "install_global", lambda spec, **kw: calls.append(spec))
    return calls


# --- ensure_review_cli ------------------------------------------------------------------------


def test_absent_binary_installs_once(tmp_path, monkeypatch):
    calls = _record_installs(monkeypatch)
    monkeypatch.setattr(review_cli, "hunk_cli_present", lambda: False)
    changes, warnings = review_cli.ensure_review_cli(tmp_path)
    assert calls == ["hunkdiff"]
    assert changes == ["hunk CLI: installed hunkdiff (npm -g)"]
    assert warnings == []


def test_present_binary_is_a_no_op(tmp_path, monkeypatch):
    calls = _record_installs(monkeypatch)
    monkeypatch.setattr(review_cli, "hunk_cli_present", lambda: True)
    assert review_cli.ensure_review_cli(tmp_path) == ([], [])
    assert calls == []


def test_non_hunk_selection_still_installs(tmp_path, monkeypatch):
    # The gesture ignores the [providers] review selection — hunk converges unconditionally.
    calls = _record_installs(monkeypatch)
    monkeypatch.setattr(review_cli, "hunk_cli_present", lambda: False)
    _seed_config(tmp_path, '[providers]\nreview = "plannotator-review"\n')
    changes, _warnings = review_cli.ensure_review_cli(tmp_path)
    assert calls == ["hunkdiff"]
    assert changes == ["hunk CLI: installed hunkdiff (npm -g)"]


def test_install_failure_degrades_to_a_warning(tmp_path, monkeypatch):
    # NpmError never propagates — the gesture returns one warning carrying the manual hint.
    def _boom(spec, **kw):
        raise npm.NpmError("npm exploded")

    monkeypatch.setattr(npm, "install_global", _boom)
    monkeypatch.setattr(review_cli, "hunk_cli_present", lambda: False)
    changes, warnings = review_cli.ensure_review_cli(tmp_path)
    assert changes == []
    assert len(warnings) == 1
    assert HINT in warnings[0]


def test_malformed_config_still_installs(tmp_path, monkeypatch):
    # The gesture reads no config, so a malformed committed TOML cannot gate it — the old
    # fail-toward-no-mutation hazard (a malformed config hiding a non-hunk selection) is gone
    # by design.
    calls = _record_installs(monkeypatch)
    monkeypatch.setattr(review_cli, "hunk_cli_present", lambda: False)
    _seed_config(tmp_path, "[providers\nreview = ")
    changes, _warnings = review_cli.ensure_review_cli(tmp_path)
    assert calls == ["hunkdiff"]
    assert changes == ["hunk CLI: installed hunkdiff (npm -g)"]


# --- doctor's review-cli check ------------------------------------------------------------------


def test_check_warns_when_hunk_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(init_mod, "hunk_cli_present", lambda: False)
    check = _review_cli_check(tmp_path)
    assert check.name == "review-cli" and check.group == "providers"
    assert check.status == "warn"
    assert check.message == "hunk CLI not found"
    assert HINT in check.remediation and "perk doctor --fix" in check.remediation


def test_check_ok_when_hunk_present(tmp_path, monkeypatch):
    monkeypatch.setattr(init_mod, "hunk_cli_present", lambda: True)
    check = _review_cli_check(tmp_path)
    assert check.status == "ok"
    assert check.message == "hunk CLI present"


def test_check_probes_under_plannotator_review_selection(tmp_path, monkeypatch):
    # The check ignores the selection — it always probes PATH.
    monkeypatch.setattr(init_mod, "hunk_cli_present", lambda: False)
    _seed_config(tmp_path, '[providers]\nreview = "plannotator-review"\n')
    check = _review_cli_check(tmp_path)
    assert check.status == "warn"
    assert check.message == "hunk CLI not found"


def test_check_probes_under_malformed_config(tmp_path, monkeypatch):
    # A malformed config no longer quiets the check — it reads no config, so it still probes.
    monkeypatch.setattr(init_mod, "hunk_cli_present", lambda: True)
    _seed_config(tmp_path, "[providers\nreview = ")
    check = _review_cli_check(tmp_path)
    assert check.status == "ok"
    assert check.message == "hunk CLI present"
