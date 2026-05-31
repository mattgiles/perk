# Phase 0 · Turn 5 — Complete & harden `perk init`

> Implementation-level plan for **T5**. Finishes the init spine begun in T1 (settings + borrowed
> packages) and extended in T4 (config + `.gitignore`): adds **environment + GitHub verification**,
> a **capability inventory**, the **flags**, the **post-init handoff**, and the **supervisor `--json`
> surface** — so a single `perk init` *fully converges* a repo. **Python-only**; **no new dependency**.

---

## 1. Objective & the gate

**Objective.** Make `perk init` the **single convergence command** for a repo. On a fresh clone it
verifies the environment, scaffolds/syncs every managed piece, verifies GitHub readiness (without
mutating), and fires a post-init handoff; on an already-initialized repo it is a no-op; `--force`
re-seeds the user-editable config; `--no-interactive` / `--json` give CI and supervisors a stable
surface.

**Acceptance gate (from `phase-0-plan.md` §T5).** `perk init` on a fresh repo verifies env,
installs/scaffolds every managed piece, and fires the handoff; on an init'd repo it is a no-op;
`--force` re-seeds config while preserving everything else; `--no-interactive` / `--json` behave;
GitHub is **verified, never mutated**.

**Non-goals (T5).** No TS work (the gateway's TS plane is Phase 1); no GitHub *mutation* (Q9 —
verification-only; the first label is created lazily by `/plan-save` in Phase 1); no `perk doctor`
(T6); no capability `add`/`remove` CLI or installed-optional state file (no optional capability
exists yet).

---

## 2. Grounding & doc lineage (what governs T5)

- **`docs/phase-0-plan.md` §T5** — the deliverables + gate this turn discharges.
- **`shared/contracts.md` §8.4** — *"the gateway verification ops in **T5** (Python)."* `check_auth()`
  / `check_repo_access()` shapes are locked there; T5 authors the Python implementation. Mutation ops
  remain named-only. **`§8.1`** — the handoff tier (this turn adds the *agent-readable* post-init
  handoff, distinct from the T3/T4 machine run-handoff JSON).
- **`docs/PRIOR_ART.md` §9** + **`.prior-art/erk/docs/learned/architecture/capability-system.md`** —
  the capability model (required-vs-optional, self-vs-consumer filtering). PRIOR_ART §9's verdict:
  *"Pi's package/resource model already covers much of capabilities"* → port the **core split**, not
  the ABC/lifecycle machinery.
- **`docs/cli-vs-pi.md` §3.2** — the supervisor surface: `--json` to stdout + stable exit-code /
  `{success, error_type, message}` semantics, **only** on commands a supervisor drives (`init`,
  `doctor`). Not an agent affordance; no `schema`/MCP.
- **`docs/python-cli-guidelines.md` §7** — `user_output`→stderr / `machine_output`→stdout; the
  three-layer command structure; `UserFacingCliError` + `Ensure`.
- **erk `src/erk/cli/commands/init/main.py`** — the step structure (repo verify → project setup →
  optional enhancements) and the **`prompt-hooks/post-init.md` handoff** pattern perk adapts.
- **`Q9`** (GitHub verification-only; lazy labels), **`Q13`** (config split).

---

## 3. Prior-art pass — sharpenings folded in

1. **erk's init is heavyweight + interactive; perk's is convergent + declarative.** erk needs
   `--upgrade` because its plain init *skips* an already-erkified repo. perk's init **always
   converges**, so plain `perk init` *is* erk's upgrade → **collapse `--upgrade`** (D2).
2. **PRIOR_ART §9 — Pi packages ≈ capabilities** → a **lightweight code-level inventory**, no
   `state.toml`, no ABC, no `add`/`remove` CLI (D1).
3. **§8.4 — verification-only, never mutate**; first label is lazy in Phase 1 (Q9) → the Python
   gateway is exactly `check_auth` + `check_repo_access` (D4).
