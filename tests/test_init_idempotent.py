import json
from pathlib import Path

import pytest

from perk import __version__
from perk.cli.ensure import UserFacingCliError
from perk.convergence.init import run_init
from perk.substrate import paths


def _seed_cfg(pi_dir: Path) -> Path:
    """The committed config path (`<root>/.perk/config.toml`), creating `.perk/` as needed.

    Config moved out of `.pi/`; tests still derive the dir from the `pi_dir` (`.pi`) local.
    """
    cfg = pi_dir.parent / ".perk"
    cfg.mkdir(parents=True, exist_ok=True)
    return cfg / "config.toml"


def _snapshot(root):
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in root.rglob("*")
        if p.is_file() and ".git/" not in p.relative_to(root).as_posix()
    }


def _write_legacy_config(root: Path) -> Path:
    """Seed a legacy committed config at `<root>/.pi/perk.toml`."""
    pi = root / ".pi"
    pi.mkdir(parents=True, exist_ok=True)
    legacy = pi / "perk.toml"
    legacy.write_text('[worktree]\nroot = "legacy-wt"\n', encoding="utf-8")
    return legacy


def test_init_refuses_legacy_only_config(tmp_path):
    # A repo carrying only the legacy committed config (`.pi/perk.toml`, no `.perk/config.toml`)
    # makes init refuse (exit 2) with a `doctor --fix` remediation — never warn-and-seed over it.
    legacy = _write_legacy_config(tmp_path)
    report = run_init(tmp_path, verify=False)
    assert not report.ok
    assert report.error_type == "legacy_config"
    assert report.exit_code == 2
    assert "perk doctor --fix" in (report.message or "")
    # Nothing seeded: the new target is not created and the legacy file is left untouched.
    assert not (tmp_path / ".perk" / "config.toml").is_file()
    assert legacy.read_text(encoding="utf-8") == '[worktree]\nroot = "legacy-wt"\n'


def test_init_legacy_local_only_does_not_block(tmp_path):
    # The refusal keys on the COMMITTED marker only: a lone legacy local file does not block init,
    # which converges a fresh `.perk/config.toml`.
    pi = tmp_path / ".pi"
    pi.mkdir(parents=True, exist_ok=True)
    (pi / "perk.local.toml").write_text('[linear]\napi_key = "lin_x"\n', encoding="utf-8")
    assert run_init(tmp_path, verify=False).ok
    assert (tmp_path / ".perk" / "config.toml").is_file()


def test_init_both_present_converges(tmp_path):
    # A repo with BOTH the legacy and the new committed file is already migrated enough to not
    # block (the marker exists) — init converges normally.
    _write_legacy_config(tmp_path)
    cfg = tmp_path / ".perk"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text('[worktree]\nroot = "wt"\n', encoding="utf-8")
    assert run_init(tmp_path, verify=False).ok


