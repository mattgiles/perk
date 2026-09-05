---
title: perk init shelling out to external CLIs (the skills-manifest pattern)
read_when: You are making perk init shell out to an external CLI (skills, gh, …), choosing its failure posture (best-effort vs load-bearing), or promoting an external skill into the managed manifest.
cluster: config-and-convergence
---

# `perk init` and external CLIs

Perk-hosted skills (`skills/<name>/`, authored or vendored) and the required external skills are
declared in a committed manifest fragment (`.agents/manifest.d/perk.yaml`) and materialized by
`perk init` shelling out to the external `skills` CLI. The original perk-authored delivery landed
in plan #51, PR #55; the patterns below generalize to any external CLI perk drives.

## Distillation

- Failure posture is per-CLI: skills delivery is load-bearing (a silent no-op is a broken
  install — D3 superseded there); GitHub readiness stays best-effort/non-fatal — "Failure
  posture: D3 superseded for the skills CLI".
- Route the whole external-CLI shell through ONE module-level patchable seam so verified init
  tests stay offline — "A single patchable seam keeps the suite offline".
- The `skills` CLI is the SINGLE materialization path for managed `.agents/skills/<name>` in
  both self-repo and consumer trees (the pi package contributes only the extension) — "The
  `skills` CLI is the single delivery path (both trees)".
- `PERK_SKILLS` owns the perk-hosted names, authored or vendored: one alphabetical tuple edit
  cascades to the fragment and, through `MANAGED_SKILL_NAMES`, to post-sync verification and
  doctor — "The `PERK_SKILLS` SSOT cascade".
- The manifest fragment is a committed declaration, never gitignored; the `skills` CLI owns the
  `.agents/` gitignore boundary — perk's block never touches it — "Committed declaration vs.
  transient state — the gitignore boundary".
- Guided onboarding is a gap-driven gesture family: healthy hosts no-op; supported installs
  confirm, run, and re-probe; non-interactive paths never prompt or mutate — "Gap-driven guided
  onboarding gestures".

## Failure posture: D3 superseded for the skills CLI (GitHub readiness stays non-fatal)

The original D3 posture — "shelling out to an external CLI must never block init" — **no longer
applies to the skills CLI**. Skills delivery is perk's own load-bearing substrate (perk's skills
are how sessions get their instructions), so a silent no-op there is a broken install, not a
degraded nicety. GitHub readiness remains best-effort/non-fatal (a flaky `gh` still degrades to an
unauthed report).

The skills shell now uses a **two-tier loud-failure posture**:

1. **A pre-flight probe** replicating the foreign tool's own refusal condition (tracked content
   under its managed pathspecs), failing fast with remediation **before any convergence** —
   env-failure, exit 2, empty changes list. A probe *error* degrades to no-short-circuit (the
   fatal post-step catches the real failure) rather than a false block.
2. **A fatal post-step** that surfaces the tool's stderr while **preserving** the changes list
   (an inline failed report, not env-failure — which would zero the changes).

Further hardening that generalizes:

- **Post-sync presence verification de-fangs version drift generically**: verifying every expected
  skill is installed after a "successful" sync catches any failure mode — including the documented
  no-version-floor residual below (an outdated CLI that links nothing is now caught).
- **The config-vs-substrate check split keeps "loud-but-non-fatal" honest**: user-config checks
  (`bindings`) stay warn-level; perk-substrate checks (`skills-delivery`) are fail-level. Split by
  ownership.
- **The posture flip is consumer-visible**: consumers with a missing/never-synced skills CLI now
  get `perk init` exit 2 / `perk doctor` exit 1 where they previously got 0 — supervisors/CI that
  tolerated the old silent pass newly fail. Intentional.

The mechanics that survive from D3 for any external shell: explicit `check=False`,
`capture_output=True`, `timeout=…` on every `subprocess.run`, and one patchable seam (below).

## The unconditional best-effort install/verify gesture (the `hunk` CLI)

