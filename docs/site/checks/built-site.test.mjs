import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { parseFrontmatter } from "@astrojs/markdown-remark";
import { JSDOM } from "jsdom";
import { loadRegistry } from "../../../extension/substrate/registry.ts";
import { corpusRoute, listCorpusFiles } from "../src/remark-rewrite-corpus-links.mjs";
import { sidebar } from "../src/sidebar.mjs";

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
    const { frontmatter } = parseFrontmatter(fs.readFileSync(file, "utf8"));
    return {
      source: relative.split(path.sep).join("/"),
      title: frontmatter.title,
      template: frontmatter.template,
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

/** Every file under `dir`, recursively (sorted — deterministic reports). */
function listDistFiles(dir) {
  const files = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  entries.sort((a, b) => a.name.localeCompare(b.name));
  for (const entry of entries) {
    const entryPath = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...listDistFiles(entryPath));
    else files.push(entryPath);
  }
  return files;
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

test("sectioned pages render a TOC listing every content h2/h3 anchor (h3 depth included)", () => {
  const offenders = [];
  let h3Covered = false;
  for (const { source, template, distFile } of routedPages()) {
    if (!fs.existsSync(distFile)) continue; // the routing test names these completely
    if (template === "splash") continue; // splash pages render no TOC by design
    const html = fs.readFileSync(distFile, "utf8");
    // Content headings only — `starlight__`-prefixed ids are site chrome (e.g. the TOC's own
    // "On this page" heading), never TOC entries.
    const headings = [...html.matchAll(/<h([23]) id="([^"]+)"/g)]
      .map(([, depth, id]) => ({ depth, id }))
      .filter(({ id }) => !id.startsWith("starlight__"));
    if (headings.filter(({ depth }) => depth === "2").length < 2) continue;
    const toc = html.match(/<starlight-toc.*?<\/starlight-toc>/s);
    if (toc === null) {
      offenders.push(`${source}: sectioned page without a starlight-toc landmark`);
      continue;
    }
    for (const { depth, id } of headings) {
      if (depth === "3") h3Covered = true;
      if (!toc[0].includes(`href="#${id}"`)) {
        offenders.push(`${source}: heading #${id} (h${depth}) missing from the TOC`);
      }
    }
  }
  assert.deepEqual(offenders, []);
  assert.ok(h3Covered, "expected at least one checked page with <h3> headings (depth coverage)");
});

test("the rendered navigation uses the explicit sidebar structure", () => {
  // Read from a sectioned page: the home is a `template: splash` page, which renders no
  // sidebar at all. Route-set equality and label assertions are unchanged.
  const html = fs.readFileSync(path.join(distDir, "how-to/index.html"), "utf8");
  const nav = html.match(/<sl-sidebar-state-persist.*?<\/sl-sidebar-state-persist>/s);
  assert.ok(nav !== null, "no sidebar markup in the built how-to landing");

  // Group labels (sections + how-to subgroups) render in document order — autogenerated
  // navigation would carry none of these labels.
  const expectedLabels = [];
  const collectLabels = (entry) => {
    if (typeof entry === "string" || !Array.isArray(entry.items)) return;
    expectedLabels.push(entry.label);
    entry.items.forEach(collectLabels);
  };
  sidebar.forEach(collectLabels);
  const renderedLabels = [...nav[0].matchAll(/<span class="large[^"]*">([^<]*)<\/span>/g)].map(
    (match) => decodeEntities(match[1]),
  );
  assert.deepEqual(renderedLabels, expectedLabels);

  // The Home label-override entry links the root…
  assert.match(nav[0], /<a href="\/"[^>]*>.{0,80}?Home/s);
  // …and the nav links are exactly the routed corpus (route set equality).
  const hrefs = [...nav[0].matchAll(/<a href="([^"]+)"/g)].map((match) => match[1]);
  const routes = routedPages().map(({ source }) => corpusRoute(source));
  assert.deepEqual([...hrefs].sort(), [...routes].sort());
});

// The deliberate pagination policy: globally off, with per-page opt-in only where a linear
// reading sequence exists — exactly the tutorials chain. The four rendered edges are pinned
// here; every other routed page renders neither control.
const PAGINATION_EDGES = {
  "tutorials/get-started.md": { next: "/tutorials/drive-an-objective/" },
  "tutorials/drive-an-objective.mdx": {
    prev: "/tutorials/get-started/",
    next: "/tutorials/drive-a-stacked-objective/",
  },
  "tutorials/drive-a-stacked-objective.md": { prev: "/tutorials/drive-an-objective/" },
};

test("prev/next pagination renders exactly the tutorials-chain edges", () => {
  const offenders = [];
  for (const { source, distFile } of routedPages()) {
    if (!fs.existsSync(distFile)) continue;
    const html = fs.readFileSync(distFile, "utf8");
    const rendered = Object.fromEntries(
      [...html.matchAll(/<a href="([^"]+)" rel="(prev|next)"/g)].map(([, href, rel]) => [
        rel,
        href,
      ]),
    );
    const expected = PAGINATION_EDGES[source] ?? {};
    for (const rel of ["prev", "next"]) {
      if (rendered[rel] !== expected[rel]) {
        offenders.push(
          `${source}: rel="${rel}" is ${rendered[rel] ?? "(absent)"}, ` +
            `expected ${expected[rel] ?? "(absent)"}`,
        );
      }
    }
  }
  assert.deepEqual(offenders, []);
});

