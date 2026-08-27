// Live warm-surface tests for the stacked-delivery status read (stackStatus.ts): the frozen
// registration baselines (tool + command), the strict bad_input decode, the objective-inference
// precedence through the registered tool, the lenient `renderStackStatus` render, and the two
// `/objective-stack` command arms (gate-on multiline success + multiline failure). Fully offline
// (fakePerk via PERK_BIN; a REAL bound AgentSession via the T1 harness). The mutating stack
// family's suite stays in doors/objectiveStack.test.ts.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { writePlanRef } from "../../../substrate/cache.ts";
import { REPORT_DETAIL_TYPE } from "../../../surfaces/surfaces.ts";
import { fakePerk, loadPerkSession, plantSession, scaffoldRepo } from "../../../testing/harness.ts";
import { OK_ENVELOPE, PLAN_REF } from "../../../testing/objectiveStackFixtures.ts";
import { renderStackStatus } from "./stackStatus.ts";

// --- frozen registration baselines (the 6.x convention) -----------------------------------

const BASELINE_STACK_STATUS = {
  name: "objective_stack_status",
  label: "Objective stack status",
  description:
    "Report an objective's stacked delivery train: layers, publication states, build " +
    "readiness, unresolved operations, pending continuation, and orphaned sync residue. " +
    "Read-only (delegates to the perk cold door).",
  parameters: {
    type: "object",
    additionalProperties: false,
    properties: {
      objective: {
        type: ["string", "number"],
        description: "The objective issue id (inferred from the session when omitted).",
      },
    },
  },
  promptSnippet: "Report the objective's stacked delivery train (read-only)",
  promptGuidelines: [
    "objective_stack_status is read-only — call it freely to inspect the delivery train, unresolved operations, pending continuations, and orphaned residue (objective inferred when omitted).",
  ],
  executionMode: "sequential",
};

test("registration parity: objective_stack_status + /objective-stack match the frozen baselines", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined }, headful: false });
  try {
    assert.deepEqual(
      h.registeredTool("objective_stack_status"),
      BASELINE_STACK_STATUS,
      "the COMPLETE objective_stack_status registration surface must match the frozen baseline",
    );
    assert.deepEqual(h.registeredCommand("objective-stack"), {
      name: "objective-stack",
      description:
        "Show an objective's stacked delivery train (status, operations, continuation, residue). " +
        "Pass an objective number (else the active objective, else the plan-ref's).",
    });
  } finally {
    h.dispose();
  }
});

// --- strict tool decode -------------------------------------------------------------------

test("decode: a mistyped objective refuses the whole call (bad_input)", async () => {
  const cwd = scaffoldRepo();
  // A throwing PERK_BIN proves the refusal happens before any cold-door exec.
  const bin = fakePerk(cwd, { stdout: "", code: 1 });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("objective_stack_status", { objective: [] });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false, "a mistyped objective must refuse");
    assert.equal(details.error_type, "bad_input");
  } finally {
    h.dispose();
  }
});

// --- objective inference precedence ---------------------------------------------------------

test("inference: explicit param wins over active_objective and plan-ref", async () => {
  const cwd = scaffoldRepo();
  writePlanRef(cwd, PLAN_REF);
  const file = plantSession(cwd, [{ active_objective: "9" }]);
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_ENVELOPE, argvFile });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined, PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    await h.invokeTool("objective_stack_status", { objective: "42" });
    assert.ok(readFileSync(argvFile, "utf8").includes("42"), "the explicit objective is passed");
  } finally {
    h.dispose();
  }
});

test("inference: active_objective wins over the plan-ref; plan-ref is the last tier", async () => {
  const cwd = scaffoldRepo();
  writePlanRef(cwd, PLAN_REF);
  const file = plantSession(cwd, [{ active_objective: "9" }]);
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_ENVELOPE, argvFile });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined, PERK_BIN: bin },
    sessionManager: SessionManager.open(file),
  });
  try {
    await h.invokeTool("objective_stack_status", {});
    const argv = readFileSync(argvFile, "utf8").trim().split("\n");
    assert.ok(argv.includes("9"), "active_objective resolved");
    assert.ok(!argv.includes("137"), "the plan-ref tier is not consulted when active is set");
  } finally {
    h.dispose();
  }
});

