// Tests for the warm `/pr-review` door. The pure `prReviewGuidance` + the two strict decodes
// (`decodeWaveParams`, `decodePostParams`) are pinned directly; the `run_pr_review_wave` flow
// tool (over a fake pi-subagents RPC responder on pi.events), the `post_pr_review` delegation +
// clean guard, and the command/tool registration + headless safety are exercised against a REAL
// bound session via the T1 harness, OFFLINE (a fake `perk` stands in for the GitHub mutation, so
// no LLM / network / gh / Python is invoked). The wave mechanics themselves are pinned in
// `extension/waves/prReviewWave.test.ts` — the guidance here carries judgment only.

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { fakePerk, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import {
  WAVE_RPC_PROTOCOL_VERSION,
  WAVE_RPC_REPLY_EVENT_PREFIX,
  WAVE_RPC_REQUEST_EVENT,
} from "../waves/rpcAdapter.ts";
import { decodePostParams, decodeWaveParams, prReviewGuidance } from "./prReview.ts";

// --- prReviewGuidance: judgment-bearing inputs over the flow-scoped wave tool ----------------

test("prReviewGuidance names the four angle-slug menu with plan-fidelity mandatory", () => {
  const text = prReviewGuidance();
  assert.match(text, /ALWAYS include \*\*plan-fidelity\*\*/);
  assert.match(text, /\*\*correctness\*\*/);
  assert.match(text, /\*\*tests\*\*/);
  assert.match(text, /\*\*quality\*\*/);
  // the lane-count cap (the wave's cost/latency bound): plan-fidelity + 1–2 others
  assert.match(text, /add 1–2 of/);
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

test("decodeWaveParams accepts valid 2- and 3-angle selections (+ directive)", () => {
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
});

test("decodeWaveParams refuses out-of-bounds angle selections (whole refusal)", () => {
  assert.equal(decodeWaveParams({}), null); // missing
  assert.equal(decodeWaveParams({ angles: ["plan-fidelity"] }), null); // 1 angle
  assert.equal(
    decodeWaveParams({ angles: ["plan-fidelity", "correctness", "tests", "quality"] }),
    null,
  ); // 4 angles
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
    pr: 7,
    angles: ["plan-fidelity", "tests"],
  });
  assert.ok(p);
  assert.equal(p?.comments?.length, 1);
  assert.equal(p?.comments?.[0]?.line, 12);
  assert.equal(p?.pr, 7);
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

test("tool: run_pr_review_wave end-to-end happy path; a following clean post passes the guard", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  // The configured review model must reach the wave as its workflow-level default (the silent
  // fallback to the agent default is exactly the failure the module headers disavow).
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(
    join(cwd, ".perk", "config.toml"),
    '[models.subagents]\npr-reviewer = "test-wave-model"\n',
    "utf8",
  );
  const bin = fakePerk(cwd, { stdout: CLEAN_JSON });
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
    assert.equal(details.complete, true);
    assert.deepEqual(details.covered, ["plan-fidelity", "quality"]);
    assert.deepEqual(details.retried, []);
    assert.deepEqual(details.failures, []);
    assert.equal(details.reports?.length, 2);
    assert.equal(details.reports?.[0]?.report.angle, "plan-fidelity");
    assert.equal(details.reports?.[1]?.report.verdict, "clean");
    // The attempt receipts ride the persisted details ONLY — an identity-only completion (no
    // `results` in the payload) still yields the attempt, with empty children.
    assert.equal(details.attempts?.length, 1);
    assert.equal(details.attempts?.[0]?.flow, "pr-review");
    assert.equal(details.attempts?.[0]?.attempt, 1);
    assert.deepEqual(details.attempts?.[0]?.requestedKeys, ["plan-fidelity", "quality"]);
    assert.equal(details.attempts?.[0]?.state, "complete");
    assert.deepEqual(details.attempts?.[0]?.children, []);
    const text = result.content[0]?.text ?? "";
    assert.match(text, /Review wave complete: covered 2\/2 angle\(s\)/);
    assert.match(text, /untrusted DATA/);
    assert.equal(text.includes("attempts"), false, "receipts never enter the model-facing prose");
    // The tool-boundary threading pins: the configured model and the operator directive both
    // reached the actual spawn (config → execute → runPrReviewWave → adapter).
    assert.equal(sink.spawns.length, 1);
    assert.equal(sink.spawns[0]?.model, "test-wave-model");
    const script = sink.spawns[0]?.workflowScript ?? "";
    const lanes = JSON.parse(
      script.slice(script.indexOf("runs.all(") + "runs.all(".length, script.indexOf(");\nreturn")),
    ) as Array<{ key: string; task: string }>;
    assert.equal(lanes.length, 2);
    for (const lane of lanes) {
      assert.match(lane.task, /Operator focus \(DATA from the human/);
      assert.match(lane.task, /focus on decode edges/);
    }
    // The recorded wave is complete → the clean guard lets a clean post through.
    const post = await h.invokeTool("post_pr_review", {
      verdict: "clean",
      summary: "clean",
      angles: ["plan-fidelity", "quality"],
    });
    assert.equal((post.details as { ok: boolean }).ok, true);
  } finally {
    h.dispose();
  }
});

test("tool: an unavailable wave degrades loud; the clean guard refuses; an actionable post still lands", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: ACTIONABLE_JSON });
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
      angles: ["plan-fidelity"],
    });
    assert.equal((actionable.details as { ok: boolean }).ok, true);
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
      pr: 42,
    });
    const details = result.details as { ok: boolean; comment_count?: number; verdict?: string };
    assert.equal(details.ok, true);
    assert.equal(details.comment_count, 2);
    const rec = h.workflowState().last_pr_review as {
      pr?: number;
      verdict?: string;
      angles?: string[];
      comment_count?: number;
      mode?: string;
    };
    assert.equal(rec?.pr, 42);
    assert.equal(rec?.verdict, "actionable");
    assert.deepEqual(rec?.angles, ["plan-fidelity", "correctness"]);
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
    const rec = h.workflowState().last_pr_review as { verdict?: string; comment_count?: number };
    assert.equal(rec?.verdict, "clean");
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
  } finally {
    h.dispose();
  }
});
