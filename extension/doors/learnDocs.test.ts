// Tests for the warm `/learn-docs` factory door: the pure `learnDocsGuidance` seed plus
// door-level delegation tests (a fake `perk` via PERK_BIN — offline, no gh/Python). The skill
// pointer is no longer in the pure guidance — the skill-binding suffix delivers it
// (command:learn-docs).

import assert from "node:assert/strict";
import { test } from "node:test";
import { fakePerk, loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import { learnDocsGuidance } from "./learnDocs.ts";

test("learnDocsGuidance names the inbox path", () => {
  const text = learnDocsGuidance(".pi/workflow/scratch/learn-docs-inbox.md", ["45", "50"]);
  assert.match(text, /\.pi\/workflow\/scratch\/learn-docs-inbox\.md/);
});

test("learnDocsGuidance carries the consumed learn numbers", () => {
  const text = learnDocsGuidance("inbox.md", ["45", "50"]);
  assert.match(text, /consumed_learn: \[45, 50\]/);
});

test("learnDocsGuidance no longer hardcodes the perk-learn-docs skill pointer", () => {
  const text = learnDocsGuidance("inbox.md", ["45"]);
  assert.doesNotMatch(text, /Follow the perk-learn-docs skill/);
});

// --- door-level tests (the cold-door delegation through runColdDoor) ----------------------------

const GATHER_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  inbox_path: ".pi/workflow/scratch/learn-docs-inbox.md",
  learn_numbers: [45, 50],
  launched: false,
});

const NO_ISSUES_JSON = JSON.stringify({
  success: false,
  error_type: "no_learn_issues",
  message: "no open perk:learn issues",
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

test("/learn-docs: a success envelope notifies the gathered count and injects the guidance", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: GATHER_JSON });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("learn-docs", "");
    assert.ok(
      h.notifies.some((n) => n.includes("gathered 2 learn issue(s)")),
      "notified the gathered count",
    );
    assert.ok(
      injected.some((m) => m.includes("learned-docs plan factory") && m.includes("[45, 50]")),
      "the factory guidance was injected",
    );
  } finally {
    h.dispose();
  }
});

test("/learn-docs: no_learn_issues at exit 1 warns gently and injects nothing", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: NO_ISSUES_JSON, code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("learn-docs", "");
    assert.ok(
      h.notifies.some((n) => n.includes("nothing to consolidate (no open perk:learn issues).")),
      "warned gently",
    );
    assert.equal(injected.length, 0, "no guidance injected");
  } finally {
    h.dispose();
  }
});

test("/learn-docs: headless success gathers the inbox but drives no turn", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: GATHER_JSON });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    headful: false,
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("learn-docs", "");
    assert.equal(injected.length, 0, "headless: no injection");
    assert.equal(h.notifies.length, 0, "headless: no notify");
  } finally {
    h.dispose();
  }
});
