import { diffChars } from "diff";
import { type SourceTarget, sourceTargetKey } from "./selection.ts";
import {
  type NewlineStyle,
  type SourceFile,
  type SourceView,
  sourceCurrentText,
} from "./source.ts";
import {
  loadUnitSource,
  projectUnitSource,
  type SourceLoadOutcome,
  type SourceProjectionOutcome,
} from "./sourceLoad.ts";

const encoder = new TextEncoder();

export type WorkspaceEditor = Readonly<{
  path: string;
  targetKey: string;
  revision: number;
  display: string;
}>;

export type WorkspaceSource = {
  path: string;
  view: SourceView;
  editor: WorkspaceEditor | null;
  dirty: boolean;
};

export type FocusEditCommand = {
  target: SourceTarget;
  base: WorkspaceEditor;
  nextDisplay: string;
};

export type FocusEditOutcome = { status: "applied" } | { status: "stale" } | { status: "refused" };

export type WorkspaceOutcome =
  | { status: "loaded"; source: WorkspaceSource }
  | { status: "refused"; detail: string }
  | { status: "failed" }
  | { status: "stale" };

export type DirtyFileSummary = {
  path: string;
  target: SourceTarget;
};

export type CurrentFileSnapshot = {
  path: string;
  loadText: string;
  loadBytes: Uint8Array;
  currentText: string;
  currentBytes: Uint8Array;
  mode: number;
  newlineStyle: NewlineStyle;
  loadHash: string;
  revision: number;
  dirty: boolean;
};

export type WorkspaceTransport = {
  load: (target: SourceTarget, signal: AbortSignal) => Promise<SourceLoadOutcome>;
  project: (
    target: SourceTarget,
    text: string,
    signal: AbortSignal,
  ) => Promise<SourceProjectionOutcome>;
};

type RawFocus = {
  raw: string;
  display: string;
  rawBoundaryByDisplay: number[];
};

type CachedView = {
  revision: number;
  view: SourceView;
};

type ProtectedLens = {
  target: SourceTarget;
  targetKey: string;
  revision: number;
  start: number;
  end: number;
  focus: RawFocus;
};

type FileEntry = {
  file: SourceFile;
  loadText: string;
  loadBytes: Uint8Array;
  currentText: string;
  revision: number;
  views: Map<string, CachedView>;
  protectedLens: ProtectedLens | null;
  lastEditedTarget: SourceTarget | null;
};

type PathLoad = {
  targetKey: string;
  promise: Promise<WorkspaceOutcome>;
};

function exactBytesEqual(left: Uint8Array, right: Uint8Array): boolean {
  if (left.byteLength !== right.byteLength) {
    return false;
  }
  for (let index = 0; index < left.byteLength; index += 1) {
    if (left[index] !== right[index]) {
      return false;
    }
  }
  return true;
}

function rawFocus(raw: string): RawFocus {
  let display = "";
  const rawBoundaryByDisplay = [0];
  let rawIndex = 0;
  while (rawIndex < raw.length) {
    const character = raw[rawIndex];
    if (character === "\r") {
      rawIndex += raw[rawIndex + 1] === "\n" ? 2 : 1;
      display += "\n";
      rawBoundaryByDisplay.push(rawIndex);
      continue;
    }
    rawIndex += 1;
    display += character;
    rawBoundaryByDisplay.push(rawIndex);
  }
  return { raw, display, rawBoundaryByDisplay };
}

function firstTerminator(text: string): string | null {
  const match = /\r\n|\r|\n/.exec(text);
  return match?.[0] ?? null;
}

function insertionTerminator(entry: FileEntry, focus: RawFocus): string {
  if (entry.file.newline_style === "lf") {
    return "\n";
  }
  if (entry.file.newline_style === "crlf") {
    return "\r\n";
  }
  if (entry.file.newline_style === "cr") {
    return "\r";
  }
  return firstTerminator(focus.raw) ?? firstTerminator(entry.currentText) ?? "\n";
}

function insertedRaw(display: string, terminator: string): string {
  return display.replaceAll("\n", terminator);
}

