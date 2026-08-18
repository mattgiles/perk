import assert from "node:assert/strict";
import test from "node:test";
import type { Change } from "diff";
import { JSDOM } from "jsdom";
import { changedChunkIndexes, cyclePane, moveFocusInList } from "./src/keyboardNav.ts";

const dom = new JSDOM("<!doctype html><html><body></body></html>");

function element(): HTMLElement {
  const node = dom.window.document.createElement("div");
  dom.window.document.body.appendChild(node);
  return node;
}

function elementWithChild(): { parent: HTMLElement; child: HTMLElement } {
  const parent = element();
  const child = dom.window.document.createElement("button");
  parent.appendChild(child);
  return { parent, child };
}

test("cyclePane steps forward and backward with wrapping", () => {
  const [a, b, c] = [element(), element(), element()];
  assert.equal(cyclePane([a, b, c], a, 1), b);
  assert.equal(cyclePane([a, b, c], b, 1), c);
  assert.equal(cyclePane([a, b, c], c, 1), a, "forward wraps at the end");
  assert.equal(cyclePane([a, b, c], a, -1), c, "backward wraps at the start");
  assert.equal(cyclePane([a, b, c], c, -1), b);
});

test("cyclePane anchors on the pane containing the active element", () => {
  const { parent, child } = elementWithChild();
  const next = element();
  assert.equal(cyclePane([parent, next], child, 1), next);
  assert.equal(cyclePane([parent, next], child, -1), next);
});

test("cyclePane skips null panes and enters at the first pane when active is outside", () => {
  const [a, b] = [element(), element()];
  assert.equal(cyclePane([a, null, b], a, 1), b, "null panes are skipped");
  assert.equal(cyclePane([null, a, b], null, 1), a, "no active element enters the first pane");
  assert.equal(cyclePane([null, a, b], element(), -1), a, "outside active enters the first pane");
  assert.equal(cyclePane([null, null], null, 1), null, "all-null cycle has no target");
  assert.equal(cyclePane([a, null], a, 1), a, "a single mounted pane cycles to itself");
});

test("moveFocusInList steps with clamping at both ends", () => {
  const [a, b, c] = [element(), element(), element()];
  assert.equal(moveFocusInList([a, b, c], a, "ArrowDown"), b);
  assert.equal(moveFocusInList([a, b, c], b, "ArrowUp"), a);
  assert.equal(moveFocusInList([a, b, c], c, "ArrowDown"), null, "clamped at the last entry");
  assert.equal(moveFocusInList([a, b, c], a, "ArrowUp"), null, "clamped at the first entry");
});

test("moveFocusInList jumps Home/End and enters at the first entry from outside", () => {
  const [a, b, c] = [element(), element(), element()];
  assert.equal(moveFocusInList([a, b, c], b, "Home"), a);
  assert.equal(moveFocusInList([a, b, c], b, "End"), c);
  assert.equal(
    moveFocusInList([a, b, c], element(), "ArrowDown"),
    a,
    "container-focused ArrowDown enters the first entry",
  );
  assert.equal(moveFocusInList([a, b, c], null, "ArrowDown"), a);
  assert.equal(moveFocusInList([a, b, c], element(), "ArrowUp"), null);
  assert.equal(moveFocusInList([], a, "Home"), null, "an empty list handles nothing");
});

function chunk(value: string, flags: { added?: boolean; removed?: boolean } = {}): Change {
  return {
    value,
    added: flags.added ?? false,
    removed: flags.removed ?? false,
    count: 1,
  };
}

test("changedChunkIndexes lists added/removed chunk indexes in chunk order", () => {
  assert.deepEqual(
    changedChunkIndexes([
      chunk("same"),
      chunk("gone", { removed: true }),
      chunk("new", { added: true }),
      chunk("same"),
      chunk("tail", { added: true }),
    ]),
    [1, 2, 4],
  );
  assert.deepEqual(changedChunkIndexes([chunk("same"), chunk("same")]), []);
  assert.deepEqual(changedChunkIndexes([]), []);
});