def test_init_converges_and_is_idempotent(tmp_path):
    # tmp_path has no `[tool.perk] self` marker -> consumer mode.
    # verify=False: pure convergence (no repo/tooling/GitHub shells).
    assert run_init(tmp_path, verify=False).ok

    settings = json.loads((tmp_path / ".pi" / "settings.json").read_text())
    packages = settings["packages"]
    assert f"npm:@mgiles/perk@{__version__}" in packages  # version-pinned perk extension
    assert "npm:@tombell/pi-diff" in packages  # surviving borrowed package (anchor)
    assert "npm:@tombell/pi-status" not in packages  # retired: footer conflict
    assert "npm:@tombell/pi-plan" not in packages  # perk owns plan mode now
    assert "npm:@juicesharp/rpiv-todo" not in packages  # perk owns checkpoints now
    assert "npm:pi-subagents" in packages  # borrowed spawned-delegation engine
    assert "npm:@ff-labs/pi-fff" in packages  # borrowed FFF search
    # pi-web-access is no longer borrowed — it is the `web` seam's default provider, converged
    # via the provider path (object form on a fresh init), so it still lands in `packages`.
    assert "npm:pi-web-access" in _identities(packages)

    # The whole `.perk/workflow/` cache tree is gitignored — no committed `.gitkeep`; init creates
    # the four cache subtrees on demand.
    assert not (tmp_path / ".perk" / "workflow" / ".gitkeep").exists()
    for sub in ("plans", "scratch/runs", "handoff", "markers"):
        assert (tmp_path / ".perk" / "workflow" / sub).is_dir()
    # perk-owned agent-definitions home (committed `.gitkeep`).
    assert (tmp_path / ".pi" / "agents" / ".gitkeep").is_file()
    # perk's three agent defs are delivered into the perk-owned `.pi/agents/perk/` subdir.
    from perk.convergence.init import PERK_AGENTS

    for name in PERK_AGENTS:
        assert (tmp_path / ".pi" / "agents" / "perk" / f"{name}.md").is_file()
    gitignore = (tmp_path / ".gitignore").read_text()
    assert "/.pi/npm/" in gitignore
    # The whole `.perk/workflow/` cache tree is gitignored wholesale (no per-file entries).
    assert "/.perk/workflow/" in gitignore
    # The borrowed pi-subagents engine's project-scoped run-artifact root is transient.
    assert "/.pi-subagents/" in gitignore
    agents_md = (tmp_path / "AGENTS.md").read_text()
    assert "perk conventions" in agents_md
    # The managed block carries the ambient gh guidance.
    assert "GitHub access goes through the `gh` CLI" in agents_md
    # ...and the ambient ast-grep code-search steer.
    assert "Prefer ast-grep for code search" in agents_md

    # ast-grep is a registered perk skill (SSOT for the manifest + delivery).
    from perk.convergence.init import PERK_SKILLS

    assert "ast-grep" in PERK_SKILLS

    # Idempotency: a second run changes nothing on disk.
    before = _snapshot(tmp_path)
    assert run_init(tmp_path, verify=False).ok
    after = _snapshot(tmp_path)
    assert before == after


def test_init_records_managed_state(tmp_path):
    from perk.convergence.managed_state import load_managed_state, managed_artifacts

    report = run_init(tmp_path, verify=False)
    assert report.ok
    assert ".perk/managed-state.toml: recorded" in report.changes
    state = load_managed_state(tmp_path)
    assert state is not None
    assert state.version == __version__
    by_key = {d.key: d for d in managed_artifacts()}
    assert {a.key for a in state.artifacts} == set(by_key)
    for artifact in state.artifacts:
        assert artifact.version == __version__
        assert artifact.hash == by_key[artifact.key].desired_hash(tmp_path, self_repo=False)


def test_init_backfills_a_missing_state_file_exactly_once(tmp_path):
    assert run_init(tmp_path, verify=False).ok
    paths.managed_state_file(tmp_path).unlink()
    # The one-time backfill: exactly the single state line, nothing else re-reported.
    backfill = run_init(tmp_path, verify=False)
    assert backfill.ok
    assert backfill.changes == [".perk/managed-state.toml: recorded"]
    again = run_init(tmp_path, verify=False)
    assert again.ok and again.changes == []


def _identities(packages):
    """Map a `packages` list (str or object-form) to the set of package specs/sources present."""
    out = set()
    for p in packages:
        if isinstance(p, str):
            out.add(p)
        elif isinstance(p, dict) and isinstance(p.get("source"), str):
            out.add(p["source"])
    return out


def test_init_writes_required_perk_version(tmp_path):
    report = run_init(tmp_path, verify=False)
    assert report.ok
    pin = paths.required_version_file(tmp_path)
    assert pin.read_text(encoding="utf-8") == f"{__version__}\n"
    assert ".perk/required-perk-version: created" in report.changes


