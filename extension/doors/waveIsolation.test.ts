// The two-session isolation regression suite (the shared-state defect this node deletes): two
// REAL bound sessions in ONE process, each with its own fake pi-subagents responder, must share
// NO pending-wave or draft-review-context state — a launch in session B while session A's wave
// is pending must not cross-refuse `wave_active` or clobber A's slot, and each session's collect
// must drain ITS OWN aggregate. The draft pair additionally proves CONTEXT isolation: session A
// primed with a plan draft and session B with an objective draft each spawn a wave carrying
// their own primed bytes. (Pre-fix, both pairs kept module-global slots — the second session's
// launch refused or erased the first's.)

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  createFakeSubagents,
  type FakeSubagents,
  waveScriptItems,
} from "../testing/fakeSubagents.ts";
import {
  loadPerkSession,
  type PerkSession,
  scaffoldRepo,
  spyInjections,
} from "../testing/harness.ts";

/** The shared fake in dynamic mode, watermarking every report with the session's marker. */
function markedFake(marker: string): FakeSubagents {
  return createFakeSubagents([
    {
      executeScript: async (script) =>
        waveScriptItems(script).map(({ key }) => ({
          key,
          ok: true,
          error: null,
          report: { angle: key, summary: marker, findings: [], fyi: [] },
        })),
    },
  ]);
}

function installPonytailSkill(cwd: string, skillName: string): void {
  const root = join(cwd, ".pi", "npm", "node_modules", "@dietrichgebert", "ponytail");
  const skillDir = join(root, "skills", skillName);
  mkdirSync(skillDir, { recursive: true });
  writeFileSync(
    join(root, "package.json"),
    JSON.stringify({ name: "@dietrichgebert/ponytail", pi: { skills: ["./skills"] } }),
    "utf8",
  );
  writeFileSync(join(skillDir, "SKILL.md"), `---\nname: ${skillName}\n---\n`, "utf8");
}

test("two sessions share no review-wave pending state (launch/collect isolate per session)", async () => {
  const openSession = async (marker: string): Promise<{ h: PerkSession; fake: FakeSubagents }> => {
    const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
    installPonytailSkill(cwd, "ponytail-review");
    const fake = markedFake(marker);
    const h = await loadPerkSession({
      cwd,
      env: { PERK_RUN_ID: "01RID" },
      extraExtensions: [fake.extension],
    });
    return { h, fake };
  };
  const a = await openSession("session A sound");
  const b = await openSession("session B sound");
  try {
    const startA = await a.h.invokeTool("start_review_wave", {
      angles: ["claimed-intent", "tests"],
      pr: 42,
      worktree: "/abs/wt-a",
    });
    assert.equal((startA.details as { ok: boolean }).ok, true);

    // Session B launches WHILE A's wave is pending: no wave_active cross-refusal, no clobber.
    const startB = await b.h.invokeTool("start_review_wave", {
      angles: ["claimed-intent", "quality"],
      pr: 7,
      worktree: "/abs/wt-b",
    });
    assert.equal(
      (startB.details as { ok: boolean }).ok,
      true,
      "B's launch must not see A's pending wave",
    );
    assert.equal(a.fake.spawns.length, 1, "A's responder saw exactly A's spawn");
    assert.equal(b.fake.spawns.length, 1, "B's responder saw exactly B's spawn");

    // Each collect drains its OWN aggregate (the watermark proves no cross-drain).
    const collectedA = await a.h.invokeTool("collect_review_wave", {});
    const detailsA = collectedA.details as {
      ok: boolean;
      covered?: string[];
      reports?: { report: { summary?: string } }[];
    };
    assert.equal(detailsA.ok, true);
    assert.deepEqual(detailsA.covered, ["claimed-intent", "tests", "ponytail"]);
    assert.equal(detailsA.reports?.[0]?.report.summary, "session A sound");

    const collectedB = await b.h.invokeTool("collect_review_wave", {});
    const detailsB = collectedB.details as {
      ok: boolean;
      covered?: string[];
      reports?: { report: { summary?: string } }[];
    };
    assert.equal(detailsB.ok, true);
    assert.deepEqual(detailsB.covered, ["claimed-intent", "quality", "ponytail"]);
    assert.equal(detailsB.reports?.[0]?.report.summary, "session B sound");

    // Drain-once stays per-session: both slots are now empty.
    for (const h of [a.h, b.h]) {
      const drained = await h.invokeTool("collect_review_wave", {});
      assert.equal((drained.details as { error_type?: string }).error_type, "no_wave");
    }
  } finally {
    a.h.dispose();
    b.h.dispose();
  }
});

// --- the draft pair: pending-state AND primed-context isolation -------------------------------

/** The minimal fake plannotator peer the browser doors need to prime a session's context. */
interface FakePlannotatorSink {
  emitDecision: (decision: Record<string, unknown>) => void;
}

function fakePlannotator(sink: FakePlannotatorSink): (pi: ExtensionAPI) => void {
  return (pi) => {
    sink.emitDecision = (decision) => pi.events.emit("plannotator:review-result", decision);
    pi.registerCommand("plannotator-review", {
      description: "fake plannotator (test)",
      handler: async () => {},
    });
    pi.events.on("plannotator:request", (data) => {
      const envelope = data as { respond: (r: unknown) => void };
      envelope.respond({ status: "handled", result: { status: "pending", reviewId: "r-1" } });
    });
  };
}

