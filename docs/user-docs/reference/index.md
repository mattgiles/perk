---
title: "Reference"
description: "Information-oriented description of perk's machinery — commands, tools, config, schemas — structured to mirror the product."
sidebar:
  order: 3000
---

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
- **[Configuration files](./configuration.md)** — every `.perk/config.toml` table and the
  `.perk/local.toml` per-user overlay, with overlay semantics and the canonical repository layout
  (dot-directory) contract.
- **[Providers & issue backends](./providers-and-backends.md)** — the supported provider set (the
  plan, footer, and web seams) and the Linear issue-backend reference (auth, labels, identifiers, maturity).
- **[JSON Schema snapshots](./json-schemas.md)** — the committed golden snapshots of perk's
  boundary models (the shared-YAML contracts, the machine batch inputs, and the `--json` output
  envelopes), drift-guarded so shape changes are reviewable.
