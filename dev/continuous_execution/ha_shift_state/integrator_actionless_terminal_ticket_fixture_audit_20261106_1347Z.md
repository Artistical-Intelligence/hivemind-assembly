# HA integrator — terminal ticket contract / MCP alias negative-review checkpoint

**2026-11-06 13:47Z — CHECKS PENDING / AWAITING CI / NO LIVE ACCEPTANCE.** Owner-authorized HA Chat Mode integrator. **Do not trigger GitHub Actions** on private or public repos. This is exact-source static diagnosis and a separate-owner handoff, not a passed test or release approval.

## Exact source baseline

- Read main at `cc415685f2c36d34673a7255c96382fa67d6c3fc` (2026-11-06 13:40:29Z), compared to previous integration anchor `64e9c9ce3e42629d794b32fcbcfdfb9189cd05ef` (five commits ahead, zero behind).
- New Worker A source blobs: `_app/hivemind_assembly/automation/event_inbox.py` `aaa677450208dec69117158ac55bf91d7f46dde8`; `progress_watchdog.py` updated (rejects coerced boolean/string clocks in `scan_delivery_health`/`scan`).
- New Worker B source: `_app/hivemind_assembly/integrations/mcp.py` blob `e67002df06954cc823f1b391048f726027b4f9e7` (three source commits `23262c7d7edc1e80105b74f068c41fb116951479`, `38237816bc4b3132e51d926c83e8cecffd053eb1`, `cc415685f2c36d34673a7255c96382fa67d6c3fc`).
- Existing verifier files: `tests/test_native_event_inbox.py` blob `903acf46d71d6bcbfc16b5b9ae7a6a3ab91d9d7f`; `tests/test_mcp_inline_text.py` blob `63bbe71cc8ea3ea146c1733e2976328717b81a53`. Store fixture source `_app/hivemind_assembly/core/store.py` blob `7c3fe3c7267f1721d751a06aef51ec7a2e2c239e`.
- The focused `.github/workflows/chatmode-native-events.yml` remains blob `b1b05f6c68bbef589a73bb40b0b1ae2757cac183`: 15 explicit test-module paths, Linux/Windows matrix. No workflow edit in this checkpoint. `.github/workflows/test.yml` already pins browser-fixture to `ubuntu-24.04`; leave unchanged.

## Deterministic source incompatibility — verifier-owned legacy positive case

`test_native_event_inbox.py::test_ticket_lifecycle_requires_evidence` creates a project with `Store.create_project(...)`, which initializes task status to `queued` (`store.py`). The test then calls `inbox.record_ticket(task_id, "accepted", artifact_sha="abc123", run_id="turn-b")` and asserts success, without changing controller task status, inserting a valid retained acceptance_result, or storing a matching artifact.

Worker A's new `record_ticket()` (in `event_inbox.py` around lines 150–200) explicitly refuses terminal `accepted` unless the controller task status itself equals `accepted`; it then checks retained same-task positive independent acceptance and the project-scoped artifact SHA. Thus that old positive call is **source-deterministically incompatible**: it will raise `ContractError("Terminal ticket requires matching controller state")`, not return a ticket. It is present in the focused pytest selection and the entire `tests` suite. **This is a predicted regression, not a newly observed Python failure.**

**Verifier-owned repair:** preserve the security fence. Rewrite the old positive branch to create a genuine controller accepted state, retained `acceptance_result` for that task with literal `passed: true`, and matching project-owned artifact. Add explicit *negative* cases (queued task with plausible digest, accepted task without valid acceptance, cross-project artifact, mismatched supplied SHA, replay after terminal). Reuse existing newer `test_ha_event_receipt_envelope_worker_a.py` positive fixture rather than weakening `record_ticket`. Worker A should independently review any needed error-semantic changes; integrator **must not edit** verifier tests or Worker A source.

## MCP newly hardened branches, missing current function-level regression

Current `mcp.py` traverses and rejects conflicting aliased `TYPE/type`, `RESOURCE/resource`, `MIME_TYPE/mimeType`, encoded-content aliases (e.g. `BASE64_DATA`, `hexData`, `CONTENT_ENCODING` when not plain text), mixed-case resource-link keys, typed URL+MIME and invalid nested descriptors. The actual `tests/test_mcp_inline_text.py` still contains 14 top-level authored test functions at the older blob and has no dedicated relation-list/contradictory rel/relation, aliased TYPE/RESOURCE/MIME, `hexData`/`binaryData` or `CONTENT_ENCODING=gzip` real-function controls.

**Verifier-owned follow-up:** import the real `inline_github_mcp_text()` and `Connections` fake SDK for negative cases: (`{"TYPE":"Resource_Link","uri":"repo://binary"}`), conflicting `type=text` plus `TYPE=resource_link`, `RESOURCE` object nested under safe text, `MIME_TYPE=image/png` with `URL`, `BASE64_DATA`/`hexData`/`binaryData` metadata, `Content-Encoding=gzip`, `rel:["download"]`, `rel:"help download"`, contradictory `rel` vs `relation`. Confirm positive ordinary UTF-8 text/JSON, informational `documentation_url`, harmless `rel:help`, and bounded inline resource mirrors. Do not assume those cases currently pass or fail until run against the real module. Worker B retains production ownership.

## Additional integration/CI evidence and limits

- Read-only GitHub compare shows **only** Worker A `event_inbox.py` / `progress_watchdog.py` and Worker B `mcp.py` changed since `64e9c9ce...`; no current verifier test or integration workflow changes.
- Static audit fetched all 15 focused selected test files: 129 top-level functions named `test_...` (not pytest-collected/parameter-expanded count); the native inbox has the stale terminal case; MCP test module 14 top-level test functions. Existing verifier receipt modules are imported by `test_native_event_inbox.py`, so avoid duplicate explicit workflow selection.
- Owner-wide no-Actions restriction: **zero** Actions dispatched/rerun, **zero** full HA Python tests, **zero** real browser/provider/external MCP tests in this checkpoint. No complete permitted HA checkout was provided to this execution environment. Old GitHub run 42152630477 at `966d4de9296b94abf74c38ae9229ca643faca513` is historical failure context only, not current-source acceptance.
- Core `_app/hivemind_assembly/core/durable_effects.py` unchanged blob `6ffd9a0c2cafd0717aa623b825d97dec5bb8693a`; its complete saved-request scope and final live lease validation are independently owned and still unresolved. Windows Unicorn/Speakeasy diagnostic remains an unrelated owner-unassigned blocker.
- No RE-Wizard project/task/code read or written. No paid API, provider/mode change, GitHub permission/approval bypass, binary or file attachment retrieval.

## Next executable milestone

On a **permitted non-Actions full HA checkout**, first execute:
`python -m pytest -q tests/test_native_event_inbox.py::test_ticket_lifecycle_requires_evidence tests/test_ha_event_receipt_envelope_worker_a.py tests/test_mcp_inline_text.py`
and record the exact tested HEAD, failures and reason. Obtain actual verifier-owned fixture/test updates before making a source-bound suite claim. Run whole Linux/Windows checks only after the owner lifts the Actions ban or permits a genuinely non-Actions environment, and keep **CHECKS PENDING / AWAITING CI** plus independent security and real native ChatGPT browser/restart acceptance open.
