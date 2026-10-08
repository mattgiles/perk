---
title: Write-capable cold doors — borrowing the `save` stage for a session that writes the main checkout
read_when: You are building a write-capable cold door (skills create/refine, librarian add docs/refresh), a shared gitignored staging claim, a repo-skill move from a worktree, or a stitched offline dogfood test.
cluster: doors-and-launch
---

# Write-capable cold doors

Most perk cold doors are **read-only** (the plan/objective-author factories borrow the `plan` stage).
A handful instead need to **write the main checkout** from a launched session — `perk skills create`
and `perk skills refine` author/edit a repo-owned skill in place, and the second family,
`perk librarian add docs` and the human `perk librarian refresh <slug>` of a docs entry, curate a
documentation mirror into the gitignored library. The architectural lever and the shared posture
below are what an agent can't derive from any single file.

## Distillation

- A write-capable cold door borrows the `save` descriptor (`mode: read-write`, `worktree: none`
  → the main checkout) with an explicit `binding_trigger`; the borrow is otherwise inert and the
  write scope is soft — "Write-capable cold door = borrow the `save` stage".
- Repo-skills verbs split into deterministic FS verbs and authoring doors; retire or move a
  repo-authored skill in-branch with `git mv`/`git rm`, never `perk skills delete` from a worktree —
  "The repo-skills lifecycle verbs share one posture".
- Main-checkout content resolves through one helper over `main_worktree_root(...) or repo_root` —
  "Main-checkout resolution for repo-owned content invoked from a worktree".
- The FS mutation is the deliverable; the network reconverge after it is surfaced but non-fatal —
  "Non-fatal network reconverge".
- Doors sharing a gitignored staging area preflight before launch, claim a unique directory
  atomically, never clean, keep the dry-run write-free, and build the seed's commands once as argv —
  "Doors that share a gitignored staging area claim, never clean".
- Dogfood gates: encode the stitched offline precondition when the network hop cannot be
  localized; drive the real CLI end to end offline when it can — "The dogfood-gate test pattern".

No section below is historical; every rule is current.

## Write-capable cold door = borrow the `save` stage (the architectural lever)

A dedicated cold door (a CLI verb, **not** a registry stage) that must WRITE the main checkout
borrows the **`save` stage descriptor** for launch, for its `mode: read-write` + `worktree: none`
pairing — `worktree: none` is what positions the session in the main checkout, where a repo-owned
skill lives (the positioning rule: `cold-door-launch.md` § "`worktree: none` resolves to the main
checkout"). The pairing is not unique to `save` (derive the current roster from
`shared/registry.yaml`); `save` is simply **the descriptor borrowed** for repo-skill authoring.
This is the write-capable sibling of the read-only `plan`-stage borrow the plan factories use
(cross-ref `plan-factories.md`).

The borrow is otherwise **inert** — borrowing `save` injects no save-stage behavior:

- The explicit `binding_trigger="command:skills-<verb>"` is required: without it `stage:save`'s
  bindings fire; with it `perk-skill-author` is delivered instead (the mechanism:
  `skill-bindings.md` § "The `binding_trigger` "borrows-a-stage" hazard").
- The extension's authoring-context injection is gated on the **read-only** mode (plan mode plus
  the objective-/gist-author mirrors, installed from `extension/pi/activation.ts::activatePerk`; the
  hooks live in `extension/pi/v1/contextInjection.ts`), so a `mode: read-write` borrow of
  `save` injects no authoring context.

There is **no structural write-sandbox.** "Scoped to `.perk/skills/NAME/**`" is a **soft scope** carried
in the seed prompt only — nothing enforces it. Pass `repo_root` = the main checkout (see the
resolution helper below) so the launched session positions there even when the verb is invoked from a
worktree.

*Source pointers:* `src/perk/cli/commands/skills/create_cmd.py` + `refine_cmd.py` and
`src/perk/cli/commands/librarian/door.py` (each door reads the `save` descriptor via
`stage_by_id("save")` — `src/perk/substrate/registry.py`; the `binding_trigger` override on the
`launch_stage` call), the `src/perk/run/launch/` package (`launch_stage` in `__init__.py` — the
single cold-launch chokepoint).

## The repo-skills lifecycle verbs share one posture

`perk skills scaffold` / `delete` / `create` / `refine` (`src/perk/cli/commands/skills/`) split by
write-capability:

- **`scaffold` / `delete`** are deterministic filesystem verbs (write/rmtree the
  `.perk/skills/NAME/` dir, then reconverge).
- **`create` / `refine`** are the write-capable cold doors (borrow `save`, soft-scope seed, launch
  an authoring session).

`refine` is a **near-twin of `create`** — borrow `save`, soft-scope seed, deliver `perk-skill-author`
— minus the create-only steps: no pre-scaffold, no fragment reconverge. The one shape difference:
`refine` **refuses on the missing `target/"SKILL.md"` file, not the dir** (a directory without a
`SKILL.md` is not refinable), pointing the user at `perk skills create`; `create` refuses on the
**existing** dir, pointing at `perk skills refine`. `create` takes `--from`; `refine` does not
(semantics: `docs/user-docs/reference/cli/remote-and-utility.md`).

**Retire or move a repo-authored skill in-branch, never with `perk skills delete`.** The verb
resolves through `repo_skills_root` to the **main checkout** and removes there
(`src/perk/cli/commands/skills/delete_cmd.py`) — the wrong tree for a plan worktree. From a
worktree, `git mv` / `git rm` the skill, hand-edit `.agents/manifest.d/perk-repo-skills.yaml` to
exactly what `render_repo_skills_manifest` (`src/perk/convergence/init/repo_skills.py`) renders
(header, source block, skills sorted by name), and let `perk init` reconverge on main after
landing.

