"""The managed GitHub Actions runner artifact (Objective #137 Node 2.2; contracts.md §8.14)."""

from pathlib import Path

import yaml

from perk import workflow_artifacts as wa
from perk.runner import GITHUB_ACTIONS_WORKFLOW


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
    assert set(inputs) == {"run_id", "stage", "plan", "base"}
    assert inputs["run_id"]["required"] is True
    assert inputs["stage"]["required"] is True
    assert inputs["plan"]["required"] is True
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


def test_composite_action_installs_perk_and_pi():
    body = wa.remote_setup_action(self_repo=False)
    doc = yaml.safe_load(body)
    assert doc["runs"]["using"] == "composite"
    assert "uv tool install" in body  # perk (the exterior)
    assert "@earendil-works/pi-coding-agent" in body  # pi (the interior)
    assert "npm ci" in body  # the Node worker's peer deps


def test_composite_action_install_is_self_vs_consumer_aware():
    # The self-repo dogfoods the code under test; a consumer installs the published distribution.
    assert "uv tool install --from . perk" in wa.remote_setup_action(self_repo=True)
    assert "uv tool install perk" in wa.remote_setup_action(self_repo=False)
    assert "--from ." not in wa.remote_setup_action(self_repo=False)


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
