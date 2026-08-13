# Prose Review Workbench PRD

**Status:** product and architecture contract for a future local-only maintainer app. The living
map in [`prose-prompt-map.yaml`](./prose-prompt-map.yaml) is its information architecture and source
allowlist. This document does not select a web framework or implement the app.

## 1. Problem

Perk behavior is partly implemented in model-facing prose spread across templates, skills,
subagent definitions, tool contracts, injected contexts, and code-owned dynamic messages. Those
fragments form workflow families: cold and warm doors are siblings, launch statements layer with
bound skills and tool contracts, and shared concerns recur across multiple capabilities. A file
browser hides those relationships, which makes review slower and makes local wording changes easy
to assess in isolation when they actually affect several session shapes.

The workbench gives a perk maintainer one local surface to answer three questions:

1. What perk-owned prose shapes this model turn, and in what order?
2. Which siblings, parents, children, aliases, or concerns should be reviewed with this fragment?
3. What canonical source file will change, and what validation is appropriate before saving it?

## 2. Product goals

- Navigate from a human capability to its workflow, delivery variant, ordered assembly, and
  logical prose fragments without starting from repository paths.
- Review related fragments side by side, especially warm/cold siblings, door/skill pairs,
  parent/child prompts, shared concern carriers, and adjacent assembly layers.
- Edit existing mapped prose in its native Markdown, YAML, Python, or TypeScript source form.
- Preview every perk-owned assembly layer in delivery order while labeling content owned by Pi,
  users, runtime state, or borrowed packages as boundaries.
- Make local edits safely: explicit per-file saves, visible diffs, optimistic conflict detection,
  cheap pre-save validation, and user-invoked targeted checks.
- Operate without remote services, telemetry, authentication, or network-loaded assets.

### Non-goals

- A generic prompt editor for downstream repositories.
- Editing borrowed prompt contents or generated/materialized copies.
- Creating, renaming, moving, or deleting source units.
- Editing the graph, capability taxonomy, relationships, selectors, or scenario definitions.
- Automatic prompt rewriting, model-assisted copy editing, or sending content to a model.
- Reconstructing Pi's exact private system prompt or replaying captured user sessions.
- Git staging, commits, resets, checkouts, branches, pushes, or pull requests.
- Broad prompt externalization or changing where existing prose lives.

## 3. Audience and success criteria

The sole v1 audience is a maintainer working on perk itself. Shipped and self-development prose are
visible as filters and badges inside the same capability hierarchy.

The product succeeds when the maintainer can:

- enter through a capability rather than a file path and reach any mapped logical fragment;
- compare a warm door with its cold sibling and bound skill without manually locating files;
- see every assembly consumer before changing a shared unit;
- edit one canonical unit through any alias and observe the same unsaved buffer everywhere;
- preview the affected scenario and save only after reviewing the exact file diff;
- detect an external file change without overwriting it; and
- verify that the resulting repository still satisfies the living-map and targeted language checks.

## 4. Information architecture

The left navigation is derived from the graph, never reconstructed from the filesystem:

```text
Capability family
└── Capability / human workflow
    ├── Session shape (cold | warm | headless | ambient | subagent)
    │   └── Ordered assembly layers
    │       └── Canonical prose unit → logical fragments
    └── Related concerns and sibling shapes
```

The top-level order is fixed: Foundation, Intent, Planning, Delivery, Review, Knowledge, Extension
& utilities. A source unit may appear under every consuming assembly, but each appearance is an
alias to one canonical unit and edit buffer. Tool/schema fragments are children of their registered
tool unit; Markdown headings and frontmatter discovery descriptions are children of their file.

Search operates over capability labels, shape labels, unit ids, source paths, fragment labels, tool
names, and concern labels. Filters are limited to audience, role, and source kind. Search results
retain their capability breadcrumb so a direct hit never collapses back into a file-only view.

## 5. Workbench layout

