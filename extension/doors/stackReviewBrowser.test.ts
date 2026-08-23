// Tests for the warm `/stack-review-browser` door + the `open_stack_review` cold-launch tool.
// The pure pieces (the explicit target grammar, the snapshot/binding decodes, the guidance
// render, the degrade notice) are pinned directly; the command/tool flows run against a REAL
// bound session via the T1 harness, OFFLINE (a fake `perk` stands in for the cold doors, and a
// fake plannotator extension registers the presence-probe command + a bus listener standing in
// for the browser).

import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { type ExtensionAPI, SessionManager } from "@earendil-works/pi-coding-agent";
import { workflowDir } from "../substrate/cache.ts";
import {
  fakePerk,
  loadPerkSession,
  plantSession,
  scaffoldRepo,
  spyInjections,
} from "../testing/harness.ts";
import { executePushAnnotations, type FetchLike } from "./annotationPush.ts";
import {
  bindingBaseRef,
  bindingTopPr,
  decodeStackCheckout,
  decodeStackReviewBinding,
  executeOpenStackReview,
  parseStackReviewArgs,
  STACK_DEGRADE_NOTICE,
  type StackSnapshotRow,
  stackReviewGuidance,
} from "./stackReviewBrowser.ts";

/** Probe the annotation surface: `findings: []` with nothing held makes NO fetch (pure probe). */
async function surfacePrimed(): Promise<boolean> {
  const never: FetchLike = async () => {
    throw new Error("the probe must not fetch");
  };
  const target = { hasUI: false, ui: undefined } as unknown as Parameters<
    typeof executePushAnnotations
  >[0];
  const result = await executePushAnnotations(
    target,
    { angle: "probe", findings: [] },
    { fetchLike: never },
  );
  return result.details.ok;
}

// --- parseStackReviewArgs (the explicit target grammar) ------------------------------------------

test("grammar: bare numbers / #n / issue URLs are OBJECTIVE ids by definition", () => {
  assert.deepEqual(parseStackReviewArgs("77"), {
    target: { kind: "objective", id: "77" },
    directive: "",
  });
  assert.deepEqual(parseStackReviewArgs("#77 focus here"), {
    target: { kind: "objective", id: "77" },
    directive: "focus here",
  });
  assert.deepEqual(parseStackReviewArgs("https://github.com/o/r/issues/77"), {
    target: { kind: "objective", id: "77" },
    directive: "",
  });
});

test("grammar: backend-native ids and Linear issue/project URLs are OBJECTIVE ids too", () => {
  assert.deepEqual(parseStackReviewArgs("ENG-123 dig in"), {
    target: { kind: "objective", id: "ENG-123" },
    directive: "dig in",
  });
  assert.deepEqual(parseStackReviewArgs("https://linear.app/acme/issue/SAV-888/some-title"), {
    target: { kind: "objective", id: "SAV-888" },
    directive: "",
  });
  assert.deepEqual(parseStackReviewArgs("https://linear.app/acme/project/proj-slug-1234"), {
    target: { kind: "objective", id: "proj-slug-1234" },
    directive: "",
  });
  // A non-Linear host with an /issue/ segment is NOT the Linear form (and not a GitHub
  // /issues/N form either) — it falls through to the focus-note arm.
  assert.deepEqual(parseStackReviewArgs("https://example.com/issue/ENG-1"), {
    target: { kind: "auto" },
    directive: "https://example.com/issue/ENG-1",
  });
});

test("grammar: pr:<n> and PR URLs are the chain arm", () => {
  assert.deepEqual(parseStackReviewArgs("pr:148 dig in"), {
    target: { kind: "pr", pr: 148 },
    directive: "dig in",
  });
  assert.deepEqual(parseStackReviewArgs("https://github.com/o/r/pull/148"), {
    target: { kind: "pr", pr: 148 },
    directive: "",
  });
});

test("grammar: no target → the ladder; a non-target first token is the WHOLE focus note", () => {
  assert.deepEqual(parseStackReviewArgs(""), { target: { kind: "auto" }, directive: "" });
  assert.deepEqual(parseStackReviewArgs("  dig into the CI edits  "), {
    target: { kind: "auto" },
    directive: "dig into the CI edits",
  });
});

