---
title: "Requirements and compatibility"
description: "Check what you need to install perk, which versions are enforced, and how local and remote model access differ."
sidebar:
  order: 3005
---

# Requirements and compatibility

perk depends on a small toolchain around its Python CLI and Pi extension. This page records
which tools are required, where version gates exist, and which credentials belong to local or
remote execution.

## Required tools

| Tool | Requirement | Compatibility detail |
|---|---|---|
| `git` | Required | perk uses git repositories, branches, commits, and worktrees. No minimum git version is enforced. |
| `gh` | Required and authenticated | A GitHub account is mandatory for the GitHub workflow. perk reaches GitHub only through the authenticated GitHub CLI; it does not make raw GitHub HTTPS requests. |
| `node` | Version 22 or newer | This is the one tool-version gate in the environment check. The Pi extension relies on Node's native TypeScript type stripping. |
| `pi` | Required | Pi is the agent harness perk launches. perk does not enforce a separate Pi version gate. |
| `skills` | Required | perk uses the skills CLI to synchronize its workflow skills. perk does not enforce a separate skills version gate. |

`ast-grep` is optional. Its absence produces a warning from `perk init` and `perk doctor`,
but never blocks either command.

## Installing perk

The published CLI requires Python 3.13 or newer. The standard installation command is:

```bash
uv tool install perk
```

`uv` provisions a compatible Python interpreter when one is needed. It installs the `perk`
executable into uv's tool bin, normally `~/.local/bin`; that directory must be on `PATH`.

## Model access

Local perk sessions use Pi's model authentication. perk does not add a second local model-key
configuration layer.

The remote runner reads model access from repository Actions secrets. It requires either
`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`; one is sufficient. The secret is separate from the
runner's GitHub credential.

## Optional surfaces

### Linear issue backend

GitHub is the default issue backend. Linear is optional and stores plans as Linear issues and
objectives as Linear Projects. See [How to switch the issue backend to Linear](../how-to/switch-to-linear.md)
for the configuration path and [Issue backends](./providers-and-backends/issue-backends.md) for
the backend contract.

### Remote runner

The remote runner is optional. A configured repository needs:

- `PERK_GH_PAT`, the repository Actions secret used for authenticated git and GitHub writes;
- one model Actions secret, `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`; and
- no disabling `PERK_ENABLED` repository variable.

`PERK_ENABLED` is an opt-out gate: unset means enabled, while `false` disables remote runs.
See [How to set up and verify the remote runner](../how-to/set-up-the-remote-runner.md) for the
managed workflow and smoke check.

## Version compatibility

The perk CLI and the `@mgiles/perk` Pi extension are expected to have matching versions. A
mismatch produces a soft, non-fatal launch warning. `perk doctor --fix` reconverges the
repo-managed package pin and reinstalls the matching extension.

`pi-subagents` deliberately remains unpinned. `perk doctor` probes the installed package for
the orchestration surfaces perk needs; incompatibility warns loudly but does not fail the
doctor run or offer a fix. This is an early-warning check rather than a version gate.

perk encodes no operating-system gate. Its command and workflow surfaces assume POSIX shell
behavior; the code and docs make no broader platform-support claim.

## Related

- **Learn:** [Get started with perk](../tutorials/get-started.md) — install the toolchain and
  drive one complete workflow in a disposable repository.
- **Do:** [How to set up and verify the remote runner](../how-to/set-up-the-remote-runner.md) —
  provision the optional remote execution surface.
- **Look up:** [Configuration files](./configuration.md) — check committed and per-user config
  keys and their precedence.