A **new point on the best-effort↔load-bearing spectrum** landed beside the skills posture: an
external CLI that is a review *surface* perk keeps available, not perk's own load-bearing
substrate — install/verify it best-effort, **unconditionally**, never fatally. The realized shape
(the `hunk` CLI, installed via `npm i -g hunkdiff`):

- **A small gesture module** — `src/perk/convergence/init/review_cli.py`,
  `ensure_review_cli(root) -> (changes, warnings)`. Never raises: no-op when the binary is
  present; absent → the global npm install, with `NpmError` degrading to **one warning carrying
  the manual-install hint** (`HUNK_INSTALL_HINT`), never a failed init. The gesture reads **no
  config** (the `root` param is retained purely as the patchable seam's signature).
- **A global-install npm gateway op** — `install_global` in `src/perk/substrate/npm.py`
  (`npm install -g <spec>`, for global CLI binaries as opposed to Pi packages).
- **Verify-gated `run_init` wiring** — the gesture is a network op, so it runs under `if verify:`
  only (the same rule that keeps managed convergences offline; see the repo-skills section below).
- **A doctor warn-level check** — `review-cli` in
  `src/perk/convergence/doctor/checks.py`, gated **inside `if verify:` because a PATH probe is
  host-dependent** — keeping `verify=False` check lists byte-stable. It always probes: ok when
  present, warn (with the install hint) when absent.
- **The `--fix` retry goes through the facade attribute** — doctor calls
  `init.ensure_review_cli(root)` (the module attribute, not a direct import) so **one conftest
  stub** (`monkeypatch.setattr(init_mod, "ensure_review_cli", …)`) keeps both init and doctor
  tests offline.

**Historical: the gesture was selection-aware at first.** It originally no-oped unless the
resolved review provider was `hunk` (`resolved_review_provider_id`, failing toward `None` — no
mutation — on any config/providers load failure, because a malformed config could hide a
non-`hunk` selection), and the doctor check had "not required" / quiet-`None` selection arms.
Both were dropped when the hunk CLI was decoupled from the `[providers] review` selection (a
seam that has since retired entirely — the surface doors are the selection): with no selection
read there is no
uncertain state to fail toward, so the fail-toward-no-mutation resolver went away with the gate.
The general rule survives for any future *selection-gated* host mutation: reads fall toward the
reference id, mutations fall toward *doing nothing*.

**Planning meta-rule (from the reconciliation that produced this).** The plan's spec text said a
malformed config resolves as an *empty selection* while its own test census required "malformed
committed TOML → no install call (fail toward no mutation)". When a plan's spec text and its test
census disagree, **the test census plus the stated principle win** — and the deviation gets noted
explicitly rather than silently absorbed.

## Gap-driven guided onboarding gestures

Guided `perk init` extends the external-CLI gesture pattern beyond skills and hunk. The family
lives in `src/perk/convergence/init/onboarding.py`, with one module-level function per gesture and
therefore one facade patch point each — the same discipline as `sync_skills`.

- **Gaps drive every action.** A healthy host returns no changes or warnings and never prompts,
  preserving idempotency. For a supported install, the sequence is confirm → run → re-probe; the
  fresh probe, not process exit alone, decides success.
- **Ownership decides whether installation is offered.** OS-owned prerequisites such as git and
  Node are guide-only. Supported user-space tools can be installed, but declines, failed runs, and
  failed re-probes become warnings with manual remediation; gestures never raise.
- **Machine paths are observational only.** Non-interactive calls never prompt or mutate host
  state, and `--json` disables interactivity outright. Keep this gate at the command boundary and
  still pass the explicit interactive posture into library calls so direct callers remain honest.

## A single patchable seam keeps the suite offline

`skills init` / `skills update --sync` would clone over the network during *verified* init tests
(the ones that run `verify=True`). The pattern that keeps the test suite offline:

- Route the whole shell through **one module-level function** — the **public** `init.sync_skills`
  (defined in `src/perk/convergence/init/skills.py`, re-exported through the facade precisely so
  the existing `init_mod.sync_skills` monkeypatch keeps working). Note the
  seam's signature has shifted since the original landing (an optional error-string return for
  the fatal post-step, `repo_skill_names`; the one-time `self_repo` param was dropped again when
  delivery presence went strict on `.agents/skills/`) — grep tests for the seam name
  before changing it again (see `init-doctor.md` on seam-signature ripple).