4. **capability-system.md — self-vs-consumer filter** (`None` = all, inside the tool's own repo; a
   frozenset = consumer) → perk's existing `_is_self_repo` drives the same filter (D1).
5. **cli-vs-pi §3.2 — `--json` is for machines that *launch* perk, never the agent perk launches**
   → `init --json` is a supervisor surface; **no `schema`/MCP** (D5).
6. **erk `prompt-hooks/post-init.md`** — the "write a markdown, then tell the agent to read+execute
   it" handoff → perk's `post-init.md` on-ramp, kept **true to what's built** (D6).
7. **erk init Step 1 (repo verify) + `shell.get_installed_tool_path`** → `perk/env.py` presence
   checks via `shutil.which`; the one real version gate is **`node ≥ 22`** (extension type-stripping)
   (D7).
8. **§8.4 "one contract per plane"** — the Python gateway mirrors the §8.4 shapes so the TS plane can
   conform in Phase 1; `require_github` is the strict DI binding (Phase-1+ consumers), while
   `init`/`doctor` call the `check_*` functions directly to *report* (D4).

---

## 4. Repo additions (end of T5)

```
perk/
├── github.py                       # NEW — gh-shelling verification gateway (check_auth, check_repo_access)
├── env.py                          # NEW — environment checks (git/gh/node>=22/pi; shutil.which)
├── capabilities.py                 # NEW — declared managed-piece inventory (required/scope); SSOT for init (+T6 doctor)
├── init.py                         # CHANGED — verify→converge→verify-gh→handoff; InitReport; flags
├── _resources.py                   # CHANGED — load the bundled post-init template
├── cli/
│   ├── context.py                  # CHANGED — + require_github (strict binding)
│   ├── ensure.py                   # CHANGED — UserFacingCliError gains optional error_type (for --json)
│   └── commands/init_cmd.py        # CHANGED — --force/--no-interactive/--json; render InitReport; exit codes
├── templates/post-init.md          # NEW — bundled handoff template (the dogfood on-ramp)
shared/contracts.md                 # CHANGED — §8.4 verification ops → implemented (Python); init --json/exit-code contract; capability-inventory note
tests/
├── test_github.py                  # NEW — faked gh: check_auth/check_repo_access + require_github raises
├── test_env.py                     # NEW — tool presence + node-version parse
├── test_capabilities.py            # NEW — inventory shape + self/consumer filter
├── test_init_t5.py                 # NEW — verify/flags/json/handoff/idempotency (or extend test_init_idempotent.py)
scripts/verify-t5.sh                # NEW — the T5 hard gate
justfile                            # CHANGED — verify runs t1..t5
```

`pyproject.toml` / `package.json` **unchanged** (no new dep; no TS).

---

## 5. Locked choices (D1–D7, all agreed)

1. **D1 — Lightweight capability inventory.** `perk/capabilities.py` declares the managed pieces
   with `required: bool` + `scope` (Phase 0: all required); init reports against it and T6 doctor
   reuses it. **Deferred:** installed-optional state file, `Capability` ABC, `add`/`remove` CLI
   (until the first optional capability exists).
2. **D2 — Collapse `--upgrade`.** Default `perk init` *is* the convergent upgrade. Flags = `--force`
   (re-seed config), `--no-interactive` (never prompt; auto when no TTY), `--json` (supervisor).
3. **D3 — Verification strictness.** Required **tooling** missing → **hard fail** (exit 2 +
   remediation). GitHub **auth** missing (binary present) → **verify, report, non-fatal**. **Never
   mutate** GitHub.
4. **D4 — `require_github` placement.** `github.py` = the gh-shelling SSOT (verification-only);
   `require_github(ctx)` = the strict DI binding for Phase-1+; init/doctor call `check_*` to report.
5. **D5 — Structured `InitReport` + `--json` + stable exit codes** (0 ok / 1 invalid-input / 2
   env-not-ready) and an `error_type` vocabulary.
6. **D6 — Post-init handoff** = a bundled `post-init.md` (true-to-built), written to
   `.pi/workflow/post-init.md`; the final output points the agent at it. The T7 dogfood on-ramp.
