# Dependency bump gut check — 2026-10-25

The five updates below are **compatible under focused checks** with Perk's current
Pi **1.4.0** / pi-subagents **0.81.0** pair. No Perk compatibility repair was found.
Use the ordinary package-update and session-restart workflow for these packages;
this assessment introduces no recurring certification requirement.

| Package | Installed → assessed target | Verdict |
| --- | --- | --- |
| `pi-web-access` | 0.37.0 → [0.44.0][web-npm] | Compatible; native SDK census and real-host loading pass. |
| `@plannotator/pi-extension` | 0.28.8 → [0.28.30][plan-npm] | Compatible; review handshake, port selection, and annotation contracts pass. |
| `@juicesharp/rpiv-todo` | 2.12.0 → [2.15.0][todo-npm] | Compatible; existing calls and old persisted task snapshots work. |
| `@juicesharp/rpiv-ask-user-question` | 2.12.0 → [2.15.0][ask-npm] | Compatible; direct model calls remain available. Script exposure changes below. |
| `@dietrichgebert/ponytail` | 5.0.0 → [5.3.2][pony-npm] | Compatible; both required skills pass Perk's preflight. |

## Snapshot and method

Assessed Perk **4.1.0**, revision
`b38e76f434cedd9d4f6a2a31e41f6b05b71c54e5`, on macOS with Node **26.12.1**.
The targets were npm's `latest` versions when queried on October 25. Verdicts are
specific to these artifacts and this host pair; other supported Node versions
were not exercised.

These packages are intentionally unpinned in [Pi settings][settings], as documented
in the [development recipes][justfile]. They are installed through Pi's project
package store, rather than Perk's root development dependency lockfile. This work
changes only this document: it leaves the installed packages, settings, host,
supplier, and lockfiles alone.

The assessment used `/tmp/perk-dep-gutcheck.RpFxJo`: a `git archive` copy of the
revision above, a fresh root `npm ci`, an independently installed Pi 1.4.0 CLI,
and fresh project-package installations of all five targets plus pi-subagents
0.81.0. No install reused the main checkout's hard-linked `.pi/npm` files.
Lifecycle scripts were disabled. Project-package installation used
`--legacy-peer-deps` to leave SDK peers supplied by the fixed host/development
graph; peer declarations and actual loading were checked separately.

Both endpoints of every version interval were downloaded with `npm pack
--ignore-scripts --json`. All **486 published baseline files** matched their
installed counterparts byte-for-byte. Artifact comparisons covered the complete
installed-to-target interval, with review focused on the interfaces Perk consumes.
The target rpiv packages resolved `@juicesharp/rpiv-config` **2.15.0**; their
`@juicesharp/rpiv-i18n` peer remains optional and was absent during the checks.

## Package findings

### pi-web-access

The packaged entry remains `./dist`; its Pi/typebox peer declarations and Node
minimum are unchanged. The existing native consumer census passes without adding
any SDK specifiers. A fresh Pi 1.4.0 process loads the actual target and registers
`web_enable`, `web_search`, `source_check`, `fetch_content`, and
`get_search_content`.

The intervening releases add providers, gateway/redirect controls, extraction and
session-isolation fixes, and update the MCP SDK from 1.27.1 to 1.32.1. Deferred
exposure and `toolActivation: "none"` are opt-in; the existing direct exposure
remains the default. No provider configuration or bridge change is needed for the
bump. Provider requests, credentials, summaries, and extraction quality were not
tested. [Released changes][web-changes], [target registration source][web-source].

### @plannotator/pi-extension

The entrypoint and `>=0.79.1` host peer remain unchanged. Perk's plan-review
request still receives a pending `reviewId` and its decision on
`plannotator:review-result`; code-review requests retain the callback and the
payload fields Perk sends. The target adds session-open/close events and guards
against stale extension instances. The actual target plan listener and Perk's
actual adapter completed a handshake and approval-with-feedback using an injected
browser-session stand-in. This proves the event contract, not a browser drive.
[Target event implementation][plan-events].

The port-range parser and Node external-annotation adapter are byte-identical
between the two packages. Six local/remote/explicit-port cases also agree with
Perk's port-selection mirror. Loopback probes through the target annotation
handler and new origin guard accept Perk-generated plan and review payloads,
return HTTP 201, preserve another source on source-scoped deletion, and reject
cross-origin writes. Perk's requests omit `Origin`, which the guard permits.
Keep the existing readiness, port reservation, and annotation-ownership code.
[Network implementation][plan-network], [annotation adapter][plan-annotations],
[origin guard][plan-origin].

### @juicesharp/rpiv-todo

The tool remains `todo`, with the existing single-task actions and task-detail
envelope. Batch creation is additive. Mutations now also append
`rpiv-todo-state` custom session entries, preserving state when calls originate
inside codemode. Replay still accepts old `todo` tool-result snapshots; valid
custom snapshots become authoritative and malformed snapshots are skipped.

