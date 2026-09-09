// The activation-local context-policy inputs (contracts.md §8.3): the runner bit
// (`PI_SUBAGENT_CHILD === "1"`, read ONCE per `session_start` in index.ts before lifecycle work)
// that the authoring-context eligibility policy (`authoring/context/eligibility.ts`) consumes
// through the Pi installers. Suppression only: a runner child receives no Perk authoring or
// plan-adapter guidance; the bit never grants tools or save authority, and it is deliberately
// NOT the runner restriction floor (`childRestrictions.ts`) — two independent captures of one
// startup boolean, each with its own consumer. Reset on shutdown so a re-activation starts from
// "not a runner".

/** The read side the installers compose (a supplier, so registration precedes capture). */
export interface ContextPolicyInputs {
  /** Whether this session is a native runner child (the last `session_start` capture). */
  runnerChild(): boolean;
}

export interface ContextPolicyController extends ContextPolicyInputs {
  /** Record the startup runner bit (every `session_start`, incl. reload — the env is re-read). */
  capture(runner: boolean): void;
  /** Activation shutdown: forget the capture. */
  clear(): void;
}

export function createContextPolicyInputs(): ContextPolicyController {
  let runner = false;
  return {
    runnerChild: () => runner,
    capture(value) {
      runner = value;
    },
    clear() {
      runner = false;
    },
  };
}
