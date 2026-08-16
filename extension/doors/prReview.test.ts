// Tests for the warm `/pr-review` door. The pure `prReviewGuidance` + the two strict decodes
// (`decodeWaveParams`, `decodePostParams`) are pinned directly; the `run_pr_review_wave` flow
// tool (over a fake pi-subagents RPC responder on pi.events), the `post_pr_review` delegation +
// clean guard, and the command/tool registration + headless safety are exercised against a REAL
// bound session via the T1 harness, OFFLINE (a fake `perk` stands in for the GitHub mutation, so
// no LLM / network / gh / Python is invoked). The wave mechanics themselves are pinned in
// `extension/waves/prReviewWave.test.ts` — the guidance here carries judgment only.

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { runScratchDir } from "../substrate/cache.ts";
import {
  fakePerk,
  fakePerkRouter,
  loadPerkSession,
  scaffoldRepo,
} from "../testing/harness.ts";
import {
  WAVE_RPC_PROTOCOL_VERSION,
  WAVE_RPC_REPLY_EVENT_PREFIX,
  WAVE_RPC_REQUEST_EVENT,
} from "../waves/rpcAdapter.ts";
import { decodePostParams, decodeWaveParams, prReviewGuidance } from "./prReview.ts";

// --- prReviewGuidance: judgment-bearing inputs over the flow-scoped wave tool ----------------

test("prReviewGuidance names the seven angle-slug menu with plan-fidelity mandatory", () => {
  const text = prReviewGuidance();
  assert.match(text, /ALWAYS include \*\*plan-fidelity\*\*/);
  assert.match(text, /\*\*correctness\*\*/);
  assert.match(text, /\*\*tests\*\*/);
  assert.match(text, /\*\*quality\*\*/);
  assert.match(text, /\*\*api-design\*\*/);
  assert.match(text, /\*\*code-organization\*\*/);
  assert.match(text, /\*\*idioms\*\*/);
  // the lane-count cap (the wave's cost/latency bound): plan-fidelity + 1–3 others
  assert.match(text, /add 1–3 of/);
});

test("prReviewGuidance runs the wave through run_pr_review_wave (no rendered mechanics)", () => {
  const text = prReviewGuidance();
  assert.match(text, /run_pr_review_wave/);
  assert.match(text, /\{ complete, covered, retried, reports, failures \}/);
  // The rendered-wave mechanics are module-owned code now — the guidance never authors them.
  assert.doesNotMatch(text, /workflowScript/);
  assert.doesNotMatch(text, /runs\.all/);
  assert.doesNotMatch(text, /async: false/);
  assert.doesNotMatch(text, /outputSchema/);
});

test("prReviewGuidance never derives clean from partial coverage (and names the enforcement)", () => {
  const text = prReviewGuidance();
  assert.match(text, /NEVER derive or post a `clean` verdict from partial coverage/);
  assert.match(text, /`post_pr_review` refuses it/);
});

test("prReviewGuidance instructs reconcile/union/dedupe and verdict derivation over typed reports", () => {
  const text = prReviewGuidance();
  assert.match(text, /union/i);
  assert.match(text, /dedupe/i);
  assert.match(text, /if ANY report is actionable/i);
});

test("prReviewGuidance tells the parent to post via the post_pr_review tool", () => {
  const text = prReviewGuidance();
  assert.match(text, /post_pr_review/);
  assert.match(text, /last_pr_review/);
});

test("prReviewGuidance renders both verdict outcomes and the next-step surfacing", () => {
  const text = prReviewGuidance();
  // actionable → advisory COMMENT review, next step /address
  assert.match(text, /COMMENT review/);
  assert.match(text, /actionable .*`\/address`/u);
  // clean → a single 👍 reaction, next step /land
  assert.match(text, /\u{1F44D} reaction/u);
  assert.match(text, /clean .*`\/land`/u);
  // FYI notes are surfaced in-session only
  assert.match(text, /FYI notes/);
});

test("prReviewGuidance does not hardcode the perk-pr-review skill pointer (binding suffix)", () => {
  const text = prReviewGuidance();
  assert.doesNotMatch(text, /Follow the perk-pr-review skill/);
});

test("prReviewGuidance injects the operator directive when set (within the invariants)", () => {
  const text = prReviewGuidance("focus on the dignified-python skill");
  assert.match(text, /Operator focus for this run/);
  assert.match(text, /focus on the dignified-python skill/);
  assert.match(text, /Plan-fidelity angle stays mandatory/);
});

