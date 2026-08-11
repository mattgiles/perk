// Live warm-door tests for the `/address` review loop. Drive a REAL bound AgentSession via
// the T1 harness and prove the submit-then-resolve `finalize_address` delegation end-to-end,
// OFFLINE: a routed fake `perk` stands in for both Python cold-door mutations.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { type PlanRef, writePlanRef } from "../substrate/cache.ts";
import {
  fakePerkRouter,
  loadPerkSession,
  scaffoldRepo,
  spyInjections,
} from "../testing/harness.ts";
import { addressGuidance, decodeResolveParams } from "./address.ts";

const REF: PlanRef = {
  provider: "github",
  pr_id: "148",
  url: "https://github.com/mattgiles/perk/issues/148",
  labels: [],
  objective_id: null,
};

const SUBMIT_PAYLOAD = {
  success: true,
  error_type: null,
  message: null,
  pr: { number: 42, url: "https://github.com/x/pull/42", is_draft: true, existed: true },
  branch: "plan-148",
  issue: 148,
  plan_embedded: true,
  base: "main",
  mergeable: true,
  conflicts: [],
  delivery: "stacked",
  operation: {
    kind: "sync",
    operation_id: "op-sync",
    abandoned_operation_id: null,
    resumed: false,
    no_op: false,
    affected: [{ node_id: "3.3" }],
    notes: [],
  },
};

const RESOLVE_PAYLOAD = {
  success: true,
  error_type: null,
  message: null,
  dry_run: false,
  results: [
    { thread_id: "PRRT_1", success: true, comment_added: true, error: null },
    { thread_id: "PRRT_2", success: true, comment_added: false, error: null },
  ],
};

const PARTIAL_PAYLOAD = {
  success: false,
  error_type: null,
  message: null,
  dry_run: false,
  results: [
    { thread_id: "PRRT_1", success: true, comment_added: false, error: null },
    { thread_id: "PRRT_2", success: false, comment_added: true, error: "bad thread" },
  ],
};

function routes(
  resolve: { json: unknown; code?: number } = { json: RESOLVE_PAYLOAD },
  submit: unknown = SUBMIT_PAYLOAD,
) {
  return {
    "pr submit": { json: submit },
    "pr resolve-threads": resolve,
  };
}

test("addressGuidance injects the configured review-classifier model when set", () => {
  const text = addressGuidance(REF, false, "x/y");
  assert.match(text, /model: "x\/y"/);
  assert.match(text, /\[models\.subagents\] review-classifier model/);
});

test("addressGuidance omits the model override when unset", () => {
  assert.doesNotMatch(addressGuidance(REF, false), /model: "/);
});

test("addressGuidance classifies via ONE foreground workflowScript one-child run", () => {
  for (const preview of [false, true]) {
    const text = addressGuidance(REF, preview);
    assert.match(text, /workflowScript/);
    assert.match(text, /async: false/);
    assert.match(text, /runs\.run/);
    assert.match(text, /outputSchema/);
    assert.match(text, /structuredOutput/);
    assert.match(text, /"additionalProperties": false/);
  }
});

test("addressGuidance renders the converged body carrying the finalizer and no manual push", () => {
  const action = addressGuidance(REF, false);
  assert.match(action, /addressing review feedback on the PR for plan github #148/);
  assert.match(action, /Plan File Mode/);
  assert.match(action, /finalize_address/);
  assert.match(action, /Never push manually/);
  assert.doesNotMatch(action, /resolve_review_threads/);
  const preview = addressGuidance(REF, true);
  assert.match(preview, /PREVIEWING/);
  assert.doesNotMatch(preview, /Plan File Mode/);
  assert.doesNotMatch(preview, /finalize_address/);
});

test("/address with no active plan-ref warns and sends no guidance", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({ cwd });
  try {
    const { seeded } = await h.runCommandHandler("address", "");
    assert.equal(seeded.length, 0, "no guidance sent without a plan-ref");
    assert.ok(h.notifies.some((n) => n.includes("needs an active plan-ref")));
  } finally {
    h.dispose();
  }
});

test("/address with an active plan-ref proceeds", async () => {
  const cwd = scaffoldRepo();
  writePlanRef(cwd, REF);
  const h = await loadPerkSession({ cwd });
  try {
    await h.runCommandHandler("address", "");
    assert.ok(h.notifies.some((n) => n.includes("classify → fix → resolve")));
    assert.ok(!h.notifies.some((n) => n.includes("needs an active plan-ref")));
  } finally {
    h.dispose();
  }
});

test("tool registration replaces resolve_review_threads with finalize_address", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.ok(h.registeredTool("finalize_address"));
    assert.equal(h.registeredTool("resolve_review_threads"), null);
  } finally {
    h.dispose();
  }
});

