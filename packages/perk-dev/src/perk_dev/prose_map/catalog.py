"""Load, validate, and query perk's living model-facing prose catalog."""

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, TemplateError, meta
from pydantic import ValidationError

from perk_dev.prose_map.discovery import DiscoveryError, discover
from perk_dev.prose_map.models import (
    Assembly,
    AssemblyLayer,
    Candidate,
    Capability,
    Catalog,
    Concern,
    ConcernRelation,
    Exclusion,
    Finding,
    Lineage,
    Match,
    ProseMap,
    ProseMapInput,
    Route,
    RoutedUnit,
    Scenario,
    SessionShape,
    ToolFieldIssue,
    UnclassifiedToolFieldIssue,
)
from perk_dev.prose_map.render import render_markdown

GRAPH_PATH = Path("docs/design/prose-prompt-map.yaml")
RENDERED_PATH = Path("docs/design/prose-prompt-map.md")


class ProseMapError(Exception):
    """The authored graph or source catalog could not be loaded."""


class _TemplateInspectionError(Exception):
    """A prompt template cannot be inspected statically."""


@dataclass(frozen=True)
class BuildResult:
    catalog: Catalog
    rendered: str


def _match(value: Match, candidate: Candidate) -> bool:
    if value.kinds and candidate.kind not in value.kinds:
        return False
    if value.paths and not any(fnmatchcase(candidate.path, pattern) for pattern in value.paths):
        return False
    return not value.ids or any(fnmatchcase(candidate.id, pattern) for pattern in value.ids)


def _domain(value: ProseMapInput) -> ProseMap:
    return ProseMap(
        capabilities=tuple(
            Capability(
                id=item.id,
                label=item.label,
                summary=item.summary,
                parent=item.parent,
            )
            for item in value.capabilities
        ),
        routes=tuple(
            Route(
                id=item.id,
                match=Match(
                    kinds=tuple(item.match.kinds),
                    paths=tuple(item.match.paths),
                    ids=tuple(item.match.ids),
                ),
                capability=item.capability,
                audience=item.audience,
                role=item.role,
                priority=item.priority,
            )
            for item in value.routes
        ),
        exclusions=tuple(
            Exclusion(
                id=item.id,
                match=Match(
                    kinds=tuple(item.match.kinds),
                    paths=tuple(item.match.paths),
                    ids=tuple(item.match.ids),
                ),
                reason=item.reason,
            )
            for item in value.exclusions
        ),
        session_shapes=tuple(
            SessionShape(
                id=item.id,
                capability=item.capability,
                label=item.label,
                delivery=item.delivery,
                trigger=item.trigger,
                assembly=item.assembly,
            )
            for item in value.session_shapes
        ),
        assemblies=tuple(
            Assembly(
                id=item.id,
                layers=tuple(
                    AssemblyLayer(
                        unit=layer.unit,
                        boundary=layer.boundary,
                        label=layer.label,
                        optional=layer.optional,
                    )
                    for layer in item.layers
                ),
            )
            for item in value.assemblies
        ),
        scenarios=tuple(
            Scenario(
                id=item.id,
                assembly=item.assembly,
                label=item.label,
                variables=tuple(sorted(item.variables.items())),
                include_ambient=item.include_ambient,
                include_tools=item.include_tools,
            )
            for item in value.scenarios
        ),
        concerns=tuple(
            Concern(
                id=item.id,
                label=item.label,
                summary=item.summary,
                canonical_unit=item.canonical_unit,
                related=tuple(
                    ConcernRelation(unit=related.unit, relation=related.relation)
                    for related in item.related
                ),
            )
            for item in value.concerns
        ),
        lineage=tuple(
            Lineage(
                id=item.id,
                source=item.source,
                relationship=item.relationship,
                targets=tuple(item.targets),
            )
            for item in value.lineage
        ),
    )


