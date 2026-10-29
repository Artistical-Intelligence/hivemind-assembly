# Independent review: workflow and context changes

**Result: PASS — source changes approved.**

Reviewed the 20 files below independently; this reviewer authored none of them.
Review used the local worktree against base
`aca9957f3b6b18bd3b94c1702cf1888eafabeb64`. The integration owner fetched and
verified all 20 reviewed files byte-for-byte against candidate commit
`512802e8444f42c5fecb8250618ef3080a4efc41`. The SHA-256 manifest below defines
the exact reviewed contents.

Previously reported blockers are resolved:

- Explicit Resume uses the renamed reconciliation state.
- Changed local evidence invalidates stale reasoning authority and requires a fresh brief.
- Legacy remote-only check history retains its origin.
- Reset replay checks retained identity before restoring a session.
- Completed resets followed by workspace drift preserve role-scoped handoff evidence without reusing obsolete execution payloads.
- Session renewal checks expected identity inside its lock and immediately before committing, including replacement of the route configuration during UI verification.

The implementation retains existing writer fencing, operation reconciliation,
source permissions, independent checks, whole-project acceptance and learning
features. No new operational performance tracking was introduced. Documentation
accurately identifies clear-context requests as falling back to new chats and
distinguishes fixture coverage from live-provider acceptance.

Verification performed independently:

- Expanded regression selection: **120 passed in 29.63 seconds** before the final binding guard and direct-acceptance test additions. Modules: `test_context_reset`, `test_workflow_scheduling`, `test_workflow_reconciliation`, `test_checks_workflow`, `test_acceptance`, `test_controller`, `test_team`, `test_reconstruction_trial`, and `test_sessions`.
- After the final binding guard: context reset, sessions and scheduling — **34 passed in 2.18 seconds**.
- Final reconciliation suite, including direct acceptance after external drift — **9 passed in 2.28 seconds**.
- `git diff --check` passed.

This approves the reviewed source contents. Full-suite, hosted release,
installation and live-provider acceptance are separate gates; this review does
not claim those passed. No live-provider inference or native-service reset was
exercised. The release-status file in this manifest still labels final validation
pending; any subsequent evidence-only documentation update requires its own
review addendum and hashes.

| File | SHA-256 |
| --- | --- |
| `AGENTS.md` | `b1f825c6c55d88cdfb2a6615f5e6c04c3651d8ba5a47256681d7b17770f353b7` |
| `README.md` | `0f2763ef014163fb68b1be391875c8c053e0bb8eda0ead3e423cb678793ef8ce` |
| `_app/hivemind_assembly/__init__.py` | `c463c96fff81f8137ef38badb4ca32be37017902cce092b2430cbff2e376c61e` |
| `_app/hivemind_assembly/application/app.py` | `2b5656be4920bfe39e2c2954c1ea23a6ccd472d346036c7c41e0989c753bf849` |
| `_app/hivemind_assembly/automation/checking.py` | `b291c86d3e3b0bbb80bf023c619779158003a40e7659df4cc0db15b6956fde96` |
| `_app/hivemind_assembly/automation/context_reset.py` | `4cfd794a776d68b9f4023d40800f135b512dbf9e908b1af97d56e6c050dedd4a` |
| `_app/hivemind_assembly/automation/native.py` | `8aec7e9e1cc3fba9e48e58cd0b6466d988f9324b52d9a62913423e2788697fe6` |
| `_app/hivemind_assembly/automation/prompts.py` | `99b29dc61a274dab87b2f0bb5467d0b07e8c958e1cd37c2e95b99972b353be12` |
| `_app/hivemind_assembly/automation/sessions.py` | `8442b3172a3c5a42f353efdbeab0c129a28a26da0ceb8f9ec1ee0ff64347d072` |
| `_app/hivemind_assembly/automation/team.py` | `183a7c1f075bc11e93fff8f686ab0ddc054c21ad1d8316e554e4ced4aeec4b6a` |
| `_app/hivemind_assembly/core/acceptance.py` | `f6b31f94e2a8dbfd5383829ae294062c94afd294fc64334f9a72dd822e392164` |
| `_app/hivemind_assembly/core/checks.py` | `66b220d0dfee8670f673e814358227589963358c5939c6c9a0894e3429a73243` |
| `_app/release_status.json` | `3aa21f58b38cc96ad5354d7f2ce7a0f10193e0af9a3344983e9ce9664095b358` |
| `dev/ROADMAP.md` | `70b0f500c66b708e0d9578a51f29030d94ef63fd52ebfa3fad9a19386d436b8c` |
| `dev/WORKFLOW_UPDATES.md` | `446fb3e707349ab5c1269a132556710f8895d56f74c9dfc4689de21221a47645` |
| `tests/test_acceptance.py` | `f71050487cb3b28f48125e34ea9c50fd5e4d88519ed0318dede3aa7ef423f97f` |
| `tests/test_context_reset.py` | `b3ffda27183ee820e7fc1aac38e9bbc89ebc7f419c96f86b8b64e11dd8b81746` |
| `tests/test_reconstruction_trial.py` | `5ff5defd3bd96b71aa9b134e0e8cc59d5c67427ebc038530603510c761a538b5` |
| `tests/test_workflow_reconciliation.py` | `8a5ea15fb5bb38c98f37be0a8cb45e89e312e0c75164373abff059276eb89d39` |
| `tests/test_workflow_scheduling.py` | `f6ad1ef12e577bc708ddc3fe4771717b3a461a40c9012f39dab00803d15c4849` |

