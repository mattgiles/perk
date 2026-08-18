// The Assembly-mode state machine, owning the two-stage options→render flow (the
// searchPanel.ts posture — pure, injectable, node:test-covered). One latest-wins
// generation counter spans both stages. The session keeps its authoritative state
// internally and applies the completion-merge rule: an async completion is dropped
// unless its generation is current; an options completion establishes the `ready`
// state; a render completion mutates only the live state's `render` slot (and is
// dropped if the state is no longer `ready`) — so same-generation `setOverride`
// changes made while a render is in flight survive when the render lands.

import type {
  AssemblyOptions,
  AssemblyOverrides,
  AssemblyRender,
  AssemblyRenderRequest,
  PresentationControl,
} from "./assembly.ts";
import { type AssemblyRenderOutcome, loadAssemblyOptions, renderAssembly } from "./assemblyLoad.ts";
import type { WorkspaceBufferExport } from "./editWorkspace.ts";
import type { DocumentLike } from "./mutationRequest.ts";
import type { FetchLike } from "./sourceLoad.ts";

export type AssemblyRenderSlot =
  | { status: "rendering" }
  | { status: "rendered"; render: AssemblyRender }
  | { status: "render-refused"; detail: string }
  | { status: "render-not-sent" }
  | { status: "render-failed" };

export type AssemblySessionState =
  | { status: "idle" }
  | { status: "loading-options"; assembly: string }
  | { status: "options-refused"; assembly: string; detail: string }
  | { status: "options-failed"; assembly: string }
  | {
      status: "ready";
      assembly: string;
      options: AssemblyOptions;
      scenarioId: string;
      overrides: AssemblyOverrides;
      render: AssemblyRenderSlot;
    };

export type AssemblySessionDeps = {
  onState: (state: AssemblySessionState) => void;
  buffersFn: () => WorkspaceBufferExport[];
  fetchFn?: FetchLike;
  documentRoot?: DocumentLike;
};

export type AssemblySession = {
  open: (assembly: string) => void;
  chooseScenario: (id: string) => void;
  setOverride: (control: PresentationControl, value: boolean | null) => void;
  rerender: () => void;
  refreshBuffers: () => void;
  clear: () => void;
  dispose: () => void;
};

function renderSlot(outcome: AssemblyRenderOutcome): AssemblyRenderSlot {
  if (outcome.status === "loaded") {
    return { status: "rendered", render: outcome.render };
  }
  if (outcome.status === "refused") {
    return { status: "render-refused", detail: outcome.detail };
  }
  if (outcome.status === "not-sent") {
    return { status: "render-not-sent" };
  }
  return { status: "render-failed" };
}

export function createAssemblySession(deps: AssemblySessionDeps): AssemblySession {
  const fetchFn = deps.fetchFn ?? fetch;
  let generation = 0;
  let state: AssemblySessionState = { status: "idle" };
  // The exact serialized buffers sent with the last issued render — refreshBuffers
  // re-renders only on mismatch (never on unrelated workspace notifications).
  let lastRenderBuffers: string | null = null;

  function emit(next: AssemblySessionState): void {
    state = next;
    deps.onState(next);
  }

  // Every issued render bumps the generation, so an older in-flight render (or
  // options load) can never land over a newer one.
  function issueRender(): void {
    if (state.status !== "ready") {
      return;
    }
    generation += 1;
    const current = generation;
    const request: AssemblyRenderRequest = {
      assembly: state.assembly,
      scenario: state.scenarioId,
      presentation: {
        include_ambient: state.overrides.ambient,
        include_tools: state.overrides.tools,
      },
    };
    const buffers = deps.buffersFn();
    lastRenderBuffers = JSON.stringify(buffers);
    emit({ ...state, render: { status: "rendering" } });
    void renderAssembly(request, buffers, fetchFn, deps.documentRoot).then((outcome) => {
      if (generation !== current || state.status !== "ready") {
        return;
      }
      emit({ ...state, render: renderSlot(outcome) });
    });
  }

  return {
    open(assembly: string): void {
      generation += 1;
      const current = generation;
      emit({ status: "loading-options", assembly });
      void loadAssemblyOptions(assembly, fetchFn).then((outcome) => {
        if (generation !== current) {
          return;
        }
        if (outcome.status === "refused") {
          emit({ status: "options-refused", assembly, detail: outcome.detail });
          return;
        }
        if (outcome.status === "failed") {
          emit({ status: "options-failed", assembly });
          return;
        }
        // Auto-select the first ordered scenario (total: the parse boundary rejects
        // empty scenario arrays) and render immediately; issueRender performs the one
        // visible `ready` emission.
        state = {
          status: "ready",
          assembly,
          options: outcome.options,
          scenarioId: outcome.options.scenarios[0].id,
          overrides: { ambient: null, tools: null },
          render: { status: "rendering" },
        };
        issueRender();
      });
    },
    chooseScenario(id: string): void {
      if (state.status !== "ready") {
        return;
      }
      // Adopt the new scenario's authored defaults: both overrides reset to null.
      state = { ...state, scenarioId: id, overrides: { ambient: null, tools: null } };
      issueRender();
    },
    setOverride(control: PresentationControl, value: boolean | null): void {
      if (state.status !== "ready") {
        return;
      }
      const overrides =
        control === "ambient"
          ? { ...state.overrides, ambient: value }
          : { ...state.overrides, tools: value };
      emit({ ...state, overrides });
    },
    rerender(): void {
      issueRender();
    },
    refreshBuffers(): void {
      if (state.status !== "ready") {
        return;
      }
      if (JSON.stringify(deps.buffersFn()) === lastRenderBuffers) {
        return;
      }
      issueRender();
    },
    clear(): void {
      generation += 1;
      lastRenderBuffers = null;
      emit({ status: "idle" });
    },
    dispose(): void {
      generation += 1;
    },
  };
}
