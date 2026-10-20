// Tests for the warm `/pr-review-browser` door. The pure `prReviewBrowserGuidance` is pinned
// directly; the code-review open (`openReviewBrowserCore`) runs over a REAL browser-operation
// owner with fake `StartBrowserDeps` + a fake bus (the owner's own lifecycle matrix lives in
// `browserOperation.test.ts`); the command's entry gates / checkout / active-PR resolution /
// injection / replacement / reload run against a REAL bound session via the T1 harness, OFFLINE
// (a fake `perk` stands in for the cold doors, and a fake plannotator extension registers the
// presence-probe command + a bus listener that stands in for the browser). The arg parse is
// `parseReviewDoorArgs` — pinned in terminal.test.ts, not re-pinned here.

import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { createServer as createHttpServer, type Server } from "node:http";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { writePlanRef } from "../../../substrate/cache.ts";
import { createPerkStatus } from "../../../surfaces/surfaces.ts";
import {
  COHORT_SETTINGS,
  fakePerk,
  gitInit,
  loadPerkSession,
  type PerkSession,
  scaffoldRepo,
  spyInjectionLoadouts,
  spyInjections,
  toolSearch,
} from "../../../testing/harness.ts";
import {
  type BrowserOperationOwner,
  createBrowserOperationOwner,
  postDegradeDecisionWarning,
} from "../browserOperation.ts";
import {
  createAnnotationState,
  executePushAnnotations,
  type FetchLike,
} from "../providers/annotations.ts";
import { type StartBrowserDeps, stackRespondMessage } from "../providers/plannotatorHandoff.ts";
import { pickEphemeralPort } from "../providers/plannotatorPort.ts";
import { reviewDetachedStatus } from "../providers/waveStatus.ts";
import {
  DEGRADE_NOTICE,
  openReviewBrowserCore,
  prReviewBrowserGuidance,
  REVIEW_BROWSER_PRIMES,
} from "./browser.ts";
import { STACK_DEGRADE_NOTICE } from "./stack.ts";

/** Probe the SESSION's annotation state through the registered tool (the harness flows). */
async function sessionSurfacePrimed(h: {
  invokeTool(name: string, params: unknown): Promise<{ details: unknown }>;
}): Promise<boolean> {
  const result = await h.invokeTool("push_annotations", { angle: "probe", findings: [] });
  return (result.details as { ok: boolean }).ok;
}

// --- prReviewBrowserGuidance ---------------------------------------------------------------------

const FOREIGN_OPTS = {
  mode: "foreign" as const,
  pr: 148,
  prUrl: "https://github.com/o/r/pull/148",
  worktree: "/wt/review-148",
};

const ACTIVE_OPTS = {
  mode: "active" as const,
  pr: 148,
  prUrl: "https://github.com/o/r/pull/148",
  worktree: "/repo/.worktrees/plan-148",
};

