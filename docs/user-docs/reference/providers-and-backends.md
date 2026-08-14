---
title: "Providers & issue backends"
description: "The supported plan, footer, and web providers, the GitHub and Linear backend comparison, and current caveats."
sidebar:
  order: 3050
---

# Providers & issue backends

Use this page to distinguish two independent choices: a **provider** supplies one Pi-facing
surface, while the **issue backend** owns canonical plan, learning, gist, and objective state.
Provider selection does not change the tracker, and backend selection does not choose your plan,
footer, or web tools.

## Orientation

perk exposes three provider seams and two issue backends:

- **Provider seams:** `plan`, `footer`, and `web`. Each seam has one selected provider from the
  supported set below. Read [Providers](./providers-and-backends/providers.md) for postures,
  package convergence, selection effects, and fallback behavior.
- **Issue backends:** GitHub (default) and Linear. One committed `[issues]` selection controls the
  issue-tracking and objective-storage protocols while keeping both in the same tracker family.
  Read [Issue backends](./providers-and-backends/issue-backends.md) for auth, storage,
  identifiers, readiness, and native metadata.

Configure both families in the [Backends configuration reference](./configuration/backends.md).
The per-repository selection is a pointer into a supported set; it does not add an arbitrary
provider or backend implementation.

## Provider seam: the supported set

The provider catalog is `shared/providers.yaml`, read by both perk planes in declaration order.
`yes` marks the no-selection default for a seam. The posture column summarizes how the selected
surface relates to perk; the guarded columns are id, seam, default, and package.

<!-- perk:reference-facts:providers:start -->
| Provider id | Seam | Default | Posture | Package |
| --- | --- | --- | --- | --- |
| `perk-plan` | `plan` | yes | reference (native) | — |
| `tombell-plan` | `plan` | — | REPLACE | `npm:@tombell/pi-plan` |
| `plannotator-plan` | `plan` | — | AUGMENT | `npm:@plannotator/pi-extension` |
| `perk-footer` | `footer` | yes | reference (native) | — |
| `powerline-footer` | `footer` | — | REPLACE (vacate-only) | `npm:pi-powerline-footer` |
| `pi-bar-footer` | `footer` | — | REPLACE (vacate-only) | `npm:pi-bar` |
| `pi-status-footer` | `footer` | — | REPLACE (vacate-only) | `npm:@tombell/pi-status` |
| `pi-default` | `footer` | — | install nothing | — |
| `pi-web-access` | `web` | yes | reference (foreign package) | `npm:pi-web-access` |
| `ollama-web-search` | `web` | — | REPLACE (vacate-only) | `npm:@ollama/pi-web-search` |
| `juicesharp-web-tools` | `web` | — | REPLACE (vacate-only) | `npm:@juicesharp/rpiv-web-tools` |
<!-- perk:reference-facts:providers:end -->

GitHub is the default issue backend; Linear is the other supported choice. Both keep pull
requests, review, CI, and merge on GitHub. Their storage and operational differences are
summarized in [Issue backends](./providers-and-backends/issue-backends.md).

## Known caveats & maturity

- `pi-status-footer` does not render extension statuses, so perk's objective progress is not
  visible there. `powerline-footer` and `pi-bar-footer` do render those statuses.
- `pi-web-access` is the only zero-config web choice. `ollama-web-search` requires a local Ollama
  daemon; `juicesharp-web-tools` requires an API key. Selecting either non-default web provider
  also removes the `pi-web-access`-specific `librarian` skill.
- Linear behavior has broad offline regression coverage and dated live validation for the core
  issue lifecycle, project-backed objectives, and attachment metadata. Workspace-specific auth,
  team, label, Project-scope, and workflow-state readiness still requires the verify-gated live
  checks; an offline green run cannot prove those workspace conditions.
- Linear rate limits arrive as `RATELIMITED` GraphQL errors. perk fails loudly and does not retry
  or back off; low-volume live validation has not exercised a rate limit.
- Optional Linear AgentSession emission is off by default, requires a separate
  `LINEAR_AGENT_TOKEN`, and remains offline-verified but unverified against a live workspace.
- Linear's GitHub Issues Sync is outside perk's coverage. Use a team without that two-way sync
  unless you have separately validated the interaction.
- Current Linear metadata uses native issue attachments. This was a clean break: artifacts from
  the earlier inline-metadata era are not read back and must be re-created or re-saved.

## Related

- **Do:** [Select a provider](../how-to/select-a-provider.md).
- **Do:** [Switch the issue backend to Linear](../how-to/switch-to-linear.md).
- **Look up:** [Backends configuration](./configuration/backends.md).
