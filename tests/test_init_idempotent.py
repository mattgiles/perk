import json

import pytest

from perk import __version__
from perk.cli.ensure import UserFacingCliError
from perk.convergence.init import run_init


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
    assert "npm:@tombell/pi-diff" in packages  # surviving borrowed package (anchor)
    assert "npm:@tombell/pi-status" not in packages  # retired: footer conflict with node 3.1
    assert "npm:@tombell/pi-plan" not in packages  # P2.T2a: perk owns plan mode now
    assert "npm:@juicesharp/rpiv-todo" not in packages  # P2.T12: perk owns checkpoints now
    assert "npm:pi-subagents" in packages  # P2.T6: borrowed spawned-delegation engine
    # #529: pi-web-access is no longer borrowed — it is the `web` seam's default provider, converged
    # via the provider path (object form on a fresh init), so it still lands in `packages`.
    assert "npm:pi-web-access" in _identities(packages)

    assert (tmp_path / ".pi" / "workflow" / ".gitkeep").is_file()
    # perk-owned agent-definitions home (committed `.gitkeep`).
    assert (tmp_path / ".pi" / "agents" / ".gitkeep").is_file()
    # perk's three agent defs are delivered into the perk-owned `.pi/agents/perk/` subdir.
    from perk.convergence.init import PERK_AGENTS

    for name in PERK_AGENTS:
        assert (tmp_path / ".pi" / "agents" / "perk" / f"{name}.md").is_file()
    gitignore = (tmp_path / ".gitignore").read_text()
    assert "/.pi/npm/" in gitignore
    assert "/.pi/workflow/plan-ref.json" in gitignore  # cache.plan-ref local mirror (T2b)
    assert "/.pi/workflow/plan.md" in gitignore  # cache.plan materialized body (transient, #43)
    agents_md = (tmp_path / "AGENTS.md").read_text()
    assert "perk conventions" in agents_md
    # The managed block carries the ambient gh guidance (#416).
    assert "GitHub access goes through the `gh` CLI" in agents_md

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


def test_init_default_repo_wires_no_foreign_provider_package_except_web_default(tmp_path):
    # The zero-config default: the plan/todo/askuser/footer seams resolve to `package: null`
    # reference providers, so no foreign package is added for them. The `web` seam is the novel
    # exception (#529): its default `pi-web-access` carries a non-null package, so the default path
    # DOES converge `npm:pi-web-access` via the provider path (object form on a fresh init).
    assert run_init(tmp_path, verify=False).ok
    packages = json.loads((tmp_path / ".pi" / "settings.json").read_text())["packages"]
    assert "npm:@tombell/pi-plan" not in _identities(packages)
    assert "npm:@juicesharp/rpiv-todo" not in _identities(packages)
    assert "npm:@ollama/pi-web-search" not in _identities(packages)
    # The web default IS wired (provider-managed), in object form.
    web_entry = next(
        p for p in packages if isinstance(p, dict) and p.get("source") == "npm:pi-web-access"
    )
    assert web_entry == {"source": "npm:pi-web-access"}


def test_init_selecting_a_provider_wires_then_deselecting_removes(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    # A user hand-added package + a borrowed package present from a prior run; both must survive.
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"packages": ["npm:@me/custom", "npm:@tombell/pi-diff"]}, indent=2) + "\n"
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
    assert "npm:@tombell/pi-diff" in _identities(packages)  # borrowed package preserved

    # Deselect (back to the default) → the provider-managed entry is removed; others survive.
    pi_dir.joinpath("perk.toml").write_text('[providers]\nplan = "perk-plan"\n', encoding="utf-8")
    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert "npm:@tombell/pi-plan" not in _identities(packages)
    assert "npm:@me/custom" in _identities(packages)
    assert "npm:@tombell/pi-diff" in _identities(packages)


def test_init_selecting_plannotator_plan_wires_then_deselecting_removes(tmp_path):
    # The augment-posture plan provider: the init wiring is selection-shape-generic, so selecting
    # `plannotator-plan` wires `npm:@plannotator/pi-extension` (object form, no filter — its
    # `pi.extensions` is the package root) and deselecting removes it; an idempotent re-run is a
    # no-op. Mirrors the tombell case — no Python source change was needed for this entry.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"packages": ["npm:@me/custom", "npm:@tombell/pi-diff"]}, indent=2) + "\n"
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
    assert "npm:@tombell/pi-diff" in _identities(packages)  # borrowed package preserved

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
    assert "npm:@tombell/pi-diff" in _identities(packages)


