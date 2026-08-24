import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { parseFrontmatter } from "@astrojs/markdown-remark";
import { listCorpusFiles } from "./remark-rewrite-corpus-links.mjs";
import { sidebar } from "./sidebar.mjs";

// The sidebar agreement guard: `sidebar.mjs` must agree with the node-2.3 frontmatter records
// (`sidebar.order`, `sidebarGroup`) over the live corpus — blueprint §3 stays the
// ordering/membership SSOT, and this guard makes sidebar↔corpus drift deterministic and loud.
// Unit-level on purpose: no build involved, so it runs in the ordinary `test-js` glob.

const corpusDir = fileURLToPath(new URL("../../user-docs/", import.meta.url));

const SECTION_LABELS = ["Tutorials", "How-to guides", "Reference", "Explanation"];
const SECTION_LANDINGS = ["tutorials", "how-to", "reference", "explanation"];
const HOW_TO_GROUPS = [
  "Core workflow",
  "Objectives & learnings",
  "Headless & remote",
  "Customization",
  "Providers & backends",
];

/** Collection id for a corpus file (docs/design/archive/docs-site-bridge-spike.md slug facts). */
function slugOf(file) {
  const stem = path
    .relative(corpusDir, file)
    .split(path.sep)
    .join("/")
    .replace(/\.mdx?$/, "");
  if (stem === "index") return "index";
  return stem.endsWith("/index") ? stem.slice(0, -"/index".length) : stem;
}

/** slug → { order, sidebarGroup } parsed from the live corpus frontmatter. */
function corpusRecords() {
  const records = new Map();
  for (const file of listCorpusFiles(corpusDir)) {
    const { frontmatter } = parseFrontmatter(fs.readFileSync(file, "utf8"));
    records.set(slugOf(file), {
      order: frontmatter.sidebar?.order,
      sidebarGroup: frontmatter.sidebarGroup,
    });
  }
  return records;
}

/** Depth-first slug list of an entry/entry-array (document order). */
function flattenSlugs(entry) {
  if (typeof entry === "string") return [entry];
  if (Array.isArray(entry)) return entry.flatMap(flattenSlugs);
  if (Array.isArray(entry.items)) return entry.items.flatMap(flattenSlugs);
  return [entry.slug];
}

test("every routed corpus page appears in the sidebar exactly once (slug set equality)", () => {
  const sidebarSlugs = flattenSlugs(sidebar);
  const corpusSlugs = [...corpusRecords().keys()];
  const duplicates = sidebarSlugs.filter((slug, index) => sidebarSlugs.indexOf(slug) !== index);
  assert.deepEqual(duplicates, [], `duplicated sidebar entries: ${duplicates.join(", ")}`);
  assert.deepEqual(
    [...sidebarSlugs].sort(),
    [...corpusSlugs].sort(),
    "sidebar slugs ≠ routed corpus slugs",
  );
});

test("top-level shape: Home first, then the four §3 sections, each landing first in its group", () => {
  assert.deepEqual(sidebar[0], { label: "Home", slug: "index" });
  assert.equal(sidebar.length, 1 + SECTION_LABELS.length);
  SECTION_LABELS.forEach((label, index) => {
    const group = sidebar[1 + index];
    assert.equal(group.label, label);
    assert.ok(Array.isArray(group.items), `${label} must be a group`);
    assert.equal(group.items[0], SECTION_LANDINGS[index], `${label} landing must be first`);
  });
});

test("entries ascend by frontmatter sidebar.order within (and across) sections", () => {
  const records = corpusRecords();
  const orders = flattenSlugs(sidebar).map((slug) => {
    const record = records.get(slug);
    assert.ok(record !== undefined, `sidebar entry without a corpus page: ${slug}`);
    assert.equal(typeof record.order, "number", `missing sidebar.order for ${slug}`);
    return { slug, order: record.order };
  });
  for (let i = 1; i < orders.length; i++) {
    assert.ok(
      orders[i - 1].order < orders[i].order,
      `sidebar order regression: ${orders[i - 1].slug} (${orders[i - 1].order}) before ${orders[i].slug} (${orders[i].order})`,
    );
  }
});

test("each how-to guide sits in the subgroup named by its sidebarGroup, subgroups in §3 order", () => {
  const records = corpusRecords();
  const howTo = sidebar.find((entry) => entry.label === "How-to guides");
  const [landing, ...subgroups] = howTo.items;
  assert.equal(landing, "how-to");
  assert.deepEqual(
    subgroups.map((group) => group.label),
    HOW_TO_GROUPS,
  );
  const placed = new Set();
  for (const group of subgroups) {
    for (const slug of group.items) {
      assert.equal(typeof slug, "string", `nested groups are not §3 shapes: ${group.label}`);
      assert.equal(
        records.get(slug)?.sidebarGroup,
        group.label,
        `${slug} placed in "${group.label}" but frontmatter says "${records.get(slug)?.sidebarGroup}"`,
      );
      placed.add(slug);
    }
  }
  // Bidirectional: every corpus page claiming a sidebarGroup is placed in that subgroup.
  for (const [slug, record] of records) {
    if (record.sidebarGroup !== undefined) {
      assert.ok(placed.has(slug), `${slug} declares sidebarGroup but is not in a subgroup`);
    }
  }
});

test("outer sections are collapsed; how-to subgroups keep the uncollapsed default", () => {
  for (const section of sidebar.slice(1)) {
    assert.equal(section.collapsed, true, `section "${section.label}" must be collapsed`);
  }
  const howTo = sidebar.find((entry) => entry.label === "How-to guides");
  for (const group of howTo.items.slice(1)) {
    assert.equal(
      group.collapsed,
      undefined,
      `subgroup "${group.label}" must keep the uncollapsed default (the outer group collapses)`,
    );
  }
});

test("the Home entry is the only label override; all other pages are bare slug shorthands", () => {
  const links = [];
  const collectLinks = (entry) => {
    if (typeof entry === "string") links.push(entry);
    else if (Array.isArray(entry.items)) entry.items.forEach(collectLinks);
    else links.push(entry);
  };
  sidebar.forEach(collectLinks);
  const overrides = links.filter((link) => typeof link !== "string");
  assert.deepEqual(overrides, [{ label: "Home", slug: "index" }]);
});
