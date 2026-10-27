---
title: init/doctor division, managed-convergence SSOT, and gitignore untrack pattern
read_when: You are adding a managed piece (a doctor check), a host-floor/env row (advisory tier, Node line floors, pi repair), write admission, the managed-state file, a doctor migration, probe, or repair
cluster: config-and-convergence
---

# `init` / `doctor` division

## Distillation

- `perk init` converges forward (idempotent desired state, never migrations); `doctor --fix`
  repairs legacy oddities; bare `doctor` is the report-only diagnostic layer — "The split".
- Doctor checks derive from the managed-convergence declarations — NEVER hand-author a parallel
  check; everything not derived from a convergence is report-only, verify-gated or offline —
  "Managed convergence is the SSOT for doctor checks", "The current check scope".
- Any new `Check.group` value — managed or report-only — needs `GROUP_ORDER` inclusion plus a
  render-visibility test — "`doctor`'s human output renders only the `GROUP_ORDER` groups".
- Growing `managed_artifacts()` requires the three-part eligibility test — "The managed-artifact
  set"; an unreadable config makes destructive reconciliation a NO-OP (contract §8.10) — "An
  unreadable config makes destructive reconciliation a NO-OP".
- Network I/O lives in the `fix AND verify`-gated repair gesture (incl. `env.repair_pi`), never a
  `ManagedConvergence` — "Network repairs live in the verify-gated repair gesture"; `init`/`--fix`
  refuse before any write on a foreign or outdated perk — "Write admission".
- Environment checks: optional and advisory tiers, fixture coverage at the actual primitive,
  required-only filtering, absent + version-invalid remediation — "The optional `EnvCheck` tier".
- The host floor makes `init` fatal but not `doctor --fix`; the Node row is a closed per-line
  table; a floor raise on a below-floor host is a gate before implement; settings converge in three
  shapes — "Host-floor rows and the three settings-convergence shapes".
- `_MIGRATIONS` run unconditionally on every `--fix`, must be idempotent, and land failures on
  `fix_errors` — "Doctor migration idempotency rule".
- Agent-dir pieces resolve through `launch_pi_agent_dir`, rewrite in place, need autouse
  `PI_CODING_AGENT_DIR` hermeticity — "Managed pieces and checks that act on files OUTSIDE the
  repo"; legacy cleanups model the retired writer — "Legacy-cleanup migrations…"; whole-directory
  checks use `:(literal)` pathspecs — "Whole-directory safety checks…"; fenced writes open
  link-blind — "Every write site behind an ignore-probe fence…".
- Historical (dated one-liners): the retired precedents "Marker-probe table craft" and
  "Report-only checks gated…"; the git-clone retirement "The retire-an-orphaned-lifecycle recipe".

## The split

- **`perk init` converges forward**: desired state, idempotent, never migrations. Maps to the
  `src/perk/convergence/init/` package — facade `__init__.py` (`run_init`,
  `managed_convergences()`, `ManagedConvergence`), `GITIGNORE_BODY` in `blocks.py`.
- **`perk doctor --fix` repairs legacy oddities**: one-off fixes for things `init` can't undo or
  that stem from historical inconsistencies. Maps to the `src/perk/convergence/doctor/` package
  (`fixes.py::_MIGRATIONS`).
- **`doctor` is the diagnostic pre-flight layer**: It utilizes report-only free functions
  (non-converging) inside `verify:` blocks. While `init` actively manages forward on-disk files,
  `doctor` provides diagnostic gating without mutating state (unless `--fix` is explicitly run).

Keep `init` a clean forward path — never a pile of version branches. New desired state goes into
the `init` package's convergences (the per-piece `ManagedConvergence.converge` callables listed by
`managed_convergences()`); one-off/legacy repairs go into the `doctor` package's
`fixes.py::_MIGRATIONS`.

## Managed convergence is the SSOT for doctor checks — never hand-author a check

A **managed convergence** (`init.ManagedConvergence`, listed by `init.managed_convergences()`) is
one structural piece expressed as a single dry-run/apply function: `init` calls it with
`apply=True` to converge; `doctor` calls it with `apply=False` to detect drift and `apply=True`
to `--fix`. `doctor._managed_checks` **auto-generates exactly one `Check` per convergence** (the
convergence `name` becomes the check name). Verification *and* `--fix` come for free —
`doctor._apply_fixes` iterates the same convergences.

So to add any new managed piece (the recipe is **three edits**, never a bespoke check):

1. Add a `ManagedConvergence` in `init.managed_convergences()` — its `name` becomes the doctor
   check name; `covers` lists the capability names it verifies.
2. Add the matching `Capability` in `src/perk/convergence/capabilities.py` (referenced by the convergence's
   `covers`).
3. Optionally add a `name → render-group` entry in `doctor._MANAGED_GROUP` (purely cosmetic
   grouping; absent ⇒ falls back to `"repository"`).

**Do NOT hand-write a check in some `_build_checks`-style function** — that produces a *duplicate*
check for the same piece (the skills-manifest work, #56, first planned a bespoke check and dropped
it for the three-edit recipe).

The coherence guard `test_every_required_capability_has_a_doctor_check`
(`tests/test_doctor.py`) enforces convergence↔capability parity: every dry-run convergence has a
check, and no applicable capability is left uncovered.

**The exception — a report-only check is not a hand-authored managed check.** This rule forbids
hand-writing a check for a piece that *has a managed convergence* (that would duplicate the
auto-generated one). A **pure validation with no converge/`--fix` semantics** has no convergence to
mirror, so it legitimately appends to `doctor._build_checks` directly and leaves `_apply_fixes`
untouched (e.g. the skill-bindings `bindings` check — see `skill-bindings.md`). Doctor group strings
are free-form (`_MANAGED_GROUP` only governs managed-convergence render grouping), and the coherence
guard checks *capability* coverage, not groups — but `perk doctor`'s condensed human output renders
only the `GROUP_ORDER` groups, so **any new `Check.group` value — managed or report-only — needs a
`GROUP_ORDER` addition in `src/perk/cli/commands/doctor/render.py` plus a render-visibility test**
(the `test_issues_group_renders` pattern in `tests/test_doctor.py`) in the same change, or the check
surfaces only in `--json` and the exit code — see "`doctor`'s human output renders only the
`GROUP_ORDER` groups" below. The test to apply: **does this piece have a `--fix`/converge side?**
Yes → three-edit managed convergence; no → a report-only `_build_checks` entry.

