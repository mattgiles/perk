// Live warm-surface tests for the ready + handoff bindings (pi/v1/delivery/ready.ts): the
// frozen registration baselines (tool + command), the full-details WIRE baselines captured from
// the pre-migration door (byte-exact on the JSON round-trip — the true wire shape, optional-key
// absence semantics included), the all-or-nothing cohort-drop matrix through the registered
// tool, the full-cohort continuation pin (stamp-facts-only message + ONE injected drive), the
// exact refusal-warning bytes through registered surfaces, the delivery-mode matrix over the
// exported continuation seam (the streaming `followUp` arm is unreachable through the idle
// harness), and the command report-before-drive order pin. OFFLINE — no LLM / network / gh /
// Python; a fake `perk` (PERK_BIN) stands in for the GitHub mark-ready.

import assert from "node:assert/strict";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { type ReadyHandoff, type ReadyOutcome, readyChange } from "../../../delivery/ready.ts";
import {
  fakePerk,
  loadPerkSession,
  scaffoldRepo,
  spyInjections,
} from "../../../testing/harness.ts";
import { driveReadyContinuation } from "./ready.ts";

const SHA_A = "a".repeat(40);
const SHA_B = "b".repeat(40);

const READY_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  pr: { number: 42, url: "https://gh/o/r/pull/42" },
  was_draft: true,
});

function stackedJson(over: Record<string, unknown> = {}): string {
  return JSON.stringify({
    success: true,
    error_type: null,
    message: null,
    pr: { number: 42, url: "https://gh/o/r/pull/42" },
    was_draft: true,
    dry_run: false,
    stacked: true,
    objective: "500",
    node: "1.2",
    stamped_head: SHA_B,
    stamp_advanced: true,
    reconcile_notice: "the ready-time reconcile pass was not launched",
    reconcile_retry: "perk ready 7",
    plan: "7",
    parent_checkpoint: SHA_A,
    ...over,
  });
}

const STACKED_READY_JSON = stackedJson();

/** Invoke the REAL registered ready tool against a fake cold door; JSON round-trip the result
 * (the true wire shape — optional keys carrying `undefined` drop exactly as they do on the
 * wire). `spyInjections` makes the full stacked cohort harness-safe: the drive injection is
 * captured instead of starting a model turn (harness invocations run idle). */
async function invokeReady(opts: { stdout: string; code?: number }) {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: opts.stdout, code: opts.code ?? 0 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const optionsSeen: unknown[] = [];
  const injected = spyInjections(h, optionsSeen);
  try {
    const result = await h.invokeTool("ready", {});
    const wire = JSON.parse(
      JSON.stringify({
        text: result.content[0]?.text,
        details: result.details,
        terminate: result.terminate ?? null,
      }),
    ) as { text: string; details: Record<string, unknown>; terminate: boolean | null };
    return { ...wire, injected, optionsSeen, notifies: [...h.notifies] };
  } finally {
    h.dispose();
  }
}

// --- frozen registration baselines (captured from the pre-migration door) ---------------------

const BASELINE_READY_TOOL = {
  name: "ready",
  label: "Mark PR ready",
  description:
    "Ready the active plan's PR. Incremental: mark the draft PR ready for review (the " +
    "deliberate review gate; submit keeps the PR draft). Stacked: the deliberate post-review " +
    "HUMAN handoff — stamps the exact verified published head (draft and non-draft PRs); " +
    "never routine post-submit choreography, never auto-run. Terminating: ends the turn.",
  parameters: { type: "object", additionalProperties: false, properties: {} },
  promptSnippet:
    "Ready the PR: open the draft for review (incremental) or record the post-review " +
    "handoff stamp (stacked; human-asked only). Terminates the turn.",
  promptGuidelines: [
    "For an incremental plan, call ready only when the PR is ready for human review; it marks the draft PR ready (the deliberate review gate). submit keeps the PR draft on purpose.",
    "For a STACKED plan, /ready is the deliberate HUMAN handoff made AFTER review + address: it stamps the exact verified published head into the delivery journal (draft and non-draft PRs alike), and the recorded stamp unblocks planning of the layer's direct dependents. Never call it as routine post-submit choreography — review happens on the draft layer PR; only invoke it when the human explicitly asks.",
    "ready operates on the active plan's worktree — it takes no arguments; the PR is discovered from the local plan-ref's branch. Idempotent: an already-ready PR is success, and a re-run converges on the same stamp.",
    "A failed stamp (error_type ready_stamp_failed) names its own remediation: the ambiguous/transient arms converge on re-run; deterministic failures need their named repair first.",
  ],
  executionMode: "sequential",
};

