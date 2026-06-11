import json

import pytest

from perk import __version__
from perk.cli.ensure import UserFacingCliError
from perk.init import run_init


def _snapshot(root):
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in root.rglob("*")
        if p.is_file() and ".git/" not in p.relative_to(root).as_posix()
    }


def test_init_converges_and_is_idempotent(tmp_path):
    # tmp_path has no `[tool.perk] self` marker -> consumer mode.
    # verify=False: pure convergence (no repo/tooling/GitHub shells).
    assert run_init(tmp_path, verify=False).ok

    settings = json.loads((tmp_path / ".pi" / "settings.json").read_text())
    packages = settings["packages"]
    assert f"git:github.com/mattgiles/perk@v{__version__}" in packages
    assert "npm:@tombell/pi-status" in packages
    assert "npm:@tombell/pi-plan" not in packages  # P2.T2a: perk owns plan mode now
    assert "npm:@juicesharp/rpiv-todo" not in packages  # P2.T12: perk owns checkpoints now
    assert "npm:pi-subagents" in packages  # P2.T6: borrowed spawned-delegation engine
    assert "npm:pi-web-access" in packages  # borrowed web-research engine (#250)

    assert (tmp_path / ".pi" / "workflow" / ".gitkeep").is_file()
    # P2.T6: perk-owned agent-definitions home (committed; T7 populates it).
    assert (tmp_path / ".pi" / "agents" / ".gitkeep").is_file()
    gitignore = (tmp_path / ".gitignore").read_text()
    assert "/.pi/npm/" in gitignore
    assert "/.pi/workflow/plan-ref.json" in gitignore  # cache.plan-ref local mirror (T2b)
    assert "/.pi/workflow/plan.md" in gitignore  # cache.plan materialized body (transient, #43)
    assert "perk conventions" in (tmp_path / "AGENTS.md").read_text()

    # Idempotency: a second run changes nothing on disk.
    before = _snapshot(tmp_path)
    assert run_init(tmp_path, verify=False).ok
    after = _snapshot(tmp_path)
    assert before == after


def _identities(packages):
    """Map a `packages` list (str or object-form) to the set of package specs/sources present."""
    out = set()
    for p in packages:
        if isinstance(p, str):
            out.add(p)
        elif isinstance(p, dict) and isinstance(p.get("source"), str):
            out.add(p["source"])
    return out


def test_init_default_repo_wires_no_foreign_provider_package(tmp_path):
    # The zero-config default: both seams resolve to the `package: null` reference providers, so
    # no foreign package is added or removed — byte-identical to today's append-only output.
    assert run_init(tmp_path, verify=False).ok
    packages = json.loads((tmp_path / ".pi" / "settings.json").read_text())["packages"]
    assert "npm:@tombell/pi-plan" not in _identities(packages)
    assert "npm:@juicesharp/rpiv-todo" not in _identities(packages)
    # All entries are still plain strings (no object-form provider entries on the default path).
    assert all(isinstance(p, str) for p in packages)


def test_init_selecting_a_provider_wires_then_deselecting_removes(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    # A user hand-added package + a borrowed package present from a prior run; both must survive.
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"packages": ["npm:@me/custom", "npm:@tombell/pi-status"]}, indent=2) + "\n"
    )
    # Select the illustrative tombell-plan provider for the plan seam.
    pi_dir.joinpath("perk.toml").write_text(
        '[providers]\nplan = "tombell-plan"\n', encoding="utf-8"
    )

    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    # The foreign package is wired in OBJECT form. Node 2.3: the real tombell-plan entry has no
    # `package_filter`, so the object carries `source` only (no merged extensions/skills keys).
    entry = next(
        p for p in packages if isinstance(p, dict) and p.get("source") == "npm:@tombell/pi-plan"
    )
    assert entry == {"source": "npm:@tombell/pi-plan"}
    assert "npm:@me/custom" in _identities(packages)  # user package preserved
    assert "npm:@tombell/pi-status" in _identities(packages)  # borrowed package preserved

    # Deselect (back to the default) → the provider-managed entry is removed; others survive.
    pi_dir.joinpath("perk.toml").write_text('[providers]\nplan = "perk-plan"\n', encoding="utf-8")
    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert "npm:@tombell/pi-plan" not in _identities(packages)
    assert "npm:@me/custom" in _identities(packages)
    assert "npm:@tombell/pi-status" in _identities(packages)


