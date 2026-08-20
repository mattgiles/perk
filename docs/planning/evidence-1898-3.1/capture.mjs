#!/usr/bin/env node

import { spawn } from "node:child_process";
import {
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { platform } from "node:os";
import path from "node:path";
import process from "node:process";
import { setTimeout as sleep } from "node:timers/promises";

const outputDir = path.resolve("docs/planning/evidence-1898-3.1");
const baseUrl = new URL(process.argv[2] ?? "http://localhost:4323/");
const chromeProfile = path.join(outputDir, ".capture-tmp");
const chromeLogPath = path.join(chromeProfile, "chrome.log");
const themes = ["light", "dark"];
const viewports = [
  { label: "320", width: 320 },
  { label: "768", width: 768 },
  { label: "1280", width: 1280 },
  { label: "1600", width: 1600 },
  { label: "640-zoom200", width: 640 },
];
const pages = [
  ["home", "/"],
  ["tutorials", "/tutorials/"],
  ["how-to", "/how-to/"],
  ["reference", "/reference/"],
  ["explanation", "/explanation/"],
  ["reference-configuration", "/reference/configuration/"],
  [
    "reference-configuration-workflow-and-ci",
    "/reference/configuration/workflow-and-ci/",
  ],
  ["tutorials-get-started", "/tutorials/get-started/"],
];

class CdpConnection {
  constructor(url) {
    this.url = url;
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
  }

  async open() {
    this.socket = new WebSocket(this.url);
    await new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", reject, { once: true });
    });
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      if (message.id !== undefined) {
        const pending = this.pending.get(message.id);
        if (pending === undefined) return;
        this.pending.delete(message.id);
        if (message.error !== undefined) {
          pending.reject(new Error(`${pending.method}: ${message.error.message}`));
        } else {
          pending.resolve(message.result ?? {});
        }
        return;
      }
      for (const listener of this.listeners.get(message.method) ?? []) {
        listener(message.params ?? {});
      }
    });
  }

  send(method, params = {}) {
    const id = this.nextId;
    this.nextId += 1;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { method, resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  once(method, timeoutMs = 30_000) {
    return new Promise((resolve, reject) => {
      let timer;
      const listener = (params) => {
        clearTimeout(timer);
        const listeners = this.listeners.get(method) ?? [];
        this.listeners.set(
          method,
          listeners.filter((candidate) => candidate !== listener),
        );
        resolve(params);
      };
      const listeners = this.listeners.get(method) ?? [];
      listeners.push(listener);
      this.listeners.set(method, listeners);
      timer = setTimeout(() => {
        this.listeners.set(
          method,
          (this.listeners.get(method) ?? []).filter((candidate) => candidate !== listener),
        );
        reject(new Error(`Timed out waiting for ${method}`));
      }, timeoutMs);
    });
  }

  close() {
    this.socket?.close();
  }
}

function chromeExecutable() {
  const candidates = [
    process.env.CHROME_BIN,
    platform() === "darwin"
      ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
      : undefined,
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ].filter(Boolean);
  const executable = candidates.find((candidate) => existsSync(candidate));
  if (executable === undefined) {
    throw new Error("Set CHROME_BIN to a Chrome/Chromium executable");
  }
  return executable;
}

async function waitForFile(file, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (existsSync(file)) return;
    await sleep(50);
  }
  throw new Error(`Timed out waiting for ${file}`);
}