## Evidence-only documentation addendum

**Result: PASS.** Reviewed the subsequent changes to `_app/release_status.json`
and its generated `README.md` and `dev/ROADMAP.md` status blocks. The integration
owner identifies documentation candidate
`2f90629340d8aac6cdc8dff8c68f373001755bcb`. These changes record local results for
the already reviewed source commit
`512802e8444f42c5fecb8250618ef3080a4efc41`; they do not change runtime code.
All other 17 original manifest hashes remain unchanged.

The integration owner ran the complete frozen-source local suite. This reviewer
inspected its retained log and JUnit XML: **826 passed, 333 skipped, zero failures
and zero errors**, in **239.84 seconds**. The XML accounts for all 1,159 tests.
The new evidence entry records the full source commit, a local Linux host, no
hosted run IDs and `live_model_inference: false`. Its focused-test and independent
review claims are consistent with the preceding verification and the native
context implementer's reported 66-case focused run.

`python dev/status_docs.py --check` independently passed after the documentation
update. The updated text continues to distinguish local fixtures from hosted
Windows/Linux/browser/package checks, release publication, installation and
signed-in native-provider acceptance. Those remaining gates are not approved or
claimed by this addendum.

The original manifest is retained as historical source-review evidence. The
following hashes supersede its three documentation hashes for this approved
evidence update:

| File | SHA-256 |
| --- | --- |
| `README.md` | `6791ed0b570557df24a544ec119ac59279b52351e96182d936b65df0c39ba98b` |
| `_app/release_status.json` | `fcec60477d488cc1642a0ba048465a15d53cb7bb5b4e079b3973e789b9709a10` |
| `dev/ROADMAP.md` | `6e4da984fba3c894c6ff21639a24a4b0967fe7583682cb182dcd3a0d598e8132` |

## Test-fixture evidence persistence addendum

**Result: PASS — two test-only changes approved.** Reviewed
`tests/native_fixtures.py` and the added regression in
`tests/test_workflow_reconciliation.py`, identified by the integration owner as
candidate `89ce43c83075559603a8da4179fc345eafa0f9c3`. No runtime implementation
was changed for this fix.

The integration owner reports the hosted Linux run at `6ffb293` completed with
1,115 passes, 43 skips and one failure in
`test_worker_project_check_retains_snapshot_and_rolls_back`. Inspection confirms
that its `pass_checks` helper previously called `Checks.finish` without
persisting the referenced report or clearing on-disk markers. The runtime's
new reconciliation correctly refused that incomplete fixture evidence. The
helper now follows the check lifecycle: begin, finish with report text and
retained remote blob versions, then persist the report and marker removals
through `Drafts.sync`. It explicitly labels the approval as fixture evidence.

The added regression checks matching local and remote reports, removal of both
folder and ledger markers, and two unchanged reconciliation passes without a
revision increment. This corrects the fixture rather than relaxing runtime
acceptance.

Independent verification after these changes:

- Reconciliation, scheduling and reconstruction-trial modules: **28 passed in 10.64 seconds**.
- Explicit execution of the hosted-failing project reconstruction test: **one skipped**, because this review environment did not yet provide Clang and LLD.
- `git diff --check` passed.