Actual candidate calls passed create/update/get and batch-create checks. A
separate probe generated a result with the published **2.12.0 reducer and response
builder**, then restored its tasks, owner, metadata, and next ID with **2.15.0's
replay code**. Custom-entry replay and stale/corrupt snapshot handling also passed.
The entry remains `index.ts`; local imports now explicitly use `.ts`, and Pi's
real loader successfully loads it without the optional i18n package. No task
migration or Perk change is needed. [Tool contract][todo-schema],
[replay implementation][todo-replay].

### @juicesharp/rpiv-ask-user-question

The `ask_user_question` name and questionnaire input remain compatible. New
answer/blocked events and optional partial-answer details extend the interface.
The actual candidate returns structured `no_ui` in a headless context, and the
RPC dialog path with a cancelled selection preserves `cancelled: true`, empty
answers, and the canonical decline text. These probes use fake dialog callbacks;
they do not exercise terminal layout or a real RPC client.

**Exposure change:** the target declares `exposure: "model-only"`. Call the tool
directly; it is no longer a codemode script member. This keeps interactive
questions declared even in Pi's codemode-only mode. Perk's implementation has no
script call to this tool, so no Perk repair is needed; operator-authored scripts
that call it must switch to a direct model call. Optional i18n remains optional,
and both rpiv tools loaded together against the same 2.15.0 config package.
[Target registration][ask-source], [tool and event contracts][ask-schema].

### @dietrichgebert/ponytail

The package still advertises `./skills`, with the exact paths and frontmatter
names Perk requires for `ponytail` and `ponytail-review`. Both candidate files
pass Perk's actual `preflightPonytailSkill` against the isolated installation.
The relevant skill changes add the `off` hint and recognize `shortcut:` comments
alongside older `ponytail:` comments. No source binding changes are required.
[Core skill][pony-core], [review skill][pony-review].

