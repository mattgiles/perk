---
title: Python CLI command groups — the §8.1 group-dir template, hybrid stage/group coexistence, sectioned help
read_when: You are adding or folding a `perk` CLI command group, a shell-emitting verb (copyable hints, emitted scripts), the sectioned root `--help` taxonomy, a pass-through noun-group, or a CLI refactor.
cluster: doors-and-launch
---

# CLI command groups

The perk CLI's command surface is organized as group directories under `src/perk/cli/commands/`
with a sectioned root help. This doc is the structure playbook: the group-dir template, the hybrid
default-dispatch recipe for stage-name/group collisions, byte-compat discipline across folds, the
help taxonomy, and the test patterns that made the migrations cheap. Realized shapes to copy:
`src/perk/cli/commands/objective/`, `src/perk/cli/commands/pr/`, `src/perk/cli/commands/learn/`,
`src/perk/cli/commands/plan/`, `src/perk/cli/commands/gist/`.

## Distillation

- New/folded command groups follow the group-dir template: `__init__.py` (docstring + AliasGroup
  + bottom registrations), standalone `{verb}_{noun}` command files, cross-verb helpers in
  `{group}/shared.py` (underscore dropped), envelope helpers once in `src/perk/cli/emit.py` —
  "The §8.1 group-dir template".
- A stage name colliding with a group name uses the hybrid default-dispatch group recipe
  (Click 8.4.x) — "The hybrid default-dispatch group recipe".
- Root `--help` is a fixed taxonomy rendered by `SectionedGroup` — "Sectioned root help
  (`SectionedGroup`)"; new commands must land in a section.
- CLI-structure tests ride the registry-keyed help-census pattern (+ the Click help-wrap
  gotcha) — "The registry-keyed help-census test pattern".
- Shell-emitting verbs: the emitted source is a PROGRAM, not display text — quote/escape and pin
  it byte-exactly — "Shell-emitting CLI verbs — emitted shell source is a program, not text".
- Historical: "The enacted taxonomy arc" is the node-by-node chronicle of the taxonomy
  migration — a record, not a playbook.

## The §8.1 group-dir template

