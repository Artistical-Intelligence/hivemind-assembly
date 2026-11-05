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

A previous focused no-API event run completed successfully for inbox/watchdog/GitHub integration on its exact tested source revision (see [Actions](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/workflows/chatmode-native-events.yml)). Updated Grok Bot source/tests and later changes must pass their *own* focused CI before acceptance. Existing broad Ubuntu/Windows packaging/browser tests are independent; don't declare the whole HA program accepted from the new focused gate.
