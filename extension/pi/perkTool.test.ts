// The live tool catalog's F1 guards (contracts.md §8.3/§8.40): every terminal / interactive /
// orchestration tool is declared `model-only`, so `ctx.executeTool()` can never reach a
// `terminate: true` result; the `kind: terminal` set is pinned AND kept honest by a
// per-registration source scan (a reviewed-set guard, not a proof: a non-terminal registration
// that terminates through a helper absent from TERMINATING_ENTRY_POINTS, without the token in
// its span, is undetected — the structural half is `kind → model-only`). Real sessions, no fakes.

import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { before, test } from "node:test";
import { fauxAssistantMessage, fauxText, fauxToolCall } from "@earendil-works/pi-ai";
import {
  type AgentToolResult,
  createCodemodeExtension,
  type ExtensionAPI,
} from "@earendil-works/pi-coding-agent";
import ts from "typescript";
import { perkToolNames, perkToolPolicy } from "../substrate/toolPolicy.ts";
import { fauxModelRuntime, scaffoldRepo } from "../testing/harness.ts";
import { ensureToolCatalog, loadPerkSessionAt } from "../testing/toolCatalog.ts";

const PI_V1 = join(import.meta.dirname, "v1");

before(ensureToolCatalog);

const MODEL_ONLY_KINDS = new Set(["terminal", "interactive", "orchestration", "host"]);

const TERMINAL_TOOLS = [
  "plan_review",
  "plan_save",
  "objective_save",
  "gist_save",
  "submit",
  "ready",
  "finalize_address",
  "land",
  "learn",
];

/**
 * The functions through which a registration's definition reaches a terminating result without
 * the `terminate: true` token in its own span (each the delegate a terminal registration calls).
 * Frozen and stale-armed: every entry must be referenced by ≥ 1 terminal registration.
 */
const TERMINATING_ENTRY_POINTS = [
  // plan_review → runPlanReviewV1 → approvedSubjectSaveResult (+ the refinement arm's
  // refinementSaveResultOf).
  "executePlanReview",
  // plan_save → deps.renderSave → renderSavePlanOutcome.
  "planSaveDepsFor",
  "objectiveSaveResultOf",
  "gistSaveResultOf",
  "finishLearnResult",
  "landPr",
  "executeFinalizeAddress",
];

const sorted = (names: Iterable<string>): string[] => [...new Set(names)].sort();

// --- the per-registration terminate scan --------------------------------------------------------

type ScannedRegistration = {
  file: string;
  name: string;
  kind: string;
  terminates: boolean;
  entryPoints: string[];
};

function productionFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return productionFiles(path);
    return path.endsWith(".ts") && !path.endsWith(".test.ts") ? [path] : [];
  });
}

function stringProperty(literal: ts.ObjectLiteralExpression, key: string): string | null {
  for (const property of literal.properties) {
    if (
      ts.isPropertyAssignment(property) &&
      property.name.getText() === key &&
      ts.isStringLiteral(property.initializer)
    ) {
      return property.initializer.text;
    }
  }
  return null;
}

/** Every `registerPerkTool(pi, <definition literal>, <policy literal>)` call in one source. */
function scanRegistrations(file: string, source: string): ScannedRegistration[] {
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true);
  const found: ScannedRegistration[] = [];
  const visit = (node: ts.Node): void => {
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === "registerPerkTool"
    ) {
      const [, definition, policy] = node.arguments;
      assert.ok(
        definition !== undefined && ts.isObjectLiteralExpression(definition),
        `${file}: registerPerkTool's definition must be an inline object literal`,
      );
      assert.ok(
        policy !== undefined && ts.isObjectLiteralExpression(policy),
        `${file}: registerPerkTool's policy must be an inline object literal`,
      );
      const name = stringProperty(definition, "name");
      const kind = stringProperty(policy, "kind");
      assert.ok(name !== null && kind !== null, `${file}: a literal name and kind are required`);
      const identifiers = new Set<string>();
      const collect = (inner: ts.Node): void => {
        if (ts.isIdentifier(inner)) identifiers.add(inner.text);
        ts.forEachChild(inner, collect);
      };
      collect(definition);
      const entryPoints = TERMINATING_ENTRY_POINTS.filter((id) => identifiers.has(id));
      found.push({
        file,
        name,
        kind,
        terminates: /\bterminate:\s*true\b/.test(definition.getText(sf)) || entryPoints.length > 0,
        entryPoints,
      });
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return found;
}

function scanProduction(): ScannedRegistration[] {
  return productionFiles(PI_V1).flatMap((path) =>
    scanRegistrations(relative(PI_V1, path), readFileSync(path, "utf8")),
  );
}

/**
 * Object-literal keys no production file may set: the structured result fields and the query
 * `outputSchema` are derived by the seam (never hand-set), and perk has no tool-result renderers.
 */
