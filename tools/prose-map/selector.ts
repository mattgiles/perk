/** Shared TypeScript selector enumeration, exact range resolution, and CLI protocol. */

import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import type { ToolDefinition } from "@earendil-works/pi-coding-agent";
import ts from "typescript";

export type ToolFieldPolicy =
  | {
      kind: "model-facing-prose";
      collector: "field" | "array-items-or-field";
    }
  | { kind: "parameter-schema" }
  | { kind: "non-prose"; reason: string };

export const TOOL_FIELD_POLICIES = {
  name: {
    kind: "non-prose",
    reason: "represented by the registered-tool candidate id and selector",
  },
  label: { kind: "non-prose", reason: "human UI label only" },
  description: { kind: "model-facing-prose", collector: "field" },
  promptSnippet: { kind: "model-facing-prose", collector: "field" },
  promptGuidelines: {
    kind: "model-facing-prose",
    collector: "array-items-or-field",
  },
  parameters: { kind: "parameter-schema" },
  constrainedSampling: {
    kind: "non-prose",
    reason: "provider sampling behavior, not model-facing prose",
  },
  renderShell: { kind: "non-prose", reason: "human UI rendering only" },
  prepareArguments: {
    kind: "non-prose",
    reason: "runtime argument preparation, not model-facing prose",
  },
  executionMode: {
    kind: "non-prose",
    reason: "runtime execution configuration, not model-facing prose",
  },
  execute: { kind: "non-prose", reason: "runtime implementation, not model-facing prose" },
  renderCall: { kind: "non-prose", reason: "human UI rendering only" },
  renderResult: { kind: "non-prose", reason: "human UI rendering only" },
} satisfies Readonly<Record<keyof ToolDefinition, ToolFieldPolicy>>;

export function validateToolFieldPolicies(
  policies: Readonly<Record<string, ToolFieldPolicy>> = TOOL_FIELD_POLICIES,
): void {
  for (const [field, policy] of Object.entries(policies)) {
    if (policy.kind === "non-prose" && policy.reason.trim().length === 0) {
      throw new Error(`tool field policy ${field} has a blank non-prose reason`);
    }
  }
}

validateToolFieldPolicies();

export interface SelectorSite {
  /** Parent-linked helper identity plus the parentless Program-discovery identity. */
  selector: string;
  catalogSelector: string;
  location: ts.Node;
  target: ts.Expression | null;
  targetKind: "prose-expression" | "event-handler";
}

export interface ToolFragmentSite {
  id: string;
  label: string;
  site: SelectorSite;
}

export type ToolFieldIssueSite =
  | {
      kind: "unclassified";
      field: string;
      reason: "unclassified-field";
      selector: string;
    }
  | {
      kind: "opaque";
      field: null;
      reason: "spread-assignment" | "dynamic-computed-property";
      selector: string;
    };

export type SelectorRecord =
  | {
      kind: "tool-registration";
      name: string;
      fragments: ToolFragmentSite[];
      issues: ToolFieldIssueSite[];
    }
  | {
      kind: "model-call";
      owner: string;
      catalogOwner: string;
      method: "sendUserMessage" | "complete" | "prompt";
      ordinal: number;
      catalogOrdinal: number;
      site: SelectorSite;
    }
  | {
      kind: "complete-structured";
      owner: string;
      catalogOwner: string;
      fields: ToolFragmentSite[];
    }
  | {
      kind: "event-handler";
      owner: string;
      catalogOwner: string;
      ordinal: number;
      catalogOrdinal: number;
      site: SelectorSite;
    }
  | {
      kind: "workflow-property";
      owner: string;
      catalogOwner: string;
      ordinal: number;
      catalogOrdinal: number;
      site: SelectorSite;
    };

export interface SelectorEnumeration {
  records: SelectorRecord[];
  sites: SelectorSite[];
}

export function staticPropertyName(name: ts.PropertyName): string | null {
  if (ts.isIdentifier(name) || ts.isStringLiteral(name) || ts.isNumericLiteral(name)) {
    return name.text;
  }
  if (ts.isComputedPropertyName(name)) {
    const expression = name.expression;
    if (
      ts.isStringLiteral(expression) ||
      ts.isNumericLiteral(expression) ||
      ts.isNoSubstitutionTemplateLiteral(expression)
    ) {
      return expression.text;
    }
  }
  return null;
}

