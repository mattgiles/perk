# Vendored `smol-toml` parser closure

Third-party code: the **parser-only** ESM closure of
[`smol-toml`](https://github.com/squirrelchat/smol-toml) `1.8.0` (BSD-3-Clause — see `LICENSE`;
every module keeps its upstream copyright header). Only the draft-review routing-config projection
(`extension/substrate/draftReviewConfig.ts`) imports it, via `./parse.js` directly.

Why vendored rather than depended upon: pi loads the perk extension from a bare git-package clone
with no `npm install`, so shipped code may import only Node builtins, relative paths, or the host
peer packages (`extension/bareImportGuard.test.ts`, `tests/test_packaging.py`). A runtime
`dependencies` entry would be unresolvable.

## Contents (exact, byte-identical to `node_modules/smol-toml/dist/`)

Runtime: `parse.js`, `struct.js`, `extract.js`, `primitive.js`, `date.js`, `error.js`, `util.js`.
Types: `parse.d.ts`, `date.d.ts`, `error.d.ts`, `util.d.ts`.

Deliberately **not** shipped: the serializer (`stringify.*`), the CJS bundle (`index.cjs`), and the
package entry point (`index.js` / `index.d.ts`).

## Updating

1. Bump the exact `smol-toml` pin in `package.json` `devDependencies` and refresh
   `package-lock.json` (`npm install --save-dev --save-exact smol-toml@<version>`).
2. Copy the files listed above from `node_modules/smol-toml/dist/` (and `LICENSE` from the package
   root) over the copies here, unmodified — this directory is excluded from Biome so upstream bytes
   stay intact; `extension/vendor/smolToml.test.ts` fails on any byte drift or file-set change.
3. Update the version named in this README.
