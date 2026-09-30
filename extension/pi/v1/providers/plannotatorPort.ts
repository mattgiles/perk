// The plannotator port-selection mirror: which port perk's browser-open core presets, decided by
// the SAME rule plannotator applies when it resolves a port itself — so a door never
// second-guesses the operator's `PLANNOTATOR_PORT` / remote setup, and a fixed SSH tunnel or a
// tailnet reaches every browser review exactly like it reaches the plain `plan_review` arm.
//
// MIRROR PIN: every rule here is a byte-faithful mirror of `@plannotator/pi-extension@0.27.22` —
// `server/network.ts` (`getRemoteOverride`/`isRemoteSession`, `getServerPortConfiguration`,
// `DEFAULT_REMOTE_PORT`) and `generated/port-range.ts` (`parsePortSelection`). A later plannotator
// that changes the rule makes perk and plannotator disagree on the port — loud (the door's
// readiness probe times out and it degrades), never silent.
//
// The deliberate divergences are about BUSY ports, never about which port is chosen:
//  - who walks a range: plannotator walks it at bind time, but the doors need ONE concrete port up
//    front (the deterministic URL they prime `push_annotations` with), so perk bind-probes the
//    range on loopback and presets the first free port as a single value — plannotator then binds
//    exactly that port;
//  - an occupied fixed port is REFUSED, where plannotator would retry and then preempt a stale
//    same-process review: a readiness probe cannot tell which review answers on a port, and the
//    doors prime annotation delivery immediately, so reusing an occupied port would let a door
//    report ready against — and push findings into — the review already holding it (possibly in
//    another perk process). The plain `plan_review` arm presets nothing and pushes nothing, so it
//    keeps plannotator's own retry + self-preemption.
// A loopback probe predicts plannotator's remote `0.0.0.0` bind on Linux and macOS: a listener on
// either address makes the other's bind fail with `EADDRINUSE`.

import { createServer } from "node:net";

/** Plannotator's `DEFAULT_REMOTE_PORT` — the port a remote session binds when none is set. */
export const PLANNOTATOR_DEFAULT_REMOTE_PORT = 19432;

/**
 * Plannotator's remote detection: `PLANNOTATOR_REMOTE` is a tri-state override (exactly `"1"` or
 * case-insensitive `"true"` → remote; exactly `"0"` or case-insensitive `"false"` → local; unset
 * or any other value → no override), else legacy SSH detection (`SSH_TTY` / `SSH_CONNECTION`
 * truthy). No trimming — plannotator does none.
 */
export function isPlannotatorRemoteSession(env: NodeJS.ProcessEnv): boolean {
  const remote = env.PLANNOTATOR_REMOTE;
  if (remote !== undefined) {
    if (remote === "1" || remote.toLowerCase() === "true") return true;
    if (remote === "0" || remote.toLowerCase() === "false") return false;
  }
  return Boolean(env.SSH_TTY || env.SSH_CONNECTION);
}

/** A whole-string fixed port or inclusive range (plannotator's `ParsedPortSelection`). */
export type ParsedPortSelection =
  | { kind: "fixed"; ports: [number] }
  | { kind: "range"; ports: number[] };

/**
 * Plannotator's `parsePortSelection`: a fixed port (`0` allowed — an ephemeral bind) or an
 * inclusive range whose bounds are concrete ports (`1 ≤ start ≤ end ≤ 65535`); anything
 * malformed or out of bounds → null.
 */
export function parsePortSelection(value: string): ParsedPortSelection | null {
  const trimmed = value.trim();
  const rangeMatch = /^(\d+)-(\d+)$/.exec(trimmed);
  if (rangeMatch) {
    const start = Number(rangeMatch[1]);
    const end = Number(rangeMatch[2]);
    if (start < 1 || end > 65535 || start > end) return null;
    return {
      kind: "range",
      ports: Array.from({ length: end - start + 1 }, (_, index) => start + index),
    };
  }
  if (!/^\d+$/.test(trimmed)) return null;
  const port = Number(trimmed);
  return port <= 65535 ? { kind: "fixed", ports: [port] } : null;
}

/**
 * The resolved port selection: `random` (an ephemeral OS pick), `single` (one fixed port — an
 * explicit `PLANNOTATOR_PORT` or the `19432` remote default), `range` (a `PLANNOTATOR_PORT` range,
 * walked in order).
 */
export type PlannotatorPortSelection =
  | { kind: "random" }
  | { kind: "single"; port: number }
  | { kind: "range"; ports: readonly number[] };