async function startChrome() {
  rmSync(chromeProfile, { force: true, recursive: true });
  mkdirSync(chromeProfile, { recursive: true });
  const log = openSync(chromeLogPath, "a");
  const child = spawn(
    chromeExecutable(),
    [
      "--headless=new",
      "--disable-background-networking",
      "--disable-component-update",
      "--disable-default-apps",
      "--disable-extensions",
      "--disable-features=Translate",
      "--disable-sync",
      "--hide-scrollbars",
      "--metrics-recording-only",
      "--no-first-run",
      "--remote-allow-origins=*",
      "--remote-debugging-port=0",
      `--user-data-dir=${chromeProfile}`,
      "--window-size=1600,1000",
      "about:blank",
    ],
    { stdio: ["ignore", log, log] },
  );
  const portFile = path.join(chromeProfile, "DevToolsActivePort");
  await waitForFile(portFile);
  const [port] = readFileSync(portFile, "utf8").trim().split("\n");
  const targetResponse = await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, {
    method: "PUT",
  });
  if (!targetResponse.ok) {
    throw new Error(`Could not create Chrome target: ${targetResponse.status}`);
  }
  const target = await targetResponse.json();
  return {
    child,
    connection: new CdpConnection(target.webSocketDebuggerUrl),
    stop: async () => {
      child.kill("SIGTERM");
      await Promise.race([
        new Promise((resolve) => child.once("exit", resolve)),
        sleep(2_000),
      ]);
      closeSync(log);
      rmSync(chromeProfile, { force: true, recursive: true });
    },
  };
}

function evaluate(connection, expression, { awaitPromise = false } = {}) {
  return connection
    .send("Runtime.evaluate", {
      expression,
      awaitPromise,
      returnByValue: true,
    })
    .then(({ result, exceptionDetails }) => {
      if (exceptionDetails !== undefined) {
        throw new Error(exceptionDetails.text ?? "Runtime.evaluate failed");
      }
      return result.value;
    });
}

async function setViewport(connection, width, height = 900) {
  await connection.send("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: false,
    screenWidth: width,
    screenHeight: height,
  });
}

async function navigate(connection, route, { scripts = true } = {}) {
  await connection.send("Emulation.setScriptExecutionDisabled", { value: !scripts });
  const loaded = connection.once("Page.loadEventFired");
  await connection.send("Page.navigate", { url: new URL(route, baseUrl).href });
  await loaded;
  if (scripts) {
    await evaluate(
      connection,
      `Promise.all([document.fonts.ready, new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))])`,
      { awaitPromise: true },
    );
  } else {
    await sleep(500);
  }
}

async function forceTheme(connection, theme, { scripts = true } = {}) {
  if (scripts) {
    await evaluate(
      connection,
      `localStorage.setItem("starlight-theme", ${JSON.stringify(theme)}); document.documentElement.setAttribute("data-theme", ${JSON.stringify(theme)});`,
    );
    await sleep(50);
    return;
  }
  const { root } = await connection.send("DOM.getDocument", { depth: 1 });
  const { nodeId } = await connection.send("DOM.querySelector", {
    nodeId: root.nodeId,
    selector: "html",
  });
  await connection.send("DOM.setAttributeValue", {
    nodeId,
    name: "data-theme",
    value: theme,
  });
  await sleep(50);
}

async function boxForSelector(connection, selector) {
  const { root } = await connection.send("DOM.getDocument", { depth: -1, pierce: true });
  const { nodeId } = await connection.send("DOM.querySelector", {
    nodeId: root.nodeId,
    selector,
  });
  if (nodeId === 0) throw new Error(`Selector not found: ${selector}`);
  const { model } = await connection.send("DOM.getBoxModel", { nodeId });
  const points = model.border;
  const xs = points.filter((_, index) => index % 2 === 0);
  const ys = points.filter((_, index) => index % 2 === 1);
  const x = Math.min(...xs);
  const y = Math.min(...ys);
  return {
    x,
    y,
    width: Math.max(...xs) - x,
    height: Math.max(...ys) - y,
  };
}

