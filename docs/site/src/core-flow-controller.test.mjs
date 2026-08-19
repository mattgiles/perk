import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { enhanceCoreFlow } from "./core-flow-controller.mjs";

// Unit tests for the core-flow interaction controller, in jsdom (the same
// `docs/site/src/**/*.test.mjs` glob as the other bridge-module tests — no build needed).
// The fixture is a minimal DOM carrying the same `data-core-flow-*` contract the post-build
// check (checks/built-site.test.mjs) pins on the real component's output: real <button>
// triggers with aria-describedby, colocated [role="tooltip"][hidden] siblings inside
// .tip-wrap, and three <details open data-core-flow-disclosure> regions.

const FIXTURE = `
<figure class="perk-diagram perk-core-flow" data-core-flow>
  <ol class="flow-spine">
    <li class="stage">
      <span class="tip-wrap"><button type="button" data-core-flow-tip
        aria-describedby="tip-a">a</button><span role="tooltip" id="tip-a" hidden
        data-core-flow-tooltip>Tooltip A</span></span>
    </li>
    <li class="stage">
      <span class="tip-wrap"><button type="button" data-core-flow-tip
        aria-describedby="tip-b">b</button><span role="tooltip" id="tip-b" hidden
        data-core-flow-tooltip>Tooltip B</span></span>
    </li>
  </ol>
  <details open data-core-flow-disclosure><summary>one</summary><p>body one</p></details>
  <details open data-core-flow-disclosure><summary>two</summary><p>body two</p></details>
  <details open data-core-flow-disclosure><summary>three</summary><p>body three</p></details>
</figure>
<button type="button" id="outside">outside</button>
`;

/** Build a fixture window; `hoverNone` selects the injected matchMedia stub's answer. */
function fixture({ hoverNone = false, enhance = true, options } = {}) {
  const dom = new JSDOM(`<!doctype html><html><body>${FIXTURE}</body></html>`);
  const { document: doc } = dom.window;
  const root = doc.querySelector("[data-core-flow]");
  const stub = (query) => ({ matches: query === "(hover: none)" && hoverNone });
  if (enhance) enhanceCoreFlow(root, options ?? { matchMedia: stub });
  const [a, b] = root.querySelectorAll("button[data-core-flow-tip]");
  return {
    dom,
    win: dom.window,
    doc,
    root,
    triggers: { a, b },
    tooltips: { a: doc.getElementById("tip-a"), b: doc.getElementById("tip-b") },
    disclosures: [...root.querySelectorAll("[data-core-flow-disclosure]")],
  };
}

const visible = (tooltip) => !tooltip.hasAttribute("hidden");
const fire = (win, target, type) => target.dispatchEvent(new win.Event(type));
const pressEscape = (win, doc) =>
  doc.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape" }));

test("unenhanced DOM: details open, all tooltips hidden", () => {
  const { dom, tooltips, disclosures } = fixture({ enhance: false });
  try {
    for (const disclosure of disclosures) assert.equal(disclosure.hasAttribute("open"), true);
    assert.equal(visible(tooltips.a), false);
    assert.equal(visible(tooltips.b), false);
  } finally {
    dom.window.close();
  }
});

test("enhance collapses all three disclosures; they toggle independently", () => {
  const { dom, disclosures } = fixture();
  try {
    for (const disclosure of disclosures) assert.equal(disclosure.hasAttribute("open"), false);
    disclosures[1].setAttribute("open", "");
    assert.equal(disclosures[0].hasAttribute("open"), false);
    assert.equal(disclosures[1].hasAttribute("open"), true);
    assert.equal(disclosures[2].hasAttribute("open"), false);
  } finally {
    dom.window.close();
  }
});

test("uninjected default path: the root window's own matchMedia is queried, bound to it", () => {
  const { dom, win, root, triggers, tooltips } = fixture({ enhance: false });
  try {
    // jsdom ships no matchMedia — install a spy implementation on THIS fixture's window so
    // the uninjected call must resolve (and bind) through ownerDocument.defaultView.
    const calls = [];
    win.matchMedia = function matchMedia(query) {
      calls.push({ query, receiver: this });
      return { matches: query === "(hover: none)" };
    };
    enhanceCoreFlow(root); // no options
    assert.deepEqual(
      calls.map(({ query }) => query),
      ["(hover: none)"],
    );
    assert.equal(calls[0].receiver, win, "matchMedia must be bound to the root window");
    // The spy answered hover-none, so the hover-incapable arm must be live: hover is not
    // intent; click pins.
    fire(win, triggers.a, "pointerenter");
    assert.equal(visible(tooltips.a), false);
    triggers.a.click();
    assert.equal(visible(tooltips.a), true);
  } finally {
    dom.window.close();
  }
});