export function propertyName(node: ts.ObjectLiteralElementLike): string | null {
  if (ts.isSpreadAssignment(node)) {
    return null;
  }
  return staticPropertyName(node.name);
}

function properties(
  object: ts.ObjectLiteralExpression,
  name: string,
): ts.ObjectLiteralElementLike[] {
  return object.properties.filter((candidate) => propertyName(candidate) === name);
}

function firstProperty(
  object: ts.ObjectLiteralExpression,
  name: string,
): ts.ObjectLiteralElementLike | null {
  return properties(object, name)[0] ?? null;
}

export function propertyInitializer(node: ts.ObjectLiteralElementLike): ts.Expression | null {
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

function toolFieldPolicy(field: string): ToolFieldPolicy | undefined {
  if (!Object.hasOwn(TOOL_FIELD_POLICIES, field)) {
    return undefined;
  }
  return TOOL_FIELD_POLICIES[field as keyof typeof TOOL_FIELD_POLICIES];
}

function toolFieldIssues(
  object: ts.ObjectLiteralExpression,
  toolName: string,
): ToolFieldIssueSite[] {
  const issues: ToolFieldIssueSite[] = [];
  object.properties.forEach((member, index) => {
    const selector = `tool:${toolName}/member:${index}`;
    if (ts.isSpreadAssignment(member)) {
      issues.push({
        kind: "opaque",
        field: null,
        reason: "spread-assignment",
        selector,
      });
      return;
    }
    const field = propertyName(member);
    if (field === null) {
      issues.push({
        kind: "opaque",
        field: null,
        reason: "dynamic-computed-property",
        selector,
      });
      return;
    }
    if (toolFieldPolicy(field) === undefined) {
      issues.push({
        kind: "unclassified",
        field,
        reason: "unclassified-field",
        selector: `tool:${toolName}.${field}`,
      });
    }
  });
  return issues;
}

function expressionSite(
  selector: string,
  location: ts.Node,
  target: ts.Expression | null,
  targetKind: SelectorSite["targetKind"] = "prose-expression",
  catalogSelector: string = selector,
): SelectorSite {
  return { selector, catalogSelector, location, target, targetKind };
}

function collectDescriptions(
  node: ts.Node,
  fieldPath: string,
  toolName: string,
  fragments: ToolFragmentSite[],
): void {
  if (ts.isObjectLiteralExpression(node)) {
    for (const child of node.properties) {
      const name = propertyName(child);
      if (name === null) {
        continue;
      }
      const childPath = `${fieldPath}.${name}`;
      const value = propertyInitializer(child);
      if (name === "description") {
        fragments.push({
          id: childPath,
          label: childPath,
          site: expressionSite(`tool:${toolName}.${childPath}`, child, value),
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

function toolFragments(object: ts.ObjectLiteralExpression, toolName: string): ToolFragmentSite[] {
  const fragments: ToolFragmentSite[] = [];
  for (const [field, policy] of Object.entries(TOOL_FIELD_POLICIES)) {
    if (policy.kind === "non-prose") {
      continue;
    }
    for (const member of properties(object, field)) {
      const value = propertyInitializer(member);
      if (policy.kind === "parameter-schema") {
        if (value !== null) {
          collectDescriptions(value, field, toolName, fragments);
        }
        continue;
      }
      if (
        policy.collector === "array-items-or-field" &&
        value !== null &&
        ts.isArrayLiteralExpression(value)
      ) {
        value.elements.forEach((element, index) => {
          fragments.push({
            id: `${field}.${index}`,
            label: `${field} item ${index + 1}`,
            site: expressionSite(`tool:${toolName}.${field}.${index}`, element, element),
          });
        });
        continue;
      }
      fragments.push({
        id: field,
        label: field,
        site: expressionSite(`tool:${toolName}.${field}`, member, value),
      });
    }
  }
  return fragments;
}

export function enclosingSymbol(node: ts.Node): string {
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

/** Enumerate every discovery-authored selector site once in depth-first source order. */
export function enumerateSelectorSites(
  sourceFile: ts.SourceFile,
  sourceIdentity: string = sourceFile.fileName,
  ordinals: Map<string, number> = new Map<string, number>(),
): SelectorEnumeration {
  const records: SelectorRecord[] = [];
  const sites: SelectorSite[] = [];
  const ownerOrdinals = new Map<string, number>();

  function nextOrdinal(key: string, values: Map<string, number> = ordinals): number {
    const ordinal = values.get(key) ?? 0;
    values.set(key, ordinal + 1);
    return ordinal;
  }

  function addRecord(record: SelectorRecord, recordSites: SelectorSite[]): void {
    records.push(record);
    sites.push(...recordSites);
  }

  function visit(node: ts.Node): void {
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      node.expression.name.text === "registerTool"
    ) {
      const argument = node.arguments[0];
      if (argument !== undefined && ts.isObjectLiteralExpression(argument)) {
        const nameMember = firstProperty(argument, "name");
        const name = nameMember === null ? null : staticString(propertyInitializer(nameMember));
        if (name !== null) {
          const fragments = toolFragments(argument, name);
          addRecord(
            {
              kind: "tool-registration",
              name,
              fragments,
              issues: toolFieldIssues(argument, name),
            },
            fragments.map((fragment) => fragment.site),
          );
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
      const argument = node.arguments[0];
      if (modelCall && argument !== undefined) {
        const owner = enclosingSymbol(node);
        const catalogOwner = "module";
        const ordinal = nextOrdinal(`${sourceIdentity}:${owner}:${method}`, ownerOrdinals);
        const catalogOrdinal = nextOrdinal(`${sourceIdentity}:${catalogOwner}:${method}`);
        const typedMethod = method as "sendUserMessage" | "complete" | "prompt";
        const site = expressionSite(
          `symbol:${owner}/call:${typedMethod}/${ordinal}/argument:0`,
          argument,
          argument,
          "prose-expression",
          `symbol:${catalogOwner}/call:${typedMethod}/${catalogOrdinal}/argument:0`,
        );
        addRecord(
          {
            kind: "model-call",
            owner,
            catalogOwner,
            method: typedMethod,
            ordinal,
            catalogOrdinal,
            site,
          },
          [site],
        );
      }
    }

    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === "completeStructured"
    ) {
      const options = node.arguments[0];
      if (options !== undefined && ts.isObjectLiteralExpression(options)) {
        const owner = enclosingSymbol(node);
        const catalogOwner = "module";
        const fields: ToolFragmentSite[] = [];
        for (const field of ["toolDescription", "system", "instruction", "schema"] as const) {
          for (const member of properties(options, field)) {
            fields.push({
              id: field,
              label: `completeStructured ${field}`,
              site: expressionSite(
                `symbol:${owner}/call:completeStructured/${field}`,
                member,
                propertyInitializer(member),
                "prose-expression",
                `symbol:${catalogOwner}/call:completeStructured/${field}`,
              ),
            });
          }
        }
        if (fields.length > 0) {
          addRecord(
            { kind: "complete-structured", owner, catalogOwner, fields },
            fields.map((field) => field.site),
          );
        }
      }
    }

    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
      const event =
        node.expression.name.text === "on" ? staticString(node.arguments[0] ?? null) : null;
      if (event === "before_agent_start") {
        const owner = enclosingSymbol(node);
        const catalogOwner = "module";
        const ordinal = nextOrdinal(`${sourceIdentity}:${owner}:before-agent-start`, ownerOrdinals);
        const catalogOrdinal = nextOrdinal(`${sourceIdentity}:${catalogOwner}:before-agent-start`);
        const handler = node.arguments[1] ?? null;
        const site = expressionSite(
          `symbol:${owner}/event:before_agent_start/${ordinal}/handler`,
          handler ?? node,
          handler,
          "event-handler",
          `symbol:${catalogOwner}/event:before_agent_start/${catalogOrdinal}/handler`,
        );
        addRecord({ kind: "event-handler", owner, catalogOwner, ordinal, catalogOrdinal, site }, [
          site,
        ]);
      }
    }

    if (ts.isPropertyAssignment(node) && propertyName(node) === "workflowScript") {
      const owner = enclosingSymbol(node);
      const catalogOwner = "module";
      const ordinal = nextOrdinal(`${sourceIdentity}:${owner}:workflow-script`, ownerOrdinals);
      const catalogOrdinal = nextOrdinal(`${sourceIdentity}:${catalogOwner}:workflow-script`);
      const site = expressionSite(
        `symbol:${owner}/property:workflowScript/${ordinal}`,
        node.initializer,
        node.initializer,
        "prose-expression",
        `symbol:${catalogOwner}/property:workflowScript/${catalogOrdinal}`,
      );
      addRecord({ kind: "workflow-property", owner, catalogOwner, ordinal, catalogOrdinal, site }, [
        site,
      ]);
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return { records, sites };
}

export type UnresolvedSelectorReason =
  | "unsupported-selector"
  | "unsupported-source-shape"
  | "selector-not-found"
  | "selector-ambiguous";

export type SelectorResult =
  | {
      selector: string;
      status: "resolved";
      start: number;
      end: number;
    }
  | {
      selector: string;
      status: "unresolved";
      reason: UnresolvedSelectorReason;
      line: number | null;
      column: number | null;
    };

export type SelectorResponse =
  | { version: 1; status: "invalid-source"; line: number; column: number }
  | { version: 1; status: "ok"; results: SelectorResult[] };

type ParsedSourceFile = ts.SourceFile & { parseDiagnostics?: unknown };
type ParserDiagnostic = ts.Diagnostic & { start: number };

/** Isolate the pinned compiler runtime seam that is intentionally absent from public typings. */
export function parseDiagnosticsFor(sourceFile: ts.SourceFile): readonly ParserDiagnostic[] {
  const diagnostics = (sourceFile as ParsedSourceFile).parseDiagnostics;
  if (!Array.isArray(diagnostics)) {
    throw new Error("TypeScript SourceFile.parseDiagnostics is unavailable");
  }
  for (const diagnostic of diagnostics) {
    if (
      typeof diagnostic !== "object" ||
      diagnostic === null ||
      typeof (diagnostic as { start?: unknown }).start !== "number"
    ) {
      throw new Error("TypeScript SourceFile.parseDiagnostics contains an invalid diagnostic");
    }
  }
  return diagnostics as ParserDiagnostic[];
}

function sourceFileFor(source: string): ts.SourceFile {
  return ts.createSourceFile(
    "<prose-review-source.ts>",
    source,
    ts.ScriptTarget.ES2022,
    true,
    ts.ScriptKind.TS,
  );
}

function codePointOffset(source: string, position: number): number {
  if (!Number.isInteger(position) || position < 0 || position > source.length) {
    throw new Error(`invalid TypeScript UTF-16 position: ${position}`);
  }
  if (position > 0 && position < source.length) {
    const previous = source.charCodeAt(position - 1);
    const current = source.charCodeAt(position);
    if (previous >= 0xd800 && previous <= 0xdbff && current >= 0xdc00 && current <= 0xdfff) {
      throw new Error(`TypeScript position splits a surrogate pair: ${position}`);
    }
  }
  return [...source.slice(0, position)].length;
}

function sourceLocation(
  source: string,
  sourceFile: ts.SourceFile,
  position: number,
): { line: number; column: number } {
  codePointOffset(source, position);
  const location = sourceFile.getLineAndCharacterOfPosition(position);
  const lineStart = position - location.character;
  const column = [...source.slice(lineStart, position)].length + 1;
  return { line: location.line + 1, column };
}

function unresolved(
  selector: string,
  reason: UnresolvedSelectorReason,
  location: { line: number; column: number } | null = null,
): SelectorResult {
  return {
    selector,
    status: "unresolved",
    reason,
    line: location?.line ?? null,
    column: location?.column ?? null,
  };
}

function transparentExpression(expression: ts.Expression): ts.Expression {
  let current = expression;
  while (
    ts.isParenthesizedExpression(current) ||
    ts.isAsExpression(current) ||
    ts.isTypeAssertionExpression(current) ||
    ts.isSatisfiesExpression(current) ||
    ts.isNonNullExpression(current)
  ) {
    current = current.expression;
  }
  return current;
}

function isStringLeaf(expression: ts.Expression): boolean {
  const current = transparentExpression(expression);
  return (
    ts.isStringLiteral(current) ||
    ts.isNoSubstitutionTemplateLiteral(current) ||
    ts.isTemplateExpression(current)
  );
}

function plusTreeHasStringLeaf(expression: ts.Expression): boolean {
  const current = transparentExpression(expression);
  if (isStringLeaf(current)) {
    return true;
  }
  if (!ts.isBinaryExpression(current) || current.operatorToken.kind !== ts.SyntaxKind.PlusToken) {
    return false;
  }
  return plusTreeHasStringLeaf(current.left) || plusTreeHasStringLeaf(current.right);
}

function eligibleTarget(site: SelectorSite): boolean {
  if (site.target === null) {
    return false;
  }
  const current = transparentExpression(site.target);
  if (site.targetKind === "event-handler") {
    return ts.isArrowFunction(current) || ts.isFunctionExpression(current);
  }
  return isStringLeaf(current) || plusTreeHasStringLeaf(current);
}

function nodeLocation(
  source: string,
  sourceFile: ts.SourceFile,
  node: ts.Node,
): { line: number; column: number } {
  return sourceLocation(source, sourceFile, node.getStart(sourceFile));
}

function resolveExactSite(
  source: string,
  sourceFile: ts.SourceFile,
  selector: string,
  matches: SelectorSite[],
): SelectorResult {
  if (matches.length > 1) {
    return unresolved(
      selector,
      "selector-ambiguous",
      nodeLocation(source, sourceFile, matches[1]?.target ?? matches[1]?.location ?? sourceFile),
    );
  }
  const site = matches[0];
  if (site === undefined) {
    throw new Error("exact selector resolution requires a site");
  }
  if (!eligibleTarget(site)) {
    return unresolved(
      selector,
      "unsupported-source-shape",
      nodeLocation(source, sourceFile, site.target ?? site.location),
    );
  }
  const target = site.target;
  if (target === null) {
    throw new Error("eligible selector site unexpectedly lacks a target");
  }
  const start = codePointOffset(source, target.getStart(sourceFile));
  const end = codePointOffset(source, target.end);
  if (start >= end) {
    throw new Error("TypeScript selector resolved an empty range");
  }
  return { selector, status: "resolved", start, end };
}

function namedSymbolDeclarations(sourceFile: ts.SourceFile, name: string): ts.Statement[] {
  const matches: ts.Statement[] = [];
  for (const statement of sourceFile.statements) {
    if (
      (ts.isFunctionDeclaration(statement) || ts.isClassDeclaration(statement)) &&
      statement.name?.text === name
    ) {
      matches.push(statement);
      continue;
    }
    if (!ts.isVariableStatement(statement) || statement.declarationList.declarations.length !== 1) {
      continue;
    }
    const declaration = statement.declarationList.declarations[0];
    if (
      declaration !== undefined &&
      ts.isIdentifier(declaration.name) &&
      declaration.name.text === name
    ) {
      matches.push(statement);
    }
  }
  return matches;
}

type TypeScriptWithIdentifierText = typeof ts & {
  isIdentifierText(
    name: string,
    languageVersion: ts.ScriptTarget,
    languageVariant: ts.LanguageVariant,
  ): boolean;
};

function isEs2022IdentifierText(name: string): boolean {
  const checker = (ts as TypeScriptWithIdentifierText).isIdentifierText;
  if (typeof checker !== "function") {
    throw new Error("TypeScript isIdentifierText is unavailable");
  }
  return checker(name, ts.ScriptTarget.ES2022, ts.LanguageVariant.Standard);
}

function bareSymbolName(selector: string): string | null {
  if (!selector.startsWith("symbol:")) {
    return null;
  }
  const name = selector.slice("symbol:".length);
  if (
    name.length === 0 ||
    name === "module" ||
    name.includes("/") ||
    !isEs2022IdentifierText(name)
  ) {
    return null;
  }
  return name;
}

function resolveBareSymbol(
  source: string,
  sourceFile: ts.SourceFile,
  selector: string,
  name: string,
): SelectorResult {
  const matches = namedSymbolDeclarations(sourceFile, name);
  if (matches.length === 0) {
    return unresolved(selector, "selector-not-found");
  }
  if (matches.length > 1) {
    const second = matches[1];
    if (second === undefined) {
      throw new Error("ambiguous symbol lacks its second declaration");
    }
    return unresolved(selector, "selector-ambiguous", nodeLocation(source, sourceFile, second));
  }
  const match = matches[0];
  if (match === undefined) {
    throw new Error("resolved symbol lacks its declaration");
  }
  const start = codePointOffset(source, match.getStart(sourceFile));
  const end = codePointOffset(source, match.end);
  if (start >= end) {
    throw new Error("TypeScript symbol resolved an empty range");
  }
  return { selector, status: "resolved", start, end };
}

const CANONICAL_ORDINAL = "(?:0|[1-9][0-9]*)";
const MODEL_CALL_SELECTOR = new RegExp(
  `^symbol:(.+)/call:(?:sendUserMessage|complete|prompt)/${CANONICAL_ORDINAL}/argument:0$`,
);
const COMPLETE_STRUCTURED_SELECTOR =
  /^symbol:(.+)\/call:completeStructured\/(?:toolDescription|system|instruction|schema)$/;
const EVENT_HANDLER_SELECTOR = new RegExp(
  `^symbol:(.+)/event:before_agent_start/${CANONICAL_ORDINAL}/handler$`,
);
const WORKFLOW_PROPERTY_SELECTOR = new RegExp(
  `^symbol:(.+)/property:workflowScript/${CANONICAL_ORDINAL}$`,
);

function isMissingSupportedSelector(selector: string): boolean {
  if (selector.startsWith("tool:")) {
    const payload = selector.slice("tool:".length);
    return payload.length > 0 && payload.includes(".");
  }
  return (
    MODEL_CALL_SELECTOR.test(selector) ||
    COMPLETE_STRUCTURED_SELECTOR.test(selector) ||
    EVENT_HANDLER_SELECTOR.test(selector) ||
    WORKFLOW_PROPERTY_SELECTOR.test(selector)
  );
}

/** Resolve an ordered selector batch against one supplied source parse and site enumeration. */
export function resolveSelectors(source: string, selectors: readonly string[]): SelectorResponse {
  const sourceFile = sourceFileFor(source);
  const diagnostics = parseDiagnosticsFor(sourceFile);
  const firstDiagnostic = diagnostics[0];
  if (firstDiagnostic !== undefined) {
    const location = sourceLocation(source, sourceFile, firstDiagnostic.start);
    return { version: 1, status: "invalid-source", ...location };
  }

  const enumeration = enumerateSelectorSites(sourceFile);
  const catalogSites = new Map<string, SelectorSite[]>();
  const helperSites = new Map<string, SelectorSite[]>();
  for (const site of enumeration.sites) {
    const catalogMatches = catalogSites.get(site.catalogSelector) ?? [];
    catalogMatches.push(site);
    catalogSites.set(site.catalogSelector, catalogMatches);

    const helperMatches = helperSites.get(site.selector) ?? [];
    helperMatches.push(site);
    helperSites.set(site.selector, helperMatches);
  }

  const results = selectors.map((selector): SelectorResult => {
    // Raw discovery identities take precedence when a parent-linked helper alias has the same text.
    const exact = catalogSites.get(selector) ?? helperSites.get(selector);
    if (exact !== undefined) {
      return resolveExactSite(source, sourceFile, selector, exact);
    }
    const symbolName = bareSymbolName(selector);
    if (symbolName !== null) {
      return resolveBareSymbol(source, sourceFile, selector, symbolName);
    }
    if (isMissingSupportedSelector(selector)) {
      return unresolved(selector, "selector-not-found");
    }
    return unresolved(selector, "unsupported-selector");
  });
  return { version: 1, status: "ok", results };
}

type SelectorRequest = { version: 1; source: string; selectors: string[] };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseRequest(value: unknown): SelectorRequest {
  if (!isRecord(value)) {
    throw new Error("selector request must be an object");
  }
  const keys = Object.keys(value).sort();
  if (keys.join("\0") !== ["selectors", "source", "version"].join("\0")) {
    throw new Error("selector request must contain exactly version, source, and selectors");
  }
  if (
    value.version !== 1 ||
    typeof value.source !== "string" ||
    !Array.isArray(value.selectors) ||
    !value.selectors.every((selector) => typeof selector === "string")
  ) {
    throw new Error("selector request has invalid field types or version");
  }
  return { version: 1, source: value.source, selectors: value.selectors };
}

async function runCli(requestPath: string): Promise<void> {
  const raw = await readFile(requestPath, "utf-8");
  const request = parseRequest(JSON.parse(raw) as unknown);
  const response = resolveSelectors(request.source, request.selectors);
  process.stdout.write(`${JSON.stringify(response)}\n`);
}

const entrypoint = process.argv[1];
if (entrypoint !== undefined && import.meta.url === pathToFileURL(entrypoint).href) {
  const requestPath = process.argv.length === 3 ? process.argv[2] : undefined;
  if (requestPath === undefined) {
    process.stderr.write("usage: node tools/prose-map/selector.ts <request-json-path>\n");
    process.exitCode = 2;
  } else {
    runCli(requestPath).catch((error: unknown) => {
      const message = error instanceof Error ? error.message : String(error);
      process.stderr.write(`${message}\n`);
      process.exitCode = 1;
    });
  }
}
