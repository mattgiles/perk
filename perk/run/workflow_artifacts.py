"""The GitHub Actions runner artifact (contracts.md §8.14).

A `--remote` launch of a drivable stage is a real drive (§8.13): the Python plane mints a
perk ``run_id``, persists the ``run_id → plan`` linkage, verifies it, then triggers a
``workflow_dispatch`` for the workflow file ``perk-run.yml`` (``runner.GITHUB_ACTIONS_WORKFLOW``),
verifying the run by matching the ``run_id`` embedded in the run-name. *This* module is the runner
side: the **managed** workflow + its composite setup action, installed by ``perk init`` and repaired
by ``perk doctor --fix`` (a ``ManagedConvergence`` in
:func:`perk.convergence.init.managed_convergences`).

The workflow checks out the plan branch, installs perk + pi (the composite action), then runs
``perk run-worker`` (the CI positioning + drive entrypoint, :mod:`perk.run.run_worker`) which
materializes the worktree and spawns the Node headless worker.

The templates are authored as code (string constants), not packaged data — writing them is a pure
file convergence, so there is no wheel-data surface to guard. The workflow file MUST honor §8.13's
input contract: a ``run-name`` embedding ``${{ inputs.run_id }}``; typed ``workflow_dispatch``
inputs ``run_id``/``stage``/``plan``/``base``; a per-plan ``concurrency`` group.
"""

from pathlib import Path

from perk import __version__
from perk.run.runner import GITHUB_ACTIONS_WORKFLOW

# The two managed files (repo-relative). The composite action lives at a fixed local path the
# workflow references as `./.github/actions/perk-remote-setup`.
RUNNER_WORKFLOW_PATH = f".github/workflows/{GITHUB_ACTIONS_WORKFLOW}"
REMOTE_SETUP_ACTION_PATH = ".github/actions/perk-remote-setup/action.yml"

# The PAT secret the runner checks out + reports with (a doctor readiness check verifies it; named
# here so the workflow and that check agree). Model credentials are resolved by the Node worker's
# env-var key resolution — passed through but not perk-managed here.
RUNNER_PAT_SECRET = "PERK_GH_PAT"

# The opt-out repo variable: set `PERK_ENABLED=false` to disable
# the runner without removing the managed workflow.
RUNNER_ENABLED_VAR = "PERK_ENABLED"

PERK_RUN_WORKFLOW = """\
# Managed by `perk init` (repaired by `perk doctor --fix`) — do not edit by hand.
# The GitHub Actions runner for a perk `--remote` drive (Objective #137 Node 2.2; contracts.md
# §8.14). The dispatcher (perk/run/runner.py GitHubActionsRunner) verifies the run by matching
# the perk `run_id` embedded in `run-name`, so the run-name MUST carry `${{ inputs.run_id }}`.
name: perk-run
run-name: "perk ${{ inputs.stage }} · plan #${{ inputs.plan }} · ${{ inputs.run_id }}"

on:
  workflow_dispatch:
    inputs:
      run_id:
        description: "perk run_id (ULID) — correlation key, embedded in run-name for discovery"
        required: true
        type: string
      stage:
        description: "Stage to drive headlessly (implement | address)"
        required: true
        type: string
      plan:
        description: "Plan issue number"
        required: true
        type: string
      base:
        description: "Base branch the plan branch targets"
        required: true
        type: string
      smoke:
        description: "Smoke mode: validate secrets + confirm runner start, then exit (no drive)."
        required: false
        default: "false"
        type: string

# One in-flight run per plan; a newer dispatch supersedes an older one (mirrors erk's
# implement-plan-${{ … }} group).
concurrency:
  group: perk-run-${{ inputs.plan }}
  cancel-in-progress: true

jobs:
  drive:
    if: vars.PERK_ENABLED != 'false'
    runs-on: ubuntu-latest
    timeout-minutes: 60
    permissions:
      contents: write
      pull-requests: write
      issues: write
    steps:
      - name: Validate required secrets
        env:
          PERK_GH_PAT: ${{ secrets.PERK_GH_PAT }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          if [ -z "$PERK_GH_PAT" ]; then
            echo "::error::PERK_GH_PAT secret is missing; add a repo-scoped PAT secret."
            exit 1
          fi
          if [ -z "$ANTHROPIC_API_KEY" ] && [ -z "$OPENAI_API_KEY" ]; then
            echo "::error::No model key set; add ANTHROPIC_API_KEY or OPENAI_API_KEY."
            exit 1
          fi

      - name: Smoke check
        if: inputs.smoke == 'true'
        run: echo "perk smoke ok — secrets validated, runner reachable (no stage drive)"

      - uses: actions/checkout@v4
        if: inputs.smoke != 'true'
        with:
          token: ${{ secrets.PERK_GH_PAT }}
          fetch-depth: 0

      - uses: ./.github/actions/perk-remote-setup
        if: inputs.smoke != 'true'

      - name: Check out the plan branch
        if: inputs.smoke != 'true'
        env:
          GH_TOKEN: ${{ secrets.PERK_GH_PAT }}
          PLAN: ${{ inputs.plan }}
        run: |
          branch="plan-$PLAN"
          git fetch origin "$branch"
          git checkout "$branch"
          # Reset to the remote tip: the plan job may have pushed commits after checkout resolved
          # github.sha at dispatch time.
          git reset --hard "origin/$branch"

      - name: Drive the stage headlessly
        if: inputs.smoke != 'true'
        env:
          PERK_GH_PAT: ${{ secrets.PERK_GH_PAT }}
          GH_TOKEN: ${{ secrets.PERK_GH_PAT }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          perk run-worker \\
            --run-id "${{ inputs.run_id }}" \\
            --stage "${{ inputs.stage }}" \\
            --plan "${{ inputs.plan }}" \\
            --base "${{ inputs.base }}"
"""

