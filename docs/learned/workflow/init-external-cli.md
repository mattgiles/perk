---
title: perk init shelling out to external CLIs (the skills-manifest pattern)
read_when: You are making perk init shell out to an external CLI (skills, gh, …), declaring a committed manifest fragment, pinning a ref for self-repo vs consumers, or scoping a cross-repo plan to the perk slice.
---

# `perk init` and external CLIs

perk authored skills (`skills/perk-*`) are declared in a committed manifest fragment
(`.agents/manifest.d/perk.yaml`) and materialized by `perk init` shelling out to the external
`skills` CLI (plan #51, PR #55). The patterns below generalize to any external CLI perk drives.

## Best-effort / non-fatal posture (D3)

Shelling out to an external CLI must **never block init** — file convergence has already
succeeded by the time the shell runs. `_sync_skills` mirrors the GitHub readiness probe:

- Guard on presence: `if shutil.which("skills") is None: return`.
- Wrap the subprocess calls against `OSError` / `subprocess.TimeoutExpired` and return on failure.
- Use explicit `check=False`, `capture_output=True`, `timeout=…` on every `subprocess.run`.

A missing, stale, or failing CLI degrades to a no-op, exactly like a flaky `gh` degrading to an
unauthed GitHub report.

## A single patchable seam keeps the suite offline

`skills init` / `skills update --sync` would clone over the network during *verified* init tests
(the ones that run `verify=True`). The pattern that keeps the test suite offline:

- Route the whole shell through **one module-level function** (`init._sync_skills(root, changes)`).
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

Consequently the `run_init` gate dropped its `not self_repo` half (`if verify:` now). `perk doctor
--fix` performs the same `init._sync_skills` under the covers as its repair gesture (plain `perk
doctor` stays read-only). The `is_self_repo(root)` split still drives ref pinning (below).

**Dogfooding caveat:** because the CLI clones the perk git repo at a pinned ref into a content-
addressed worktree, a perk developer's *uncommitted* edits to `skills/perk-*/SKILL.md` are not
reflected in the loaded `.agents/skills/` symlink until pushed and re-synced. The committed
`skills/<name>/` bodies remain the in-repo source and a pre-sync `is_skill_installed` fallback.

## Ref pinning mirrors `_desired_packages`

The committed fragment pins a source `ref` the same way the Pi package entry does
(`_desired_packages`): `main` for the self-repo, `v{__version__}` for consumers. `PERK_SKILLS` is
the SSOT tuple of fragment skill names; `_desired_skills_manifest(self_repo)` renders the YAML.
Keep these two ref decisions in lockstep — a consumer pinned to `v{__version__}` should resolve
skills and packages from the same tag.

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
that already existed in source and had to be rebuilt. If a consumer's installed `skills` predates
fragment support, `perk init`'s sync **silently links nothing** (no error). A minimum-version gate
is an untracked gap — keep it in mind before relying on an external CLI's newer behavior.

## Cross-references

- `perk/init.py` — `PERK_SKILLS`, `_desired_skills_manifest`, `_converge_skills_manifest`,
  `_skill_link_state`, `_sync_skills`, `_desired_packages`, `is_self_repo`, `run_init`
- `perk/capabilities.py` — the `skills-manifest` capability
- `perk/doctor.py` — `_MANAGED_GROUP` (`skills-manifest` → `skills` group)
- `tests/conftest.py` — `stub_env` (the `_sync_skills` patch seam)
- `tests/test_init_t5.py` — `test_cli_idempotent_second_run`
- `init-doctor.md` — managed-convergence SSOT and the `changes`-delta idempotency rule
