// Tests for the warm `/pr-review-browser` door. The pure `prReviewBrowserGuidance` +
// `observeBrowserReadiness` are pinned directly; the command's entry gates / checkout /
// active-PR resolution / injection run against a REAL bound session via the T1 harness, OFFLINE
// (a fake `perk` stands in for the cold doors, and a fake plannotator extension registers the
// presence-probe command + a bus listener that stands in for the browser). The arg parse is
// `parsePrReviewTerminalArgs` — pinned in prReviewTerminal.test.ts, not re-pinned here.

import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { writePlanRef } from "../substrate/cache.ts";
import { fakePerk, loadPerkSession, scaffoldRepo, spyInjections } from "../testing/harness.ts";
import type { CodeReviewOutcome, StartedBrowser } from "./plannotatorHandoff.ts";
import { observeBrowserReadiness, prReviewBrowserGuidance } from "./prReviewBrowser.ts";

// --- prReviewBrowserGuidance ---------------------------------------------------------------------

const FOREIGN_OPTS = {
  mode: "foreign" as const,
  pr: 148,
  prUrl: "https://github.com/o/r/pull/148",
  worktree: "/wt/review-148",
  url: "http://127.0.0.1:45001",
};

const ACTIVE_OPTS = {
  mode: "active" as const,
  pr: 148,
  prUrl: "https://github.com/o/r/pull/148",
  worktree: "/repo/.worktrees/plan-148",
  url: "http://127.0.0.1:45001",
};

