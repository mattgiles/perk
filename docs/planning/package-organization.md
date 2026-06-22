# Package organization for `perk/` — the north star

*A durable design doc settling, from first principles, **why `perk/` is organized the way it is** and
**where every module should live**. Same genre/home as `node-3.1-architecture-correction.md`: an
architecture note, not a turn plan. The one code move it justifies now — `perk/objective_drift.py` →
`perk/objective/drift.py` — landed with this doc (Stage A). Every larger, fixture-heavy
reorganization is staged as a follow-up node below, **not** implemented yet.*

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

## 1B. Reconciling today's asymmetries

`perk/` is layered by role, but with six asymmetries. For each: *deliberate* (with the principle that
justifies it) or *to-be-fixed* (with the target + the stage that does it).

1. **`linear_backend/` is a subpackage but there is no `github_backend/`** (GitHub's issue/objective
   substrate lives *inside* `perk/github/`) → **to-be-fixed** via Principles 2 & 3 (**Stage C**).
   Today it is grounded in "PRs are GitHub-universal", which keeps PR/CI/auth in `github/` — correct —
   but the *issue/objective* substrate is backend-selectable and should move under
   `perk/backends/github/` now that a second backend (Linear) exists.

2. **`perk/github/` plays two roles** — universal forge machinery (PR/CI/auth) *and* GitHub's
   issue/objective-tier substrate → **to-be-fixed** (**Stage C**): `github/` becomes the **pure forge
   gateway**; the issue/objective substrate moves to `backends/github/`.

3. **`objective_drift.py` is a top-level module** although it is pure objective mechanics → **fixed
   NOW** (**Stage A**, Part 2): it is conceptually `perk.objective.drift` and moved there. This is the
   only asymmetry with no principled defense — it was simply added at the top level in #612.

4. **`issue_backend.py` (contract) vs `issues.py` (impl+resolver); `objective_store.py` (contract) vs
   `objective_stores.py` (impl+resolver)** — the contract-vs-impl distinction rides on a near-invisible
   `s` → **to-be-fixed** (**Stage C**): the two backend-neutral resolvers consolidate into
   `backends/resolve.py`; the adapters move into `backends/github/`; the confusing `issues.py` /
   `objective_stores.py` modules disappear, killing the singular/plural smell.

5. **`backends/linear.py` (the `LinearClient`) sits beside `linear_backend/`** rather than inside it →
   **to-be-fixed** (**Stage B**): → `backends/linear/client.py`. Principle 4 keeps the client a
   distinct module (it is the API seam), but it belongs *inside* the `linear/` subpackage.

6. **`backends/linear_agent.py` (the Linear Agents-UI session mirror) is a third flat Linear concern**
   outside `linear_backend/` → **to-be-fixed** (**Stage B**): → `backends/linear/agent.py`.

---

## 1C. The target tree (the north star)

```
perk/
  substrate/                  # cross-cutting plumbing (config, git, output, providers,
                              #   registry, bindings, binding_delivery) — unchanged
  plan.py                     # pure plan mechanics (single module — see Stage D)
  objective/                  # pure objective mechanics
    _models.py  parse.py  render.py  manifest.py  graph.py
    drift.py                  # ← moved from perk/objective_drift.py (Stage A — DONE)
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
      backend.py              #   GitHubIssueBackend       (from today's issues.py)
      objective_store.py      #   GitHubObjectiveStore     (from today's objective_stores.py)
      plans.py objectives.py engagement.py   # substrate (from today's perk/github/)
    linear/                   # the Linear backend (renamed from linear_backend/)
      client.py               #   LinearClient            (from backends/linear.py)
      backend.py issue_ops.py project_ops.py project_store.py
      objectives.py readiness.py _helpers.py
      agent.py                #   Linear Agents mirror     (from backends/linear_agent.py)
  state/  run/  convergence/  cli/   # orchestration + surface (unchanged)
```

The two symmetries this end-state restores: **`backends/github/` ↔ `backends/linear/`** (Principle 6
over Asymmetries 1, 4, 5, 6), and **`github/` as a single-role forge gateway** (Principle 2 over
Asymmetry 2).

---

## 1D. The staged roadmap (the "how", deferred)

Each stage records scope, churn/risk, the guards/tests it must keep green, and the ordering rationale.
**Only Stage A is implemented in this PR.** B/C/D are doc-only here.

### Stage A — `objective_drift` → `objective/drift.py` (DONE in this PR; see Part 2)

The single genuinely-isolated, ~0-risk move. The module is imported by module-path in exactly four
files; a hard cutover (no compat shim) re-points them. No import cycle, because
`perk/objective/__init__.py` does **not** import the new `drift` submodule, and `drift.py` imports its
three dependencies from sibling submodules (`_models`, `graph`, `manifest`) rather than the package
root. `ty` over the whole repo is the completeness oracle (a rename is a pure type-resolution change).

### Stage B — `linear_backend/` → `backends/linear/` (+ fold `linear.py` → `client.py`, `linear_agent.py` → `agent.py`)

Linear-only churn, **no `perk.github` fixture impact**. Updates every
`from perk.backends import … linear, linear_backend`, `from perk.backends.linear import …`,
`from perk.backends.linear_backend… import …`, and the Linear test modules. **Medium risk.** Must keep
the Linear conformance bindings + the offline GraphQL fakes green. Ordering: before Stage C, because
it is self-contained and proves the per-backend-subpackage shape that Stage C mirrors for GitHub.

### Stage C — the github split (the big one)

Introduce `perk/backends/github/`; move `perk/github/{plans,objectives,engagement}.py` (the
issue/objective substrate) into it; move `GitHubIssueBackend` / `GitHubObjectiveStore` into
`backends/github/`; consolidate the two resolvers into `backends/resolve.py`; **delete**
`issues.py` / `objective_stores.py`. **Cost:** the ~245 `monkeypatch.setattr(github, …)`
issue/objective-tier sites must re-point at the new substrate module (the PR/CI/auth-tier monkeypatch
sites are **unaffected** — they stay on `perk.github`); the **source-scan boundary guards**
(`tests/test_issues.py`, `tests/test_issue_backend.py::TestImportDirection`, the objective-tier guard)
must be rewritten for the new allowed-set + import directions. The import-cycle literal discipline (the
`backend_id` constant) and the late-bound-delegation equivalence lock must be preserved — the
late-bound adapters will delegate to `perk.backends.github` module functions instead of `perk.github`,
so the fixtures migrate to a backend-substrate fake (the Fake-backend condition recorded in
`docs/learned/workflow/issue-backend.md`, now met because Linear landed). **Highest risk — plan as its
own dedicated node (or a small node sequence).** Ordering: last, because it is the most expensive and
benefits from the Stage B template.

### Stage D — `plan.py` packaging (ratify or split)

Decide whether to leave `plan.py` a single module or split it into a `plan/` package for symmetry with
`objective/`. **Recommendation: ratify-as-is.** `plan.py` is cohesive and under 400 lines; Principle 6
makes symmetry a *tie-breaker*, not a mandate, and a cohesive sub-400-line module needs no package.
Lowest value of the four stages; recorded here so the decision is settled rather than reopened.

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
