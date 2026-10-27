// The v2 host entry. With `durable/`, it is the only v2 production home that may import Durable,
// chord or pi-ai — `layeringGuard.test.ts` enforces that confinement, and that the kernel stays
// Durable-free. It grows into the full lifecycle (lock → gate → resume → quiescence → close) of
// docs/design/pi-durable-v2-foundations.md §10; today it only opens and closes a Harness, and
// schedules no work (opening runs nothing until `resume()`, a submit or a wait).

import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import { createModels } from "@earendil-works/pi-ai/models";
import { createRegistry, Harness, type Storage } from "@earendil-works/pi-durable";

/** An opened v2 host: the Harness over the caller's storage. */
export interface OpenHost {
  readonly harness: Harness;
  /** Close the Harness and its storage. Call once — close is not idempotent. */
  close(): Promise<void>;
}

/** Open a Harness over `storage` with the built-in registry and the default model catalog. */
export async function openHost(storage: Storage): Promise<OpenHost> {
  const harness = await Harness.open(
    storage,
    { models: createModels(), registry: createRegistry() },
    BACKGROUND_CONTEXT,
  );
  return { harness, close: () => harness.close(BACKGROUND_CONTEXT) };
}
