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
| `gh` | Version 2.48.0 or newer, authenticated | A GitHub account is mandatory for the GitHub workflow. perk reaches GitHub only through the authenticated GitHub CLI; it does not make raw GitHub HTTPS requests. Exhaustive issue reads use `gh api --slurp` (gh 2.48.0); an older gh fails those reads loudly rather than silently truncating. |
| `node` | Version 22 or newer | This is the one tool-version gate in the environment check. The Pi extension relies on Node's native TypeScript type stripping. |
| `pi` | Version 0.87.0 or newer | Pi is the agent harness perk launches. 0.87.0 is the supported minimum: the extension's context-evidence leaf, `/btw`'s side-session seeding, and its thread summarization use Pi's `buildSessionProjection()` session projection and `ModelRegistry.streamSimple`, both added in 0.87.0. perk still enforces no Pi version gate — on an older Pi the extension's hooks fail (`buildSessionProjection is not a function`) and perk's owned guidance is not injected, so upgrade Pi rather than expecting a typed refusal. |
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

## Host SDK bridge

Two of the packages `perk init` wires — `pi-subagents` and `pi-web-access` — ship compiled
JavaScript that Node loads natively, so each would otherwise load its own copy of the Pi SDK
(`@earendil-works/*`, `typebox`) beside the one the running Pi already holds. perk's **host SDK
bridge** redirects exactly those SDK imports, from exactly those two installed packages, onto the
SDK instances the running Pi already loaded. Values and class identity are shared; nothing else
changes.

The bridge is on by default and is active when:

- Pi runs on Node with `module.registerHooks` (Node 22.15 or newer — every Pi-supported Node), and
- Pi was launched from its npm package (the `pi` command), so perk can locate the SDK entry, and
- the two packages are installed under the repo's `.pi/npm/node_modules/`.

Everything else stays unbridged and loads as before: packages Pi loads **before** perk (user-scope
`packages` in `~/.pi/agent/settings.json`, agent-dir `extensions`, extensions passed with `pi -e`),
copies of the two packages installed outside the repo, Bun or compiled Pi builds, and embedded SDK
hosts. perk installs no launcher preload and adds no `NODE_OPTIONS`; `perk init` only keeps perk's
own `packages` entry ahead of the two packages in `.pi/settings.json` so Pi loads perk first
(`perk doctor` reports the order as `settings-wiring` drift; `perk doctor --fix` repairs it).

To disable the bridge, set `PERK_DISABLE_NATIVE_SDK_BRIDGE=1` in the environment of the `perk`
(or `pi`) launch. The value is read once per process: quit and relaunch to change it — `/reload`
does not re-read it. Only the exact value `1` disables.

Where the state shows: `/perk-selfcheck` reports `bridge=<state>` in its summary line and a
`native sdk bridge:` block (the SDK entry it found and the bridged package roots) in its census —
`installed`, `disabled`, `skipped:no-consumers` (neither package installed), or an `unsupported:*`
reason. A `perk: sdk bridge — …` warning appears at session start only when an install was
declined or failed (`declined:*` / `failed:*`); the packages then load their own SDK copies for
that session, and perk otherwise runs normally.

## Version compatibility

The perk CLI and the `@mgiles/perk` Pi extension are expected to have matching versions. A
mismatch produces a soft, non-fatal launch warning. `perk doctor --fix` reconverges the
repo-managed package pin and reinstalls the matching extension.

`pi-subagents` deliberately remains unpinned. `perk doctor` probes the installed package for
the orchestration surfaces perk needs; incompatibility warns loudly but does not fail the
doctor run or offer a fix. This is an early-warning check rather than a version gate.
pi-subagents 0.70.1 is the guidance baseline: `subagent-compat` warns on any other installed
version. The baseline is **source-verified** — perk's engine guidance was re-read against the
installed 0.70.1 package, `perk doctor` and a read-only `perk.scout` lane were exercised on it —
while the live browser-wave half of its re-verification is recorded as owed (see
`docs/design/archive/pi-subagents-0.70.1-reverify.md`); treat it as the version perk's guidance
matches, not as a promise that every interactive flow was driven on it. perk's report definitions
no longer carry the `completionGuard` field that pi-subagents removed in 0.70.1, so a 0.68–0.70.0
engine may fail a report lane whose task text reads as implementation work — upgrade pi-subagents
rather than re-adding the field.

Plannotator 0.27.16 or newer is required by the stack review browser (`/stack-review-browser`,
`perk objective stack review`), which opens Plannotator's static-patch mode over the pinned
combined patch. An older Plannotator ignores the `patchFile` payload field and opens a live local
review of the checkout instead — a silently wrong diff, not a refusal — so check the installed
version (`npm ls @plannotator/pi-extension` under `.pi/npm`) before relying on the stack browser.
Ordinary plan and single-PR browser review have no Plannotator floor beyond what `perk init`
installs.

perk encodes no operating-system gate. Its command and workflow surfaces assume POSIX shell
behavior; the code and docs make no broader platform-support claim.

## Related

- **Learn:** [Get started with perk](../tutorials/get-started.md) — install the toolchain and
  drive one complete workflow in a disposable repository.
- **Do:** [How to set up and verify the remote runner](../how-to/set-up-the-remote-runner.md) —
  provision the optional remote execution surface.
- **Look up:** [Configuration files](./configuration.md) — check committed and per-user config
  keys and their precedence.
