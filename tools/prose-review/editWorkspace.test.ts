import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate as tick } from "node:timers/promises";
import { EditWorkspace, type WorkspaceTransport } from "./src/editWorkspace.ts";
import { CATALOG_STALE_DETAIL, CONFLICT_DETAIL, NOT_SENT_DETAIL } from "./src/save.ts";
import type { SourceSaveLoadOutcome } from "./src/saveLoad.ts";
import type { SourceTarget } from "./src/selection.ts";
import type { NewlineStyle, ReadOnlyReason, SourceView, UnitSource } from "./src/source.ts";
import type { SourceLoadOutcome, SourceProjectionOutcome } from "./src/sourceLoad.ts";
import type { UnitRef } from "./src/tree.ts";

const HASH = "0123456789abcdef".repeat(4);
const UNIT_A: UnitRef = { id: "unit:a", kind: "markdown", path: "shared.md" };
const UNIT_ALIAS: UnitRef = { id: "unit:alias", kind: "markdown", path: "shared.md" };
const UNIT_B: UnitRef = { id: "unit:b", kind: "markdown", path: "other.md" };
const UNIT_C: UnitRef = { id: "unit:c", kind: "markdown", path: "third.md" };
const FRAGMENT_A = { id: "a", label: "Fragment A" };
const FRAGMENT_B = { id: "b", label: "Fragment B" };
const TARGET_A: SourceTarget = { unit: UNIT_A, fragment: FRAGMENT_A };
const TARGET_ALIAS: SourceTarget = { unit: UNIT_ALIAS, fragment: FRAGMENT_B };
const WHOLE_A: SourceTarget = { unit: UNIT_A, fragment: null };
const WHOLE_B: SourceTarget = { unit: UNIT_B, fragment: null };
const WHOLE_ALIAS: SourceTarget = { unit: UNIT_ALIAS, fragment: null };
const TARGET_B: SourceTarget = { unit: UNIT_B, fragment: FRAGMENT_B };
const TARGET_C: SourceTarget = {
  unit: UNIT_C,
  fragment: { id: "c", label: "Fragment C" },
};

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

function editableView(
  target: SourceTarget,
  text: string,
  focus: string,
  occurrence = 0,
): SourceView {
  assert.ok(target.fragment !== null);
  let start = -1;
  let offset = 0;
  for (let index = 0; index <= occurrence; index += 1) {
    start = text.indexOf(focus, offset);
    assert.notEqual(start, -1);
    offset = start + focus.length;
  }
  return {
    unit: target.unit.id,
    fragment: target.fragment,
    kind: target.unit.kind,
    before: text.slice(0, start),
    focus,
    after: text.slice(start + focus.length),
    editable: true,
    read_only_reason: null,
  };
}

