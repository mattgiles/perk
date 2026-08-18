// The typed fetch boundary for /api/assembly/options and /api/assembly/render: local
// mirrors of the wire shapes plus reject-unknown structural parsers (the
// tree.ts/comparison.ts posture — every known field required and correctly typed; any
// defect rejects the whole payload with null). The closed vocabularies below are
// endpoint-only, so they live here rather than in wire.ts. One deliberate opening:
// a problem's `reason` is validated as a non-empty string, not a closed set — the
// client renders the server's fixed `detail` copy and must not duplicate the
// server-internal reason vocabulary.

import { type FragmentRef, parseFragmentRef } from "./selection.ts";
import { parseUnitRef, type UnitRef } from "./tree.ts";
import { type BoundaryKind, isBoundaryKind } from "./wire.ts";

export const LAYER_PRESENCES = ["always", "varies"] as const;

export type LayerPresence = (typeof LAYER_PRESENCES)[number];

export const PRESENTATION_CONTROLS = ["ambient", "tools"] as const;

export type PresentationControl = (typeof PRESENTATION_CONTROLS)[number];

export const BOUNDARY_OWNERS = ["pi", "user", "runtime", "borrowed-package"] as const;

export type BoundaryOwner = (typeof BOUNDARY_OWNERS)[number];

export const OWNED_CONTENT_KINDS = ["rendered-template", "raw-source", "source-fragments"] as const;

export type OwnedContentKind = (typeof OWNED_CONTENT_KINDS)[number];

export type AssemblyScenario = {
  id: string;
  label: string;
  variables: Record<string, string>;
  include_ambient: boolean;
  include_tools: boolean;
};

// The parse boundary guarantees at least one scenario, so scenarios[0] is defined
// under noUncheckedIndexedAccess and the session controller stays total.
export type AssemblyOptions = {
  assembly: string;
  scenarios: [AssemblyScenario, ...AssemblyScenario[]];
};

export type AssemblyPresentation = {
  include_ambient: boolean;
  include_tools: boolean;
};

export type AssemblyLayerPresentation = {
  position: number;
  label: string | null;
  presence: LayerPresence;
  presence_label: string | null;
  visibility_control: PresentationControl | null;
};

export type AssemblyContentPart = {
  fragment: FragmentRef | null;
  text: string;
};

export type AssemblyLayerProblem = {
  fragment: FragmentRef | null;
  reason: string;
  detail: string;
};

export type AssemblyOwnedLayer = {
  type: "owned";
  presentation: AssemblyLayerPresentation;
  unit: UnitRef;
  content_kind: OwnedContentKind;
  parts: AssemblyContentPart[];
};

export type AssemblyBoundaryLayer = {
  type: "boundary";
  presentation: AssemblyLayerPresentation;
  boundary: BoundaryKind;
  owner: BoundaryOwner;
};

export type AssemblyFailureLayer = {
  type: "failure";
  presentation: AssemblyLayerPresentation;
  unit: UnitRef;
  problems: AssemblyLayerProblem[];
};

export type AssemblyRenderedLayer = AssemblyOwnedLayer | AssemblyBoundaryLayer | AssemblyFailureLayer;

export type AssemblyRender = {
  assembly: string;
  scenario: AssemblyScenario;
  presentation: AssemblyPresentation;
  layers: AssemblyRenderedLayer[];
};

// The exact render request identity (the nullable overrides ride verbatim so the
// server echo matches the request-time resolution).
export type AssemblyRenderRequest = {
  assembly: string;
  scenario: string;
  presentation: {
    include_ambient: boolean | null;
    include_tools: boolean | null;
  };
};