### The current check scope (dated census)

As of 2026-10 — the authority is `src/perk/convergence/doctor/__init__.py::_build_checks` plus
`src/perk/convergence/doctor/fixes.py::_apply_fixes`, never this list:

- **Managed checks** are exactly the convergences `managed_convergences()` declares —
  `settings-wiring`, `workflow-dir`, `skills-manifest`, `runner-workflow`,
  `required-perk-version`, `gitignore-block`, `agents-block`, `library-readme` — one check each
  via `_managed_checks`, repaired by `converge(True)` on `fail`.
- **The only other `--fix` arms keyed on a `fail` check** are `config` (re-seed missing files,
  never overwrite) and `extension-install`.
- **`_MIGRATIONS` run unconditionally** on every `--fix` (§ "Doctor migration idempotency rule").
- **Network repairs** are the fix-AND-verify gestures in `run_doctor`: `env.repair_pi`,
  `converge_repo_skills_manifest(apply=True)`, `sync_skills`, the Linear label ensure, and
  `ensure_review_cli`.
- **Every non-managed check** is appended directly in `_build_checks`, in two tiers: verify-gated
  (host or network shells — the env rows, `skills-delivery`, `extension-install`, `review-cli`, …)
  and offline (config and file reads — `config`, `providers`, `stage-models`,
  `subagent-package-scope`, …). Beyond the arms and gestures above, they are report-only.

## The managed-artifact set (`managed_artifacts()`) — the eligibility trio

`src/perk/convergence/managed_state.py` is the managed-artifact version+hash state library: init and
`doctor --fix` record each managed artifact's desired-content digest + perk version into
`.perk/managed-state.toml`, and doctor's report-only `_artifact_health_check` (`artifact-health`,
contracts §8.5/§8.6) classifies live content against it (up-to-date / stale / drifted).

**Growing `managed_artifacts()` has a three-part eligibility test** — the desired content must be:

1. **Offline-computable** — no network I/O to render the desired payload.
2. **perk-version-deterministic** — derived from the pinned perk version, not from user content.
3. **An actual `ManagedConvergence`** — not a verify-gated network gesture (those have no
   converge/desired-content side to hash).