test("guidance(foreign): FOREIGN framing + the background open + cleanup step", () => {
  const text = prReviewBrowserGuidance(FOREIGN_OPTS);
  assert.match(text, /FOREIGN PR #148/);
  assert.match(text, /untrusted foreign code/);
  assert.ok(text.includes("https://github.com/o/r/pull/148"), "the pr_url threads through");
  assert.ok(text.includes("`/wt/review-148`"), "the worktree path threads through");
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
  assert.match(text, /own_pr/); // formal verdicts on the human's own PR — the common case here
  assert.match(text, /perk pr review-context --pr 148/);
  assert.match(text, /perk\.adversarial-reviewer/);
});

test("guidance: the directive arm renders/omits on foreign and active — no model arm exists", () => {
  for (const opts of [FOREIGN_OPTS, ACTIVE_OPTS]) {
    const withDirective = prReviewBrowserGuidance({ ...opts, directive: "dig into CI" });
    assert.match(withDirective, /Operator focus for this run/);
    assert.match(withDirective, /dig into CI/);
    assert.match(withDirective, /claimed-intent stays mandatory/);
    assert.match(withDirective, /verbatim as the `directive` param/);
    const bare = prReviewBrowserGuidance(opts);
    assert.doesNotMatch(bare, /Operator focus for this run/);
    // Model resolution moved into start_review_wave — no model plumbing in any arm.
    for (const text of [withDirective, bare]) {
      assert.doesNotMatch(text, /model: "/);
      assert.doesNotMatch(text, /\[models\.subagents\]/);
    }
  }
});

test("guidance(both modes): the tool-owned completion-only wave pins", () => {
  for (const opts of [FOREIGN_OPTS, ACTIVE_OPTS]) {
    const text = prReviewBrowserGuidance(opts);
    assert.match(text, /start_review_wave/, "the fan-out is the launch tool");
    assert.match(text, /collect_review_wave/, "completion rides the collect tool");
    assert.match(text, /push_annotations/, "annotation delivery rides the push tool");
    // The shared yield partial (`prompts/common/review-wave-yield.md`) is included once.
    assert.match(text, /4\. \*\*Yield\.\*\*/, "the shared yield step is rendered in");
    assert.match(text, /Children do not stream — no finding reaches you before the wave finishes/);
    assert.match(text, /ONLY the matching WORKFLOW completion authorizes the collect call/);
    assert.match(text, /routine successful child completion does not wake you/);
    // The code-owned wave marker + the early-decision policy ride step 1.
    assert.match(text, /'reviewer wave running' marker until the wave lands/);
    assert.match(text, /an early decision is authoritative and forgoes the findings/);
    assert.match(text, /never compose annotation HTTP/, "the tool owns the mechanics");
    assert.match(text, /replace: true/, "the final push is the tool's replace");
    assert.match(text, /disjoint final per-angle arrays/);
    assert.match(text, /visible source names the owning lane/);
    assert.match(text, /`findings: \[\]` is the pure retry/);
    assert.match(
      text,
      /no later wake is promised/,
      "the post-readiness held push degrades in-session",
    );
    assert.match(text, /\{complete, covered, reports, failures\}/, "the typed aggregate");
    assert.match(text, /wave_running/, "the collect grace arm is named");
    assert.match(text, /the \*\*source of truth\*\*/, "final reports drive the reconcile");
    assert.match(text, /never receive the surface handle/);
    assert.match(text, /alongside your findings/);
    assert.match(text, /reported honestly/, "incompleteness is surfaced, never papered over");
    assert.match(
      text,
      /Exactly one source-bound `ponytail` lane is required automatic coverage and appended last/,
    );
    assert.match(text, /outside the 2–3 selection cap/);
    assert.match(text, /MUST NOT be selected or duplicated/);
    assert.match(text, /does not spawn or fall back/);
    assert.match(text, /`skill-unavailable`/);
    // The retired model-authored mechanics and the annotation HTTP surface are gone — including
    // the URL itself: the model never sees the server address.
    for (const gone of [
      /workflowScript/,
      /runs\.all/,
      /subagent_wait|bg_wait|hold your turn open|timeout expiry IS the streaming cadence/,
      /external-annotations/,
      /curl/,
      /127\.0\.0\.1/,
      /localhost/,
      /subagent\(\{\s*action/,
      // The retired streaming protocol: no relay, no provisional batches, no uncovered-source
      // clear, no streamed disclosures.
      /Native-wake relay|Subagent progress update|provisional|streamed|uncovered source/,
    ]) {
      assert.doesNotMatch(text, gone, `retired mechanics must not appear: ${gone}`);
    }
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

test("guidance: no hardcoded perk-pr-review-browser skill pointer (the binding suffix delivers it)", () => {
  for (const opts of [FOREIGN_OPTS, ACTIVE_OPTS] as const) {
    assert.doesNotMatch(prReviewBrowserGuidance(opts), /Follow the `perk-pr-review-browser` skill/);
  }
});

// --- openReviewBrowserCore over a real owner (fake bus + fake deps) ------------------------------

/** A minimal in-process event bus (the pi.events shape the bridge speaks). */
function fakeBus(): {
  emit(name: string, data?: unknown): void;
  on(name: string, handler: (data: unknown) => void): () => void;
} {
  const handlers = new Map<string, Set<(data: unknown) => void>>();
  return {
    emit(name, data) {
      for (const handler of [...(handlers.get(name) ?? [])]) handler(data);
    },
    on(name, handler) {
      let set = handlers.get(name);
      if (set === undefined) {
        set = new Set();
        handlers.set(name, set);
      }
      set.add(handler);
      return () => set?.delete(handler);
    },
  };
}

/** The `code-review` envelope the fake bus records (the core's request). */
interface CoreEnvelope {
  action: string;
  payload: Record<string, unknown>;
  respond: (response: unknown) => void;
}

/**
 * The core-level scaffold: a fake bus recording each `code-review` request (+ the preset port at
 * emit time), a fake pi (bus + injections) and ctx, and the suite-owned annotation state the
 * real owner primes.
 */
function coreScaffold() {
  const bus = fakeBus();
  const envelopes: CoreEnvelope[] = [];
  const portAtEmit: (string | undefined)[] = [];
  bus.on("plannotator:request", (raw) => {
    envelopes.push(raw as CoreEnvelope);
    portAtEmit.push(process.env.PLANNOTATOR_PORT);
  });
  const injected: { message: string; options?: { deliverAs?: string } }[] = [];
  const notified: { message: string; severity?: string }[] = [];
  const pi = {
    events: bus,
    sendUserMessage(message: string, options?: { deliverAs?: string }) {
      injected.push(options === undefined ? { message } : { message, options });
    },
  } as unknown as ExtensionAPI;
  const ctx = {
    cwd: "/wt/review-77",
    hasUI: true,
    ui: {
      notify: (message: string, severity?: string) => notified.push({ message, severity }),
      setStatus: () => {},
    },
    isIdle: () => true,
    signal: undefined,
  } as unknown as ExtensionContext;
  const annotations = createAnnotationState();
  return { bus, envelopes, portAtEmit, injected, notified, pi, ctx, annotations };
}

type CoreScaffold = ReturnType<typeof coreScaffold>;

/** A real browser-operation owner over the scaffold's annotation state. */
function coreOwner(
  s: CoreScaffold,
  browserDeps: StartBrowserDeps,
  annotationDeps?: { fetchLike: FetchLike },
): BrowserOperationOwner {
  return createBrowserOperationOwner(s.pi, {
    annotations: s.annotations,
    gating: { primeDeferred: (names) => [...names] },
    status: createPerkStatus(),
    browserDeps,
    consoleQuietMs: 10,
    ...(annotationDeps !== undefined ? { annotationDeps } : {}),
  });
}

/** A readiness poll that never sees the server: the tiny budget times out → the owner degrades. */
const NEVER_READY: StartBrowserDeps = {
  pickFreePort: async () => 45031,
  probe: async () => false,
  intervalMs: 1,
  budgetMs: 3,
  sleep: async () => {},
};

/** Poll `done()` on real timers (bounded — a stuck condition fails the assertion, never hangs). */
async function until(done: () => boolean | Promise<boolean>, ms = 5000): Promise<void> {
  const start = Date.now();
  while (!(await done()) && Date.now() - start < ms) {
    await new Promise((r) => setTimeout(r, 10));
  }
}

/** Settle every recorded core bridge (`handled`) and wait for the poll's env restore. */
async function settleCore(s: CoreScaffold): Promise<void> {
  for (const envelope of s.envelopes) {
    envelope.respond({ status: "handled", result: { approved: true } });
  }
  await until(() => !("PLANNOTATOR_PORT" in process.env));
}

test("openReviewBrowserCore: the stack degrade notice reaches the owner's degrade", async () => {
  const s = coreScaffold();
  try {
    const opened = await openReviewBrowserCore(s.pi, s.ctx, coreOwner(s, NEVER_READY), {
      scope: "stack-review-browser",
      browserOpts: { cwd: "/wt/review-42", source: { mode: "patch", patchFile: "/wt/r.patch" } },
      guidance: "STACK GUIDANCE",
      degradeNotice: STACK_DEGRADE_NOTICE,
      respondMessageFor: stackRespondMessage,
    });
    assert.deepEqual(opened, { kind: "launched", guidance: "STACK GUIDANCE" });
    assert.deepEqual(
      s.envelopes[0]?.payload,
      { cwd: "/wt/review-42", patchFile: "/wt/r.patch" },
      "the static-patch payload is byte-stable",
    );
    await until(() => s.injected.length > 0);
    assert.deepEqual(
      s.injected.map((m) => m.message),
      [STACK_DEGRADE_NOTICE],
      "the stack notice (never the PR notice) is injected once; the core delivers no guidance",
    );
    assert.ok(!s.injected.some((m) => m.message === DEGRADE_NOTICE));
    assert.ok(
      s.notified.some(
        (n) =>
          n.severity === "error" &&
          n.message.includes("stack-review-browser") &&
          n.message.includes(
            "the plannotator review server did not become ready at http://127.0.0.1:45031 — " +
              "the browser review is unavailable",
          ),
      ),
      "the byte-stable degrade line under the stack scope",
    );
    assert.equal(s.annotations.surface, null, "the degrade cleared the surface");
  } finally {
    await settleCore(s);
  }
});

test("code review (PR and stack mappers): a handled respond after a timeout-degrade is ignored with one post-degrade warning — nothing injected, the surface stays cleared", async () => {
  for (const arm of [
    { scope: "pr-review-browser", notice: DEGRADE_NOTICE, mapper: undefined },
    { scope: "stack-review-browser", notice: STACK_DEGRADE_NOTICE, mapper: stackRespondMessage },
  ]) {
    const s = coreScaffold();
    try {
      const opened = await openReviewBrowserCore(s.pi, s.ctx, coreOwner(s, NEVER_READY), {
        scope: arm.scope,
        browserOpts: {
          cwd: "/wt",
          source: { mode: "pr", prUrl: "https://github.com/o/r/pull/77" },
        },
        guidance: "G",
        ...(arm.mapper !== undefined
          ? { degradeNotice: arm.notice, respondMessageFor: arm.mapper }
          : {}),
      });
      assert.equal(opened.kind, "launched", arm.scope);
      await until(() => s.injected.length > 0);
      assert.deepEqual(
        s.injected.map((m) => m.message),
        [arm.notice],
        `${arm.scope}: degraded`,
      );
      // The human decides in the never-ready tab AFTER the degrade moved the flow in-session.
      s.envelopes[0]?.respond({
        status: "handled",
        result: {
          approved: false,
          feedback: "late",
          annotations: [{ filePath: "src/a.ts", lineStart: 3, lineEnd: 3, side: "new", text: "x" }],
        },
      });
      await until(() => s.notified.some((n) => n.severity === "warning"));
      const warnings = s.notified.filter((n) => n.severity === "warning");
      assert.equal(warnings.length, 1, `${arm.scope}: exactly one warning`);
      assert.ok(
        warnings[0]?.message.endsWith(postDegradeDecisionWarning(arm.scope)),
        `${arm.scope}: ${warnings[0]?.message}`,
      );
      assert.deepEqual(
        s.injected.map((m) => m.message),
        [arm.notice],
        `${arm.scope}: the late decision injected nothing (no respond mapper ran)`,
      );
      assert.equal(s.annotations.surface, null, `${arm.scope}: the surface stays cleared`);
    } finally {
      await settleCore(s);
    }
  }
});

test("owner-primed review surface: pushed findings round-trip as feedback coordinates/text", async () => {
  const s = coreScaffold();
  const posted: Record<string, unknown>[] = [];
  const recording: FetchLike = async (_url, init) => {
    if (init.method === "POST") {
      const body = JSON.parse(init.body ?? "{}") as { annotations: Record<string, unknown>[] };
      posted.push(...body.annotations);
    }
    return {
      ok: true,
      status: init.method === "POST" ? 201 : 200,
      text: async () => (init.method === "POST" ? '{"ids":[]}' : '{"removed":0}'),
    };
  };
  const owner = coreOwner(s, {
    pickFreePort: async () => 45041,
    probe: async () => true,
    intervalMs: 1,
    budgetMs: 50,
    sleep: async () => {},
  });
  try {
    const opened = await openReviewBrowserCore(s.pi, s.ctx, owner, {
      scope: "pr-review-browser",
      browserOpts: { cwd: "/wt", source: { mode: "pr", prUrl: "https://github.com/o/r/pull/77" } },
      guidance: "G",
    });
    assert.equal(opened.kind, "launched");
    await until(() => s.annotations.ready);
    const target = { hasUI: false, ui: undefined } as unknown as Parameters<
      typeof executePushAnnotations
    >[1];
    // Two angles at distinct anchors (one on the old side), plus one body the parent merged
    // from two concerns at a shared anchor before pushing.
    const correctness = await executePushAnnotations(
      s.annotations,
      target,
      {
        angle: "correctness",
        findings: [
          { path: "src/a.ts", line: 3, severity: "major", confidence: "high", body: "A" },
          {
            path: "src/b.ts",
            line: 7,
            side: "LEFT",
            severity: "minor",
            confidence: "medium",
            body: "B (removed line)",
          },
        ],
      },
      { fetchLike: recording },
    );
    assert.equal(correctness.details.ok, true);
    const tests = await executePushAnnotations(
      s.annotations,
      target,
      {
        angle: "tests",
        findings: [
          {
            path: "src/c.ts",
            line: 10,
            severity: "major",
            confidence: "high",
            body: "C1: untested branch.\n\nC2 (merged): the fixture is unused.",
          },
        ],
      },
      { fetchLike: recording },
    );
    assert.equal(tests.details.ok, true);
    assert.equal(posted.length, 3, "three annotations reached the server");

    // The human finishes: plannotator returns the perk-pushed annotations with their content.
    s.envelopes[0]?.respond({
      status: "handled",
      result: { approved: false, feedback: "see notes", annotations: posted },
    });
    await until(() => s.injected.length > 0);
    const message = s.injected[0]?.message ?? "";
    const json = /```json\n([\s\S]*?)\n```/.exec(message)?.[1];
    assert.ok(json !== undefined, message);
    const returned = JSON.parse(json) as Record<string, unknown>[];
    const fields = ["filePath", "lineStart", "lineEnd", "side", "text", "source"] as const;
    const pick = (a: Record<string, unknown>) => Object.fromEntries(fields.map((f) => [f, a[f]]));
    assert.deepEqual(
      returned.map(pick),
      posted.map(pick),
      "coordinates, side, text and the owning lane's source survive the round trip",
    );
    assert.deepEqual(
      returned.map((a) => a.side),
      ["new", "old", "new"],
    );
    assert.equal(returned[2]?.source, "perk:tests");
    assert.match(String(returned[2]?.text), /C1: untested branch\.\n\nC2 \(merged\)/);
    assert.equal(s.annotations.surface, null, "the decided operation cleared its surface");
  } finally {
    await settleCore(s);
  }
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
  pr: { number: 42, url: "https://github.com/o/r/pull/42", base_ref: "topic/predecessor" },
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
          n.includes("select the plannotator plan provider (`[providers] plan = ") &&
          n.includes('"plannotator-plan"`), run `perk init`, then restart pi'),
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

test("/pr-review-browser <pr>: foreign success injects ONE URL-free guidance, primes then clears the surface", async () => {
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
    // The model never sees the server address — no localhost URL anywhere in the guidance.
    assert.doesNotMatch(text, /127\.0\.0\.1|localhost/);
    assert.equal(sink.envelopes.length, 1, "the bridge request was emitted");
    assert.deepEqual(
      sink.envelopes[0]?.payload,
      { cwd, prUrl: "https://github.com/o/r/pull/77" },
      "the PR-mode payload is byte-stable",
    );
    assert.match(
      sink.envAtEmit[0] ?? "",
      /^\d+$/,
      "PLANNOTATOR_PORT preset at emit time (the door-held deterministic port)",
    );
    // The PR-mode open primed the annotation surface for push_annotations…
    assert.equal(
      await sessionSurfacePrimed(h),
      true,
      "the surface is primed after the PR-mode open",
    );
    const marker = pointer("perk-pr-review-browser");
    assert.equal(text.split(marker).length - 1, 1, "exactly one command:pr-review-browser pointer");
    // …and the bridge settle clears it (the background task's finally).
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

test("/pr-review-browser <pr> in a discovery-cohort session: REVIEW_BROWSER_PRIMES are active when the guidance is sent", async () => {
  assert.deepEqual([...REVIEW_BROWSER_PRIMES], ["collect_review_wave", "push_annotations"]);
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON });
  const sink: FakeBrowser = { envelopes: [], envAtEmit: [] };
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
    await h.runCommandHandler("pr-review-browser", "77");
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

test("/pr-review-browser (no arg): a stacked PR keeps the PR-URL payload despite a conflicting plan base", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  plantPlanRef(cwd, "main");
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
    const marker = pointer("perk-pr-review-browser");
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
    assert.equal(
      injected.length,
      0,
      "no guidance injection in pre-PR mode (no reviewers, including no Ponytail lane)",
    );
    assert.equal(sink.envelopes.length, 1, "the local bridge was emitted");
    assert.deepEqual(
      sink.envelopes[0]?.payload,
      { cwd, diffType: "since-base", defaultBranch: "release-1.x" },
      "the local payload pins {cwd, diffType, defaultBranch} and omits prUrl",
    );
    assert.equal(sink.envAtEmit[0], undefined, "no port dance — PLANNOTATOR_PORT never preset");
    assert.equal(
      await sessionSurfacePrimed(h),
      false,
      "the local (pre-PR) mode never primes the surface",
    );

    // The respond routes under the new scope: exit-before-approved (closed ≠ approved).
    sink.envelopes[0]?.respond({ status: "handled", result: { approved: false, exit: true } });
    for (let i = 0; i < 5; i++) await Promise.resolve();
    assert.ok(
      h.notifies.some(
        (n) =>
          n.includes("pr-review-browser") && n.includes("Code review closed without feedback."),
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

for (const base_ref of [undefined, null, 7, "", " \t\n"]) {
  test(`/pr-review-browser: malformed locator base ${JSON.stringify(base_ref)} refuses before open/guidance`, async () => {
    const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
    plantPlanRef(cwd, "main");
    const bin = fakePerk(cwd, {
      stdout: JSON.stringify({ success: true, pr: { number: 42, url: "url", base_ref } }),
    });
    const sink: FakeBrowser = { envelopes: [], envAtEmit: [] };
    const h = await loadPerkSession({
      cwd,
      env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
      extraExtensions: [fakePlannotator(sink)],
    });
    const injected = spyInjections(h);
    try {
      await h.runCommandHandler("pr-review-browser", "");
      assert.ok(h.notifies.some((n) => n.includes("bad_output")));
      assert.equal(injected.length, 0);
      assert.equal(sink.envelopes.length, 0);
    } finally {
      h.dispose();
    }
  });
}

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

test("/pr-review-browser <pr>: a configured reviewer model never reaches the guidance (tool-resolved)", async () => {
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
    // Model resolution lives in start_review_wave now — the door reads no config and the
    // guidance carries no model plumbing.
    assert.doesNotMatch(text, /test\/model/);
    assert.doesNotMatch(text, /model: "/);
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

// --- the browser-operation owner (replacement, reload) through the harness ----------------------

/** Every request a serving fake review server received (recorded before it answers). */
interface ServedRequest {
  port: number;
  method: string;
  url: string;
  body: string;
}

interface ServingSink {
  envelopes: CodeReviewEnvelope[];
  servers: Server[];
  requests: ServedRequest[];
  /** The plan-review handshakes answered so far (their review ids are `r-<n>`). */
  planReviews: number;
  /** Emit a plan-review decision on the session bus (bound once the fake loads). */
  emitDecision: (decision: Record<string, unknown>) => void;
}

function newServingSink(): ServingSink {
  return { envelopes: [], servers: [], requests: [], planReviews: 0, emitDecision: () => {} };
}

/**
 * A fake plannotator whose code-review server answers like the real one AND records every
 * request: it binds the port the door presets while the request is emitted (exactly where real
 * plannotator binds), answers the readiness probe (`/api/diff`, `/api/plan`), accepts annotation
 * pushes (`201` POST / `200` DELETE), and keeps each code-review envelope for an explicit
 * `respond` (a plan-review handshake is answered pending; its decision rides `emitDecision`).
 */
function servingPlannotator(sink: ServingSink): (pi: ExtensionAPI) => void {
  return (pi) => {
    pi.registerCommand("plannotator-review", {
      description: "fake plannotator (test)",
      handler: async () => {},
    });
    sink.emitDecision = (decision) => pi.events.emit("plannotator:review-result", decision);
    pi.events.on("plannotator:request", (data) => {
      const envelope = data as CodeReviewEnvelope;
      sink.envelopes.push(envelope);
      if (envelope.action === "plan-review") {
        // The plan server is bound before the handshake answers (the decision comes later).
        sink.planReviews += 1;
        envelope.respond({
          status: "handled",
          result: { status: "pending", reviewId: `r-${sink.planReviews}` },
        });
      }
      const preset = process.env.PLANNOTATOR_PORT;
      if (preset === undefined) return; // the local mode presets nothing — no server to bind
      const port = Number(preset);
      const server = createHttpServer((req, res) => {
        let body = "";
        req.on("data", (chunk) => {
          body += String(chunk);
        });
        req.on("end", () => {
          sink.requests.push({ port, method: req.method ?? "", url: req.url ?? "", body });
          if (req.method === "POST") {
            res.writeHead(201, { "content-type": "application/json" });
            res.end('{"ids":[]}');
            return;
          }
          res.writeHead(200, { "content-type": "application/json" });
          res.end("{}");
        });
      });
      server.listen(port, "127.0.0.1");
      sink.servers.push(server);
    });
  };
}

async function closeServers(sink: ServingSink): Promise<void> {
  await Promise.all(
    sink.servers.map((server) => new Promise((resolve) => server.close(() => resolve(null)))),
  );
}

/** The annotation-push requests a served port received, as `METHOD url`. */
function annotationCalls(sink: ServingSink, port: number): string[] {
  return sink.requests
    .filter((r) => r.port === port && r.url.startsWith("/api/external-annotations"))
    .map((r) => `${r.method} ${r.url}`);
}

const CHECKOUT_78_JSON = JSON.stringify({
  ...JSON.parse(CHECKOUT_OK_JSON),
  path: "/wt/review-78",
  pr: 78,
  url: "https://github.com/o/r/pull/78",
});

test("/pr-review-browser twice: an older review's late settle never clears the successor's surface; the first tab is marked replaced", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON });
  const sink = newServingSink();
  const priorPort = process.env.PLANNOTATOR_PORT;
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [servingPlannotator(sink)],
  });
  try {
    // Review A comes up (its readiness poll ends on the first probe and restores the env).
    await h.runCommandHandler("pr-review-browser", "77");
    await until(() => process.env.PLANNOTATOR_PORT === priorPort);
    assert.equal(sink.envelopes.length, 1, "A's request was emitted");
    const firstPort = sink.requests[0]?.port ?? 0;
    assert.ok(firstPort > 0, "A's server answered the readiness probe");
    // Review B: another PR, opened while A's tab is still open.
    fakePerk(cwd, { stdout: CHECKOUT_78_JSON });
    await h.runCommandHandler("pr-review-browser", "78");
    assert.equal(sink.envelopes.length, 2, "B's request was emitted");
    // A's human finishes in the old tab AFTER B opened.
    sink.envelopes[0]?.respond({ status: "handled", result: { approved: true } });
    for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 5));
    assert.equal(
      await sessionSurfacePrimed(h),
      true,
      "A's late settle left B's annotation surface primed",
    );
    assert.deepEqual(
      annotationCalls(sink, firstPort),
      ["DELETE /api/external-annotations?source=perk%3Awave", "POST /api/external-annotations"],
      "A's tab got the detached marker, on A's server",
    );
    const markerPost = sink.requests.find(
      (r) => r.port === firstPort && r.method === "POST" && r.url === "/api/external-annotations",
    );
    assert.ok(
      markerPost?.body.includes(reviewDetachedStatus("replaced")),
      "the marker says a newer browser review replaced it",
    );
    assert.ok(
      h.notifies.some((n) =>
        n.includes(
          "the earlier browser review (pr-review-browser) was replaced — its tab is marked " +
            "detached and its decision will not be routed",
        ),
      ),
      "one info line names the replacement",
    );
    // B's own settle clears B's surface.
    sink.envelopes[1]?.respond({ status: "handled", result: { approved: true } });
    await until(async () => !(await sessionSurfacePrimed(h)));
    assert.equal(await sessionSurfacePrimed(h), false, "B's settle clears the surface");
  } finally {
    for (const envelope of sink.envelopes) {
      envelope.respond({ status: "handled", result: { approved: true } });
    }
    await until(() => process.env.PLANNOTATOR_PORT === priorPort);
    await closeServers(sink);
    h.dispose();
  }
});

/** Capture `console.error` lines for the duration of a test (restore via the returned fn). */
function captureConsoleErrors(): { lines: string[]; restore(): void } {
  const lines: string[] = [];
  const original = console.error;
  console.error = (...args: unknown[]) => {
    lines.push(args.map(String).join(" "));
  };
  return {
    lines,
    restore() {
      console.error = original;
    },
  };
}

const STALE_CTX = /stale after session replacement/;

test("/pr-review-browser: /reload marks the browser detached and the successor activation is clean", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON });
  const sink = newServingSink();
  const priorPort = process.env.PLANNOTATOR_PORT;
  const errors = captureConsoleErrors();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [servingPlannotator(sink)],
  });
  try {
    await h.runCommandHandler("pr-review-browser", "77");
    await until(() => process.env.PLANNOTATOR_PORT === priorPort);
    assert.equal(await sessionSurfacePrimed(h), true, "the PR review is open and primed");
    const port = sink.requests[0]?.port ?? 0;

    const before = sink.requests.length;
    await h.reload();
    // The old activation spoke to its browser inside session_shutdown — before reload resolved.
    const atReload = sink.requests.slice(before);
    assert.deepEqual(
      atReload.map((r) => `${r.port} ${r.method} ${r.url}`),
      [
        `${port} DELETE /api/external-annotations?source=perk%3Awave`,
        `${port} POST /api/external-annotations`,
      ],
    );
    assert.ok(
      atReload[1]?.body.includes(reviewDetachedStatus("session-ended")),
      "the tab now says the review is detached",
    );
    assert.deepEqual(
      errors.lines.filter((line) => STALE_CTX.test(line)),
      [],
    );
    assert.ok(!h.notifies.some((n) => STALE_CTX.test(n)));

    // The successor activation is clean: no primed surface, no wave to collect.
    const push = await h.invokeTool("push_annotations", { angle: "probe", findings: [] });
    assert.equal((push.details as { error_type?: string }).error_type, "no_surface");
    const collect = await h.invokeTool("collect_review_wave", {});
    assert.equal((collect.details as { error_type?: string }).error_type, "no_wave");
    // A late decision on the detached tab reaches nothing (its bridge settled `aborted`).
    sink.envelopes[0]?.respond({ status: "handled", result: { approved: true } });
    for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 5));
    assert.deepEqual(
      errors.lines.filter((line) => STALE_CTX.test(line)),
      [],
    );
  } finally {
    errors.restore();
    await until(() => process.env.PLANNOTATOR_PORT === priorPort);
    await closeServers(sink);
    h.dispose();
  }
});

/** Probe the SESSION's primed annotation mode through the registered tool (null = unprimed). */
async function sessionAnnotationMode(h: PerkSession): Promise<string | null> {
  const result = await h.invokeTool("push_annotations", { angle: "probe", findings: [] });
  if (!(result.details as { ok: boolean }).ok) return null;
  return (result.details as { mode?: string }).mode ?? null;
}

const DRAFT_MD = "# The working draft\n\nStep one.\n";

test("cross-door replacement: /pr-review-browser retires a live /plan-review-browser and vice versa", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  gitInit(cwd, { dirty: false });
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON });
  const sink = newServingSink();
  const priorPort = process.env.PLANNOTATOR_PORT;
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PERK_WAVE_RPC_PING_MS: "20" },
    extraExtensions: [servingPlannotator(sink)],
  });
  const markerCalls = (port: number) =>
    sink.requests.filter((r) => r.port === port && r.url.startsWith("/api/external-annotations"));
  try {
    await h.invokeTool("plan_draft", { plan: DRAFT_MD });
    // The plan door opens first: its two surfaces are primed (plan mode + the draft context).
    await h.runCommandHandler("plan-review-browser", "");
    await until(() => process.env.PLANNOTATOR_PORT === priorPort);
    assert.equal(sink.envelopes[0]?.action, "plan-review");
    assert.equal(await sessionAnnotationMode(h), "plan");
    const planPort = sink.requests[0]?.port ?? 0;

    // The PR door replaces it — across doors, through the one owner.
    await h.runCommandHandler("pr-review-browser", "77");
    await until(() => process.env.PLANNOTATOR_PORT === priorPort);
    assert.equal(sink.envelopes[1]?.action, "code-review");
    const planMarker = markerCalls(planPort);
    assert.deepEqual(
      planMarker.map((r) => `${r.method} ${r.url}`),
      ["DELETE /api/external-annotations?source=perk%3Awave", "POST /api/external-annotations"],
      "the plan tab got the detached marker",
    );
    assert.ok(planMarker[1]?.body.includes(reviewDetachedStatus("replaced")));
    assert.ok(
      h.notifies.some((n) =>
        n.includes("the earlier browser review (plan-review-browser) was replaced"),
      ),
      "the PR door's open names the replaced plan review",
    );
    const noDraft = await h.invokeTool("start_draft_review_wave", {
      angles: ["grounding", "risk"],
    });
    assert.equal(
      (noDraft.details as { error_type?: string }).error_type,
      "no_draft_context",
      "the plan door's companion context was cleared",
    );
    assert.equal(await sessionAnnotationMode(h), "review", "the surface is the PR review's");
    const planShaped = await h.invokeTool("push_annotations", {
      angle: "probe",
      findings: [{ phrase: "Step one.", severity: "minor", confidence: "high", body: "p" }],
    });
    assert.equal((planShaped.details as { error_type?: string }).error_type, "bad_input");
    const prPort = sink.requests.find((r) => r.port !== planPort)?.port ?? 0;
    const reviewShaped = await h.invokeTool("push_annotations", {
      angle: "probe",
      findings: [{ path: "src/a.ts", line: 3, severity: "minor", confidence: "high", body: "r" }],
    });
    assert.equal((reviewShaped.details as { ok: boolean }).ok, true);
    assert.ok(
      markerCalls(prPort).some((r) => r.method === "POST" && r.body.includes("src/a.ts")),
      "the review-shaped batch reached the PR server",
    );
    // The detached plan tab's late verdict reaches nothing (its listener was disposed).
    const notifiesBefore = h.notifies.length;
    sink.emitDecision({ reviewId: "r-1", approved: true });
    for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 5));
    assert.deepEqual(h.notifies.slice(notifiesBefore), [], "nothing routed, nothing warned");

    // And back: the plan door replaces the PR review.
    await h.runCommandHandler("plan-review-browser", "");
    await until(() => process.env.PLANNOTATOR_PORT === priorPort);
    // After the review-shaped batch, the PR tab's last two requests are the detach marker.
    const prMarker = markerCalls(prPort).slice(1);
    assert.deepEqual(
      prMarker.map((r) => `${r.method} ${r.url}`),
      ["DELETE /api/external-annotations?source=perk%3Awave", "POST /api/external-annotations"],
      "the PR tab got the detached marker",
    );
    assert.ok(prMarker[1]?.body.includes(reviewDetachedStatus("replaced")));
    assert.ok(
      h.notifies.some((n) =>
        n.includes("the earlier browser review (pr-review-browser) was replaced"),
      ),
    );
    // The PR tab's late respond is dropped by its settled bridge: nothing injected or warned.
    const afterReturn = h.notifies.length;
    sink.envelopes[1]?.respond({ status: "handled", result: { approved: true } });
    for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 5));
    assert.deepEqual(h.notifies.slice(afterReturn), []);
    assert.equal(await sessionAnnotationMode(h), "plan", "the surface is the plan review's again");
  } finally {
    for (let i = 0; i < sink.planReviews; i++) {
      sink.emitDecision({ reviewId: `r-${i + 1}`, approved: false, feedback: "settle" });
    }
    for (const envelope of sink.envelopes) {
      if (envelope.action === "code-review") {
        envelope.respond({ status: "handled", result: { approved: true } });
      }
    }
    await until(() => process.env.PLANNOTATOR_PORT === priorPort);
    await closeServers(sink);
    h.dispose();
  }
});

