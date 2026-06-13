# Reference

**Purpose:** information-oriented description of perk's machinery — commands, tools, config,
schemas — structured to mirror the product, so a reader who knows the product's shape can
find the matching page.

## Authoring rules

- Describe; don't instruct and don't explain — tasks belong in
  [how-to/](../how-to/index.md), rationale in [explanation/](../explanation/index.md).
- Austere and consistent: same structure, same tone, page after page.
- **Accuracy is the governing virtue.** The CLI reference is written against real `--help`
  output and (from Objective #453 Node 2.1 onward) guarded by a pytest check, so a
  documented-but-missing command fails CI.

See the [user-docs router](../index.md) for how this quadrant fits the overall system.

## Pages

- **[CLI commands](./cli.md)** — every `perk …` command, written against real `--help` and
  guarded by a pytest existence check.
- **[In-session commands & tools](./in-session.md)** — the warm `/…` commands, the
  model-facing tools, and the stage/door table for the session interior.
- **[Objectives — the roadmap model](./objectives.md)** — the objective command recap, the
  roadmap node schema, node statuses, and the objective metadata blocks.
- **[Configuration files](./configuration.md)** — every `.pi/perk.toml` table and the
  `.pi/perk.local.toml` per-user overlay, with overlay semantics.

> **Status:** pages are added by later Objective
> [#453](https://github.com/mattgiles/perk/issues/453) nodes; this page lists only pages
> that actually exist (currently: the CLI commands reference, the in-session reference, the
> objectives roadmap-model reference, and the configuration reference).
