---
title: "How to scope Pi resources per project"
description: "Disable or filter a package's extensions, skills, prompts, or themes in one repo using Pi's per-project overrides."
sidebar:
  order: 2290
sidebarGroup: "Customization"
---

# How to scope Pi resources per project

Use Pi's project settings to enable a package for this repository while narrowing the extensions,
skills, prompts, or themes it loads.

## Steps

1. **Open the project resource editor.** Run `pi config -l` from the repository. This starts in
   project scope and writes `.pi/settings.json`; inherited global resources are shown separately.
2. **Distinguish package state from resource filters.** The package-level control enables or
   disables the package in this project. The extension, skill, prompt, and theme controls beneath a
   package filter what an enabled package contributes. Those filters produce an object-form
   `packages` entry such as:

   ```json
   {
     "source": "npm:example-package",
     "extensions": ["extensions/*.ts", "!extensions/legacy.ts"],
     "skills": [],
     "prompts": ["+prompts/review.md"]
   }
   ```

   Omit a resource key to load all resources of that type, use `[]` to load none, and use glob
   patterns with `!pattern` exclusions. `+path` force-includes one exact package-relative path and
   `-path` force-excludes one. Filters can only narrow resources the package already exposes.
3. **Keep top-level resources separate.** Top-level `extensions`, `skills`, `prompts`, and `themes`
   arrays name project-local resources and their include/exclude patterns; they do not select a perk
   provider. Similarly, filtering an installed package does not change the committed `[providers]`
   choice.
4. **Reconverge and inspect.** Run `perk init`, then `perk doctor`. perk recognizes package identity
   in string or object form, preserves unrelated package entries and user-owned filters, and does not
   rewrite the top-level resource arrays. Doctor reports malformed settings and warns when an
   object-form override or disable pattern touches perk's own managed package/resources; it does not
   treat ordinary filters on unrelated packages as provider selection.
5. **Verify the loaded set.** Restart Pi in the project and confirm that the intended resource is
   absent while the package's allowed resources still load. Return to `pi config -l` to undo or
   adjust the filter.

## Expected result

The project loads only the selected resources, the override remains in `.pi/settings.json`, and
subsequent perk convergence preserves it.

## Related

- **Do:** [Select a provider](./select-a-provider.md) — swap a provider package rather than filter
  one package's resources.
- **Do:** [Attach a skill to a stage](./attach-a-skill-to-a-stage.md) — add guidance rather than trim
  it.
- **Look up:** [`perk doctor`](../reference/cli/setup-and-health.md#perk-doctor) — resource and provider-package
  diagnostics.