test("local mode: a bridge respond after the task's ctx went stale is contained to one stderr line", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  plantPlanRef(cwd, "main");
  const noPr = JSON.stringify({ success: false, error_type: "no_pr", message: "No PR found" });
  const bin = fakePerk(cwd, { stdout: noPr, code: 1 });
  const sink: FakeBrowser = { envelopes: [], envAtEmit: [] };
  const rejections: unknown[] = [];
  const onRejection = (reason: unknown): void => {
    rejections.push(reason);
  };
  process.on("unhandledRejection", onRejection);
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakePlannotator(sink)],
  });
  let errors: { lines: string[]; restore(): void } | null = null;
  try {
    await h.runCommandHandler("pr-review-browser", "");
    assert.equal(sink.envelopes.length, 1, "the local bridge was emitted");
    await h.reload();
    errors = captureConsoleErrors();
    // The human finishes in the local review after the reload: the task's captured pi/ctx are
    // stale, so routing the feedback turn throws inside the detached task.
    sink.envelopes[0]?.respond({
      status: "handled",
      result: { approved: false, feedback: "fix X" },
    });
    for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 5));
    const failures = errors.lines.filter((line) =>
      line.startsWith("perk: pr-review-browser — the local browser review task failed:"),
    );
    assert.equal(failures.length, 1, JSON.stringify(errors.lines));
    assert.match(failures[0] ?? "", STALE_CTX, "the line names the stale ctx");
    assert.deepEqual(rejections, [], "no unhandled rejection");
  } finally {
    errors?.restore();
    process.off("unhandledRejection", onRejection);
    h.dispose();
  }
});

