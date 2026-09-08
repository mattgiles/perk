import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import {
  type ConfigValue,
  decodeRoutingConfig,
  markRoutingValue,
  projectRoutingConfig,
  ROUTING_CONFIG_FIELDS,
  type RoutingConfigDocument,
  RoutingConfigError,
  routingConfigComponents,
  selectRoutingString,
} from "./draftReviewConfig.ts";
import { digestSessionData } from "./sessionData.ts";

type Case = {
  name: string;
  toml?: string | null;
  bytes_base64?: string;
  values?: Record<string, string | null>;
  refuse?: Record<string, string>;
  equivalent_to?: string;
  dialect?: string;
};
const fixture = JSON.parse(
  readFileSync(
    join(import.meta.dirname, "..", "..", "shared", "fixtures", "draft-review-config.json"),
    "utf8",
  ),
) as { fields: string[]; fake_credential: string; cases: Case[] };
const FIELDS = ["issues.backend", "issues.team", "workflow.base", "linear.api_key"] as const;

function bytesOf(c: Case): Uint8Array | null {
  if (c.bytes_base64 !== undefined) return Buffer.from(c.bytes_base64, "base64");
  if (c.toml === null) return null;
  return Buffer.from(c.toml ?? "", "utf8");
}
function selectAll(document: RoutingConfigDocument): Record<string, string | undefined> {
  const out: Record<string, string | undefined> = {};
  for (const field of FIELDS) {
    const [table, key] = field.split(".") as [string, string];
    out[field] = selectRoutingString(document, "role", table, key);
  }
  return out;
}
function refusal(work: () => unknown): string {
  try {
    work();
  } catch (error) {
    assert.ok(error instanceof RoutingConfigError, String(error));
    assert.equal(error.message, error.explanation);
    return error.explanation;
  }
  assert.fail("expected a routing-config refusal");
}

test("fixture shape: the shared file names exactly the four selected fields", () => {
  assert.deepEqual(fixture.fields, [...FIELDS]);
  assert.ok(fixture.cases.length >= 15);
  assert.match(fixture.fake_credential, /^lin_api_FAKE/);
  const names = new Set(fixture.cases.map((c) => c.name));
  assert.equal(names.size, fixture.cases.length, "case names are unique");
  for (const c of fixture.cases)
    if (c.equivalent_to !== undefined) assert.ok(names.has(c.equivalent_to), c.name);
});

test("TOML 1.1 syntax the vendored parser accepts is not routing drift: decodable here, Python-refused there", () => {
  // The dialect boundary (§8.23): the projection certifies nothing about whole-config validity.
  // A document only the TOML 1.1-capable parser reads (a trailing inline-table comma, a `\x`
  // escape) projects normally — even identically to its TOML 1.0 twin — while Python's reader
  // refuses the whole file, so such an edit surfaces at save as the CLI's config error, never
  // as `target-changed` and never as a save to the wrong place. The fixture pins BOTH readings;
  // if either parser's dialect moves, this test (or its Python twin) trips.
  const dialect = fixture.cases.filter((c) => c.dialect === "toml-1.1");
  assert.deepEqual(
    dialect.map((c) => c.name),
    ["toml-1.1-trailing-comma-in-unrelated-inline-table", "toml-1.1-hex-escape-in-selected-value"],
  );
  for (const c of dialect) {
    assert.equal(c.refuse, undefined, `${c.name}: the TS projection must NOT refuse`);
    assert.ok(c.toml);
    for (const field of ["issues.backend", "issues.team", "workflow.base"])
      assert.deepEqual(
        (c as { python?: Record<string, unknown> }).python?.[field],
        { raises: "TOMLDecodeError" },
        `${c.name}: Python's config reader must refuse ${field}`,
      );
    // The whole document decodes and every selected value is the parser's own reading.
    decodeRoutingConfig(Buffer.from(c.toml, "utf8"), "main_config");
  }
  const [trailingComma, hexEscape] = dialect;
  assert.ok(
    trailingComma?.toml?.includes(", }") && trailingComma.equivalent_to === "basic-strings",
  );
  assert.ok(hexEscape?.toml?.includes("\\x67"));
  assert.equal(hexEscape?.values?.["issues.backend"], "github");
});

