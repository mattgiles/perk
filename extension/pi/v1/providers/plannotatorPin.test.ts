// The Plannotator mirror pin stays ONE fact: the pin is a concrete version, no provider module
// respells a `@plannotator/pi-extension@<semver>` stamp of its own (mirror comments reference
// `PLANNOTATOR_MIRROR_PIN` instead), and every prose carrier names exactly the pinned version.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { PLANNOTATOR_MIRROR_PIN } from "./plannotatorPin.ts";

const STAMP = /@plannotator\/pi-extension@(\d+\.\d+\.\d+)/g;

/** Every `@plannotator/pi-extension@<semver>` version stamped in `text`. */
function stampedVersions(text: string): string[] {
  return [...text.matchAll(STAMP)].flatMap((m) => (m[1] === undefined ? [] : [m[1]]));
}

const REPO_ROOT = new URL("../../../../", import.meta.url);

const PROSE_CARRIERS = [
  "shared/contracts.md",
  "docs/user-docs/reference/requirements-and-compatibility.md",
  "skills/perk-expert/references/providers-and-backends.md",
] as const;

test("the mirror pin is a concrete semver", () => {
  assert.match(PLANNOTATOR_MIRROR_PIN, /^\d+\.\d+\.\d+$/);
});

test("no provider module but plannotatorPin.ts stamps its own plannotator version", () => {
  const files = readdirSync(import.meta.dirname)
    .filter((f) => f.endsWith(".ts"))
    .sort();
  assert.ok(
    ["plannotatorPin.ts", "plannotator.ts", "plannotatorHandoff.ts", "plannotatorPort.ts"].every(
      (f) => files.includes(f),
    ),
    "scan misaimed",
  );
  const stamped = files
    // The pin module owns the version; this guard's own control string is not a stamp.
    .filter((f) => f !== "plannotatorPin.ts" && f !== path.basename(import.meta.filename))
    .flatMap((f) =>
      stampedVersions(readFileSync(`${import.meta.dirname}/${f}`, "utf8")).map((v) => `${f}: ${v}`),
    );
  assert.deepEqual(stamped, [], "reference PLANNOTATOR_MIRROR_PIN (plannotatorPin.ts) instead");
  // Same-classifier control: the scan would see a respelled stamp.
  assert.deepEqual(stampedVersions("pinned at `@plannotator/pi-extension@1.2.3`"), ["1.2.3"]);
});

for (const carrier of PROSE_CARRIERS) {
  test(`${carrier} names exactly the mirror pin`, () => {
    const text = readFileSync(new URL(carrier, REPO_ROOT), "utf8");
    assert.ok(text.includes(`\`@plannotator/pi-extension@${PLANNOTATOR_MIRROR_PIN}\``), carrier);
    const versions = stampedVersions(text);
    assert.ok(versions.length > 0, `${carrier}: no plannotator stamp found`);
    assert.deepEqual(
      [...new Set(versions)],
      [PLANNOTATOR_MIRROR_PIN],
      `${carrier}: every @plannotator/pi-extension@<semver> must equal PLANNOTATOR_MIRROR_PIN`,
    );
  });
}
