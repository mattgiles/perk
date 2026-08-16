import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";
import type {
  AttentionFileSummary,
  DirtyFileSummary,
  EditWorkspace,
  WorkspaceSource,
} from "./editWorkspace.ts";
import { type SourceTarget, sourceTargetKey } from "./selection.ts";

export type WorkspaceLoadState =
  | { status: "loading" }
  | { status: "refused"; detail: string }
  | { status: "failed" }
  | { status: "loaded"; source: WorkspaceSource };

const WorkspaceContext = createContext<EditWorkspace | null>(null);

export function WorkspaceProvider({
  workspace,
  children,
}: {
  workspace: EditWorkspace;
  children?: ReactNode;
}) {
  return <WorkspaceContext.Provider value={workspace}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): EditWorkspace {
  const workspace = useContext(WorkspaceContext);
  if (workspace === null) {
    throw new Error("WorkspaceProvider is required");
  }
  return workspace;
}

export function useWorkspaceSource(target: SourceTarget): {
  state: WorkspaceLoadState;
  retry: () => void;
} {
  const workspace = useWorkspace();
  const [retryRevision, setRetryRevision] = useState(0);
  const [state, setState] = useState<WorkspaceLoadState>(() => {
    const source = workspace.inspect(target);
    return source === null ? { status: "loading" } : { status: "loaded", source };
  });
  const key = sourceTargetKey(target);
  const path = target.unit.path;

  // biome-ignore lint/correctness/useExhaustiveDependencies: key captures the complete target identity.
  useEffect(() => {
    let active = true;
    const refresh = (): void => {
      const current = workspace.inspect(target);
      if (current !== null) {
        setState({ status: "loaded", source: current });
        return;
      }
      setState({ status: "loading" });
      void workspace.ensure(target).then((outcome) => {
        if (!active || outcome.status === "stale") {
          return;
        }
        setState(outcome);
      });
    };
    const unsubscribe = workspace.subscribePath(path, refresh);
    refresh();
    return () => {
      active = false;
      unsubscribe();
    };
    // key is the exact target identity; retryRevision is the explicit transient retry.
  }, [workspace, path, key, retryRevision]);

  const retry = useCallback(() => setRetryRevision((current) => current + 1), []);
  return { state, retry };
}

export function useAttentionFiles(): AttentionFileSummary[] {
  const workspace = useWorkspace();
  const [summaries, setSummaries] = useState(() => workspace.attentionFiles());
  useEffect(
    () => workspace.subscribeGlobal(() => setSummaries(workspace.attentionFiles())),
    [workspace],
  );
  return summaries;
}

export function useDirtyFiles(): DirtyFileSummary[] {
  const workspace = useWorkspace();
  const [summaries, setSummaries] = useState(() => workspace.dirtyFiles());
  useEffect(
    () => workspace.subscribeGlobal(() => setSummaries(workspace.dirtyFiles())),
    [workspace],
  );
  return summaries;
}