const SEAM_DERIVED_KEYS = new Set([
  "outputSchema",
  "structuredContent",
  "isError",
  "renderResult",
  "renderCall",
]);

/** Every `<file>:<line> <key>` where an object literal sets one of SEAM_DERIVED_KEYS. */
function seamDerivedKeys(file: string, source: string): string[] {
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true);
  const found: string[] = [];
  const visit = (node: ts.Node): void => {
    if (
      ts.isObjectLiteralElementLike(node) &&
      ts.isObjectLiteralExpression(node.parent) &&
      node.name !== undefined &&
      SEAM_DERIVED_KEYS.has(node.name.getText(sf).replace(/^["']|["']$/g, ""))
    ) {
      const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
      found.push(`${file}:${line + 1} ${node.name.getText(sf)}`);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return found;
}

/** The bidirectional check: terminates(def) ⇔ kind === "terminal". */
function terminateMismatches(scanned: ScannedRegistration[]): string[] {
  return scanned
    .filter((r) => r.terminates !== (r.kind === "terminal"))
    .map((r) => `${r.file}: ${r.name} (kind ${r.kind}, terminates ${r.terminates})`);
}

// --- the census -------------------------------------------------------------------------------

test("exposure census: model-only iff terminal/interactive/orchestration/host; readOnlyHint iff not blocked", async () => {
  const h = await loadPerkSessionAt(scaffoldRepo());
  try {
    for (const name of perkToolNames()) {
      const policy = perkToolPolicy(name);
      const info = h.toolInfo(name);
      assert.ok(policy !== undefined && info !== null, name);
      assert.equal(
        info.exposure,
        MODEL_ONLY_KINDS.has(policy.kind) ? "model-only" : "direct",
        `${name} (${policy.kind})`,
      );
      assert.deepEqual(
        info.annotations,
        policy.gated === "blocked" ? undefined : { readOnlyHint: true },
        `${name} annotations`,
      );
    }
  } finally {
    h.dispose();
  }
});

test("terminal census pin: exactly the nine tools that can end the turn", () => {
  assert.deepEqual(
    sorted(perkToolNames().filter((name) => perkToolPolicy(name)?.kind === "terminal")),
    sorted(TERMINAL_TOOLS),
  );
});

test("per-registration terminate scan: terminates(definition) ⇔ kind terminal, over every registration", () => {
  const scanned = scanProduction();
  // The loadout host registers through `registerLoadoutHost`, never `registerPerkTool`.
  assert.deepEqual(
    sorted(scanned.map((r) => r.name)),
    sorted(perkToolNames().filter((name) => perkToolPolicy(name)?.kind !== "host")),
    "the scan sees every catalogued registration (and nothing else)",
  );
  for (const r of scanned) assert.equal(r.kind, perkToolPolicy(r.name)?.kind, r.name);
  assert.deepEqual(terminateMismatches(scanned), []);
  const referenced = new Set(
    scanned.filter((r) => r.kind === "terminal").flatMap((r) => r.entryPoints),
  );
  assert.deepEqual(
    TERMINATING_ENTRY_POINTS.filter((id) => !referenced.has(id)),
    [],
    "stale TERMINATING_ENTRY_POINTS entr(y/ies): no terminal registration references them",
  );
});

test("the scan discriminates within a mixed-kind module: a terminating plan_draft fails", () => {
  const source = readFileSync(join(PI_V1, "plan.ts"), "utf8");
  const anchor = 'name: "plan_draft",';
  assert.equal(source.split(anchor).length, 2, "one plan_draft registration");
  const mutated = source.replace(
    anchor,
    `${anchor}\n    renderResult: () => ({ terminate: true }),`,
  );
  const scanned = scanRegistrations("plan.ts", mutated);
  assert.ok(scanned.some((r) => r.name === "plan_save" && r.kind === "terminal"));
  assert.deepEqual(terminateMismatches(scanned), [
    "plan.ts: plan_draft (kind action, terminates true)",
  ]);
});

test("seam-derived census: no production file hand-sets outputSchema/structuredContent/isError or a tool-result renderer", () => {
  const found = productionFiles(PI_V1).flatMap((path) =>
    seamDerivedKeys(relative(PI_V1, path), readFileSync(path, "utf8")),
  );
  assert.deepEqual(found, []);
  // The scan is not vacuous: a hand-set key in a registration is caught.
  const source = readFileSync(join(PI_V1, "plan.ts"), "utf8");
  const anchor = 'name: "plan_draft",';
  const mutated = source.replace(anchor, `${anchor}\n    "isError": true, renderCall() {},`);
  assert.deepEqual(
    seamDerivedKeys("plan.ts", mutated).map((hit) => hit.replace(/:\d+ /, " ")),
    ['plan.ts "isError"', "plan.ts renderCall"],
  );
});

// --- the nested-runner probe --------------------------------------------------------------------

type Outcome = {
  isError: boolean;
  text: string;
  details: unknown;
  structuredContent: unknown;
  hasStructuredContent: boolean;
};

/** A test-only tool that calls `ctx.executeTool` for each target and records the outcomes. */
function nestedProbe(targets: readonly string[], outcomes: Map<string, Outcome>) {
  return (pi: ExtensionAPI) => {
    pi.registerTool({
      name: "nested_probe",
      label: "nested_probe",
      description: "test-only nested-call probe",
      parameters: { type: "object", additionalProperties: false, properties: {} } as never,
      async execute(_id, _params, _signal, _onUpdate, ctx) {
        for (const target of targets) {
          const outcome = await ctx.executeTool(target, {});
          const result = outcome.result as AgentToolResult<unknown>;
          const text = result.content.map((c) => (c.type === "text" ? c.text : "")).join("");
          outcomes.set(target, {
            isError: outcome.isError,
            text,
            details: result.details,
            structuredContent: result.structuredContent,
            hasStructuredContent: "structuredContent" in result,
          });
        }
        return { content: [{ type: "text", text: "probed" }], details: {} };
      },
    });
  };
}

for (const mode of ["on", "only"] as const) {
  test(`nested-runner probe (codemode ${mode}): model-only perk tools are declared but never callable`, async () => {
    const targets = ["submit", "plan_review", "run_scout_wave"];
    const outcomes = new Map<string, Outcome>();
    const reg = await fauxModelRuntime();
    const h = await loadPerkSessionAt(scaffoldRepo(), {
      headful: false,
      model: reg.getModel(),
      modelRuntime: reg.modelRuntime,
      extraExtensions: [createCodemodeExtension({ mode }), nestedProbe(targets, outcomes)],
    });
    try {
      h.session.setActiveToolsByName([...h.session.getActiveToolNames(), "codemode"]);
      assert.ok(h.session.getActiveToolNames().includes("codemode"));
      reg.setResponses([
        fauxAssistantMessage([fauxToolCall("nested_probe", {})], { stopReason: "toolUse" }),
        fauxAssistantMessage([fauxText("done")], { stopReason: "stop" }),
      ]);
      await h.session.prompt("probe the nested runner");
      for (const target of targets) {
        const outcome = outcomes.get(target);
        assert.ok(outcome !== undefined, `${target} was probed`);
        assert.equal(outcome.isError, true, target);
        assert.ok(outcome.text.includes(`Tool ${target} not found`), `${target}: ${outcome.text}`);
      }
      const active = h.session.getActiveToolNames();
      const callable = new Set(h.session.getCallableToolNames());
      const modelOnly = perkToolNames().filter((name) =>
        MODEL_ONLY_KINDS.has(perkToolPolicy(name)?.kind ?? ""),
      );
      for (const name of targets) assert.ok(active.includes(name), `${name} is active (declared)`);
      assert.deepEqual(
        modelOnly.filter((name) => callable.has(name)),
        [],
        "no model-only perk tool is callable",
      );
      assert.ok(callable.has("plan_draft"), "an action perk tool stays callable");
    } finally {
      h.dispose();
    }
  });
}

test("positive nested probe: a nested caller of the query tool receives structuredContent + isError", async () => {
  // No active objective and no plan-ref, so the query soft-fails deterministically before any
  // cold-door exec.
  const targets = ["objective_stack_status", "submit", "plan_review", "run_scout_wave"];
  const outcomes = new Map<string, Outcome>();
  const reg = await fauxModelRuntime();
  const h = await loadPerkSessionAt(scaffoldRepo(), {
    headful: false,
    model: reg.getModel(),
    modelRuntime: reg.modelRuntime,
    extraExtensions: [nestedProbe(targets, outcomes)],
  });
  try {
    reg.setResponses([
      fauxAssistantMessage([fauxToolCall("nested_probe", {})], { stopReason: "toolUse" }),
      fauxAssistantMessage([fauxText("done")], { stopReason: "stop" }),
    ]);
    await h.session.prompt("probe the query tool");
    const query = outcomes.get("objective_stack_status");
    assert.ok(query !== undefined, "the query tool was probed");
    assert.equal(query.isError, true);
    assert.ok(query.hasStructuredContent, "structuredContent reaches the nested caller");
    assert.deepEqual(query.structuredContent, query.details);
    const details = query.details as { ok?: unknown; error_type?: unknown };
    assert.equal(details.ok, false);
    assert.equal(details.error_type, "no_objective");
    // The model-only kinds still answer not-found.
    for (const target of targets.slice(1)) {
      const outcome = outcomes.get(target);
      assert.ok(outcome !== undefined, `${target} was probed`);
      assert.equal(outcome.isError, true, target);
      assert.ok(outcome.text.includes(`Tool ${target} not found`), `${target}: ${outcome.text}`);
    }
  } finally {
    h.dispose();
  }
});