test("guidance(foreign): FOREIGN framing + the background-open URL + cleanup step", () => {
  const text = prReviewBrowserGuidance(FOREIGN_OPTS);
  assert.match(text, /FOREIGN PR #148/);
  assert.match(text, /untrusted foreign code/);
  assert.ok(text.includes("https://github.com/o/r/pull/148"), "the pr_url threads through");
  assert.ok(text.includes("`/wt/review-148`"), "the worktree path threads through");
  assert.ok(
    text.includes("POST http://127.0.0.1:45001/api/external-annotations"),
    "the annotation endpoint is baked in",
  );
  assert.match(text, /opening the plannotator browser in the BACKGROUND/);
  assert.doesNotMatch(text, /hunk/, "no terminal-surface strings");
  assert.match(text, /perk pr review cleanup --pr 148/);
  assert.match(text, /perk\.adversarial-reviewer/);
  assert.match(text, /submit_pr_review/);
  assert.match(text, /dry_run: true/);
});

test("guidance(active): no cleanup, no detached-checkout framing, the own-PR note", () => {
  const text = prReviewBrowserGuidance(ACTIVE_OPTS);
  assert.doesNotMatch(text, /review cleanup/);
  assert.doesNotMatch(text, /detached/);
  assert.doesNotMatch(text, /untrusted foreign code/);
  assert.match(text, /ACTIVE worktree/);
  assert.ok(text.includes("`/repo/.worktrees/plan-148`"));
  assert.ok(text.includes("POST http://127.0.0.1:45001/api/external-annotations"));
  assert.match(text, /own_pr/); // formal verdicts on the human's own PR — the common case here
  assert.match(text, /perk pr review-context --pr 148/);
  assert.match(text, /perk\.adversarial-reviewer/);
});

test("guidance: the model and directive arms render/omit on foreign and active", () => {
  for (const opts of [FOREIGN_OPTS, ACTIVE_OPTS]) {
    const withModel = prReviewBrowserGuidance({ ...opts, model: "anthropic/claude-opus-4" });
    assert.match(withModel, /model: "anthropic\/claude-opus-4"/);
    assert.match(withModel, /\[models\.subagents\] adversarial-reviewer model/);
    const withDirective = prReviewBrowserGuidance({ ...opts, directive: "dig into CI" });
    assert.match(withDirective, /Operator focus for this run/);
    assert.match(withDirective, /dig into CI/);
    assert.match(withDirective, /claimed-intent stays mandatory/);
    const bare = prReviewBrowserGuidance(opts);
    assert.doesNotMatch(bare, /model: "/);
    assert.doesNotMatch(bare, /Operator focus for this run/);
  }
});

test("guidance(both modes): the async streaming-wave pins", () => {
  for (const opts of [FOREIGN_OPTS, ACTIVE_OPTS]) {
    const text = prReviewBrowserGuidance(opts);
    assert.match(text, /async: true/, "the fan-out is async");
    assert.match(text, /wait\(\{ timeoutMs: 30000 \}\)/, "the wait loop is the streaming cadence");
    assert.match(text, /Subagent progress update/, "progress-update batches are processed");
    assert.match(text, /never re-push an anchor already pushed/, "incremental path+line dedupe");
    assert.match(text, /Hold-and-accumulate until a POST succeeds/, "a refused POST ≠ a degrade");
    assert.match(text, /NEVER a degrade/);
    assert.match(
      text,
      /completion reports are the \*\*source of truth\*\*/,
      "completion reports drive the reconcile",
    );
    assert.match(text, /never receive the surface handle/);
    assert.match(text, /not the URL, not the port/, "children get no browser details");
    assert.ok(
      text.includes("Never `GET http://127.0.0.1:45001/api/diff`"),
      "the diff route stays forbidden",
    );
  }
});

test("guidance(both modes): the flipped posting contract — native post is THE GitHub path", () => {
  for (const opts of [FOREIGN_OPTS, ACTIVE_OPTS]) {
    const text = prReviewBrowserGuidance(opts);
    assert.match(text, /that is the GitHub path/);
    assert.match(text, /perk composes nothing by default/);
    assert.match(text, /ONLY for a \*\*request-changes\*\* verdict/);
    assert.match(text, /end your turn/);
    assert.doesNotMatch(text, /read back/i, "the read-back/dedupe contract is deleted");
  }
});

test("guidance: no hardcoded perk-review skill pointer (the binding suffix delivers it)", () => {
  for (const opts of [FOREIGN_OPTS, ACTIVE_OPTS] as const) {
    assert.doesNotMatch(prReviewBrowserGuidance(opts), /Follow the `perk-review` skill/);
  }
});

// --- observeBrowserReadiness (the background readiness observer) ---------------------------------

const HANDLED: CodeReviewOutcome = {
  status: "handled",
  approved: true,
  feedback: undefined,
  annotationCount: 0,
  annotations: [],
  exit: false,
};

function fakeStarted(
  readiness: "ready" | "timeout" | "bridge_settled" | "aborted",
  bridge: CodeReviewOutcome = HANDLED,
): StartedBrowser {
  return {
    url: "http://127.0.0.1:45001",
    port: 45001,
    bridgePromise: Promise.resolve(bridge),
    readiness: Promise.resolve(readiness),
  };
}

async function observe(
  started: StartedBrowser,
  opts?: { idle?: boolean },
): Promise<{ notifies: { message: string; severity?: string }[]; sent: { message: string; options?: { deliverAs?: string } }[] }> {
  const notifies: { message: string; severity?: string }[] = [];
  const sent: { message: string; options?: { deliverAs?: string } }[] = [];
  await observeBrowserReadiness(
    {
      sendUserMessage: (message: string, options?: { deliverAs?: "steer" | "followUp" }) => {
        sent.push(options === undefined ? { message } : { message, options });
      },
    },
    {
      hasUI: true,
      ui: { notify: (message: string, severity?: string) => notifies.push({ message, severity }) },
      isIdle: () => opts?.idle ?? true,
    },
    started,
  );
  return { notifies, sent };
}

test("observer: ready → the info note naming the URL, nothing injected", async () => {
  const { notifies, sent } = await observe(fakeStarted("ready"));
  assert.equal(sent.length, 0);
  assert.equal(notifies.length, 1);
  assert.match(notifies[0]?.message ?? "", /plannotator is up at http:\/\/127\.0\.0\.1:45001/);
  assert.equal(notifies[0]?.severity, "info");
});

test("observer: timeout → a loud error + the degrade notice (idle → immediate)", async () => {
  const { notifies, sent } = await observe(fakeStarted("timeout"));
  assert.equal(notifies.length, 1);
  assert.equal(notifies[0]?.severity, "error");
  assert.match(notifies[0]?.message ?? "", /did not become ready at http:\/\/127\.0\.0\.1:45001/);
  assert.equal(sent.length, 1, "the degrade notice is injected");
  assert.match(sent[0]?.message ?? "", /browser review is unavailable/);
  assert.match(sent[0]?.message ?? "", /render the reviewers' reconciled findings as a table/);
  assert.match(sent[0]?.message ?? "", /perk composes nothing by default/);
  assert.equal(sent[0]?.options, undefined, "idle ⇒ an immediate turn");
});

test("observer: timeout while streaming → the degrade notice rides followUp", async () => {
  const { sent } = await observe(fakeStarted("timeout"), { idle: false });
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0]?.options, { deliverAs: "followUp" });
});

test("observer: a bridge settled error/unavailable → error + degrade; handled/aborted → silent", async () => {
  const degraded = await observe(fakeStarted("bridge_settled", { status: "error", warning: "boom" }));
  assert.equal(degraded.notifies.length, 1);
  assert.equal(degraded.notifies[0]?.severity, "error");
  assert.equal(degraded.sent.length, 1, "the degrade notice is injected");

  const handled = await observe(fakeStarted("bridge_settled", HANDLED));
  assert.equal(handled.notifies.length, 0, "the respond routing owns the handled arm");
  assert.equal(handled.sent.length, 0);

  const aborted = await observe(fakeStarted("bridge_settled", { status: "aborted" }));
  assert.equal(aborted.notifies.length, 0);
  assert.equal(aborted.sent.length, 0);

  const turnAborted = await observe(fakeStarted("aborted"));
  assert.equal(turnAborted.notifies.length, 0, "an aborted turn stays silent");
  assert.equal(turnAborted.sent.length, 0);
});

// --- the command flow through the harness --------------------------------------------------------

const CHECKOUT_OK_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  path: "/wt/review-77",
  pr: 77,
  url: "https://github.com/o/r/pull/77",
  head_sha: "aaaabbbbccccddddeeeeffff0000111122223333",
  base_sha: "0123456789abcdef0123456789abcdef01234567",
  base_ref: "main",
});

