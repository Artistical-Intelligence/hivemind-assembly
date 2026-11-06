# HA integrator: MCP hypermedia relation bypass review and focused discovery audit

**2026-11-06 — CHECKS PENDING / AWAITING EXECUTABLE TESTS AND QUALIFIED REVIEW.** HA-only ChatGPT Chat Mode. Owner no-GitHub-Actions override applies to public and private repositories. No RE-Wizard access, model API, alternate surface, automated MCP attachment download, hosted file materialization, game/archived compiler tests, unauthorized production/verifier edits, or approval bypass.

## Exact-source checkpoint

- Read-only starting `main` commit: `98cf0bd40b3cc2f61f18bda8d289ba65a36156de` (source snapshot; do not interpret historical CI as current-head passing).
- Worker B production: `_app/hivemind_assembly/integrations/mcp.py` blob `40e2bc584c0c0d4fe7b265963e6fe379f34da837`, specifically `inline_github_mcp_text()` and nested `reject_remaining_media()`, approximately lines 290-470.
- Verifier-owned tests: `tests/test_mcp_inline_text.py` blob `63bbe71cc8ea3ea146c1733e2976328717b81a53`. It has a positive informational documentation URL fixture and existing nested file/encoded-media negatives, but no dedicated `rel` multi-token/list/contradictory-key negatives in the inspected source.
- Focused `.github/workflows/chatmode-native-events.yml` blob `820702519a7d3ee57342197e2114daeae0a37e6c`. Read-only test inventory: all seven `tests/test_ha_event_*.py` modules are selected (five directly, two imported from `test_native_event_inbox.py`); the explicit pytest CLI includes 14 distinct direct paths without duplicates. **No workflow edit needed.**

## Newly isolated source-level issue: unconverted downloadable hypermedia relation

Within `inline_github_mcp_text()`, `reject_remaining_media()` rejects link-like metadata when the `rel` value is a **single exact string** such as `"download"`, and one of `href/url/uri/path/location` exists. It does **not** recognize a whitespace-delimited multi-relation string, an array relation or a dangerous `relation` when a harmless `rel` key is also present. The generic untyped `href` key is intentionally not banned, so these cases do not meet the other typed-link, MIME, URI-key or named-descriptor checks when only an untyped `href` is supplied.

Proposed minimal input shape for Worker B/verifier to test against the **actual** production function in a complete HA checkout:

```python
response = {
    "content": [{"type": "text", "text": "inline source"}],
    "structuredContent": {"metadata": {"links": [
        {"rel": ["download"], "href": "https://example.invalid/private.zip"},
    ]}},
}
inline_github_mcp_text(response)  # should raise Blocked, not pass linked metadata
```

Additional adversarial variants for the same nested link: `{"rel":"help download","href":"https://example.invalid/private.zip"}`, `{"rel":"help","relation":"download","href":"https://example.invalid/private.zip"}` and `{"relation":["download"],"href":"https://example.invalid/private.zip"}`. For comparison, `{"rel":"download","href":...}` already satisfies the guard, and `{"rel":"help","href":"https://example.invalid/docs"}` must remain an allowed informational link. No URL in this review was fetched.

**Executed isolated predicate probe:** I copied only the exact `relation = value.get("rel", value.get("relation"))` check from the source into a local Python scratch function, then evaluated five synthetic dictionaries. Guard decisions were: single `download` = true (rejected by this guard); `help download` = false; `["download"]` = false; `relation:["download"]` = false; documentation `help` = false. **This is a real execution of an extracted predicate, NOT execution of the imported HA function, full MCP bridge, unit tests or provider flow.** The contradictory two-key case is a source-inferred additional candidate and was not included in the five-case probe. The full bridge rejection/passthrough must be verified with the actual module.

Impact is exposure of an *unconverted downloadable URL descriptor* in a supposed text-only source-read result, not automatic execution or a confirmed download. This can weaken HA's own inline text boundary but does not imply that ChatGPT's separate hosted attachment/materialization approval was bypassed.

## Repair ownership and nonregression contract

**Worker B alone** should harden nested hypermedia relation interpretation in `mcp.py`: normalize tokenized strings and relation lists; fail closed on unsupported/malformed relation types accompanying a link; inspect both `rel` and `relation` if provided rather than silently privileging one; reject a file/download relation regardless of token order/case while retaining harmless documentation URLs. Avoid a blanket ban on `href` that would break ordinary metadata. Do not weaken grants, size limits, binary checks or tool-name mediation.

**Verifier alone** should add positive/negative tests to its owned `test_mcp_inline_text.py`; include nested structuredContent and harmless URL controls, plus a fake MCP source-read route to confirm links do not reach the caller. Run `python -m pytest -q tests/test_mcp_inline_text.py` with the exact Worker B source commit in an authorized local non-Actions checkout and record every test/method count, pass/fail/error/skip and independent reviewer. Integrator must recheck any workflow test-selection delta after those commits, not preempt worker-owned source or tests.

## Separate outstanding HA acceptance blockers

- `_app/hivemind_assembly/core/durable_effects.py` blob `6ffd9a0c2cafd0717aa623b825d97dec5bb8693a`: `_contains_exact_event()` uses existential `any()` on event inputs; `finalize()` verifies the saved message task/route but does not enforce full saved packet project, task, modern owner/epoch and *all* event-input scope. The existing negative tests in `test_ha_event_receipt_scope.py` and `test_ha_event_uncertain_reconciliation.py` capture the intended fail-closed contract. `finalize()` also lacks the final live-lease check immediately before marking the event read. Core source is assigned to the separate interactive maintainer; **no integrator source edits or unauthorized review approval**.
- Historical Actions may be read, but never replayed or labeled current. Full HA Windows/Linux regressions, Windows Unicorn/Speakeasy native exception analysis, actual external MCP/ChatGPT browser delivery/restart, and independent security/reviewer acceptance remain open.

## Execution and conservation receipt

- GitHub Actions created/dispatched/retried: **0**. Full-package Python/pytest tests: **0**. Live browser/provider tests: **0**. Isolated extracted-predicate Python cases actually exercised: **5**, expressly nonintegration evidence. No complete permitted local HA checkout was obtained; no binaries, dependencies, credentials or private data downloaded.
- No changes to production sources, verifier tests, CI workflows, task schedules, ownership, roles, provider or RE-Wizard. Keep `CHECKS PENDING` and the owner-wide no-Actions restriction.
- Next independent milestones: Worker B relation-gate patch + verifier current-source negative tests; core owner receipt authorization/expiry fix + positive fixture modernization; non-Actions executable cross-platform validation in a complete authorized checkout; actual native browser/provider and independent security acceptance.
