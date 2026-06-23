// Warm-door binding delivery. Pure render/suffix cases mirror tests/test_binding_delivery.py
// (the cold twin), plus harness-driven Mechanism-A injection, the cold↔warm dedup, and the
// stale-context strip, driven through a REAL bound AgentSession (offline). See bindingDelivery.ts.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import {
  loadPerkSession,
  plantRawSession,
  plantSession,
  scaffoldRepo,
} from "../testing/harness.ts";
import {
  BINDING_CONTEXT_TYPE,
  BINDING_HEADER,
  bindingSuffix,
  renderBindings,
  resolvedBindings,
} from "./bindingDelivery.ts";

/** Write a `.pi/perk.toml` with the given `[[bindings]]` rows. */
function writeBindings(
  cwd: string,
  rows: { trigger: string; skill: string; mode: string }[],
): void {
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  const body = rows
    .map(
      (r) => `[[bindings]]\ntrigger = "${r.trigger}"\nskill = "${r.skill}"\nmode = "${r.mode}"\n`,
    )
    .join("\n");
  writeFileSync(join(cwd, ".pi", "perk.toml"), body, "utf8");
}

/** Write `.agents/skills/<skill>/SKILL.md`. */
function writeSkill(cwd: string, skill: string, body: string): void {
  const dir = join(cwd, ".agents", "skills", skill);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "SKILL.md"), body, "utf8");
}

// --- The cross-plane literal pin (mirror of the sibling pin in tests/test_binding_delivery.py) ---

test("BINDING_HEADER is the exact cross-plane dedup marker (== the Python cold _HEADER)", () => {
  assert.equal(BINDING_HEADER, "The following skill binding(s) apply here:");
});

// --- Pure render/suffix cases (mirror render_cold_bindings in tests/test_binding_delivery.py) ---

test("nudge at a new trigger renders a pointer under the header", () => {
  const cwd = scaffoldRepo();
  writeBindings(cwd, [{ trigger: "stage:save", skill: "my-skill", mode: "nudge" }]);
  writeSkill(cwd, "my-skill", "# my-skill\n"); // installed -> no missing-skill warning
  const { text, warnings } = renderBindings(cwd, "stage:save");
  assert.ok(text !== null);
  assert.match(text, /Follow the `my-skill` skill\./);
  assert.ok(text.includes(BINDING_HEADER)); // the header
  assert.deepEqual(warnings, []);
});

test("a nudge to an uninstalled skill warns loud-but-non-fatal (D6)", () => {
  const cwd = scaffoldRepo();
  writeBindings(cwd, [{ trigger: "stage:save", skill: "ghost-skill", mode: "nudge" }]);
  const { text, warnings } = renderBindings(cwd, "stage:save");
  assert.ok(text !== null);
  assert.match(text, /Follow the `ghost-skill` skill\./); // the pointer still reaches the model
  assert.equal(warnings.length, 1);
  assert.match(warnings[0] as string, /ghost-skill/);
});

