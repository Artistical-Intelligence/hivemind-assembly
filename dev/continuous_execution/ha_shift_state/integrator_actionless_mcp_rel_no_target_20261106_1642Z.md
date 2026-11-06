# HA integrator — source-only MCP relation/no-target negative audit

**2026-11-06 16:42Z. CHECKS PENDING / AWAITING CI. Owner temporary no-GitHub-Actions override is in force.**

## Exact immutable inputs and role boundary

- Starting **main source commit**: `9eb75401182a1f02c27fdd8976950a507319e6ac` (Worker B's `fix(mcp): validate resource relations without explicit link target [skip ci]`).
- `_app/hivemind_assembly/integrations/mcp.py` **blob**: `962c649e85a160e193ac0a634d4249f1c59fa4f3`.
- `tests/test_mcp_inline_text.py` **blob**: `63bbe71cc8ea3ea146c1733e2976328717b81a53` (14 authored test functions, parameter expansion not counted).
- `.github/workflows/chatmode-native-events.yml` blob `b1b05f6c68bbef589a73bb40b0b1ae2757cac183`: includes MCP test module in its 15 distinct direct pytest paths; additional event verifier modules are collected via imports.
- `.github/workflows/test.yml` blob `094ac74c77d5b6f7a08664ae45ecc6392cc78ac2`: browser fixture already uses `ubuntu-24.04`; the broad push trigger must not be invoked under owner no-Actions override.
- Integration role **must not write** Worker B production modules or verifier-owned tests. No RE-Wizard source or tasks accessed.

## Source-bound finding

Worker B's latest source change removes the `has_link_target` condition on `rel`/`relation` metadata. The recursive media validator therefore rejects a forbidden role even when a malicious/irregular wrapper omits `href`, `url` or `uri`, or supplies only `documentation_url`. All spelling aliases of `rel`/`relation` are inspected; list and compound-delimited roles are normalized; conflicting duplicated role declarations block. This is a sensible **source-level fail-closed fix** to the previously reported no-target relation path, **not an independently accepted complete MCP transport repair**.

The embedded `type=resource` conversion also calls `_validate_source_text_mime(mime)` **before** dropping the wrapper, including transfer-encoding and content-transfer-encoding MIME parameters. This correct order was confirmed from the current exact source. Nested structured metadata separately applies encoding and MIME guards. No new bypass of those guards was demonstrated in this review.

### Deterministic *isolated*, copied-predicate exercise

A permitted local Python interpreter executed the exact relation-guard algorithm copied from `mcp.py` lines approximately 450–504 against **24 synthetic dictionaries**: **16 expected rejections and 8 expected approvals, all matching the expected predicate classifications**.

Blocked examples: bare `rel=download` with no target; `rel=download` plus only `documentation_url`; casefolded `REL=DoWnLoAd`; whitespace/semicolon/hyphen/underscore compound download, artifact or attachment roles; array `[next, download]`; `relation=attachment`; mismatched `rel`/`relation` and `rel`/`REL`; truthy numeric, mapping, empty list and blank relation declarations. Positive examples: ordinary `help`, `self`, `help next` list, equivalent repeated aliases, `help-center`, and informational documentation URLs with or without a benign relation.

**Limit of this result:** manually copied Python predicate, NOT imported `inline_github_mcp_text()`, NOT `Connections._external()`, NOT actual HA pytest, no MCP SDK, no browser or third-party hosted connector. **Executed actual HA tests: 0.** The current verifier test module does not directly exercise these latest no-target relations, MIME/transfer aliases or contradictory relation keys. Do not treat 24/24 as a release or security acceptance gate.

## Verifier-owned actual-function negative and positive tests

On the exact source revision above, extend `tests/test_mcp_inline_text.py` without weakening production checks:

1. Negative: `inline_github_mcp_text({"content":[{"type":"text","text":"safe"}],"structuredContent":{"metadata":{"rel":"download"}}})` must raise `Blocked` **without a URL**.
2. Negative: `{"metadata":{"REL":"DoWnLoAd","documentation_url":"https://example.invalid/docs"}}`; `{"metadata":{"rel":["help","download"]}}`; `{"metadata":{"rel":"help","relation":"attachment"}}`; `{"metadata":{"rel":"help","REL":"download"}}` must each raise `Blocked`.
3. Negative: malformed `rel` values such as `null`, integer, dict, blank and empty array; duplicate inconsistent aliases; oversize list/string. Avoid network connections.
4. Positive: `{"metadata":{"rel":"help","relation":["help"],"documentation_url":"https://example.invalid/docs"}}`, plus safe UTF-8 inline resource and `transferEncoding=identity` metadata, must preserve readable text without fabricating a downloadable resource.
5. Run through an authorized **stub of `Connections._external()`** as well as the pure function to verify response withholding and post-await grant revocation. Verify no hosted platform approval was claimed bypassed. Tests must remain under qualified independent verifier ownership.

## Independent upstream semantic spot check

Inline source reads on this invocation: DeepSeek superagent `src/app/effects.ts` blob `9255cda8f7a63ed0e7ab70bb023a5927fe5218d5` (ordered queue, retry/backoff); Grokbot `src/grokbot_kit/terminal.py` blob `58d60328eabec06e48d7c8ebc37847aed19c438a`, `docs/event.md` blob `cbb6e27ab140bad2ede071d94a5a759c6ab71008`; HA `grokbot_event_adapter.py` blob `b8922faacba2bb7a2ac7a837a34bcfae81e6c77a`. Current upstream terminal classification distinguishes `completed/denied/permission_denied` from successful completion and `error/failed/result_invalid`. HA's status/reason admission maps the denial separately to `delegated_denied`; no contradictory semantic mapping found in this **limited source check**. Blind retry of a possibly sent native browser turn would be unsafe; do not adopt DeepSeek's generic effect retry semantics for uncertain ChatGPT browser delivery. No full upstream port or runtime execution claimed.

## Whole-system gates retained

- Core `_app/hivemind_assembly/core/durable_effects.py` blob `6ffd9a0c2cafd0717aa623b825d97dec5bb8693a` still has prior source-identified existential saved-event authorization and missing terminal live-lease recheck; separately owned, **not fixed here**.
- Historical whole-HA Actions 42152630477 at `966d4de9296b94abf74c38ae9229ca643faca513` failed: Ubuntu 1491 passed / 23 failed / 85 skipped; Windows 1465 passed / 17 failed / 117 skipped. Those are **historical evidence only**, not new-current-source CI. Windows Unicorn/Speakeasy remains separately unresolved.
- `test.yml` listens to all pushes, but all potential status/evidence writes must use `[skip ci]`; no Actions runs dispatched, rerun, enabled, or requested, no self-hosted runner, no private source transfer to public CI.
- Newly executed: **24 isolated Python relation-predicate checks**; **0 imported HA tests; 0 Actions; 0 live HA browser, provider, external MCP or reviewer-qualification acceptances.** Tool/model/usage availability was not inferred from filenames, fixtures or status badges.

**Next ready milestone:** verifier implements the actual-module MCP tests above; Worker B handles only failures genuinely reproduced by those tests. Independently repair full durable-effect receipt/lease authorization under its own source owner. Re-run full offline Linux/Windows checks only in a separately confirmed permitted non-Actions environment and obtain real ChatGPT Chat Mode native browser receipt/restart and qualified security acceptance before release. No change to owner no-Actions override or scheduled role.
