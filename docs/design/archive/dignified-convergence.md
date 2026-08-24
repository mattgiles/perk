# The dignified-Python convergence checklist + per-module friction backlog

> **Status: executed.** The Phase-4 sweeps this doc scoped have all landed — node 4.2
> (core domain, PR #288), node 4.3 (launch/run, PR #305), node 4.4
> (provider/registry/binding, PR #300), node 4.5 (init/doctor/env + misc, PR #313). The §3
> backlog entries are now historical record, and the open rulings were resolved as recorded
> in the Objective #225 node descriptions (each node's prose carries its landed summary).

**Objective #225, Node 4.1.** This doc is the *bounded scope* for the Phase-4 convergence sweeps
(Nodes 4.2–4.5): §1 fixes the checklist every sweep applies, §2 rules on the ruff rules that keep
it enforced, §3 records the per-module friction backlog (one entry per non-CLI `perk/` module,
bucketed by sweep node), §4 records the erk-pattern adoption rulings, and §5 totals the effort and
proposes rebalancing. A sweep implementer should be able to execute their bucket from §3 alone;
where the audit was uncertain, the uncertainty is recorded as an explicit **open ruling** for the
sweep — never silently omitted.

Audit sources: the `dignified-python` skill (core + `references/checklists.md`,
`references/module-design.md`, `subprocess.md`, `references/advanced/*`),
[python-cli-guidelines.md](../first-principles/python-cli-guidelines.md), AGENTS.md's
dignified-python bullet, and the erk prior art in the erk repo (§4). All anchors are
durable (function/class names), never line numbers. The sweeps are **behavior-preserving**: every
backlog item below is a refactor, a mechanical fix, or a recorded verdict — no semantic change.

---

## §1 The convergence checklist

Each axis carries a one-line rationale and an enforcement tier: **ruff-enforceable** (a rule in §2
catches regressions mechanically) or **judgment** (the sweep audits by reading; regressions are
caught in review).

1. **`encoding="utf-8"` on every `read_text`/`write_text`/`open`** (including multiline calls) —
   default encoding is platform-dependent. *ruff-enforceable* (`PLW1514`).
2. **≤4-level indentation; extract helpers beyond that** — deep nesting hides control flow.
   *ruff-enforceable* (`PLR1702`) for block nesting; *judgment* for argument-continuation depth
   (see the §3 nesting verdicts — perk's deep-indent lines are almost all multi-line constructor
   calls, not control nesting).
3. **Import hygiene: module-level absolute imports; inline imports only with a justification
   comment** (cycle / TYPE_CHECKING / conditional feature / *measured* startup cost) —
   import-order surprises and hidden deps. *ruff-enforceable* (`PLC0415`) for placement;
   *judgment* for whether the justification holds.
4. **No single-use destructuring of object fields into locals** — access `obj.field` directly;
   locals earn their name by reuse or by clarifying a genuinely opaque expression. *judgment*.
5. **Properties and magic methods are O(1); I/O gets an explicit method name** — `x.size` must
   never hide a query. *judgment*. **Verdict recorded here (a deliberate relaxation of the
   skill's letter — dignified-python says "Properties Must Be O(1)", full stop):** an O(n) scan
   over a small, already-in-memory list is acceptable in a `@property` when n is bounded and
   there is no I/O —
   this rules `DoctorReport.healthy`/`DoctorReport.exit_code` (`perk/doctor.py`) and
   `InitReport.exit_code` (`perk/init.py`) **acceptable as-is** (n = the check list, ~20 items,
   pure). The line is I/O or unbounded n, not big-O pedantry.
6. **Shallow-module verdicts (keep vs merge)** — a module must pay for its import path with a
   coherent concept, not a line count. *judgment*. Verdicts for the six candidates
   (`output.py`, `_resources.py`, `resume.py`, `run_id.py`, `capabilities.py`, `env.py`) are in
   §3 — **all six are KEEP** (each is one concept with a real cross-module consumer set; merging
   would create grab-bags).
7. **LBYL over exception-as-control-flow; exceptions only at boundaries or when the operation is
   the authoritative test** — branch on cheap precise checks; raise/translate at the CLI/gateway
   boundary. *judgment*. perk's standing error model (codified in `perk/github.py`'s mutation-ops
   banner) is part of this axis: *lookups return `… | None`, mutations raise, callers that branch
   get result dataclasses*.
8. **pathlib everywhere (no `os.path`)** — one path vocabulary. *ruff-enforceable* (`PTH`).
   `os.environ`, `os.execvpe`, `os.chdir` are not path ops and stay (no pathlib equivalent).
9. **Subprocess discipline: explicit `check=` and `timeout=` on every `subprocess.run`, routed
   through one wrapper** — ambiguous failure handling is the classic silent bug. *judgment* (plus
   the §3 tripwire-test item). **Verdict recorded here:** "one wrapper" means **one wrapper per
   process boundary**, not one repo-global utility — `git._run` and `github._run` are the
   sanctioned gateway wrappers; the three standalone sites (`env._node_version`,
   `init._sync_skills`, `run_worker._spawn_worker`) are each a single named wrapper function for
   their one external tool. A repo-global erk-style wrapper is **rejected** (§4 row 1). All nine
   current sites already pass `check=` and a `timeout=` explicitly.

   > **Status: superseded (the proc-primitive consolidation).** The captured-wrapper family
   > grew from two gateway wrappers + three standalone sites to six wrapper functions + three
   > one-off captured sites, and drifted (`git._run` had no spawn arm at all — a missing `git`
   > binary escaped as a raw `FileNotFoundError`). The mechanics now live once in
   > `perk.substrate.proc` (`run_captured`/`run_checked` raising a structured `ProcFailure`);
   > the original coupling objection is honored structurally — **the domain facades stay**,
   > each still owning its error type (`GitError`/`NpmError`/`GitHubError`/…) and translating
   > `ProcFailure` at its boundary. Only spawn/timeout/env/kwargs mechanics and the default
   > message shapes centralized. The tripwire test remains and now pins the smaller sanctioned
   > set (`proc.run_captured` + the three inherited-stdio streaming sites).
10. **No re-exports; one canonical import path; declare variables close to use; context managers
    inline in `with`** — every symbol has exactly one home; lifecycles stay visible. *judgment*
    (ruff `I`/`RUF` already cover fragments).
11. **Keyword-only arguments on 5+-parameter functions** (`*` after the first/`ctx` parameter;
    ABC/Protocol methods and Click callbacks exempt) — call sites must be self-documenting.
    *judgment* — an AST probe finds **zero violations** across the 24 modules today, so this axis
    is lock-in, not remediation. Ruff `PLR0913` is *not* a usable proxy (see §2).
12. **Default-parameter discipline** — avoid default values unless ~95% of callers genuinely want
    the default; eliminate a default that no call site ever overrides; a forgotten parameter must
    never silently produce wrong behavior. *judgment*. The §3 per-case verdicts (`dry_run=False`,
    `derive_title(fallback=…)`, `GitHubActionsRunner(ref="")`, …) are applications of this axis.
13. **No import-time computation or side effects** — module-level code that does I/O, reads the
    environment, or can fail belongs in a `@cache`-wrapped function. *judgment*. **Verdict
    recorded here (a deliberate relaxation of the skill's letter — module-design.md classes even
    `Path()` construction as computation to defer):** pure, infallible, never-mocked module
    constants — relative `Path(...)` literals, `re.compile(...)` patterns, f-strings over other
    constants — are accepted as-is; the `@cache` deferral is required only where the expression
    does I/O, reads env/config, or can raise. Today's tree has no sites past that line (the
    accepted-as-is sites are listed in their §3 entries).

Two axes from AGENTS.md's dignified-python bullet need no checklist row because they are already
mechanically enforced: modern type syntax / no `from __future__ import annotations` (ruff `UP` is
enabled; zero occurrences in the tree) and exception chaining (`B904` via the enabled `B` group).

---

## §2 Candidate ruff rules

Measured against today's tree with ruff **0.15.16** (the `uvx` default), the version the counts
below were probed with. Current config (`pyproject.toml`):
`select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]`, py313, scoped to `perk/**` + `tests/**`.
The `pyproject.toml` change itself lands in the **first sweep (4.2)** so the convergence stays
enforced rather than one-shot; this section is recommendation-only.

| Rule | What it enforces (§1 axis) | Violations today | Ruling |
|---|---|---|---|
| `PLW1514` (unspecified-encoding) | §1.1 encoding on `read_text`/`write_text`/`open` | **0** in `perk/` + `tests/` (preview rule) | **ADOPT** — zero-cost lock-in of an already-converged axis; catches multiline calls a grep misses. |
| `PTH` (flake8-use-pathlib, whole group) | §1.8 pathlib everywhere | **1** in `perk/` (`PTH115` `os.readlink` in `init._skill_link_state`) + **15** in `tests/` (`PTH201` `Path(".")`, all auto-fixable, concentrated in `tests/test_pr_land.py` and `tests/test_pr_review_post_cmd.py`) | **ADOPT** — fix the one production site in the 4.5 sweep; the 15 test sites are mechanical `--fix` fodder when 4.2 enables the rule. |
| `PLR1702` (too-many-nested-blocks) | §1.2 nesting depth | **0** (preview rule) | **ADOPT** — confirms the deep-indent grep signal (21 lines in `registry.py`, 12 in `doctor.py`, …) is argument continuation, not block nesting; locks the ceiling. |
| `PLC0415` (import-outside-top-level) | §1.3 inline imports | **2** in `perk/` (`doctor._runner_checks` — unjustified, fixed in 4.5; `github._read_plan_body` — justified cycle comment, gets `# noqa: PLC0415` when the rule lands) + **25** in `tests/` | **ADOPT for `perk/**` only** — add a `per-file-ignores` entry for `tests/**` (test-local imports are idiomatic there). |

Mechanics note for the 4.2 implementer: `PLW1514`, `PLR1702`, and `PLC0415` are **preview** rules
in ruff 0.15. Enable them via `lint.preview = true` + `lint.explicit-preview-rules = true` so
*only* the explicitly selected preview rules activate (no blanket preview drift). Toolchain
tripwire (docs/learned/toolchain/): `RUF100` fires on a `# noqa` for a non-enabled rule — land the
`# noqa: PLC0415` on `github._read_plan_body` in the same commit that enables the rule, not before.

**Considered and rejected:** a broader `PL` complexity subset (`PLR0912`/`PLR0915`,
too-many-branches/statements) — perk's long functions (`launch.launch_stage`,
`init._converge_settings`) are addressed as targeted §3 items; a blanket statement-count ceiling
would fight the deliberately linear check-builder style in `doctor.py` without improving it.
Also rejected: `PLR0913` (too-many-arguments) as a proxy for the §1.11 keyword-only axis — it
fires 28× on today's tree, nearly all on *compliant* keyword-only signatures (it counts kw-only
params too), so it measures arity, not the directive; §1.11 stays judgment-tier.

