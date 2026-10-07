// The SDK-boundary admission decision (contracts.md §8.76(f)) — pure: no I/O, no SDK.
//
// Both thin entries (the extension's `index.ts`, the worker's `workerMain.ts`) admit the Pi SDK
// they actually loaded against the shared host floor BEFORE any SDK-bearing module links. This is
// the decision they share; the observation (the SDK's public `VERSION`) is read by
// `hostSdkVersion.ts` and the floor by `hostFloor.ts`, so this module stays importable in any
// process and testable without one.
//
// Independence: the decision reads ONLY its two arguments — never `process.env` (no PATH `pi`, no
// `PERK_CLI_VERSION`), never a file. The PATH CLI (the Python launch admission), the extension's
// host SDK and the worker's SDK are three independent observations against one minimum; equality
// between them is never required.
//
// Vocabulary mirrors perk/substrate/pi_host.py: the same three outcomes, the same refusal error
// codes, the same 80-character unverifiable preview, the same install command.

import { formatSemver, parseSemver, satisfiesFloor } from "./semver.ts";

export const HOST_SDK_PACKAGE = "@earendil-works/pi-coding-agent";
export const PI_INSTALL_COMMAND = `npm install -g ${HOST_SDK_PACKAGE}`;

const DETAIL_PREVIEW_CHARS = 80;

export type HostSdkOutcome = "admitted" | "unsupported" | "unverifiable";
export type HostSdkErrorType = "pi_version_unsupported" | "pi_version_unverifiable";

/**
 * One admission decision about the loaded host SDK.
 *
 * `observed` is the parsed version's canonical text (build metadata dropped; `null` when
 * unverifiable); `required` is the floor's canonical text; `detail` is the unverifiable reason
 * (`""` otherwise).
 */
export interface HostSdkAdmission {
  outcome: HostSdkOutcome;
  observed: string | null;
  required: string;
  detail: string;
}

/**
 * Decide admission of the observed SDK `VERSION` against the floor's `required` text (pure).
 *
 * Throws when `required` is not a version — a corrupt perk bundle, not a host verdict.
 */
export function admitHostSdk(observed: unknown, required: string): HostSdkAdmission {
  const floor = parseSemver(required);
  if (floor === null) {
    throw new Error(`perk: host floor pi.min_version is not a version: ${required}`);
  }
  const requiredText = formatSemver(floor);
  if (typeof observed !== "string") {
    return {
      outcome: "unverifiable",
      observed: null,
      required: requiredText,
      detail: `${HOST_SDK_PACKAGE} exports no VERSION string (got ${typeof observed})`,
    };
  }
  const parsed = parseSemver(observed);
  if (parsed === null) {
    const preview = observed.trim().slice(0, DETAIL_PREVIEW_CHARS);
    return {
      outcome: "unverifiable",
      observed: null,
      required: requiredText,
      detail: `VERSION is ${JSON.stringify(preview)} instead of a version`,
    };
  }
  return {
    outcome: satisfiesFloor(parsed, floor) ? "admitted" : "unsupported",
    observed: formatSemver(parsed),
    required: requiredText,
    detail: "",
  };
}

/** The typed error code for a non-admitted SDK (only meaningful when not `admitted`). */
export function hostSdkErrorType(admission: HostSdkAdmission): HostSdkErrorType {
  return admission.outcome === "unsupported" ? "pi_version_unsupported" : "pi_version_unverifiable";
}

const WORKER_REPAIR =
  "npm ci in this checkout (self-repo), or re-run the remote setup's worker-deps install (consumer).";

/** The human refusal text for a non-admitted SDK, worded for the entry that refuses. */
export function formatHostSdkRefusal(
  admission: HostSdkAdmission,
  surface: "extension" | "worker",
): string {
  const { observed, required, detail } = admission;
  if (surface === "extension") {
    if (admission.outcome === "unsupported") {
      return (
        `perk requires Pi >= ${required}; the Pi running this session is ${observed} ` +
        `(${HOST_SDK_PACKAGE} VERSION). Upgrade it: ${PI_INSTALL_COMMAND} — perk init and ` +
        "perk doctor report the same requirement."
      );
    }
    return (
      `perk requires Pi >= ${required} and could not verify this Pi's version (${detail}). ` +
      `Reinstall it: ${PI_INSTALL_COMMAND}.`
    );
  }
  if (admission.outcome === "unsupported") {
    return (
      `perk worker: the loaded Pi SDK (${HOST_SDK_PACKAGE}) is version ${observed}; perk ` +
      `requires Pi >= ${required}. Reinstall the worker's SDK at a supported version: ` +
      WORKER_REPAIR
    );
  }
  return (
    `perk worker: could not verify the loaded Pi SDK's version (${detail}); perk requires ` +
    `Pi >= ${required}. Reinstall the worker's SDK: ${WORKER_REPAIR}`
  );
}
