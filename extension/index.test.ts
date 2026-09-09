// Extension-factory wiring tests. The live harness binds extension/index.ts through Pi's real
// loader and runner, so these assertions cover registration rather than only renderer helpers —
// and the activation wiring: footer install/vacate, version parity.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { REPORT_DETAIL_TYPE } from "./surfaces/surfaces.ts";
import { loadPerkSession, scaffoldRepo } from "./testing/harness.ts";

test("the perk factory registers the report-detail renderer", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.deepEqual(
      h.renderAppendedEntry(REPORT_DETAIL_TYPE, {
        text: "perk: submit — failed\ncomplete detail",
        severity: "error",
      }),
      ["<error>perk: submit — failed</>", "<dim>complete detail</>"],
    );
  } finally {
    h.dispose();
  }
});

test("footer install: a headful claim installs the perk footer once with the identity segment and no toast or working indicator; headless installs none", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    // The `v<version> loaded` toast is retired — identity is a standing footer segment.
    assert.ok(!h.notifies.some((m) => m.includes("loaded")));
    assert.ok(h.footerFactory() !== null, "the perk footer factory was installed");
    const footer = h.renderFooter(80);
    assert.equal(footer.length, 1);
    assert.ok((footer[0] as string).includes("perk v"), footer[0]);
    // D5 rescinded: perk never touches the working indicator.
    assert.equal(h.workingIndicators.length, 0);
  } finally {
    h.dispose();
  }
  // Headless (ctx.hasUI === false): no footer, no working indicator, and no UI notifications even
  // on the loud unclaimed path (the report seam writes to stderr instead).
  const headless = await loadPerkSession({
    cwd: scaffoldRepo(),
    env: { PERK_RUN_ID: "01MISS" },
    headful: false,
  });
  try {
    assert.equal(headless.footerFactory(), null);
    assert.equal(headless.workingIndicators.length, 0);
    assert.equal(headless.notifies.length, 0);
  } finally {
    headless.dispose();
  }
});

for (const footerId of ["pi-bar-footer", "pi-status-footer", "pi-default"]) {
  test(`footer seam: a foreign [providers] footer = "${footerId}" selection vacates installPerkFooter`, async () => {
    // Install-site (runtime) vacating: under a non-`perk-footer` selection perk does NOT install
    // its own footer (no factory captured), leaving the foreign footer (or pi's stock footer, for
    // `pi-default`) as the sole surface. The default-repo case (factory installed) is proven by
    // the footer install test above.
    const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
    mkdirSync(join(cwd, ".perk"), { recursive: true });
    writeFileSync(
      join(cwd, ".perk", "config.toml"),
      `[providers]\nfooter = "${footerId}"\n`,
      "utf8",
    );
    const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
    try {
      assert.equal(
        h.footerFactory(),
        null,
        "perk installed no footer under a foreign footer selection",
      );
    } finally {
      h.dispose();
    }
  });
}

test("footer install: a same-activation session_start re-emit reinstalls the footer", async () => {
  // Install-per-headful-session_start (pi ≥ 0.84's explicit dispose-on-replace contract): a
  // second `session_start` on the SAME activation installs a fresh factory. Discriminating:
  // the retired once-only `footerInstalled` guard recorded exactly one install here — a
  // `reload()`-based probe cannot tell the difference (reload re-runs the extension factory,
  // resetting any module-level guard).
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.equal(h.footerInstallCount(), 1, "bind installs the footer once");
    await h.emitSessionStart();
    assert.equal(h.footerInstallCount(), 2, "a same-activation session_start reinstalls");
    const footer = h.renderFooter(80);
    assert.equal(footer.length, 1, "FOOTER_MAX_LINES holds after the reinstall");
  } finally {
    h.dispose();
  }
});

test("version parity: a divergent PERK_CLI_VERSION emits the soft drift warning", async () => {
  // The harness loads the extension from source, so perkVersion() is the real repo
  // package.json version; a fake PERK_CLI_VERSION guarantees a mismatch -> the warning fires.
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID", PERK_CLI_VERSION: "9.9.9-not-real" },
  });
  try {
    assert.ok(
      h.notifies.some((m) => /version parity/.test(m)),
      `expected a version-parity warning, got ${JSON.stringify(h.notifies)}`,
    );
  } finally {
    h.dispose();
  }
});

test("version parity: no PERK_CLI_VERSION emits no drift warning", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.ok(
      !h.notifies.some((m) => /version parity/.test(m)),
      `expected no version-parity warning, got ${JSON.stringify(h.notifies)}`,
    );
  } finally {
    h.dispose();
  }
});
