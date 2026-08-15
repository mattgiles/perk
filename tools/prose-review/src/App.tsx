import { useEffect, useState } from "react";
import { type CatalogSummary, parseSummary } from "./summary.ts";

type LoadState =
  | { status: "loading" }
  | { status: "failed" }
  | { status: "loaded"; summary: CatalogSummary };

// The entire round-trip-proof UI: fetch the typed summary DTO once on mount and render
// it — every repository-derived value flows through JSX text interpolation only
// (escaped by default; the dom-sinks scan and the CSP back this invariant up).
export function App() {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    const load = async (): Promise<void> => {
      try {
        const response = await fetch("/api/catalog/summary");
        if (!response.ok) {
          throw new Error(`unexpected status ${response.status}`);
        }
        const summary = parseSummary(await response.json());
        if (summary === null) {
          throw new Error("ill-shaped summary payload");
        }
        if (!cancelled) {
          setState({ status: "loaded", summary });
        }
      } catch {
        // One fixed failure message for every arm: non-ok, network, JSON parse,
        // and a parseSummary rejection.
        if (!cancelled) {
          setState({ status: "failed" });
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.status === "loading") {
    return <p>Loading catalog summary…</p>;
  }
  if (state.status === "failed") {
    return <p>Failed to load catalog summary.</p>;
  }
  const { summary } = state;
  return (
    <main>
      <h1>Prose Review</h1>
      <h2>Catalog</h2>
      <ul>
        <li>units: {summary.units}</li>
        <li>fragments: {summary.fragments}</li>
        <li>session shapes: {summary.session_shapes}</li>
        <li>assemblies: {summary.assemblies}</li>
        <li>scenarios: {summary.scenarios}</li>
        <li>concerns: {summary.concerns}</li>
        <li>lineage rules: {summary.lineage_rules}</li>
      </ul>
      <h2>Capabilities</h2>
      <ul>
        {summary.capabilities.map((capability) => (
          <li key={capability.id}>{capability.label}</li>
        ))}
      </ul>
    </main>
  );
}