/** The per-activation port selection plus whether plannotator will treat the session as remote. */
export interface PlannotatorPorts {
  readonly selection: PlannotatorPortSelection;
  readonly remote: boolean;
}

/**
 * Resolve the port selection with plannotator's precedence: a truthy `PLANNOTATOR_PORT` that
 * parses wins (a range → `range`; a fixed `0` → `random`, because plannotator's `listen(0)` would
 * pick a port perk cannot know in advance — perk makes that OS pick itself so the door's URL
 * stays deterministic; any other fixed port → `single`); a set-but-unparseable value falls
 * through SILENTLY (plannotator's "invalid port - fall back silently"); then remote → the
 * `19432` single port; else `random`.
 */
export function resolvePlannotatorPorts(env: NodeJS.ProcessEnv): PlannotatorPorts {
  const remote = isPlannotatorRemoteSession(env);
  const envPort = env.PLANNOTATOR_PORT;
  if (envPort) {
    const parsed = parsePortSelection(envPort);
    if (parsed !== null) {
      if (parsed.kind === "range") {
        return { selection: { kind: "range", ports: parsed.ports }, remote };
      }
      const [port] = parsed.ports;
      if (port === 0) return { selection: { kind: "random" }, remote };
      return { selection: { kind: "single", port }, remote };
    }
  }
  if (remote) {
    return { selection: { kind: "single", port: PLANNOTATOR_DEFAULT_REMOTE_PORT }, remote };
  }
  return { selection: { kind: "random" }, remote };
}

/**
 * The local default every browser-open core falls back to when a caller passes no selection —
 * direct-core call sites and their tests stay byte-stable and hermetic (they never read
 * `process.env`).
 */
export const LOCAL_PLANNOTATOR_PORTS: PlannotatorPorts = Object.freeze({
  selection: Object.freeze({ kind: "random" }),
  remote: false,
});

/** Pick a free ephemeral port: `node:net` listen(0) → read → close. */
export async function pickEphemeralPort(): Promise<number> {
  return await new Promise<number>((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address !== null ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

/**
 * The fixed-port probe: whether `port` binds on loopback right now. Any bind error resolves
 * false — conservative: an unusable port is skipped or refused, never chosen. A bind (not a
 * connect) because it must predict plannotator's bind.
 */
export async function portBinds(port: number): Promise<boolean> {
  return await new Promise<boolean>((resolve) => {
    const server = createServer();
    server.once("error", () => resolve(false));
    server.listen(port, "127.0.0.1", () => {
      server.close(() => resolve(true));
    });
  });
}

/** The injectable picker seams (tests drive a fake ephemeral picker / fixed-port probe). */
export interface PortPickerDeps {
  ephemeral: () => Promise<number>;
  probe: (port: number) => Promise<boolean>;
}

/**
 * The concrete port to preset for a selection. `random` → an ephemeral pick. `single` → the port
 * when the probe reports it bindable, else throws: an occupied fixed port is refused (see the
 * header — reusing it would let the door announce and prime the review already holding it).
 * `range` → the first port the probe reports bindable, in order; none → throws. Every throw is
 * reported by the doors' pick-failure arm.
 */
export async function pickPlannotatorPort(
  selection: PlannotatorPortSelection,
  deps: PortPickerDeps,
): Promise<number> {
  switch (selection.kind) {
    case "random":
      return await deps.ephemeral();
    case "single": {
      if (await deps.probe(selection.port)) return selection.port;
      throw new Error(
        `Plannotator port ${selection.port} is in use — another review or process holds it; decide that review first, or set PLANNOTATOR_PORT to a range`,
      );
    }
    case "range": {
      for (const port of selection.ports) {
        if (await deps.probe(port)) return port;
      }
      const first = selection.ports[0];
      const last = selection.ports[selection.ports.length - 1];
      throw new Error(
        `PLANNOTATOR_PORT range ${first}-${last} is exhausted — every port is in use; widen the range or decide an open review`,
      );
    }
    default: {
      const unreachable: never = selection;
      throw new Error(`unknown port selection: ${JSON.stringify(unreachable)}`);
    }
  }
}

/**
 * The doors' shared readiness line. Plannotator never auto-opens a browser in a remote session
 * (it notifies the advertised URL instead), so the local "browser opening" text would be false
 * there.
 */
export function browserUpNotice(started: { url: string; remote: boolean }): string {
  if (!started.remote) return `plannotator is up at ${started.url} — browser opening`;
  return (
    `plannotator is up at ${started.url} — reach it from your machine through your tunnel or ` +
    "tailnet (Plannotator's own notice carries the advertised URL)"
  );
}
