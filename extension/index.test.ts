// Extension-factory wiring tests. The live harness binds extension/index.ts through Pi's real
// loader and runner, so these assertions cover registration rather than only renderer helpers.

import assert from "node:assert/strict";
import { test } from "node:test";
import { REPORT_DETAIL_TYPE } from "./surfaces/surfaces.ts";
import { loadPerkSession, scaffoldRepo } from "./testing/harness.ts";

test("the perk factory registers the report-detail renderer", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.deepEqual(
      h.renderAppendedEntry(REPORT_DETAIL_TYPE, {
        text: "perk: submit — failed\ncomplete detail",
        severity: "error",
      }),
      ["<error>perk: submit — failed</>", "<dim>complete detail</>"],
    );
  } finally {
    h.dispose();
  }
});