for (const c of fixture.cases) {
  test(`fixture ${c.name}: exact decoded strings, absent values, and code-owned refusals`, () => {
    const bytes = bytesOf(c);
    const whole = c.refuse?.["*"];
    if (whole !== undefined) {
      const explanation = refusal(() => decodeRoutingConfig(bytes, "main_config"));
      assert.equal(explanation, `routing config main_config: ${whole}`);
      assert.ok(!explanation.includes(fixture.fake_credential));
      return;
    }
    const document = decodeRoutingConfig(bytes, "main_config");
    for (const field of FIELDS) {
      const [table, key] = field.split(".") as [string, string];
      const refused = c.refuse?.[field];
      if (refused !== undefined) {
        const explanation = refusal(() =>
          selectRoutingString(document, "worktree_local", table, key),
        );
        assert.equal(explanation, `routing config worktree_local: ${refused}`);
        assert.ok(!explanation.includes(fixture.fake_credential), "no config excerpt");
        assert.ok(!explanation.includes("leaked"));
        continue;
      }
      const expected = c.values?.[field];
      assert.notEqual(expected, undefined, `${c.name} lacks ${field}`);
      if (expected === undefined) return;
      const actual = selectRoutingString(document, "main_config", table, key);
      assert.equal(actual, expected === null ? undefined : expected);
      const mark = markRoutingValue(actual);
      if (expected === null) assert.deepEqual(mark, { state: "absent" });
      else {
        assert.deepEqual(mark, { state: "present", digest: digestSessionData(expected) });
        assert.ok(!JSON.stringify(mark).includes(expected) || expected === "");
      }
    }
  });
}

test("equivalent TOML spellings project identically; absent, empty, and comment-only files coincide", () => {
  const byName = new Map(fixture.cases.map((c) => [c.name, c]));
  for (const c of fixture.cases) {
    if (c.equivalent_to === undefined) continue;
    const reference = byName.get(c.equivalent_to);
    assert.ok(reference);
    assert.deepEqual(
      selectAll(decodeRoutingConfig(bytesOf(c), "r")),
      selectAll(decodeRoutingConfig(bytesOf(reference), "r")),
      `${c.name} ≡ ${c.equivalent_to}`,
    );
  }
  // Present-but-different bytes that differ ONLY in an unselected way are also identical.
  const basic = byName.get("basic-strings");
  assert.ok(basic?.toml);
  const withCompaction = `${basic.toml}\n[compaction]\nreserve_tokens = 65536\n`;
  assert.deepEqual(
    selectAll(decodeRoutingConfig(Buffer.from(withCompaction), "r")),
    selectAll(decodeRoutingConfig(Buffer.from(basic.toml), "r")),
  );
  const empty = selectAll(decodeRoutingConfig(Buffer.alloc(0), "r"));
  assert.deepEqual(empty, selectAll(decodeRoutingConfig(null, "r")));
  assert.deepEqual(Object.values(empty), [undefined, undefined, undefined, undefined]);
});

test("selection is exact: equal spelling differences are not identity, but any string difference is", () => {
  const value = (toml: string) =>
    markRoutingValue(
      selectRoutingString(decodeRoutingConfig(Buffer.from(toml), "r"), "r", "issues", "backend"),
    );
  assert.deepEqual(value('[issues]\nbackend = "linear"\n'), value("issues.backend = 'linear'"));
  assert.notDeepEqual(
    value('[issues]\nbackend = "linear"\n'),
    value('[issues]\nbackend = "Linear"\n'),
  );
  assert.notDeepEqual(
    value('[issues]\nbackend = "linear"\n'),
    value('[issues]\nbackend = "linear "\n'),
  );
  assert.notDeepEqual(value('[issues]\nbackend = ""\n'), value("[issues]\n"));
  // Unicode is compared by decoded code points, never by source escaping.
  assert.deepEqual(value('[issues]\nbackend = "雪"\n'), value('[issues]\nbackend = "\\u96EA"\n'));
});