test("finalize_address submits before resolving, records the batch, and terminates", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerkRouter(cwd, routes(), { argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("finalize_address", {
      threads: [{ thread_id: "PRRT_1", comment: "Fixed" }, { thread_id: "PRRT_2" }],
      pr: 42,
      counts: { actionable: 2, informational: 0, praise: 0, question: 0 },
    });
    const details = result.details as {
      ok: boolean;
      submit?: { operation?: { affected_count: number } };
      resolved_thread_ids?: string[];
    };
    assert.equal(details.ok, true);
    assert.equal(result.terminate, true);
    assert.equal(details.submit?.operation?.affected_count, 1);
    assert.deepEqual(details.resolved_thread_ids, ["PRRT_1", "PRRT_2"]);
    assert.match(result.content[0]?.text ?? "", /Resolved 2 review thread\(s\)/);
    assert.match(result.content[0]?.text ?? "", /cascaded 1 layer\(s\)/);
    assert.deepEqual(readFileSync(argvFile, "utf8").trim().split("\n"), [
      "pr submit",
      "pr resolve-threads",
    ]);
    const batch = h.workflowState().last_review_batch as {
      pr?: number;
      resolved_thread_ids?: string[];
    };
    assert.equal(batch?.pr, 42);
    assert.deepEqual(batch?.resolved_thread_ids, ["PRRT_1", "PRRT_2"]);
  } finally {
    h.dispose();
  }
});

test("finalize_address re-drives a definitive conflict without parsed paths", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const submit = { ...SUBMIT_PAYLOAD, mergeable: false, conflicts: [] };
  const bin = fakePerkRouter(cwd, routes({ json: RESOLVE_PAYLOAD }, submit));
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  const injected = spyInjections(h);
  try {
    const result = await h.invokeTool("finalize_address", {
      threads: [{ thread_id: "PRRT_1" }, { thread_id: "PRRT_2" }],
    });
    assert.equal((result.details as { ok: boolean }).ok, true);
    assert.equal(injected.length, 1);
    assert.match(injected[0] ?? "", /perk\.conflict-resolver/);
    assert.equal(h.workflowState().conflict_resolution_attempts, 1);
  } finally {
    h.dispose();
  }
});

test("finalize_address: submit failure does not resolve and stays non-terminating", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerkRouter(
    cwd,
    { "pr submit": { json: { success: false, error_type: "remote_drift", message: "drift" } } },
    { argvFile },
  );
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("finalize_address", {
      threads: [{ thread_id: "PRRT_1" }],
    });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "remote_drift");
    assert.equal(result.terminate, undefined);
    assert.match(result.content[0]?.text ?? "", /threads were NOT resolved/);
    assert.equal(readFileSync(argvFile, "utf8").trim(), "pr submit");
    assert.equal(h.workflowState().last_review_batch, undefined);
  } finally {
    h.dispose();
  }
});

