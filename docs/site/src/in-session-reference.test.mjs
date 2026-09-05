import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { loadRegistry } from "../../../extension/substrate/registry.ts";
import {
  BORROWED_TOOLS,
  PERK_TOOLS,
  SUBAGENT_CHILD_TOOLS,
} from "../../../extension/substrate/toolGating.ts";
import { loadPerkSession, scaffoldRepo } from "../../../extension/testing/harness.ts";

// Source/runtime guard for the split in-session reference. The docs own prose; runtime owns
// vocabulary and matrix facts. Marked regions keep those facts machine-comparable without a
// second hand-maintained expected list in this test.

const userDocsDir = fileURLToPath(new URL("../../user-docs/", import.meta.url));
const hubPath = path.join(userDocsDir, "reference/in-session.md");
const toolsPath = path.join(userDocsDir, "reference/in-session/model-tools.md");
const stagesPath = path.join(userDocsDir, "reference/in-session/stages-and-doors.mdx");

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
    assertSetEqual(documentedPerkTools, PERK_TOOLS, "documented perk tools must equal PERK_TOOLS");
  } finally {
    harness.dispose();
  }
});

test("marked borrowed and spawned-child censuses equal their exported authorities", () => {
  const source = read(toolsPath);
  const borrowed = oneCodeNamePerRow(
    markedRegion(
      source,
      "<!-- BEGIN borrowed tool census -->",
      "<!-- END borrowed tool census -->",
      "borrowed tool census",
    ),
    "borrowed tool census",
  );
  const children = oneCodeNamePerRow(
    markedRegion(
      source,
      "<!-- BEGIN child tool census -->",
      "<!-- END child tool census -->",
      "child tool census",
    ),
    "child tool census",
  );
  for (const known of ["web_search", "linear_create_issue", "subagent", "todo"]) {
    assert.ok(borrowed.includes(known), `borrowed tool census: known anchor ${known} missing`);
  }
  assert.ok(children.includes("structured_output"), "child tool census: known anchor missing");
  assert.ok(children.includes("contact_supervisor"), "child tool census: supervisor missing");
  assert.ok(!children.includes("subagent_wait") && !children.includes("bg_wait"));
  assertSetEqual(borrowed, BORROWED_TOOLS, "documented borrowed tools must equal BORROWED_TOOLS");
  assertSetEqual(
    children,
    SUBAGENT_CHILD_TOOLS,
    "documented child tools must equal SUBAGENT_CHILD_TOOLS",
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