def load_graph(root: Path) -> ProseMap:
    """Parse the authored YAML boundary and return trusted domain values."""
    path = root / GRAPH_PATH
    if not path.is_file():
        raise ProseMapError(f"prose map is missing: {path}")
    try:
        raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
        boundary = ProseMapInput.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ProseMapError(f"invalid prose map {path}: {exc}") from exc
    return _domain(boundary)


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def validate_graph(graph: ProseMap) -> list[Finding]:
    findings: list[Finding] = []
    capability_ids = [item.id for item in graph.capabilities]
    assembly_ids = [item.id for item in graph.assemblies]
    for label, values in (
        ("capability", capability_ids),
        ("route", [item.id for item in graph.routes]),
        ("exclusion", [item.id for item in graph.exclusions]),
        ("session shape", [item.id for item in graph.session_shapes]),
        ("assembly", assembly_ids),
        ("scenario", [item.id for item in graph.scenarios]),
        ("concern", [item.id for item in graph.concerns]),
        ("lineage", [item.id for item in graph.lineage]),
    ):
        for duplicate in sorted(_duplicates(values)):
            findings.append(Finding("duplicate-id", f"duplicate {label} id: {duplicate}"))

    capabilities = set(capability_ids)
    parents = {item.id: item.parent for item in graph.capabilities}
    for capability in graph.capabilities:
        if capability.parent is not None and capability.parent not in capabilities:
            findings.append(
                Finding(
                    "unknown-parent",
                    f"capability {capability.id} has unknown parent {capability.parent}",
                )
            )
        visited: set[str] = set()
        current: str | None = capability.id
        while current is not None and current in parents:
            if current in visited:
                findings.append(
                    Finding("capability-cycle", f"capability hierarchy cycles at {current}")
                )
                break
            visited.add(current)
            current = parents[current]

    for route in graph.routes:
        if route.capability not in capabilities:
            findings.append(
                Finding(
                    "unknown-capability",
                    f"route {route.id} names unknown capability {route.capability}",
                )
            )
        if not (route.match.kinds or route.match.paths or route.match.ids):
            findings.append(Finding("empty-match", f"route {route.id} matches everything"))
    for exclusion in graph.exclusions:
        if not (exclusion.match.kinds or exclusion.match.paths or exclusion.match.ids):
            findings.append(Finding("empty-match", f"exclusion {exclusion.id} matches everything"))

    assemblies = set(assembly_ids)
    for shape in graph.session_shapes:
        if shape.capability not in capabilities:
            findings.append(
                Finding(
                    "unknown-capability",
                    f"session shape {shape.id} names unknown capability {shape.capability}",
                )
            )
        if shape.assembly not in assemblies:
            findings.append(
                Finding(
                    "unknown-assembly",
                    f"session shape {shape.id} names unknown assembly {shape.assembly}",
                )
            )
    for scenario in graph.scenarios:
        if scenario.assembly not in assemblies:
            findings.append(
                Finding(
                    "unknown-assembly",
                    f"scenario {scenario.id} names unknown assembly {scenario.assembly}",
                )
            )
    for assembly in graph.assemblies:
        for index, layer in enumerate(assembly.layers, start=1):
            if (layer.unit is None) == (layer.boundary is None):
                findings.append(
                    Finding(
                        "invalid-layer",
                        f"assembly {assembly.id} layer {index} must name one unit or boundary",
                    )
                )
    return findings


