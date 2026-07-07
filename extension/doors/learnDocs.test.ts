// Door-level tests for the warm `/learn-docs` factory command (registered via
// `registerLearnFactoryDoor(pi, DOCS_DOOR)` — learnFactory.ts): the cold-door delegation through
// a fake `perk` via PERK_BIN (offline, no gh/Python). The pure decode + guidance tests live in
// learnFactory.test.ts. The headless early-return is fully shared `registerLearnFactoryDoor`
// code, so it is covered ONCE here (its learn-code twin is deliberately dropped).

import assert from "node:assert/strict";
import { test } from "node:test";
import { fakePerk, loadPerkSession, scaffoldRepo, spyInjections } from "../testing/harness.ts";

const GATHER_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  inbox_path: ".perk/workflow/scratch/learn-docs-inbox.md",
  learn_numbers: [45, 50],
  launched: false,
});

const NO_ISSUES_JSON = JSON.stringify({
  success: false,
  error_type: "no_learn_issues",
  message: "no open perk:learn issues",
});

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
