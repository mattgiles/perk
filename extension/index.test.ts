// Extension-factory wiring tests. The live harness binds extension/index.ts through Pi's real
// loader and runner, so these assertions cover registration rather than only renderer helpers —
// and the activation wiring: footer install/vacate, version parity, the host-SDK bridge arms.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { BridgeStatus } from "./substrate/nativeSdkBridge.ts";
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

// ---------------------------------------------------------------------------
// The host-SDK bridge reporting arms (contracts.md §8.73): failed/declined installs warn ONCE per
// activation; installed/disabled/skipped/unsupported are standing state — selfcheck-only (D7).
// ---------------------------------------------------------------------------

const BRIDGE_BASE: BridgeStatus = {
  state: "installed",
  hostEntry: "/pi/dist/index.js",
  roots: ["/repo/pi-subagents"],
  specifiers: 7,
  reused: false,
  detail: "",
};

test("sdk bridge: the default (harness) activation is the inert embedded-host state — selfcheck-only, no warning", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({ cwd, env: { PERK_RUN_ID: "01RID" } });
  try {
    assert.ok(
      !h.notifies.some((m) => /sdk bridge/.test(m)),
      `expected no sdk-bridge warning, got ${JSON.stringify(h.notifies)}`,
    );
    await h.invokeCommand("perk-selfcheck");
    const msg = h.notifies.at(-1) ?? "";
    assert.match(msg, /^perk: selfcheck — /);
    assert.match(msg, /bridge=unsupported:embedded-host/);
    const entries = h.session.sessionManager.getEntries() as unknown as {
      customType?: string;
      data?: { text?: string };
    }[];
    const detail = entries.find((entry) => entry.customType === REPORT_DETAIL_TYPE);
    assert.match(detail?.data?.text ?? "", /\n {2}native sdk bridge: unsupported:embedded-host\n/);
  } finally {
    h.dispose();
  }
});

test("sdk bridge: a failed install warns exactly once per activation, even across two session_starts", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    nativeSdkBridge: () => ({
      ...BRIDGE_BASE,
      state: "failed:register-hooks",
      roots: [],
      specifiers: 0,
      detail: "test-injected",
    }),
  });
  try {
    await h.emitSessionStart();
    const warnings = h.notifyEvents.filter((e) => /^perk: sdk bridge — /.test(e.message));
    assert.equal(warnings.length, 1, JSON.stringify(h.notifies));
    assert.equal(warnings[0]?.severity, "warning");
    assert.match(
      warnings[0]?.message ?? "",
      /^perk: sdk bridge — failed:register-hooks — test-injected — the native SDK consumers load their own SDK copies this session; \/perk-selfcheck shows the state$/,
    );
    await h.invokeCommand("perk-selfcheck");
    assert.match(h.notifies.at(-1) ?? "", /bridge=failed:register-hooks/);
  } finally {
    h.dispose();
  }
});

test("sdk bridge: a declined install says the earlier bridge stays active", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    nativeSdkBridge: () => ({
      ...BRIDGE_BASE,
      state: "declined:host-mismatch",
      roots: [],
      specifiers: 0,
      detail: "active bridge host: /other/dist/index.js",
    }),
  });
  try {
    const warnings = h.notifies.filter((m) => /^perk: sdk bridge — /.test(m));
    assert.equal(warnings.length, 1, JSON.stringify(h.notifies));
    assert.match(
      warnings[0] ?? "",
      /declined:host-mismatch — active bridge host: \/other\/dist\/index\.js — an earlier host-SDK bridge in this process stays active for its own roots; this perk copy installed none; \/perk-selfcheck shows the state$/,
    );
  } finally {
    h.dispose();
  }
});

test("sdk bridge: an installed bridge emits no warning and reports through selfcheck", async () => {
  const cwd = scaffoldRepo({ handoff: { runId: "01RID", mode: "read-only" } });
  const h = await loadPerkSession({
    cwd,
    env: { PERK_RUN_ID: "01RID" },
    nativeSdkBridge: () => ({ ...BRIDGE_BASE, reused: true }),
  });
  try {
    await h.emitSessionStart();
    assert.ok(
      !h.notifies.some((m) => /sdk bridge/.test(m)),
      `expected no sdk-bridge warning, got ${JSON.stringify(h.notifies)}`,
    );
    await h.invokeCommand("perk-selfcheck");
    assert.match(h.notifies.at(-1) ?? "", /bridge=installed/);
    const entries = h.session.sessionManager.getEntries() as unknown as {
      customType?: string;
      data?: { text?: string };
    }[];
    const detail = entries.find((entry) => entry.customType === REPORT_DETAIL_TYPE);
    assert.match(
      detail?.data?.text ?? "",
      /\n {2}native sdk bridge: installed \(roots=1, specifiers=7, reused\)\n {4}host: \/pi\/dist\/index\.js\n {4}roots: 1 — \/repo\/pi-subagents/,
    );
  } finally {
    h.dispose();
  }
});