- `commands/{group}/__init__.py` carries: the design docstring (the original module's design prose),
  the `AliasGroup` group def, top-of-file imports of the verb commands, and one
  `register_with_aliases(group, verb)` call per verb at the bottom.
- Verb files are standalone `@click.command("name")` defs (never `@group.command(...)` decorators)
  named `{verb}_{noun}` (e.g. `submit_pr`), with a one-line docstring naming the command.
- Verb-local helpers move with the verb and keep their `_` prefix. Cross-verb helpers go in
  `{group}/shared.py` and **drop the leading underscore** — intentional intra-package API
  (e.g. `parse_objective_id`, `action_payload`).
- The result-envelope helpers (`fail`/`emit`/`EXIT_FOR_TYPE`) live **once** in
  `src/perk/cli/emit.py` — a neutral `src/perk/cli/`-level leaf beside `context.py`/`ensure.py`
  that every group (and `perk_dev`) imports. Groups still never import another group's `shared.py`.
- Nested groups nest dirs and follow the same pattern recursively (`workflow/run/`,
  `doctor/workflow/`).

## Dissolving Click registration cycles via a sibling render module

When a subgroup needs the parent's helpers, the import cycle is **helper-induced, not
registration-induced** — extract the shared helpers into a sibling leaf module (the
`src/perk/cli/commands/doctor/render.py` pattern) so both `__init__.py`s import top-of-file
normally.
Prefer this over the bottom-of-file `# noqa: E402` import idiom whenever shared helpers cause the
cycle; bottom-of-file imports remain only for genuinely registration-induced cycles (see
`workflow/init-doctor.md`).

## The hybrid default-dispatch group recipe (Click 8.4.x)

When a stage launcher and a command group want the same name (`perk learn` launches the learn stage
AND `perk learn capture|docs` are verbs), the coexistence template is
`src/perk/cli/commands/learn/__init__.py` (`LearnGroup`):

- Group `context_settings={"ignore_unknown_options": True}` so launcher options (`--worktree`,
  `--dry-run`, `--remote`, pi-args) survive group-level parsing and reach `resolve_command` intact.
- A `parse_args` override: empty args → substitute the hidden launcher name (guard
  `ctx.resilient_parsing` for shell completion, and only when the launcher actually registered).
  This makes bare `perk learn` launch instead of printing group help.
- A `resolve_command` override: if `args[0]` is a registered verb, defer to `super()`; otherwise
  route to the launcher with **ALL args preserved** — Click's default convention strips `args[0]`;
  don't.
- `--help` needs no special diversion: it's a known eager option consumed during the group's own
  parse (even with `ignore_unknown_options`), so group help renders before `resolve_command` runs.
- The hidden launcher comes from the public `make_stage_launcher(stage)` in
  `src/perk/cli/stages.py`, registered via `add_command` with `hidden = True`, and the stage joins `DEDICATED_STAGES` so the
  generic launcher generator skips it.

This is the template for any future stage-name/group collision.

## Byte-identical JSON across a group migration

Folds must keep JSON shapes, `error_type`s, and exit codes byte-identical:

- The consolidated `fail(..., extra=)` signature in `src/perk/cli/emit.py` preserves exact key
  order by merging `extra` **after** the base keys. Dry-run-capable verbs pass `extra={"dry_run": False}` on
  every failure path.
- When a plan asserts "X is the only divergence" among N near-identical private helpers, **re-grep
  all N bodies before consolidating** — the pr fold found *five of eight* `_fail` copies carried
  `"dry_run": False` (exactly the dry-run-capable verbs), not the one the plan claimed.

## Sectioned root help (`SectionedGroup`)

- `SectionedGroup(AliasGroup)` in `src/perk/cli/alias.py` is **root-only** (Launchers/Groups/Setup/
  Other/Hidden): extend-don't-replace keeps existing `isinstance(cli, AliasGroup)` assertions green;
  plain subgroups stay plain `AliasGroup`. Cheap lock: assert `isinstance(cli, SectionedGroup)` for
  root and the negative for subgroups.
- **`SectionedAliasGroup` is-an `AliasGroup`, is-NOT-a `SectionedGroup`.** The two sectioning classes
  are **siblings off `AliasGroup`**, not parent/child. A *subgroup* that wants its own sections
  (Launchers/Workers/Commands) is a `SectionedAliasGroup` (paired with `mark_kind` to tag each verb's
  bucket; unmarked verbs fall into the catch-all Commands section, so an unmarked group renders
  exactly like a bare `AliasGroup`, empty sections omitted). This is *why*
  `test_root_and_subgroups_use_alias_group` (subgroups are `AliasGroup` but **not** `SectionedGroup`)
  keeps passing for a now-sectioned subgroup — `SectionedAliasGroup` never inherits `SectionedGroup`.
  Don't confuse the two.
- The `Hidden` section is env-gated default-off — `PERK_SHOW_HIDDEN` with the same truthiness shape
  as `PERK_RUN_ID` (`not in (None, "", "0")`); the section is omitted entirely when empty or when
  the flag is off.
- Help-taxonomy upkeep when adding a group is two lines: `COMMAND_GROUPS` in
  `src/perk/cli/alias.py` + the groups-section test.
- **The launcher long-help sentence reaches only part of the launcher section:** only commands
  built by `make_stage_launcher` carry the generated "Opens a primed pi session…" long-help
  paragraph — dedicated hand-written commands do not (uniform launcher help would require
  hand-adding the sentence, or a shared helper); the section *header* is what disambiguates them.
  Don't assume the factory covers the whole section. The section's membership is the live
  authority, never a frozen list here: `STAGE_LAUNCHERS` is a **curated 3-item list**
  (`plan`/`implement`/`learn`, `src/perk/cli/alias.py`) **plus** the flat aliases
  (submit/address/land/…), which `SectionedGroup.format_commands` routes into the launcher
  bucket **before** consulting the list; guarded by `tests/test_cli_help_sections.py`'s drift
  guard.
- **Click two-paragraph help = a free short/long split:** composing help as
  `summary + blank line + long sentence` enriches `--help` bodies while leaving listing rows
  untouched — `get_short_help_str()` takes only the first paragraph. This is the cheap way to add
  disambiguating prose without churning group listings; lock it by asserting the listing row lacks
  the sentence while the command's `--help` contains it.

## The registry-keyed help-census test pattern (+ the Click help-wrap gotcha)

When a generated launcher's help states **data-derived scope** (here: `make_stage_launcher`
deriving the `--remote` help from `stage.doors.cold_remote`), pin the wording with a census test
**keyed off the registry data, not a hand-written stage list**:

- Derive the expected set from `load_registry()` (the stages with `cold_remote: true`) and assert
  **both arms** — scoped wording present on non-remotable surfaces, absent on remotable ones.
