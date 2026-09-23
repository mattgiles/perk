// The pi-subagents fixture entry: like the real package, the entry hands off to a lazily imported
// extension module (so the consumer's census imports resolve from a module BELOW the entry).
export const extension = await import("./src/extension/index.js");