The concrete contrast to reach for: the two `.agents/manifest.d/` fragments share a directory and
a header but have **opposite** eligibility — `perk.yaml` ✓ (rendered from the pinned skill set);
`perk-repo-skills.yaml` ✗ (needs a GitHub read via `derive_repo_source` and derives from the
user-authored `.perk/skills/`). **Similar names/locations ≠ same lifecycle model** — judge each
artifact against the trio, not its neighbors. (The other deliberate exclusions — the state file
itself, the gitignored caches — are enumerated in `managed_artifacts()`'s docstring.)

**Self-repo reconvergence is whole-repo — expect unrelated rows in the diff.** `perk init` rewrites
the *entire* `.perk/managed-state.toml`, so any reconvergence run — even one scoped to a single key
— also refreshes **pre-existing stale rows** (the `skills-manifest` row is the recorded instance):
verify each is a legitimate `desired == live` refresh and commit it with the intended move. A
mid-plan `uv run perk init` can also **revert deliberate divergences** (the recorded instance
rewrote `.github/workflows/perk-run.yml` because the branch's template differed from a pin a human
state-update commit made on main): inspect the **whole** init diff, classify each unexpected
row/file via git history, and restore deliberate pins before committing.

## Gitignore untrack pattern

A gitignore rule is **inert for already-tracked files** — `git check-ignore` even reports a tracked
path as "not ignored" (confusing). Adding the rule to `.gitignore` without untracking the file
leaves it churning on every change.

The proper two-plane fix:

1. **`init`** — add the entry to `GITIGNORE_BODY` (`src/perk/convergence/init/blocks.py`) so it
   lives *inside* the managed block (init owns all managed gitignore entries; never hand-add
   outside the `# BEGIN/END perk managed` block).
2. **`doctor --fix`** — run `git rm --cached <file>` (kept on disk) and strip any stray ungrouped
   line. `is_tracked` / `rm_cached` helpers live in `src/perk/substrate/git.py`.

**Generalizable rule:** any file materialized into `.perk/workflow/` is transient and covered by
the managed gitignore block — the whole `.perk/workflow/` tree is gitignored **wholesale**
(`/.perk/workflow/` in `GITIGNORE_BODY`), so a new transient file under it needs no per-file
entry.

## `report.changes` must reflect real filesystem deltas (idempotency)

Anything appended to `InitReport.changes` must be a **genuine delta**, never "an action was
attempted". The load-bearing invariant `test_cli_idempotent_second_run`
(`tests/test_init_t5.py`) asserts a second `perk init` on a converged repo reports
`changes == []`. A convergence that always appends a change on success breaks it.

The pattern for any side-effecting step (e.g. shelling out to an external CLI): **snapshot before
and after, append only on difference.** `sync_skills` snapshots the `.agents/skills/` symlink set
(`_skill_link_state`: name → target) before and after running `skills sync`, and appends a change
only when the set actually changed.

**The constant-desired variant needs an explicit delta gate.** `_converge_subagents` (the managed
`subagents.disableBuiltins: true` merge) is the first **constant-desired / no-config-read**
convergence — unlike the `_converge_compaction`/`_converge_models` write-*when-present* siblings, its
desired value never varies. With a constant desired value the change fragment must be **delta-gated**
— return an empty change list when the key is already `true` — or *every* future init/fix run that
changes anything else appends a phantom `subagents: …` line, violating the genuine-delta rule above.
(Idempotency on a fully-converged repo is still the `new_text == old_text` short-circuit in
`_converge_settings`; the delta gate is the *additional* requirement a constant-desired fragment
carries. See `borrowed-packages.md` for why a borrowed package's behavior has to be converged like
this at all.)

## An unreadable config makes destructive reconciliation a NO-OP (contract §8.10)

A fail-open catch that substitutes an **empty selection** for an unreadable config into a
two-directional reconciler makes "unreadable" indistinguishable from "user deselected everything"
— init would *strip* valid entries the broken config still names. The regression vector is
structural: every future `RETIRED_PROVIDER_KEYS` growth turns previously-valid configs
unreadable, re-arming the trap.

The settled posture: an unreadable config makes destructive reconciliation a **NO-OP** —
surfacing defers to the config check, and the next init after repair reconciles normally. Pinned
by `test_init_unreadable_config_never_strips_provider_or_linear_packages`
(`tests/test_init_idempotent.py`).

Rule of thumb: at a fail-open boundary, "fall back to empty" is only safe when the consumer is
**additive**; in a remove-capable reconciler it converts a read failure into deletion (see
`broad-catch-narrowing.md`).

## Committed-tracked managed delivery vs the cold-door symlink mirror

A convergence that writes byte-stable content into a **committed, tracked** subdir is inherited by
linked worktrees via plain `git checkout`, so it needs **no** cold-door worktree symlink mirror
(skills' `materialize_skills` `.agents/skills/` mirror exists only because those are *symlinks* the
cold door must repoint — `cold-door-launch.md`, `skill-bindings.md`); perk owns the WHOLE subdir —
it prunes stray files inside, never touches sibling user files outside — and computes the same
change-list for `apply=True`/`apply=False`. No committed-tracked instance remains: the agent defs
ship in the npm package (`pi/subagents.md` § "Agent-def delivery") and the legacy directory is
removed by the `--fix` migration in § "Legacy-cleanup migrations model the retired writer's shape".

## "doctor checks disk; selfcheck checks the prompt"

perk converges context **onto disk** (`perk init` writes the `<!-- BEGIN perk managed -->` AGENTS
block; `/learn-docs` maintains `.pi/APPEND_SYSTEM.md`) and trusts Pi to splice it into the model
prompt. `perk doctor` verifies only the **disk** side. The `/perk-selfcheck` command verifies the
**prompt** side via the live `getSystemPromptOptions()` (see `docs/learned/pi/extension-api.md` for
why that must be a *command* handler). The division:

| Surface | Verifies | Mechanism |
|---|---|---|
| `perk doctor` | the on-disk convergence | managed-convergence dry-run |
| `/perk-selfcheck` | the spliced system prompt | live `getSystemPromptOptions()` |
| `/perk-selfcheck` (census) | the per-surface payload cost | report-only census over the same live inputs |

The division grew a **third column**: `/perk-selfcheck` additionally reports the per-surface
payload census — append prompt, context files, skills section, tool definitions, perk-injected
`custom_message` branch context. It is report-only and emits derived identifiers/counts/chars
only (never raw text, matching `pi/extension-api.md`'s `getSystemPromptOptions` sensitivity
note), with a stable line grammar that later
audits diff against; the committed baseline is `docs/design/archive/context-payload-baseline.md`.

This made `<!-- BEGIN perk managed -->` a **cross-plane string contract**:
`src/perk/convergence/init/blocks.py` (`AGENTS_BEGIN`, facade-re-exported) writes it,
`extension/pi/v1/selfcheck.ts` (`MANAGED_AGENTS_MARKER`) reads it. Changing the
literal in one plane must update the other in the same turn (recorded in `shared/contracts.md` §8.7).

**Byte-match proof for the managed AGENTS block:** after editing the convergence source
(`_agents_inner()`) and the committed `AGENTS.md` in parallel, prove they're in sync with a small
`uv run python` snippet that splits the file on the `AGENTS_BEGIN`/`AGENTS_END` markers and
compares the inner text to the function output — cheaper and exact, versus re-running `perk init`
and eyeballing. (The scratch-dir `perk init` smoke still validates end-to-end convergence.)

The selfcheck probes are tolerant by design: an **absent** on-disk ambient index counts as wired (a
fresh consumer repo has none until the first `/learn-docs` lands), so selfcheck never false-fails on
it; only an index that *exists but didn't reach* the prompt is a gap. The "reached" probe is a
trimmed-substring match (robust to join-newline/whitespace differences) and stays sound only while Pi
loads `.pi/APPEND_SYSTEM.md` **verbatim** — see `docs/learned/pi/context-system.md`.

## `doctor`'s human output renders only the `GROUP_ORDER` groups

`perk doctor`'s **condensed human output** renders only the groups in the literal group-order
tuple in the doctor command module. Its render loop iterates that tuple, so any check whose group
is **not** listed is **invisible in the human text** and surfaces only in `--json` and the exit
code.

**The trap struck again** (the skills-delivery check): the new `skills` group wasn't in the render
order — and neither were the pre-existing `bindings` and `providers` groups, meaning those checks
had been silently invisible in human output the whole time. Durable rule: **any new `Check.group`
value MUST be added to the render group order in the same change**, and a render-visibility test
is cheap insurance.

This is distinct from `src/perk/convergence/doctor/data.py`'s `_MANAGED_GROUP` (which only *assigns* a managed
convergence's group name, falling back to `"repository"`); assigning a group there does **not**
make it render unless that group is also in the render module's `GROUP_ORDER`
(`src/perk/cli/commands/doctor/render.py`). Any new doctor groups will remain completely invisible in
the condensed human text unless explicitly added there.

The latent trap: "mirror an existing group" instructions inherit that group's own render status —
the `bindings` and `providers` groups were unrendered for a long time before the skills-delivery
fix added them. Extending `GROUP_ORDER` changes long-standing behavior for previously-invisible
groups, so treat it as a deliberate cross-cutting change, not a drive-by. **Verify render
visibility empirically with `perk doctor`, not just `--json`.**

## The optional `EnvCheck` tier (a non-fatal tool — #617)

Adding a tool whose **absence should warn, not block** is a reusable three-touch pattern in
`src/perk/convergence/`:

- **`env.py` (`src/perk/convergence/env.py`):** add an `optional: bool = False` flag to the frozen `EnvCheck` dataclass; add an
  optional-tool check helper mirroring the required one but stamping **`optional=True` on BOTH the
  present and absent results**; and change `required_tools_ok` to filter optional checks out
  (`all(c.ok for c in checks if not c.optional)`). **That filter is what keeps a missing optional
  tool off the `missing_tool` exit-2 path.**
- **`doctor/checks.py` (`src/perk/convergence/doctor/checks.py`):** map the env status as
  `"ok" if c.ok else ("warn" if c.optional else "fail")`
  (annotate the local as `Status` for ty). **No `GROUP_ORDER` change** — `environment` already
  renders, and a `warn` leaves `report.healthy` / the exit code untouched (the existing
  healthy-allows-warnings invariant).
- **`init`'s human render:** the success-path env loop gains a **3-way mark** (`✓` / `⚠️`
  optional-not-ok / `✗`). The failure path stays unreachable for optional tools because
  `required_tools_ok` ignores them.

