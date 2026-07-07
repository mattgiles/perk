// Tests for the implement-here exit (implementHere.ts): the guidance-builder content pins plus
// the `/implement-here` command arms driven through the real harness session (with the mandatory
// `session.sendUserMessage` spy — the keyless offline session can't run an injected turn).

import assert from "node:assert/strict";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { loadPerkSession, plantSession, scaffoldRepo, spyInjections } from "../testing/harness.ts";
import { implementHereGuidance } from "./implementHere.ts";

// ------------------------------------------------------------- implementHereGuidance (pure)

test("implementHereGuidance: content pins (no-issue / no-commit / doors / draft-intact)", () => {
  const cwd = scaffoldRepo();
  const text = implementHereGuidance(cwd, {});
  assert.match(text, /IMPLEMENT HERE/);
  assert.match(text, /no plan issue was created and none will be/);
  assert.match(text, /Do NOT commit, branch, or push unless the user explicitly asks/);
  assert.match(text, /\/submit, \/land, \/learn\) do not apply/);
  assert.match(text, /\/plan-save can still create the canonical issue later/);
  assert.doesNotMatch(text, /implement THESE final bytes/, "no inlined plan by default");
});

test("implementHereGuidance: the edited variant inlines the final reviewed bytes", () => {
  const cwd = scaffoldRepo();
  const text = implementHereGuidance(cwd, { editedPlan: "# Final plan bytes\n" });
  assert.match(text, /The human edited the plan during review; implement THESE final bytes:/);
  assert.match(text, /# Final plan bytes/);
});

// ----------------------------------------------------------- the /implement-here command arms

test("/implement-here: gate on -> gate exited (no save) + the guidance injected", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.inMemory(cwd) });
  const injected = spyInjections(h);
  try {
    await h.invokeCommand("plan");
    assert.equal(h.workflowState().mode, "read-only", "plan mode on");
    await h.runCommandHandler("implement-here", "");
    assert.equal(h.workflowState().mode, "read-write", "the gate exited");
    assert.ok(
      h.notifies.some((n) => n.includes("plan mode off — implementing here; no issue saved")),
      "the exit was reported",
    );
    assert.ok(
      injected.some(
        (m) => m.includes("IMPLEMENT HERE") && m.includes("Do NOT commit, branch, or push"),
      ),
      "the implement-now guidance was injected",
    );
  } finally {
    h.dispose();
  }
});

test("/implement-here: gate off -> warning, gate untouched, nothing injected", async () => {
  const cwd = scaffoldRepo();
  const h = await loadPerkSession({ cwd });
  const injected = spyInjections(h);
  try {
    await h.runCommandHandler("implement-here", "");
    assert.ok(
      h.notifies.some((n) => n.includes("not in plan mode — nothing to exit")),
      "warned that there is nothing to exit",
    );
    assert.notEqual(h.workflowState().mode, "read-only", "no gate transition");
    assert.equal(injected.length, 0, "nothing injected");
  } finally {
    h.dispose();
  }
});

test("/implement-here: a seeded node claim refuses; gate stays on, nothing injected", async () => {
  const cwd = scaffoldRepo();
  const file = plantSession(cwd, [
    {
      run_id: "01RID",
      mode: "read-only",
      objective_node_claim: { objective: "115", node: "1.2" },
    },
  ]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  const injected = spyInjections(h);
  try {
    assert.equal(h.workflowState().mode, "read-only", "the planted gate is on");
    await h.runCommandHandler("implement-here", "");
    assert.ok(
      h.notifies.some((n) => n.includes("objective-node planning session")),
      "refused with the objective carve-out",
    );
    assert.equal(h.workflowState().mode, "read-only", "the gate stays on");
    assert.equal(injected.length, 0, "nothing injected");
  } finally {
    h.dispose();
  }
});
