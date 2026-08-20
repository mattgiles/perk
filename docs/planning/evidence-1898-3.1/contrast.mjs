#!/usr/bin/env node

import assert from "node:assert/strict";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const outputDir = path.join(root, "docs/planning/evidence-1898-3.1");
const blueprintPath = path.join(root, "docs/design/docs-site-visual-blueprint.md");
const tokensPath = path.join(root, "docs/site/src/styles/tokens.css");
const systemPath = path.join(root, "docs/site/src/styles/system.css");
const distPath = path.join(root, "docs/site/dist");
const blueprint = readFileSync(blueprintPath, "utf8");

const coreTokens = {
  text: "--perk-text",
  muted: "--perk-muted",
  accent: "--perk-accent",
  "accent-strong": "--perk-accent-strong",
  "accent-invert": "--sl-color-text-invert",
  success: "--perk-success",
  "success-low": "--perk-success-low",
  warning: "--perk-warning",
  "warning-low": "--perk-warning-low",
  danger: "--perk-danger",
  "danger-low": "--perk-danger-low",
  canvas: "--perk-canvas",
  surface: "--perk-surface",
};
const washTokens = {
  ...coreTokens,
  "text-invert": "--sl-color-text-invert",
  "accent-low": "--sl-color-accent-low",
  "accent-high": "--sl-color-accent-high",
};

function section(text, start, end = null) {
  const startIndex = text.indexOf(start);
  assert.notEqual(startIndex, -1, `section start not found: ${start}`);
  if (end === null) return text.slice(startIndex);
  const endIndex = text.indexOf(end, startIndex);
  assert.notEqual(endIndex, -1, `section end not found: ${end}`);
  return text.slice(startIndex, endIndex);
}

function declarations(body) {
  const result = new Map();
  for (const match of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    result.set(match[1], match[2].trim().toLowerCase());
  }
  return result;
}