def test_init_default_repo_wires_no_foreign_provider_package_except_web_default(tmp_path):
    # The zero-config default: the plan/todo/askuser/footer seams resolve to `package: null`
    # providers, so no foreign package is added for them. The `web` seam is the novel
    # exception: its default `pi-web-access` carries a non-null package, so the default path
    # DOES converge `npm:pi-web-access` via the provider path (object form on a fresh init).
    assert run_init(tmp_path, verify=False).ok
    packages = json.loads((tmp_path / ".pi" / "settings.json").read_text())["packages"]
    assert "npm:@tombell/pi-plan" not in _identities(packages)
    assert "npm:@juicesharp/rpiv-todo" not in _identities(packages)
    assert "npm:@ollama/pi-web-search" not in _identities(packages)
    assert "npm:@plannotator/pi-extension" not in _identities(packages)
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
    _seed_cfg(pi_dir).write_text('[providers]\nplan = "tombell-plan"\n', encoding="utf-8")

    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    # The foreign package is wired in OBJECT form. The real tombell-plan entry has no
    # `package_filter`, so the object carries `source` only (no merged extensions/skills keys).
    entry = next(
        p for p in packages if isinstance(p, dict) and p.get("source") == "npm:@tombell/pi-plan"
    )
    assert entry == {"source": "npm:@tombell/pi-plan"}
    assert "npm:@me/custom" in _identities(packages)  # user package preserved
    assert "npm:@tombell/pi-diff" in _identities(packages)  # borrowed package preserved

    # Deselect (back to the default) → the provider-managed entry is removed; others survive.
    _seed_cfg(pi_dir).write_text('[providers]\nplan = "perk-plan"\n', encoding="utf-8")
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
    _seed_cfg(pi_dir).write_text('[providers]\nplan = "plannotator-plan"\n', encoding="utf-8")

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
    _seed_cfg(pi_dir).write_text('[providers]\nplan = "perk-plan"\n', encoding="utf-8")
    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert "npm:@plannotator/pi-extension" not in _identities(packages)
    assert "npm:@me/custom" in _identities(packages)
    assert "npm:@tombell/pi-diff" in _identities(packages)


def test_init_selecting_a_todo_provider_wires_then_deselecting_removes(tmp_path):
    # The todo-seam analogue: the init wiring is already seam-generic, so selecting the
    # real `juicesharp-todo` provider wires `npm:@juicesharp/rpiv-todo` (object form, no filter) and
    # deselecting removes it — locking the generic behavior for the todo seam too.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"packages": ["npm:@me/custom", "npm:@tombell/pi-diff"]}, indent=2) + "\n"
    )
    _seed_cfg(pi_dir).write_text('[providers]\ntodo = "juicesharp-todo"\n', encoding="utf-8")

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
    _seed_cfg(pi_dir).write_text('[providers]\ntodo = "perk-checkpoints"\n', encoding="utf-8")
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
    _seed_cfg(pi_dir).write_text('[providers]\naskuser = "juicesharp-ask-user"\n', encoding="utf-8")

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
    _seed_cfg(pi_dir).write_text('[providers]\naskuser = "perk-ask-user"\n', encoding="utf-8")
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
    _seed_cfg(pi_dir).write_text('[providers]\nfooter = "pi-bar-footer"\n', encoding="utf-8")

    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    entry = next(p for p in packages if isinstance(p, dict) and p.get("source") == "npm:pi-bar")
    assert entry == {"source": "npm:pi-bar"}
    assert "npm:@me/custom" in _identities(packages)  # user package preserved
    assert "npm:@tombell/pi-diff" in _identities(packages)  # borrowed package preserved

    # Deselect (back to the default) → the provider-managed entry is removed; others survive.
    _seed_cfg(pi_dir).write_text('[providers]\nfooter = "perk-footer"\n', encoding="utf-8")
    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert "npm:pi-bar" not in _identities(packages)
    assert "npm:@me/custom" in _identities(packages)
    assert "npm:@tombell/pi-diff" in _identities(packages)


