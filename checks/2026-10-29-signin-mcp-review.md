# Independent review: sign-in observation and HA MCP setup

Reviewer: separate assistant session `/root/review_signin_mcp`, 2026-10-29.
Integration owner transcribed this report; reviewer made no edits or pushes.
Base: `8067456289cfee469b665bde7e5edd7c97534995`.
Source candidate: `cbdaf0da00499e455a5ba4b3365b40d392b674ce`.
UI/version addendum: `ec4312098d6d6ec8a0a8716ddc08a5cf8104a1ff`.
Evidence/docs addendum: `4eac0d236fc79246683a1c7c16eca654765c09a6`.

**Source, focused regression, UI/version and evidence review passed. No remaining
blocking findings within this scope.** Whole-project acceptance and live-provider
acceptance remain distinct.

## Reviewed file identities (SHA-256)

| File | SHA-256 |
| --- | --- |
| `_app/hivemind_assembly/automation/signin.py` | `8b3636395635027d13a922a484ae5ef357aee3ee7fb7dcf4499aa65043e7ad8d` |
| `_app/hivemind_assembly/application/app.py` | `3244324e09bc4c3711d1546fb82351f417aa99de0b59aaeb9e93b4f36488ce30` |
| `_app/hivemind_assembly/application/static/assistants.js` | `5c2f44965970dee47d676255de5c3f2bb3d09ce002e6dc3b1688132439e45c9b` |
| `_app/hivemind_assembly/application/static/style.css` | `58d97235c8438e9ba7e0ff1576102f8031773ec05fa6b509d9dd278c02196cd3` |
| `_app/hivemind_assembly/__init__.py` | `536b283b91e6ee5f36d02b9583cd429b75c21eeb9201151ff536108ff649420a` |
| `tests/test_signin.py` | `2ca0bf1c5106d98c5b31f4ea16b4a60f6ea85eb40ebae182af7f406bb1968ec0` |
| `tests/test_dashboard_browser.py` | `c1c711655da1220ca600b1b982bbff7fb20dafc70a6870c8f1b3700911387782` |
| `_app/release_status.json` | `b4c500ab9abadfaf1ec611b2aad33b2605e6a44397c01281437a8c3c011f2352` |
| `README.md` | `29dbc9bd6c23b8f77f5a87806b0f94c8fd9fc2f9b8e9ee04b7e0ca76c31e85d8` |
| `dev/ROADMAP.md` | `a86e27a7213afc69ea43a4455d5f02fabb2c1a606346e7b4c90966f3de9b04b3` |

## Review findings resolved

- MCP preflight and sign-in originally checked a default browser profile while
  creation used the configured route profile. Both now resolve the configured profile.
- Reopening a closed sign-in tab could retain the old watcher. Replacement cancels
  and drains that watcher, then observes the new tab.
- Interrupted connector setup could leave the UI permanently working. Cancellation
  restores retry status.
- Thread-safe future wrappers could report cancellation before asynchronous cleanup
  finished. Actual asyncio connector tasks are retained and drained before browser replacement.
- The new MCP buttons lacked hover help. The explicit title describes creation and
  existing project access behavior; corresponding dashboard regression passes.
- README's manually maintained version header was stale; both README and ROADMAP
  headers now identify 0.37.1 alongside the generated evidence.

## Verified boundaries

Account observation is independent of model selection and session readiness. It
requires positive account email evidence; loading/login observations clear it.
Sign-in alone does not rebind routes, enable MCP sharing, create connectors, send
messages, or introduce model API fallback. Explicit MCP creation waits for sign-in
in the configured profile and retains existing sharing controls. Repeated opens
reuse the tab/watcher; changed profiles and reopened tabs get fresh observation.
The dashboard exposes sign-in, setup retry, and Create HA MCP. Responsive service
grouping and the 0.37.1 version change were independently reviewed.

## Independent checks

- `WORKBENCH_TEST_CHROME=/tmp/ha-test-chromium python -m pytest -q tests/test_signin.py tests/test_shared_signin.py tests/test_auto_reconnect.py`: **14 passed** (26.78s).
- Changed assistants dashboard case: **1 passed** (7.17s).
- Hover-description dashboard regression after repair: **1 passed** (3.32s).
- `python -m pytest -q tests/test_status_docs.py` after header repair: **4 passed** (0.04s).
- Source and documentation `git diff --check`: passed.

## Integration owner evidence and limits

- Dashboard/sign-in/connector integration run: **28 passed, 4 skipped, 1 deselected,
  1 failed**; sole failure was missing hover help. Subsequent two affected dashboard
  cases both passed after repair (11.51s).
- Named application/native-recovery/session/status checks: **39 passed, 1 failed**;
  sole failure was the README version header. After repair, all four status tests passed.
- The broader non-browser non-slow run is **incomplete/unverified**. Automatic
  approval review blocked further access after reporting an unsolicited Microsoft
  telemetry connection, with destination and payload not authorized. The blocked
  operation was not retried. No pass is claimed for that run.

Fixtures do not establish live Claude/ChatGPT layout compatibility or live account
acceptance. The connector fixture exercises HA's real local gateway and OAuth
approval against a stand-in ChatGPT page. No live provider messages were sent.
Hosted CI, Windows packaging and live provider acceptance remain separate gates.
