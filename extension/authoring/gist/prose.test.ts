// The feature-owned prose units: the §8.57 live-state-and-pointers discipline of the injected
// gist-authoring context and the pure addendum composition.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  GIST_AUTHOR_MARKER,
  GIST_AUTHORING_CONTEXT,
  GIST_DRAFT_TOOL_GUIDELINES,
  GIST_SAVE_TOOL_GUIDELINES,
  gistAuthoringContextContent,
} from "./prose.ts";

test("gistAuthoringContextContent: pure over the addendum param", () => {
  assert.equal(gistAuthoringContextContent(undefined), GIST_AUTHORING_CONTEXT);
  assert.equal(gistAuthoringContextContent(""), GIST_AUTHORING_CONTEXT);
  const withAddendum = gistAuthoringContextContent("House rule: cite a file path per change.\n");
  assert.equal(
    withAddendum,
    `${GIST_AUTHORING_CONTEXT}\n\nHouse rule: cite a file path per change.`,
  );
});

test("GIST_AUTHORING_CONTEXT is live state + pointers only (§8.57)", () => {
  // The injected context names the working-draft artifact, the review tool, and the bound
  // skill — it never restates the flow (the launch statement's job), the artifact's lightness
  // detail, or the save/failsafe endings, and it carries no skill read path (binding-delivered).
  assert.match(GIST_AUTHORING_CONTEXT, /\[GIST AUTHORING\]/);
  assert.ok(GIST_AUTHORING_CONTEXT.includes(GIST_AUTHOR_MARKER));
  assert.match(GIST_AUTHORING_CONTEXT, /gist_draft/);
  assert.match(GIST_AUTHORING_CONTEXT, /plan_review/);
  assert.match(GIST_AUTHORING_CONTEXT, /perk-gist-author/);
  assert.doesNotMatch(GIST_AUTHORING_CONTEXT, /no steps, no roadmap, no estimates/);
  assert.doesNotMatch(GIST_AUTHORING_CONTEXT, /\/gist-save/);
  assert.doesNotMatch(GIST_AUTHORING_CONTEXT, /\.agents\/skills/);
});

test("the tool guidelines keep their draft/save split", () => {
  assert.equal(GIST_DRAFT_TOOL_GUIDELINES.length, 3);
  assert.match(String(GIST_DRAFT_TOOL_GUIDELINES[0]), /pass the FULL prose each time/);
  assert.match(String(GIST_DRAFT_TOOL_GUIDELINES[1]), /never saves to the issue backend/);
  assert.equal(GIST_SAVE_TOOL_GUIDELINES.length, 3);
  assert.match(String(GIST_SAVE_TOOL_GUIDELINES[0]), /ends the turn/);
  assert.match(String(GIST_SAVE_TOOL_GUIDELINES[1]), /no implementation steps or roadmap/);
});
