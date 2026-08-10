// The TS plane's twin of perk/_resources.py: locate the bundled `shared/`
// contracts dir and read the lockstep version. `extension/` and `shared/` are
// siblings in both the dev tree and the published tarball (npm `files` preserves
// the layout), so a single `../shared` path resolves in both modes — no
// dual-path manifest is needed.

import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

function packageRoot(): string {
  return join(dirname(fileURLToPath(import.meta.url)), "..", "..");
}

/** Absolute path to the bundled `shared/` contracts directory. */
export function sharedDir(): string {
  const dir = join(packageRoot(), "shared");
  if (!existsSync(dir)) {
    throw new Error(`perk: could not locate the bundled 'shared/' directory at ${dir}`);
  }
  return dir;
}

/** Absolute path to the bundled `prompts/` directory. */
export function promptsDir(): string {
  const dir = join(packageRoot(), "prompts");
  if (!existsSync(dir)) {
    throw new Error(`perk: could not locate the bundled 'prompts/' directory at ${dir}`);
  }
  return dir;
}

/** perk version, read from the package.json shipped alongside the extension. */
export function perkVersion(): string {
  try {
    const pkg = JSON.parse(readFileSync(join(packageRoot(), "package.json"), "utf8"));
    return typeof pkg.version === "string" ? pkg.version : "0.0.0";
  } catch {
    return "0.0.0";
  }
}

/**
 * The vintage-stamp filter over a perkVersion() value: the version, or undefined for the
 * "0.0.0" failure sentinel. A `perk_version` stamp claims an EXACT session vintage
 * (contracts §8.3 — the session-audit read side treats it as the exact basis), so the
 * self-confessed-unknown sentinel must not masquerade as one; omitting the stamp leaves the
 * session on the honest timestamp-estimate arm.
 */
export function versionStamp(version: string): string | undefined {
  return version === "0.0.0" ? undefined : version;
}
