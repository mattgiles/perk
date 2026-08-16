/** Structural discovery of perk-owned TypeScript prose that can shape a model turn. */

import path from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";

import { enumerateSelectorSites, type SelectorRecord } from "./selector.ts";

type ProseKind = "typescript-tool" | "typescript-model-call" | "typescript-symbol";

export interface DiscoveredFragment {
  id: string;
  label: string;
  selector: string;
}

export interface DiscoveredCandidate {
  id: string;
  kind: ProseKind;
  path: string;
  selector: string;
  fragments: DiscoveredFragment[];
}

export interface UnclassifiedToolFieldIssue {
  kind: "unclassified";
  field: string;
  reason: "unclassified-field";
  tool: string;
  path: string;
  selector: string;
}

export interface OpaqueToolFieldIssue {
  kind: "opaque";
  field: null;
  reason: "spread-assignment" | "dynamic-computed-property";
  tool: string;
  path: string;
  selector: string;
}

export type ToolFieldIssue = UnclassifiedToolFieldIssue | OpaqueToolFieldIssue;

export interface TypeScriptCatalog {
  candidates: DiscoveredCandidate[];
  governed_tools: string[];
  tool_field_issues: ToolFieldIssue[];
}

function staticString(node: ts.Expression | null): string | null {
  if (node !== null && (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node))) {
    return node.text;
  }
  return null;
}

function normalizedPath(root: string, fileName: string): string {
  return path.relative(root, fileName).split(path.sep).join("/");
}

interface SourceScanResult {
  candidates: DiscoveredCandidate[];
  toolFieldIssues: ToolFieldIssue[];
}

function uniqueFragments(
  fragments: ReadonlyArray<{
    id: string;
    label: string;
    site: { catalogSelector: string };
  }>,
): DiscoveredFragment[] {
  const seen = new Set<string>();
  const result: DiscoveredFragment[] = [];
  for (const fragment of fragments) {
    if (seen.has(fragment.site.catalogSelector)) {
      continue;
    }
    seen.add(fragment.site.catalogSelector);
    result.push({
      id: fragment.id,
      label: fragment.label,
      selector: fragment.site.catalogSelector,
    });
  }
  return result;
}

function recordCandidate(record: SelectorRecord, sourcePath: string): DiscoveredCandidate | null {
  if (record.kind === "tool-registration") {
    const fragments = uniqueFragments(record.fragments);
    if (fragments.length === 0) {
      return null;
    }
    return {
      id: `typescript-tool:${record.name}`,
      kind: "typescript-tool",
      path: sourcePath,
      selector: `tool:${record.name}`,
      fragments,
    };
  }
  if (record.kind === "model-call") {
    return {
      id: `typescript-model-call:${sourcePath}:${record.catalogOwner}:${record.method}:${record.catalogOrdinal}`,
      kind: "typescript-model-call",
      path: sourcePath,
      selector: `symbol:${record.catalogOwner}/call:${record.method}/${record.catalogOrdinal}`,
      fragments: [
        {
          id: "argument:0",
          label: `${record.method} model-facing argument`,
          selector: record.site.catalogSelector,
        },
      ],
    };
  }
  if (record.kind === "complete-structured") {
    const fragments = uniqueFragments(record.fields);
    if (fragments.length === 0) {
      return null;
    }
    return {
      id: `typescript-symbol:${sourcePath}:${record.catalogOwner}:complete-structured`,
      kind: "typescript-symbol",
      path: sourcePath,
      selector: `symbol:${record.catalogOwner}/call:completeStructured`,
      fragments,
    };
  }
  if (record.kind === "event-handler") {
    return {
      id: `typescript-model-call:${sourcePath}:${record.catalogOwner}:before-agent-start:${record.catalogOrdinal}`,
      kind: "typescript-model-call",
      path: sourcePath,
      selector: `symbol:${record.catalogOwner}/event:before_agent_start/${record.catalogOrdinal}`,
      fragments: [
        {
          id: "handler",
          label: "before_agent_start injected context",
          selector: record.site.catalogSelector,
        },
      ],
    };
  }
  return {
    id: `typescript-model-call:${sourcePath}:${record.catalogOwner}:workflow-script:${record.catalogOrdinal}`,
    kind: "typescript-model-call",
    path: sourcePath,
    selector: record.site.catalogSelector,
    fragments: [
      {
        id: "workflowScript",
        label: "Subagent workflow script",
        selector: record.site.catalogSelector,
      },
    ],
  };
}