async function writeScreenshot(
  connection,
  filename,
  selector = null,
  { padding = 0, includeVisibleTooltip = false } = {},
) {
  let clip;
  if (selector === null) {
    const { contentSize } = await connection.send("Page.getLayoutMetrics");
    clip = {
      x: 0,
      y: 0,
      width: Math.ceil(contentSize.width),
      height: Math.ceil(contentSize.height),
      scale: 1,
    };
  } else {
    const boxes = [await boxForSelector(connection, selector)];
    if (includeVisibleTooltip) {
      boxes.push(await boxForSelector(connection, "[data-core-flow-tooltip]:not([hidden])"));
    }
    const x = Math.min(...boxes.map((box) => box.x));
    const y = Math.min(...boxes.map((box) => box.y));
    const right = Math.max(...boxes.map((box) => box.x + box.width));
    const bottom = Math.max(...boxes.map((box) => box.y + box.height));
    clip = {
      x: Math.max(0, Math.floor(x - padding)),
      y: Math.max(0, Math.floor(y - padding)),
      width: Math.ceil(right - x + padding * 2),
      height: Math.ceil(bottom - y + padding * 2),
      scale: 1,
    };
  }
  const { data } = await connection.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: true,
    clip,
  });
  writeFileSync(path.join(outputDir, filename), Buffer.from(data, "base64"));
}

async function basePageEvidence(connection, route, theme, width) {
  return evaluate(
    connection,
    `(() => {
      const root = document.documentElement;
      const body = document.body;
      const maxWidth = Math.max(root.scrollWidth, body?.scrollWidth ?? 0);
      const expected = ${JSON.stringify(route)};
      const actual = location.pathname;
      const details = [...document.querySelectorAll("[data-core-flow-disclosure]")];
      return {
        expected,
        actual,
        theme: root.getAttribute("data-theme"),
        overflowPx: Math.max(0, maxWidth - root.clientWidth),
        brokenImages: [...document.images].filter((image) => !image.complete || image.naturalWidth === 0).length,
        fonts: document.fonts.status,
        details: details.map((detail) => detail.open),
        h1: document.querySelector("h1")?.textContent.trim() ?? "",
      };
    })()`,
  ).then((evidence) => ({
    ...evidence,
    verdict:
      evidence.actual === route &&
      evidence.theme === theme &&
      evidence.overflowPx <= 1 &&
      evidence.brokenImages === 0 &&
      evidence.fonts === "loaded" &&
      (route !== "/" || evidence.details.every((open) => !open))
        ? "PASS"
        : "FAIL",
    width,
  }));
}

function keyboardPayload(key, { shift = false } = {}) {
  const definitions = {
    Tab: { code: "Tab", keyCode: 9 },
    Enter: { code: "Enter", keyCode: 13 },
    Space: { code: "Space", keyCode: 32, key: " " },
    Escape: { code: "Escape", keyCode: 27 },
  };
  const definition = definitions[key];
  return {
    key: definition.key ?? key,
    code: definition.code,
    windowsVirtualKeyCode: definition.keyCode,
    nativeVirtualKeyCode: definition.keyCode,
    modifiers: shift ? 8 : 0,
  };
}

async function press(connection, key, options = {}) {
  const payload = keyboardPayload(key, options);
  const text = key === "Enter" ? "\r" : key === "Space" ? " " : undefined;
  await connection.send("Input.dispatchKeyEvent", { type: "keyDown", ...payload, text });
  await connection.send("Input.dispatchKeyEvent", { type: "keyUp", ...payload });
  await sleep(30);
}

function activeEvidence(connection) {
  return evaluate(
    connection,
    `(() => {
      const active = document.activeElement;
      const relevant = [...document.querySelectorAll(
        ".hero .sl-link-button, [data-core-flow] button[data-core-flow-tip], [data-core-flow] summary",
      )];
      const tooltipId = active?.getAttribute?.("aria-describedby");
      const tooltip = tooltipId ? document.getElementById(tooltipId) : null;
      const text = active?.textContent?.replace(/\\s+/g, " ").trim() ?? "";
      let kind = "other";
      if (active?.matches?.(".hero .sl-link-button")) kind = "hero-action";
      else if (active?.matches?.("button[data-core-flow-tip]")) kind = "tooltip-trigger";
      else if (active?.matches?.("summary")) kind = "summary";
      return {
        tag: active?.tagName?.toLowerCase() ?? "none",
        kind,
        text,
        href: active?.getAttribute?.("href") ?? null,
        relevantIndex: relevant.indexOf(active),
        inFigure: active?.closest?.("[data-core-flow]") !== null,
        tooltipVisible: tooltip !== null && !tooltip.hidden,
        tooltipId,
      };
    })()`,
  );
}