---

## §3 Per-module friction backlog

One entry per module; **"clean" is an explicit verdict**, not an omission. Each friction item:
checklist axis → durable anchor → proposed fix (one sentence) → effort (S/M/L). Effort: S ≤ ~30
min mechanical, M = a focused refactor with test updates, L = a multi-part refactor.

### Node 4.2 — core domain (`github.py`, `git.py`, `plan.py`, `objective.py`, `cache.py`, `config.py`)

Plus the bucket-level task: **enable the §2 ruff rules** (pyproject change + the mechanical
`--fix` of the 15 test `PTH201` sites + the `# noqa: PLC0415` on `github._read_plan_body`). (S)

**`github.py` (2,127 lines)** — the dominant friction in the codebase; see the §5 rebalancing
ruling before starting.

- §1.10/§1.7 — *the proc→returncode→json.loads→isinstance pipeline is hand-rolled ~15×*
  (anchors: `check_repo_access`, `find_plan_issue`, `list_learn_issues`, `create_plan_issue`,
  `_post_comment_with_id`, `get_objective`, `find_pr_for_branch`, `create_pr`,
  `_find_plan_body_comment_id`, `find_comment_id_by_marker`, `get_pr`, `get_plan`,
  `get_plan_body`, `get_pr_review_context`, `trigger_workflow`, `get_workflow_run`,
  `get_workflow_permissions`): extract a `_run_json(args, *, what, cwd, timeout)` helper that
  runs, raises `_failed(...)` on non-zero, parses, and type-checks the payload — each call site
  collapses to one line. **(L** — mechanical but wide; byte-identical error messages must be
  preserved where tests assert them**)**
