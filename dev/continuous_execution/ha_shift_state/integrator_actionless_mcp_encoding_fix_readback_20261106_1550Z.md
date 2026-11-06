# HA integrator — Worker B MCP transfer-encoding repair readback

**2026-11-06 15:50Z. CHECKS PENDING / AWAITING CI / NO LIVE ACCEPTANCE.**
Owner-authorized HA integrator, ChatGPT Chat Mode only. This is source-pinned **offline diagnostic evidence**, not a qualified independent review. Owner temporary **NO GITHUB ACTIONS** order remains in effect. No RE-Wizard reads/writes, model API, task changes, provider substitution, binaries, games, archives, or approval bypass.

## Exact source inventory and delta

- Pre-audit main from prior integration handoff: `b3421cb8535532d8df50c32207d555629e5e5607`.
- Fresh verified main before this evidence write: `4b64e28edee7ee16817149e3ec059f7e3751d9ca`, at 2026-11-06 15:34:52Z (latest commit).
- GitHub compare `b3421cb8...4b64e28e`: **two commits, one changed source file**, `_app/hivemind_assembly/integrations/mcp.py`, 43 insertions, 17 deletions in aggregate.
- Worker B changes: `c195f27681e6bef9972f31e2f2cc317bd9419d5d` adds normalized standalone transfer-encoding checks and MIME alias validation; `4b64e28edee7ee16817149e3ec059f7e3751d9ca` also rejects blob/data paired with alternate MIME aliases.
- Current **mcp.py blob**: `f9df5466519b644e8efd854ca727c2daf0f8ca9f`.
- Current **verifier MCP tests blob**: `63bbe71cc8ea3ea146c1733e2976328717b81a53`; **14 authored top-level test functions**. They do not yet explicitly exercise transferEncoding/contentTransferEncoding, contentType/mediaType, or cross-spelling MIME encoding conflicts.
- Focused workflow `.github/workflows/chatmode-native-events.yml` blob `b1b05f6c68bbef589a73bb40b0b1ae2757cac183`: **15 unique explicit pytest module paths**, no repeats; `tests/test_native_event_inbox.py` imports the two additional receipt/reconciliation verifier modules. Do not explicitly select them a second time.
- Whole-project `.github/workflows/test.yml` blob `094ac74c77d5b6f7a08664ae45ecc6392cc78ac2` already pins local browser-fixture to `ubuntu-24.04`, with other jobs unchanged. No workflow edits required this run.

## Source-level security result

The specific gap reported in `integrator_actionless_mime_contract_review_20261106.md` is now **source-addressed**, not independently test-accepted:

1. `_plain_source_encoding()` only allows explicit `utf-8`, `us-ascii`, or `identity` (with bounded harmless aliases), rejecting malformed/non-plain encodings.
2. `_validate_source_text_mime()` recognizes `encoding`, `contentencoding`, `transferencoding`, and `contenttransferencoding` MIME parameters, including hyphen/underscore/case spellings and contradictory repeat values.
3. `reject_remaining_media()` recursively applies the same normalized encoding keys to nested structured metadata; untrusted `contentType`/`mediaType` aliases are now validated as MIME declarations, not only `mimeType`.
4. Encoded `blob`/`data` with any of `mimeType`, `contentType`, or `mediaType` now fails closed. The previously reviewed resource-link/rel checks are unchanged.
5. This changes HA's own inline-source response normalization only; it **does not** change third-party hosted GitHub MCP file materialization or ChatGPT host approvals. It does **not** establish that any external MCP result or browser request was observed.

### Permitted deterministic local probe

An available Python interpreter executed **33 isolated tests of manually copied pure source predicates** from current mcp.py: `_validate_source_text_mime()` 20/20 expected classifications, and `_plain_source_encoding()` 13/13 expected classifications. Included positive UTF-8/ASCII/identity/plain JSON, harmless unknown MIME parameter and equivalent aliases; negative base64/gzip/hex/UTF-16, legacy charset, conflicting charset/repeated transfer alias, malformed control, empty encoding, nontext MIME and overlong declaration. **These are copied-predicate tests only**: no HA imports, MCP SDK/client calls, HTTP, actual module `inline_github_mcp_text()` calls or release verification. Source/future-handoff evidence must not present 33/33 as HA pytest passing.

