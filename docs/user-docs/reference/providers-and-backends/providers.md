---
title: "Providers"
description: "Provider postures, package convergence, selection effects, and fallback behavior for perk's plan, footer, and web seams."
sidebar:
  order: 3051
---

# Providers

A provider supplies one selectable implementation for the `plan`, `footer`, or `web` seam. The
[Providers & issue backends hub](../providers-and-backends.md) lists the complete supported set;
this page describes what each posture and selection does. Provider selection does not change the
GitHub or Linear issue backend.

## Postures

The three seams divide into one artifact seam and two interface seams. The plan seam must preserve
a durable plan contract, so foreign plan providers have adapter behavior. A footer or web provider
owns only an interface, so perk yields that interface without bridging an artifact.

### Plan: reference, replace, or augment

- **`perk-plan` — reference.** perk registers its complete plan-authoring surface and writes the
  resulting plan through `plan_save` into the plan reference consumed by later stages.
- **`tombell-plan` — REPLACE.** perk vacates its plan surface at registration time: it does not
  register `/plan`, `--plan`, or `Ctrl+Alt+P`, avoiding duplicate names with
  `@tombell/pi-plan`. The `planAdapterTombell` prompt bridge remains available and directs the
  foreign prose result through perk's review/save flow. It lands the same plan contract; it does
  not drive the foreign tool or replace perk's read-only gate.
- **`plannotator-plan` — AUGMENT.** perk keeps `/plan`, its authoring context, and the read-only
  gate. It vacates only `--plan`, `Ctrl+Alt+P`, and the matching startup handler because
  plannotator registers those surfaces. `planAdapterPlannotator` sends the draft to the browser
  through `plan_review`. An approval without direct edits saves through the normal approval seam.
  For a plan approval with `# Direct Edits`, perk applies the diff and saves the edited bytes; if
  the diff cannot apply, it saves the original bytes and reports the fallback. For objective and
  gist approvals with direct edits, perk does not save: it returns one revise round so the agent
  folds the edits into the appropriate draft fields and re-reviews. A denial returns the feedback
  to the agent.

The adapters are selected behavior, not new storage formats. A plan reference's `provider` field
names the **issue backend**, not the plan-provider id.

### Footer: vacate-only

The footer is an interface seam with no durable artifact and no adapter:

- **`perk-footer`** installs perk's footer during a headful session start.
- **`powerline-footer`, `pi-bar-footer`, and `pi-status-footer`** make perk skip that install, so
  the selected extension owns the single footer slot. `powerline-footer` and `pi-bar-footer`
  render extension statuses, so perk's objective status remains visible. `pi-status-footer` does
  not render extension statuses; hidden objective progress is its accepted limitation.
- **`pi-default`** also makes perk skip its footer, but installs no replacement package. Pi's stock
  footer remains.

### Web: package selection with nothing to vacate

perk registers no web tools of its own. Selecting a web provider only chooses the installed
package, and every web entry is vacate-only with no adapter. The default, `pi-web-access`, is itself
a foreign package because perk has no native web implementation.

The providers do not share a normalized tool vocabulary:

- `pi-web-access`: `web_search`, `fetch_content`, and `get_search_content` (`code_search` remains
  allowlisted for version tolerance);
- `ollama-web-search`: `ollama_web_search` and `ollama_web_fetch`;
- `juicesharp-web-tools`: `web_search` and `web_fetch`.

The read-only gate recognizes the union of those names. `pi-web-access` is zero-config;
`ollama-web-search` requires a local Ollama daemon, and `juicesharp-web-tools` requires an API key.
The bundled `librarian` skill depends on `pi-web-access`, so selecting either alternative removes
that skill from the delivered package surface.

### Built in, not selectable

`ask_user_question` and `todo` are required borrowed packages, not provider seams. perk installs
`@juicesharp/rpiv-ask-user-question` and `@juicesharp/rpiv-todo` for every managed repository. The
retired `[providers] askuser` and `[providers] todo` keys fail config validation. The retired review
seam is also not selectable: `/pr-review-terminal` chooses hunk and `/pr-review-browser` chooses
plannotator directly.

## What selection does

### Package convergence

`perk init` reconciles provider-managed entries in `.pi/settings.json` in both directions:

- the package for each resolved selection is added in Pi's object form;
- a package from the supported provider set is removed when no selected seam wants it;
- a null-package provider such as `perk-plan`, `perk-footer`, or `pi-default` adds nothing;
- the default `pi-web-access` package is still added because that catalog entry has a package;
- borrowed packages and unrelated operator-managed packages are not provider-managed and remain
  untouched.

The desired package set is computed across all seams before reconciliation, so one desired package
is not removed merely because another seam does not select it. If `.perk/config.toml` is malformed,
ill-typed, or contains a retired provider key, convergence cannot establish intent and performs no
provider add or removal. The config check reports the error; a later `perk init` reconciles once the
config is valid. This deliberately favors a non-destructive no-op over stripping a package named by
broken config.

The hunk CLI is independent of provider selection. A verified `perk init` tries a best-effort
`npm install -g hunkdiff` when `hunk` is absent. Failure is a warning with the manual install hint,
not a provider-resolution failure.

### Runtime and doctor effects

Plan and footer selection also controls the vacating behavior described above. Web selection needs
no runtime vacating because perk owns no web tool registration.

`perk doctor` reports the resolved `plan`, `footer`, and `web` ids in its `providers` check. Catalog
load or catalog validation failure is an installation failure; an unknown or wrong-seam repository
selection is a warning with its fallback. Package drift is repaired through the existing
`settings-wiring` convergence rather than a separate provider check. The verify-gated
`review-cli` check reports whether the independently managed `hunk` binary is available, and
`perk doctor --fix` retries its best-effort installation.

## Fallback semantics

Both planes resolve one provider for each seam:

- an absent selection uses that seam's catalog default without a warning;
- an unknown id or an id from the wrong seam produces one finding and uses the seam default;
- ordinary selection mistakes therefore do not crash a session or switch another seam.

There is one deliberate cross-plane difference for a **missing catalog default**, which indicates
an installation or version-skew problem rather than an ordinary selection mistake. The short-lived
Python CLI treats it as a corrupt-install error. A long-lived TypeScript session can observe newer
or older `shared/providers.yaml` bytes than its loaded code, so it synthesizes a known reference
fallback for only the affected seam and reports the problem. Other seams continue resolving.
Call-site catches that handle an unreadable config also report the error and fall back to perk's
reference behavior.

## Related

- **Look up:** [Providers & issue backends](../providers-and-backends.md).
- **Do:** [Select a provider](../../how-to/select-a-provider.md).
- **Look up:** [Backends configuration](../configuration/backends.md).
