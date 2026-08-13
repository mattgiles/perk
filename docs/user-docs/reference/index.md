---
title: "Reference"
description: "Information-oriented description of perk's machinery — commands, tools, config, schemas — structured to mirror the product."
sidebar:
  order: 3000
---

# Reference

You need to look up how something works — an exact command, tool, config key, or schema,
described as it is and structured to mirror the product.

## Recommended starts

<div class="perk-recommended">

- **[CLI commands](./cli.md)** — the surface you touch first: every `perk …` command,
  written against real `--help` output.
- **[Configuration files](./configuration.md)** — every `.perk/config.toml` table and the
  `.perk/local.toml` per-user overlay.

</div>

## Pages

- **[CLI commands](./cli.md)** — every `perk …` command, written against real `--help` and
  guarded by a pytest existence check.
- **[In-session commands & tools](./in-session.md)** — the warm `/…` commands, the
  model-facing tools, and the stage/door table for the session interior.
- **[Configuration files](./configuration.md)** — every `.perk/config.toml` table and the
  `.perk/local.toml` per-user overlay, with overlay semantics and the canonical repository layout
  (dot-directory) contract.
- **[Objectives — the roadmap model](./objectives.md)** — the objective command recap, the
  roadmap node schema, node statuses, and the objective metadata blocks.
- **[Providers & issue backends](./providers-and-backends.md)** — the supported provider set (the
  plan, footer, and web seams) and the Linear issue-backend reference (auth, labels, identifiers,
  maturity).
- **[JSON Schema snapshots](./json-schemas.md)** — the committed golden snapshots of perk's
  boundary models (the shared-YAML contracts, the machine batch inputs, and the `--json` output
  envelopes), drift-guarded so shape changes are reviewable.
