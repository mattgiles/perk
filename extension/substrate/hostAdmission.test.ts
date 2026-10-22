// The pure SDK-boundary admission decision (contracts.md §8.76(f)) and its exact refusal texts,
// plus the precondition pin: the SDK this suite runs on is itself admitted by the shipped floor.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import {
  admitHostSdk,
  formatHostSdkRefusal,
  HOST_SDK_PACKAGE,
  type HostSdkAdmission,
  hostSdkErrorType,
  REQUIREMENTS_DOC_URL,
} from "./hostAdmission.ts";
import { loadHostFloor } from "./hostFloor.ts";
import { loadedHostSdkVersion } from "./hostSdkVersion.ts";

const REPO_ROOT = fileURLToPath(new URL("../../", import.meta.url));
const DOC_URL =
  "https://github.com/mattgiles/perk/blob/main/docs/user-docs/reference/requirements-and-compatibility.md#version-compatibility";

test("constants: the SDK package and the public requirements reference", () => {
  assert.equal(HOST_SDK_PACKAGE, "@earendil-works/pi-coding-agent");
  assert.equal(REQUIREMENTS_DOC_URL, DOC_URL);
});

test("the refusal's public URL points at a file and heading that exist in this checkout", () => {
  // The URL is the always-available repair source (the docs tree ships in no distribution), so a
  // moved or re-headed page must fail here, not on a user.
  const [, afterBlob] = REQUIREMENTS_DOC_URL.split("/blob/main/");
  assert.ok(afterBlob, REQUIREMENTS_DOC_URL);
  const [relative, anchor] = afterBlob.split("#");
  assert.ok(relative, REQUIREMENTS_DOC_URL);
  assert.equal(anchor, "version-compatibility");
  const doc = path.join(REPO_ROOT, relative);
  assert.ok(fs.existsSync(doc), doc);
  const headings = fs.readFileSync(doc, "utf8").split("\n");
  assert.ok(headings.includes("## Version compatibility"), doc);
});

for (const [observed, canonical] of [
  ["1.0.0", "1.0.0"],
  ["1.0.1", "1.0.1"],
  ["1.10.0", "1.10.0"],
  ["v1.0.0", "1.0.0"],
  ["1.0.0+abc", "1.0.0"],
] as const) {
  test(`admitHostSdk: ${observed} is admitted as ${canonical}`, () => {
    assert.deepEqual(admitHostSdk(observed, "1.0.0"), {
      outcome: "admitted",
      observed: canonical,
      required: "1.0.0",
      detail: "",
    });
  });
}

for (const observed of ["0.99.2", "1.0.0-rc.1"]) {
  test(`admitHostSdk: ${observed} is unsupported`, () => {
    const admission = admitHostSdk(observed, "1.0.0");
    assert.deepEqual(admission, {
      outcome: "unsupported",
      observed,
      required: "1.0.0",
      detail: "",
    });
    assert.equal(hostSdkErrorType(admission), "pi_version_unsupported");
  });
}

test("admitHostSdk: a missing or non-string VERSION is unverifiable", () => {
  assert.deepEqual(admitHostSdk(undefined, "1.0.0"), {
    outcome: "unverifiable",
    observed: null,
    required: "1.0.0",
    detail: "@earendil-works/pi-coding-agent exports no VERSION string (got undefined)",
  });
  assert.equal(
    admitHostSdk(42, "1.0.0").detail,
    "@earendil-works/pi-coding-agent exports no VERSION string (got number)",
  );
  assert.equal(hostSdkErrorType(admitHostSdk(undefined, "1.0.0")), "pi_version_unverifiable");
});

test("admitHostSdk: an unparseable VERSION string is unverifiable with a bounded preview", () => {
  assert.deepEqual(admitHostSdk("", "1.0.0"), {
    outcome: "unverifiable",
    observed: null,
    required: "1.0.0",
    detail: 'VERSION is "" instead of a version',
  });
  assert.equal(admitHostSdk("latest", "1.0.0").detail, 'VERSION is "latest" instead of a version');
  const long = "x".repeat(500);
  const admission = admitHostSdk(long, "1.0.0");
  assert.equal(admission.outcome, "unverifiable");
  assert.equal(admission.detail, `VERSION is "${"x".repeat(80)}" instead of a version`);
  assert.equal(hostSdkErrorType(admission), "pi_version_unverifiable");
});