def test_init_selecting_plannotator_plan_wires_then_deselecting_removes(tmp_path):
    # The augment-posture plan provider: the init wiring is selection-shape-generic, so selecting
    # `plannotator-plan` wires `npm:@plannotator/pi-extension` (object form, no filter — its
    # `pi.extensions` is the package root) and deselecting removes it; an idempotent re-run is a
    # no-op. Mirrors the tombell case — no Python source change was needed for this entry.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"packages": ["npm:@me/custom", "npm:@tombell/pi-status"]}, indent=2) + "\n"
    )
    pi_dir.joinpath("perk.toml").write_text(
        '[providers]\nplan = "plannotator-plan"\n', encoding="utf-8"
    )

    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    entry = next(
        p
        for p in packages
        if isinstance(p, dict) and p.get("source") == "npm:@plannotator/pi-extension"
    )
    assert entry == {"source": "npm:@plannotator/pi-extension"}
    assert "npm:@me/custom" in _identities(packages)  # user package preserved
    assert "npm:@tombell/pi-status" in _identities(packages)  # borrowed package preserved

    # An idempotent re-run with the selection in place changes nothing.
    before = _snapshot(tmp_path)
    assert run_init(tmp_path, verify=False).ok
    assert before == _snapshot(tmp_path)

    # Deselect (back to the default) → the provider-managed entry is removed; others survive.
    pi_dir.joinpath("perk.toml").write_text('[providers]\nplan = "perk-plan"\n', encoding="utf-8")
    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert "npm:@plannotator/pi-extension" not in _identities(packages)
    assert "npm:@me/custom" in _identities(packages)
    assert "npm:@tombell/pi-status" in _identities(packages)


def test_init_selecting_a_todo_provider_wires_then_deselecting_removes(tmp_path):
    # The todo-seam analogue (Node 3.2): the init wiring is already seam-generic, so selecting the
    # real `juicesharp-todo` provider wires `npm:@juicesharp/rpiv-todo` (object form, no filter) and
    # deselecting removes it — locking the generic behavior for the todo seam too.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"packages": ["npm:@me/custom", "npm:@tombell/pi-status"]}, indent=2) + "\n"
    )
    pi_dir.joinpath("perk.toml").write_text(
        '[providers]\ntodo = "juicesharp-todo"\n', encoding="utf-8"
    )

    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    # The real juicesharp-todo entry has no `package_filter`, so the object carries `source` only.
    entry = next(
        p
        for p in packages
        if isinstance(p, dict) and p.get("source") == "npm:@juicesharp/rpiv-todo"
    )
    assert entry == {"source": "npm:@juicesharp/rpiv-todo"}
    assert "npm:@me/custom" in _identities(packages)  # user package preserved
    assert "npm:@tombell/pi-status" in _identities(packages)  # borrowed package preserved

    # Deselect (back to the default) → the provider-managed entry is removed; others survive.
    pi_dir.joinpath("perk.toml").write_text(
        '[providers]\ntodo = "perk-checkpoints"\n', encoding="utf-8"
    )
    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert "npm:@juicesharp/rpiv-todo" not in _identities(packages)
    assert "npm:@me/custom" in _identities(packages)
    assert "npm:@tombell/pi-status" in _identities(packages)


def test_init_provider_wiring_is_idempotent(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    pi_dir.joinpath("perk.toml").write_text(
        '[providers]\nplan = "tombell-plan"\n', encoding="utf-8"
    )
    assert run_init(tmp_path, verify=False).ok
    before = _snapshot(tmp_path)
    assert run_init(tmp_path, verify=False).ok
    assert before == _snapshot(tmp_path)  # a re-run with the selection in place changes nothing


def test_init_writes_compaction_when_present(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    pi_dir.joinpath("perk.toml").write_text(
        "[compaction]\nenabled = false\nreserve_tokens = 8192\n", encoding="utf-8"
    )
    assert run_init(tmp_path, verify=False).ok
    settings = json.loads((pi_dir / "settings.json").read_text())
    assert settings["compaction"] == {"enabled": False, "reserveTokens": 8192}
    # Idempotent: a second run changes nothing on disk.
    before = _snapshot(tmp_path)
    assert run_init(tmp_path, verify=False).ok
    assert before == _snapshot(tmp_path)


def test_init_compaction_overwrites_perk_keys_preserving_others(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    # An existing settings.json `compaction` with a perk-specified key (to overwrite) and an
    # unrelated hand-added key (to preserve).
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"compaction": {"reserveTokens": 999, "customKey": 7}}, indent=2) + "\n"
    )
    pi_dir.joinpath("perk.toml").write_text(
        "[compaction]\nreserve_tokens = 8192\n", encoding="utf-8"
    )
    run_init(tmp_path, verify=False)
    compaction = json.loads((pi_dir / "settings.json").read_text())["compaction"]
    assert compaction["reserveTokens"] == 8192  # perk key overwrote
    assert compaction["customKey"] == 7  # unrelated key preserved


