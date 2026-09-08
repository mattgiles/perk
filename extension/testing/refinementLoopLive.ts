// The TS side of the live cross-plane refinement-loop integration proof (dev-only; excluded from
// the published tarball via the `!extension/testing/` rule in package.json `files`). NOT a
// `.test.ts` — never picked up by `node --test`; it is driven once, as a subprocess, by the
// Python-owned `tests/test_objective_refine_cmd.py` end-to-end test.
//
// It runs the REAL interior over a real branch-backed workflow session rooted at the temp
// checkout the Python side prepared: the strict context import (the cold door's transfer bytes
// written unchanged as the session artifact), the draft seam (a first draft the scripted human
// DENIES — routed through the real completion, saving nothing — then the revision), and the
// approved save through the real seam + the real cold-door adapter (`runColdDoor` stages the
// exact draft bytes to run scratch). The ONE faked boundary is `pi.exec`: instead of spawning
// `perk`, it hands the staged argv to Python over stdout and reads the worker's exact envelope
// back over stdin — so the canonical Python worker (over its fake Linear workspace, in the
// pytest process) is the backend, and the adapter decodes the very bytes it produced.
//
// argv: <spec.json> — {cwd, runId, transferPath, expectedDigest, deniedMarkdown,
// revisedMarkdown}. stdout line 1: {"phase":"staged", argv, stagedBytes}; stdin: {"code",
// "stdout"} (the worker's exit code + stdout); stdout line 2: the final report.

import { readFileSync } from "node:fs";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  importRefinementContext,
  REFINEMENT_CONTEXT_ARTIFACT,
  validateContextTransfer,
} from "../authoring/refinement/context.ts";
import {
  renderRefinementDraft,
  resumeRefinementDraft,
  reviseRefinementDraft,
} from "../authoring/refinement/draft.ts";
import { completeRefinementReview } from "../authoring/refinement/review.ts";
import { refinementApprovalSave, reviewedPairOf } from "../authoring/refinement/save.ts";
import { coldDoorRefinementBackend } from "../pi/v1/objectiveRefinement.ts";
import { openBranchWorkflowSession } from "../session/branchWorkflowSession.ts";
import { type BranchEntry, WORKFLOW_STATE_TYPE } from "../substrate/workflowState.ts";

interface Spec {
  cwd: string;
  runId: string;
  transferPath: string;
  expectedDigest: string;
  deniedMarkdown: string;
  revisedMarkdown: string;
}

/** The whole of stdin (the pipe is non-blocking under the event loop — never `readFileSync(0)`). */
function stdinToEnd(): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk: string) => {
      data += chunk;
    });
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

function fail(message: string): never {
  process.stdout.write(`${JSON.stringify({ phase: "failed", message })}\n`);
  process.exit(1);
}

const specPath = process.argv[2];
if (!specPath) fail("usage: node refinementLoopLive.ts <spec.json>");
const spec = JSON.parse(readFileSync(specPath, "utf8")) as Spec;

const branch: BranchEntry[] = [
  {
    type: "custom",
    customType: WORKFLOW_STATE_TYPE,
    data: { run_id: spec.runId, stage: "objective-refine", mode: "read-only" },
  },
];
let invocations = 0;
const pi = {
  on() {},
  appendEntry(customType: string, data: Record<string, unknown>) {
    branch.push({ type: "custom", customType, data });
  },
  async exec(_cmd: string, args: string[]) {
    invocations += 1;
    const stagedBytes = readFileSync(args[args.indexOf("--draft-file") + 1] as string, "utf8");
    process.stdout.write(`${JSON.stringify({ phase: "staged", argv: args, stagedBytes })}\n`);
    const reply = JSON.parse(await stdinToEnd()) as { code: number; stdout: string };
    return { code: reply.code, stdout: reply.stdout, stderr: "", killed: false };
  },
} as unknown as ExtensionAPI;
const ctx = {
  cwd: spec.cwd,
  hasUI: true,
  isIdle: () => true,
  sessionManager: { getBranch: () => branch, getSessionId: () => "refinement-loop-live" },
  ui: { notify() {} },
} as unknown as ExtensionContext;

const session = openBranchWorkflowSession(pi, ctx);

// 1. The strict import of the cold door's transfer bytes.
const transfer = readFileSync(spec.transferPath, "utf8");
const validated = validateContextTransfer(transfer, {
  runId: spec.runId,
  expectedDigest: spec.expectedDigest,
});
if (!validated.ok) fail(`transfer refused: ${validated.problem}`);
const imported = importRefinementContext(session, validated.read);
if (imported.status !== "imported") fail(`import ${imported.status}`);
const stored = session.readArtifact(REFINEMENT_CONTEXT_ARTIFACT, { provenance: "strict" });
if (stored.status !== "found") fail("the imported context is not readable");

// 2. The denied round: a first draft the scripted human rejects — the completion routes the
//    denial without ever reaching the save seam.
const first = reviseRefinementDraft({ markdown: spec.deniedMarkdown }, session);
if (first.status !== "revised") fail(`first draft ${first.status}`);
const denied = await completeRefinementReview(
  { status: "denied", feedback: "Too vague — name the seams as observed.", reviewId: "deny-1" },
  async () => fail("a denial must never reach the save seam"),
);

// 3. The revision, then what the human is shown (captured BEFORE the verdict).
const second = reviseRefinementDraft({ markdown: spec.revisedMarkdown }, session);
if (second.status !== "revised") fail(`revised draft ${second.status}`);
const resumed = resumeRefinementDraft(session);
if (resumed.kind !== "valid") fail(`resume ${resumed.kind}`);
const reviewed = reviewedPairOf(resumed.pair);
const rendered = renderRefinementDraft(resumed.pair);

// 4. The approval → the real seam over the real cold-door adapter (Python is the worker).
let gateActive = true;
const gate = {
  isActive: () => gateActive,
  exit: () => {
    gateActive = false;
  },
};
const result = await completeRefinementReview({ status: "approved", reviewId: "approve-1" }, () =>
  refinementApprovalSave({
    session,
    backend: coldDoorRefinementBackend(pi, ctx),
    gate,
    reviewed,
  }),
);

process.stdout.write(
  `${JSON.stringify({
    phase: "done",
    storedContext: stored.content,
    denied: denied.status,
    rendered,
    reviewed,
    result,
    gateActive,
    invocations,
  })}\n`,
);