test("the excluded authoring file produces no built output", () => {
  // `_authoring.md` is excluded from the collection (the `[^_]` glob); a route directory or
  // HTML for it anywhere under dist/ would mean the exclusion silently stopped holding.
  const offenders = listDistFiles(distDir).filter((file) =>
    path.relative(distDir, file).includes("_authoring"),
  );
  assert.deepEqual(offenders, []);
});

test("the search-indexed page set is exactly the routed corpus", () => {
  // Pagefind indexes only `data-pagefind-body` content once the attribute exists anywhere in
  // the build (Starlight stamps it on every docs page) — so the set of built pages carrying
  // it IS the index membership, and it must equal the routed corpus route set.
  const carrying = [];
  for (const file of listDistFiles(distDir)) {
    if (path.extname(file) !== ".html") continue;
    if (!fs.readFileSync(file, "utf8").includes("data-pagefind-body")) continue;
    const relative = path.relative(distDir, file).split(path.sep).join("/");
    carrying.push(relative === "index.html" ? "/" : `/${relative.replace(/index\.html$/, "")}`);
  }
  const routes = routedPages().map(({ source }) => corpusRoute(source));
  assert.deepEqual([...carrying].sort(), [...routes].sort());
});

test("Expressive Code renders code frames (spot: the get-started tutorial)", () => {
  const html = fs.readFileSync(path.join(distDir, "tutorials/get-started/index.html"), "utf8");
  assert.ok(html.includes("expressive-code"), "no expressive-code markup in get-started");
});

// --- Home, landing, and tutorial structure (deterministic markup checks; geometry, zoom,
// and exposure verification remain browser-based) --------------------------------------------

const HOME_BAND_IDS = [
  "the-workflow",
  "choose-by-intent",
  "common-paths",
  "how-perk-fits-together",
  "requirements-and-provenance",
];