def test_init_governs_pi_status_and_pi_default_footers(tmp_path):
    # The footer is governed EXCLUSIVELY by `[providers] footer` — no footer outcome ever
    # needs a manual `packages` edit. Four cases prove the two new providers + the managed-identity
    # "revert the manual edit" guarantee for `npm:@tombell/pi-status`.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    settings = pi_dir / "settings.json"
    perk_toml = _seed_cfg(pi_dir)

    # (1) footer = "pi-status-footer" adds `npm:@tombell/pi-status` in object form.
    settings.write_text(json.dumps({"packages": ["npm:@me/custom"]}, indent=2) + "\n")
    perk_toml.write_text('[providers]\nfooter = "pi-status-footer"\n', encoding="utf-8")
    run_init(tmp_path, verify=False)
    packages = json.loads(settings.read_text())["packages"]
    entry = next(
        p for p in packages if isinstance(p, dict) and p.get("source") == "npm:@tombell/pi-status"
    )
    assert entry == {"source": "npm:@tombell/pi-status"}  # no `package_filter`
    assert "npm:@me/custom" in _identities(packages)  # user package preserved

    # (2) pi-default (`package: null`) adds nothing — pi's stock footer stands.
    settings.write_text(json.dumps({"packages": ["npm:@me/custom"]}, indent=2) + "\n")
    perk_toml.write_text('[providers]\nfooter = "pi-default"\n', encoding="utf-8")
    run_init(tmp_path, verify=False)
    packages = json.loads(settings.read_text())["packages"]
    assert "npm:@tombell/pi-status" not in _identities(packages)
    assert "npm:@me/custom" in _identities(packages)  # user package preserved

    # (3) switching to pi-status then back to the default removes the managed pi-status entry.
    perk_toml.write_text('[providers]\nfooter = "pi-status-footer"\n', encoding="utf-8")
    run_init(tmp_path, verify=False)
    assert "npm:@tombell/pi-status" in _identities(json.loads(settings.read_text())["packages"])
    perk_toml.write_text('[providers]\nfooter = "perk-footer"\n', encoding="utf-8")
    run_init(tmp_path, verify=False)
    assert "npm:@tombell/pi-status" not in _identities(json.loads(settings.read_text())["packages"])

    # (4) a HAND-ADDED `npm:@tombell/pi-status` string with footer UNSELECTED is removed by
    # convergence (now that pi-status is a managed identity) — the machine-governed "revert the
    # manual edit" guarantee.
    settings.write_text(
        json.dumps({"packages": ["npm:@me/custom", "npm:@tombell/pi-status"]}, indent=2) + "\n"
    )
    perk_toml.write_text("[providers]\n", encoding="utf-8")
    run_init(tmp_path, verify=False)
    packages = json.loads(settings.read_text())["packages"]
    assert "npm:@tombell/pi-status" not in _identities(packages)
    assert "npm:@me/custom" in _identities(packages)  # user package preserved


def test_init_selecting_a_web_provider_swaps_the_package(tmp_path):
    # The web-seam two-directional swap: selecting the foreign `ollama-web-search` provider
    # REMOVES the default `npm:pi-web-access` (also provider-managed) and ADDS
    # `npm:@ollama/pi-web-search` (object form, no filter); reverting swaps back.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"packages": ["npm:@me/custom", "npm:pi-web-access"]}, indent=2) + "\n"
    )
    _seed_cfg(pi_dir).write_text('[providers]\nweb = "ollama-web-search"\n', encoding="utf-8")

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
    _seed_cfg(pi_dir).write_text('[providers]\nweb = "pi-web-access"\n', encoding="utf-8")
    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert "npm:@ollama/pi-web-search" not in _identities(packages)
    assert "npm:pi-web-access" in _identities(packages)
    assert "npm:@me/custom" in _identities(packages)


