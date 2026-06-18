---
title: perk init shelling out to external CLIs (the skills-manifest pattern)
read_when: You are making perk init shell out to an external CLI (skills, gh, …), choosing a failure posture for an external substrate (best-effort vs load-bearing), declaring a committed manifest fragment, promoting an external skill into the managed manifest (the three-SSOT split — PERK_SKILLS / REQUIRED_EXTERNAL_SKILLS / MANAGED_SKILL_NAMES verification SSOT), pinning a ref for self-repo vs consumers, or scoping a cross-repo plan to the perk slice.
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

## A single patchable seam keeps the suite offline

`skills init` / `skills update --sync` would clone over the network during *verified* init tests
(the ones that run `verify=True`). The pattern that keeps the test suite offline:

- Route the whole shell through **one module-level function** (`init._sync_skills`). Note the
  seam's signature has widened since the original landing (self-repo awareness for installed-skill
  checks, an optional error-string return for the fatal post-step) — grep tests for the seam name
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
`SKILL.md`** keeps the dev-tree doctor check green (the `is_skill_installed(self_repo=True)`
fallback), and the test suite runs with **verification disabled** so no real shell runs. (`perk
init` also writes a gitignored `.pi/perk.local.toml` — never appears in `git status`.)

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

## Cross-references

- `perk/convergence/init.py` — `PERK_SKILLS`, `_desired_skills_manifest`, `_converge_skills_manifest`,
  `_skill_link_state`, `_sync_skills`, `_desired_packages`, `is_self_repo`, `run_init`
- `perk/convergence/capabilities.py` — the `skills-manifest` capability
- `perk/convergence/doctor.py` — `_MANAGED_GROUP` (`skills-manifest` → `skills` group)
- `tests/conftest.py` — `stub_env` (the `_sync_skills` patch seam)
- `tests/test_init_t5.py` — `test_cli_idempotent_second_run`
- `init-doctor.md` — managed-convergence SSOT and the `changes`-delta idempotency rule
