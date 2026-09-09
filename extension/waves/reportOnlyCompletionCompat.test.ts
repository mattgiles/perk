// Installed-engine completion policy for report-only lanes, not model review quality: the REAL
// pi-subagents supplier validates the structured report, classifies the terminal outcome and
// produces the aggregate over detached native children whose session is a scripted, no-mutation
// report-only child. The fixture reproduces the incident's shape — a draft-review task whose
// `<untrusted_draft>` carries an implementation-intent sentence ("… must change …") and exceeds
// the intent arbiter's 8,000-character bound — and proves: the managed `completionGuard: false`
// profile completes on a valid nonempty AND a valid empty report; a test-local counterfactual
// with the guard enabled fails with the missing-implementation-mutation diagnostic on the SAME
// task/report (the former defect is reached, not dodged); and the exemption never bypasses the
// required report contract (an invalid or missing `structured_output` still fails the lane).
// Downstream failed-coverage/annotation semantics over these outcomes are pinned separately with
// the fake seams (`reportWave.test.ts`, `pi/v1/draftReviewWaveTools.test.ts`).
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test } from "node:test";
import {
  bootInstalledEngine,
  INSTALLED_PI_SUBAGENTS,
  type InstalledEngine,
  installedEngineSkip,
  isolateEngineEnv,
  runnerIdentities,
} from "../testing/installedEngine.ts";
import { buildDraftReviewAssignments, DRAFT_REVIEW_REPORT_SCHEMA } from "./draftReviewWave.ts";
import { createReportWave, type ReportWaveResult } from "./reportWave.ts";

/** The incident's trigger sentence (a reviewer-role implementation-intent match: "must change"). */
const TRIGGER = "Its no-resume-command assertion must change; its safety assertions must not.";

/** The supplier's own diagnostic for a guard-enabled lane that completed without editing. */
const MISSING_IMPLEMENTATION_MUTATION_MESSAGE =
  "Subagent completed without making edits for an implementation task.";

/** A synthetic plan draft carrying the trigger sentence, padded past the arbiter's 8,000 bound. */
function syntheticDraft(): string {
  const sections = [
    "# Plan: tighten the resume-command regression suite",
    "",
    "## Summary",
    "",
    "The resume-command test currently asserts that no resume command is offered after a clean",
    `settlement. ${TRIGGER} The safety assertions cover the abort path, the timeout path and the`,
    "budget-exhausted path; they stay exactly as written.",
    "",
    "## Steps",
    "",
  ];
  for (let i = 1; sections.join("\n").length < 8_400; i += 1) {
    sections.push(
      `${i}. Inspect fixture ${i} of the settlement matrix, record its observed terminal state ` +
        "in the evidence table, and cross-check the recorded state against the receipt's child " +
        "projection so the table names the exact settlement path each fixture exercises.",
    );
  }
  return sections.join("\n");
}

const NONEMPTY_REPORT = {
  angle: "grounding",
  streamed: false,
  summary: "Four grounding concerns about the resume-command suite.",
  findings: [
    {
      phrase: "no resume command is offered",
      severity: "major",
      confidence: "high",
      body: "The draft treats the resume-command absence as settled; the suite still asserts it.",
    },
    {
      phrase: "settlement matrix",
      severity: "major",
      confidence: "medium",
      body: "No settlement matrix exists in the repository; the fixtures are enumerated inline.",
    },
    {
      phrase: "evidence table",
      severity: "major",
      confidence: "medium",
      body: "The evidence table the steps reference is not produced by any existing step.",
    },
    {
      phrase: null,
      severity: "major",
      confidence: "low",
      body: "The draft never names the file that owns the resume-command assertion.",
    },
  ],
  fyi: ["The safety assertions are correctly described as unchanged."],
};

const EMPTY_REPORT = {
  angle: "grounding",
  streamed: false,
  summary: "No grounding concerns: every claim resolves against the repository.",
  findings: [],
  fyi: [],
};

/** Schema-invalid on purpose: `streamed` and `fyi` are required by the closed report shape. */
const INVALID_REPORT = { angle: "grounding", summary: "missing required fields", findings: [] };

interface Observation {
  agent: string;
  child_run_id: string;
  pid: number;
  launch_cwd: string;
  prompt_length: number;
  prompt_has_trigger: boolean;
  structured: string;
}

function failureOf(result: ReportWaveResult, key: string): { reason: string; detail: string } {
  const failure = result.failures.find((f) => f.key === key);
  assert.ok(failure, `lane '${key}' must be a failure: ${JSON.stringify(result.failures)}`);
  assert.equal(
    result.reports.some((r) => r.key === key),
    false,
    `lane '${key}' must not be covered`,
  );
  return failure;
}