test("prReviewGuidance is byte-stable when the directive is empty/absent", () => {
  assert.equal(prReviewGuidance(), prReviewGuidance(""));
  assert.doesNotMatch(prReviewGuidance(""), /Operator focus for this run/);
});

// --- decodeWaveParams: strict decode (angle bounds enforced before any spawn) ----------------

test("decodeWaveParams accepts valid 2-, 3-, and 4-angle selections (+ directive)", () => {
  assert.deepEqual(decodeWaveParams({ angles: ["plan-fidelity", "tests"] }), {
    angles: ["plan-fidelity", "tests"],
  });
  assert.deepEqual(
    decodeWaveParams({
      angles: ["plan-fidelity", "correctness", "quality"],
      directive: "focus on the dignified-python skill",
    }),
    {
      angles: ["plan-fidelity", "correctness", "quality"],
      directive: "focus on the dignified-python skill",
    },
  );
  // A 4-slug selection including a widened-menu angle passes the widened window.
  assert.deepEqual(
    decodeWaveParams({ angles: ["plan-fidelity", "api-design", "code-organization", "idioms"] }),
    { angles: ["plan-fidelity", "api-design", "code-organization", "idioms"] },
  );
});

test("decodeWaveParams refuses out-of-bounds angle selections (whole refusal)", () => {
  assert.equal(decodeWaveParams({}), null); // missing
  assert.equal(decodeWaveParams({ angles: ["plan-fidelity"] }), null); // 1 angle
  assert.equal(
    decodeWaveParams({
      angles: ["plan-fidelity", "correctness", "tests", "quality", "idioms"],
    }),
    null,
  ); // 5 angles
  assert.equal(decodeWaveParams({ angles: ["plan-fidelity", "plan-fidelity"] }), null); // duplicate
  assert.equal(decodeWaveParams({ angles: ["plan-fidelity", "security"] }), null); // unknown slug
  assert.equal(decodeWaveParams({ angles: ["correctness", "tests"] }), null); // no plan-fidelity
  assert.equal(decodeWaveParams({ angles: "plan-fidelity,tests" }), null); // not an array
});

test("decodeWaveParams refuses a non-string or blank directive; a padded one decodes trimmed", () => {
  assert.equal(decodeWaveParams({ angles: ["plan-fidelity", "tests"], directive: 7 }), null);
  assert.equal(decodeWaveParams({ angles: ["plan-fidelity", "tests"], directive: "" }), null);
  // Whitespace-only would ride every lane as a dangling, contentless operator-focus suffix.
  assert.equal(decodeWaveParams({ angles: ["plan-fidelity", "tests"], directive: "   " }), null);
  assert.deepEqual(decodeWaveParams({ angles: ["plan-fidelity", "tests"], directive: " focus " }), {
    angles: ["plan-fidelity", "tests"],
    directive: "focus",
  });
});

// --- decodePostParams: strict decode (a GitHub mutation — whole-batch refusal on any drift) --

test("decodePostParams accepts a valid clean verdict (no comments)", () => {
  const p = decodePostParams({ verdict: "clean", summary: "all good", angles: ["plan-fidelity"] });
  assert.ok(p);
  assert.equal(p?.verdict, "clean");
  assert.equal(p?.comments, undefined);
  assert.deepEqual(p?.angles, ["plan-fidelity"]);
});

test("decodePostParams accepts a valid actionable verdict with comments + fyi", () => {
  const p = decodePostParams({
    verdict: "actionable",
    summary: "two issues",
    comments: [{ path: "a.ts", line: 12, body: "fix this" }],
    fyi: ["a nit"],
    angles: ["plan-fidelity", "tests"],
  });
  assert.ok(p);
  assert.equal(p?.comments?.length, 1);
  assert.equal(p?.comments?.[0]?.line, 12);
});

test("decodePostParams rejects the removed caller-supplied pr field", () => {
  assert.equal(decodePostParams({ verdict: "clean", summary: "clean", pr: 42 }), null);
});

test("decodePostParams rejects a clean verdict carrying comments (contradiction)", () => {
  assert.equal(
    decodePostParams({
      verdict: "clean",
      summary: "ok",
      comments: [{ path: "a.ts", line: 1, body: "x" }],
    }),
    null,
  );
});

