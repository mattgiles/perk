// Live warm-door tests for the v1 learn-factory installer (`/learn-docs` + `/learn-code`): the
// strict `decodeGather` reject/coercion branches (once — the decode is kind-independent), the
// frozen command-description baselines (byte pins for both kinds, covering the routing
// vocabulary's user-facing strings), the cold-door delegation through a fake `perk` via PERK_BIN
// (offline, no gh/Python), the interactive `plan_save` host guard arms, and the headless
// materialize-only arm. The pure guidance renders live in learning/prose.test.ts.

import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  fakePerk,
  loadPerkSession,
  scaffoldRepo,
  spyInjections,
} from "../../../testing/harness.ts";
import { decodeGather } from "./factory.ts";

const GATHER_DOCS_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  inbox_path: ".perk/workflow/scratch/learn-docs-inbox.md",
  learn_numbers: [45, 50],
  launched: false,
});

const GATHER_CODE_JSON = JSON.stringify({
  success: true,
  error_type: null,
  message: null,
  inbox_path: ".perk/workflow/scratch/learn-code-inbox.md",
  learn_numbers: [47, 48],
  launched: false,
});

// --- decodeGather reject branches (the strict decode returns null) ------------------------------

test("decodeGather: missing inbox_path rejects", () => {
  assert.equal(decodeGather({ learn_numbers: ["45"] }), null);
});

test("decodeGather: non-array learn_numbers rejects", () => {
  assert.equal(decodeGather({ inbox_path: "inbox.md", learn_numbers: "45" }), null);
});

test("decodeGather: bad element types in learn_numbers reject", () => {
  assert.equal(decodeGather({ inbox_path: "inbox.md", learn_numbers: [{}, true] }), null);
});

test("decodeGather: valid payload coerces numbers to string ids", () => {
  // String ids are canonical (§8.21); the numeric tolerance covers older envelopes.
  assert.deepEqual(decodeGather({ inbox_path: "inbox.md", learn_numbers: [45, "50"] }), {
    inbox_path: "inbox.md",
    learn_numbers: ["45", "50"],
  });
});

// --- registration parity (the baseline-exact description pins) -----------------------------------

test("registration parity: both factory commands match the frozen baselines", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  try {
    assert.deepEqual(
      h.registeredCommand("learn-docs"),
      {
        name: "learn-docs",
        description:
          "Start the learned-docs plan factory: gather open perk:learn issues into an inbox " +
          "and author a docs/learned consolidation plan.",
      },
      "the /learn-docs command surface must match the frozen baseline byte-exactly",
    );
    assert.deepEqual(
      h.registeredCommand("learn-code"),
      {
        name: "learn-code",
        description:
          "Start the learn-code plan factory: gather pre-stamped SHOULD_BE_CODE perk:learn " +
          "issues into an inbox and author a plan routing each into its real code home.",
      },
      "the /learn-code command surface must match the frozen baseline byte-exactly",
    );
  } finally {
    h.dispose();
  }
});

// --- the success + empty-inbox arms (both kinds — the kind config is behavior) -------------------

test("/learn-docs: a success envelope notifies the gathered count and injects the guidance", async () => {
  // Doubles as the host guard's proceed case: the default read-write, stage-unscoped host keeps
  // `plan_save` active, so the guard admits the gather.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: GATHER_DOCS_JSON });
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
  const noIssues = JSON.stringify({
    success: false,
    error_type: "no_learn_issues",
    message: "no open perk:learn issues",
  });
  const bin = fakePerk(cwd, { stdout: noIssues, code: 1 });
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

test("/learn-code: a success envelope notifies the gathered count and injects the guidance", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: GATHER_CODE_JSON });
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
  const noIssues = JSON.stringify({
    success: false,
    error_type: "no_learn_issues",
    message: "no SHOULD_BE_CODE perk:learn issues",
  });
  const bin = fakePerk(cwd, { stdout: noIssues, code: 1 });
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

// --- the interactive host guard (shared register code — covered once on the docs kind) ----------

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
  const bin = fakePerk(cwd, { stdout: GATHER_DOCS_JSON, argvFile });
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
  const bin = fakePerk(cwd, { stdout: GATHER_DOCS_JSON, argvFile });
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
  const bin = fakePerk(cwd, { stdout: GATHER_DOCS_JSON, argvFile });
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

// --- the headless arms (shared register code — covered once on the docs kind) -------------------

test("/learn-docs: headless success gathers the inbox but drives no turn", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerk(cwd, { stdout: GATHER_DOCS_JSON });
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
  const bin = fakePerk(cwd, { stdout: GATHER_DOCS_JSON, argvFile });
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