test("transclude inlines the skill body with frontmatter stripped", () => {
  const cwd = scaffoldRepo();
  writeBindings(cwd, [{ trigger: "stage:save", skill: "deep-skill", mode: "transclude" }]);
  writeSkill(
    cwd,
    "deep-skill",
    "---\nname: deep-skill\ndescription: x\n---\n\n# Deep\n\nThe body lives here.\n",
  );
  const { text, warnings } = renderBindings(cwd, "stage:save");
  assert.ok(text !== null);
  assert.match(text, /The body lives here\./);
  assert.match(text, /# Deep/);
  assert.doesNotMatch(text, /name: deep-skill/); // frontmatter stripped
  assert.match(text, /inlined for `stage:save`/);
  assert.deepEqual(warnings, []);
});

test("a missing transclude target warns and falls back to the nudge pointer", () => {
  const cwd = scaffoldRepo();
  writeBindings(cwd, [{ trigger: "stage:save", skill: "ghost-skill", mode: "transclude" }]);
  const { text, warnings } = renderBindings(cwd, "stage:save");
  assert.ok(text !== null);
  assert.match(text, /Follow the `ghost-skill` skill\./); // nudge fallback
  assert.equal(warnings.length, 1);
  assert.match(warnings[0] as string, /ghost-skill/);
});

test("a shipped default IS delivered (the single delivery path)", () => {
  const cwd = scaffoldRepo(); // no user overlay
  const { text } = renderBindings(cwd, "stage:implement");
  assert.ok(text !== null);
  assert.match(text, /Follow the `perk-implement` skill\./);
  // resolvedBindings is the full shipped default set (no subtraction).
  assert.ok(resolvedBindings(cwd).some((b) => b.trigger === "stage:implement"));
});

test("a user override of a perk-owned trigger IS delivered", () => {
  const cwd = scaffoldRepo();
  writeBindings(cwd, [{ trigger: "stage:implement", skill: "custom-implement", mode: "nudge" }]);
  const { text } = renderBindings(cwd, "stage:implement");
  assert.ok(text !== null);
  assert.match(text, /Follow the `custom-implement` skill\./);
});

test("only the matching trigger is rendered", () => {
  const cwd = scaffoldRepo();
  writeBindings(cwd, [
    { trigger: "stage:save", skill: "save-skill", mode: "nudge" },
    { trigger: "stage:other", skill: "other-skill", mode: "nudge" },
  ]);
  const { text } = renderBindings(cwd, "stage:save");
  assert.ok(text !== null);
  assert.match(text, /save-skill/);
  assert.doesNotMatch(text, /other-skill/);
});

test("a shape-invalid user binding is dropped (renders nothing, no warm issue surface)", () => {
  const cwd = scaffoldRepo();
  writeBindings(cwd, [{ trigger: "stage:save", skill: "", mode: "nudge" }]); // missing skill
  assert.equal(renderBindings(cwd, "stage:save").text, null);
});

// --- bindingSuffix (Mechanism B) ---

test("bindingSuffix: empty when no binding matches; prefixed (with the default) when it does", () => {
  const cwd = scaffoldRepo();
  // A shipped command default IS now delivered — the suffix carries its pointer.
  const def = bindingSuffix(cwd, "command:objective-reconcile");
  assert.ok(def.startsWith("\n\n"));
  assert.match(def, /Follow the `perk-objective-reconcile` skill\./);
  // A trigger nothing matches → empty suffix.
  assert.equal(bindingSuffix(cwd, "command:nonexistent"), "");

  writeBindings(cwd, [{ trigger: "command:learn-docs", skill: "custom-docs", mode: "nudge" }]);
  const suffix = bindingSuffix(cwd, "command:learn-docs");
  assert.ok(suffix.startsWith("\n\n"));
  assert.match(suffix, /Follow the `custom-docs` skill\./);
  assert.ok(suffix.includes(BINDING_HEADER));
});

// --- Mechanism A: the before_agent_start injection + dedup + strip (harness) ---

test("Mechanism A injects the launched stage's resolved bindings as hidden context", async () => {
  const cwd = scaffoldRepo();
  writeBindings(cwd, [{ trigger: "stage:save", skill: "my-skill", mode: "nudge" }]);
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-write", stage: "save" }]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(h.workflowState().stage, "save");
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some(
        (m) => m.customType === BINDING_CONTEXT_TYPE && String(m.content).includes(BINDING_HEADER),
      ),
      "stage:save binding injected under the header",
    );
  } finally {
    h.dispose();
  }
});

test("Mechanism A injects the stage:plan DEFAULT pointer with no user overlay (D6)", async () => {
  const cwd = scaffoldRepo(); // no user overlay → only the shipped defaults
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-only", stage: "plan" }]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(h.workflowState().stage, "plan");
    const injected = await h.emitBeforeAgentStart();
    assert.ok(
      injected.some(
        (m) =>
          m.customType === BINDING_CONTEXT_TYPE &&
          String(m.content).includes("Follow the `perk-plan` skill."),
      ),
      "the stage:plan default is delivered warm (cold `perk plan` launches idle)",
    );
  } finally {
    h.dispose();
  }
});