function disclosureStates(connection) {
  return evaluate(
    connection,
    `[...document.querySelectorAll("[data-core-flow-disclosure]")].map((detail) => detail.open)`,
  );
}

async function runKeyboardPass(connection) {
  await connection.send("Emulation.setEmulatedMedia", { media: "screen", features: [] });
  await setViewport(connection, 1280);
  await navigate(connection, "/");
  await forceTheme(connection, "light");
  const lines = [
    "Keyboard-only hardening pass",
    `URL: ${new URL("/", baseUrl).href}`,
    "Driver: CDP Input.dispatchKeyEvent only (Tab, Shift-Tab, Enter, Space, Escape)",
    "",
  ];
  const seen = new Set();
  const encountered = [];
  let heroActions = 0;
  let tooltipTriggers = 0;
  let summaries = 0;
  let planEscapeVerified = false;

  for (let step = 1; step <= 100; step += 1) {
    await press(connection, "Tab");
    const active = await activeEvidence(connection);
    if (active.relevantIndex < 0 || seen.has(active.relevantIndex)) continue;
    seen.add(active.relevantIndex);
    encountered.push(active.relevantIndex);
    lines.push(
      `Tab ${step}: ${active.kind} — ${active.text}${active.tooltipId ? ` — tooltip ${active.tooltipVisible ? "visible" : "HIDDEN"}` : ""}`,
    );

    if (active.kind === "hero-action") {
      heroActions += 1;
    } else if (active.kind === "tooltip-trigger") {
      tooltipTriggers += 1;
      if (!active.tooltipVisible) throw new Error(`Focused tooltip was hidden: ${active.text}`);
      if (!planEscapeVerified && active.tooltipId === "perk-core-flow-tip-plan") {
        await press(connection, "Escape");
        const escaped = await activeEvidence(connection);
        if (escaped.tooltipVisible || escaped.tooltipId !== active.tooltipId) {
          throw new Error("Escape did not dismiss and latch the focused plan tooltip");
        }
        lines.push("Escape: plan tooltip dismissed; focus remained on the plan trigger; latch held");
        await press(connection, "Tab", { shift: true });
        const dropped = await activeEvidence(connection);
        await press(connection, "Tab");
        const reestablished = await activeEvidence(connection);
        if (reestablished.tooltipId !== active.tooltipId || !reestablished.tooltipVisible) {
          throw new Error("Plan tooltip did not reappear after focus intent dropped and re-established");
        }
        lines.push(
          `Shift-Tab → ${dropped.text}; Tab → plan: focus intent dropped/re-established and tooltip reappeared`,
        );
        planEscapeVerified = true;
      }
    } else if (active.kind === "summary") {
      const index = summaries;
      summaries += 1;
      const toggleKey = index === 1 ? "Space" : "Enter";
      const before = await disclosureStates(connection);
      await press(connection, toggleKey);
      const opened = await disclosureStates(connection);
      if (!opened[index] || opened.some((state, candidate) => candidate !== index && state !== before[candidate])) {
        throw new Error(
          `${toggleKey} did not independently open summary ${index + 1}: before=${before.join(",")}; after=${opened.join(",")}`,
        );
      }
      await press(connection, toggleKey);
      const closed = await disclosureStates(connection);
      if (closed[index] || closed.some((state, candidate) => candidate !== index && state !== before[candidate])) {
        throw new Error(`${toggleKey} did not independently close summary ${index + 1}`);
      }
      lines.push(
        `${toggleKey}: summary ${index + 1} opened and closed independently; peers stayed unchanged`,
      );
      if (index === 2) {
        await press(connection, "Space");
        const reopened = await disclosureStates(connection);
        if (!reopened[index]) throw new Error("Third disclosure did not reopen for cache-trigger traversal");
        lines.push("Space: summary 3 reopened so its two cache tooltip buttons entered the Tab order");
      }
    }

    if (heroActions === 2 && tooltipTriggers === 9 && summaries === 3) break;
  }

  if (heroActions !== 2 || tooltipTriggers !== 9 || summaries !== 3) {
    throw new Error(
      `Incomplete keyboard traversal: hero=${heroActions}, tooltip triggers=${tooltipTriggers}, summaries=${summaries}`,
    );
  }
  if (!encountered.every((value, index) => index === 0 || value > encountered[index - 1])) {
    throw new Error(`Relevant controls were not reached in source order: ${encountered.join(",")}`);
  }

  let reverseSteps = 0;
  while ((await activeEvidence(connection)).inFigure && reverseSteps < 30) {
    await press(connection, "Tab", { shift: true });
    reverseSteps += 1;
  }
  const exited = await activeEvidence(connection);
  if (exited.inFigure) throw new Error("Shift-Tab did not leave the figure");
  lines.push(
    "",
    `Counts: 2 hero actions; 9 tooltip buttons; 3 summaries; relevant controls reached in source order (${encountered.join(" → ")}).`,
    `Shift-Tab reverse walk: left the figure after ${reverseSteps} stops at “${exited.text}”; no focus trap.`,
    "Verdict: PASS",
  );
  const transcript = `${lines.join("\n")}\n`;
  writeFileSync(path.join(outputDir, "keyboard-transcript.txt"), transcript);
  return { verdict: "PASS", transcript, heroActions, tooltipTriggers, summaries, reverseSteps };
}

