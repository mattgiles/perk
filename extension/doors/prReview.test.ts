// #175 — tests for the warm `/pr-review` door. The pure `prReviewGuidance` is pinned directly
// (spawn target, fresh context, inline-model injection); the command's registration + headless
// safety is exercised against a REAL bound session via the T1 harness, OFFLINE (no LLM / network).

import assert from "node:assert/strict";
import { test } from "node:test";
import { loadPerkSession, scaffoldRepo } from "../testing/harness.ts";
import { prReviewGuidance } from "./prReview.ts";

test("prReviewGuidance spawns perk.pr-reviewer with a fresh context", () => {
  const text = prReviewGuidance();
  assert.match(text, /perk\.pr-reviewer/);
  assert.match(text, /context: "fresh"/);
});

test("prReviewGuidance injects the configured model when set", () => {
  const text = prReviewGuidance("anthropic/claude-opus-4");
  assert.match(text, /model: "anthropic\/claude-opus-4"/);
  assert.match(text, /\[subagents\] pr-reviewer model/);
});

test("prReviewGuidance omits the model override when unset", () => {
  const text = prReviewGuidance();
  assert.doesNotMatch(text, /model: "/);
  assert.match(text, /default model/);
});

test("prReviewGuidance tells the parent to take no further action (the child posts)", () => {
  const text = prReviewGuidance();
  assert.match(text, /posts/);
  assert.match(text, /NO further action/);
});

test("prReviewGuidance renders both verdict outcomes and the next-step surfacing", () => {
  const text = prReviewGuidance();
  // actionable → advisory COMMENT review, next step /address
  assert.match(text, /COMMENT review/);
  assert.match(text, /actionable .*`\/address`/u);
  // clean → a single 👍 reaction, next step /land
  assert.match(text, /\u{1F44D} reaction/u);
  assert.match(text, /clean .*`\/land`/u);
  // FYI notes are surfaced in-session only
  assert.match(text, /FYI notes/);
});

test("prReviewGuidance does not hardcode the perk-pr-review skill pointer (binding suffix)", () => {
  const text = prReviewGuidance();
  assert.doesNotMatch(text, /Follow the perk-pr-review skill/);
});

test("/pr-review registers and is headless-safe", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-write" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" }, headful: false });
  try {
    assert.ok(h.registeredCommands().includes("pr-review"), "the /pr-review command is registered");
  } finally {
    h.dispose();
  }
});
