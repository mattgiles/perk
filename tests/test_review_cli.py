"""The review seam's hunk-CLI gesture (`ensure_review_cli`) + doctor's `review-cli` check.

The gesture is best-effort and selection-aware: it installs the global `hunkdiff` binary only when
the resolved review provider is `hunk` and the binary is absent, degrades an install failure to a
warning carrying the manual hint, and fails toward NO mutation on any config/providers load
failure. Patches land on the names where they are looked up (`perk.convergence.init.review_cli`'s
`hunk_cli_present` binding; `perk.substrate.npm.install_global`, resolved via the `npm` module
attribute at call time).
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


def test_hunk_resolved_and_absent_installs_once(tmp_path, monkeypatch):
    # The zero-config default resolves to `hunk`; an absent binary triggers the global install.
    calls = _record_installs(monkeypatch)
    monkeypatch.setattr(review_cli, "hunk_cli_present", lambda: False)
    changes, warnings = review_cli.ensure_review_cli(tmp_path)
    assert calls == ["hunkdiff"]
    assert changes == ["hunk CLI: installed hunkdiff (npm -g)"]
    assert warnings == []


def test_hunk_resolved_and_present_is_a_no_op(tmp_path, monkeypatch):
    calls = _record_installs(monkeypatch)
    monkeypatch.setattr(review_cli, "hunk_cli_present", lambda: True)
    assert review_cli.ensure_review_cli(tmp_path) == ([], [])
    assert calls == []


def test_non_hunk_selection_never_installs(tmp_path, monkeypatch):
    calls = _record_installs(monkeypatch)
    monkeypatch.setattr(review_cli, "hunk_cli_present", lambda: False)
    _seed_config(tmp_path, '[providers]\nreview = "plannotator-review"\n')
    assert review_cli.ensure_review_cli(tmp_path) == ([], [])
    assert calls == []


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


def test_malformed_config_fails_toward_no_mutation(tmp_path, monkeypatch):
    # A malformed committed TOML could hide a non-hunk selection — never install on it.
    calls = _record_installs(monkeypatch)
    monkeypatch.setattr(review_cli, "hunk_cli_present", lambda: False)
    _seed_config(tmp_path, "[providers\nreview = ")
    assert review_cli.resolved_review_provider_id(tmp_path) is None
    assert review_cli.ensure_review_cli(tmp_path) == ([], [])
    assert calls == []


# --- doctor's review-cli check ------------------------------------------------------------------


def test_check_warns_when_hunk_resolved_and_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(init_mod, "hunk_cli_present", lambda: False)
    check = _review_cli_check(tmp_path)
    assert check is not None
    assert check.name == "review-cli" and check.group == "providers"
    assert check.status == "warn"
    assert check.message == "hunk CLI not found"
    assert HINT in check.remediation and "perk doctor --fix" in check.remediation


def test_check_ok_when_hunk_present(tmp_path, monkeypatch):
    monkeypatch.setattr(init_mod, "hunk_cli_present", lambda: True)
    check = _review_cli_check(tmp_path)
    assert check is not None
    assert check.status == "ok"
    assert check.message == "hunk CLI present"


def test_check_ok_not_required_when_plannotator_review_selected(tmp_path, monkeypatch):
    # A non-hunk selection never probes PATH — the CLI is simply not required.
    monkeypatch.setattr(init_mod, "hunk_cli_present", lambda: False)
    _seed_config(tmp_path, '[providers]\nreview = "plannotator-review"\n')
    check = _review_cli_check(tmp_path)
    assert check is not None
    assert check.status == "ok"
    assert check.message == "review surface: plannotator-review (hunk CLI not required)"


def test_check_quiet_none_when_config_unresolvable(tmp_path):
    # The config check owns a malformed TOML; the review-cli check stays quiet (None).
    _seed_config(tmp_path, "[providers\nreview = ")
    assert _review_cli_check(tmp_path) is None