test("the home page renders the hero actions and the five band sections", () => {
  const html = fs.readFileSync(path.join(distDir, "index.html"), "utf8");
  for (const href of ["/tutorials/get-started/", "/explanation/how-perk-thinks/"]) {
    assert.match(
      html,
      new RegExp(`<a[^>]*class="sl-link-button[^"]*"[^>]*href="${href}"`),
      `hero action ${href} missing`,
    );
  }
  const bands = [...html.matchAll(/<section class="perk-band[^"]*"/g)];
  assert.equal(bands.length, HOME_BAND_IDS.length, "expected exactly five perk-band sections");
  for (const id of HOME_BAND_IDS) {
    assert.ok(html.includes(`<h2 id="${id}"`), `band heading anchor #${id} missing`);
  }
});

// Semantic content is pinned per static-SVG figure so hand-duplicated wide/narrow variants
// cannot drift apart silently: `ordered` labels appear in source order in BOTH variants,
// `required` labels are present, and arrowhead / dashed-conditional-connector counts match.
// The home's band-2 core-flow figure is interactive semantic HTML, not SVG — its contract is
// pinned by its own test below.
const HOME_DIAGRAM_CONTENT = [
  {
    name: "two planes",
    ordered: ["Exterior", "Durable state", "Interior"],
    required: [
      "plans &amp; objectives",
      "pull requests",
      "pushed branch commits",
      "plan issues · branches",
      "plan issues · pull requests",
    ],
    titleRequired: "Two planes around one durable state",
    descriptionRequired: [
      "Exterior",
      "Interior",
      "durable-state artifact",
      "plans and objectives",
      "pull requests",
      "pushed branch commits",
      "plan issues · branches",
      "plan issues · pull requests",
    ],
    textRequired: [
      "exterior",
      "interior",
      "durable state",
      "plans and objectives",
      "pull requests",
      "pushed branch commits",
      "plan issues and branches",
      "plan issues and pull requests",
    ],
    arrowheads: 4,
    conditionalConnectors: 0,
  },
];

const OBJECTIVE_TUTORIAL_DIAGRAM_CONTENT = [
  {
    name: "plans inside objectives",
    ordered: ["Objective (durable issue)", "✓ 1.1", "▸ 1.2", "○ 1.3", "plan issue", "PR"],
    required: ["perk objective plan", "implement", "merge → node done + reconcile"],
    titleRequired: "Plans inside an objective",
    descriptionRequired: [
      "1.1 is complete",
      "1.2 is current",
      "1.3 is pending",
      "perk objective plan",
      "plan issue",
      "pull request",
      "merge → node done + reconcile",
    ],
    textRequired: [
      "durable issue holding a roadmap of nodes",
      "perk objective plan",
      "current node",
      "bounded plan issue",
      "produces a PR",
      "marks the node done",
      "reconciles the roadmap",
      "unblocking the next node",
    ],
    arrowheads: 3,
    conditionalConnectors: 0,
  },
];

// The headless/remote flow figure additionally pins its exact directed-edge set through the
// connectors' data-from/data-to attributes (`edges`), proving the human gate is terminal (no
// edge originates at it) rather than relying on arrow count alone.
const HEADLESS_REMOTE_DIAGRAM_CONTENT = [
  {
    name: "headless/remote flow",
    ordered: [
      "Local operator",
      "GitHub Actions",
      "○ implement",
      "○ address",
      "GitHub state",
      "! HUMAN GATE",
    ],
    required: [
      "deterministic supervisor",
      "dispatch",
      "plan · branch",
      "PR · report",
      "review + land",
    ],
    titleRequired: "headless remote flow",
    descriptionRequired: [
      "dispatches bounded work",
      "GitHub Actions process boundary",
      "implement and address",
      "same stage implementation",
      "durable GitHub state",
      "HUMAN GATE",
      "no automatic outgoing step",
      "automation stops there",
    ],
    textRequired: [
      "local operator",
      "deterministic supervisor",
      "dispatches bounded work",
      "implement and address stages",
      "same stage implementation",
      "durable GitHub state",
      "plan and branch",
      "pushed branch, pull request, checks, and report comments",
      "human gate — review and land",
      "does not continue automatically",
      "no automatic step leaves the human gate",
    ],
    arrowheads: 4,
    conditionalConnectors: 0,
    connectors: 4,
    edges: ["operator→runner", "runner→github", "github→runner", "github→human-gate"],
  },
];

const REGISTRY_MATRIX = loadRegistry().stages.map((stage) => ({
  id: stage.id,
  mode: stage.mode,
  warm: stage.doors.warm,
  coldLocal: stage.doors.cold_local,
  coldRemote: stage.doors.cold_remote,
  coldCommand: stage.id === "audit" ? `perk-dev ${stage.command}` : `perk ${stage.command}`,
}));

const STAGES_AND_DOORS_DIAGRAM_CONTENT = [
  {
    name: "warm and cold doors",
    ordered: REGISTRY_MATRIX.map((stage) => `○ ${stage.id}`),
    required: ["Warm", "Cold local", "Cold remote", "dev-only"],
    titleRequired: "Warm and cold door availability by stage",
    descriptionRequired: [
      "thirteen-row matrix",
      "Every stage has a cold-local door",
      "Warm doors",
      "Cold-remote doors",
      "implement and address",
      "yes or an em dash",
    ],
    textRequired: [
      "Which doors are available for each registry stage?",
      "Warm door",
      "Cold-local door",
      "Cold-remote door",
      "no standalone slash launcher",
      "/implement refresh only; not a warm stage door",
      "perk-dev audit judge",
    ],
    arrowheads: 0,
    conditionalConnectors: 0,
    connectors: 0,
    matrix: REGISTRY_MATRIX,
  },
];

function normalizeMarkupText(markup) {
  return decodeEntities(markup.replace(/<[^>]*>/g, " "))
    .replace(/\s+/g, " ")
    .trim();
}

function assertDiagramFigures(page, expectedFigures) {
  const html = fs.readFileSync(path.join(distDir, page), "utf8");
  // Figures carrying the `perk-core-flow` modifier hold the interactive semantic-HTML
  // contract (their own test) — only the static-SVG figures take the assertions below.
  const staticFigures = [
    ...html.matchAll(/<figure class="perk-diagram[^"]*".*?<\/figure>/gs),
  ].filter(([figure]) => !/^<figure class="[^"]*\bperk-core-flow\b/.test(figure));
  assert.equal(
    staticFigures.length,
    expectedFigures.length,
    `${page}: expected exactly ${expectedFigures.length} static perk-diagram figure(s)`,
  );

  const seenIds = new Set();
  staticFigures.forEach(([figure], figureIndex) => {
    const expected = expectedFigures[figureIndex];
    const svgs = [...figure.matchAll(/<svg.*?<\/svg>/gs)].map(([block]) => block);
    assert.equal(svgs.length, 2, `${expected.name}: expected exactly two SVG variants`);
    const variants = svgs.map((block) => block.match(/data-variant="([^"]+)"/)?.[1]);
    assert.deepEqual([...variants].sort(), ["narrow", "wide"]);

    for (const block of svgs) {
      const tag = block.match(/^<svg[^>]*>/)[0];
      const variant = `${expected.name} (${tag.match(/data-variant="([^"]+)"/)?.[1]})`;
      assert.match(tag, /role="img"/, `${variant}: SVG without role="img"`);

      // aria-labelledby resolves within this SVG to one <title> followed by one <desc>, and
      // both ids remain unique within the rendered document.
      const labelledby = tag.match(/aria-labelledby="([^"]+)"/)?.[1];
      assert.ok(labelledby, `${variant}: SVG without aria-labelledby`);
      const ids = labelledby.split(/\s+/);
      assert.equal(ids.length, 2, `${variant}: expected a <title> + <desc> id pair`);
      const [titleId, descId] = ids;
      assert.ok(
        block.includes(`<title id="${titleId}"`),
        `${variant}: first id must be its <title>`,
      );
      assert.ok(block.includes(`<desc id="${descId}"`), `${variant}: second id must be its <desc>`);
      for (const id of ids) {
        assert.ok(!seenIds.has(id), `duplicated accessible-name id: ${id}`);
        seenIds.add(id);
        const occurrences = [...html.matchAll(new RegExp(` id="${id}"`, "g"))];
        assert.equal(occurrences.length, 1, `id ${id} must be document-unique`);
      }

      const title = normalizeMarkupText(block.match(/<title[^>]*>(.*?)<\/title>/s)?.[1] ?? "");
      const description = normalizeMarkupText(block.match(/<desc[^>]*>(.*?)<\/desc>/s)?.[1] ?? "");
      assert.ok(title.includes(expected.titleRequired), `${variant}: title lost its subject`);
      for (const semantic of expected.descriptionRequired) {
        assert.ok(
          description.includes(semantic),
          `${variant}: description missing ${JSON.stringify(semantic)}`,
        );
      }

      // Strip accessible prose before checking the graphical markup's node order and markers.
      const content = block.replace(/<title.*?<\/title>/s, "").replace(/<desc.*?<\/desc>/s, "");
      let cursor = -1;
      for (const label of expected.ordered) {
        const at = content.indexOf(label);
        assert.ok(
          at > cursor,
          `${variant}: label ${JSON.stringify(label)} missing or out of order`,
        );
        cursor = at;
      }
      for (const label of expected.required) {
        assert.ok(content.includes(label), `${variant}: label ${JSON.stringify(label)} missing`);
      }
      assert.equal(
        [...content.matchAll(/class="arrowhead/g)].length,
        expected.arrowheads,
        `${variant}: arrowhead count`,
      );
      assert.equal(
        [...content.matchAll(/class="connector conditional/g)].length,
        expected.conditionalConnectors,
        `${variant}: dashed conditional-connector count`,
      );
      if (expected.connectors !== undefined) {
        assert.equal(
          [...content.matchAll(/class="connector(?:\s|")/g)].length,
          expected.connectors,
          `${variant}: connector count`,
        );
      }
      if (expected.edges !== undefined) {
        const pairs = [...content.matchAll(/<(?:line|path)[^>]*data-from="[^"]*"[^>]*>/g)].map(
          ([tag]) => {
            const from = tag.match(/data-from="([^"]+)"/)?.[1];
            const to = tag.match(/data-to="([^"]+)"/)?.[1];
            return `${from}→${to}`;
          },
        );
        assert.deepEqual(
          [...pairs].sort(),
          [...expected.edges].sort(),
          `${variant}: directed-edge set (data-from→data-to)`,
        );
        for (const pair of pairs) {
          assert.ok(
            !pair.startsWith("human-gate→"),
            `${variant}: the human gate must be terminal — found outgoing edge ${pair}`,
          );
        }
      }
      if (expected.matrix !== undefined) {
        const rowBlocks = [
          ...content.matchAll(/<g(?<attrs>[^>]*data-stage="[^"]+"[^>]*)>(?<body>.*?)<\/g>/gs),
        ];
        assert.equal(rowBlocks.length, expected.matrix.length, `${variant}: matrix row count`);
        rowBlocks.forEach((match, rowIndex) => {
          const attrs = match.groups.attrs;
          const body = match.groups.body;
          const attribute = (name) => attrs.match(new RegExp(`${name}="([^"]+)"`))?.[1];
          const row = expected.matrix[rowIndex];
          assert.equal(attribute("data-stage"), row.id, `${variant}: stage order`);
          assert.equal(attribute("data-warm"), String(row.warm), `${variant}: ${row.id} warm`);
          assert.equal(
            attribute("data-cold-local"),
            String(row.coldLocal),
            `${variant}: ${row.id} cold-local`,
          );
          assert.equal(
            attribute("data-cold-remote"),
            String(row.coldRemote),
            `${variant}: ${row.id} cold-remote`,
          );
          assert.ok(
            body.includes(`○ ${row.id}`),
            `${variant}: ${row.id} lost ordinary-stage glyph`,
          );
          const values = [
            ...body.matchAll(
              /<text class="(?:cell-value|door-value)(?:\s[^"]*)?"[^>]*>(.*?)<\/text>/gs,
            ),
          ].map((valueMatch) => normalizeMarkupText(valueMatch[1]));
          assert.deepEqual(
            values,
            [row.warm, row.coldLocal, row.coldRemote].map((value) => (value ? "yes" : "—")),
            `${variant}: ${row.id} visible values drifted from its data attributes`,
          );
        });
      }
    }
  });

  // Per-matched-figure adjacency: each static figure is immediately followed by its own
  // textual equivalent (never a page-global count, which a second figure could satisfy).
  const textBlocks = staticFigures.map((match, figureIndex) => {
    const tail = html.slice(match.index + match[0].length);
    const adjacent = tail.match(/^\s*<div class="perk-diagram-text"[^>]*>(.*?)<\/div>/s);
    assert.ok(
      adjacent,
      `${page}: figure ${expectedFigures[figureIndex].name} needs an ` +
        "immediately-adjacent perk-diagram-text",
    );
    return adjacent[1];
  });
  const texts = textBlocks.map((block) => normalizeMarkupText(block));
  texts.forEach((text, figureIndex) => {
    const expected = expectedFigures[figureIndex];
    for (const semantic of expected.textRequired) {
      assert.ok(
        text.includes(semantic),
        `${page}: textual equivalent missing ${JSON.stringify(semantic)}`,
      );
    }
    if (expected.matrix !== undefined) {
      const table = textBlocks[figureIndex].match(/<table[^>]*>(.*?)<\/table>/s)?.[1];
      assert.ok(table, `${page}: matrix textual equivalent needs a rendered table`);
      const rows = [...table.matchAll(/<tr[^>]*>(.*?)<\/tr>/gs)].map((rowMatch) =>
        [...rowMatch[1].matchAll(/<t[hd][^>]*>(.*?)<\/t[hd]>/gs)].map((cellMatch) =>
          normalizeMarkupText(cellMatch[1]),
        ),
      );
      assert.deepEqual(rows[0], [
        "Stage",
        "Mode",
        "Warm door",
        "Warm command",
        "Cold-local door",
        "Cold command",
        "Cold-remote door",
      ]);
      assert.equal(rows.length - 1, expected.matrix.length, `${page}: textual matrix row count`);
      expected.matrix.forEach((stage, rowIndex) => {
        const cells = rows[rowIndex + 1];
        assert.equal(cells.length, 7, `${page}: ${stage.id} textual row width`);
        assert.ok(cells[0].startsWith(stage.id), `${page}: ${stage.id} textual order`);
        assert.equal(cells[1], stage.mode, `${page}: ${stage.id} textual mode`);
        assert.equal(cells[2], stage.warm ? "yes" : "—", `${page}: ${stage.id} textual warm`);
        assert.equal(
          cells[4],
          stage.coldLocal ? "yes" : "—",
          `${page}: ${stage.id} textual cold-local`,
        );
        assert.equal(cells[5], stage.coldCommand, `${page}: ${stage.id} textual cold command`);
        assert.equal(
          cells[6],
          stage.coldRemote ? "yes" : "—",
          `${page}: ${stage.id} textual cold-remote`,
        );
        if (stage.id === "gist-author" || stage.id === "objective-author") {
          assert.equal(cells[3], "no standalone slash launcher", `${page}: ${stage.id} warm label`);
        }
        if (stage.id === "implement") {
          assert.match(cells[3], /refresh only; not a warm stage door/);
        }
      });
    }
  });
}