At that point the compiler-dependent test still required execution with its
actual toolchain. This addendum does not claim a full hosted pass, release
installation or live-provider acceptance.

Subsequent toolchain verification resolves the local compiler-test gap: the
integration owner supplied portable Clang/LLD 18 and reran the exact previously
failing project reconstruction test together with reconciliation and scheduling.
This reviewer inspected the completed retained run log: **28 passed in 16.96
seconds**, with no skips or failures. This is actual compiled/emulated fixture
execution, not live model inference. The full hosted suite and release gates
remain separate.

The following hash supersedes the prior reconciliation-test hash and adds the
newly reviewed helper:

| File | SHA-256 |
| --- | --- |
| `tests/native_fixtures.py` | `8f3afe04bd10df0918a17988c6b6c9d761758516e33f6d732627816fd62892d6` |
| `tests/test_workflow_reconciliation.py` | `cf1322df4d1c3bcf094f7df051588cf6135ab75e7aa9912678e0e905e4baee81` |

## Portable exact-byte test fixtures addendum

**Result: PASS.** Reviewed the two test-only writes in
`tests/test_workflow_reconciliation.py`, identified by the integration owner as
candidate `62799677c766a702d9cc93192525f193812a9bec`. Both now use
`write_bytes(b"int a = 2;\n")` where the test subsequently asserts an exact
decoded LF string or an exact raw-byte SHA-256. This avoids Windows text-mode
newline translation while preserving the intended checks. The reviewer also
inspected the other writes and hash/content assertions in the three newly added
test modules and found no further equivalent mismatch.

Independent rerun of the complete reconciliation module: **10 passed in 2.38
seconds**. No runtime behavior was changed. Windows-hosted execution remains a
separate gate; a Linux fixture pass is not represented as a Windows run.

This final approved hash supersedes the earlier reconciliation-test hashes:

| File | SHA-256 |
| --- | --- |
| `tests/test_workflow_reconciliation.py` | `30c90c0296172d9011dda13dc3902e29ed2a689d5642757f0f722e926ccc0e93` |

## Windows fixture encoding and setup isolation addendum

**Result: PASS — two test-only changes approved.** Reviewed candidate
`8c7ad5b2a0476689ebd0e2407dc26a12cd300153`, as identified by the integration
owner. The changes affect only `tests/test_workflow_reconciliation.py` and
`tests/test_app.py`; runtime code and assertion strength are unchanged.

This reviewer inspected the downloaded Windows JUnit results from hosted run
`40821771661`. Its main suite reports **1,083 passed, 74 skipped and three
failures**, with no errors. Two reconciliation fixtures wrote an em dash using
the Windows default encoding; the runtime correctly attempted UTF-8 decoding
and rejected byte `0x97`. Those fixtures now explicitly use UTF-8 for all text
I/O, matching the application contract. The exact-byte writes approved above
remain exact byte writes. Inspection of the other newly added context-reset
and scheduling tests found no further equivalent encoding mismatch: scheduling
writes contain ASCII and reset attachments are handled as bytes.

The third Windows failure was the mocked first-run installation test observing
installation still in progress at its existing five-second deadline. The test
already substituted foundation and optional-tool installers, but real Windows
prerequisite probes still ran before the fake installer. The fixture now also
substitutes `prerequisites.missing` with an empty result. This completes the
mocked setup boundary while retaining the original timeout and all progress,
readiness and saved-path assertions. Dedicated prerequisite tests remain
unchanged and continue to cover availability and version behavior.

Independent combined rerun of reconciliation, application and prerequisite
tests: **54 passed in 9.40 seconds**. Source approval and the targeted fixture
gate pass. This Linux rerun does not establish that the updated Windows hosted
suite, complete release pipeline, installation or live-provider acceptance has
passed; those remain separate gates.

These approved hashes supersede the prior reconciliation-test hash and add the
reviewed application-test fixture:

| File | SHA-256 |
| --- | --- |
| `tests/test_workflow_reconciliation.py` | `aef0acf67a0bbc970864597dc0ff35fa70a754cefbd79c0ace45430a8356579b` |
| `tests/test_app.py` | `6467f9d961f1c2a85028a20a3252a6bff38f23350eafa922922d8c4043637667` |