test("decodePostParams rejects a malformed comment row", () => {
  assert.equal(
    decodePostParams({
      verdict: "actionable",
      summary: "s",
      comments: [{ path: "a.ts", line: 1.5, body: "x" }], // non-integer line
    }),
    null,
  );
  assert.equal(
    decodePostParams({
      verdict: "actionable",
      summary: "s",
      comments: [{ path: "", line: 1, body: "x" }], // empty path
    }),
    null,
  );
});

test("decodePostParams rejects a missing/invalid verdict or summary", () => {
  assert.equal(decodePostParams({ summary: "s" }), null);
  assert.equal(decodePostParams({ verdict: "maybe", summary: "s" }), null);
  assert.equal(decodePostParams({ verdict: "clean" }), null);
  assert.equal(decodePostParams({ verdict: "clean", summary: "" }), null);
});

// --- run_pr_review_wave: the flow tool over a fake pi-subagents RPC responder ----------------

/** The spawn params the fake responder observes (the tool-boundary threading assertions). */
interface SpawnSink {
  spawns: { workflowScript?: string; model?: string; outputSchema?: unknown }[];
}

function installPonytailReviewSkill(cwd: string): void {
  const root = join(cwd, ".pi", "npm", "node_modules", "@dietrichgebert", "ponytail");
  const skillDir = join(root, "skills", "ponytail-review");
  mkdirSync(skillDir, { recursive: true });
  writeFileSync(
    join(root, "package.json"),
    JSON.stringify({ name: "@dietrichgebert/ponytail", pi: { skills: ["./skills"] } }),
    "utf8",
  );
  writeFileSync(join(skillDir, "SKILL.md"), "---\nname: ponytail-review\n---\n", "utf8");
}

/**
 * A fake pi-subagents responder bound as a bus peer (the fakePlannotator pattern): answers
 * ping/spawn on `pi.events` with the v1 envelope, writes a terminal `status.json` carrying one
 * schema-valid report per lane into a real temp `asyncDir`, and emits the advertised completion
 * event. Each spawn's params land in `sink` so tests can pin what the tool threaded onto the
 * wave (configured model, directive-suffixed lane tasks). Offline like everything here.
 */
function fakeSubagentsResponder(sink: SpawnSink): (pi: ExtensionAPI) => void {
  return (pi) => {
    pi.events.on(WAVE_RPC_REQUEST_EVENT, (raw) => {
      const request = raw as {
        requestId: string;
        method: string;
        params?: { workflowScript?: string; model?: string; outputSchema?: unknown };
      };
      const reply = (payload: Record<string, unknown>): void => {
        pi.events.emit(`${WAVE_RPC_REPLY_EVENT_PREFIX}${request.requestId}`, {
          version: WAVE_RPC_PROTOCOL_VERSION,
          requestId: request.requestId,
          method: request.method,
          ...payload,
        });
      };
      if (request.method === "ping") {
        reply({
          success: true,
          data: {
            version: WAVE_RPC_PROTOCOL_VERSION,
            methods: ["ping", "status", "spawn", "steer", "interrupt", "stop", "resume"],
            capabilities: { asyncSpawn: true },
            events: { asyncComplete: "subagent:async-complete" },
            session: {},
          },
        });
        return;
      }
      if (request.method === "spawn") {
        if (request.params !== undefined) sink.spawns.push(request.params);
        // Parse the module-rendered script's lane keys and answer each with a schema-valid report.
        const script = request.params?.workflowScript ?? "";
        const start = script.indexOf("runs.all(") + "runs.all(".length;
        const end = script.indexOf(");\nreturn");
        const lanes = JSON.parse(script.slice(start, end)) as Array<{ key: string }>;
        const asyncDir = mkdtempSync(join(tmpdir(), "perk-pr-review-e2e-"));
        writeFileSync(
          join(asyncDir, "status.json"),
          JSON.stringify({
            runId: basename(asyncDir),
            mode: "workflow",
            state: "complete",
            startedAt: 0,
            workflow: {
              value: lanes.map(({ key }) => ({
                key,
                ok: true,
                error: null,
                report: { angle: key, verdict: "clean", findings: [], fyi: [] },
              })),
            },
          }),
        );
        reply({
          success: true,
          data: { text: "Started async run.", details: { asyncId: basename(asyncDir), asyncDir } },
        });
        // Emitted right after the reply — the runner subscribed before spawn and buffers.
        pi.events.emit("subagent:async-complete", {
          id: basename(asyncDir),
          asyncDir,
          state: "complete",
        });
        return;
      }
      reply({
        success: false,
        error: { code: "not_found", message: `fake responder rejects ${request.method}` },
      });
    });
  };
}

