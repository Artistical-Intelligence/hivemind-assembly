# Independent review: connector menu navigation

Reviewer: separate assistant session `/root/review_connector_navigation`, 2026-10-29.
Root transcribed this report; reviewer made no edits or pushes.
Base: `3d61ed255fa6ba649f561384093ede5dc366f40b`.
Source/test candidate: `012212650e207f757d4e3ab3f6658b8c0b5c386b`.
Version/evidence candidate: `01d66249c74572d503f17206ae6dcdd5f850f04b`.

**PASS after one repaired finding. No remaining findings.**

## Reviewed file identities (SHA-256)

| File | SHA-256 |
| --- | --- |
| `_app/browser-helper/extension/navigation.js` | `f16122025b43a5b08f0535b637f5d7f1a2c431e67b99574c042543f15315896b` |
| `_app/hivemind_assembly/integrations/auto_reconnect.py` | `e205df0a04150272deb1f6f309f4ca010e08e7557980262997df8ae914162676` |
| `tests/test_connector_navigation.py` | `a002fcbb3e26838054627a7e77c76dcd95c434bbac3b4a60f13135d5c4cf87ff` |
| `_app/hivemind_assembly/__init__.py` | `5a188e60339ec5cecf88d6d33c872612aca2b2f577e6087ea8b3b72bcf6dbd90` |
| `_app/release_status.json` | `f2df922d6b89b2843ba27cf08ddfe8c3c8115bfcf1955dc3ef22b0e4c30a3c5f` |
| `README.md` | `762a6887e4969805b486eb61fe02f44ce23e80d2fc8a09ea8e04bd6d413302d7` |
| `dev/ROADMAP.md` | `daef1fa16b6092a868b5f1da562e034661b942a4bc5b9469b7433b7ad24ae2f5` |

## Findings and boundaries

- A form-associated submit button outside its form bypassed the existing
  closest-form exclusion. Reviewer reproduced submission, root repaired the guard
  using `el.form || el.closest('form')`, and the new negative fixture passes.
- Navigation still acts only on recognized controls on official setup pages.
  Ambiguous matches, unrelated dialogs, hidden/inert targets and form submits are
  excluded. Accessible labels now include aria-labelledby references.
- Existing extension `step()` states remain compatible. Additive `plan()` marks one
  target for actual Playwright pointer input. The fixture reproduces a menu that
  ignores synthetic clicks but opens with trusted pointerdown input.
- Retries are bounded to two per control key, a 1.5-second cooldown, six attempts
  per document and a 25-second outer deadline across navigation.
- Failed setup retains its page for inspection/manual completion. Successful and
  cancelled operations preserve existing cleanup. Stalled form navigation reports
  the last observed navigation state.
- Version 0.37.4 and generated evidence agree; historical evidence is preserved.
  README distinguishes automatic browser clicks from the helper's step() path.

## Verification

Independent final browser/mocked regressions:
`WORKBENCH_TEST_CHROME=/tmp/ha-test-chromium python -m pytest -q tests/test_connector_navigation.py`
— **11 passed in 16.70s**.

Independent final documentation checks:
`python -m pytest -q tests/test_status_docs.py` — **4 passed in 0.04s**.

Reviewer read root's integration log (`46 passed in 52.66s`) for:
`WORKBENCH_TEST_CHROME=/tmp/ha-test-chromium python3 -m pytest -q
 tests/test_debug_mcp.py tests/test_signin.py tests/test_shared_signin.py
 tests/test_auto_reconnect.py tests/test_chrome_helper.py tests/test_connector_navigation.py`.
This combined run was not independently repeated. The 11-case focused run overlaps
it; no summed unique-test total is claimed. `git diff --check` passed.

Official documentation inspected by root and reviewer:
https://developers.openai.com/plugins/quickstart
It confirms Plugins, plus, Add custom MCP server; it does not establish actual
account layout or DOM behavior.

## Limits

Only intercepted provider fixtures and mocks were used. No live provider account
was accessed, no real connector was created, and no model request was sent.
These tests demonstrate the repair for a reproduced input mechanism, not proof
that this was the original live-user cause. Windows packaging, hosted suites and
live ChatGPT/Claude acceptance remain separate gates.
