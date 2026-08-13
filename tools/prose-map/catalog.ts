/** Structural discovery of perk-owned TypeScript prose that can shape a model turn. */

import path from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";

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

export interface TypeScriptCatalog {
  candidates: DiscoveredCandidate[];
  governed_tools: string[];
}

function propertyName(node: ts.ObjectLiteralElementLike): string | null {
  if (!ts.isPropertyAssignment(node) && !ts.isShorthandPropertyAssignment(node)) {
    return null;
  }
  const name = node.name;
  if (ts.isIdentifier(name) || ts.isStringLiteral(name) || ts.isNumericLiteral(name)) {
    return name.text;
  }
  return null;
}

function property(
  object: ts.ObjectLiteralExpression,
  name: string,
): ts.ObjectLiteralElementLike | null {
  return object.properties.find((candidate) => propertyName(candidate) === name) ?? null;
}

function initializer(node: ts.ObjectLiteralElementLike): ts.Expression | null {
  if (ts.isPropertyAssignment(node)) {
    return node.initializer;
  }
  if (ts.isShorthandPropertyAssignment(node)) {
    return node.name;
  }
  return null;
}

function staticString(node: ts.Expression | null): string | null {
  if (node !== null && (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node))) {
    return node.text;
  }
  return null;
}

function toolFragments(object: ts.ObjectLiteralExpression, toolName: string): DiscoveredFragment[] {
  const fragments: DiscoveredFragment[] = [];
  for (const field of ["description", "promptSnippet", "promptGuidelines"] as const) {
    const member = property(object, field);
    if (member === null) {
      continue;
    }
    const value = initializer(member);
    if (value !== null && ts.isArrayLiteralExpression(value)) {
      value.elements.forEach((_element, index) => {
        fragments.push({
          id: `${field}.${index}`,
          label: `${field} item ${index + 1}`,
          selector: `tool:${toolName}.${field}.${index}`,
        });
      });
    } else {
      fragments.push({
        id: field,
        label: field,
        selector: `tool:${toolName}.${field}`,
      });
    }
  }

  const parameters = property(object, "parameters");
  const parametersValue = parameters === null ? null : initializer(parameters);
  if (parametersValue !== null) {
    collectDescriptions(parametersValue, "parameters", toolName, fragments);
  }
  return fragments;
}

function collectDescriptions(
  node: ts.Node,
  fieldPath: string,
  toolName: string,
  fragments: DiscoveredFragment[],
): void {
  if (ts.isObjectLiteralExpression(node)) {
    for (const child of node.properties) {
      const name = propertyName(child);
      if (name === null) {
        continue;
      }
      const childPath = `${fieldPath}.${name}`;
      const value = initializer(child);
      if (name === "description" && value !== null) {
        fragments.push({
          id: childPath,
          label: childPath,
          selector: `tool:${toolName}.${childPath}`,
        });
      }
      if (value !== null) {
        collectDescriptions(value, childPath, toolName, fragments);
      }
    }
  } else if (ts.isArrayLiteralExpression(node)) {
    node.elements.forEach((child, index) => {
      collectDescriptions(child, `${fieldPath}.${index}`, toolName, fragments);
    });
  }
}

function enclosingSymbol(node: ts.Node): string {
  let current: ts.Node | undefined = node;
  while (current !== undefined) {
    if (
      (ts.isFunctionDeclaration(current) || ts.isClassDeclaration(current)) &&
      current.name !== undefined
    ) {
      return current.name.text;
    }
    if (ts.isMethodDeclaration(current) && current.name !== undefined) {
      return current.name.getText();
    }
    if (ts.isVariableDeclaration(current) && ts.isIdentifier(current.name)) {
      return current.name.text;
    }
    current = current.parent;
  }
  return "module";
}

function normalizedPath(root: string, fileName: string): string {
  return path.relative(root, fileName).split(path.sep).join("/");
}

