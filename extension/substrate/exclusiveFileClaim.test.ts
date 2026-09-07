import assert from "node:assert/strict";
import {
  closeSync,
  existsSync,
  mkdtempSync,
  readFileSync,
  readSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type TestContext, test } from "node:test";
import { acquireExclusiveFileClaim, type ClaimRecordCodec } from "./exclusiveFileClaim.ts";

const codec: ClaimRecordCodec<{ label: string }> = {
  encode: (token) => ({ token, label: "fixture" }),
  decode(raw) {
    if (
      typeof raw !== "object" ||
      raw === null ||
      !("token" in raw) ||
      typeof raw.token !== "string" ||
      !("label" in raw) ||
      typeof raw.label !== "string"
    )
      return null;
    return { token: raw.token, owner: { label: raw.label } };
  },
};
function fixture(t: TestContext) {
  const dir = mkdtempSync(join(tmpdir(), "perk-claim-core-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  return join(dir, "resource.lock");
}
function fault(): never {
  throw Object.assign(new Error("induced"), { code: "EIO" });
}

test("codec receives a fresh UUID, check reads back, diagnostics omit token, metadata never changes", (t) => {
  const path = fixture(t);
  let reads = 0;
  const result = acquireExclusiveFileClaim(path, codec, {
    read(...args) {
      reads++;
      return readSync(...args);
    },
  });
  assert.equal(result.kind, "acquired");
  if (result.kind !== "acquired") return;
  const bytes = readFileSync(path, "utf8");
  const token = JSON.parse(bytes).token;
  assert.match(token, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.equal(result.claim.check(), "owned");
  assert.ok(reads > 0);
  assert.deepEqual(acquireExclusiveFileClaim(path, codec), {
    kind: "busy",
    path,
    owner: { label: "fixture" },
  });
  assert.equal(readFileSync(path, "utf8"), bytes);
  result.claim.finish("release");
  const next = acquireExclusiveFileClaim(path, codec);
  assert.equal(next.kind, "acquired");
  if (next.kind !== "acquired") return;
  assert.notEqual(JSON.parse(readFileSync(path, "utf8")).token, token);
  next.claim.finish("release");
});

for (const failure of ["encode", "sync"] as const) {
  test(`initial ${failure} failure cleans only the fresh file and closes once`, (t) => {
    const path = fixture(t);
    let closes = 0;
    const result = acquireExclusiveFileClaim(
      path,
      {
        ...codec,
        encode: failure === "encode" ? fault : codec.encode,
      },
      {
        ...(failure === "sync" ? { sync: fault } : {}),
        close(fd) {
          closes++;
          closeSync(fd);
        },
      },
    );
    assert.deepEqual(result, { kind: "io-error", path, residue: false });
    assert.equal(existsSync(path), false);
    assert.equal(closes, 1);
  });
}

test("sync failure after replacement leaves successor residue", (t) => {
  const path = fixture(t);
  assert.deepEqual(
    acquireExclusiveFileClaim(path, codec, {
      sync() {
        renameSync(path, `${path}.old`);
        writeFileSync(path, "successor");
        fault();
      },
    }),
    { kind: "io-error", path, residue: true },
  );
  assert.equal(readFileSync(path, "utf8"), "successor");
});

for (const broken of [
  "malformed",
  "decode-throw",
  "read-error",
  "short-read",
  "close-error",
] as const) {
  test(`incumbent ${broken} never acquires or reclaims`, (t) => {
    const path = fixture(t);
    writeFileSync(path, broken === "malformed" ? "{" : JSON.stringify(codec.encode("incumbent")));
    const result = acquireExclusiveFileClaim(
      path,
      broken === "decode-throw" ? { ...codec, decode: fault } : codec,
      broken === "read-error"
        ? { read: fault }
        : broken === "short-read"
          ? { read: () => 0 }
          : broken === "close-error"
            ? {
                close(fd) {
                  closeSync(fd);
                  fault();
                },
              }
            : {},
    );
    assert.equal(
      result.kind,
      broken === "read-error" || broken === "close-error" ? "io-error" : "busy",
    );
    assert.ok(existsSync(path));
  });
}

for (const size of [16384, 16385]) {
  test(`incumbent byte limit ${size} bounds diagnostic reads`, (t) => {
    const path = fixture(t);
    const record = JSON.stringify(codec.encode("incumbent"));
    writeFileSync(path, record.padEnd(size));
    let reads = 0;
    const result = acquireExclusiveFileClaim(path, codec, {
      read(...args) {
        reads++;
        return readSync(...args);
      },
    });
    assert.deepEqual(result, {
      kind: "busy",
      path,
      ...(size === 16384 ? { owner: { label: "fixture" } } : {}),
    });
    assert.equal(reads > 0, size === 16384);
  });
}

test("relative resource paths refuse before filesystem effects", () => {
  let opens = 0;
  assert.deepEqual(
    acquireExclusiveFileClaim("resource.lock", codec, {
      open() {
        opens++;
        return 1;
      },
    }),
    { kind: "io-error", path: "resource.lock", residue: false },
  );
  assert.equal(opens, 0);
});
