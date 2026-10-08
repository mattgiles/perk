---
title: "Requirements and compatibility"
description: "Check what you need to install perk, which versions are enforced, and how local and remote model access differ."
sidebar:
  order: 3005
---

# Requirements and compatibility

perk depends on a small toolchain around its Python CLI and Pi extension. This page records
which tools are required, where version floors are enforced, and which credentials belong to
local or remote execution.

## Required tools

| Tool | Requirement | Compatibility detail |
|---|---|---|
| `git` | Required | perk uses git repositories, branches, commits, and worktrees. No minimum git version is enforced. |
| `gh` | Version 2.48.0 or newer, authenticated | A GitHub account is mandatory for the GitHub workflow. perk reaches GitHub only through the authenticated GitHub CLI; it does not make raw GitHub HTTPS requests. Exhaustive issue reads use `gh api --slurp` (gh 2.48.0); an older gh fails those reads loudly rather than silently truncating. |
| `node` | Version 22.19.0 or newer | Pi's own `engines.node` floor; `perk init`/`perk doctor` compare the full version (not just the major), and an older or unreadable Node fails the environment check. The Pi extension relies on Node's native TypeScript type stripping. |
| `pi` | Version 1.0.0 or newer | Pi is the agent harness perk launches. perk refuses to launch a session (plain, staged or resumed) on an older Pi, a 1.0.0 prerelease, or a `pi` whose `--version` cannot be read, naming the executable, the observed version, the required version and the upgrade command (`npm install -g @earendil-works/pi-coding-agent`). `perk init` and `perk doctor` report the same requirement. |
| `skills` | Required | perk uses the skills CLI to synchronize its workflow skills. perk does not enforce a separate skills version gate. |
| `cloc` | Required | `perk pr submit` and `perk pr stats` count the PR's change stats with it. No version gate is enforced. A missing `cloc` fails `perk init` / `perk doctor` like any required tool, but submit degrades to an "unavailable" note in the PR body rather than failing. |

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
- at least one of the two packages is installed under the repo's `.pi/npm/node_modules/` — each
  installed package is bridged; a missing one is only noted in the selfcheck detail.

Everything else stays unbridged and loads as before: packages Pi loads **before** perk (user-scope
`packages` in `~/.pi/agent/settings.json`, agent-dir `extensions`, extensions passed with `pi -e`),
copies of the two packages installed outside the repo, Bun or compiled Pi builds, and embedded SDK
hosts. perk installs no launcher preload and adds no `NODE_OPTIONS`; `perk init` only keeps perk's
own `packages` entry ahead of the two packages in `.pi/settings.json` so Pi loads perk first
(`perk doctor` reports the order as `settings-wiring` drift; `perk doctor --fix` repairs it).

To disable the bridge, set `PERK_DISABLE_NATIVE_SDK_BRIDGE=1` in the environment of the `perk`
(or `pi`) launch. The value is read once per process: quit and relaunch to change it — `/reload`
does not re-read it. Only the value `1` disables (surrounding whitespace is ignored; `0`, `true`
or an empty value leave the bridge on).

Where the state shows: `/perk-selfcheck` reports `bridge=<state>` in its summary line and a
`native sdk bridge:` block (the SDK entry it found and the bridged package roots) in its census —
`installed`, `disabled`, `skipped:no-consumers` (neither package installed), or an `unsupported:*`
reason. A `perk: sdk bridge — …` warning appears at session start in two cases only, and perk
otherwise runs normally:

- **failed** (`failed:*`) — this perk copy could not install the bridge; the packages load their
  own SDK copies for that session.
- **declined** (`declined:*`) — another perk copy in the same process already bridged a different
  Pi entry (or a different bridge version); that earlier bridge stays active for the packages it
  already serves, and this perk copy installs none.

## Version compatibility

**Host floor.** perk declares its minimum supported host versions once — Pi ≥ 1.0.0 and
Node ≥ 22.19.0 — in the bundled `shared/host-floor.yaml`, and compares against them with semver
precedence. Every local launch (bare `perk`, a stage launch such as `perk plan`, `perk resume`)
runs `pi --version` once before anything else in the launch's exec phase and ends in one of three
outcomes: *admitted* (the version is at or above the floor — later releases such as 1.0.3 or 1.10.0
are admitted), *unsupported* (`pi_version_unsupported` —
an older version or a prerelease of the floor such as `1.0.0-rc.1`), or *unverifiable*
(`pi_version_unverifiable` — the command failed, timed out after 20 s, or printed something that
is not a version). Both refusals exit 1 and there is no override. `--dry-run` previews never
probe, and `perk init`, `perk doctor` and `--help` are never gated by the launch check — the
environment checks report the floor instead, so the repair path stays reachable. The managed
remote runner installs exactly Pi 1.0.0 for both the global `pi` CLI and the consumer worker's
SDK, and sets up exactly Node 22.19.0. Pi 1.0.0 is the enforced host floor; its certification
record, `docs/design/archive/pi-1.0.0-certification.md`, is still waiting on its PR-door rows.