7. **D7 — Env checks** = presence of `git`/`gh`/`node`/`pi`; one version gate **`node ≥ 22`**.

---

## 6. Work breakdown (ordered)

### T5.a — `perk/github.py` (the verification gateway)
Frozen dataclasses mirroring §8.4; `gh`-shelling with `check=False` + `timeout`; **never mutates**.
```python
@dataclass(frozen=True)
class AuthStatus:  ok: bool; user: str | None; scopes: tuple[str, ...]; error: str | None
@dataclass(frozen=True)
class RepoAccess:  ok: bool; repo: str | None; can_push: bool; error: str | None
class GitHubError(Exception): ...          # gh binary missing / unparseable output

def check_auth() -> AuthStatus:
    # `gh auth status` (rc 0 ⇒ authed). user via `gh api user --jq .login`;
    # scopes parsed from the "Token scopes:" line. error = stderr when rc != 0.
def check_repo_access(repo_root: Path) -> RepoAccess:
    # `gh repo view --json nameWithOwner,viewerPermission`; can_push =
    # viewerPermission in {WRITE, MAINTAIN, ADMIN}. Not-found / no-remote ⇒ ok=false.
```
`gh` binary absent ⇒ `GitHubError` (env.py reports it as a missing tool; the gateway never silently
no-ops). Parse defensively (jq where available) for cross-version stability.

### T5.b — `perk/env.py` (environment checks)
```python
@dataclass(frozen=True)
class EnvCheck:  name: str; ok: bool; detail: str; remediation: str
def check_environment() -> list[EnvCheck]:
    # presence via shutil.which for git, gh, node, pi;
    # node ≥ 22 via `node --version` (parse vMAJOR; defensive).
def required_tools_ok(checks) -> bool   # gate for exit-2 (missing required tool)
```

### T5.c — `perk/capabilities.py` (the inventory — pure metadata)
```python
@dataclass(frozen=True)
class Capability:  name: str; summary: str; required: bool; scope: Literal["both","self","consumer"]
CAPABILITIES: tuple[Capability, ...] = (
    Capability("perk-extension",  "perk's own Pi extension",            required=True, scope="both"),
    Capability("borrowed-packages","crossover scaffolding (plan/diff/status/todo)", required=True, scope="both"),
    Capability("settings-wiring", ".pi/settings.json package entries",  required=True, scope="both"),
    Capability("workflow-dir",    ".pi/workflow/ cache layout",         required=True, scope="both"),
    Capability("config",          ".pi/perk.toml + perk.local.toml",    required=True, scope="both"),
    Capability("gitignore-block", "managed .gitignore entries",         required=True, scope="both"),
    Capability("agents-block",    "managed AGENTS.md conventions",      required=True, scope="both"),
)
def applicable(self_repo: bool) -> tuple[Capability, ...]   # scope filter; Phase 0 = all
```
Pure data: no behavior coupling. init reports against it; **T6 adds `verify(root) -> CheckResult`**.
The `required`/`scope` fields are declared and Phase-0-uniform — the rail optional capabilities +
consumer-only pieces ride later (honest rail-laying, not fiction).

### T5.d — `perk/cli/ensure.py` (error_type)
`UserFacingCliError` gains an optional `error_type: str | None = None` so `--json` can surface a
stable code. `_converge_settings` raises `error_type="invalid_settings"`; config parse →
`"invalid_config"`.

### T5.e — `perk/cli/context.py` (`require_github`)
```python
def require_github(ctx: click.Context) -> AuthStatus:
    auth = github.check_auth()
    if not auth.ok:
        raise UserFacingCliError("GitHub not authenticated\nRun: gh auth login",
                                 error_type="github_unauthed")
    return auth
```
Strict binding for Phase-1+ commands; **init does not route through it** (init reports via `check_*`).

### T5.f — `perk/init.py` (the pipeline + flags)
Refactor `run_init` to return an **`InitReport`** and add flag params. Pipeline (§7). Converge
functions are unchanged; the report is built **against `CAPABILITIES`**.

