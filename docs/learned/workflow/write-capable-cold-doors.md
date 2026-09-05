---
title: Write-capable cold doors — borrowing the `save` stage for a session that writes the main checkout
read_when: You are building or debugging a write-capable cold door (`perk skills create`/`refine`), the repo-authored-skills lifecycle verbs, main-checkout resolution from a worktree, or the dogfood-gate test.
cluster: doors-and-launch
---

# Write-capable cold doors

Most perk cold doors are **read-only** (the plan/objective-author factories borrow the `plan` stage).
A handful instead need to **write the main checkout** from a launched session — `perk skills create`
and `perk skills refine` author/edit a repo-owned skill in place. The architectural lever and the
shared posture below are what an agent can't derive from any single file.

## Write-capable cold door = borrow the `save` stage (the architectural lever)

A dedicated cold door (a CLI verb, **not** a registry stage) that must WRITE the main checkout
borrows the **`save` stage descriptor** for launch. `save`'s descriptor pairs `mode: read-write`
with `worktree: none` — the pairing is not unique to `save` (derive the current roster of stages
carrying it from `shared/registry.yaml`); `save` is simply **the descriptor borrowed** for
repo-skill authoring. The positioning rule keys off the `worktree:` field: `worktree: none` is the
load-bearing property — it resolves to `repo_root` (the main checkout) — while a read-write stage
with `worktree: create`/`reuse` resolves to a linked worktree, which is wrong here (a repo-owned
skill lives in the main working tree). This is the
write-capable sibling of the read-only `plan`-stage borrow the plan factories use (cross-ref
`plan-factories.md`).

The borrow is otherwise **inert** — borrowing `save` injects no save-stage behavior:

- A `binding_trigger="command:skills-<verb>"` override suppresses `stage:save`'s bindings and
  delivers the authoring skill (`perk-skill-author`) instead (cross-ref the `binding_trigger`
  "borrows-a-stage" hazard in `skill-bindings.md` — **any** stage-borrowing command must set this).
- The extension's authoring-context injection is gated on the **read-only** mode (plan mode plus
  the objective-/gist-author mirrors, `extension/index.ts`), so a `mode: read-write` borrow of
  `save` injects no authoring context.

There is **no structural write-sandbox.** "Scoped to `.perk/skills/NAME/**`" is a **soft scope** carried
in the seed prompt only — nothing enforces it. Pass `repo_root` = the main checkout (see the
resolution helper below) so the launched session positions there even when the verb is invoked from a
worktree.

*Source pointers:* `src/perk/cli/commands/skills/create_cmd.py` + `refine_cmd.py` (both doors read
the `save` descriptor via `stage_by_id("save")` — `src/perk/substrate/registry.py`; the
`binding_trigger` override on the `launch_stage` call), the `src/perk/run/launch/` package
(`launch_stage` in `__init__.py` — the single cold-launch chokepoint).

## The repo-skills lifecycle verbs share one posture

`perk skills scaffold` / `delete` / `create` / `refine` (`src/perk/cli/commands/skills/`) split by
write-capability:

- **`scaffold` / `delete`** are deterministic filesystem verbs (write/rmtree the
  `.perk/skills/NAME/` dir, then reconverge).
- **`create` / `refine`** are the write-capable cold doors (borrow `save`, soft-scope seed, launch
  an authoring session).

`refine` is a **near-twin of `create`** — borrow `save`, soft-scope seed, deliver `perk-skill-author`
— minus the create-only steps: no pre-scaffold, no fragment reconverge, no `--from`. The one shape
difference: `refine` **refuses on the missing `target/"SKILL.md"` file, not the dir** (a directory
without a `SKILL.md` is not refinable), pointing the user at `perk skills create`; `create` refuses
on the **existing** dir, pointing at `perk skills refine`.

## Main-checkout resolution for repo-owned content invoked from a worktree

