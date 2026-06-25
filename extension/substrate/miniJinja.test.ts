import { strict as assert } from "node:assert";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import { render } from "./miniJinja.ts";

// Out-of-subset templates CANNOT be committed under prompts/ (the frozen-grammar guard forbids
// them), so unit tests point `rootDir` at a throwaway temp dir holding the template under test.
function withTemplates(files: Record<string, string>): string {
  const dir = mkdtempSync(join(tmpdir(), "perk-minijinja-"));
  for (const [name, body] of Object.entries(files)) {
    writeFileSync(join(dir, name), body);
  }
  return dir;
}

/** Render a single inline template `body` named `main.md` with `vars`. */
function r(body: string, vars: Record<string, unknown> = {}): string {
  return render("main.md", vars, withTemplates({ "main.md": body }));
}

// ---------------------------------------------------------------------------
// Positive
// ---------------------------------------------------------------------------

test("variable substitution", () => {
  assert.equal(r("Hello, {{ name }}!", { name: "world" }), "Hello, world!");
});

test("multiple vars on one line", () => {
  assert.equal(r("{{ a }}-{{ b }}-{{ a }}", { a: "x", b: "y" }), "x-y-x");
});

test("include splices the recursively-rendered template, trims the post-tag newline, keeps trailing newline", () => {
  const dir = withTemplates({
    "main.md": 'Welcome, {{ name }}.\n{% include "_greeting.md" %}\n\nThat is all.\n',
    "_greeting.md": "Greetings from {{ place }}.\n",
  });
  assert.equal(
    render("main.md", { name: "Ada", place: "the fixture" }, dir),
    "Welcome, Ada.\nGreetings from the fixture.\n\nThat is all.\n",
  );
});

test("block-level if/elif/else/endif (own-line tags; trim swallows the newline)", () => {
  // trim_blocks consumes the `\n` after every block tag's `%}`, including `{% endif %}`.
  const tpl = "{% if a %}\nA\n{% elif b %}\nB\n{% else %}\nC\n{% endif %}\n";
  assert.equal(r(tpl, { a: "x", b: "" }), "A\n");
  assert.equal(r(tpl, { a: "", b: "y" }), "B\n");
  assert.equal(r(tpl, { a: "", b: "" }), "C\n");
});

test("inline block tags (mid-line; no trim) render text after endif normally", () => {
  const tpl = "pre;{% if read %} mid {% endif %} post";
  assert.equal(r(tpl, { read: "x" }), "pre; mid  post");
  assert.equal(r(tpl, { read: "" }), "pre; post");
});

test("== / or / not / and", () => {
  assert.equal(r('{% if p == "github" %}gh{% endif %}', { p: "github" }), "gh");
  assert.equal(
    r('{% if p == "github" or p == "linear" %}known{% endif %}', { p: "linear" }),
    "known",
  );
  assert.equal(r("{% if not x %}empty{% endif %}", { x: "" }), "empty");
  assert.equal(r("{% if a and b %}both{% endif %}", { a: "1", b: "1" }), "both");
  assert.equal(r("{% if a and b %}both{% endif %}", { a: "1", b: "" }), "");
});

test("nested if", () => {
  const tpl = "{% if a %}{% if b %}AB{% else %}A{% endif %}{% endif %}";
  assert.equal(r(tpl, { a: "1", b: "1" }), "AB");
  assert.equal(r(tpl, { a: "1", b: "" }), "A");
  assert.equal(r(tpl, { a: "", b: "1" }), "");
});

// ---------------------------------------------------------------------------
// Value semantics
// ---------------------------------------------------------------------------

test("non-string var (boolean/number) throws", () => {
  assert.throws(() => r("{{ x }}", { x: true }), /string-only/);
  assert.throws(() => r("{{ x }}", { x: 42 }), /string-only/);
  assert.throws(() => r("{{ x }}", { x: null }), /string-only/);
});

test("empty-string var renders empty and is falsy", () => {
  assert.equal(r("[{{ x }}]", { x: "" }), "[]");
  assert.equal(r("{% if x %}yes{% else %}no{% endif %}", { x: "" }), "no");
});

test("missing var in {{ }} throws", () => {
  assert.throws(() => r("{{ missing }}", {}), /undefined/);
});

test("missing var inside {% if %} / {% elif %} throws (StrictUndefined parity)", () => {
  assert.throws(() => r("{% if missing %}x{% endif %}", {}), /undefined/);
  assert.throws(() => r("{% if a %}a{% elif missing %}b{% endif %}", { a: "" }), /undefined/);
});

// ---------------------------------------------------------------------------
// Malformed conditions (each throws)
// ---------------------------------------------------------------------------

for (const [label, tpl] of [
  ["adjacent atoms", "{% if a b %}x{% endif %}"],
  ["missing right operand", "{% if a == %}x{% endif %}"],
  ["missing left operand", "{% if == a %}x{% endif %}"],
  ["dangling not", "{% if not %}x{% endif %}"],
  ["empty condition", "{% if %}x{% endif %}"],
  ["duplicate else", "{% if a %}x{% else %}y{% else %}z{% endif %}"],
  ["elif after else", "{% if a %}x{% else %}y{% elif b %}z{% endif %}"],
] as const) {
  test(`malformed condition throws: ${label}`, () => {
    assert.throws(() => r(tpl, { a: "1", b: "1" }), /perk mini-jinja:/);
  });
}

// ---------------------------------------------------------------------------
// Out-of-subset (each throws)
// ---------------------------------------------------------------------------

for (const [label, tpl] of [
  ["comment", "{# nope #}"],
  ["whitespace-control block", "{%- if a -%}x{%- endif -%}"],
  ["whitespace-control var", "{{- x -}}"],
  ["for loop", "{% for x in y %}{{ x }}{% endfor %}"],
  ["set", "{% set a = 1 %}"],
  ["filter", "{{ x | upper }}"],
  ["attribute access", "{{ a.b }}"],
  ["not-equal operator", "{% if a != b %}x{% endif %}"],
  ["in operator", "{% if a in b %}x{% endif %}"],
  ["parentheses", "{% if (a or b) %}x{% endif %}"],
  ["numeric literal", "{% if a == 1 %}x{% endif %}"],
  ["escaped string", '{% if a == "x\\"y" %}x{% endif %}'],
  ["unclosed if", "{% if a %}x"],
  ["stray endif", "x{% endif %}"],
  ["unterminated var", "{{ x"],
] as const) {
  test(`out-of-subset throws: ${label}`, () => {
    assert.throws(() => r(tpl, { a: "1", b: "1", x: "v", y: "z" }), /perk mini-jinja:/);
  });
}

// ---------------------------------------------------------------------------
// Path containment (each throws)
// ---------------------------------------------------------------------------

test("path containment: parent-traversal top-level name throws", () => {
  const dir = withTemplates({ "main.md": "x" });
  assert.throws(() => render("../outside.md", {}, dir), /perk mini-jinja:/);
});

test("path containment: parent-traversal include throws", () => {
  const dir = withTemplates({ "main.md": '{% include "../x.md" %}' });
  assert.throws(() => render("main.md", {}, dir), /perk mini-jinja:/);
});

test("path containment: absolute include path throws", () => {
  const dir = withTemplates({ "main.md": '{% include "/etc/passwd" %}' });
  assert.throws(() => render("main.md", {}, dir), /perk mini-jinja:/);
});

test("path containment: empty path throws", () => {
  const dir = withTemplates({ "main.md": "x" });
  assert.throws(() => render("", {}, dir), /perk mini-jinja:/);
});