test("diagram pages render labeled, content-equal wide and narrow SVG variants", () => {
  assertDiagramFigures("index.html", HOME_DIAGRAM_CONTENT);
  assertDiagramFigures(
    "tutorials/drive-an-objective/index.html",
    OBJECTIVE_TUTORIAL_DIAGRAM_CONTENT,
  );
  assertDiagramFigures(
    "reference/in-session/stages-and-doors/index.html",
    STAGES_AND_DOORS_DIAGRAM_CONTENT,
  );
  assertDiagramFigures(
    "explanation/headless-and-remote/index.html",
    HEADLESS_REMOTE_DIAGRAM_CONTENT,
  );
});

// --- The interactive core-flow figure (home band 2) ------------------------------------------

// Bound verbatim (the visual blueprint §5 interactive contract): the 9 supplementary
// tooltips — 7 spine stages + the 2 cache curation loops. Supplementary color only; the
// diagram + textual equivalent stand alone.
const CORE_FLOW_TOOLTIPS = {
  "perk-core-flow-tip-plan":
    "A read-only session explores the repo and authors a bounded plan; a human review gates it " +
    "before save — on the browser review door an agent draft-review wave assists.",
  "perk-core-flow-tip-save":
    "The approved plan is persisted as a durable issue — the canonical artifact the rest of " +
    "the workflow consumes.",
  "perk-core-flow-tip-implement":
    "A worktree session executes the saved plan and runs the repo's CI checks before submitting.",
  "perk-core-flow-tip-submit": "The change goes up as a pull request for human review.",
  "perk-core-flow-tip-address":
    "Review feedback is classified and resolved — this stage runs only when review asks.",
  "perk-core-flow-tip-land":
    "The approved pull request merges; objective nodes advance and reconcile automatically.",
  "perk-core-flow-tip-learn":
    "Durable learnings from the session are captured into learn issues for later consolidation.",
  "perk-core-flow-tip-harvest":
    "Harvest mines docs/learned for improvement opportunities and authors one bounded " +
    "objective — an objective factory, never a direct plan.",
  "perk-core-flow-tip-dreaming":
    "Dreaming reads the learned corpus as a whole and authors a reviewed curation objective — " +
    "pruning and consolidating perk's memory.",
};