def test_init_selecting_a_todo_provider_wires_then_deselecting_removes(tmp_path):
    # The todo-seam analogue (Node 3.2): the init wiring is already seam-generic, so selecting the
    # real `juicesharp-todo` provider wires `npm:@juicesharp/rpiv-todo` (object form, no filter) and
    # deselecting removes it — locking the generic behavior for the todo seam too.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"packages": ["npm:@me/custom", "npm:@tombell/pi-diff"]}, indent=2) + "\n"
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
    assert "npm:@tombell/pi-diff" in _identities(packages)  # borrowed package preserved

    # Deselect (back to the default) → the provider-managed entry is removed; others survive.
    pi_dir.joinpath("perk.toml").write_text(
        '[providers]\ntodo = "perk-checkpoints"\n', encoding="utf-8"
    )
    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert "npm:@juicesharp/rpiv-todo" not in _identities(packages)
    assert "npm:@me/custom" in _identities(packages)
    assert "npm:@tombell/pi-diff" in _identities(packages)


def test_init_selecting_an_askuser_provider_wires_then_deselecting_removes(tmp_path):
    # The askuser-seam analogue: the init wiring is seam-generic, so selecting the real
    # `juicesharp-ask-user` provider wires `npm:@juicesharp/rpiv-ask-user-question` (object form,
    # no filter) and deselecting removes it. The vacate-only adapter (no shim) is irrelevant to
    # init's package wiring — only the `package` field matters here.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"packages": ["npm:@me/custom", "npm:@tombell/pi-diff"]}, indent=2) + "\n"
    )
    pi_dir.joinpath("perk.toml").write_text(
        '[providers]\naskuser = "juicesharp-ask-user"\n', encoding="utf-8"
    )

    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    entry = next(
        p
        for p in packages
        if isinstance(p, dict) and p.get("source") == "npm:@juicesharp/rpiv-ask-user-question"
    )
    assert entry == {"source": "npm:@juicesharp/rpiv-ask-user-question"}
    assert "npm:@me/custom" in _identities(packages)  # user package preserved
    assert "npm:@tombell/pi-diff" in _identities(packages)  # borrowed package preserved

    # An idempotent re-run with the selection in place changes nothing.
    before = _snapshot(tmp_path)
    assert run_init(tmp_path, verify=False).ok
    assert before == _snapshot(tmp_path)

    # Deselect (back to the default) → the provider-managed entry is removed; others survive.
    pi_dir.joinpath("perk.toml").write_text(
        '[providers]\naskuser = "perk-ask-user"\n', encoding="utf-8"
    )
    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert "npm:@juicesharp/rpiv-ask-user-question" not in _identities(packages)
    assert "npm:@me/custom" in _identities(packages)
    assert "npm:@tombell/pi-diff" in _identities(packages)


def test_init_selecting_a_footer_provider_wires_then_deselecting_removes(tmp_path):
    # The footer-seam analogue: selecting the real `pi-bar-footer` provider wires `npm:pi-bar`
    # (object form, no filter) and deselecting removes it. The vacate-only adapter (no shim) is
    # irrelevant to init's package wiring — only the `package` field matters here.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"packages": ["npm:@me/custom", "npm:@tombell/pi-diff"]}, indent=2) + "\n"
    )
    pi_dir.joinpath("perk.toml").write_text(
        '[providers]\nfooter = "pi-bar-footer"\n', encoding="utf-8"
    )

    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    entry = next(p for p in packages if isinstance(p, dict) and p.get("source") == "npm:pi-bar")
    assert entry == {"source": "npm:pi-bar"}
    assert "npm:@me/custom" in _identities(packages)  # user package preserved
    assert "npm:@tombell/pi-diff" in _identities(packages)  # borrowed package preserved

    # Deselect (back to the default) → the provider-managed entry is removed; others survive.
    pi_dir.joinpath("perk.toml").write_text(
        '[providers]\nfooter = "perk-footer"\n', encoding="utf-8"
    )
    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert "npm:pi-bar" not in _identities(packages)
    assert "npm:@me/custom" in _identities(packages)
    assert "npm:@tombell/pi-diff" in _identities(packages)