# The `perk` install command differs by repo kind: the perk self-repo dogfoods the code under test
# (`--from .`); a consumer installs the published PyPI distribution pinned to the exact perk version
# that wired the repo. The pin is baked into `action.yml` at `perk init` time (re-converged by
# `perk doctor --fix`), so the remote runner reproduces the same perk the local CLI ran.
_PERK_INSTALL_SELF = "uv tool install --from . perk"
_PERK_INSTALL_CONSUMER = f"uv tool install perk=={__version__}"

# The Node worker deps step differs by repo kind. The self-repo has the `package.json` + lockfile +
# the `@earendil-works/*` devDeps the worker resolves, so `npm ci` works. A consumer checkout has no
# worker clone (`.pi/git` + `.pi/npm` are gitignored, and nothing in the composite runs `pi` to
# trigger pi's git-package `npm install`), so consumer remote drive genuinely cannot run end-to-end
# until worker-clone reconciliation + dep resolution are wired. Until then the consumer step is
# a loud, explicit deferral instead of a silently-broken `npm ci`.
_WORKER_DEPS_SELF = "npm ci"
_WORKER_DEPS_CONSUMER = (
    'echo "::error::perk remote drive for consumer repos lands in Node 2.4 '
    '(the .pi/git worker-clone + Node peer-dep resolution are not wired yet)."; '
    "exit 1"
)

_REMOTE_SETUP_ACTION_TEMPLATE = """\
# Managed by `perk init` (repaired by `perk doctor --fix`) — do not edit by hand.
# The composite setup for a perk remote drive (Objective #137 Node 2.2): install the two pinned
# toolchains, then perk (the exterior CLI) + pi (the interior the Node worker drives) + the Node
# deps `extension/workerMain.ts` resolves its peer packages from.
name: perk-remote-setup
description: "Install perk + pi and the Node worker deps for a headless remote drive."
runs:
  using: composite
  steps:
    - name: Set up uv (+ Python 3.13)
      uses: astral-sh/setup-uv@v5
      with:
        python-version: "3.13"

    - name: Set up Node 22
      uses: actions/setup-node@v4
      with:
        node-version: "22"

    - name: Install perk
      shell: bash
      run: {perk_install}

    - name: Install pi
      shell: bash
      run: npm install -g @earendil-works/pi-coding-agent

    - name: Install Node worker deps
      shell: bash
      run: {worker_deps}

    - name: Configure git identity
      shell: bash
      run: |
        git config --global user.name "perk[bot]"
        git config --global user.email "perk[bot]@users.noreply.github.com"
"""


def remote_setup_action(self_repo: bool) -> str:
    """The composite setup action body for this repo kind (self-repo dogfoods the local code)."""
    install = _PERK_INSTALL_SELF if self_repo else _PERK_INSTALL_CONSUMER
    worker_deps = _WORKER_DEPS_SELF if self_repo else _WORKER_DEPS_CONSUMER
    return _REMOTE_SETUP_ACTION_TEMPLATE.format(perk_install=install, worker_deps=worker_deps)


def _converge_file(path: Path, content: str, *, label: str, apply: bool) -> list[str]:
    """Full-file managed convergence: write ``content`` when the file is absent or has drifted."""
    current = path.read_text(encoding="utf-8") if path.is_file() else None
    if current == content:
        return []
    verb = "created" if current is None else "updated"
    if apply:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return [f"{label}: {verb}"]


def converge_runner_workflow(root: Path, self_repo: bool, *, apply: bool = True) -> list[str]:
    """Converge both managed runner files (the workflow + its composite setup action).

    Full-file managed (like the settings/gitignore/AGENTS blocks): ``init`` writes them, ``perk
    doctor`` dry-runs for drift (``apply=False``) and repairs it (``apply=True``). A hand-edited
    file reads as drift and is overwritten back to the template — these are perk-owned artifacts.
    The composite action's ``perk`` install command is self-vs-consumer aware (``self_repo``).
    """
    changes: list[str] = []
    changes += _converge_file(
        root / RUNNER_WORKFLOW_PATH, PERK_RUN_WORKFLOW, label=RUNNER_WORKFLOW_PATH, apply=apply
    )
    changes += _converge_file(
        root / REMOTE_SETUP_ACTION_PATH,
        remote_setup_action(self_repo),
        label=REMOTE_SETUP_ACTION_PATH,
        apply=apply,
    )
    return changes