- §1.10 — *the `"404" in (proc.stderr + proc.stdout)` not-found idiom is repeated 6×* (anchors:
  `get_objective`, `_get_comment_body`, `get_pr`, `get_pr_body`, `get_plan`, `get_plan_body`,
  `secret_exists`): extract `_is_not_found(proc) -> bool` (folding the `"not found"` lowercase
  variant used by the `gh issue view` callers). (S)
- §1.10 — *the REST arg-list building (`"-X", method, "-f", f"k={v}", …`) is assembled by hand at
  every call site*: extract a small `_rest_args(path, *, method, fields, body_path=None, jq=None)`
  builder; apply it opportunistically while touching call sites for `_run_json` (do **not** chase
  byte-identical coverage — the helper earns its keep only where it simplifies). (M)
- §1.10 — *`list_learn_issues` duplicates `find_plan_issue`'s label-scoped LIST call*: extract the
  shared `_list_label_issues(label, repo_root)` read both consume. (S)
- §1.3 — `_read_plan_body`'s inline `from perk import cache` carries a cycle-justification comment:
  **verdict — keep** (it is the sanctioned inline-import shape; gets `# noqa: PLC0415` in 4.2).
- §1.5 — no property/magic-method issues; §1.9 — all subprocess routed through `_run` with
  explicit `check=False` + timeouts: **clean**.