**The `advisory` tier.** `EnvCheck.advisory` is a non-blocking caution on an `ok` row (the `pi`
row's off-pin caution naming the pinned install command): the row stays `ok=True`; doctor shows
`warn` "<name> ok, with a caution" without changing `healthy` or the exit code; a *successful*
init adds the advisory to `warnings` — add it at the success return, not after the env gate, or it
leaks into the `skills_sync_failed` report. The `--json` row shape is unchanged.

Three adjacent traps matter whenever this environment-check family grows:

- **Stub the primitive a check actually calls.** A doctor check that reads the git-config
  primitive directly bypasses the init-facade onboarding stubs. The shared conftest environment
  fixture therefore needs its own deterministic stub for that primitive; otherwise every
  `run_doctor(verify=True)` test observes the developer or CI host's real git identity.
- **Filter optional checks at diagnostic composition too.** Excluding them from the fatality
  predicate does not exclude them from derived text such as a joined missing-tools message. Apply
  the required-only filter wherever that message is built and pin it: optional `ast-grep` once
  leaked into the required-tools failure despite correctly leaving the exit predicate.
- **Model absent and version-invalid remediation as separate arms.** A per-tool table covering
  only missing binaries leaves installed-but-outdated tools with stale, command-free guidance.
  Exercise and populate remediation for both states.

## Host-floor rows and the three settings-convergence shapes

**The host-floor rows.** `env.py::_check_pi` / `_check_node` read `shared/host-floor.yaml`
(contracts §8.76) — `_check_pi` through the same `probe_pi_host` the launch admission uses, an
unparsable Node version counting as outdated. They feed `perk init`'s fatal preflight, so `init`
refuses on an outdated Pi/Node, while `perk doctor` reports the `fail` row and does **not** gate
`--fix` on it (`doctor/__init__.py::run_doctor`). Hence:

- **The Node row is a closed per-line table** (`node.min_version` + `node.line_floors`):
  `host_floor._node_problems` backs both `validate()` and `supported_node_lines()`; five arms —
  absent / unparsable / unsupported line / below its line's floor / ok. The TS reader reads only
  `min_version`; launch admission never probes Node. Adding a Node line is a deliberate release
  touching `line_floors`, `engines.node` in both `package.json`s, the lockfile, the
  `describe_node_lines` literals in `tests/test_env.py`/`tests/test_init_onboarding.py`, the prose
  sweep, and CI's `setup-node` (guarded by
  `tests/test_workflow_artifacts.py::test_ci_workflows_exercise_the_node_floor`). npm's engine
  check admits later-triple prereleases exactly as `satisfies_floor` does.
- **uv and certifi.** `[tool.uv] required-version` is the single uv declaration; `setup-uv`
  discovers it; the consumer action carries `REMOTE_UV_VERSION_SPEC`, test-pinned equal; `uv tool
  install` ignores project config, so the installing uv is operator-required. certifi protects only
  the default httpx path (`SSL_CERT_FILE`/`SSL_CERT_DIR` take precedence). The enforced vs
  operator-required split lives in `docs/user-docs/reference/security.md`.
- **A floor raise on a below-floor host.** `engine-strict` gates only install commands, so a green
  `run_ci` does not prove the host meets `engines`; `npm install --package-lock-only
  --engine-strict=false` regenerates the lockfile; after landing, every new worktree's setup hook
  refuses until the host is upgraded — treat a host-upgrade prerequisite as a gate before the
  implement launch.
- **Reconvergence after a floor raise goes through the owner** (`runner-workflow` →
  `action.yml` + `managed-state.toml`). Regenerate managed artifacts with
  `uv run perk init --no-interactive` when a host bump is in flight; `doctor --fix` also repairs
  the `pi` row (below), which installs the adopted set onto the global prefix
  (`docs/developers/pi-subagents-reverify.md` § Pre-land gating and the post-land cutover). The
  committed self-repo artifacts have a lockstep test
  (`test_committed_self_repo_remote_artifacts_are_the_owners_render`).
- `.perk/local.toml` is not materialized into worktrees, so a doctor `config` fail there is
  environmental.
- A hand edit that drops `.pi/settings.json`'s trailing newline reads as `settings-wiring` drift.
- `_converge_discovery` re-adds a deleted `defaultTools` at the END of the JSON object, so
  byte-identical repair criteria depend on where the committed file puts the key (the committed
  self-repo file now puts it last).
- **The `pi` row has side effects** (Pi 1.0.0): `pi --version` runs `cleanupManagedInstall()` and
  takes the global settings lock before its version branch. The probe runs in the invocation
  directory, so a directory-dependent version-manager shim could report a different Pi (untested).
  A corrupt bundled floor crashes as `HostFloorError` rather than a typed refusal.

**The three shapes in `init/settings.py::_converge_settings`:**

1. **Write-when-present** — `_converge_compaction`, `_converge_models`.
2. **Constant-desired** — `_converge_subagents`' `disableBuiltins`, with a delta-gated change
   fragment.
