import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";

import {
  PONYTAIL_CORE_SKILL,
  PONYTAIL_PACKAGE_ROOT,
  PONYTAIL_REVIEW_SKILL,
  preflightPonytailSkill,
  type RequiredPonytailSkill,
} from "./ponytail.ts";

async function withRepo(run: (root: string) => Promise<void>): Promise<void> {
  const root = await mkdtemp(path.join(tmpdir(), "perk-ponytail-"));
  try {
    await run(root);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

function failureDetail(result: Awaited<ReturnType<typeof preflightPonytailSkill>>): string {
  assert.equal(result.ok, false);
  return result.ok ? "" : result.detail;
}

async function plantPackage(
  root: string,
  options: {
    packageName?: string;
    advertised?: unknown;
    coreName?: string;
    reviewName?: string;
  } = {},
): Promise<void> {
  const packageRoot = path.join(root, PONYTAIL_PACKAGE_ROOT);
  await mkdir(packageRoot, { recursive: true });
  await writeFile(
    path.join(packageRoot, "package.json"),
    JSON.stringify({
      name: options.packageName ?? "@dietrichgebert/ponytail",
      pi: { skills: options.advertised ?? ["./skills"] },
    }),
  );
  for (const [requirement, name] of [
    [PONYTAIL_CORE_SKILL, options.coreName ?? "ponytail"],
    [PONYTAIL_REVIEW_SKILL, options.reviewName ?? "ponytail-review"],
  ] as Array<[RequiredPonytailSkill, string]>) {
    const file = path.join(root, requirement.skillFile);
    await mkdir(path.dirname(file), { recursive: true });
    await writeFile(
      file,
      `---\nname: ${name}\ndescription: >\n  source-bound test skill\n  with folded prose\n---\n\n# Skill\n`,
    );
  }
}

test("preflight accepts both exact known skill files", async () => {
  await withRepo(async (root) => {
    await plantPackage(root);
    assert.deepEqual(await preflightPonytailSkill(PONYTAIL_CORE_SKILL, root), { ok: true });
    assert.deepEqual(await preflightPonytailSkill(PONYTAIL_REVIEW_SKILL, root), { ok: true });
  });
});

test("preflight rejects package identity and skills advertisement drift", async () => {
  await withRepo(async (root) => {
    await plantPackage(root, { packageName: "hostile" });
    assert.match(
      failureDetail(await preflightPonytailSkill(PONYTAIL_CORE_SKILL, root)),
      /package identity/,
    );
    await plantPackage(root, { advertised: [] });
    assert.match(
      failureDetail(await preflightPonytailSkill(PONYTAIL_CORE_SKILL, root)),
      /does not advertise/,
    );
  });
});

test("preflight rejects a missing exact file and wrong frontmatter name", async () => {
  await withRepo(async (root) => {
    await plantPackage(root, { reviewName: "ponytail" });
    assert.match(
      failureDetail(await preflightPonytailSkill(PONYTAIL_REVIEW_SKILL, root)),
      /frontmatter name is not ponytail-review/,
    );
    await rm(path.join(root, PONYTAIL_CORE_SKILL.skillFile));
    assert.match(
      failureDetail(await preflightPonytailSkill(PONYTAIL_CORE_SKILL, root)),
      /missing or unreadable/,
    );
  });
});

test("same-named project skills never satisfy or override the exact package source", async () => {
  await withRepo(async (root) => {
    const hostile = path.join(root, ".agents/skills/ponytail/SKILL.md");
    await mkdir(path.dirname(hostile), { recursive: true });
    await writeFile(hostile, "---\nname: ponytail\ndescription: hostile\n---\n");

    const absent = await preflightPonytailSkill(PONYTAIL_CORE_SKILL, root);
    assert.equal(absent.ok, false, "project collision must not satisfy an absent package file");

    await plantPackage(root);
    assert.deepEqual(await preflightPonytailSkill(PONYTAIL_CORE_SKILL, root), { ok: true });
  });
});
