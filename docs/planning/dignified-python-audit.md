# Dignified Python audit — perk's Python tree

> **Objective #714, Node 1.1.** This is the authoritative prioritized findings catalog that the
> Phase 2–4 remediation nodes draw from, and the document against which the objective roadmap is
> reconciled after this node lands.

## 1. Framing

This audit holds perk's entire Python tree up against the **`dignified-python`** standard
(`.agents/skills/dignified-python/`) and records, for every material finding, a concrete
`file:symbol` anchor, a severity, the observed problem, and a recommended remediation — organized
by quality dimension.

**Scope:** `perk/**/*.py` (~26.7k lines across ~120 modules) + `tests/**/*.py` (~28.2k lines across
~74 modules).

**The suite is already green.** `ruff` is configured with `E, F, I, UP, B, SIM, RUF, PLW1514, PTH,
PLR1702, PLC0415` and `ty` type-checks the whole tree; `just ci` passes. The value of this audit is
therefore **in what those tools cannot see** — module depth and cohesion, type-literacy (tools
accept `dict[str, object]` + `cast` happily), declare-close-to-use, single-use destructuring,
LBYL/EAFP *fit* (not mere `B904` chaining), and genuine edge-case correctness. We deliberately do
**not** re-catalog anything `ruff`/`ty` already enforces.

> **Already-enforced — do NOT re-catalog.** `PTH` (pathlib — confirmed **zero** `os.path` in
> `perk/`), `PLW1514` (explicit `encoding=` — confirmed **zero** bare `open()` without encoding),
> `PLR1702` (nesting depth — so no finding here is "this is N levels deep"; structural depth is
> discussed only where extracting a helper improves *cohesion*), `PLC0415` (inline imports —
> intentionally ignored in `tests/`; the single production inline import,
> `github/reviews.py:_read_plan_body`, carries an explicit `# noqa: PLC0415` and is a deliberate
> import-cycle break, **not** a finding). `UP`/`B`/`SIM`/`RUF` cover modern syntax, bug-bears, and
> simplifications. The catalog records only what survives a green suite.

## 2. How to read this catalog

### Severity scale (locked)

- **P1 — Correctness / risk.** A genuine bug, latent failure, or maintainability hazard that *will*
  bite. The fix is justified on its own merits.
- **P2 — Dignity debt.** A clear dignified-python violation (deep/shallow modules, low
  type-literacy, idiom drift) that materially hurts readability/navigability but is not a bug.
- **P3 — Polish.** Minor, batchable improvement; nice-to-have.

### Finding schema (locked — every finding carries all fields)

Each finding is a table row with: **Anchor** (`path/module.py:Symbol` — a function/class/method
name, **never** a line number), **Sev**, **Observation** (concretely, against the standard), and
**Remediation** (behavior-preserving unless an explicit P1 correctness fix, which notes any
`shared/contracts.md` implication). The owning **Target node** is given per cluster in §4 headers
and exhaustively in §5.

### Granularity rule

