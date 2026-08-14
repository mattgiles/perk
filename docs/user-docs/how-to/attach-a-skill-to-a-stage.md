---
title: "How to attach your own skill to a stage or command"
description: "Bind your own installed skill to a stage or command so its guidance is delivered automatically into that session."
sidebar:
  order: 2260
sidebarGroup: "Customization"
---

# How to attach your own skill to a stage or command

Add one `[[bindings]]` row so an installed skill is delivered whenever a particular perk door runs.

## Prerequisite

The skill must be available at `.agents/skills/<name>/SKILL.md`. If it is authored in this
repository, commit, push, and sync it before binding it.

## Steps

1. **Choose the trigger kind.** Use `stage:<id>` when the target is a registry stage; that one
   binding covers the stage's cold launcher and warm command. Use `command:<id>` only for a
   deliverable command that is not itself a registry stage. Look up the accepted ids instead of
   guessing: a syntactically valid command trigger with no delivery surface cannot fire.
2. **Choose the delivery mode.** Use `nudge` to add a short instruction that points the model to the
   installed `SKILL.md`; this is the lightweight default. Use `transclude` when the full skill body
   must be inserted into the prompt.
3. **Add the binding.** Put the row in the committed `.perk/config.toml`. For example, deliver the
   installed `house-style` skill whenever the `submit` stage runs:

   ```toml
   [[bindings]]
   trigger = "stage:submit"
   skill = "house-style"
   mode = "nudge"
   ```

   A user row replaces a shipped binding with the same trigger; a new trigger is appended to the
   effective set.
4. **Validate the row.** Run [`perk doctor`](../reference/cli.md#perk-doctor). Fix an unknown target,
   duplicate trigger, unsupported mode, or missing installed skill before relying on the binding.
5. **Verify delivery.** Run the chosen stage or command. A `nudge` should tell the session to read
   `.agents/skills/house-style/SKILL.md`; a `transclude` binding should place that skill's body in the
   delivered prompt.

## Expected result

The skill is exposed to the bound session and its guidance arrives in the selected mode whenever the
trigger runs.

## Related

- **Do:** [Author a repo skill](./author-a-repo-skill.md) — create the repo-local skill to bind.
- **Do:** [Scope Pi resources per project](./scope-pi-resources-per-project.md) — trim package
  resources instead of adding guidance.
- **Look up:** [`[[bindings]]` configuration](../reference/configuration/skills-and-bindings.md#bindings) — exact fields,
  precedence, and validation.