- Gate the call site `if verify:` in `run_init` — the pure unit-test path (`verify=False`) already
  skips it. (The sync runs in **both** self-repo and consumer trees — see below.)
- Stub that one seam in `tests/conftest.py`'s `stub_env`
  (`monkeypatch.setattr(init_mod, "sync_skills", lambda root, changes, **kw: None)`), next to the
  env / github stubs. Any other verified-path test (e.g. the non-fatal github test) stubs the same
  seam.

One function = one patch point. Don't scatter `subprocess.run` calls across the convergence.

## The `skills` CLI is the single delivery path (both trees)

The `skills` CLI materializes every managed `.agents/skills/<name>` in **both** self-repo and
consumer trees via `skills update --sync`. Perk-hosted includes authored and vendored skills;
required external skills use the same delivery path. The Pi package contributes only the
**extension** — its `pi`
manifest no longer lists `skills`, so Pi never discovers the package's top-level `skills/` dir
(convention auto-discovery applies *only* when no `pi` manifest is present; the manifest stays for
`extensions`). This kills the double-load that previously emitted a noisy `[Skill conflicts]` block
(Pi found each `perk-*` skill twice — once from `.agents/skills/`, once from the package `skills/`).

**Negative correction (the original assumption was wrong):** **no** settings-level package filter
(`.pi/settings.json` `"skills": []`) and **no** removal of the `..`/`git:` package are needed.
Because Pi's convention auto-discovery of a package's `skills/` dir applies *only when the package
has no `pi` manifest at all*, dropping just the `skills` key from the manifest (which stays for
`extensions`) is sufficient to stop discovery entirely. The earlier plan assumed a filter or a
package removal was required; neither is.

Consequently the `run_init` gate dropped its `not self_repo` half (`if verify:` now). `perk doctor
--fix` performs the same `init.sync_skills` under the covers as its repair gesture (plain `perk
doctor` stays read-only). The `is_self_repo(root)` split still drives install pinning (below).

**Dogfooding caveat:** because the CLI clones the perk git repo at a pinned ref into a content-
addressed worktree, a perk developer's *uncommitted* edits to `skills/<name>/SKILL.md` are not
reflected in the loaded `.agents/skills/` symlink until pushed and re-synced. The committed
`skills/<name>/` bodies remain the in-repo source; the one-time pre-sync `is_skill_installed`
fallback is retired — presence is strict on `.agents/skills/` everywhere, and the self-repo
committed-but-undelivered state is classified by doctor's `_skills_delivery_check` instead (see
`skill-bindings.md`).

## Ref pinning: the skills-manifest `main` ref beside the version-pinned installs

> **Update (superseded — the "mirrors `_desired_packages`" claim no longer holds).**
> `_desired_packages` (in `src/perk/convergence/init/settings.py`) now wires `..` for the
> self-repo and the **version-pinned** `npm:@mgiles/perk@{__version__}` (`_perk_npm_entry`) for
> consumers, and the remote CI install pins `perk=={__version__}`
> (`workflow_artifacts._PERK_INSTALL_CONSUMER`). Only the **skills-CLI manifest source ref**
> still tracks `main` (`_desired_skills_manifest`) — the why-`main` rationale below survives for
> that one surface. The full policy is `distribution.md` §"The three-way install-pin policy".

Historically the committed fragment resolved its source `ref` the same way the Pi package entry
did: both the self-repo **and** consumers tracked `main`. Still current: `PERK_SKILLS` is the
SSOT tuple of perk-hosted fragment names; `REQUIRED_EXTERNAL_SKILLS` supplies the other required
names. `_desired_skills_manifest(self_repo)` renders the YAML (the `self_repo` param is retained
for signature stability but no longer branches the ref).