const PR_URL_OK_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  pr: { number: 42, url: "https://github.com/o/r/pull/42" },
});

/** The plannotator:request envelope the fake browser listener records. */
interface CodeReviewEnvelope {
  requestId: string;
  action: string;
  payload: { prUrl?: string; cwd: string; diffType?: string; defaultBranch?: string };
  respond: (response: unknown) => void;
}

interface FakeBrowser {
  envelopes: CodeReviewEnvelope[];
  envAtEmit: (string | undefined)[];
}

/**
 * A fake plannotator extension: registers the `plannotator-review` presence-probe target and a
 * bus listener that records each `code-review` envelope (+ `PLANNOTATOR_PORT` at emit time) so
 * tests can respond explicitly. Never responds on its own — a test's `finally` settles the
 * bridge so the background readiness poll ends promptly.
 */
function fakePlannotator(sink: FakeBrowser): (pi: ExtensionAPI) => void {
  return (pi) => {
    pi.registerCommand("plannotator-review", {
      description: "fake plannotator (test)",
      handler: async () => {},
    });
    pi.events.on("plannotator:request", (data) => {
      sink.envelopes.push(data as CodeReviewEnvelope);
      sink.envAtEmit.push(process.env.PLANNOTATOR_PORT);
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

/** The path-carrying nudge pointer line the binding suffix delivers for `skill`. */
function pointer(skill: string): string {
  return `Follow the \`${skill}\` skill (read \`.agents/skills/${skill}/SKILL.md\`).`;
}

/** Plant the plan-ref the active/local arms read their pinned base from. */
function plantPlanRef(cwd: string, base: string | null): void {
  writePlanRef(cwd, {
    provider: "github",
    pr_id: "42",
    url: "https://github.com/o/r/issues/42",
    labels: [],
    objective_id: null,
    base,
  });
}

test("/pr-review-browser: registers; an unparseable PR URL reports usage, no work", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON, argvFile });
  const sink: FakeBrowser = { envelopes: [], envAtEmit: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    assert.ok(h.registeredCommands().includes("pr-review-browser"), "the command is registered");
    await h.runCommandHandler("pr-review-browser", "https://github.com/o/r/issues/45");
    assert.ok(
      h.notifies.some((n) => n.includes("usage: /pr-review-browser [pr number|url] [focus note]")),
      "usage reported",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(existsSync(argvFile), false, "no cold door executed");
    assert.equal(sink.envelopes.length, 0, "no bridge emitted");
  } finally {
    h.dispose();
  }
});

test("/pr-review-browser: headless → refusal, nothing executed", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON, argvFile });
  const sink: FakeBrowser = { envelopes: [], envAtEmit: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    headful: false,
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-browser", "77");
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(existsSync(argvFile), false, "no cold door executed");
    assert.equal(sink.envelopes.length, 0, "no bridge emitted");
  } finally {
    h.dispose();
  }
});

