import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { after, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { corpusRoute, listCorpusFiles } from "../src/remark-rewrite-corpus-links.mjs";

// Pagefind query smoke over the built index — the spike-proven pattern
// (docs/design/docs-site-bridge-spike.md criterion 7): the Pagefind bundle loads its index
// chunks via fetch(), which cannot read bare file paths in Node, so `dist/` is served over a
// loopback HTTP server and `pagefind.options({ basePath })` points at it. A smoke, not a
// relevance matrix (relevance tuning is a later node).

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

test("a 'worktree' query returns at least one result resolving to a routed URL", async () => {
  const pagefindBundle = path.join(distDir, "pagefind/pagefind.js");
  assert.ok(
    fs.existsSync(pagefindBundle),
    `missing ${pagefindBundle} — run \`astro build\` first (the site's \`check\` script does)`,
  );
  const baseUrl = await serveDist();
  const pagefind = await import(pathToFileURL(pagefindBundle).href);
  await pagefind.options({ basePath: `${baseUrl}/pagefind/` });
  const search = await pagefind.search("worktree");
  assert.ok(search.results.length >= 1, "no Pagefind results for 'worktree'");

  const routed = new Set(
    listCorpusFiles(corpusDir).map((file) => corpusRoute(path.relative(corpusDir, file))),
  );
  const pages = await Promise.all(search.results.slice(0, 5).map((result) => result.data()));
  const urls = pages.map((page) => new URL(page.url, baseUrl).pathname);
  assert.ok(
    urls.some((url) => routed.has(url)),
    `no routed URL among the top results: ${urls.join(", ")}`,
  );
});