const PR_URL_JSON = {
  success: true,
  error_type: null,
  message: null,
  branch: "plan-7",
  pr: { number: 42, url: "https://github.test/o/r/pull/42" },
};

const ACTIONABLE_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  dry_run: false,
  pr: 42,
  mode: "review",
  verdict: "actionable",
  fyi: [],
  next_command: "/address",
  comment_count: 2,
});

const CLEAN_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  dry_run: false,
  pr: 42,
  mode: "reaction",
  verdict: "clean",
  fyi: [],
  next_command: "/land",
  comment_count: 0,
});

function latestReviewBatch(cwd: string): Record<string, unknown> {
  const dir = runScratchDir(cwd, "01RID");
  const files = readdirSync(dir)
    .filter((name) => name.startsWith("review-post-") && name.endsWith(".json"))
    .sort();
  const latest = files.at(-1);
  assert.ok(latest, "review-post staged a cold-door batch");
  return JSON.parse(readFileSync(join(dir, latest), "utf8")) as Record<string, unknown>;
}

test("tool: run_pr_review_wave end-to-end happy path; a following clean post is single-use", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  installPonytailReviewSkill(cwd);
  // The configured review model must reach the wave as its workflow-level default (the silent
  // fallback to the agent default is exactly the failure the module headers disavow).
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[models.subagents]\npr-reviewer = "test-wave-model"\n',
    "utf8",
  );
  const bin = fakePerkRouter(cwd, {
    "pr url": { json: PR_URL_JSON },
    "pr review-post": { json: JSON.parse(CLEAN_JSON) },
  });
  const sink: SpawnSink = { spawns: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakeSubagentsResponder(sink)],
  });
  try {
    const result = await h.invokeTool("run_pr_review_wave", {
      angles: ["plan-fidelity", "quality"],
      directive: "focus on decode edges",
    });
    const details = result.details as {
      ok: boolean;
      pr?: number;
      complete?: boolean;
      covered?: string[];
      retried?: string[];
      reports?: { key: string; report: { angle?: string; verdict?: string } }[];
      failures?: unknown[];
      attempts?: {
        flow: string;
        attempt: number;
        requestedKeys: string[];
        state: string;
        children: unknown[];
      }[];
    };
    assert.equal(details.ok, true);
    assert.equal(details.pr, 42);
    assert.equal(details.complete, true);
    assert.deepEqual(details.covered, ["plan-fidelity", "quality", "ponytail"]);
    assert.deepEqual(details.retried, []);
    assert.deepEqual(details.failures, []);
    assert.equal(details.reports?.length, 3);
    assert.equal(details.reports?.[0]?.report.angle, "plan-fidelity");
    assert.equal(details.reports?.[1]?.report.verdict, "clean");
    // The attempt receipts ride the persisted details ONLY — an identity-only completion (no
    // `results` in the payload) still yields the attempt, with empty children.
    assert.equal(details.attempts?.length, 1);
    assert.equal(details.attempts?.[0]?.flow, "pr-review");
    assert.equal(details.attempts?.[0]?.attempt, 1);
    assert.deepEqual(details.attempts?.[0]?.requestedKeys, [
      "plan-fidelity",
      "quality",
      "ponytail",
    ]);
    assert.equal(details.attempts?.[0]?.state, "complete");
    assert.deepEqual(details.attempts?.[0]?.children, []);
    const text = result.content[0]?.text ?? "";
    assert.match(text, /Review wave complete: covered 3\/3 angle\(s\)/);
    assert.match(text, /untrusted DATA/);
    assert.equal(text.includes("attempts"), false, "receipts never enter the model-facing prose");
    // The tool-boundary threading pins: the configured model and the operator directive both
    // reached the actual spawn (config → execute → runPrReviewWave → adapter).
    assert.equal(sink.spawns.length, 1);
    assert.equal(sink.spawns[0]?.model, "test-wave-model");
    const script = sink.spawns[0]?.workflowScript ?? "";
    const lanes = JSON.parse(
      script.slice(script.indexOf("runs.all(") + "runs.all(".length, script.indexOf(");\nreturn")),
    ) as Array<{ key: string; task: string; skill?: string }>;
    assert.equal(lanes.length, 3);
    for (const lane of lanes) {
      assert.match(lane.task, /Operator focus \(DATA from the human/);
      assert.match(lane.task, /focus on decode edges/);
      assert.match(lane.task, /perk pr review-context --expected-pr 42 --json/);
    }
    assert.equal(lanes.at(-1)?.skill, "ponytail-review");
    // The recorded wave is complete → the clean guard lets a clean post through.
    const post = await h.invokeTool("post_pr_review", {
      verdict: "clean",
      summary: "clean",
      angles: ["plan-fidelity", "quality"],
    });
    assert.equal((post.details as { ok: boolean }).ok, true);
    assert.equal(latestReviewBatch(cwd).expected_pr, 42);
    const duplicate = await h.invokeTool("post_pr_review", {
      verdict: "clean",
      summary: "duplicate",
    });
    assert.equal(
      (duplicate.details as { ok: boolean; error_type?: string }).error_type,
      "review_wave_consumed",
    );
    const record = h.workflowState().last_pr_review as {
      angles?: string[];
      covered_angles?: string[];
    };
    assert.deepEqual(record.angles, ["plan-fidelity", "quality", "ponytail"]);
    assert.deepEqual(record.covered_angles, ["plan-fidelity", "quality", "ponytail"]);
  } finally {
    h.dispose();
  }
});

