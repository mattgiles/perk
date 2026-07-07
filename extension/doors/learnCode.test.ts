// Door-level tests for the warm `/learn-code` factory command (registered via
// `registerLearnFactoryDoor(pi, CODE_DOOR)` — learnFactory.ts): the kind-config-bearing arms —
// the success envelope and the gentle empty inbox — through a fake `perk` via PERK_BIN (offline,
// no gh/Python). The pure decode + guidance tests live in learnFactory.test.ts; the shared
// headless arm is covered once in learnDocs.test.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import { fakePerk, loadPerkSession, scaffoldRepo, spyInjections } from "../testing/harness.ts";

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