### T5.g — `perk/templates/post-init.md` + `_resources.py`
Bundle the handoff template; `init` writes it to `.pi/workflow/post-init.md` with `{repo}`/`{mode}`
substitutions. Content stays true to what's built (§6 below / D6).

### T5.h — `perk/cli/commands/init_cmd.py` (render + exit codes)
`--force/--no-interactive/--json`; render `InitReport` (human→stderr, `--json`→stdout); map
`error_type`→exit code; in `--json` mode, catch `UserFacingCliError` and emit a JSON error object too
(the supervisor always gets JSON).

### T5.i — `shared/contracts.md`
§8.4 verification ops → **implemented (Python)**; add the **init `--json`/exit-code contract** (codes
+ `error_type` vocab) and a one-line **capability-inventory** note.

### T5.j — `scripts/verify-t5.sh` + `justfile`
The hard gate (§10); `just verify` runs t1..t5.

---

## 7. The init pipeline (the locked design)

```python
def run_init(root=None, *, force=False, interactive=True) -> InitReport:
    root = (root or Path.cwd()).resolve()
    env = check_environment()
    if not repo_root(root):                       # not a git repo
        return InitReport.env_failure("not_a_repo", "Run inside a git repository", env)
    if not required_tools_ok(env):                # missing git/node>=22/pi/gh binary
        return InitReport.env_failure("missing_tool", "Install the missing tool(s)", env)

    self_repo = _is_self_repo(root)
    changes: list[str] = []
    _converge_settings(root, self_repo, changes)  # may raise UserFacingCliError(invalid_settings)
    _converge_workflow_dir(root, changes)
    _converge_config(root, changes, force=force)  # force ⇒ re-seed templates (confirm if interactive)
    _converge_gitignore(root, changes)
    _converge_agents(root, changes)

    auth = github.check_auth()                    # verify only — never mutate
    repo = github.check_repo_access(root) if auth.ok else RepoAccess.skipped()
    handoff = _write_post_init(root, self_repo)   # .pi/workflow/post-init.md

    return InitReport(ok=True, mode="self" if self_repo else "consumer",
                      env=env, github=GitHubReport(auth, repo),
                      changes=changes, handoff=handoff)
```

**Flag semantics.** Default = convergent upgrade. `--force` re-seeds the seeded-once config
(confirmed via `user_confirm` unless `--no-interactive`). `--no-interactive` ⇒ never prompt
(auto-implied when `sys.stdout`/stderr is not a TTY).

**`--json` shape** (stdout, one object):
```json
{ "success": true, "mode": "consumer", "error_type": null, "message": null,
  "env":    [ { "name": "node", "ok": true, "detail": "v22.19.0", "remediation": "" }, … ],
  "github": { "auth": { "ok": false, "user": null, "scopes": [], "error": "not logged in" },
              "repo": { "ok": false, "repo": null, "can_push": false, "error": "skipped" } },
  "changes": [ "settings-wiring: added @perk/pi…", … ],
  "handoff": ".pi/workflow/post-init.md" }
```

**Exit codes (D5).** `0` converged · `1` invalid input (`invalid_settings`/`invalid_config`, the
`UserFacingCliError` path) · `2` environment-not-ready (`not_a_repo`/`missing_tool`). GitHub-unauthed
is **non-fatal** in `init` (reported, exit 0); `github_unauthed` is reserved for the strict
`require_github` path. In `--json` mode the report is emitted on every path, including errors.

**Human render.** Step-style stderr output (env ✓/✗ with remediation, converged pieces, GitHub
readiness, then *"📋 Next: read and execute .pi/workflow/post-init.md"*).

---

## 8. The GitHub gateway + post-init handoff

**Gateway (§8.4 conformance).** `check_auth`/`check_repo_access` return the §8.4 field shapes as
typed dataclasses (the Python plane); the TS plane authors the same names + shapes in Phase 1, so
`doctor` can verify both and either can later swap `gh`-shell → API. **Verification-only**: no
`create_label`/`create_*` in T5 (those are named-only in §8.4, authored with their stage handlers).