test("/pr-review-browser: plannotator absent → the pinned provider-selection refusal, no work", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-browser", "77");
    assert.ok(
      h.notifies.some(
        (n) =>
          n.includes("the plannotator extension is not loaded") &&
          n.includes('select a plannotator provider (`[providers] plan = "plannotator"` or') &&
          n.includes('`review = "plannotator-review"`), run `perk init`, then restart pi'),
      ),
      "the refusal names the fix",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(existsSync(argvFile), false, "no cold door executed");
  } finally {
    h.dispose();
  }
});

test("/pr-review-browser <pr>: a checkout failure (pr_not_found) is surfaced, nothing injected", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const notFound = JSON.stringify({
    success: false,
    error_type: "pr_not_found",
    message: "PR #999 not found",
  });
  const bin = fakePerk(cwd, { stdout: notFound, code: 1 });
  const sink: FakeBrowser = { envelopes: [], envAtEmit: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-browser", "999");
    assert.ok(
      h.notifies.some((n) => n.includes("pr_not_found") && n.includes("PR #999 not found")),
      "the envelope failure is surfaced",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(sink.envelopes.length, 0, "no bridge emitted");
  } finally {
    h.dispose();
  }
});

test("/pr-review-browser <pr>: foreign success injects ONE guidance with the URL and ONE pointer", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON });
  const sink: FakeBrowser = { envelopes: [], envAtEmit: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-browser", "77");
    assert.ok(
      h.notifies.some((n) =>
        n.includes(
          "PR #77 → adversarial reviewers → plannotator browser triage → you post from the browser",
        ),
      ),
      "the info line names the flow",
    );
    assert.equal(injected.length, 1, "one guidance injection");
    const text = injected[0] ?? "";
    assert.match(text, /FOREIGN PR #77/);
    assert.ok(text.includes("`/wt/review-77`"), "the checkout worktree threads through");
    assert.ok(text.includes("https://github.com/o/r/pull/77"), "the pr_url threads through");
    assert.match(
      text,
      /POST http:\/\/127\.0\.0\.1:\d+\/api\/external-annotations/,
      "the deterministic local endpoint is baked in before readiness",
    );
    assert.equal(sink.envelopes.length, 1, "the bridge request was emitted");
    assert.deepEqual(
      sink.envelopes[0]?.payload,
      { cwd, prUrl: "https://github.com/o/r/pull/77" },
      "the PR-mode payload is byte-stable",
    );
    assert.equal(sink.envAtEmit[0], String(new URL(text.match(/http:\/\/127\.0\.0\.1:\d+/)?.[0] ?? "").port), "PLANNOTATOR_PORT preset at emit time");
    const marker = pointer("perk-review");
    assert.equal(text.split(marker).length - 1, 1, "exactly one command:pr-review-browser pointer");
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});

test("/pr-review-browser (no arg): a resolved PR injects the ACTIVE guidance homed at ctx.cwd", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  plantPlanRef(cwd, null);
  const bin = fakePerk(cwd, { stdout: PR_URL_OK_JSON });
  const sink: FakeBrowser = { envelopes: [], envAtEmit: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-browser", "dig into the CI changes");
    assert.ok(
      h.notifies.some((n) =>
        n.includes(
          "PR #42 (active worktree) → adversarial reviewers (focus: dig into the CI changes) → plannotator browser triage → you post from the browser",
        ),
      ),
      "the info line names the active-worktree flow + focus",
    );
    assert.equal(injected.length, 1, "one guidance injection");
    const text = injected[0] ?? "";
    assert.match(text, /ACTIVE worktree/);
    assert.ok(text.includes(`\`${cwd}\``), "ctx.cwd is the worktree");
    assert.doesNotMatch(text, /review cleanup/);
    assert.match(text, /Operator focus for this run/);
    assert.match(text, /dig into the CI changes/);
    assert.deepEqual(
      sink.envelopes[0]?.payload,
      { cwd, prUrl: "https://github.com/o/r/pull/42" },
      "the ladder's url feeds the bridge",
    );
    const marker = pointer("perk-review");
    assert.equal(text.split(marker).length - 1, 1, "exactly one pointer");
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});