def _validate_references(graph: ProseMap, candidate_ids: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for assembly in graph.assemblies:
        for layer in assembly.layers:
            if layer.unit is not None and layer.unit not in candidate_ids:
                findings.append(
                    Finding(
                        "unknown-unit",
                        f"assembly {assembly.id} names unknown unit {layer.unit}",
                    )
                )
    for concern in graph.concerns:
        if concern.canonical_unit not in candidate_ids:
            findings.append(
                Finding(
                    "unknown-unit",
                    f"concern {concern.id} names unknown canonical unit {concern.canonical_unit}",
                )
            )
        for related in concern.related:
            if related.unit not in candidate_ids:
                findings.append(
                    Finding(
                        "unknown-unit",
                        f"concern {concern.id} names unknown related unit {related.unit}",
                    )
                )
    for lineage in graph.lineage:
        if not any(fnmatchcase(candidate_id, lineage.source) for candidate_id in candidate_ids):
            findings.append(
                Finding(
                    "stale-lineage",
                    f"lineage {lineage.id} source matches no unit: {lineage.source}",
                )
            )
    return findings


type _TemplateMetadata = tuple[frozenset[str], tuple[str, ...]]


def _template_metadata(
    environment: Environment,
    template_name: str,
    cache: dict[str, _TemplateMetadata],
) -> _TemplateMetadata:
    cached = cache.get(template_name)
    if cached is not None:
        return cached
    loader = environment.loader
    if loader is None:
        raise _TemplateInspectionError("template environment has no loader")
    source, _, _ = loader.get_source(environment, template_name)
    parsed = environment.parse(source)
    references: list[str] = []
    for reference in meta.find_referenced_templates(parsed):
        if reference is None:
            raise _TemplateInspectionError(
                f"template {template_name} contains a dynamic template reference"
            )
        references.append(reference)
    result = (
        frozenset(meta.find_undeclared_variables(parsed)),
        tuple(references),
    )
    cache[template_name] = result
    return result


def _collect_template_variables(
    environment: Environment,
    template_name: str,
    cache: dict[str, _TemplateMetadata],
    visited: set[str],
) -> set[str]:
    if template_name in visited:
        return set()
    visited.add(template_name)
    variables, references = _template_metadata(environment, template_name, cache)
    result = set(variables)
    for reference in references:
        result.update(_collect_template_variables(environment, reference, cache, visited))
    return result


def _template_variables(
    environment: Environment,
    unit_id: str,
    template_name: str,
    cache: dict[str, _TemplateMetadata],
) -> set[str]:
    try:
        return _collect_template_variables(environment, template_name, cache, set())
    except (OSError, UnicodeError, TemplateError, _TemplateInspectionError) as exc:
        raise ProseMapError(
            f"cannot inspect prompt template {unit_id} ({template_name}): {exc}"
        ) from exc


def validate_scenario_fixtures(
    root: Path,
    graph: ProseMap,
    candidates: tuple[Candidate, ...],
) -> list[Finding]:
    """Validate scenarios against every static variable required by prompt layers."""
    assemblies = {assembly.id: assembly for assembly in graph.assemblies}
    previewable = {shape.assembly for shape in graph.session_shapes if shape.assembly in assemblies}
    scenarios: dict[str, list[Scenario]] = {}
    for scenario in graph.scenarios:
        scenarios.setdefault(scenario.assembly, []).append(scenario)

    findings: list[Finding] = []
    candidates_by_id = {candidate.id: candidate for candidate in candidates}
    environment = Environment(loader=FileSystemLoader(root / "prompts"))
    cache: dict[str, _TemplateMetadata] = {}
    prompt_root = Path("prompts")
    for assembly_id in sorted(previewable):
        assembly_scenarios = scenarios.get(assembly_id, [])
        if not assembly_scenarios:
            findings.append(
                Finding(
                    "missing-assembly-scenario",
                    f"previewable assembly {assembly_id} has no scenario",
                )
            )

        requirements: dict[str, set[str]] = {}
        for layer in assemblies[assembly_id].layers:
            if layer.unit is None:
                continue
            candidate = candidates_by_id.get(layer.unit)
            if candidate is None or candidate.kind != "markdown":
                continue
            candidate_path = Path(candidate.path)
            if candidate_path == prompt_root or not candidate_path.is_relative_to(prompt_root):
                continue
            template_name = candidate_path.relative_to(prompt_root).as_posix()
            requirements[candidate.id] = _template_variables(
                environment,
                candidate.id,
                template_name,
                cache,
            )

        for scenario in assembly_scenarios:
            supplied = {name for name, _ in scenario.variables}
            for unit_id, required in requirements.items():
                missing = sorted(required - supplied)
                if missing:
                    findings.append(
                        Finding(
                            "missing-scenario-variable",
                            f"scenario {scenario.id} is missing variables for {unit_id}: "
                            f"{', '.join(missing)}",
                        )
                    )
    return findings


def validate_tool_field_governance(issues: tuple[ToolFieldIssue, ...]) -> list[Finding]:
    """Convert registered-tool field discovery issues into checker findings."""
    findings: list[Finding] = []
    for issue in issues:
        if isinstance(issue, UnclassifiedToolFieldIssue):
            findings.append(
                Finding(
                    "unclassified-tool-field",
                    f"governed tool {issue.tool} has unclassified registered-tool field "
                    f"{issue.field} at {issue.path} ({issue.selector}); add a model-facing "
                    "collector or a reasoned non-prose policy entry",
                )
            )
            continue
        findings.append(
            Finding(
                "opaque-tool-contract",
                f"governed tool {issue.tool} has opaque registered-tool member at "
                f"{issue.path} ({issue.selector}): {issue.reason}; replace it with "
                "statically named fields",
            )
        )
    return findings


def build_catalog(root: Path) -> Catalog:
    """Join discovered prose with the authored semantic overlay and validate the result."""
    graph = load_graph(root)
    try:
        discovery = discover(root)
    except DiscoveryError as exc:
        raise ProseMapError(str(exc)) from exc
    candidates = discovery.candidates
    governed_tools = discovery.governed_tools
    findings = validate_tool_field_governance(discovery.tool_field_issues)
    findings.extend(validate_graph(graph))
    candidate_ids = [candidate.id for candidate in candidates]
    for duplicate in sorted(_duplicates(candidate_ids)):
        findings.append(Finding("duplicate-unit", f"duplicate discovered unit id: {duplicate}"))
    candidate_id_set = set(candidate_ids)
    findings.extend(_validate_references(graph, candidate_id_set))
    findings.extend(validate_scenario_fixtures(root, graph, candidates))

    units: list[RoutedUnit] = []
    excluded: list[Candidate] = []
    exclusion_hits = dict.fromkeys((item.id for item in graph.exclusions), 0)
    route_hits = dict.fromkeys((item.id for item in graph.routes), 0)
    for candidate in candidates:
        exclusions = [item for item in graph.exclusions if _match(item.match, candidate)]
        if exclusions:
            excluded.append(candidate)
            for exclusion in exclusions:
                exclusion_hits[exclusion.id] += 1
            continue
        matches = [item for item in graph.routes if _match(item.match, candidate)]
        if not matches:
            findings.append(
                Finding("unmapped-unit", f"no semantic route for {candidate.id} ({candidate.path})")
            )
            continue
        priority = max(item.priority for item in matches)
        winners = [item for item in matches if item.priority == priority]
        if len(winners) != 1:
            route_ids = ", ".join(item.id for item in winners)
            findings.append(
                Finding(
                    "ambiguous-route",
                    f"{candidate.id} ties at priority {priority}: {route_ids}",
                )
            )
            continue
        route = winners[0]
        route_hits[route.id] += 1
        units.append(
            RoutedUnit(
                candidate=candidate,
                capability=route.capability,
                audience=route.audience,
                role=route.role,
            )
        )

    for exclusion_id, count in exclusion_hits.items():
        if count == 0:
            findings.append(
                Finding("stale-exclusion", f"exclusion {exclusion_id} matches no candidate")
            )
    for route_id, count in route_hits.items():
        if count == 0:
            findings.append(Finding("stale-route", f"route {route_id} maps no candidate"))

    discovered_tools = {
        candidate.id.removeprefix("typescript-tool:")
        for candidate in candidates
        if candidate.kind == "typescript-tool"
    }
    governed_set = set(governed_tools)
    for name in sorted(governed_set - discovered_tools):
        findings.append(
            Finding("missing-tool-contract", f"PERK_TOOLS tool has no discovered contract: {name}")
        )
    for name in sorted(discovered_tools - governed_set):
        findings.append(
            Finding(
                "ungoverned-tool-contract", f"registered tool is absent from PERK_TOOLS: {name}"
            )
        )

    return Catalog(
        graph=graph,
        units=tuple(sorted(units, key=lambda unit: unit.candidate.id)),
        excluded=tuple(sorted(excluded, key=lambda candidate: candidate.id)),
        findings=tuple(sorted(findings, key=lambda finding: (finding.code, finding.message))),
        governed_tools=tuple(sorted(governed_tools)),
    )


def build(root: Path) -> BuildResult:
    """Build the validated catalog and its deterministic Markdown projection."""
    catalog = build_catalog(root)
    return BuildResult(catalog=catalog, rendered=render_markdown(catalog))