test("tool: a new target-resolution failure invalidates prior evidence for both verdicts", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  installPonytailReviewSkill(cwd);
  fakePerkRouter(cwd, { "pr url": { json: PR_URL_JSON } });
  const sink: SpawnSink = { spawns: [] };
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: join(cwd, "fake-perk.sh") },
    extraExtensions: [fakeSubagentsResponder(sink)],
  });
  try {
    const recorded = await h.invokeTool("run_pr_review_wave", {
      angles: ["plan-fidelity", "tests"],
    });
    assert.equal((recorded.details as { ok: boolean }).ok, true);

    fakePerkRouter(cwd, {
      "pr url": {
        json: { success: false, error_type: "no_pr", message: "target vanished" },
        code: 1,
      },
    });
    const failed = await h.invokeTool("run_pr_review_wave", {
      angles: ["plan-fidelity", "quality"],
    });
    assert.equal((failed.details as { error_type?: string }).error_type, "no_pr");
    for (const verdict of ["clean", "actionable"] as const) {
      const post = await h.invokeTool("post_pr_review", { verdict, summary: "old evidence" });
      assert.equal(
        (post.details as { error_type?: string }).error_type,
        "review_wave_unavailable",
      );
    }
  } finally {
    h.dispose();
  }
});

test("tool: bad wave input does not discard a prior recorded outcome", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  installPonytailReviewSkill(cwd);
  const bin = fakePerkRouter(cwd, {
    "pr url": { json: PR_URL_JSON },
    "pr review-post": { json: JSON.parse(CLEAN_JSON) },
  });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakeSubagentsResponder({ spawns: [] })],
  });
  try {
    await h.invokeTool("run_pr_review_wave", { angles: ["plan-fidelity", "tests"] });
    const bad = await h.invokeTool("run_pr_review_wave", { angles: ["plan-fidelity"] });
    assert.equal((bad.details as { error_type?: string }).error_type, "bad_input");
    const post = await h.invokeTool("post_pr_review", { verdict: "clean", summary: "clean" });
    assert.equal((post.details as { ok: boolean }).ok, true);
  } finally {
    h.dispose();
  }
});

test("tool: mutation target drift returns stale_review_wave and invalidates the record", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  installPonytailReviewSkill(cwd);
  const bin = fakePerkRouter(cwd, {
    "pr url": { json: PR_URL_JSON },
    "pr review-post": {
      json: {
        success: false,
        error_type: "review_target_changed",
        message: "expected PR #42, found PR #43",
      },
      code: 1,
    },
  });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [fakeSubagentsResponder({ spawns: [] })],
  });
  try {
    await h.invokeTool("run_pr_review_wave", { angles: ["plan-fidelity", "tests"] });
    const stale = await h.invokeTool("post_pr_review", { verdict: "clean", summary: "clean" });
    assert.equal((stale.details as { error_type?: string }).error_type, "stale_review_wave");
    assert.equal(latestReviewBatch(cwd).expected_pr, 42);
    assert.match(stale.content[0]?.text ?? "", /rerun \/pr-review/);
    const retry = await h.invokeTool("post_pr_review", { verdict: "clean", summary: "retry" });
    assert.equal((retry.details as { error_type?: string }).error_type, "review_wave_unavailable");
    assert.equal(h.workflowState().last_pr_review, undefined);
  } finally {
    h.dispose();
  }
});

