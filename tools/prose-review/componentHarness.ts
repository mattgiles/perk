// The shared jsdom infrastructure for the component suites (plain .ts — not matched
// by the `*.test.ts` run glob; typechecked as an import of the included test files).
// One DOM install/teardown, one act-wrapped render/interaction surface, and the
// fetch-stub install/restore idiom — the suites own only their fixtures and routes.

// The bootstrap DOM must exist before react-dom's module-scope environment
// probes run — keep this side-effect import first.
import "./domBootstrap.ts";
import assert from "node:assert/strict";
import { setImmediate as tick } from "node:timers/promises";
import { JSDOM } from "jsdom";
import * as React from "react";
import { createRoot, type Root } from "react-dom/client";

export type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

export function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

export type RenderHarness = {
  window: JSDOM["window"];
  container: HTMLElement;
  render: (node: React.ReactNode) => Promise<void>;
  click: (element: Element) => Promise<void>;
  keydown: (element: Element, key: string, init?: KeyboardEventInit) => Promise<KeyboardEvent>;
  input: (element: HTMLTextAreaElement, value: string) => Promise<void>;
  selectOption: (element: HTMLSelectElement, value: string) => Promise<void>;
  settle: () => Promise<void>;
  cleanup: () => Promise<void>;
};

export type InstallDomOptions = {
  // When set, the page carries the CSRF meta tag mutation requests read.
  csrfToken?: string;
};

export function installDom(options: InstallDomOptions = {}): RenderHarness {
  const head =
    options.csrfToken === undefined
      ? ""
      : `<head><meta name='csrf-token' content='${options.csrfToken}'></head>`;
  const dom = new JSDOM(`<!doctype html><html>${head}<body><div id='root'></div></body></html>`, {
    url: "http://127.0.0.1/",
  });
  const previous = new Map<string, PropertyDescriptor | undefined>();
  const globals: Record<string, unknown> = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
    HTMLSelectElement: dom.window.HTMLSelectElement,
    Element: dom.window.Element,
    Node: dom.window.Node,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
    KeyboardEvent: dom.window.KeyboardEvent,
    InputEvent: dom.window.InputEvent,
    MutationObserver: dom.window.MutationObserver,
    getComputedStyle: dom.window.getComputedStyle.bind(dom.window),
    IS_REACT_ACT_ENVIRONMENT: true,
    React,
  };
  for (const [name, value] of Object.entries(globals)) {
    previous.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
  }

  // jsdom lacks scrollIntoView; production calls it plainly, so a no-op polyfill
  // keeps the traversal handlers runnable under node:test.
  if (dom.window.Element.prototype.scrollIntoView === undefined) {
    dom.window.Element.prototype.scrollIntoView = () => undefined;
  }

  const container = dom.window.document.querySelector<HTMLElement>("#root");
  assert.ok(container !== null);
  const root: Root = createRoot(container);
  return {
    window: dom.window,
    container,
    async render(node: React.ReactNode): Promise<void> {
      await React.act(async () => {
        root.render(node);
        await tick();
      });
    },
    async click(element: Element): Promise<void> {
      await React.act(async () => {
        element.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
        await tick();
      });
    },
    async keydown(element: Element, key: string, init?: KeyboardEventInit): Promise<KeyboardEvent> {
      // Bubbling + cancelable mirrors real key events: React's delegated onKeyDown
      // handlers and window-level listeners both observe it, and tests can assert
      // defaultPrevented afterwards.
      const event = new dom.window.KeyboardEvent("keydown", {
        bubbles: true,
        cancelable: true,
        key,
        ...init,
      });
      await React.act(async () => {
        element.dispatchEvent(event);
        await tick();
      });
      return event;
    },
    async input(element: HTMLTextAreaElement, value: string): Promise<void> {
      const setter = Object.getOwnPropertyDescriptor(
        dom.window.HTMLTextAreaElement.prototype,
        "value",
      )?.set;
      assert.ok(setter !== undefined);
      const previousValue = element.value;
      await React.act(async () => {
        setter.call(element, value);
        const tracked = element as HTMLTextAreaElement & {
          _valueTracker?: { setValue: (next: string) => void };
        };
        tracked._valueTracker?.setValue(previousValue);
        element.dispatchEvent(new dom.window.InputEvent("input", { bubbles: true }));
        element.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
        await tick();
      });
    },
    async selectOption(element: HTMLSelectElement, value: string): Promise<void> {
      // Unlike inputs/textareas, React attaches no value tracker to a <select>:
      // a plain value assignment plus one native change event is enough.
      await React.act(async () => {
        element.value = value;
        element.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
        await tick();
      });
    },
    async settle(): Promise<void> {
      await React.act(async () => {
        await tick();
        await tick();
      });
    },
    async cleanup(): Promise<void> {
      await React.act(async () => root.unmount());
      dom.window.close();
      for (const [name, descriptor] of previous) {
        if (descriptor === undefined) {
          Reflect.deleteProperty(globalThis, name);
        } else {
          Object.defineProperty(globalThis, name, descriptor);
        }
      }
    },
  };
}

export function response(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export type FetchStub = (url: string, init?: RequestInit) => Promise<Response> | Response;

/** Install a URL-string fetch stub; the returned function restores the previous fetch. */
export function stubFetch(handler: FetchStub): () => void {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = (async (input, init): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    return handler(url, init);
  }) as typeof fetch;
  return () => {
    globalThis.fetch = previousFetch;
  };
}

export function itemAt<T>(items: ArrayLike<T>, index: number): T {
  const item = items[index];
  assert.ok(item !== undefined, `missing item at index ${index}`);
  return item;
}

export function normalizedText(element: Element): string {
  return (element.textContent ?? "").replaceAll(/\s+/g, " ").trim();
}

export function buttonByText(container: ParentNode, text: string): HTMLButtonElement {
  const button = [...container.querySelectorAll<HTMLButtonElement>("button")].find(
    (candidate) => normalizedText(candidate) === text,
  );
  assert.ok(button !== undefined, `missing button: ${text}`);
  return button;
}

export function buttonStartingWith(container: ParentNode, text: string): HTMLButtonElement {
  const button = [...container.querySelectorAll<HTMLButtonElement>("button")].find((candidate) =>
    normalizedText(candidate).startsWith(text),
  );
  assert.ok(button !== undefined, `missing button starting with: ${text}`);
  return button;
}

export function buttonByLabel(container: ParentNode, label: string): HTMLButtonElement {
  const button = container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
  assert.ok(button !== null, `missing labeled button: ${label}`);
  return button;
}
