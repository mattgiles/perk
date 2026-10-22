---
title: "Security"
description: "Which trust store each perk path verifies TLS against, which floors perk enforces, and the advisories that moved them."
sidebar:
  order: 3007
---

# Security

perk verifies TLS through several clients, and each one trusts its own certificate store. This
page records which store each path uses by default, which version floors perk enforces, which
ones stay with you, and the advisories that moved them. perk never disables certificate
verification and never asks you to.

## Where TLS is verified

| Path | Client | Trust store by default |
|---|---|---|
| perk CLI (Linear backend, librarian probe) | `httpx` | The `certifi` bundle, floored by perk's wheel metadata. `SSL_CERT_FILE` or `SSL_CERT_DIR` take precedence when set, so a bundle you supply is yours to keep current. |
| `pi` (model traffic) and every `npm` install | Node.js | Node's bundled store, floored by perk's Node supported release lines. |
| `gh` | Go | The operating-system store. |
| `git` over HTTPS | libcurl | The operating-system store; on macOS, the built-in `git` reads `/etc/ssl/cert.pem`, which macOS updates do not refresh. |
| Librarian docs crawl | the host `curl` | The operating-system store (on macOS, `/etc/ssl/cert.pem` for the built-in `curl`). |

**Enforced by perk:**

- Node.js on a supported release line — `perk init` exits 2 and `perk doctor` fails on an
  outdated Node or one on an unsupported line, and `engines.node` refuses `npm ci` under
  `engine-strict`.
- The `certifi` floor — the published wheel requires it, so every fresh `uv tool install perk`
  resolves a patched bundle.
- The `uv` floor for perk's own checkout, worktrees and CI — `[tool.uv] required-version` in
  `pyproject.toml`, which `uv` project commands and `setup-uv` honor; the managed remote setup
  action pins the same floor explicitly.

**Operator-required:**

- The `uv` that runs `uv tool install perk` or `uv tool upgrade perk` — uv tool commands ignore
  project configuration, so an outdated uv can still download a new perk.
- Any CA bundle you supply through `SSL_CERT_FILE` or `SSL_CERT_DIR`.
- The operating-system stores behind `git`, `curl`, `gh` and `mise`.
- Restarting every running Pi process after a Node upgrade — a running process keeps the
  runtime and bundled trust store it started with, and `perk doctor`'s `node` row probes a fresh
  `node --version`, never the running Pi.

## Advisories

### 2026-10 — eMudhra intermediate-CA compromise

Eight eMudhra intermediate CAs, chaining to `emSign ECC Root CA - G3` and `AAA Certificate
Services`, shipped with recoverable private keys. Browsers and operating systems block them
through revocation feeds; non-browser TLS clients need a software update.

| Component | Floor | Enforcement |
|---|---|---|
| Node.js | 22.23.4 (22.x), 24.22.1 (24.x), 26.12.1 (26.x) | `perk init`, `perk doctor`, `engines.node`, CI and the remote setup action |
| `certifi` | 2026.10.19 | perk's wheel metadata |
| `uv` | 0.13.4 | perk's checkout and CI; operator-required for `uv tool install` |
| `mise` | 2026.10.17 | Operator-required |

What to do, in order:

1. Update `mise` (`mise self-update`) or Homebrew (`brew update`).
2. Move Node.js onto a supported release line at or above its floor, for example
   `mise use -g node@26.12.1` or `brew upgrade node`.
3. Quit every running Pi session and long-lived worker, then relaunch under the patched Node.
4. Update uv, then perk: `UV_SYSTEM_CERTS=true uv self update`, then `uv tool upgrade perk`.
5. On macOS, apply the `/etc/ssl/cert.pem` fix from the incident site for the built-in `git` and
   `curl`.
6. Re-check any bundle you maintain through `SSL_CERT_FILE` or `SSL_CERT_DIR`.

To verify, run `perk doctor` and confirm the `node` row passes, then run the incident site's
check from each verifier you use — for example `curl https://dv-g3b-emudhra.we-have-a-problem.com/`
must fail with a certificate error.

Sources: [the incident site](https://emudhra.we-have-a-problem.com/), the
[Python announcement](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576/),
the [Cloudflare post](https://blog.cloudflare.com/emudhra-certificate-compromise), and the
[Node.js security releases](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases).

## Related

- **Look up:** [Requirements and compatibility](./requirements-and-compatibility.md) — check the
  full toolchain and every enforced version floor.
- **Do:** [How to diagnose a perk repo](../how-to/diagnose-a-perk-repo.md) — read `perk doctor`'s
  rows, including the `node` environment check.
- **Look up:** [Setup and health](./cli/setup-and-health.md) — check what `perk init` and
  `perk doctor` report and when they exit non-zero.