The v1 surface is a dense desktop workbench. It remains usable at 200% zoom; small screens may stack
the inspector below the center pane, but mobile authoring is not a goal.

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│ Prose Review     Search…                Audience ▾  Role ▾  Kind ▾        Workspace (3)      │
├──────────────────────┬──────────────────────────────────────────┬───────────────────────────┤
│ CAPABILITY TREE      │ Planning / Plan / Warm / plan_review     │ RELATIONSHIPS & SOURCE    │
│                      │                                          │                           │
│ ▾ Planning           │ [ Edit ] [ Compare ] [ Assembly ]        │ Canonical source          │
│   ▾ Plan authoring   │ ┌──────────────────────────────────────┐ │ extension/factories/…   │
│     ○ Cold           │ │ source-native focused editor         │ │ tool:plan_review.…      │
│     ● Warm           │ │ with surrounding read-only context   │ │                           │
│       1 Pi boundary  │ └──────────────────────────────────────┘ │ Consumed by               │
│       2 author flow  │                                          │ • plan.cold               │
│       3 plan skill   │ File diff / validation results           │ • plan.warm               │
│       4 plan_review  │                                          │                           │
│       5 user boundary│ [Discard file]            [Save file]    │ Related                    │
│                      │                                          │ • cold sibling            │
│ ▸ Review             │                                          │ • bound plan skill        │
│ ▸ Knowledge          │                                          │ • review-first concern    │
├──────────────────────┴──────────────────────────────────────────┴───────────────────────────┤
│ Workspace drawer: unsaved files · conflicts · last targeted checks                         │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Left pane:** capability tree, shape siblings, assembly order, and aliases. Boundaries are
  visible but never selectable for editing.
- **Center pane:** three persistent modes—Edit, Compare, Assembly. Navigation does not discard
  buffers or change the active center mode.
- **Right pane:** canonical locator, audience/role/kind, consumers, siblings, parent/child links,
  concerns, lineage, and generated targets.
- **Workspace drawer:** all dirty files, validation state, conflicts, and targeted-check history.
  It is global because one source file may contain several mapped units.

Keyboard navigation covers tree movement, pane focus, mode switching, relationship selection,
diff traversal, save, and workspace opening. Native focus indicators remain visible; state is never
communicated by color alone.

## 6. Core user flows

### Browse and understand an assembly

1. Choose a capability, then a session shape.
2. The tree expands its assembly in delivery order.
3. Selecting a unit opens its canonical source and relationship inspector.
4. Selecting a boundary explains its owner and why exact content is unavailable; it never offers
   an editor.

### Compare a prose family

1. Open Compare from a selected unit or shape.
2. The relationship inspector offers only graph-backed comparison targets: sibling shape, adjacent
   layer, bound skill, parent/child, alias consumer, or concern relative.
3. Two source-native panes scroll independently. Each pane shows its capability/shape breadcrumb;
   identical canonical units share one buffer rather than displaying divergent copies.
4. Differences are computed from current buffers, so unsaved edits participate immediately.

### Edit and save

1. Open a mapped fragment through any alias.
2. Load its full file bytes, mode, newline style, and SHA-256 content hash. The focused range is
   editable; surrounding source context is read-only unless another mapped fragment in the same
   file is selected.
3. Keep edits in memory across navigation and coalesce all edits to the same file in one buffer.
4. Before save, show the exact full-file diff and run cheap syntax, template, selector, and graph
   checks. A failure blocks save and anchors the error to the affected source when possible.
5. Immediately before replacement, compare the on-disk hash with the load hash. A mismatch opens a
   conflict state with Reload and Copy Edits actions; it never writes.
6. On success, write a temporary file in the same directory, preserve mode/newline behavior, and
   atomically replace the original. Refresh the source hash and graph-derived views.

Discard is explicit per file. Closing or reloading with dirty buffers requires confirmation. The
app never silently persists editor state into source files.

### Preview an assembly

1. Open Assembly from a session shape and select one of its graph-authored scenarios.
2. Render each perk-owned layer through its production composer or source adapter and display the
   layers separately in delivery order, with an optional concatenated view.
3. Show Pi system text, user content, runtime state, and borrowed prompts as labeled placeholders.
4. Ambient skills and model-visible tool contracts have independent visibility toggles. Toggling
   changes presentation only; it does not alter the graph or source.
5. Unsaved edits render from the shared workspace buffer. Conditional templates show the chosen
   scenario arm and expose the scenario variables in a read-only inspector.

Preview is a review aid, not a claim to reproduce the host's complete model request.

### Run targeted checks

Pre-save checks are cheap and synchronous. After save, the maintainer may run checks suggested by
the affected source adapters: `perk-dev prose-map check`, the relevant prompt-render parity test,
targeted pytest/node tests, Ruff, ty, Biome, or TypeScript typecheck. The app streams captured output
and records the result in the workspace drawer. It never launches the full `run_ci` gate or applies
formatting automatically.