test("inference: plan-ref tier resolves when nothing else does; else a soft no_objective fail", async () => {
  const cwd = scaffoldRepo();
  writePlanRef(cwd, PLAN_REF);
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerk(cwd, { stdout: OK_ENVELOPE, argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined, PERK_BIN: bin } });
  try {
    await h.invokeTool("objective_stack_status", {});
    assert.ok(readFileSync(argvFile, "utf8").includes("137"), "the plan-ref objective resolved");
  } finally {
    h.dispose();
  }

  const bare = scaffoldRepo();
  const bareBin = fakePerk(bare, { stdout: OK_ENVELOPE });
  const h2 = await loadPerkSession({
    cwd: bare,
    env: { PERK_RUN_ID: undefined, PERK_BIN: bareBin },
  });
  try {
    const result = await h2.invokeTool("objective_stack_status", {});
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "no_objective");
  } finally {
    h2.dispose();
  }
});

// --- the lenient render ----------------------------------------------------------------------

test("renderStackStatus: train + operations + continuation + residue", () => {
  const text = renderStackStatus({
    objective: { id: "7", url: "https://x/7", redirected_from: null },
    delivery: "stacked",
    train: {
      base: "main",
      published_prefix_len: 1,
      layers: [
        { node_id: "1.1", branch: "plan-101", pr_number: 11, publication: "published" },
        { node_id: "1.2", branch: "plan-102", pr_number: 12, publication: "unpublished" },
      ],
      next_build_ready: { node_id: "1.3", ready: true, reason: null },
      blockers: [{ code: "stack_drift", message: "drifted", node_id: null, plan_id: null }],
      information: [],
    },
    operations: [{ operation_id: "01OP", kind: "sync", prepared_created: "2026-01-01" }],
    continuation: {
      operation_id: "01OP",
      conflict_node_id: "1.2",
      worktree_path: "/wt/sync-01OP",
      manifest_path: "/m/01L.json",
      parseable: true,
    },
    orphaned_residue: { observed: true, reason: null, worktrees: ["/wt/sync-01X"], refs: [] },
  });
  assert.match(text, /stacked delivery train \(base main, published prefix 1\/2\)/);
  assert.match(text, /1\. 1\.1 plan-101 pr #11 \[published\]/);
  assert.match(text, /next build-ready: 1\.3/);
  assert.match(text, /\[stack_drift\] drifted/);
  assert.match(text, /unresolved operation: 01OP \(sync, prepared 2026-01-01\)/);
  assert.match(text, /pending continuation: operation 01OP stopped on node 1\.2/);
  // The parseable arm offers all three gestures, resolve explicitly human-requested.
  assert.match(
    text,
    /resume via objective_stack_sync \{ continue: true \}, discard via \{ abort: true \}, or dispatch automated resolution via \{ resolve: true \} \(on explicit human request\)/,
  );
  assert.match(text, /orphaned residue: 1 worktree\(s\), 0 ref\(s\)/);
});

test("renderStackStatus: honors observed:false, the unparseable manifest, and no_train", () => {
  const text = renderStackStatus({
    objective: { id: "7" },
    no_train: "objective #7 is incremental",
    continuation: { manifest_path: "/m/01L.json", parseable: false },
    orphaned_residue: { observed: false, reason: "config unavailable", worktrees: [], refs: [] },
  });
  assert.match(text, /Objective #7: objective #7 is incremental/);
  assert.match(text, /UNPARSEABLE manifest at \/m\/01L\.json/);
  // The unparseable arm keeps only continue/abort — no automated-resolution offer.
  assert.match(
    text,
    /resume via objective_stack_sync \{ continue: true \}, or discard via \{ abort: true \}/,
  );
  assert.doesNotMatch(text, /resolve: true/);
  assert.match(text, /orphaned residue: not observed — config unavailable/);
});

test("renderStackStatus: the handoff part renders only for a non-not_applicable value", () => {
  const text = renderStackStatus({
    objective: { id: "7" },
    train: {
      base: "main",
      published_prefix_len: 2,
      layers: [
        {
          node_id: "1.1",
          branch: "plan-101",
          pr_number: 11,
          publication: "published",
          handoff: "ready",
        },
        {
          node_id: "1.2",
          branch: "plan-102",
          pr_number: 12,
          publication: "landed",
          handoff: "not_applicable",
        },
        { node_id: "1.3", branch: "plan-103", pr_number: 13, publication: "unpublished" },
      ],
    },
  });
  assert.match(text, /1\. 1\.1 plan-101 pr #11 \[published\] handoff ready/);
  // not_applicable and an absent field both degrade the part, never the render.
  assert.match(text, /2\. 1\.2 plan-102 pr #12 \[landed\]\n/);
  assert.match(text, /3\. 1\.3 plan-103 pr #13 \[unpublished\]$/m);
  assert.doesNotMatch(text, /1\.2 .*handoff/);
  assert.doesNotMatch(text, /1\.3 .*handoff/);
});

test("renderStackStatus: the landed prefix rides the train line when non-zero", () => {
  const payload = {
    objective: { id: "7" },
    train: {
      base: "main",
      published_prefix_len: 2,
      landed_prefix_len: 1,
      layers: [
        { node_id: "1.1", branch: "plan-101", pr_number: 11, publication: "landed" },
        { node_id: "1.2", branch: "plan-102", pr_number: 12, publication: "published" },
      ],
    },
  };
  assert.match(
    renderStackStatus(payload),
    /stacked delivery train \(base main, published prefix 2\/2, landed 1\)/,
  );
  assert.match(renderStackStatus(payload), /1\. 1\.1 plan-101 pr #11 \[landed\]/);
  // Zero landed layers: the line stays exactly the pre-growth shape.
  const zero = { ...payload, train: { ...payload.train, landed_prefix_len: 0 } };
  assert.match(renderStackStatus(zero), /published prefix 2\/2\)/);
});

test("renderStackStatus: planning_gate handoff rows render after the readiness line", () => {
  const text = renderStackStatus({
    objective: { id: "7" },
    train: {
      base: "main",
      published_prefix_len: 1,
      layers: [
        { node_id: "1.1", branch: "plan-101", pr_number: 11, publication: "published" },
        { node_id: "1.2", branch: "plan-102", publication: "unpublished" },
      ],
      next_build_ready: { node_id: "1.2", ready: true, reason: null },
      planning_gate: {
        node_id: "1.2",
        ready: false,
        blockers: [
          {
            kind: "handoff",
            code: null,
            message: null,
            dependency_node_id: "1.1",
            plan: "101",
            pr: 11,
            handoff_state: "stale",
            stamped_head: "a".repeat(40),
            current_head: "b".repeat(40),
            remediation: "perk ready 101",
          },
          // A technical row never renders a planning-gated line (the build-blocked
          // line/findings already carry it).
          { kind: "technical", code: "prefix_gap", message: "gap" },
        ],
      },
    },
  });
  assert.match(text, /next build-ready: 1\.2/);
  assert.match(
    text,
    /planning gated: 1\.2 waits on 1\.1 \(plan #101, PR #11\) — stale; stamped a{12} ≠ head b{12}; record the handoff: perk ready 101/,
  );
  assert.doesNotMatch(text, /planning gated: .*prefix_gap/);
});

test("renderStackStatus: planning_gate degrades leniently (absent, ready, malformed)", () => {
  const base = {
    objective: { id: "7" },
    train: {
      base: "main",
      published_prefix_len: 0,
      layers: [{ node_id: "1.1", branch: "plan-101", publication: "unpublished" }],
      next_build_ready: { node_id: "1.1", ready: true, reason: null },
    },
  };
  // Absent block: the pre-growth render is unchanged.
  assert.doesNotMatch(renderStackStatus(base), /planning gated/);
  // A ready gate renders nothing.
  const ready = {
    ...base,
    train: { ...base.train, planning_gate: { node_id: "1.1", ready: true, blockers: [] } },
  };
  assert.doesNotMatch(renderStackStatus(ready), /planning gated/);
  // Malformed fields degrade to placeholders — never a reject.
  const malformed = {
    ...base,
    train: {
      ...base.train,
      planning_gate: {
        node_id: 7,
        ready: "nope",
        blockers: [{ kind: "handoff", dependency_node_id: 9, plan: 101, pr: "11" }, "junk"],
      },
    },
  };
  const text = renderStackStatus(malformed);
  assert.match(
    text,
    /planning gated: \? waits on \? \(plan #\?, PR #\?\) — \?; record the handoff: \?/,
  );
});

// --- the /objective-stack command arms -------------------------------------------------------

test("/objective-stack renders multiline status as a headline plus generic detail", async (t) => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const bin = fakePerk(cwd, {
    stdout: JSON.stringify({
      success: true,
      objective: { id: "7" },
      no_train: "objective #7 is incremental",
      orphaned_residue: {
        observed: true,
        reason: null,
        worktrees: ["/tmp/perk-sync"],
        refs: ["refs/perk/sync"],
      },
    }),
  });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_BIN: bin },
    mode: "print",
  });
  const stderr: string[] = [];
  t.mock.method(console, "error", (message: unknown) => stderr.push(String(message)));
  const complete =
    "Objective #7: objective #7 is incremental\n" +
    "orphaned residue: 1 worktree(s), 1 ref(s) — sweep via objective_stack_recover";
  try {
    await h.invokeCommand("objective-stack", "7");
    assert.deepEqual(
      h.notifyEvents.filter((event) => event.message.includes("objective #7 is incremental")),
      [
        {
          message: "perk: objective-stack — Objective #7: objective #7 is incremental",
          severity: "info",
        },
      ],
    );
    const entries = h.session.sessionManager.getEntries() as unknown as {
      customType?: string;
      data?: unknown;
    }[];
    assert.deepEqual(
      entries.filter((entry) => entry.customType === REPORT_DETAIL_TYPE).map((entry) => entry.data),
      [{ text: `perk: objective-stack — ${complete}`, severity: "info" }],
    );
    assert.deepEqual(stderr, []);
  } finally {
    h.dispose();
  }
});

test("/objective-stack reports a multiline cold-door failure without raw stderr", async (t) => {
  const cwd = scaffoldRepo();
  const message = "no train\ninspect the objective linkage";
  const bin = fakePerk(cwd, {
    stdout: JSON.stringify({ success: false, error_type: "not_stacked", message }),
    code: 1,
  });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: undefined, PERK_BIN: bin },
    mode: "print",
  });
  const stderr: string[] = [];
  t.mock.method(console, "error", (value: unknown) => stderr.push(String(value)));
  try {
    await h.invokeCommand("objective-stack", "7");
    assert.deepEqual(
      h.notifyEvents.filter((event) => event.severity === "error"),
      [{ message: "perk: objective-stack — no train", severity: "error" }],
    );
    const entries = h.session.sessionManager.getEntries() as unknown as {
      customType?: string;
      data?: unknown;
    }[];
    assert.deepEqual(
      entries.filter((entry) => entry.customType === REPORT_DETAIL_TYPE).map((entry) => entry.data),
      [{ text: `perk: objective-stack — ${message}`, severity: "error" }],
    );
    assert.deepEqual(stderr, []);
  } finally {
    h.dispose();
  }
});
