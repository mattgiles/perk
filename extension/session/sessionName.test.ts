// The pure OWNING suite for `session/sessionName.ts`: the control-character strip, the byte-exact
// composition matrix, title normalization (code-point cap, no split surrogate), the
// `plan.derive_title` twin, the origin rule (cold-launch provenance only), the structural hint
// decode, and the refresh's ownership / hint-policy / decode-then-rank behaviors — over ONE
// recording fake of the `SessionNamePorts` slice.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { PlanRef } from "../substrate/cache.ts";
import {
  type BranchEntry,
  WORKFLOW_STATE_TYPE,
  type WorkflowState,
} from "../substrate/workflowState.ts";
import {
  composeSessionName,
  decodeNamingHints,
  deriveTitle,
  type HintPolicy,
  type NamingHints,
  normalizeTitle,
  originStage,
  refreshSessionName,
  type SessionNamePorts,
  stripControls,
} from "./sessionName.ts";

const ESC = "\u001b";
const BEL = "\u0007";
const CONTROL_PROBE =
  // biome-ignore lint/suspicious/noControlCharactersInRegex: the assertion is about them
  /[\u0000-\u001f\u007f-\u009f\u2028\u2029\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/;

// --- fixtures ------------------------------------------------------------------------------------

function entry(data: Record<string, unknown>): BranchEntry {
  return { type: "custom", customType: WORKFLOW_STATE_TYPE, data };
}

/** The cold claim's combined entry — the ONE shape carrying both `run_id` and `stage`. */
function claimEntry(stage: string, runId = "01RID"): BranchEntry {
  return entry({
    run_id: runId,
    pi_session_id: "s.jsonl",
    mode: "read-write",
    perk_version: "3.4.0",
    stage,
  });
}

function ref(prId: string, extra: Partial<PlanRef> = {}): PlanRef {
  return {
    provider: "github",
    pr_id: prId,
    url: `https://github.com/o/r/issues/${prId}`,
    labels: ["perk:plan"],
    objective_id: null,
    ...extra,
  };
}

interface FakePorts extends SessionNamePorts {
  appends: WorkflowState[];
  setCalls: string[];
  current: string | undefined;
}

/**
 * A recording fake: `branch` is the given entries; `rebuild` returns `state` (the unvalidated
 * rebuilt shape — tests plant malformed values through `as`); `setSessionName` updates `current`
 * unless `failSet`; `append` records unless `failAppendWhen` matches the payload.
 */
function fakePorts(opts: {
  branch: BranchEntry[];
  state?: Record<string, unknown>;
  current?: string;
  failSet?: boolean;
  failAppendWhen?: (data: WorkflowState) => boolean;
}): FakePorts {
  const ports: FakePorts = {
    appends: [],
    setCalls: [],
    current: opts.current,
    branch: () => opts.branch,
    rebuild: () => (opts.state ?? {}) as WorkflowState,
    append: (data) => {
      if (opts.failAppendWhen?.(data)) throw new Error("append refused");
      ports.appends.push(data);
    },
    getSessionName: () => ports.current,
    setSessionName: (name) => {
      if (opts.failSet) throw new Error("boom");
      ports.setCalls.push(name);
      ports.current = name;
    },
  };
  return ports;
}

function refresh(
  ports: SessionNamePorts,
  hints: NamingHints = {},
  policy: HintPolicy = "override",
) {
  return refreshSessionName(ports, { hints, policy });
}

// --- stripControls -------------------------------------------------------------------------------

test("stripControls: removes ESC + OSC + BEL leaving the plain payload", () => {
  assert.equal(stripControls(`${ESC}]0;evil${BEL}`), "]0;evil");
});

test("stripControls: removes C0/C1/DEL, bidi, format, separator and BOM characters", () => {
  const cases: Array<[string, string]> = [
    [BEL, ""],
    [`${ESC}[31m`, "[31m"],
    [ESC, ""],
    ["\u007f", ""],
    ["\u0085", ""],
    ["\u202e", ""],
    ["\u200f", ""],
    ["\u2066", ""],
    ["\u2028", ""],
    ["\u2060", ""],
    ["\ufeff", ""],
    ["a\tb", "ab"],
  ];
  for (const [input, expected] of cases) {
    assert.equal(stripControls(input), expected, JSON.stringify(input));
  }
});

test("stripControls: leaves plain text, spaces, emoji and CJK untouched", () => {
  const text = "Add retry 🚀 再试 — ok";
  assert.equal(stripControls(text), text);
});

// --- composeSessionName --------------------------------------------------------------------------

test("composeSessionName: byte-exact matrix", () => {
  assert.equal(
    composeSessionName({
      purpose: "implement",
      planId: "42",
      objectiveId: "7",
      nodeId: "1.1",
      title: "Add retry",
    }),
    "implement | plan #42 | objective #7 / 1.1 | Add retry",
  );
  assert.equal(
    composeSessionName({
      purpose: "objective-plan",
      planId: null,
      objectiveId: "2457",
      nodeId: "2.1",
      title: "Perk-owned session names",
    }),
    "objective-plan | objective #2457 / 2.1 | Perk-owned session names",
  );
  assert.equal(
    composeSessionName({
      purpose: "implement",
      planId: "42",
      objectiveId: null,
      nodeId: null,
      title: null,
    }),
    "implement | plan #42",
  );
  assert.equal(
    composeSessionName({
      purpose: "plan",
      planId: null,
      objectiveId: null,
      nodeId: null,
      title: "Add retry",
    }),
    "plan | Add retry",
  );
  assert.equal(
    composeSessionName({
      purpose: "learn",
      planId: null,
      objectiveId: null,
      nodeId: null,
      title: null,
    }),
    "learn",
  );
});

test("composeSessionName: a node renders only beside an objective; blank ids are omitted", () => {
  assert.equal(
    composeSessionName({
      purpose: "implement",
      planId: "42",
      objectiveId: null,
      nodeId: "1.1",
      title: null,
    }),
    "implement | plan #42",
  );
  assert.equal(
    composeSessionName({
      purpose: "implement",
      planId: "  ",
      objectiveId: "",
      nodeId: " ",
      title: "  ",
    }),
    "implement",
  );
});

test("composeSessionName: ids and titles carrying an OSC sequence compose control-free", () => {
  const evil = `${ESC}]0;x${BEL}`;
  const name = composeSessionName({
    purpose: `implement${evil}`,
    planId: `42${evil}`,
    objectiveId: `7${evil}`,
    nodeId: `1.1${evil}`,
    title: `Add${evil} retry`,
  });
  assert.equal(name, "implement]0;x | plan #42]0;x | objective #7]0;x / 1.1]0;x | Add]0;x retry");
  assert.doesNotMatch(name, CONTROL_PROBE);
});

// --- normalizeTitle ------------------------------------------------------------------------------

test("normalizeTitle: trims, collapses whitespace, strips a leading `#` run", () => {
  assert.equal(normalizeTitle("  Add   retry\n\tnow  "), "Add retry now");
  assert.equal(normalizeTitle("## Title"), "Title");
  assert.equal(normalizeTitle("#Title"), "Title");
});

test("normalizeTitle: caps at 80 code points (79 + …) without splitting a surrogate pair", () => {
  const long = "x".repeat(100);
  const capped = normalizeTitle(long);
  assert.ok(capped !== null);
  assert.equal(Array.from(capped).length, 80);
  assert.equal(capped, `${"x".repeat(79)}…`);

  const astral = "😀".repeat(100);
  const cappedAstral = normalizeTitle(astral);
  assert.ok(cappedAstral !== null);
  assert.equal(Array.from(cappedAstral).length, 80);
  assert.equal(cappedAstral, `${"😀".repeat(79)}…`);
  // No lone surrogate anywhere in the result.
  assert.doesNotMatch(
    cappedAstral,
    /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/,
  );
});

test("normalizeTitle: control-laden input is sanitized before the cap", () => {
  const laden = `${ESC}`.repeat(50) + "y".repeat(50);
  assert.equal(normalizeTitle(laden), "y".repeat(50)); // controls do not count toward the cap
});

test("normalizeTitle: blank / null / undefined → null", () => {
  assert.equal(normalizeTitle("   "), null);
  assert.equal(normalizeTitle("###"), null);
  assert.equal(normalizeTitle(null), null);
  assert.equal(normalizeTitle(undefined), null);
});

// --- deriveTitle (the plan.derive_title twin) ----------------------------------------------------

test("deriveTitle: first real H1, else null", () => {
  assert.equal(deriveTitle("# Real Title\n\nbody"), "Real Title");
  assert.equal(deriveTitle("no heading here"), null);
});

test("deriveTitle: a `#` inside a code fence is not a heading", () => {
  const md =
    'Here is the plan.\n\n```toml\n# Add only if you want format-on-commit too:\nid = "ruff-check"\n```\n';
  assert.equal(deriveTitle(md), null);
});

test("deriveTitle: prefers the real H1 over a fenced `#`", () => {
  assert.equal(deriveTitle("# Add prek hook\n\n```sh\n# not a title\n```\n"), "Add prek hook");
  assert.equal(deriveTitle("```sh\n# not a title\n```\n# After the fence\n"), "After the fence");
});

test("deriveTitle: four-space indent is code; `~~~` fences toggle like backticks", () => {
  assert.equal(deriveTitle("    # four-space code, not a heading\n"), null);
  assert.equal(deriveTitle("   # three spaces is a heading\n"), "three spaces is a heading");
  assert.equal(deriveTitle("~~~\n# fenced\n~~~\n# Real\n"), "Real");
  assert.equal(deriveTitle("```\n~~~\n# still fenced by the backticks\n```\n"), null);
});

// --- originStage ---------------------------------------------------------------------------------

test("originStage: the cold claim entry names the stage; first wins over later stage appends", () => {
  assert.equal(originStage([claimEntry("implement")]), "implement");
  assert.equal(
    originStage([claimEntry("implement"), entry({ stage: "objective-refine" })]),
    "implement",
  );
});

test("originStage: a stage-only append after a mint or adopt entry is not an origin", () => {
  assert.equal(
    originStage([
      entry({ run_id: "01MINT", pi_session_id: "s.jsonl", perk_version: "3.4.0" }),
      entry({ stage: "objective-refine" }),
    ]),
    null,
  );
  assert.equal(
    originStage([
      entry({
        run_id: "01RID",
        pi_session_id: "c.jsonl",
        predecessor: "01PARENT",
        mode: "read-write",
      }),
      entry({ stage: "objective-refine" }),
    ]),
    null,
  );
});

test("originStage: non-perk entries and blank fields are ignored; empty → null", () => {
  assert.equal(originStage([]), null);
  assert.equal(
    originStage([
      { type: "message" },
      { type: "custom", customType: "other", data: { run_id: "x", stage: "implement" } },
      entry({ run_id: "", stage: "implement" }),
      entry({ run_id: "01RID", stage: "  " }),
    ]),
    null,
  );
});

// --- decodeNamingHints ---------------------------------------------------------------------------

test("decodeNamingHints: keeps non-blank string fields (trimmed, controls stripped) only", () => {
  assert.deepEqual(
    decodeNamingHints({ title: `  Add${BEL} retry `, node: "1.1", extra: "ignored" }),
    { title: "Add retry", node: "1.1" },
  );
  assert.deepEqual(decodeNamingHints({ title: "   ", node: 11 }), {});
  assert.deepEqual(decodeNamingHints({ title: undefined }), {});
  assert.deepEqual(decodeNamingHints(null), {});
  assert.deepEqual(decodeNamingHints("title"), {});
  assert.deepEqual(decodeNamingHints(["title"]), {});
});

// --- refreshSessionName --------------------------------------------------------------------------

test("refresh: unnamed + origin → applied with one session_name append (no hints → no naming append)", () => {
  const ports = fakePorts({
    branch: [claimEntry("implement")],
    state: { active_plan_ref: ref("42") },
  });
  const outcome = refresh(ports);
  assert.deepEqual(outcome, { status: "applied", name: "implement | plan #42" });
  assert.deepEqual(ports.setCalls, ["implement | plan #42"]);
  assert.deepEqual(ports.appends, [{ session_name: "implement | plan #42" }]);
});

test("refresh: non-empty hints persist as session_naming before the name append", () => {
  const ports = fakePorts({
    branch: [claimEntry("implement")],
    state: { active_plan_ref: ref("42", { objective_id: "7" }) },
  });
  const outcome = refresh(ports, { title: "Add retry", node: "1.1" });
  assert.deepEqual(outcome, {
    status: "applied",
    name: "implement | plan #42 | objective #7 / 1.1 | Add retry",
  });
  assert.deepEqual(ports.appends, [
    { session_naming: { title: "Add retry", node: "1.1" } },
    { session_name: "implement | plan #42 | objective #7 / 1.1 | Add retry" },
  ]);
});

test("refresh: owned + changed identifiers → applied; owned + equal → unchanged", () => {
  const changed = fakePorts({
    branch: [claimEntry("implement")],
    state: { active_plan_ref: ref("43"), session_name: "implement | plan #42" },
    current: "implement | plan #42",
  });
  assert.deepEqual(refresh(changed), { status: "applied", name: "implement | plan #43" });
  assert.deepEqual(changed.setCalls, ["implement | plan #43"]);

  const equal = fakePorts({
    branch: [claimEntry("implement")],
    state: { active_plan_ref: ref("42"), session_name: "implement | plan #42" },
    current: "implement | plan #42",
  });
  assert.deepEqual(refresh(equal), { status: "unchanged", name: "implement | plan #42" });
  assert.deepEqual(equal.setCalls, []);
  assert.deepEqual(equal.appends, []);
});

test("refresh: a foreign current name is preserved — no write, hints still persisted", () => {
  const ports = fakePorts({
    branch: [claimEntry("implement")],
    state: { active_plan_ref: ref("42"), session_name: "implement | plan #41" },
    current: "mine",
  });
  assert.deepEqual(refresh(ports, { title: "Learned" }), { status: "preserved", current: "mine" });
  assert.deepEqual(ports.setCalls, []);
  assert.deepEqual(ports.appends, [{ session_naming: { title: "Learned" } }]);
});

test("refresh: no origin → skipped with zero appends and zero writes", () => {
  const ports = fakePorts({
    branch: [entry({ run_id: "01MINT" }), entry({ stage: "objective-refine" })],
    state: { active_plan_ref: ref("42") },
  });
  assert.deepEqual(refresh(ports, { title: "Ignored" }), {
    status: "skipped",
    reason: "no-origin",
  });
  assert.deepEqual(ports.setCalls, []);
  assert.deepEqual(ports.appends, []);
});

test("refresh hint policy: override lets a hint win; fill keeps the stored value and appends nothing", () => {
  const stored = { session_naming: { title: "Old" } };
  const override = fakePorts({ branch: [claimEntry("plan")], state: stored });
  assert.deepEqual(refresh(override, { title: "New" }, "override"), {
    status: "applied",
    name: "plan | New",
  });
  assert.deepEqual(override.appends[0], { session_naming: { title: "New" } });

  const fill = fakePorts({ branch: [claimEntry("plan")], state: stored });
  assert.deepEqual(refresh(fill, { title: "New" }, "fill"), {
    status: "applied",
    name: "plan | Old",
  });
  assert.deepEqual(fill.appends, [{ session_name: "plan | Old" }]); // no session_naming append
});

test("refresh hint policy: fill applies a hint where nothing is stored", () => {
  const ports = fakePorts({ branch: [claimEntry("plan")], state: {} });
  assert.deepEqual(refresh(ports, { title: "Launch" }, "fill"), {
    status: "applied",
    name: "plan | Launch",
  });
  assert.deepEqual(ports.appends, [
    { session_naming: { title: "Launch" } },
    { session_name: "plan | Launch" },
  ]);
});

test("refresh hint policy: undefined / blank hint fields never clobber; equal hints append nothing", () => {
  for (const hints of [{ title: undefined }, { title: "  " }, { title: "Old" }]) {
    const ports = fakePorts({
      branch: [claimEntry("plan")],
      state: { session_naming: { title: "Old" }, session_name: "plan | Old" },
      current: "plan | Old",
    });
    assert.deepEqual(refresh(ports, hints, "override"), {
      status: "unchanged",
      name: "plan | Old",
    });
    assert.deepEqual(ports.appends, [], JSON.stringify(hints));
  }
});

test("refresh decode-then-rank: a half-valid claim never suppresses the ref objective nor lends its node", () => {
  const ports = fakePorts({
    branch: [claimEntry("implement")],
    state: {
      objective_node_claim: { objective: "", node: "1.1" },
      active_plan_ref: ref("42", { objective_id: "7" }),
    },
  });
  assert.deepEqual(refresh(ports), {
    status: "applied",
    name: "implement | plan #42 | objective #7",
  });

  const hinted = fakePorts({
    branch: [claimEntry("implement")],
    state: {
      objective_node_claim: { objective: "", node: "1.1" },
      active_plan_ref: ref("42", { objective_id: "7" }),
    },
  });
  assert.deepEqual(refresh(hinted, { node: "2.2" }), {
    status: "applied",
    name: "implement | plan #42 | objective #7 / 2.2", // the node comes from merged.node only
  });
});

test("refresh decode-then-rank: malformed values fall through to valid lower tiers or are omitted", () => {
  const nonStringClaim = fakePorts({
    branch: [claimEntry("implement")],
    state: {
      objective_node_claim: { objective: 7, node: "1.1" },
      active_plan_ref: ref("42", { objective_id: "9" }),
    },
  });
  assert.deepEqual(refresh(nonStringClaim), {
    status: "applied",
    name: "implement | plan #42 | objective #9",
  });

  const blankPlan = fakePorts({
    branch: [claimEntry("implement")],
    state: { active_plan_ref: ref(""), active_objective: "5" },
  });
  assert.deepEqual(refresh(blankPlan), { status: "applied", name: "implement | objective #5" });

  const nonStringObjective = fakePorts({
    branch: [claimEntry("implement")],
    state: { active_objective: 42 },
  });
  assert.deepEqual(refresh(nonStringObjective), { status: "applied", name: "implement" });
});

test("refresh: a valid claim outranks the ref objective and pairs its own node", () => {
  const ports = fakePorts({
    branch: [claimEntry("objective-plan")],
    state: {
      objective_node_claim: { objective: "2457", node: "2.1" },
      active_plan_ref: ref("42", { objective_id: "7" }),
      active_objective: "5",
    },
  });
  assert.deepEqual(refresh(ports, { node: "9.9" }), {
    status: "applied",
    name: "objective-plan | plan #42 | objective #2457 / 2.1",
  });
});

test("refresh: a throwing setSessionName is failed with no session_name append", () => {
  const ports = fakePorts({
    branch: [claimEntry("implement")],
    state: { active_plan_ref: ref("42") },
    failSet: true,
  });
  const outcome = refresh(ports);
  assert.equal(outcome.status, "failed");
  assert.match((outcome as { problem: string }).problem, /boom/);
  assert.deepEqual(ports.appends, []);
});

test("refresh: a failed ownership append after a successful write is failed, then preserved next time", () => {
  const ports = fakePorts({
    branch: [claimEntry("implement")],
    state: { active_plan_ref: ref("42") },
    failAppendWhen: (data) => data.session_name !== undefined,
  });
  const first = refresh(ports);
  assert.equal(first.status, "failed");
  assert.equal(ports.current, "implement | plan #42"); // the name stayed in place
  // The next refresh sees the current name without an ownership record → preserved.
  const second = refresh(ports);
  assert.deepEqual(second, { status: "preserved", current: "implement | plan #42" });
});

test("refresh: same-text collision — a human /name equal to perk's record is treated as owned", () => {
  const ports = fakePorts({
    branch: [claimEntry("implement")],
    state: { active_plan_ref: ref("43"), session_name: "implement | plan #42" },
    current: "implement | plan #42", // a /name that repeats perk's record byte-for-byte
  });
  assert.deepEqual(refresh(ports), { status: "applied", name: "implement | plan #43" });
});