## 7. Source adapters

Every editable unit resolves through one adapter selected by its graph locator:

- **Markdown:** file body, frontmatter description, or heading-delimited section. Heading identity
  is structural and read-only in v1; changing it is a graph/schema change outside the app.
- **YAML:** a mapped scalar or collection path with parsing and exact-path re-resolution.
- **Python:** a named symbol or enclosing-symbol call argument selected with Python's AST.
- **TypeScript:** a named symbol, registered tool field path, or enclosing-symbol call/property
  selected with the TypeScript compiler API.

An adapter exposes read, focused-range replacement, cheap validation, and affected-check hints. It
must preserve unrelated bytes and reject any edit that makes its selector ambiguous or missing.
Unsupported expression shapes remain readable and comparable but are explicitly non-editable.

## 8. Assembly rendering

The renderer consumes a catalog snapshot, assembly id, scenario id, presentation toggles, and the
workspace's current buffers. It returns ordered typed layers:

- rendered perk-owned text with canonical source/fragment provenance;
- external boundary placeholders with owner and boundary kind; or
- a typed render failure attached to the responsible unit.

It reuses production prompt renderers/composers where they have a stable read-only seam. Dynamic
code-owned guidance receives scenario fixtures through narrow adapters; the renderer does not
execute arbitrary repository code or model tools. One failed layer remains visible and does not
erase successfully rendered siblings.

## 9. Local security and repository safety

- The launcher binds `127.0.0.1` on an operating-system-assigned port and opens that exact URL.
- There are no external assets, network requests, telemetry, accounts, cookies, or authentication.
- Requests with a non-loopback Host or unrecognized Origin are rejected. State-changing requests
  require the current process-local anti-CSRF token.
- The repository root is fixed at launch. Every path is resolved, must remain beneath that root,
  and must match an editable canonical unit in the current catalog snapshot. Symlink escapes fail.
- Generated/materialized lineage targets and boundaries are always read-only.
- The process inherits ordinary user permissions and never elevates them.
- Read-only Git status/diff may annotate files. No endpoint or process adapter exposes mutating Git
  operations.

The future launcher is `perk-dev prose-review`; it chooses a random loopback port and opens the
browser by default, with `--no-open` as the only required launch option.

## 10. Core architecture seams

Framework choice is deferred, but the implementation must preserve these deep modules:

- **Catalog:** loads the authored graph and discovered source catalog once, validates it, and serves
  immutable capability, relation, assembly, scenario, source, and lineage queries.
- **EditWorkspace:** owns canonical per-file buffers, source hashes, dirty state, diffs, conflicts,
  and unload protection. UI aliases contain only a unit id and never own text.
- **SourceAdapter:** abstracts extraction, focused replacement, validation, and atomic save for one
  locator family. It is the only module allowed to read or write canonical source files.
- **AssemblyRenderer:** composes typed owned layers and external placeholders from catalog scenarios
  plus workspace buffers.
- **CheckRunner:** exposes an allowlisted set of non-mutating targeted commands with bounded
  execution, captured output, cancellation, and no shell interpolation.

The HTTP layer and UI consume typed DTOs from these modules. They do not parse YAML, traverse the
repository, construct source paths, or infer relationships themselves.

## 11. Acceptance scenarios

1. **Warm/cold family:** navigate Planning → Plan authoring, compare cold and warm shapes, and see
   their shared context, skill, and tool units as canonical aliases.
2. **Shared buffer:** edit the plan skill from one assembly; every other alias and comparison pane
   reflects the unsaved bytes immediately.
3. **Layered preview:** preview interactive and headless implementation scenarios; owned layers
   render in order while Pi/user/runtime content remains labeled placeholders.
4. **Safe save:** edit a Markdown section, review the full-file diff, pass cheap checks, save
   atomically, and observe a clean workspace state without unrelated formatting changes.
5. **Conflict:** modify the same file externally after it loads; save refuses and preserves both
   disk content and the in-memory edit.
6. **Invalid source:** break TypeScript syntax or remove a mapped heading; pre-save validation
   rejects the write with the structural reason.
7. **Containment:** attempt a traversal, symlink escape, generated-target edit, or unmapped-file
   write; every attempt is rejected before filesystem mutation.
8. **Graph drift:** add a new model-facing tool field outside the map; `prose-map check` fails until
   it is routed or deliberately excluded through normal YAML/code review.
