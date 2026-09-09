// The two native-child booleans (contracts.md §8.3): the pi-subagents runner bit and perk's
// report restriction packet. Neither is identity; the floor is the only thing that restricts.

const FAMILY = "perk.parent-restrictions/";
const NAMESPACE = `${FAMILY}1`;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The runner stamp pi-subagents sets on every background (runner-hosted) child. */
export function isRunnerChild(env: NodeJS.ProcessEnv): boolean {
  return env.PI_SUBAGENT_CHILD === "1";
}

/**
 * Runner bit AND perk's packet ⇒ floor. No packet (the delegation-dispatched writer) ⇒ no floor.
 * A present packet must be exactly `{readOnly: boolean}` under perk's v1 namespace; any other
 * `perk.parent-restrictions/…` key (an unsupported version — producer/consumer skew) or any
 * other shape fails closed. Unrelated namespaces beside it are opaque.
 */
export function decodeReadOnlyFloor(runner: boolean, raw: string | undefined): boolean {
  if (!runner || raw === undefined) return false;
  let envelope: unknown;
  try {
    envelope = JSON.parse(raw);
  } catch {
    return true;
  }
  if (!isRecord(envelope)) return true;
  if (Object.keys(envelope).some((key) => key.startsWith(FAMILY) && key !== NAMESPACE)) return true;
  if (!Object.hasOwn(envelope, NAMESPACE)) return false;
  const value = envelope[NAMESPACE];
  // Own-key check: a polluted `Object.prototype.readOnly` must never un-floor a malformed value.
  if (!isRecord(value) || !Object.hasOwn(value, "readOnly") || Object.keys(value).length !== 1) {
    return true;
  }
  return typeof value.readOnly === "boolean" ? value.readOnly : true;
}
