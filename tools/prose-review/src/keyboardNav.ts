// The pure keyboard-navigation helpers behind the workbench's keyboard contract
// (recorded in docs/design/prose-review-stack.md): F6 pane cycling and clamped
// DOM-order list stepping (tree entries and search results). Framework-free so
// node:test drives them directly; the components own only event wiring and focus
// calls.

/**
 * The next pane in the F6 cycle. `panes` is the fixed cycle order (null entries —
 * e.g. the unmounted drawer — are skipped); the pane containing (or being) `active`
 * anchors the step, wrapping at both ends. When `active` sits in no pane, the first
 * non-null pane is the entry point regardless of direction.
 */
export function cyclePane(
  panes: (HTMLElement | null)[],
  active: Element | null,
  direction: 1 | -1,
): HTMLElement | null {
  const mounted = panes.filter((pane): pane is HTMLElement => pane !== null);
  if (mounted.length === 0) {
    return null;
  }
  const current =
    active === null ? -1 : mounted.findIndex((pane) => pane === active || pane.contains(active));
  if (current === -1) {
    return mounted[0] ?? null;
  }
  const next = (current + direction + mounted.length) % mounted.length;
  return mounted[next] ?? null;
}

/**
 * Clamped stepping over a DOM-order button list. Arrow keys step by one; Home/End
 * jump to the extremes. Returns the element to focus, or null when the key is
 * unhandled here (`active` outside the list on Arrow keys aside — ArrowDown then
 * enters at the first entry, the post-F6 container-focused case) or the step is
 * already at the clamp.
 */
export function moveFocusInList(
  buttons: HTMLElement[],
  active: Element | null,
  key: "ArrowDown" | "ArrowUp" | "Home" | "End",
): HTMLElement | null {
  if (buttons.length === 0) {
    return null;
  }
  if (key === "Home") {
    return buttons[0] ?? null;
  }
  if (key === "End") {
    return buttons[buttons.length - 1] ?? null;
  }
  // Identity lookup only — a non-HTMLElement active is simply absent (-1).
  const current = active === null ? -1 : buttons.indexOf(active as HTMLElement);
  if (current === -1) {
    return key === "ArrowDown" ? (buttons[0] ?? null) : null;
  }
  const next = current + (key === "ArrowDown" ? 1 : -1);
  if (next < 0 || next >= buttons.length) {
    return null;
  }
  return buttons[next] ?? null;
}