test("Mechanism A is a no-op when no stage is launched", async () => {
  const cwd = scaffoldRepo();
  writeBindings(cwd, [{ trigger: "stage:save", skill: "my-skill", mode: "nudge" }]);
  // A run_id keep-session but NO stage recorded → no stage trigger.
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-write" }]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const injected = await h.emitBeforeAgentStart();
    assert.equal(
      injected.some((m) => m.customType === BINDING_CONTEXT_TYPE),
      false,
      "no stage → no injection",
    );
  } finally {
    h.dispose();
  }
});

test("Mechanism A dedups against a cold-prompt header already on the branch", async () => {
  const cwd = scaffoldRepo();
  writeBindings(cwd, [{ trigger: "stage:save", skill: "my-skill", mode: "nudge" }]);
  // Simulate the cold door: a prior message on the branch already carries BINDING_HEADER.
  const file = plantRawSession(cwd, [
    {
      custom: {
        type: "perk:workflow-state",
        data: { run_id: "01RID", mode: "read-write", stage: "save" },
      },
    },
    { assistant: `${BINDING_HEADER}\n\nFollow the \`my-skill\` skill.` },
  ]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(h.workflowState().stage, "save");
    const injected = await h.emitBeforeAgentStart();
    assert.equal(
      injected.some((m) => m.customType === BINDING_CONTEXT_TYPE),
      false,
      "header already on branch (cold prompt) → no warm double-delivery",
    );
  } finally {
    h.dispose();
  }
});

test("Mechanism A dedups against a prior warm binding-context custom (idempotent across turns)", async () => {
  const cwd = scaffoldRepo();
  writeBindings(cwd, [{ trigger: "stage:save", skill: "my-skill", mode: "nudge" }]);
  const file = plantRawSession(cwd, [
    {
      custom: {
        type: "perk:workflow-state",
        data: { run_id: "01RID", mode: "read-write", stage: "save" },
      },
    },
    {
      custom: {
        type: BINDING_CONTEXT_TYPE,
        data: { content: `${BINDING_HEADER}\n\nFollow the \`my-skill\` skill.` },
      },
    },
  ]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const injected = await h.emitBeforeAgentStart();
    assert.equal(
      injected.some((m) => m.customType === BINDING_CONTEXT_TYPE),
      false,
      "prior warm injection on branch → no re-injection",
    );
  } finally {
    h.dispose();
  }
});

test("the context strip removes a stale binding-context custom when the stage no longer binds", async () => {
  const cwd = scaffoldRepo();
  // NO user overlay → stage:save renders nothing → a lingering binding-context is stale.
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-write", stage: "save" }]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const surviving = await h.emitContext([
      { customType: BINDING_CONTEXT_TYPE, content: `${BINDING_HEADER}\n\nstale` },
      { role: "user", content: "a normal message" },
    ]);
    assert.equal(
      surviving.some((m) => (m as { customType?: string }).customType === BINDING_CONTEXT_TYPE),
      false,
      "stale binding-context stripped",
    );
    assert.equal(surviving.length, 1, "the normal message survives");
  } finally {
    h.dispose();
  }
});

test("the context strip KEEPS the binding-context (and the cold user prompt) while the stage binds", async () => {
  const cwd = scaffoldRepo();
  writeBindings(cwd, [{ trigger: "stage:save", skill: "my-skill", mode: "nudge" }]);
  const file = plantSession(cwd, [{ run_id: "01RID", mode: "read-write", stage: "save" }]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    const surviving = await h.emitContext([
      {
        customType: BINDING_CONTEXT_TYPE,
        content: `${BINDING_HEADER}\n\nFollow the \`my-skill\` skill.`,
      },
      { role: "user", content: `${BINDING_HEADER}\n\ncold prompt bindings` },
    ]);
    assert.equal(
      surviving.some((m) => (m as { customType?: string }).customType === BINDING_CONTEXT_TYPE),
      true,
      "the live binding-context is kept",
    );
    assert.equal(surviving.length, 2, "the cold user prompt carrying the header is never stripped");
  } finally {
    h.dispose();
  }
});
