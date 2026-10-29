# Independent review: dedicated HA debugging MCP connection

Reviewer: separate assistant session `/root/review_debug_mcp`, 2026-10-29.
Integration owner transcribed this report; reviewer made no edits or pushes.
Base: `9dd6a52ed8244fc19b89932d3d97d0a15f3ef77c`.
Final source/test review: `5d2986d94c216af7b27a34cd49da752f01f47ccc`.
Automatic connector/version/evidence addendum: `20ba409526bffd7abd110947fd9dc3a03e61dccd`.

**PASS. No unresolved material findings within the disclosed debugging scope.**

## Reviewed file identities (SHA-256)

| File | SHA-256 |
| --- | --- |
| `_app/hivemind_assembly/integrations/debug_mcp.py` | `22bfcc5cf76d1b8076a6ec9bc6ea3886a5ba5ca4763c538f4c03ead59ac0cd50` |
| `_app/hivemind_assembly/integrations/quick_connect.py` | `d2a460552eb9846e760b3452dfb20d3477a692fe5c7262f85f92134dc02e8a3f` |
| `_app/hivemind_assembly/integrations/auto_reconnect.py` | `cd6d5146a43d5def89aa6da99fc7f4a02fc211bbf1454531ec985ceee73a0beb` |
| `_app/hivemind_assembly/application/app.py` | `d806068878539a3008a7fcbae75b940b9aa509037b7c6dd4158835994b22f4d7` |
| `_app/hivemind_assembly/application/static/index.html` | `6ee649b0308b47fec9b4adfedb18ab08bbe5afbcf9773906c188f6fb2b8ae94d` |
| `_app/hivemind_assembly/application/static/quick_connect.js` | `1eb5d67dd3b4b6bfb4ad422c22d8d43e91ad87c2fb1e128f81dc56e9be2cab24` |
| `tests/test_debug_mcp.py` | `060a72212c47fa40b3f0a472b454a00e974c8f8e93069ab0377a787ebb96c3e6` |
| `tests/test_auto_reconnect.py` | `09566531e9fdfb9abbde4ba4157c9eabc319abc5415e808577a9bf5fe663b077` |
| `_app/hivemind_assembly/__init__.py` | `88853bd6e9260477165eebab39d91c8af50ecb63415aab4aa54e41dce21742d9` |
| `_app/release_status.json` | `9284f2b52a3dd22b8fbb213a3a8e47f81a08b620b691ccef607e00bb3092e548` |
| `README.md` | `1cb7bfd31e851762e050c47b3cc6538302ba4f95ed918b16f7fc514a4efe7e06` |
| `dev/ROADMAP.md` | `d6876a819ae65e169c634c62fd4e96758ad85f7900c756d50bfaf0e637ce8228` |

## Verified boundaries and repaired findings

- Dedicated gateway, `ha.debug` OAuth scope and three-tool catalog isolate owner
  debugging from ordinary HA project-worker MCP access. No project broker passthrough.
- Gateway callbacks are bound to the grant epoch. Selected route/provider/profile,
  expected account, model/mode/effort, host allowlist and browser mode are checked
  against the grant. Old callbacks and changed identities cannot acquire new access.
- Stop revokes access, cancels admitted operations and debug-owned setup tasks, and
  stops the tunnel even when cancellation times out. A stopping guard prevents a
  concurrent start from inheriting the closing tunnel.
- Action request IDs bind route and action, retain uncertain outcomes, reject
  conflicting reuse and avoid duplicate effects. Busy assistant work is fenced.
- Images are sanitized control maps built from bounded observed control labels and
  positions, not raw provider screenshots. Recognized forms, conversations, history,
  account menus and embedded frames are excluded. Generic visible labels and setup
  diagnostics are intentionally shared, as described in the owner UI.
- Retry setup uses the existing native acceptance/recovery path and may send normal
  setup-test messages and consume allowance. The UI and MCP instructions disclose this.
  Quota popup handling never clicks spending controls or enables overage.
- Exact connector naming keeps HA Debugging automation separate from Hivemind Assembly.
  Both names/scopes passed browser-form creation and real loopback OAuth approval.
- SDK results use structured dictionaries; the dashboard displays the actual temporary
  approval-code field, and the browser test uses HA's Settings navigation.
- Version 0.37.3 and evidence agree. Current setup status references new debugging;
  historical 0.37.2 evidence remains unchanged.

## Independent checks

With `WORKBENCH_TEST_CHROME=/tmp/ha-test-chromium HA_SKIP_HELPER_REGISTRATION=1
HA_MEANING_SEARCH=0 PYTHONPATH=_app`:

- `python -m pytest -q tests/test_debug_mcp.py`: 9 passed in 11.29s.
  Teardown emitted `PytestUnraisableExceptionWarning` from `BaseEventLoop.__del__`
  (`Invalid file descriptor: -1`); exit status was zero.
- `python -m pytest -q tests/test_auto_reconnect.py`: 4 passed in 22.27s, no warnings.
- `python -m pytest -q tests/test_status_docs.py` after final correction:
  4 passed in 0.04s. Generated status documents match release_status.json.

## Integration owner checks

Reviewer read retained result logs. With local Chromium enabled:

- `tests/test_debug_mcp.py tests/test_quick_connect.py tests/test_auto_reconnect.py
  tests/test_mcp_connections.py tests/test_mcp_checks.py tests/test_app.py`:
  62 passed in 43.78s.
- `tests/test_setup_recovery.py tests/test_team.py tests/test_startup_handoff.py
  tests/test_dashboard_browser.py::test_every_button_has_a_hover_description`:
  26 passed in 18.99s.
- Expanded `tests/test_auto_reconnect.py`: 4 passed in 45.19s.
- Four status-document checks and `git diff --check` passed.

These runs overlap: the 62-case run includes the nine diagnostics tests and the
original three connector cases. The later four-case connector run repeats those
and adds the debugging parameter case. No summed unique-test total is claimed.

## Limits

Tests used local provider fixtures, loopback OAuth and Chromium with intercepted
provider routes. No live account or remote tunnel connection was exercised.
Visible control labels and setup diagnostics can include user content displayed
in unfamiliar headings or controls; this is not universal private-text redaction.
No real provider messages were sent in these tests. Windows packaging, hosted
full suites and live-provider connection acceptance remain separate gates.