test("grammar: a malformed pr: token is a usage failure, never silently a focus note", () => {
  assert.equal(parseStackReviewArgs("pr:abc"), null);
  assert.equal(parseStackReviewArgs("pr: 42"), null);
});

// --- the snapshot decodes -------------------------------------------------------------------------

const ROW_A: StackSnapshotRow = {
  pr: 41,
  url: "https://github.com/o/r/pull/41",
  branch: "plan-301",
  head_sha: "a".repeat(40),
  base_ref: "main",
  node_id: "1.1",
  plan_id: "301",
};

const ROW_B: StackSnapshotRow = {
  pr: 42,
  url: "https://github.com/o/r/pull/42",
  branch: "feat-b",
  head_sha: "b".repeat(40),
  base_ref: "plan-301",
  node_id: null,
  plan_id: null,
};

const STACK_CHECKOUT_PAYLOAD = {
  success: true,
  error_type: null,
  message: null,
  path: "/wt/review-42",
  pr: 42,
  url: "https://github.com/o/r/pull/42",
  head_sha: "b".repeat(40),
  base_sha: "0".repeat(40),
  base_ref: "main",
  stack: [ROW_A, ROW_B],
  stack_notes: ["drift: PR #41 head moved"],
};

test("decodeStackCheckout: the full envelope decodes; missing stack fields refuse", () => {
  const decoded = decodeStackCheckout(STACK_CHECKOUT_PAYLOAD as never);
  assert.ok(decoded !== null);
  assert.deepEqual(
    decoded.stack.map((r) => r.pr),
    [41, 42],
  );
  assert.equal(decoded.base_ref, "main", "base_ref IS the stack base on the stack envelope");
  assert.deepEqual(decoded.stack_notes, ["drift: PR #41 head moved"]);
  const { stack: _stack, ...noStack } = STACK_CHECKOUT_PAYLOAD;
  assert.equal(decodeStackCheckout(noStack as never), null);
  assert.equal(
    decodeStackCheckout({ ...STACK_CHECKOUT_PAYLOAD, stack: [] } as never),
    null,
    "an empty member table is never a stack snapshot",
  );
  assert.equal(
    decodeStackCheckout({
      ...STACK_CHECKOUT_PAYLOAD,
      stack: [{ ...ROW_A, pr: "41" }],
    } as never),
    null,
    "a malformed row refuses the whole decode",
  );
});

test("decodeStackReviewBinding: every field REQUIRED; endpoints derive; blank focus → null", () => {
  const binding = {
    stack: [ROW_A, ROW_B],
    checkout_path: "/wt/review-42",
    notes: [],
    focus: "  ",
  };
  const decoded = decodeStackReviewBinding(binding);
  assert.ok(decoded !== null);
  assert.equal(decoded.focus, null, "a blank focus normalizes to null (no focus)");
  assert.equal(bindingTopPr(decoded), 42, "top PR derives from the LAST ordered row");
  assert.equal(bindingBaseRef(decoded), "main", "the stack base derives from the FIRST row");
  assert.equal(decodeStackReviewBinding({ ...binding, focus: "dig in" })?.focus, "dig in");
  assert.equal(decodeStackReviewBinding({ ...binding, focus: null })?.focus, null);
  // Strictness: a missing or mistyped field — ANY of the four — refuses the whole decode.
  assert.equal(decodeStackReviewBinding({ ...binding, checkout_path: "" }), null);
  assert.equal(decodeStackReviewBinding({ ...binding, stack: [] }), null);
  const { stack: _s, ...noStack } = binding;
  assert.equal(decodeStackReviewBinding(noStack), null);
  const { notes: _n, ...noNotes } = binding;
  assert.equal(decodeStackReviewBinding(noNotes), null, "absent notes is drift, not a default");
  const { focus: _f, ...noFocus } = binding;
  assert.equal(decodeStackReviewBinding(noFocus), null, "absent focus is drift, not a default");
  assert.equal(decodeStackReviewBinding({ ...binding, focus: 7 }), null);
  assert.equal(decodeStackReviewBinding({ ...binding, notes: ["x", 7] }), null);
  assert.equal(decodeStackReviewBinding(undefined), null);
});

