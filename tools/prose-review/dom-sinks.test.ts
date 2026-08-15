import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// The text-only rendering invariant's source-scan guard: repository-derived content
// must reach the page through JSX text interpolation only, never an HTML sink. The
// CSP is the runtime backstop; this scan keeps the sinks out of the source at all.
const BANNED_SINKS = [
  "innerHTML",
  "outerHTML",
  "insertAdjacentHTML",
  "dangerouslySetInnerHTML",
  "document.write",
] as const;

const WORKSPACE = path.dirname(fileURLToPath(import.meta.url));

function frontendSources(): string[] {
  const sources = [path.join(WORKSPACE, "index.html")];
  for (const entry of readdirSync(path.join(WORKSPACE, "src"), {
    recursive: true,
    withFileTypes: true,
  })) {
    if (entry.isFile()) {
      sources.push(path.join(entry.parentPath, entry.name));
    }
  }
  return sources;
}

test("frontend sources contain no banned HTML sinks", () => {
  const sources = frontendSources();
  const visited = sources.map((file) => path.relative(WORKSPACE, file));

  // Vacuousness self-check: an empty or misrooted scan must fail loudly, never pass.
  assert.ok(
    visited.includes("index.html"),
    `scan missed index.html (visited: ${visited.join(", ")})`,
  );
  assert.ok(
    visited.includes(path.join("src", "App.tsx")),
    `scan missed src/App.tsx (visited: ${visited.join(", ")})`,
  );
  assert.ok(visited.length >= 3, `scan visited too few files: ${visited.join(", ")}`);

  for (const file of sources) {
    const text = readFileSync(file, "utf-8");
    for (const sink of BANNED_SINKS) {
      assert.ok(
        !text.includes(sink),
        `${path.relative(WORKSPACE, file)} contains banned HTML sink: ${sink}`,
      );
    }
  }
});
