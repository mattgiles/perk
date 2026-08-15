import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import axe from "axe-core";
import { JSDOM } from "jsdom";
import { corpusRoute, listCorpusFiles } from "../src/remark-rewrite-corpus-links.mjs";

// The static accessibility gate: axe-core run in jsdom against EVERY routed built page. This
// is deliberately a static-DOM check, not a browser: pages load with
// `runScripts: "outside-only"` (page scripts never execute) and no subresources, so results
// are deterministic and hermetic. Any `serious`/`critical` violation on any routed page fails
// the gate; lower-impact violations print as a summary but do not fail (the bound bar is
// serious/critical).
//
// Exactly one axe rule is disabled: `color-contrast`. It requires real layout (computed
// styles, font rasterization) that jsdom does not perform; the deterministic substitute is
// the committed WCAG-math contrast check over the live token CSS in
// tests/test_docs_site_system.py (all §9 pairs plus the inline-code backgrounds). Rules axe
// reports as `incomplete` under jsdom are printed for visibility — never failed and never
// disabled.

const corpusDir = fileURLToPath(new URL("../../user-docs/", import.meta.url));
const distDir = fileURLToPath(new URL("../dist/", import.meta.url));

function routedDistPages() {
  const pages = listCorpusFiles(corpusDir).map((file) => {
    const relative = path.relative(corpusDir, file);
    return {
      route: corpusRoute(relative),
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

test("every routed page passes static axe (no serious/critical violations)", async () => {
  const pages = routedDistPages();
  const offenders = [];
  const lowImpact = [];
  const incomplete = [];
  let checkedPages = 0;

  for (const { route, distFile } of pages) {
    assert.ok(fs.existsSync(distFile), `${route}: missing built page ${distFile}`);
    const html = fs.readFileSync(distFile, "utf8");

    // Belt-and-suspenders landmark/skip-nav assertions, independent of axe's ruleset: exactly
    // one <main> landmark, and Starlight's skip link targeting the #_top page title.
    const mains = [...html.matchAll(/<main[\s>]/g)];
    assert.equal(mains.length, 1, `${route}: expected exactly one <main> landmark`);
    assert.match(
      html,
      /<a[^>]*class="sl-skip-link[^"]*"[^>]*href="#_top"/,
      `${route}: missing skip link targeting #_top`,
    );

    const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true });
    try {
      dom.window.eval(axe.source);
      const results = await dom.window.axe.run(dom.window.document, {
        rules: { "color-contrast": { enabled: false } },
      });
      assert.ok(results.passes.length > 0, `${route}: axe evaluated zero passing rules`);
      for (const violation of results.violations) {
        const record =
          `${route} → ${violation.id} → ${violation.impact} → ` +
          violation.nodes.map((node) => node.target.join(" ")).join(", ");
        if (violation.impact === "serious" || violation.impact === "critical") {
          offenders.push(record);
        } else {
          lowImpact.push(record);
        }
      }
      for (const entry of results.incomplete) {
        incomplete.push(`${route} → ${entry.id} (incomplete)`);
      }
      checkedPages += 1;
    } finally {
      dom.window.close();
    }
  }

  if (lowImpact.length > 0) {
    console.log(`axe low-impact violations (not failing):\n  ${lowImpact.join("\n  ")}`);
  }
  if (incomplete.length > 0) {
    console.log(
      `axe incomplete results under jsdom (informational):\n  ${incomplete.join("\n  ")}`,
    );
  }
  assert.deepEqual(offenders, []);
  // Non-vacuity: every routed page was actually evaluated.
  assert.equal(checkedPages, pages.length);
});