test("registration parity: ready tool + /ready command match the frozen baselines", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.deepEqual(
      h.registeredTool("ready"),
      BASELINE_READY_TOOL,
      "the COMPLETE ready registration surface must match the frozen baseline",
    );
    assert.deepEqual(h.registeredCommand("ready"), {
      name: "ready",
      description:
        "Ready the plan's PR: open the draft for review (incremental) or record the " +
        "post-review handoff stamp (stacked).",
    });
  } finally {
    h.dispose();
  }
});

// --- full-details wire baselines (captured from the pre-migration door) -----------------------

test("wire baseline: incremental, legacy absent-stacked form — terminating, no drive", async () => {
  const r = await invokeReady({ stdout: READY_JSON });
  assert.equal(r.text, "Marked ready: PR #42 is open for review.");
  assert.deepEqual(r.details, {
    ok: true,
    pr: { number: 42, url: "https://gh/o/r/pull/42" },
    was_draft: true,
  });
  assert.equal(r.terminate, true);
  assert.deepEqual(r.injected, [], "an incremental ready drives nothing, quietly");
});

test("wire baseline: incremental, the current worker's explicit stacked:false form", async () => {
  // The live worker emits `stacked: false` with null continuation fields (ready_cmd.py:
  // \"stacked=false, rest null\"); the false-vs-absent distinction is wire-visible — the
  // false value must round-trip while the null cohort fields stay dropped.
  const r = await invokeReady({
    stdout: JSON.stringify({
      success: true,
      error_type: null,
      message: null,
      pr: { number: 42, url: "https://gh/o/r/pull/42" },
      was_draft: true,
      dry_run: false,
      stacked: false,
      objective: null,
      node: null,
      stamped_head: null,
      stamp_advanced: null,
      reconcile_notice: null,
      reconcile_retry: null,
      plan: null,
      parent_checkpoint: null,
    }),
  });
  assert.equal(r.text, "Marked ready: PR #42 is open for review.");
  assert.deepEqual(r.details, {
    ok: true,
    pr: { number: 42, url: "https://gh/o/r/pull/42" },
    was_draft: true,
    stacked: false,
  });
  assert.equal(r.terminate, true);
  assert.deepEqual(r.injected, [], "an incremental ready drives nothing, quietly");
});

test('argv: the adapter delegates exactly ["pr", "ready", "--json"]', async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: READY_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeTool("ready", {});
    assert.deepEqual(readFileSync(argvFile, "utf8").trim().split("\n"), ["pr", "ready", "--json"]);
  } finally {
    h.dispose();
  }
});

