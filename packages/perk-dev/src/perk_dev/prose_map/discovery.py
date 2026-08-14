"""Discover stable logical prose units from perk's canonical source tree."""

import ast
import json
import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from perk.substrate.proc import ProcFailure, run_checked
from perk_dev.prose_map.models import (
    Candidate,
    DiscoveredCandidateInput,
    DiscoveredOpaqueToolFieldInput,
    DiscoveredToolFieldInput,
    DiscoveryResult,
    Fragment,
    OpaqueToolFieldIssue,
    ToolFieldIssue,
    TypeScriptCatalogInput,
    UnclassifiedToolFieldIssue,
)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_TYPESCRIPT_SCAN_TIMEOUT_S = 60
_PYTHON_PROSE_MARKERS = (
    "<stacked_layer_context>",
    "<untrusted_",
    "instructions to obey",
    "never as instructions",
    "treat every line as data",
)
_PYTHON_SOURCE_ROOTS = ("src/perk", "packages/perk-dev/src/perk_dev")


class DiscoveryError(Exception):
    """A source catalog could not be discovered reliably."""


def _slug(value: str) -> str:
    return _SLUG_RE.sub("-", value.lower()).strip("-") or "section"


def _markdown_fragments(path: Path) -> tuple[Fragment, ...]:
    text = path.read_text(encoding="utf-8")
    fragments: list[Fragment] = []
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end >= 0:
            raw_frontmatter = yaml.safe_load(text[4:end])
            if isinstance(raw_frontmatter, dict):
                description = raw_frontmatter.get("description")
                if isinstance(description, str) and description.strip():
                    fragments.append(
                        Fragment(
                            id="frontmatter:description",
                            label="Discovery description",
                            selector="frontmatter.description",
                        )
                    )
            body = text[end + 5 :]

    stack: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    for line in body.splitlines():
        match = _HEADING_RE.match(line)
        if match is None:
            continue
        level = len(match.group(1))
        label = match.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, _slug(label)))
        base = "/".join(part for _, part in stack)
        seen[base] = seen.get(base, 0) + 1
        suffix = "" if seen[base] == 1 else f"~{seen[base]}"
        fragments.append(
            Fragment(
                id=f"section:{base}{suffix}",
                label=label,
                selector=f"heading:{base}{suffix}",
            )
        )

    if not fragments:
        fragments.append(Fragment(id="body", label="Document body", selector="file-body"))
    return tuple(fragments)


def _markdown_candidates(root: Path) -> list[Candidate]:
    candidates: list[Candidate] = []
    for directory in ("prompts", "skills", "agents"):
        for path in sorted((root / directory).rglob("*.md")):
            relative = path.relative_to(root).as_posix()
            candidates.append(
                Candidate(
                    id=f"markdown:{relative}",
                    kind="markdown",
                    path=relative,
                    selector="file",
                    fragments=_markdown_fragments(path),
                )
            )
    return candidates


def _python_symbols(tree: ast.Module) -> list[ast.AST]:
    return [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign, ast.AnnAssign))
    ]


def _symbol_name(node: ast.AST) -> str | None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name
    if isinstance(node, ast.Assign):
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        return names[0] if len(names) == 1 else None
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def _without_docstring(node: ast.AST) -> list[ast.AST]:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return [node]
    body = node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return list(body)