function scanSource(
  root: string,
  sourceFile: ts.SourceFile,
  ordinals: Map<string, number>,
): SourceScanResult {
  const sourcePath = normalizedPath(root, sourceFile.fileName);
  const enumeration = enumerateSelectorSites(sourceFile, sourcePath, ordinals);
  const candidates = enumeration.records
    .map((record) => recordCandidate(record, sourcePath))
    .filter((candidate): candidate is DiscoveredCandidate => candidate !== null);
  const toolFieldIssues = enumeration.records.flatMap((record): ToolFieldIssue[] => {
    if (record.kind !== "tool-registration") {
      return [];
    }
    return record.issues.map((issue) => ({
      ...issue,
      tool: record.name,
      path: sourcePath,
    }));
  });
  return { candidates, toolFieldIssues };
}

function governedTools(program: ts.Program): string[] {
  const names: string[] = [];
  for (const sourceFile of program.getSourceFiles()) {
    if (sourceFile.isDeclarationFile) {
      continue;
    }
    function visit(node: ts.Node): void {
      if (
        ts.isVariableDeclaration(node) &&
        ts.isIdentifier(node.name) &&
        node.name.text === "PERK_TOOLS" &&
        node.initializer !== undefined &&
        ts.isArrayLiteralExpression(node.initializer)
      ) {
        for (const element of node.initializer.elements) {
          const value = staticString(element);
          if (value !== null) {
            names.push(value);
          }
        }
      }
      ts.forEachChild(node, visit);
    }
    visit(sourceFile);
  }
  return [...new Set(names)].sort();
}

export function scanRepository(root: string): TypeScriptCatalog {
  const extensionRoot = path.join(root, "extension");
  const files = ts.sys.readDirectory(
    extensionRoot,
    [".ts"],
    ["**/*.test.ts", "**/testing/**", "**/vendor/**"],
  );
  const program = ts.createProgram(files, {
    allowImportingTsExtensions: true,
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    noEmit: true,
    target: ts.ScriptTarget.ES2022,
  });
  const ordinals = new Map<string, number>();
  const sourceScans = program
    .getSourceFiles()
    .filter(
      (sourceFile) =>
        !sourceFile.isDeclarationFile && sourceFile.fileName.startsWith(extensionRoot),
    )
    .map((sourceFile) => scanSource(root, sourceFile, ordinals));
  const candidates = sourceScans
    .flatMap((result) => result.candidates)
    .sort((left, right) => left.id.localeCompare(right.id));
  const governed_tools = governedTools(program);
  const governedSet = new Set(governed_tools);
  const tool_field_issues = sourceScans
    .flatMap((result) => result.toolFieldIssues)
    .filter((issue) => governedSet.has(issue.tool))
    .sort((left, right) => {
      const leftKey = [left.path, left.tool, left.selector, left.kind, left.reason];
      const rightKey = [right.path, right.tool, right.selector, right.kind, right.reason];
      for (let index = 0; index < leftKey.length; index += 1) {
        const leftValue = leftKey[index] ?? "";
        const rightValue = rightKey[index] ?? "";
        if (leftValue < rightValue) {
          return -1;
        }
        if (leftValue > rightValue) {
          return 1;
        }
      }
      return 0;
    });
  return { candidates, governed_tools, tool_field_issues };
}

const entrypoint = process.argv[1];
if (entrypoint !== undefined && import.meta.url === pathToFileURL(entrypoint).href) {
  const root = process.argv[2];
  if (root === undefined) {
    process.stderr.write("usage: node tools/prose-map/catalog.ts <repo-root>\n");
    process.exitCode = 2;
  } else {
    process.stdout.write(`${JSON.stringify(scanRepository(path.resolve(root)))}\n`);
  }
}