Record material **P1**/**P2** findings plus genuinely worthwhile **P3** polish. **Skip** anything
`ruff`/`ty` already enforces and pure taste nits — the catalog records only what survives a green
suite. Findings are prioritized and signal-first, not a lint-every-nit dump.

## 3. Coverage map

Every module group below carries an explicit verdict — its listed findings, or a stated
"**clean** — no material findings". This proves the whole tree was inspected without drowning the
catalog in noise. (`✎ §4.x` points at the dimension section(s) where the group's findings live.)

| Group | Largest modules (lines) | Verdict |
| --- | --- | --- |
| `backends/` | `linear_backend.py` (3579), `objective_store.py` (448), `issues.py` (395), `objective_stores.py` (375), `engagement.py` (371), `issue_backend.py` (342), `linear.py` (292), `linear_agent.py` (265) | **Findings** — the audit's centre of gravity: module depth (§4.1), type-literacy (§4.2), idiom + fail-open boundaries (§4.3, §4.5). |
| `convergence/` | `init.py` (1488), `doctor.py` (1185), `env.py`, `capabilities.py` | **Findings** — long multi-concern modules + `cast`-heavy dict shaping (§4.1, §4.2, §4.5). |
| `objective.py` + `objective_drift.py` | `objective.py` (1039), `objective_drift.py` (348) | **Findings** — broad parse/render/graph/manifest surface (§4.1); `Any`-typed parse layer + duplicate `Severity` (§4.2, §4.3). |
| `run/` | `launch.py` (852), `run_report.py` (235), `runner.py` (208), `run_worker.py` (206), `workflow_artifacts.py` (240), `resume.py` | **Findings** — `launch.py` breadth (§4.1); `dict[str, Any]` plan-ref plumbing (§4.2); one fail-open boundary (§4.5). |
| `github/` | `prs.py` (573), `reviews.py` (563), `objectives.py` (504), `plans.py` (470), `engagement.py`, `workflows.py`, `auth.py`, `_exec.py` | **Findings** — `dict[str, Any]` GraphQL parse layer + `_nodes`/`_graphql` Any-leak (§4.2); `__init__.py` re-export facade (§4.3). |
| `cli/` | `cli.py`, `alias.py` (286), `stages.py` (182), `context.py`, `ensure.py`, `commands/**` (71 files; `plan/save_cmd.py` 559, `pr/land_cmd.py` 472) | **Findings** — large command-impl functions + repeated fail-open `except Exception` boundaries (§4.1, §4.5). |
| `state/` | `cache.py` (331), `gc.py` (176), `run_id.py` | **Findings (light)** — `dict[str, Any]` JSON-artifact readers (§4.2); otherwise clean, cohesive leaf. |
| `substrate/` | `git.py` (435), `registry.py` (280), `bindings.py` (277), `config.py` (266), `providers.py` (262), `binding_delivery.py`, `output.py` | **Findings (light)** — duplicate `Severity` enum naming (§4.3); `_as_list`/`_str`/`Any` registry parse helpers (§4.2). Otherwise a clean, well-factored substrate. |
| `plan.py` (395) | — | **Findings (light)** — `dict[str, object]` lifecycle helpers; small and cohesive otherwise (§4.2). |
| `tests/**` | `test_linear_backend.py` (4086), `test_github.py` (1907), `test_launch.py` (1560) | **Findings** — fake-backend duplication across 3 modules + very large test files (§4.1, §4.2); respects test-plane idioms (fixtures, monkeypatch, intentional `PLC0415` ignore). |

## 4. Findings by dimension

Five sections, one per dimension, ordered by severity within each. Anchors are `file:symbol`.

### 4.1 Organization & module depth

*Long/shallow modules, weak cohesion, narrow-interface opportunities. Structural depth is discussed
only where a helper extraction improves cohesion — raw nesting is already `PLR1702`-bounded.*

| Anchor | Sev | Observation | Remediation |
| --- | --- | --- | --- |
| `backends/linear_backend.py` (whole module) | P2 | One 3579-line module holds **seven** top-level classes: `_LinearIssueOps`, `_LinearProjectOps`, `LinearIssueBackend`, `LinearObjectiveStore`, `LinearProjectObjectiveStore`, `LinearReadiness`, `LinearProjectReadiness` — the Linear client ops, the issue backend, both objective stores, and both readiness probes. This is the single biggest cohesion liability in the tree and the objective's Node 2.1 target. | Decompose along the natural seams (issue ops, project ops, issue backend, objective store, project objective store, readiness/payload helpers) into focused modules. **Preserve** the late-bound adapter wiring and the substrate-home principle (only `LinearClient` encapsulates GraphQL; op classes register only the client). Behavior-preserving; parity/lifecycle smokes stay green. → **2.1** |
| `backends/linear_backend.py:LinearProjectObjectiveStore.adopt_source_as_objective` / `.create_objective` / `.add_objective_node` | P2 | The three longest methods in the tree (176 / 148 / 121 lines). Each interleaves live-roadmap derivation, phase/milestone enrichment, issue creation, and relation wiring in one body. | As part of the 2.1 split, extract the cohesive sub-steps (phase→milestone resolution, node-issue materialization, relation/edge sweep) into named private helpers with narrow interfaces, so each public method reads as a short sequence of intent-named calls. → ~~**2.1**~~ **3.1** *(reconciled — see §4.1 outcome below: 2.1 delivered the verbatim module split only; this long-method extraction is deferred to **3.1**, which re-types those exact methods anyway)*. |

> **§4.1 outcome (Node 2.1, PR #718).** The verbatim `linear_backend.py` → `linear_backend/`
> **package** split landed under **2.1** — a pure behavior-preserving relocation following the
> `perk/github` precedent: the 7 top-level classes + module helpers moved into `_helpers.py`,
> `issue_ops.py`, `project_ops.py`, `backend.py`, `objectives.py`, `project_store.py`,
> `readiness.py` behind an `__init__.py` re-export facade (the `linear_backend.X` import path is
> preserved verbatim — zero consumer/test churn). The **long-method sub-step extraction** (the row
> directly above) was **deferred to 3.1**, which re-types those exact methods — keeping 2.1 a clean
> verbatim split with no logic edits. This keep-and-annotate corrects the original row's `→ 2.1`
> assignment; the finding itself is unchanged.
| `objective.py` (whole module) | P2 | A single 1039-line module exposes **~37 module-level functions + 6 dataclasses/enums** spanning four distinct concerns: roadmap parse/validate (`validate_roadmap`, `parse_roadmap_nodes`, `parse_structured_roadmap`), render (`render_roadmap_block`, `render_node_block`, `render_roadmap_table`, `render_body_comment`), the dependency graph (`DependencyGraph`, `build_graph`, `_graph_from_sequential`), and the manifest (`Manifest`, `render_manifest_block`, `parse_manifest`, `_validate_manifest`). Broad multi-concern surface; navigability suffers. | Split into focused modules (e.g. `objective/parse.py`, `objective/render.py`, `objective/graph.py`, `objective/manifest.py`) with narrow interfaces, **preserving** the render/parse contracts (byte-stable block rendering) exactly. → **2.3** |
| `convergence/init.py:run_init` (and module) | P2 | 1488-line module; `run_init` alone is ~102 lines orchestrating package/settings/skills/agents/AGENTS convergence. Many `_converge_*` helpers already exist, but the top-level orchestration + dict-shaping (`report_to_dict`, `_linear_to_dict`, `_env_to_dict`) crowd one file. | Group the convergence helpers into a cohesive sub-package (settings, packages, skills, agents, report-shaping) keeping `init`'s **forward-only** convergence contract and idempotence intact. → **2.2** |
| `convergence/doctor.py:_linear_checks` (and module) | P2 | 1185-line module; `_linear_checks` is ~131 lines building many `Check` objects inline. The report-vs-fix split and exit-code contract are load-bearing and must be preserved. | Extract per-domain check builders into cohesive units; preserve `doctor`'s report-vs-fix split, `GROUP_ORDER` render order, and exit-code contract. → **2.2** |
| `run/launch.py` (whole module) | P2 | 852-line module mixing worktree resolution (`resolve_worktree`, `resolve_base`), per-stage prompt builders (`_initial_prompt`, `_implement_prompt`, `_address_prompt`, `_learn_prompt`, `_plan_read_instruction`), the launch driver (`launch_stage`, ~145 lines), remote driving (`_drive_remote_target`), and post-launch materialization (`run_worktree_setup`, `materialize_plan_body`, `materialize_skills`). The argv/env-seed ordering is documented and load-bearing. | Decompose into focused modules (prompt builders, worktree resolution, the launch driver, materialization) with narrow interfaces, **preserving** the documented launch argv/env-seed ordering exactly. → **2.3** |
| `cli/commands/plan/save_cmd.py:_plan_save_impl` | P3 | ~211-line implementation function threading handoff-link resolution, base resolution, adoption, compose, write, and render. The `_link_from_handoff`/`_adopt_from_handoff`/`_resolve_plan_base` helpers are already extracted; the residual `_plan_save_impl` body is still long. | Continue the extraction trend — pull the compose+write sequence into a named helper so `_plan_save_impl` reads as a short orchestration. Low priority (already partially factored). → **4.2** |
| `tests/test_linear_backend.py` / `tests/test_github.py` / `tests/test_launch.py` | P3 | The three largest test modules (4086 / 1907 / 1560 lines). Very large single files slow navigation; section boundaries are natural split points. | Where a file mixes clearly separable concerns (e.g. issue-backend vs objective-store vs project-store in `test_linear_backend.py`), split at section boundaries — but respect the build-once `xdist_group` pinning so shared fixtures stay on one worker. Lands last (4.3). → **4.3** |

### 4.2 Type-literacy

*`dict[str, object]` / `dict[str, Any]` + `cast(...)` pervasiveness, missing typed parse helpers,
where the `_require_*` family should consolidate vs. be left alone. **Evaluate, do not
blanket-convert** — the objective's explicit caution.*

| Anchor | Sev | Observation | Remediation |
| --- | --- | --- | --- |
| `backends/linear_backend.py` (GraphQL payload layer) | P2 | **56 × `dict[str, object]` and 9 × `cast(...)`** in one module — by far the densest untyped-payload surface in the tree. There is **zero `TypedDict` anywhere in `perk/`**. GraphQL payloads flow as untyped dicts narrowed by scattered casts plus the three `_require_*` helpers in `backends/linear.py`. | After the 2.1 split, evaluate typed parse helpers / `TypedDict`s for the recurring payload shapes and **consolidate on the deliberate `_require_*` narrowing-helper family** rather than scattering `cast`. Evaluate where a `TypedDict` adds genuine clarity vs. where `_require_dict`/`_require_list`/`_require_str` already suffice — do **not** blanket-convert. → **3.1** |
| `backends/linear.py:_require_dict` / `_require_list` / `_require_str` | P2 | The deliberate narrowing-helper family. Today only **three** helpers exist and they are called inconsistently — `linear_backend.py` mixes them with raw `cast` and inline `isinstance` walks. The family is the right pattern; it is under-used. | In 3.1, route the payload-access sites through this family (extending it — e.g. `_require_int`, an optional-aware `_opt_str` — only where a real recurring shape demands it). The helpers are the consolidation target; the `cast` sites are the debt. → **3.1** |
| `objective.py:parse_structured_roadmap` / `parse_adopt_mapping` / `validate_roadmap` / `_validate_manifest` | P2 | The parse layer is typed `dict[str, Any]` / `raw: Any` throughout (9 × `dict[str, Any]`, 6 × `cast`), e.g. `cast(dict[str, Any], dict(raw))` in `parse_structured_roadmap`. `Any` defeats `ty` on the most validation-critical code in the module. | When 2.3 splits `objective.py`, tighten the parse signatures from `Any` toward `object` + the narrowing-helper pattern (mirroring `_require_*`), so the validators gain real type-checking. Behavior-preserving. → **2.3** (typing rides the split) |
| `github/reviews.py:_graphql` / `_nodes` / `_parse_review_threads` | P2 | `_graphql` returns `dict[str, Any]` and `_nodes(obj: Any, ...)` walks with `Any`, so every GraphQL parse downstream (`_parse_review_threads`, `_parse_reviews`, `get_pr_feedback`) is `Any`-typed. The same `dict[str, Any]` parse shape recurs across `github/objectives.py`, `github/plans.py`, `github/prs.py`. | Narrow `_graphql`'s return to `dict[str, object]` and re-type the `_nodes` walker + parse helpers off `object`, leaning on `isinstance` guards already present. Sequenced with 4.1 (the backends/github sweep) so the new typing lands with the idiom pass. → **4.1** |
| `convergence/init.py:_env_to_dict` / `report_to_dict` / `_linear_to_dict` + the `cast("str", …)` package sites | P2 | Four `cast` sites (`cast("dict[str, object]", entry)`, `cast("str", packages[first])`, `cast("str", packages.pop(i))`, `cast("str", identity)`) shaping the settings-package list. The casts assert structure that an `isinstance`-guard or a typed helper would prove instead. | In 2.2, replace the package-list `cast`s with guarded narrowing (the list is read from JSON — `isinstance(entry, str)` / `isinstance(entry, dict)` branches already exist alongside the casts). → **2.2** |
| `state/cache.py` (handoff/dispatch/plan-ref/agent-session readers) | P3 | 10 × `dict[str, Any]` on the JSON-artifact read/write helpers (`read_handoff`, `write_handoff`, `read_dispatch`, `read_plan_ref`, `read_agent_session`, …). These are genuine free-form JSON blobs, so `dict[str, Any]` is *defensible* — but consumers then index them untyped. | Low priority. Leave the raw readers as-is (free-form JSON is the honest shape) but consider a thin typed accessor at the few hot consumer sites (plan-ref fields) if 4.2 finds repeated unguarded `["key"]` indexing. Evaluate, don't force. → **4.2** |
| `substrate/registry.py:_as_list` / `_str` / `_parse_stage` (`value: Any`) | P3 | The registry parser takes `Any` and hand-narrows. Small and self-contained; `Any` is the YAML-parse reality. | Optional: tighten the helper params `Any → object` with the existing `isinstance` guards. Genuinely low-value — flag only because it is the same pattern as the higher-severity sites. → **4.2** |
| `plan.py` (`dict[str, object]` lifecycle helpers) | P3 | 5 × `dict[str, object]` on small render/parse helpers. Cohesive and already typed at `object` (not `Any`) — the correct floor. | No action needed beyond a confirming read in 4.2. Recorded for coverage completeness. → **4.2** |

### 4.3 Idiom & elegance

*Declare-close-to-use, single-use destructuring, canonical import paths, naming. (`pathlib` +
explicit-encoding are `ruff`-enforced and confirmed clean — not re-cataloged.)*

| Anchor | Sev | Observation | Remediation |
| --- | --- | --- | --- |
| `substrate/registry.py:Severity` **vs** `objective_drift.py:Severity` | P2 | **Two distinct `Severity` enums** with the same name but different bases and members: `registry.Severity(Enum)` = `{ERROR, WARNING}` vs `objective_drift.Severity(StrEnum)` = `{ERROR, WARNING, INFO}`. Same-named domain types with diverging shapes are a navigation/confusion hazard (which `Severity` is in scope?). | Rename to disambiguate by domain (e.g. `RegistryIssueSeverity` / `DriftSeverity`) **or** unify on one `StrEnum` if the value sets can converge. Cross-plane: neither is in `shared/` so this is a pure-Python rename. → **4.2** |
| `github/__init__.py` (the re-export facade) | P3 | `github/__init__.py` re-exports ~40 symbols from `auth`/`engagement`/`objectives`/`plans`/`prs`/`reviews`/`workflows`, creating a second import path for each (`perk.github.X` *and* `perk.github.plans.X`). dignified-python's "one canonical import path / no re-exports" rule is in tension here. | **Keep** — this is a deliberate, documented gateway facade (the module docstring spells out the issue-tier-demotion contract and the source-scan test that enforces reaching the issue tier through the resolver). Record as a *conscious, justified* exception, not a defect to fix. No action. → (none — documented exception) |
| `backends/linear_backend.py` payload-access sites (idiom rider) | P3 | Throughout the GraphQL methods, single-use locals are destructured from payload dicts immediately before one use (the `issue.get("description")` → local → one-use pattern). Mild declare-close-to-use / single-use-destructuring drift, but pervasive enough to note. | Fold into the 2.1 split + 3.1 typing pass — as payloads gain typed accessors, inline the single-use reads at their call site. Low-value on its own; rides the structural work. → **2.1 / 3.1** |
| `cli/commands/**` (command-impl idiom rider) | P3 | Across the 71 command modules, the `_*_impl` functions carry occasional declare-far-from-use locals (a value computed early, used after a branch). No single egregious site; a diffuse pattern. | Opportunistic cleanup during the 4.2 sweep — inline at use site where it improves readability; do not churn. → **4.2** |

### 4.4 Correctness

*Genuine edge-case findings surfaced during the read. The audit does not pre-invent bugs; the
green suite + `ty` already catch the obvious class. Findings here are latent/edge hazards.*

| Anchor | Sev | Observation | Remediation |
| --- | --- | --- | --- |
| `github/reviews.py:_nodes` (None-safe walker) | P3 | `_nodes(obj, *path)` is robustly None-safe (`(cur or {}).get(...)`) and filters non-dict nodes — **correct**, recorded as a *clean* anchor proving the parse layer is defensive. The latent hazard is elsewhere: parse helpers that index `payload["data"]["repository"]…` without the same None-guard would `KeyError` on a partial/error payload. | During 4.1, audit each `github/*` parse helper for the same None-safety `_nodes` already has; where a helper does raw chained `["…"]` indexing on a GraphQL payload, route it through `_nodes`/`.get(...)`. Behavior-preserving hardening; no contract change. → **4.1** |
| `substrate/git.py:detect_trunk_branch` | P3 | The `try/except GitError: pass` / `continue` here is the **correct** EAFP pattern (the git probe *is* the authoritative existence test — LBYL would race) — recorded as a clean anchor, not a defect. It is the right template for the fail-open boundaries below to be measured against. | No change. Anchored as the reference "good" boundary for §4.5. → (none) |

> **Correctness posture.** The exhaustive sweep (4.1 + 4.2) is where additional P1/P2 correctness
> findings will surface as the reader touches each payload-access and boundary site. This section is
> deliberately short: a green `ty` + the test suite already eliminate the obvious bug class, and the
> audit refuses to manufacture fiction. The two anchors above establish the *shape* (an unguarded
> payload access; a fail-open that should report) the remediation nodes watch for.

### 4.5 Exception handling / LBYL

*LBYL-vs-EAFP fit, exception chaining (`from`), and — the highest-value lens here — error
boundaries that **report** vs. silently **swallow**. dignified-python: error boundaries report,
never silent.*

The tree has **15 `except Exception` sites** and a handful of narrower `except …: pass`/`continue`
swallows. Most are *deliberate, well-commented* fail-soft/fail-open boundaries — those are
**correct** and recorded as clean. The findings are the few that swallow without reporting.

| Anchor | Sev | Observation | Remediation |
| --- | --- | --- | --- |
| `backends/linear_backend.py:LinearIssueBackend` PR-attachment helper (`except (IssueBackendError, GitHubError, ValueError): pass`) | P2 | A `pass` swallow with **no stderr note** — if attaching the GitHub PR link to the Linear issue fails, the failure is invisible. dignified-python: an error boundary should *report* (even non-fatally) rather than silently drop. Contrast the well-behaved fail-soft sites in `linear_agent.py`/`run_report.py` which all emit a stderr note. | Convert to a fail-soft-**with-report** boundary: keep it non-fatal but emit a one-line stderr note (matching the `linear_agent.py` `except Exception as exc:  # fail-soft` convention that logs `exc`). Behavior-preserving for the happy path; adds observability. → **4.1** |
| `backends/linear_backend.py` node-status mirror (`except IssueBackendError: pass`) | P3 | Same class — a silent `pass` around the node-status mirror write. The *adjacent* project-lifecycle nudge correctly uses `with suppress(IssueBackendError)` (idiomatic, intentional). The bare `pass` is the odd one out. | Either align with the `suppress(...)` idiom used two lines below, or add a stderr note if the mirror failure is worth surfacing. Consistency fix. → **4.1** |
| `run/launch.py:_sweep_stale_pi_agent_locks` (`except OSError: pass`) | P3 | `except OSError: pass` around `lock.unlink(missing_ok=True)`. This is a best-effort cleanup of pi's global agent-lock dir; swallowing is *defensible* (the whole function is opportunistic). Borderline — recorded for the reader to confirm intent. | Keep, but add a terse comment stating the swallow is intentional (the cleanup is best-effort), matching the self-documenting style of `detect_trunk_branch`. Or leave as-is. Low priority. → **4.2** |
| `cli/commands/**` fail-open `except Exception as exc:` boundaries (land_cmd, save_cmd, reconcile_cmd, create_cmd) | P3 | The ~10 `except Exception as exc:  # fail-open: …` sites in the CLI command layer are **correct** — each carries an explicit comment stating *why* the boundary is fail-open (status updates / objective tracking / learn consumption never block the primary operation) and most surface `exc`. Recorded as the **reference good pattern**, not a defect. | No change. Audited and verified clean — they model the report-don't-swallow discipline. The §4.5 P2/P3 findings above are the deviations from *this* standard. → (none) |
| `cli/commands/learn/__init__.py` & `cli/commands/plan/__init__.py` (`except (RegistryError, FileNotFoundError, StopIteration): pass`) | P3 | A narrow, typed `pass` swallow in the alias-resolution helper. The exception set is precise (not broad `Exception`) and the swallow has a clear meaning ("no active plan/learn → no alias"). Borderline-clean; the precise exception tuple is the saving grace. | Confirm intent with a one-line comment during 4.2 if not already obvious from context. Very low priority. → **4.2** |

## 5. Findings → remediation roadmap

### 5.1 Mapping table (finding cluster → owning node)

| Finding cluster | Dimension(s) | Target node |
| --- | --- | --- |
| `linear_backend.py` decomposition (7 classes, 3579 lines; longest methods) | Organization (§4.1) | **2.1** (verbatim package split) / **3.1** (long-method extraction — reconciled, see §4.1 outcome) |
| `convergence/init.py` + `doctor.py` taming (long multi-concern modules; package-list `cast`s) | Organization (§4.1), Type-literacy (§4.2) | **2.2** |
| `objective.py` split (parse/render/graph/manifest) + parse-layer `Any` tightening; `launch.py` decomposition | Organization (§4.1), Type-literacy (§4.2) | **2.3** |
| Linear GraphQL type-literacy (`dict[str, object]`×56, `cast`×9, zero `TypedDict`; consolidate on `_require_*`) | Type-literacy (§4.2), idiom rider (§4.3) | **3.1** |
| backends/ + github/ sweep: `_graphql`/`_nodes` Any-leak narrowing; payload None-safety hardening; the two report-don't-swallow boundary fixes | Type-literacy (§4.2), Correctness (§4.4), Exception/LBYL (§4.5) | **4.1** |
| cli/ + run/ + state/ + substrate/ sweep: duplicate `Severity` rename; `save_cmd` residual extraction; registry/cache typing polish; borderline-swallow comments | Idiom (§4.3), Type-literacy (§4.2), Exception/LBYL (§4.5) | **4.2** |
| tests/ dignity pass: fake-backend duplication, very large test files, helper typing | Organization (§4.1), Type-literacy (§4.2) | **4.3** |
| `github/__init__.py` re-export facade; `detect_trunk_branch`/`_nodes` clean anchors; CLI fail-open boundaries | Idiom (§4.3), Correctness (§4.4), Exception/LBYL (§4.5) | **none (documented/clean)** |

### 5.2 Roadmap reconciliation notes (prescriptive — input to the post-land `/objective-reconcile`)

The findings **broadly confirm the existing Phase 2–4 roadmap** — the node boundaries match the real
seams found in the tree. Concrete recommendations for the reconcile pass:

1. **Keep 2.1 as the linchpin.** `linear_backend.py` is, by a wide margin, the deepest cohesion
   liability (3579 lines, 7 classes, the 3 longest methods in the tree). It correctly gates 3.1
   (typing) and 4.1 (sweep) via `depends_on`. No change — the audit validates the dependency.

2. **3.1 scope is right but should explicitly own the `_require_*` consolidation, not just
   `TypedDict` evaluation.** The audit's strongest type-literacy signal is *56 `dict[str, object]` +
   9 `cast` consolidated onto an under-used 3-helper family* — the deliverable is "route through and
   extend `_require_*`", with `TypedDict` as a *secondary, evaluate-don't-force* option.
   *Recommend:* sharpen the 3.1 node description to foreground `_require_*` consolidation (the
   objective prose already cautions "evaluate, do not blanket-convert" — keep that).

3. **Fold the `github/` GraphQL Any-leak (`_graphql`/`_nodes`) explicitly into 4.1.** It is the same
   `dict[str, Any]` parse-layer pattern as the Linear payloads but lives outside 2.1/3.1's
   backends-only scope. 4.1 already names github/ — *recommend* the reconcile note that 4.1's
   type-literacy work includes narrowing the github GraphQL parse helpers off `Any`, so it isn't
   lost between the Linear-scoped 3.1 and the idiom-scoped 4.1.

4. **No new node needed; one cross-cutting micro-cluster spans 4.2.** The duplicate `Severity` enum
   (`registry` vs `objective_drift`) is a pure rename touching two `substrate`/root modules — it
   sits naturally in 4.2's `substrate/` scope. No roadmap change; recorded so 4.2 doesn't miss it.

5. **Correctness (§4.4) stays distributed across 4.1/4.2, not its own node — confirmed.** The audit
   found **no** standalone P1 correctness bug warranting a dedicated node; the latent hazards
   (unguarded payload access, silent boundaries) are best fixed *in situ* during the same-file sweep.
   The roadmap's choice to thread correctness through the dimension sweeps (rather than a separate
   "fix bugs" node) is the right call. *Recommend:* the reconcile note should state explicitly that
   §4.4 produced no P1 — so a future reader doesn't expect a correctness node that was deliberately
   not created.

6. **4.3 (tests) lands last — confirmed; flag the `xdist_group` constraint.** The test-file splits
   must respect the build-once `xdist_group` pinning (shared fixtures pinned to one worker).
   *Recommend:* the 4.3 node description gain a one-line caveat that test-module splitting must not
   break the `-n auto --dist loadgroup` grouping.

## 6. Verification

- Every finding carries all schema fields (anchor, dimension, severity, observation, remediation,
  target node) — the §4 tables + §5 mapping.
- Every anchor resolves to a real `file:symbol` (verified against the tree during the audit pass;
  no line numbers used).
- Severities are applied consistently per the §2 scale (P1 = bug/risk, P2 = dignity debt, P3 =
  polish). The audit found **no P1** — recorded honestly rather than inflated.
- The §3 coverage map gives **every** module group an explicit verdict (findings / clean).
- §5 maps every finding cluster to a node and carries actionable reconciliation notes.
- `just ci` stays green — no Python touched (this is a `docs/planning/` doc; no markdown linter is
  wired, so it skips all code hooks). A trivial guardrail, not the substantive check.