/**
 * Settle ONE session's bridge (DENY) and wait for both of its background tasks to end: the
 * decision task (its own completion signal — the injected deny turn) and the readiness poll
 * (its exit is observable as the `PLANNOTATOR_PORT` restore — `expectedPort` names the value
 * the poll's `finally` puts back). The two concurrent doors NEST their save/restore of that
 * process-global (B saved A's port as its prior value), so the caller settles in REVERSE open
 * order — B first (restores A's port), then A (restores absence) — leaving the env clean and
 * provably no poll still running at dispose.
 */
async function settleDoor(
  sink: FakePlannotatorSink,
  injected: string[],
  expectedPort: string | undefined,
): Promise<void> {
  sink.emitDecision({ reviewId: "r-1", approved: false, feedback: "settle" });
  const start = Date.now();
  const done = (): boolean =>
    injected.some((m) => m.includes("DENIED")) && process.env.PLANNOTATOR_PORT === expectedPort;
  while (!done()) {
    if (Date.now() - start > 5000) break; // bounded — never hang a test on cleanup
    await new Promise((r) => setTimeout(r, 25));
  }
  assert.ok(done(), "the door's decision task and readiness poll both ended");
}

const PLAN_DRAFT = "# The session-A plan draft\n\nStep one.\n";
const OBJECTIVE_PROSE = "# Ship retries\n\nThe gateway needs retries.\n";

test("two sessions share no draft-review context: each wave receives its own primed bytes", async () => {
  // Session A: a PLAN draft primed through the real /plan-review-browser door.
  const cwdA = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only", stage: "plan" } });
  installPonytailSkill(cwdA, "ponytail");
  const fakeA = markedFake("draft A");
  const sinkA: FakePlannotatorSink = { emitDecision: () => {} };
  const hA = await loadPerkSession({
    cwd: cwdA,
    env: { PERK_RUN_ID: "01RID" },
    extraExtensions: [fakePlannotator(sinkA), fakeA.extension],
  });
  // Session B: an OBJECTIVE draft primed through the real /objective-review-browser door.
  const cwdB = scaffoldRepo({
    handoff: { runId: "01RID", mode: "read-only", stage: "objective-author" },
  });
  installPonytailSkill(cwdB, "ponytail");
  const fakeB = markedFake("draft B");
  const sinkB: FakePlannotatorSink = { emitDecision: () => {} };
  const hB = await loadPerkSession({
    cwd: cwdB,
    env: { PERK_RUN_ID: "01RID" },
    extraExtensions: [fakePlannotator(sinkB), fakeB.extension],
  });
  const injectedA = spyInjections(hA);
  const injectedB = spyInjections(hB);
  const priorPort = process.env.PLANNOTATOR_PORT;
  let portA: string | undefined;
  try {
    await hA.invokeTool("plan_draft", { plan: PLAN_DRAFT });
    await hA.runCommandHandler("plan-review-browser", "");
    portA = process.env.PLANNOTATOR_PORT; // A's preset — the prior value B's poll will restore
    await hB.invokeTool("objective_draft", {
      prose: OBJECTIVE_PROSE,
      title: "Ship retries",
      roadmap: [{ id: "1.1", description: "first" }],
    });
    await hB.runCommandHandler("objective-review-browser", "");

    // Both sessions launch: no cross-refusal, and EACH wave carries its own primed bytes.
    const startA = await hA.invokeTool("start_draft_review_wave", {
      angles: ["grounding", "risk"],
    });
    assert.equal((startA.details as { ok: boolean }).ok, true);
    const startB = await hB.invokeTool("start_draft_review_wave", {
      angles: ["grounding", "scope"],
    });
    assert.equal(
      (startB.details as { ok: boolean }).ok,
      true,
      "B's launch must not see A's pending wave or context",
    );
    assert.equal(fakeA.spawns.length, 1);
    assert.equal(fakeB.spawns.length, 1);
    const scriptA = String(fakeA.spawns[0]?.workflowScript ?? "");
    const scriptB = String(fakeB.spawns[0]?.workflowScript ?? "");
    assert.match(scriptA, /Draft type: plan\./);
    assert.match(scriptA, /# The session-A plan draft/);
    assert.doesNotMatch(scriptA, /Ship retries/, "A's wave never sees B's primed bytes");
    assert.match(scriptB, /Draft type: objective\./);
    assert.match(scriptB, /Ship retries/);
    assert.doesNotMatch(scriptB, /session-A plan draft/, "B's wave never sees A's primed bytes");

    // Each collect drains its own aggregate.
    const collectedA = await hA.invokeTool("collect_draft_review_wave", {});
    assert.equal(
      (collectedA.details as { reports?: { report: { summary?: string } }[] }).reports?.[0]?.report
        .summary,
      "draft A",
    );
    const collectedB = await hB.invokeTool("collect_draft_review_wave", {});
    assert.equal(
      (collectedB.details as { reports?: { report: { summary?: string } }[] }).reports?.[0]?.report
        .summary,
      "draft B",
    );
  } finally {
    // Reverse open order: B's poll restores A's port, then A's restores the original absence.
    await settleDoor(sinkB, injectedB, portA);
    await settleDoor(sinkA, injectedA, priorPort);
    // Belt-and-braces: the polls' restores are verified above; put back the pre-test value even
    // if a bounded wait broke out early.
    if (priorPort === undefined) delete process.env.PLANNOTATOR_PORT;
    else process.env.PLANNOTATOR_PORT = priorPort;
    hA.dispose();
    hB.dispose();
  }
});