**Post-init handoff (D6).** `templates/post-init.md` — written to `.pi/workflow/post-init.md`
(gitignored transient; regenerated each init). Content true to what's built, e.g.:

> # perk is initialized ({mode})
> This repo follows the **perk** plan-oriented workflow. Conventions: see `AGENTS.md`.
> The spine `plan → save → implement → submit → land → learn` is being built (Phase 1).
> **Cold-door launchers exist now:** `perk plan -- <pi args>` positions a worktree, mints a
> `run_id`, and launches a primed `pi` session. In-session stage handlers land in Phase 1.
> **Next:** when Phase 1 lands, start a plan here — this repo is the dogfood substrate.

This is the **T7 dogfood on-ramp** (plan Phase 1 on a freshly-init'd, doctor-healthy repo), not
decoration. It grows as the spine lands.

---

## 9. Capability inventory + self/consumer (D1)

`capabilities.py` is the **single inventory** of what `perk init` manages. T5 uses it to structure
init's report (`changes` cross-referenced to capability names); **T6 `doctor` reuses the same tuple**
and adds a `verify(root) -> CheckResult` per capability — exactly erk's "registry as SSOT for
artifact detection + health checks," minus the ABC/lifecycle. The **self-vs-consumer filter**
(`applicable(self_repo)`) mirrors capability-system.md's `None`-vs-frozenset filter; Phase 0 returns
the full set either way (all `scope="both"`), with the self-package entry (`..` vs `npm:@perk/pi@ver`)
already handled by `_desired_packages`.

**Deferred (flagged, not omitted):** installed-optional **state file**, `Capability` ABC with
`install`/`uninstall`, `capability add`/`remove`/`list` CLI, backend-awareness. These are fiction
until the first *optional* capability exists. erk's interactive setup (statusline, Claude
permissions, global `~/.erk` config, backup cleanup) is **erk-specific and not ported**.

---

## 10. Acceptance gate — concrete, runnable checks (`scripts/verify-t5.sh`)

uv-only; temp git repos; CI-robust (GitHub verify is non-fatal, so checks assert the *report has a
github section*, not `ok=true`).

1. **Full convergence (fresh repo).** `perk init` in a temp git repo → exit 0; `.pi/settings.json`,
   `.pi/perk.toml`, `.pi/perk.local.toml`, `.pi/workflow/`, the `.gitignore` + `AGENTS.md` managed
   blocks, and `.pi/workflow/post-init.md` all present.
2. **`--json` shape.** `perk init --json` → stdout parses to `{success:true, mode:"consumer",
   env:[…], github:{auth,repo}, changes:[…], handoff:"…"}`.
3. **Idempotent re-run.** Second `perk init` → exit 0, `changes:[]` ("already converged").
4. **`--force` re-seeds config.** Mutate `perk.toml`, run `perk init --force --no-interactive`,
   assert it is restored to the template; managed blocks untouched.
5. **Env-not-ready.** `perk init` outside a git repo → **exit 2**, `error_type:"not_a_repo"`,
   remediation present; `--json` emits the error object.
6. **GitHub gateway unit.** Faked `gh` (monkeypatched subprocess): `check_auth` parses authed +
   unauthed; `check_repo_access` parses permission; **`require_github` raises `UserFacingCliError`
   (`github_unauthed`) when unauthed.**
7. **Unit suites.** `pytest test_github test_env test_capabilities test_init_t5` green.

`just verify` runs t1..t5; `just ci` stays green.

---

