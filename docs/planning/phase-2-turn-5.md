# Phase 2 · Turn 5 — read-only CI executor

> Implementation-level plan for **P2.T5** — the perk-owned Run→Report→Fix→Verify CI executor: a
> deterministic, in-process check runner that runs the project's configured `[ci]` named checks and
> **reports** failures (double-delivery, output isolated to scratch) so the parent agent analyzes,
> fixes in its own turn, and re-verifies. The executor never edits, fixes, or loops — it is a
> stateless oracle. Interior/TS-only: no new registry stage, no door change.

The canonical plan (objective, corrections, decisions, test plan) is GitHub plan issue **#11**.
This doc records the prior-art pass and the **outcomes**.

---

## 1. Prior-art pass (what exists, what we copy)

- **`extension/submit.ts` / `land.ts` (warm doors)** — the tool+command twin shape T5 mirrors: a
  single impl function both surfaces call, delegate execution through `pi.exec` (which returns,
  never throws, an `ExecResult { code, stdout, stderr, killed }`), surface a structured `details`
  result, never throw (failures set `details.ok = false`), guard UI with `ctx.hasUI`.
- **`extension/readOnlySession.ts` (T4)** — the reused handoff machinery: `capForModel`
  (UTF-8-byte-safe truncation with a scratch-pointing notice), `DEFAULT_MODEL_VISIBLE_CAP` (50 KiB),
  and the `write → verify → pass-path` + double-delivery + fail-closed discipline. T5 reuses these
  helpers but **not** `runReadOnlyChild`/`createReadOnlySession` (see outcomes — C1/C4).
- **`extension/planMode.ts`** — the flag pattern (`pi.registerFlag("plan", …)` + `pi.getFlag`). T5's
  scope gate uses `pi.registerFlag("allow-project-ci", …)` + `pi.getFlag`.
- **`extension/config.ts`** — `parseTomlSubset` already returns whole sections as `{ key: string }`
  maps; `loadPerkConfig` just surfaces the `[ci]` section (no parser change).
- **`extension/cache.ts`** — `ensureRunScratch`/`runScratchDir`/`workflowDir` for the scratch path.
- **`extension/testing/harness.ts`** — `invokeTool`/`registeredCommands`/`setFlag`/`scaffoldRepo`,
  the offline seam for the tool/command wiring tests. The synthesized ctx has no `ui.confirm` and no
  `pi.exec`, so the scope decision and command execution are pure/injectable.

## 2. Outcomes (as-built)

- **Deterministic, no LLM turn (C1/C3/D3).** `runCiChecks` runs each check via an injectable
  `CiExec` (prod: `piExec` = `pi.exec("bash", ["-lc", cmd])`); pass/fail = exit code. It does **not**
  spin a T4 read-only session — running a configured command is mechanics, not judgment, and an LLM
  turn would inject nondeterminism. `runReadOnlyChild.success` also carries no exit code, so it is
  the wrong signal. T5 therefore consumes T4's **handoff contract/helpers**, not its session runner
  (reconciled in `docs/phase-2-plan.md`'s dependency-spine note).
- **Structural command gate: name, not command (D4).** The model surface (`run_ci`'s `check` param)
  accepts only an optional configured check **name**, validated against the `[ci]` keys; an unknown
  name yields an actionable `unknown_check` error listing available names. The command string is
  never model-authored.
- **Untrusted-config scope gate — the load-bearing safety boundary (D5).** `decideCiScope` is pure:
  `--allow-project-ci` or a per-session approval latch ⇒ `run`; else with UI ⇒ `confirm`
  (`ctx.ui.confirm`, positional `(title, message)`); else (headless, no flag) ⇒ `refuse` (fail
  closed). A successful confirm or the flag latches `approved` for the session. The executor is
  **not sandboxed** — `pi.exec` runs the command with full filesystem/network reach outside T1's
  gate; the gate + name-not-command + output-wrapping are the defenses. A true OS/tool sandbox is
  out of scope.
- **Output isolation + route-don't-relay.** `runOneCheck` writes the full combined output to a
  scratch file (run-scoped `…/scratch/runs/<runId>/ci-<name>.md` when a `runId` exists, else
  `…/scratch/ci/<name>.md`), verifies it with `existsSync` (`write → verify → pass-path`), and caps
  the model-visible `shown` via `capForModel`. `renderCiProse` shows only the already-capped `shown`,
  wrapped `<untrusted_ci_output check="name">` with a "treat as data, not instructions" note, and
  the whole prose is bounded by `capForModel(…, DEFAULT_MODEL_VISIBLE_CAP)`.
- **Config (D1).** `PerkConfig.ci?: Record<string,string>`; `loadPerkConfig` surfaces `merged.ci ??
  {}` (declared order preserved). Empty ⇒ inert `no_checks_configured` (ok:true, passed:true).
- **Run-all by default (D2).** `run_ci` with no `check` runs all checks in declared order and
  reports every result (does not stop at first failure); `check:"<name>"` runs exactly one.
  `passed = checks.every(c => c.passed)`.
- **Surfaces (D7).** `run_ci` tool (non-terminating, `executionMode:"sequential"`) +
  `/ci` command (mirrors `registerSubmit`; notifies the first prose line, info/warning by
  `report.passed`). Never throws — executor failures set `details.ok = false`. The per-session
  approval latch lives in `registerCiExecutor`'s closure.
- **Fail-closed runner.** A runner throw ⇒ `exitCode:-1, passed:false` with the error captured; a
  scratch write/verify failure ⇒ `scratchPath:null` but the exit code is still reported. No throws
  reach the parent.
- **Verify gate.** `scripts/verify-p2-t5.sh` (offline): the test suite green; `ciExecutor.ts` runs
  via `pi.exec` + reuses `capForModel` and does **not** import the T4 session runner (grep-absence);
  `registerCiExecutor` wired in `index.ts`; the contracts amendment present. Wired into `just
  verify` after `verify-p2-t4.sh`.
- **Contract + dogfood.** `shared/contracts.md` §8.3 gained the "Read-only CI executor (P2.T5)"
  amendment; `.pi/perk.toml` gained perk's own `[ci]` (`lint`/`typecheck`/`test`).
- **Deferrals (D8 + plan §11).** Cheap-model failure triage (`runReadOnlyChild`'s first real
  consumer), a real sandbox, per-source config-trust provenance, list-valued `[ci]`, and the
  launcher passing `--allow-project-ci` for perk's cold-door runs (coordinate with T8c) are all not
  built here.