const CORE_FLOW_STAGES = [
  "○ plan",
  "○ save",
  "▸ implement (current)",
  "○ submit",
  "◇ address",
  "○ land",
  "○ learn",
];

// Review loops and cache loops, with truthful shipped-surface labels: human review is the
// universal gate, and EVERY human-review loop carries the built-in optional agent wave (the
// draft-review wave on authoring surfaces, the PR review wave on submit).
const CORE_FLOW_LOOPS = [
  ["↻ human review · optional agent wave", 3], // spine plan + gist + objective satellites
  ["↻ human PR review · optional agent wave", 1],
  ["↻ human review", 3], // exactly the three wave-suffixed labels above
  ["↻ human PR review", 1],
  ["↻ harvest → objective authoring", 1],
  ["↻ dreaming — corpus self-curation", 1],
];

const CORE_FLOW_SATELLITES = [
  ["gist authoring", "problem statements — plan → save"],
  ["objective authoring", "plans of plans — plan → save"],
  ["docs/learned", "the durable learned-docs cache"],
];

const CORE_FLOW_FEEDS = [
  "⇢ objective plan — seeds an objective",
  "⇢ spine plan — seeds a plan",
  "⇢ spine plan — each node emits a bounded plan",
  "⇢ spine plan — ambient learned context",
  "⇢ objective plan — ambient learned context",
  "⇢ gist plan — ambient learned context",
  "spine learn ⇢ docs/learned — mediated: /learn captures learn issues; perk learn docs " +
    "folds them into the corpus",
];