test("finalize_address: partial resolve notes successful submit and stays non-terminating", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const bin = fakePerkRouter(cwd, routes({ json: PARTIAL_PAYLOAD }));
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("finalize_address", {
      threads: [
        { thread_id: "PRRT_1", comment: "already resolved" },
        { thread_id: "PRRT_2", comment: "reply posted before resolve failed" },
      ],
    });
    const details = result.details as {
      ok: boolean;
      error_type?: string;
      submit?: unknown;
      resolved_thread_ids?: string[];
      retry_threads?: Array<{ thread_id: string; comment?: string }>;
    };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "partial_failure");
    assert.ok(details.submit, "successful submit facts ride the partial arm");
    assert.deepEqual(details.resolved_thread_ids, ["PRRT_1"]);
    assert.deepEqual(details.retry_threads, [{ thread_id: "PRRT_2" }]);
    assert.equal(result.terminate, undefined);
    assert.match(result.content[0]?.text ?? "", /submit already succeeded/i);
    assert.match(result.content[0]?.text ?? "", /only details\.retry_threads/i);
    assert.equal(h.workflowState().last_review_batch, undefined);
  } finally {
    h.dispose();
  }
});

test("finalize_address: malformed resolve rows fail as bad_output after submit", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const malformed = {
    success: true,
    error_type: null,
    message: null,
    results: [{ thread_id: "PRRT_1", success: "yes", comment_added: false }],
  };
  const bin = fakePerkRouter(cwd, routes({ json: malformed }));
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("finalize_address", {
      threads: [{ thread_id: "PRRT_1" }],
    });
    const details = result.details as { ok: boolean; error_type?: string; submit?: unknown };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_output");
    assert.ok(details.submit);
    assert.equal(h.workflowState().last_review_batch, undefined);
  } finally {
    h.dispose();
  }
});

test("finalize_address: empty threads fails before either cold door", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerkRouter(cwd, routes(), { argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("finalize_address", { threads: [] });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
    assert.throws(() => readFileSync(argvFile, "utf8"));
  } finally {
    h.dispose();
  }
});

test("/address and /address --preview register and are headless-safe", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  try {
    assert.ok(h.registeredCommands().includes("address"));
  } finally {
    h.dispose();
  }
});

// --- tool-boundary decode (strict-fail on mistyped params) --------------------------------------

test("finalize_address: a malformed row → bad_input, no exec", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerkRouter(cwd, routes(), { argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("finalize_address", {
      threads: [{ thread_id: "PRRT_1" }, { comment: "no id" }],
    });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
    assert.throws(() => readFileSync(argvFile, "utf8"));
  } finally {
    h.dispose();
  }
});

test("finalize_address: mistyped counts → bad_input, no exec", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const argvFile = join(cwd, "argv.txt");
  const bin = fakePerkRouter(cwd, routes(), { argvFile });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID", PERK_BIN: bin } });
  try {
    const result = await h.invokeTool("finalize_address", {
      threads: [{ thread_id: "PRRT_1" }],
      counts: "x",
    });
    const details = result.details as { ok: boolean; error_type?: string };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "bad_input");
    assert.throws(() => readFileSync(argvFile, "utf8"));
  } finally {
    h.dispose();
  }
});

test("decodeResolveParams: tri-state strict-fail shapes", () => {
  assert.deepEqual(decodeResolveParams({ threads: [{ thread_id: "t1", comment: "c" }] }), {
    threads: [{ thread_id: "t1", comment: "c" }],
    pr: undefined,
    counts: undefined,
  });
  assert.deepEqual(decodeResolveParams({})?.threads, []);
  assert.deepEqual(decodeResolveParams({ threads: "x" })?.threads, []);
  assert.equal(decodeResolveParams(undefined), null);
  assert.equal(decodeResolveParams({ threads: [{ comment: "no id" }] }), null);
  assert.equal(decodeResolveParams({ threads: [{ thread_id: 5 }] }), null);
  assert.equal(decodeResolveParams({ threads: [{ thread_id: "t1", comment: 5 }] }), null);
  assert.equal(decodeResolveParams({ threads: [], pr: "42" }), null);
  assert.equal(decodeResolveParams({ threads: [], counts: "x" }), null);
  assert.equal(decodeResolveParams({ threads: [], counts: { actionable: "2" } }), null);
  assert.deepEqual(decodeResolveParams({ threads: [], counts: { actionable: 2 } })?.counts, {
    actionable: 2,
  });
});