// --- the guidance ---------------------------------------------------------------------------------

const GUIDANCE_OPTS = {
  topPr: 42,
  checkout: "/wt/review-42",
  stackBase: "main",
  members: [ROW_A, ROW_B],
  notes: ["drift: PR #41 head moved"],
};

test("guidance: the member table, the stack framing, and the wave launch pins", () => {
  const text = stackReviewGuidance(GUIDANCE_OPTS);
  assert.match(text, /2 member PRs on base `main`, topped by PR #42/);
  assert.match(text, /1\. PR #41 `plan-301` ← `main` · node 1\.1 · plan #301/);
  assert.match(text, /2\. PR #42 `feat-b` ← `plan-301` — https:\/\/github\.com\/o\/r\/pull\/42/);
  assert.match(text, /drift: PR #41 head moved/);
  assert.ok(text.includes('`{ angles, pr: 42, worktree: "/wt/review-42", stack: true }`'));
  assert.match(text, /perk pr review-context --pr 42 --stack/);
  assert.match(text, /combined-diff coordinates/);
  assert.match(text, /untrusted foreign code/);
  assert.doesNotMatch(text, /127\.0\.0\.1|localhost/);
});

test("guidance: the stack posting protocol — perk-side, dry-run-all-first, bottom→top, the ledger", () => {
  const text = stackReviewGuidance(GUIDANCE_OPTS);
  assert.match(text, /NO attached PR/);
  assert.match(text, /ALL posting is perk-side/);
  assert.match(text, /dry-run ALL batches before ANY real post/);
  assert.match(text, /bottom→top/);
  assert.match(text, /review_posts/);
  assert.match(text, /never replay a posted review/);
  assert.match(text, /owning PR's review body/);
  assert.match(text, /sanity-check its quoted context/);
  assert.match(text, /perk pr review cleanup --pr 42/);
  // The streaming-wave companions are all named (the drive-coverage guard's inputs).
  assert.match(text, /start_review_wave/);
  assert.match(text, /collect_review_wave/);
  assert.match(text, /push_annotations/);
  assert.match(text, /submit_pr_review/);
  assert.match(text, /subagent_wait\(\{ timeoutMs: 30000 \}\)/);
  assert.match(text, /never compose annotation HTTP/);
  assert.match(text, /replace: true/);
});

test("guidance: the directive and notes arms render/omit", () => {
  const withDirective = stackReviewGuidance({ ...GUIDANCE_OPTS, directive: "dig into CI" });
  assert.match(withDirective, /Operator focus for this run/);
  assert.match(withDirective, /dig into CI/);
  const bare = stackReviewGuidance(GUIDANCE_OPTS);
  assert.doesNotMatch(bare, /Operator focus for this run/);
  const noNotes = stackReviewGuidance({ ...GUIDANCE_OPTS, notes: [] });
  assert.doesNotMatch(noNotes, /Notes from resolution\/checkout/);
});

test("STACK_DEGRADE_NOTICE: in-session degrade with the posting protocol unchanged", () => {
  assert.match(STACK_DEGRADE_NOTICE, /render the reviewers' reconciled findings as a table/);
  assert.match(STACK_DEGRADE_NOTICE, /push_annotations` now refuses \(`no_surface`\)/);
  assert.match(STACK_DEGRADE_NOTICE, /never depended on the browser/);
  assert.match(STACK_DEGRADE_NOTICE, /bottom→top via `submit_pr_review`/);
});

// --- the command flow through the harness ---------------------------------------------------------

const STACK_CHECKOUT_OK_JSON = JSON.stringify(STACK_CHECKOUT_PAYLOAD);

/** The plannotator:request envelope the fake browser listener records. */
interface CodeReviewEnvelope {
  requestId: string;
  action: string;
  payload: { prUrl?: string; cwd: string; diffType?: string; defaultBranch?: string };
  respond: (response: unknown) => void;
}

interface FakeBrowser {
  envelopes: CodeReviewEnvelope[];
}

function fakePlannotator(sink: FakeBrowser): (pi: ExtensionAPI) => void {
  return (pi) => {
    pi.registerCommand("plannotator-review", {
      description: "fake plannotator (test)",
      handler: async () => {},
    });
    pi.events.on("plannotator:request", (data) => {
      sink.envelopes.push(data as CodeReviewEnvelope);
    });
  };
}

/** Settle every recorded bridge and wait for the poll's env restore (bounded). */
async function settleBridges(sink: FakeBrowser): Promise<void> {
  for (const envelope of sink.envelopes) {
    envelope.respond({ status: "handled", result: { approved: true } });
  }
  const start = Date.now();
  while ("PLANNOTATOR_PORT" in process.env) {
    if (Date.now() - start > 5000) break; // bounded — never hang a test on cleanup
    await new Promise((r) => setTimeout(r, 25));
  }
}

test("/stack-review-browser: headless → refusal; plannotator absent → the pinned refusal", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: STACK_CHECKOUT_OK_JSON, argvFile });
  const sink: FakeBrowser = { envelopes: [] };
  const headless = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    headful: false,
    extraExtensions: [fakePlannotator(sink)],
  });
  try {
    assert.ok(headless.registeredCommands().includes("stack-review-browser"));
    await headless.runCommandHandler("stack-review-browser", "77");
    assert.equal(existsSync(argvFile), false, "no cold door executed headless");
  } finally {
    headless.dispose();
  }

  const noPlannotator = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
  });
  try {
    await noPlannotator.runCommandHandler("stack-review-browser", "77");
    assert.ok(
      noPlannotator.notifies.some((n) => n.includes("the plannotator extension is not loaded")),
      "the refusal names the fix",
    );
    assert.equal(existsSync(argvFile), false, "no cold door executed without plannotator");
  } finally {
    noPlannotator.dispose();
  }
});

test("/stack-review-browser: a malformed pr: token reports usage, nothing executed", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: STACK_CHECKOUT_OK_JSON, argvFile });
  const sink: FakeBrowser = { envelopes: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink)],
  });
  try {
    await h.runCommandHandler("stack-review-browser", "pr:abc");
    assert.ok(h.notifies.some((n) => n.includes("usage: /stack-review-browser")));
    assert.equal(existsSync(argvFile), false, "no cold door executed");
    assert.equal(sink.envelopes.length, 0, "no bridge emitted");
  } finally {
    h.dispose();
  }
});

test("/stack-review-browser: a typed checkout refusal is surfaced, nothing injected", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const refusal = JSON.stringify({
    success: false,
    error_type: "not_a_stack",
    message: "Not a stack: 1 open member PR(s) resolved",
  });
  const bin = fakePerk(cwd, { stdout: refusal, code: 1 });
  const sink: FakeBrowser = { envelopes: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("stack-review-browser", "pr:42");
    assert.ok(
      h.notifies.some((n) => n.includes("not_a_stack") && n.includes("Not a stack")),
      "the envelope failure is surfaced",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(sink.envelopes.length, 0, "no bridge emitted");
  } finally {
    h.dispose();
  }
});

test("/stack-review-browser 77: objective argv, ONE guidance injection, the local-mode payload with origin/<base>, prime→clear", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: STACK_CHECKOUT_OK_JSON, argvFile });
  const sink: FakeBrowser = { envelopes: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("stack-review-browser", "77 dig into CI");
    const argv = readFileSync(argvFile, "utf8").trim().split("\n");
    assert.deepEqual(argv, ["pr", "review", "checkout", "--stack", "--objective", "77", "--json"]);
    assert.ok(
      h.notifies.some((n) =>
        n.includes(
          "stack of 2 PRs (base main, top #42) → adversarial reviewers (focus: dig into CI) → plannotator browser triage → judgment-routed per-PR posting",
        ),
      ),
      "the info line names the flow",
    );
    assert.equal(injected.length, 1, "one guidance injection");
    const text = injected[0] ?? "";
    assert.match(text, /topped by PR #42/);
    assert.match(text, /dig into CI/);
    assert.doesNotMatch(text, /127\.0\.0\.1|localhost/);
    assert.ok(
      text.includes("Follow the `perk-pr-review-browser` skill"),
      "the widened skill rides the command:stack-review-browser binding suffix",
    );
    // The browser opened on the CHECKOUT in local mode with the remote-tracking base.
    assert.equal(sink.envelopes.length, 1, "the bridge request was emitted");
    assert.deepEqual(sink.envelopes[0]?.payload, {
      cwd: "/wt/review-42",
      diffType: "since-base",
      defaultBranch: "origin/main",
    });
    assert.equal(await surfacePrimed(), true, "the surface is primed after the open");
    await settleBridges(sink);
    const start = Date.now();
    while ((await surfacePrimed()) && Date.now() - start < 5000) {
      await new Promise((r) => setTimeout(r, 25));
    }
    assert.equal(await surfacePrimed(), false, "the bridge settle clears the surface");
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});

test("/stack-review-browser (no target): the active_objective ladder feeds --objective", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ active_objective: "9" }]);
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: STACK_CHECKOUT_OK_JSON, argvFile });
  const sink: FakeBrowser = { envelopes: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined, PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
    extraExtensions: [fakePlannotator(sink)],
  });
  try {
    await h.runCommandHandler("stack-review-browser", "");
    const argv = readFileSync(argvFile, "utf8").trim().split("\n");
    assert.deepEqual(argv, ["pr", "review", "checkout", "--stack", "--objective", "9", "--json"]);
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});

test("/stack-review-browser (no target, no session objective): bare --stack; no_objective names the forms", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const noObjective = JSON.stringify({
    success: false,
    error_type: "no_objective",
    message: "No objective given",
  });
  const bin = fakePerk(cwd, { stdout: noObjective, code: 1, argvFile });
  const sink: FakeBrowser = { envelopes: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("stack-review-browser", "");
    const argv = readFileSync(argvFile, "utf8").trim().split("\n");
    assert.deepEqual(argv, ["pr", "review", "checkout", "--stack", "--json"]);
    assert.ok(
      h.notifies.some(
        (n) => n.includes("no stack target") && n.includes("pass an objective id / issue URL"),
      ),
      "the no_objective arm is a usage refusal naming the explicit forms",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(sink.envelopes.length, 0, "no bridge emitted");
  } finally {
    h.dispose();
  }
});

// --- open_stack_review (the cold-launch tool) ------------------------------------------------------

const RUN_ID = "01STACKRUN";

/** Scaffold a claimed stack-review launch: the handoff carries the `stack_review` binding and
 * the checkout dir exists on disk. */
function scaffoldStackLaunch(opts: { checkout?: boolean; binding?: boolean } = {}): {
  cwd: string;
  checkoutPath: string;
} {
  const cwd = scaffoldRepo({
    handoff: { runId: RUN_ID, mode: "read-write", stage: "stack-review" },
  });
  const checkoutPath = join(cwd, "review-42");
  if (opts.checkout !== false) mkdirSync(checkoutPath, { recursive: true });
  const binding = {
    stack: [ROW_A, ROW_B],
    checkout_path: checkoutPath,
    notes: ["drift: PR #41 head moved"],
    focus: "dig into CI",
  };
  writeFileSync(
    join(workflowDir(cwd), "handoff", `${RUN_ID}.json`),
    `${JSON.stringify({
      run_id: RUN_ID,
      consumed: false,
      mode: "read-write",
      stage: "stack-review",
      ...(opts.binding !== false ? { stack_review: binding } : {}),
    })}\n`,
    "utf8",
  );
  return { cwd, checkoutPath };
}

test("open_stack_review: refuses outside a stack-review launch (no binding) — bad_state", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: RUN_ID, mode: "read-write", stage: "implement" } });
  const sink: FakeBrowser = { envelopes: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: RUN_ID },
    extraExtensions: [fakePlannotator(sink)],
  });
  try {
    const result = await h.invokeTool("open_stack_review", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_state");
    assert.match(
      result.content[0]?.text ?? "",
      /runs only inside a perk objective stack review session/,
    );
    assert.equal(sink.envelopes.length, 0, "no bridge emitted");
  } finally {
    h.dispose();
  }
});

test("open_stack_review: a missing checkout dir is bad_state naming the re-run", async () => {
  const { cwd } = scaffoldStackLaunch({ checkout: false });
  const sink: FakeBrowser = { envelopes: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: RUN_ID },
    extraExtensions: [fakePlannotator(sink)],
  });
  try {
    const result = await h.invokeTool("open_stack_review", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_state");
    assert.match(result.content[0]?.text ?? "", /stack checkout is missing/);
  } finally {
    h.dispose();
  }
});

test("open_stack_review: headless → the typed refusal, nothing opened", async () => {
  const { cwd } = scaffoldStackLaunch();
  const sink: FakeBrowser = { envelopes: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: RUN_ID },
    headful: false,
    extraExtensions: [fakePlannotator(sink)],
  });
  try {
    const result = await h.invokeTool("open_stack_review", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "headless");
    assert.equal(sink.envelopes.length, 0, "no bridge emitted");
  } finally {
    h.dispose();
  }
});

test("open_stack_review: success returns the guidance as ok text; second call is single-use bad_state", async () => {
  const { cwd, checkoutPath } = scaffoldStackLaunch();
  const sink: FakeBrowser = { envelopes: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: RUN_ID },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    const result = await h.invokeTool("open_stack_review", {});
    const details = result.details as {
      ok: boolean;
      top_pr?: number;
      member_count?: number;
    };
    assert.equal(details.ok, true);
    assert.equal(details.top_pr, 42);
    assert.equal(details.member_count, 2);
    const text = result.content[0]?.text ?? "";
    assert.match(text, /topped by PR #42/);
    assert.match(text, /dig into CI/, "the launch focus threads into the guidance");
    assert.match(text, /drift: PR #41 head moved/, "the snapshot notes render");
    assert.doesNotMatch(text, /127\.0\.0\.1|localhost/);
    assert.equal(injected.length, 0, "the tool returns the guidance — it injects nothing");
    assert.equal(sink.envelopes.length, 1, "the bridge request was emitted");
    assert.deepEqual(sink.envelopes[0]?.payload, {
      cwd: checkoutPath,
      diffType: "since-base",
      defaultBranch: "origin/main",
    });

    const second = await h.invokeTool("open_stack_review", {});
    const secondDetails = second.details as { ok: boolean; error_type?: string };
    assert.equal(secondDetails.ok, false);
    assert.equal(secondDetails.error_type, "bad_state");
    assert.match(second.content[0]?.text ?? "", /single-use/);
    assert.equal(sink.envelopes.length, 1, "no second bridge");
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});

test("executeOpenStackReview: a browser-open failure is browser_failed and keeps the latch closed", async () => {
  // The execute core over the injected open seam (the port-pick failure surfaces as a false
  // return from the shared open) — the real registration wires the same core to the tool.
  const { cwd, checkoutPath } = scaffoldStackLaunch();
  const branch = [{ type: "custom", customType: "perk:workflow-state", data: { run_id: RUN_ID } }];
  const pi = {
    getCommands: () => [{ name: "plannotator-review" }],
  } as unknown as ExtensionAPI;
  const ctx = {
    cwd,
    hasUI: true,
    sessionManager: { getBranch: () => branch },
    ui: { notify: () => {} },
  } as unknown as Parameters<typeof executeOpenStackReview>[1];

  const latch = { opened: false };
  const opens: string[] = [];
  const failed = await executeOpenStackReview(pi, ctx, latch, (_pi, _ctx, opts) => {
    opens.push(opts.checkoutPath);
    return Promise.resolve(false);
  });
  const failedDetails = failed.details as { ok: boolean; error_type?: string };
  assert.equal(failedDetails.ok, false);
  assert.equal(failedDetails.error_type, "browser_failed");
  assert.match(failed.content[0]?.text ?? "", /could not start the plannotator review server/);
  assert.deepEqual(opens, [checkoutPath], "the open was attempted with the bound checkout");
  assert.equal(latch.opened, false, "a failed open never consumes the single-use latch");

  // The failure is retryable: the SAME latch accepts a later successful open…
  const succeeded = await executeOpenStackReview(pi, ctx, latch, () => Promise.resolve(true));
  assert.equal((succeeded.details as { ok: boolean }).ok, true);
  assert.equal(latch.opened, true);
  // …and only then does single-use bite.
  const third = await executeOpenStackReview(pi, ctx, latch, () => Promise.resolve(true));
  const thirdDetails = third.details as { ok: boolean; error_type?: string };
  assert.equal(thirdDetails.ok, false);
  assert.equal(thirdDetails.error_type, "bad_state");
});