const CORE_FLOW_TEXT_REQUIRED = [
  // The bound stage-order sentence, entire.
  "How does a change move through perk? The spine walks seven stages in order — plan, save, " +
    "implement (shown in-flight as an example), submit, then address only if review asks, " +
    "then land, and finally learn.",
  "everywhere a human reviews, a built-in agent review wave can optionally assist",
  "harvest",
  "dreaming",
  "learn issues",
  "perk learn docs",
];

const countOccurrences = (text, needle) => text.split(needle).length - 1;

test("the home band-2 core-flow figure holds the interactive semantic-HTML contract", () => {
  const html = fs.readFileSync(path.join(distDir, "index.html"), "utf8");
  const figures = [
    ...html.matchAll(/<figure class="[^"]*\bperk-core-flow\b[^"]*"[^>]*>.*?<\/figure>/gs),
  ];
  assert.equal(figures.length, 1, "expected exactly one perk-core-flow figure on the home");
  const [figure] = figures[0];
  assert.match(
    figure.match(/^<figure[^>]*>/)[0],
    /class="perk-diagram perk-core-flow[^"]*"[^>]*\bdata-core-flow\b/,
    "the figure must reuse the shared perk-diagram class and carry the controller mount hook",
  );

  // Zero inline SVG: connectors are CSS decoration; semantics live in source order + text.
  assert.equal([...figure.matchAll(/<svg/g)].length, 0, "no <svg> anywhere in the core flow");

  // Three source-expanded, independently-native disclosures with bound labels AND their
  // collapsed-visible hints INSIDE the <summary>.
  const details = [...figure.matchAll(/<details([^>]*)>(.*?)<\/details>/gs)];
  assert.equal(details.length, 3, "expected exactly three satellite disclosures");
  details.forEach((match, index) => {
    const [, attributes, body] = match;
    assert.match(attributes, /\bopen\b/, `satellite ${index}: <details> must ship open`);
    assert.match(attributes, /\bdata-core-flow-disclosure\b/, `satellite ${index}: mount hook`);
    const summary = body.match(/<summary[^>]*>(.*?)<\/summary>/s);
    assert.ok(summary, `satellite ${index}: missing <summary>`);
    const summaryText = normalizeMarkupText(summary[1]);
    const [label, hint] = CORE_FLOW_SATELLITES[index];
    assert.ok(summaryText.includes(label), `satellite ${index}: summary lost ${label}`);
    assert.ok(summaryText.includes(hint), `satellite ${index}: summary hint ${hint} missing`);
  });

  // The 7 stage chips in source order inside the spine list.
  const spine = figure.match(/<ol class="flow-spine[^"]*"[^>]*>.*?<\/ol>/s);
  assert.ok(spine, "missing the flow-spine list");
  const stageButtons = [
    ...spine[0].matchAll(/<button[^>]*data-core-flow-tip[^>]*>(.*?)<\/button>/gs),
  ].map(([, inner]) => normalizeMarkupText(inner));
  assert.deepEqual(stageButtons, CORE_FLOW_STAGES);
  assert.ok(
    normalizeMarkupText(spine[0]).includes("(if review asks)"),
    "the conditional address step lost its visible condition label",
  );

  // Bound loop labels, exact occurrence counts (↻ human review is a prefix of the wave label).
  const figureText = normalizeMarkupText(figure);
  for (const [label, count] of CORE_FLOW_LOOPS) {
    assert.equal(countOccurrences(figureText, label), count, `loop label ${label}`);
  }

  // Labeled feeds: the three ambient-context feeds plus the mediated learn feed.
  for (const feed of CORE_FLOW_FEEDS) {
    assert.ok(figureText.includes(feed), `feed label missing: ${feed}`);
  }
  assert.equal(countOccurrences(figureText, "ambient learned context"), 3);

  // Exactly 9 tooltip triggers, each a real <button type="button"> colocated with its
  // [role="tooltip"][hidden] sibling inside one .tip-wrap (whitespace-tolerant — the source
  // formats each element on its own line), aria-describedby resolving to a document-unique
  // id, and the bound copy verbatim.
  const wraps = [
    ...figure.matchAll(
      /<span class="tip-wrap[^"]*"[^>]*>\s*<button type="button" data-core-flow-tip aria-describedby="([^"]+)"[^>]*>.*?<\/button>\s*<span role="tooltip" id="([^"]+)" hidden data-core-flow-tooltip[^>]*>(.*?)<\/span>\s*<\/span>/gs,
    ),
  ];
  assert.equal(wraps.length, 9, "expected 9 colocated trigger/tooltip pairs");
  assert.equal([...figure.matchAll(/data-core-flow-tip\b/g)].length, 9);
  const expectedIds = Object.keys(CORE_FLOW_TOOLTIPS);
  assert.deepEqual(
    wraps.map(([, describedby]) => describedby),
    expectedIds,
    "trigger order / aria-describedby ids drifted",
  );
  for (const [, describedby, tooltipId, copy] of wraps) {
    assert.equal(describedby, tooltipId, "aria-describedby must point at the sibling tooltip");
    const occurrences = [...html.matchAll(new RegExp(` id="${tooltipId}"`, "g"))];
    assert.equal(occurrences.length, 1, `id ${tooltipId} must be document-unique`);
    assert.equal(normalizeMarkupText(copy), CORE_FLOW_TOOLTIPS[tooltipId]);
  }

  // The adjacent textual equivalent immediately follows the figure (Astro may inline the
  // controller-mount module script between the two — an artifact of the component script,
  // not of source order).
  const figureMatch = figures[0];
  const tail = html.slice(figureMatch.index + figureMatch[0].length);
  const adjacent = tail.match(
    /^\s*(?:<script type="module">.*?<\/script>\s*)?<div class="perk-diagram-text"[^>]*>(.*?)<\/div>/s,
  );
  assert.ok(adjacent, "the core-flow figure needs its adjacent perk-diagram-text");
  const text = normalizeMarkupText(adjacent[1]);
  for (const phrase of CORE_FLOW_TEXT_REQUIRED) {
    assert.ok(text.includes(phrase), `textual equivalent missing ${JSON.stringify(phrase)}`);
  }

  // The controller mount must actually ship: some module script on the page (inline or a
  // built asset) carries the controller's attribute/event contract — markers that survive
  // minification. Without this, deleting the component's mount block would leave the
  // shipped disclosures permanently expanded and every tooltip dead while tests stay green.
  const mountMarkers = ["data-core-flow-disclosure", "data-core-flow-tip", "beforeprint"];
  const scriptSources = [
    ...[...html.matchAll(/<script type="module">(.*?)<\/script>/gs)].map(([, inline]) => inline),
    ...[...html.matchAll(/<script type="module" src="(\/[^"]+)"/g)].map(([, src]) =>
      fs.readFileSync(path.join(distDir, src.slice(1)), "utf8"),
    ),
  ];
  assert.ok(
    scriptSources.some((source) => mountMarkers.every((marker) => source.includes(marker))),
    "the built home ships no script carrying the core-flow controller contract",
  );
});

