// Dual-presentation rule (docs/design/docs-site-blueprint.md §6): corpus sources keep their
// standalone `#` H1 so they read complete on GitHub; the site renders exactly one H1 from the
// frontmatter `title`, so the first top-level depth-1 heading is removed from the body here.
// Top-level-children semantics only — a depth-1 heading nested inside another node is left alone.
export default function remarkStripFirstH1() {
  return (tree) => {
    const index = tree.children.findIndex((node) => node.type === "heading" && node.depth === 1);
    if (index !== -1) tree.children.splice(index, 1);
  };
}
