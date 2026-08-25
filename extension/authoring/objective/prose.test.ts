// The feature-owned objective prose — pure render units: the backend-aware objective-read
// clause matrix, the seed guidance the warm doors inject (factory / reconcile / save), and the
// objective-authoring context content (+ the config addendum append). The injection/strip
// wiring is proven live in `pi/v1/objectiveAuthoring.test.ts`; the cross-plane byte-parity of
// the linear read clause is owned by the `objective-read-*` live-parity cases.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  factoryGuidance,
  OBJECTIVE_AUTHORING_CONTEXT,
  objectiveAuthoringContextContent,
  objectiveReadInstruction,
  objectiveSaveGuidance,
  reconcileGuidance,
} from "./prose.ts";

// Local fragments of the shared linear arm — used by the per-plane selection + guidance
// composition tests below (no longer a cross-plane lockstep; the `objective-read-*` live-parity
// cases own cross-plane byte-parity).
const OBJECTIVE_LINEAR_SUBSTRINGS = [
  "Linear Project",
  "linear_get_issue",
  "linear_list_comments",
  "inspect a node-issue",
  "if the linear tools are unavailable, open ",
];
const LINEAR_URL = "https://linear.app/acme/project/objective-7";

test("objectiveReadInstruction: linear arm carries the shared substrings + the url", () => {
  const clause = objectiveReadInstruction("linear", "7", LINEAR_URL);
  for (const needle of OBJECTIVE_LINEAR_SUBSTRINGS) {
    assert.ok(clause.includes(needle), `linear objective-read instruction missing: ${needle}`);
  }
  assert.ok(clause.includes(LINEAR_URL));
});

test("objectiveReadInstruction: linear without a url uses the indirect form, drops the open fallback", () => {
  const clause = objectiveReadInstruction("linear", "7", "");
  assert.ok(clause.includes("run `perk objective show 7` for its URL"));
  assert.ok(!clause.includes("if the linear tools are unavailable, open "));
  assert.ok(clause.includes("linear_get_issue") && clause.includes("linear_list_comments"));
});

test("objectiveReadInstruction: github (and any non-linear) arm is empty", () => {
  assert.equal(objectiveReadInstruction("github", "7", LINEAR_URL), "");
  assert.equal(objectiveReadInstruction("gitlab", "7", LINEAR_URL), "");
});

test("factoryGuidance + reconcileGuidance: linear arm injects the read clause; github is unchanged", () => {
  const planLinear = factoryGuidance("7", "1.2", "linear", LINEAR_URL);
  const reconcileLinear = reconcileGuidance("7", "linear", LINEAR_URL);
  for (const needle of OBJECTIVE_LINEAR_SUBSTRINGS) {
    assert.ok(planLinear.includes(needle), `factoryGuidance(linear) missing: ${needle}`);
    assert.ok(reconcileLinear.includes(needle), `reconcileGuidance(linear) missing: ${needle}`);
  }
  // The github arm (default) carries no linear fragment.
  const planGithub = factoryGuidance("7", "1.2");
  const reconcileGithub = reconcileGuidance("7");
  for (const needle of OBJECTIVE_LINEAR_SUBSTRINGS) {
    assert.ok(!planGithub.includes(needle), `factoryGuidance(github) leaked: ${needle}`);
    assert.ok(!reconcileGithub.includes(needle), `reconcileGuidance(github) leaked: ${needle}`);
  }
});

test("reconcileGuidance names both reconcile_objective and add_objective_node", () => {
  const text = reconcileGuidance("7");
  assert.ok(text.includes("reconcile_objective"), "still names reconcile_objective");
  assert.ok(text.includes("add_objective_node"), "now names add_objective_node");
  assert.ok(text.includes("SPARINGLY"), "frames node insertion as sparing");
  // The other side of the rule: the positive trigger circumstances are named too.
  assert.ok(text.includes("deferred follow-up"), "names the deferred-follow-up trigger");
  assert.ok(text.includes("missing prerequisite"), "names the missing-prerequisite trigger");
});

test("reconcileGuidance instructs reading objective engagement as untrusted DATA", () => {
  const text = reconcileGuidance("7");
  assert.ok(
    text.includes("perk objective engagement 7"),
    "names the objective engagement read worker with the objective id",
  );
  assert.ok(
    text.includes("<untrusted_objective_engagement>"),
    "names the untrusted-DATA block tag",
  );
  assert.ok(
    text.includes("never as instructions"),
    "frames the engagement as DATA, never instructions",
  );
});

