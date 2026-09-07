// Conservative routing fingerprints, never semantic backend discovery. No raw routing inputs
// escape in a refusal or persisted record; order and exact bytes are contractual (§8.23).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { handoffPath, isSafeRunId } from "../substrate/cache.ts";
import { draftReviewGitContext } from "../substrate/git.ts";
import { configFile, localConfigFile } from "../substrate/paths.ts";
import { isNonblank, type ReviewSubject, reviewRefused } from "./draftReviewState.ts";
import { digestSessionData, type WorkflowSession } from "./workflowSession.ts";

export type FileMark = { state: "absent" } | { state: "present"; digest: string };
export type PlanHandoff = {
  objective_id: string | null;
  node_id: string | null;
  adopt_from: string | null;
  consumed_learn: string[];
};
export type ObjectiveHandoff = { adopt_from: string | null; supersedes: string | null };
export type GistHandoff = { gist_scope: "plan" | "objective" | null };
export type TargetProjection = {
  worktree_root: string;
  git_dir: string;
  git_common_dir: string;
  run_id: string;
  subject: ReviewSubject;
  warm_node_claim: { objective: string; node: string } | null;
  handoff: PlanHandoff | ObjectiveHandoff | GistHandoff | null;
  files: { main_config: FileMark; worktree_config: FileMark; worktree_local: FileMark };
  git_config_digest: string;
  environment: { GH_REPO: string | null; GH_HOST: string | null };
};
export interface DraftReviewBindingPorts {
  git(cwd: string): ReturnType<typeof draftReviewGitContext>;
  /** null means ENOENT only; every other read failure throws. */
  read(path: string): Uint8Array | null;
  environment(): { GH_REPO?: string; GH_HOST?: string };
}
const production: DraftReviewBindingPorts = {
  git: draftReviewGitContext,
  read(path) {
    try {
      return readFileSync(path);
    } catch (error) {
      if (typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT")
        return null;
      throw error;
    }
  },
  environment: () => ({ GH_REPO: process.env.GH_REPO, GH_HOST: process.env.GH_HOST }),
};
function optionalId(value: unknown): string | null {
  if (value === undefined || value === null) return null;
  if (!isNonblank(value)) throw new Error("invalid handoff ID");
  return value;
}
/** Ignore unrelated keys, but never normalize relevant IDs/arrays as the Python save may do. */
export function projectReviewHandoff(
  raw: unknown,
  subject: ReviewSubject,
  runId: string,
): TargetProjection["handoff"] {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw))
    throw new Error("invalid handoff");
  const h = raw as Record<string, unknown>;
  if (h.run_id !== runId) throw new Error("wrong handoff run");
  if (subject === "plan") {
    const consumed: string[] = [];
    if (h.consumed_learn !== undefined) {
      if (!Array.isArray(h.consumed_learn)) throw new Error("invalid consumed learns");
      for (const item of h.consumed_learn) {
        if (!isNonblank(item)) throw new Error("invalid consumed learn");
        consumed.push(item);
      }
    }
    return {
      objective_id: optionalId(h.objective_id),
      node_id: optionalId(h.node_id),
      adopt_from: optionalId(h.adopt_from),
      consumed_learn: consumed,
    };
  }
  if (subject === "objective")
    return { adopt_from: optionalId(h.adopt_from), supersedes: optionalId(h.supersedes) };
  const scope = h.gist_scope;
  if (scope != null && scope !== "plan" && scope !== "objective")
    throw new Error("invalid gist scope");
  return { gist_scope: scope ?? null };
}
/** Only the fixed-shape constructor below supplies this encoding; input-map order is not used. */
export function targetEncoding(projection: TargetProjection): string {
  const p = projection;
  const mark = (m: FileMark): FileMark =>
    m.state === "absent" ? { state: "absent" } : { state: "present", digest: m.digest };
  // Reconstruct even nested typed inputs, so callers cannot accidentally change digest ordering.
  const h = p.handoff;
  const handoff =
    h === null ? null : projectReviewHandoff({ run_id: p.run_id, ...h }, p.subject, p.run_id);
  const ordered: TargetProjection = {
    worktree_root: p.worktree_root,
    git_dir: p.git_dir,
    git_common_dir: p.git_common_dir,
    run_id: p.run_id,
    subject: p.subject,
    warm_node_claim:
      p.warm_node_claim === null
        ? null
        : { objective: p.warm_node_claim.objective, node: p.warm_node_claim.node },
    handoff,
    files: {
      main_config: mark(p.files.main_config),
      worktree_config: mark(p.files.worktree_config),
      worktree_local: mark(p.files.worktree_local),
    },
    git_config_digest: p.git_config_digest,
    environment: { GH_REPO: p.environment.GH_REPO, GH_HOST: p.environment.GH_HOST },
  };
  return `perk/draft-review-target/v1\n${JSON.stringify(ordered)}`;
}
export type DraftReviewBinding = {
  runId: string;
  subject: ReviewSubject;
  digest: string;
  warmNodeClaim: { objective: string; node: string } | null;
};
export function captureDraftReviewBinding(
  cwd: string,
  session: WorkflowSession,
  ports: DraftReviewBindingPorts = production,
): { ok: true; binding: DraftReviewBinding } | ReturnType<typeof reviewRefused> {
  try {
    const context = session.draftReviewContext();
    if (!context.ok) return reviewRefused(context.reason);
    const { runId, subject, warmNodeClaim } = context;
    if (!isSafeRunId(runId)) return reviewRefused("no-identity");
    const git = ports.git(cwd);
    if (git === null) return reviewRefused("io-error");
    const file = (path: string): FileMark => {
      const bytes = ports.read(path);
      return bytes === null
        ? { state: "absent" }
        : { state: "present", digest: digestSessionData(bytes) };
    };
    const handoffBytes = ports.read(handoffPath(git.worktreeRoot, runId));
    const handoff =
      handoffBytes === null
        ? null
        : projectReviewHandoff(
            JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(handoffBytes)),
            subject,
            runId,
          );
    const env = ports.environment();
    const envMark = (value: string | undefined): string | null =>
      value === undefined ? null : digestSessionData(value);
    const projection: TargetProjection = {
      worktree_root: git.worktreeRoot,
      git_dir: git.gitDir,
      git_common_dir: git.gitCommonDir,
      run_id: runId,
      subject,
      warm_node_claim: warmNodeClaim,
      handoff,
      files: {
        main_config: file(configFile(resolve(git.gitCommonDir, ".."))),
        worktree_config: file(configFile(git.worktreeRoot)),
        worktree_local: file(localConfigFile(git.worktreeRoot)),
      },
      git_config_digest: digestSessionData(git.configBytes),
      environment: { GH_REPO: envMark(env.GH_REPO), GH_HOST: envMark(env.GH_HOST) },
    };
    return {
      ok: true,
      binding: {
        runId,
        subject,
        digest: digestSessionData(targetEncoding(projection)),
        warmNodeClaim,
      },
    };
  } catch {
    return reviewRefused("io-error");
  }
}
