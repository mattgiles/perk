import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { parseFrontmatter } from "@astrojs/markdown-remark";
import { corpusRoute, listCorpusFiles } from "../src/remark-rewrite-corpus-links.mjs";

// Post-build checks over the static output (`astro build` must have run first — the site's
// `check` script sequences that). Deliberately OUTSIDE `src/` so the unit-test glob
// (`docs/site/src/**/*.test.mjs`) never runs these without a build.

const corpusDir = fileURLToPath(new URL("../../user-docs/", import.meta.url));
const distDir = fileURLToPath(new URL("../dist/", import.meta.url));

// The five standard HTML entities Starlight's rendering escapes in text content; titles with
// literal backticks render raw (frontmatter titles are plain text, never markdown-processed).
const ENTITIES = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'" };

function decodeEntities(text) {
  return text.replace(/&amp;|&lt;|&gt;|&quot;|&#39;/g, (entity) => ENTITIES[entity]);
}

function h1InnerText(html) {
  const matches = [...html.matchAll(/<h1[^>]*>(.*?)<\/h1>/gs)];
  if (matches.length !== 1) return { count: matches.length, text: undefined };
  return { count: 1, text: decodeEntities(matches[0][1].replace(/<[^>]*>/g, "")) };
}

function routedPages() {
  const pages = listCorpusFiles(corpusDir).map((file) => {
    const relative = path.relative(corpusDir, file);
    return {
      source: relative.split(path.sep).join("/"),
      title: parseFrontmatter(fs.readFileSync(file, "utf8")).frontmatter.title,
      distFile: path.join(distDir, corpusRoute(relative), "index.html"),
    };
  });
  assert.ok(pages.length > 0, "empty corpus — nothing to check");
  assert.ok(
    fs.existsSync(distDir),
    `missing ${distDir} — run \`astro build\` first (the site's \`check\` script does)`,
  );
  return pages;
}

test("the complete corpus is routed, with exactly one H1 equal to the frontmatter title", () => {
  const offenders = [];
  for (const { source, title, distFile } of routedPages()) {
    if (!fs.existsSync(distFile)) {
      offenders.push(`${source}: missing built page ${distFile}`);
      continue;
    }
    const { count, text } = h1InnerText(fs.readFileSync(distFile, "utf8"));
    if (count !== 1) offenders.push(`${source}: expected exactly one <h1>, found ${count}`);
    else if (text !== title)
      offenders.push(`${source}: H1 ${JSON.stringify(text)} ≠ title ${JSON.stringify(title)}`);
  }
  assert.deepEqual(offenders, []);
});

test("every page with two or more <h2> sections renders the Starlight TOC landmark", () => {
  const offenders = [];
  for (const { source, distFile } of routedPages()) {
    if (!fs.existsSync(distFile)) continue; // the routing test names these completely
    const html = fs.readFileSync(distFile, "utf8");
    const h2Count = (html.match(/<h2 id=/g) ?? []).length;
    if (h2Count >= 2 && !html.includes("starlight-toc")) {
      offenders.push(`${source}: ${h2Count} <h2> sections but no starlight-toc landmark`);
    }
  }
  assert.deepEqual(offenders, []);
});

test("Expressive Code renders code frames (spot: the get-started tutorial)", () => {
  const html = fs.readFileSync(path.join(distDir, "tutorials/get-started/index.html"), "utf8");
  assert.ok(html.includes("expressive-code"), "no expressive-code markup in get-started");
});
