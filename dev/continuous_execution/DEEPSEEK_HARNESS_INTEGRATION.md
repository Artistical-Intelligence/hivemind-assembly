# DeepSeek Harness + Super-agent + Grok Bot techniques adapted into HA

**Implementation date:** November 5, 2026. **CHECKS PENDING** until independent review and live browser/provider acceptance. This is actual HA Python code, not a substitute for HA's tested ChatGPT or Claude subscription web modes. No code in this implementation directly invokes a paid model API.

## Sources reviewed and engineering lineage

- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness): packages/core/agent-loop, session, tool-executor-native and scope. The *separate scopes* and *native vs provider tool execution* boundaries inform this adaptation. This is not an import of its Cordis/TypeScript runtime.
- [DeepSeek Super-agent prototype](https://github.com/deepseek-ai/dsh-superagent-prototype): MIT-licensed `src/core/intake.ts`, `tickets.ts`, `assignments.ts`, `engine.ts`, `memory.ts` and `src/app/outbox.ts`, `effects.ts`, `sessions.ts`, `retry-health.ts`. Concrete techniques adapted: stable trigger IDs, source-scope admission, per-thread ticket subscriptions, stored delivery and consumed/read states, separate ticket/assignment lifecycle, persisted receipts, retry evidence and the principle of an independent monitor. No executable TypeScript or third-party model adapter is loaded by HA.
- [Grok Bot integration kit](https://github.com/rodrigo-pasini/grokbot-kit), MIT: `src/grokbot_kit/payload.py`, `terminal.py`, `deliver.py`, and `docs/event.md`. Concrete techniques adapted: distinguish terminal success/error/timeout from nonterminal `needs_input`, direct the event only to the originating task, deduplicate delivery receipts and keep freeform agent summaries outside trusted control flow. This is *not* an import of a Grok Bot cloud runtime, headless agent CLI, API provider, login or webhook connection.

This source list is the engineering attribution and should be reviewed with the upstream LICENSE files before distributing any substantial literal reuse; the HA changes are original Python implementations following inspected architectural patterns.

## Completed source implementation

| HA file | Role | Evidence level |
| --- | --- | --- |
| `_app/hivemind_assembly/automation/event_inbox.py` | Durable SQLite event admission, exact-ID dedupe, project-scoped thread subscriptions, per-task unread/read receipts, projected work ticket and local HA journal bridge | Focused CI and source acceptance separate |
| `_app/hivemind_assembly/automation/team.py` | Existing **native browser** ChatGPT Chat-only intent path feeds bounded `event_inputs` into the current `self.ask` request; acknowledged after exact validated saved message receipt. The existing `NativeTeam.run` loop checks the local watchdog. No separate LLM/tool execution route introduced. | Implemented in HA native path; live browser receipt pending |
| `_app/hivemind_assembly/automation/progress_watchdog.py` | Deterministic local monitor compares validated turn count against completed operation count, emits a bounded `possible_stall` event, does not pause/reassign tasks or infer model capability | Possible-stall indicator only, not a full KPI evaluator |
| `_app/hivemind_assembly/automation/github_event_adapter.py` | Optional authenticated GitHub webhook ingress using HMAC-SHA256 and exact repo mapping; no network listener; only source SHA, run ID and enum outcomes are forwarded | Requires a real trusted inbound host connection before external use |
| `_app/hivemind_assembly/automation/grokbot_event_adapter.py` | Optional versioned `grokbot-kit.event/v1` intake for `completed/error/timeout/needs_input`; task-targeted and metadata-only | Requires a trusted host to authenticate target/route; doesn't launch CLI, model, or webhook |
| `tests/test_native_event_inbox.py`, `test_progress_watchdog.py`, `test_github_event_adapter.py`, `test_grokbot_event_adapter.py` | Deterministic local tests: dedupe, isolation, durable read receipts, cross-project rejection, denied remote input, watch signals, authenticated CI, direct delegate completion | Offline tests; not proof of live browser receipt |
| `.github/workflows/chatmode-native-events.yml` | Narrow no-model-API GitHub Actions gate for the above Python contracts | Inspect exact workflow run and test counts; separate main project CI still applies |

### Execution behavior

```text
existing HA local journal OR authenticated external adapter
        |
        | stable trigger ID, project/role checks, dedupe
        v
 durable SQLite trigger ----> subscribed existing work ticket
                                  |
                                  | unread bounded event inputs
                                  v
                existing NativeTeam.ask() / browser.exchange()
                                  |
                                  | existing validated response receipt
                                  v
                 acknowledged event, ready for later work

    independent local watchdog -> "possible_stall" event
    never direct model/API call, never automatic full-time retask
```

**No silent paid API:** These new modules use the Python standard library, the existing local Store and native browser connector. An admitted trigger never starts a model; it is included in an existing authorized Chat Mode `ask` turn. External webhook adapters are pure input validation functions and are not connected to an outgoing network client. HA's pre-existing native worker may consume its normal service subscription allowance; these changes do not make it free, nor enable an alternative model provider/API mode.

**Persistence and retry discipline:** Stable source IDs deduplicate incoming triggers. SQLite stores event -> task delivery until the corresponding native request is validated and the exact serialized event IDs are acknowledged. If a prior saved native answer is replayed after a restart, the consumer acknowledges only event IDs in that validated request, never newer arrivals that the model did not see. The local journal is separate authoritative evidence; its bridge uses a persistent per-project source cursor.

**Scope:** No new filesystem/browser authority, source mediation bypass, automatic GitHub action, external webhook listener, task object creation, scheduler change, independent reviewer approval, cross-project task ownership, paid API call, credential storage or live RE-Wizard mutation. Grok Bot `needs_input` remains a task signal, not automatic permission grant. External strings are treated as data, not instructions.

## Remaining engineering and acceptance gates

1. **Focused CI must pass on the latest commit** including all four new test modules; inspect job logs and test count, not just a green workflow badge.
2. **Independent review:** verify no cross-project routing, dedupe/acknowledgment race, false progress inference, event-store schema drift, arbitrary trusted-source impersonation, unexpected API call or provider-mode leakage.
3. **Live HA native browser proof:** configured OpenAI Chat route receives an event in the actual conversation, responds through `browser.exchange`, retains exact model receipt across restart, and later retries/unsubscribes safely; verify Claude, Work, Codex and generic routes remain unaffected.
4. **External source connectivity:** the HMAC GitHub adapter is not an HTTP server and the Grok Bot adapter is not a bot connector. A trusted event source must explicitly bind project/repo/target and credentials without exposing them to workers; verify end-to-end negative cases before enabling.
5. **Production watchdog policy:** current heuristic detects validated turns without executed operations. Some meaningful non-tool research is legitimate; its signal is **advisory only**. Shift Manager must inspect source and task evidence before reallocating a full-time worker. The monitor must not turn into a token-expensive polling assistant.
6. **Event wakeup:** a signal currently becomes available during a scheduled/natively authorized worker turn; there is no proved off-schedule wakeup of a ChatGPT hosted task or sub-hour service override.
7. **DeepSeek's full ticket/scheduling features are not ported:** end-to-end broker subscriptions, persistent executor effects, multi-step ticket assignment/restart, context-recall scoring, universal plugin API, model selection/fallback and independently qualified review remain separate projects. Use existing HA components and no paid API fallback rather than claiming this initial implementation is a complete Super-agent.

## Scope-limited test status

**Verified on the latest focused source revision:** [Actions run 42095932643](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/42095932643) at commit `2867c4571d23451d64a50b4496d78acc2cd9064b` completed **13 passed, 0 failed** in 0.62 seconds. This includes inbox, watchdog, signed GitHub admission, Grok Bot event routing, and a test using HA's real `NativeTeam.ask` request assembly with a fake browser and explicit simulated `NativeBrowser.exchange` validated-receipt boundary. The first attempt [run 42095607635](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/42095607635) exposed that a fake browser returning a dictionary does NOT set a native message to `validated`: that test initially failed 1/13. The revised test verifies `prepared` remains unread until the *existing* `NativeTransport.exchange` controller validation is represented and only then acknowledges. No real ChatGPT browser provider was used. These are **scoped local Python acceptance tests**, not live provider, external webhook or full HA acceptance. Existing broader Ubuntu/Windows packaging/browser checks remain independent.

## November 5 integration source/CI recheck (CHECKS PENDING)

This is a source-pinned follow-up, **not** independent source acceptance or live provider/browser validation:

- At HA commit `3c7efdd3fda6d980a3924db89953fc936533262f`, [focused Actions 42106433677](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/42106433677) ran **56 tests per platform** (the original native event/adapter/MCP suite plus core durable-effects tests). **Ubuntu: 55 passed, 1 failed; Windows: 55 passed, 1 failed.** Both failed `test_native_initial_subscription_receives_prior_unread_ci`; no independent platform-specific failure was recorded in this focused gate. A verified, authenticated CI event that arrives before the first task subscription is currently stored without delivery. Worker A owns the inbox repair and must preserve explicit-unsubscribe non-resurrection. All 13 core durable-effect tests passed as part of each platform's 55 successes.
- Earlier standalone [core effects run 42105576454](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/42105576454) passed **13/13** at `3de2a8c17978b4cda6c7f80ca19f9493b4950789`. Its module handles one effect per event, controller epoch/owner fencing, post-claim validated-receipt requirements, per-chat in-flight ordering and fail-closed uncertain replay. **It is not proven wired to the live `NativeTeam` code path**, so standalone success does not close integration.
- Broader HA [run 42105701999](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/42105701999) at `ff3bac8af52e43d436160813129286f20757c5f4` is **cancelled/incomplete due newer commits**, not green: Windows package job passed with a tested replacement install; browser-fixture job failed before any tests because `playwright==1.58.0` cannot install Chromium on the current `ubuntu26.04-x64` runner; Windows whole-suite job emitted an **ARM64 Unicorn `reg_write` access violation** in `test_call_images.py::test_hidden_cases_pinned_and_rebuilt` before cancellation. Ubuntu whole-suite job was cancelled. Distinguish platform setup failure, native package/crash and missing complete CI verdict. Browser-fixture can be investigated by a separate workflow owner using a supported pinned runner rather than bypassing tests. Do not change broad CI or reverse-engineering source from the integrator's file scope.

**Upstream reconciliation (inline public source reads; not vendored code):** [DeepSeek `effects.ts`](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/main/src/app/effects.ts) blob `9255cda8f7a63ed0e7ab70bb023a5927fe5218d5` supports handler-specific retry/backoff; [`outbox.ts`](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/main/src/app/outbox.ts) blob `a5f64b56eca71a4668e0893f890db937bd23a573` stores receipts and serializes per-conversation ticket replies. HA intentionally **must not** adopt blind post-timeout retry for a ChatGPT browser turn: the event may have been sent even if local receipt was lost. HA's local receipt evidence is narrower than an external source acknowledgement, and uncertain outcomes require reconciliation before re-dispatch. [Grokbot `terminal.py`](https://github.com/rodrigo-pasini/grokbot-kit/blob/main/src/grokbot_kit/terminal.py) blob `4a9cb2d36a3a54fbb5a0f7bd1d953c5862202e3a` emits terminal `completed/denied/permission_denied` distinctly from nonterminal `needs_input`; HA adapter `grokbot_event_adapter.py` blob `9d2f55d0ae28832d6da65156a757ca42c60615b7` maps that to `delegated_denied`, not `delegated_completed`. This is a source-level semantic match pending negative tests and host authenticated target binding.

**Current blocker to final acceptance:** the integration has no authorized evidence of a real configured ChatGPT Chat Mode native browser request receiving a source-bound event and persisting the corresponding validated reply across a crash/restart; local fake browser, GitHub Actions Python and public source inspection cannot substitute for that. Qualified independent security/source review, negative project isolation and repaired **current-HEAD** cross-platform CI remain mandatory. No new paid model API, alternate provider, cross-project authority, platform approval bypass, or release approval was introduced.