def test_init_provider_wiring_is_idempotent(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    _seed_cfg(pi_dir).write_text('[providers]\nplan = "tombell-plan"\n', encoding="utf-8")
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
    _seed_cfg(pi_dir).write_text('[issues]\nbackend = "linear"\nteam = "ENG"\n', encoding="utf-8")

    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    # The plain-string entry (the borrowed-set convention; no package_filter), exactly once.
    assert packages.count("npm:pi-mono-linear") == 1
    assert "npm:@me/custom" in _identities(packages)
    assert "npm:@tombell/pi-diff" in _identities(packages)

    # Deselect (back to github) → the entry is removed; others survive.
    _seed_cfg(pi_dir).write_text('[issues]\nbackend = "github"\n', encoding="utf-8")
    run_init(tmp_path, verify=False)
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert "npm:pi-mono-linear" not in _identities(packages)
    assert "npm:@me/custom" in _identities(packages)
    assert "npm:@tombell/pi-diff" in _identities(packages)


def test_init_linear_wiring_is_idempotent(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    _seed_cfg(pi_dir).write_text('[issues]\nbackend = "linear"\n', encoding="utf-8")
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
    _seed_cfg(pi_dir).write_text(
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
    _seed_cfg(pi_dir).write_text("[compaction]\nreserve_tokens = 8192\n", encoding="utf-8")
    run_init(tmp_path, verify=False)
    compaction = json.loads((pi_dir / "settings.json").read_text())["compaction"]
    assert compaction["reserveTokens"] == 8192  # perk key overwrote
    assert compaction["customKey"] == 7  # unrelated key preserved


def test_init_illtyped_compaction_defers_to_config_check(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    # An ill-typed [compaction] value (ConfigError) defers to the config check: init still
    # converges everything else (no crash) and simply writes no `compaction` block.
    _seed_cfg(pi_dir).write_text("[compaction]\nreserve_tokens = true\n", encoding="utf-8")
    assert run_init(tmp_path, verify=False).ok
    settings = json.loads((pi_dir / "settings.json").read_text())
    assert "compaction" not in settings


def test_init_compaction_absent_leaves_existing_untouched(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    # No [compaction] in config.toml → an existing settings.json `compaction` is never touched.
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"compaction": {"reserveTokens": 999}}, indent=2) + "\n"
    )
    run_init(tmp_path, verify=False)
    compaction = json.loads((pi_dir / "settings.json").read_text())["compaction"]
    assert compaction == {"reserveTokens": 999}  # left exactly as the user set it


def test_init_writes_models_when_present(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    _seed_cfg(pi_dir).write_text(
        '[models]\ndefault = "anthropic/claude-opus-4-1"\nthinking = "high"\n', encoding="utf-8"
    )
    assert run_init(tmp_path, verify=False).ok
    settings = json.loads((pi_dir / "settings.json").read_text())
    assert settings["defaultProvider"] == "anthropic"
    assert settings["defaultModel"] == "claude-opus-4-1"
    assert settings["defaultThinkingLevel"] == "high"
    # Idempotent: a second run changes nothing on disk.
    before = _snapshot(tmp_path)
    assert run_init(tmp_path, verify=False).ok
    assert before == _snapshot(tmp_path)


def test_init_models_overwrites_perk_keys_preserving_others(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    # An existing settings.json with a stale perk-specified key (to overwrite) and an unrelated
    # top-level user key (to preserve).
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"defaultModel": "stale-model", "theme": "nightowl"}, indent=2) + "\n"
    )
    _seed_cfg(pi_dir).write_text(
        '[models]\ndefault = "anthropic/claude-opus-4-1"\n', encoding="utf-8"
    )
    run_init(tmp_path, verify=False)
    settings = json.loads((pi_dir / "settings.json").read_text())
    assert settings["defaultModel"] == "claude-opus-4-1"  # perk key overwrote
    assert settings["defaultProvider"] == "anthropic"
    assert settings["theme"] == "nightowl"  # unrelated key preserved


def test_init_illtyped_models_defers_to_config_check(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    # An ill-typed [models] value (ConfigError) defers to the config check: init still converges
    # everything else (no crash) and simply writes no default-model keys.
    _seed_cfg(pi_dir).write_text('[models]\nthinking = "hgih"\n', encoding="utf-8")
    assert run_init(tmp_path, verify=False).ok
    settings = json.loads((pi_dir / "settings.json").read_text())
    assert "defaultThinkingLevel" not in settings
    assert "defaultProvider" not in settings and "defaultModel" not in settings


def test_init_models_absent_leaves_existing_untouched(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    # No [models] in config.toml → pre-existing settings.json defaults are never touched.
    pi_dir.joinpath("settings.json").write_text(
        json.dumps({"defaultProvider": "zai", "defaultModel": "glm-5"}, indent=2) + "\n"
    )
    run_init(tmp_path, verify=False)
    settings = json.loads((pi_dir / "settings.json").read_text())
    assert settings["defaultProvider"] == "zai"
    assert settings["defaultModel"] == "glm-5"  # left exactly as the user set them


def test_init_writes_subagents_disable_builtins(tmp_path):
    # Constant desired, no config read: a bare repo converges the builtins-off key
    # unconditionally (perk borrows pi-subagents as engine-only).
    assert run_init(tmp_path, verify=False).ok
    settings = json.loads((tmp_path / ".pi" / "settings.json").read_text())
    assert settings["subagents"] == {"disableBuiltins": True}


def test_init_subagents_overwrites_perk_key_preserving_others(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    # A hand-flipped `disableBuiltins` (to converge back — perk owns that key) beside a
    # per-agent `agentOverrides` re-enable (the sanctioned escape hatch, to preserve intact).
    pi_dir.joinpath("settings.json").write_text(
        json.dumps(
            {
                "subagents": {
                    "disableBuiltins": False,
                    "agentOverrides": {"oracle": {"disabled": False}},
                }
            },
            indent=2,
        )
        + "\n"
    )
    run_init(tmp_path, verify=False)
    subagents = json.loads((pi_dir / "settings.json").read_text())["subagents"]
    assert subagents["disableBuiltins"] is True  # perk key overwrote
    assert subagents["agentOverrides"] == {"oracle": {"disabled": False}}  # preserved intact


def test_init_seeds_tui_mode_fullscreen(tmp_path):
    # Seed-when-absent: a bare repo gains the fullscreen default once.
    assert run_init(tmp_path, verify=False).ok
    settings = json.loads((tmp_path / ".pi" / "settings.json").read_text())
    assert settings["tuiMode"] == "fullscreen"


def test_init_preserves_existing_tui_mode(tmp_path):
    # Presence — not value — is the guard: a committed opt-out survives reconvergence.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    pi_dir.joinpath("settings.json").write_text(json.dumps({"tuiMode": "regular"}, indent=2) + "\n")
    run_init(tmp_path, verify=False)
    settings = json.loads((pi_dir / "settings.json").read_text())
    assert settings["tuiMode"] == "regular"


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
    assert f"npm:@mgiles/perk@{__version__}" in settings["packages"]  # perk entry added


def test_init_migrates_legacy_git_perk_entry(tmp_path):
    # A repo wired by an earlier perk init carries the legacy `git:` perk entry. init must strip
    # it (forward convergence to the npm wiring) and add the version-pinned npm entry, without
    # touching the user's own entries.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    (pi_dir / "settings.json").write_text(
        json.dumps({"packages": ["git:github.com/mattgiles/perk@main", "npm:@me/custom"]}, indent=2)
        + "\n"
    )

    run_init(tmp_path, verify=False)

    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    # legacy git perk entry stripped, npm pin added
    assert not any(
        isinstance(p, str) and p.startswith("git:github.com/mattgiles/perk") for p in packages
    )
    assert f"npm:@mgiles/perk@{__version__}" in packages  # npm pin added
    assert "npm:@me/custom" in packages  # user entry preserved


def test_init_reconciles_stale_perk_version(tmp_path):
    # A consumer pinned to a stale npm version must be reconciled forward to the pin
    # (version-aware convergence), preserving list position and the user's unrelated packages.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    (pi_dir / "settings.json").write_text(
        json.dumps({"packages": ["npm:@mgiles/perk@0.0.0", "npm:@me/custom"]}, indent=2) + "\n"
    )

    run_init(tmp_path, verify=False)

    pin = f"npm:@mgiles/perk@{__version__}"
    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert pin in packages  # reconciled forward
    assert "npm:@mgiles/perk@0.0.0" not in packages  # stale version gone
    assert "npm:@me/custom" in packages  # user entry preserved
    # position preserved (rewritten in place, not appended)
    assert packages.index(pin) < packages.index("npm:@me/custom")


def test_init_preserves_unrelated_git_package(tmp_path):
    # A user's unrelated git: package with its own ref is never touched (only perk's own npm
    # identity is ever in the desired set); the npm pin is added (not a git entry).
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    (pi_dir / "settings.json").write_text(
        json.dumps({"packages": ["git:github.com/someone/other@v1.2.3"]}, indent=2) + "\n"
    )

    run_init(tmp_path, verify=False)

    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert "git:github.com/someone/other@v1.2.3" in packages  # untouched
    assert f"npm:@mgiles/perk@{__version__}" in packages  # npm pin added


def test_init_dedups_duplicate_perk_entries(tmp_path):
    # A pathological repo with two perk npm entries converges to a single pinned entry
    # (rewrite the first, drop the rest) rather than producing duplicate pinned entries.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    (pi_dir / "settings.json").write_text(
        json.dumps(
            {
                "packages": [
                    "npm:@mgiles/perk@0.0.0",
                    "npm:@mgiles/perk@0.0.2",
                ]
            },
            indent=2,
        )
        + "\n"
    )

    run_init(tmp_path, verify=False)

    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    perk_entries = [p for p in packages if isinstance(p, str) and p.startswith("npm:@mgiles/perk")]
    assert perk_entries == [f"npm:@mgiles/perk@{__version__}"]  # collapsed to one


def test_init_ref_reconcile_is_idempotent(tmp_path):
    # Once at the pin, a re-run is a no-op (spec equals desired → no change).
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    run_init(tmp_path, verify=False)
    first = (pi_dir / "settings.json").read_text()
    run_init(tmp_path, verify=False)
    assert (pi_dir / "settings.json").read_text() == first  # converged → stable


def test_init_recognizes_object_form_perk_entry(tmp_path):
    # A user rewrote perk's entry to object form via `pi config -l` (resource filtering). The
    # entry must be *recognized* (no duplicate string append), its `source` pin reconciled
    # forward IN PLACE, and the user's filter keys preserved byte-for-byte.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    (pi_dir / "settings.json").write_text(
        json.dumps(
            {
                "packages": [
                    {"source": "npm:@mgiles/perk@0.0.0", "extensions": []},
                    "npm:@me/custom",
                ]
            },
            indent=2,
        )
        + "\n"
    )

    run_init(tmp_path, verify=False)

    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    # No string perk entry appended (the old latent-corruption path).
    assert not any(isinstance(p, str) and p.startswith("npm:@mgiles/perk") for p in packages)
    # The object entry survives at its position with the pin reconciled + filters preserved.
    assert packages[0] == {"source": f"npm:@mgiles/perk@{__version__}", "extensions": []}
    assert "npm:@me/custom" in packages  # user entry preserved