test("admitHostSdk: a floor that is not a version throws (a corrupt bundle)", () => {
  assert.throws(
    () => admitHostSdk("1.0.0", "one"),
    /perk: host floor pi\.min_version is not a version: one/,
  );
});

const UNSUPPORTED: HostSdkAdmission = {
  outcome: "unsupported",
  observed: "0.99.2",
  required: "1.0.0",
  detail: "",
};
const UNVERIFIABLE: HostSdkAdmission = {
  outcome: "unverifiable",
  observed: null,
  required: "1.0.0",
  detail: "@earendil-works/pi-coding-agent exports no VERSION string (got undefined)",
};

test("formatHostSdkRefusal: extension texts", () => {
  assert.equal(
    formatHostSdkRefusal(UNSUPPORTED, "extension"),
    "perk requires Pi >= 1.0.0; the Pi running this session is 0.99.2 " +
      "(@earendil-works/pi-coding-agent VERSION). Upgrade that Pi to perk's adopted Pi version " +
      "with its pinned companion set — the exact npm command is in perk's \"Requirements and " +
      'compatibility" reference (https://github.com/mattgiles/perk/blob/main/docs/user-docs/' +
      "reference/requirements-and-compatibility.md#version-compatibility), and perk init / " +
      "perk doctor print it when the PATH pi is not the adopted one.",
  );
  assert.equal(
    formatHostSdkRefusal(UNVERIFIABLE, "extension"),
    "perk requires Pi >= 1.0.0 and could not verify this Pi's version " +
      "(@earendil-works/pi-coding-agent exports no VERSION string (got undefined)). " +
      "Reinstall that Pi to perk's adopted Pi version with its pinned companion set — the " +
      'exact npm command is in perk\'s "Requirements and compatibility" reference ' +
      "(https://github.com/mattgiles/perk/blob/main/docs/user-docs/reference/" +
      "requirements-and-compatibility.md#version-compatibility), and perk init / perk doctor " +
      "print it when the PATH pi is not the adopted one.",
  );
});

test("formatHostSdkRefusal: worker texts", () => {
  assert.equal(
    formatHostSdkRefusal(UNSUPPORTED, "worker"),
    "perk worker: the loaded Pi SDK (@earendil-works/pi-coding-agent) is version 0.99.2; " +
      "perk requires Pi >= 1.0.0. Reinstall the worker's SDK at a supported version: npm ci " +
      "in this checkout (self-repo), or re-run the remote setup's worker-deps install (consumer).",
  );
  assert.equal(
    formatHostSdkRefusal(UNVERIFIABLE, "worker"),
    "perk worker: could not verify the loaded Pi SDK's version " +
      "(@earendil-works/pi-coding-agent exports no VERSION string (got undefined)); perk " +
      "requires Pi >= 1.0.0. Reinstall the worker's SDK: npm ci in this checkout (self-repo), " +
      "or re-run the remote setup's worker-deps install (consumer).",
  );
});

test("the shipped floor: the previous floor and its prerelease are refused; the floor and an unequal later release are admitted", () => {
  // Readings against the bundled floor itself (not an explicit argument): a raise refuses the
  // floor it replaced, a prerelease of the new floor stays below it, and a later release unequal
  // to the floor and to the dev pin is admitted on its own reading — never equality.
  const floor = loadHostFloor().piMinVersion;
  for (const observed of ["1.0.0", "1.1.0-rc.1"]) {
    assert.deepEqual(admitHostSdk(observed, floor), {
      outcome: "unsupported",
      observed,
      required: "1.1.0",
      detail: "",
    });
  }
  for (const observed of ["1.1.0", "1.2.0"]) {
    assert.deepEqual(admitHostSdk(observed, floor), {
      outcome: "admitted",
      observed,
      required: "1.1.0",
      detail: "",
    });
  }
});

test("precondition: the installed SDK this suite runs on is admitted by the shipped floor", () => {
  // CI's real-runtime tier must run on an admitted SDK. A red pin here means a stale
  // node_modules (e.g. a worktree resolving an older SDK by walk-up) — repair the install.
  const admission = admitHostSdk(loadedHostSdkVersion(), loadHostFloor().piMinVersion);
  assert.equal(admission.outcome, "admitted", JSON.stringify(admission));
});
