"""Boundary models and trusted domain values for the living prose map."""

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

type Audience = Literal["shipped", "self-development", "both"]
type DeliveryMode = Literal["cold", "warm", "headless", "ambient", "subagent"]
type ProseKind = Literal[
    "markdown",
    "python-symbol",
    "typescript-tool",
    "typescript-model-call",
    "typescript-symbol",
    "managed-prose",
    "ambient-routing",
]
type ProseRole = Literal[
    "launch",
    "context",
    "adapter",
    "skill-detail",
    "ambient-discovery",
    "tool-contract",
    "subagent-instruction",
    "control-guidance",
]
type BoundaryKind = Literal["pi-system", "borrowed-prompt", "user-content", "runtime-state"]


class _InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CapabilityInput(_InputModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    parent: str | None = None


class MatchInput(_InputModel):
    kinds: list[ProseKind] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    ids: list[str] = Field(default_factory=list)


class RouteInput(_InputModel):
    id: str = Field(min_length=1)
    match: MatchInput
    capability: str = Field(min_length=1)
    audience: Audience
    role: ProseRole
    priority: int


class ExclusionInput(_InputModel):
    id: str = Field(min_length=1)
    match: MatchInput
    reason: str = Field(min_length=1)


class SessionShapeInput(_InputModel):
    id: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    label: str = Field(min_length=1)
    delivery: DeliveryMode
    trigger: str = Field(min_length=1)
    assembly: str = Field(min_length=1)


class AssemblyLayerInput(_InputModel):
    unit: str | None = None
    boundary: BoundaryKind | None = None
    label: str | None = None
    optional: bool = False


class AssemblyInput(_InputModel):
    id: str = Field(min_length=1)
    layers: list[AssemblyLayerInput] = Field(min_length=1)


class ScenarioInput(_InputModel):
    id: str = Field(min_length=1)
    assembly: str = Field(min_length=1)
    label: str = Field(min_length=1)
    variables: dict[str, str] = Field(default_factory=dict)
    include_ambient: bool
    include_tools: bool


class ConcernRelationInput(_InputModel):
    unit: str = Field(min_length=1)
    relation: str = Field(min_length=1)


class ConcernInput(_InputModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    canonical_unit: str = Field(min_length=1)
    related: list[ConcernRelationInput] = Field(default_factory=list)


class LineageInput(_InputModel):
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    relationship: Literal["generated-from", "materializes-to", "bundled-as"]
    targets: list[str] = Field(min_length=1)


class ProseMapInput(_InputModel):
    schema_version: Literal[1]
    capabilities: list[CapabilityInput] = Field(min_length=1)
    routes: list[RouteInput] = Field(min_length=1)
    exclusions: list[ExclusionInput] = Field(default_factory=list)
    session_shapes: list[SessionShapeInput] = Field(default_factory=list)
    assemblies: list[AssemblyInput] = Field(default_factory=list)
    scenarios: list[ScenarioInput] = Field(default_factory=list)
    concerns: list[ConcernInput] = Field(default_factory=list)
    lineage: list[LineageInput] = Field(default_factory=list)


class DiscoveredFragmentInput(_InputModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    selector: str = Field(min_length=1)


class DiscoveredCandidateInput(_InputModel):
    id: str = Field(min_length=1)
    kind: ProseKind
    path: str = Field(min_length=1)
    selector: str = Field(min_length=1)
    fragments: list[DiscoveredFragmentInput] = Field(min_length=1)


class _DiscoveredToolFieldInput(_InputModel):
    tool: str = Field(min_length=1)
    path: str = Field(min_length=1)
    selector: str = Field(min_length=1)


class DiscoveredUnclassifiedToolFieldInput(_DiscoveredToolFieldInput):
    kind: Literal["unclassified"]
    field: str = Field(min_length=1)
    reason: Literal["unclassified-field"]


class DiscoveredOpaqueToolFieldInput(_DiscoveredToolFieldInput):
    kind: Literal["opaque"]
    field: None
    reason: Literal["spread-assignment", "dynamic-computed-property"]


type DiscoveredToolFieldInput = Annotated[
    DiscoveredUnclassifiedToolFieldInput | DiscoveredOpaqueToolFieldInput,
    Field(discriminator="kind"),
]


class TypeScriptCatalogInput(_InputModel):
    candidates: list[DiscoveredCandidateInput]
    governed_tools: list[str]
    tool_field_issues: list[DiscoveredToolFieldInput]


@dataclass(frozen=True)
class Capability:
    id: str
    label: str
    summary: str
    parent: str | None


@dataclass(frozen=True)
class Match:
    kinds: tuple[ProseKind, ...]
    paths: tuple[str, ...]
    ids: tuple[str, ...]


@dataclass(frozen=True)
class Route:
    id: str
    match: Match
    capability: str
    audience: Audience
    role: ProseRole
    priority: int


@dataclass(frozen=True)
class Exclusion:
    id: str
    match: Match
    reason: str


@dataclass(frozen=True)
class SessionShape:
    id: str
    capability: str
    label: str
    delivery: DeliveryMode
    trigger: str
    assembly: str


@dataclass(frozen=True)
class AssemblyLayer:
    unit: str | None
    boundary: BoundaryKind | None
    label: str | None
    optional: bool


@dataclass(frozen=True)
class Assembly:
    id: str
    layers: tuple[AssemblyLayer, ...]


@dataclass(frozen=True)
class Scenario:
    id: str
    assembly: str
    label: str
    variables: tuple[tuple[str, str], ...]
    include_ambient: bool
    include_tools: bool


@dataclass(frozen=True)
class ConcernRelation:
    unit: str
    relation: str


@dataclass(frozen=True)
class Concern:
    id: str
    label: str
    summary: str
    canonical_unit: str
    related: tuple[ConcernRelation, ...]


@dataclass(frozen=True)
class Lineage:
    id: str
    source: str
    relationship: Literal["generated-from", "materializes-to", "bundled-as"]
    targets: tuple[str, ...]


@dataclass(frozen=True)
class ProseMap:
    capabilities: tuple[Capability, ...]
    routes: tuple[Route, ...]
    exclusions: tuple[Exclusion, ...]
    session_shapes: tuple[SessionShape, ...]
    assemblies: tuple[Assembly, ...]
    scenarios: tuple[Scenario, ...]
    concerns: tuple[Concern, ...]
    lineage: tuple[Lineage, ...]


@dataclass(frozen=True)
class Fragment:
    id: str
    label: str
    selector: str


@dataclass(frozen=True)
class Candidate:
    id: str
    kind: ProseKind
    path: str
    selector: str
    fragments: tuple[Fragment, ...]


@dataclass(frozen=True)
class UnclassifiedToolFieldIssue:
    kind: Literal["unclassified"]
    field: str
    reason: Literal["unclassified-field"]
    tool: str
    path: str
    selector: str


@dataclass(frozen=True)
class OpaqueToolFieldIssue:
    kind: Literal["opaque"]
    field: None
    reason: Literal["spread-assignment", "dynamic-computed-property"]
    tool: str
    path: str
    selector: str


type ToolFieldIssue = UnclassifiedToolFieldIssue | OpaqueToolFieldIssue


@dataclass(frozen=True)
class DiscoveryResult:
    candidates: tuple[Candidate, ...]
    governed_tools: tuple[str, ...]
    tool_field_issues: tuple[ToolFieldIssue, ...]


@dataclass(frozen=True)
class RoutedUnit:
    candidate: Candidate
    capability: str
    audience: Audience
    role: ProseRole


@dataclass(frozen=True)
class Finding:
    code: str
    message: str


@dataclass(frozen=True)
class Catalog:
    graph: ProseMap
    units: tuple[RoutedUnit, ...]
    excluded: tuple[Candidate, ...]
    findings: tuple[Finding, ...]
    governed_tools: tuple[str, ...]
