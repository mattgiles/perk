# Design: adapter architecture + the provider-selection substrate

**Status:** design doc (Objective #115, Node 1.3)
**Motivation:** This is the **third and final design-doc node** of Objective #115's Phase 1, and it
closes the hand-off chain its two siblings opened. Node 1.1 (`docs/design/pluggability-taxonomy.md`,
PR #117) locked *which* surfaces are seams — the four criteria C1–C4 and the verdict that exactly
two surfaces pass, **plan** and **todo**. Node 1.2 (`docs/design/provider-contract.md`, PR #122)
locked *what contract* a provider must satisfy — the seven provider dimensions and the two
conformance points: the durable cross-plane `cache.plan-ref` for plan, and the transient
`perk:checkpoint` session entry (with the `## Steps` / `[WIP:n]`/`[DONE:n]` vocabulary) for todo.
Both stopped at the verdict / the contract shape and pointed forward to this node: "Node 1.3 —
adapter architecture + selection substrate: how a chosen provider is wired in, including the
`shared/providers.yaml` shape." This doc is that hand-off. It locks the last missing shape — **how a
provider is selected and wired**: the perk-owned adapter-shim architecture, the `shared/providers.yaml`
supported-set registry shape, the `[providers]` config schema, and how `perk init` reads the
selection and wires the chosen package(s) plus Pi package filtering into `.pi/settings.json`.

Like both siblings, this node ships **a prose design doc only** — no code, no schema, no
`shared/providers.yaml`, no parser, no config-reading, no `init` wiring, and no `shared/contracts.md`
change. Per the repo's "don't author fiction for unbuilt components" rule, it **locks shapes** and
points forward; Phases 2–3 (Nodes 2.1/2.2/2.3/3.1/3.2) implement them. The single deliverable is one
new file — *this file* — and it is intentionally **not** listed in `docs/index.md` (mirroring both
siblings and the `session-introspection.md` precedent).

## The central thesis: two complementary wiring mechanisms

Selecting a provider is not one act but **two** — because a provider has two halves (Node 1.2,
dimensions 2 and 3): an **owned surface** (the authoring UX, free to vary) and a **produced
contract** (the perk-internal artifact boundary, the invariant). Wiring a foreign provider therefore
requires two complementary mechanisms, one per half:

1. **Pi package filtering** swaps the *surface*. The object-form `packages` entry in
   `.pi/settings.json` (`{ "source": …, "extensions": […], "skills": […], … }`, per Pi
   `docs/packages.md` "Package Filtering") narrows what each foreign package loads: omit a key →
   load all of that type; `[]` → load none; `!pattern` excludes; `+path` force-includes; `-path`
   force-excludes. perk uses this to **enable only the foreign extension(s) that present the chosen
   surface and disable conflicting ones** — so a selected `@tombell/pi-plan` loads its plan-mode
   extension while perk's own plan surface steps aside (see mechanism asymmetry below).

2. **The perk-owned adapter shim** lands the *contract*. A shim is perk substrate (a small module
   under `extension/`, Node 2.3/3.2) that **observes the foreign provider's output and lands it at
   the Node 1.2 artifact boundary**: a foreign plan surface's decision-complete plan is bridged to
   `plan_save` → `cache.plan-ref`; a foreign todo surface's progress is bridged to the
   `perk:checkpoint` entry + the `[WIP:n]`/`[DONE:n]` vocabulary. The shim is the only thing that
   knows the foreign package's shape; everything downstream still binds only to the perk-internal
   artifact (Node 1.2's isolation guarantee, dimension 7).

Filtering alone cannot make a foreign provider conform (its output would never reach perk's artifact
boundary); a shim alone cannot prevent two surfaces colliding (both perk's and the foreign one would
present a plan command). **Both are required, and they are orthogonal**: filtering is declarative
config written by `init`; the shim is runtime perk code.

### Invariant 1 — the gate stays perk's (Node 1.2 Generalization 2)

The read-only **tool-gate** (`extension/toolGating.ts` `registerToolGating`) is **shared perk
substrate** — also consumed by the read-only CI executor — that the plan provider *composes* via
`enter`/`exit`, never *owns*. An adapter shim therefore **composes the gate, never owns or replaces
it.** When a foreign plan provider is adapted (Node 2.3), the perk-owned shim bridges the foreign
authoring surface to perk's gate + `plan_save` + `cache.plan-ref`; the gate itself is not swapped,
filtered, or handed to the foreign package. A shim that tried to own the gate would break the CI
executor and every other gate consumer. This is the load-bearing constraint the adapter architecture
must respect.

### Invariant 2 — perk defers at runtime; it is NOT filtered

The two wiring mechanisms apply **asymmetrically** across the perk reference provider and the foreign
provider, and the asymmetry is forced by perk's packaging:

- **The foreign package is filtered.** It is its own `packages` entry, so Pi filtering can enable or
  disable its extensions surgically.
- **perk is never filtered; it defers at runtime.** perk's entire extension is a **single package
  entry** (`extension/index.ts` registers `planMode`, `planSave`, `checkpoints`, `toolGating`,
  objectives, CI, … all together). Pi filtering operates at package/extension-file granularity, so
  it **cannot disable just `planMode`** without tearing out unrelated perk surfaces. Therefore perk's
  reference provider **steps aside at runtime** — when a foreign plan provider is selected, perk's
  `planMode`/`planSave` notice the selection (via the resolved `[providers]` config) and decline to
  present their surface, rather than being filtered out of the build. The runtime-deferral mechanics
  are Nodes 2.2 (plan) / 3.1 (todo); 1.3 only locks that the asymmetry exists and why.

This asymmetry is why "select a foreign provider" is **not** symmetric with "deselect it": deselect
reverts to perk's always-present reference provider (which simply resumes presenting its surface),
while the foreign package is added/removed from `packages` entirely.

## The `shared/providers.yaml` shape — the supported-set registry

Node 1.3 locks (but does not author) `shared/providers.yaml` as the **third bundled cross-plane
YAML**, a sibling of `shared/registry.yaml` and `shared/bindings.yaml`: authored once, bundled into
each build artifact (wheel → `perk/_shared/`, npm tarball → `shared/`), and parsed directly by both
planes at runtime — **no codegen**. It is the **supported set**: the full catalog of providers perk
knows how to wire, distinct from the per-repo *selection* (which lives in `.pi/perk.toml`, below).
Because it is read by both planes' YAML readers (like its siblings), it can carry **nested**
structure — notably the Pi `package_filter` object — that the narrow-TOML config reader could not.

The locked shape:

```yaml
schema_version: 1

providers:
  - id: perk-plan            # provider id (the cache.plan-ref `provider` field; Node 1.2 dim 1)
    seam: plan               # plan | todo
    package: null            # null ⇒ perk's own bundled reference provider (no foreign package)
    adapter: null            # null ⇒ no shim needed; perk already produces the contract natively
    default: true            # exactly ONE default per seam — the behavior-preserving no-config pick
  - id: perk-checkpoints
    seam: todo
    package: null
    adapter: null
    default: true

  # --- illustrative foreign entries (NOT authored in 1.3; shown to lock the shape) ---
  - id: tombell-plan         # ILLUSTRATIVE — the real entry lands with the Node 2.3 adapter
    seam: plan
    package: "npm:@tombell/pi-plan"   # the foreign Pi package to add to `packages`
    adapter: "planAdapterTombell"     # the perk-owned shim module bridging surface → cache.plan-ref
    default: false
    package_filter:                   # optional Pi object-form filter applied to the foreign package
      extensions: ["extensions/*.ts"]
      skills: []
  - id: juicesharp-todo      # ILLUSTRATIVE — the real entry lands with the Node 3.2 adapter
    seam: todo
    package: "npm:@juicesharp/rpiv-todo"
    adapter: "todoAdapterJuicesharp"
    default: false
```

The fields, and what each is for:

- **`id`** — the stable provider id; for the plan seam it is exactly the `cache.plan-ref` `provider`
  string (Node 1.2 dimension 1).
  > **Reconciling note (shipped contract):** this equivalence is aspirational — in the shipped
  > contract `cache.plan-ref.provider` is the **issue backend** (the stamped `backend_id`), not the
  > seam id. See `shared/contracts.md` §8.10.
- **`seam`** — `plan` | `todo`; the two seams Node 1.1 scope-fenced.
- **`package`** (nullable) — the foreign Pi package spec added to `.pi/settings.json` `packages`;
  `null` for perk's own bundled reference provider (nothing to add).
- **`adapter`** (nullable) — the perk-owned shim module that bridges the foreign surface to the Node
  1.2 artifact boundary; `null` for the reference provider (perk produces the contract natively).
- **`default`** (bool) — **exactly one `true` per seam**; the behavior-preserving no-config pick
  (Node 1.1 C3, Node 1.2 dimension 6).
- **`package_filter`** (optional) — a Pi object-form filter (`extensions`/`skills`/… arrays) merged
  into the foreign package's `packages` entry to enable only the conflicting surface and disable the
  rest.

The file ships with the **two reference entries** (`perk-plan`, `perk-checkpoints`, both
`default: true`) plus **one illustrative foreign entry per seam**, the foreign entries flagged
illustrative — their real form lands with the adapters in 2.3 / 3.2.

## Parser + validation + doctor split (mirrors `bindings.py`)

The reader split mirrors the established `shared/bindings.yaml` precedent exactly. **Node 2.1** adds
the two shape-only loaders — `perk/providers.py` (Python) and `extension/providers.ts` (TS) — each
parsing `shared/providers.yaml` into records and returning structured `Issue` records (never
throwing). The division of validation labor is the same one `bindings.py` established:

- **Loader rules (shape-only, both planes):** `schema_version == 1`; every entry well-formed and its
  `id` unique; `seam ∈ {plan, todo}`; and **exactly one `default: true` per seam**. These are
  intrinsic, single-file checks the loaders can make without touching the repo.
- **Doctor's job (cross-checks):** does the repo's `[providers]` *selection* name a provider that
  **exists** in the supported set? Is the selected provider's `package` actually **wired** into
  `.pi/settings.json` with the right filter? Did a deselect leave an orphaned foreign package? These
  cross-file/cross-plane checks are `doctor`'s responsibility (mirroring how bindings target-existence
  validation lives in doctor, not the loaders). 1.3 assigns them; Node 2.1 implements them.

## The `[providers]` config — selection in `.pi/perk.toml`

The per-repo **selection** (distinct from the supported set) is a new flat `[providers]` table in
`.pi/perk.toml`:

```toml
[providers]
plan = "tombell-plan"       # a provider id from shared/providers.yaml, seam == plan
todo = "perk-checkpoints"   # a provider id from shared/providers.yaml, seam == todo
```

Locked decisions about this table:

- **Flat string table, one key per seam** (`plan` / `todo`), values are **bare provider-id strings**.
  Strings only — because the TS narrow-TOML reader `parseTomlSubset` (the dependency-free subset
  reader, also used for `[ci]` and `[workflow]`) reads **string values only**; richer structure
  (e.g. the `package_filter`) lives in `shared/providers.yaml`, which both planes' full YAML readers
  parse. The selection is just a pointer into the supported set.
- **Absent table or absent key → the seam's `default: true` provider** — zero behavior change, the
  no-config default (Node 1.1 C3). A repo that never writes `[providers]` runs perk's reference
  providers exactly as today.
- **`perk.local.toml` overlay wins** — the standard local-override precedence applies, so a developer
  can select a provider locally without committing the choice.

## `perk init` wiring — two-directional reconciliation

`perk init` is where the `[providers]` selection becomes `.pi/settings.json` `packages` entries.
Locked shape:

1. **Resolve the selected provider per seam** — read `[providers]` (with the `perk.local.toml`
   overlay) and look each id up in `shared/providers.yaml`; absent → the seam default.
2. **The static `BORROWED_PACKAGES` layer is unchanged.** Today `_desired_packages` pins perk's own
   package plus the static borrowed set; that path stays exactly as-is for non-provider packages.
3. **A selection-driven layer composes on top.** For each seam whose selected provider has a non-null
   `package`, `init` adds that foreign package to `packages` in **object form**, merging the
   provider's `package_filter` (Node 2.3/3.2). perk's own package is **never filtered** (Invariant 2).
4. **Two-directional reconciliation — the new wrinkle.** Unlike today's append-only
   `_converge_settings` (which only *adds* desired packages), provider wiring must also **remove** a
   foreign package when the selection changes away from it. Deselecting a provider has to drop its
   package from `packages` — which means `init` needs the **full supported set** (`shared/providers.yaml`)
   to know *which* package entries are provider-managed and therefore removable, distinct from the
   user's own hand-added packages, which it must never touch. This bidirectional converge (add the
   selected, remove the deselected-but-previously-managed) is the one genuinely new convergence
   behavior 1.3 introduces over today's forward-only append.
5. **Retired foreign packages re-enter only when selected.** `@tombell/pi-plan` and
   `@juicesharp/rpiv-todo` were both borrowed-then-retired (Node 1.1's history); under this
   architecture they re-enter `packages` **only** when a `[providers]` selection names them — wired
   by the adapters in Nodes 2.3 (plan) / 3.2 (todo). The default build still ships neither.

## The two seams instantiated

| Seam | Reference provider (default) | Foreign-adapter target | Produced contract (conformance point) |
|---|---|---|---|
| **plan** | `perk-plan` — perk's own `planMode`/`planSave` over `toolGating` | `@tombell/pi-plan` (Node 2.3) | durable cross-plane `cache.plan-ref` (+ `active_plan_ref`) |
| **todo** | `perk-checkpoints` — perk's own `checkpoints` | `@juicesharp/rpiv-todo` (Node 3.2) | transient TS-only `perk:checkpoint` entry (+ `## Steps`/`[WIP:n]`/`[DONE:n]`) |

Both reference providers have `package: null` / `adapter: null` (perk produces the contract natively,
no surface to filter); both foreign targets carry a `package` + an `adapter` shim and re-enter
`packages` only on selection. The plan seam additionally **composes the shared tool-gate** (Invariant
1); the todo seam composes no shared primitive (Node 1.2 Generalization 2).

## Forward hand-off (what 1.3 does NOT decide)

Per the repo's anti-fiction rule, 1.3 locks shapes only and defers all machinery:

- **Node 2.1** — author the substrate: `shared/providers.yaml` itself, the `perk/providers.py` +
  `extension/providers.ts` shape-only loaders, the `[providers]` config-reading in both config
  readers, the two-directional `init` wiring, the doctor selection-exists / package-wired
  cross-checks, and the `shared/contracts.md` spec for all of it (1.3 changes no contract).
- **Node 2.2** — refactor perk's plan mode behind the seam so it defers at runtime when a foreign
  plan provider is selected (Invariant 2's mechanics).
- **Node 2.3** — the **first foreign plan adapter**: the concrete `@tombell/pi-plan` shim bridging
  its surface to `plan_save` → `cache.plan-ref`. The concrete per-package bridge is deferred here.
- **Node 3.1** — refactor perk's checkpoints behind the seam (the todo runtime-deferral).
- **Node 3.2** — the **first foreign todo adapter**: the concrete `@juicesharp/rpiv-todo` shim
  bridging its surface to the `perk:checkpoint` entry.

1.1 locked *which* surfaces are seams; 1.2 locked *what contract* they must satisfy; **1.3 locks how
a provider is selected and wired**; Phases 2–3 implement the refactor + the first foreign adapters.

## References

- **Sibling design docs:** `docs/design/pluggability-taxonomy.md` (Node 1.1 — the four criteria
  C1–C4, the plan/todo verdicts, the scope fence) and `docs/design/provider-contract.md` (Node 1.2 —
  the seven provider dimensions, the two artifact tiers, the two conformance points `cache.plan-ref`
  and `perk:checkpoint`, Generalization 2's shared-primitive composition).
- **Pi package filtering:** `@earendil-works/pi-coding-agent/docs/packages.md` — the object-form
  `packages` entry (`source` + `extensions`/`skills`/`prompts`/`themes` arrays), the
  `!exclude`/`+include`/`-exclude`/`[]`=none/omit=all semantics, and package identity/dedup.
- **Cross-plane YAML siblings:** `shared/registry.yaml` (the stage registry) and
  `shared/bindings.yaml` (skill bindings) + their loaders `perk/bindings.py` / `extension/bindings.ts`
  — the bundled-once, parsed-by-both-planes, shape-only-loader + doctor-cross-check precedent this
  node's `shared/providers.yaml` follows.
- **init wiring:** `perk/init.py` (`BORROWED_PACKAGES`, `_desired_packages`, `_converge_settings`,
  `_npm_name`/`_git_identity` package identity) — the append-only convergence this node extends to
  two-directional.
- **Config reader:** `extension/config.ts` (`parseTomlSubset`, the string-only narrow-TOML reader
  shared by `[ci]`/`[workflow]`) and the `perk.local.toml` overlay precedence — why `[providers]`
  values are bare strings.
- **Reference providers:** `extension/planMode.ts` / `extension/planSave.ts` / `extension/toolGating.ts`
  (the plan reference + the shared gate) and `extension/checkpoints.ts` (the todo reference);
  `extension/cache.ts` `PlanRef` / `perk.plan.PlanRef` (the `cache.plan-ref` payload, `provider`
  field = the provider id).
- **Foreign targets / borrow-then-retire history:** `@tombell/pi-plan` (plan, Node 2.3 target) and
  `@juicesharp/rpiv-todo` (todo, Node 3.2 target) — `docs/ROADMAP.md` default-package strategy.
- **Format precedent:** `docs/design/session-introspection.md` (the `# Design:` / `**Status:**` /
  `**Motivation:**` / `## References` shape; like both siblings, intentionally **not** listed in
  `docs/index.md`).
