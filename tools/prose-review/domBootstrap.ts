// Installs a minimal DOM BEFORE react-dom evaluates (componentHarness.ts imports
// this module first), so react-dom's module-scope environment probes — notably
// isInputEventSupported, which otherwise falls back to an attachEvent-era change
// polyfill that cannot deliver onChange under jsdom — match a real browser.
// Each suite's installDom() still installs and tears down its own fresh JSDOM;
// this bootstrap window only ever backs those module-scope probes.

import { JSDOM } from "jsdom";

if (Object.getOwnPropertyDescriptor(globalThis, "window") === undefined) {
  const bootstrap = new JSDOM("<!doctype html><html><body></body></html>");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    writable: true,
    value: bootstrap.window,
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    writable: true,
    value: bootstrap.window.document,
  });
}
