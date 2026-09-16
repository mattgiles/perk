// The OWNING suite for the `pi/v1/sessionName.ts` binding: the ports forward to the real Pi
// surfaces (`appendEntry("perk:workflow-state", …)` / `setSessionName` / `getSessionName`), the
// hint policy is forwarded to the core verbatim, and ONLY the `failed` outcome reaches `report()`
// (one warning naming the scope) — every other outcome is silent. Structural fakes for `pi`/`ctx`.

import assert from "node:assert/strict";
import { test } from "node:test";
import { WORKFLOW_STATE_TYPE } from "../../substrate/workflowState.ts";
import {
  refreshSessionNameV1,
  type SessionNameCtx,
  type SessionNamePi,
  titleHints,
} from "./sessionName.ts";

interface Fakes {
  pi: SessionNamePi;
  ctx: SessionNameCtx;
  entries: Array<{ type: string; customType?: string; data?: Record<string, unknown> }>;
  appends: Array<{ customType: string; data: unknown }>;
  setCalls: string[];
  notifies: Array<{ message: string; type?: string }>;
  name: string | undefined;
}

/** The branch is live: appends land on it so a `rebuild()` after an append sees the new field. */
function fakes(opts: {
  entries?: Array<Record<string, unknown>>;
  name?: string;
  failSet?: boolean;
  hasUI?: boolean;
}): Fakes {
  const entries = (opts.entries ?? []).map((data) => ({
    type: "custom",
    customType: WORKFLOW_STATE_TYPE,
    data,
  }));
  const f: Fakes = {
    entries,
    appends: [],
    setCalls: [],
    notifies: [],
    name: opts.name,
    pi: {
      appendEntry: (customType: string, data?: unknown) => {
        f.appends.push({ customType, data });
        entries.push({ type: "custom", customType, data: data as Record<string, unknown> });
      },
      getSessionName: () => f.name,
      setSessionName: (name: string) => {
        if (opts.failSet) throw new Error("boom");
        f.setCalls.push(name);
        f.name = name;
      },
    },
    ctx: {
      hasUI: opts.hasUI ?? true,
      sessionManager: { getBranch: () => entries },
      ui: { notify: (message, type) => f.notifies.push({ message, type }) },
    },
  };
  return f;
}

const CLAIM = {
  run_id: "01RID",
  pi_session_id: "s.jsonl",
  mode: "read-write",
  perk_version: "3.4.0",
  stage: "implement",
};

test("binding: the ports forward to appendEntry(perk:workflow-state), setSessionName, getSessionName", () => {
  const f = fakes({
    entries: [CLAIM, { active_plan_ref: { pr_id: "42", objective_id: "7" } }],
  });
  const outcome = refreshSessionNameV1(f.pi, f.ctx, {
    hints: { title: "Add retry", node: "1.1" },
    policy: "override",
  });
  assert.deepEqual(outcome, {
    status: "applied",
    name: "implement | plan #42 | objective #7 / 1.1 | Add retry",
  });
  assert.deepEqual(f.setCalls, ["implement | plan #42 | objective #7 / 1.1 | Add retry"]);
  assert.deepEqual(f.appends, [
    {
      customType: WORKFLOW_STATE_TYPE,
      data: { session_naming: { title: "Add retry", node: "1.1" } },
    },
    {
      customType: WORKFLOW_STATE_TYPE,
      data: { session_name: "implement | plan #42 | objective #7 / 1.1 | Add retry" },
    },
  ]);
  assert.deepEqual(f.notifies, []); // applied is silent
});

test("binding: the hint policy is forwarded — fill keeps a stored title the hint would override", () => {
  const f = fakes({ entries: [CLAIM, { session_naming: { title: "Learned" } }] });
  const outcome = refreshSessionNameV1(f.pi, f.ctx, { hints: { title: "Launch" }, policy: "fill" });
  assert.deepEqual(outcome, { status: "applied", name: "implement | Learned" });
  const overridden = fakes({ entries: [CLAIM, { session_naming: { title: "Learned" } }] });
  assert.deepEqual(
    refreshSessionNameV1(overridden.pi, overridden.ctx, {
      hints: { title: "Launch" },
      policy: "override",
    }),
    { status: "applied", name: "implement | Launch" },
  );
});

test("binding: unchanged / preserved / skipped are silent", () => {
  const unchanged = fakes({
    entries: [CLAIM, { active_plan_ref: { pr_id: "42" }, session_name: "implement | plan #42" }],
    name: "implement | plan #42",
  });
  assert.equal(
    refreshSessionNameV1(unchanged.pi, unchanged.ctx, { hints: {}, policy: "fill" }).status,
    "unchanged",
  );
  assert.deepEqual(unchanged.notifies, []);

  const preserved = fakes({ entries: [CLAIM, { active_plan_ref: { pr_id: "42" } }], name: "mine" });
  assert.equal(
    refreshSessionNameV1(preserved.pi, preserved.ctx, { hints: {}, policy: "fill" }).status,
    "preserved",
  );
  assert.deepEqual(preserved.notifies, []);
  assert.deepEqual(preserved.setCalls, []);

  const skipped = fakes({ entries: [{ run_id: "01MINT" }, { stage: "objective-refine" }] });
  assert.equal(
    refreshSessionNameV1(skipped.pi, skipped.ctx, { hints: {}, policy: "fill" }).status,
    "skipped",
  );
  assert.deepEqual(skipped.notifies, []);
  assert.deepEqual(skipped.appends, []);
});

test("titleHints: null → {} (a stored title survives under override); a title → { title }", () => {
  assert.deepEqual(titleHints(null), {});
  assert.deepEqual(titleHints("T"), { title: "T" });
});

test("binding: failed → exactly one warning notify naming the session-name scope", () => {
  const f = fakes({ entries: [CLAIM, { active_plan_ref: { pr_id: "42" } }], failSet: true });
  const outcome = refreshSessionNameV1(f.pi, f.ctx, { hints: {}, policy: "override" });
  assert.equal(outcome.status, "failed");
  assert.equal(f.notifies.length, 1);
  assert.equal(f.notifies[0]?.type, "warning");
  assert.match(f.notifies[0]?.message ?? "", /session name/);
  assert.match(f.notifies[0]?.message ?? "", /boom/);
  assert.deepEqual(f.appends, []);
});
