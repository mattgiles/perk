# Phase 0 · Turn 6 — `perk doctor`

> Implementation-level plan for **T6**. `init`'s **diagnostic twin**: where `init` converges a repo
> *forward* to the desired state, `doctor` **reports** coherence and `--fix` **repairs** drift — plus
> a forward-looking seam for legacy/one-off migrations `init` deliberately won't bake in. Reuses
> `init`'s convergence helpers in **dry-run** mode for a single desired-state SSOT. **Python-only**;
> **no new dependency**.

---

## 1. Objective & the gate

**Objective.** Keep a perk-managed repo *trustworthy while everything else is in flux*. `perk doctor`
inspects the borrowed-package + GitHub + state setup and reports a structured, grouped health view
(condensed by default, `--verbose` expands); `perk doctor --fix` repairs known drift (and establishes
the home for future legacy migrations); `--json` + stable exit codes give supervisors the second
canonical machine surface (the first is `init`, T5).

**Acceptance gate (from `phase-0-plan.md` §T6).** `perk doctor` reports health on an init'd repo;
`--fix` remediates a deliberately-broken setup; **dual mode** distinguishes self (perk's own repo)
from consumer.

**Non-goals (T6).** No TS work (doctor is a CLI diagnostic over the *shared* artifacts; the runtime
extension-load proof remains T1's gate). No GitHub **mutation** (Q9 — verification-only). No
session-`perk:workflow-state` ↔ GitHub coherence check (needs the Phase-1 spine; the CLI can't read
session entries). No `doctor workflow` CI smoke test (Phase 3). No outside-a-repo env-only diagnosis
(Phase 0 doctor requires a repo).

---

## 2. Grounding & doc lineage (what governs T6)

- **`docs/phase-0-plan.md` §T6** — the deliverables (grouped structured checks, condensed/`--verbose`,
  consolidated remediation, `--fix`, `--json` + exit codes, self-vs-consumer) + the gate.
- **`perk/capabilities.py`** (T5) — the declared managed-piece inventory. T5 promised *"T6 doctor
  reuses the same tuple and adds a `verify()` side."* This turn discharges that promise: the
  inventory becomes the **self-vs-consumer filter** + the managed-piece check set.
- **`perk/init.py`** (T1/T4/T5) — the convergence helpers (`_converge_settings`,
  `_converge_workflow_dir`, `_apply_managed_block`). D2 refactors them to a **plan/apply** shape so
  `init` (apply) and `doctor` (dry-run verify / apply fix) share one desired-state SSOT.
- **`perk/env.py` + `perk/github.py`** (T5) — reused verbatim for the Environment + GitHub groups
  (github stays **verification-only, non-fatal**).
- **`perk/registry.py`** (T2) + **`perk/cache.py`** (T3) — the registry self-check and the cache
  layout/handoff integrity check.
- **`shared/contracts.md` §8.5** (T5) — the supervisor-surface convention (human→stderr, `--json`→
  stdout, stable exit codes, `error_type` vocab). T6 adds **§8.6** (the doctor surface) and marks the
  capability-inventory `verify()` side implemented.
- **`docs/cli-vs-pi.md` §3.2** — `--json` is for machines that *launch* perk (`init`, `doctor`),
  never the agent; no `schema`/MCP.
- **`docs/python-cli-guidelines.md` §7** — `user_output`→stderr / `machine_output`→stdout; the
  `UserFacingCliError` + `Ensure` + `PerkContext`/`require_repo` DI.
- **erk `src/erk/cli/commands/doctor.py` + `core/health_checks/`** — the `CheckResult` shape
  (`passed`/`warning`/`info`/`message`/`details`/`remediation`), the **grouped condensed-vs-verbose**
  rendering, and the **consolidated remediation** block — ported and simplified to one module.

---

## 3. Prior-art pass — sharpenings folded in

1. **erk's doctor *reports* remediations; it does not auto-fix** — the migrations live in
   `init --upgrade` / `managed_artifacts`. perk inverts this: `init` is pure forward-convergence and
   **`doctor --fix` is the deliberate home for repairs + legacy oddities** (`phase-0-plan.md` §T6).
   So perk's `--fix` *applies* — but Phase 0 has **no prior versions to migrate**, so the migration
   *mechanism* ships with an **empty repair set** (D4 — no fictional migrations).
2. **erk's `CheckResult` carries `warning`/`info` booleans**; perk collapses these into one
   `status: Literal["ok","warn","info","fail"]` — cleaner to serialize and to map to exit codes.
3. **erk's `managed_artifacts` check is capability-aware** (`load_installed_capabilities` →
   `frozenset | None`) — perk reuses `capabilities.applicable(self_repo)` as the same self-vs-consumer
   filter, but over the **declared** inventory (no installed-state file yet; D1 carryover).
4. **erk re-derives "desired" inside each check** (drift risk vs the converge path). perk avoids the
   duplication by **reusing `init`'s converge helpers in dry-run mode** as the verifier (D2) — init
   and doctor can never disagree about desired state. **Config is exempt** (user-editable).
5. **erk groups checks for display + consolidates remediation.** perk ports both: condensed group
   summaries by default, `--verbose` expands every check, and a single de-duplicated remediation
   block at the end.
6. **T5's `verify` seam was the load-bearing testability lesson** (§15) — `run_doctor` gets the same
   `verify=False` seam so unit tests exercise the engine without an installed/authed toolchain.
7. **doctor's job is to *report* tool problems, not refuse to run** — so a missing required tool is a
   **failing check (exit 1)**, a deliberate divergence from `init` (where missing tool = exit 2). Only
   `not_a_repo` blocks doctor (exit 2) (D5).
8. **`doctor` is a Click *group* with `invoke_without_command=True`** (`cli/doctor-workflow.md`
   tripwire) — bare `perk doctor` runs the health checks today, and the Phase-3 `perk doctor workflow`
   subgroup slots in later **without a breaking command-type change**.
9. **No silent pass** (`error-handling-patterns.md` Pattern 3 — silent-fallback prohibition). A check
   that *cannot be evaluated* (gh errored, a file unreadable, a shell timed out) reports `warn`/`info`
   **with the reason** — never a silent `ok`. The github `try/except GitHubError -> warn` is the
   canonical instance; every group obeys it.
10. **Monkeypatch-free testability via a pure/impure split** (the `FakeHealthCheckRunner` lesson in
    `health-check-runner-gateway.md` + `parameter-injection-pattern.md`). Separate the check-*building*
    (impure: env/github/converge) from the **pure** report/render/exit/json layer, so the latter tests
    against synthetic `Check` lists with zero monkeypatch. perk doesn't need erk's full gateway — the
    split + the `verify` seam suffice.

---

## 4. Repo additions (end of T6)

```
perk/
├── doctor.py                       # NEW — Check + DoctorReport + run_doctor + FIXERS + the (empty) migration seam
├── init.py                         # CHANGED — converge helpers refactored to plan/apply shape (apply: bool -> list[str])
├── cli/
│   └── commands/doctor_cmd.py      # NEW — Click group (invoke_without_command=True); --fix/--verbose/--json; grouped render (stderr) + json (stdout); ctx.exit
├── cli/cli.py                      # CHANGED — register the doctor command
shared/contracts.md                 # CHANGED — new §8.6 (doctor machine surface); capability-inventory verify() -> implemented
tests/
├── test_doctor.py                  # NEW — groups/status/exit codes/--fix round-trip/self-consumer filter (verify=False)
├── test_init_idempotent.py         # CHANGED — converge-helper refactor keeps idempotency green (apply=True path)
scripts/verify-t6.sh                # NEW — the T6 hard gate
justfile                            # CHANGED — verify runs t1..t6
```

`pyproject.toml` / `package.json` **unchanged** (no new dep; no TS).

---

## 5. Locked choices (D1–D7, all agreed)

1. **D1 — `perk/doctor.py` mirroring `perk/init.py`.** `run_doctor(root, *, fix, interactive,
   verify) -> DoctorReport`, a frozen `Check` (pure data → serializable), `DoctorReport` with an
   `exit_code` property + `report_to_dict`. **One module** (perk's scale doesn't need erk's
   `health_checks/` package). The command is a **Click group** (`invoke_without_command=True`) so
   Phase-3 `doctor workflow` is non-breaking; the report/render/exit layer is **pure** (built from a
   `list[Check]`) for monkeypatch-free tests.
2. **D2 — SSOT via convergence reuse (accepted: refactor `init.py`).** The *structural* converge
   helpers become `(…, *, apply) -> list[str]`. `init` calls `apply=True`; doctor's managed-piece
   **checks** call `apply=False` (empty ⇒ healthy); doctor **`--fix`** calls `apply=True` as the
   fixer. **Config is exempt** — user-editable, so doctor checks *present + parses + required keys*,
   never content-diffs.
3. **D3 — Six check groups (what's checkable now):** Environment (`env`), GitHub (`github`,
   **non-fatal/`warn`**), Package wiring (settings dry-run), Repository (workflow-dir + gitignore +
   agents dry-runs; config present/valid), Registry self-check (`registry`), State/cache (`cache`).
   Session↔GitHub coherence + `doctor workflow` deferred.
4. **D4 — `--fix` = real repairs + an honest, empty migration seam.** Fixers re-run the matching
   converge helper (`apply=True`) / `cache.ensure_layout`; un-auto-fixable checks carry remediation
   text only. The legacy migration mechanism is wired but ships **empty** — perk has no prior versions
   (no fictional migrations). `--fix` re-verifies; exit reflects the post-fix state.
5. **D5 — Exit codes + dual-mode (+ the deliberate divergence).** `0` healthy (warnings allowed) ·
   `1` unhealthy (≥1 `fail`) · `2` `not_a_repo`. Missing **required tool = exit 1** (a reported
   finding), *not* exit 2. `self_repo = _is_self_repo(root)`; `capabilities.applicable(self_repo)`
   filters the managed-piece checks (infra checks always run).
6. **D6 — Machine surface + contracts §8.6.** `--json` object `{ success, healthy, self_repo, checks:
   […], summary:{passed,warnings,failed}, fixed:[…] }`; human (condensed groups + consolidated
   remediation; `--verbose` expands) → stderr, json → stdout. Amend contracts with §8.6 + mark the
   inventory `verify()` side implemented.
7. **D7 — Python-only; no new dep; no TS change.** Reuse `env`/`github`/`registry`/`cache`/
   `capabilities` + the refactored `init` converge helpers. tomllib/shutil stdlib.

---

## 6. Work breakdown (ordered)

### T6.a — `perk/init.py` converge-helper refactor (D2, the SSOT seam)

- `_converge_settings(root, self_repo, *, apply=True) -> list[str]` — compute desired settings,
  compare to actual; return change descriptions; **only `write_text` when `apply`**. (The
  `invalid_settings` `UserFacingCliError` on malformed JSON stays — raised in both modes.)
- `_converge_workflow_dir(root, *, apply=True) -> list[str]`.
- `_apply_managed_block(…, *, apply=True) -> list[str]` (drives both the gitignore and AGENTS
  blocks). Returns `[f"{label}: {verb}"]` when it would change.
- `run_init` aggregates: `changes.extend(_converge_settings(root, self_repo, apply=True))`, etc.
  **`_converge_config` is unchanged** (init-only re-seed/force; not part of the dry-run SSOT).
- *Acceptance:* T1/T4/T5 idempotency gates stay green (apply=True path is byte-identical).

### T6.b — `perk/doctor.py` (the engine)

- `Status = Literal["ok", "warn", "info", "fail"]`; `@dataclass(frozen=True) Check(name, group,
  status, message, detail, remediation)` — pure data.
- `@dataclass(frozen=True) DoctorReport(checks: list[Check], fixed: list[str], self_repo: bool,
  error_type: str | None, message: str | None)` with:
  - `healthy` property (no `fail`), `exit_code` property (`not_a_repo`→2; any `fail`→1; else 0),
  - `not_repo()` classmethod (mirrors `InitReport.env_failure`).
- **Pure / impure split (sharpening #10).** The check-*builders* are impure (env/github shells,
  converge dry-runs, file reads). Everything downstream — `DoctorReport`, `exit_code`,
  `report_to_dict`, and the renderer — is **pure over a `list[Check]`**, so the
  status/exit/json/render layer is tested against synthetic `Check` lists with **zero monkeypatch**
  (perk's right-sized version of erk's `FakeHealthCheckRunner`).
- **No silent pass (sharpening #9).** A builder that cannot evaluate its check (a shell raised, a
  file is unreadable) emits `warn`/`info` **with the reason in `detail`** — never a silent `ok`.
- `run_doctor(root, *, fix=False, interactive=True, verify=True) -> DoctorReport`:
  1. resolve `self_repo = _is_self_repo(root)`;
  2. build checks group-by-group (below); `verify=False` skips **only the external shells**
     (env/github), leaving the pure managed/registry/cache checks deterministic for tests;
  3. if `fix`: for each `fail` with a registered fixer, apply it, record into `fixed`, then
     **re-run** the affected checks; finally run the (empty) migration seam.
- The group builders (each returns `list[Check]`):
  - `_env_checks()` — `env.check_environment()` → `fail` when `not ok`; remediation passthrough.
  - `_github_checks(root)` — `github.check_auth()`/`check_repo_access()` wrapped in
    `try/except GitHubError`; unauthed/no-access ⇒ **`warn`** (non-fatal, D3); never mutates.
  - `_managed_checks(root, self_repo)` — the converge dry-runs (`apply=False`): empty ⇒ `ok`,
    non-empty ⇒ `fail` with `detail` = the would-be changes. Filtered by
    `capabilities.applicable(self_repo)`.
  - `_config_check(root)` — files present + `tomllib` parses + required keys (NOT a content diff).
  - `_registry_check()` — `registry.load_*`/validate; corrupt ⇒ `fail`, remediation = reinstall.
  - `_cache_check(root)` — `cache` layout subdirs present + handoff blobs parse.
- `FIXERS: dict[str, Callable[[Path, bool], list[str]]]` — maps check `name` → repair (the
  `apply=True` converge helper / `cache.ensure_layout`). Checks without an entry are
  remediation-only.
- `_MIGRATIONS: tuple[…, ...] = ()` — the ordered legacy-repair seam; **empty in Phase 0** (a
  comment documents the shape so the first real migration is mechanical).
- `report_to_dict(report) -> dict[str, object]` — the §8.6 `--json` object.

### T6.c — `perk/cli/commands/doctor_cmd.py` (the command)

- `@click.group("doctor", invoke_without_command=True)` with `--fix`, `-v/--verbose`, `--json`;
  `@click.pass_context` (sharpening #8 — bare `perk doctor` runs the checks; Phase-3
  `perk doctor workflow` slots in as a subgroup without a breaking change). Early-return when
  `ctx.invoked_subcommand is not None`.
- `require_repo(ctx)` → on failure return `DoctorReport.not_repo()` (exit 2). Else `run_doctor(...,
  fix=fix, interactive=not no_interactive_or_tty)`.
- `--json` → `machine_output(json.dumps(report_to_dict(report)))` to **stdout**; else `_render(report,
  verbose)` to **stderr** (grouped condensed summaries / `--verbose` per-check + a single
  consolidated remediation block + a summary line). `ctx.exit(report.exit_code)`.

### T6.d — `perk/cli/cli.py`

- Register the doctor command alongside `init`/`worktree`/`state`/registry/stages.

### T6.e — `shared/contracts.md`

- New **§8.6** (the doctor machine surface — exit codes, the `--json` object, the
  report-don't-refuse divergence, the non-fatal-GitHub note). Mark the capability-inventory
  `verify()` side **implemented (T6)** in the §8.4/§8.5 inventory note.

### T6.f — tests + `scripts/verify-t6.sh` + `justfile`

- `tests/test_doctor.py`:
  - **pure layer (no monkeypatch):** synthetic `Check` lists exercise `exit_code` (0/1/2),
    `healthy`, `report_to_dict`, and the three-way condensed render;
  - **engine (verify=False):** group presence, the `--fix` round-trip on a broken managed block,
    the self-vs-consumer filter, and **no-silent-pass** (an un-evaluable check → `warn`, not `ok`);
  - **coherence guard (sharpening #2):** assert **every required `capabilities.applicable(...)`
    piece has a corresponding doctor check, and every dry-run converge helper is verified** — so
    `init` and `doctor` cannot silently diverge on *coverage* (not just on desired state).
- `test_init_idempotent.py` updated for the converge-helper refactor. `verify-t6.sh` (below).
  `just verify` → t1..t6.

---

## 7. The doctor engine (the locked design)

```
run_doctor(root, *, fix, interactive, verify):
    if root is None or not git-repo:            # (the CLI resolves this via require_repo)
        return DoctorReport.not_repo()
    self_repo = _is_self_repo(root)

    checks  = [ *_managed_checks(root, self_repo),   # settings / workflow-dir / gitignore / agents (converge dry-run)
                _config_check(root),                  # present + valid (NOT a content diff)
                _registry_check(),                    # packaged registry loads + validates
                *_cache_check(root) ]                 # .pi/workflow/ layout + handoff integrity
    if verify:
        checks = [ *_env_checks(), *_github_checks(root), *checks ]   # external shells (skipped in tests)

    fixed = []
    if fix:
        for c in [c for c in checks if c.status == "fail" and c.name in FIXERS]:
            fixed += FIXERS[c.name](root, self_repo)        # re-converge / ensure_layout
        for repair in _MIGRATIONS:                          # empty in Phase 0
            fixed += repair.apply(root)
        checks = <re-run the affected groups>               # post-fix truth
    return DoctorReport(checks, fixed, self_repo, error_type=None, message=None)
```

**Status → exit code.** `DoctorReport.exit_code`: `not_a_repo` ⇒ **2**; any `fail` ⇒ **1**; else
**0** (warnings allowed). `--fix` re-verifies, so the exit reflects *post-fix* health.

**Why dry-run reuse (D2).** A managed-piece check is *literally* "would `init`'s converge change
this?" — so the desired state has exactly one definition. `--fix` is *literally* "let `init`'s
converge change it." init and doctor cannot drift apart, and the fixer is already idempotent and
tested by T1/T4/T5.

**Config is special.** `_config_check` never content-diffs (a user's customized `worktree.root` is
**not** drift). It asserts the files exist, parse as TOML, and carry the required keys; the only
auto-fix is **re-seeding a *missing* file** (never clobbering a present one).

---

## 8. Check groups & the self-vs-consumer filter (D3, D5)

| Group | Backed by | `fail` vs `warn` | Auto-fix? |
| --- | --- | --- | --- |
| **environment** | `env.check_environment()` | tool missing / node<22 = **fail** | no (remediation text) |
| **github** | `github.check_auth`/`check_repo_access` | unauthed / no-access = **warn** (non-fatal) | no (never mutates) |
| **package** | `_converge_settings(apply=False)` | drift/missing entry = **fail** | yes (`apply=True`) |
| **repository** | `_converge_workflow_dir` / gitignore / agents dry-runs + `_config_check` | drift/missing = **fail**; config invalid = **fail** | yes (re-converge; config: re-seed if *missing*) |
| **registry** | `registry` load+validate | corrupt = **fail** | no (reinstall) |
| **state** | `cache` layout + handoff parse | missing subdir / bad blob = **fail** | yes (`cache.ensure_layout`) |

**Dual-mode.** `self_repo = _is_self_repo(root)`; **managed-piece** checks are filtered through
`capabilities.applicable(self_repo)` (Phase 0 sets are identical — all `scope="both"` — but the
filter is wired and tested). **Infra** checks (env/github/registry/cache) always run. The `--json`
object carries `self_repo` so a supervisor can see which mode ran.

**Coherence guard (the D2 SSOT, operationalized).** D2 keeps init/doctor from disagreeing on
*desired state*; a unit test keeps them from disagreeing on *coverage* — it asserts every required
capability `init` converges has a corresponding doctor check (and every dry-run converge helper is
verified). This is erk's capability-registration tripwire (*"Doctor doesn't check artifacts | Missing
`managed_artifacts` declaration"*) + its defensive "uncategorized checks" catch-all, turned into a
test. **No silent pass:** any group that cannot evaluate a check reports `warn`/`info` with the
reason, never `ok`.

---

## 9. The machine surface (D6) — `--json` + §8.6

```
{ "success": bool,                       # the command ran (not "healthy")
  "healthy": bool,                       # no fail checks
  "self_repo": bool,
  "error_type": string|null,             # "not_a_repo" on the exit-2 path
  "message": string|null,
  "checks": [ { "name", "group", "status", "message", "detail", "remediation" } ],
  "summary": { "passed": int, "warnings": int, "failed": int },
  "fixed": string[] }                    # repairs applied by --fix ([] otherwise)
```

Human render (stderr) follows erk's **three-way condensed rule** per group: *(a)* all-pass,
no-warnings → one collapsed `group (n checks)` line; *(b)* all-pass, with-warnings → the line + expand
**only** the warnings; *(c)* any failure → the line + expand **only** the failures. `--verbose`
expands every check. After the groups: a **single de-duplicated remediation block**, then a summary
line.
`--json` (stdout) emits the object on every path (including the `not_a_repo` exit-2 error object).
This is the **second** canonical supervisor command (the first is `init`); the agent never parses it.

---

## 10. Acceptance gate — concrete, runnable checks (`scripts/verify-t6.sh`)

uv-only; temp git repos; CI-robust (GitHub is non-fatal → assert the github section exists, never
`ok=true`; env tools exist in the dev image but the gate doesn't depend on auth).

1. **Healthy report (fresh init'd repo).** `perk init` then `perk doctor` → **exit 0**; `--json`
   parses to `{success:true, healthy:true, self_repo:false, summary.failed:0, …}` with all six groups
   present.
2. **`--fix` round-trip.** Break a managed piece (remove the `.gitignore` managed block / drop a
   `.pi/settings.json` package entry / `rm` a `.pi/workflow/` subdir) → `perk doctor` reports that
   check `fail` (**exit 1**) → `perk doctor --fix` repairs (and lists it in `fixed`) → re-run
   **exit 0**.
3. **Dual-mode.** `perk doctor --json` in perk's own repo (`self_repo:true`) vs a temp consumer
   (`self_repo:false`); assert the flag differs and the managed-piece filter was applied.
4. **Exit codes + json error path.** `perk doctor` outside a git repo → **exit 2**,
   `error_type:"not_a_repo"`, `--json` emits the error object.
5. **Registry + cache integrity.** The registry self-check and the cache-layout check pass on the
   init'd repo.
6. **Config is not flagged on user edits.** Edit `.pi/perk.toml`'s `worktree.root`, run
   `perk doctor` → the config check stays **`ok`** (user edits are not drift).
7. **Unit suite.** `pytest test_doctor` green — the **pure** layer (synthetic `Check` lists →
   exit/json/render, no monkeypatch), the **verify=False** engine (groups, `--fix`, self/consumer
   filter, no-silent-pass), and the **coherence guard** (every required capability ↔ a doctor check).
8. **Group, not command.** `perk doctor --help` shows a group (`invoke_without_command=True`); bare
   `perk doctor` runs the checks — the seam for Phase-3 `perk doctor workflow`.

`just verify` runs t1..t6; `just ci` stays green.

---

## 11. Risks & mitigations

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| converge-helper refactor regresses init idempotency | med | apply=True path is byte-identical; T1/T4/T5 gates + `test_init_idempotent` re-run in `just verify` |
| doctor and init drift on "desired state" | low | **eliminated by D2** — both call the same dry-run/apply helpers |
| config check mistakes a user edit for drift | med | config is **present+valid only**, never content-diffed; gate check 6 guards it |
| `--fix` clobbers a user-customized config | med | config fixer **only re-seeds a missing file**; never overwrites a present one |
| GitHub unauthed flakes the gate | med | github is **non-fatal/`warn`**; gate asserts the section exists, not `ok=true` |
| over-building the migration seam (fiction) | low | `_MIGRATIONS = ()` in Phase 0; only the *shape* is documented |
| missing tool wrongly blocks doctor | low | **D5** — missing tool = a `fail` check (exit 1), only `not_a_repo` blocks (exit 2) |
| init converges a piece doctor never checks (silent coverage gap) | med | the **coherence-guard** test (every required capability ↔ a doctor check) |
| a check silently passes when it couldn't be evaluated | med | **no-silent-pass** rule — un-evaluable → `warn`/`info` + reason; covered by a unit |
| `doctor` ships as a bare command, Phase-3 `workflow` needs a group | low | ship as a **group** now (`invoke_without_command=True`) |
| re-running all checks after `--fix` is wasteful | low | re-run only the **affected** groups; checks are cheap and deterministic |

---

## 12. Explicitly out of scope for T6 (pointers)

- **Session-`perk:workflow-state` ↔ cache ↔ GitHub coherence** — needs the Phase-1 spine (the CLI
  can't read session entries). Phase 0's "state" group = the **CLI-checkable** cache integrity only.
- **`doctor workflow` GitHub-CI smoke test** — **Phase 3** (needs the worker + queue).
- **Outside-a-repo env-only diagnosis** — Phase 0 doctor requires a repo (`not_a_repo` → exit 2).
- **Real legacy migrations** — the seam ships empty; the first migration lands when there's a prior
  version to migrate from.
- **Capability `add`/`remove`/`list` CLI + installed-optional state file + `Capability` ABC** — until
  the first *optional* capability exists (D1 carryover from T5).
- **TS-side diagnostics** — doctor is a CLI surface; the runtime extension-load proof stays T1's gate.
- **An `allow_modified` drift allowlist** (erk's `[artifacts].allow_modified`) — **not needed in
  Phase 0**: perk's managed pieces are marker-delimited blocks ("don't edit between markers" ⇒ an edit
  *is* drift to re-converge) plus the already-exempt user config. If perk ever manages a whole
  user-customizable file, the allowlist is the pattern to adopt then.

---

## 13. Open questions settled (D1–D7)

1. **Module shape (D1)** — one `perk/doctor.py` mirroring `perk/init.py` (`run_doctor`/`DoctorReport`/
   `report_to_dict`); pure-data `Check`; the command is a **Click group**
   (`invoke_without_command=True`) and the report/render/exit layer is **pure** over a `list[Check]`.
2. **SSOT (D2)** — reuse `init`'s converge helpers in dry-run (verify) / apply (fix); config exempt.
3. **Groups (D3)** — environment / github / package / repository / registry / state; session↔GitHub
   + `doctor workflow` deferred.
4. **`--fix` (D4)** — real repairs via the converge helpers + an **empty** migration seam (no
   fictional migrations).
5. **Exit codes + dual-mode (D5)** — 0 healthy / 1 unhealthy / 2 not_a_repo; missing tool = exit 1
   (report-don't-refuse); `capabilities.applicable` filter.
6. **Machine surface (D6)** — `--json` object + §8.6; human→stderr / json→stdout; `ctx.exit`.
7. **Scope (D7)** — Python-only; no new dep; no TS change.

---

## 14. Definition of done

- `perk doctor` on an init'd repo reports a grouped, structured health view (condensed + `--verbose`)
  with a consolidated remediation block and the correct exit code.
- `perk doctor --fix` repairs a deliberately-broken managed piece (re-converge) and re-verifies;
  config user-edits are never flagged or clobbered.
- Dual-mode distinguishes self vs consumer (`self_repo` in `--json`; `capabilities.applicable`
  filter).
- `--json` emits the §8.6 object on every path; exit codes 0/1/2 are stable (missing tool = 1,
  not_a_repo = 2).
- `init`'s converge helpers are the shared SSOT (D2); T1/T4/T5 idempotency stays green; a
  **coherence-guard** test proves every required capability has a doctor check.
- `doctor` ships as a **Click group** (`invoke_without_command=True`); the pure report/render/exit
  layer is tested **without monkeypatch**; un-evaluable checks **never silently pass**.
- `shared/contracts.md` gains §8.6 + marks the inventory `verify()` side implemented.
- `scripts/verify-t6.sh` 7/7; `just verify` t1..t6 ALL PASS; `just ci` green; no new dep; no TS change.

---

## 15. T6 outcomes (recorded after implementation)

**Status: implemented; T6 hard gate 8/8 PASS; T1–T5 gates still PASS; `just ci` green.**

**Built (as planned):** `perk/init.py` (converge helpers refactored to the plan/apply shape +
`ManagedConvergence`/`managed_convergences` registry — the D2 SSOT), `perk/doctor.py`
(`Check`/`DoctorReport`/`run_doctor`/`report_to_dict` + the six group builders + `FIXERS`-by-dispatch
+ the empty `_MIGRATIONS` seam), `perk/cli/commands/doctor_cmd.py` (Click **group**, three-way
condensed render → stderr, json → stdout, `ctx.exit`), `perk/cli/cli.py` registration,
`shared/contracts.md` **§8.6** + the inventory `verify()` note, `tests/test_doctor.py`,
`scripts/verify-t6.sh`, `just verify` → t1–t6. **Python-only — no TS change; no new dependency.**

**Gate results:** all 8 PASS — (1) healthy on fresh init (six groups, `--json`); (2) `--fix`
round-trip on a broken managed block; (3) dual-mode `self_repo`; (4) not-a-repo → exit 2 + json error;
(5) registry + cache integrity; (6) config user-edit not flagged; (7) unit suite (13); (8) doctor is a
Click group. Full suite **79 pytest + 11 node:test**.

**Decisions confirmed by building (D1–D7 all held), with three refinements:**
- **The workflow-dir convergence now owns the *full* cache layout** (`.gitkeep` **+** `cache.SUBDIRS`),
  not just `.gitkeep`. Discovered while building: a freshly-init'd repo had only `.gitkeep`, so doctor
  reported `cache-layout` **fail** — breaking gate check 1. The fix is the more coherent design: the
  `workflow-dir` capability *is* the cache layout, so `init` creates it and doctor verifies the same
  shape via the **one** shared convergence. Consequently the separate `cache-layout` check was folded
  away, `workflow-dir` regrouped under **state**, and the `state` group keeps only the read-only
  **handoff-integrity** check. `cache._SUBDIRS` was promoted to public **`cache.SUBDIRS`**.
- **Dropped the vestigial `interactive` param** from `run_doctor`/the command. doctor's fixes are
  non-destructive (re-converge marker-blocks; seed *missing* config only via `force=False`), so it
  **never prompts** — the plan's `interactive` plumbing was dead.
- **`info` glyph is `•`, not `ℹ`** (ruff `RUF001` ambiguous-unicode; no Phase-0 check emits `info`).

**The SSOT, concretely.** `init.managed_convergences(root, self_repo)` is the literal shared list:
`run_init` iterates it with `apply=True`; doctor's `_managed_checks` calls each with `apply=False`
(empty ⇒ ok) and `--fix` re-runs the failing one with `apply=True`. Each `ManagedConvergence` carries
`covers` (the capability names it verifies), which the **coherence-guard** test consumes to prove no
required capability is left unchecked.

**Deps:** **none added.**

**Implementation notes (easy-to-forget, for later turns):**
- The dry-run converge helpers are **side-effect-free** under `apply=False` (no `mkdir`; only
  `write_text`/`mkdir` when `apply=True`) — so doctor verification never mutates the repo.
- doctor reaches into init via the public `init.managed_convergences` plus two privates
  (`init._is_self_repo`, `init._converge_config`) — module-qualified to signal the reach.
- **The config check never content-diffs** (present + `tomllib`-parses); its fixer re-seeds *missing*
  files only (`_converge_config(..., force=False)`), so a present/edited config is never clobbered.
- **No silent pass:** `_managed_checks` wraps the dry-run in `try/except UserFacingCliError` → a
  malformed `.pi/settings.json` becomes a **fail** (with the parse error in `detail`), never a silent
  `ok`; github `GitHubError` → `warn`.
- **Pure/impure split:** `report_to_dict` and `doctor_cmd._render` are tested against synthetic
  `Check` lists with **zero monkeypatch** (the `verify=False` seam covers the impure groups).
- `report_to_dict` returns `dict[str, object]`, so test code must narrow (`isinstance(x, list)`) before
  `len()` (ty `invalid-argument-type`).

**Contract reconciliation (`shared/contracts.md`, per §2).** New **§8.6** documents the doctor machine
surface (exit codes incl. the report-don't-refuse divergence, the non-fatal-GitHub + no-silent-pass
rules, the `--json` object, the six groups); the §8.5 capability-inventory note now marks the
`verify()` side **implemented (T6)**.

**Still deferred (unchanged):** session-`perk:workflow-state` ↔ GitHub coherence (Phase 1 spine);
`doctor workflow` CI smoke (Phase 3 — the group seam is in place); the `allow_modified` drift
allowlist (until perk manages a whole user-customizable file); real legacy migrations (`_MIGRATIONS`
ships empty); the capability `add`/`remove`/`list` CLI + `Capability` ABC (until an optional
capability exists).

**Verify:** `bash scripts/verify-t6.sh` (8/8 PASS), `just verify` (t1–t6 ALL PASS), `just ci` green
(ruff + biome + ty + tsc + 79 pytest + 11 node:test).
