# Independent review: setup progress and target resets

Reviewer: fresh assistant session `/root/review_setup_progress`, 2026-10-29.
Root transcribed this report; reviewer made no edits or pushes.
Base: `22461ee3a41a005570f5a77406357be260dfaf31`.
Source/test candidate: `565ecd67fb7cc33aed66bcc3051886fbdc7a6df4`.
Evidence candidate: `f75a065f9c4d6c9f3f3bb7e48aa89bd6e2573d95`.
Reviewer checked local file bytes; remote commits were not independently fetched.

**PASS after repairs. No remaining actionable findings within this scope.**

## Reviewed file identities (SHA-256)

| File | SHA-256 |
| --- | --- |
| `_app/hivemind_assembly/automation/sessions.py` | `81c87f883588d6c120329f36a8991e5327ce6977fa6638216fa64d70007f4a78` |
| `_app/hivemind_assembly/automation/onboarding.py` | `77045a2afb4e3597648d94b33ca1b32ca653e0e3cf491d5325610d4f9578d5e6` |
| `_app/hivemind_assembly/automation/team.py` | `997d5c7fd18f2eda8b31718ed15659291a569fab1182fe3e12395c77b4eef5bb` |
| `_app/hivemind_assembly/application/app.py` | `184754d6810ba6cab52f1a9168d7933e5eeac35ac17fddb395188e7f506a0748` |
| `_app/hivemind_assembly/application/static/assistants.js` | `4f22f7dfb1274fb87131204316b219f0c11ffbd3b5e16cf0b02ba211340edeec` |
| `tests/test_setup_progress.py` | `3e06c80f958241e615ddc4c3180793dcf6516f93298a3c55e81abca9bcb6f4b3` |
| `_app/release_status.json` | `8913b102a01a901d7606cb2986e83e8432e9e53366e5a8275306f61bd812cd41` |
| `README.md` | `43cae8a053a9da1cc70a8fed840e10dbcbca6381a4c3ff9e92444d0b703e33a3` |
| `dev/ROADMAP.md` | `e3420388618fc0d0589d24de84d3841cd3ba3e6831ee1826bcb21f30274656d3` |

## Findings and verification

Saved-chat recovery has a 45-second search budget plus concurrent, individually
bounded three-second cleanup. Uncertain delivery, original request and binding
are retained. Progress exposes account waiting, search, identity, reply and file
verification; attention overrides prior progress. Explicit and legacy target
resets are replayed in journal order, preserving later observations.

Reviewer identified serial probe cleanup extending the account lock; root changed
it to concurrent cleanup. Reviewer reproduced an early 601-second poll after the
sole exhausted observation was reset; unknown scopes now retain the daily hold.
An intermediate repair delayed active shared accounts unnecessarily; a known active
peer now preserves the ten-minute cadence, while any exhausted peer retains daily
polling. Durable poll timestamps remain intact.

Independent final regression command:
`WORKBENCH_TEST_CHROME=/tmp/ha-test-chromium python -m pytest -q
 tests/test_setup_progress.py tests/test_setup_recovery.py tests/test_sessions.py
 tests/test_native_readiness.py tests/test_journal_order.py tests/test_policy.py`
— **74 passed in 20.95s**, execution session 70984.

Root integration command added test_startup_handoff.py, test_team.py,
test_native_recovery.py and test_app.py to the same bundle:
**118 passed in 29.25s**. Reviewer inspected this log, not a second execution.
These overlapping results are not a summed unique-test count.

Independent evidence addendum: **4 status-document tests passed in 0.27s**,
execution session 74153. Generator and `git diff --check` passed. Release evidence,
README and ROADMAP agree with the reviewed source and recorded limitations.
Root also ran pyflakes on changed Python sources and tests successfully.

## Limits

Local fixtures and Chromium only. No live provider account acceptance or original
live-user root cause is established. Windows packaging and full hosted suites are
separate gates. Screenshot/OCR follow-on work is outside this approval.
