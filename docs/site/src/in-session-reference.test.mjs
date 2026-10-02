import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { loadRegistry } from "../../../extension/substrate/registry.ts";
import {
  PACKAGE_TOOL_POLICY,
  SYNTHETIC_PATH_TOOL_POLICY,
} from "../../../extension/substrate/toolPolicy.ts";
import { loadPerkSession, scaffoldRepo } from "../../../extension/testing/harness.ts";

// Source/runtime guard for the split in-session reference. The docs own prose; runtime owns
// vocabulary and matrix facts. Marked regions keep those facts machine-comparable without a
// second hand-maintained expected list in this test.

const userDocsDir = fileURLToPath(new URL("../../user-docs/", import.meta.url));
const hubPath = path.join(userDocsDir, "reference/in-session.md");
const toolsPath = path.join(userDocsDir, "reference/in-session/model-tools.md");
const stagesPath = path.join(userDocsDir, "reference/in-session/stages-and-doors.mdx");
const matrixPath = fileURLToPath(
  new URL("../../../shared/fixtures/tool-matrix.json", import.meta.url),
);

function read(file) {
  return fs.readFileSync(file, "utf8");
}

function markedRegion(source, begin, end, selector) {
  assert.equal(source.split(begin).length - 1, 1, `${selector}: begin marker must occur once`);
  assert.equal(source.split(end).length - 1, 1, `${selector}: end marker must occur once`);
  const start = source.indexOf(begin) + begin.length;
  const finish = source.indexOf(end, start);
  assert.ok(finish > start, `${selector}: marker order/region is invalid`);
  const region = source.slice(start, finish);
  assert.ok(region.trim().length > 0, `${selector}: selected an empty region`);
  return region;
}

function dataRows(region, selector) {
  const rows = region
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("|") && line.endsWith("|"))
    .map((line) =>
      line
        .slice(1, -1)
        .split("|")
        .map((cell) => cell.trim()),
    )
    .filter((cells) => !cells.every((cell) => /^-+$/.test(cell)))
    .slice(1);
  assert.ok(rows.length > 0, `${selector}: table has no data rows`);
  return rows;
}

function oneCodeNamePerRow(region, selector) {
  const names = dataRows(region, selector).map((cells, index) => {
    const matches = [...cells.join(" | ").matchAll(/`([a-z][a-z0-9_-]+)`/g)].map(
      (match) => match[1],
    );
    assert.equal(matches.length, 1, `${selector}: row ${index + 1} must carry exactly one name`);
    return matches[0];
  });
  assert.equal(new Set(names).size, names.length, `${selector}: duplicate name`);
  return names;
}

function slashCommands(region) {
  const commands = [...region.matchAll(/`(\/[a-z][a-z0-9-]*)`/g)].map((match) => match[1]);
  assert.ok(commands.length > 0, "command census: no slash commands selected");
  assert.equal(new Set(commands).size, commands.length, "command census: duplicate command");
  return commands;
}

function assertSetEqual(actual, expected, message) {
  assert.deepEqual([...actual].sort(), [...expected].sort(), message);
}

function booleanCell(value, selector) {
  assert.ok(value === "yes" || value === "—", `${selector}: expected yes or —, got ${value}`);
  return value === "yes";
}

async function loadDefaultPerkSession() {
  const cwd = scaffoldRepo();
  const savedCwd = process.cwd();
  process.chdir(cwd);
  try {
    return await loadPerkSession({ cwd, env: { PERK_RUN_ID: undefined } });
  } finally {
    process.chdir(savedCwd);
  }
}