3. **Seed-when-unnamed** — `_converge_discovery` appends `+tool_search` when no string entry
   names the tool in Pi's plain/`+`/`-` form; it appends at the end, never rewrites or reorders an
   operator's entry, and never appends after an operator's `-tool_search` (Pi applies modifiers in
   order). The `[7, null]` case: Pi drops non-strings before resolving, so a list with no string
   entries resolves to "no builtin tools" and is left alone — the guard is
   `not any(isinstance(entry, str) …)`, not emptiness.

(There is no `tuiMode` seed: Pi 1.0's native fullscreen default replaced it.)

**A user-ownable seed stays out of the managed-state desired/observed portions** — otherwise an
opted-out repo is `locally-modified` forever. Its drift comes only from the `ManagedConvergence`
dry-run, never the lens: deleting the key makes doctor `fail` while the recorded hash does not
move, by design (`tests/test_init_idempotent.py::test_discovery_default_is_invisible_to_the_settings_portion`).

**Rule — converge in the consumer's resolved semantics.** When converging a key someone else
consumes, state the invariant in that consumer's resolved terms ("the resolved selection gains
`tool_search` and nothing else"); enumerate every normalization step (Pi filters non-strings,
treats a non-array as `[]`, merges project onto user); give the cross-plane fixture
`shared/fixtures/default-tools-seed.json` one row per classification edge (consumed by
`test_init_default_tools_seed_matches_the_shared_fixture` and
`extension/substrate/discoveryPilot.test.ts`); and derive shape classes from those edges, never
from JSON syntax — both defects in the seed came from reasoning over raw JSON. The `defaultTools`
resolution facts themselves live in `pi/tool-loadout.md` § "`defaultTools` resolution".

## Write admission (`convergence/write_admission.py`)

`perk init` and `doctor --fix` refuse before any write, with exit 2 (`write_refusal`):

- **`foreign_perk`** (self-repo): the running perk's checkout must *equal* the converged root —
  equality, not containment, because worktrees nest under `<main>/.worktrees/`.
- **`perk_outdated`** (consumer repos): the running perk is older than
  `.perk/required-perk-version`.

Bare `doctor` is never gated. In perk's own repo always run `uv run perk init` /
`uv run perk doctor --fix` from the checkout being converged. The maintainer invariant: a green
`--fix` means everything works — an unverifiable row fails, and repairs re-probe. Test pattern for
a verify-gated gate: stub through the facade in `conftest.stub_env`; the gate's own tests restore
the real function first. Diagnostic note: in a linked worktree `init`/`doctor --fix` report a
per-skill `skills update --sync` conflict (the known `dot-directory-migration.md` conflict) and
leave untracked `.agents/local.yaml`, `.agents/cache/`, `.perk/local.toml`.

## Fail-level checks, fix_errors, and the machine-surface co-owners

Lessons from making skills delivery a fail-level concern (see also `init-external-cli.md`):

- **A new fail-level verify-gated check shifts the baseline of every `verify=True` test repo** —
  freshly-converged test repos now fail the new check unless the healthy end-state exists. Budget
  for a conftest fixture that plants that end-state (e.g. the converged skills workspace) rather
  than patching individual tests.
- **Failed repairs are first-class report data**: `DoctorReport.fix_errors` is rendered in human
  output and present in `--json`, never folded into `fixed`. The `--fix` re-verify must trigger on
  fixes *or* fix-errors — otherwise a failing sync with zero successful fixes reports stale
  pre-fix checks.
- **The machine-surface contract sections are always co-owners**: when adding error types or
  report fields, the exit-code taxonomy (`shared/contracts.md` §8.5) and the `--json` shape
  (§8.6) need same-turn amendment — plan them in, not just the feature's own section.
- **Seam-signature ripple**: before changing a patched seam's signature, grep tests for the seam
  name — the skills-sync seam had 8 stub sites whose monkeypatch lambdas all needed widening.

## Network repairs live in the verify-gated repair gesture, never a `ManagedConvergence`

Managed convergences run **unconditionally in offline unit tests**, so anything that does network
I/O (the Linear label ensure, skills sync) must instead follow the `sync_skills` pattern: a
`fix AND verify`-gated call in `run_doctor` appending to `fixed`/`fix_errors`, idempotent via
lookup-first. Corollary: `_apply_fixes`' check-keyed loop only acts on `fail` checks — warn-level
findings are repairable *only* through the gesture path.

Related readiness shape (full detail in `linear-backend.md`): **one report-shaped probe, two
consumers** — a never-raising `check_readiness` with an `ensure_labels` flag splitting doctor's
lookup-only path from init/`--fix`'s converge path. Probe results carry only what was
*discovered*; an input value a render needs goes on the wrapping report, not the probe result. And
a verify-gated group that can't run must say *why it stopped* (a single warn check), never
silently pass.

**`doctor --fix` repairs the `pi` row itself** (`env.repair_pi`): on any gap, the advisory
included, and only under fix AND verify; a failing `node` row blocks it; anything still wrong after
the install lands on `fix_errors`. Consequence: a worktree `doctor --fix` installs the adopted set
onto the operator's global prefix — when a host bump is in flight, regenerate managed artifacts with
`uv run perk init --no-interactive` instead. `runner-pat-secret` checks presence only (an expired
PAT is invisible) — run `perk doctor workflow smoke-test --wait` before relying on remote legs (an
age advisory is a routed code follow-up).

