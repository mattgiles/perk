// The check wire boundary: the one frontend vocabulary owner for the CheckRunner
// protocol. Closed literal arrays mirror perk_dev.prose_review.checks (a vocabulary
// change here is a deliberate wire-contract change, never a silent widening);
// reject-unknown structural parsers return null on any ill-shaped payload.

export const CHECK_IDS = [
  "prose-map",
  "learned-docs",
  "prompt-parity",
  "worker-prompt-pins",
  "worker-test-pins",
  "ruff",
  "ty",
  "biome",
  "tsc",
] as const;
export type CheckId = (typeof CHECK_IDS)[number];

export const CHECK_RUN_STATUSES = [
  "running",
  "passed",
  "failed",
  "cancelled",
  "timeout",
  "spawn-failed",
] as const;
export type CheckRunStatus = (typeof CHECK_RUN_STATUSES)[number];

// The closed session-notice vocabulary and its fixed copy — one string per notice,
// rendered verbatim at the top of the drawer's Checks section.
export type CheckNotice = "not-sent" | "busy" | "start-failed" | "run-lost";
export const CHECK_NOTICE_DETAILS: Record<CheckNotice, string> = {
  "not-sent":
    "The check request did not leave the browser. Retry when the workbench session is available.",
  busy: "A check is already running.",
  "start-failed": "The check could not be started.",
  "run-lost": "Run record no longer available.",
};

export type CheckRun = {
  run: string;
  check: CheckId;
  label: string;
  command: string;
  status: CheckRunStatus;
  exit_code: number | null;
  output: string;
  next_offset: number;
  truncated: boolean;
};

export type LatestCheck = {
  run: CheckRun | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function included<T extends string>(values: readonly T[], value: unknown): value is T {
  return typeof value === "string" && (values as readonly string[]).includes(value);
}

export function parseCheckRun(value: unknown): CheckRun | null {
  if (
    !isRecord(value) ||
    typeof value.run !== "string" ||
    !included(CHECK_IDS, value.check) ||
    typeof value.label !== "string" ||
    typeof value.command !== "string" ||
    !included(CHECK_RUN_STATUSES, value.status) ||
    (value.exit_code !== null && !Number.isInteger(value.exit_code)) ||
    typeof value.output !== "string" ||
    !Number.isInteger(value.next_offset) ||
    (value.next_offset as number) < 0 ||
    typeof value.truncated !== "boolean"
  ) {
    return null;
  }
  return {
    run: value.run,
    check: value.check,
    label: value.label,
    command: value.command,
    status: value.status,
    exit_code: value.exit_code as number | null,
    output: value.output,
    next_offset: value.next_offset as number,
    truncated: value.truncated,
  };
}

export function parseLatestCheck(value: unknown): LatestCheck | null {
  if (!isRecord(value)) {
    return null;
  }
  if (value.run === null) {
    return { run: null };
  }
  const run = parseCheckRun(value.run);
  return run === null ? null : { run };
}
