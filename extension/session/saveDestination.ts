// The save-destination fence's capture: WHERE an approved draft would be written, reduced to
// per-component digests so a review can tell "the destination moved" from "unrelated config
// noise" without ever retaining or reporting a raw routing value (contracts.md §8.23).
//
// Exactly three inputs route a save — the committed `[issues] backend`/`team` (the Python
// resolver's whole vocabulary), the git `remote.*.url`/`remote.*.gh-resolved` entries `gh`
// resolves the repo from (GitHub backend only; Linear never reads remotes), and the objective
// node claim a plan save links to. Everything else (`branch.*`, `user.*`, `[workflow] base`,
// credentials, the process environment, the run handoff) is deliberately NOT a component: none
// of it decides where the artifact lands, so none of it may strand an approval.
import { resolveIssueDestination } from "../substrate/config.ts";
import { remoteConfig } from "../substrate/git.ts";
import { digestSessionData } from "../substrate/sessionData.ts";

export const DESTINATION_COMPONENTS = ["issues", "remotes", "node_claim"] as const;
export type DestinationComponent = (typeof DESTINATION_COMPONENTS)[number];

/** Component name → `digestSessionData(value)`. No aggregate digest; no raw value retained. */
export type SaveDestination = Readonly<Partial<Record<DestinationComponent, string>>>;

/** The seams the capture shells through — injectable so tests can prove the Linear arm never forks git. */
export interface SaveDestinationPorts {
  issues(cwd: string): { backend: string | null; team: string | null };
  remotes(cwd: string): string | null;
}

const PRODUCTION_PORTS: SaveDestinationPorts = {
  issues: resolveIssueDestination,
  remotes: remoteConfig,
};

/**
 * Capture the save destination at `cwd` for a review that would link `nodeClaim`. `issues` and
 * `node_claim` are always present; `remotes` only when the resolved backend is GitHub (or
 * unset — the fail-safe default): Linear saves never consult git remotes, so no git subprocess
 * runs there. Returns `null` when the destination cannot be verified (the GitHub arm's remotes
 * read failed) — callers must treat that as "unverifiable", never as "unchanged".
 */
export function captureSaveDestination(
  cwd: string,
  nodeClaim: { objective: string; node: string } | null,
  ports: SaveDestinationPorts = PRODUCTION_PORTS,
): SaveDestination | null {
  const issues = ports.issues(cwd);
  const destination: Partial<Record<DestinationComponent, string>> = {
    issues: digestSessionData(JSON.stringify({ backend: issues.backend, team: issues.team })),
    node_claim: digestSessionData(
      JSON.stringify(
        nodeClaim === null ? null : { objective: nodeClaim.objective, node: nodeClaim.node },
      ),
    ),
  };
  if (issues.backend === null || issues.backend === "github") {
    const remotes = ports.remotes(cwd);
    if (remotes === null) return null;
    destination.remotes = digestSessionData(remotes);
  }
  return destination;
}

/**
 * The components whose digests differ between the reviewed and current captures, in
 * `DESTINATION_COMPONENTS` order; a key present on one side only counts as changed. "Changed at
 * all" is `changed.length > 0`.
 */
export function changedDestinationComponents(
  reviewed: SaveDestination,
  current: SaveDestination,
): DestinationComponent[] {
  return DESTINATION_COMPONENTS.filter((component) => reviewed[component] !== current[component]);
}
