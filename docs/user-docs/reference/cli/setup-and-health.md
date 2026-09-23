---
title: "Setup and health"
description: "Exact reference for perk init, perk doctor, and the doctor workflow remote-readiness checks."
sidebar:
  order: 3011
---

# Setup and health

This page holds the exact reference for the setup and health commands: `perk init`
(scaffold/converge) and the `perk doctor` group, including the `doctor workflow` remote-runner
checks. For the full command map and shared conventions, start at the
[CLI commands hub](../cli.md).

### `perk init`

Scaffold or converge the current repo for perk (idempotent; safe to re-run). Wires
`.pi/settings.json` and the borrowed package set, creates the `.perk/workflow/` cache, scaffolds
config, manages `.gitignore` and the `AGENTS.md` managed block, and verifies GitHub access
without mutating it. It converges a skills-manifest fragment (`.agents/manifest.d/perk.yaml`)
declaring perk's own skills **plus a set of required external skills** (from upstream sources),
materialized via the `skills` CLI; a missing required skill fails `init` (and `doctor`). It also
checks for the optional `ast-grep` CLI (structural code search) —
non-fatal: a missing `ast-grep` is a `⚠️` warning, never a blocking failure. Init also writes the
committed `.perk/required-perk-version` pin (the repo's required perk version); `perk doctor`
reports a missing or stale pin as drift and `--fix` rewrites it to the running CLI's version.
When your running `perk` CLI's version differs from that committed pin, interactive `perk`
invocations also print one soft stderr warning (never fatal). It is suppressed for
`--version`/`--help`, any `--json`/machine-output command, the `run-worker` worker path, non-TTY
stderr, `CI`, outside a git repo, and when `PERK_SKIP_VERSION_CHECK=1` (any non-empty value) is
set; the same opt-out also silences the post-upgrade notice (see
[`perk release-notes`](./remote-and-utility.md#perk-release-notes)).
Init also records `.perk/managed-state.toml` — a machine-written version+hash record of every
managed artifact, written as a convergence side effect (commit it; a converged repo re-runs
without touching it).

Run **interactively**, `perk init` is also a guided onboarding flow. It offers to install the
missing *supported* required tools — `gh` via `brew install gh` (when brew is on PATH), `pi` via
`npm install -g @earendil-works/pi-coding-agent` (when node ≥ 22 is present), and `skills` via
its official installer script on macOS / `go install` elsewhere (`git` and `node` stay
guide-only — the failure report carries their install commands). It offers to run `gh auth
login` when the GitHub CLI is unauthenticated, checks your git commit identity
(`user.name`/`user.email`) and prompts to set it (globally by default, or repo-local), and —
when the committed `[issues] backend` is `"linear"` with a `team` and no API key resolves —
prompts for a Linear API key (hidden input), validates it against Linear, and stores it in the
gitignored `.perk/local.toml` (tightened to mode `0600`; the write refuses unless the file is
provably untracked and gitignored). Every gesture is gap-driven (a healthy host prompts for
nothing), and **every prompt and mutation is disabled** by `--no-interactive`, a non-TTY stdin,
or `--json` (a machine surface — nothing may interleave with the stdout JSON); the git-identity
*check* itself still runs on every verified init — non-interactively it only degrades to a
report warning carrying the manual `git config` commands.

`--force` re-seeds
the user-editable config to defaults; `--no-interactive`
never prompts (CI/supervisor); `--json` emits a machine-readable report.

### `perk doctor`

Diagnose the perk-managed repo, reporting a grouped health view. `--fix` re-converges drifted
managed pieces (and seeds missing config) without ever mutating GitHub or overwriting your config
edits. `--fix` also **reconciles perk's own npm version pin** (`npm:@mgiles/perk`) in
`.pi/settings.json` to the version this perk wants (e.g. a stale `npm:@mgiles/perk@0.0.0` → the
pinned `@{version}`). perk's own extension is delivered as the pinned `npm:@mgiles/perk` install
(below); the older `git:`-clone delivery path has been retired. If your repo was previously on the
git clone, `perk doctor --fix` **migrates it forward** by removing the now-orphaned
`.pi/git/<host>/<path>` clone (filesystem-only; idempotent — a no-op once gone).
`settings-wiring` also converges the **load order** of `.pi/settings.json` `packages`: perk's own
entry is kept ahead of `npm:pi-subagents` and `npm:pi-web-access`, because perk's host SDK bridge
(see [Requirements and compatibility](../requirements-and-compatibility.md#host-sdk-bridge)) only
serves packages Pi loads after perk. perk listed after either package is `settings-wiring` drift —
`fail`, with the detail naming the move — and `perk doctor --fix` (like `perk init`) moves perk's
entry to just before the first of the two, leaving every other entry's relative order unchanged.
The `package` group's `extension-install` check verifies perk's own `@mgiles/perk` npm extension is
**physically installed** under `.pi/npm/` at the pinned version (the install also carries perk's
`perk.*` agent definitions, which pi-subagents discovers as package agents). Because pi installs a missing
project-scope `npm:` package lazily and unlocked at launch, perk owns the install: `perk init`
installs the pin (and reinstalls it on version drift), `perk doctor` **fails** when the install is
absent or its version differs from the pin and `perk doctor --fix` installs/reinstalls
`npm:@mgiles/perk@{version}` (`npm install … --prefix .pi/npm --legacy-peer-deps`, under a cross-process
lock), and `perk <stage>` **warms** the install before every local launch — installing it if absent
under the same lock — so concurrent sessions never race pi's unlocked lazy install. All npm work is
best-effort and non-fatal: a not-yet-published pin or flaky network is swallowed (init/doctor/launch
never crash; pi's lazy install remains the fallback). The self-repo (which wires the local `..`
package) is exempt.
The `package` group also carries the report-only `cli-version` check: it compares the running
`perk` CLI's version against the repo's committed `.perk/required-perk-version` pin and **warns**
(never fails — a running CLI cannot install itself) on a mismatch. There are two remedies:
upgrade perk (e.g. `uv tool upgrade perk`) to match the repo, or — if the *pin* is the stale
side — re-run `perk init` / `perk doctor --fix`, which reconverges the pin to this CLI (the
`required-perk-version` managed check owns that file drift and fails alongside the warn on a
mismatch, deliberately).
The `package` group also carries the report-only `resource-overrides` check: it warns (never
fails, and `--fix` never touches it) when a pi resource override reaches perk's own resources —
either perk's `packages` entry rewritten to object form with filter keys (filtering perk's own
extension breaks every interactive stage session), or a `-`/`!` disable pattern in the top-level
`extensions`/`skills`/`prompts`/`themes` override arrays that mentions `@mgiles/perk` or a perk
skill name (a substring heuristic — perk does not reimplement pi's filter semantics). Review the
overrides via `pi config -l`; see
[How to scope Pi resources per project](../../how-to/scope-pi-resources-per-project.md).
The `package` group also carries the report-only `subagent-engine` check (never `fail`). The
borrowed pi-subagents engine's presence is owned by `settings-wiring`, and perk's `perk.*` agent
definitions ship inside the perk extension package — pi-subagents discovers them as package agents
(`/subagents` lists them as `[package]`), so on a healthy repo the check is `ok` and its detail
enumerates the shipped definitions. It **warns** when a `.pi/agents/perk/` directory is left over
from an older perk version that wrote the definitions into the repo: pi-subagents ranks project
definitions above package ones, so those stale copies silently shadow the shipped definitions until
removed; the warning's remediation says exactly what `--fix` will do. `perk doctor --fix` removes
the directory **filesystem-only** when it is the flat set of `.md` files older perk versions wrote
and every one of them has a shipped replacement in the installed extension (taking
`.pi/agents/.gitkeep` along only when it is the sole leftover) — a symlink at `.pi`, `.pi/agents`
or `.pi/agents/perk`, a subdirectory, any other file, or a definition with no shipped counterpart
(the extension not installed yet, or a name perk no longer ships) makes it refuse the whole
removal and name the cause for you to handle by hand, so no `perk.*` agent is ever left without a
definition. You commit the deletion; the shipped definitions serve from the next spawn, no session
restart needed. Should an individual file fail to delete after the preflight passed, the error is
reported and the next `--fix` picks up where it left off.
The `package` group also carries the report-only `subagent-compat` check: it reads the installed
pi-subagents version. `info` when the package is not installed (pi lazy-installs it at launch);
`warn` — never `fail`, no `--fix` — when the version is unreadable or differs from the version
perk's guidance was verified against (`_SUBAGENTS_GUIDANCE_VERIFIED_VERSION`). pi-subagents stays
unpinned, so the check is an early-warning surface, not a gate: a mismatch says "re-verify"
(`docs/developers/pi-subagents-reverify.md`), not "broken".
The `package` group also carries the report-only `subagent-package-scope` check: it reads the
user-scope `settings.json` in the launch-precedence agent dir (`PI_CODING_AGENT_DIR` → `[pi]
agent_dir` → `~/.pi/agent`) beside the project `.pi/settings.json`, and warns — never fails, no
`--fix` arm — when both list `pi-subagents` (matched by npm identity, so a pinned
`npm:pi-subagents@0.67.0` or an object-form `{"source": "npm:pi-subagents"}` entry counts). A
user entry counts only when it actually loads the package's extensions under pi's resource
filters: `"extensions": []` disables them all, and `"autoload": false` loads nothing unless an
`extensions` pattern positively enables one — a non-empty regular pattern list is treated as
loading (perk does not reimplement pi's glob matching). A project entry with `"autoload":
false` never counts — pi keeps that delta pair on purpose, so nothing is orphaned. perk
converges `npm:pi-subagents` into the **project** scope; a second copy in the user scope is
harmless to pi's package loading (it dedupes by identity, project wins) but not to perk's waves:
pi 0.85.1 loads the user-scope extensions *before* project trust resolves and then drops the
user copy from the final set **without invalidating it**, and pi-subagents' RPC bridge
subscribes on `pi.events`, so the orphan — which never receives `session_start` — keeps
answering perk's wave RPC with `no_active_session` a few milliseconds before the project instance
succeeds. perk now holds that reply until the live reply arrives and warns **once per extension
activation** in the session (`perk: waves — A duplicate pi-subagents extension is loaded …`),
but the duplicate still costs a listener and the warning, so the check names both files (as
absolute paths, even for a relative `PI_CODING_AGENT_DIR`) and the remediation: remove the user-scope entry (`pi remove npm:pi-subagents` when that file is
pi's default `~/.pi/agent/settings.json` — `pi remove` writes user scope by default; otherwise
edit the file), then **restart** every running pi session in this repo — `/reload` re-runs the
same two-phase load and does not clear the orphan. `info` when the agent dir cannot be resolved
(a broken `[pi] agent_dir` is the `config` check's finding); `warn … not evaluated` naming the
path and the cause (not readable, not valid UTF-8, not valid JSON, or not a JSON object) when the
user settings cannot be evaluated; a warn deferring to `settings-wiring` when the project settings
cannot; `ok` otherwise, saying which scope(s) carry the entry ("project scope only", "user scope
only", or "not configured in either scope" — the last is `settings-wiring`'s finding).
The package group also carries a report-only `ponytail-compat` check for the managed internal
review dependency. A lazy install that is not present yet is `info`. When installed, doctor verifies
package identity, the `./skills` export, both exact `SKILL.md` files, and their `ponytail` /
`ponytail-review` frontmatter names. Divergence is a warning, never a failure, and has no `--fix`
arm because Perk preserves operator source pins. Set the managed entry's source to known-good
`npm:@dietrichgebert/ponytail@4.9.0`, run `perk init`, and restart the Perk/Pi session. Runtime
review-wave preflight is the enforcement boundary: an incompatible Ponytail lane remains explicitly
uncovered rather than resolving a same-named skill elsewhere.
Beyond these doctor checks, a local `perk <stage>` launch also surfaces a **soft, non-fatal warning
at session start** when the `@mgiles/perk` extension that pi actually loaded differs in version from the
running `perk` CLI (pi can lazy-load a stale `npm:` package), pointing you at `perk doctor --fix` to
reinstall the pinned version. It is silent when versions match and for an ad-hoc `pi` launch.
The `state` group carries the report-only `artifact-health` check: it classifies every managed
artifact against the recorded `.perk/managed-state.toml` state as `up-to-date`,
`not-installed`, `locally-modified` (you changed it since perk last wrote it — a fork that
`--fix` would overwrite), `changed-upstream` (untouched by you, but perk's desired content moved
— e.g. a version upgrade), or `state-missing` (drift with no recorded hash to arbitrate). It is
diagnostic only (`ok`/`info`/`warn`, never `fail`) — the managed dry-run checks stay
authoritative for pass/fail — and the per-artifact rows appear in the `--json` report's
`artifact_health` array. `--fix` reconverges the drifted artifacts and then re-records the state
file.
The
`environment` group reports required tools as `fail` when missing and optional tools
(e.g. `ast-grep`) as `warn`. `--verbose` shows every check, not just failures; `--json` emits a machine-readable report.
This is a group whose bare invocation runs the health report.

### `perk doctor workflow`

Diagnose the remote-runner subsystem: static prerequisites plus an optional live CI smoke.

### `perk doctor workflow check`

Run the static remote-runner prerequisite checks (GitHub readiness, runner prereqs, the managed
workflow file). `--verbose` shows every check; `--json` emits a machine-readable report.

### `perk doctor workflow smoke-test`

Dispatch a throwaway CI run (a smoke short-circuit) to prove the runner is live. `--wait` polls
the dispatched run to completion; `--verbose` shows every prereq check; `--json` emits a
machine-readable report.

## Related

- **Do:** [How to diagnose a perk repo](../../how-to/diagnose-a-perk-repo.md) — read a failing doctor report and apply the bounded repair.
- **Do:** [How to configure and verify CI checks](../../how-to/configure-and-verify-ci-checks.md) — author the check rows init and doctor converge.
- **Look up:** [Configuration files](../configuration.md) — the tables `perk init` writes and `perk doctor` verifies.
