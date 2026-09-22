// Tests for the warm `/stack-review-browser` door + the `open_stack_review` cold-launch tool.
// The pure pieces (the explicit target grammar, the snapshot/binding decodes, the guidance
// render, the degrade notice) are pinned directly; the command/tool flows run against a REAL
// bound session via the T1 harness, OFFLINE (a fake `perk` stands in for the cold doors, and a
// fake plannotator extension registers the presence-probe command + a bus listener standing in
// for the browser).

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { type ExtensionAPI, SessionManager } from "@earendil-works/pi-coding-agent";
import { workflowDir } from "../../../substrate/cache.ts";
import { createPerkStatus } from "../../../surfaces/surfaces.ts";
import {
  fakePerk,
  loadPerkSession,
  plantSession,
  scaffoldRepo,
  spyInjections,
} from "../../../testing/harness.ts";
import { pinnedReviewContextCommand } from "../../../waves/adversarialReviewWave.ts";
import { createAnnotationState } from "../providers/annotations.ts";
import { createStackPinState } from "./reviewWave.ts";
import {
  bindingBaseRef,
  bindingTopPr,
  decodeStackCheckout,
  decodeStackReviewBinding,
  executeOpenStackReview,
  parseStackReviewArgs,
  patchPathFor,
  pinnedStackOf,
  STACK_DEGRADE_NOTICE,
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
    ui: { notify: () => {}, setStatus: () => {} },
  } as unknown as Parameters<typeof executeOpenStackReview>[1];

  const latch = { opened: false };
  const stackPin = createStackPinState();
  const opens: { checkoutPath: string; patchPath: string; pinnedTop: number }[] = [];
  const failed = await executeOpenStackReview(
    pi,
    ctx,
    latch,
    createAnnotationState(),
    createPerkStatus(),
    stackPin,
    (_pi, _ctx, _annotations, _status, _pin, opts) => {
      opens.push({
        checkoutPath: opts.checkoutPath,
        patchPath: opts.patchPath,
        pinnedTop: opts.pinned.topPr,
      });
      return Promise.resolve(false);
    },
  );
  const failedDetails = failed.details as { ok: boolean; error_type?: string };
  assert.equal(failedDetails.ok, false);
  assert.equal(failedDetails.error_type, "browser_failed");
  assert.match(failed.content[0]?.text ?? "", /could not start the plannotator review server/);
  assert.deepEqual(
    opens,
    [{ checkoutPath, patchPath: patchPathFor(checkoutPath), pinnedTop: 42 }],
    "the open was attempted with the bound checkout, its verified patch and the pins",
  );
  assert.equal(latch.opened, false, "a failed open never consumes the single-use latch");

  // The failure is retryable: the SAME latch accepts a later successful open (the seam sets
  // the pin the way the real open does)…
  const succeeded = await executeOpenStackReview(
    pi,
    ctx,
    latch,
    createAnnotationState(),
    createPerkStatus(),
    stackPin,
    (_pi, _ctx, _annotations, _status, pin, opts) => {
      pin.pinned = opts.pinned;
      return Promise.resolve(true);
    },
  );
  assert.equal((succeeded.details as { ok: boolean }).ok, true);
  assert.equal(latch.opened, true);
  assert.deepEqual(
    stackPin.pinned,
    pinnedStackOf(42, checkoutPath, "0".repeat(40), [ROW_A, ROW_B]),
    "a successful open binds the verified snapshot's pins",
  );
  // …and only then does single-use bite.
  const third = await executeOpenStackReview(
    pi,
    ctx,
    latch,
    createAnnotationState(),
    createPerkStatus(),
    stackPin,
    () => Promise.resolve(true),
  );
  const thirdDetails = third.details as { ok: boolean; error_type?: string };
  assert.equal(thirdDetails.ok, false);
  assert.equal(thirdDetails.error_type, "bad_state");
});