*Dated:* the extension-clone lifecycle is retired (npm delivery, `distribution.md`; § "The
retire-an-orphaned-lifecycle recipe"); its lesson stands — **commit-freshness ≠ dependency
installation**: when retiring a bundled check, separate the concerns it covered.

## Adding a NEW gated probe beside an existing gated check (#603)

The project-backed objective readiness probe (`check_project_readiness`, a SEPARATE function beside
`check_readiness` — see `linear-backend.md`) wired two new doctor checks + a nullable init sub-report,
and surfaced three reusable disciplines:

- **A new gated probe beside an existing gated check ⇒ census ALL its monkeypatches.** Every
  existing test that monkeypatches the *sibling* readiness function to `auth_ok && team_ok` AND
  reaches the new probe must ALSO monkeypatch it, else it falls through to the **real network
  probe** — four pre-existing tests broke, both `--fix` tests among them (`run_doctor(fix=True,
  verify=True)` runs the checks under verify). The auth/team-FAILURE tests are the natural place to
  assert the new checks are **ABSENT** (monkeypatch the probe to `raise`).
- **`report.healthy` is the WRONG assertion for "this check stays non-fatal."** A scaffolded
  synthetic repo is never globally healthy (unrelated fail-level checks exist), so assert
  `all(c.status != "fail" for c in <the relevant group>)` instead.
- **Two-phase independent probe + honest-scope-proxy.** Projects-read and states-coverage are
  **separate** `try/except` with **no early return between them** (test that the states query
  still issues after a projects error). Write scope isn't probeable without a mutation, so a
  **non-mutating read is the honest proxy** and the message says "read-access". The new probe field
  is **nullable and must NOT flip the report's `ok`**; it runs only when `auth_ok && team_ok`, so a
  degraded repo reports `project: None`.

## Marker-probe table craft (#2005) — retired precedent

*Dated:* the doctor `subagent-compat` source-literal marker-probe table is gone — doctor never reads
a borrowed package's source, and `subagent-compat` is a plain version tripwire (`pi/subagents.md`
§ "Engine-coupling posture — public surfaces only"). Its craft, for any probe over a surface perk
owns or vendors:

- Never pin a probe to a removal/cutover message — pin positive load-bearing surface literals.
- Leave a surface no stable literal distinguishes unprobed, with an intent comment at the table.
- The exact-pin test (version + one full row) forces bumps to be deliberate, reviewed re-verifies.

## Report-only checks gated on an installed package's version range (retired precedent)

*Dated 2026-09:* the doctor check that fired only while pi-subagents 0.67.x's host-builtin
intersection was installed — with its half-open affected range and the `PI_FFF_MODE` launch
injection — was deleted when pi-subagents 0.70.0 removed the intersection (records:
`docs/design/archive/pi-subagents-0.68.0-reverify.md` closed the range,
`docs/design/archive/pi-subagents-0.70.1-reverify.md` retired it). Its four disciplines:

- Gate on a strict `X.Y.Z` against a half-open `[lower, upper)` range; a non-semver or unreadable
  version ⇒ `info` "not evaluated", never a mismatch; keep a closed range's two `ok` arms
  distinguishable (below the range vs at/above the fix).
- Mirror the foreign tool's OWN precedence exactly — an approximation makes doctor disagree with
  the tool it diagnoses.
- Take an `environ` seam defaulting to `os.environ` at call time, paired with an autouse `delenv`
  in `tests/conftest.py`, so a developer's exported value never flips unrelated doctor tests.
- Pin parity between a doctor detail and a launch-seam constant by a test, not an import
  (`convergence.doctor` has no edge into `perk.run.launch`).

## Extending a report-only advisory warn silently flips fixture arms

A new/extended report-only advisory warn evaluated over an existing fixture corpus silently flips
previously-`ok` test arms whose planted artifacts predate the new expectation (observed:
aggregating declaration-expectation parts into the repo-skills warn turned fixture skills without
the expected frontmatter into `warn`s in unrelated tests).

The fix is posture, not assertion: update the fixtures to the new-clean shape so each test keeps
asserting its own concern; add dedicated arms per new warn part, including an aggregate arm
proving multiple parts ride ONE warn check. Convention: when extending a report-only doctor
nudge, grep for every fixture that plants the artifact the nudge inspects.

## Managed pieces and checks that act on files OUTSIDE the repo (the user's agent dir)

Some checks read files inside the user's Pi agent directory rather than the repo. The live
instances are the `subagent-package-scope` check's user-scope `settings.json` read and
pi-subagents' private `extensions/subagent/config.json`, which perk observes and refuses but never
converges (`workflow/borrowed-packages.md` § "Borrowed-engine stances"; the refusal surface is in
`workflow/mergeability-and-conflict-resolution.md`). *Dated:* the `subagent-bridge-config` and
host-tools reads and the `subagent-worktree-default` convergence — the one worked example of
*writing* there — are retired. Three rules govern them:

- **Resolve the user scope through the ONE shared resolver `launch_stage` also consumes** —
  `src/perk/substrate/config.py::launch_pi_agent_dir` (env `PI_CODING_AGENT_DIR` → main-checkout
  `[pi] agent_dir` → `~/.pi/agent`; `None` on an unresolvable home; `ConfigError` /
  `TOMLDecodeError` propagate and each caller keeps its own posture). Never a parallel
  `Path.home()`/env copy: the check must act on exactly the store a perk session's engine reads.
- **Writing there: rewrite ONE key in place via atomic replace, never create the file**, and treat
  only a genuinely missing path as compatible — every other unreadable shape is the loud arm
  (`workflow/broad-catch-narrowing.md`). (The retired `subagent-worktree-default` convergence was
  the instance.) The read-side disciplines apply to any check that inspects the user's agent dir.
- **Doctor `--fix` catches `UserFacingCliError` from a managed `converge(True)`** and records
  `"<check>: <message>"` on `fix_errors` instead of aborting, so a refusal on one piece never
  blocks the rest of the repair pass.

**The `subagent-package-scope` shape** (#2472): `package` group, `ok`/`info`/`warn`, never `fail`,
no `--fix` (an operator-owned user file). User scope resolves via `launch_pi_agent_dir`
(`ConfigError`/`TOMLDecodeError` ⇒ `info`), project scope via `.pi/settings.json`; identity via the
init package-identity helper against the constant dirname (the borrowed-entry invariant is pinned
in a test). Model none/user/project/both explicitly — the first cut's `ok` arm claimed "project
scope only" when neither scope listed it. `Path.absolute()`-normalize both paths (the resolver
preserves a relative `PI_CODING_AGENT_DIR`); a project `autoload: false` entry never counts (pi
keeps both entries of such a delta). Specify a report-only check's state machine and cause
vocabulary up front.

