# Phase 2 · Turn 4 — in-process read-only SDK session (context-isolation primitive #1)

> Implementation-level plan for **P2.T4** — the perk-owned, in-process context-isolation primitive:
> a deterministic, fully-isolated read-only child spun at the SDK level via `createAgentSession`,
> plus the handoff contract (cap model-visible output, keep the full result in a verified scratch
> file + structured block, return double-delivery) that the spawned shape (T6) will also honor.
> Substrate only — the consumer is the read-only CI executor (T5). No registry stage, no door
> change, no cross-CLI behavior.

The canonical plan (the corrections, key-changes list, test plan, and assumptions) is GitHub plan
issue **#9**. This doc records the prior-art pass and the **outcomes**.

---

## 1. Prior-art pass (what exists, what we copy)

- **`examples/sdk/05-tools.ts`** — the read-only recipe `tools: ["read","grep","find","ls"]`. T4's
  `SDK_READ_ONLY_TOOLS` is exactly this set (no `bash`), distinct from T1's in-session
  `READ_ONLY_TOOLS` (which sub-allowlists `bash`).
- **`examples/extensions/subagent/index.ts`** — caps model-visible output at
  `PER_TASK_OUTPUT_CAP = 50 * 1024` while keeping the full result in details, and extracts the
  child's final text via a last-assistant-text scan (`getFinalOutput`). T4 mirrors both:
  `DEFAULT_MODEL_VISIBLE_CAP` + `capForModel` (the byte-trim loop) and `extractFinalAssistantText`.
- **`extension/testing/harness.ts` (`loadPerkSession`)** — the established offline recipe:
  `DefaultResourceLoader` + `await loader.reload()` before `createAgentSession`, a throwaway temp
  `agentDir` via `mkdtemp`, `SessionManager.inMemory`, `SettingsManager.inMemory({compaction:off,
  retry:off})`, keyless `getModel`, never prompting. `createReadOnlySession` follows the same shape
  but with the `no*` lock-down flags instead of `extensionFactories: [perk]`.
- **`extension/cache.ts`** — `runScratchDir`/`workflowDir` for the run-scoped scratch path.

## 2. Outcomes (as-built)

- **Isolation via the `no*` flags, not `extensionFactories: []` (the corrected substantive
  change).** `createReadOnlySession` builds the child loader with
  `noExtensions/noSkills/noPromptTemplates/noThemes/noContextFiles`, then `await loader.reload()`
  (a custom loader is not auto-reloaded by `createAgentSession`). This keeps perk's own extension
  out of the child (so no `session_start`/`turn_end` handlers fire, and the path is offline) — the
  read-only safety would hold regardless via the tools allowlist, but the determinism/offline
  guarantees come from the flags. `agentDir` is a throwaway `mkdtemp` under `tmpdir()`.
- **Two exports for two consumption shapes.** `createReadOnlySession` (the session factory, for
  T5's finer-grained loop control) and `runReadOnlyChild` (the one-shot handoff orchestrator). The
  orchestrator is offline-testable via an injectable `runTask`/`createSession` deps object; the real
  SDK read-only guarantee is proven separately and offline via `getActiveToolNames()` with no
  `prompt()`, run with API-key envs unset.
- **Handoff contract = double-delivery + route-don't-relay + write→verify→pass-path.**
  `runReadOnlyChild` resolves a scratch path (run-scoped `<step|"child">.md` when a `runId` is
  given, else a `mkdtemp` dir under `.pi/workflow/scratch`), runs the task, writes the full raw
  output, verifies it with `existsSync`, caps the model-visible output into `prose`, and returns
  `ChildHandoff { success, prose, structured, scratchPath }`. The raw output never enters the
  parent beyond the cap — only the path/summary does.
- **Fail loud + fail closed.** `runReadOnlyChild` never throws to the parent: on session-create/task
  throw, a failed scratch-verify, or an aborted signal, it returns
  `{ success:false, scratchPath:null }` with the error in **both** `prose` and `structured.error`.
  The session is always `dispose()`d in `finally`.
- **Typing note.** `model?: Model<Api>` (both `Model` and `Api` imported from `@earendil-works/pi-ai`)
  — `createAgentSession` takes `Model<any>`; `Model<Api>` satisfies its constraint cleanly without
  a bare `any`.
- **Verify gate.** `scripts/verify-p2-t4.sh` (offline): the test suite green, the `createAgentSession`
  + lock-down-flags + `loader.reload` wiring grep, an offline assertion that `SDK_READ_ONLY_TOOLS`
  excludes `bash`/`edit`/`write`, and the contracts amendment. Wired into `just verify` after
  `verify-p2-t2c.sh`.
- **Contract.** `shared/contracts.md` §8.3 gained the "In-process read-only child sessions (P2.T4)"
  amendment locking the shared handoff shape for T4 (in-process) and T6 (spawned).
- **Deferrals.** Whether/how to add a gated `bash` to the child's allowlist, and the placement of
  `structured` into a forking-safe tool `details`, are T5's to own. No registry stage / door work in
  this turn.