- **Enumerate every surface the generic help reaches, including hidden ones.** The merged
  launcher+worker commands (`pr submit`/`pr land`/`plan save`) are obvious; a hybrid group's
  hidden launcher is also reachable as `<group> launch --help` — a census whose `surfaces` mapping
  skips it claims coverage it doesn't exercise.
- **A statically-worded help string that names a data-derived set needs its own registry pin.**
  `plan resume`'s `--remote` help hand-names `implement/address`; the census asserts each
  registry-remotable stage id appears in that help, so the wording fails loudly when the set
  changes.

**The Click help-wrap gotcha:** Click wraps option help across lines in `--help` output, so a
substring assertion fails when the wrap point lands mid-phrase. Normalize first —
`" ".join(result.output.split())` — and assert against the flattened text.

## The flat top-level informational command (the Other bucket recipe)

Not every command wants a group or a stage launcher. A **flat top-level informational command**
(two worked examples: `run-worker`, `perk release-notes`) is a single-file
`commands/{name}_cmd.py` registered beside `run_worker_cmd` in `src/perk/cli/cli.py` — no alias, no
group, no registry stage. An unlisted root command falls into `SectionedGroup.format_commands`'
`Other` catch-all **automatically**; there is no taxonomy edit. The full recipe is four touches:

1. The flat `commands/{name}_cmd.py` module + `cli.add_command(...)` in `src/perk/cli/cli.py`.
2. `tests/test_cli_parity_smoke.py`'s `EXPECTED_SURFACE` fingerprint: a `root` row
   (alphabetically sorted, usually no aliases) **and** a `sections: "other"` entry.
3. `tests/test_cli_help_sections.py::test_workers_render_under_other`: assert the command renders
   in the `Other:` help slice.
4. `docs/user-docs/reference/cli.md`: the matching `## Other` entry.

## Testing patterns for CLI structure work

- **Help-slice tests must match the rendered row** (`"objective (obj)"`, `"worktree (wt)"`), never a
  bare-name substring — `objective-author`/`objective-plan`/`objective-save` all contain
  `"objective"` and false-positive a slice assertion.
- **Drift guard:** a regression test walks the live root surface (non-alias, non-hidden) and asserts
  the curated section lists (a) resolve to live commands, (b) are pairwise disjoint, (c) union with
  the `Other` catch-all to the full visible set — catches a new command added without classification.
- **Behavior-parity smoke (~30 seconds) for structural refactors:** dump `--help` for the root and
  every (sub)group via `CliRunner` in both the worktree and main, then diff. Rendering depends only
  on registration, so identical help ⇒ identical command/alias surface. For renaming folds the diff
  should show exactly the planned renames and nothing else. The smoke is also a **discovery tool**,
  not just an acceptance check — a re-run of it surfaced the generated-vs-dedicated launcher split
  above (resume/replan absent from the diff).
- **Keep tests driving through the `cli` object** unless they genuinely unit-test a helper — only
  three test files imported command modules directly, which made the six-group migration cheap.
