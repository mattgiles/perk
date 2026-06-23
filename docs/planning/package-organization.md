# Package organization for `perk/` — the north star

*A durable design doc settling, from first principles, **why `perk/` is organized the way it is** and
**where every module lives**. Same genre/home as `node-3.1-architecture-correction.md`: an
architecture note, not a turn plan. The layout it describes (§1C) is **fully realized** — every module
lives at the home these principles assign it.*

---

## 1A. The governing first principles (the "why")

These are the organizing axes. Each module's home is decided by applying them in order; when two
axes disagree, the earlier one wins, and Principle 6 (symmetry) is the final tie-breaker.

1. **Layer by role, depend downward.** Lower layers never import upward. The role layers,
   lowest → highest:
   `substrate` (cross-cutting plumbing) → **pure mechanics** (`plan`, `objective`) →
   **forge gateway** (`github`) + **backends** (`backends/`) →
   **orchestration** (`state`, `run`, `convergence`) → **`cli`** (the Click surface).
   An import that points *up* this list is a layering violation.

2. **Universal vs. backend-selectable.** A capability that is the **same for every issue backend** —
   pull requests, code review, CI/workflows, auth (all git-forge/GitHub-universal, *even under a
   Linear issue backend*, because perk's code still lives on GitHub) — lives in the **forge gateway**
   `perk/github/`. A capability that is **backend-selectable** — issue tracking, objective storage —
   lives behind a **backend-neutral contract** in `perk/backends/`, with one **subpackage per
   concrete backend**.

3. **Contract / adapter / substrate separation.** For each selectable tier:
   - a pure **contract** module (a `Protocol` + frozen dataclasses + the tier's error type), importing
     **nothing** from any concrete backend;
   - one **adapter** per backend, mapping that backend's native surface onto the contract;
   - the backend's **substrate** — its raw API calls.
   A single **resolver** turns config (`[issues]`) into the right adapter.

4. **The client is the API seam.** A backend's API-client class — `LinearClient`; the `gh`/`_exec`
   layer — is the **sole** encapsulation of its transport. Higher layers compose primitives *through*
   it; they never reach a sibling's private transport. (See
   `node-3.1-architecture-correction.md`: "the client is the API seam" — op classes register only the
   client.)

5. **Pure mechanics are network-free and deterministic.** `plan` and `objective` (including drift) do
   storage shaping / parsing / rendering with **no Click, subprocess, or network**, which is exactly
   what makes them deterministically unit-testable. They sit **below** the gateway and backends:
   those import the mechanics, never the reverse.

6. **Symmetry is the tie-breaker.** When two things play the same role — the GitHub backend and the
   Linear backend; the issue tier and the objective tier — they should have the **same shape**.
   Symmetry is a tie-breaker, *not* a mandate: a deliberate asymmetry is fine when an earlier
   principle demands it, but it must be **named explicitly** (next section).

---

## 1B. Where each concern lives

`perk/` is layered by role. Each formerly-asymmetric concern now lives at the home its governing
principle assigns — no open asymmetry remains:

1. **The GitHub backend's issue/objective substrate lives under `perk/backends/github/`** (Principles
   2 & 3) — symmetric with `perk/backends/linear/`. Issue tracking and objective storage are
   backend-selectable, so they sit behind the backend-neutral contract, one subpackage per concrete
   backend, rather than inside the forge gateway.

2. **`perk/github/` is a pure forge gateway** — universal git-forge machinery (PR/CI/auth) only
   (Principle 2). It never imports the backend tier; the issue/objective substrate it once also held
   now lives in `backends/github/`.

3. **`perk/objective/drift.py` is pure objective mechanics under the `objective/` package**
   (Principle 5) — conceptually `perk.objective.drift`, homed there rather than at the top level.

