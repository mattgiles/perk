// Dev-only loader for the configuration schemas the exact-pinned dev
// `@earendil-works/pi-coding-agent` publishes in its `schemas/` directory (listed in that
// package's `package.json` `files`). perk's producer tests validate the Pi configuration perk
// writes against the adopted Pi's own declared contract through these validators.
//
// The pin bump (`just bump-pi`) IS the refresh: the files are read from whatever the root
// `node_modules` resolves, after asserting that install is the dev pin — never vendored, never
// fetched (the `$schema`/`$id` URLs are never dereferenced). It resolves the ROOT dev install by
// specifier, never the settings-delivered `.pi/npm` copy.

import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Compile } from "typebox/compile";

export const PI_DEV_PACKAGE = "@earendil-works/pi-coding-agent";

/** The structural slice of TypeBox's `Validator` the producer checks use. */
export interface ConfigValidator {
  Check(value: unknown): boolean;
  Errors(value: unknown): readonly { instancePath: string; message: string }[];
}

export interface PiConfigSchemas {
  /** The resolved dev package's manifest version (asserted equal to the dev pin). */
  readonly version: string;
  readonly settings: ConfigValidator;
  readonly models: ConfigValidator;
  /** The settings schema's `$defs.ModelThinkingLevel.enum`, in Pi's order. */
  readonly thinkingLevels: readonly string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readJsonRecord(file: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(readFileSync(file, "utf8"));
  if (!isRecord(parsed)) throw new Error(`${file} is not a JSON object`);
  return parsed;
}

/** The root `package.json`'s exact dev pin of the Pi coding agent. */
export function piDevPin(): string {
  const file = join(import.meta.dirname, "..", "..", "package.json");
  const devDependencies = readJsonRecord(file).devDependencies;
  if (!isRecord(devDependencies)) throw new Error(`${file} has no devDependencies object`);
  const pin = devDependencies[PI_DEV_PACKAGE];
  if (typeof pin !== "string") {
    throw new Error(`${file} has no devDependencies["${PI_DEV_PACKAGE}"] string`);
  }
  return pin;
}

function readSchema(root: string, version: string, kind: "settings" | "models") {
  const file = join(root, "schemas", `${kind}.schema.json`);
  if (!existsSync(file)) {
    throw new Error(
      `${PI_DEV_PACKAGE}@${version} ships no schemas/${kind}.schema.json — re-decide the ` +
        "config-schema producer check per docs/developers/pi-subagents-reverify.md step 4 " +
        "(vendoring is the recorded-decision fallback)",
    );
  }
  return readJsonRecord(file);
}

function thinkingLevelsOf(settingsSchema: Record<string, unknown>): string[] {
  const defs = settingsSchema.$defs;
  const level = isRecord(defs) ? defs.ModelThinkingLevel : undefined;
  const levels = isRecord(level) ? level.enum : undefined;
  if (
    !Array.isArray(levels) ||
    levels.length === 0 ||
    !levels.every((entry): entry is string => typeof entry === "string")
  ) {
    throw new Error(
      "settings.schema.json no longer defines $defs.ModelThinkingLevel.enum — re-derive " +
        "PI_THINKING_LEVEL_ORDER (src/perk/substrate/config.py)",
    );
  }
  return levels;
}

/** Resolve the dev Pi package, assert it is the dev pin, and compile both config schemas. */
export function loadPiConfigSchemas(): PiConfigSchemas {
  // The specifier resolves to <root>/dist/index.js → the package root is one level up from dist/.
  const root = resolve(dirname(fileURLToPath(import.meta.resolve(PI_DEV_PACKAGE))), "..");
  const manifest = readJsonRecord(join(root, "package.json"));
  const { name, version } = manifest;
  const pin = piDevPin();
  if (name !== PI_DEV_PACKAGE || version !== pin) {
    throw new Error(
      `resolved ${String(name)}@${String(version)} at ${root}, but package.json pins ${pin} — ` +
        "run `npm install` in this checkout (a worktree resolves the parent checkout's " +
        "node_modules until it installs its own; docs/learned/toolchain/worktree-node-modules.md)",
    );
  }
  const settingsSchema = readSchema(root, version, "settings");
  const modelsSchema = readSchema(root, version, "models");
  return {
    version,
    settings: Compile(settingsSchema),
    models: Compile(modelsSchema),
    thinkingLevels: thinkingLevelsOf(settingsSchema),
  };
}

/**
 * The validator's verdict as `"<pointer>: <message>"` strings — `[]` only when `Check` passes. A
 * rejection without a reported error still yields one entry (never a false pass).
 */
export function schemaErrors(validator: ConfigValidator, document: unknown): string[] {
  if (validator.Check(document)) return [];
  const errors = validator
    .Errors(document)
    .map(({ instancePath, message }) => `${instancePath === "" ? "/" : instancePath}: ${message}`);
  return errors.length > 0 ? errors : ["/: rejected without a reported error"];
}