test("absent matchMedia (the jsdom default): falls back to hover-capable and enhances", () => {
  const { dom, win, root, triggers, tooltips, disclosures } = fixture({
    enhance: false,
  });
  try {
    assert.equal(win.matchMedia, undefined); // the fixture's premise
    enhanceCoreFlow(root); // no options — the absent-capability fallback arm
    assert.equal(root.hasAttribute("data-enhanced"), true);
    for (const disclosure of disclosures) assert.equal(disclosure.hasAttribute("open"), false);
    fire(win, triggers.a, "pointerenter"); // fallback is hover-capable
    assert.equal(visible(tooltips.a), true);
  } finally {
    dom.window.close();
  }
});

test("a documentless root no-ops without throwing", () => {
  const { dom, doc } = fixture({ enhance: false });
  try {
    const windowless = doc.implementation.createHTMLDocument("no-window");
    windowless.body.innerHTML = FIXTURE;
    const root = windowless.querySelector("[data-core-flow]");
    assert.equal(windowless.defaultView, null);
    enhanceCoreFlow(root);
    assert.equal(root.hasAttribute("data-enhanced"), false);
    for (const disclosure of root.querySelectorAll("[data-core-flow-disclosure]")) {
      assert.equal(disclosure.hasAttribute("open"), true); // the source state stays complete
    }
  } finally {
    dom.window.close();
  }
});

test("hover-capable: focus shows / blur hides; pointerenter shows / pointerleave hides", () => {
  const { dom, win, triggers, tooltips } = fixture();
  try {
    triggers.a.focus();
    assert.equal(visible(tooltips.a), true);
    triggers.a.blur();
    assert.equal(visible(tooltips.a), false);
    fire(win, triggers.a, "pointerenter");
    assert.equal(visible(tooltips.a), true);
    fire(win, triggers.a, "pointerleave");
    assert.equal(visible(tooltips.a), false);
  } finally {
    dom.window.close();
  }
});

test("the tooltip itself is hoverable: crossing from trigger to tooltip keeps it open", () => {
  const { dom, win, triggers, tooltips } = fixture();
  try {
    // The pointer crosses from the trigger onto the tooltip (the CSS bridge makes the two
    // hit areas contiguous, so the leave's relatedTarget IS the tooltip): hover intent
    // survives the crossing — the tooltip never blinks off.
    fire(win, triggers.a, "pointerenter");
    assert.equal(visible(tooltips.a), true);
    triggers.a.dispatchEvent(new win.MouseEvent("pointerleave", { relatedTarget: tooltips.a }));
    assert.equal(visible(tooltips.a), true);
    fire(win, tooltips.a, "pointerenter");
    assert.equal(visible(tooltips.a), true);
    // Crossing back down onto the trigger keeps it open too…
    tooltips.a.dispatchEvent(new win.MouseEvent("pointerleave", { relatedTarget: triggers.a }));
    assert.equal(visible(tooltips.a), true);
    // …and leaving the tooltip for anywhere else releases the hover intent.
    fire(win, tooltips.a, "pointerenter");
    fire(win, tooltips.a, "pointerleave");
    assert.equal(visible(tooltips.a), false);
  } finally {
    dom.window.close();
  }
});

test("overlapping intents (both orders): hiding requires losing both", () => {
  const { dom, win, triggers, tooltips } = fixture();
  try {
    // pointerleave while focused keeps it open…
    triggers.a.focus();
    fire(win, triggers.a, "pointerenter");
    fire(win, triggers.a, "pointerleave");
    assert.equal(visible(tooltips.a), true);
    triggers.a.blur();
    assert.equal(visible(tooltips.a), false);
    // …and blur while hovered keeps it open.
    fire(win, triggers.a, "pointerenter");
    triggers.a.focus();
    triggers.a.blur();
    assert.equal(visible(tooltips.a), true);
    fire(win, triggers.a, "pointerleave");
    assert.equal(visible(tooltips.a), false);
  } finally {
    dom.window.close();
  }
});

