# HA integrator — source-pinned MIME and encoded-metadata contract audit

**2026-11-06 — CHECKS PENDING / AWAITING CI / NO LIVE ACCEPTANCE.** Owner-authorized ChatGPT Chat Mode HA integrator; docs/evidence only. **Do not initiate GitHub Actions** or access RE-Wizard. This is not a production-code repair or independent qualified security acceptance.

## Immutable source reference and change delta

- Observed `main` HEAD: `3408459795b28d35680a373bf1af84098c107956` (2026-11-06 14:37:19Z), following Worker B's `865cf71d81dc9ed1c7a3ebf3c4f27040dca02500` and `3408459795b28d35680a373bf1af84098c107956` MIME-hardening commits.
- `_app/hivemind_assembly/integrations/mcp.py` blob `f54d58865a377a90764cc5c12e04860cf274c78e`; `tests/test_mcp_inline_text.py` blob `63bbe71cc8ea3ea146c1733e2976328717b81a53` (14 authored top-level test functions, not parametrized collection count).
- `_app/hivemind_assembly/core/durable_effects.py` blob `6ffd9a0c2cafd0717aa623b825d97dec5bb8693a`; `_app/hivemind_assembly/automation/event_inbox.py` `aaa677450208dec69117158ac55bf91d7f46dde8`; `tests/test_native_event_inbox.py` `903acf46d71d6bcbfc16b5b9ae7a6a3ab91d9d7f`.
- Focused `.github/workflows/chatmode-native-events.yml` blob `b1b05f6c68bbef589a73bb40b0b1ae2757cac183`: 15 unique explicit pytest modules, including MCP. All eight `test_ha_event_*.py` files are included either explicitly (six) or by explicit test imports at `tests/test_native_event_inbox.py` lines 551 and 563 (receipt-scope and uncertain-reconciliation). Do not add those two explicitly and duplicate collection. Broad `.github/workflows/test.yml` blob `094ac74c77d5b6f7a08664ae45ecc6392cc78ac2`, browser fixture pinned to ubuntu-24.04.

## Newly narrowed source contract and unresolved encoded-metadata variant

Worker B's new `_validate_source_text_mime()` (mcp.py lines 46–78) rejects non-text MIME, malformed controls, non-UTF-8 charset, conflicting charset and MIME *parameters* declaring disallowed encodings. The recursive `reject_remaining_media()` (lines 326–584) checks all nested MIME aliases and explicitly checks structured metadata keys `encoding` / `contentEncoding` (lines 502–510). It does **not** check metadata keys normalizing to `transferencoding` or `contenttransferencoding`. The MIME **parameter** checks cover those spellings inside a MIME string, but not at the separate dictionary-key layer.

Thus the following **candidate negative fixture** has a declared encoded payload indicator that is not rejected by that particular recursive-encoding guard (actual full function not executed here):

```python
{"content": [{"type": "text", "text": "source"}],
 "structuredContent": {"metadata": {"contentTransferEncoding": "base64"}}}
```

Try also `transferEncoding=gzip`, `Content-Transfer-Encoding=base64`, `TRANSFER_ENCODING=utf-16`; contrast with already recognized `contentEncoding=base64`. A distinct `content_type=application/octet-stream` metadata key is not treated as `mimeType` by the same recursive MIME parser, and merits a separate compatibility/negative analysis, not a blanket assumption that every `contentType` is a real media declaration. **Scope:** this is a source-level policy gap/hypothesis about encoded metadata, **not** proof of binary download, credential disclosure, outbound attachment materialization or a hosted ChatGPT approval bypass.

The owner-approved local Python interpreter executed **eight isolated copied-predicate classification checks**, all matching the exact visible normalized-key branches: `encoding`, `contentEncoding`, `Content-Encoding` recognized; `transferEncoding`, `contentTransferEncoding`, `Content-Transfer-Encoding`, `TRANSFER_ENCODING`, `content_type` not recognized by that specific branch. These are **not** tests of the imported HA function, SDK client, browser or full package.

**Worker B production handoff:** evaluate fail-closed support for alternative transfer-encoding and content-type metadata declarations while preserving safe UTF-8/JSON and informative documentation URLs; run actual `inline_github_mcp_text()` local fixtures before classifying exploitable vs benign. Do not modify hosted GitHub MCP platform controls or broaden read permissions.

**Verifier test handoff (separate owner):** add actual-function negative fixtures for `mimeType="text/plain; charset=windows-1252"`, `mimeType="text/plain; Content-Transfer-Encoding=base64"`, nested `contentTransferEncoding=base64` / `transferEncoding=gzip`, unusual media subtype, and type/MIME alias contradictions. Preserve positives for plain text/JSON, allowed UTF-8/US-ASCII, harmless `documentation_url`, and normal `rel=help`. Do not grant a success verdict from isolated predicate checks. Current verifier test blob predates the two newest MIME commits.

## Distinct, still-open integration defects

- Legacy `tests/test_native_event_inbox.py::test_ticket_lifecycle_requires_evidence` expects acceptance from a queued task and fabricated artifact hash; Worker A's actual `record_ticket()` requires matching controller accepted state, retained positive acceptance record and project-owned artifact. This remains a **predicted test-source incompatibility**, not an executed test failure. Verifier must modernize the positive fixture, *not* weaken Worker A's guard.
- Core `DurableEventEffects.finalize()` at the immutable core blob still checks only existence of an exact event within a validated receipt's `body.event_inputs` but does not validate the whole saved request's task/project/owner/epoch bindings or refence the live task lease at final write. Separate core maintainer owns repair. Its tests' absence of strict bindings must not relax runtime authorization.
- Windows Unicorn/Speakeasy native memory faults seen in historical broad suite are a separate owner-unassigned reproduction lane; not a reason to treat current integration suites green.

## CI/no-Actions compliance and executable next milestone

Read all 22 workflow `on:` headers: the broad `test.yml` listens for any push, while `release.yml` listens for completion of the broad contracts workflow and tag pushes. Documentation-only `[skip ci]` commits have not generated newer runs in the read-only listing; nevertheless skipped required checks can remain pending and no Actions may be dispatched, rerun or enabled. Last visible read-only Actions runs at SHA `966d4de9296b94abf74c38ae9229ca643faca513` are historical only (latest listed 2026-11-06 03:15:41Z), **not** current source-bound acceptance.

At a permitted full non-Actions checkout, run:
```bash
python -m pytest -q tests/test_mcp_inline_text.py tests/test_mcp_connections.py
python -m pytest -q tests/test_native_event_inbox.py::test_ticket_lifecycle_requires_evidence tests/test_ha_event_receipt_scope.py tests/test_ha_event_uncertain_reconciliation.py
```
Record the exact HEAD and per-case outcomes; the first command may pass without newly authored negative fixtures. Current environment has a Python interpreter but **no installed HA package or full checkout**, so package-level pytest was **not executed**. Work for this checkpoint: **8 isolated predicate checks executed, 0 actual HA tests, 0 GitHub Actions initiated, 0 live ChatGPT browser/external MCP tests**. Whole-HA Linux/Windows tests, verified core repair, qualified independent security review, real native browser response/restart and external MCP acceptance all remain **CHECKS PENDING / AWAITING CI**. No provider, task, release or other project changes.
