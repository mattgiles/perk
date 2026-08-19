// Interaction controller for the core-flow diagram (components/CoreFlowDiagram.astro).
// Framework-free ES module so node:test + jsdom can unit-test the full state machine
// (core-flow-controller.test.mjs) — the component mounts it via its processed module script.
//
// The unenhanced source state is complete: satellites ship `<details open>`, tooltips ship
// `hidden`. Enhancement collapses the disclosures (they stay native and independent — never
// accordion-coupled), re-opens them around printing, and drives the supplementary tooltips.
//
// Tooltip state machine (bound in the visual blueprint §5): per trigger, three intent bits
// (`hover`, `focus`, `pinned`) and a `dismissed` latch —
//   visible ⇔ (hover ∨ focus ∨ pinned) ∧ ¬dismissed.
// Losing one intent while another holds does NOT hide. Hover intent is held by the trigger
// OR the visible tooltip itself (WCAG 2.2 SC 1.4.13 hoverable): a pointerleave whose
// `relatedTarget` is the paired trigger/tooltip is a crossing, not a departure, so the
// tooltip never blinks off mid-crossing — and the component's CSS bridges the 8px gap with
// a hit-area pseudo-element so the crossing never passes dead space. On hover-capable
// hover/focus drive visibility and click is a no-op; on hover-incapable devices click
// toggles `pinned` (Enter/Space on the button also produce click — the keyboard path) while
// focus AND pointer events are ignored as intent, so a tap's focus-then-synthesized-click
// sequence yields exactly one visible toggle-on. Escape is owned at the document level: it
// hides the open tooltip regardless of where focus sits and latches `dismissed`, which
// clears only when the trigger's remaining intents fully drop (pointerleave/blur) or on a
// new tap — so Escape never flickers while still hovered/focused. Only one tooltip is
// visible at a time.

/**
 * Enhance one core-flow figure. Idempotent (`data-enhanced` on the root); a root whose
 * document has no window (`defaultView === null`) is left unenhanced — the source state is
 * complete. `matchMedia` is the injection seam for tests; it defaults to the root window's
 * own `matchMedia`, bound to that window.
 */
export function enhanceCoreFlow(root, { matchMedia } = {}) {
  const doc = root.ownerDocument;
  const win = doc.defaultView;
  if (win === null) return;
  if (root.hasAttribute("data-enhanced")) return;
  root.setAttribute("data-enhanced", "");

  // The default resolves through the root's own window; jsdom ships no matchMedia at all,
  // so absent capability data falls back to the hover-capable arm.
  const media =
    matchMedia ?? (typeof win.matchMedia === "function" ? win.matchMedia.bind(win) : null);
  const hoverIncapable = media?.("(hover: none)").matches === true;

  // --- Disclosures: collapsed by default once enhanced; re-opened around printing ----------
  const disclosures = [...root.querySelectorAll("[data-core-flow-disclosure]")];
  for (const disclosure of disclosures) {
    disclosure.removeAttribute("open");
  }

  let printedState = null;
  win.addEventListener("beforeprint", () => {
    printedState = disclosures.map((disclosure) => disclosure.hasAttribute("open"));
    for (const disclosure of disclosures) {
      disclosure.setAttribute("open", "");
    }
  });
  win.addEventListener("afterprint", () => {
    if (printedState === null) return;
    disclosures.forEach((disclosure, index) => {
      if (!printedState[index]) disclosure.removeAttribute("open");
    });
    printedState = null;
  });

  // --- Tooltips -----------------------------------------------------------------------------
  let openState = null;

  function hide(state) {
    if (openState === state) openState = null;
    state.tooltip.setAttribute("hidden", "");
  }

  function align(state) {
    // Measured once at show time against the figure box; jsdom's zero-size rects fall
    // through to the centered default (and must not throw).
    state.tooltip.setAttribute("data-align", "center");
    const tip = state.tooltip.getBoundingClientRect();
    const box = root.getBoundingClientRect();
    if (tip.width > 0 && box.width > 0) {
      if (tip.left < box.left) state.tooltip.setAttribute("data-align", "start");
      else if (tip.right > box.right) state.tooltip.setAttribute("data-align", "end");
    }
  }

  function show(state) {
    if (openState === state) return;
    if (openState !== null) {
      // One at a time: the newcomer clears every intent and the pin on the open one.
      const previous = openState;
      previous.hover = false;
      previous.focus = false;
      previous.pinned = false;
      previous.dismissed = false;
      hide(previous);
    }
    openState = state;
    state.tooltip.removeAttribute("hidden");
    align(state);
  }

  function sync(state) {
    const visible = (state.hover || state.focus || state.pinned) && !state.dismissed;
    if (visible) show(state);
    else hide(state);
  }

  function settleDismissal(state) {
    if (!state.hover && !state.focus && !state.pinned) state.dismissed = false;
  }

  for (const trigger of root.querySelectorAll("button[data-core-flow-tip]")) {
    const tooltip = doc.getElementById(trigger.getAttribute("aria-describedby"));
    const state = { tooltip, hover: false, focus: false, pinned: false, dismissed: false };

    const hoverEnter = () => {
      if (hoverIncapable) return; // taps fire pointerenter too — never hover intent
      state.hover = true;
      sync(state);
    };
    const hoverLeave = (event) => {
      // A leave whose destination is the paired trigger/tooltip is a crossing between the
      // two hover surfaces (SC 1.4.13: the tooltip is hoverable) — hover intent survives.
      const to = event.relatedTarget ?? null;
      if (to !== null && (trigger.contains(to) || tooltip.contains(to))) return;
      state.hover = false;
      settleDismissal(state);
      sync(state);
    };
    trigger.addEventListener("pointerenter", hoverEnter);
    trigger.addEventListener("pointerleave", hoverLeave);
    tooltip.addEventListener("pointerenter", hoverEnter);
    tooltip.addEventListener("pointerleave", hoverLeave);
    trigger.addEventListener("focus", () => {
      if (hoverIncapable) return; // the tap sequence synthesizes focus before click
      state.focus = true;
      sync(state);
    });
    trigger.addEventListener("blur", () => {
      state.focus = false;
      settleDismissal(state);
      sync(state);
    });
    trigger.addEventListener("click", () => {
      if (!hoverIncapable) return; // hover/focus own visibility on hover-capable devices
      if (state.pinned) {
        state.pinned = false;
      } else {
        state.dismissed = false; // a new tap always un-latches
        state.pinned = true;
      }
      sync(state);
    });
  }

  doc.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || openState === null) return;
    const state = openState;
    state.pinned = false;
    state.dismissed = true;
    sync(state);
  });
}