test("/pr-review-browser <pr>: an operator's PLANNOTATOR_PORT range presets its first free port", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON });
  const sink: FakeBrowser = { envelopes: [], envAtEmit: [] };
  // A free port with room for a three-port range (a dynamic pick keeps CI off 19432).
  let first = await pickEphemeralPort();
  while (first + 2 > 65535) first = await pickEphemeralPort();
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PLANNOTATOR_PORT: `${first}-${first + 2}` },
    extraExtensions: [fakePlannotator(sink)],
  });
  // The selection was resolved at activation: clearing the variable proves the door never
  // re-reads it at open time (and lets `settleBridges` observe the poll's restore-by-delete).
  delete process.env.PLANNOTATOR_PORT;
  try {
    await h.runCommandHandler("pr-review-browser", "77");
    assert.equal(sink.envelopes.length, 1, "the bridge request was emitted");
    assert.equal(sink.envAtEmit[0], String(first), "the range's first free port is preset");
  } finally {
    await settleBridges(sink);
    h.dispose();
  }
});

test("/pr-review-browser <pr>: a PLANNOTATOR_PORT another review already serves is refused at the boundary — nothing emitted, primed, injected, or sent to the old review", async () => {
  // The fixed-port collision: an "old review" answers every request on the operator's port. The
  // door must refuse loudly before the bridge request, the annotation prime, or the guidance —
  // so no readiness probe or annotation push can ever reach the review already holding it.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: CHECKOUT_OK_JSON });
  const sink: FakeBrowser = { envelopes: [], envAtEmit: [] };
  const oldReviewRequests: string[] = [];
  const oldReview = createHttpServer((req, res) => {
    oldReviewRequests.push(`${req.method} ${req.url}`);
    res.writeHead(200, { "content-type": "application/json" });
    res.end("{}");
  });
  await new Promise<void>((resolve) => oldReview.listen(0, "127.0.0.1", () => resolve()));
  const address = oldReview.address();
  const port = typeof address === "object" && address !== null ? address.port : 0;
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PLANNOTATOR_PORT: String(port) },
    extraExtensions: [fakePlannotator(sink)],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("pr-review-browser", "77");
    assert.ok(
      h.notifies.some(
        (n) => n.includes("could not pick a free local port") && n.includes(`${port} is in use`),
      ),
      "the refusal is reported loudly, naming the occupied port",
    );
    assert.equal(sink.envelopes.length, 0, "no bridge request emitted");
    assert.equal(injected.length, 0, "no guidance injected");
    assert.equal(await sessionSurfacePrimed(h), false, "push_annotations refuses — never primed");
    assert.deepEqual(oldReviewRequests, [], "the old review received no probe and no findings");
  } finally {
    h.dispose();
    await new Promise<void>((resolve) => oldReview.close(() => resolve()));
  }
});
