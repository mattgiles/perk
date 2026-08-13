---
title: "How to select a provider"
description: "Swap perk's bundled plan-authoring, footer, or web surface for a supported foreign provider, or back to the default."
sidebar:
  order: 2300
sidebarGroup: "Providers & backends"
---

# How to select a provider

Switch the footer from the foreign `pi-status-footer` package to Pi's package-free stock footer, and
prove that convergence removes only the package the selection owned.

## Steps

1. **Converge the starting selection.** Set the committed footer selector in `.perk/config.toml`:

   ```toml
   [providers]
   footer = "pi-status-footer"
   ```

   Run `perk init`, then `perk doctor`. Doctor should report `footer=pi-status-footer`.
2. **Record the package identities.** Read, but do not hand-edit, `.pi/settings.json`. The selected
   footer should contribute `npm:@tombell/pi-status`. Record every other package identity so you can
   prove that unrelated packages survive the switch. For a quick source-spec list:

   ```bash
   jq -r '.packages[] | if type == "string" then . else .source end' \
     .pi/settings.json | sort
   ```

3. **Change only the committed footer selector.** Replace that one value in `.perk/config.toml`:

   ```toml
   [providers]
   footer = "pi-default"
   ```

   Do not remove or rewrite package entries in `.pi/settings.json` yourself.
4. **Converge the new selection.** Run `perk init` again. Provider convergence uses the supported
   catalog to remove the previous footer package while preserving entries it does not own.
5. **Compare the result.** Read the normalized package identities again. Require all of these
   conditions:
   - `npm:@tombell/pi-status` is absent;
   - the before and after sets of every unrelated identity are exactly equal;
   - no replacement footer package or footer resource filter was added.
6. **Verify resolution.** Run `perk doctor` and require the providers check to report
   `footer=pi-default`.

## Expected result

`pi-default` installs no footer package. perk vacates its footer installation point, no replacement
package or filter is present, and Pi keeps its stock built-in footer. Unrelated package identities
are unchanged.

The `plan` and `web` seams use the same committed edit → `perk init` → `perk doctor` flow. Use their
reference entries to choose an id and understand any package, posture, credential, or fallback
differences.

## Related

- **Do:** [Scope Pi resources per project](./scope-pi-resources-per-project.md) — filter resources
  after selection.
- **Look up:** [`[providers]` configuration](../reference/configuration.md#providers) — selector
  syntax and precedence.
- **Look up:** [Providers and backends](../reference/providers-and-backends.md) — supported set,
  postures, fallback, and packages.
