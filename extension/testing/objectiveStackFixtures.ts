// The two stack-local fixtures shared by the stacked-delivery suites (the mutating family in
// doors/objectiveStack.test.ts and the status door in pi/v1/delivery/stackStatus.test.ts).
// `fakePerk`/`plantSession` stay in testing/harness.ts and `writePlanRef` in substrate/cache.ts —
// import those from their real homes.

import type { PlanRef } from "../substrate/cache.ts";

/** A plan-ref carrying an objective linkage (the inference precedence's last tier). */
export const PLAN_REF: PlanRef = {
  provider: "github",
  pr_id: "1457",
  url: "https://github.com/o/r/issues/1457",
  labels: [],
  objective_id: "137",
};

/** A minimal success envelope every stack worker fake can return (renders leniently). */
export const OK_ENVELOPE = JSON.stringify({
  success: true,
  objective: { id: "7", url: "https://x/7", redirected_from: null },
  no_op: false,
  declined: false,
  affected: [],
  operations: [],
});