test("/pr-review-browser (no arg, no PR yet): the local since-base bridge, NO injection, NO port dance", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  plantPlanRef(cwd, "release-1.x");
  const noPr = JSON.stringify({ success: false, error_type: "no_pr", message: "No PR found" });
  const bin = fakePerk(cwd, { stdout: noPr, code: 1 });
  const sink: FakeBrowser = { envelopes: [], envAtEmit: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-browser", "");
    assert.ok(
      h.notifies.some((n) =>
        n.includes("No PR yet — opening plannotator local review (since-base vs release-1.x)"),
      ),
      "the local-mode note names the pinned base",
    );
    assert.equal(injected.length, 0, "no guidance injection in local mode (no reviewers)");
    assert.equal(sink.envelopes.length, 1, "the local bridge was emitted");
    assert.deepEqual(
      sink.envelopes[0]?.payload,
      { cwd, diffType: "since-base", defaultBranch: "release-1.x" },
      "the local payload pins {cwd, diffType, defaultBranch} and omits prUrl",
    );
    assert.equal(sink.envAtEmit[0], undefined, "no port dance — PLANNOTATOR_PORT never preset");

    // The respond routes under the new scope: exit-before-approved (closed ≠ approved).
    sink.envelopes[0]?.respond({ status: "handled", result: { approved: false, exit: true } });
    for (let i = 0; i < 5; i++) await Promise.resolve();
    assert.ok(
      h.notifies.some(
        (n) => n.includes("pr-review-browser") && n.includes("Code review closed without feedback."),
      ),
      "the exit arm reports under the pr-review-browser scope",
    );
    assert.ok(
      !h.notifies.some((n) => n.includes("approved — no changes requested")),
      "closed-without-feedback never reports as approved",
    );
    assert.equal(injected.length, 0, "still nothing injected");
  } finally {
    h.dispose();
  }
});

test("/pr-review-browser (no arg, no PR yet): feedback + annotations inject the triage turn", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  plantPlanRef(cwd, null);
  const noPr = JSON.stringify({ success: false, error_type: "no_pr", message: "No PR found" });
  const bin = fakePerk(cwd, { stdout: noPr, code: 1 });
  const sink: FakeBrowser = { envelopes: [], envAtEmit: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-browser", "");
    assert.ok(
      h.notifies.some((n) => n.includes("since-base vs repo default")),
      "a null base names the repo default",
    );
    sink.envelopes[0]?.respond({
      status: "handled",
      result: { approved: false, feedback: "fix X", annotations: [{}] },
    });
    for (let i = 0; i < 5; i++) await Promise.resolve();
    assert.equal(injected.length, 1, "the feedback injects a turn");
    assert.ok(injected[0]?.startsWith("fix X"));
    assert.match(injected[0] ?? "", /Triage these review notes first/);
  } finally {
    h.dispose();
  }
});

test("/pr-review-browser (no arg): a no_plan_ref fail arm reports the pass-a-PR hint, nothing injected", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const noPlanRef = JSON.stringify({
    success: false,
    error_type: "no_plan_ref",
    message: "no plan-ref in this worktree",
  });
  const bin = fakePerk(cwd, { stdout: noPlanRef, code: 1 });
  const sink: FakeBrowser = { envelopes: [], envAtEmit: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-browser", "");
    assert.ok(
      h.notifies.some(
        (n) =>
          n.includes("no plan-ref in this worktree") &&
          n.includes("pass a PR number/URL, or run from a plan worktree"),
      ),
      "the fail arm appends the hint",
    );
    assert.equal(injected.length, 0, "nothing injected");
    assert.equal(sink.envelopes.length, 0, "no bridge emitted");
  } finally {
    h.dispose();
  }
});

test("/pr-review-browser <pr>: the configured adversarial-reviewer model threads through", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const { mkdirSync, writeFileSync } = await import("node:fs");
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[models.subagents]\nadversarial-reviewer = "test/model"\n',
    "utf8",
  );
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON });
  const sink: FakeBrowser = { envelopes: [], envAtEmit: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-browser", "77 dig into the CI changes");
    const text = injected[0] ?? "";
    assert.match(text, /model: "test\/model"/);
    assert.match(text, /Operator focus for this run/);
    assert.match(text, /dig into the CI changes/);
    assert.ok(
      h.notifies.some((n) => n.includes("(focus: dig into the CI changes)")),
      "the info line carries the focus",
    );
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});