Content that must live in the MAIN working tree (here `.perk/skills/`, which the repo-skills
convergence reads) resolves its root via the established `config.py` precedent
`git.main_worktree_root(repo_root) or repo_root` (cross-ref `config-tables.md`'s local-secret
reader, which uses the same idiom). Factor it into **one tiny helper** (`repo_skills_root(ctx)` in
`skills/shared.py`) rather than inlining at each call site, so a verb run from inside a linked
worktree still targets the main checkout. Tests pin it offline by monkeypatching
`shared.git.main_worktree_root` → `None` (which falls back to `tmp_path`).

## Non-fatal network reconverge: the FS mutation is the deliverable, errors ride the payload

Each FS-mutating verb does the filesystem write/rmtree **FIRST** (fatal only on a true FS failure),
**THEN** calls `converge_repo_skills_manifest(root, apply=True)` whose GitHub read
(`github.repo_identity`) can fail offline / with no remote. Reconverge `errors`/`warnings` are
**surfaced** (in the `--json` payload + on stderr) but **non-fatal — exit stays 0**. This mirrors
`perk init`'s `InitReport.warnings` posture: init/doctor will reconverge later regardless, so a
transient offline reconverge must not fail the local FS verb.

Test it with a **stubbed convergence** returning a canned `RepoSkillsConvergence` /
`RepoSkillsManifest` — never hitting the network. Two scope disciplines that held:

- **Reconverge ONLY the `perk-repo-skills.yaml` fragment**, never the slow all-sources `skills update
  --sync` (the fragment is the only thing the FS mutation could have invalidated).
- **`delete`'s symlink cleanup is strictly single-target** — best-effort `unlink` the one dangling
  `.agents/skills/NAME` symlink inside `try/except OSError`; never a broad sweep.

## The dogfood-gate test pattern (stubbed external CLI → only the offline precondition is automatable)

When an E2E path depends on a stubbed external CLI **plus** a network clone, full materialization is
an inherently manual/network step that **cannot run in CI**. Here `perk skills sync` shells to the
real `skills` binary, which clones the repo's default-branch GitHub URL — uncloneable offline. So
encode only the **stitched offline precondition** as a regression test
(`tests/test_repo_skills_dogfood.py`):

- Run the **real** CLI verb with only `github.repo_identity` stubbed (so convergence renders
  offline), then assert **BOTH** the frontmatter-valid `.perk/skills/<name>/SKILL.md` **AND** the
  converged `.agents/manifest.d/perk-repo-skills.yaml` shape — i.e. the exact input `skills sync`
  consumes. Pin the main checkout to the fixture with
  `monkeypatch.setattr(shared.git, "main_worktree_root", lambda _root: None)`.
- Assert a **structural negative** ("refine skips sync") by **spying that the
  `converge_repo_skills_manifest` / `run_skills` seams stay uncalled** (monkeypatch them to append to
  a list, assert `== []`) while the launch stub fires exactly once — **stronger** than asserting the
  file is byte-unchanged (which a no-op reconverge would also satisfy).

This stitched gate is worth keeping **even when** component tests (`test_repo_skills.py`,
`test_skills_cmd.py`) already assert the sub-clauses, because its value is proving scaffold-output
**IS** sync-ready as one coherent precondition.

The **manual** network dogfood (against a `gh repo create --private --clone` scratch repo) has one
gotcha worth recording: the default `gh` token lacks the `delete_repo` scope, so the scratch remote
**can't be API-deleted** afterward.

## Cross-references

- `plan-factories.md` — the read-only `plan`-stage borrow sibling (the same lever, read-only flavor).
- `cold-door-launch.md` — `launch_stage`, the worktree `.agents/skills/` mirror.
- `config-tables.md` — the `main_worktree_root(repo_root) or repo_root` precedent (the local-secret reader).
- `init-external-cli.md` — the repo-authored-skills convergence + the `skills` CLI delivery path.
- `cli-command-groups.md` — the `perk skills` pass-through group + the parity-smoke fingerprint.
- `doc-reconciliation.md` — the docs-only-node accuracy gate.
