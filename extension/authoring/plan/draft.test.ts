// Direct feature tests for the plan working-draft operations — memory session only; no Pi, no
// filesystem. The failure taxonomy (blank_plan / no_identity / write_refused / unverified) is
// the adapter's rendered vocabulary, so the exact problem bytes are pinned here.

import assert from "node:assert/strict";
import { test } from "node:test";
import { openMemoryWorkflowSession } from "../../session/memoryWorkflowSession.ts";
import { PLAN_DRAFT_ARTIFACT, resumePlanDraft, revisePlanDraft } from "./draft.ts";

const PLAN = "# A plan\n\n## Steps\n\n1. Do the thing.\n";

test("revisePlanDraft: a blank plan refuses FIRST (before identity), exact problem bytes", () => {
  // Blank outranks no-identity: the identity-less session must still see the blank refusal.
  const session = openMemoryWorkflowSession({ runId: null });
  const result = revisePlanDraft({ plan: "   \n\t" }, session);
  assert.deepEqual(result, {
    status: "rejected",
    reason: "blank_plan",
    problem: "no plan markdown to write (pass the full working draft)",
  });
});

test("revisePlanDraft: an identity-less session rejects no_identity, exact problem bytes", () => {
  const session = openMemoryWorkflowSession({ runId: null });
  const result = revisePlanDraft({ plan: PLAN }, session);
  assert.deepEqual(result, {
    status: "rejected",
    reason: "no_identity",
    problem: "session has no run_id — cannot write the plan-draft artifact",
  });
});

test("revisePlanDraft: a verified write revises; the pointer + byte count ride the result", () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  const result = revisePlanDraft({ plan: PLAN }, session);
  assert.equal(result.status, "revised");
  if (result.status !== "revised") return;
  assert.equal(result.pointer.name, PLAN_DRAFT_ARTIFACT);
  assert.equal(result.pointer.run_id, "RID");
  assert.equal(result.bytes, Buffer.byteLength(PLAN, "utf8"));
  assert.equal(resumePlanDraft(session), PLAN);
});

test("revisePlanDraft: a byte-identical rewrite short-circuits unchanged", () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  assert.equal(revisePlanDraft({ plan: PLAN }, session).status, "revised");
  const again = revisePlanDraft({ plan: PLAN }, session);
  assert.equal(again.status, "unchanged");
  if (again.status !== "unchanged") return;
  assert.equal(again.bytes, Buffer.byteLength(PLAN, "utf8"));
});

test("revisePlanDraft: a seam refusal classifies write_refused (nothing landed)", () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  session.failNextWrite();
  const result = revisePlanDraft({ plan: PLAN }, session);
  assert.deepEqual(result, {
    status: "rejected",
    reason: "write_refused",
    problem: `could not write the ${PLAN_DRAFT_ARTIFACT} artifact (see warnings)`,
  });
  assert.equal(resumePlanDraft(session), null, "nothing consumable landed");
});

test("revisePlanDraft: a failed read-back proof classifies unverified", () => {
  const session = openMemoryWorkflowSession({ runId: "RID" });
  session.failNextPointerAppend();
  const result = revisePlanDraft({ plan: PLAN }, session);
  assert.deepEqual(result, {
    status: "unverified",
    problem: `could not write the ${PLAN_DRAFT_ARTIFACT} artifact (see warnings)`,
  });
  assert.equal(resumePlanDraft(session), null, "an orphaned write is never consumable");
});

test("resumePlanDraft: absent and invalid reads both fail open to null", () => {
  const absent = openMemoryWorkflowSession({ runId: "RID" });
  assert.equal(resumePlanDraft(absent), null);

  const corrupted = openMemoryWorkflowSession({ runId: "RID" });
  assert.equal(revisePlanDraft({ plan: PLAN }, corrupted).status, "revised");
  corrupted.corruptContent(PLAN_DRAFT_ARTIFACT);
  assert.equal(resumePlanDraft(corrupted), null, "a digest mismatch reads null (fail-open)");

  const identityless = openMemoryWorkflowSession({ runId: null });
  assert.equal(resumePlanDraft(identityless), null, "no identity reads absent → null");
});