async function focusFirstTooltipByKeyboard(connection) {
  for (let count = 0; count < 50; count += 1) {
    await press(connection, "Tab");
    const active = await activeEvidence(connection);
    if (active.tooltipId === "perk-core-flow-tip-plan") {
      if (!active.tooltipVisible) throw new Error("Plan tooltip did not open from keyboard focus");
      return;
    }
  }
  throw new Error("Could not reach the plan tooltip by Tab");
}

function durationMilliseconds(value) {
  return Math.max(
    ...value.split(",").map((part) => {
      const trimmed = part.trim();
      if (trimmed.endsWith("ms")) return Number.parseFloat(trimmed);
      if (trimmed.endsWith("s")) return Number.parseFloat(trimmed) * 1000;
      return Number.POSITIVE_INFINITY;
    }),
  );
}

async function probeReducedMotion(connection) {
  const probes = [];
  const routes = [
    ["/", ".perk-band .sl-link-card"],
    ["/", ".hero .sl-link-button"],
    ["/tutorials/", ".perk-recommended li"],
  ];
  for (const [route, selector] of routes) {
    await navigate(connection, route);
    await forceTheme(connection, "light");
    const values = await evaluate(
      connection,
      `[...document.querySelectorAll(${JSON.stringify(selector)})].map((node) => getComputedStyle(node).transitionDuration)`,
    );
    if (values.length === 0) throw new Error(`Reduced-motion selector matched no elements: ${selector}`);
    const maximumMs = Math.max(...values.map(durationMilliseconds));
    probes.push({ route, selector, count: values.length, values: [...new Set(values)], maximumMs });
  }
  const lines = [
    "Reduced-motion computed-style probe",
    "Emulation: prefers-reduced-motion: reduce",
    "Threshold: every transition-duration <= 0.1ms",
    "",
    ...probes.map(
      (probe) =>
        `${probe.route}  ${probe.selector}  count=${probe.count}  duration=${probe.values.join(",")}  max=${probe.maximumMs}ms  ${probe.maximumMs <= 0.1 ? "PASS" : "FAIL"}`,
    ),
  ];
  const verdict = probes.every((probe) => probe.maximumMs <= 0.1) ? "PASS" : "FAIL";
  lines.push("", `Verdict: ${verdict}`);
  writeFileSync(path.join(outputDir, "reduced-motion-probe.txt"), `${lines.join("\n")}\n`);
  if (verdict !== "PASS") throw new Error("Reduced-motion transition probe failed");
  return { verdict, probes };
}

