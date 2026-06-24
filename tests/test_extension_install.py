import json
import threading
import time
from pathlib import Path

import pytest

from perk import __version__
from perk.convergence import init as init_mod
from perk.convergence.init import extension_install as _ext_install


def _plant_install(root, version):
    pkg = init_mod.consumer_perk_package_dir(root)
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")


# --- status classification ------------------------------------------------------------


def test_status_self_repo(tmp_path):
    status, _ = init_mod.extension_install_status(tmp_path, self_repo=True)
    assert status == "self"


def test_status_absent(tmp_path):
    status, _ = init_mod.extension_install_status(tmp_path, self_repo=False)
    assert status == "absent"


def test_status_present(tmp_path):
    _plant_install(tmp_path, __version__)
    status, detail = init_mod.extension_install_status(tmp_path, self_repo=False)
    assert status == "present"
    assert detail == __version__


def test_status_mismatch(tmp_path):
    _plant_install(tmp_path, "0.0.0")
    status, detail = init_mod.extension_install_status(tmp_path, self_repo=False)
    assert status == "mismatch"
    assert "0.0.0" in detail and __version__ in detail


def test_status_unverifiable_unreadable_version(tmp_path):
    pkg = init_mod.consumer_perk_package_dir(tmp_path)
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "package.json").write_text("{ not json", encoding="utf-8")
    status, _ = init_mod.extension_install_status(tmp_path, self_repo=False)
    assert status == "unverifiable"


def test_installed_version_none_when_absent(tmp_path):
    assert init_mod.installed_perk_version(tmp_path) is None


@pytest.mark.parametrize("payload", ["[]", "null", "42", '"x"'])
def test_status_unverifiable_non_dict_json(tmp_path, payload):
    # Valid JSON that is not a dict: indexing ["version"] raises TypeError — must degrade to
    # `unverifiable`, never crash (the never-raises contract).
    pkg = init_mod.consumer_perk_package_dir(tmp_path)
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "package.json").write_text(payload, encoding="utf-8")
    assert init_mod.installed_perk_version(tmp_path) is None
    status, _ = init_mod.extension_install_status(tmp_path, self_repo=False)
    assert status == "unverifiable"


def test_npm_run_wraps_oserror_as_npmerror(monkeypatch):
    # `npm` absent from PATH raises FileNotFoundError (an OSError); _run must re-raise NpmError so
    # the best-effort callers swallow it rather than crash on a raw traceback.
    def _boom(*a, **k):
        raise FileNotFoundError("No such file or directory: 'npm'")

    monkeypatch.setattr(_ext_install.npm.subprocess, "run", _boom)
    with pytest.raises(_ext_install.npm.NpmError):
        _ext_install.npm.install("@mgiles/perk@1.0.0", prefix=Path("/tmp/x"))


def test_paths_match_pi_layout(tmp_path):
    assert init_mod.consumer_npm_install_root(tmp_path) == tmp_path / ".pi" / "npm"
    assert (
        init_mod.consumer_perk_package_dir(tmp_path)
        == tmp_path / ".pi" / "npm" / "node_modules" / "@mgiles" / "perk"
    )


# --- materialize_extension_install ----------------------------------------------------


def test_materialize_self_repo_is_noop(tmp_path, monkeypatch):
    def _boom(root):  # pragma: no cover - must not install in the self-repo
        raise AssertionError("no install in the self-repo")

    monkeypatch.setattr(_ext_install, "_install_perk_extension", _boom)
    assert init_mod.materialize_extension_install(tmp_path, self_repo=True) is None


def test_materialize_absent_installs(tmp_path, monkeypatch):
    calls: list = []

    def _install(root):
        calls.append(root)
        _plant_install(root, __version__)

    monkeypatch.setattr(_ext_install, "_install_perk_extension", _install)
    msg = init_mod.materialize_extension_install(tmp_path, self_repo=False)
    assert calls == [tmp_path]
    assert msg is not None and f"installed @mgiles/perk@{__version__}" in msg
    assert "reinstalled" not in msg


def test_materialize_mismatch_reinstalls(tmp_path, monkeypatch):
    _plant_install(tmp_path, "0.0.0")
    calls: list = []

    def _install(root):
        calls.append(root)
        _plant_install(root, __version__)

    monkeypatch.setattr(_ext_install, "_install_perk_extension", _install)
    msg = init_mod.materialize_extension_install(tmp_path, self_repo=False)
    assert calls == [tmp_path]
    assert msg is not None and "reinstalled" in msg and "was 0.0.0" in msg