## Main-checkout resolution for repo-owned content invoked from a worktree

Content that must live in the MAIN working tree (here `.perk/skills/`, which the repo-skills
convergence reads) resolves its root via the established `config.py` precedent
`git.main_worktree_root(repo_root) or repo_root` (cross-ref `config-tables.md`'s local-secret
reader, which uses the same idiom). Factor it into **one tiny helper** (`repo_skills_root(ctx)` in
`skills/shared.py`) rather than inlining at each call site, so a verb run from inside a linked
worktree still targets the main checkout. Tests pin it offline by monkeypatching
`shared.git.main_worktree_root` → `None` (which falls back to `tmp_path`).

## Non-fatal network reconverge: the FS mutation is the deliverable

Each FS-mutating verb does the filesystem write/rmtree **FIRST** (fatal only on a true FS failure),
**THEN** calls `converge_repo_skills_manifest(root, apply=True)` whose GitHub read
(`github.repo_identity`) can fail offline / with no remote. Reconverge `errors`/`warnings` are
**surfaced but non-fatal — exit stays 0**. This mirrors `perk init`'s `InitReport.warnings`
posture: init/doctor will reconverge later regardless, so a transient offline reconverge must not
fail the local FS verb. Where they surface depends on the verb:

- **`scaffold` / `delete`** return a result: under `--json` the payload carries `warnings`/`errors`
  (stdout, via `emit`); the human path prints them to stderr.
- **`create`** never returns: after `perform_scaffold` it prints warnings/errors to stderr via
  `user_output` on both the human and `--json` paths, then execs its authoring session, so there
  is no outcome payload. Its only `machine_output` is the `--dry-run --json` preview, which
  scaffolds nothing.

Test it with a **stubbed convergence** returning a canned `RepoSkillsConvergence` /
`RepoSkillsManifest` — never hitting the network. Two scope disciplines that held:

- **Reconverge ONLY the `perk-repo-skills.yaml` fragment**, never the slow all-sources `skills update
  --sync` (the fragment is the only thing the FS mutation could have invalidated).
- **`delete`'s symlink cleanup is strictly single-target** — best-effort `unlink` the one dangling
  `.agents/skills/NAME` symlink inside `try/except OSError`; never a broad sweep.

## Doors that share a gitignored staging area claim, never clean

`perk librarian add docs` and the human `perk librarian refresh <slug>` of a docs entry crawl
into a staging directory under the gitignored library (`src/perk/library/docs_session.py`,
contracts §8.75(k)). The rules that held:

- **Run the cache-only preflight before launch**, so a refusal costs no session.
- **Claim atomically, never clean.** Claim a unique per-session directory with `mkdir` without
  `exist_ok` over `<slug>`, `<slug>-2`, …; never delete an existing one — it may be an in-progress
  or abandoned run (a leftover is `list`'s to report and the human's to dispose of).
- **Keep the dry-run write-free.** It previews the first free name; the real launch claims its own,
  which may differ.
- **Build the seed's commands once, as argv** (`DocsCrawlPlan`) and render them with `shlex.join`,
  so the dry-run and the seed cannot diverge and paths with spaces or URLs with `&` / `?`
  round-trip.
- **Run the delivered skill script through perk's own interpreter** (`sys.executable`), never an
  assumed `python3`.

## The dogfood-gate test pattern — precondition-only, or the stitched real-CLI variant

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

**The stronger variant — the stitched real-CLI dogfood.** When the network hop can be localized,
drive the real CLI end to end offline. `tests/test_library_dogfood.py` does: `tests/_library_upstream.py`
points `url.<base>.insteadOf` env config at a local bare repo (`workflow/git-substrate.md` §
"Config-pinned is not a sandbox"), so real `CliRunner` sequences cover adopting flat mirrors by
their printed hints, pin → throttle → drift → refresh, and first use from a consumer's main checkout
and from a linked worktree. Craft:

- Commit the scaffold's untracked init output first (`_commit_scaffold`) — that baseline is a
  fixture fact, not an observation.
- Use `--untracked-files=all` for every clean-tree assertion; default porcelain collapses a new
  directory to its first untracked ancestor.
- Mark a case `slow` only from a measured ≥ 1 s serial median (`toolchain/test-parallelism.md`).

## Cross-references

- `plan-factories.md` — the read-only `plan`-stage borrow sibling (the same lever, read-only flavor).
- `cold-door-launch.md` — `launch_stage`; § "`worktree: none` resolves to the main checkout" (the
  positioning rule the `save` borrow relies on); the worktree `.agents/skills/` mirror.
- `skill-bindings.md` — § "The `binding_trigger` "borrows-a-stage" hazard" (the trigger-diversion
  mechanism).
- `config-tables.md` — the `main_worktree_root(repo_root) or repo_root` precedent (the local-secret reader).
- `init-external-cli.md` — the repo-authored-skills convergence + the `skills` CLI delivery path.
- `cli-command-groups.md` — the `perk skills` pass-through group + the parity-smoke fingerprint.
- `doc-reconciliation.md` — the docs-only-node accuracy gate.
- `src/perk/library/docs_session.py` — the docs doors' deterministic half (preflight, staging
  claim, `DocsCrawlPlan`); `src/perk/cli/commands/librarian/door.py` — the launch glue.
- `tests/test_library_dogfood.py` + `tests/_library_upstream.py` — the stitched real-CLI dogfood
  and its offline bare upstream.
- `pi/read-only-bash-gate.md` — why `perk librarian prepare …` stays gate-blocked and `add docs` is
  not admitted.
- `git-substrate.md` — the config pin, the lock-free clone fence, the env-config `insteadOf` seam.