test("tool: a transient post failure retains the same recorded outcome for retry", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  installPonytailReviewSkill(cwd);
  fakePerkRouter(cwd, {
    "pr url": { json: PR_URL_JSON },
    "pr review-post": {
      json: { success: false, error_type: "github_error", message: "temporary failure" },
      code: 1,
    },
  });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: join(cwd, "fake-perk.sh") },
    extraExtensions: [fakeSubagentsResponder({ spawns: [] })],
  });
  try {
    await h.invokeTool("run_pr_review_wave", { angles: ["plan-fidelity", "tests"] });
    const failed = await h.invokeTool("post_pr_review", { verdict: "clean", summary: "clean" });
    assert.equal((failed.details as { error_type?: string }).error_type, "github_error");

    fakePerkRouter(cwd, { "pr review-post": { json: JSON.parse(CLEAN_JSON) } });
    const retry = await h.invokeTool("post_pr_review", { verdict: "clean", summary: "clean" });
    assert.equal((retry.details as { ok: boolean }).ok, true);
    assert.equal(latestReviewBatch(cwd).expected_pr, 42);
  } finally {
    h.dispose();
  }
});

test("tool: an unavailable wave degrades loud; the clean guard refuses; an actionable post still lands", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerkRouter(cwd, {
    "pr url": { json: PR_URL_JSON },
    "pr review-post": { json: JSON.parse(ACTIONABLE_JSON) },
  });
  // No RPC responder bound + a tiny ping timeout → the deterministic `unavailable` arm.
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin, PERK_WAVE_RPC_PING_MS: "20" },
  });
  try {
    const result = await h.invokeTool("run_pr_review_wave", {
      angles: ["plan-fidelity", "correctness"],
    });
    const details = result.details as {
      ok: boolean;
      complete?: boolean;
      covered?: string[];
      failures?: { key: string | null; reason: string }[];
      attempts?: { state: string; requestedKeys: string[] }[];
    };
    assert.equal(details.ok, true, "an incomplete wave is an ok result carrying complete: false");
    assert.equal(details.complete, false);
    assert.deepEqual(details.covered, []);
    assert.equal(details.failures?.[0]?.reason, "unavailable");
    // Even the pre-spawn capability failure is preserved as an attempt receipt.
    assert.equal(details.attempts?.length, 1);
    assert.equal(details.attempts?.[0]?.state, "unavailable");
    assert.ok(
      h.notifies.some((n) => n.includes("review wave incomplete")),
      "the loud degrade warning names the incomplete coverage",
    );
    // The clean guard: a clean post is refused while the recorded wave is incomplete.
    const clean = await h.invokeTool("post_pr_review", { verdict: "clean", summary: "clean" });
    const cleanDetails = clean.details as { ok: boolean; error_type?: string };
    assert.equal(cleanDetails.ok, false);
    assert.equal(cleanDetails.error_type, "incomplete_coverage");
    assert.equal(h.workflowState().last_pr_review, undefined, "a refused post records nothing");
    // An actionable post (summary opening with the coverage note) still goes through.
    const actionable = await h.invokeTool("post_pr_review", {
      verdict: "actionable",
      summary: "Incomplete coverage (correctness failed): one issue found",
      comments: [{ path: "a.ts", line: 12, body: "fix" }],
      angles: ["caller-supplied-is-ignored"],
    });
    assert.equal((actionable.details as { ok: boolean }).ok, true);
    const record = h.workflowState().last_pr_review as {
      angles?: string[];
      covered_angles?: string[];
    };
    assert.deepEqual(record.angles, ["plan-fidelity", "correctness", "ponytail"]);
    assert.deepEqual(record.covered_angles, []);
  } finally {
    h.dispose();
  }
});

// --- post_pr_review: end-to-end delegation (offline fake perk) ------------------------------