test("Escape at the document level dismisses a hover-opened tooltip (focus elsewhere)", () => {
  const { dom, win, doc, triggers, tooltips } = fixture();
  try {
    doc.getElementById("outside").focus();
    fire(win, triggers.a, "pointerenter");
    assert.equal(visible(tooltips.a), true);
    pressEscape(win, doc);
    assert.equal(visible(tooltips.a), false);
    // Still hovered: the dismissed latch holds until hover intent drops and re-establishes.
    fire(win, triggers.a, "pointerenter");
    assert.equal(visible(tooltips.a), false);
    fire(win, triggers.a, "pointerleave");
    fire(win, triggers.a, "pointerenter");
    assert.equal(visible(tooltips.a), true);
  } finally {
    dom.window.close();
  }
});

test("Escape on a focused trigger dismisses without moving focus; the latch holds", () => {
  const { dom, win, doc, triggers, tooltips } = fixture();
  try {
    triggers.a.focus();
    assert.equal(visible(tooltips.a), true);
    pressEscape(win, doc);
    assert.equal(visible(tooltips.a), false);
    assert.equal(doc.activeElement, triggers.a); // focus never moved
    fire(win, triggers.a, "focus"); // a re-fired focus intent must not defeat the latch
    assert.equal(visible(tooltips.a), false);
    triggers.a.blur(); // intent drops → latch clears
    triggers.a.focus();
    assert.equal(visible(tooltips.a), true);
  } finally {
    dom.window.close();
  }
});

test("hover-none: focus→click activation yields one visible toggle-on; click toggles off", () => {
  const { dom, win, triggers, tooltips } = fixture({ hoverNone: true });
  try {
    // The tap sequence: pointerenter + focus are ignored as intent; click pins.
    fire(win, triggers.a, "pointerenter");
    triggers.a.focus();
    assert.equal(visible(tooltips.a), false);
    triggers.a.click();
    assert.equal(visible(tooltips.a), true);
    triggers.a.click();
    assert.equal(visible(tooltips.a), false);
  } finally {
    dom.window.close();
  }
});

test("hover-capable: click is a no-op", () => {
  const { dom, triggers, tooltips } = fixture();
  try {
    triggers.a.click();
    assert.equal(visible(tooltips.a), false);
  } finally {
    dom.window.close();
  }
});

test("one at a time across triggers, including clearing a pin", () => {
  const { dom, win, triggers, tooltips } = fixture({ hoverNone: true });
  try {
    triggers.a.click();
    assert.equal(visible(tooltips.a), true);
    triggers.b.click();
    assert.equal(visible(tooltips.b), true);
    assert.equal(visible(tooltips.a), false);
    // a's pin was cleared by b opening: the next click toggles a ON, not off.
    triggers.a.click();
    assert.equal(visible(tooltips.a), true);
    assert.equal(visible(tooltips.b), false);
    fire(win, triggers.a, "pointerenter"); // ignored as intent on hover-none — still pinned
    assert.equal(visible(tooltips.a), true);
  } finally {
    dom.window.close();
  }
});

test("data-align measurement defaults to center in jsdom and does not throw", () => {
  const { dom, triggers, tooltips } = fixture();
  try {
    triggers.a.focus();
    assert.equal(tooltips.a.getAttribute("data-align"), "center");
  } finally {
    dom.window.close();
  }
});

test("beforeprint opens all disclosures; afterprint restores the prior open/closed set", () => {
  const { dom, win, disclosures } = fixture();
  try {
    disclosures[1].setAttribute("open", "");
    fire(win, win, "beforeprint");
    for (const disclosure of disclosures) assert.equal(disclosure.hasAttribute("open"), true);
    fire(win, win, "afterprint");
    assert.equal(disclosures[0].hasAttribute("open"), false);
    assert.equal(disclosures[1].hasAttribute("open"), true);
    assert.equal(disclosures[2].hasAttribute("open"), false);
  } finally {
    dom.window.close();
  }
});

test("double-enhance is idempotent (a second call never re-collapses)", () => {
  const { dom, root, disclosures } = fixture();
  try {
    disclosures[0].setAttribute("open", "");
    enhanceCoreFlow(root, { matchMedia: () => ({ matches: false }) });
    assert.equal(disclosures[0].hasAttribute("open"), true);
    assert.equal(root.hasAttribute("data-enhanced"), true);
  } finally {
    dom.window.close();
  }
});