### Actual-module regression cases to add (verifier-owned)

For every case, wrap in an ordinary inline text MCP `content` block plus optional `structuredContent.metadata`; assert `Blocked` for negative cases, and no resource link / blob / URL escape:
- `contentTransferEncoding: base64`, `transferEncoding: gzip`, `Content-Transfer-Encoding: base64`, `TRANSFER_ENCODING: utf-16`; contrast `contentEncoding: utf-8`, `transferEncoding: identity`.
- `contentType: application/octet-stream`, `mediaType: image/png`, and `contentType: text/plain` with sibling `data: YQ==` or `blob: YQ==`; contrast harmless `contentType: text/plain` and informational `documentation_url`.
- Conflicting `mimeType`/`contentType`, repeated transfer-encoding aliases with different normalized values, malformed/non-string/null encoding values, safe text with `rel: help` documentation URL and blocked list/compound `rel: download` link.
- Execute the actual `Connections._external()` stub with this data, so a source guard does not produce a false assertion about attachment return. Preserve authorization and revoke-after-await tests.

Worker B owns source repair if any actual-module negative fails. The verifier owns regression tests and negative/positive source review. **Integrator must not edit these production or verifier files.**

## Distinct unresolved blocker and no-Actions status

Current `_app/hivemind_assembly/core/durable_effects.py` blob `6ffd9a0c2cafd0717aa623b825d97dec5bb8693a` still validates only the existence of one matching event in `DurableEventEffects.finalize()` instead of checking the entire saved request task/project/owner/epoch and all event inputs. It calls `_fence` only at entry to the transaction, not after receipt processing, leaving a late lease clock-expiration window. Current receipt-scope verifier blob `e946a5b664c3c646f8502883172e3a7b8caec7bf`. Core maintainer—not integrator—must repair while modernizing legacy test fixtures, then obtain independent qualified security review.

Historical whole-HA Ubuntu/Windows failures, Windows Unicorn/Speakeasy native crash, and successful local Chromium fixture tests belong to earlier immutable source revisions. They are **not** current-source passes. Real HA ChatGPT Chat Mode native browser receipt, restart/reconciliation, provider and external MCP acceptance remain pending.

Read-only workflow header audit at this source: broad `test.yml` listens to all pushes; other 20 workflows are path-filtered, manually dispatched or triggered by successful `workflow_run` / tags. No evidence-only path meets another workflow's source/trigger paths. Because `[skip ci]` suppresses eligible push/PR workflows but cannot guarantee every event type, check for new Actions runs after each push. No Actions or self-hosted runs may be initiated, enabled, rerun, or dispatched. GitHub quotas are owner-restricted.

**Execution accounting this invocation:** 33 isolated copied-predicate checks executed (33 expected); **zero** actual HA pytest tests, **zero** GitHub Actions dispatches, **zero** live browser/provider/external MCP tests. Actual HA Python package/checkout is unavailable locally. A suitable permitted non-Actions full checkout should execute:

```bash
python -m pytest -q tests/test_mcp_inline_text.py tests/test_mcp_connections.py
python -m pytest -q tests/test_core_durable_effects.py tests/test_native_event_inbox.py
python -m pytest -q tests/test_native_event_inbox.py::test_ticket_lifecycle_requires_evidence
```

Those commands are **not executed here**. The second command selects the verifier receipt/reconciliation tests indirectly via native-inbox imports; avoid double-counting. Windows native compiler/oracle reproduction stays separate with no game/archive fetches.

**Next ready milestone:** verifier adds actual-module negative tests for Worker B's encoding/MIME variants; core owner repairs entire saved-request scope and final live-lease fence. Then independently review and run permitted full offline Linux/Windows suites and, only with separate real service access, ChatGPT native-browser/restart acceptance. Maintain **CHECKS PENDING / AWAITING CI**; do not promote or release.