function matrixMarkdown(rows) {
  const lines = [
    "| # | Shot | Route/state | Theme | Width | Result | Assertion |",
    "|---:|---|---|---|---:|---|---|",
  ];
  rows.forEach((row, index) => {
    lines.push(
      `| ${index + 1} | \`${row.shot}\` | ${row.route ?? row.state} | ${row.theme} | ${row.width} | **${row.verdict}** | ${row.assertion} |`,
    );
  });
  return `${lines.join("\n")}\n`;
}

async function main() {
  mkdirSync(outputDir, { recursive: true });
  const chrome = await startChrome();
  const connection = chrome.connection;
  const rows = [];
  let summary;
  try {
    await connection.open();
    await Promise.all([
      connection.send("Page.enable"),
      connection.send("Runtime.enable"),
      connection.send("DOM.enable"),
    ]);
    await connection.send("Emulation.setEmulatedMedia", { media: "screen", features: [] });

    for (const [slug, route] of pages) {
      for (const theme of themes) {
        for (const viewport of viewports) {
          await setViewport(connection, viewport.width);
          await navigate(connection, route);
          await forceTheme(connection, theme);
          const evidence = await basePageEvidence(connection, route, theme, viewport.label);
          const shot = `hardening--${slug}--${theme}--${viewport.label}.png`;
          await writeScreenshot(connection, shot);
          rows.push({
            shot,
            route,
            theme,
            width: viewport.label,
            verdict: evidence.verdict,
            assertion: `route/theme/fonts/images; overflow=${evidence.overflowPx}px${route === "/" ? "; disclosures collapsed" : ""}`,
          });
          if (evidence.verdict !== "PASS") {
            throw new Error(`${shot} failed: ${JSON.stringify(evidence)}`);
          }
        }
      }
    }

    for (const theme of themes) {
      for (const width of [320, 1280]) {
        await setViewport(connection, width);
        await navigate(connection, "/");
        await forceTheme(connection, theme);
        await evaluate(
          connection,
          `document.querySelectorAll("[data-core-flow-disclosure]").forEach((detail) => detail.open = true)`,
        );
        const expanded = await disclosureStates(connection);
        if (expanded.length !== 3 || !expanded.every(Boolean)) {
          throw new Error("Expanded-state assertion failed");
        }
        const shot = `hardening--band2-expanded--${theme}--${width}.png`;
        await writeScreenshot(connection, shot, ".perk-band", { padding: 12 });
        rows.push({
          shot,
          state: "band 2 — all three disclosures expanded",
          theme,
          width,
          verdict: "PASS",
          assertion: "3/3 native disclosures open",
        });
      }
    }

    for (const theme of themes) {
      await setViewport(connection, 1280);
      await navigate(connection, "/", { scripts: false });
      await forceTheme(connection, theme, { scripts: false });
      const { root } = await connection.send("DOM.getDocument", { depth: -1, pierce: true });
      const { nodeIds } = await connection.send("DOM.querySelectorAll", {
        nodeId: root.nodeId,
        selector: "[data-core-flow-disclosure]",
      });
      const openStates = [];
      for (const nodeId of nodeIds) {
        const { attributes } = await connection.send("DOM.getAttributes", { nodeId });
        openStates.push(attributes.some((value, index) => index % 2 === 0 && value === "open"));
      }
      if (openStates.length !== 3 || !openStates.every(Boolean)) {
        throw new Error(`No-JS disclosure assertion failed: ${openStates.join(",")}`);
      }
      const shot = `hardening--band2-nojs--${theme}--1280.png`;
      await writeScreenshot(connection, shot, ".perk-band", { padding: 12 });
      rows.push({
        shot,
        state: "band 2 — scripts disabled",
        theme,
        width: 1280,
        verdict: "PASS",
        assertion: "DOM assertion: 3/3 disclosures carry open",
      });
    }
    await connection.send("Emulation.setScriptExecutionDisabled", { value: false });

    await setViewport(connection, 1280);
    await connection.send("Emulation.setEmulatedMedia", { media: "print", features: [] });
    await navigate(connection, "/");
    await forceTheme(connection, "light");
    let printStates = await disclosureStates(connection);
    let printMethod = "media emulation event";
    if (!printStates.every(Boolean)) {
      await evaluate(connection, `window.dispatchEvent(new Event("beforeprint"))`);
      printMethod = "manual beforeprint dispatch after media emulation";
      printStates = await disclosureStates(connection);
    }
    if (printStates.length !== 3 || !printStates.every(Boolean)) {
      throw new Error(`Print disclosure assertion failed: ${printStates.join(",")}`);
    }
    const printShot = "hardening--band2-print--light--1280.png";
    await writeScreenshot(connection, printShot, ".perk-band", { padding: 12 });
    rows.push({
      shot: printShot,
      state: "band 2 — print media",
      theme: "light",
      width: 1280,
      verdict: "PASS",
      assertion: `3/3 disclosures open; ${printMethod}`,
    });
    await evaluate(connection, `window.dispatchEvent(new Event("afterprint"))`);
    await connection.send("Emulation.setEmulatedMedia", { media: "screen", features: [] });

    for (const theme of themes) {
      await setViewport(connection, 1280);
      await navigate(connection, "/");
      await forceTheme(connection, theme);
      await focusFirstTooltipByKeyboard(connection);
      const shot = `hardening--band2-tooltip-focus--${theme}--1280.png`;
      await writeScreenshot(connection, shot, ".perk-band", {
        padding: 12,
        includeVisibleTooltip: true,
      });
      rows.push({
        shot,
        state: "band 2 — keyboard-focused plan tooltip",
        theme,
        width: 1280,
        verdict: "PASS",
        assertion: "Tab focus; tooltip visible; focus ring captured",
      });
    }

    await connection.send("Emulation.setEmulatedMedia", {
      media: "screen",
      features: [{ name: "prefers-reduced-motion", value: "reduce" }],
    });
    for (const theme of themes) {
      await setViewport(connection, 1280);
      await navigate(connection, "/");
      await forceTheme(connection, theme);
      const shot = `hardening--band2-reduced-motion--${theme}--1280.png`;
      await writeScreenshot(connection, shot);
      rows.push({
        shot,
        state: "full home — reduced motion",
        theme,
        width: 1280,
        verdict: "PASS",
        assertion: "prefers-reduced-motion: reduce emulated",
      });
    }
    const reducedMotion = await probeReducedMotion(connection);
    const keyboard = await runKeyboardPass(connection);

    if (rows.length !== 91) throw new Error(`Expected 91 screenshots, captured ${rows.length}`);
    writeFileSync(path.join(outputDir, "rendered-matrix.md"), matrixMarkdown(rows));
    summary = {
      date: new Date().toISOString(),
      baseUrl: baseUrl.href,
      screenshots: rows.length,
      passes: rows.filter((row) => row.verdict === "PASS").length,
      failures: rows.filter((row) => row.verdict !== "PASS").length,
      printMethod,
      keyboard: {
        verdict: keyboard.verdict,
        heroActions: keyboard.heroActions,
        tooltipTriggers: keyboard.tooltipTriggers,
        summaries: keyboard.summaries,
        reverseSteps: keyboard.reverseSteps,
      },
      reducedMotion,
      rows,
    };
    writeFileSync(path.join(outputDir, "capture-summary.json"), `${JSON.stringify(summary, null, 2)}\n`);
  } finally {
    connection.close();
    await chrome.stop();
  }
  process.stdout.write(
    `Captured ${summary.screenshots} screenshots: ${summary.passes} PASS, ${summary.failures} FAIL\n`,
  );
}

await main();
