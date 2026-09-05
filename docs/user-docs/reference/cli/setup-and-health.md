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
The `package` group's `extension-install` check verifies perk's own `@mgiles/perk` npm extension is
**physically installed** under `.pi/npm/` at the pinned version. Because pi installs a missing
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
The `package` group also carries the report-only `subagent-compat` check: it reads the installed
pi-subagents version and probes the installed source for the orchestration surfaces perk's
guidance assumes (`workflowScript` orchestration, the `outputSchema` → `structuredOutput`
results, the async completion-notification wake, the supervisor channel, the supervisor
request message type, the v1 extension RPC events, retained
children + the retained-child resume contract, the statement-body explicit-return script
wrapper, the completion-receipt surfaces — the wait-completion projection, the wait tool's
`details.completions`, and the serialized workflow child `runId` — and the
streaming-wave delivery-chain surfaces: session-scoped supervisor delivery, the typed child
supervisor-channel config, the in-process async workflow host, and the omitted-async await
semantics for workflow children — plus the intercom-bridge tool-delivery surface, the explicit
acceptance-disable surface, and invocation-local skill mechanics the
report-wave spawn contract relies on: workflow-item `skill`, agent `skillPath`, local-path
precedence over global name resolution, and async skill injection). One **behavior arm** runs
after the substring probes: the installed engine's own `validateWorkflowScript` is executed
over perk's bundled representative wave script, so a validator that rejects what perk's
renderer emits joins the divergences; when the arm cannot evaluate (no `node`, a missing
fixture, a failed spawn) the detail carries a visible `behavior probe skipped (…)` note and
the status is unaffected. When the package is
not installed (pi lazy-installs it at launch) the check is `info` — compatibility is simply not
evaluated. On any divergence it warns **loudly** but never fails, and there is no `--fix` arm —
pi-subagents deliberately stays unpinned, so the check is an early-warning surface, not an
enforcement gate.
The package group also carries a report-only `ponytail-compat` check for the managed internal
review dependency. A lazy install that is not present yet is `info`. When installed, doctor verifies
package identity, the `./skills` export, both exact `SKILL.md` files, and their `ponytail` /
`ponytail-review` frontmatter names. Divergence is a warning, never a failure, and has no `--fix`
arm because Perk preserves operator source pins. Set the managed entry's source to known-good
`npm:@dietrichgebert/ponytail@4.9.0`, run `perk init`, and restart the Perk/Pi session. Runtime
review-wave preflight is the enforcement boundary: an incompatible Ponytail lane remains explicitly
uncovered rather than resolving a same-named skill elsewhere.
The `package` group also carries the report-only `subagent-bridge-config` check: it reads
`subagents.intercomBridge.mode` from both pi settings scopes — the project `.pi/settings.json`
and the user-global `~/.pi/agent/settings.json` — and warns (never fails, no `--fix` arm — perk
neither sets nor manages the key) when either scope sets it to `"off"` or `"fork-only"`. Either
value silently disables pi-subagents' supervisor channel for perk's fresh-context wave children,
so perk's live-streaming review flows degrade to completion-only; remove the key (or set it to
`"always"`) in the named settings file to restore streaming.
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
