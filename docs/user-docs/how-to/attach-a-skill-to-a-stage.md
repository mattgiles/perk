# How to attach your own skill to a stage or command

Bind your own installed skill to a stage or command so its guidance is delivered automatically into
that session — either as a new trigger or as an override of one of perk's defaults.

**Prerequisite:** the skill is installed under `.agents/skills/<name>/SKILL.md`. (perk's own
`perk-*` skills are already installed there.) A repo-authored `.perk/skills/<name>` skill qualifies
too once it is committed + synced — it then lands under `.agents/skills/<name>/` and binds here
exactly like any installed skill (see [How to author a repo-specific skill](./author-a-repo-skill.md)).
The `[[bindings]]` row shape is documented in the
[configuration reference](../reference/configuration.md#bindings).

## Steps

1. **Pick a trigger.** A trigger is one `"<kind>:<id>"` string.
   - `stage:<id>` binds a registry stage — it fires at **both** the cold launcher and the warm
     slash-command of that name. Bindable stage ids: `objective-author`, `objective-save`,
     `objective-plan`, `plan`, `save`, `implement`, `submit`, `address`, `land`, `learn`.
   - `command:<id>` binds a command that is **not** a registry stage. Seven command targets have a
     delivery surface: `objective-reconcile`, `objective-replan`, `learn-docs`, `learn-code`,
     `pr-review`, `skills-create`, and `skills-refine`.

   **Caveat:** a `command:<id>` outside those seven validates but **never fires** — it has no
   delivery surface. When a command is also a registry stage, bind `stage:<id>`, not
   `command:<id>`.

2. **Choose `nudge` or `transclude`.** This is the `mode` field.
   - `nudge` delivers a short pointer (``Follow the `<skill>` skill (read
     `.agents/skills/<skill>/SKILL.md`).``). The pointer carries the skill's read path, so it works
     even for a skill hidden from the ambient system prompt via `disable-model-invocation: true`
     frontmatter. Pick it for an installed skill — lightweight, and never stranded by hiding.
   - `transclude` inlines the full `SKILL.md` body into the prompt (heavier context, but guaranteed
     present). Pick it to force the body in.

3. **Add a `[[bindings]]` row** to `.perk/config.toml` for a new trigger. A row at a trigger perk does
   not already bind is **appended**. Example — attach your skill to the `submit` stage (which has no
   default binding):

   ```toml
   [[bindings]]
   trigger = "stage:submit"
   skill = "house-style"
   mode = "nudge"
   ```

4. **Override a default binding.** A row at a trigger perk already binds **replaces perk's default
   in place**. Example — rebind the `plan` stage (perk's default `perk-plan` nudge) to your own
   skill, or switch its delivery to `transclude`:

   ```toml
   [[bindings]]
   trigger = "stage:plan"
   skill = "house-style"
   mode = "transclude"
   ```

5. **Validate.** Run [`perk doctor`](../reference/cli.md#perk-doctor) — it checks that every
   binding's skill is installed and its trigger target exists. An uninstalled-skill nudge or a
   missing-transclude-target degrades **loud-but-non-fatal** at delivery (the session still runs).

## Per-user variant (optional)

Put the rows in `.perk/local.toml` instead to keep them off the committed config. Note: a local
`[[bindings]]` array **replaces the committed array wholesale** — it is not merged element-wise, so
include every binding you want active, not just your additions. See the
[overlay semantics](../reference/configuration.md#local-overrides--overlay-semantics) in the
configuration reference.

## perk's workflow skills are hidden from the ambient prompt

perk's stage-orchestrator `perk-*` skills (`perk-plan`, `perk-implement`, …) ship
`disable-model-invocation: true`, so they never appear in a session's ambient skill listing — each
is delivered only into its own door via these bindings (or a seed-prompt pointer). The files stay
installed under `.agents/skills/` and `/skill:<name>` still works; only the system-prompt
visibility is scoped.

## perk ships an auto-discovered `perk-expert` skill

Alongside the workflow `perk-*` skills (which orchestrate individual stages), perk delivers a
`perk-expert` skill that Pi **auto-discovers by description** — no `[[bindings]]` row needed. It is
the on-demand expert on configuring and customizing perk (the `.perk/config.toml` tables, provider
seams, the issue backend, CI checks, subagent overrides), carrying self-contained references that
travel into your repo. Pi invokes it when a task matches "how does perk … / how do I configure … /
which knob controls …".

## See also

- [How to author a repo-specific skill](./author-a-repo-skill.md) — scaffold and author the
  `.perk/skills/<name>` skill you then bind here.
- [Configuration reference — `[[bindings]]`](../reference/configuration.md#bindings) — the row shape
  and overlay semantics.
- [`perk doctor`](../reference/cli.md#perk-doctor) — validates every binding's skill and target.

---

← Back to the [how-to router](index.md).
