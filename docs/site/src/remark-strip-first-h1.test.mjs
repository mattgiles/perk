import assert from "node:assert/strict";
import { test } from "node:test";
import remarkStripFirstH1 from "./remark-strip-first-h1.mjs";

const transform = remarkStripFirstH1();

function heading(depth, text) {
  return { type: "heading", depth, children: [{ type: "text", value: text }] };
}

function paragraph(text) {
  return { type: "paragraph", children: [{ type: "text", value: text }] };
}

test("removes only the first top-level depth-1 heading", () => {
  const first = heading(1, "First");
  const second = heading(1, "Second");
  const tree = { type: "root", children: [first, paragraph("intro"), second] };
  transform(tree);
  assert.deepEqual(tree.children, [paragraph("intro"), second]);
});

test("leaves deeper headings alone", () => {
  const h2 = heading(2, "Section");
  const h3 = heading(3, "Subsection");
  const tree = { type: "root", children: [h2, h3] };
  transform(tree);
  assert.deepEqual(tree.children, [h2, h3]);
});

test("no-op on trees without an H1", () => {
  const children = [paragraph("a"), heading(2, "b"), paragraph("c")];
  const tree = { type: "root", children: [...children] };
  transform(tree);
  assert.deepEqual(tree.children, children);
});

test("preserves sibling order around the removed heading", () => {
  const before = paragraph("before");
  const after = paragraph("after");
  const tree = { type: "root", children: [before, heading(1, "Title"), after] };
  transform(tree);
  assert.deepEqual(tree.children, [before, after]);
});

test("does not descend: a depth-1 heading nested inside another node is untouched", () => {
  const nested = { type: "blockquote", children: [heading(1, "Quoted title")] };
  const tree = { type: "root", children: [nested, heading(1, "Real title")] };
  transform(tree);
  assert.deepEqual(tree.children, [nested]);
});