test("wire baseline: the FULL stacked cohort — stamp facts + ONE injected drive", async () => {
  const r = await invokeReady({ stdout: STACKED_READY_JSON });
  assert.equal(
    r.text,
    `Marked ready: PR #42 is open for review. Handoff stamped: objective #500 node 1.2 at ${SHA_B}.`,
  );
  // Stamp facts ONLY in the terminating message: the continuation is announced by the drive,
  // after its refusal arms have accepted — never preemptively by the stamp gesture.
  assert.doesNotMatch(r.text, /[Cc]ontinuing|reconcile pass/);
  assert.deepEqual(r.details, {
    ok: true,
    pr: { number: 42, url: "https://gh/o/r/pull/42" },
    was_draft: true,
    stacked: true,
    handoff: {
      objective: "500",
      node: "1.2",
      stamped_head: SHA_B,
      stamp_advanced: true,
      plan: "7",
      parent_checkpoint: SHA_A,
    },
  });
  assert.equal(r.terminate, true);
  assert.equal(r.injected.length, 1, "exactly ONE injected drive turn");
  const content = r.injected[0] ?? "";
  assert.match(content, new RegExp(`${SHA_A}\\.\\.${SHA_B}`), "the pinned accepted range");
  assert.match(content, /objective #500/);
  assert.match(content, /plan #7/);
  assert.match(content, /gh pr view 42/);
  // The guidance deliberately names NO ready/land re-entry gesture (those tools are scoped
  // off in the objective stages this drive can land in — see stageTools.test.ts).
  assert.doesNotMatch(content, /\bready\b|\bland\b/);
  // The command:objective-reconcile binding suffix rides the same message (Mechanism B).
  assert.match(content, /perk-objective-reconcile/);
  // The harness invocation runs idle → the immediate arm (no delivery options).
  assert.deepEqual(r.optionsSeen, [undefined]);
  // The continuation announce is the drive's own info report, after acceptance.
  assert.ok(
    r.notifies.includes(
      `perk: ready — continuing into the ready-time reconcile pass — objective #500, ` +
        `pinned range ${SHA_A}..${SHA_B}`,
    ),
    "the drive announces the continuation exactly once accepted",
  );
});

test("wire baseline: re-stamp verbs (already ready / handoff already stamped) still drive", async () => {
  const r = await invokeReady({
    stdout: stackedJson({ was_draft: false, stamp_advanced: false }),
  });
  assert.equal(
    r.text,
    `Already ready: PR #42 is open for review. Handoff already stamped: objective #500 node 1.2 at ${SHA_B}.`,
  );
  assert.equal(r.injected.length, 1, "an existed=true re-stamp re-enters the pass");
});

// Each continuation-cohort field is independently load-bearing: a missing/wrong-typed value
// drops the cohort WHOLE (never half-rendered) while the `stacked` routing fact passes through
// — and the drive's mixed-version arm warns instead of driving.
const COHORT_DROPS: readonly { label: string; over: Record<string, unknown> }[] = [
  { label: "missing objective", over: { objective: undefined } },
  { label: "wrong-typed node", over: { node: 12 } },
  { label: "missing stamped_head", over: { stamped_head: undefined } },
  { label: "wrong-typed stamp_advanced", over: { stamp_advanced: "yes" } },
  { label: "wrong-typed plan", over: { plan: 7 } },
  { label: "null parent_checkpoint", over: { parent_checkpoint: null } },
];

test("wire baseline: each missing/wrong-typed cohort field drops the cohort whole", async () => {
  for (const { label, over } of COHORT_DROPS) {
    const r = await invokeReady({ stdout: stackedJson(over) });
    assert.deepEqual(
      r.details,
      {
        ok: true,
        pr: { number: 42, url: "https://gh/o/r/pull/42" },
        was_draft: true,
        stacked: true,
      },
      `${label}: the routing fact passes through; the cohort never half-attaches`,
    );
    assert.equal(r.text, "Marked ready: PR #42 is open for review.", label);
    assert.deepEqual(r.injected, [], `${label}: a dropped cohort drives nothing`);
    assert.ok(
      r.notifies.some((n) => /malformed/.test(n)),
      `${label}: the mixed-version arm warns loudly`,
    );
  }
});

// --- failure arms through the registered tool -------------------------------------------------

test("tool: a missing/failing worker fails loud-but-soft (no terminate)", async () => {
  const r = await invokeReady({ stdout: "", code: 1 });
  assert.equal(r.details.ok, false);
  assert.equal(r.details.error_type, "exec_failed");
  assert.notEqual(r.terminate, true, "a failed ready does not terminate");
  assert.deepEqual(r.injected, [], "a failed ready drives nothing, quietly");
});

test("tool: garbage worker output fails soft with bad_output", async () => {
  const r = await invokeReady({ stdout: "not json" });
  assert.equal(r.details.ok, false);
  assert.equal(r.details.error_type, "bad_output");
});

test("tool: success:true with a malformed pr fails as bad_output (unexpected payload)", async () => {
  const r = await invokeReady({
    stdout: JSON.stringify({
      success: true,
      error_type: null,
      message: null,
      pr: { number: 42, url: 12345 },
    }),
  });
  assert.equal(r.details.ok, false);
  assert.equal(r.details.error_type, "bad_output");
  assert.match(String(r.details.error ?? ""), /unexpected payload/);
});

// --- refusal warnings through registered surfaces (exact bytes; zero injections) --------------

test("tool: a malformed cohort warns with the exact mixed-version bytes", async () => {
  const r = await invokeReady({ stdout: stackedJson({ plan: undefined }) });
  assert.deepEqual(r.injected, []);
  assert.ok(
    r.notifies.includes(
      "perk: ready — ready-time reconcile pass not driven — the worker reported a stacked " +
        "stamp but its continuation facts were malformed (a mixed-version envelope?). The " +
        "handoff stamp stands; re-run /ready to enter the pass.",
    ),
    `expected the exact malformed-cohort warning; got: ${JSON.stringify(r.notifies)}`,
  );
});

test("tool: invalid evidence warns with the exact strict-validation bytes", async () => {
  // One representative corruption — the per-field matrix is feature-tier (delivery/ready.test.ts).
  const r = await invokeReady({ stdout: stackedJson({ stamped_head: "B".repeat(40) }) });
  assert.deepEqual(r.injected, []);
  assert.ok(
    r.notifies.includes(
      "perk: ready — ready-time reconcile pass not driven — the stamp evidence failed strict " +
        "validation (ids marker-safe; both diff-range endpoints full 40-hex lowercase). The " +
        "handoff stamp stands; re-run `perk ready 7` to enter the pass.",
    ),
    `expected the exact strict-validation warning; got: ${JSON.stringify(r.notifies)}`,
  );
});

test("/ready in a read-only session: the stamp stands, the drive refuses loudly", async () => {
  // A read-only-scaffolded session driving `/ready` the command — exactly production's
  // read-only gesture (the command is not a gated tool; the DRIVE refuses, not the stamp).
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const bin = fakePerk(cwd, { stdout: STACKED_READY_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    await h.invokeCommand("ready");
    assert.deepEqual(injected, [], "no drive into a read-only session");
    assert.ok(
      h.notifies.some((n) => /Handoff stamped/.test(n)),
      "the stamp gesture's own success line still lands",
    );
    assert.ok(
      h.notifies.includes(
        "perk: ready — ready-time reconcile pass not driven — this session is read-only (the " +
          "pass's write tools are gated off); exit the read-only session or run the pass from " +
          "a terminal. The handoff stamp stands; re-run `perk ready 7` to enter the pass.",
      ),
      `expected the exact read-only warning; got: ${JSON.stringify(h.notifies)}`,
    );
  } finally {
    h.dispose();
  }
});

// --- the delivery-mode matrix over the exported continuation seam ------------------------------
// (the ONE direct seam: the idle harness cannot produce the streaming `followUp` arm)

function spyPi(exec?: () => Promise<object>): {
  pi: ExtensionAPI;
  calls: { content: string; options?: { deliverAs?: string } }[];
} {
  const calls: { content: string; options?: { deliverAs?: string } }[] = [];
  const pi = {
    exec,
    sendUserMessage: (content: string, options?: { deliverAs?: string }) => {
      calls.push({ content, options });
    },
  } as unknown as ExtensionAPI;
  return { pi, calls };
}

function spyCtx(opts?: { idle?: boolean; cwd?: string }): {
  ctx: ExtensionContext;
  warnings: string[];
} {
  const warnings: string[] = [];
  const ctx = {
    cwd: opts?.cwd ?? ".",
    hasUI: true,
    isIdle: () => opts?.idle !== false,
    ui: {
      notify: (message: string, type?: string) => {
        if (type === "warning") warnings.push(message);
      },
    },
  } as unknown as ExtensionContext;
  return { ctx, warnings };
}

/** Mint outcomes through the intended feature interface (`readyChange` over fake deps) — the
 * drive evidence is mint-only, so a structural stamped-outcome literal cannot exist here. */
async function stampedOutcome(over: Partial<ReadyHandoff> = {}): Promise<ReadyOutcome> {
  return readyChange({
    markReady: async () => ({
      ok: true,
      facts: {
        route: "stacked",
        pr: { number: 42, url: "https://gh/o/r/pull/42" },
        was_draft: true,
        handoff: {
          objective: "500",
          node: "1.2",
          stamped_head: SHA_B,
          stamp_advanced: true,
          plan: "7",
          parent_checkpoint: SHA_A,
          ...over,
        },
      },
    }),
    sessionReadOnly: () => false,
  });
}

test("driveReadyContinuation: failed and completed are quiet arms", async () => {
  const { pi, calls } = spyPi();
  const { ctx, warnings } = spyCtx();
  await driveReadyContinuation(pi, ctx, {
    kind: "failed",
    message: "boom",
    errorType: "github_error",
  });
  await driveReadyContinuation(pi, ctx, {
    kind: "completed",
    facts: { route: "incremental", pr: { number: 42, url: "u" }, was_draft: true, stacked: false },
  });
  assert.equal(calls.length, 0);
  assert.equal(warnings.length, 0);
});

test("driveReadyContinuation: idle (/ready command) → one immediate turn", async () => {
  const { pi, calls } = spyPi();
  const { ctx, warnings } = spyCtx({ idle: true });
  await driveReadyContinuation(pi, ctx, await stampedOutcome());
  assert.equal(warnings.length, 0);
  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.options, undefined);
  assert.match(calls[0]?.content ?? "", new RegExp(`${SHA_A}\\.\\.${SHA_B}`));
});

test("driveReadyContinuation: streaming (ready tool) → followUp", async () => {
  const { pi, calls } = spyPi();
  const { ctx } = spyCtx({ idle: false });
  await driveReadyContinuation(pi, ctx, await stampedOutcome());
  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.options?.deliverAs, "followUp");
});

test("driveReadyContinuation: an unsafe plan id renders the <plan> retry placeholder", async () => {
  const { pi, calls } = spyPi();
  const { ctx, warnings } = spyCtx();
  // An unsafe plan id also fails the evidence vocabulary — the warning must NOT interpolate it.
  await driveReadyContinuation(pi, ctx, await stampedOutcome({ plan: "7 !" }));
  assert.equal(calls.length, 0);
  assert.equal(warnings.length, 1);
  assert.match(warnings[0] ?? "", /re-run `perk ready <plan>` to enter the pass\./);
});

// --- the linear composition path: URL fetch + fail-open indirect clause ------------------------

/** Write a committed `.perk/config.toml` selecting the issue backend (resolveIssueBackendId
 * reads it). */
function writeBackend(cwd: string, backend: string): void {
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), `[issues]\nbackend = "${backend}"\n`, "utf8");
}

