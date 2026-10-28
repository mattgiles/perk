// The containment probes' evidence instrument (dev-only). Every probe reports one machine-readable
// row per (mechanism, criterion) as a `node:test` diagnostic prefixed `perk-v2-containment `, so a
// CI log carries the measurement verbatim (the slow tier runs under the `spec` reporter because
// `dot` drops diagnostics). The vocabulary is closed: `../../containment/census.test.ts` pins it
// and checks every literal the probe files use against it. A row reports what was measured; it
// never decides the verdict — the binding record's decision rule does, over every host's rows.

import { accessSync, constants, existsSync, readFileSync } from "node:fs";
import { release } from "node:os";
import type { TestContext } from "node:test";
import { localDaemon } from "@earendil-works/pi-env";
import { ownCgroupPath } from "./cgroup.ts";
import { commandExists } from "./probe.ts";

/** The prefix every evidence line carries (the CI-log filter). */
export const EVIDENCE_PREFIX = "perk-v2-containment ";

export const MECHANISMS = [
  "repro",
  "supervised",
  "pidns",
  "bwrap",
  "pdeathsig",
  "journal",
  "cgroup",
  "systemd-scope",
  "marker",
] as const;

export const CRITERIA = [
  "availability",
  "crash-A",
  "crash-B",
  "crash-C",
  "descendants",
  "pid-reuse",
  "setsid-escape",
  "leader-exited",
  "group-kill",
  "group-kill-mitigated",
  "report",
  "survival",
] as const;

export const RESULTS = ["PASS", "FAIL", "unavailable", "not_measured", "recorded"] as const;

export type Mechanism = (typeof MECHANISMS)[number];
export type Criterion = (typeof CRITERIA)[number];
/** `recorded` is a residual row's result: a survival map, no pass/fail. */
export type Result = (typeof RESULTS)[number];
export type HostName = "github" | "local";

/** The host facts the `host` row carries (every value a string, so the row diffs cleanly). */
export type HostFacts = Readonly<Record<string, string>>;

export type EvidenceRow = {
  readonly kind: "host" | "probe";
  readonly host: HostName;
  readonly mechanism?: Mechanism;
  readonly criterion?: Criterion;
  readonly result: Result;
  /** Verbatim stderr / exit status / per-process survival map. */
  readonly detail: string;
  readonly facts?: HostFacts;
};

/** The probe's measurement, without the fields `evidence` fills in. */
export type ProbeRow = {
  readonly mechanism: Mechanism;
  readonly criterion: Criterion;
  readonly result: Result;
  readonly detail: string;
};

export function hostName(): HostName {
  return process.env.GITHUB_ACTIONS === "true" ? "github" : "local";
}

function emit(t: TestContext, row: EvidenceRow): void {
  t.diagnostic(EVIDENCE_PREFIX + JSON.stringify(row));
}

/** Report one probe row on `t`. Returns the row's result so a caller can assert on it. */
export function evidence(t: TestContext, row: ProbeRow): Result {
  emit(t, { kind: "probe", host: hostName(), ...row });
  return row.result;
}

/** Report the `host` row (once per run, from `ownerDeath.slow.test.ts`). */
export function hostEvidence(t: TestContext): HostFacts {
  const facts = hostFacts();
  emit(t, { kind: "host", host: hostName(), result: "recorded", detail: "", facts });
  return facts;
}

function readTrimmed(path: string): string {
  try {
    return readFileSync(path, "utf8").trim();
  } catch {
    return "absent";
  }
}

function writable(path: string): boolean {
  try {
    accessSync(path, constants.W_OK);
    return true;
  } catch {
    return false;
  }
}

/** `PRETTY_NAME` from os-release, or `absent`. */
function osRelease(): string {
  const text = readTrimmed("/etc/os-release");
  return /^PRETTY_NAME="?([^"\n]*)"?$/m.exec(text)?.[1] ?? "absent";
}

/** The `localDaemon()` path, or the message it threw. */
export function daemonPath(): { path: string } | { error: string } {
  try {
    return { path: localDaemon() };
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

export function hostFacts(): HostFacts {
  const cgroup = ownCgroupPath();
  const daemon = daemonPath();
  const facts: Record<string, string> = {
    platform: process.platform,
    arch: process.arch,
    release: release(),
    osRelease: osRelease(),
    node: process.version,
    uid: String(process.getuid?.() ?? "n/a"),
    apparmor_restrict_unprivileged_userns: readTrimmed(
      "/proc/sys/kernel/apparmor_restrict_unprivileged_userns",
    ),
    max_user_namespaces: readTrimmed("/proc/sys/user/max_user_namespaces"),
    ownCgroup: cgroup ?? "absent",
    ownCgroupWritable: String(cgroup !== undefined && writable(cgroup)),
    cgroupKill: String(cgroup !== undefined && existsSync(`${cgroup}/cgroup.kill`)),
    piEnvDaemon: "path" in daemon ? daemon.path : `throws: ${daemon.error}`,
  };
  for (const command of ["bwrap", "unshare", "setpriv", "systemd-run", "setsid"]) {
    facts[command] = commandExists(command) ? "present" : "missing";
  }
  for (const name of ["ImageOS", "ImageVersion", "RUNNER_OS"]) {
    const value = process.env[name];
    if (value !== undefined) facts[name] = value;
  }
  return facts;
}