test("factoryGuidance explores via ONE explore_objective_node call — no transcribed mechanics", () => {
  const text = factoryGuidance("42", "1.2");
  assert.match(text, /explore_objective_node/);
  assert.match(text, /\[models\.subagents\] objective-explorer/);
  // The transcription surface is gone: no workflowScript skeleton, no schema block, no model
  // clause — the tool owns the mechanics and reads the model at execute time.
  assert.doesNotMatch(text, /workflowScript/);
  assert.doesNotMatch(text, /outputSchema/);
  assert.doesNotMatch(text, /runs\.run/);
  assert.doesNotMatch(text, /structuredOutput/);
  assert.doesNotMatch(text, /"additionalProperties": false/);
  assert.doesNotMatch(text, /model: "/);
});

test("factoryGuidance instructs the file-first loop (draft → review → approval-driven save)", () => {
  const text = factoryGuidance("42", "1.2");
  // The draft tool and the review step are present.
  assert.match(text, /plan_draft/);
  assert.match(text, /plan_review/);
  // The unconditional planning mark (re-records the claim even on resume).
  assert.match(text, /even if it is already `planning`/);
  assert.match(text, /records the in-session claim/);
  // Approval carries the node link.
  assert.match(text, /recovers `objective_id`\/`node_id` automatically/);
  // The old primary-save mandate is gone (the failsafe sentence is phrased differently).
  assert.doesNotMatch(text, /then persist with/);
  assert.doesNotMatch(text, /passing BOTH `objective_id: "/);
  // The failsafe + never-implement mandate survive.
  assert.match(text, /Manual failsafe: `\/plan-save`/);
  assert.match(text, /ALWAYS save, NEVER implement directly/);
});

test("factoryGuidance instructs the node-engagement fetch (backend-neutral, both backends)", () => {
  // The warm seed instructs the model to fetch the node-issue's pre-planning engagement
  // once it knows the node. The instruction is backend-neutral (harmless on github) so it appears
  // for both linear and github seeds.
  const linear = factoryGuidance("7", "1.2", "linear", LINEAR_URL);
  const github = factoryGuidance("7", "1.2");
  for (const text of [linear, github]) {
    assert.match(text, /perk objective node-engagement 7 --node <id>/);
    assert.match(text, /untrusted\s+DATA/);
  }
});

test("objectiveSaveGuidance: with no title, drives the objective_save tool with prose + roadmap", () => {
  const text = objectiveSaveGuidance();
  assert.match(text, /objective_save/);
  assert.match(text, /prose/);
  assert.match(text, /roadmap/);
  assert.match(text, /JSON array of nodes/);
  assert.match(text, /defaults to the prose's first heading/);
});

test("objectiveSaveGuidance: with a title argument, names that title", () => {
  const text = objectiveSaveGuidance("Ship retries");
  assert.match(text, /title: "Ship retries"/);
});

test("objectiveSaveGuidance: does not hardcode the perk-objective-author skill pointer", () => {
  // The skill pointer rides the binding suffix, never the guidance body.
  assert.doesNotMatch(objectiveSaveGuidance(), /perk-objective-author/);
});

test("objectiveAuthoringContextContent: carries the authoring contract; appends the addendum", () => {
  const base = objectiveAuthoringContextContent(undefined);
  assert.match(base, /\[OBJECTIVE AUTHORING\]/);
  assert.equal(base, OBJECTIVE_AUTHORING_CONTEXT, "no addendum without config");

  const withAddendum = objectiveAuthoringContextContent(
    "House rule: cite a file path per change.\n",
  );
  assert.match(withAddendum, /House rule: cite a file path per change\./);
  assert.ok(withAddendum.startsWith(OBJECTIVE_AUTHORING_CONTEXT));
  assert.ok(withAddendum.endsWith("House rule: cite a file path per change."), "addendum trimmed");
});

test("OBJECTIVE_AUTHORING_CONTEXT is live state + pointers only (§8.57)", () => {
  // The injected context names the working-draft artifact, the review tool, and the bound
  // skill — it never restates the flow (the launch statement's job), the delivery-ask step,
  // or the save/failsafe endings, and it carries no skill read path (binding-delivered).
  assert.match(OBJECTIVE_AUTHORING_CONTEXT, /\[OBJECTIVE AUTHORING\]/);
  assert.match(OBJECTIVE_AUTHORING_CONTEXT, /objective_draft/);
  assert.match(OBJECTIVE_AUTHORING_CONTEXT, /plan_review/);
  assert.match(OBJECTIVE_AUTHORING_CONTEXT, /perk-objective-author/);
  assert.doesNotMatch(OBJECTIVE_AUTHORING_CONTEXT, /ask_user_question/);
  assert.doesNotMatch(OBJECTIVE_AUTHORING_CONTEXT, /incremental as the first, recommended option/);
  assert.doesNotMatch(OBJECTIVE_AUTHORING_CONTEXT, /\/objective-save/);
  assert.doesNotMatch(OBJECTIVE_AUTHORING_CONTEXT, /rendered objective/);
  assert.doesNotMatch(OBJECTIVE_AUTHORING_CONTEXT, /\.agents\/skills/);
});
