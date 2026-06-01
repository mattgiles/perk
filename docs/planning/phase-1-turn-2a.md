# Phase 1 · Turn 2a — GitHub plan write (the Python/worker half)

Detailed execution plan for **P1.T2a** of [phase-1-plan.md](../phase-1-plan.md). T2a builds the
**first GitHub *mutation*** in perk (Phase 0's gateway was read/verify only): the **cold/worker
door** that creates a plan as a GitHub issue with the **header/body split**, and — more durably — it
**establishes the write-safety conventions** (`--dry-run`, idempotency, error-translation) that
`submit`/`land` reuse. It is the first **real consumer** of the Phase-0 `PerkContext` +
`require_github` DI seam.

> **Scope discipline.** T2a is **Python-plane only**. It ships the `perk/github.py` mutation ops, a
> `perk/plan.py` storage/metadata-block module, and one `require_github` consumer command
> (`perk plan-save`) with a `--json` supervisor surface. It writes **`github.plan` only** — it
> **emits** the provider-agnostic plan-ref but **does not** write `cache.plan-ref` or any session
> entry (**all of `cache.plan-ref` is T2b**). It is the *cold/worker* save door; the **warm
> in-session `/plan-save` tool is T3** (a native TS gateway — T2a's twin per §8.4, **not** a thing
> T3 shells). No TS, no `cache.plan-ref`, no session linkage, no plan-authoring enforcement (the
> no-line-numbers rule is a T3 skill concern — T2a stores verbatim).

---

## 1. Objective & the gate

**Goal.** Stand up perk's GitHub *write* plane around the single most reusable storage idea in the
prior art — the **two-part header/body plan** + the **provider-agnostic ref** (PRIOR_ART §2) — and
lock the three write-safety conventions once, in Python, where the CliRunner test surface is richest,
so every later mutation (`submit`/`land`) inherits them.

**The dual-gateway framing (why this is the *Python* half).** §8.4 is "one contract, implemented
**once per plane**, no shared module." T2a is the **worker/cold** gateway (the §8.4 "Python CLI
(init/worker)" side); the **in-session warm** gateway is T3 (TS). The `create_plan_issue` operation
is deliberately implemented twice across the planes — that is the no-coupling boundary
([cli-vs-pi.md](../cli-vs-pi.md) §3), and T2a's conventions are what the TS twin mirrors. The
extension never shells `perk` (confirmed: it shells nothing today).

**Hard gate (must pass to land T2a).** Via `scripts/verify-p1-t2a.sh` on a fresh `perk init`-ed repo,
**fully offline** (`gh` is never invoked):

1. **`perk plan-save --dry-run --plan-file <tmp>` exits 0** and prints the composed plan
   **header + body** without touching `gh` (the dry-run convention is real, not a stub).
2. **`perk plan-save --json --dry-run …` emits one well-formed object** `{ success, error_type,
   message, … }` to stdout (the supervisor surface; human text stays on stderr).
3. **Exit-code discipline holds** — missing `--plan-file` ⇒ exit 1 (`invalid_input`); run outside a
   repo ⇒ exit 2 (`not_a_repo`); unauthed (live path) ⇒ exit 1 (`github_unauthed`).
4. **The metadata-block engine round-trips** — `find_metadata_block(render_metadata_block(k, d), k)
   == d` (proven by the unit suite the gate runs).
5. **The registry `save` stage now declares `writes: [github.plan]`** (and the registry self-check
   still passes).
6. **The pytest suite is green** (the new `tests/test_plan.py` + `tests/commands/test_plan_save.py`
   + the extended `tests/test_github.py`).

`just verify` runs t1…t7 + p1-t1 **+ p1-t2a**; `just ci` stays green.

---

## 2. Grounding & doc lineage (what governs T2a)

- **The phase plan.** [phase-1-plan.md](../phase-1-plan.md) §P1.T2 → **T2a**: *create the plan issue
  with the header/body split (foundational #2 / PRIOR_ART §2); establish the gateway's write-safety
  conventions — `--dry-run`, idempotency, error-translation — that submit/land reuse; the first
  GitHub mutation; the first real `PerkContext` + `require_github` consumer; write ops follow the
  `GitHubError → UserFacingCliError` boundary.* T2a discharges that verbatim.
- **The storage model.** [PRIOR_ART.md](../PRIOR_ART.md) §2 (two-part header/body, provider-agnostic
  ref, staged field population, idempotent save, no-line-numbers) and §12.1 (lean toward the *newer*
  "single canonical body + workflow-created PR" simplification). The header/body **format** is erk's
  metadata-block shape ([metadata-blocks reference](../../.prior-art/erk/docs/learned/architecture/metadata-blocks.md)),
  perk-namespaced.
- **GitHub-write first principles (mined for this turn).** REST `gh api` over porcelain
  ([github-api-rate-limits](../../.prior-art/erk/docs/learned/architecture/github-api-rate-limits.md)),
  large bodies via `-F body=@file`
  ([github-cli-comment-patterns](../../.prior-art/erk/docs/learned/ci/github-cli-comment-patterns.md) /
  [subprocess-wrappers](../../.prior-art/erk/docs/learned/architecture/subprocess-wrappers.md)),
  command-level idempotency keyed on the header id
  ([session-deduplication](../../.prior-art/erk/docs/learned/planning/session-deduplication.md)),
  search/index eventual consistency
  ([github-commit-indexing-timing](../../.prior-art/erk/docs/learned/ci/github-commit-indexing-timing.md)),
  AND-semantics label filters
  ([github-graphql-label-semantics](../../.prior-art/erk/docs/learned/architecture/github-graphql-label-semantics.md)),
  minimal label taxonomy ([label-scheme](../../.prior-art/erk/docs/learned/planning/label-scheme.md)),
  union-vs-exception by caller behavior
  ([discriminated-union-error-handling](../../.prior-art/erk/docs/learned/architecture/discriminated-union-error-handling.md) /
  [not-found-sentinel](../../.prior-art/erk/docs/learned/architecture/not-found-sentinel.md)), and
  deferred transient-retry
  ([github-api-retry-mechanism](../../.prior-art/erk/docs/learned/architecture/github-api-retry-mechanism.md)).
- **The division of labor.** [cli-vs-pi.md](../cli-vs-pi.md) §2.1 (the extension owns *in-session*
  mutations → that is T3, not T2a), §3 (no in-process coupling; coordinate through durable
  state/launch/schema), §3.2 (the agent-facing JSON surface dissolves — `--json` survives **only**
  for the supervisor), §4.4 (the `save` stage cold door is "usually warm," but it exists — that is
  what T2a builds).
- **CLI conventions.** [python-cli-guidelines.md](../python-cli-guidelines.md) §1 (the three-layer
  decorator → `require_*` → `_impl` shape — its canonical example is *literally* `save_plan` +
  `require_github`), §5 (errors: `UserFacingCliError` for expected, `RuntimeError` never for user
  errors), §8.2 (the narrow machine surface: `--json` + stable exit codes only for supervisors),
  §9 (CliRunner + `PerkContext.for_test`).
- **The contract under amendment.** [contracts.md](../../shared/contracts.md) §8.4 — author the
  `create_label`/`create_plan_issue` **payloads** (were "named only, deferred to Phase 1") and pin
  the concrete plan-header fields + the `perk:plan` label. The state-tier layout (§8.1) and the
  `run_id` correlation role (§8.2) are pre-existing and unchanged.
- **Repo conventions in force.** uv + ruff + ty; dignified-python (no `from __future__ import
  annotations`; `StringEnum` over bare strings where a closed set exists; explicit `check=` on every
  subprocess; LBYL via `Ensure`). One subprocess wrapper (`github._run`).

---

## 3. Design decisions (locked)

- **D1 — T2a is the Python/worker half of the §8.4 dual gateway.** The cold save door
  (`perk plan-save`); the warm in-session twin is T3 (native TS). `create_plan_issue` is implemented
  once per plane by design; no shared module, no extension→`perk` shelling.
- **D2 — Command name: `perk plan-save`** (top-level, hyphenated — mirrors the warm `/plan-save` and
  erk's own verb). A `plan` Click *group* would collide with the registry-generated `perk plan`
  launcher (the plan-stage cold door); a `plan` group / launcher-coexistence is deferred to Phase 2
  when read verbs (`plan list/view/log`) arrive. File: `perk/cli/commands/plan_save_cmd.py` (flat,
  matching the existing layout).
- **D3 — Three write-safety conventions, established here, reused by submit/land:**
  - **`--dry-run`:** every mutation op takes `dry_run`; when true it returns the *planned* action
    and **never shells `gh`**; the command prints the plan (`dim`/`bright_black` per guidelines §7.2).
  - **REST over porcelain + large-body via file (erk's hardest-won write lesson).** Use `gh api
    repos/{owner}/{repo}/…` (REST — its own rate-limit quota), **never** porcelain
    `gh issue create`/`gh pr create` (GraphQL, a *separate, often-exhausted* quota); `gh api` fills
    `{owner}/{repo}` from repo context. Plan bodies are long, so pass the body as
    **`-F body=@<tmpfile>`** (a `mktemp`→write→call→`rm` helper), never inline — inline hits ARG_MAX
    (~2 MB) and GitHub abuse detection at ~3,500 chars. (github-api-rate-limits /
    github-cli-comment-patterns.)
  - **Idempotency — keyed on `run_id`, via list-by-label, create-then-record.** An existing open
    `perk:plan` issue whose **parsed `plan-header` `run_id`** matches is **returned, not duplicated**
    (the §8.2 cold correlation key, from `PERK_RUN_ID`/`--run-id`). Discover it with the **list**
    endpoint (`gh api …/issues?labels=perk:plan&state=open`) + a client-side header match — **not**
    `--search`, whose index is eventually consistent (a just-created issue may not surface). Record
    state **only after** a successful create (session-deduplication's rule). `create_label` treats
    "already exists" (HTTP 422) as success. Coherent split: cold = `run_id`, warm T3 =
    `pi_session_id`. No `run_id` ⇒ no dedup. *Limit: two near-simultaneous cold saves in one index
    window may still race — acceptable for the MVP.*
  - **Error model — by caller behavior (erk's union-vs-exception rule).** **Lookups** the caller
    branches on (`find_plan_issue`) return a **`T | None` / sentinel**, never raise. **Mutations**
    whose only failure handling is terminate-with-message (`create_plan_issue` / `add_issue_comment`
    / `create_label`) **raise a structured `GitHubError`** (success returns the data — number/url);
    the **command boundary** catches it → `UserFacingCliError`. (Phase-0 reads keep their result
    dataclasses — init/doctor *branch* on them to report non-fatally.)
- **D4 — The T2a↔T2b seam: T2a writes `github.plan` and *emits* the plan-ref; it never touches
  `cache.plan-ref` or a session entry.** All of `cache.plan-ref` (the local cache file **and** the
  `active_plan_ref` session-entry linkage rebuilt on `session_start`/`session_tree`) is T2b. T2a
  fills `save.writes: [github.plan]`; T2b appends `cache.plan-ref`.
- **D5 — Reuse the one subprocess wrapper.** New mutations route through `github._run` (already
  `check=False`, captured, `timeout=`, `FileNotFoundError`/`TimeoutExpired` → `GitHubError`). Writes
  get a **longer timeout** (issue create is slower than a status read) — parameterize `_run`'s
  timeout, default unchanged for reads. **Transient-network retry** (exponential backoff for
  timeouts/connection-resets, *never* rate-limits/auth) stays **deferred** (§10) but slots in at this
  one wrapper when the headless fleet lands — erk's lesson: retries belong in the gateway layer, not
  call sites (github-api-retry-mechanism).
- **D6 — No plan-authoring enforcement.** The no-line-numbers rule and authoring judgment live in the
  **T3 planning skill**; T2a stores the plan body **verbatim**.

---

## 4. Deliverables

| Path | What |
|---|---|
| `perk/plan.py` | The metadata-block engine (`render_metadata_block` / `find_metadata_block`), header/body composition (`compose_plan_header` / `compose_plan_body`), the plan-ref struct + `PlanHeader` dataclass, and `run_id`-keyed idempotency helpers. No Click, no I/O — pure + trivially testable. |
| `perk/github.py` | New **REST** mutation ops: `create_label`, `create_plan_issue`, `add_issue_comment`, `find_plan_issue` (+ success dataclasses `PlanIssue`/`Label`/`CommentResult`; `find_plan_issue → PlanIssue \| None`). A `-F body=@file` body-file helper; parameterized `_run` timeout. |
| `perk/cli/commands/plan_save_cmd.py` | `perk plan-save` — three-layer Click; `--plan-file`/`--run-id`/`--dry-run`/`--json`; `require_github` consumer; the `GitHubError → UserFacingCliError` boundary; the supervisor `--json` + exit-code surface. |
| `perk/cli/cli.py` | Register `plan_save`. |
| `shared/contracts.md` | Amend §8.4: author the `create_label`/`create_plan_issue` payloads; pin the plan-header fields + `perk:plan` label; update the status note. |
| `shared/registry.yaml` | Fill `save.writes: [github.plan]` (`requires`/`reads` stay `[]`). |
| `tests/test_plan.py`, `tests/test_github.py` (extend), `tests/commands/test_plan_save.py` | The unit + CliRunner suites. |
| `scripts/verify-p1-t2a.sh` + `justfile` | The offline hard gate; appended to `just verify`. |

No TS, no `extension/` change, no `cache.plan-ref`/session work.

---

## 5. The storage module (`perk/plan.py`)

**Metadata-block format** (erk's shape, perk-namespaced — human-readable on GitHub, machine-parseable):

```
<!-- perk:metadata-block:plan-header -->
<details><summary><code>plan-header</code></summary>

```yaml
run_id: 01J…
lifecycle_stage: planned
branch: null
pr: null
created: 2026-05-30T…Z
objective_id: null
```

</details>
<!-- /perk:metadata-block:plan-header -->
```

- `render_metadata_block(key, data) -> str` and `find_metadata_block(text, key) -> dict | None` are
  an **inverse pair** (round-trip tested). YAML body, HTML-comment delimiters, collapsible
  `<details>`. No custom regex beyond the delimiter scan (metadata-blocks best-practice 1).
- **Two-part composition** (PRIOR_ART §2):
  - **Issue body** = the `plan-header` block (compact, queryable **without** fetching comments).
  - **First comment** = the `plan-body` block — the full plan markdown in a collapsible `<details>`.
- **Plan-header fields (the minimal observably-distinct set, Q8 consolidation):** `run_id`,
  `lifecycle_stage` (`planned`; Q8 collapses `planned → impl`, post-states derived from PR),
  `branch: null`, `pr: null` (staged — populated at submit, PRIOR_ART §2), `created`,
  `objective_id: null` (Phase 2). Modeled as a `PlanHeader` dataclass; `lifecycle_stage` a
  `StringEnum`.
- **Plan-ref struct** (§8.4, provider-agnostic): `{ provider: "github", pr_id: <issue-number-as-
  string>, url, labels: ["perk:plan"], objective_id: null }`. `pr_id` is a **string** (allows
  non-numeric ids); during planning it carries the **issue** id, with `branch`/`pr` staged null.
  T2a **emits** this (in `--json`); **T2b** materializes it into `cache.plan-ref`.

## 6. The gateway mutation ops (`perk/github.py`)

The first mutations; all route through `_run`, use **REST `gh api`** (never porcelain), and follow D3.

- `create_label(name, *, color, description, repo_root, dry_run) -> Label` — `gh api
  repos/{owner}/{repo}/labels -X POST -f name=… -f color=…`; **HTTP 422 "already exists" ⇒
  `Label(ok=True)`** (lazy + idempotent). The `perk:plan` label is created here, on first save
  (Q9 lazy-create).
- `find_plan_issue(*, run_id, repo_root) -> PlanIssue | None` — `gh api
  repos/{owner}/{repo}/issues?labels=perk:plan&state=open` (the **list** endpoint, not `--search`),
  then a client-side `find_metadata_block` `run_id` match. Returns `None` when no match — a lookup
  the caller branches on, **never raises**.
- `create_plan_issue(*, title, body, labels, repo_root, run_id, dry_run) -> PlanIssue` —
  idempotency first (`find_plan_issue(run_id)` hit ⇒ return it). Else `gh api
  repos/{owner}/{repo}/issues -X POST -f title=… -F body=@<tmp> -f 'labels[]=perk:plan'
  --jq '{number, url: .html_url}'`. Returns `PlanIssue(number, url)` on success; **raises
  `GitHubError`** on failure.
- `add_issue_comment(*, issue, body, repo_root, dry_run) -> CommentResult` — `gh api
  repos/{owner}/{repo}/issues/{n}/comments -X POST -F body=@<tmp>` (the plan-body first comment).
- **Body-file helper** — composed header/body written to a `mktemp` file, passed `-F body=@path`,
  removed in a `finally`. Never inline (D3: ARG_MAX + abuse detection).
- **Result/raise split (D3):** `find_plan_issue` returns `PlanIssue | None`; the
  create/comment/label mutations return their frozen success dataclass (`PlanIssue{number, url}`,
  `Label`, `CommentResult`) and **raise `GitHubError`** for *both* infra (gh-missing/timeout via
  `_run`) and operation (non-2xx) failures. `dry_run` returns a planned success type without shelling.
- **Label-query guardrail:** query by the **single** `perk:plan` label — GitHub label filters are
  **AND**, so never combine type labels in one query (github-graphql-label-semantics); note that
  (re)labeling bumps an issue's `updated_at` (a sort-order side effect) if idempotent updates ever
  re-label.

## 7. The command (`perk plan-save`)

Three layers (guidelines §1): thin callback → `require_github` → `_plan_save_impl(*, …)`.

- **Flags:** `--plan-file PATH` (the plan markdown; `click.Path(exists=True)`), `--run-id TEXT`
  (default `None`; else `PERK_RUN_ID` from env), `--title TEXT` (default `None` → derive from the
  plan's first `# ` heading), `--dry-run`, `--json`.
- **Plan source priority** (PRIOR_ART §2): explicit `--plan-file` → (later) session scratch dir →
  mtime fallback. T2a implements **`--plan-file` only**; the scratch/mtime fallbacks are noted as
  T3/Phase-2 (the warm tool supplies the body in-session).
- **Flow:** `require_github(ctx)` (gate; raises `github_unauthed` → exit 1) → read + compose
  header/body → `create_label("perk:plan", …)` → `create_plan_issue(…)` (idempotent) →
  `add_issue_comment(…, plan-body)` → emit the plan-ref. The mutations **raise `GitHubError`** on
  failure; the command catches it → `UserFacingCliError` (guidelines §5).
- **Supervisor surface (§8.2 / front-matter obligation):** human text → stderr
  (`user_output`/Rich); `--json` → stdout, one object `{ success, error_type, message, plan_ref,
  issue: { number, url }, dry_run }`. **Exit codes:** `0` saved · `1` invalid input
  (`invalid_input` missing/empty plan-file) / unauthed (`github_unauthed`) / op failure
  (`github_error`) · `2` `not_a_repo`. (Mirrors the init/doctor exit-code discipline, §8.5/§8.6.)
- **`--doors` legality:** the `save` stage's `doors` already encodes `warm: true, cold_local: true,
  cold_remote: false`; T2a is the cold_local consumer and changes no door field.

## 8. Contract & registry amendments

- **`shared/contracts.md` §8.4:**
  - Move `create_label` + `create_plan_issue` from "named only" to **authored**, with payloads:
    `create_label{ name, color, description } -> { ok, error }`; `create_plan_issue{ title, body,
    labels[], run_id } -> { ok, number, url, error }`; note `add_issue_comment` (plan-body) +
    `find_plan_issue` (idempotency). Keep `create_pr`/`mark_pr_ready`/`merge_pr`/`resolve_review_
    threads` deferred (their stages haven't landed).
  - Pin the **plan-header field set** (§5) and the **`perk:plan` label** (§8.4 said these "land with
    `/plan-save` in Phase 1").
  - Update the status note: "**(T2a):** the §8.4 *plan-write* mutations are implemented in the
    Python plane (`perk/github.py` + `perk/plan.py`) — the cold/worker save door; the TS in-session
    twin lands in T3."
- **`shared/registry.yaml`:** `save.writes: [github.plan]` (`requires`/`reads` stay `[]`, filled
  when a real consumer reads them).

## 9. Tests + the verify gate

- **`tests/test_plan.py`:** `render`↔`find` round-trip (incl. absent block → `None`, malformed →
  `None`); header/body composition; `PlanHeader` defaults + `lifecycle_stage` enum; plan-ref struct
  shape; `run_id` idempotency-key extraction.
- **`tests/test_github.py` (extend):** `create_label` created / 422-exists (ok) / other-error
  (**raises**); `create_plan_issue` success (number/url) / non-2xx (**raises** `GitHubError`) /
  gh-missing (**raises**) / `dry_run` (no shell, planned payload) / idempotent (`find_plan_issue`
  hit ⇒ returned, **no POST**); `find_plan_issue` match / no-match (`None`); the body-file helper
  writes `-F body=@…` (asserted on the captured argv), never inline. All via `monkeypatch` on
  `subprocess.run` (the existing `_Proc` fake).
- **`tests/commands/test_plan_save.py`:** CliRunner + `PerkContext.for_test` — success (monkeypatched
  ops); unauthed → exit 1 + `github_unauthed`; missing `--plan-file` → exit 1; `not_a_repo` → exit 2;
  `--dry-run` (no `gh`); `--json` object shape; `GitHubError` → styled exit-1; idempotent (existing
  issue returned, no duplicate create).
- **`scripts/verify-p1-t2a.sh`** (offline, fresh init'd repo, mirrors the existing verify style):
  (1) `perk plan-save --dry-run --plan-file <tmp>` exits 0 + prints header+body; (2) `--json
  --dry-run` emits a well-formed object; (3) missing-file → exit 1; (4) the registry self-check
  passes with `save.writes` filled; (5) the pytest subset is green. Appended to `just verify` after
  `verify-p1-t1.sh`. **No network, no `gh`.**

## 10. Explicitly out of scope for T2a (pointers)

- **`cache.plan-ref`** (the local cache file) **and the `active_plan_ref` session linkage / rebuild**
  — **T2b** (TS plane). T2a only *emits* the ref.
- **The warm `/plan-save` terminating tool**, dual-surface tool return, `terminate: true`,
  `executionMode: "sequential"`, the planning skill, the no-line-numbers enforcement — **T3** (TS).
- **`create_pr`/`mark_pr_ready`/`merge_pr`/`resolve_review_threads` payloads** — their stages
  (`submit`/`land`/Phase-2 `address`); named-only in §8.4 until then.
- **Transient-network retry infra** (exponential backoff, injectable time) — Phase 3 / the headless
  fleet; recorded as a principle (D5), slots in at the one `_run` wrapper. T2a does *not* build it.
- **Push-permission LBYL** — `require_github` gates on *auth* only; a missing-push-right surfaces as
  the REST error → `UserFacingCliError`. Strengthening `require_github` with a `can_push` check
  (`check_repo_access` already computes it) is a later sharpening, not T2a.
- **A `plan` command group / `plan list/view/log` read surface** — Phase 2 (resolves the `perk plan`
  launcher collision then).
- **Scratch-dir / mtime plan-source fallbacks** — T3/Phase-2 (warm supplies the body in-session).
- **Remote target (`--remote`)** — Phase 3; `cold_remote: false` holds for `save`.

## 11. Definition of done

The six gate checks in §1 pass via `scripts/verify-p1-t2a.sh` on a fresh init'd repo **offline**;
`perk plan-save` is the first `require_github` consumer; the write-safety conventions
(`--dry-run`, REST `gh api` + `-F body=@file`, `run_id` list-by-label idempotency, the
lookups-return / mutations-raise → `UserFacingCliError` error model) are established and tested;
`github.plan` writes are real (gated only by the offline dry-run + monkeypatched unit/CliRunner
suites); §8.4 is amended and `save.writes` filled; `just ci` and `just verify` (t1…t7 + p1-t1 +
p1-t2a) are green. T2a lands; **T2b can now materialize the emitted plan-ref into `cache.plan-ref`,
and T3 can build the warm twin against the locked conventions.**

---

## 12. Outcomes (recorded on landing)

**Status: landed, all green.** `just verify` runs **t1…t7 + p1-t1 + p1-t2a, all PASS**; `just ci`
green — ruff + ruff-format + ty + biome + tsc clean; **109 pytest** (80 prior + 29 new) **+ 17
`node:test`**. The whole T2a gate runs **offline** (the dry-run path + monkeypatched unit/CliRunner
suites never invoke `gh`).

**Built (matches §4–§7):**
- `perk/plan.py` — the metadata-block engine (`render_metadata_block`/`find_metadata_block` inverse
  pair, `render_plan_body`), `PlanHeader` (+ `LifecycleStage` `StrEnum`) / `PlanRef` dataclasses, the
  `perk:plan` label constants, and the `run_id`/title/`now_iso` helpers. Pure, no I/O.
- `perk/github.py` — REST mutation ops `create_label` / `find_plan_issue` / `create_plan_issue` /
  `add_issue_comment` (+ `Label`/`PlanIssue`/`CommentResult`), a `_body_file` `-F body=@file` helper,
  and a parameterized `_run` timeout (`_READ_TIMEOUT=15` / `_WRITE_TIMEOUT=30`).
- `perk/cli/commands/plan_save_cmd.py` + registration — `perk plan-save`, the first `require_github`
  consumer; three-layer; supervisor `--json` + exit codes (0/1/2).
- `shared/contracts.md` §8.4 — authored the four mutation payloads, the plan-header field set, the
  `perk:plan` label + AND-semantics note, and the P1.T2a status block. `shared/registry.yaml` —
  `save.writes: [github.plan]`.
- `scripts/verify-p1-t2a.sh` + `justfile`; tests `tests/test_plan.py`, extended `tests/test_github.py`,
  `tests/test_plan_save.py`.

**Deviations from the plan (recorded, not retro-edited):**
- **Tests are flat (`tests/test_plan*.py`), not `tests/commands/`** — matches the existing perk test
  layout (all suites live at `tests/` root); the doc's `tests/commands/` was erk-guideline-shaped.
- **`--dry-run` bypasses `require_github`** (§7 had it gating unconditionally). Dry-run composes +
  prints locally and needs neither auth nor network — required for the offline gate; the live path
  still gates. Also added: a one-line `error_type="not_a_repo"` to `require_repo` (context.py) so the
  supervisor surface yields exit 2 — a clean global improvement, no test depended on the old raise.
- **`--plan-file` is `click.Path` *without* `exists=True`** (§7 sketched `exists=True`): plan-file
  problems (omitted / missing / empty) are validated via `UserFacingCliError` so they all yield the
  **invalid_input exit 1** the gate wants, rather than Click's usage-error exit 2.
- **`find_plan_issue` raises `GitHubError` on an infra/query failure** (returns `None` only for a
  genuine no-match) — honoring the prior-art "don't catch-to-return-None" rule over the doc's looser
  "never raises"; the not-found contract (returns `None`) is intact.

**Contract/registry:** §8.4 amended in-turn; `save.writes` filled (`requires`/`reads` stay `[]`). No
TS/`cache.plan-ref`/session work (all T2b).

**Tree at handoff (staged-clean for the user to commit):** new — `perk/plan.py`,
`perk/cli/commands/plan_save_cmd.py`, `tests/test_plan.py`, `tests/test_plan_save.py`,
`scripts/verify-p1-t2a.sh`, `docs/planning/phase-1-turn-2a.md`; modified — `perk/github.py`,
`perk/cli/cli.py`, `perk/cli/context.py`, `tests/test_github.py`, `shared/contracts.md`,
`shared/registry.yaml`, `justfile`, `docs/index.md`.

**Unblocks T2b:** the emitted plan-ref (`--json` `plan_ref`) is ready to materialize into
`cache.plan-ref` + the `active_plan_ref` session linkage; the write-safety conventions are locked for
the T3 warm twin and the submit/land mutations.
