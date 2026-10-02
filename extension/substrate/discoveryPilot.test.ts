// The native-discovery pilot (contracts.md §8.40 "The discovery pilot"), driven through REAL
// bound AgentSessions (Mode A, fully offline) with Pi's real builtin `tool_search` loaded. A
// cohort session opts in with `defaultTools: ["+tool_search"]`; a nonparticipant session loads
// the SAME extension set without it, so the registries are identical and only activation differs.
// The nested-execution probe lives in its own file (`discoveryNested.test.ts`) so its fixture
// registration never enters this process's census.
//
// `PERK_PRINT_DISCOVERY_CENSUS=1` prints the census tables to stderr for transcription into the
// design record (`docs/design/native-discovery-pilot.md`).

import assert from "node:assert/strict";
import { before, test } from "node:test";
import {
  COHORT_SETTINGS,
  type PerkSession,
  type RecordedRequest,
  recordingRuntime,
  staged,
  toolSearch,
} from "../testing/harness.ts";
import { ensureToolCatalog } from "../testing/toolCatalog.ts";
import {
  isEligible,
  isPerkTool,
  perkToolNames,
  perkToolPolicy,
  REGISTRY_STAGE_IDS,
} from "./toolPolicy.ts";

before(ensureToolCatalog);

const PRINT = process.env.PERK_PRINT_DISCOVERY_CENSUS === "1";

/** The catalogued discovery-pilot family (`declared: "deferred"`), in catalog order. */
function family(): string[] {
  return perkToolNames().filter((name) => perkToolPolicy(name)?.declared === "deferred");
}

/** A census-capable session: the real `tool_search` registered; `cohort` activates it. */
async function pilotSession(
  stage: string,
  mode: "read-only" | "read-write",
  cohort: boolean,
  opts: Omit<Parameters<typeof staged>[2] & object, "model" | "modelRuntime"> = {},
): Promise<{ h: PerkSession; rt: Awaited<ReturnType<typeof recordingRuntime>> }> {
  const rt = await recordingRuntime();
  const h = await staged(stage, mode, {
    headful: false,
    ...opts,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    extraExtensions: [toolSearch(), ...(opts.extraExtensions ?? [])],
    ...(cohort ? { settings: { ...COHORT_SETTINGS, ...(opts.settings ?? {}) } } : {}),
  });
  return { h, rt };
}

/** The bytes one census request costs: its declared tools plus its system prompt. */
function requestBytes(request: RecordedRequest): number {
  return Buffer.byteLength(JSON.stringify(request.declared)) + Buffer.byteLength(request.prompt);
}

// --- 8. census and savings (criteria S1/S2) -------------------------------------------------------

/** The production `query`/`action` tools — the population a deferral can ever reach. */
const MEASURED_POPULATION = [
  "add_objective_node",
  "collect_draft_review_wave",
  "collect_review_wave",
  "gist_draft",
  "objective_draft",
  "objective_node",
  "objective_refinement_draft",
  "objective_stack_adopt",
  "objective_stack_land",
  "objective_stack_recover",
  "objective_stack_status",
  "plan_draft",
  "post_pr_review",
  "push_annotations",
  "reconcile_objective",
  "run_ci",
  "submit_pr_review",
];

/** The stage where no family member is eligible read-write: the fixed cost's measuring point. */
const FIXED_COST_STAGE = "gist-author";

