# Related systems and implementation decisions

This comparison informs engineering choices; upstream benchmark results are not
Hivemind Assembly results. No additional framework is required at runtime for
these changes, and no inference transport substitution is introduced.

| Project | Useful approach | Decision for Hivemind Assembly |
| --- | --- | --- |
| [ReAgent](https://github.com/Dryxio/reagent) | Candidate overlays, configured build/runtime gates, dependency-ordered manifests, explicit evidence gaps | Adopt separate candidate builds and independent behavior checks. The implemented first lane compiles freestanding C and executes candidate/original bytes in Unicorn. Multi-function dependency planning and cumulative project builds remain future work. |
| [Hermes scheduler](https://github.com/NousResearch/hermes-agent/blob/ddabd3837862022a6053331fe3ba97cf9716b9e3/cron/scheduler_tick.py) | Durable admission before dispatch, guarded ownership, explicit treatment of recurring and one-shot work | Retain already authorized operations before dispatch, drain them without requiring another model allowance, and avoid resending uncertain native messages. Full Hermes coordination integration remains required; the current SessionDB host does not satisfy that requirement by itself. |
| [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | Separate resumable execution checkpoints from durable cross-thread knowledge | Preserve the existing operation/flow journal separately from learning assets. Borrow the separation of concerns without adding a second agent runtime. |
| [ACE](https://github.com/ace-agent/ace) | Localized grow-and-refine edits; generation, reflection and curation have different responsibilities | Add stable playbook entry IDs, guarded delta edits, duplicate rejection, preserved conditions/exceptions and execution evidence. Proposals remain candidates; the complete ACE adaptation loop is not yet integrated. |
| [SkillOpt](https://github.com/microsoft/SkillOpt) | Bounded procedure edits driven by scored trajectories and held-out evaluation | Keep proposal generation separate from protected evaluation and promotion. Do not equate a successful task, a plausible lesson or retrieval with demonstrated procedure improvement. Native-session rollout evaluation is still required. |
| [ShinkaEvolve](https://github.com/SakanaAI/ShinkaEvolve) | Separate candidate generation, execution evaluation and program archive; sample-efficient search | Keep independently measured correctness and timing as the gate for executable improvements. Retain the current small optimizer until there is a measurable bottleneck and enough evaluation signal to justify broader search. |
| [McSema](https://github.com/lifting-bits/mcsema) | Separate control-flow recovery from instruction translation; reuse an established intermediate representation and toolchain | Continue using Ghidra/SLEIGH and independent execution machinery. Investigate mature lifting engines for broader executable reconstruction rather than treating the bounded interpreter as a complete platform. McSema itself is archived and is not adopted as a new dependency. |

## Implemented changes

- Freestanding C candidates compile in a temporary build directory. ELF extraction
  rejects unresolved relocations and external dependencies. Candidate code runs
  in Unicorn; the candidate executable is never launched directly on the host.
- Protected original bytes and boundary/random cases are retained before a task
  begins. Completion recompiles the actual candidate and compares scalar return
  values, preserved registers and stack balance. Input/output widths and the SysV
  x86-64 calling convention are explicit. Passing these cases is not a proof over
  all inputs, memory effects, operating systems or complete applications.
- Read-only replay-safe computation batches persist each operation independently.
  Successful results survive restart; a failed independent computation does not
  discard the other results. Missing model allowance does not block retained work.
- Response deadlines use bounded persistent backoff. Admission and native request
  identity remain enforced. Missing sign-in, ambiguous delivery and model mismatch
  are not treated as permission to resend or switch transports.
- Playbook edits retain unrelated entries exactly. Context selection ranks relevant
  active assets within a character budget and excludes invalid dependencies or
  incompatible route bindings. Sharing restrictions continue to apply.

## Remaining integration work

The strongest next investments are full Hermes task/role coordination, function
call graph manifests, cumulative builds, richer platform observation and a real
native-session procedure optimization benchmark. A larger collection of framework
wrappers would not substitute for those end-to-end capabilities.
