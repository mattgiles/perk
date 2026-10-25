// The TS side of the Pi config-schema producer check (dev-only; excluded from the published
// tarball via the `!extension/testing/` rule in package.json `files`). NOT a `.test.ts` — it is
// never picked up by `node --test "extension/**/*.test.ts"`; it is invoked once, as a subprocess,
// by the Python-owned `tests/test_pi_config_schemas.py`.
//
// argv: <settings.json> [<settings.json> ...]. Validates each file's parsed JSON, whole and
// unmodified, against the exact-pinned dev Pi package's `schemas/settings.schema.json` and prints
// `{"version", "thinkingLevels", "results"}` on stdout — `results` holds one error-string array per
// file IN ARGV ORDER (`[]` = conforms). A loader failure (version mismatch, missing schema) exits
// non-zero with its message on stderr.

import { readFileSync } from "node:fs";
import { loadPiConfigSchemas, schemaErrors } from "./piConfigSchemas.ts";

const files = process.argv.slice(2);
if (files.length === 0) {
  process.stderr.write("usage: node piConfigSchemasLive.ts <settings.json> [...]\n");
  process.exit(2);
}

const schemas = loadPiConfigSchemas();
const results = files.map((file) =>
  schemaErrors(schemas.settings, JSON.parse(readFileSync(file, "utf8"))),
);
process.stdout.write(
  JSON.stringify({ version: schemas.version, thinkingLevels: schemas.thinkingLevels, results }),
);
