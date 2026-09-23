// hostSdkNamespaces(): exactly the census keys, every value a non-empty namespace, and the values
// ARE the instances this process resolves for the same specifiers (identity — the facades' point).

import assert from "node:assert/strict";
import { test } from "node:test";
import { truncateToWidth } from "@earendil-works/pi-tui";
import { Type } from "typebox";
import { hostSdkNamespaces } from "./hostSdk.ts";
import { NATIVE_SDK_CENSUS } from "./nativeSdkBridge.ts";

test("hostSdkNamespaces: exactly the census keys, each a namespace with ≥ 1 export", () => {
  const namespaces = hostSdkNamespaces();
  assert.deepEqual([...namespaces.keys()].sort(), [...NATIVE_SDK_CENSUS].sort());
  for (const [specifier, namespace] of namespaces) {
    assert.equal(typeof namespace, "object", specifier);
    assert.ok(
      Object.keys(namespace).filter((key) => key !== "__esModule").length > 0,
      `${specifier} captured an empty namespace`,
    );
  }
});

test("hostSdkNamespaces: the captured values are this process's own instances", () => {
  const namespaces = hostSdkNamespaces();
  const tui = namespaces.get("@earendil-works/pi-tui") as { truncateToWidth?: unknown };
  assert.equal(tui.truncateToWidth, truncateToWidth, "pi-tui reaches the bridge via surfaces.ts");
  const typebox = namespaces.get("typebox") as { Type?: unknown };
  assert.equal(typebox.Type, Type);
});