- **Open ruling for the sweep:** `dry_run: bool = False` default parameters are pervasive across
  the mutation ops. The audit's recommendation is **keep** (False is the only safe default and
  erk used the same convention), but if the sweep finds a call site that *forgot* `dry_run`
  plumb-through, escalate to keyword-required (`*, dry_run: bool`) for that op family.

**`git.py` (206 lines)** — **clean.** `_run` is the sanctioned per-boundary wrapper (explicit
`check=False`, `timeout=`, domain `GitError`); LBYL with operation-as-authoritative-test
documented per function. One adoption item lands here from §4 row 3: set
`GIT_TERMINAL_PROMPT=0` in `git._run`'s subprocess env so a credential prompt fails fast instead
of hanging to the timeout. (S)

**`plan.py` (260 lines)** — **clean.** Pure, deterministic, no I/O; the block engine's
delimiter-scan style is deliberate (no custom regex). `derive_title`'s `fallback` default is a
documented convenience — keep.

**`objective.py` (681 lines)**

- §1.10 (no re-exports) — `render_metadata_block_for` is a pure re-export shim over
  `plan.render_metadata_block`: delete it and point its callers at the canonical
  `perk.plan.render_metadata_block`. (S)
- §1.10 (one canonical path) — `DependencyGraph.next_node` is a doc-decorated alias of
  `DependencyGraph.next_plannable`: collapse to one method (keep `next_plannable`, migrate
  callers). (S)
- §1.2 — `validate_roadmap`'s per-node validation body is long but ≤4 levels and linear:
  **verdict — acceptable**; optionally extract `_validate_node(i, raw) -> ObjectiveNode | str`
  if the sweep touches it anyway (do not refactor for its own sake).
- §1.5 — `DependencyGraph._node_map` is an O(n) *method* (not property) rebuilt per call:
  **verdict — acceptable** (n = roadmap nodes, pure).

**`cache.py` (226 lines)** — **clean**, with one recorded verdict: the single-record readers
(`read_handoff`, `read_dispatch`, `read_plan_ref`) let `json.JSONDecodeError` propagate on a
corrupt cache file while `list_dispatch_records` skips-and-warns. **Verdict — acceptable
asymmetry**: a corrupt *active* pointer should fail loudly at the command boundary, while the
supervisor's *enumeration* must survive one bad record. Record, don't change.

**`config.py` (137 lines)** — **clean.** LBYL silent-omit parsers are documented and mirrored
across `_parse_providers_selection`/`_parse_subagents_selection`/`parse_compaction_table`; the
bool-is-int guard carries its comment.

### Node 4.3 — launch/run (`launch.py`, `run_id.py`, `run_report.py`, `run_worker.py`, `runner.py`, `resume.py`)

**`launch.py` (589 lines)**

- §1.2/§1.10 — `launch_stage` interleaves six concerns (target resolve, worktree, prompt
  assembly, binding delivery, dry-run preview, materialize+exec) in one ~90-line body: extract
  the prompt+bindings assembly (`_resolve_prompt(stage, resolved, config, prompt_override,
  binding_trigger, …) -> str | None` or similar) and the dry-run preview block into helpers so
  the remaining body reads as the launch pipeline. (M)
- §1.10 — `_drive_remote_target` constructs three near-identical `DispatchRecord`s by hand
  (`status="dispatching"` → `"failed"` → `"dispatched"`): build once and use
  `dataclasses.replace` for the two transitions. (S)