4. **The two backend-neutral resolvers + the backend-id constants live in `perk/backends/resolve.py`**
   (Principle 3); the adapters live under `backends/github/`. The old `issues.py` /
   `objective_stores.py` modules are gone — killing the singular/plural contract-vs-impl smell where
   the distinction rode on a near-invisible `s`.

5. **`LinearClient` is `perk/backends/linear/client.py`** — Principle 4 keeps the client a distinct
   module (it is the API seam), inside the `linear/` subpackage.

6. **The Linear Agents-UI session mirror is `perk/backends/linear/agent.py`** — a Linear concern,
   homed inside the `linear/` subpackage with the rest of the backend.

---

## 1C. The tree (the north star)

```
perk/
  substrate/                  # cross-cutting plumbing (config, git, output, providers,
                              #   registry, bindings, binding_delivery) — unchanged
  plan.py                     # pure plan mechanics (single module — ratified, Stage D)
  objective/                  # pure objective mechanics
    _models.py  parse.py  render.py  manifest.py  graph.py
    drift.py                  # pure objective drift mechanics
  github/                     # UNIVERSAL git-forge gateway (used by ALL backends)
    _exec.py  auth.py  prs.py  reviews.py  workflows.py
  backends/
    issue_backend.py          # contract: IssueBackend Protocol + dataclasses + error
    objective_store.py        # contract: ObjectiveStore Protocol + dataclasses + error
    engagement.py             # contract: shared human-engagement read model + classifier
    resolve.py                # BOTH resolvers (resolve_issue_backend / resolve_objective_store)
                              #   + the backend-id constants
                              #   (replaces issues.py + objective_stores.py)
    github/                   # the GitHub backend (issue + objective substrate + adapters)
      backend.py              #   GitHubIssueBackend
      objective_store.py      #   GitHubObjectiveStore
      plans.py objectives.py engagement.py   # GitHub issue/objective substrate
    linear/                   # the Linear backend (renamed from linear_backend/)
      client.py               #   LinearClient (the API seam)
      backend.py issue_ops.py project_ops.py project_store.py
      objectives.py readiness.py _helpers.py
      agent.py                #   Linear Agents mirror
  state/  run/  convergence/  cli/   # orchestration + surface (unchanged)
```

Two symmetries hold across this layout: **`backends/github/` ↔ `backends/linear/`** (Principle 6), and
**`github/` as a single-role forge gateway** (Principle 2).

---

## 1D. Settled decisions

The staged reorg that produced this layout is **fully realized** — every module in §1C lives at its
home. One durable decision is recorded here so it is settled rather than reopened:

### `plan.py` stays a single module

`plan.py` is **not** split into a `plan/` package. It is cohesive — one tier of pure plan mechanics
(plan-issue header/body/metadata-block shaping/parsing/rendering) — and **395 lines**, under the
400-line threshold. Principle 6 makes symmetry with `objective/` a *tie-breaker*, not a mandate, and a
cohesive sub-400-line module needs no package: `objective/` is a package because objective mechanics
genuinely span six concerns (`_models` / `parse` / `render` / `manifest` / `graph` / `drift`);
`plan.py` has no such internal seams. Splitting would add a package boundary, an `__init__.py`
re-export surface, and import churn for zero cohesion or testability gain.

---

## 1E. Cross-references

- `docs/learned/workflow/issue-backend.md` — the universal-vs-selectable tier principle and the
  explicit "GitHub issue-tier move is deferred until a 2nd backend + Fake-backend fixtures" note.
- `docs/learned/workflow/objective-store.md` — the parallel objective-tier split, the resolver
  single-sourced off `[issues]`, the import-cycle `backend_id` literal discipline, the
  late-bound-delegation equivalence lock.
- `docs/learned/workflow/github-gateway.md` — the `gh` gateway parse-helper family and consolidation
  boundary rules.
- `docs/learned/workflow/linear-backend.md` — the Linear backend's client-is-the-seam layering and
  fakes.
- `docs/planning/node-3.1-architecture-correction.md` — "the client is the API seam" (Principle 4).