def test_init_compaction_absent_leaves_existing_untouched(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    # No [compaction] in perk.toml → an existing settings.json `compaction` is never touched.
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"compaction": {"reserveTokens": 999}}, indent=2) + "\n"
    )
    run_init(tmp_path, verify=False)
    compaction = json.loads((pi_dir / "settings.json").read_text())["compaction"]
    assert compaction == {"reserveTokens": 999}  # left exactly as the user set it


def test_init_preserves_user_settings(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    (pi_dir / "settings.json").write_text(
        json.dumps({"packages": ["npm:@me/custom"], "theme": "nightowl"}, indent=2) + "\n"
    )

    run_init(tmp_path, verify=False)

    settings = json.loads((pi_dir / "settings.json").read_text())
    assert "npm:@me/custom" in settings["packages"]  # user entry preserved
    assert settings["theme"] == "nightowl"  # unknown key preserved
    assert (
        f"git:github.com/mattgiles/perk@v{__version__}" in settings["packages"]
    )  # perk entry added


def test_init_migrates_legacy_npm_perk_entry(tmp_path):
    # A repo wired by an earlier perk init carries the stale `npm:@perk/pi` entry that
    # Pi can't install (never published). init must strip it (forward convergence) and
    # replace it with the git URL, without touching the user's own entries.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    (pi_dir / "settings.json").write_text(
        json.dumps({"packages": ["npm:@perk/pi@0.0.0", "npm:@me/custom"]}, indent=2) + "\n"
    )

    run_init(tmp_path, verify=False)

    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert not any(p.startswith("npm:@perk/pi") for p in packages)  # legacy entry stripped
    assert f"git:github.com/mattgiles/perk@v{__version__}" in packages  # git entry added
    assert "npm:@me/custom" in packages  # user entry preserved


def test_init_rejects_malformed_settings(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    (pi_dir / "settings.json").write_text("{not json", encoding="utf-8")
    # The operation must error, not silently clobber the user's file.
    with pytest.raises(UserFacingCliError):
        run_init(tmp_path, verify=False)
    assert (pi_dir / "settings.json").read_text() == "{not json"  # untouched


def test_init_self_mode_uses_local_path(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.perk]\nself = true\n", encoding="utf-8")
    run_init(tmp_path, verify=False)
    packages = json.loads((tmp_path / ".pi" / "settings.json").read_text())["packages"]
    assert ".." in packages
    assert not any(p.startswith("git:github.com/mattgiles/perk") for p in packages)


def test_init_writes_skills_manifest_fragment(tmp_path):
    # Consumer mode: the fragment declares the perk source pinned to the release tag and lists
    # every perk skill. The fragment is a committed declaration, never gitignored.
    run_init(tmp_path, verify=False)
    fragment = tmp_path / ".agents" / "manifest.d" / "perk.yaml"
    assert fragment.is_file()
    text = fragment.read_text(encoding="utf-8")
    assert "url: https://github.com/mattgiles/perk" in text
    assert f"ref: v{__version__}" in text
    from perk.init import PERK_SKILLS

    for name in PERK_SKILLS:
        assert f"name: {name}" in text


def test_init_self_mode_skills_manifest_tracks_main(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.perk]\nself = true\n", encoding="utf-8")
    run_init(tmp_path, verify=False)
    text = (tmp_path / ".agents" / "manifest.d" / "perk.yaml").read_text(encoding="utf-8")
    assert "ref: main" in text
    assert f"ref: v{__version__}" not in text


def test_init_preserves_user_skills_manifest(tmp_path):
    # The user's own `.agents/manifest.yaml` is never touched by perk init.
    agents = tmp_path / ".agents"
    agents.mkdir()
    user_manifest = agents / "manifest.yaml"
    original = (
        "sources:\n  me:\n    url: https://example.com/x\n    ref: main\n"
        "skills:\n  - source: me\n    name: mine\n"
    )
    user_manifest.write_text(original, encoding="utf-8")
    run_init(tmp_path, verify=False)
    assert user_manifest.read_text(encoding="utf-8") == original  # untouched
    assert (agents / "manifest.d" / "perk.yaml").is_file()  # fragment still written alongside