def test_init_collapses_mixed_perk_duplicates_object_canonical(tmp_path):
    # The corruption the string-only bug produced: an object-form entry PLUS stale string
    # duplicates. The object entry is canonical (it carries the user's filters, which perk
    # cannot reconstruct); the string duplicates are dropped.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    (pi_dir / "settings.json").write_text(
        json.dumps(
            {
                "packages": [
                    "npm:@mgiles/perk@0.0.0",
                    {"source": "npm:@mgiles/perk@0.0.2", "skills": ["perk-implement"]},
                    "npm:@mgiles/perk@0.0.1",
                ]
            },
            indent=2,
        )
        + "\n"
    )

    run_init(tmp_path, verify=False)

    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    perk_entries = [
        p
        for p in packages
        if (isinstance(p, str) and p.startswith("npm:@mgiles/perk"))
        or (isinstance(p, dict) and str(p.get("source", "")).startswith("npm:@mgiles/perk"))
    ]
    assert perk_entries == [
        {"source": f"npm:@mgiles/perk@{__version__}", "skills": ["perk-implement"]}
    ]


def test_init_recognizes_object_form_borrowed_entry(tmp_path):
    # An object-form BORROWED entry is recognized by identity (never duplicate-appended) and
    # left untouched (borrowed packages are unpinned/append-only — never version-reconciled).
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    (pi_dir / "settings.json").write_text(
        json.dumps({"packages": [{"source": "npm:@tombell/pi-diff"}]}, indent=2) + "\n"
    )

    run_init(tmp_path, verify=False)

    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert "npm:@tombell/pi-diff" not in packages  # no duplicate string append
    assert {"source": "npm:@tombell/pi-diff"} in packages  # untouched