Such pieces force **hermetic isolation in EVERY test that reaches them** — not just the
user-scope arms — or a developer's real agent dir flips unrelated assertions (and a test can poison
the real store). The mechanics that make the isolation workable:

- An **autouse `PI_CODING_AGENT_DIR` fixture** is the right default — the env arm wins precedence
  — but it must **not** `mkdir` under `tmp_path` (tests asserting an untouched `tmp_path` broke;
  consumers mkdir on demand).
- Tests that `delenv` to exercise the config/default arms must also isolate `Path.home`: patch
  `Path.home` → `<tmp>/home` (Python-process-only — safer than `HOME=`, which git/gh subprocesses
  would also see). Resolution happens at call time, so the monkeypatch lands.
- Session-scoped fixtures sit outside function-scoped autouse fixtures — wrap their `run_init` in
  `pytest.MonkeyPatch.context()`.
- **Mutating the scaffolded `.pi/settings.json` in a doctor test must merge, not overwrite** —
  preserve the init-converged keys AND init's serialization shape (indent=2 + trailing newline),
  or the unrelated `settings-wiring` check goes red. Doctor tests are coupled across checks
  through the shared scaffold.

## Legacy-cleanup migrations model the retired writer's shape

A `--fix` that removes a retired convergence's output models what the retired WRITER produced (a
flat `<name>.md` set), not the engine's discovery breadth — the first cut walked recursively, which
handled a layout perk never produced and symlink-checked only the leaf (#2456). The realized
instance is the legacy `.pi/agents/perk/` agent-def directory
(`perk/convergence/doctor/legacy_agent_defs.py`):

- **Classify every entry link-blind** (`is_symlink()` before `is_dir()`/`is_file()`); refuse on a
  symlink at any owned ancestor, on any non-flat/non-`.md` entry, and on any def lacking its
  shipped replacement (`shipped_agent_defs_dir`) — deletion never runs before the replacements are
  proven present.
- **"All-or-nothing" is a property of the PREFLIGHT.** Post-preflight `OSError`s land on
  `fix_errors` and the next `--fix` resumes — say so in contracts rather than claim transactional
  atomicity.
- **When a report-only check has a `--fix` repair, share ONE classification between them** — a
  leaf module both `checks.py` and `fixes.py` import — so the remediation states exactly what
  `--fix` will do and the two can never disagree.

## Whole-directory safety checks need representative probes and literal pathspecs

A check that vouches for a whole redirected directory (`_pi_agent_dir_check`,
`src/perk/convergence/doctor/checks.py`, guarding a `[pi] agent_dir` inside the repo) can be
vacuously green: an auth.json-only ignore probe reports acceptable coverage while trust, settings,
model-store data, locks, and nested session logs stay exposed. Probe **representative** sensitive
and volatile artifact classes — including nonexistent files (warn before pi writes the first one)
and nested paths — and describe the result as representative coverage, never exhaustive proof.
Keep ignore rules distinct from already-tracked content: scan tracked artifacts separately and
report remediation without auto-untracking user files (gitignore rules never untrack). Where one
exception must remain trackable, ignore the directory's contents and then negate the exception
(`/.pi/agent/*` followed by `!/.pi/agent/models.json`) rather than excluding a parent directory Git
cannot descend into.

**A filesystem path is not a literal Git pathspec.** `--` stops option parsing but not pathspec
grammar — brackets, wildcards, and magic-like names redirect or hide a tracked-artifact scan. Use
`:(literal)<repo-relative-dir>` at this boundary (`git.tracked_paths`), with regression tests that
create real tracked files under metacharacter names and prove both detection and the exclusion of
unrelated glob matches.

## Every write site behind an ignore-probe fence refuses redirects without following links

The "classify every entry link-blind" bullet of § "Legacy-cleanup migrations model the retired
writer's shape" applies to **every converged file and every lock file**, not only cleanup. An ignore
probe checks a path *name* (`workflow/git-substrate.md` § "Ignore probes are name-only…"), so a
symlinked leaf or ancestor passes the fence while the write lands elsewhere. PR review found two
instances in the library foundation: `converge_library_readme`
(`src/perk/convergence/init/library.py`) checked only whether the library directory was a symlink —
a symlinked `README.md` or `docs/` ancestor let `init`/`doctor --fix` overwrite the repo-root README
— and the library lock followed a pre-existing symlink out of the cache.

**The rule:** check the leaf and each owned ancestor link-blind, confirm the root `resolve()`s where
expected, open with `O_NOFOLLOW` after an `lstat` check, then `fstat` for a regular file (with
`O_NONBLOCK`, so a swapped-in FIFO cannot hang the open) — realized in `src/perk/library/lock.py`.
`src/perk/delivery/oplock.py` still follows symlinks (a known gap).

### "Refused before the lock, zero writes" has a structural limit

When a guard's inputs come from lock-protected state — the library `remove`'s entry path comes from
the catalog, which is read under the lock — the entry probe runs under the lock, and a refusal there
can leave the (ignored) lock file behind. Write the weaker guarantee into the contract and the user
docs (review caught the stronger promise), and probe the lock file's own path before creating it.

### An atomic catalog write does not make a multi-step publish atomic

Recovery prose lists the on-disk state after **each** rename step, not only "before" and "after".
The library publish is displace → swap-in → catalog write: a kill between the first two leaves the
catalog pointing at a missing target with the displaced `.<slug>.previous-*` as the only copy of the
prior revision, and a kill between the last two leaves a different state again. This extends
"all-or-nothing is a property of the PREFLIGHT" above.

### Remediation text must not send the user to a destructive verb

A `directory_catalogued`/`kind_mismatch` refusal points to a content-preserving next step (keep the
entry, or `record --publish … --replace`) and names a deleting verb only as the deletion it is — the
first draft told the user to run `perk librarian remove`, which deletes the directory they were
trying to keep.

## Managed template reconvergence

When you edit managed full-file templates in the codebase (for example, `PERK_RUN_WORKFLOW` in
`src/perk/run/workflow_artifacts.py`), you must immediately trigger self-repo copy reconvergence (such as
updating `.github/workflows/perk-run.yml` in perk's own repo) in the same turn. Run
`perk doctor --fix` or `perk init` to apply the updated template to the self-repo, and commit the
converged changes together with the template edits.

## Click bottom-of-file imports

To avoid circular imports when registering Click command subgroups, place the subgroup registration
imports at the bottom of the parent group file, strictly *after* the parent group object (`cli` or
`perk_group`) has been fully defined. This ensures the parent group is available in the module
namespace when child commands attempt to import and register themselves onto it.

**Scope this idiom to genuinely registration-induced cycles.** When the cycle is *helper-induced*
(a subgroup importing the parent's helpers), dissolve it instead by extracting the shared helpers
into a sibling leaf module (the `doctor/render.py` pattern) so both `__init__.py`s import
top-of-file normally — see `docs/learned/workflow/cli-command-groups.md`.

### `register_with_aliases` single-command constraint

The `register_with_aliases` helper in `src/perk/cli/alias.py` is strictly designed for single-command
registration. Attempting to pass extra positionals (e.g., trying to register multiple commands in a
single call) will fail loudly at import time.

## The retire-an-orphaned-lifecycle recipe

*Dated:* when the git-clone extension-delivery lifecycle was superseded by the npm install
(`distribution.md`), its removal settled a reusable recipe:

- **Relocate the one surviving primitive beside its dependency and scrub the facade.**
  `consumer_git_clone_root` moved verbatim into `settings.py` beside its sole dependency
  `GIT_PACKAGE`, re-exported through the `init/__init__.py` facade so the attribute path keeps
  resolving; scrub the dead module's imports, `__all__` entries and the package docstring —
  RUF022 isort-alphabetical in BOTH the import list and `__all__`.
- **Removing a doctor check is a three-site edit:** the `_xxx_check` def in `checks.py`; the
  import + `__all__` entry + `checks.append(...)` in `doctor/__init__.py`; the fix branch in
  `fixes.py`.
- **Dead substrate primitives go last**, after a repo-wide sole-consumption proof — shared
  primitives (`git.fetch`) and shared fixtures stay.
- **The forward migration is a `_MIGRATIONS` entry** (`_remove_orphaned_git_clone`):
  forward-only, filesystem-only on a gitignored path, returning `(changes, errors)` — the full
  contract is § "Doctor migration idempotency rule".

## Doctor migration idempotency rule

`_MIGRATIONS` (`src/perk/convergence/doctor/fixes.py`) is the forward-migration contract:

- They run **unconditionally on every `--fix`** — not gated on a failing check, even when every
  check is green.
- Each must be **idempotent**: no changes once converged (the `again.fixed == []` tests).
- Each returns `(changes, errors)`; an `OSError` lands on `report.fix_errors` loudly.
- A `run_doctor(fix=True, verify=False)` test exercises a migration without seeding a failing check.

## Cross-references

- `src/perk/convergence/init/__init__.py` — the facade (`run_init`, `managed_convergences()`,
  `ManagedConvergence`); `blocks.py` — `GITIGNORE_BODY`; `skills.py` — `_skill_link_state`,
  `sync_skills`
- `src/perk/convergence/doctor/` — `fixes.py::_MIGRATIONS`, `checks.py::_managed_checks`,
  `data.py::_MANAGED_GROUP`, `fixes.py::_apply_fixes`
- `src/perk/cli/commands/doctor/render.py` — `GROUP_ORDER` (the human-render group allow-list)
- `src/perk/convergence/capabilities.py` — `Capability`, `applicable()`
- `src/perk/substrate/git.py` — `is_tracked`, `rm_cached`, `tracked_paths` (the `:(literal)` pathspec boundary)
- `src/perk/library/guard.py` — `require_unlinked_components`; `src/perk/library/lock.py` — the
  `lstat` + `O_NOFOLLOW` + `fstat` lock open
- `docs/learned/workflow/git-substrate.md` — the ignore-probe mechanics (name-only, beyond-a-symlink
  fatal)
- `src/perk/substrate/config.py` — `launch_pi_agent_dir` (the one agent-dir precedence);
  `src/perk/convergence/doctor/checks.py` — `_subagent_compat_check`,
  `_subagent_package_scope_check`, `_stage_models_check`
- `src/perk/convergence/doctor/__init__.py` — `run_doctor`, `_build_checks` (the live check census)
- `src/perk/convergence/write_admission.py` — `write_refusal`
- `src/perk/convergence/doctor/legacy_agent_defs.py` — the legacy agent-def classification shared
  by its check and its `--fix` migration
- `docs/design/archive/pi-subagents-0.68.0-reverify.md` +
  `docs/design/archive/pi-subagents-0.70.1-reverify.md` — the retired version-gated check's records
- `docs/learned/workflow/cold-door-launch.md` — the launch side of the agent-dir precedence; `docs/learned/workflow/broad-catch-narrowing.md` — classifying every read outcome of a file perk does not own
- `tests/test_doctor.py` — `test_every_required_capability_has_a_doctor_check`
- `tests/test_init_t5.py` — `test_cli_idempotent_second_run`
- `extension/pi/v1/selfcheck.ts` — `MANAGED_AGENTS_MARKER`, `readAmbientIndex`, `buildSelfcheckReport`
- `docs/learned/pi/extension-api.md` — why selfcheck must be a command handler
- `docs/learned/workflow/linear-backend.md` — the full Linear readiness probe shape
- `docs/learned/workflow/distribution.md` — the npm extension-delivery lifecycle that superseded the git-clone lifecycle
- `src/perk/convergence/env.py` (`_check_pi`, `_check_node`, `repair_pi`), `shared/host-floor.yaml`,
  `src/perk/convergence/init/settings.py` (`_converge_settings` and its three shapes)
- `docs/learned/pi/tool-loadout.md` — the `defaultTools` resolution the seed must respect
