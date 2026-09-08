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
//
// The `issues` component digests the two keys only while the extension's TOML subset reader
// provably reads them as Python's `tomllib` does; a spelling it cannot vouch for (dotted keys,
// an inline table, escapes …) widens the component to the whole committed document, so a
// routing edit the subset reader cannot see still moves the digest. Widening over-fences
// (an unrelated edit to that file then reads as "issues changed"); it never under-fences.
import { type IssueRouting, resolveIssueRouting } from "../substrate/config.ts";
import { remoteConfig } from "../substrate/git.ts";
import { digestSessionData } from "../substrate/sessionData.ts";

export const DESTINATION_COMPONENTS = ["issues", "remotes", "node_claim"] as const;
export type DestinationComponent = (typeof DESTINATION_COMPONENTS)[number];

/** Component name → `digestSessionData(value)`. No aggregate digest; no raw value retained. */
export type SaveDestination = Readonly<Partial<Record<DestinationComponent, string>>>;

/** The seams the capture shells through — injectable so tests can prove the Linear arm never forks git. */
export interface SaveDestinationPorts {
  issues(cwd: string): IssueRouting;
  remotes(cwd: string): string | null;
}

const PRODUCTION_PORTS: SaveDestinationPorts = {
  issues: resolveIssueRouting,
  remotes: remoteConfig,
};

/** The `issues` component's digest input: the proven keys, or the unproven document verbatim. */
function issuesComponent(issues: IssueRouting): string {
  return issues.kind === "keys"
    ? JSON.stringify({ backend: issues.backend, team: issues.team })
    : JSON.stringify({ document: issues.text });
}

/**
 * Capture the save destination at `cwd` for a review that would link `nodeClaim`. `issues` and
 * `node_claim` are always present; `remotes` whenever the read backend is anything but exactly
 * `"linear"` — GitHub, unset (the fail-safe default), unknown, or a value the reader cannot
 * vouch for (an escaped `"\u0067ithub"` reads verbatim here while Python saves to GitHub):
 * only a Linear save never consults git remotes, so only there does no git subprocess run. (The
 * only way the subset reader reads `"linear"` is a bare `[issues]` table `tomllib` reads the
 * same way.) Returns `null` when the destination cannot be verified (the GitHub arm's remotes
 * read failed) — callers must treat that as "unverifiable", never as "unchanged".
 */
export function captureSaveDestination(
  cwd: string,
  nodeClaim: { objective: string; node: string } | null,
  ports: SaveDestinationPorts = PRODUCTION_PORTS,
): SaveDestination | null {
  const issues = ports.issues(cwd);
  const destination: Partial<Record<DestinationComponent, string>> = {
    issues: digestSessionData(issuesComponent(issues)),
    node_claim: digestSessionData(
      JSON.stringify(
        nodeClaim === null ? null : { objective: nodeClaim.objective, node: nodeClaim.node },
      ),
    ),
  };
  if (issues.backend !== "linear") {
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