def test_materialize_present_is_noop(tmp_path, monkeypatch):
    _plant_install(tmp_path, __version__)

    def _boom(root):  # pragma: no cover - present does no install
        raise AssertionError("present is a no-op")

    monkeypatch.setattr(_ext_install, "_install_perk_extension", _boom)
    assert init_mod.materialize_extension_install(tmp_path, self_repo=False) is None


def test_materialize_unverifiable_is_noop(tmp_path, monkeypatch):
    pkg = init_mod.consumer_perk_package_dir(tmp_path)
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "package.json").write_text("{ bad", encoding="utf-8")

    def _boom(root):  # pragma: no cover - unverifiable leaves the install as-is
        raise AssertionError("unverifiable is a no-op")

    monkeypatch.setattr(_ext_install, "_install_perk_extension", _boom)
    assert init_mod.materialize_extension_install(tmp_path, self_repo=False) is None


def test_materialize_swallows_npmerror(tmp_path, monkeypatch):
    def _boom(root):
        raise _ext_install.npm.NpmError("registry 404")

    monkeypatch.setattr(_ext_install, "_install_perk_extension", _boom)
    msg = init_mod.materialize_extension_install(tmp_path, self_repo=False)
    assert msg is not None
    assert "non-fatal" in msg and "registry 404" in msg


# --- ensure_extension_install_present -------------------------------------------------


def test_ensure_present_self_repo_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _ext_install, "_install_perk_extension", lambda root: pytest.fail("no install")
    )
    assert init_mod.ensure_extension_install_present(tmp_path, self_repo=True) is None


def test_ensure_present_when_installed_is_cheap_noop(tmp_path, monkeypatch):
    _plant_install(tmp_path, __version__)

    def _boom(root):  # pragma: no cover - present must not install / check version
        raise AssertionError("present install must not reinstall")

    monkeypatch.setattr(_ext_install, "_install_perk_extension", _boom)
    assert init_mod.ensure_extension_install_present(tmp_path, self_repo=False) is None


def test_ensure_present_installs_when_absent(tmp_path, monkeypatch):
    calls: list = []

    def _install(root):
        calls.append(root)
        _plant_install(root, __version__)

    monkeypatch.setattr(_ext_install, "_install_perk_extension", _install)
    msg = init_mod.ensure_extension_install_present(tmp_path, self_repo=False)
    assert calls == [tmp_path]
    assert msg is not None and "pre-launch" in msg
    # The lock file lives under .pi/npm/ (gitignored; survives a node_modules wipe).
    assert (tmp_path / ".pi" / "npm" / ".perk-npm-install.lock").is_file()


def test_ensure_present_swallows_npmerror(tmp_path, monkeypatch):
    def _boom(root):
        raise _ext_install.npm.NpmError("network down")

    monkeypatch.setattr(_ext_install, "_install_perk_extension", _boom)
    assert init_mod.ensure_extension_install_present(tmp_path, self_repo=False) is None


def test_ensure_present_two_racers_install_exactly_once(tmp_path, monkeypatch):
    # Core race regression: two concurrent invocations against an absent install serialize on the
    # flock + double-checked is_dir() so `_install_perk_extension` runs EXACTLY once.
    call_count = 0
    count_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def _slow_install(root):
        nonlocal call_count
        with count_lock:
            call_count += 1
        time.sleep(0.2)
        _plant_install(root, __version__)

    monkeypatch.setattr(_ext_install, "_install_perk_extension", _slow_install)
    results: list = []
    results_lock = threading.Lock()

    def _racer():
        barrier.wait()
        msg = init_mod.ensure_extension_install_present(tmp_path, self_repo=False)
        with results_lock:
            results.append(msg)

    threads = [threading.Thread(target=_racer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert call_count == 1  # the lock + double-checked is_dir() serialized the racers
    assert sum(1 for m in results if m is not None) == 1  # only one reports a change
    assert (tmp_path / ".pi" / "npm" / ".perk-npm-install.lock").is_file()


def test_lock_fallback_when_fcntl_none(tmp_path, monkeypatch):
    # When fcntl is unavailable (non-POSIX), the lock degrades to a no-op and materialize runs.
    monkeypatch.setattr(_ext_install, "fcntl", None)
    monkeypatch.setattr(
        _ext_install, "_install_perk_extension", lambda root: _plant_install(root, __version__)
    )
    msg = init_mod.materialize_extension_install(tmp_path, self_repo=False)
    assert msg is not None and "installed" in msg
