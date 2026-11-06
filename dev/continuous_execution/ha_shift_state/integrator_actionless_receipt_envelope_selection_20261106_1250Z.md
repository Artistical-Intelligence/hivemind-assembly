# HA integrator — new retained-receipt regression selection and MCP relation follow-up

**2026-11-06 — CHECKS PENDING / AWAITING EXECUTABLE CI AND QUALIFIED INDEPENDENT REVIEW.** ChatGPT Chat Mode, HA-only. Owner-wide no-GitHub-Actions override remains in force. This note is an integration handoff, not release acceptance.

## Immutable source and changed workflow

- Initial inspected `main` commit: `d07d2fd68fb674984df6b734a610dbd176702c3e` (2026-11-06T12:38:37Z). Related preceding changes: Worker A event-inbox source `44be618d48c1c9550c86357aa108b99ff2e693b3` and standalone tests `61863edaf3f741dc12db359578974e8cb2eb18fa`; Worker B MCP relation hardening `91312a78d7d46d87f6fecb970be09fb985b225f1` and `d07d2fd68fb674984df6b734a610dbd176702c3e`.
- New standalone Worker A test: `tests/test_ha_event_receipt_envelope_worker_a.py`, blob `8f76d8a3dc246bcc12af8643720aab328aaf94ba`. Its ten parametrized pytest cases cover a malformed unrelated acceptance record, missing valid acceptance evidence, a greater-than-20-item saved request, six forged/non-numeric arrival proofs, and a legitimate numeric receipt + restart replay. Authored test function count is five; expanded case count is ten. **Authored is not executed.**
- Production source: `_app/hivemind_assembly/automation/event_inbox.py` includes a SQLite JSON-validity gate for retained acceptance filtering, a 20-event saved-request bound, and an exact-type numeric arrival proof check (avoid Python `True == 1.0`). The implementation changes remain worker-owned and independently unaccepted.
- Before integrator correction, focused `.github/workflows/chatmode-native-events.yml` blob `820702519a7d3ee57342197e2114daeae0a37e6c` had `tests/test_ha_event_*.py` in its **push trigger** but omitted the new standalone module from explicit `python -m pytest` arguments. The selected `tests/test_native_event_inbox.py` contains no import of this new module. Consequently, a trigger was not proof of collection.
- **Integrator correction:** commit `f33f16cd1f3538c9a8fb2a3ad0a1d487d52f400c`, new workflow blob `b1b05f6c68bbef589a73bb40b0b1ae2757cac183`, adds `tests/test_ha_event_receipt_envelope_worker_a.py` once to the existing focused Linux/Windows pytest invocation. No runner, workflow dispatch, permissions, credential, concurrency, browser-fixture, broad `test.yml`, verifier-owned tests, or worker-owned source changed. Existing `tests/test_ha_event_*.py` trigger already includes this module.

## Distinct source-level MCP security review

At new Worker B `mcp.py` blob `64c936f90d7a73883787b5e1c1521d9bb91ed51d`, `reject_remaining_media()` examines tokenized `rel` and `relation` list/string declarations, mixed-case or separator aliases, conflicting roles, and link targets rather than using the former single exact `rel: "download"` predicate. This source change addresses the previously recorded list, multi-token and contradictory relation cases.

In an actually available local Python interpreter (no HA checkout or external service), 12 synthetic cases were executed against a **manually copied isolated current relation-guard branch**: seven downloadable-role variants, conflicting benign declarations, malformed type, harmless documentation link, consistent harmless aliases and a no-link-target case. **12/12 behaved as expected in that extracted branch.** This is *not* an import or execution of the actual HA `inline_github_mcp_text()` function, MCP `Connections` bridge, pytest, or hosted ChatGPT file-materialization permission gate. The verifier-owned `tests/test_mcp_inline_text.py` inspected blob `63bbe71cc8ea3ea146c1733e2976328717b81a53` predates these production fixes and does not contain dedicated list/multi-token/mixed-alias relation regressions. Worker B owns `mcp.py`; verifier owns these test additions. No owner scope transfer.

## No-Actions trigger and execution audit

Read-only inspected 22 `.github/workflows/*.yml` definitions. The changed focused workflow uses `push` and `workflow_dispatch`; broad `test.yml` uses `push`/`pull_request`; `release.yml` has `workflow_run` on completed full-contract runs and push tags. No applicable direct `workflow_dispatch`, tag, or other run was requested. All integrator commits use `[skip ci]` to suppress eligible push/PR work; this is not a universal trigger bypass. Avoid commits if a live trigger changes in a way that would start Actions. Do not dispatch/rerun/enable any Actions, public or private.

- Executed full HA Python/pytest: **0**. New focused test cases actually executed: **0 of ten**.
- Executed GitHub Actions: **0**; live native browser/provider and hosted external MCP: **0**.
- Executed *isolated copied relation-guard probe*: **12 cases**, not module-level acceptance.
- No complete authorized HA checkout available locally. No binaries/ZIPs/private material/API keys/RE-Wizard code fetched; no owner-approved alternate execution mode/provider.
- Historical CI at `966d4de9296b94abf74c38ae9229ca643faca513` is read-only and **does not verify this source**. Broad Linux/Windows, qualified reviewer, actual native ChatGPT request/restart receipt, Windows Unicorn/Speakeasy, and core durable-effect receipt-scope/final live-lease defects are still pending.

## Next owner-scoped reproduction

When a permitted non-Actions complete HA checkout exists, run `python -m pytest -q tests/test_ha_event_receipt_envelope_worker_a.py tests/test_mcp_inline_text.py` with the exact tested HEAD, record expanded collected/pass/fail/error/skip counts, and rerun the focused selection without duplicate imports. Verifier should first supply actual `inline_github_mcp_text()` negative/positive tests for list, multi-token, mixed-case, conflicting aliases and harmless documentation links, and independent source/security review; integrator should recheck selected tests after any new module. Core durable-effect finalizer remains a separate source owner and must not be marked accepted on this evidence. Keep **CHECKS PENDING / AWAITING CI** until actual source-bound executable and native acceptance.