def test_init_self_mode_recognizes_object_form_local_entry(tmp_path):
    # Self-repo: an object-form `{"source": ".."}` local entry is recognized — no duplicate
    # `..` string append.
    (tmp_path / "pyproject.toml").write_text("[tool.perk]\nself = true\n", encoding="utf-8")
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    (pi_dir / "settings.json").write_text(
        json.dumps({"packages": [{"source": "..", "themes": []}]}, indent=2) + "\n"
    )

    run_init(tmp_path, verify=False)

    packages = json.loads((tmp_path / ".pi" / "settings.json").read_text())["packages"]
    assert ".." not in packages  # no duplicate string append
    assert {"source": "..", "themes": []} in packages  # untouched (filters preserved)


def test_init_strips_object_form_legacy_git_perk_entry(tmp_path):
    # The legacy `git:` perk migration is identity-aware too: a user-rewritten object-form
    # legacy entry is stripped (same string-only root cause as the duplicate append).
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    (pi_dir / "settings.json").write_text(
        json.dumps(
            {"packages": [{"source": "git:github.com/mattgiles/perk@main", "extensions": []}]},
            indent=2,
        )
        + "\n"
    )

    run_init(tmp_path, verify=False)

    packages = json.loads((pi_dir / "settings.json").read_text())["packages"]
    assert not any(
        isinstance(p, dict) and str(p.get("source", "")).startswith("git:") for p in packages
    )
    assert f"npm:@mgiles/perk@{__version__}" in packages  # npm pin added