test("census and savings (A): per-stage request bytes with and without the cohort; the fixed cost is tool_search's own declaration", async () => {
  const members = family();
  const rows: { stage: string; baseline: number; cohort: number; net: number }[] = [];
  let censusTools: string[] = [];
  let toolSearchOwn = -1;
  const toolRows: string[] = [];

  for (const stage of REGISTRY_STAGE_IDS) {
    const measured: Record<"baseline" | "cohort", RecordedRequest> = {} as never;
    for (const cohort of [false, true]) {
      const { h, rt } = await pilotSession(stage, "read-write", cohort);
      try {
        rt.census();
        await h.session.prompt("census");
        measured[cohort ? "cohort" : "baseline"] = rt.last();
        if (stage === FIXED_COST_STAGE && cohort) {
          // tool_search's exact delta: its declaration (plus the array separator) and its
          // snippet line (plus the line separator); it carries no guidelines.
          const declared = (rt.last().declared as { name: string }[]).find(
            (t) => t.name === "tool_search",
          );
          const snippet = h.registeredTool("tool_search")?.promptSnippet ?? "";
          assert.ok(declared !== undefined, "tool_search is declared in a cohort session");
          assert.deepEqual(h.registeredTool("tool_search")?.promptGuidelines ?? [], []);
          toolSearchOwn =
            Buffer.byteLength(JSON.stringify(declared)) +
            1 +
            Buffer.byteLength(`- tool_search: ${snippet}\n`);
        }
        if (stage === "implement" && !cohort) {
          censusTools = perkToolNames().filter((name) => {
            const policy = perkToolPolicy(name);
            return (
              (policy?.kind === "query" || policy?.kind === "action") &&
              h.registeredTool(name) !== null
            );
          });
          for (const name of censusTools) {
            const def = h.registeredTool(name);
            const policy = perkToolPolicy(name);
            assert.ok(def !== null && policy !== undefined);
            const request = Buffer.byteLength(
              JSON.stringify({ description: def.description, parameters: def.parameters }),
            );
            const prompt =
              Buffer.byteLength(def.promptSnippet ?? "") +
              Buffer.byteLength((def.promptGuidelines ?? []).join("\n"));
            const gated = typeof policy.gated === "object" ? "carve-out" : policy.gated;
            toolRows.push(
              `| \`${name}\` | ${policy.kind} | ${gated} | ${policy.stages.join(", ")} | ${request} | ${prompt} |`,
            );
          }
        }
      } finally {
        h.dispose();
      }
    }
    const { baseline, cohort } = measured;
    assert.ok(cohort.tools.includes("tool_search"), `${stage}: the cohort declares tool_search`);
    assert.ok(!baseline.tools.includes("tool_search"), `${stage}: a nonparticipant does not`);
    const eligibleMembers = members.filter((name) =>
      isEligible(name, undefined, stage, "read-write"),
    );
    for (const name of eligibleMembers) {
      assert.ok(baseline.tools.includes(name), `${stage}: a nonparticipant declares ${name}`);
      assert.ok(!cohort.tools.includes(name), `${stage}: the cohort defers ${name}`);
    }
    assert.deepEqual(
      cohort.tools.filter(isPerkTool).sort(),
      baseline.tools.filter((name) => isPerkTool(name) && !eligibleMembers.includes(name)).sort(),
      `${stage}: the cohort's perk declarations are the nonparticipant's minus the deferred family`,
    );
    const b = requestBytes(baseline);
    const c = requestBytes(cohort);
    rows.push({ stage, baseline: b, cohort: c, net: b - c });
  }

  assert.deepEqual([...censusTools].sort(), MEASURED_POPULATION, "the measured population");
  const fixedCost = -(rows.find((r) => r.stage === FIXED_COST_STAGE)?.net ?? Number.NaN);
  assert.equal(fixedCost, toolSearchOwn, "the fixed cost is tool_search's own bytes");

  if (PRINT) {
    const out = [
      "",
      "Per-tool census (implement session; request = JSON {description, parameters}; prompt = snippet + guidelines):",
      "",
      "| tool | kind | gated | stages | request bytes | prompt bytes |",
      "|---|---|---|---|---|---|",
      ...toolRows,
      "",
      `Per-stage census request bytes (declared + system prompt), read-write; fixed cost = ${fixedCost}:`,
      "",
      "| stage | nonparticipant | cohort | net |",
      "|---|---|---|---|",
      ...rows.map((r) => `| ${r.stage} | ${r.baseline} | ${r.cohort} | ${r.net} |`),
      "",
    ];
    process.stderr.write(`${out.join("\n")}\n`);
  }

  if (members.length === 0) {
    // The baseline: identical perk declarations; the cohort costs exactly tool_search everywhere.
    for (const r of rows) assert.equal(r.net, -fixedCost, `${r.stage}: net is -fixedCost`);
    return;
  }
  assert.ok(fixedCost <= 1024, `S2: the fixed cost ${fixedCost} ≤ 1024`);
  for (const r of rows) {
    const eligible = members.some((name) => isEligible(name, undefined, r.stage, "read-write"));
    if (eligible) assert.ok(r.net >= 4096, `S1: ${r.stage} net ${r.net} ≥ 4096`);
    else assert.equal(r.net, -fixedCost, `${r.stage}: no member eligible, net is -fixedCost`);
  }
});
