// Tests for the warm `/stack-review-browser` door + the `open_stack_review` cold-launch tool.
// The pure pieces (the explicit target grammar, the snapshot/binding decodes, the guidance
// render, the degrade notice) are pinned directly; the execute core runs over a fake open seam
// and over `openStackBrowser` on a REAL browser-operation owner (the launch-time digest
// re-check); the command/tool flows run against a REAL bound session via the T1 harness,
// OFFLINE (a fake `perk` stands in for the cold doors, and a fake plannotator extension
// registers the presence-probe command + a bus listener standing in for the browser).

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createServer as createHttpServer, type Server } from "node:http";
import { join } from "node:path";
import { test } from "node:test";
import {
  type ExtensionAPI,
  type ExtensionContext,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { workflowDir } from "../../../substrate/cache.ts";
import { createPerkStatus } from "../../../surfaces/surfaces.ts";
import {
  COHORT_SETTINGS,
  fakePerk,
  loadPerkSession,
  plantSession,
  scaffoldRepo,
  spyInjectionLoadouts,
  spyInjections,
  toolSearch,
} from "../../../testing/harness.ts";
import { pinnedReviewContextCommand } from "../../../waves/adversarialReviewWave.ts";
import { createBrowserOperationOwner } from "../browserOperation.ts";
import { createAnnotationState, type FetchLike } from "../providers/annotations.ts";
import { reviewDetachedStatus } from "../providers/waveStatus.ts";
import { REVIEW_BROWSER_PRIMES } from "./browser.ts";
import { createStackPinState } from "./reviewWave.ts";
import {
  bindingBaseRef,
  bindingTopPr,
  decodeStackCheckout,
  decodeStackReviewBinding,
  executeOpenStackReview,
  openStackBrowser,
  parseStackReviewArgs,
  patchPathFor,
  pinnedStackOf,
  pinSupersedeRefusal,
  STACK_DEGRADE_NOTICE,
  type StackBrowserOpen,
  type StackOpenResult,
  type StackSnapshotRow,
  stackReviewGuidance,
  verifyStackPatch,
} from "./stack.ts";

/** Probe the SESSION's annotation state through the registered tool (the harness flows). */
async function sessionSurfacePrimed(h: {
  invokeTool(name: string, params: unknown): Promise<{ details: unknown }>;
}): Promise<boolean> {
  const result = await h.invokeTool("push_annotations", { angle: "probe", findings: [] });
  return (result.details as { ok: boolean }).ok;
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

/** The combined patch a stack checkout writes beside the checkout, and its digest. */
const PATCH_TEXT = "diff --git a/a.txt b/a.txt\n+++ b/a.txt\n@@ -0,0 +1 @@\n+a\n";
const PATCH_SHA256 = createHash("sha256").update(PATCH_TEXT, "utf8").digest("hex");

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
  patch_sha256: PATCH_SHA256,
};

/** The verified pin the snapshot above yields. */
const PINNED = pinnedStackOf(42, "/wt/review-42", "0".repeat(40), [ROW_A, ROW_B]);

test("patchPathFor / pinnedStackOf: the derived `<checkout>.patch` sibling and the bottom→top pins", () => {
  assert.equal(patchPathFor("/wt/review-42"), "/wt/review-42.patch");
  assert.deepEqual(PINNED, {
    topPr: 42,
    checkout: "/wt/review-42",
    baseSha: "0".repeat(40),
    heads: [
      { pr: 41, headSha: "a".repeat(40) },
      { pr: 42, headSha: "b".repeat(40) },
    ],
  });
});

test("verifyStackPatch: missing / unreadable / mismatch / ok over the derived sibling", () => {
  const cwd = scaffoldRepo();
  const checkout = join(cwd, "review-42");
  mkdirSync(checkout);
  const missing = verifyStackPatch(checkout, PATCH_SHA256);
  assert.equal(missing.ok, false);
  if (missing.ok) return;
  assert.equal(missing.reason, "missing");
  assert.equal(missing.patchPath, `${checkout}.patch`);
  assert.match(missing.detail, /combined patch is missing at '.*review-42\.patch'/);

  writeFileSync(`${checkout}.patch`, `${PATCH_TEXT}tampered\n`, "utf8");
  const mismatch = verifyStackPatch(checkout, PATCH_SHA256);
  assert.equal(mismatch.ok, false);
  if (mismatch.ok) return;
  assert.equal(mismatch.reason, "mismatch");
  assert.match(mismatch.detail, /refreshed since this snapshot was taken/);

  writeFileSync(`${checkout}.patch`, PATCH_TEXT, "utf8");
  assert.deepEqual(verifyStackPatch(checkout, PATCH_SHA256), {
    ok: true,
    patchPath: `${checkout}.patch`,
  });

  // A directory where the patch should be is unreadable (EISDIR), not missing.
  mkdirSync(`${checkout}.unreadable.patch`);
  const unreadable = verifyStackPatch(`${checkout}.unreadable`, PATCH_SHA256);
  assert.equal(unreadable.ok, false);
  if (unreadable.ok) return;
  assert.equal(unreadable.reason, "unreadable");
});

test("pinSupersedeRefusal: no pending stack wave or the SAME pin → proceed; a different pin in flight → the refusal names the pending review", () => {
  const idle = createStackPinState();
  assert.equal(pinSupersedeRefusal(idle, PINNED), null, "nothing in flight");
  idle.pinned = PINNED;
  assert.equal(pinSupersedeRefusal(idle, PINNED), null, "an open review with no wave pending");
  const busy = { pinned: PINNED, inFlight: PINNED };
  assert.equal(
    pinSupersedeRefusal(busy, { ...PINNED }),
    null,
    "a stale-session reopen of the same pin",
  );
  // A refreshed checkout of the same top PR (one head moved) IS a different pin.
  const moved = {
    ...PINNED,
    heads: [
      PINNED.heads[0] as { pr: number; headSha: string },
      { pr: 42, headSha: "c".repeat(40) },
    ],
  };
  const refusal = pinSupersedeRefusal(busy, moved);
  assert.ok(refusal !== null);
  assert.match(
    refusal,
    /still pending against the open stack review \(top PR #42 at \/wt\/review-42\)/,
  );
  assert.match(refusal, /collect_review_wave/);
  // Another stack entirely.
  const other = pinnedStackOf(9, "/wt/review-9", "1".repeat(40), [
    { ...ROW_A, pr: 8 },
    { ...ROW_B, pr: 9 },
  ]);
  assert.ok(pinSupersedeRefusal(busy, other) !== null);
});

test("decodeStackCheckout: the full envelope decodes; missing stack fields refuse", () => {
  const decoded = decodeStackCheckout(STACK_CHECKOUT_PAYLOAD as never);
  assert.ok(decoded !== null);
  assert.deepEqual(
    decoded.stack.map((r) => r.pr),
    [41, 42],
  );
  assert.equal(decoded.base_ref, "main", "base_ref IS the stack base on the stack envelope");
  assert.deepEqual(decoded.stack_notes, ["drift: PR #41 head moved"]);
  assert.equal(decoded.patch_sha256, PATCH_SHA256);
  const { stack: _stack, ...noStack } = STACK_CHECKOUT_PAYLOAD;
  assert.equal(decodeStackCheckout(noStack as never), null);
  const { patch_sha256: _p, ...noPatch } = STACK_CHECKOUT_PAYLOAD;
  assert.equal(decodeStackCheckout(noPatch as never), null, "patch_sha256 is REQUIRED");
  assert.equal(
    decodeStackCheckout({ ...STACK_CHECKOUT_PAYLOAD, patch_sha256: "abc" } as never),
    null,
    "a non-64-hex digest refuses",
  );
  assert.equal(
    decodeStackCheckout({
      ...STACK_CHECKOUT_PAYLOAD,
      patch_sha256: PATCH_SHA256.toUpperCase(),
    } as never),
    null,
    "uppercase hex refuses",
  );
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
    base_sha: "0".repeat(40),
    patch_sha256: PATCH_SHA256,
  };
  const decoded = decodeStackReviewBinding(binding);
  assert.ok(decoded !== null);
  assert.equal(decoded.focus, null, "a blank focus normalizes to null (no focus)");
  assert.equal(decoded.base_sha, "0".repeat(40));
  assert.equal(decoded.patch_sha256, PATCH_SHA256);
  // The pinned identity is REQUIRED and shape-checked (40-hex / 64-hex).
  const { base_sha: _b, ...noBase } = binding;
  assert.equal(decodeStackReviewBinding(noBase), null, "absent base_sha is drift");
  const { patch_sha256: _ps, ...noDigest } = binding;
  assert.equal(decodeStackReviewBinding(noDigest), null, "absent patch_sha256 is drift");
  assert.equal(decodeStackReviewBinding({ ...binding, base_sha: "0".repeat(12) }), null);
  assert.equal(decodeStackReviewBinding({ ...binding, patch_sha256: "f".repeat(63) }), null);
  assert.equal(decodeStackReviewBinding({ ...binding, base_sha: null }), null);
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
  pinned: PINNED,
};

test("guidance: the member table, the stack framing, and the wave launch pins", () => {
  const text = stackReviewGuidance(GUIDANCE_OPTS);
  assert.match(text, /2 member PRs on base `main`, topped by PR #42/);
  assert.match(text, /1\. PR #41 `plan-301` ← `main` · node 1\.1 · plan #301/);
  assert.match(text, /2\. PR #42 `feat-b` ← `plan-301` — https:\/\/github\.com\/o\/r\/pull\/42/);
  assert.match(text, /drift: PR #41 head moved/);
  assert.ok(text.includes('`{ angles, pr: 42, worktree: "/wt/review-42", stack: true }`'));
  // The routing step names EXACTLY the pinned command (the same one the lanes run); the
  // unpinned `--stack` fetch is gone from the guidance.
  assert.ok(text.includes(`\`${pinnedReviewContextCommand(PINNED)} --json\``));
  assert.doesNotMatch(text, /review-context --pr 42 --stack --json`/);
  assert.match(text, /static patch of the pinned combined diff/);
  assert.match(text, /moving refs cannot change it/);
  assert.doesNotMatch(text, /since-base/);
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
  // The review-wave companions are all named (the drive-coverage guard's inputs).
  assert.match(text, /start_review_wave/);
  assert.match(text, /collect_review_wave/);
  assert.match(text, /push_annotations/);
  assert.match(text, /submit_pr_review/);
  // The shared yield partial is included once; the marker + early-decision policy ride step 1.
  assert.match(text, /4\. \*\*Yield\.\*\*/);
  assert.match(text, /Children do not stream — no finding reaches you before the wave finishes/);
  assert.match(text, /'reviewer wave running' marker until the wave lands/);
  assert.match(text, /an early decision is authoritative and forgoes the findings/);
  assert.match(text, /combined-diff coordinates/);
  assert.match(text, /disjoint final per-angle arrays/);
  assert.match(text, /visible source names the owning lane/);
  assert.match(text, /alongside your findings/);
  assert.doesNotMatch(
    text,
    /subagent_wait|bg_wait|hold your turn open|timeout expiry IS the streaming cadence/,
  );
  assert.doesNotMatch(
    text,
    /Native-wake relay|Subagent progress update|provisional|streamed|uncovered source/,
    "the retired streaming protocol is gone",
  );
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
  payload: {
    prUrl?: string;
    cwd: string;
    diffType?: string;
    defaultBranch?: string;
    patchFile?: string;
  };
  respond: (response: unknown) => void;
}

/**
 * Plant a real checkout dir + its `<checkout>.patch` sibling under `cwd` and return the checkout
 * envelope JSON the fake cold door emits for it (the digest matches the planted bytes unless a
 * caller tampers afterwards).
 */
function plantStackCheckout(cwd: string): { checkoutPath: string; json: string } {
  const checkoutPath = join(cwd, "review-42");
  mkdirSync(checkoutPath, { recursive: true });
  writeFileSync(patchPathFor(checkoutPath), PATCH_TEXT, "utf8");
  return {
    checkoutPath,
    json: JSON.stringify({ ...STACK_CHECKOUT_PAYLOAD, path: checkoutPath }),
  };
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

test("/stack-review-browser 77: objective argv, ONE guidance injection, the static-patch payload, the pin, prime→clear", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const planted = plantStackCheckout(cwd);
  const bin = fakePerk(cwd, { stdout: planted.json, argvFile });
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
    assert.ok(
      text.includes(pinnedReviewContextCommand({ ...PINNED, checkout: planted.checkoutPath })),
      "the guidance carries the pinned review-context command",
    );
    // The browser opened plannotator's static-patch mode over the verified `<checkout>.patch`
    // — no diffType / defaultBranch / prUrl.
    assert.equal(sink.envelopes.length, 1, "the bridge request was emitted");
    assert.deepEqual(sink.envelopes[0]?.payload, {
      cwd: planted.checkoutPath,
      patchFile: patchPathFor(planted.checkoutPath),
    });
    assert.equal(await sessionSurfacePrimed(h), true, "the surface is primed after the open");
    // The open bound the pin: a stack wave for THIS stack is no longer refused bad_state /
    // bad_input (it fails later on the absent subagent runner — a wave failure, not a binding
    // refusal); a wave aimed elsewhere is bad_input.
    const bound = await h.invokeTool("start_review_wave", {
      angles: ["claimed-intent", "tests"],
      pr: 42,
      worktree: planted.checkoutPath,
      stack: true,
    });
    const boundType = (bound.details as { error_type?: string }).error_type;
    assert.notEqual(boundType, "bad_state");
    assert.notEqual(boundType, "bad_input");
    const elsewhere = await h.invokeTool("start_review_wave", {
      angles: ["claimed-intent", "tests"],
      pr: 43,
      worktree: planted.checkoutPath,
      stack: true,
    });
    assert.equal((elsewhere.details as { error_type?: string }).error_type, "bad_input");
    await settleBridges(sink);
    const start = Date.now();
    while ((await sessionSurfacePrimed(h)) && Date.now() - start < 5000) {
      await new Promise((r) => setTimeout(r, 25));
    }
    assert.equal(await sessionSurfacePrimed(h), false, "the bridge settle clears the surface");
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});

/** Every request a serving fake review server received. */
interface ServedRequest {
  port: number;
  method: string;
  url: string;
  body: string;
}

/**
 * A fake plannotator whose code-review server binds the preset port while the request is
 * emitted (where real plannotator binds), answers the readiness probe, accepts annotation pushes
 * and records every request; each envelope is kept for an explicit `respond`.
 */
function servingPlannotator(
  sink: FakeBrowser,
  served: { servers: Server[]; requests: ServedRequest[] },
): (pi: ExtensionAPI) => void {
  return (pi) => {
    pi.registerCommand("plannotator-review", {
      description: "fake plannotator (test)",
      handler: async () => {},
    });
    pi.events.on("plannotator:request", (data) => {
      sink.envelopes.push(data as CodeReviewEnvelope);
      const port = Number(process.env.PLANNOTATOR_PORT);
      const server = createHttpServer((req, res) => {
        let body = "";
        req.on("data", (chunk) => {
          body += String(chunk);
        });
        req.on("end", () => {
          served.requests.push({ port, method: req.method ?? "", url: req.url ?? "", body });
          res.writeHead(req.method === "POST" ? 201 : 200, { "content-type": "application/json" });
          res.end(req.method === "POST" ? '{"ids":[]}' : "{}");
        });
      });
      server.listen(port, "127.0.0.1");
      served.servers.push(server);
    });
  };
}

test("/stack-review-browser twice on the SAME pin replaces the earlier review (marker `replaced`) and rebinds the pin", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const planted = plantStackCheckout(cwd);
  const bin = fakePerk(cwd, { stdout: planted.json });
  const sink: FakeBrowser = { envelopes: [] };
  const served: { servers: Server[]; requests: ServedRequest[] } = { servers: [], requests: [] };
  const priorPort = process.env.PLANNOTATOR_PORT;
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [servingPlannotator(sink, served)],
  });
  const injected = spyInjections(h);
  const settled = async () => {
    const start = Date.now();
    while (process.env.PLANNOTATOR_PORT !== priorPort && Date.now() - start < 5000) {
      await new Promise((r) => setTimeout(r, 10));
    }
  };
  try {
    await h.runCommandHandler("stack-review-browser", "77");
    await settled();
    const firstPort = served.requests[0]?.port ?? 0;
    assert.ok(firstPort > 0, "the first review answered its readiness probe");
    // The SAME pin again (e.g. a reopen from a fresh turn): the pin guard lets it through, and
    // the owner replaces the first review rather than priming beside it.
    await h.runCommandHandler("stack-review-browser", "77");
    await settled();
    assert.equal(sink.envelopes.length, 2, "two requests, one per open");
    assert.equal(injected.length, 2, "each launched open injected its guidance");
    const firstTab = served.requests.filter(
      (r) => r.port === firstPort && r.url.startsWith("/api/external-annotations"),
    );
    assert.deepEqual(
      firstTab.map((r) => `${r.method} ${r.url}`),
      ["DELETE /api/external-annotations?source=perk%3Awave", "POST /api/external-annotations"],
      "the first tab got the detached marker",
    );
    assert.ok(firstTab[1]?.body.includes(reviewDetachedStatus("replaced")));
    assert.ok(
      h.notifies.some((n) =>
        n.includes("the earlier browser review (stack-review-browser) was replaced"),
      ),
    );
    // The first review's late settle never clears the second's surface.
    sink.envelopes[0]?.respond({ status: "handled", result: { approved: true } });
    for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 5));
    assert.equal(await sessionSurfacePrimed(h), true, "the second review's surface survives");
    // The pin is (re)bound: a stack wave for this stack is no binding refusal.
    const bound = await h.invokeTool("start_review_wave", {
      angles: ["claimed-intent", "tests"],
      pr: 42,
      worktree: planted.checkoutPath,
      stack: true,
    });
    const boundType = (bound.details as { error_type?: string }).error_type;
    assert.notEqual(boundType, "bad_state");
    assert.notEqual(boundType, "bad_input");
  } finally {
    await settleBridges(sink);
    await Promise.all(
      served.servers.map((server) => new Promise((resolve) => server.close(() => resolve(null)))),
    );
    h.dispose();
  }
});

test("/stack-review-browser 77 in a discovery-cohort session: REVIEW_BROWSER_PRIMES are active when the guidance is sent", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const planted = plantStackCheckout(cwd);
  const bin = fakePerk(cwd, { stdout: planted.json });
  const sink: FakeBrowser = { envelopes: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink), toolSearch()],
    settings: COHORT_SETTINGS,
  });
  const spy = spyInjectionLoadouts(h);
  try {
    for (const name of REVIEW_BROWSER_PRIMES)
      assert.ok(!h.session.getActiveToolNames().includes(name), `${name} deferred at startup`);
    await h.runCommandHandler("stack-review-browser", "77");
    assert.equal(spy.injected.length, 1, "one guidance injection");
    for (const name of REVIEW_BROWSER_PRIMES) {
      assert.ok(spy.injected[0]?.includes(name), `the guidance names ${name}`);
      assert.ok(spy.active[0]?.includes(name), `${name} active when the guidance is sent`);
    }
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});

test("/stack-review-browser: a missing or digest-mismatched patch reports the reason and emits NO request", async () => {
  for (const arm of ["missing", "mismatch"] as const) {
    const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
    const planted = plantStackCheckout(cwd);
    if (arm === "mismatch") {
      // Refresh residue: the checkout envelope names a digest the file no longer has.
      writeFileSync(patchPathFor(planted.checkoutPath), `${PATCH_TEXT}moved\n`, "utf8");
    }
    let json = planted.json;
    if (arm === "missing") {
      // A checkout dir with NO sibling patch beside it.
      mkdirSync(join(cwd, "review-gone"));
      json = JSON.stringify({ ...STACK_CHECKOUT_PAYLOAD, path: join(cwd, "review-gone") });
    }
    const bin = fakePerk(cwd, { stdout: json });
    const sink: FakeBrowser = { envelopes: [] };
    const h = await loadPerkSession({
      cwd,
      env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
      extraExtensions: [fakePlannotator(sink)],
    });
    const injected = spyInjections(h);
    try {
      await h.runCommandHandler("stack-review-browser", "77");
      assert.ok(
        h.notifies.some((n) => n.includes(`${arm}:`) && n.includes(".patch")),
        `${arm}: the refusal names the reason and the patch path`,
      );
      assert.equal(sink.envelopes.length, 0, `${arm}: no bridge emitted`);
      assert.equal(injected.length, 0, `${arm}: nothing injected`);
      const wave = await h.invokeTool("start_review_wave", {
        angles: ["claimed-intent", "tests"],
        pr: 42,
        worktree: planted.checkoutPath,
        stack: true,
      });
      assert.equal(
        (wave.details as { error_type?: string }).error_type,
        "bad_state",
        `${arm}: no pin was bound`,
      );
    } finally {
      h.dispose();
    }
  }
});

test("/stack-review-browser (no target): the active_objective ladder feeds --objective", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [{ active_objective: "9" }]);
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: plantStackCheckout(cwd).json, argvFile });
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
function scaffoldStackLaunch(
  opts: { checkout?: boolean; binding?: boolean; patch?: "ok" | "missing" | "mismatch" } = {},
): {
  cwd: string;
  checkoutPath: string;
} {
  const cwd = scaffoldRepo({
    handoff: { runId: RUN_ID, mode: "read-write", stage: "stack-review" },
  });
  const checkoutPath = join(cwd, "review-42");
  if (opts.checkout !== false) mkdirSync(checkoutPath, { recursive: true });
  const patch = opts.patch ?? "ok";
  if (patch === "ok") writeFileSync(patchPathFor(checkoutPath), PATCH_TEXT, "utf8");
  if (patch === "mismatch") writeFileSync(patchPathFor(checkoutPath), `${PATCH_TEXT}x\n`, "utf8");
  const binding = {
    stack: [ROW_A, ROW_B],
    checkout_path: checkoutPath,
    notes: ["drift: PR #41 head moved"],
    focus: "dig into CI",
    base_sha: "0".repeat(40),
    patch_sha256: PATCH_SHA256,
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

test("open_stack_review: a missing or digest-mismatched patch is bad_state naming the path, nothing opened", async () => {
  for (const arm of ["missing", "mismatch"] as const) {
    const { cwd, checkoutPath } = scaffoldStackLaunch({ patch: arm });
    const sink: FakeBrowser = { envelopes: [] };
    const h = await loadPerkSession({
      cwd,
      env: { PERK_RUN_ID: RUN_ID },
      extraExtensions: [fakePlannotator(sink)],
    });
    try {
      const result = await h.invokeTool("open_stack_review", {});
      const details = result.details as { ok: boolean; error_type?: string };
      assert.equal(details.ok, false, arm);
      assert.equal(details.error_type, "bad_state", arm);
      const text = result.content[0]?.text ?? "";
      assert.ok(text.includes(patchPathFor(checkoutPath)), `${arm}: names the patch path`);
      if (arm === "mismatch") assert.match(text, /refreshed since this snapshot was taken/);
      assert.equal(sink.envelopes.length, 0, `${arm}: no bridge emitted`);
      // The latch stays open: a repaired patch lets a later call succeed.
      writeFileSync(patchPathFor(checkoutPath), PATCH_TEXT, "utf8");
      const repaired = await h.invokeTool("open_stack_review", {});
      assert.equal((repaired.details as { ok: boolean }).ok, true, `${arm}: repairable`);
      await settleBridges(sink);
    } finally {
      await settleBridges(sink);
      h.dispose();
    }
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
    assert.ok(
      text.includes(pinnedReviewContextCommand({ ...PINNED, checkout: checkoutPath })),
      "the guidance carries the pinned review-context command",
    );
    assert.equal(sink.envelopes.length, 1, "the bridge request was emitted");
    assert.deepEqual(sink.envelopes[0]?.payload, {
      cwd: checkoutPath,
      patchFile: patchPathFor(checkoutPath),
    });
    // The open bound the pin for this activation's wave tool.
    const bound = await h.invokeTool("start_review_wave", {
      angles: ["claimed-intent", "tests"],
      pr: 42,
      worktree: checkoutPath,
      stack: true,
    });
    const boundType = (bound.details as { error_type?: string }).error_type;
    assert.notEqual(boundType, "bad_state");
    assert.notEqual(boundType, "bad_input");
    // The cold launch primes THIS activation's threaded annotation state (a fresh/wrong state
    // here would leave push_annotations refusing no_surface while the browser sits open).
    assert.equal(await sessionSurfacePrimed(h), true, "the open primed the annotation surface");

    const second = await h.invokeTool("open_stack_review", {});
    const secondDetails = second.details as { ok: boolean; error_type?: string };
    assert.equal(secondDetails.ok, false);
    assert.equal(secondDetails.error_type, "bad_state");
    assert.match(second.content[0]?.text ?? "", /single-use/);
    assert.equal(sink.envelopes.length, 1, "no second bridge");

    // The same settle discipline as the warm door: the bridge settle clears the surface.
    await settleBridges(sink);
    const start = Date.now();
    while ((await sessionSurfacePrimed(h)) && Date.now() - start < 5000) {
      await new Promise((r) => setTimeout(r, 25));
    }
    assert.equal(await sessionSurfacePrimed(h), false, "the bridge settle cleared the surface");
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});

/**
 * The execute-core scaffold over a claimed launch: a fake pi (plannotator present, a fake bus
 * recording each `code-review` request, injections) and a ctx whose branch carries the run id.
 */
function executeScaffold() {
  const { cwd, checkoutPath } = scaffoldStackLaunch();
  const branch = [{ type: "custom", customType: "perk:workflow-state", data: { run_id: RUN_ID } }];
  const handlers = new Set<(data: unknown) => void>();
  const envelopes: CodeReviewEnvelope[] = [];
  const injected: string[] = [];
  const notified: { message: string; severity?: string }[] = [];
  const bus = {
    emit(name: string, data?: unknown) {
      if (name === "plannotator:request") envelopes.push(data as CodeReviewEnvelope);
      for (const handler of [...handlers]) handler(data);
    },
    on(_name: string, handler: (data: unknown) => void) {
      handlers.add(handler);
      return () => handlers.delete(handler);
    },
  };
  const pi = {
    events: bus,
    getCommands: () => [{ name: "plannotator-review" }],
    sendUserMessage(message: string) {
      injected.push(message);
    },
  } as unknown as ExtensionAPI;
  const ctx = {
    cwd,
    hasUI: true,
    sessionManager: { getBranch: () => branch },
    ui: {
      notify: (message: string, severity?: string) => notified.push({ message, severity }),
      setStatus: () => {},
    },
    isIdle: () => true,
    signal: undefined,
  } as unknown as ExtensionContext;
  return { cwd, checkoutPath, envelopes, injected, notified, pi, ctx };
}

/** A fake open seam returning `result` and recording what it was asked to open. */
function fakeOpen(result: StackOpenResult): {
  open: StackBrowserOpen;
  opens: { checkoutPath: string; patchSha256: string }[];
} {
  const opens: { checkoutPath: string; patchSha256: string }[] = [];
  return {
    opens,
    open: (_ctx, opts) => {
      opens.push({ checkoutPath: opts.checkoutPath, patchSha256: opts.patchSha256 });
      return Promise.resolve(
        result.kind === "launched" ? { ...result, guidance: opts.guidance } : result,
      );
    },
  };
}

const LAUNCHED: StackOpenResult = { kind: "launched", guidance: "" };

test("executeOpenStackReview: a stack wave pending against a DIFFERENT pin refuses bad_state before any open; the same pin proceeds", async () => {
  const s = executeScaffold();
  const bound = pinnedStackOf(42, s.checkoutPath, "0".repeat(40), [ROW_A, ROW_B]);
  const otherStack = pinnedStackOf(9, join(s.cwd, "review-9"), "1".repeat(40), [
    { ...ROW_A, pr: 8 },
    { ...ROW_B, pr: 9 },
  ]);
  const seam = fakeOpen(LAUNCHED);

  // A wave still in flight against another stack: refused, nothing opened (the owner is never
  // reached), latch untouched.
  const latch = { opened: false };
  const busy = { pinned: otherStack, inFlight: otherStack };
  const refused = await executeOpenStackReview(s.pi, s.ctx, latch, busy, seam.open);
  const refusedDetails = refused.details as { ok: boolean; error_type?: string };
  assert.equal(refusedDetails.ok, false);
  assert.equal(refusedDetails.error_type, "bad_state");
  assert.match(
    refused.content[0]?.text ?? "",
    /still pending against the open stack review \(top PR #9/,
  );
  assert.deepEqual(seam.opens, [], "no open attempted");
  assert.equal(latch.opened, false);
  assert.deepEqual(busy.pinned, otherStack, "the pending review's pin is untouched");

  // The SAME pin in flight (a stale-session reopen): proceeds.
  const same = { pinned: bound, inFlight: bound };
  const ok = await executeOpenStackReview(s.pi, s.ctx, latch, same, seam.open);
  assert.equal((ok.details as { ok: boolean }).ok, true, ok.content[0]?.text);
  assert.deepEqual(seam.opens, [{ checkoutPath: s.checkoutPath, patchSha256: PATCH_SHA256 }]);
});

test("executeOpenStackReview: a browser-open failure is browser_failed and keeps the latch closed; the same latch then accepts a launched open which BINDS the pin, and only then does single-use bite", async () => {
  const s = executeScaffold();
  const latch = { opened: false };
  const stackPin = createStackPinState();
  const unlaunched = fakeOpen({ kind: "unlaunched" });
  const failed = await executeOpenStackReview(s.pi, s.ctx, latch, stackPin, unlaunched.open);
  const failedDetails = failed.details as { ok: boolean; error_type?: string };
  assert.equal(failedDetails.ok, false);
  assert.equal(failedDetails.error_type, "browser_failed");
  assert.match(failed.content[0]?.text ?? "", /could not start the plannotator review server/);
  assert.deepEqual(
    unlaunched.opens,
    [{ checkoutPath: s.checkoutPath, patchSha256: PATCH_SHA256 }],
    "the open was attempted with the bound checkout and the snapshot's patch digest",
  );
  assert.equal(latch.opened, false, "a failed open never consumes the single-use latch");
  assert.equal(stackPin.pinned, null, "a failed open binds no pin");

  // The failure is retryable: the SAME latch accepts a later launched open — the execute core
  // (not the seam) binds the verified snapshot's pins…
  const launched = fakeOpen(LAUNCHED);
  const succeeded = await executeOpenStackReview(s.pi, s.ctx, latch, stackPin, launched.open);
  assert.equal((succeeded.details as { ok: boolean }).ok, true);
  assert.match(succeeded.content[0]?.text ?? "", /topped by PR #42/, "the guidance is the ok text");
  assert.equal(latch.opened, true);
  assert.deepEqual(
    stackPin.pinned,
    pinnedStackOf(42, s.checkoutPath, "0".repeat(40), [ROW_A, ROW_B]),
    "a launched open binds the verified snapshot's pins",
  );
  // …and only then does single-use bite.
  const third = await executeOpenStackReview(s.pi, s.ctx, latch, stackPin, launched.open);
  const thirdDetails = third.details as { ok: boolean; error_type?: string };
  assert.equal(thirdDetails.ok, false);
  assert.equal(thirdDetails.error_type, "bad_state");
  assert.equal(launched.opens.length, 1, "the single-use refusal opens nothing");
});

test("executeOpenStackReview: a retired open consumes the latch and returns the non-terminating retired result (ok:true, details.status retired, no pin bound)", async () => {
  const s = executeScaffold();
  const latch = { opened: false };
  const stackPin = createStackPinState();
  const retired = fakeOpen({ kind: "retired" });
  const result = await executeOpenStackReview(s.pi, s.ctx, latch, stackPin, retired.open);
  assert.deepEqual(result.details, {
    ok: true,
    status: "retired",
    top_pr: 42,
    checkout_path: s.checkoutPath,
    member_count: 2,
  });
  assert.equal(result.terminate, undefined, "non-terminating");
  assert.equal(
    result.content[0]?.text,
    "a newer browser review replaced this open before it started — nothing was opened; follow " +
      "that review's guidance and do not call open_stack_review again (single-use)",
  );
  assert.equal(latch.opened, true, "the latch is consumed — no retry can retire the newer review");
  assert.equal(stackPin.pinned, null, "no pin bound");
  const again = await executeOpenStackReview(s.pi, s.ctx, latch, stackPin, retired.open);
  assert.equal((again.details as { error_type?: string }).error_type, "bad_state");
  assert.equal(retired.opens.length, 1, "the second call opens nothing");
});

test("executeOpenStackReview: a refused open (launch-time digest drift) is bad_state naming the patch path, binds no pin and keeps the latch closed", async () => {
  const s = executeScaffold();
  const latch = { opened: false };
  const stackPin = createStackPinState();
  const detail = `mismatch: the stack's combined patch at '${patchPathFor(s.checkoutPath)}' does not match`;
  const refused = fakeOpen({ kind: "refused", detail });
  const result = await executeOpenStackReview(s.pi, s.ctx, latch, stackPin, refused.open);
  const details = result.details as { ok: boolean; error_type?: string; error?: string };
  assert.equal(details.ok, false);
  assert.equal(details.error_type, "bad_state");
  assert.ok(details.error?.includes(patchPathFor(s.checkoutPath)), details.error);
  assert.equal(latch.opened, false, "a refused open is retryable after a re-snapshot");
  assert.equal(stackPin.pinned, null, "a refused open binds no pin");
});

// --- the stack open over the real browser-operation owner --------------------------------------------

/** A readiness probe gated by the test: the FIRST probe waits for `release`, later ones answer. */
function gatedProbe(): { probe: () => Promise<boolean>; release(): void } {
  let release: (ready: boolean) => void = () => {};
  const gate = new Promise<boolean>((resolve) => {
    release = resolve;
  });
  let calls = 0;
  return {
    probe: () => {
      calls += 1;
      return calls === 1 ? gate : Promise.resolve(true);
    },
    release: () => release(true),
  };
}

/** Poll `done()` on real timers (bounded — a stuck condition fails the assertion, never hangs). */
async function until(done: () => boolean | Promise<boolean>, ms = 2000): Promise<void> {
  const start = Date.now();
  while (!(await done()) && Date.now() - start < ms) {
    await new Promise((r) => setTimeout(r, 5));
  }
}

for (const drift of [true, false]) {
  test(
    drift
      ? "stack open: the patch is rewritten while the owner waits for a predecessor's retirement → the launch refuses on the digest, no request is emitted, nothing is primed, no pin is bound, the earlier review is already detached"
      : "stack open (control): an unchanged patch across the same predecessor hold launches",
    async () => {
      const s = executeScaffold();
      const annotations = createAnnotationState();
      const pushes: { method: string; url: string; body?: string }[] = [];
      const recording: FetchLike = async (url, init) => {
        pushes.push({ method: init.method, url, body: init.body });
        return {
          ok: true,
          status: init.method === "POST" ? 201 : 200,
          text: async () => (init.method === "POST" ? '{"ids":[]}' : '{"removed":0}'),
        };
      };
      const gated = gatedProbe();
      const ports = [45051, 45052];
      const owner = createBrowserOperationOwner(s.pi, {
        annotations,
        gating: { primeDeferred: (names) => [...names] },
        status: createPerkStatus(),
        browserDeps: {
          pickFreePort: async () => ports.shift() ?? 45099,
          probe: gated.probe,
          intervalMs: 1,
          budgetMs: 50,
          sleep: async () => {},
        },
        annotationDeps: { fetchLike: recording },
        consoleQuietMs: 10,
        // The owner's budgets never expire here: the predecessor's quiesce truly holds the start.
        sleep: () => new Promise<void>(() => {}),
      });
      const open: StackBrowserOpen = (ctx, opts) => openStackBrowser(s.pi, ctx, owner, opts);
      const stackPin = createStackPinState();
      try {
        // The earlier review (A): a launched open whose readiness poll is still in its first probe.
        const first = await open(s.ctx, {
          checkoutPath: s.checkoutPath,
          patchSha256: PATCH_SHA256,
          guidance: "A",
        });
        assert.equal(first.kind, "launched");
        assert.equal(s.envelopes.length, 1);
        const surfaceA = annotations.surface;
        assert.ok(surfaceA !== null, "A primed the surface");

        // The tool's open (B) passes its pre-open digest gate, then waits on A's retirement.
        const latch = { opened: false };
        const pending = executeOpenStackReview(s.pi, s.ctx, latch, stackPin, open);
        await until(() => pushes.length === 2);
        assert.deepEqual(
          pushes.map((push) => `${push.method} ${push.url}`),
          [
            "DELETE http://127.0.0.1:45051/api/external-annotations?source=perk%3Awave",
            "POST http://127.0.0.1:45051/api/external-annotations",
          ],
          "A is already detached (marked replaced on A's tab) while B waits",
        );
        assert.match(pushes[1]?.body ?? "", /a newer browser review replaced it/);
        if (drift) {
          // A `perk pr review checkout --stack` refresh lands inside the hold.
          writeFileSync(patchPathFor(s.checkoutPath), `${PATCH_TEXT}refreshed\n`, "utf8");
        }
        gated.release(); // A's poll ends → A quiesces → B's start proceeds.
        const result = await pending;

        if (drift) {
          const details = result.details as { ok: boolean; error_type?: string; error?: string };
          assert.equal(details.ok, false);
          assert.equal(details.error_type, "bad_state");
          assert.match(details.error ?? "", /^mismatch: .*refreshed since this snapshot was taken/);
          assert.ok(details.error?.includes(patchPathFor(s.checkoutPath)));
          assert.equal(s.envelopes.length, 1, "no request was emitted for B");
          assert.equal(annotations.surface, null, "nothing primed (A's surface already closed)");
          assert.equal(stackPin.pinned, null, "no pin bound");
          assert.equal(latch.opened, false, "the latch stays closed");
          assert.ok(
            s.notified.some(
              (n) =>
                n.severity === "error" &&
                n.message === `perk: stack-review-browser — ${details.error}`,
            ),
            "the owner reported the refusal verbatim",
          );
          assert.ok(
            !s.notified.some((n) => n.message.includes("could not pick a free local port")),
            "never the port-pick line",
          );
        } else {
          assert.equal((result.details as { ok: boolean }).ok, true, result.content[0]?.text);
          assert.equal(s.envelopes.length, 2, "B's request was emitted");
          assert.notEqual(annotations.surface, null);
          assert.notEqual(annotations.surface, surfaceA, "B re-primed a NEW surface");
          assert.equal(annotations.surface?.url, "http://127.0.0.1:45052");
          assert.notEqual(stackPin.pinned, null, "the launched open bound the pin");
          assert.equal(latch.opened, true);
        }
      } finally {
        for (const envelope of s.envelopes) {
          envelope.respond({ status: "handled", result: { approved: true } });
        }
        await until(() => !("PLANNOTATOR_PORT" in process.env));
      }
    },
  );
}