- §1.4 — `_implement_prompt`/`_address_prompt`/`_learn_prompt` destructure `plan_ref` fields into
  locals (`provider`/`pr_id`/`url`) that are each used 1–3×: **verdict — acceptable** (the locals
  name untyped `dict` lookups inside f-strings; inlining would hurt readability).
- §1.8 — `os.environ`/`os.chdir`/`os.execvpe` are process-control, not path ops: **clean** under
  the pathlib axis.
- `_initial_prompt(config: Config | None = None)` default: **verdict — keep** (the `None`
  fallback is the documented "no subagents table" case).

**`run_id.py` (51 lines)** — **clean; shallow-module verdict: KEEP** (the run-id minting/parsing
concept is consumed by launch, cache, workflow_smoke, and the TS plane's contract; its EAFP in
`is_run_id` carries the authoritative-test justification in its docstring).

**`run_report.py` (241 lines)**

- §1.10 — `format_outcome` and `format_step_summary` duplicate the status/terminal-signal/budget/
  PR/run-URL body assembly: extract the shared fragment builder (the only differences are the
  head line and trailing newline). (S)
- §1.7 — the two `except Exception` catches in `report_started`/`report_terminal` are **sanctioned
  fail-soft boundaries** (documented: observability must never change the worker's exit code) —
  **verdict — keep**, including the broad catch.

**`run_worker.py` (191 lines)**

- §1.10 (one canonical path) — `position_worktree` calls the *private*
  `launch._materialize_plan_body` across module lines: promote it to a public
  `launch.materialize_plan_body` (or move it to `cache`/a shared home) and update both callers.
  (S)
- §1.9 — `_spawn_worker` is the sanctioned single wrapper for the node spawn (explicit
  `check=False`, `timeout=WORKER_TIMEOUT_S`): **clean**.

**`runner.py` (208 lines)** — **clean**, with one recorded ruling. The `GitHubError →
RunnerError` translations are proper boundary re-raises with `from exc`.
`GitHubActionsRunner.__init__(ref: str = "")` default: **verdict — keep** ("" is the documented
default-runner sentinel in the dispatch record).

- Interface choice — `Runner` is a `Protocol` with a single perk-owned implementation, where the
  dignified-python default (`references/advanced/interfaces.md`: "internal application code you
  own → ABC") points at an ABC. **Verdict — keep the Protocol, recorded as a deliberate override
  of the skill default:** the contract is minimal (four methods), there is no shared
  implementation to inherit, no `isinstance` validation is needed (the dispatch path selects by
  construction, not by type check), and structural typing *is* the documented "keep future
  runners open" seam — a future runner kind should satisfy the contract without importing and
  subclassing perk's class. Revisit only if a second runner needs shared behavior.

**`resume.py` (44 lines)** — **clean; shallow-module verdict: KEEP** (the pure resume-stage
decision matrix is separated *precisely* so it unit-tests without GitHub; merging it into
`launch.py` or `github.py` would re-couple it).

### Node 4.4 — provider/registry/binding (`providers.py`, `registry.py`, `bindings.py`, `binding_delivery.py`, `capabilities.py`)

**`providers.py` (251 lines)** — **clean.** The parser-tolerates/validator-reports split is the
house pattern; `resolve_providers`' inner `resolve_seam` closure is ≤4 levels and pure.
`load_providers(path: Path | None = None)`: **verdict — keep** (the `None` default is the
bundled-file convention shared with `load_registry`/`load_bindings`).

**`registry.py` (290 lines)**

- §1.2 — the 21 deep-indent lines are multi-line `Issue(...)` constructor continuations inside
  `_check_graph`/`_check_doors_and_run_id`, not block nesting (PLR1702: 0): **verdict —
  acceptable**; *optionally* add a module-local `_err(where, msg) -> Issue` shorthand to flatten
  the validators if the sweep touches them — cosmetic only, not required. (S, optional)
- Otherwise **clean** (same parser/validator split as providers/bindings).

**`bindings.py` (275 lines)** — **clean**, with one cross-module item shared with
`binding_delivery.py` below. `resolve_bindings(defaults: list[Binding] | None = None)` performs
I/O (`load_bindings()`) when defaulted: **verdict — acceptable but flagged** — every production
caller passes `defaults=None` deliberately (the bundled-set read *is* the default behavior), and
tests inject; if a future caller needs purity it passes `defaults`.

**`binding_delivery.py` (108 lines)**

- §1.10 (one canonical path) — `SKILLS_SUBDIR`/`SKILL_FILENAME` duplicate
  `bindings._SKILLS_DIR`/`bindings._SKILL_FILENAME` (two declarations of the same contract
  constants, one private and one public): consolidate to a single public pair in `bindings.py`
  (the module that owns `is_skill_installed`) and import them here. (S)
- Module-level `Path(".agents/skills")` construction (`SKILLS_SUBDIR`): **verdict — acceptable
  under the §1.13 recorded relaxation** (pure, infallible, never mocked). Note this is *not*
  within module-design.md's own static-constant carve-out — the skill explicitly classes `Path()`
  construction as computation to defer behind `@cache`; perk accepts these knowingly. The same
  recorded verdict covers `bindings._SKILLS_DIR`/`_SELF_REPO_SKILLS_DIR` and the three
  `github.py` module-level `re.compile` constants (`_CHECKOUT_RE`/`_PLAIN_FOOTER_RE`/
  `_HTML_FOOTER_RE`).

**`capabilities.py` (71 lines)** — **clean; shallow-module verdict: KEEP** (the declared
inventory is the init/doctor coverage contract; its docstring already records the deliberate
deferrals — don't author the ABC until an optional capability exists).

### Node 4.5 — init/doctor/env + misc (`init.py`, `doctor.py`, `env.py`, `workflow_artifacts.py`, `workflow_smoke.py`, `output.py`, `_resources.py`)

Plus the bucket-level task: **the subprocess tripwire test** — a `pytest` regression test that
greps `perk/**/*.py` for `subprocess.run(` outside the sanctioned wrapper functions
(`git._run`, `github._run`, `env._node_version`, `init._sync_skills`, `run_worker._spawn_worker`)
and asserts every call passes explicit `check=` and `timeout=` — the mechanical enforcement of
the §1.9 verdict. (S)

**`init.py` (865 lines)**

- §1.8 — `_skill_link_state` uses `os.readlink(entry)` (the tree's one `PTH` production
  violation): replace with `entry.readlink()` (`PTH115`); note `Path.readlink()` returns a `Path`
  — coerce with `str(...)` to keep the `{name: target}` snapshot shape. (S)
- §1.7 (report, never silent) — `_sync_skills`'s `except (OSError, subprocess.TimeoutExpired):
  return` swallows the failure invisibly even though the docstring declares best-effort: emit one
  `user_output("⚠ skills sync skipped: …")` line before returning. (S)
- §1.10 (one canonical path) — `doctor._fix_config` and `doctor.run_doctor` reach into
  `init._converge_config` / `init._sync_skills` as privates: promote both to public names
  (`converge_config`, `sync_skills`) since doctor is a deliberate second consumer (the D2 SSOT).
  (S)
- §1.2/§1.10 — `_converge_settings` interleaves identity-dedup bookkeeping (`have_local`/
  `have_npm`/`have_git` + the three-way `want` dispatch) with provider and compaction composition:
  extract the static-package merge loop into `_merge_static_packages(packages, desired) ->
  tuple[list, list[str]]` so the body reads as the three composition layers. (M)
- `run_init(root: Path | None = None)`: **verdict — keep** (the `Path.cwd()` boundary convenience
  is documented; every internal caller passes `root`).

**`doctor.py` (801 lines)**

- §1.3 — `_runner_checks`'s inline `from perk.workflow_artifacts import RUNNER_ENABLED_VAR,
  RUNNER_PAT_SECRET` has **no justification comment and no cycle** (`init` already imports
  `workflow_artifacts` at module level, and `doctor` imports `init`): move it to the module-level
  import block. (S)
- §1.7 (report, never silent) — `_untrack_materialized_plan_cache`'s `except git.GitError: pass`
  silently swallows a failed `git rm --cached`: append a loud entry (or `user_output` warning)
  noting the untrack failed, so `--fix` output never silently under-reports. (S)
- §1.2/§1.10 — `_runner_checks` is ~165 lines of linear `Check(...)` assembly: extract the four
  concern blocks (`_runner_enabled_check`, `_runner_pat_check`, `_runner_model_check`,
  `_runner_permissions_check`) — the deep-indent grep signal here is constructor continuation,
  and the extraction is for navigability, not nesting. (M)
- §1.5 — `DoctorReport.healthy`/`DoctorReport.exit_code` O(n) properties: **verdict — acceptable**
  (the §1.5 recorded verdict; pure scan of an in-memory list).

**`env.py` (80 lines)** — **shallow-module verdict: KEEP** (the tool-presence contract shared by
init and doctor). One item: `_which` is a single-line pass-through over `shutil.which` consumed
twice — inline `shutil.which(name)` at both call sites and delete the wrapper. (S)
`_node_major`'s `try/except ValueError` around `int(...)`: **verdict — keep** (parsing is the
authoritative test; the advanced-reference "prefer real parsers over brittle pre-checks" case).

**`workflow_artifacts.py` (240 lines)** — **clean.** Templates-as-code is a documented decision;
`_converge_file` is the right shared shape. The f-string module constants
(`RUNNER_WORKFLOW_PATH`, `_PERK_INSTALL_CONSUMER`) interpolate other constants only — accepted
under the §1.13 recorded relaxation (not the skill's own carve-out; see the §1.13 verdict).

**`workflow_smoke.py` (135 lines)**

- §1.10 (output discipline, guidelines §7) — `dispatch_smoke` uses `print(..., file=sys.stderr)`
  where every sibling module uses `perk.output.user_output`: switch to `user_output` and drop the
  `sys` import. (S)
- Otherwise **clean** (`contextlib.suppress(GitHubError)` in `cancel_smoke` is a documented
  best-effort cancel — keep; injectable `sleep`/`now` is the house testability pattern).

**`output.py` (32 lines)** — **clean; shallow-module verdict: KEEP** (the stderr/stdout split is
a load-bearing contract — cli-vs-pi §3.2 — and must not live inside any one consumer).

**`_resources.py` (35 lines)** — **clean; shallow-module verdict: KEEP** (the single "where is
shared/?" resolver with a TS twin; merging it into `registry.py` would force
bindings/providers to import registry for path resolution).

**`__init__.py` / `__main__.py` coverage note** — `__init__.py` (5 lines) carries only the
docstring + `__version__` lockstep constant (no re-exports — already converged with §1.10);
`__main__.py` (3 lines) is the minimal `python -m perk` shim. **Both clean; no backlog entries.**

---

## §4 erk-pattern adoption opportunities

Decision-table style per [migration-adoption-audit.md](./migration-adoption-audit.md) —
record-only here; adoption happens in the named sweep node.

| # | Pattern | erk evidence | perk today | Ruling | Why (one line) |
|---|---|---|---|---|---|
| 1 | Repo-global subprocess wrapper (`run_subprocess_with_context`, retry/timing built in) | erk's `packages/erk-shared/src/erk_shared/subprocess_utils.py`; erk's `docs/learned/architecture/subprocess-wrappers.md` | Per-boundary wrappers (`git._run`, `github._run`) + three single-tool wrapper functions, all explicit `check=`/`timeout=` | **DROP** (tripwire test instead — 4.5) *(superseded — see the §1.9 status note)* | erk's wrapper exists for retry/timing/gateway DI perk doesn't have; one global wrapper would couple `GitError`/`GitHubError`/best-effort error models. |
| 2 | `GIT_TERMINAL_PROMPT=0` env for git subprocesses | `erk_shared/subprocess_utils.py` `copied_env_for_git_subprocess` | `git._run` inherits the ambient env — a credential prompt hangs until the 30s timeout | **ADOPT (4.2)** | One-line env injection makes every git failure fast and explicit instead of timeout-shaped. |
| 3 | Discriminated-union error handling (`T \| ErrorType` at gateway boundaries) | erk's `docs/learned/architecture/discriminated-union-error-handling.md` | Error-by-caller-behavior: lookups → `… \| None`, mutations → raise, branching callers → result dataclasses (`github.py` mutation-ops banner) | **DROP** | perk already sits in erk's own "when exceptions are better" carve-out (callers terminate or branch on a typed result, never inspect error structure mid-flow). |
| 4 | No chained `.get()` (LBYL-violation tripwire) | erk's `docs/learned/conventions.md` "LBYL Violations in Disguise" | `(payload.get("data") or {}).get(…)` chains in `github._parse_review_threads`/`_parse_reviews`/`get_pr_feedback`; `launch._drive_remote_target` | **DROP, with a recorded carve-out** | For *foreign* JSON payloads (GraphQL/REST responses) the `or {}` walk is the honest null-tolerant read; the erk rule stands for **perk-owned dicts** (where a missing key is a bug) — the sweeps enforce only the latter. |
| 5 | Frozen dataclasses with plain fields (no `_field` + property pass-throughs) | `conventions.md` "Immutable Classes" | Pervasive — 17 of 24 modules use `@dataclass(frozen=True)` with plain fields | **DROP (already adopted)** | Nothing to do; the convention is already perk's default shape. |
| 6 | Gateway ABC, 4-place implementation (abc/real/fake/dry_run) | erk's `docs/learned/architecture/gateway-abc-implementation.md` | One implementation per plane (cli-vs-pi §3); tests monkeypatch the module wrapper | **DROP** | perk deliberately rejected the gateway hierarchy (PRIOR_ART: the surface dissolves on Pi); a fake/dry-run lattice is weight without a second consumer. |
| 7 | Time abstraction (`context.time.sleep/now`, never bare `time.*`) | erk's `docs/learned/universal-tripwires.md` | Call-site injection: `trigger_workflow(sleep=time.sleep)`, `poll_smoke(sleep=…, now=…)` | **DROP** | The two loops that need fake time already inject it; a global Time gateway is the 4-place pattern in disguise. |
| 8 | Lightweight `__init__` (no I/O/subprocess in constructors; factory methods) | `universal-tripwires.md` | All constructors are frozen-dataclass field assignment; `GitHubActionsRunner.__init__` stores one string | **DROP (already adopted)** | No violations to fix. |
| 9 | `_id`-suffix naming for integer identifiers | `conventions.md` "Variable Naming by Type" | Mixed by design: `pr_id` is a **string** (contracts §8.4 provider-agnostic ids); `comment_id`/`pr_number` are ints | **DROP, with a recorded note** | perk's `pr_id`-as-string is a cross-plane contract, not drift; renaming would fight `shared/contracts.md`. The useful residue — prefer `*_number` for ints alongside string `*_id` — is already the de-facto pattern in `github.py`. |
| 10 | Speculative-feature constant pattern (`ENABLE_X` + grep-able marker) | `conventions.md` "Speculative Feature Pattern" | No speculative features in the non-CLI modules | **DROP (no current need)** | Adopt ad hoc if a removable feature ever ships; nothing to converge now. |

---

## §5 Rebalancing proposals

Per-node effort totals from §3 (bucket-level tasks included):

| Node | Items | Effort profile |
|---|---|---|
| 4.2 | ruff enablement (S) + github.py (L + M + 2S + 1 open ruling) + git GIT_TERMINAL_PROMPT (S) + objective (2S) + 3 recorded verdicts | **1L + 1M + 6S** — dominated by `github.py` |
| 4.3 | launch (M + S) + run_report (S) + run_worker (S) + 3 clean/keep verdicts | **1M + 3S** |
| 4.4 | binding_delivery↔bindings constants (S) + registry optional `_err` (S, optional) + 3 clean/keep verdicts | **1–2S** — the lightest bucket |
| 4.5 | tripwire test (S) + init (M + 3S) + doctor (M + 2S) + env (S) + workflow_smoke (S) + 4 clean/keep verdicts | **2M + 8S** — the widest bucket |

**The `github.py` ruling.** At 2,127 lines, `github.py` is ~2× the rest of bucket 4.2 combined,
and its headline item (the `_run_json` extraction, L) touches ~15 functions whose error strings
are test-asserted. Ruling:

1. **Node 4.2 keeps `github.py`, scoped to the §3 items as written** — the `_run_json` /
   `_is_not_found` / `_list_label_issues` extractions plus the opportunistic `_rest_args`
   builder. This is mechanical-but-wide, and it is the *prerequisite* for any future split (a
   package split before helper consolidation would copy the boilerplate five times).
2. **A `perk/github/` package split is explicitly OUT of scope for 4.2** and is **proposed as a
   new follow-on node** for `/objective-reconcile` to add (or reject) post-merge: the module's
   five section banners (core reads + issue mutations / objective ops / PR lifecycle /
   review-feedback + pr-review ops / workflow-dispatch + runner reads) are already the natural
   seams. The audit's recommendation is to add it only if `github.py` keeps growing past the
   helper consolidation — the banners make the single file navigable today.

**Bucket-balance proposal.** 4.4 is deliberately light and 4.5 deliberately wide — but 4.4's
modules are the contract-coupled trio (registry/bindings/providers + their TS twins), where
small diffs are a feature, and 4.5's items are almost all S. No node moves are proposed; the
flag for `/objective-reconcile` is solely the optional `github.py` package-split node from the
ruling above.