def _owned_strings(node: ast.AST) -> tuple[str, ...]:
    """Return string literals owned by a symbol, excluding docstrings and nested symbols."""
    values: list[str] = []

    def visit(current: ast.AST) -> None:
        if current is not node and isinstance(
            current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            return
        if isinstance(current, ast.Constant) and isinstance(current.value, str):
            values.append(current.value)
            return
        for child in ast.iter_child_nodes(current):
            visit(child)

    for child in _without_docstring(node):
        visit(child)
    return tuple(values)


def _parse_python(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise DiscoveryError(f"Python prose discovery could not parse {path}: {exc}") from exc


def _require_python_symbol(root: Path, relative: str, name: str) -> None:
    path = root / relative
    matches = [node for node in _python_symbols(_parse_python(path)) if _symbol_name(node) == name]
    if len(matches) != 1:
        raise DiscoveryError(
            f"Python prose selector {relative}::symbol:{name} resolved {len(matches)} times"
        )


def _python_candidates(root: Path) -> list[Candidate]:
    candidates: list[Candidate] = []
    for source_root in _PYTHON_SOURCE_ROOTS:
        for path in sorted((root / source_root).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            for node in _python_symbols(_parse_python(path)):
                name = _symbol_name(node)
                if name is None:
                    continue
                strings = _owned_strings(node)
                if not any(
                    len(value.strip()) >= 40
                    and any(marker in value.lower() for marker in _PYTHON_PROSE_MARKERS)
                    for value in strings
                ):
                    continue
                selector = f"symbol:{name}"
                candidates.append(
                    Candidate(
                        id=f"python-symbol:{relative}:{name}",
                        kind="python-symbol",
                        path=relative,
                        selector=selector,
                        fragments=(
                            Fragment(
                                id=selector,
                                label=name.removeprefix("_").replace("_", " ").capitalize(),
                                selector=selector,
                            ),
                        ),
                    )
                )
    return candidates


def _managed_candidates(root: Path) -> list[Candidate]:
    agents_path = root / "AGENTS.md"
    repo_fragments = _markdown_fragments(agents_path)
    developing_fragment = next(
        (
            fragment
            for fragment in repo_fragments
            if fragment.selector == "heading:agents/developing-perk"
        ),
        None,
    )
    if developing_fragment is None:
        raise DiscoveryError(
            "managed AGENTS prose selector heading:agents/developing-perk did not resolve"
        )
    _require_python_symbol(root, "src/perk/convergence/init/blocks.py", "_agents_inner")
    _require_python_symbol(root, "src/perk/cli/commands/skills/shared.py", "todo_skill_md")
    candidates = [
        Candidate(
            id="managed:repo-agents",
            kind="managed-prose",
            path="AGENTS.md",
            selector="heading:agents/developing-perk",
            fragments=(developing_fragment,),
        ),
        Candidate(
            id="managed:downstream-agents",
            kind="managed-prose",
            path="src/perk/convergence/init/blocks.py",
            selector="symbol:_agents_inner",
            fragments=(
                Fragment(
                    id="symbol:_agents_inner",
                    label="Managed downstream AGENTS instructions",
                    selector="symbol:_agents_inner",
                ),
            ),
        ),
        Candidate(
            id="managed:skill-scaffold",
            kind="managed-prose",
            path="src/perk/cli/commands/skills/shared.py",
            selector="symbol:todo_skill_md",
            fragments=(
                Fragment(
                    id="symbol:todo_skill_md",
                    label="Repository skill scaffold",
                    selector="symbol:todo_skill_md",
                ),
            ),
        ),
    ]
    clusters_path = root / "docs/learned/clusters.yaml"
    raw_clusters = yaml.safe_load(clusters_path.read_text(encoding="utf-8"))
    cluster_fragments: list[Fragment] = []
    if isinstance(raw_clusters, dict) and isinstance(raw_clusters.get("clusters"), list):
        for raw_cluster in raw_clusters["clusters"]:
            if isinstance(raw_cluster, dict) and isinstance(raw_cluster.get("id"), str):
                cluster_id = raw_cluster["id"]
                cluster_fragments.append(
                    Fragment(
                        id=f"cluster:{cluster_id}",
                        label=f"{cluster_id} routing cue",
                        selector=f"clusters.{cluster_id}.rollup",
                    )
                )
    if not cluster_fragments:
        cluster_fragments.append(
            Fragment(id="clusters", label="Learned routing clusters", selector="clusters")
        )
    candidates.append(
        Candidate(
            id="ambient:learned-routing",
            kind="ambient-routing",
            path="docs/learned/clusters.yaml",
            selector="clusters.*.rollup",
            fragments=tuple(cluster_fragments),
        )
    )
    return candidates


def _from_discovered(value: DiscoveredCandidateInput) -> Candidate:
    return Candidate(
        id=value.id,
        kind=value.kind,
        path=value.path,
        selector=value.selector,
        fragments=tuple(
            Fragment(id=fragment.id, label=fragment.label, selector=fragment.selector)
            for fragment in value.fragments
        ),
    )


def _from_tool_field_issue(value: DiscoveredToolFieldInput) -> ToolFieldIssue:
    if isinstance(value, DiscoveredOpaqueToolFieldInput):
        return OpaqueToolFieldIssue(
            kind=value.kind,
            field=value.field,
            reason=value.reason,
            tool=value.tool,
            path=value.path,
            selector=value.selector,
        )
    return UnclassifiedToolFieldIssue(
        kind=value.kind,
        field=value.field,
        reason=value.reason,
        tool=value.tool,
        path=value.path,
        selector=value.selector,
    )


def _typescript_candidates(root: Path) -> DiscoveryResult:
    script = root / "tools/prose-map/catalog.ts"
    if not script.is_file():
        raise DiscoveryError(f"TypeScript prose scanner is missing: {script}")
    try:
        stdout = run_checked(
            ["node", str(script), str(root)],
            cwd=root,
            timeout=_TYPESCRIPT_SCAN_TIMEOUT_S,
        )
    except ProcFailure as exc:
        raise DiscoveryError(f"TypeScript prose discovery failed: {exc}") from exc
    try:
        raw: object = json.loads(stdout)
        catalog = TypeScriptCatalogInput.model_validate(raw)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise DiscoveryError(f"TypeScript prose discovery returned invalid JSON: {exc}") from exc
    return DiscoveryResult(
        candidates=tuple(_from_discovered(value) for value in catalog.candidates),
        governed_tools=tuple(catalog.governed_tools),
        tool_field_issues=tuple(
            _from_tool_field_issue(value) for value in catalog.tool_field_issues
        ),
    )


def discover(root: Path) -> DiscoveryResult:
    """Discover the complete production prose candidate catalog."""
    candidates = [
        *_markdown_candidates(root),
        *_python_candidates(root),
        *_managed_candidates(root),
    ]
    typescript = _typescript_candidates(root)
    candidates.extend(typescript.candidates)
    return DiscoveryResult(
        candidates=tuple(sorted(candidates, key=lambda candidate: candidate.id)),
        governed_tools=typescript.governed_tools,
        tool_field_issues=typescript.tool_field_issues,
    )
