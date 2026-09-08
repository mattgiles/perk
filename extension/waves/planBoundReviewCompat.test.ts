// Installed-engine placement, not model review quality: two real detached native children.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { isAbsolute, join, relative, resolve } from "node:path";
import { test } from "node:test";
import type { Static } from "typebox";
import { Compile } from "typebox/compile";
import {
  bootInstalledEngine,
  INSTALLED_PI_SUBAGENTS,
  type InstalledEngine,
  installedEngineSkip,
  isolateEngineEnv,
  runnerIdentities,
} from "../testing/installedEngine.ts";
import { createReportWave, type ReportWaveResult } from "./reportWave.ts";

const OBSERVATION_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "child_run_id",
    "pid",
    "launch_cwd",
    "process_cwd",
    "plan_ref_text",
    "plan_snapshot_text",
    "read_only",
  ],
  properties: {
    child_run_id: { type: "string", minLength: 1 },
    pid: { type: "integer", minimum: 1 },
    launch_cwd: { type: "string", minLength: 1 },
    process_cwd: { type: "string", minLength: 1 },
    plan_ref_text: { type: ["string", "null"] },
    plan_snapshot_text: { type: ["string", "null"] },
    read_only: { type: "boolean" },
  },
} as const;
type Observation = Static<typeof OBSERVATION_SCHEMA>;

function observationOf(result: ReportWaveResult, key: string): Observation {
  assert.equal(result.complete, true, JSON.stringify(result));
  assert.deepEqual(result.failures, []);
  assert.equal(result.reports.length, 1);
  assert.equal(result.reports[0]?.key, key);
  const observation = result.reports[0]?.report;
  assert.ok(Compile(OBSERVATION_SCHEMA).Check(observation), JSON.stringify(observation));
  assert.equal(result.receipt.children.length, 1);
  const child = result.receipt.children[0];
  assert.equal(child?.key, key);
  assert.equal(child?.runId, observation.child_run_id);
  assert.notEqual(observation.pid, process.pid);
  assert.doesNotMatch(
    JSON.stringify(result.receipt),
    /plan_ref_text|plan_snapshot_text|read_only|verdict/,
  );
  return observation;
}

test("installed engine: plan-bound caller placement versus native worktree default", {
  skip: installedEngineSkip(),
  timeout: 180_000,
}, async (t) => {
  const root = realpathSync(INSTALLED_PI_SUBAGENTS);
  const scratch = realpathSync(mkdtempSync(join(tmpdir(), "perk-plan-bound-")));
  const caller = join(scratch, "caller");
  const env = isolateEngineEnv(scratch);
  let engine: InstalledEngine | undefined;
  let passed = false;
  t.after(async () => {
    if (engine) await engine.teardown(t, () => passed);
    else env.restore();
  });
  t.mock.method(globalThis, "fetch", () => {
    throw new Error("network forbidden in placement test");
  });
  const git = (...args: string[]) =>
    execFileSync("git", ["-C", caller, ...args], { encoding: "utf8", timeout: 10_000 });
  mkdirSync(join(caller, ".pi/agents/perk"), { recursive: true });
  mkdirSync(join(caller, ".perk/workflow"), { recursive: true });
  writeFileSync(join(caller, ".gitignore"), ".perk/\n.pi/subagents/\n");
  writeFileSync(
    join(caller, ".pi/agents/perk/pr-reviewer.md"),
    readFileSync(resolve(import.meta.dirname, "../../agents/pr-reviewer.md")),
  );
  writeFileSync(
    join(caller, ".pi/settings.json"),
    JSON.stringify({ subagents: { disableBuiltins: true } }),
  );
  const planRef = '{"plan_id":"synthetic","branch":"fixture"}\n';
  const planSnapshot = "# Synthetic caller-only plan\n\n Preserve these bytes. \n";
  writeFileSync(join(caller, ".perk/workflow/plan-ref.json"), planRef);
  writeFileSync(join(caller, ".perk/workflow/plan.md"), planSnapshot);
  git("init", "-q");
  git("add", ".gitignore", ".pi");
  git("-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "fixture");
  assert.equal(git("status", "--porcelain"), "");
  const inventory = git("worktree", "list", "--porcelain");
  const setupLog = join(scratch, "setup.log");
  const hook = join(scratch, "setup.sh");
  writeFileSync(hook, `#!/bin/sh\nprintf 'setup\\n' >> '${setupLog}'\nprintf '{}\\n'\n`);
  chmodSync(hook, 0o755);
  engine = await bootInstalledEngine({
    root,
    scratch,
    caller,
    env,
    parentSessionId: "placement-parent",
    factoryModule: resolve(import.meta.dirname, "../testing/planBoundReviewChildFactory.mjs"),
    config: {
      worktree: true,
      worktreeBaseDir: join(scratch, "worktrees"),
      worktreeSetupHook: hook,
      worktreeSetupHookTimeoutMs: 5_000,
      artifactDir: "temp",
      asyncByDefault: true,
    },
  });
  assert.equal(engine.config.worktree, true);
  const wave = createReportWave(engine.events, { parentReadOnly: () => false });
  const request = {
    flow: "plan-bound-review-compat",
    completeness: "strict" as const,
    outputSchema: OBSERVATION_SCHEMA,
    timeoutMs: 60_000,
  };
  const task = "Measure the actual child launch via the scripted observation factory.";
  const protectedResult = await wave.run({
    ...request,
    execution: "caller-read-only",
    assignments: [{ key: "protected", agent: "perk.pr-reviewer", task }],
  });
  const protectedObservation = observationOf(protectedResult, "protected");
  assert.equal(realpathSync(protectedObservation.launch_cwd), realpathSync(caller));
  assert.equal(realpathSync(protectedObservation.process_cwd), realpathSync(caller));
  assert.equal(protectedObservation.plan_ref_text, planRef);
  assert.equal(protectedObservation.plan_snapshot_text, planSnapshot);
  assert.equal(protectedObservation.read_only, true);
  assert.equal(git("worktree", "list", "--porcelain"), inventory);
  assert.equal(existsSync(setupLog), false);
  const controlResult = await wave.run({
    ...request,
    assignments: [{ key: "control", agent: "perk.pr-reviewer", task }],
  });
  const control = observationOf(controlResult, "control");
  // The native engine may remove its clean worktree before returning; compare canonical-root
  // placement without requiring the allocation to remain on disk after settlement.
  const controlCwd = existsSync(control.launch_cwd)
    ? realpathSync(control.launch_cwd)
    : resolve(control.launch_cwd);
  assert.notEqual(controlCwd, realpathSync(caller));
  const allocated = relative(join(scratch, "worktrees"), controlCwd);
  assert.ok(allocated !== "" && !allocated.startsWith("..") && !isAbsolute(allocated), controlCwd);
  assert.notEqual(control.child_run_id, protectedObservation.child_run_id);
  assert.equal(control.plan_ref_text, null);
  assert.equal(control.plan_snapshot_text, null);
  assert.equal(control.read_only, false);
  assert.equal(readFileSync(setupLog, "utf8"), "setup\n");
  assert.deepEqual(
    new Set(runnerIdentities(env.nativeTemp).map(({ runId }) => runId)),
    new Set([protectedObservation.child_run_id, control.child_run_id]),
    "exactly two detached native children",
  );
  passed = true;
});