The four empty resource filters remain in force. A real Pi resource-loader
census discovers neither Ponytail's ordinary extension nor its skills, while
loading the other reviewed extensions. Changes to Ponytail's hooks, commands,
and ordinary Pi extension therefore do not enter Perk's review lanes.
[Perk's source-bound preflight][pony-preflight].

## Measured checks

| Check | Result and boundary |
| --- | --- |
| Selected nine-file Node integration set | Baseline **270 PASS**; candidates **270 PASS**, zero skips. Includes the installed-consumer SDK census. |
| Candidate root `npm run typecheck` | **PASS**, without source adaptations. |
| Selected Python compatibility coverage | **81 PASS**, **1 skipped**, 267 deselected. The skip is the below-floor-host refusal case; the current host is admitted. The real-host bridge/load test ran and passed. |
| Candidate artifact assertions | **14 PASS**: rpiv loading, todo calls/persistence/replay/batch, question headless/cancel/exposure, Ponytail preflight/filter settings, plan event handshake, port parity, and both annotation modes. |
| Actual 2.12.0 → 2.15.0 todo envelope | **PASS**, using the published old producer and new replay implementation. |
| Actual Pi resource-loader census | **PASS**: reviewed extensions loaded; Ponytail extension and ordinary skills absent. |
| Fresh Pi CLI registration census | **PASS**: 65 registered tools, all expected reviewed-package tools present, no extension-load errors; no model turn. |

The standalone artifact assertions were temporary scripts in the scratch copy,
not a new committed test framework. Their plan-session starter, RPC dialogs, and
annotation HTTP wrapper are test stand-ins; the candidate listener, tool
implementations, annotation handler, and origin guard are the published code.

### Reproduction entrypoints

In an independent copy at the recorded Perk revision, use Node 26.12.1, run
`npm ci --ignore-scripts`, and install the fixed candidate graph:

```bash
npm install --prefix .pi/npm --legacy-peer-deps --ignore-scripts --save-exact \
  pi-subagents@0.81.0 pi-web-access@0.44.0 \
  @plannotator/pi-extension@0.28.30 @juicesharp/rpiv-todo@2.15.0 \
  @juicesharp/rpiv-ask-user-question@2.15.0 @dietrichgebert/ponytail@5.3.2
npm run typecheck
node --test --test-concurrency=4 \
  extension/substrate/nativeSdkBridge.test.ts \
  extension/substrate/toolGating.test.ts extension/substrate/toolMatrix.test.ts \
  extension/pi/v1/providers/plannotator.test.ts \
  extension/pi/v1/providers/plannotatorHandoff.test.ts \
  extension/pi/v1/providers/plannotatorPort.test.ts \
  extension/pi/v1/providers/annotations.test.ts \
  extension/pi/v1/annotationReadiness.test.ts extension/waves/ponytail.test.ts
uv run pytest -n0 -q \
  tests/test_native_sdk_bridge_live.py tests/test_native_sdk_bridge_parity.py \
  tests/test_skill_exposure.py tests/test_subagent_agents.py \
  tests/test_tool_matrix_postures.py tests/test_doctor.py \
  -k 'ponytail or native_sdk_bridge or skill_exposure or subagent_agents or tool_matrix_postures'
```

The real-host test requires an independent Pi **1.4.0** CLI on `PATH` as well as
the project packages. The measured Python command used `uv run --project` with
the main checkout's existing Python environment and absolute test paths into the
scratch copy; its Perk source was the same recorded revision. Scratch Pi settings
selected only Perk, pi-subagents, and these five exact artifacts, preserving
Ponytail's resource filters. Unrelated pi-diff/pi-fff packages were excluded from
the candidate runtime census.

Target npm tarball identities, checked by npm during acquisition:

```text
pi-web-access@0.44.0
sha512-8YK2Nb0P7ezRL0FS7P1cPYu7gDUOuhXWA3FOBev0bKsuPtG2QrDVm2GriKBgZI1Sq7SC8QRsfVFYYP8huUEo8w==
@plannotator/pi-extension@0.28.30
sha512-smnaY4zBGMyQpq87YQ+orodqfeWf0KpeucY0W/4Pz6n4YsFuMMtSluzeXtLK0MlndWdC1/fjSThaxeIaNE6bSw==
@juicesharp/rpiv-todo@2.15.0
sha512-8WfYssdgQgSWzFNsRzdw5Z6ZJIjO2ecM/YqEzYpR/ore+Hh5aNmafGVy94uFbIofAv2wGGitx5e3J/ucRrViXQ==
@juicesharp/rpiv-ask-user-question@2.15.0
sha512-Gm6de5IZF52BaSeh9dnDqJBn821Z5XfJkCmhkCmqTzvNv3SCpSv1mA4Gj5VBcfrSe+xTtWSVQzJwIqJFQHH3Lg==
@dietrichgebert/ponytail@5.3.2
sha512-AjJnMi54AXO55kXi0ISNPacLuTjb7e9V4lV2oidyxBOnVoPih8CIAmnfHgwX2VyPsDqwQhJthJ9bNu30MaHuOg==
```

## Limits and next action

Proceed with the five reviewed updates and restart Pi. The assessment leaves
Pi/pi-subagents unchanged and establishes no verdict for later `latest` artifacts
or additional packages included by a blanket update.

Interactive browser/terminal drives, external provider/model requests, remote
runners, full CI, and the opt-in prose-review suites were not run. Existing
browser readiness/cancellation tests passed, but live review/reload behavior and
questionnaire rendering remain unverified. No pair-certification stamp or
submission gate is claimed by this document.

[settings]: ../../../.pi/settings.json
[justfile]: ../../../justfile
[pony-preflight]: ../../../extension/waves/ponytail.ts
[web-npm]: https://registry.npmjs.org/pi-web-access/0.44.0
[plan-npm]: https://registry.npmjs.org/@plannotator/pi-extension/0.28.30
[todo-npm]: https://registry.npmjs.org/@juicesharp/rpiv-todo/2.15.0
[ask-npm]: https://registry.npmjs.org/@juicesharp/rpiv-ask-user-question/2.15.0
[pony-npm]: https://registry.npmjs.org/@dietrichgebert/ponytail/5.3.2
[web-changes]: https://github.com/nicobailon/pi-web-access/blob/d0e323ac935e8753d11e1853b81c057e39dee4dc/CHANGELOG.md
[web-source]: https://github.com/nicobailon/pi-web-access/blob/d0e323ac935e8753d11e1853b81c057e39dee4dc/index.ts
[plan-events]: https://github.com/backnotprop/plannotator/blob/bbcaa97c1478fd5d75697022c10086878f8beef0/apps/pi-extension/plannotator-events.ts
[plan-network]: https://github.com/backnotprop/plannotator/blob/bbcaa97c1478fd5d75697022c10086878f8beef0/apps/pi-extension/server/network.ts
[plan-annotations]: https://github.com/backnotprop/plannotator/blob/bbcaa97c1478fd5d75697022c10086878f8beef0/apps/pi-extension/server/external-annotations.ts
[plan-origin]: https://github.com/backnotprop/plannotator/blob/bbcaa97c1478fd5d75697022c10086878f8beef0/apps/pi-extension/server/request-origin-guard.ts
[todo-schema]: https://github.com/juicesharp/rpiv-mono/blob/ce6d3530410812ca504ec294995581a52170f9e1/packages/rpiv-todo/docs/tool-schema.md
[todo-replay]: https://github.com/juicesharp/rpiv-mono/blob/ce6d3530410812ca504ec294995581a52170f9e1/packages/rpiv-todo/state/replay.ts
[ask-source]: https://github.com/juicesharp/rpiv-mono/blob/ce6d3530410812ca504ec294995581a52170f9e1/packages/rpiv-ask-user-question/ask-user-question.ts
[ask-schema]: https://github.com/juicesharp/rpiv-mono/blob/ce6d3530410812ca504ec294995581a52170f9e1/packages/rpiv-ask-user-question/docs/tool-schema.md
[pony-core]: https://github.com/DietrichGebert/ponytail/blob/16352ac229eb08a9598dcae48fe9f2b342567d86/skills/ponytail/SKILL.md
[pony-review]: https://github.com/DietrichGebert/ponytail/blob/16352ac229eb08a9598dcae48fe9f2b342567d86/skills/ponytail-review/SKILL.md