function wholeView(target: SourceTarget, text: string): SourceView {
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

function readOnlyView(target: SourceTarget, text: string, reason: ReadOnlyReason): SourceView {
  return {
    unit: target.unit.id,
    fragment: target.fragment,
    kind: target.unit.kind,
    before: "",
    focus: text,
    after: "",
    editable: false,
    read_only_reason: reason,
  };
}

function loadOutcome(
  target: SourceTarget,
  text: string,
  view: SourceView,
  options: { mode?: number; newlineStyle?: NewlineStyle; hash?: string } = {},
): SourceLoadOutcome {
  assert.equal(view.before + view.focus + view.after, text);
  return {
    status: "loaded",
    source: {
      file: {
        path: target.unit.path,
        mode: options.mode ?? 0o644,
        newline_style: options.newlineStyle ?? "lf",
        load_hash: options.hash ?? HASH,
      },
      view,
    },
  };
}

function immediateTransport(
  loads: (target: SourceTarget) => SourceLoadOutcome,
  projections: (target: SourceTarget, text: string) => SourceProjectionOutcome = () => ({
    status: "failed",
  }),
): WorkspaceTransport {
  return {
    load: (target) => Promise.resolve(loads(target)),
    project: (target, text) => Promise.resolve(projections(target, text)),
  };
}

async function loadedWorkspace(
  text: string,
  view: SourceView,
  options: { mode?: number; newlineStyle?: NewlineStyle; hash?: string } = {},
): Promise<EditWorkspace> {
  const workspace = new EditWorkspace(
    immediateTransport((target) => loadOutcome(target, text, view, options)),
  );
  assert.equal((await workspace.ensure(TARGET_A)).status, "loaded");
  return workspace;
}

function applyEdit(workspace: EditWorkspace, target: SourceTarget, nextDisplay: string): void {
  const source = workspace.inspect(target);
  assert.ok(source?.editor !== null && source?.editor !== undefined);
  assert.deepEqual(workspace.editFocus({ target, base: source.editor, nextDisplay }), {
    status: "applied",
  });
}

function savedOutcome(
  target: SourceTarget,
  hash: string,
  catalogRefreshed = true,
): SourceSaveLoadOutcome {
  return {
    status: "loaded",
    result: {
      status: "saved",
      source: {
        unit: target.unit.id,
        kind: target.unit.kind,
        file: {
          path: target.unit.path,
          mode: 0o6751,
          newline_style: "lf",
          load_hash: hash,
        },
      },
      materialized: [],
      checks: [{ id: "prose-map", command: "perk-dev prose-map check" }],
      catalog_refreshed: catalogRefreshed,
      refresh_detail: catalogRefreshed ? null : CATALOG_STALE_DETAIL,
    },
  };
}

test("one path entry coalesces canonical loads across unit ids while paths stay independent", async () => {
  const first = deferred<SourceLoadOutcome>();
  const second = deferred<SourceLoadOutcome>();
  const loadCalls: SourceTarget[] = [];
  const transport: WorkspaceTransport = {
    load: (target) => {
      loadCalls.push(target);
      return target.unit.path === "shared.md" ? first.promise : second.promise;
    },
    project: () => Promise.resolve({ status: "failed" }),
  };
  const workspace = new EditWorkspace(transport);
  const pendingA = workspace.ensure(TARGET_A);
  const pendingAlias = workspace.ensure(WHOLE_ALIAS);
  assert.equal(loadCalls.length, 1);

  const text = "before A after";
  first.resolve(loadOutcome(TARGET_A, text, editableView(TARGET_A, text, "A")));
  assert.equal((await pendingA).status, "loaded");
  const alias = await pendingAlias;
  assert.equal(alias.status, "loaded");
  assert.equal(alias.status === "loaded" ? alias.source.view.unit : null, UNIT_ALIAS.id);
  assert.equal(alias.status === "loaded" ? alias.source.view.focus : null, text);
  assert.equal(loadCalls.length, 1);

  const pendingB = workspace.ensure(TARGET_B);
  assert.equal(loadCalls.length, 2);
  second.resolve(loadOutcome(TARGET_B, "other B", editableView(TARGET_B, "other B", "B")));
  assert.equal((await pendingB).status, "loaded");
  assert.equal(workspace.snapshot("shared.md")?.currentText, text);
  assert.equal(workspace.snapshot("other.md")?.currentText, "other B");
});

test("canonical loads reject a mismatched response path before initializing an entry", async () => {
  const text = "before A after";
  let calls = 0;
  const workspace = new EditWorkspace({
    load: (target) => {
      calls += 1;
      const outcome = loadOutcome(target, text, editableView(target, text, "A"));
      if (calls === 1 && outcome.status === "loaded") {
        return Promise.resolve({
          ...outcome,
          source: { ...outcome.source, file: { ...outcome.source.file, path: "wrong.md" } },
        });
      }
      return Promise.resolve(outcome);
    },
    project: () => Promise.resolve({ status: "failed" }),
  });

  assert.deepEqual(await workspace.ensure(TARGET_A), { status: "failed" });
  assert.equal(workspace.snapshot("shared.md"), null);
  assert.equal((await workspace.ensure(TARGET_A)).status, "loaded");
  assert.equal(calls, 2);
});

test("inspection and transport values cannot mutate workspace authority", async () => {
  const text = "before A after";
  const outcome = loadOutcome(TARGET_A, text, editableView(TARGET_A, text, "A"), {
    mode: 0o751,
  });
  const workspace = new EditWorkspace(immediateTransport(() => outcome));
  const loaded = await workspace.ensure(TARGET_A);
  assert.equal(loaded.status, "loaded");
  assert.equal(outcome.status, "loaded");
  if (loaded.status !== "loaded" || outcome.status !== "loaded") {
    return;
  }

  outcome.source.file.mode = 0;
  outcome.source.view.focus = "transport mutation";
  loaded.source.view.focus = "inspection mutation";
  assert.ok(loaded.source.view.fragment !== null);
  loaded.source.view.fragment.id = "changed";

  assert.equal(workspace.snapshot("shared.md")?.mode, 0o751);
  assert.equal(workspace.inspect(TARGET_A)?.view.focus, "A");
  assert.equal(workspace.inspect(TARGET_A)?.view.fragment?.id, FRAGMENT_A.id);
});

test("projection promises coalesce by path, target, and revision", async () => {
  const projection = deferred<SourceProjectionOutcome>();
  let projectCalls = 0;
  const text = "A and B";
  const workspace = new EditWorkspace({
    load: (target) => Promise.resolve(loadOutcome(target, text, wholeView(target, text))),
    project: () => {
      projectCalls += 1;
      return projection.promise;
    },
  });
  await workspace.ensure(WHOLE_A);
  const first = workspace.ensure(TARGET_ALIAS);
  const second = workspace.ensure(TARGET_ALIAS);
  assert.equal(projectCalls, 1);
  projection.resolve({ status: "loaded", view: editableView(TARGET_ALIAS, text, "B") });
  assert.equal((await first).status, "loaded");
  assert.equal((await second).status, "loaded");
  assert.equal(projectCalls, 1);
});

test("same-revision projections must reconstruct current text before caching", async () => {
  const text = "A then B";
  let calls = 0;
  const workspace = new EditWorkspace({
    load: (target) => Promise.resolve(loadOutcome(target, text, wholeView(target, text))),
    project: (target, current) => {
      calls += 1;
      const projected = calls === 1 ? "wrong B" : current;
      return Promise.resolve({
        status: "loaded",
        view: editableView(target, projected, "B"),
      });
    },
  });
  await workspace.ensure(WHOLE_A);

  assert.deepEqual(await workspace.ensure(TARGET_ALIAS), { status: "failed" });
  assert.equal(workspace.inspect(TARGET_ALIAS), null);
  assert.equal((await workspace.ensure(TARGET_ALIAS)).status, "loaded");
  assert.equal(workspace.inspect(TARGET_ALIAS)?.view.focus, "B");
  assert.equal(calls, 2);
});

test("unsubscribing a requester never cancels a shared load needed later", async () => {
  const load = deferred<SourceLoadOutcome>();
  const capturedSignals: AbortSignal[] = [];
  const workspace = new EditWorkspace({
    load: (_target, signal) => {
      capturedSignals.push(signal);
      return load.promise;
    },
    project: () => Promise.resolve({ status: "failed" }),
  });
  let notifications = 0;
  const unsubscribe = workspace.subscribePath("shared.md", () => {
    notifications += 1;
  });
  const pending = workspace.ensure(TARGET_A);
  unsubscribe();
  assert.equal(capturedSignals[0]?.aborted, false);
  const text = "before A after";
  load.resolve(loadOutcome(TARGET_A, text, editableView(TARGET_A, text, "A")));
  assert.equal((await pending).status, "loaded");
  assert.equal(notifications, 0);
  assert.equal(workspace.inspect(TARGET_A)?.view.focus, "A");
});

test("stale projection results never enter a newer revision cache", async () => {
  const stale = deferred<SourceProjectionOutcome>();
  let projectionCalls = 0;
  const text = "A then B";
  const workspace = new EditWorkspace({
    load: (target) => Promise.resolve(loadOutcome(target, text, editableView(TARGET_A, text, "A"))),
    project: (target, current) => {
      projectionCalls += 1;
      if (projectionCalls === 1) {
        return stale.promise;
      }
      return Promise.resolve({ status: "loaded", view: editableView(target, current, "B") });
    },
  });
  await workspace.ensure(TARGET_A);
  const pending = workspace.ensure(TARGET_ALIAS);
  applyEdit(workspace, TARGET_A, "AA");
  stale.resolve({ status: "loaded", view: editableView(TARGET_ALIAS, text, "B") });
  assert.deepEqual(await pending, { status: "stale" });
  assert.equal(workspace.inspect(TARGET_ALIAS), null);
  assert.equal((await workspace.ensure(TARGET_ALIAS)).status, "loaded");
  assert.equal(projectionCalls, 2);
});

test("dispose aborts owned requests and makes late outcomes no-ops", async () => {
  const load = deferred<SourceLoadOutcome>();
  const signals: AbortSignal[] = [];
  let notifications = 0;
  const workspace = new EditWorkspace({
    load: (_target, currentSignal) => {
      signals.push(currentSignal);
      return load.promise;
    },
    project: () => Promise.resolve({ status: "failed" }),
  });
  workspace.subscribeGlobal(() => {
    notifications += 1;
  });
  const pending = workspace.ensure(TARGET_A);
  const pendingOther = workspace.ensure(TARGET_B);
  assert.equal(signals.length, 2);
  assert.equal(signals[0], signals[1]);
  workspace.dispose();
  assert.equal(signals[0]?.aborted, true);
  const text = "before A after";
  load.resolve(loadOutcome(TARGET_A, text, editableView(TARGET_A, text, "A")));
  assert.deepEqual(await pending, { status: "stale" });
  assert.deepEqual(await pendingOther, { status: "stale" });
  assert.equal(workspace.snapshot("shared.md"), null);
  assert.equal(notifications, 0);
  assert.deepEqual(await workspace.ensure(TARGET_A), { status: "failed" });
});

test("load text and byte snapshots preserve BOM, astral Unicode, metadata, and defensive copies", async () => {
  const text = "\ufeffno terminal newline 😀";
  const workspace = await loadedWorkspace(text, editableView(TARGET_A, text, "😀"), {
    mode: 0o6751,
    newlineStyle: "none",
    hash: "a".repeat(64),
  });
  const snapshot = workspace.snapshot("shared.md");
  assert.ok(snapshot !== null);
  assert.equal(snapshot.loadText, text);
  assert.equal(new TextDecoder("utf-8", { ignoreBOM: true }).decode(snapshot.loadBytes), text);
  assert.equal(new TextDecoder("utf-8", { ignoreBOM: true }).decode(snapshot.currentBytes), text);
  assert.equal(snapshot.mode, 0o6751);
  assert.equal(snapshot.newlineStyle, "none");
  assert.equal(snapshot.loadHash, "a".repeat(64));
  assert.equal(snapshot.dirty, false);

  snapshot.loadBytes[0] = 0;
  snapshot.currentBytes[0] = 0;
  const later = workspace.snapshot("shared.md");
  assert.ok(later !== null);
  assert.equal(new TextDecoder("utf-8", { ignoreBOM: true }).decode(later.loadBytes), text);
  const currentBytes = later.currentBytes;
  currentBytes[0] = 0;
  assert.equal(
    new TextDecoder("utf-8", { ignoreBOM: true }).decode(
      workspace.snapshot("shared.md")?.currentBytes ?? new Uint8Array(),
    ),
    text,
  );
});

test("dirty state is byte-exact and exact visible reversion becomes clean", async () => {
  const text = "before α\r\nFocus 😀\rafter";
  const workspace = await loadedWorkspace(text, editableView(TARGET_A, text, "Focus 😀\r"), {
    newlineStyle: "mixed",
  });
  applyEdit(workspace, TARGET_A, "Changed 😀\n");
  assert.equal(workspace.snapshot("shared.md")?.dirty, true);
  assert.equal(workspace.dirtyFiles().length, 1);
  applyEdit(workspace, TARGET_A, "Focus 😀\n");
  assert.equal(workspace.snapshot("shared.md")?.currentText, text);
  assert.equal(workspace.snapshot("shared.md")?.dirty, false);
  assert.deepEqual(workspace.dirtyFiles(), []);
});

for (const [style, terminator] of [
  ["lf", "\n"],
  ["crlf", "\r\n"],
  ["cr", "\r"],
] as const) {
  test(`inserted display breaks use loaded ${style} style`, async () => {
    const text = `context${terminator}ab`;
    const workspace = await loadedWorkspace(text, editableView(TARGET_A, text, "ab"), {
      newlineStyle: style,
    });
    applyEdit(workspace, TARGET_A, "a\nb");
    assert.equal(workspace.inspect(TARGET_A)?.view.focus, `a${terminator}b`);
  });
}

test("mixed raw boundaries survive repeated-text non-newline edits and raw lens growth", async () => {
  const focus = "one\r\ntwo\rrepeat\nrepeat";
  const text = `head\n${focus}\r\ntail`;
  const workspace = await loadedWorkspace(text, editableView(TARGET_A, text, focus), {
    newlineStyle: "mixed",
  });
  applyEdit(workspace, TARGET_A, "one\nTWO\nrepeat\nrepeat\nnew");
  assert.equal(workspace.inspect(TARGET_A)?.view.focus, "one\r\nTWO\rrepeat\nrepeat\r\nnew");
  assert.equal(workspace.inspect(TARGET_A)?.view.after, "\r\ntail");
});

test("inserted breaks fall back from an empty mixed focus to current text, then LF", async () => {
  const mixedText = "head\rab\ntail";
  const mixed = await loadedWorkspace(mixedText, editableView(TARGET_A, mixedText, "ab"), {
    newlineStyle: "mixed",
  });
  applyEdit(mixed, TARGET_A, "a\nb");
  assert.equal(mixed.inspect(TARGET_A)?.view.focus, "a\rb");

  const plain = await loadedWorkspace("ab", editableView(TARGET_A, "ab", "ab"), {
    newlineStyle: "none",
  });
  applyEdit(plain, TARGET_A, "a\nb");
  assert.equal(plain.inspect(TARGET_A)?.view.focus, "a\nb");
});

test("one protected lens survives invalid syntax while every other target re-projects", async () => {
  const text = "A then B";
  let projectionCalls = 0;
  let bProjection: SourceProjectionOutcome = {
    status: "loaded",
    view: editableView(TARGET_ALIAS, text, "B"),
  };
  const workspace = new EditWorkspace({
    load: (target) => Promise.resolve(loadOutcome(target, text, editableView(TARGET_A, text, "A"))),
    project: () => {
      projectionCalls += 1;
      return Promise.resolve(bProjection);
    },
  });
  await workspace.ensure(TARGET_A);
  await workspace.ensure(TARGET_ALIAS);
  assert.equal(projectionCalls, 1);
  assert.equal(workspace.inspect(TARGET_ALIAS)?.view.focus, "B");

  applyEdit(workspace, TARGET_A, "invalid {{{");
  assert.equal(workspace.inspect(TARGET_A)?.editor?.display, "invalid {{{");
  assert.equal(workspace.inspect(TARGET_ALIAS), null);
  bProjection = {
    status: "loaded",
    view: readOnlyView(TARGET_ALIAS, "invalid {{{ then B", "invalid-source"),
  };
  const invalid = await workspace.ensure(TARGET_ALIAS);
  assert.equal(
    invalid.status === "loaded" ? invalid.source.view.read_only_reason : null,
    "invalid-source",
  );
  assert.equal(projectionCalls, 2);
  assert.equal((await workspace.ensure(TARGET_ALIAS)).status, "loaded");
  assert.equal(projectionCalls, 2, "stable read-only projections cache for their exact revision");
  assert.equal(workspace.inspect(TARGET_A)?.editor?.display, "invalid {{{");

  assert.equal(workspace.snapshot("shared.md")?.currentText, "invalid {{{ then B");
  applyEdit(workspace, TARGET_A, "valid A");
  const validCurrent = workspace.snapshot("shared.md")?.currentText;
  assert.equal(validCurrent, "valid A then B");
  bProjection = { status: "loaded", view: editableView(TARGET_ALIAS, validCurrent, "B") };
  assert.equal((await workspace.ensure(TARGET_ALIAS)).status, "loaded");
  assert.equal(projectionCalls, 3, "a new revision invalidates the prior stable projection");
  applyEdit(workspace, TARGET_ALIAS, "edited B");
  assert.equal(workspace.inspect(TARGET_A), null);
  assert.equal(workspace.inspect(TARGET_ALIAS)?.editor?.display, "edited B");
  assert.equal(workspace.dirtyFiles()[0]?.target.unit.id, UNIT_ALIAS.id);
});

test("revision-bound edit commands reject stale editor snapshots", async () => {
  const text = "before A after";
  const workspace = await loadedWorkspace(text, editableView(TARGET_A, text, "A"));
  const initial = workspace.inspect(TARGET_A)?.editor;
  assert.ok(initial !== null && initial !== undefined);

  applyEdit(workspace, TARGET_A, "AA");
  assert.deepEqual(
    workspace.editFocus({ target: TARGET_A, base: initial, nextDisplay: "stale edit" }),
    { status: "stale" },
  );
  assert.equal(workspace.snapshot("shared.md")?.currentText, "before AA after");
});

test("adapter-unavailable is transient, uncached, and retried only by another ensure", async () => {
  const text = "A then B";
  let calls = 0;
  const workspace = new EditWorkspace({
    load: (target) => Promise.resolve(loadOutcome(target, text, wholeView(target, text))),
    project: (target) => {
      calls += 1;
      if (calls < 3) {
        return Promise.resolve({
          status: "loaded",
          view: readOnlyView(target, text, "adapter-unavailable"),
        });
      }
      return Promise.resolve({ status: "loaded", view: editableView(target, text, "B") });
    },
  });
  await workspace.ensure(WHOLE_A);
  const first = await workspace.ensure(TARGET_ALIAS);
  assert.equal(
    first.status === "loaded" ? first.source.view.read_only_reason : null,
    "adapter-unavailable",
  );
  assert.equal(workspace.inspect(TARGET_ALIAS), null);
  assert.equal(calls, 1);
  await Promise.resolve();
  assert.equal(calls, 1);
  assert.equal((await workspace.ensure(TARGET_ALIAS)).status, "loaded");
  assert.equal(calls, 2);
  assert.equal(workspace.inspect(TARGET_ALIAS), null);
  const recovered = await workspace.ensure(TARGET_ALIAS);
  assert.equal(recovered.status, "loaded");
  assert.equal(calls, 3);
  assert.equal(workspace.inspect(TARGET_ALIAS)?.view.editable, true);
});

test("stale helper overlap recovers the latest target only after explicit retry", async () => {
  const held = deferred<SourceProjectionOutcome>();
  const text = "A then B";
  let calls = 0;
  const workspace = new EditWorkspace({
    load: (target) => Promise.resolve(loadOutcome(target, text, editableView(TARGET_A, text, "A"))),
    project: (target, current) => {
      calls += 1;
      if (calls === 1) {
        return held.promise;
      }
      if (calls === 2) {
        return Promise.resolve({
          status: "loaded",
          view: readOnlyView(target, current, "adapter-unavailable"),
        });
      }
      return Promise.resolve({ status: "loaded", view: editableView(target, current, "B") });
    },
  });
  await workspace.ensure(TARGET_A);
  const stale = workspace.ensure(TARGET_ALIAS);
  applyEdit(workspace, TARGET_A, "AA");

  const busy = await workspace.ensure(TARGET_ALIAS);
  assert.equal(busy.status, "loaded");
  assert.equal(
    busy.status === "loaded" ? busy.source.view.read_only_reason : null,
    "adapter-unavailable",
  );
  assert.equal(workspace.inspect(TARGET_ALIAS), null);

  held.resolve({ status: "loaded", view: editableView(TARGET_ALIAS, text, "B") });
  assert.deepEqual(await stale, { status: "stale" });
  assert.equal(workspace.inspect(TARGET_ALIAS), null);

  assert.equal((await workspace.ensure(TARGET_ALIAS)).status, "loaded");
  assert.equal(workspace.inspect(TARGET_ALIAS)?.editor?.display, "B");
  assert.equal(workspace.snapshot("shared.md")?.currentText, "AA then B");
  assert.equal(calls, 3);
});

test("whole-unit aliases immediately expose edited current text without another load", async () => {
  const text = "before A after";
  let loads = 0;
  const workspace = new EditWorkspace(
    immediateTransport((target) => {
      loads += 1;
      return loadOutcome(target, text, editableView(TARGET_A, text, "A"));
    }),
  );
  await workspace.ensure(TARGET_A);
  applyEdit(workspace, TARGET_A, "edited A");
  const alias = await workspace.ensure(WHOLE_ALIAS);
  assert.equal(alias.status, "loaded");
  assert.equal(alias.status === "loaded" ? alias.source.view.focus : null, "before edited A after");
  assert.equal(loads, 1);
});

test("last-edited dirty summaries sort by path and discard restores only one immutable load", async () => {
  const loads: UnitSource[] = [];
  const texts = new Map([
    ["shared.md", "before A after"],
    ["other.md", "other B tail"],
  ]);
  const workspace = new EditWorkspace(
    immediateTransport((target) => {
      const text = texts.get(target.unit.path) ?? "";
      const view = editableView(target, text, target === TARGET_A ? "A" : "B");
      const outcome = loadOutcome(target, text, view, {
        mode: target === TARGET_A ? 0o755 : 0o640,
        newlineStyle: "none",
      });
      if (outcome.status === "loaded") {
        loads.push(outcome.source);
      }
      return outcome;
    }),
  );
  await workspace.ensure(TARGET_A);
  await workspace.ensure(TARGET_B);
  applyEdit(workspace, TARGET_A, "edited A");
  applyEdit(workspace, TARGET_B, "edited B");
  assert.deepEqual(
    workspace.dirtyFiles().map((summary) => [summary.path, summary.target.unit.id]),
    [
      ["other.md", "unit:b"],
      ["shared.md", "unit:a"],
    ],
  );

  const beforeDiscard = workspace.snapshot("shared.md");
  assert.ok(beforeDiscard !== null);
  assert.equal(workspace.discard("shared.md"), true);
  const afterDiscard = workspace.snapshot("shared.md");
  assert.ok(afterDiscard !== null);
  assert.equal(afterDiscard.currentText, beforeDiscard.loadText);
  assert.equal(afterDiscard.mode, beforeDiscard.mode);
  assert.equal(afterDiscard.loadHash, beforeDiscard.loadHash);
  assert.equal(afterDiscard.revision, beforeDiscard.revision + 1);
  assert.deepEqual(
    workspace.dirtyFiles().map((summary) => summary.path),
    ["other.md"],
  );
  assert.equal(workspace.snapshot("other.md")?.dirty, true);
  assert.equal(loads.length, 2);
});

test("path and global subscribers are notified synchronously on edits and discard", async () => {
  const text = "before A after";
  const workspace = await loadedWorkspace(text, editableView(TARGET_A, text, "A"));
  const events: string[] = [];
  const unsubscribePath = workspace.subscribePath("shared.md", () => events.push("path"));
  const unsubscribeGlobal = workspace.subscribeGlobal(() => events.push("global"));
  applyEdit(workspace, TARGET_A, "AA");
  assert.deepEqual(events, ["path", "global"]);
  events.length = 0;
  workspace.discard("shared.md");
  assert.deepEqual(events, ["path", "global"]);
  unsubscribePath();
  unsubscribeGlobal();
});

test("review is revision-bound and saving locks only its path before baseline adoption", async () => {
  const firstText = "before A after";
  const secondText = "other B tail";
  const pendingSave = deferred<SourceSaveLoadOutcome>();
  const workspace = new EditWorkspace({
    load: (target) => {
      const text = target.unit.path === UNIT_A.path ? firstText : secondText;
      const focus = target.unit.path === UNIT_A.path ? "A" : "B";
      return Promise.resolve(loadOutcome(target, text, editableView(target, text, focus)));
    },
    project: (target, text) => {
      const focus = target.unit.path === UNIT_A.path ? "saved A" : "edited B";
      return Promise.resolve({ status: "loaded", view: editableView(target, text, focus) });
    },
    save: () => pendingSave.promise,
  });
  await workspace.ensure(TARGET_A);
  await workspace.ensure(TARGET_B);
  applyEdit(workspace, TARGET_A, "saved A");
  applyEdit(workspace, TARGET_B, "edited B");

  const reviewed = workspace.beginSaveReview(UNIT_A.path);
  assert.equal(reviewed.status, "reviewed");
  const pending = workspace.saveReviewed(UNIT_A.path);
  assert.equal(workspace.inspect(TARGET_A)?.saveState.status, "saving");
  const firstEditor = workspace.inspect(TARGET_A)?.editor;
  assert.ok(firstEditor !== null && firstEditor !== undefined);
  assert.deepEqual(
    workspace.editFocus({ target: TARGET_A, base: firstEditor, nextDisplay: "blocked" }),
    { status: "refused" },
  );
  assert.equal(workspace.discard(UNIT_A.path), false);
  assert.deepEqual(await workspace.saveReviewed(UNIT_A.path), { status: "refused" });
  applyEdit(workspace, TARGET_B, "other path remains editable");

  const newHash = "f".repeat(64);
  pendingSave.resolve(savedOutcome(TARGET_A, newHash));
  assert.deepEqual(await pending, { status: "completed" });
  const snapshot = workspace.snapshot(UNIT_A.path);
  assert.equal(snapshot?.currentText, "before saved A after");
  assert.equal(snapshot?.loadText, "before saved A after");
  assert.equal(snapshot?.loadHash, newHash);
  assert.equal(snapshot?.mode, 0o6751);
  assert.equal(snapshot?.dirty, false);
  assert.equal(workspace.inspect(WHOLE_A)?.saveState.status, "saved");
  assert.equal(
    workspace.snapshot(UNIT_B.path)?.currentText,
    "other other path remains editable tail",
  );
});

test("validation, refusal, not-sent, and refresh-failed outcomes keep exact retry rules", async () => {
  const text = "before A after";
  const outcomes: SourceSaveLoadOutcome[] = [
    { status: "not-sent" },
    {
      status: "loaded",
      result: {
        status: "validation-failed",
        diagnostics: [
          {
            code: "selector-not-found",
            message: "missing",
            selector: "heading:missing",
            line: null,
            column: null,
          },
        ],
      },
    },
    {
      status: "loaded",
      result: { status: "refused", reason: "unsafe-path", detail: "unsafe" },
    },
  ];
  const workspace = new EditWorkspace({
    load: (target) => Promise.resolve(loadOutcome(target, text, editableView(target, text, "A"))),
    project: (target, current) =>
      Promise.resolve({ status: "loaded", view: editableView(target, current, "A") }),
    save: () => Promise.resolve(outcomes.shift() ?? { status: "indeterminate" }),
  });
  await workspace.ensure(TARGET_A);
  applyEdit(workspace, TARGET_A, "edited A");

  assert.equal(workspace.beginSaveReview(UNIT_A.path).status, "reviewed");
  await workspace.saveReviewed(UNIT_A.path);
  assert.deepEqual(workspace.inspect(TARGET_A)?.saveState, {
    status: "not-sent",
    detail: NOT_SENT_DETAIL,
  });
  assert.equal(workspace.inspect(TARGET_A)?.canSave, true);

  await workspace.saveReviewed(UNIT_A.path);
  const validation = workspace.inspect(TARGET_A);
  assert.equal(validation?.saveState.status, "validation-failed");
  assert.equal(validation?.review, null);
  assert.equal(validation?.canReview, false);
  applyEdit(workspace, TARGET_A, "fixed A");
  assert.equal(workspace.inspect(TARGET_A)?.saveState.status, "idle");

  assert.equal(workspace.beginSaveReview(UNIT_A.path).status, "reviewed");
  await workspace.saveReviewed(UNIT_A.path);
  assert.equal(workspace.inspect(TARGET_A)?.saveState.status, "refused");
  assert.equal(workspace.inspect(TARGET_A)?.canReview, false);
  assert.equal(workspace.discard(UNIT_A.path), true);
  assert.equal(workspace.snapshot(UNIT_A.path)?.dirty, false);

  await workspace.ensure(TARGET_A);
  applyEdit(workspace, TARGET_A, "refresh failed A");
  assert.equal(workspace.beginSaveReview(UNIT_A.path).status, "reviewed");
  outcomes.push(savedOutcome(TARGET_A, "e".repeat(64), false));
  await workspace.saveReviewed(UNIT_A.path);
  assert.deepEqual(workspace.writeState(), {
    frozen: true,
    suspended: false,
    detail: CATALOG_STALE_DETAIL,
    catalogEpoch: 0,
  });
  assert.equal(workspace.inspect(WHOLE_A)?.saveState.status, "saved");
});

test("determinate write failure preserves the frozen review for exact same-buffer retry", async () => {
  const text = "before A after";
  const requests: Array<{ target: SourceTarget; loadHash: string; text: string }> = [];
  const outcomes: SourceSaveLoadOutcome[] = [
    {
      status: "loaded",
      result: {
        status: "refused",
        reason: "write-failed",
        detail: "The source could not be saved safely.",
      },
    },
    savedOutcome(TARGET_A, "d".repeat(64)),
  ];
  const workspace = new EditWorkspace({
    load: (target) => Promise.resolve(loadOutcome(target, text, editableView(target, text, "A"))),
    project: (target, current) =>
      Promise.resolve({ status: "loaded", view: editableView(target, current, "edited A") }),
    save: (target, loadHash, current) => {
      requests.push({ target, loadHash, text: current });
      return Promise.resolve(outcomes.shift() ?? { status: "indeterminate" });
    },
  });
  await workspace.ensure(TARGET_A);
  applyEdit(workspace, TARGET_A, "edited A");

  const reviewed = workspace.beginSaveReview(UNIT_A.path);
  assert.equal(reviewed.status, "reviewed");
  assert.equal(
    reviewed.status === "reviewed" ? reviewed.review.currentText : null,
    "before edited A after",
  );
  await workspace.saveReviewed(UNIT_A.path);

  const failed = workspace.inspect(TARGET_A);
  assert.deepEqual(failed?.saveState, {
    status: "refused",
    reason: "write-failed",
    detail: "The source could not be saved safely.",
  });
  assert.deepEqual(failed?.review, reviewed.status === "reviewed" ? reviewed.review : null);
  assert.equal(failed?.canSave, true);
  assert.equal(failed?.canReview, false);

  await workspace.saveReviewed(UNIT_A.path);

  assert.equal(requests.length, 2);
  assert.deepEqual(requests[1], requests[0]);
  assert.equal(workspace.inspect(WHOLE_A)?.saveState.status, "saved");
  assert.equal(workspace.inspect(WHOLE_A)?.review, null);
  assert.equal(workspace.snapshot(UNIT_A.path)?.dirty, false);
});

test("conflict persists across manual reversion and reload owns the path lock", async () => {
  const text = "before A after";
  const pendingReload = deferred<SourceLoadOutcome>();
  const workspace = new EditWorkspace({
    load: (target) => Promise.resolve(loadOutcome(target, text, editableView(target, text, "A"))),
    project: () => Promise.resolve({ status: "failed" }),
    save: () =>
      Promise.resolve({
        status: "loaded",
        result: { status: "conflict", detail: CONFLICT_DETAIL },
      }),
    reload: () => pendingReload.promise,
  });
  await workspace.ensure(TARGET_A);
  applyEdit(workspace, TARGET_A, "edited A");
  workspace.beginSaveReview(UNIT_A.path);
  await workspace.saveReviewed(UNIT_A.path);
  assert.equal(workspace.inspect(TARGET_A)?.saveState.status, "conflict");
  assert.equal(workspace.discard(UNIT_A.path), false);

  applyEdit(workspace, TARGET_A, "A");
  assert.equal(workspace.snapshot(UNIT_A.path)?.dirty, false);
  assert.deepEqual(
    workspace.attentionFiles().map((entry) => [entry.path, entry.dirty, entry.saveState.status]),
    [[UNIT_A.path, false, "conflict"]],
  );

  const pending = workspace.reloadConflict(UNIT_A.path);
  assert.equal(workspace.inspect(TARGET_A)?.saveState.status, "reloading");
  assert.deepEqual(await workspace.reloadConflict(UNIT_A.path), { status: "refused" });
  assert.equal(workspace.discard(UNIT_A.path), false);
  const external = "before external after";
  pendingReload.resolve(
    loadOutcome(TARGET_A, external, editableView(TARGET_A, external, "external"), {
      hash: "d".repeat(64),
    }),
  );
  assert.deepEqual(await pending, { status: "completed" });
  assert.equal(workspace.snapshot(UNIT_A.path)?.currentText, external);
  assert.equal(workspace.snapshot(UNIT_A.path)?.dirty, false);
  assert.equal(workspace.inspect(WHOLE_A)?.saveState.status, "idle");
  assert.deepEqual(workspace.attentionFiles(), []);
});

test("indeterminate reconciliation distinguishes submitted, prior, third, and retryable failure", async () => {
  const text = "before A after";

  async function reconciled(reloadOutcome: SourceLoadOutcome): Promise<EditWorkspace> {
    const workspace = new EditWorkspace({
      load: (target) => Promise.resolve(loadOutcome(target, text, editableView(target, text, "A"))),
      project: () => Promise.resolve({ status: "failed" }),
      save: () => Promise.resolve({ status: "indeterminate" }),
      reload: () => Promise.resolve(reloadOutcome),
    });
    await workspace.ensure(TARGET_A);
    applyEdit(workspace, TARGET_A, "submitted A");
    workspace.beginSaveReview(UNIT_A.path);
    await workspace.saveReviewed(UNIT_A.path);
    return workspace;
  }

  const submittedText = "before submitted A after";
  const submitted = await reconciled(
    loadOutcome(TARGET_A, submittedText, editableView(TARGET_A, submittedText, "submitted A"), {
      hash: "c".repeat(64),
    }),
  );
  assert.equal(submitted.snapshot(UNIT_A.path)?.dirty, false);
  assert.equal(submitted.inspect(WHOLE_A)?.saveState.status, "reconciled-saved");
  assert.equal(submitted.writeState().frozen, true);

  const prior = await reconciled(loadOutcome(TARGET_A, text, editableView(TARGET_A, text, "A")));
  assert.equal(prior.snapshot(UNIT_A.path)?.currentText, submittedText);
  assert.equal(prior.snapshot(UNIT_A.path)?.dirty, true);
  assert.deepEqual(prior.writeState(), {
    frozen: false,
    suspended: false,
    detail: null,
    catalogEpoch: 0,
  });
  assert.equal(prior.inspect(WHOLE_A)?.saveState.status, "idle");

  const thirdText = "before third after";
  const third = await reconciled(
    loadOutcome(TARGET_A, thirdText, editableView(TARGET_A, thirdText, "third"), {
      hash: "b".repeat(64),
    }),
  );
  assert.equal(third.snapshot(UNIT_A.path)?.currentText, submittedText);
  assert.equal(third.inspect(WHOLE_A)?.saveState.status, "conflict");
  assert.equal(third.writeState().frozen, true);

  let canonical: SourceLoadOutcome = { status: "failed" };
  const retry = new EditWorkspace({
    load: (target) => Promise.resolve(loadOutcome(target, text, editableView(target, text, "A"))),
    project: () => Promise.resolve({ status: "failed" }),
    save: () => Promise.resolve({ status: "indeterminate" }),
    reload: () => Promise.resolve(canonical),
  });
  await retry.ensure(TARGET_A);
  applyEdit(retry, TARGET_A, "submitted A");
  retry.beginSaveReview(UNIT_A.path);
  await retry.saveReviewed(UNIT_A.path);
  assert.equal(retry.inspect(TARGET_A)?.saveState.status, "indeterminate");
  assert.deepEqual(retry.writeState(), {
    frozen: false,
    suspended: true,
    detail: null,
    catalogEpoch: 0,
  });
  assert.equal(retry.discard(UNIT_A.path), false);
  canonical = loadOutcome(TARGET_A, text, editableView(TARGET_A, text, "A"));
  assert.deepEqual(await retry.reconcileSave(UNIT_A.path), { status: "completed" });
  assert.equal(retry.inspect(WHOLE_A)?.saveState.status, "idle");
  assert.equal(retry.snapshot(UNIT_A.path)?.dirty, true);
});

test("concurrent indeterminate files keep global saves suspended until every reconciliation settles", async () => {
  const texts = new Map([
    [UNIT_A.path, "before A after"],
    [UNIT_B.path, "before B after"],
    [UNIT_C.path, "before C after"],
  ]);
  const pendingSaveA = deferred<SourceSaveLoadOutcome>();
  const pendingSaveB = deferred<SourceSaveLoadOutcome>();
  const pendingReloadA = deferred<SourceLoadOutcome>();
  const pendingReloadB = deferred<SourceLoadOutcome>();
  let secondReloadB = false;
  const workspace = new EditWorkspace({
    load: (target) => {
      const text = texts.get(target.unit.path) ?? "";
      const focus = target.fragment?.id.toUpperCase() ?? text;
      return Promise.resolve(loadOutcome(target, text, editableView(target, text, focus)));
    },
    project: () => Promise.resolve({ status: "failed" }),
    save: (target) =>
      target.unit.path === UNIT_A.path ? pendingSaveA.promise : pendingSaveB.promise,
    reload: (target) => {
      if (target.unit.path === UNIT_A.path) {
        return pendingReloadA.promise;
      }
      if (!secondReloadB) {
        secondReloadB = true;
        return pendingReloadB.promise;
      }
      const text = texts.get(UNIT_B.path) ?? "";
      return Promise.resolve(loadOutcome(TARGET_B, text, editableView(TARGET_B, text, "B")));
    },
  });
  await workspace.ensure(TARGET_A);
  await workspace.ensure(TARGET_B);
  await workspace.ensure(TARGET_C);
  applyEdit(workspace, TARGET_A, "submitted A");
  applyEdit(workspace, TARGET_B, "submitted B");
  applyEdit(workspace, TARGET_C, "editable C");
  workspace.beginSaveReview(UNIT_A.path);
  workspace.beginSaveReview(UNIT_B.path);
  const saveA = workspace.saveReviewed(UNIT_A.path);
  const saveB = workspace.saveReviewed(UNIT_B.path);
  pendingSaveA.resolve({ status: "indeterminate" });
  pendingSaveB.resolve({ status: "indeterminate" });
  await tick();

  assert.equal(workspace.inspect(TARGET_A)?.saveState.status, "reconciling");
  assert.equal(workspace.inspect(TARGET_B)?.saveState.status, "reconciling");
  assert.equal(workspace.writeState().suspended, true);
  const editorA = workspace.inspect(TARGET_A)?.editor;
  assert.ok(editorA !== null && editorA !== undefined);
  assert.deepEqual(
    workspace.editFocus({ target: TARGET_A, base: editorA, nextDisplay: "blocked A" }),
    { status: "refused" },
  );
  assert.equal(workspace.discard(UNIT_A.path), false);
  assert.equal(workspace.beginSaveReview(UNIT_A.path).status, "refused");
  assert.deepEqual(await workspace.saveReviewed(UNIT_A.path), { status: "refused" });
  applyEdit(workspace, TARGET_C, "still editable C");
  assert.equal(workspace.beginSaveReview(UNIT_C.path).status, "refused");

  const textA = texts.get(UNIT_A.path) ?? "";
  pendingReloadA.resolve(loadOutcome(TARGET_A, textA, editableView(TARGET_A, textA, "A")));
  assert.deepEqual(await saveA, { status: "completed" });
  assert.equal(workspace.inspect(WHOLE_A)?.saveState.status, "idle");
  assert.equal(workspace.writeState().suspended, true);
  assert.equal(workspace.beginSaveReview(UNIT_C.path).status, "refused");

  pendingReloadB.resolve({ status: "failed" });
  assert.deepEqual(await saveB, { status: "completed" });
  assert.equal(workspace.inspect(TARGET_B)?.saveState.status, "indeterminate");
  assert.equal(workspace.writeState().suspended, true);
  assert.equal(workspace.snapshot(UNIT_B.path)?.currentText, "before submitted B after");

  assert.deepEqual(await workspace.reconcileSave(UNIT_B.path), { status: "completed" });
  assert.equal(workspace.inspect(WHOLE_B)?.saveState.status, "idle");
  assert.equal(workspace.writeState().suspended, false);
  assert.equal(workspace.beginSaveReview(UNIT_C.path).status, "reviewed");
});