test("tool: post_pr_review delegates an actionable batch, records last_pr_review", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: ACTIONABLE_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("post_pr_review", {
      verdict: "actionable",
      summary: "two issues",
      comments: [{ path: "a.ts", line: 12, body: "fix" }],
      angles: ["plan-fidelity", "correctness"],
    });
    const details = result.details as { ok: boolean; comment_count?: number; verdict?: string };
    assert.equal(details.ok, true);
    assert.equal(details.comment_count, 2);
    assert.equal(latestReviewBatch(cwd).expected_pr, undefined);
    const rec = h.workflowState().last_pr_review as {
      pr?: number;
      verdict?: string;
      angles?: string[];
      covered_angles?: string[];
      comment_count?: number;
      mode?: string;
    };
    assert.equal(rec?.pr, 42);
    assert.equal(rec?.verdict, "actionable");
    assert.deepEqual(rec?.angles, ["plan-fidelity", "correctness"]);
    assert.deepEqual(rec?.covered_angles, ["plan-fidelity", "correctness"]);
    assert.equal(rec?.comment_count, 2);
    assert.equal(rec?.mode, "review");
  } finally {
    h.dispose();
  }
});

test("tool: post_pr_review delegates a clean batch (👍), records last_pr_review", async () => {
  // With NO recorded wave this session, a clean post passes — the guard's no-wave arm (the tool
  // stays usable standalone).
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: CLEAN_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("post_pr_review", {
      verdict: "clean",
      summary: "clean",
      angles: ["plan-fidelity"],
    });
    const details = result.details as { ok: boolean; verdict?: string };
    assert.equal(details.ok, true);
    assert.match(result.content[0]?.text ?? "", /Next step: \/land/);
    const rec = h.workflowState().last_pr_review as {
      verdict?: string;
      angles?: string[];
      covered_angles?: string[];
      comment_count?: number;
    };
    assert.equal(rec?.verdict, "clean");
    assert.deepEqual(rec?.angles, ["plan-fidelity"]);
    assert.deepEqual(rec?.covered_angles, ["plan-fidelity"]);
    assert.equal(rec?.comment_count, 0);
  } finally {
    h.dispose();
  }
});

test("tool: a failing worker fails loud-but-soft (no throw)", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("post_pr_review", { verdict: "clean", summary: "x" });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "exec_failed");
    assert.equal(h.workflowState().last_pr_review, undefined);
  } finally {
    h.dispose();
  }
});

test("/pr-review, run_pr_review_wave and post_pr_review register and are headless-safe", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  try {
    assert.ok(h.registeredCommands().includes("pr-review"), "the /pr-review command is registered");
    // Both tools are registered and execute without a UI: a bad-input call decodes to bad_input
    // before any spawn/exec (no responder or fake perk needed), proving registration + headless
    // safety.
    const wave = await h.invokeTool("run_pr_review_wave", { angles: ["plan-fidelity"] });
    const waveDetails = wave.details as { ok: boolean; error_type?: string };
    assert.equal(waveDetails.ok, false);
    assert.equal(waveDetails.error_type, "bad_input");
    const post = await h.invokeTool("post_pr_review", { summary: "missing verdict" });
    const postDetails = post.details as { ok: boolean; error_type?: string };
    assert.equal(postDetails.ok, false);
    assert.equal(postDetails.error_type, "bad_input");
    // The REGISTERED tool schema is the model-facing contract, authored independently of the
    // strict decode — pin the 2–4 window and the seven-slug enum so it cannot drift silently.
    const tool = h.registeredTool("run_pr_review_wave");
    assert.ok(tool);
    const params = tool.parameters as {
      required: string[];
      properties: {
        angles: { minItems: number; maxItems: number; items: { enum: string[] } };
      };
    };
    assert.deepEqual(params.required, ["angles"]);
    assert.equal(params.properties.angles.minItems, 2);
    assert.equal(params.properties.angles.maxItems, 4);
    assert.deepEqual(params.properties.angles.items.enum, [
      "plan-fidelity",
      "correctness",
      "tests",
      "quality",
      "api-design",
      "code-organization",
      "idioms",
    ]);
    assert.match(tool.description ?? "", /multi-angle \/pr-review reviewer wave/);
    assert.ok(
      tool.promptGuidelines?.some((g) => g.includes("2–4 unique slugs")),
      "the tool guidelines carry the widened 2–4 window",
    );
    const postTool = h.registeredTool("post_pr_review");
    assert.ok(postTool);
    const postParams = postTool.parameters as { properties: Record<string, unknown> };
    assert.equal(Object.hasOwn(postParams.properties, "pr"), false);
  } finally {
    h.dispose();
  }
});