test("drive (linear): fetches the objective URL into the read clause", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  writeBackend(cwd, "linear");
  const url = "https://linear.app/acme/project/objective-500";
  const { pi, calls } = spyPi(async () => ({
    code: 0,
    killed: false,
    stdout: JSON.stringify({ success: true, error_type: null, objective: { id: "500", url } }),
    stderr: "",
  }));
  const { ctx } = spyCtx({ cwd });
  await driveReadyContinuation(pi, ctx, await stampedOutcome());
  assert.equal(calls.length, 1);
  const content = calls[0]?.content ?? "";
  assert.match(content, /This objective is a Linear Project/);
  assert.ok(content.includes(url), "the fetched Project URL is referenced");
});

test("drive (linear): a failed URL fetch falls open to the indirect clause", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  writeBackend(cwd, "linear");
  const { pi, calls } = spyPi(async () => ({ code: 1, killed: false, stdout: "", stderr: "boom" }));
  const { ctx } = spyCtx({ cwd });
  await driveReadyContinuation(pi, ctx, await stampedOutcome());
  assert.equal(calls.length, 1);
  const content = calls[0]?.content ?? "";
  assert.match(content, /This objective is a Linear Project/);
  assert.match(content, /perk objective show 500.*for its URL/);
});

// --- the command path ---------------------------------------------------------------------------