- **CliRunner clobbers `sys.stdin` mid-invoke.** A command that gates on `sys.stdin.isatty()` (here
  `delete`'s interactive-confirm vs non-interactive-refuse split) **cannot** be tested by
  monkeypatching `sys.stdin.isatty` — Click's `CliRunner.invoke` REPLACES `sys.stdin` with its own
  (always non-tty) stream for the duration of the call. The working recipe: swap the command
  module's whole `sys` reference for a fake —
  `monkeypatch.setattr(delete_cmd, "sys", SimpleNamespace(stdin=SimpleNamespace(isatty=lambda: True)))`
  — so the module's `sys.stdin.isatty()` reads the fake. Pair it with monkeypatching `user_confirm`
  for the declined path; pass `--yes` / `--json` to exercise the other branches. Generalizes to any
  Click command forking on `isatty()` under `CliRunner`.
- When renaming a module used in `monkeypatch.setattr(module, ...)`, grep the **bare module name**,
  not just `module.` — a sed rewrite on `module.` misses the no-trailing-dot usage.
- Test files keep their flat names across folds — only invocations and monkeypatch import paths
  change (`perk.cli.commands.pr_X_cmd` → `perk.cli.commands.pr.X_cmd`).

## Shell-emitting CLI verbs — emitted shell source is a program, not text

A verb that emits shell source (a copyable hint, a sourceable script — anchor:
`src/perk/cli/commands/worktree/checkout_cmd.py`, the `perk worktree checkout` verb) needs
shell-level safety, not textual output checks:

- **Quote every user-controlled argument in copyable hints** — `shlex.quote` (minimal quoting
  keeps the common hint clean) so an argument like `#7` doesn't become a shell comment and
  whitespace/metacharacter names survive tokenization as one argument.
- **Guard state-changing commands so failure can't be masked by success output** — a `cd`
  without `|| return 1` in a sourced script echoes success and returns 0 even when the target
  vanished, silently un-breaking `&&` chains.
- **Confine name-based filesystem resolution before emitting navigation commands** — a bare
  `Path` join adopts absolute inputs wholesale and permits `../` traversal; validate like
  `worktree create` (no separators, no `.`/`..`) and resolve directories only (`is_dir()`, not
  `exists()`).
- **Test generated scripts by sourcing them in a real shell** — write script →
  `bash -c "source … && …"`, proving PWD actually changes (including through an
  apostrophe-containing path) and that both failure modes return non-zero and break `&&` chains.
  Substring assertions on script text catch none of this.
- Adjacent smoke-test gotcha: `cmd | head -N; echo "exit=$?"` reports `head`'s exit status, not
  `cmd`'s — use `${PIPESTATUS[0]}` or drop the pipe when the exit code is the assertion.

## Mechanical-migration gotchas

- Bash `case` patterns containing spaces must be **quoted** (`"pr submit")`, not `pr submit)` —
  syntax error). The `fakePerkRouter` in `extension/testing/harness.ts` now handles two-token route
  keys generically; new groups only update route keys in tests.
- `git mv` then edit preserves rename detection and blame across a group-dir migration.
- Pre-commit ruff hooks can fail the **first** commit attempt after mechanical string widening
  (line-length overflow; the format hook auto-fixes then reports failure) — re-stage and re-commit,
  don't pre-wrap manually.

## The decided command taxonomy (Objective #495)

Objective #495 decides a single CLI taxonomy and writes it down. The **canonical SSOT is
[`python-cli-guidelines.md` §11](../../design/first-principles/python-cli-guidelines.md)** — §11 owns the
*what* (which commands exist, naming, the launcher/worker merge, the mapping table); this playbook
stays the structural *how-to*. Summary of the decided shape:

- **Five naming rules (§11.1).** Noun-groups organize operations about a durable domain/entity
  (`plan`, `objective`, `pr`, `worktree`, `state`, `registry`, `workflow`, `learn`); `plan` and
  `objective` are symmetric planning entities; one canonical command per stage (ergonomics via flat
  aliases); a flat name is earned (`implement` is the one flat working verb); ties break on
  ergonomics.
- **The launcher+worker merge model (§11.2).** Where a stage has both a launcher and a deterministic
  worker, they merge into one command: **session by default, deterministic worker under `--json`**
  (the switch the warm door already shells). The merged (L+W) set is exactly **`pr submit`,
  `pr land`, `plan save`**. The `--json` overload ("skip the session" + "emit JSON") is an accepted,
  recorded trade-off.
- **The flat-alias set (§11.3).** Surviving earned flat names: `implement` (`impl`) + the hot-path
  PR aliases `submit` / `address` / `land` / `ready` + the short group aliases
  (`obj` / `wt` / `st` / `reg` / `wf`).
- **Warm/cold reconciliation (§11.4).** Warm slash = the ergonomic name; the warm plane needs zero
  renames. Registry stage ids stay stable (cross-plane `stage:<id>` triggers); only the cold CLI
  restructures.
- **Clean-break removal list (§11.5).** Removed with no back-compat alias: flat
  `objective-author`/`objective-plan`/`objective-save` (+ `oauthor`/`oplan`), flat
  `save`/`resume`/`replan`, and `plan-save` (`psave`).

The decided noun-group list above is the #495-era snapshot. The **live** group census is
`COMMAND_GROUPS` in `src/perk/cli/alias.py` — now including `gist`, which postdates the decision
and joined via the standard two-line taxonomy upkeep — guarded by
`tests/test_cli_help_sections.py` + `tests/test_cli_parity_smoke.py::EXPECTED_SURFACE`. Derive
the current taxonomy from `alias.py`, never from this doc.

**`pr ready` is worker-only (W), not L+W** — `ready` is not a registry stage and has no generated
launcher; `perk pr ready` is the deterministic non-launching worker. *Amended by contracts.md
§8.66:* the flat spelling `perk ready` is now a distinct **continuation wrapper** command (worker
mechanics first, then — stacked + interactive only — a seeded ready-time reconcile launch). That
launch still adds NO `ready` registry stage: it borrows the `objective-save` stage descriptor
with a `binding_trigger` override, so the original constraint stands — never mint a `ready`
stage. See §11.7 Correction 1 (as amended).

## The enacted taxonomy arc (nodes 1.1–3.3, all landed)

The taxonomy was enacted in four landed nodes: **1.1** wrote the SSOT (docs-only); **2.1** shipped
the *dormant* substrate (merge factory + flat-alias + sectioned help, zero live commands); **3.1/
3.2/3.3** folded the `objective`/`plan`/`pr` groups onto it. The merged (L+W) set is exactly
**`pr submit`, `pr land`, `plan save`**. `PlanGroup` became the **3rd inline copy** of the hybrid
default-dispatch pattern (after `LearnGroup`); a shared `HybridDispatchGroup` base stays a
deliberate deferral (each group keeps its own copy). The `shared/registry.yaml` `command:` field
stayed **informational** through every fold (`_check_shapes` only validates non-empty; launchers key
off `stage.id`) — reaffirmed by all three folds. The cross-cutting recipe + gotchas:

### The "dormant substrate" discipline (node 2.1)

A capability-before-enactment node ships the mechanism + tests but wires **zero** live commands.
Dormancy is proven by a **structural** parity-smoke fingerprint asserted against a *literal expected
dict* (`tests/test_cli_parity_smoke.py`'s `EXPECTED_SURFACE`): verb-sets + sorted-alias-tuples + each
root command's section bucket — **never raw `--help` text** (terminal-width-brittle). That literal
dict is precisely the artifact a later enactment node *edits* — the diff is the review surface. Prove
the merge factory itself via **one unregistered construction** over a real stage+worker pair
(`make_merged_command(submit_stage, submit_pr)`), no live registration needed. Reusable for any
dormant-substrate node.

**The `EXPECTED_SURFACE` fingerprint is alphabetically SORTED — ignore any positional instruction in a
plan.** `_surface_fingerprint` sorts the verbs, so a new verb row goes in TRUE alphabetical order
regardless of registration order or where a plan says to put it (e.g. `refine` lands between `list`
and `remove`, since `refi < remo` — not where "add it after create" would suggest).
`test_live_surface_matches_canonical_fingerprint` is the catch if you guess wrong.

### `MergedCommand` mechanics (conceptually)

`MergedCommand` (in `src/perk/cli/stages.py`, built by `make_merged_command`) is a `click.Command`
subclass holding **two intact halves** — the launcher (`make_stage_launcher(stage)`) and an existing
worker `Command`. It dispatches on the literal `--json` token *anywhere* in argv (the proven
`LearnGroup` pattern), stashes the chosen half, and delegates the **full argv** to it — **neither
half's options are unioned**. The `--help` guard fires `MergedCommand`'s own help **only** when
`--help`/`-h` is present AND `--json` absent (so `--json --help` correctly renders the *worker's*
help). Accepted edge (mirrors `LearnGroup`): you cannot pass `--json` *through to pi* as a launcher
pi-arg via the merged command — use the explicit stage launcher.

### Per-object marker state, never module globals

Flat-alias bookkeeping is stashed on the **root group object**; the launcher/worker kind marker on
the **command object** (mirroring the existing `ALIAS_ATTR` trick). Module-level sets would cause
cross-test leakage. Note that `SectionedGroup.format_commands` routes flat-alias names into the
launcher bucket **before** the `STAGE_LAUNCHERS` check, so an empty alias set renders
byte-identically — a fold can swap a generated launcher for a `MergedCommand`/flat alias with the
rendered rows unchanged (the diff is exactly the *added* rows, nothing moves).

### Retiring a generated flat launcher takes TWO edits

`register_stage_commands` auto-generates one flat `perk <stage>` launcher per registry stage **not**
in `DEDICATED_STAGES`. Replacing it with a grouped/merged command requires BOTH: add the stage id to
`DEDICATED_STAGES` (`src/perk/cli/stages.py`, stops generation) AND drop it from the curated
`STAGE_LAUNCHERS` list (`src/perk/cli/alias.py`, honesty — `test_section_lists_drift_guard`'s
"no stale entries" assertion). Step 2 is rarely load-bearing for *rendering* (the flat alias keeps the row
live), but the list must stay honest.

### Build merged/grouped commands defensively

At group import time, wrap the registry read in `try/except (RegistryError, FileNotFoundError,
KeyError)` and in the fallback register the **bare worker** under the verb name (mirroring
`LearnGroup`'s registry-load guard). A broken registry must never brick the group's `--help` or the
warm `perk <group> <verb> --json` worker doors — only the bare-launch half is lost.

### Launcher-only (L) ≠ merged (L+W)

A stage with a launcher + warm session-flow but **no deterministic worker** is launcher-only: build a
plain `@click.command` mirroring the launcher's option set by hand (`--worktree`/`--dry-run`/
`--remote`/`pi_args`), with the two-paragraph short/long help split (documented above). `pr address`
is this shape. The genuinely merged set is exactly **`pr submit`, `pr land`, `plan save`**. Reaffirm:
**`pr ready` is worker-only (W)** — not a registry stage, so a generated launcher would require an
illegal `ready` stage. (Since contracts.md §8.66 the flat `perk ready` is a distinct
continuation-wrapper command — not a launcher for a `ready` stage; its seeded launch borrows
`objective-save`.)

### Pure-relocation fold ≠ the launcher+worker merge model

Recognizing "this is relocation, not merge" up front keeps the change small. The `objective` group
fold (node 3.1) used **none** of the merge machinery (no `MergedCommand`, no flat alias; bare `perk
objective` stays group help — SSOT §11.7-Q4). It was just: `git mv` the `{verb}_cmd.py` files into
the group dir, switch `cls=AliasGroup` → `cls=SectionedAliasGroup`, wrap each registration as
`register_with_aliases(group, mark_kind(cmd, "launcher"|"worker"))`, drop the flat registrations +
aliases, update the informational registry `command:` fields. The **one** behavior delta was
promoting `objective-save` from a generic-generated launcher to a dedicated `save_cmd.py` (which
required adding it to `DEDICATED_STAGES`), gaining a `--json` failure surface. Generalize: don't
reach for the merge factory just because a node is in the taxonomy objective.

### Threading an optional kwarg through the launch chain is safe/mechanical

Defaulting a new kwarg (e.g. `preview: bool = False`) through `launch_stage → _resolve_prompt →
_initial_prompt → …` leaves every existing caller unaffected. Key semantic to document at the
command: a **seed-prompt-shaping flag is a local-launch concept** and is therefore **inert on
`--remote`** (the remote path builds no seed prompt).

### The "update the warm doors' argv" clause is often a verified no-op

Before implementing an "update X to match the cold rename" clause, **verify X is actually stale**.
The warm submit/land/ready doors already shell `["pr", "<verb>", "--json"]` and `/address` shells no
cold launcher — so the pr fold touched **zero** `extension/doors/*.ts`. The warm↔cold contract
(`<group> <verb> --json`) may already satisfy the clause; `MergedCommand` routes `--json` straight to
the worker.

### Cold-door argv changes ripple PAST the factory's own test

When changing any `runColdDoor`/`pi.exec` argv leading token, **grep ALL `extension/**/*.test.ts`
for the literal token**, not just the obvious factory test. The plan fold's `["plan","save"]`
respelling broke the plan-review suite (today `pi/v1/planReview.test.ts`), which asserted `argv[0] === "plan-save"` via the approval→save
(`approvalSave`) path — not just the save suite. Prefer asserting `argv.slice(0,2)` deepEqual
over the bare leading token.

### Merged-command worker tests must invoke the worker OBJECT directly

After a `MergedCommand` fold the deterministic worker is reachable through the registered `cli`
**only under `--json`**. Worker-behavior tests asserting human/JSON output must retarget from
`runner.invoke(cli, ["<verb>", …])` to invoking the worker **command object** directly with an
explicit `obj=PerkContext(...)` (the root callback's lazy default doesn't run), dropping the leading
verb token. Add separate end-to-end merged-routing coverage through `cli` (launcher default vs
`--json`→worker).

### Parallel CLI-taxonomy nodes union-conflict on a predictable file set

Nodes 3.1/3.2/3.3 edit the SAME files, so rebasing onto a merged sibling is **expected** conflict
whose resolution is almost always a **union** of each node's deletions/additions, not a choice of
sides. Hand-merge concentrates in `src/perk/cli/stages.py` (`DEDICATED_STAGES`) and the
`src/perk/cli/cli.py` root import+registration block; the big structural fixtures
(`STAGE_LAUNCHERS`, `EXPECTED_SURFACE`, `EXPECTED_ROOT_ALIASES`) usually auto-merge because nodes edit line-disjoint entries — but
**re-verify the merged `EXPECTED_SURFACE` by eye** and run `just ci` (the authoritative union check).
Incidental `package-lock.json` churn re-blocks `git rebase`; `git checkout package-lock.json` first
(the known stale-SDK/package-lock trap — see `toolchain/worktree-node-modules.md`).

### The bi-directional cli.md guard arc

The exists↔documented *tests/test_user_docs_cli_reference.py* guard (since deleted) was recurring friction across the
folds: it was worked around per-node (an accepted transient red called out in the PR body; a
`xfail(strict=False)` on exactly the two guards a surface change breaks) while `cli.md`
reconciliation was deferred, then **deleted outright** in node 3.1 in favor of the *structural*
guards (`EXPECTED_SURFACE` fingerprint + the help-sections drift guard), which catch real surface
regressions via structural diffs rather than brittle prose lockstep. Follow-through lesson: when you
delete a guard, also fix any doc prose that **advertised** it (the cli.md intro claimed "guarded by a
pytest existence check"). The structural successors live in `tests/test_cli_parity_smoke.py` (the
`EXPECTED_SURFACE` fingerprint) + `tests/test_cli_help_sections.py` (the help-sections drift guard).

### An SSOT node can disprove its parent objective — propagate to THREE surfaces

The launcher/worker (L/W/L+W) annotations in an *aspirational* objective target tree are author-time
guesses — verify each against `shared/registry.yaml` (does the stage id exist?) +
`src/perk/cli/stages.py`, never the tree (a command has a launcher half only if it's a registry
stage). The
objective's tree annotated `pr ready` as L+W; verified, `ready` is **not** a registry stage, so it is
worker-only. When a docs-SSOT node corrects its parent, the fix must reach **three** surfaces: (1)
the SSOT itself, (2) the objective's **Reconcilable prose**, and (3) the downstream **node
descriptions** — a future enactment agent reading only the roadmap table would otherwise re-introduce
the error. This is the concrete reason `/objective-reconcile` must reach node descriptions, not just
prose.

**All of nodes 1.1–3.3 have landed.** The `objective`/`plan`/`pr` groups are folded; `objective` is
pure relocation (`SectionedAliasGroup` + `mark_kind`, Launchers/Workers sections, no merge, no flat
alias); `plan`/`pr` use the hybrid `PlanGroup`/`pr` shapes with `MergedCommand` for the merged verbs.
Doc/test reconciliation (node 4.1) deleted the brittle cli.md guard for the structural guards.

## The external-TUI exec verb shape (taxonomy kind X, distinct from L)

`perk plan watch` (`src/perk/cli/commands/plan/watch_cmd.py`) established a new taxonomy kind —
the **external-TUI exec verb** (kind X, added inline as the §11.6 taxonomy correction; distinct
from L because it execs a foreign TUI, not a pi session):

- A **standalone Click verb with `ignore_unknown_options` + variadic UNPROCESSED args**, with an
  explicitly decided pass-through grammar: perk owns only its own flags before the first bare
  `--`; Click consumes that `--`; a double `--` reaches the child's own separator.
- **One argv construction shared by dry-run and exec** — the preview prints exactly what would
  run; `shlex.join` for all printed command text.
- **A chdir+exec handoff with an inherited external exit contract** — the child's exit status IS
  the command's exit status; perk adds no wrapper semantics.

Companion test lessons for cwd-sensitive CLI verbs:

- **Seam fakes must record the resolved repo argument + operation order.** A fake that discards
  the repo argument can't detect the diff-base ladder running against the invocation root instead
  of the plan worktree — record *resolved* paths (macOS `/tmp` symlinks skew raw comparisons)
  plus an ops-order log.
- **Apply `monkeypatch.chdir(tmp)` BEFORE stubbing `os.chdir`** — teardown is LIFO, so the
  reversed order restores cwd through the stub.

## The `objective doctor` worker (#626)

`perk objective doctor <id> [--fix] [--dry-run] [--json]`
(`src/perk/cli/commands/objective/doctor_cmd.py`)
is the manifest-drift detect/repair worker (the engine lives in `objective-store.md`). Its **exit
codes** follow the report-vs-abort split: a detect or fix that *completes* → **0** — **even an
ERROR-severity report-only drift is a clean report** (drift was successfully *detected*); an
**aborted** repair (a failed write) → **1**; not-a-repo → **2**. The `--json` `fix.failed.error`
maps from an **optional `error` field** on the repair-action shape (`applied` / would-apply entries
omit it). Per the parity-smoke rule above, a new worker must be added to `EXPECTED_SURFACE` in
`tests/test_cli_parity_smoke.py` **alphabetically within its group** (`("doctor", ("doc",))`).

## The `perk skills` group (#681) — pass-through-first architecture

`perk skills` wraps an upstream skills CLI as a noun-group. The durable architecture:

- **Pass-through-first.** Every verb is a thin **forward** to the substrate binary EXCEPT the verbs
  upstream lacks. The non-pass-through set is **derived from the group's `__init__.py`
  docstring/registrations** (`src/perk/cli/commands/skills/__init__.py`), never this doc —
  currently `remove` (direct manifest edit + `skills sync`), the repo-authored-skill verbs
  `scaffold`/`delete`, and the session-launching write-capable doors `create`/`refine` (the
  `write-capable-cold-doors.md` shape). The pass-through runner uses **inherited stdio** (NO
  `capture_output`) so
  the user sees native output, then propagates the upstream exit code **verbatim**; the reimplemented
  verb's own sync uses `capture_output=True` (it needs stderr on rollback).
- **Managed-source authority.** The perk manifest fragment's `sources` keys are the authoritative
  "is this perk-managed" check (upstream errors on duplicate aliases).
- **The sanctioned-subprocess guard (standing discipline).**
  `tests/test_tooling.py::test_subprocess_run_only_in_sanctioned_wrappers_with_check_and_timeout`
  enforces that EVERY `subprocess.run` site in `src/perk/` lives in an allowlisted
  `_SANCTIONED_SUBPROCESS_WRAPPERS` set keyed by `(file_stem, func_name)` (**bare stem**, not full
  path) and carries explicit `check=` / `timeout=`. A new site fails CI until added — budget for it
  whenever introducing a subprocess call (dignified-python).
- **N symmetric error/rollback arms = test ALL arms.** `remove`'s `skills sync` is guarded against
  **four** failure arms, each restoring the original bytes; `/pr-review` flagged that only the
  non-zero-exit arm was tested — **the structural-coverage reviewer counts arms.**
- The multi-surface noun-group lockstep (`register_with_aliases` + `COMMAND_GROUPS` +
  `EXPECTED_SURFACE` + the help-sections assertion + docs) is already documented above — `perk skills`
  is one more instance.
- **The envelope helpers are shared, not mirrored.** The group's original ~5-line
  `skills_fail` / `skills_emit` copies were superseded by the `src/perk/cli/emit.py` consolidation —
  skills verbs now import `fail`/`emit` like every other group. That alignment carried one
  deliberate behavior change: `skills_fail` always exited 1, so the `not_a_repo` failure now exits
  **2** per the CLI-wide `EXIT_FOR_TYPE` convention.

## Warm-plane ids are decoupled from cold spellings

A CLI regrouping does not ripple into the warm plane: `/learn-docs`, `command:learn-docs`,
deliverable command targets, and inbox artifact paths/headers all survive a cold rename untouched —
only the `pi.exec` argv arrays in the extension change.

## Residuals

- `docs/design/first-principles/python-cli-guidelines.md` has been reconciled against the grouped
  surface (Objective #225, node 5.1) — its §8.1 now documents the group-dir template and
  cross-links this doc as the detailed playbook. Its §11 is now the **decided-taxonomy SSOT**
  (Objective #495, node 1.1) — the canonical *what* for the merge model, flat aliases, mapping
  table, and removal list. Keep the two in sync when the structure evolves; §11 is authoritative on
  the target taxonomy.
- Cosmetic asymmetry: `learn capture`'s human dry-run line was respelled to the grouped form, but
  `learn docs`' human gather/dry-run label still prints the old `learn-docs {label}` spelling
  (harmless stderr human text; a future polish pass could align it).

## Cross-references

- `src/perk/cli/commands/objective/`, `src/perk/cli/commands/pr/` — realized group-dir shapes
- `src/perk/cli/commands/learn/__init__.py` — `LearnGroup`, the hybrid default-dispatch template
- `src/perk/cli/commands/plan/__init__.py` — `PlanGroup`, the hybrid group with a merged `save` verb
  (the `MergedCommand` launcher+worker folded under `--json`, Node 3.2)
- `src/perk/cli/alias.py` — `AliasGroup`, `SectionedGroup`, `COMMAND_GROUPS`, `register_with_aliases`
- `src/perk/cli/stages.py` — `make_stage_launcher`, `DEDICATED_STAGES`
- `docs/learned/workflow/init-doctor.md` — the bottom-of-file-imports idiom this doc supersedes for
  helper-induced cycles
