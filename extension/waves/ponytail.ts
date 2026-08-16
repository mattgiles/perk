// The source-identity boundary for Perk's automatic Ponytail review lanes. Ponytail is installed
// as an all-resource-disabled project package, so ordinary Pi sessions never discover any of its
// resources. A review lane opts into exactly one skill through its agent's invocation-local
// `skillPath`; this module preflights the exact project package + file before that lane can spawn.
// A same-named project/user skill is never a fallback source.

import { readFile } from "node:fs/promises";
import path from "node:path";

import { parse as parseMiniYaml } from "../substrate/miniYaml.ts";

export const PONYTAIL_PACKAGE_NAME = "@dietrichgebert/ponytail";
export const PONYTAIL_PACKAGE_ROOT = ".pi/npm/node_modules/@dietrichgebert/ponytail";

export type PonytailSkillName = "ponytail" | "ponytail-review";

/** Non-serialized lane metadata: the exact package skill a lane requires. */
export interface RequiredPonytailSkill {
  skill: PonytailSkillName;
  skillFile: string;
}

export const PONYTAIL_CORE_SKILL: RequiredPonytailSkill = {
  skill: "ponytail",
  skillFile: `${PONYTAIL_PACKAGE_ROOT}/skills/ponytail/SKILL.md`,
};

export const PONYTAIL_REVIEW_SKILL: RequiredPonytailSkill = {
  skill: "ponytail-review",
  skillFile: `${PONYTAIL_PACKAGE_ROOT}/skills/ponytail-review/SKILL.md`,
};

export type PonytailPreflight = { ok: true } | { ok: false; detail: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function frontmatter(text: string): Record<string, unknown> | null {
  if (!text.startsWith("---\n")) return null;
  const lines = text.split("\n");
  const end = lines.findIndex((line, index) => index > 0 && line === "---");
  if (end < 0) return null;
  try {
    const parsed = parseMiniYaml(lines.slice(1, end).join("\n"));
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * Validate one exact source-bound skill against the project install. The check is deliberately
 * self-contained and fail-closed: package identity, `pi.skills`, exact file readability, and
 * frontmatter name must all agree. Callers invoke it once per review pass and skip only the
 * affected lane on failure.
 */
export async function preflightPonytailSkill(
  requirement: RequiredPonytailSkill,
  repoRoot = process.cwd(),
): Promise<PonytailPreflight> {
  const packageRoot = path.resolve(repoRoot, PONYTAIL_PACKAGE_ROOT);
  let manifest: unknown;
  try {
    manifest = JSON.parse(await readFile(path.join(packageRoot, "package.json"), "utf8"));
  } catch {
    return { ok: false, detail: "Ponytail package.json is missing, unreadable, or invalid JSON" };
  }
  if (!isRecord(manifest) || manifest.name !== PONYTAIL_PACKAGE_NAME) {
    return {
      ok: false,
      detail: `Ponytail package identity does not match ${PONYTAIL_PACKAGE_NAME}`,
    };
  }
  const pi = manifest.pi;
  const advertised = isRecord(pi) ? pi.skills : undefined;
  if (!Array.isArray(advertised) || !advertised.includes("./skills")) {
    return { ok: false, detail: "Ponytail package.json does not advertise ./skills in pi.skills" };
  }

  let skillText: string;
  try {
    skillText = await readFile(path.resolve(repoRoot, requirement.skillFile), "utf8");
  } catch {
    return {
      ok: false,
      detail: `required Ponytail skill is missing or unreadable: ${requirement.skillFile}`,
    };
  }
  const metadata = frontmatter(skillText);
  if (metadata === null || metadata.name !== requirement.skill) {
    return {
      ok: false,
      detail: `required Ponytail skill frontmatter name is not ${requirement.skill}: ${requirement.skillFile}`,
    };
  }
  return { ok: true };
}
