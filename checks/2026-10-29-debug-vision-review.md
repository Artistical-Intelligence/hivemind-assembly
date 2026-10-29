# Independent review: MCP screenshots and OCR

Reviewer: fresh assistant session `/root/review_debug_vision`, 2026-10-29.
Root transcribed this report; reviewer made no edits or pushes.
Base: `3333d646f06c195c30b385ab4b14bfd15c34add2`.
Source/test candidate: `2e7929999b90a0cdb6ed979f4533d53a26ccbb21`.
Evidence candidate: `a5f9aade6f1c5a4a31ab294b28784f7473d2cec7`.
Review used authoritative local worktree contents.

**PASS after one repaired finding. No remaining findings.**

## Reviewed file identities (SHA-256)

| File | SHA-256 |
| --- | --- |
| `_app/hivemind_assembly/integrations/debug_mcp.py` | `b0e2a7b970d424a5fedfbc557caa11bb56ed179d60dc56c94946f20266e6face` |
| `_app/hivemind_assembly/integrations/debug_vision.py` | `2c780ceff5721e5bb2109003a79ff0dc24853815e445db0466baf08965cfc97d` |
| `_app/hivemind_assembly/application/app.py` | `5bc8729cbf4bb2b53703fd818fe8071606e10380807c736cc8e9dbc05250af56` |
| `_app/hivemind_assembly/application/static/index.html` | `5f7cab7bd675180abed5c804f5900fc0c56b0e6572f46f12349a593ee22ab8f3` |
| `_app/hivemind_assembly/application/static/quick_connect.js` | `d045320fe8acb5ad8ceec81bde6b5b5846a9c4e04338a761cadb809caf313ddc` |
| `tests/test_debug_mcp.py` | `d18677a6792e26b7649b64cfb5f4fe59def348bb41c6e2a3feb38ced9b429d53` |
| `tests/test_debug_vision.py` | `fd8d90ab919283fc2373c20708eb7a4f89c4f29c29ca78284b8a5c1dc3edb3d4` |
| `_app/release_status.json` | `c38c7ff6ea239bfb5057d9ad3da23d2b09467630a2620995a11ebcb5d6497957` |
| `README.md` | `1de3891cbc67785bfcde99cee215239a515647ac875b75c50841adf6b5c72f8e` |
| `dev/ROADMAP.md` | `bc4fa68110fa3844562062e056e8f7dd6bf36e079a7beb957e8815f1cffbfb99` |

## Findings and boundaries

Reviewer reproduced navigation during the final password-field await bypassing
capture's previous response fence. Root added a final verify() with no awaits
before return; the independent reproducer now raises Blocked. Regression cases
cover navigation, identity and grant changes at this exact boundary.

Reviewed strict opt-in screenshot grants, selected routes, immutable active grants,
OAuth disclosure and stale epochs. Actual viewport pixels and local English OCR
with word boxes are exposed only through the debugging connection. Read-only
capture bypasses a busy account dispatch lock without driving provider controls.
Navigation, page replacement, identity and authentication-page fences apply.
Stop cancels admitted operations; OCR has bounded execution and reaps subprocesses.
Missing or failed OCR retains screenshot review. Recognized masks are explicitly
not complete redaction; visible conversation content is disclosed. Existing
sanitized control-map and bounded-action behavior remains intact.

## Verification

Independent exact-source command:
`WORKBENCH_TEST_CHROME=/tmp/ha-test-chromium PYTHONPATH=_app python -m pytest -q
 tests/test_debug_mcp.py tests/test_debug_vision.py`
— **21 passed in 17.04s**, no skips. Real Chromium/Tesseract used local fixtures.
A separate actual Chromium check confirmed clipping captures the scrolled visible
viewport without changing scroll position.

Root integration log inspected independently: `tests/test_debug_vision.py`,
`test_debug_mcp.py`, `test_auto_reconnect.py`, `test_connector_navigation.py`,
`test_setup_progress.py`, `test_app.py` — **71 passed in 62.36s**.
These overlapping results are not a summed unique-test total.

Independent evidence addendum: **4 status-document tests passed in 0.03s**.
Generator and `git diff --check` passed; README instructions, privacy disclosures
and release evidence match the reviewed implementation. Source hashes unchanged.
Root also passed pyflakes on changed debugging implementation and new tests.

## Limits

No live provider account, remote tunnel or signed-in acceptance was tested.
Windows packaging and full hosted suites remain separate gates. OCR is local
English Tesseract; its Windows installation is an existing prerequisite path,
not newly verified by these Linux fixtures. Screenshots can include conversation
content; masks do not promise universal redaction.