function reconstructRawFocus(entry: FileEntry, previous: RawFocus, nextDisplay: string): string {
  const terminator = insertionTerminator(entry, previous);
  let previousOffset = 0;
  let reconstructed = "";
  for (const change of diffChars(previous.display, nextDisplay)) {
    if (change.added) {
      reconstructed += insertedRaw(change.value, terminator);
      continue;
    }
    const nextOffset = previousOffset + change.value.length;
    if (!change.removed) {
      const rawStart = previous.rawBoundaryByDisplay[previousOffset];
      const rawEnd = previous.rawBoundaryByDisplay[nextOffset];
      if (rawStart === undefined || rawEnd === undefined) {
        throw new Error("display-to-raw boundary map is incomplete");
      }
      reconstructed += previous.raw.slice(rawStart, rawEnd);
    }
    previousOffset = nextOffset;
  }
  return reconstructed;
}

function viewForLens(entry: FileEntry, lens: ProtectedLens): SourceView {
  return {
    unit: lens.target.unit.id,
    fragment: lens.target.fragment,
    kind: lens.target.unit.kind,
    before: entry.currentText.slice(0, lens.start),
    focus: entry.currentText.slice(lens.start, lens.end),
    after: entry.currentText.slice(lens.end),
    editable: true,
    read_only_reason: null,
  };
}

function synthesizedWholeView(target: SourceTarget, text: string): SourceView {
  return {
    unit: target.unit.id,
    fragment: null,
    kind: target.unit.kind,
    before: "",
    focus: text,
    after: "",
    editable: false,
    read_only_reason: "whole-unit",
  };
}

function stableProjection(view: SourceView): boolean {
  return view.read_only_reason !== "adapter-unavailable";
}

function cloneTarget(target: SourceTarget): SourceTarget {
  return {
    unit: { ...target.unit },
    fragment: target.fragment === null ? null : { ...target.fragment },
  };
}

function cloneView(view: SourceView): SourceView {
  return {
    ...view,
    fragment: view.fragment === null ? null : { ...view.fragment },
  };
}

function transportOutcome(outcome: SourceLoadOutcome | SourceProjectionOutcome): WorkspaceOutcome {
  if (outcome.status === "refused") {
    return outcome;
  }
  return { status: "failed" };
}

const DEFAULT_TRANSPORT: WorkspaceTransport = {
  load: (target, signal) => loadUnitSource(target, { signal }),
  project: (target, text, signal) => projectUnitSource(target, text, { signal }),
};

export class EditWorkspace {
  readonly #transport: WorkspaceTransport;
  readonly #files = new Map<string, FileEntry>();
  readonly #pathLoads = new Map<string, PathLoad>();
  readonly #projectionLoads = new Map<string, Promise<WorkspaceOutcome>>();
  readonly #controller = new AbortController();
  readonly #pathSubscribers = new Map<string, Set<() => void>>();
  readonly #globalSubscribers = new Set<() => void>();
  #alive = true;

  constructor(transport: WorkspaceTransport = DEFAULT_TRANSPORT) {
    this.#transport = transport;
  }

