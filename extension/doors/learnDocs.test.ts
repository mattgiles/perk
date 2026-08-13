// Door-level tests for the warm `/learn-docs` factory command (registered via
// `registerLearnFactoryDoor(pi, DOCS_DOOR)` — learnFactory.ts): the cold-door delegation through
// a fake `perk` via PERK_BIN (offline, no gh/Python). The pure decode + guidance tests live in
// learnFactory.test.ts. The headless early-return AND the interactive host guard are fully
// shared `registerLearnFactoryDoor` code, so both are covered ONCE here (their learn-code twins
// are deliberately dropped).

import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
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
  // Doubles as the host guard's proceed case: the default read-write, stage-unscoped host keeps
  // `plan_save` active, so the guard admits the gather.
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

// --- the interactive host guard (shared registerLearnFactoryDoor code — covered once here) ----

/** Assert the guard refused: no gather ran, nothing injected, and the cold door is named. */
function assertRefused(
  h: Awaited<ReturnType<typeof loadPerkSession>>,
  injected: string[],
  argvFile: string,
): void {
  assert.ok(!existsSync(argvFile), "the guard refuses BEFORE the gather (fake perk never ran)");
  assert.equal(injected.length, 0, "no guidance injected on refusal");
  assert.ok(
    h.notifies.some((n) => n.includes("plan_save") && n.includes("perk learn docs")),
    "the refusal names the missing tool and the cold door",
  );
}

test("/learn-docs: a gated read-only host is refused before the gather", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: GATHER_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("learn-docs", "");
    assertRefused(h, injected, argvFile);
  } finally {
    h.dispose();
  }
});

test("/learn-docs: a worktree-stage host (plan_save scoped off) is refused", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write", stage: "implement" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: GATHER_JSON, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("learn-docs", "");
    assertRefused(h, injected, argvFile);
  } finally {
    h.dispose();
  }
});

test("/learn-docs: a foreign setActiveTools restriction (no perk state) is refused", async () => {
  // The @tombell/pi-plan shape: a foreign provider hides tools via setActiveTools WITHOUT
  // writing perk workflow-state — only `pi.getActiveTools()` can see it (the authoritative
  // predicate; workflow-state would report a viable host here).
  const foreignRestrictor = (pi: ExtensionAPI): void => {
    pi.on("session_start", async () => {
      pi.setActiveTools(pi.getActiveTools().filter((name) => name !== "plan_save"));
    });
  };
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: GATHER_JSON, argvFile });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    extraExtensions: [foreignRestrictor],
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("learn-docs", "");
    assertRefused(h, injected, argvFile);
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

test("/learn-docs: headless with plan_save unavailable keeps materialize-only behavior", async () => {
  // The guard is interactive-only (ctx.hasUI): a headless gated host — where plan_save is scoped
  // off — must NOT be refused; the gather still runs so the inbox is materialized (no turn is
  // driven headless, so the save hazard cannot occur). Losing the hasUI arm would fail this.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: GATHER_JSON, argvFile });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    headful: false,
  });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("learn-docs", "");
    assert.ok(existsSync(argvFile), "the headless gather still ran (materialize-only)");
    assert.equal(injected.length, 0, "headless: no injection");
    assert.equal(h.notifies.length, 0, "headless: no notify (no refusal)");
  } finally {
    h.dispose();
  }
});
