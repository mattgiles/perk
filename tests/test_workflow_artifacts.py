"""The managed GitHub Actions runner artifact (Objective #137 Node 2.2; contracts.md §8.14)."""

from pathlib import Path

import yaml

from perk.run import workflow_artifacts as wa
from perk.run.runner import GITHUB_ACTIONS_WORKFLOW


def test_workflow_path_matches_the_locked_dispatch_filename():
    # §8.13 locks `perk-run.yml` (runner.GITHUB_ACTIONS_WORKFLOW); the managed file must match.
    expected = f".github/workflows/{GITHUB_ACTIONS_WORKFLOW}"
    assert expected == wa.RUNNER_WORKFLOW_PATH


def test_workflow_honors_the_dispatch_input_contract():
    doc = yaml.safe_load(wa.PERK_RUN_WORKFLOW)
    # run-name embeds ${{ inputs.run_id }} so the dispatcher can verify-by-discovery.
    assert "${{ inputs.run_id }}" in doc["run-name"]
    # The four typed workflow_dispatch inputs.
    inputs = doc[True]["workflow_dispatch"]["inputs"]  # PyYAML parses bare `on:` as the bool True
    assert set(inputs) == {"run_id", "stage", "plan", "base", "smoke"}
    assert inputs["run_id"]["required"] is True
    assert inputs["stage"]["required"] is True
    assert inputs["plan"]["required"] is True
    # `base` is required with no default — the dispatcher always sends it (B6, the tight contract).
    assert inputs["base"]["required"] is True
    assert "default" not in inputs["base"]
    # The additive `smoke` input is optional and defaults off (Node 3.3); real dispatches omit it.
    assert inputs["smoke"]["required"] is False
    assert inputs["smoke"]["default"] == "false"
    # A per-plan concurrency group (mirrors erk's implement-plan-${{ … }}).
    assert doc["concurrency"]["group"] == "perk-run-${{ inputs.plan }}"


def test_workflow_validates_the_secret_and_invokes_run_worker():
    assert "PERK_GH_PAT" in wa.PERK_RUN_WORKFLOW
    assert "::error::" in wa.PERK_RUN_WORKFLOW
    # The drive step calls the runner-side positioning entrypoint and checks out the plan branch.
    assert "perk run-worker" in wa.PERK_RUN_WORKFLOW
    assert "plan-$PLAN" in wa.PERK_RUN_WORKFLOW
    # References its own composite setup action.
    assert "./.github/actions/perk-remote-setup" in wa.PERK_RUN_WORKFLOW


def test_smoke_short_circuit_guards_the_drive_steps():
    # Node 3.3: `smoke=true` runs only Validate + Smoke check; every later step is guarded off.
    doc = yaml.safe_load(wa.PERK_RUN_WORKFLOW)
    steps = doc["jobs"]["drive"]["steps"]
    by_name = {s.get("name"): s for s in steps}
    assert by_name["Smoke check"]["if"] == "inputs.smoke == 'true'"
    # The checkout/setup steps are `uses:` (no name) — find them by their `uses` value.
    checkout = next(s for s in steps if s.get("uses") == "actions/checkout@v4")
    setup = next(s for s in steps if s.get("uses") == "./.github/actions/perk-remote-setup")
    assert checkout["if"] == "inputs.smoke != 'true'"
    assert setup["if"] == "inputs.smoke != 'true'"
    assert by_name["Check out the plan branch"]["if"] == "inputs.smoke != 'true'"
    assert by_name["Drive the stage headlessly"]["if"] == "inputs.smoke != 'true'"


def test_composite_action_installs_perk_and_pi():
    body = wa.remote_setup_action(self_repo=True)
    doc = yaml.safe_load(body)
    assert doc["runs"]["using"] == "composite"
    assert "uv tool install" in body  # perk (the exterior)
    assert "@earendil-works/pi-coding-agent" in body  # pi (the interior)
    assert "npm ci" in body  # the Node worker's peer deps (self-repo)


def test_composite_action_install_is_self_vs_consumer_aware():
    # The self-repo dogfoods the code under test; a consumer installs the version-pinned git build.
    assert "uv tool install --from . perk" in wa.remote_setup_action(self_repo=True)
    consumer = wa.remote_setup_action(self_repo=False)
    assert "git+https://github.com/mattgiles/perk@main" in consumer
    assert "--from ." not in consumer
    # The fictional bare `uv tool install perk` is gone (B3).
    assert "run: uv tool install perk" not in consumer


def test_composite_action_configures_git_identity():
    # B1: both repo-kind variants set a git identity so the worker's commits succeed on a fresh
    # runner (no user.name/user.email otherwise).
    for self_repo in (True, False):
        body = wa.remote_setup_action(self_repo=self_repo)
        assert 'git config --global user.name "perk[bot]"' in body
        assert "perk[bot]@users.noreply.github.com" in body


def test_composite_action_worker_deps_is_repo_kind_aware():
    # B4: self uses `npm ci`; consumer is a loud Node-2.4 deferral (no silent `npm ci`).
    assert "npm ci" in wa.remote_setup_action(self_repo=True)
    consumer = wa.remote_setup_action(self_repo=False)
    assert "npm ci" not in consumer
    assert "::error::" in consumer
    assert "exit 1" in consumer
    assert "Node 2.4" in consumer


def test_workflow_validates_model_keys_fail_fast():
    # B5: the validate step fails fast when BOTH model keys are empty.
    doc = yaml.safe_load(wa.PERK_RUN_WORKFLOW)
    validate = next(
        s for s in doc["jobs"]["drive"]["steps"] if s.get("name") == "Validate required secrets"
    )
    assert "ANTHROPIC_API_KEY" in validate["env"]
    assert "OPENAI_API_KEY" in validate["env"]
    assert '[ -z "$ANTHROPIC_API_KEY" ] && [ -z "$OPENAI_API_KEY" ]' in validate["run"]


def test_converge_creates_both_files_then_is_a_noop(tmp_path: Path):
    created = wa.converge_runner_workflow(tmp_path, True, apply=True)
    assert any("perk-run.yml" in c for c in created)
    assert any("perk-remote-setup" in c for c in created)
    assert (tmp_path / wa.RUNNER_WORKFLOW_PATH).is_file()
    assert (tmp_path / wa.REMOTE_SETUP_ACTION_PATH).is_file()
    # Idempotent: a converged repo yields no further changes.
    assert wa.converge_runner_workflow(tmp_path, True, apply=True) == []


def test_converge_reports_and_repairs_drift(tmp_path: Path):
    wa.converge_runner_workflow(tmp_path, True, apply=True)
    workflow = tmp_path / wa.RUNNER_WORKFLOW_PATH
    workflow.write_text("name: tampered\n", encoding="utf-8")
    # Dry-run reports the drift without writing.
    drift = wa.converge_runner_workflow(tmp_path, True, apply=False)
    assert any("perk-run.yml: updated" in c for c in drift)
    assert workflow.read_text(encoding="utf-8") == "name: tampered\n"
    # Apply repairs it back to the template.
    wa.converge_runner_workflow(tmp_path, True, apply=True)
    assert workflow.read_text(encoding="utf-8") == wa.PERK_RUN_WORKFLOW