test("marked command and perk-tool censuses equal a default perk-only harness session", async () => {
  const commandRegion = markedRegion(
    read(hubPath),
    "<!-- BEGIN perk command census -->",
    "<!-- END perk command census -->",
    "command census",
  );
  const documentedCommands = slashCommands(commandRegion).map((name) => name.slice(1));
  for (const known of ["plan", "objective", "ci", "pr-review-browser", "btw"]) {
    assert.ok(documentedCommands.includes(known), `command census: known anchor /${known} missing`);
  }

  const perkToolRegion = markedRegion(
    read(toolsPath),
    "<!-- BEGIN perk tool census -->",
    "<!-- END perk tool census -->",
    "perk tool census",
  );
  const documentedPerkTools = oneCodeNamePerRow(perkToolRegion, "perk tool census");
  for (const known of ["plan_draft", "run_ci", "objective_stack_land"]) {
    assert.ok(
      documentedPerkTools.includes(known),
      `perk tool census: known anchor ${known} missing`,
    );
  }

  const harness = await loadDefaultPerkSession();
  try {
    assertSetEqual(
      documentedCommands,
      harness.registeredCommands(),
      "documented slash commands must equal the live default registration set",
    );
    const registeredPerkTools = harness.session
      .getAllTools()
      .filter((tool) => tool.sourceInfo.source !== "builtin")
      .map((tool) => tool.name);
    assertSetEqual(
      documentedPerkTools,
      registeredPerkTools,
      "documented perk tools must equal the live perk-only non-builtin registrations",
    );
    const matrix = JSON.parse(read(matrixPath));
    const catalogued = Object.entries(matrix.tools)
      .filter(([, entry]) => entry.owner === "perk")
      .map(([name]) => name);
    assertSetEqual(
      documentedPerkTools,
      catalogued,
      "documented perk tools must equal the tool catalog (shared/fixtures/tool-matrix.json)",
    );
    for (const cells of dataRows(perkToolRegion, "perk tool census")) {
      assert.equal(cells.length, 4, "perk tool census: Family | Tool | Kind | Under the gate");
      const [, toolCell, kind, gate] = cells;
      const name = toolCell.match(/`([^`]+)`/)?.[1];
      const entry = matrix.tools[name];
      assert.equal(kind, entry.kind, `${name}: Kind drift against the tool matrix`);
      const expectedGate = `${entry.gated}${entry.mode_over_stage ? ", mode-over-stage" : ""}`;
      assert.equal(gate, expectedGate, `${name}: Under-the-gate drift against the tool matrix`);
    }
    assert.ok(
      documentedPerkTools.includes("resolve_submit_conflicts"),
      "single-use foreground tool must be documented",
    );
    assert.ok(
      !documentedPerkTools.some((name) => name.includes("unlock")),
      "recovery remains human-only",
    );
  } finally {
    harness.dispose();
  }
});

test("marked foreign posture table and Linear exception equal the provenance-posture authority", () => {
  const source = read(toolsPath);
  const region = markedRegion(
    source,
    "<!-- BEGIN foreign posture table -->",
    "<!-- END foreign posture table -->",
    "foreign posture table",
  );
  const matrix = JSON.parse(read(matrixPath));
  const rows = matrix.postures;
  const documented = dataRows(region, "foreign posture table").map((cells, index) => {
    assert.equal(cells.length, 4, `foreign posture table row ${index + 1}: four columns`);
    const [provenanceCell, posture, , gate] = cells;
    const provenance = provenanceCell.match(/^`([^`]+)`$/)?.[1];
    assert.ok(provenance !== undefined, `foreign posture table row ${index + 1}: one provenance`);
    const row = rows.packages[provenance] ?? rows.paths[provenance];
    assert.ok(row !== undefined, `${provenance}: no posture row`);
    assert.equal(posture.split(" ")[0], row.posture, `${provenance}: Posture drift`);
    assert.equal(gate, row.gated, `${provenance}: Under-the-gate drift`);
    return provenance;
  });
  assert.equal(new Set(documented).size, documented.length, "foreign posture table: duplicate");
  assertSetEqual(
    documented,
    [...Object.keys(PACKAGE_TOOL_POLICY), ...Object.keys(SYNTHETIC_PATH_TOOL_POLICY)],
    "documented provenance rows must equal PACKAGE_TOOL_POLICY ∪ SYNTHETIC_PATH_TOOL_POLICY",
  );
  const linear = oneCodeNamePerRow(
    markedRegion(
      source,
      "<!-- BEGIN linear exception -->",
      "<!-- END linear exception -->",
      "linear exception",
    ),
    "linear exception",
  );
  assertSetEqual(
    linear,
    PACKAGE_TOOL_POLICY["npm:pi-mono-linear"]?.except?.names ?? [],
    "documented Linear exception names must equal the package row's except list",
  );
});

test("marked stage matrix equals registry order, modes, doors, and cold command labels", () => {
  const region = markedRegion(
    read(stagesPath),
    "{/* BEGIN perk stage matrix */}",
    "{/* END perk stage matrix */}",
    "stage matrix",
  );
  const rows = dataRows(region, "stage matrix");
  const registry = loadRegistry();
  assert.equal(rows.length, registry.stages.length, "stage matrix must cover every registry stage");

  const seen = new Set();
  rows.forEach((cells, index) => {
    assert.equal(cells.length, 7, `stage matrix row ${index + 1}: expected seven columns`);
    const [stageCell, mode, warm, warmCommand, coldLocal, coldCommand, coldRemote] = cells;
    const id = stageCell.match(/`([^`]+)`/)?.[1];
    assert.ok(id, `stage matrix row ${index + 1}: missing code-form stage id`);
    assert.ok(!seen.has(id), `stage matrix: duplicate stage ${id}`);
    seen.add(id);

    const expected = registry.stages[index];
    assert.equal(id, expected.id, `stage matrix row ${index + 1}: registry order drift`);
    assert.equal(mode, expected.mode, `${id}: mode drift`);
    assert.equal(booleanCell(warm, `${id} warm`), expected.doors.warm, `${id}: warm drift`);
    assert.equal(
      booleanCell(coldLocal, `${id} cold-local`),
      expected.doors.cold_local,
      `${id}: cold-local drift`,
    );
    assert.equal(
      booleanCell(coldRemote, `${id} cold-remote`),
      expected.doors.cold_remote,
      `${id}: cold-remote drift`,
    );
    const expectedCold =
      id === "audit" ? `\`perk-dev ${expected.command}\`` : `\`perk ${expected.command}\``;
    assert.equal(coldCommand, expectedCold, `${id}: cold command label drift`);

    if (id === "gist-author" || id === "objective-author") {
      assert.equal(warmCommand, "no standalone slash launcher", `${id}: launcher distinction lost`);
    }
    if (id === "implement") {
      assert.match(warmCommand, /refresh only; not a warm stage door/);
    }
  });

  for (const known of ["gist-author", "implement", "audit"]) {
    assert.ok(seen.has(known), `stage matrix: known anchor ${known} missing`);
  }
});