Why `main`, not a tag — the original motivation: at the time perk had no release cadence. The
lone `v0.0.1` tag went stale because `__version__` was never bumped and no newer version/tag was
ever cut, so a consumer pinned to `v{__version__}` received a months-old skill set missing newer
skills → `missing-skill` at `skills update --sync`. The rationale that survives the release pipeline
(perk now cuts real `v{version}` releases — `distribution.md`): skill bodies ship via the
skills CLI's git clone, not the npm/PyPI artifacts, so `main` remains the ref that reflects the
current skill set. Trade-off: the consumer-delivered skill set is not pinned/reproducible —
accepted deliberately; a stale clone is refreshed by re-sync / `git pull`.

**`__version__`'s remaining role after the collapse (#552) — since superseded.** Once the three
consumer-ref sites collapsed `v{__version__}` → `main` — `init._desired_skills_manifest`,
`init._desired_packages` (the Pi `git:` package), and `workflow_artifacts._PERK_INSTALL_CONSUMER`
(the remote CI install) — `__version__` was for a while **only** a `perk --version` value + the
AGENTS managed-block `perk version:` stamp, never a ref pin.

> **Update.** `__version__` is again the machine-surface install pin: the npm extension entry
> (`_perk_npm_entry` → `npm:@mgiles/perk@{__version__}`) and the PyPI consumer install
> (`workflow_artifacts._PERK_INSTALL_CONSUMER` → `perk=={__version__}`) both derive from it, and
> `from perk import __version__` is back in `workflow_artifacts.py`. See `distribution.md`
> §"The three-way install-pin policy". The #552 collapse above stands as history.

## The `PERK_SKILLS` SSOT cascade + the self-converge `missing-skill` expectation (#617)

**`PERK_SKILLS` is the perk-hosted SSOT — one tuple edit feeds three mechanisms.** Adding a name
to `PERK_SKILLS` in `src/perk/convergence/init/skills.py` (kept **alphabetical**) changes the
manifest renderer and, through the derived `MANAGED_SKILL_NAMES` union, feeds `sync_skills()`'s
post-sync verification and the `skills-delivery` doctor check — **no bespoke delivery code**.
Perk-hosted means authored **or vendored**, including non-`perk-` names such as `ast-grep` and
`dignified-python`. Moving an already-required skill from an external source into `PERK_SKILLS`
changes its source mapping without changing the verification union.

Regenerate the committed fragment offline with `_converge_skills_manifest(root, True, apply=True)`
and refresh its recorded digest with `record_managed_state(root, self_repo=True)`. Compare the
fragment to `_desired_skills_manifest(True)` and inspect the state-file diff; do not run full
init merely to regenerate declarations.

**The pre-merge `missing-skill` failure is expected and does not roll back artifact writes.**
The recorded self-converge ran full `perk init` and printed
`✗ skills delivery failed: ... missing-skill`: the skills CLI resolved `source: perk → ref: main`
but the new skill **wasn't on `main` yet**. Init had already converged the managed artifacts before
its fatal sync failure. That first-appearance posture remains current: do not weaken enforcement
or point the production source at a feature branch to make a pre-merge sync pass.

Presence is strict on `.agents/skills/`, the delivery read path, even in the self-repo. Doctor
classifies a missing perk-hosted delivery with a committed `skills/<name>/SKILL.md` as pre-merge
**first appearance → warn** vs a **stale delivered set → fail**, probing the local `origin/main`.
The committed layout is never a green substitute for delivery. Offline tests disable verification
or stub the external shell; they do not need a developer's cache or a live upstream.

## Promoting external skills into the managed manifest (the three-SSOT split) (#647)

The skills-delivery surface has **three** constants in `src/perk/convergence/init/skills.py`, each with a distinct meaning —
editing the wrong one is the trap:

