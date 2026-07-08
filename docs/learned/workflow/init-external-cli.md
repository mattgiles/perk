---
title: perk init shelling out to external CLIs (the skills-manifest pattern)
read_when: You are making perk init shell out to an external CLI (skills, gh, …), choosing a failure posture for an external substrate (best-effort vs load-bearing), adding a selection-aware best-effort install/verify gesture for an external CLI (the review-seam `ensure_review_cli` shape — never-raises, warn-level verify-gated doctor check, facade-attribute `--fix` retry, fail-toward-no-mutation resolution), declaring a committed manifest fragment, promoting an external skill into the managed manifest (the three-SSOT split — PERK_SKILLS / REQUIRED_EXTERNAL_SKILLS / MANAGED_SKILL_NAMES verification SSOT), pinning a ref for self-repo vs consumers, or scoping a cross-repo plan to the perk slice.
---

# `perk init` and external CLIs

perk authored skills (`skills/perk-*`) are declared in a committed manifest fragment
(`.agents/manifest.d/perk.yaml`) and materialized by `perk init` shelling out to the external
`skills` CLI (plan #51, PR #55). The patterns below generalize to any external CLI perk drives.

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

## The selection-aware best-effort install/verify gesture (the review-seam `hunk` CLI)

A **new point on the best-effort↔load-bearing spectrum** landed beside the skills posture: an
external CLI that is a *provider selection's* substrate, not perk's own — install/verify it
best-effort, **only when the selection asks for it**, never fatally. The realized shape (the
review seam's `hunk` CLI, installed via `npm i -g hunkdiff`):

- **A small gesture module** — `src/perk/convergence/init/review_cli.py`,
  `ensure_review_cli(root) -> (changes, warnings)`. Never raises: no-op unless the resolved review
  provider is `hunk` *and* the binary is absent; `NpmError` degrades to **one warning carrying the
  manual-install hint** (`HUNK_INSTALL_HINT`), never a failed init.
- **A global-install npm gateway op** — `install_global` in `src/perk/substrate/npm.py`
  (`npm install -g <spec>`, for global CLI binaries as opposed to Pi packages).
- **Verify-gated `run_init` wiring** — the gesture is a network op, so it runs under `if verify:`
  only (the same rule that keeps managed convergences offline; see the repo-skills section below).
- **A doctor warn-level selection-aware check** — `review-cli` in
  `src/perk/convergence/doctor/checks.py`, gated **inside `if verify:` because a PATH probe is
  host-dependent** — keeping `verify=False` check lists byte-stable. It returns `None` (no check
  at all) when the selection cannot be resolved, and an ok/"not required" row when a non-`hunk`
  provider is selected.
- **The `--fix` retry goes through the facade attribute** — doctor calls
  `init.ensure_review_cli(root)` (the module attribute, not a direct import) so **one conftest
  stub** (`monkeypatch.setattr(init_mod, "ensure_review_cli", …)`) keeps both init and doctor
  tests offline.

**Fail toward no mutation.** `resolved_review_provider_id` returns `None` on
`TOMLDecodeError`/`ConfigError` as well as `ProvidersError` — a global install is a **host
mutation**, and a malformed config could hide a non-default selection, so the gesture must never
install onto uncertain state (the config/providers checks own surfacing those failures). Contrast
the resolver's usual fail-safe-to-default posture: reads fall toward the reference id, mutations
fall toward *doing nothing*.

**Planning meta-rule (from the reconciliation that produced this).** The plan's spec text said a
malformed config resolves as an *empty selection* while its own test census required "malformed
committed TOML → no install call (fail toward no mutation)". When a plan's spec text and its test
census disagree, **the test census plus the stated principle win** — and the deviation gets noted
explicitly rather than silently absorbed.

## A single patchable seam keeps the suite offline

`skills init` / `skills update --sync` would clone over the network during *verified* init tests
(the ones that run `verify=True`). The pattern that keeps the test suite offline:

- Route the whole shell through **one module-level function** (`init._sync_skills`). Note the
  seam's signature has shifted since the original landing (an optional error-string return for
  the fatal post-step, `repo_skill_names`; the one-time `self_repo` param was dropped again when
  delivery presence went strict on `.agents/skills/`) — grep tests for the seam name
  before changing it again (see `init-doctor.md` on seam-signature ripple).
- Gate the call site `if verify:` in `run_init` — the pure unit-test path (`verify=False`) already
  skips it. (The sync runs in **both** self-repo and consumer trees — see below.)
- Stub that one seam in `tests/conftest.py`'s `stub_env`
  (`monkeypatch.setattr(init_mod, "_sync_skills", lambda root, changes: None)`), next to the env /
  github stubs. Any other verified-path test (e.g. the non-fatal github test) stubs the same seam.

One function = one patch point. Don't scatter `subprocess.run` calls across the convergence.

## The `skills` CLI is the single delivery path (both trees)

The `skills` CLI materializes `.agents/skills/perk-*` in **both** self-repo and consumer trees via
`skills update --sync`. The `..`/`git:` Pi package contributes only the **extension** — its `pi`
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
--fix` performs the same `init._sync_skills` under the covers as its repair gesture (plain `perk
doctor` stays read-only). The `is_self_repo(root)` split still drives ref pinning (below).

**Dogfooding caveat:** because the CLI clones the perk git repo at a pinned ref into a content-
addressed worktree, a perk developer's *uncommitted* edits to `skills/perk-*/SKILL.md` are not
reflected in the loaded `.agents/skills/` symlink until pushed and re-synced. The committed
`skills/<name>/` bodies remain the in-repo source and a pre-sync `is_skill_installed` fallback.

## Ref pinning mirrors `_desired_packages`

The committed fragment resolves its source `ref` the same way the Pi package entry does
(`_desired_packages`): both the self-repo **and** consumers track `main`. `PERK_SKILLS` is
the SSOT tuple of fragment skill names; `_desired_skills_manifest(self_repo)` renders the YAML
(the `self_repo` param is retained for signature stability but no longer branches the ref).

Why `main`, not a tag: perk has no release cadence. The lone `v0.0.1` tag went stale because
`__version__` was never bumped and the tag never moved, so a consumer pinned to `v{__version__}`
received a months-old skill set missing newer skills → `missing-skill` at `skills update --sync`.
`main` is the only ref that reflects current state for this pre-1.0 rolling tool. Trade-off:
consumer installs are no longer pinned/reproducible — accepted deliberately; a stale clone is
refreshed by re-sync / `git pull`.

The lockstep principle still holds, restated: the skills source, the Pi `git:` package, and the
remote CI install (`workflow_artifacts._PERK_INSTALL_CONSUMER`) all resolve from the same `main`
ref.

**`__version__`'s remaining role after the collapse (#552).** Once the three consumer-ref sites
collapsed `v{__version__}` → `main` — `init._desired_skills_manifest`, `init._desired_packages` (the
Pi `git:` package), and `workflow_artifacts._PERK_INSTALL_CONSUMER` (the remote CI install) —
`__version__` is now **only** a `perk --version` value + the AGENTS managed-block `perk version:`
stamp, **never again a ref pin**. The import was therefore **removed from `workflow_artifacts.py`**
(and its test) once the last ref reference left, while `init.py` keeps it for the managed-block stamp
and `test_init_idempotent.py` keeps it for the self-mode negative assertion.

## The `PERK_SKILLS` SSOT cascade + the self-converge `missing-skill` expectation (#617)

**`PERK_SKILLS` is a true SSOT — one tuple edit cascades to three mechanisms.** Adding a skill name to
the `PERK_SKILLS` tuple in `init.py` (kept **alphabetical**) auto-regenerates the committed manifest
fragment (the `skills-manifest` ManagedConvergence), feeds `sync_skills()`'s post-sync verification,
and is picked up by the `skills-delivery` doctor check — **no further code change**. The SSOT holds
even for a **non-`perk-` skill name** (e.g. a bundled upstream skill like `ast-grep`).

**The pre-merge `missing-skill` failure is EXPECTED and non-fatal to the artifact write.** Running
the worktree's `perk init` to regenerate the managed artifacts prints a loud
`✗ skills delivery failed: ... missing-skill` — because the skills CLI resolves `source: perk →
ref: main` and the new skill **isn't on `main` yet**. This is the **documented first-appearance
path**: init **still converges** the managed artifacts (manifest fragment + AGENTS.md), which is
exactly what you commit — don't try to "fix" the sync failure. The committed **working-tree
`SKILL.md`** keeps the dev-tree doctor check at **warn** (never green: `is_skill_installed` is
strict on the `.agents/skills/` delivery read path — the only path warm injection reads — and the
skills-delivery check classifies a missing self-repo delivery as pre-merge **first appearance →
warn** vs a **stale delivered set → fail** by probing the local `origin/main` for the committed
`skills/<name>`), and the test suite runs with **verification disabled** so no real shell runs.
(`perk init` also writes a gitignored `.pi/perk.local.toml` — never appears in `git status`.)

## Promoting external skills into the managed manifest (the three-SSOT split) (#647)

The skills-delivery surface has **three** constants in `init.py`, each with a distinct meaning —
editing the wrong one is the trap:

- **`PERK_SKILLS`** — perk-authored skill names only, source `perk`. Add a **perk** skill here.
- **`REQUIRED_EXTERNAL_SKILLS`** — `(source_key, name)` pairs for non-perk skills perk *requires*,
  declared from upstream `REQUIRED_SKILL_SOURCES` (a frozen `SkillSource` key/url/ref dataclass).
  Add a **promoted external** skill here, and its source if new.
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
- **Gotchas confirmed live:** **dagster tracks `ref: master`** (the one off-default ref — tests
  assert it). A worktree `perk init` regen can surface a **`conflict`** failure (not the planned
  first-appearance `missing-skill`) because the worktree's `.agents/skills/` symlinks were already
  materialized; crucially init reports **"Converged before failure: …perk.yaml: updated"** — the
  fragment convergence runs **before** the fatal sync, so the regenerated fragment is correct and
  committable regardless of the sync conflict. **Don't be alarmed by the conflict; check "Converged
  before failure" and verify the fragment content.**
- **Posture note:** this is **consumer-visible** — a consumer's `perk init` now clones the new
  sources (`astral`/`dagster`/`mattpocock`) and fails if any required skill isn't delivered.
  `mastering-typescript` (source `spillwave`) deliberately stays in the **user-editable**
  `.agents/manifest.yaml` as the one repo-specific add-on (the skills CLI merges `manifest.yaml` +
  `manifest.d/*.yaml`).
- Cross-ref the recurring **"run_ci green ≠ committable"** rule (pre-commit `ruff-format` can
  collapse a multi-line `"\n".join(...)` after CI passed — re-stage, re-commit) →
  `docs/learned/toolchain/ruff.md`.

## Committed declaration vs. transient state — the gitignore boundary

The manifest fragment is a **committed declaration** and is *never* gitignored (it is desired
state, like `AGENTS.md`'s managed block). The `skills` CLI writes *its own* gitignore block for the
transient `.agents/` paths it owns (`local.yaml`, `cache/`, `skills/`, `.claude/skills/`).

**perk's managed gitignore block does not touch `.agents/` at all** — that boundary is owned by the
`skills` CLI. Don't add `.agents/` entries to `GITIGNORE_BODY`; don't let perk converge paths
another tool owns. (Contrast with `.pi/workflow/` transient files, which perk *does* own and gitignore
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

A repo can author its **own** skills under `.pi/skills/<name>/SKILL.md`. perk renders them into a
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
the skills CLI sees the declared `.pi/skills/` source). The deciding question repeats the
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
(a freshly-added `.pi/skills/` skill is unresolvable until committed + pushed to the default branch).

### Substrate-build patterns (the dormant module beneath the gesture)

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

- `perk/convergence/init.py` — `PERK_SKILLS`, `_desired_skills_manifest`, `_converge_skills_manifest`,
  `_skill_link_state`, `_sync_skills`, `_desired_packages`, `is_self_repo`, `run_init`
- `perk/convergence/capabilities.py` — the `skills-manifest` capability
- `perk/convergence/doctor.py` — `_MANAGED_GROUP` (`skills-manifest` → `skills` group)
- `tests/conftest.py` — `stub_env` (the `_sync_skills` patch seam)
- `tests/test_init_t5.py` — `test_cli_idempotent_second_run`
- `init-doctor.md` — managed-convergence SSOT and the `changes`-delta idempotency rule
- `github-gateway.md` — the `repo_identity` read shape this convergence is the sole consumer of