  inspect(target: SourceTarget): WorkspaceSource | null {
    const entry = this.#files.get(target.unit.path);
    if (entry === undefined) {
      return null;
    }
    const key = sourceTargetKey(target);
    if (
      entry.protectedLens !== null &&
      entry.protectedLens.targetKey === key &&
      entry.protectedLens.revision === entry.revision
    ) {
      return this.#workspaceSource(
        entry,
        viewForLens(entry, entry.protectedLens),
        entry.protectedLens.focus.display,
        key,
      );
    }
    if (target.fragment === null) {
      return this.#workspaceSource(
        entry,
        synthesizedWholeView(target, entry.currentText),
        null,
        key,
      );
    }
    const cached = entry.views.get(key);
    if (cached === undefined || cached.revision !== entry.revision) {
      return null;
    }
    return this.#workspaceSource(entry, cached.view, rawFocus(cached.view.focus).display, key);
  }

  async ensure(target: SourceTarget): Promise<WorkspaceOutcome> {
    if (!this.#alive) {
      return { status: "failed" };
    }
    const current = this.inspect(target);
    if (current !== null) {
      return { status: "loaded", source: current };
    }
    const path = target.unit.path;
    const entry = this.#files.get(path);
    if (entry === undefined) {
      return this.#ensurePath(target);
    }
    return this.#ensureProjection(entry, target);
  }

  editFocus(command: FocusEditCommand): FocusEditOutcome {
    if (!this.#alive) {
      return { status: "refused" };
    }
    const { target, base, nextDisplay } = command;
    const path = target.unit.path;
    const key = sourceTargetKey(target);
    const entry = this.#files.get(path);
    if (entry === undefined) {
      return { status: "refused" };
    }
    if (base.path !== path || base.targetKey !== key || base.revision !== entry.revision) {
      return { status: "stale" };
    }

    let start: number;
    let end: number;
    let previous: RawFocus;
    if (
      entry.protectedLens !== null &&
      entry.protectedLens.targetKey === key &&
      entry.protectedLens.revision === entry.revision
    ) {
      start = entry.protectedLens.start;
      end = entry.protectedLens.end;
      previous = entry.protectedLens.focus;
    } else {
      const cached = entry.views.get(key);
      if (cached === undefined || cached.revision !== entry.revision || !cached.view.editable) {
        return { status: "refused" };
      }
      if (sourceCurrentText(cached.view) !== entry.currentText) {
        return { status: "refused" };
      }
      start = cached.view.before.length;
      end = start + cached.view.focus.length;
      previous = rawFocus(cached.view.focus);
    }
    if (base.display !== previous.display) {
      return { status: "stale" };
    }

    const replacement = reconstructRawFocus(entry, previous, nextDisplay);
    entry.currentText =
      entry.currentText.slice(0, start) + replacement + entry.currentText.slice(end);
    entry.revision += 1;
    entry.views.clear();
    entry.protectedLens = {
      target: cloneTarget(target),
      targetKey: key,
      revision: entry.revision,
      start,
      end: start + replacement.length,
      focus: rawFocus(replacement),
    };
    entry.lastEditedTarget = cloneTarget(target);
    this.#notifyPath(path);
    this.#notifyGlobal();
    return { status: "applied" };
  }

  discard(path: string): boolean {
    if (!this.#alive) {
      return false;
    }
    const entry = this.#files.get(path);
    if (entry === undefined) {
      return false;
    }
    entry.currentText = entry.loadText;
    entry.revision += 1;
    entry.views.clear();
    entry.protectedLens = null;
    this.#notifyPath(path);
    this.#notifyGlobal();
    return true;
  }

  snapshot(path: string): CurrentFileSnapshot | null {
    const entry = this.#files.get(path);
    if (entry === undefined) {
      return null;
    }
    const currentBytes = encoder.encode(entry.currentText);
    return {
      path,
      loadText: entry.loadText,
      loadBytes: new Uint8Array(entry.loadBytes),
      currentText: entry.currentText,
      currentBytes: new Uint8Array(currentBytes),
      mode: entry.file.mode,
      newlineStyle: entry.file.newline_style,
      loadHash: entry.file.load_hash,
      revision: entry.revision,
      dirty: !exactBytesEqual(currentBytes, entry.loadBytes),
    };
  }

  dirtyFiles(): DirtyFileSummary[] {
    const summaries: DirtyFileSummary[] = [];
    for (const [path, entry] of this.#files) {
      if (entry.lastEditedTarget !== null && this.#dirty(entry)) {
        summaries.push({ path, target: cloneTarget(entry.lastEditedTarget) });
      }
    }
    return summaries.sort((left, right) => left.path.localeCompare(right.path));
  }

  subscribePath(path: string, subscriber: () => void): () => void {
    let subscribers = this.#pathSubscribers.get(path);
    if (subscribers === undefined) {
      subscribers = new Set();
      this.#pathSubscribers.set(path, subscribers);
    }
    subscribers.add(subscriber);
    return () => {
      subscribers.delete(subscriber);
      if (subscribers.size === 0) {
        this.#pathSubscribers.delete(path);
      }
    };
  }

  subscribeGlobal(subscriber: () => void): () => void {
    this.#globalSubscribers.add(subscriber);
    return () => this.#globalSubscribers.delete(subscriber);
  }

  dispose(): void {
    if (!this.#alive) {
      return;
    }
    this.#alive = false;
    this.#controller.abort();
    this.#pathLoads.clear();
    this.#projectionLoads.clear();
    this.#pathSubscribers.clear();
    this.#globalSubscribers.clear();
  }

  async #ensurePath(target: SourceTarget): Promise<WorkspaceOutcome> {
    const path = target.unit.path;
    const key = sourceTargetKey(target);
    const pending = this.#pathLoads.get(path);
    if (pending !== undefined) {
      const outcome = await pending.promise;
      if (pending.targetKey === key || !this.#alive) {
        return outcome;
      }
      return this.ensure(target);
    }

    const promise = this.#transport.load(target, this.#controller.signal).then((outcome) => {
      if (!this.#alive) {
        return { status: "stale" } as const;
      }
      if (outcome.status !== "loaded") {
        return transportOutcome(outcome);
      }
      if (outcome.source.file.path !== path) {
        return { status: "failed" } as const;
      }
      const loadText = sourceCurrentText(outcome.source.view);
      const loadBytes = encoder.encode(loadText);
      const entry: FileEntry = {
        file: { ...outcome.source.file },
        loadText,
        loadBytes: new Uint8Array(loadBytes),
        currentText: loadText,
        revision: 0,
        views: new Map(),
        protectedLens: null,
        lastEditedTarget: null,
      };
      if (!this.#acceptView(entry, target, 0, outcome.source.view)) {
        return { status: "failed" } as const;
      }
      this.#files.set(path, entry);
      this.#notifyPath(path);
      this.#notifyGlobal();
      return {
        status: "loaded",
        source: this.#workspaceSource(
          entry,
          outcome.source.view,
          rawFocus(outcome.source.view.focus).display,
          key,
        ),
      } as const;
    });
    const load = { targetKey: key, promise };
    this.#pathLoads.set(path, load);
    void promise.finally(() => {
      if (this.#pathLoads.get(path) === load) {
        this.#pathLoads.delete(path);
      }
    });
    return promise;
  }

  async #ensureProjection(entry: FileEntry, target: SourceTarget): Promise<WorkspaceOutcome> {
    if (target.fragment === null) {
      const source = this.inspect(target);
      return source === null ? { status: "failed" } : { status: "loaded", source };
    }
    const path = target.unit.path;
    const revision = entry.revision;
    const requestKey = JSON.stringify([path, sourceTargetKey(target), revision]);
    const pending = this.#projectionLoads.get(requestKey);
    if (pending !== undefined) {
      return pending;
    }

    const promise = this.#transport
      .project(target, entry.currentText, this.#controller.signal)
      .then((outcome): WorkspaceOutcome => {
        if (!this.#alive || entry.revision !== revision) {
          return { status: "stale" };
        }
        if (outcome.status !== "loaded") {
          return transportOutcome(outcome);
        }
        if (!this.#acceptView(entry, target, revision, outcome.view)) {
          return { status: "failed" };
        }
        if (!stableProjection(outcome.view)) {
          return {
            status: "loaded",
            source: this.#workspaceSource(
              entry,
              outcome.view,
              rawFocus(outcome.view.focus).display,
              sourceTargetKey(target),
            ),
          };
        }
        const source = this.inspect(target);
        if (source === null) {
          return { status: "failed" };
        }
        this.#notifyPath(path);
        return { status: "loaded", source };
      });
    this.#projectionLoads.set(requestKey, promise);
    void promise.finally(() => {
      if (this.#projectionLoads.get(requestKey) === promise) {
        this.#projectionLoads.delete(requestKey);
      }
    });
    return promise;
  }

  #acceptView(entry: FileEntry, target: SourceTarget, revision: number, view: SourceView): boolean {
    if (
      view.unit !== target.unit.id ||
      view.kind !== target.unit.kind ||
      view.fragment?.id !== target.fragment?.id ||
      view.fragment?.label !== target.fragment?.label ||
      sourceCurrentText(view) !== entry.currentText
    ) {
      return false;
    }
    if (stableProjection(view)) {
      entry.views.set(sourceTargetKey(target), { revision, view: cloneView(view) });
    }
    return true;
  }

  #workspaceSource(
    entry: FileEntry,
    view: SourceView,
    focusDisplay: string | null,
    targetKey: string,
  ): WorkspaceSource {
    return {
      path: entry.file.path,
      view: cloneView(view),
      editor:
        view.editable && focusDisplay !== null
          ? {
              path: entry.file.path,
              targetKey,
              revision: entry.revision,
              display: focusDisplay,
            }
          : null,
      dirty: this.#dirty(entry),
    };
  }

  #dirty(entry: FileEntry): boolean {
    return !exactBytesEqual(encoder.encode(entry.currentText), entry.loadBytes);
  }

  #notifyPath(path: string): void {
    for (const subscriber of this.#pathSubscribers.get(path) ?? []) {
      subscriber();
    }
  }

  #notifyGlobal(): void {
    for (const subscriber of this.#globalSubscribers) {
      subscriber();
    }
  }
}
