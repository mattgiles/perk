export type DocumentLike = {
  querySelector: (selector: string) => { getAttribute: (name: string) => string | null } | null;
};

export function mutationHeaders(
  documentRoot: DocumentLike | undefined,
): Record<string, string> | null {
  const token = documentRoot?.querySelector('meta[name="csrf-token"]')?.getAttribute("content");
  if (token === undefined || token === null || token.trim().length === 0) {
    return null;
  }
  return {
    "Content-Type": "application/json",
    "X-Prose-Review-Csrf": token,
  };
}
