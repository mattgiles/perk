// Every census specifier statically, plus the lazy paths the real package takes: lazy census
// imports, a lazy relative module that itself imports a census specifier, an `import.meta.resolve`
// probe and the exact-entry import pi-subagents' child-session loader performs.
import * as piAgentCore from "@earendil-works/pi-agent-core";
import * as piAi from "@earendil-works/pi-ai";
import * as piAiCompat from "@earendil-works/pi-ai/compat";
import * as piCodingAgent from "@earendil-works/pi-coding-agent";
import * as piTui from "@earendil-works/pi-tui";
import { realpathSync } from "node:fs";
import { pathToFileURL } from "node:url";
import * as typebox from "typebox";
import * as typeboxCompile from "typebox/compile";
import { nestedOrigin } from "../nested/index.js";

export const statics = {
  "@earendil-works/pi-coding-agent": piCodingAgent,
  "@earendil-works/pi-tui": piTui,
  "@earendil-works/pi-ai": piAi,
  "@earendil-works/pi-ai/compat": piAiCompat,
  "@earendil-works/pi-agent-core": piAgentCore,
  typebox,
  "typebox/compile": typeboxCompile,
};
export { nestedOrigin };
export const resolvedHost = import.meta.resolve("@earendil-works/pi-coding-agent");
export const lazyCompile = () => import("typebox/compile");
export const lazyCompat = () => import("@earendil-works/pi-ai/compat");
export const lazyRelative = () => import("./lazy.js");
export const lazyLate = () => import("./late.js");
export const exactEntry = (entryPath) => import(pathToFileURL(realpathSync(entryPath)).href);
