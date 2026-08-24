import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { after, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { ranking } from "../src/pagefind-ranking.mjs";
import { corpusRoute, listCorpusFiles } from "../src/remark-rewrite-corpus-links.mjs";

// The ten-query relevance matrix over the built Pagefind index (the blueprint §7 search
// acceptance matrix, encoded verbatim), plus the authoring-governance exclusion sentinel.
// Transport is the spike-proven pattern (docs/design/archive/docs-site-bridge-spike.md criterion 7):
// the Pagefind bundle loads its index chunks via fetch(), which cannot read bare file paths
// in Node, so `dist/` is served over a loopback HTTP server and
// `pagefind.options({ basePath })` points at it. Ranking comes from the shared module
// (src/pagefind-ranking.mjs) — the exact object the real browser UI runs with, so a passing
// matrix here is a passing matrix in the shipped search box.

const corpusDir = fileURLToPath(new URL("../../user-docs/", import.meta.url));
const distDir = fileURLToPath(new URL("../dist/", import.meta.url));

const MIME = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".json": "application/json",
  ".wasm": "application/wasm",
};

let server;
after(() => server?.close());

function serveDist() {
  server = http.createServer((request, response) => {
    const urlPath = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
    let filePath = path.join(distDir, urlPath);
    if (urlPath.endsWith("/")) filePath = path.join(filePath, "index.html");
    try {
      const body = fs.readFileSync(filePath);
      response.writeHead(200, {
        "content-type": MIME[path.extname(filePath)] ?? "application/octet-stream",
      });
      response.end(body);
    } catch {
      response.writeHead(404);
      response.end();
    }
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      resolve(`http://127.0.0.1:${server.address().port}`);
    });
  });
}

/**
 * One loopback server + one configured Pagefind instance shared by every test (Pagefind
 * options must be set before the first search, and node:test runs this file's tests
 * sequentially). Resolves `{ baseUrl, pagefind, topRoutes }`.
 */
let sessionPromise;
function pagefindSession() {
  sessionPromise ??= (async () => {
    const pagefindBundle = path.join(distDir, "pagefind/pagefind.js");
    assert.ok(
      fs.existsSync(pagefindBundle),
      `missing ${pagefindBundle} — run \`astro build\` first (the site's \`check\` script does)`,
    );
    const baseUrl = await serveDist();
    const pagefind = await import(pathToFileURL(pagefindBundle).href);
    await pagefind.options({ basePath: `${baseUrl}/pagefind/`, ranking });
    /** The top-5 result routes (plus their result pages) for a query. */
    const topRoutes = async (query) => {
      const search = await pagefind.search(query);
      const pages = await Promise.all(search.results.slice(0, 5).map((result) => result.data()));
      return pages.map((page) => ({
        route: new URL(page.url, baseUrl).pathname,
        page,
      }));
    };
    return { baseUrl, pagefind, topRoutes };
  })();
  return sessionPromise;
}

// The blueprint §7 search-relevance matrix, verbatim: each query must surface its named
// destination route(s) among the top 5 results. `allOf` rows name every required
// destination; the one `anyOf` row passes on either.
const MATRIX = [
  {
    query: "install perk",
    anyOf: ["/tutorials/get-started/", "/reference/requirements-and-compatibility/"],
  },
  { query: "resume plan", allOf: ["/how-to/resume-a-plan/"] },
  { query: "/land", allOf: ["/reference/in-session/workflow-commands/"] },
  { query: "perk objective plan", allOf: ["/reference/cli/objective/"] },
  {
    query: "[[ci.checks]]",
    allOf: ["/reference/configuration/workflow-and-ci/", "/how-to/configure-and-verify-ci-checks/"],
  },
  { query: "dirty worktree", allOf: ["/how-to/recover-a-dirty-worktree/"] },
  {
    query: "Linear",
    allOf: ["/how-to/switch-to-linear/", "/reference/providers-and-backends/issue-backends/"],
  },
  {
    query: "remote runner",
    allOf: ["/how-to/set-up-the-remote-runner/", "/explanation/headless-and-remote/"],
  },
  { query: "plan vs objective", allOf: ["/explanation/gists-plans-and-objectives/"] },
  { query: "doctor", allOf: ["/how-to/diagnose-a-perk-repo/", "/reference/cli/setup-and-health/"] },
];

test("the ten-query relevance matrix holds over the built index (top-5 bar)", async () => {
  const { topRoutes } = await pagefindSession();
  const failures = [];
  for (const { query, allOf, anyOf } of MATRIX) {
    const routes = (await topRoutes(query)).map(({ route }) => route);
    const passed = allOf
      ? allOf.every((route) => routes.includes(route))
      : anyOf.some((route) => routes.includes(route));
    if (!passed) {
      const requirement = allOf
        ? `all of ${JSON.stringify(allOf)}`
        : `any of ${JSON.stringify(anyOf)}`;
      failures.push(
        `query ${JSON.stringify(query)}: required ${requirement} in the top 5; ` +
          `actual top 5: ${routes.join(", ") || "(no results)"}`,
      );
    }
  }
  assert.deepEqual(failures, [], `relevance matrix failure(s):\n${failures.join("\n")}`);
});

test("the /land result deep-links the #land command heading via a sub-result", async () => {
  // Granularity proof for command tokens: the workflow-commands result must not just rank —
  // its heading-level sub-results must carry the `#land` anchor, the deep link the search UI
  // offers for the exact command heading.
  const { baseUrl, topRoutes } = await pagefindSession();
  const hit = (await topRoutes("/land")).find(
    ({ route }) => route === "/reference/in-session/workflow-commands/",
  );
  assert.ok(hit, "no /reference/in-session/workflow-commands/ result in the top 5 for '/land'");
  const anchors = (hit.page.sub_results ?? []).map(
    (subResult) => new URL(subResult.url, baseUrl).hash,
  );
  assert.ok(
    anchors.includes("#land"),
    `no sub-result anchored at #land; sub-result anchors: ${anchors.join(", ") || "(none)"}`,
  );
});

test("authoring-governance content never enters the search index (the Divio sentinel)", async () => {
  // `Divio` is the bound sentinel token: present in the excluded `_authoring.md`, absent from
  // every routed source (uniqueness domain = the whole docs/user-docs/ tree) — so a zero-result
  // search proves the excluded file is unindexed, and the two source assertions keep that
  // zero-result meaningful rather than vacuous.
  const authoring = fs.readFileSync(path.join(corpusDir, "_authoring.md"), "utf8");
  assert.ok(authoring.includes("Divio"), "_authoring.md lost the 'Divio' sentinel token");
  const leaks = listCorpusFiles(corpusDir).filter((file) =>
    /divio/i.test(fs.readFileSync(file, "utf8")),
  );
  assert.deepEqual(
    leaks.map((file) => corpusRoute(path.relative(corpusDir, file))),
    [],
    "routed corpus source(s) carry the 'Divio' sentinel — the zero-result assertion would go vacuous",
  );
  const { pagefind } = await pagefindSession();
  const search = await pagefind.search("Divio");
  assert.equal(
    search.results.length,
    0,
    `expected zero Pagefind results for 'Divio', found ${search.results.length}`,
  );
});