test("installed engine: report-only lanes complete through the real supplier on valid reports; the guard-enabled counterfactual and contract violations fail", {
  skip: installedEngineSkip(),
  timeout: 300_000,
}, async (t) => {
  const root = realpathSync(INSTALLED_PI_SUBAGENTS);
  const scratch = realpathSync(mkdtempSync(join(tmpdir(), "perk-report-only-")));
  const caller = join(scratch, "caller");
  const observationDir = join(scratch, "observations");
  mkdirSync(observationDir, { recursive: true });
  const env = isolateEngineEnv(scratch);
  let engine: InstalledEngine | undefined;
  let passed = false;
  t.after(async () => {
    if (engine) await engine.teardown(t, () => passed);
    else env.restore();
  });
  t.mock.method(globalThis, "fetch", () => {
    throw new Error("network forbidden in completion test");
  });

  // Test-owned copies of the canonical draft-reviewer definition: the verbatim managed profile
  // under its real name, byte-identical siblings under lane-specific names (the scripted child
  // keys its behavior on the runtime agent name so the TASK stays identical across lanes), and
  // ONE counterfactual with the `completionGuard: false` line removed — the pre-fix profile shape.
  // The installed dependency and the repo's real profile are never edited.
  const canonical = readFileSync(
    resolve(import.meta.dirname, "../../agents/draft-reviewer.md"),
    "utf8",
  );
  assert.match(canonical, /^completionGuard: false$/m);
  const renamed = (name: string) => canonical.replace(/^name: draft-reviewer$/m, `name: ${name}`);
  const guarded = renamed("draft-reviewer-guarded").replace(/^completionGuard: false\n/m, "");
  assert.doesNotMatch(guarded, /completionGuard/);
  const agentDir = join(caller, ".pi/agents/perk");
  mkdirSync(agentDir, { recursive: true });
  writeFileSync(join(agentDir, "draft-reviewer.md"), canonical);
  writeFileSync(join(agentDir, "draft-reviewer-empty.md"), renamed("draft-reviewer-empty"));
  writeFileSync(join(agentDir, "draft-reviewer-invalid.md"), renamed("draft-reviewer-invalid"));
  writeFileSync(join(agentDir, "draft-reviewer-missing.md"), renamed("draft-reviewer-missing"));
  writeFileSync(join(agentDir, "draft-reviewer-guarded.md"), guarded);
  writeFileSync(
    join(caller, ".pi/settings.json"),
    JSON.stringify({ subagents: { disableBuiltins: true } }),
  );
  writeFileSync(join(caller, ".gitignore"), ".pi/subagents/\n");
  const git = (...args: string[]) =>
    execFileSync("git", ["-C", caller, ...args], { encoding: "utf8", timeout: 10_000 });
  git("init", "-q");
  git("add", ".gitignore", ".pi");
  git("-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "fixture");
  assert.equal(git("status", "--porcelain"), "");

  engine = await bootInstalledEngine({
    root,
    scratch,
    caller,
    env,
    parentSessionId: "report-only-parent",
    factoryModule: resolve(import.meta.dirname, "../testing/reportOnlyCompletionChildFactory.mjs"),
    config: { worktree: false, artifactDir: "temp", asyncByDefault: true },
  });
  t.diagnostic(`installed pi-subagents ${engine.version} at ${root} (executed, not skipped)`);

  // The real installed parser reads the policy field off the test-owned copies.
  const agents = (
    engine.discovery.discoverAgents(caller, "project") as {
      agents: { name: string; completionGuard?: boolean; tools?: string[] }[];
    }
  ).agents;
  const byName = new Map(agents.map((agent) => [agent.name, agent]));
  for (const name of [
    "perk.draft-reviewer",
    "perk.draft-reviewer-empty",
    "perk.draft-reviewer-invalid",
    "perk.draft-reviewer-missing",
  ]) {
    assert.equal(byName.get(name)?.completionGuard, false, name);
  }
  assert.equal(byName.get("perk.draft-reviewer-guarded")?.completionGuard, undefined);
  for (const agent of byName.values()) {
    assert.ok(agent.tools?.includes("bash"), `${agent.name}: inspection bash stays available`);
  }

  // The task comes from the production assignment builder: the grounding angle over the draft.
  const draft = syntheticDraft();
  const [grounding] = buildDraftReviewAssignments({
    angles: ["grounding"],
    draftType: "plan",
    draft,
  });
  assert.ok(grounding);
  assert.equal(grounding.agent, "perk.draft-reviewer");
  assert.ok(grounding.task.includes(`<untrusted_draft>\n${draft}\n</untrusted_draft>`));
  assert.ok(grounding.task.includes(TRIGGER));
  assert.ok(grounding.task.length > 8_000, `task length ${grounding.task.length}`);
  const lane = (key: string, agent: string) => ({ ...grounding, key, label: key, agent });

  const fixturePath = join(scratch, "report-only-fixture.json");
  writeFileSync(
    fixturePath,
    JSON.stringify({
      observationDir,
      lanes: {
        "perk.draft-reviewer": { mode: "report", report: NONEMPTY_REPORT },
        "perk.draft-reviewer-empty": { mode: "report", report: EMPTY_REPORT },
        "perk.draft-reviewer-guarded": { mode: "report", report: NONEMPTY_REPORT },
        "perk.draft-reviewer-invalid": { mode: "invalid", report: INVALID_REPORT },
        "perk.draft-reviewer-missing": { mode: "missing" },
      },
    }),
  );
  process.env.PERK_TEST_REPORT_ONLY_FIXTURE = fixturePath;

  const wave = createReportWave(engine.events);
  const request = {
    flow: "report-only-completion-compat",
    completeness: "strict" as const,
    outputSchema: DRAFT_REVIEW_REPORT_SCHEMA,
    timeoutMs: 120_000,
  };

  // Wave A — the managed policy: a valid nonempty and a valid empty report both COMPLETE.
  const valid = await wave.run({
    ...request,
    assignments: [
      lane("nonempty", "perk.draft-reviewer"),
      lane("empty", "perk.draft-reviewer-empty"),
    ],
  });
  assert.equal(valid.complete, true, JSON.stringify(valid.failures));
  assert.deepEqual(valid.failures, []);
  assert.deepEqual(
    valid.reports.map((r) => r.key).sort(),
    ["empty", "nonempty"],
    "both lanes covered",
  );
  assert.deepEqual(valid.reports.find((r) => r.key === "nonempty")?.report, NONEMPTY_REPORT);
  assert.deepEqual(valid.reports.find((r) => r.key === "empty")?.report, EMPTY_REPORT);
  assert.equal(valid.receipt.children.length, 2);

  // Wave B — the counterfactual and the contract violations: none is covered.
  const failing = await wave.run({
    ...request,
    assignments: [
      lane("guarded", "perk.draft-reviewer-guarded"),
      lane("invalid", "perk.draft-reviewer-invalid"),
      lane("missing", "perk.draft-reviewer-missing"),
    ],
  });
  assert.equal(failing.complete, false);
  assert.deepEqual(failing.reports, [], "no failed lane is ever promoted to a report");
  const guardedFailure = failureOf(failing, "guarded");
  assert.equal(guardedFailure.reason, "lane-failed");
  assert.ok(
    guardedFailure.detail.includes(MISSING_IMPLEMENTATION_MUTATION_MESSAGE),
    `the counterfactual reaches the former defect: ${guardedFailure.detail}`,
  );
  assert.equal(failureOf(failing, "invalid").reason, "lane-failed");
  assert.equal(failureOf(failing, "missing").reason, "lane-failed");
  assert.equal(failing.receipt.children.length, 3);

  // Every lane's child saw the delivered task (trigger + arbiter-defeating length) and behaved
  // as scripted; the guarded lane's report WAS captured by the engine — the failure is the
  // completion policy, not the report contract.
  const observations = new Map<string, Observation>();
  for (const name of [
    "perk.draft-reviewer",
    "perk.draft-reviewer-empty",
    "perk.draft-reviewer-guarded",
    "perk.draft-reviewer-invalid",
    "perk.draft-reviewer-missing",
  ]) {
    const observation = JSON.parse(
      readFileSync(join(observationDir, `${name}.json`), "utf8"),
    ) as Observation;
    assert.equal(observation.agent, name);
    assert.notEqual(observation.pid, process.pid);
    assert.equal(realpathSync(observation.launch_cwd), caller, name);
    assert.equal(observation.prompt_has_trigger, true, name);
    assert.ok(observation.prompt_length > 8_000, `${name}: ${observation.prompt_length}`);
    observations.set(name, observation);
  }
  assert.equal(observations.get("perk.draft-reviewer")?.structured, "captured");
  assert.equal(observations.get("perk.draft-reviewer-empty")?.structured, "captured");
  assert.equal(observations.get("perk.draft-reviewer-guarded")?.structured, "captured");
  assert.match(
    observations.get("perk.draft-reviewer-invalid")?.structured ?? "",
    /^rejected: Structured output validation failed/,
  );
  assert.equal(observations.get("perk.draft-reviewer-missing")?.structured, "not-called");
  // No lane mutated the caller; the successes did not depend on any edit.
  assert.equal(git("status", "--porcelain"), "");
  // Each lane was a real detached native child: the receipts' child identities are exactly the
  // identities the children observed, and every one has a native runner status behind it.
  const receiptRunIds = [...valid.receipt.children, ...failing.receipt.children]
    .map((child) => child.runId)
    .sort();
  const observedRunIds = [...observations.values()].map((o) => o.child_run_id).sort();
  assert.deepEqual(receiptRunIds, observedRunIds);
  assert.equal(new Set(observedRunIds).size, 5, "five distinct native children");
  const runnerRunIds = new Set(runnerIdentities(env.nativeTemp).map(({ runId }) => runId));
  for (const runId of observedRunIds) assert.ok(runnerRunIds.has(runId), runId);
  passed = true;
});