test("projection reads each distinct path once, aliases main/worktree roles, and gates workflow_base by subject", () => {
  const files = new Map<string, Uint8Array | null>();
  const reads: string[] = [];
  const read = (path: string) => {
    reads.push(path);
    const bytes = files.get(path);
    return bytes === undefined ? null : bytes;
  };
  const main = {
    main_config: "/main/config",
    worktree_config: "/main/config",
    worktree_local: "/main/local",
    main_local: "/main/local",
  };
  const linked = {
    main_config: "/main/config",
    worktree_config: "/wt/config",
    worktree_local: "/wt/local",
    main_local: "/main/local",
  };
  files.set(
    "/main/config",
    Buffer.from('[issues]\nbackend = "linear"\nteam = "ENG"\n[workflow]\nbase = "main"\n'),
  );
  files.set(
    "/main/local",
    Buffer.from('[linear]\napi_key = "lin_api_FAKE"\n[workflow]\nbase = "local-main"\n'),
  );
  files.set("/wt/config", Buffer.from('[issues]\nbackend = "github"\n[workflow]\nbase = "wt"\n'));
  files.set(
    "/wt/local",
    Buffer.from('[workflow]\nbase = "wt-local"\n[linear]\napi_key = "lin_api_WORKTREE"\n'),
  );
  const present = (s: string): ConfigValue => ({ state: "present", digest: digestSessionData(s) });

  // Main checkout, plan: two distinct files, each read once, both roles served from one parse.
  const mainPlan = projectRoutingConfig({ workflowBase: true, paths: main, read });
  assert.deepEqual(reads, ["/main/config", "/main/local"]);
  assert.deepEqual(mainPlan, {
    main_issues: { backend: present("linear"), team: present("ENG") },
    workflow_base: { committed: present("main"), local: present("local-main") },
    linear_credentials: { api_key: present("lin_api_FAKE") },
  });
  // Linked worktree, objective: issues + credential come from MAIN; workflow.base from the worktree.
  reads.length = 0;
  const linkedObjective = projectRoutingConfig({ workflowBase: true, paths: linked, read });
  assert.deepEqual(reads, ["/main/config", "/wt/config", "/wt/local", "/main/local"]);
  assert.deepEqual(linkedObjective, {
    main_issues: { backend: present("linear"), team: present("ENG") },
    workflow_base: { committed: present("wt"), local: present("wt-local") },
    linear_credentials: { api_key: present("lin_api_FAKE") },
  });
  // Gist/refinement: workflow_base inactive — the worktree files are not even read.
  reads.length = 0;
  const linkedGist = projectRoutingConfig({ workflowBase: false, paths: linked, read });
  assert.deepEqual(reads, ["/main/config", "/main/local"]);
  assert.deepEqual(linkedGist, {
    main_issues: { backend: present("linear"), team: present("ENG") },
    workflow_base: null,
    linear_credentials: { api_key: present("lin_api_FAKE") },
  });
  // Component view: fixed names; inactive fields are null; no raw credential anywhere.
  const components = routingConfigComponents(linkedGist);
  assert.deepEqual(
    Object.keys(components),
    ROUTING_CONFIG_FIELDS.map((f) => f.name),
  );
  assert.equal(components["worktree_config.workflow.base"], null);
  assert.ok(!JSON.stringify(components).includes("lin_api_"));
  assert.ok(!JSON.stringify(linkedObjective).includes("lin_api_"));

  // Failures name the aliased roles sharing one file, and read errors translate to the role.
  files.set("/main/config", Buffer.from("[issues\n"));
  assert.equal(
    refusal(() => projectRoutingConfig({ workflowBase: true, paths: main, read })),
    "routing config main_config/worktree_config: TOML parse failed",
  );
  files.set("/main/config", Buffer.from('issues = "x"\n'));
  assert.equal(
    refusal(() => projectRoutingConfig({ workflowBase: true, paths: linked, read })),
    "routing config main_config: [issues] is not a table",
  );
  files.set("/main/config", Buffer.from("[issues]\n"));
  assert.equal(
    refusal(() =>
      projectRoutingConfig({
        workflowBase: true,
        paths: linked,
        read(path) {
          if (path === "/wt/local") throw new Error("EACCES /wt/local lin_api_SECRET");
          return read(path);
        },
      }),
    ),
    "routing config worktree_local: unreadable",
  );
  // A huge integer in an unrelated table never breaks the capture.
  files.set(
    "/wt/local",
    Buffer.from("[compaction]\nreserve_tokens = 340282366920938463463374607431768211456\n"),
  );
  assert.deepEqual(
    projectRoutingConfig({ workflowBase: true, paths: linked, read }).workflow_base,
    {
      committed: present("wt"),
      local: { state: "absent" },
    },
  );
});