- **`PERK_SKILLS`** — perk-hosted skill names, authored **or vendored**, source `perk`. Add a
  skill hosted under perk's `skills/` here, regardless of authorship.
- **`REQUIRED_EXTERNAL_SKILLS`** — `(source_key, name)` pairs for skills perk *requires from
  other hosts*, declared from `REQUIRED_SKILL_SOURCES` (a frozen `SkillSource` key/url/ref
  dataclass). Add a **promoted external** skill here, and its source if new. The remaining required
  external sources are Astral and Matt Pocock; `dignified-python` now belongs to `PERK_SKILLS`,
  and Dagster is no longer a required source.
- **`MANAGED_SKILL_NAMES = tuple(sorted({*PERK_SKILLS, *external}))`** — the **verification SSOT**
  ("every skill perk requires delivered"). **Both verification consumers iterate
  `MANAGED_SKILL_NAMES`, not `PERK_SKILLS`** (`sync_skills()`'s post-sync missing-loop and
  `doctor._skills_delivery_check()`'s (c) clause). `bindings.is_skill_installed` is source-agnostic
  (checks `.agents/skills/<name>/SKILL.md`), so promoting required **no** change there.

- **Idempotency hinges on deterministic ordering.** `_desired_skills_manifest` sorts sources by
  `.key` and skills by `(source, name)` so the fragment is byte-stable — the `skills-manifest`
  ManagedConvergence stays a no-op and doctor's byte-for-byte drift compare holds. **Verify a regen
  via `_desired_skills_manifest(True) == fragment.read_text()`**, not a full `perk init` (which can
  fail on unrelated worktree state).
- **Test-substrate ripple.** Promoting external skills to *required* means verified-mode
  doctor/init tests see them missing unless the healthy-substrate planters cover them. Two planters
  had to switch `PERK_SKILLS → MANAGED_SKILL_NAMES` (`tests/conftest.py::converge_skills_workspace`,
  `tests/test_init_t5.py::_install_perk_skills`). **General rule: when widening the verified set,
  sweep every fixture that plants the "healthy" substrate.**
- **Historical gotchas confirmed live:** Dagster then tracked `ref: master`, the off-default
  ref that the original tests asserted. That is now a **legacy-fragment fixture**, not a current
  source requirement: current tests assert `dignified-python` maps once to `perk` and no Dagster
  source remains. The recorded worktree `perk init` also hit a **`conflict`** failure because its
  `.agents/skills/` symlinks were already materialized. Init reported **"Converged before failure:
  …perk.yaml: updated"** — convergence preceded the fatal sync, so the fragment was committable.
  The ordering lesson survives; use the offline seams above for declaration-only regeneration.
- **Current consumer posture:** the managed fragment resolves perk-hosted skills from `perk`
  (`main`), plus external skills from `astral` and `mattpocock`, and sync fails if any required skill
  isn't delivered. After upgrading perk, `perk init` or `perk doctor --fix` replaces the old
  Dagster mapping through normal convergence and skills-CLI link reconciliation; no custom
  migration, source fallback, or cache cleanup is needed. Required installation does not force
  invocation: the vendored `dignified-python` frontmatter remains undeclared for `stages:`, so
  consumers without a config override still expose it to all stages. Repo-specific add-ons such
  as `mastering-typescript` (source `spillwave`) remain in the **user-editable**
  `.agents/manifest.yaml` (the skills CLI merges it with `manifest.d/*.yaml`).
- Cross-ref the recurring **"run_ci green ≠ committable"** rule (pre-commit `ruff-format` can
  collapse a multi-line `"\n".join(...)` after CI passed — re-stage, re-commit) →
  `docs/learned/toolchain/ruff.md`.

## Committed declaration vs. transient state — the gitignore boundary

The manifest fragment is a **committed declaration** and is *never* gitignored (it is desired
state, like `AGENTS.md`'s managed block). The `skills` CLI writes *its own* gitignore block for the
transient `.agents/` paths it owns (`local.yaml`, `cache/`, `skills/`, `.claude/skills/`).

**perk's managed gitignore block does not touch `.agents/` at all** — that boundary is owned by the
`skills` CLI. Don't add `.agents/` entries to `GITIGNORE_BODY`; don't let perk converge paths
another tool owns. (Contrast with `.perk/workflow/` transient files, which perk *does* own and gitignore
— see `init-doctor.md`.)

## Cross-repo plans: scope the PR to the current repo

A single perk plan issue can describe work spanning **multiple repos**. Plan #51's Part 1 was Go
fragment support in `github.com/mattgiles/skills` (a *different* repo); Parts 2–4 were the perk-side
Python. The perk PR (#55) implemented **only the perk-side slice**.

When a plan has a "Part N — other-repo" section, scope the worktree implementation to the perk repo
and treat the other repo as an external dependency / precondition, not part of this PR.

## Residual gap: no version floor on the external CLI

`env.check_environment` only checks **presence** of `skills`, not its version. Fragment support is
a *version* capability: during #56 the brew-installed binary (0.5.0) predated the fragment support
that already existed in source and had to be rebuilt. A minimum-version gate is still untracked —
but the post-sync presence verification (above) now catches the worst failure mode generically: an
outdated CLI whose sync links nothing fails loudly instead of silently passing. Pathspec drift vs.
the skills CLI (under-/over-match of the pre-flight probe) remains possible; the generic post-sync
net is the backstop.

## Repo-authored skills: a second fragment, a verify-gated gesture (not a ManagedConvergence)

A repo can author its **own** skills under `.perk/skills/<name>/SKILL.md` (`REPO_SKILLS_REL`). perk renders them into a
**second** skills-CLI manifest fragment, `.agents/manifest.d/perk-repo-skills.yaml`, beside the
perk-managed `perk.yaml`, under a self-referential GitHub source derived from
`github.repo_identity` (alias `perk-<repo>`, the repo `url`, its default-branch `ref`). The
substrate is `repo_skills.build_repo_skills_manifest`; the wiring is
`repo_skills.converge_repo_skills_manifest(root, *, apply)`.

The load-bearing call: this is **NOT** a `ManagedConvergence`, even though it converges a committed
fragment. Rendering a *valid* fragment does a GitHub read (`repo_identity`), and managed
convergences run **unconditionally in offline unit tests** — so a managed convergence here would
shell `gh` in every `run_init(verify=False)`. Instead it mirrors the **skills-delivery gesture**:
init/doctor call it **under `verify` only**, right beside `sync_skills`, **before** the sync (so
the skills CLI sees the declared `.perk/skills/` source). The deciding question repeats the
init-doctor rule: *does this do network I/O on a valid input?* If yes → verify-gated gesture, never
a `ManagedConvergence`. **`.agents/manifest.yaml` is never mutated** — only the `.d/` fragment.

Posture split (the resolved grilling): structural errors + untracked warnings are **non-fatal in
`init`** — it exits 0, keeps converging, and surfaces them on the new **`InitReport.warnings`**
field (kept separate from `changes` so `changes` stays a pure delta list — the idempotency
invariant). Only the sync-time remote `missing-skill` stays **fatal** (`skills_sync_failed`). In
`doctor`, the verify-gated report-only **`repo-skills`** check (group `skills`) is fail-level for
structural errors (incl. no-GitHub-remote, which the substrate folds into `errors`) **and** drift,
warn-level for an untracked SKILL.md. `errors-present → never write or remove` keeps a
previously-good fragment from being clobbered by a transient bad edit.

The sync remediation is the **simplest** possible: no stderr parsing. `sync_skills` takes the
declared repo-authored skill **names** (`repo_skill_names`), folds them into the existing post-sync
presence loop (a free backstop for a CLI that exits 0 but skips an unresolvable skill — robust to
either "non-zero exit" or "exit-0-but-skipped" CLI behavior), and appends **one** repo-aware
remediation clause to every failure message, gated solely on "are repo-authored skills declared?"
(a freshly-added `.perk/skills/` skill is unresolvable until committed + pushed to the default branch).

### Substrate-build patterns (building the module beneath the gesture)

Building `repo_skills.build_repo_skills_manifest` (discover/parse/validate/render + orchestrator)
surfaced patterns that generalize beyond skills:

- **Gate an early-return on BOTH items AND errors.** `discover_repo_skills` returns
  `(parsed, fm_errors)`. An early-return keyed only on `parsed` empty silently drops parse errors —
  a `SKILL.md` that fails frontmatter parse leaves `parsed==[]` but `fm_errors` non-empty, so a
  bare `not parsed` guard would report a false clean "no skills". Gate on
  `not parsed and not fm_errors` so genuine no-skills still short-circuits (and skips the network)
  while parse errors fall through to surface as fatal `errors`. General lesson: when a discover step
  returns `(items, errors)`, never early-return on `items` empty alone.
- **Self-exclusion when scanning sibling fragments to detect collisions with your own output.**
  `effective_manifest_source_keys` reads `.agents/manifest.yaml` + all `.agents/manifest.d/*.yaml`
  **except** the repo-skills fragment it itself renders, so a re-render never flags itself as an
  alias collision. Generalize: any "scan siblings to validate my managed artifact" convergence
  needs this carve-out.
- **Network-skip ordering driven by testability.** Accumulate every offline failure path
  (frontmatter parse / validation / duplicate-name) and gate `if errors: return` **before** the
  one GitHub `repo_identity` read (see `github-gateway.md`), so every fatal path except
  no-GitHub-remote is exercisable offline — a test asserts the stubbed read records **zero** calls
  on those paths.
- **Byte-identical shared-constant extraction.** Factoring a literal (`MANAGED_HEADER`) into one
  constant feeding a byte-stable renderer must be verified by **direct byte-equality** against the
  live fragment, not just green CI: the ruff-format pre-commit hook reshaped a multi-line return
  into one line **after** CI passed (output bytes unchanged, but you only know by checking against
  the live `.agents/manifest.d/perk.yaml` + the manifest-drift doctor test).
- **The seam-signature ripple was a no-op.** Widening `sync_skills` with a defaulted
  `repo_skill_names` keyword needed **zero** stub edits because the existing monkeypatch stubs
  already used `lambda root, changes, **kw: ...` (`conftest.stub_env` + the test_init_t5/test_doctor
  monkeypatches) — a keyword-with-default is absorbed by `**kw` stubs. Contrast the earlier
  breaking widenings (see the seam-signature note above); the absorbing shape is the cheap one.
- **Residual: alias-grammar sanitization is intended but unbuilt.** The source alias is emitted as a
  plain `perk-<repo-name>` with no sanitization to the `skills` grammar (`^[a-z0-9][a-z0-9_-]*$`);
  a repo name with `.`/uppercase yields an invalid alias. Flagged as intended-future-work (not
  contradicted reality) — whoever owns alias-correctness adds sanitization or softens the objective
  prose.

## Cross-references

- `src/perk/convergence/init/skills.py` — `PERK_SKILLS`, `_desired_skills_manifest`,
  `_converge_skills_manifest`, `_skill_link_state`, `sync_skills`
- `src/perk/convergence/init/settings.py` — `_desired_packages`
- `src/perk/convergence/init/__init__.py` — the facade (`is_self_repo`, `run_init`)
- `src/perk/convergence/capabilities.py` — the `skills-manifest` capability
- `src/perk/convergence/doctor/data.py` — `_MANAGED_GROUP` (`skills-manifest` → `skills` group)
- `tests/conftest.py` — `stub_env` (the `sync_skills` patch seam)
- `tests/test_init_t5.py` — `test_cli_idempotent_second_run`
- `init-doctor.md` — managed-convergence SSOT and the `changes`-delta idempotency rule
- `github-gateway.md` — the `repo_identity` read shape this convergence is the sole consumer of