## 11. Risks & mitigations

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| `gh` output format drifts across versions | med | parse via `--json`/`--jq` where available; tolerate missing fields; `check=False` + defensive parse |
| `gh` unauthed in CI flakes the gate | med | GitHub verify is **non-fatal**; gate asserts the section exists, not `ok=true` |
| init refactor regresses T1/T4 idempotency | med | keep the `_converge_*` functions; the gate re-checks idempotency (check 3) + t1/t4 stay in `just verify` |
| capability inventory over-abstracts | low | **pure metadata**, no behavior; converge stays in init; verify deferred to T6 |
| `node`/`pi` absent in some envs misreports | low | presence via `shutil.which`; version parse defensive (missing ⇒ ok=false + remediation, never a crash) |
| `post-init.md` content drifts from reality | low | keep minimal + true-to-built; it references only shipped commands |
| `--json` inconsistent on the error path | low | init_cmd emits a JSON error object for `UserFacingCliError` too (error_type threaded) |

---

## 12. Explicitly out of scope for T5 (pointers)

- **TS GitHub gateway** + in-session mutations — **Phase 1** (§8.4).
- **GitHub mutation ops** (`create_label`/`create_*`/`merge_pr`/…) — authored with their stage
  handlers, **Phase 1+** (Q7/Q9).
- **Capability `add`/`remove`/`list` CLI + installed-optional state file + `Capability` ABC** —
  until the first optional capability exists.
- **`perk doctor`** (the verify() side of the inventory; `--fix`; dual-mode) — **T6**.
- **erk-specific init** (statusline, Claude permissions, global `~/.erk` config, backup cleanup,
  interactive label setup) — **not ported** (Pi-native + lazy-in-Phase-1).

---

## 13. Open questions settled (D1–D7)

1. **Capability sizing (D1)** — lightweight metadata inventory; defer state-file + ABC + add/remove.
2. **Flags (D2)** — drop `--upgrade` (default *is* upgrade); keep `--force`/`--no-interactive`/`--json`.
3. **Verification strictness (D3)** — tooling fatal (exit 2); GitHub auth non-fatal (report); never
   mutate.
4. **`require_github` (D4)** — `github.py` SSOT + strict `require_github` binding; init/doctor report
   via `check_*`.
5. **Machine surface (D5)** — `InitReport` + `--json`; exit codes 0/1/2; `error_type` vocab
   (`not_a_repo`, `missing_tool`, `invalid_settings`, `invalid_config`, + reserved `github_unauthed`).
6. **Post-init handoff (D6)** — bundled `post-init.md` at `.pi/workflow/post-init.md`; true-to-built;
   T7 on-ramp.
7. **Env checks (D7)** — presence of git/gh/node/pi; one version gate `node ≥ 22`.

---

## 14. Definition of done

- `perk init` on a fresh repo verifies env, converges every managed piece, verifies GitHub (no
  mutation), writes `post-init.md`, and points the agent at it; re-run is a no-op.
- `--force` re-seeds config; `--no-interactive` never prompts; `--json` emits the stable report with
  correct exit codes on every path.
- `github.py` implements §8.4's verification ops; `require_github` is the strict binding (tested).
- `capabilities.py` declares the managed inventory (SSOT for init, ready for T6).
- `shared/contracts.md` updated (§8.4 → implemented; init `--json`/exit-code contract; inventory note).
- `scripts/verify-t5.sh` 7/7; `just verify` t1..t5 ALL PASS; `just ci` green; no new dep; no TS change.

---

## 15. T5 outcomes (recorded after implementation)

**Status: implemented; T5 hard gate 7/7 PASS; T1–T4 gates still PASS; `just ci` green.**

**Built (as planned):** `perk/github.py` (verification gateway), `perk/env.py` (tool/version
checks), `perk/capabilities.py` (inventory), `perk/cli/context.py` (+`require_github`),
`perk/cli/ensure.py` (`UserFacingCliError.error_type`), `perk/init.py` (refactored to the
verify→converge→verify-gh→handoff pipeline returning `InitReport`; `--force` re-seed), and
`perk/cli/commands/init_cmd.py` (`--force/--no-interactive/--json`, render, exit codes). Tests:
`test_github`, `test_env`, `test_capabilities`, `test_init_t5` (+ a `stub_env` conftest fixture).
`shared/contracts.md` §8.4→implemented + new §8.5; `scripts/verify-t5.sh`; `just verify` runs t1–t5.
**Python-only — no TS change; no new dependency** (`gh` shelled, `tomllib`/`shutil` stdlib).

