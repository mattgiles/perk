// Tests for the warm `/learn-code` factory door: the pure `learnCodeGuidance` seed plus
// door-level delegation tests (a fake `perk` via PERK_BIN — offline, no gh/Python). The skill
// pointer is no longer in the pure guidance — the skill-binding suffix delivers it
// (command:learn-code).

import assert from "node:assert/strict";
import { test } from "node:test";
import { fakePerk, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import { learnCodeGuidance } from "./learnCode.ts";

test("learnCodeGuidance names the inbox path", () => {
  const text = learnCodeGuidance(".perk/workflow/scratch/learn-code-inbox.md", ["47", "48"]);
  assert.match(text, /\.perk\/workflow\/scratch\/learn-code-inbox\.md/);
});

test("learnCodeGuidance carries the consumed learn numbers", () => {
  const text = learnCodeGuidance("inbox.md", ["47", "48"]);
  assert.match(text, /consumed_learn: \[47, 48\]/);
});

test("learnCodeGuidance does not hardcode the perk-learn-code skill pointer", () => {
  const text = learnCodeGuidance("inbox.md", ["47"]);
  assert.doesNotMatch(text, /Follow the perk-learn-code skill/);
});

// --- door-level tests (the cold-door delegation through runColdDoor) ----------------------------

const GATHER_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  inbox_path: ".perk/workflow/scratch/learn-code-inbox.md",
  learn_numbers: [47, 48],
  launched: false,
});

const NO_ISSUES_JSON = JSON.stringify({
  success: false,
  error_type: "no_learn_issues",
  message: "no SHOULD_BE_CODE perk:learn issues",
});

/**
 * Spy on the live session's `sendUserMessage` (the delegate behind `pi.sendUserMessage`) — the
 * keyless offline session can't run the injected turn, so we capture the injection instead.
 */
function spyInjections(h: Awaited<ReturnType<typeof loadPerkSession>>): string[] {
  const injected: string[] = [];
  (h.session as unknown as { sendUserMessage: (c: unknown) => Promise<void> }).sendUserMessage =
    async (c) => {
      injected.push(typeof c === "string" ? c : JSON.stringify(c));
    };
  return injected;
}

test("/learn-code: a success envelope notifies the gathered count and injects the guidance", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: GATHER_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("learn-code", "");
    assert.ok(
      h.notifies.some((n) => n.includes("gathered 2 learn issue(s)")),
      "notified the gathered count",
    );
    assert.ok(
      injected.some((m) => m.includes("learn-code plan factory") && m.includes("[47, 48]")),
      "the factory guidance was injected",
    );
  } finally {
    h.dispose();
  }
});

test("/learn-code: no_learn_issues at exit 1 warns gently and injects nothing", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: NO_ISSUES_JSON, code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("learn-code", "");
    assert.ok(
      h.notifies.some((n) => n.includes("nothing to route into code")),
      "warned gently",
    );
    assert.equal(injected.length, 0, "no guidance injected");
  } finally {
    h.dispose();
  }
});

test("/learn-code: headless success gathers the inbox but drives no turn", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: GATHER_JSON });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    headful: false,
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("learn-code", "");
    assert.equal(injected.length, 0, "headless: no injection");
    assert.equal(h.notifies.length, 0, "headless: no notify");
  } finally {
    h.dispose();
  }
});
