// The boundary explanation contract: frontend-owned fixed copy keyed by the closed
// BoundaryKind vocabulary (PRD §6 — selecting a boundary explains its owner; it never
// offers an editor). The graph carries no such prose, so this copy lives here rather
// than as a DTO field; the tree pane, center pane, and inspector all reuse it.

import type { BoundaryKind } from "./wire.ts";

export const BOUNDARY_INFO: Record<BoundaryKind, { owner: string; explanation: string }> = {
  "pi-system": {
    owner: "Pi (the host harness)",
    explanation:
      "Pi owns this layer's exact content. It is not stored in this repository, so there is nothing to view or edit here.",
  },
  "user-content": {
    owner: "The user",
    explanation:
      "Supplied by the human at session runtime. No canonical source exists in the repository.",
  },
  "runtime-state": {
    owner: "Runtime state",
    explanation:
      "Computed by the workflow at session runtime. No canonical prose source exists in the repository.",
  },
  "borrowed-prompt": {
    owner: "A borrowed package",
    explanation: "Owned by an external package and read-only by policy. It is not editable here.",
  },
};