**Gate results:** all 7 PASS — (1) full convergence on a fresh repo + `post-init.md`; (2) `--json`
shape; (3) idempotent re-run (`changes:[]`); (4) `--force` re-seeds config, `.gitignore` untouched;
(5) non-repo → exit 2 / `not_a_repo` / remediation; (6) github gateway (faked `gh`) + `require_github`
raises; (7) unit suites. Full suite **64 pytest + 11 node:test**.

**Decisions confirmed by building:**
- **D1–D7 all held.** The lightweight capability inventory, collapsed `--upgrade`, tooling-fatal /
  auth-non-fatal split, `github.py`+`require_github` placement, `InitReport`/exit-code surface,
  `post-init.md` on-ramp, and the `node≥22` gate all built as specified.
- **A `verify` seam was added to `run_init`** (not in the plan body): `verify=False` skips the
  external repo/tooling/GitHub shells so unit tests run pure convergence **without depending on an
  installed, authenticated toolchain** (CI may lack `pi`/`gh`-auth). The CLI always verifies
  (default). This is the testability counterpart to the gate's real-path check.
- **The post-init template is a module-level string constant** (`POST_INIT_TEMPLATE` in `init.py`),
  not a bundled `templates/post-init.md` file as the plan sketched — consistent with the existing
  `PERK_TOML_TEMPLATE`/AGENTS-block pattern, and avoids packaging a data file. `_resources.py`
  was therefore **not** touched.
- **`require_github(ctx)` validates the context** (`_perk(ctx)`) for DI uniformity even though it
  only needs `check_auth()` — so `ctx` isn't a dead parameter.

**Deps:** **none added.**

**Implementation notes (easy-to-forget, for later turns):**
- `init.py` imports `env`/`github` **as modules** (`from perk import env, github`) and calls
  `env.check_environment()` / `github.check_auth()` — so tests patch the *module attribute*
  (`monkeypatch.setattr(env_mod, "check_environment", …)`) and the patch is seen at call time. The
  `stub_env` fixture relies on this.
- **Click 8.4 separates streams** in `CliRunner` (no `mix_stderr`): `result.stdout` is the `--json`
  object, `result.stderr` the human text. Parse `result.stdout`.
- The repo check runs **before** the tool gate, so `not_a_repo` wins over `missing_tool` (lets the
  non-repo gate check be toolchain-independent).
- `post-init.md` lives at `.pi/workflow/post-init.md` and is **gitignored** (added to the managed
  block); it is regenerated each init (idempotency holds — same content).
- **Forward-converged the T1/T4 gates:** `perk init` now requires a git repo, so `verify-t1.sh`
  (checks 2/4) gained `git init -q` + excludes `.git/` from the idempotency snapshot; the human
  "already converged" line changed case, so T1/T4 greps became `grep -qi`.

**Contract reconciliation (`shared/contracts.md`, per §2).** §8.4 marked **implemented (Python)** with
`require_github` semantics; the §8.4 Status note gained a T5 line; **new §8.5** documents the `init`
machine surface (exit codes, `error_type` vocab, the `--json` object, the post-init handoff, and the
capability inventory).

**Still deferred (unchanged):** the TS GitHub gateway + in-session mutations (Phase 1); GitHub
mutation ops (Phase 1+); the capability `add`/`remove`/`list` CLI + installed-optional state file +
`Capability` ABC (until an optional capability exists); `perk doctor` + the inventory's `verify()`
side (T6); erk-specific init bits (statusline, Claude permissions, global config, backup cleanup).

**Verify:** `bash scripts/verify-t5.sh` (7/7 PASS), `just verify` (t1–t5 ALL PASS), `just ci` green
(ruff + biome + ty + tsc + 64 pytest + 11 node:test).