def test_init_selecting_a_web_provider_swaps_the_package(tmp_path):
    # The web-seam two-directional swap (#529): selecting the foreign `ollama-web-search` provider
    # REMOVES the default `npm:pi-web-access` (also provider-managed) and ADDS
    # `npm:@ollama/pi-web-search` (object form, no filter); reverting swaps back.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"packages": ["npm:@me/custom", "npm:pi-web-access"]}, indent=2) + "\n"
    )
    pi_dir.joinpath("perk.toml").write_text(
        '[providers]\nweb = "ollama-web-search"\n', encoding="utf-8"
    )

    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    entry = next(
        p
        for p in packages
        if isinstance(p, dict) and p.get("source") == "npm:@ollama/pi-web-search"
    )
    assert entry == {"source": "npm:@ollama/pi-web-search"}
    # The default web package is provider-managed too, so a foreign web selection removes it.
    assert "npm:pi-web-access" not in _identities(packages)
    assert "npm:@me/custom" in _identities(packages)  # user package preserved

    # Revert to the default `pi-web-access` → ollama removed, pi-web-access re-added.
    pi_dir.joinpath("perk.toml").write_text(
        '[providers]\nweb = "pi-web-access"\n', encoding="utf-8"
    )
    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert "npm:@ollama/pi-web-search" not in _identities(packages)
    assert "npm:pi-web-access" in _identities(packages)
    assert "npm:@me/custom" in _identities(packages)


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


def test_init_default_repo_wires_no_linear_package(tmp_path):
    # No [issues] selection (or backend = "github") → no pi-mono-linear entry.
    assert run_init(tmp_path, verify=False).ok
    packages = json.loads((tmp_path / ".pi" / "settings.json").read_text())["packages"]
    assert "npm:pi-mono-linear" not in _identities(packages)


def test_init_selecting_linear_wires_then_deselecting_removes(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    # User + borrowed packages present from a prior run; both must survive.
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"packages": ["npm:@me/custom", "npm:@tombell/pi-diff"]}, indent=2) + "\n"
    )
    pi_dir.joinpath("perk.toml").write_text(
        '[issues]\nbackend = "linear"\nteam = "ENG"\n', encoding="utf-8"
    )

    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    # The plain-string entry (the borrowed-set convention; no package_filter), exactly once.
    assert packages.count("npm:pi-mono-linear") == 1
    assert "npm:@me/custom" in _identities(packages)
    assert "npm:@tombell/pi-diff" in _identities(packages)

    # Deselect (back to github) → the entry is removed; others survive.
    pi_dir.joinpath("perk.toml").write_text('[issues]\nbackend = "github"\n', encoding="utf-8")
    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert "npm:pi-mono-linear" not in _identities(packages)
    assert "npm:@me/custom" in _identities(packages)
    assert "npm:@tombell/pi-diff" in _identities(packages)


def test_init_linear_wiring_is_idempotent(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    pi_dir.joinpath("perk.toml").write_text('[issues]\nbackend = "linear"\n', encoding="utf-8")
    assert run_init(tmp_path, verify=False).ok
    before = _snapshot(tmp_path)
    assert run_init(tmp_path, verify=False).ok
    assert before == _snapshot(tmp_path)


def test_init_removes_hand_added_linear_package_without_selection(tmp_path):
    # Hand-adding pi-mono-linear without selecting linear is unsupported — init removes it.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"packages": ["npm:pi-mono-linear"]}, indent=2) + "\n"
    )
    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert "npm:pi-mono-linear" not in _identities(packages)


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
    # legacy entry stripped (string entries only; the web default adds an object-form entry)
    assert not any(isinstance(p, str) and p.startswith("npm:@perk/pi") for p in packages)
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
    assert not any(
        isinstance(p, str) and p.startswith("git:github.com/mattgiles/perk") for p in packages
    )


def test_init_writes_skills_manifest_fragment(tmp_path):
    # Consumer mode: the fragment declares the perk source pinned to the release tag and lists
    # every perk skill. The fragment is a committed declaration, never gitignored.
    run_init(tmp_path, verify=False)
    fragment = tmp_path / ".agents" / "manifest.d" / "perk.yaml"
    assert fragment.is_file()
    text = fragment.read_text(encoding="utf-8")
    assert "url: https://github.com/mattgiles/perk" in text
    assert f"ref: v{__version__}" in text
    from perk.convergence.init import PERK_SKILLS

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
