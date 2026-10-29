# Independent review: native message recovery

**Result: PASS — the source changes in the manifest below are approved.**

Reviewed against base `5faf95f0f6d874e25f830cea7c1529704b40cdf8`, with final
implementation/test candidate `cb37d733b1514ba93b476b788c1ad08235c40f3b`.
This reviewer authored none of the implementation or regression tests. Read
`AGENTS.md` and inspected the affected transport, session, setup, controller,
task-recovery and test paths. No blocking source findings remain.

## Findings and resolution

The initial session-recovery implementation could cache a clone before its
page and identity were initialized. A duplicate-message exception during the
new echo scan bypassed the existing cache cleanup. Retrying setup on the same
`Sessions` object then skipped rediscovery, even after the owner corrected the
duplicate. This was a recovery blocker, although the retained uncertain
delivery still prevented an automatic resend.

Commit `f44bf9b6f26833c39e5f55f430fa7b7af68bdbd0` moves cache insertion after successful page recovery and
identity discovery. An independent temporary-script reproduction verified
that a failed duplicate scan leaves no cached clone and that a subsequent
attempt rescans and selects the original persistent tab. The durable regression
added in `cb37d733b1514ba93b476b788c1ad08235c40f3b` exercises the same sequence
and verifies that the journal remains `delivery_uncertain`.

The reviewed behavior preserves the required safeguards:

- Shared DOM extraction collapses nested wrapper/bubble matches while retaining
  separate sibling messages. Whole-token markers avoid prefix collisions, and
  distinct matching user messages are rejected as ambiguous.
- A full canonical request envelope is still required before acknowledgement
  or draft-to-conversation binding. A marker-only clipped message is rejected.
- Replies and completion controls belong to the interval between the selected
  logical user turn and the next one. Nested assistant matches are extracted
  once; earlier and later answers or completion controls do not certify this turn.
- Dispatch intent is persisted before submission. A click exception triggers
  observation of that same intent, without another click. Later reconciliation
  of retained dispatch/uncertain states also observes without resending.
- Cancellation is propagated, uncertain send state is retained, and dispatch
  and route locks are released. An absent acknowledgement raises
  `DeliveryPending`; setup stops after three such checks per run. Ordinary task
  recovery continues to use the existing bounded retry schedule.
- The `test_run2.py` change only adapts its mock to the new echo extraction
  call; malformed response retention and invalid/processing assertions remain.

## Independently executed verification

Final focused command:

```sh
WORKBENCH_TEST_CHROME=/tmp/ha-test-chromium python -m pytest -q tests/test_native_recovery.py tests/test_native.py tests/test_native_readiness.py tests/test_sessions.py tests/test_run2.py tests/test_browser_fixture.py tests/test_surfaces.py
```

**48 passed, zero skipped, in 74.10 seconds.** This includes actual local
Chromium 153 execution of flat/nested message delivery, true duplicate rejection,
clipped-envelope rejection, attachment/download checks, prefix markers,
next-user reply/completion boundaries, code-block extraction and existing
surface regressions. The fixture invokes the production JavaScript extraction
functions. The send-failure and cancellation cases use deterministic transport
fakes, rather than a provider intentionally timing out.

Earlier focused runs passed before the final test additions; their counts are
superseded by the final run above. `git diff --check` passed. No signed-in live
provider, provider inference, hosted CI, release installation, or remote
publication was verified by this review. Local browser fixtures do not establish
live-provider acceptance. The default Playwright browser download failure was
worked around with a separately obtained Chromium executable; it was not
represented as a successful Playwright installation.

## Reviewed source manifest

| File | SHA-256 |
| --- | --- |
| `_app/hivemind_assembly/automation/native.py` | `f30e2a6c632093d9b893155651efabdebe8d730064359ffdbb01dd3c8237d6f8` |
| `_app/hivemind_assembly/automation/sessions.py` | `ac6c49b2966f571b4996b642df4b744dc2b487551fdd39bae5e346236cebfc08` |
| `_app/hivemind_assembly/automation/onboarding.py` | `05a677bc15ed93a7e3229028d63bd191b4ccee461e5522c1fd89bb52aa6ffd43` |
| `tests/test_native_recovery.py` | `e5e2bb758a9b59cc5d895537131345b11cde0bdc2ffd27a1dbfd11ef82b89d89` |
| `tests/test_browser_fixture.py` | `58817a37fd03cbd4474a59ceb40a76eaacc675499bb70453c6d6344f94dabacb` |
| `tests/test_run2.py` | `ad877d822d25da590d65e7c37bb69e4761cb591a293437fd826768e1cf251687` |

## Evidence documentation addendum

**Result: PASS — evidence wording and generated status documents approved.**
Reviewed documentation candidate
`b4c2e84158ae394602d01b3593eb800be1e21051`. The only substantive documentation
change records this native-recovery work with the full source commit, a local
host, no hosted run IDs and `live_model_inference: false`. Historical results
remain separate. README and ROADMAP reflect the source evidence record;
`python dev/status_docs.py --check` independently passed.

The integration owner supplied the following completed command outputs. This
reviewer did not execute these broader runs and was not supplied retained XML
or log files; the counts below are coordinator-reported, distinct from the
independently executed 48-test run above:

- Candidate, without `WORKBENCH_TEST_CHROME`:
  `python -m pytest tests -m 'not slow' -q --disable-warnings --tb=short --maxfail=3`
  exited successfully: **694 passed, 103 skipped, 374 deselected in 158.36 seconds**.
- Candidate, same command with the Chromium executable enabled: stopped at the
  three-failure limit with **3 failed, 180 passed, 37 skipped, 374 deselected in
  142.19 seconds**. Failures were two Chrome-relay extension serviceworker
  timeouts and the dashboard retained-result assertion.
- Untouched base `5faf95f0f6d874e25f830cea7c1529704b40cdf8`, running the two
  Chrome-relay tests and that dashboard test: **2 failed, 1 passed in 83.04
  seconds**, with the same two serviceworker timeouts. Repeating the base
  dashboard test alone subsequently failed in **21.96 seconds**. The candidate
  dashboard test also failed when retried alone.

Independent source inspection explains why the unchanged dashboard assertion
can be timing-sensitive: `workspace.js` first displays the completed job's
summary, which includes `scope: native_tool_tests`. The Last result click
handler then awaits `/api/project/check-result`, which returns the native raw
observations artifact without that scope field. Playwright's click can finish
before the asynchronous response is rendered, so the immediate text assertion
can observe either the old summary or the raw report. The relevant dashboard,
API and test files are unchanged by this recovery work. This observation does
not repair or approve the dashboard defect. No causal claim is made about the
extension timeouts beyond their reported reproduction on the unchanged base.

The evidence accurately retains these failures and explicitly declines a full
browser-suite, signed-in provider, hosted CI, installer or release-verification
claim. The source review passes; those broader acceptance gates remain open.

| File | SHA-256 |
| --- | --- |
| `_app/release_status.json` | `049c49dd3370a26994c4ec9a40980494c876e88f6ae3c058edde66eda89850bc` |
| `README.md` | `d022b0fde6316e281dc2eb70bfe7bd93ef33ba055b99d2e3126edaa2b08043e0` |
| `dev/ROADMAP.md` | `6b776ee9b21d50f170eacde4de0d7e5d321dce015ea3d13c8747037738e0518c` |
