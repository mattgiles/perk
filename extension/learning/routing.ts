// The learn flow's routing vocabulary + decisions: the two learn plan-factory kinds (the TS twin
// of the Python plane's `factory_common.py` — `LearnFactoryKind` + `DOCS_FACTORY`/`CODE_FACTORY`)
// and the pure bare-`/learn` launch decision. The kind bundle is feature routing vocabulary — the
// cross-plane mirror — including its two user-facing strings (a deliberate variation on
// registration-prose placement; the adapter baseline test pins their byte-stability).

import { learnManifestPath } from "./analystWave.ts";

/**
 * The per-kind parameter bundle shared by the two warm learn-factory doors (the TS twin of the
 * frozen `LearnFactoryKind` dataclass). `subcommand` derives the cold argv, the `runColdDoor`
 * label, and the headless log tail; `seedTemplate` and `bindingTrigger` stay explicit so the
 * strings remain greppable against `prompts/stages/` and `shared/bindings.yaml`.
 */
export interface LearnFactoryKind {
  /** The command id and `report()` scope. */
  readonly name: string;
  /** The cold-door verb under `perk learn`. */
  readonly subcommand: string;
  readonly seedTemplate: string;
  readonly bindingTrigger: string;
  /** The `registerPerkCommand` description. */
  readonly description: string;
  /** The gentle `no_learn_issues` warning. */
  readonly emptyMessage: string;
}

export const DOCS_FACTORY: LearnFactoryKind = {
  name: "learn-docs",
  subcommand: "docs",
  seedTemplate: "stages/learn-docs.md",
  bindingTrigger: "command:learn-docs",
  description:
    "Start the learned-docs plan factory: gather open perk:learn issues into an inbox and author " +
    "a docs/learned consolidation plan.",
  emptyMessage: "nothing to consolidate (no open perk:learn issues).",
};

export const CODE_FACTORY: LearnFactoryKind = {
  name: "learn-code",
  subcommand: "code",
  seedTemplate: "stages/learn-code.md",
  bindingTrigger: "command:learn-code",
  description:
    "Start the learn-code plan factory: gather pre-stamped SHOULD_BE_CODE perk:learn issues into " +
    "an inbox and author a plan routing each into its real code home.",
  emptyMessage: "nothing to route into code (no SHOULD_BE_CODE perk:learn issues).",
};

/**
 * The bare-`/learn` launch decision: a learn-docs plan short-circuits to a deterministic
 * marker-clear no-op (`consumed_skip` — land already stamped `learn_state: skipped` for a
 * `consumed_learn` plan, §8.36); a gather failure or a bundle-less success degrades to the
 * simple learn pass (`fallback` — /learn is never a dead end); otherwise orchestrate the
 * analyst wave over the gathered bundle.
 */
export type LearnLaunchDecision =
  | { kind: "consumed_skip" }
  | { kind: "fallback"; reason: "gather_failed" | "no_bundle" }
  | { kind: "orchestrate"; bundleDir: string; manifestPath: string };

/**
 * Decide the bare-`/learn` launch from the decoded evidence-gather outcome (`bundleDir` already
 * resolved absolute by the caller — cwd semantics stay adapter-side). Branch order: gather
 * failure → fallback; `skipped` → consumed_skip; null bundle → fallback; else orchestrate
 * (`manifestPath` via `learnManifestPath` — the one derivation point).
 */
export function decideLearnLaunch(
  gather: { ok: false } | { ok: true; skipped: boolean; bundleDir: string | null },
): LearnLaunchDecision {
  if (!gather.ok) return { kind: "fallback", reason: "gather_failed" };
  if (gather.skipped) return { kind: "consumed_skip" };
  if (gather.bundleDir === null) return { kind: "fallback", reason: "no_bundle" };
  return {
    kind: "orchestrate",
    bundleDir: gather.bundleDir,
    manifestPath: learnManifestPath(gather.bundleDir),
  };
}
