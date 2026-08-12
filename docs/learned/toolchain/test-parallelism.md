---
title: Parallelizing the two test suites
read_when: You are making `just test` / `just ci` faster, adding pytest-xdist config, or splitting a harness-heavy `node:test` file into siblings.
cluster: toolchain-gotchas
---

# Parallelizing perk's two test suites

perk runs two framework suites — `pytest` and `node:test`. Each parallelizes differently, and the
levers are not interchangeable. Landed in #592 (PR #591) with no production code and no
`shared/` / user-docs change.

## Python: xdist-by-default

`pytest-xdist` in the dev dependency group + a `[tool.pytest.ini_options]` table with
`addopts = "-n auto --dist loadgroup"` and `testpaths = ["tests"]` makes **EVERY** `uv run pytest`
parallel — local, `just test-py`/`just test`, and CI — with **no justfile change**.

- **`-n0` on the CLI overrides `addopts`** — the documented serial-debug escape hatch. Extra CLI
  args (`-k <expr>`) coexist with `addopts`.
- The suite was already xdist-safe (env mutations are function-scoped `monkeypatch.setenv`, every
  `os.chdir` is a no-op `monkeypatch.setattr`, fixtures use `tmp_path`/`tmp_path_factory`).
  `testpaths` is **hygiene, not a fix** — pytest's default `norecursedirs` `.*` glob already
  excludes dotdirs like `.agents/cache/`.

### The build-once-under-parallelism idiom

A session-scoped build fixture only builds **once** IF its consumers can't scatter across workers.
`--dist loadgroup` + tagging both consumers with the **SAME** `xdist_group` pins them to one worker,
so the session fixture builds once (verifiable: both run on the same `gwN`). Without the shared
group, `loadgroup` scatters them and the session fixture rebuilds per-worker. Move a
`skipif(which(...) is None)` **INTO** the fixture as `pytest.skip(...)` so the skip survives the
refactor. (Measured ≈4× on an 11-core box: ~70 s → ~18 s.)

## JavaScript: split files, don't add intra-file concurrency

Node's `--test` runs each **FILE** in its own child process and parallelizes **ACROSS** files;
tests **within** a file run sequentially. So the wall-clock floor is the slowest single file, and
the lever is **splitting the largest harness-heavy files** into siblings.

- **Intra-file `describe({concurrency:true})` is UNSAFE here.** The session harness's env-apply
  mutates `process.env` **process-globally** and restores on dispose, so concurrent sessions in one
  process clobber each other. Node isolates env **per-file (per-process)**, so more files is safe;
  intra-file concurrency would need a per-session env-injection harness refactor (out of scope).
- `--test-concurrency=$(( $(getconf _NPROCESSORS_ONLN) * 2 ))` (portable macOS+Linux) mildly
  oversubscribes cores — session construction is I/O-bound, so in-flight files overlap I/O waits.
  Add it to **both** the `test-js` and `test` justfile recipes.

### The file-split recipe + gotchas

- **Split at existing section-comment boundaries** (`// --- … ---`), never line numbers. Each new
  sibling re-imports the harness helpers + local fixtures its moved tests use.
- **noUnusedLocals drives the trim loop.** With `noUnusedLocals`/`noUnusedParameters` on,
  `tsc --noEmit` flags every now-unused import/const/helper per file. Biome `recommended` does NOT
  remove unused imports, so **tsc is the oracle**. Shared top-of-file consts/fakes must be
  DUPLICATED into each sibling, then trimmed per-file by what tsc reports (for both the new file and
  the truncated keep file).
- **The `sed`-capture off-by-one gotcha:** capturing a multi-line import block by line range can
  drop a trailing `} from "./mod.ts";` on the line *after* the range → a syntax error. Verify the
  closing brace landed; re-check against `git show HEAD:<file>` line numbers.
- **Count-preservation proof:** compare `grep -cE '\btest\('` on the original (`git show
  HEAD:<file>`) vs the sum across the split files, then run `node --test --test-reporter=tap` and
  check the `# tests`/`# pass`/`# fail` summary (the `dot` reporter doesn't print a count).
- Run `biome check --write` on every new file before CI (formats + sorts imports).
- Per the AGENTS per-turn-doc convention, this kind of test-infra change still writes a
  `docs/planning/` note with a measured before/after table (no `shared/` / user-docs churn — not
  cross-plane/user-facing).

## Cross-references

- `docs/learned/toolchain/biome.md` — the noUnusedLocals / tsc-oracle relationship
- `docs/learned/toolchain/worktree-node-modules.md` — the SIGTERM-kill / stale-modules traps
- `docs/learned/toolchain/ruff.md` — the run_ci-green-≠-committable format-on-commit trap