function scanSource(
  root: string,
  sourceFile: ts.SourceFile,
  ordinals: Map<string, number>,
): DiscoveredCandidate[] {
  const candidates: DiscoveredCandidate[] = [];
  const sourcePath = normalizedPath(root, sourceFile.fileName);

  function nextOrdinal(key: string): number {
    const ordinal = ordinals.get(key) ?? 0;
    ordinals.set(key, ordinal + 1);
    return ordinal;
  }

  function visit(node: ts.Node): void {
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      node.expression.name.text === "registerTool"
    ) {
      const argument = node.arguments[0];
      if (argument !== undefined && ts.isObjectLiteralExpression(argument)) {
        const nameMember = property(argument, "name");
        const name = nameMember === null ? null : staticString(initializer(nameMember));
        if (name !== null) {
          const fragments = toolFragments(argument, name);
          if (fragments.length > 0) {
            candidates.push({
              id: `typescript-tool:${name}`,
              kind: "typescript-tool",
              path: sourcePath,
              selector: `tool:${name}`,
              fragments,
            });
          }
        }
      }
    }

    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
      const method = node.expression.name.text;
      const receiver = node.expression.expression.getText(sourceFile);
      const modelCall =
        method === "sendUserMessage" ||
        method === "complete" ||
        (method === "prompt" && receiver.endsWith("session"));
      if (modelCall && node.arguments.length > 0) {
        const symbol = enclosingSymbol(node);
        const key = `${sourcePath}:${symbol}:${method}`;
        const ordinal = nextOrdinal(key);
        candidates.push({
          id: `typescript-model-call:${sourcePath}:${symbol}:${method}:${ordinal}`,
          kind: "typescript-model-call",
          path: sourcePath,
          selector: `symbol:${symbol}/call:${method}/${ordinal}`,
          fragments: [
            {
              id: "argument:0",
              label: `${method} model-facing argument`,
              selector: `symbol:${symbol}/call:${method}/${ordinal}/argument:0`,
            },
          ],
        });
      }
    }

    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === "completeStructured"
    ) {
      const options = node.arguments[0];
      if (options !== undefined && ts.isObjectLiteralExpression(options)) {
        const symbol = enclosingSymbol(node);
        const fields = ["toolDescription", "system", "instruction", "schema"]
          .map((field) => property(options, field))
          .filter((member): member is ts.ObjectLiteralElementLike => member !== null)
          .map((member) => {
            const field = propertyName(member) ?? "field";
            return {
              id: field,
              label: `completeStructured ${field}`,
              selector: `symbol:${symbol}/call:completeStructured/${field}`,
            };
          });
        if (fields.length > 0) {
          candidates.push({
            id: `typescript-symbol:${sourcePath}:${symbol}:complete-structured`,
            kind: "typescript-symbol",
            path: sourcePath,
            selector: `symbol:${symbol}/call:completeStructured`,
            fragments: fields,
          });
        }
      }
    }

    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
      const event =
        node.expression.name.text === "on" ? staticString(node.arguments[0] ?? null) : null;
      if (event === "before_agent_start") {
        const symbol = enclosingSymbol(node);
        const key = `${sourcePath}:${symbol}:before-agent-start`;
        const ordinal = nextOrdinal(key);
        candidates.push({
          id: `typescript-model-call:${sourcePath}:${symbol}:before-agent-start:${ordinal}`,
          kind: "typescript-model-call",
          path: sourcePath,
          selector: `symbol:${symbol}/event:before_agent_start/${ordinal}`,
          fragments: [
            {
              id: "handler",
              label: "before_agent_start injected context",
              selector: `symbol:${symbol}/event:before_agent_start/${ordinal}/handler`,
            },
          ],
        });
      }
    }

    if (ts.isPropertyAssignment(node) && propertyName(node) === "workflowScript") {
      const symbol = enclosingSymbol(node);
      const key = `${sourcePath}:${symbol}:workflow-script`;
      const ordinal = nextOrdinal(key);
      candidates.push({
        id: `typescript-model-call:${sourcePath}:${symbol}:workflow-script:${ordinal}`,
        kind: "typescript-model-call",
        path: sourcePath,
        selector: `symbol:${symbol}/property:workflowScript/${ordinal}`,
        fragments: [
          {
            id: "workflowScript",
            label: "Subagent workflow script",
            selector: `symbol:${symbol}/property:workflowScript/${ordinal}`,
          },
        ],
      });
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return candidates;
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
  const candidates = program
    .getSourceFiles()
    .filter(
      (sourceFile) =>
        !sourceFile.isDeclarationFile && sourceFile.fileName.startsWith(extensionRoot),
    )
    .flatMap((sourceFile) => scanSource(root, sourceFile, ordinals))
    .sort((left, right) => left.id.localeCompare(right.id));
  return { candidates, governed_tools: governedTools(program) };
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
