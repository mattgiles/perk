import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { DRAFT_REVIEW_RECONCILIATION } from "./draftReviewDiagnostics.ts";

const root = new URL("../../../", import.meta.url);
const read = (path: string) => readFileSync(new URL(path, root), "utf8");
const normalized = (path: string) => read(path).replace(/\s+/g, " ");

test("human-only stop guidance pins quiescence, preserved evidence, orphan-not-proof and fresh-run-only content transfer", () => {
  const text = normalized(DRAFT_REVIEW_RECONCILIATION);
  for (const clause of [
    "Human-only; no in-place state repair",
    "every child save subprocess",
    "Establish subprocess quiescence, not merely PID death",
    "Keep the lock, review artifact, relevant draft",
    "run handoff, Pi session/transcript, and identity/digest diagnostics",
    "Do not edit JSONL, forge provenance pointers, prune the run, delete artifacts, or remove the lock",
    "orphan alone is not proof of no effects",
    "this and prior attempts",
    "neither a new review nor a new run is a safe retry",
    "continue its normal plan/objective/gist workflow rather than duplicate it",
    "Never blindly reset an in-progress node",
    "different run ID",
    "Never copy correlation, consumption, provenance maps, locks, request IDs, review IDs, dispatch intent, or approvals",
    "Leave the abandoned residue intact",
    "No automated rollback, quarantine, or cleanup is promised",
  ])
    assert.ok(text.includes(clause), `missing operator safety clause: ${clause}`);
  for (const command of [
    "perk plan",
    "perk objective plan <objective> --node <node>",
    "perk objective author",
    "perk gist author --scope <scope>",
  ])
    assert.ok(text.includes(command));
  assert.match(
    read(DRAFT_REVIEW_RECONCILIATION),
    /^---\ntitle: "How to reconcile a draft-review stop"/,
  );
  assert.ok(read("docs/user-docs/how-to/index.md").includes("./reconcile-a-draft-review-stop.md"));
  assert.ok(read("docs/site/src/sidebar.mjs").includes('"how-to/reconcile-a-draft-review-stop"'));
  const inventory = read("docs/design/docs-site-blueprint.md");
  assert.ok(inventory.includes("`/how-to/reconcile-a-draft-review-stop/`"));
});

for (const path of [
  "prompts/contexts/adapters/plannotator-plan.md",
  "prompts/contexts/adapters/plannotator-objective.md",
  "prompts/contexts/adapters/plannotator-gist.md",
  "prompts/stages/plan-review-browser.md",
  "prompts/stages/objective-review-browser.md",
  "skills/perk-plan-review-browser/SKILL.md",
  "skills/perk-objective-review-browser/SKILL.md",
]) {
  test(`${path}: runtime eligibility outranks unconditional apply/save and blind retry guidance`, () => {
    const text = normalized(path);
    assert.ok(text.includes(DRAFT_REVIEW_RECONCILIATION));
    assert.match(text, /diagnostic DATA only|only diagnostic DATA/);
    assert.match(text, /[Nn]o in-place repair/);
    assert.match(text, /intent/);
    assert.match(text, /startup\/reload/);
    assert.doesNotMatch(text, /if the save FAILED|completed review is never lost/);
  });
}