def test_init_object_form_convergence_is_idempotent(tmp_path):
    # After converging an object-form perk entry, a second run is a byte-for-byte no-op.
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    (pi_dir / "settings.json").write_text(
        json.dumps({"packages": [{"source": "npm:@mgiles/perk@0.0.0", "extensions": []}]}, indent=2)
        + "\n"
    )
    run_init(tmp_path, verify=False)
    first = (pi_dir / "settings.json").read_text()
    run_init(tmp_path, verify=False)
    assert (pi_dir / "settings.json").read_text() == first  # converged → stable


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
    # Self-repo wires `..` only — neither a git: perk entry nor an npm:@mgiles/perk entry.
    assert not any(
        isinstance(p, str) and p.startswith("git:github.com/mattgiles/perk") for p in packages
    )
    assert not any(isinstance(p, str) and p.startswith("npm:@mgiles/perk") for p in packages)


def test_init_writes_skills_manifest_fragment(tmp_path):
    # Consumer mode: the fragment declares the perk source tracking main plus the required
    # external sources, and lists the union of perk + external skills. The fragment is a
    # committed declaration, never gitignored.
    run_init(tmp_path, verify=False)
    fragment = tmp_path / ".agents" / "manifest.d" / "perk.yaml"
    assert fragment.is_file()
    text = fragment.read_text(encoding="utf-8")
    assert "url: https://github.com/mattgiles/perk" in text
    assert "ref: main" in text
    from perk.convergence.init import PERK_SKILLS, REQUIRED_EXTERNAL_SKILLS

    for name in PERK_SKILLS:
        assert f"name: {name}" in text
    # The three required external sources are declared (note dagster tracks `master`).
    assert "url: https://github.com/astral-sh/claude-code-plugins" in text
    assert "url: https://github.com/dagster-io/skills" in text
    assert "ref: master" in text
    assert "url: https://github.com/mattpocock/skills" in text
    # Every promoted external skill is declared from its source.
    for src, name in REQUIRED_EXTERNAL_SKILLS:
        assert f"  - source: {src}\n    name: {name}" in text


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


# --- perk's @mgiles/perk npm install (forward reconcile) ----------------------------------


def test_consumer_git_clone_root_derived_from_git_package(tmp_path):
    # `consumer_git_clone_root` (relocated to settings, re-exported via init) derives the
    # orphaned-clone path from GIT_PACKAGE — the path `doctor --fix` removes when migrating a
    # former git-clone consumer forward to the npm install.
    from perk.convergence import init as init_mod

    clone = init_mod.consumer_git_clone_root(tmp_path)
    remainder = init_mod.GIT_PACKAGE.removeprefix("git:")
    expected = tmp_path / ".pi" / "git"
    for segment in remainder.split("/"):
        expected = expected / segment
    assert clone == expected


def test_init_verify_installs_perk_extension_and_is_idempotent(git_repo, stub_env):
    from perk.convergence import init as init_mod

    # stub_env's fake `_install_perk_extension` lands the pinned @mgiles/perk package.json, so a
    # verified init installs the pin (absent → installed) and a second run is a no-op (present).
    report = run_init(git_repo, verify=True)
    assert report.ok
    pkg = init_mod.consumer_perk_package_dir(git_repo)
    assert (pkg / "package.json").is_file()
    assert init_mod.installed_perk_version(git_repo) == __version__
    assert any(f"installed @mgiles/perk@{__version__}" in line for line in report.changes)
    again = run_init(git_repo, verify=True)
    assert again.ok
    assert not any("@mgiles/perk" in line for line in again.changes)  # present → no change
