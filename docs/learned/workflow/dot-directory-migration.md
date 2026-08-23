---
title: The `.pi/`→`.perk/` dot-directory migration — canonical contract + phased path-root move mechanics
read_when: You are relocating a perk-owned dot-directory path root, using the centralized path seam (`paths.py`/`paths.ts`), answering "where does X live?", or dogfooding a gitignored cache-root move mid-flight.
cluster: code-migration
---

# The `.pi/`→`.perk/` dot-directory migration

A multi-node arc (objective #878) moved perk's owned dot-directory state out of the shared `.pi/`
namespace into a dedicated `.perk/` root. This doc is the completed-migration record; its durable
content is the cross-cutting mechanics —
the ownership contract, the centralized path seam, the sweep discipline, the filesystem-migration
pattern, and the dogfood hazards — so a future path-root move is a localized edit rather than a
repo-wide archaeology dig.

## Distillation

- `.perk/` is perk-owned; `.pi/`/`.agents/` are discovery namespaces perk only *contributes*
  materializations into — "The canonical dot-directory contract".
- One redirectable per-plane path seam, established first, makes each move a localized edit —
  "The centralized path seam".
- The family guard is a regression backstop + consumer-census oracle, never completeness — "The
  source-scan guard is a backstop"; sweeps need three grep forms — "Path-root sweeps".
- Forward-only idempotent doctor migrations: move / identical-drop / conflict-retain, with the
  deep-compare gotchas — "The `_MIGRATIONS` filesystem-migration pattern".
- Dogfooding a gitignored cache-root move forces same-turn worktree-binding + gitignore
  reconverge — "BIGGEST: dogfooding a gitignored cache-root move".
- All three families ship under `.perk/`, with live doctor migrations and guard/SSOT pointers —
  "The enacted contract".

## The canonical dot-directory contract (ownership-vs-discovery)

`.perk/` is **perk-owned**: committed source (`config.toml`, `skills/`) plus a local cache
(`workflow/`, `local.toml`). `.pi/` and `.agents/` are **discovery namespaces** owned by Pi and the
skills CLI respectively — perk writes only a few *generated materializations* into them: the
perk-managed slice of `.pi/settings.json`, `.pi/agents/perk/*.md`, `.pi/APPEND_SYSTEM.md`, and
`.agents/manifest.d/perk*.yaml`. **Never imply `.pi/` is generally perk-owned** — perk owns its
own root and *contributes* materializations into the discovery roots.

The SSOT for the contract is
`docs/user-docs/reference/configuration/repository-layout.md` → section "Repository layout — the
dot-directory contract"; the compact mirror is `skills/perk-expert/references/configuration.md`
(user-docs is SSOT via its *Canonical sources* footer). Per the config-surface second-mirror
convention, **update BOTH the same turn** the topology changes.

## The centralized path seam (Node 1.1)

Two per-plane leaf seams — `src/perk/substrate/paths.py` + `extension/substrate/paths.ts` — own
construction of the perk-owned dot-path families: `config_dir`, `config_file`,
`local_config_file`, `repo_skills_dir`, plus the filename constants `CONFIG_FILENAME`,
`LOCAL_CONFIG_FILENAME`, `REPO_SKILLS_REL`. The **workflow** family stays in the established cache
seam (`cache.workflow_dir` / `workflowDir`) — it was already centralized there — so the path
guards allowlist BOTH `paths` and `cache`. The Pi-root helpers (`perk_dir`/`perkDir`, returning
`<root>/.pi`) were deleted as dead code — zero callers on either plane, and the names contradicted
the ownership contract (`.pi/` is a discovery namespace, not perk-owned).

Establishing the redirectable seam **first** is what makes each later move-phase a localized edit:
`config_dir` is the single config-family redirection point, and the file helpers
(`config_file`/`local_config_file`) derive from it rather than re-constructing the root. Re-export
constants to avoid call-site churn — `REPO_SKILLS_REL` is re-exported from `paths` via the
redundant-alias (F401-silencing) form.

> Correction to a planning-time assumption: there is **no** `REPO_SKILLS_DIR` constant. The family
> is `REPO_SKILLS_REL` (the display string) + `repo_skills_dir()` (the `Path`).

The seam has since grown beyond the original family (the `legacy_*` accessors and
managed-state/required-version helpers) — the module itself is the census.

## The source-scan guard is a backstop, not completeness

(Cross-ref `source-scan-guards.md`.) The dot-dir family guard matches a quoted dot-segment that is
operator-adjacent to a family follow-segment, so it **deliberately misses**:

- split-across-variables construction (`pi_dir = root / ".pi"` then `pi_dir / name`);
- single-string-literal forms (`".pi/workflow"`, `Path(".pi/skills")`).

A manual census is still required — the guard is a regression *backstop*, not a completeness proof.
BUT the family-scoped guard doubles as a **consumer-census oracle**: write it early and let its
first run enumerate the production consumers the plan census overlooked; then grep the
split/single-string forms by hand.

## Path-root sweeps need THREE grep forms

A path-root rename has three distinct sweep surfaces, and forms (2)/(3) break only at runtime if
missed:

1. **slash-literal** — `.pi/workflow`;
2. **pathlib/join token** — `".pi" / "workflow"` or `".pi", "workflow"`;
3. **escaped-regex** — `\.pi\/workflow` (in TS test assertions).

## Filesystem-failure-injection tests target the root dir by NAME

Tests that force a write failure by chmod-ing the root read-only (e.g. set `.pi` to `0o444` so a
`mkdir` beneath it fails) **silently pass-by-not-failing** after the root moves — the old name no
longer exists, so nothing fails. Repoint the chmod target to the new root or the test stops
exercising the failure path.

## The `_MIGRATIONS` filesystem-migration pattern (Nodes 3.1, 4.1)

Forward-only, filesystem-only (no network), idempotent (`([],[])` once the legacy root is gone).
Per-child triad:

- **move** when the target is absent (`shutil.move`);
- **drop** the redundant legacy copy when it is byte-identical to the target;
- **report a conflict and LEAVE IN PLACE** when they differ — errors ride `fix_errors`, loud.

`rmdir` the legacy root only when it is empty. The skills/workflow migrations write legacy paths as
**frozen flat-string literals** (`Path(".pi/skills")`, `root / ".pi/workflow"`), while the
**config** migration constructs its legacy paths via the seam's `legacy_*` helpers
(`legacy_config_file`/`legacy_local_config_file` — built only for the doctor migration, never read
by config readers); both shapes stay exempt from the operator-adjacency paths guard by design —
the seam's *primary* accessors point at the new home.

### Byte-identical directory-compare gotchas (the durable cross-cutting insight, Node 4.1)

The naive `filecmp.dircmp` 4-bucket check (`left_only` / `right_only` / `diff_files` /
`funny_files`) is **WRONG twice**:

- **(a) `dircmp.diff_files` is a SHALLOW compare** — it stats size+mtime, not content. Two files
  with an equal stat signature but differing content land in NO rejected bucket → a false
  "identical" → a **silent drop**. Force a content compare with
  `filecmp.cmpfiles(..., shallow=False)` and reject on `mismatch or errors`.
- **(b) same-name type collisions (dir vs file)** file under `common_funny`, not any of the four
  buckets — add them to the rejection explicitly.

Recursion descends via `common_dirs` — **test it with a DEEP nested-only difference**, not a flat
single-file diff, or the recursion path goes unexercised.

### Adding to `_MIGRATIONS` ripples into tests monkeypatching shared git primitives

A new migration that calls the same `git.is_tracked` / `git.rm_cached` as an existing one **shifts
the observed `fix_errors` count** in unrelated migration tests that monkeypatch those primitives
globally. Expect to update the count assertions in sibling tests.

### `init` no longer creating the legacy dir breaks tests that assumed it did

Once convergence stops creating `.pi/workflow/` (+ its `.gitkeep`), tests that wrote a legacy file
there were relying on `init` to make the dir — they now need an explicit `mkdir(parents=True)`.

## The manifest fragment is source-location-independent

The skills-manifest `source` points at the whole repo URL (+ ref) and encodes **no** source
subdirectory, so a `.pi/skills`→`.perk/skills` move yields a **byte-identical** fragment.
"Regeneration" is the reconverge re-reading the new dir, not a content change.

> Correction: "regenerate the manifest with new source paths" was a planning-time no-op — the
> fragment does not encode the source subdir at all.

## BIGGEST: dogfooding a gitignored cache-root move mid-flight forces a self-repo reconverge to LAND

A worktree positioned by the *pre-change* perk holds its in-flight binding `plan-ref.json` at the
**old** path. `/submit` (running new code) reads the **new** path → "No saved plan in this
worktree." Copying the binding to the new path then trips `/submit`'s "Uncommitted changes" guard,
because the self-repo's COMMITTED `.gitignore` still lists the old ignore lines — leaving `.perk/`
untracked-and-unignored.

Landing required, the same turn:

1. move the worktree binding to the new path;
2. re-run `perk init` to reconverge the self-repo `.gitignore` to the new wholesale entry;
3. remove the now-legacy tracked `.gitkeep`.

**A phase-split move of a gitignored cache location cannot be fully deferred when dogfooded live** —
expect to migrate the active worktree binding + reconverge the self-repo gitignore the same turn you
land.

### Test-fixture ripple when a path seam moves (Node 4.1)

Helpers that plant under the old root then `_commit(root, ".pi")` / `git add .pi` **break loudly**
(`git add .pi` exits 128 — pathspec didn't match) once the dir is gone. Flip the plant path AND the
commit/add path argument **together**.

## Editing the AGENTS managed block (Node 5.1)

The block is generated by `src/perk/convergence/init/blocks.py::_agents_inner()`. After editing the
generator you MUST regenerate this repo's committed managed block by running `perk init` **the same
turn**, else the committed block drifts. `tests/test_init_idempotent.py` asserts only **substrings**
("perk conventions", "GitHub access goes through the `gh` CLI", "Prefer ast-grep for code search") —
preserve those exact substrings across rewordings; if a reword drops one, fix the substring in the
test (don't add a byte-exact block assertion).

### `perk init` in a worktree fails skills-sync but still converges AGENTS

`perk init` in a linked worktree exits non-zero with `✗ skills delivery failed: … conflict` (every
skill conflicts in a linked worktree) — the known non-fatal worktree gotcha. It reports `Converged
before failure:` **first**, so the managed-block regen still lands. **Verify the AGENTS block
directly** rather than trusting the exit code. (`.perk/local.toml: created` also appears — it's
gitignored, so expect it absent from `git status`.)

### Audit-before-edit when earlier nodes migrated in-turn (Node 5.1)

A node description can name files that earlier nodes already moved, or that are already precise →
the work is audit-only / no-change. **Don't blindly retarget every named file; grep first.** The
verification grep
`grep -rn '\.pi/workflow\|\.pi/perk\.toml\|\.pi/skills' docs/user-docs skills` should return ONLY
the deliberate "Migrating from `.pi/perk.toml`" legacy callouts — KEEP those. `docs/design/*`,
`docs/learned/*`, `docs/planning/*` are historical records — out of scope for path migrations.

## The legacy doctor check is warn-only-when-actionable

It warns **only** when `--fix` has something to do — a tracked legacy `.gitkeep`, or a movable
mirror (`plan-ref.json` / `agent-session.json`) at the legacy path with the target absent — and
never flags disposable scratch/handoff/markers. So it converges to `ok` and never becomes permanent
noise.

## The enacted contract

The migration is complete — all three families ship under `.perk/`: **config** at
`.perk/config.toml` (+ `.perk/local.toml`; the legacy `.pi/perk.toml` / `.pi/perk.local.toml`
paths survive only as the seam's `legacy_*` helpers, never read by config readers), the
**workflow cache** at `.perk/workflow/` (`cache.workflow_dir` / `workflowDir`), and **repo
skills** at `.perk/skills/` (`REPO_SKILLS_REL`). The doctor migrations are live —
`src/perk/convergence/doctor/fixes.py::_MIGRATIONS` includes `_migrate_legacy_workflow_cache`,
`_migrate_legacy_repo_skills`, and `_migrate_legacy_config`, each following the
move/identical-drop/conflict-retain triad above. Enforcement: `tests/test_paths_guard.py` +
`extension/pathsGuard.test.ts`; the layout SSOT is
`docs/user-docs/reference/configuration/repository-layout.md`.

Objective #878 is GitHub-backed (header + roadmap-only, no Reconcilable prose region) → landed
narratives live in NODE descriptions ("LANDED (PR #N)" convention, `pr` field = plan-issue #,
narrative cites the merge PR).

## Sources

- Issues #897, #901, #905, #908; plans #891, #899, #902, #906; PRs #900, #904, #907; objective #878.

## Cross-references

- `docs/learned/workflow/source-scan-guards.md` — the path-family guard widened across this migration
- `docs/learned/workflow/init-doctor.md` — init convergence + the warn-when-actionable doctor check
- `docs/learned/workflow/config-tables.md` — the config-file readers the config move touched
- `docs/learned/workflow/init-external-cli.md` — the skills manifest reconverge
- `docs/learned/workflow/write-capable-cold-doors.md` — `repo_skills_root` / the skills source dir
- `docs/learned/workflow/worktree-lifecycle.md` — the worktree binding + gitignore dogfood hazard
- `docs/user-docs/reference/configuration/repository-layout.md` — the canonical dot-directory contract (SSOT)
