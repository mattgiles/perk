# How to scope pi resources per-project

Disable or filter a package's extensions, skills, prompts, or themes in *this* repo only, using
pi's own per-project resource overrides — without perk fighting you over `.pi/settings.json`. This
is the sanctioned way to trim a *borrowed* or *provider* package's resources per-repo (e.g. drop a
theme a borrowed package ships, or a skill you never use here).

**Prerequisite:** the repo is perk-managed (`perk init` has run). Know which package or resource
you want to scope; `pi config -l` (pi's interactive project-scope config UI) is the recommended
editing surface.

## Steps

1. **Open pi's project-scope config.** Run `pi config -l` in the repo. Toggling a resource off for
   a package rewrites its `.pi/settings.json` `packages` entry to **object form** —
   `{ "source": "<spec>", "extensions"/"skills"/"prompts"/"themes": [...] }` — or adds a
   `-`/`!`-prefixed disable pattern to the top-level override arrays.

2. **Scope freely — perk's convergence respects both shapes.** `perk init` and
   `perk doctor --fix` recognize a package entry by its *identity* in every form, so:
   - An object-form entry is never duplicate-appended back as a string.
   - Top-level `extensions`/`skills`/`prompts`/`themes` override arrays are yours; perk never
     writes or rewrites them.
   - If you filtered **perk's own package**, perk still keeps its version pin fresh by rewriting
     only the entry's `source` — your filter keys survive byte-for-byte. (perk never *creates* an
     object-form entry for its own package; it only reconciles the pin inside one you made.)

3. **Don't filter perk's own extension.** Filtering `@mgiles/perk`'s extension off (e.g.
   `"extensions": []` on its entry) silently breaks every interactive stage session — no stage
   tools, no footer, no gates. The same goes for disable patterns that hit perk's skills
   (`perk-implement`, `perk-plan`, …): the stage sessions that inject them lose their guidance.

4. **Run `perk doctor` to validate.** The report-only `resource-overrides` check (group
   `package`) **warns** — never fails, and `--fix` never touches it — when an override reaches
   perk's own resources: an object-form perk entry (named with its filter keys) or a `-`/`!`
   disable pattern mentioning `@mgiles/perk` or a perk skill name. The sweep is an honest
   substring heuristic — perk does not reimplement pi's filter-pattern semantics, so a pattern
   that matches perk resources without naming them escapes it. Overrides scoped to other
   packages stay quiet.

5. **To undo,** re-enable the resource via `pi config -l` (or restore the plain string `packages`
   entry by hand) and re-run `perk doctor`.

## See also

- [`perk doctor`](../reference/cli.md#perk-doctor) — the `resource-overrides` check.
- [How to select a plan or todo provider](./select-a-provider.md) — swapping whole provider
  packages (a `[providers]` selection, not a resource override).
- [How to attach your own skill to a stage or command](./attach-a-skill-to-a-stage.md) — adding
  guidance rather than trimming it.

---

← Back to the [how-to router](index.md).