function themeScopes(cssText) {
  const stripped = cssText.replaceAll(/\/\*[\s\S]*?\*\//g, "");
  const darkMatch = stripped.match(/:root\s*\{([^{}]*)\}/);
  const lightMatch = stripped.match(/:root\[data-theme=["']light["']\]\s*\{([^{}]*)\}/);
  assert.ok(darkMatch, "dark :root scope missing");
  assert.ok(lightMatch, "light :root scope missing");
  return {
    dark: declarations(darkMatch[1]),
    light: declarations(lightMatch[1]),
  };
}

function resolve(scopes, theme, property) {
  let current = property;
  for (let depth = 0; depth < 5; depth += 1) {
    const value = scopes[theme].get(current) ?? scopes.dark.get(current);
    assert.ok(value, `${theme}: ${current} is not declared`);
    const variable = value.match(/^var\((--[\w-]+)\)$/);
    if (variable === null) {
      assert.match(value, /^#[0-9a-f]{6}$/, `${theme}: ${current} did not resolve to a hex color`);
      return value;
    }
    current = variable[1];
  }
  throw new Error(`${theme}: variable indirection is too deep for ${property}`);
}

function luminance(color) {
  const channels = [1, 3, 5].map((offset) => Number.parseInt(color.slice(offset, offset + 2), 16) / 255);
  const linear = channels.map((channel) =>
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(foreground, background) {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

function formatTable(headers, rows) {
  const widths = headers.map((header, index) =>
    Math.max(header.length, ...rows.map((row) => String(row[index]).length)),
  );
  const line = (row) =>
    row
      .map((cell, index) => String(cell).padEnd(widths[index]))
      .join("  ")
      .trimEnd();
  return [line(headers), widths.map((width) => "-".repeat(width)).join("  "), ...rows.map(line)].join("\n");
}

function corePairs() {
  const text = section(
    blueprint,
    "### Programmatic WCAG 2.2 AA contrast check",
    "Exit status:",
  );
  const rows = [];
  for (const line of text.split("\n")) {
    const match = line.match(
      /^(light|dark)\s+([\w-]+)\/([\w-]+)\s+(#[0-9a-f]{6})\s+(#[0-9a-f]{6})\s+([\d.]+)/i,
    );
    if (match === null) continue;
    rows.push({
      theme: match[1],
      foregroundName: match[2],
      backgroundName: match[3],
      recordedForeground: match[4].toLowerCase(),
      recordedBackground: match[5].toLowerCase(),
      recordedRatio: match[6],
    });
  }
  assert.equal(rows.length, 28, `expected 28 core pairs, found ${rows.length}`);
  return rows;
}

function washPairs() {
  const text = section(blueprint, "### Hero-wash contrast evidence");
  const rows = [];
  for (const line of text.split("\n")) {
    const match = line.match(
      /^\| (light|dark) \| ([\w-]+)\/([\w-]+) \| `(#[0-9a-f]{6})` \| `(#[0-9a-f]{6})` \| ([\d.]+) \|$/,
    );
    if (match === null) continue;
    rows.push({
      theme: match[1],
      foregroundName: match[2],
      backgroundName: match[3],
      recordedForeground: match[4],
      recordedBackground: match[5],
      recordedRatio: match[6],
    });
  }
  assert.equal(rows.length, 8, `expected 8 hero-wash pairs, found ${rows.length}`);
  return rows;
}

function recordedPalette() {
  const text = section(
    blueprint,
    "### Code-palette contrast evidence",
    "## §12 Home and landing finish",
  );
  const rows = [];
  for (const line of text.split("\n")) {
    const match = line.match(
      /^\| (light|dark) \| `(#[0-9a-f]{6})` \| `(#[0-9a-f]{6})` \| ([\d.]+) \|$/,
    );
    if (match === null) continue;
    rows.push({ theme: match[1], foreground: match[2], background: match[3], ratio: match[4] });
  }
  assert.equal(rows.length, 21, `expected 21 recorded palette rows, found ${rows.length}`);
  const counts = text.match(/\(([\d,]+) occurrences; (\d+) dark \/ (\d+) light colors\)/);
  assert.ok(counts, "recorded palette occurrence/color counts missing");
  return {
    rows,
    occurrences: Number(counts[1].replaceAll(",", "")),
    darkCount: Number(counts[2]),
    lightCount: Number(counts[3]),
  };
}

function htmlFiles(directory) {
  const result = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) result.push(...htmlFiles(candidate));
    else if (entry.name === "index.html") result.push(candidate);
  }
  return result;
}

function emittedPalette() {
  const pairs = [];
  const pattern = /style="--0:(#[0-9a-f]{6});--1:(#[0-9a-f]{6})"/gi;
  for (const file of htmlFiles(distPath)) {
    const html = readFileSync(file, "utf8");
    for (const match of html.matchAll(pattern)) {
      pairs.push([match[1].toLowerCase(), match[2].toLowerCase()]);
    }
  }
  assert.ok(pairs.length > 0, "fresh dist contained no emitted --0/--1 span pairs");
  return {
    occurrences: pairs.length,
    dark: [...new Set(pairs.map(([dark]) => dark))].sort(),
    light: [...new Set(pairs.map(([, light]) => light))].sort(),
  };
}

function setDelta(left, right) {
  const rightSet = new Set(right);
  return left.filter((value) => !rightSet.has(value));
}

const tokenScopes = themeScopes(readFileSync(tokensPath, "utf8"));
const systemScopes = themeScopes(readFileSync(systemPath, "utf8"));
const failures = [];

const coreRows = corePairs().map((row) => {
  const foreground = resolve(tokenScopes, row.theme, coreTokens[row.foregroundName]);
  const background = resolve(tokenScopes, row.theme, coreTokens[row.backgroundName]);
  const ratio = contrast(foreground, background);
  if (
    foreground !== row.recordedForeground ||
    background !== row.recordedBackground ||
    ratio.toFixed(2) !== row.recordedRatio ||
    ratio < 4.5
  ) {
    failures.push(`core ${row.theme} ${row.foregroundName}/${row.backgroundName}`);
  }
  return [
    row.theme,
    `${row.foregroundName}/${row.backgroundName}`,
    foreground,
    background,
    ratio.toFixed(2),
    ratio >= 4.5 ? "PASS" : "FAIL",
  ];
});
for (const theme of ["light", "dark"]) {
  const foreground = resolve(tokenScopes, theme, "--perk-text");
  const background = resolve(systemScopes, theme, "--sl-color-bg-inline-code");
  const ratio = contrast(foreground, background);
  if (ratio < 4.5) failures.push(`inline code ${theme}`);
  coreRows.push([
    theme,
    "text/inline-code",
    foreground,
    background,
    ratio.toFixed(2),
    ratio >= 4.5 ? "PASS" : "FAIL",
  ]);
}
const coreOutput = `${formatTable(
  ["theme", "pair", "fg", "bg", "ratio", "AA"],
  coreRows,
)}\n\nVerdict: ${failures.length === 0 ? "PASS" : "FAIL"} (${coreRows.length}/30 pairs at or above 4.5:1; the 28 recorded rows also agree to 2 decimals)\n`;
writeFileSync(path.join(outputDir, "contrast-core.txt"), coreOutput);

const failuresBeforeWash = failures.length;
const washRows = washPairs().map((row) => {
  const foreground = resolve(tokenScopes, row.theme, washTokens[row.foregroundName]);
  const background = resolve(tokenScopes, row.theme, washTokens[row.backgroundName]);
  const ratio = contrast(foreground, background);
  if (
    foreground !== row.recordedForeground ||
    background !== row.recordedBackground ||
    ratio.toFixed(2) !== row.recordedRatio ||
    ratio < 4.5
  ) {
    failures.push(`hero wash ${row.theme} ${row.foregroundName}/${row.backgroundName}`);
  }
  return [
    row.theme,
    `${row.foregroundName}/${row.backgroundName}`,
    foreground,
    background,
    ratio.toFixed(2),
    ratio >= 4.5 ? "PASS" : "FAIL",
  ];
});
const washOutput = `${formatTable(
  ["theme", "pair", "fg", "bg", "ratio", "AA"],
  washRows,
)}\n\nVerdict: ${failures.length === failuresBeforeWash ? "PASS" : "FAIL"} (8/8 live pairs agree with §12 to 2 decimals)\n`;
writeFileSync(path.join(outputDir, "contrast-hero-wash.txt"), washOutput);

const recorded = recordedPalette();
const emitted = emittedPalette();
const recordedSets = {
  dark: recorded.rows.filter((row) => row.theme === "dark").map((row) => row.foreground).sort(),
  light: recorded.rows.filter((row) => row.theme === "light").map((row) => row.foreground).sort(),
};
const membership = {
  darkAdded: setDelta(emitted.dark, recordedSets.dark),
  darkRemoved: setDelta(recordedSets.dark, emitted.dark),
  lightAdded: setDelta(emitted.light, recordedSets.light),
  lightRemoved: setDelta(recordedSets.light, emitted.light),
};
const membershipPass = Object.values(membership).every((values) => values.length === 0);
if (!membershipPass) failures.push("emitted palette membership");
const paletteRows = [];
for (const theme of ["dark", "light"]) {
  const background = resolve(tokenScopes, theme, "--perk-surface");
  for (const foreground of emitted[theme]) {
    const ratio = contrast(foreground, background);
    const recordedRow = recorded.rows.find(
      (row) => row.theme === theme && row.foreground === foreground,
    );
    const recordedAgreement = recordedRow?.background === background && recordedRow.ratio === ratio.toFixed(2);
    if (ratio < 4.5 || !recordedAgreement) failures.push(`palette ${theme} ${foreground}`);
    paletteRows.push([
      theme,
      foreground,
      background,
      ratio.toFixed(2),
      ratio >= 4.5 ? "PASS" : "FAIL",
      recordedAgreement ? "MATCH" : "DELTA",
    ]);
  }
}
const paletteLines = [
  formatTable(["theme", "foreground", "background", "ratio", "AA", "§11"], paletteRows),
  "",
  "Membership reconciliation (fresh docs/site/dist/**/index.html)",
  `occurrences: recorded dated run=${recorded.occurrences}; fresh=${emitted.occurrences}; delta=${emitted.occurrences - recorded.occurrences}`,
  `dark colors: recorded=${recordedSets.dark.length}; fresh=${emitted.dark.length}; added=${membership.darkAdded.join(",") || "∅"}; removed=${membership.darkRemoved.join(",") || "∅"}`,
  `light colors: recorded=${recordedSets.light.length}; fresh=${emitted.light.length}; added=${membership.lightAdded.join(",") || "∅"}; removed=${membership.lightRemoved.join(",") || "∅"}`,
  `membership verdict: ${membershipPass ? "PASS" : "FAIL"}`,
  `contrast/table verdict: ${paletteRows.every((row) => row[4] === "PASS" && row[5] === "MATCH") ? "PASS" : "FAIL"}`,
  "",
];
const paletteOutput = paletteLines.join("\n");
writeFileSync(path.join(outputDir, "contrast-code-palette.txt"), paletteOutput);

const summary = {
  generatedAt: new Date().toISOString(),
  method: "WCAG sRGB relative-luminance linearization; 4.5:1 normal-text threshold",
  core: { pairs: coreRows.length, verdict: coreRows.every((row) => row[5] === "PASS") ? "PASS" : "FAIL" },
  heroWash: { pairs: washRows.length, verdict: washRows.every((row) => row[5] === "PASS") ? "PASS" : "FAIL" },
  palette: {
    occurrences: { recorded: recorded.occurrences, fresh: emitted.occurrences },
    recorded: recordedSets,
    emitted: { dark: emitted.dark, light: emitted.light },
    membership,
    membershipVerdict: membershipPass ? "PASS" : "FAIL",
    contrastVerdict: paletteRows.every((row) => row[4] === "PASS") ? "PASS" : "FAIL",
  },
  failures,
  verdict: failures.length === 0 ? "PASS" : "FAIL",
};
writeFileSync(path.join(outputDir, "contrast-summary.json"), `${JSON.stringify(summary, null, 2)}\n`);

process.stdout.write(coreOutput);
process.stdout.write("\n");
process.stdout.write(washOutput);
process.stdout.write("\n");
process.stdout.write(paletteOutput);
if (failures.length > 0) {
  throw new Error(`Contrast evidence failed: ${failures.join(", ")}`);
}