test("/ready command: notifies success", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: READY_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    await h.invokeCommand("ready");
    assert.ok(
      h.notifies.some((n) => /#42/.test(n)),
      "command notifies the ready PR",
    );
  } finally {
    h.dispose();
  }
});

test("/ready command: the success line lands BEFORE the injected drive turn", async (t) => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: STACKED_READY_JSON });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    headful: false,
    mode: "print",
  });
  // ONE shared recorder across both channels: headless report() writes console.error; the
  // injected drive turn rides sendUserMessage — the interleaving IS the order pin.
  const events: string[] = [];
  t.mock.method(console, "error", (message: unknown) => events.push(`report:${String(message)}`));
  (
    h.session as unknown as { sendUserMessage: (c: unknown, o?: unknown) => Promise<void> }
  ).sendUserMessage = async (c) => {
    events.push(`inject:${typeof c === "string" ? c.slice(0, 30) : "?"}`);
  };
  try {
    await h.invokeCommand("ready");
    const reportIndex = events.findIndex((e) =>
      e.startsWith("report:perk: ready — Marked ready: PR #42"),
    );
    const injectIndex = events.findIndex((e) => e.startsWith("inject:"));
    assert.notEqual(reportIndex, -1, "the success line was reported");
    assert.notEqual(injectIndex, -1, "the drive turn was injected");
    assert.ok(reportIndex < injectIndex, "report-before-drive");
  } finally {
    h.dispose();
  }
});