export type AssemblyOverrides = {
  ambient: boolean | null;
  tools: boolean | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function nonEmpty(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function parseArray<T>(value: unknown, parseEntry: (entry: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const entries: T[] = [];
  for (const entry of value) {
    const parsed = parseEntry(entry);
    if (parsed === null) {
      return null;
    }
    entries.push(parsed);
  }
  return entries;
}

function isLayerPresence(value: unknown): value is LayerPresence {
  return typeof value === "string" && (LAYER_PRESENCES as readonly string[]).includes(value);
}

function isPresentationControl(value: unknown): value is PresentationControl {
  return typeof value === "string" && (PRESENTATION_CONTROLS as readonly string[]).includes(value);
}

function isBoundaryOwner(value: unknown): value is BoundaryOwner {
  return typeof value === "string" && (BOUNDARY_OWNERS as readonly string[]).includes(value);
}

function isOwnedContentKind(value: unknown): value is OwnedContentKind {
  return typeof value === "string" && (OWNED_CONTENT_KINDS as readonly string[]).includes(value);
}

// Entries stay in received key order — the server sorts, the client only displays.
function parseVariables(value: unknown): Record<string, string> | null {
  if (!isRecord(value) || Array.isArray(value)) {
    return null;
  }
  const variables: Record<string, string> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (typeof entry !== "string") {
      return null;
    }
    variables[key] = entry;
  }
  return variables;
}

function parseScenario(value: unknown): AssemblyScenario | null {
  if (
    !isRecord(value) ||
    !nonEmpty(value.id) ||
    typeof value.label !== "string" ||
    typeof value.include_ambient !== "boolean" ||
    typeof value.include_tools !== "boolean"
  ) {
    return null;
  }
  const variables = parseVariables(value.variables);
  if (variables === null) {
    return null;
  }
  return {
    id: value.id,
    label: value.label,
    variables,
    include_ambient: value.include_ambient,
    include_tools: value.include_tools,
  };
}

/**
 * Validate one complete assembly-options response; null rejects any malformed member.
 * An empty `scenarios` array is rejected too: the backend's scenario-data completeness
 * makes it an ill-shaped payload, not a real state.
 */
export function parseAssemblyOptions(value: unknown): AssemblyOptions | null {
  if (!isRecord(value) || !nonEmpty(value.assembly)) {
    return null;
  }
  const scenarios = parseArray(value.scenarios, parseScenario);
  if (scenarios === null) {
    return null;
  }
  const [first, ...rest] = scenarios;
  if (first === undefined) {
    return null;
  }
  return { assembly: value.assembly, scenarios: [first, ...rest] };
}

function parsePresentation(value: unknown): AssemblyPresentation | null {
  if (
    !isRecord(value) ||
    typeof value.include_ambient !== "boolean" ||
    typeof value.include_tools !== "boolean"
  ) {
    return null;
  }
  return { include_ambient: value.include_ambient, include_tools: value.include_tools };
}

function parseLayerPresentation(value: unknown): AssemblyLayerPresentation | null {
  if (!isRecord(value)) {
    return null;
  }
  const { position, label, presence_label: presenceLabel } = value;
  if (typeof position !== "number" || !Number.isInteger(position) || position < 1) {
    return null;
  }
  if (label !== null && typeof label !== "string") {
    return null;
  }
  if (!isLayerPresence(value.presence)) {
    return null;
  }
  if (presenceLabel !== null && typeof presenceLabel !== "string") {
    return null;
  }
  const control = value.visibility_control;
  if (control !== null && !isPresentationControl(control)) {
    return null;
  }
  return {
    position,
    label,
    presence: value.presence,
    presence_label: presenceLabel,
    visibility_control: control,
  };
}

function parseNullableFragment(value: unknown): { fragment: FragmentRef | null } | null {
  if (value === null) {
    return { fragment: null };
  }
  const fragment = parseFragmentRef(value);
  if (fragment === null) {
    return null;
  }
  return { fragment };
}

function parsePart(value: unknown): AssemblyContentPart | null {
  if (!isRecord(value) || typeof value.text !== "string") {
    return null;
  }
  const fragment = parseNullableFragment(value.fragment);
  if (fragment === null) {
    return null;
  }
  return { fragment: fragment.fragment, text: value.text };
}

function parseProblem(value: unknown): AssemblyLayerProblem | null {
  if (!isRecord(value) || !nonEmpty(value.reason) || typeof value.detail !== "string") {
    return null;
  }
  const fragment = parseNullableFragment(value.fragment);
  if (fragment === null) {
    return null;
  }
  return { fragment: fragment.fragment, reason: value.reason, detail: value.detail };
}

function parseLayer(value: unknown): AssemblyRenderedLayer | null {
  if (!isRecord(value)) {
    return null;
  }
  const presentation = parseLayerPresentation(value.presentation);
  if (presentation === null) {
    return null;
  }
  if (value.type === "owned") {
    const unit = parseUnitRef(value.unit);
    const parts = parseArray(value.parts, parsePart);
    if (unit === null || parts === null || !isOwnedContentKind(value.content_kind)) {
      return null;
    }
    return { type: "owned", presentation, unit, content_kind: value.content_kind, parts };
  }
  if (value.type === "boundary") {
    if (!isBoundaryKind(value.boundary) || !isBoundaryOwner(value.owner)) {
      return null;
    }
    return { type: "boundary", presentation, boundary: value.boundary, owner: value.owner };
  }
  if (value.type === "failure") {
    const unit = parseUnitRef(value.unit);
    const problems = parseArray(value.problems, parseProblem);
    if (unit === null || problems === null) {
      return null;
    }
    return { type: "failure", presentation, unit, problems };
  }
  return null;
}

/** Validate one complete assembly-render response; null rejects any malformed member. */
export function parseAssemblyRender(value: unknown): AssemblyRender | null {
  if (!isRecord(value) || !nonEmpty(value.assembly)) {
    return null;
  }
  const scenario = parseScenario(value.scenario);
  const presentation = parsePresentation(value.presentation);
  const layers = parseArray(value.layers, parseLayer);
  if (scenario === null || presentation === null || layers === null) {
    return null;
  }
  return { assembly: value.assembly, scenario, presentation, layers };
}

/** The comparisonOptionsMatchRequest posture: the echo must name the requested subject. */
export function assemblyRenderMatchesRequest(
  render: AssemblyRender,
  request: AssemblyRenderRequest,
): boolean {
  return render.assembly === request.assembly && render.scenario.id === request.scenario;
}

/** Resolve the two visibility booleans locally: `override ?? scenario default`. */
export function resolvedPresentation(
  scenario: AssemblyScenario,
  overrides: AssemblyOverrides,
): AssemblyPresentation {
  return {
    include_ambient: overrides.ambient ?? scenario.include_ambient,
    include_tools: overrides.tools ?? scenario.include_tools,
  };
}

// Visibility is derived client-side and never re-POSTs: a layer is hidden exactly when
// its visibility_control names a control whose resolved value is false. Presence never
// affects visibility — it is display metadata only.
export function visibleLayers(
  layers: AssemblyRenderedLayer[],
  resolved: AssemblyPresentation,
): AssemblyRenderedLayer[] {
  return layers.filter((layer) => {
    const control = layer.presentation.visibility_control;
    if (control === "ambient") {
      return resolved.include_ambient;
    }
    if (control === "tools") {
      return resolved.include_tools;
    }
    return true;
  });
}

function layerText(layer: AssemblyRenderedLayer): string {
  if (layer.type === "owned") {
    return layer.parts.map((part) => part.text).join("");
  }
  if (layer.type === "boundary") {
    const label = layer.presentation.label ?? layer.boundary;
    return `[[ boundary: ${label} · owner: ${layer.owner} ]]`;
  }
  return `[[ layer failed: ${layer.unit.id} ]]`;
}

/** Join currently-visible layers in delivery order with one blank line between layers. */
export function concatenatedText(layers: AssemblyRenderedLayer[]): string {
  return layers.map(layerText).join("\n\n");
}