**The same floor at the SDK boundary.** The perk extension checks the Pi it is loaded into (the
SDK's `VERSION`) before it registers anything, and refuses to load on an older Pi or a prerelease
of the floor such as `1.0.0-rc.1`. Pi reports that as a failed extension load whose message
carries perk's refusal (`perk requires Pi >= 1.0.0; the Pi running this session is <version> …`)
and, on Pi 0.99 and 1.0, exits with its `pi -ne` hint — so a plain `pi` in a perk-wired repo
never runs with a partial set of perk tools. The headless worker checks the SDK it loaded the same
way, before any extension, resource, provider or model work, and ends the run with a typed
failure (`pi_version_unsupported` or `pi_version_unverifiable` in its run outcome); a remote
run's outcome note on the plan issue shows the failed status, the terminal signal and the
refusal summary. The three observations — the `pi` on your PATH, the extension's Pi, the
worker's SDK — are checked independently against the one minimum and need not be equal: a
passing `pi --version` says nothing about the other two. `/perk-selfcheck` shows the admitted
version as `host sdk: <version> (floor >= 1.0.0)`.

The perk CLI and the `@mgiles/perk` Pi extension are expected to have matching versions. A
mismatch produces a soft, non-fatal launch warning. `perk doctor --fix` reconverges the
repo-managed package pin and reinstalls the matching extension.

`pi-subagents` is pinned to 0.75.0: `perk init` writes `npm:pi-subagents@0.75.0` into
`.pi/settings.json` and rewrites an existing unpinned or differently pinned entry in place, and
`perk doctor` reports such an entry as `settings-wiring` drift that `perk doctor --fix` repairs.
The pin exists because perk's report waves send the inline script text under pi-subagents' RPC
spawn key `script`, which releases before 0.74.0 do not accept; 0.75.0 is also the first release
whose background children start on Pi 1.0.0. Pi installs the version that the checkout's own
committed `.pi/settings.json` names, at launch. An existing repo gets the new entry from
`perk init` or `perk doctor --fix` after you upgrade perk. An older branch or worktree keeps its
own committed entry (and its older perk) until it is rebased.

perk's waves need pi-subagents' workflow scripts. A `disabledFeatures` list in pi-subagents'
`config.json` that contains `workflow-scripts` fails every wave with the engine's own message
naming that setting. Per the engine source, `missions` (perk spawns with `mission: false`) and
`extension-bindings` (every perk lane carries its read-only restriction packet) also refuse
every wave.

Separately, `perk doctor`'s `subagent-compat` check compares the installed version with the
version perk's engine guidance was last re-verified against, and warns on any other version. It
is an early-warning check that never fails the doctor run. The stamp is currently 0.75.0: the
source was re-verified, the Pi 1.0.0 trust matrix passed, and the doctor and scout waves and both
browser-door waves (the plan door and the PR door) passed on the Pi 0.99.2 host. See
`docs/design/archive/pi-subagents-0.75.0-reverify.md`. On the Pi 1.0.0 host, the plan door
passed and the PR door is still pending in `docs/design/archive/pi-1.0.0-certification.md`.

Plannotator 0.27.16 or newer is required by the stack review browser (`/stack-review-browser`,
`perk objective stack review`), which opens Plannotator's static-patch mode over the pinned
combined patch. An older Plannotator ignores the `patchFile` payload field and opens a live local
review of the checkout instead — a silently wrong diff, not a refusal — so check the installed
version (`npm ls @plannotator/pi-extension` under `.pi/npm`) before relying on the stack browser.
Ordinary plan and single-PR browser review have no Plannotator floor beyond what `perk init`
installs.

perk's browser doors mirror Plannotator's remote detection and port selection as of
`@plannotator/pi-extension@0.27.22` (`server/network.ts`, `generated/port-range.ts`). A later
Plannotator that changes that rule makes the doors and Plannotator disagree on the port — a loud
failure (the readiness probe times out and the door degrades), never a silent one.

perk encodes no operating-system gate. Its command and workflow surfaces assume POSIX shell
behavior; the code and docs make no broader platform-support claim.

## Related

- **Learn:** [Get started with perk](../tutorials/get-started.md) — install the toolchain and
  drive one complete workflow in a disposable repository.
- **Do:** [How to set up and verify the remote runner](../how-to/set-up-the-remote-runner.md) —
  provision the optional remote execution surface.
- **Look up:** [Configuration files](./configuration.md) — check committed and per-user config
  keys and their precedence.