test("every route-style internal href on an MDX page maps to a built page", () => {
  // JSX attribute hrefs bypass the remark link rewriter and its audit. Check every internal
  // route in each MDX page's built output against dist/<path>/index.html instead.
  const mdxPages = [
    "index.html",
    "tutorials/drive-an-objective/index.html",
    "reference/in-session/stages-and-doors/index.html",
    "explanation/headless-and-remote/index.html",
  ];
  const offenders = [];
  for (const page of mdxPages) {
    const html = fs.readFileSync(path.join(distDir, page), "utf8");
    const hrefs = [...html.matchAll(/<a[^>]* href="(\/[^"]*)"/g)].map(([, href]) => href);
    assert.ok(hrefs.length > 0, `${page}: no internal hrefs found`);
    for (const href of new Set(hrefs)) {
      const routePath = href.split("#")[0];
      const target = path.join(distDir, routePath, "index.html");
      if (!fs.existsSync(target)) offenders.push(`${page}: ${href} → missing ${target}`);
    }
  }
  assert.deepEqual(offenders, []);

  // The four-way intent router is pinned exactly: one card per quadrant landing in section
  // order, so dropping, duplicating, or retargeting a card fails here.
  const homeHtml = fs.readFileSync(path.join(distDir, "index.html"), "utf8");
  const cardHrefs = [
    ...homeHtml.matchAll(/<div class="sl-link-card[^"]*">\s*<span[^>]*>\s*<a href="([^"]+)"/g),
  ].map(([, href]) => href);
  assert.deepEqual(cardHrefs, ["/tutorials/", "/how-to/", "/reference/", "/explanation/"]);
});

test("each quadrant landing renders a recommended-starts region with 2–3 links", () => {
  const offenders = [];
  for (const section of ["tutorials", "how-to", "reference", "explanation"]) {
    const html = fs.readFileSync(path.join(distDir, section, "index.html"), "utf8");
    const region = html.match(/<div class="perk-recommended"[^>]*>.*?<\/div>/s);
    if (region === null) {
      offenders.push(`${section}: no perk-recommended region`);
      continue;
    }
    const links = [...region[0].matchAll(/<a href="/g)].length;
    if (links < 2 || links > 3) {
      offenders.push(`${section}: expected 2–3 recommended links, found ${links}`);
    }
  }
  assert.deepEqual(offenders, []);
});

test("eyebrow/wide-mode CSS routes carry their aria-current sidebar link in the built HTML", () => {
  // The §4B landing eyebrows and the §4C path-eyebrow/92ch wide mode (src/styles/system.css)
  // are pure CSS keyed on the sidebar's `aria-current="page"` link — zero corpus edits, zero
  // component overrides. That coupling holds only while each keyed route's built page renders
  // a sidebar link with the EXACT href the CSS enumerates; this pins it, so restructuring the
  // sidebar or the route shape fails loudly here instead of silently dropping the treatment.
  const systemCss = fs.readFileSync(
    fileURLToPath(new URL("../src/styles/system.css", import.meta.url)),
    "utf8",
  );
  const hrefs = [
    ...new Set([...systemCss.matchAll(/\[href="(\/[^"]+)"\]/g)].map(([, href]) => href)),
  ];
  // Four quadrant landings + five configuration children (the value-exact enumeration itself
  // is guarded against the settled routes by tests/test_docs_site_system.py).
  assert.equal(hrefs.length, 9, `unexpected keyed-route set: ${hrefs.join(", ")}`);
  for (const href of hrefs) {
    const distFile = path.join(distDir, href, "index.html");
    assert.ok(fs.existsSync(distFile), `${href}: keyed route has no built page`);
    const html = fs.readFileSync(distFile, "utf8");
    assert.match(
      html,
      new RegExp(
        `<a[^>]*href="${href}"[^>]*aria-current="page"|<a[^>]*aria-current="page"[^>]*href="${href}"`,
      ),
      `${href}: built page missing its aria-current="page" sidebar link with the exact href`,
    );
  }
});

test("the how-to landing retains the five operator-group heading anchors", () => {
  const html = fs.readFileSync(path.join(distDir, "how-to/index.html"), "utf8");
  const groupIds = [
    "core-workflow",
    "objectives--learnings",
    "headless--remote",
    "customization",
    "providers--backends",
  ];
  for (const id of groupIds) {
    assert.ok(html.includes(`<h2 id="${id}"`), `group heading anchor #${id} missing`);
  }
});

// --- No runtime network (launch-gate leg C) --------------------------------------------------

// The local-only contract: a built page must render and function with no network access, so no
// FETCHING position may reference an external origin. Plain `<a href>` external links are
// deliberately allowed — they are content links a reader may choose to follow, not requests the
// page performs. That distinction is why this check parses attributes (jsdom) rather than
// grepping page text: code samples legitimately contain URLs as text.

/** External origin = absolute http(s) or protocol-relative. `data:` and same-origin paths pass. */
function isExternalUrl(value) {
  return /^(?:https?:)?\/\//i.test(value.trim());
}

/** The URL half of each srcset candidate (`url [descriptor]`, comma-separated). */
function srcsetUrls(value) {
  return value
    .split(",")
    .map((candidate) => candidate.trim().split(/\s+/)[0])
    .filter((url) => url.length > 0);
}

// Every attribute position where the BROWSER fetches (or navigates to) the URL at runtime.
const FETCHING_POSITIONS = [
  ["script[src]", "src"],
  ["link[href]", "href"],
  ["img[src]", "src"],
  ["source[src]", "src"],
  ["video[src]", "src"],
  ["video[poster]", "poster"],
  ["audio[src]", "src"],
  ["track[src]", "src"],
  ["iframe[src]", "src"],
  ["embed[src]", "src"],
  ["object[data]", "data"],
  ["form[action]", "action"],
];
const SRCSET_POSITIONS = [
  ["img[srcset]", "srcset"],
  ["source[srcset]", "srcset"],
];

test("built assets and functionality reference no external origin", () => {
  const files = listDistFiles(distDir);
  const htmlFiles = files.filter((file) => path.extname(file) === ".html");
  const cssFiles = files.filter((file) => path.extname(file) === ".css");
  // Non-vacuity: the sweep must cover the full built output, 404 page and stylesheets included.
  assert.ok(
    htmlFiles.some((file) => path.basename(file) === "404.html"),
    "expected 404.html in the built output",
  );
  assert.ok(htmlFiles.length > 1, "expected built HTML pages to sweep");
  assert.ok(cssFiles.length > 0, "expected built CSS files to sweep");

  const offenders = [];
  for (const file of htmlFiles) {
    const relative = path.relative(distDir, file).split(path.sep).join("/");
    const dom = new JSDOM(fs.readFileSync(file, "utf8"), { runScripts: "outside-only" });
    try {
      const { document } = dom.window;
      for (const [selector, attribute] of FETCHING_POSITIONS) {
        for (const element of document.querySelectorAll(selector)) {
          const value = element.getAttribute(attribute) ?? "";
          if (isExternalUrl(value)) offenders.push(`${relative}: ${selector} → ${value}`);
        }
      }
      for (const [selector, attribute] of SRCSET_POSITIONS) {
        for (const element of document.querySelectorAll(selector)) {
          for (const url of srcsetUrls(element.getAttribute(attribute) ?? "")) {
            if (isExternalUrl(url)) offenders.push(`${relative}: ${selector} → ${url}`);
          }
        }
      }
      for (const meta of document.querySelectorAll('meta[http-equiv="refresh" i]')) {
        const content = meta.getAttribute("content") ?? "";
        const url = content.match(/url\s*=\s*['"]?([^'";]+)/i)?.[1];
        if (url !== undefined && isExternalUrl(url)) {
          offenders.push(`${relative}: meta[http-equiv=refresh] → ${url}`);
        }
      }
    } finally {
      dom.window.close();
    }
  }

  // CSS fetches: url(…) references and @import (both the url(…) and bare-string forms).
  for (const file of cssFiles) {
    const relative = path.relative(distDir, file).split(path.sep).join("/");
    const text = fs.readFileSync(file, "utf8");
    for (const [, url] of text.matchAll(/url\(\s*['"]?([^'")]+?)['"]?\s*\)/g)) {
      if (isExternalUrl(url)) offenders.push(`${relative}: url(${url})`);
    }
    for (const [, url] of text.matchAll(/@import\s+(?:url\(\s*)?['"]?([^'")\s;]+)/g)) {
      if (isExternalUrl(url)) offenders.push(`${relative}: @import ${url}`);
    }
  }

  assert.deepEqual(offenders, []);
});
