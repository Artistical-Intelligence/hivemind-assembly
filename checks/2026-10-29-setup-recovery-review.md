# Independent review: setup recovery and quota handling

Reviewer: separate assistant session `/root/review_setup_recovery`, 2026-10-29.
Integration owner transcribed this report; reviewer made no edits or pushes.
Initial source candidate: `662ee6e859b1774a5cf742dd3bdba5db95c7f652`.
Final source candidate: `937e031ac84241904b821b04c5a45bdaaf4fed2c`.
Version/evidence documentation candidate: `0dadbe22d6229c44971056af4e6ebca79b0f5a98`.

**PASS. No remaining material source or evidence findings in this scope.**

## Reviewed identities (SHA-256)

| File | SHA-256 |
| --- | --- |
| `_app/hivemind_assembly/automation/providers.py` | `3bac970f1f8633a08942556c409c8965a82b1101e82a473d74264991154e8170` |
| `_app/hivemind_assembly/automation/sessions.py` | `4e29125b17d605f56d14f79f52e9ef5cb3999585a40c63106ade92364e4ab107` |
| `_app/hivemind_assembly/automation/native.py` | `3a764cb0560705b79caedb43ac09ad267247e23cbf5c3e213b5a40302edbb55d` |
| `_app/hivemind_assembly/automation/onboarding.py` | `dc71cc1cd49e08c18df5958c6c53345c0e524e1ca780656f9533a516a31f9a32` |
| `_app/hivemind_assembly/automation/team.py` | `e1cf5abf445a52730bd8adcc00216aaa31085328619a022ba8d0bbae3c368d77` |
| `tests/test_setup_recovery.py` | `00970a4c6f44a2963379e6b8b92e5d32a5be76d1625bfb3fb300048f857b88d0` |
| `_app/hivemind_assembly/__init__.py` | `28f79a3020fe534c3ea5bee3ff3c323620343c7d80e209dffcea9918dce50254` |
| `_app/release_status.json` | `300fc9b65f4c4d778d467193574e8659e5ad6164c3bd1823ecd4fae89f0f3057` |
| `README.md` | `40a6f78fa60c614bf025c577246903149d255b3afa4942bd3e83668800b1bb31` |
| `dev/ROADMAP.md` | `ed7efaca8ee6e59ce0107f6e01b58d7153164c11115de1b8487457c9beacb0cf` |

## Verified behavior and resolved findings

- Uncertain bootstrap requests are never resent. Recovery requires the complete exact
  request envelope, deduplicates same-chat tabs and rejects distinct-chat ambiguity.
- History scanning is bounded, restricted to provider conversation links in navigation,
  excludes message links, and stops on incomplete evidence. Candidate URLs are hints,
  never confirmation or bindings. Probe cleanup continues after individual close failures
  and preserves cancellation.
- Shared account dispatch locks are reused across session clones without recursive
  acquisition. Show and snapshots use the active setup draft without rebinding it.
- Visible explicit usage limits are detected before dismissing a dialog. Spending
  controls are not clicked. Quota observations and the daily polling hold persist
  even when no earlier numeric allowance observation exists.
- Integration exposed a route-less temporary reservation error. The final guard leaves
  account observations and polling untouched when there is no configured provider route;
  both existing startup recovery variants pass after repair.
- Version 0.37.2 and generated evidence documents agree. Evidence separates local
  fixtures from live account and packaging acceptance.

## Checks

Initial independent focused run: 63 passed in 18.03s, using local Chromium fixtures:
`tests/test_setup_recovery.py tests/test_native_readiness.py tests/test_native_recovery.py
 tests/test_sessions.py tests/test_shared_signin.py tests/test_policy.py tests/test_popups.py`.

Final independent addendum adds `tests/test_startup_handoff.py`: 70 tests passed.
A combined run initially reported 73 passed and one status-document failure while the
integration owner was concurrently regenerating evidence. After generation completed,
all four `tests/test_status_docs.py` cases passed (0.07s), and
`python dev/status_docs.py --check` passed. These overlapping runs are not additive.

Owner's integration run of `tests/test_app.py tests/test_team.py
 tests/test_startup_handoff.py tests/test_run2.py tests/test_browser_fixture.py`:
initially 31 passed and two reservation failures; after repair, **44 passed in 34.54s**.
Reviewer read the retained local result. `git diff --check` passed.

## Limits

These are source and local browser fixtures, not signed-in Claude or ChatGPT acceptance.
No live messages were sent and no spending settings were changed. Direct remote MCP
inspection/control of HA browser tabs is not implemented. Hosted CI and Windows
installer verification remain separate gates; no results for them are inferred here.
