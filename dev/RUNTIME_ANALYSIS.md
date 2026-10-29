# Runtime analysis in Hivemind Assembly

## Scope and name

The owner requested Frida, x64dbg, Microsoft Time Travel Debugging (TTD),
WinDbg, Cheat Engine (CE), and a personal exoproc fork as one reverse-engineering
tool. They also required a RIP check around ntdll critical sections in exoproc
and prefer prefilled setup forms, known settings and required permissions.

Hivemind Assembly remains the application and integration owner. **Hivemind
Runtime** is the proposed name for the runtime-analysis subsystem and personal
source fork; the name is under discussion. This does not replace the existing
Ghidra, REA or Hermes foundations or create a competing agent runtime.

Keep the existing reusable automation and learning core separate from the
reverse-engineering domain. Direct specialist calls remain primary; MCP is an
optional interface. Keep complete native tools available where their specialist
features exceed the shared interface.

## Relationship to earlier integration work

| Layer | Role |
| --- | --- |
| Hivemind Assembly | One application, project state, setup, orchestration, evidence, verification and reusable learning |
| Ghidra and REA | Existing static analysis, decompilation, P-code and program structure |
| Runtime analysis | Process discovery, live instrumentation, memory observations, native debugging, recording and replay |
| Reconstruction and testing | Existing build/compare loop; runtime observations become evidence and reproducible test inputs |
| Other planned specialists | decomp-toolkit, objdiff, platform recompilers and emulators remain part of the broader design, without claiming they are implemented merely by naming them |

The useful shared object is an investigation: a pinned program/build, process
identity, module mapping, addresses, observations, traces and artifacts. Preserve
module identity and relative virtual addresses so ASLR-adjusted live addresses
can be related to the correct static image. An address from a different build,
architecture or trace position must not silently be reused.

A representative workflow is: identify a function in Ghidra/REA, select the same
build in a live process, inspect it through Frida or a native debugger, retain a
TTD recording when appropriate, then turn observed behavior into a controlled
reconstruction comparison. A matching address or successful launch alone is
not evidence that a reconstruction is equivalent.

## Initial integration boundary

| Engine | Intended direct operations | Boundary |
| --- | --- | --- |
| Frida | Structured module enumeration and bounded memory reads through its supported Python/JavaScript APIs | Optional binding loaded only in a separate bounded worker; attach and detach outcomes remain explicit |
| x64dbg | Typed native launch and attach; preserve its full UI/plugin capabilities | A dispatched process is not proof of successful attachment or synchronized breakpoints |
| WinDbg | Typed native attach, launch and trace opening | DbgEng and the supported debugger data model are the path to deeper synchronization |
| TTD | Separate recording, stop-recording and replay operations | Stopping a recording must not terminate the target; recorder instrumentation can remain until target exit |
| Cheat Engine | Native launch and generated cheat-table handoff using documented Lua functions | Preserve CE's own script prompt/settings; do not invent a Lua command-line switch |
| exoproc | Source-matched local build, structured doctor/process discovery and retained native CLI/MCP capability | No invented attach flag; a published unpatched binary is not evidence that the local guard is present |

Live operations use the existing owner-enabled native-execution boundary and
broker operation identities. Side effects are not discardable computations.
Journal dispatch intent before starting an interactive tool; an uncertain
dispatch must not be retried as if no external action occurred.

Use one invasive debugger/instrumentation owner per target by default. Tool
handoff is explicit, and closing a UI or sending a stop command is not proof that
a debugger detached. Do not consume another debugger's suspend count. Preserve
existing settings and obtain genuine user-only input in the provider/tool's own
secure flow when necessary.

## exoproc acceptance requirement

Before redirecting a candidate thread, inspect a fresh context while holding
only the suspension acquired by exoproc. Resolve the target process's ntdll
mapping and reject a candidate whose RIP falls in that mapping. This conservative
range includes internal critical-section routines without relying on an
incomplete exported-name list. Missing mapping/context or invalid ranges must
fail closed. Balance suspension and handle ownership on every path, including
rejection, exceptions, retry and hibernation/restore.

A controlled spin stub already established by exoproc requires an exact retained
parked-state check; an arbitrary flag or caller-supplied context cannot bypass
candidate validation. RIP outside ntdll is a minimum exclusion check. It does
not establish that the thread holds no loader lock or other lock acquired earlier.

Tests must distinguish pure range/ownership checks from actual Windows thread
behavior. A checked-in patch is not a live-Windows validation claim.

## Acquisition and packaging

Use official pinned releases/source revisions and record SHA-256, byte size,
source URL and retrieval time in `runtime-tool-sources.json`. Preserve each
engine's original license and notices. Keep complete third-party downloads
outside this repository.

Microsoft runtime packages are separately licensed components. The TTD SDK
headers/samples have their own license and do not relicense the runtime.
Cheat Engine's current FAQ describes private source use without a grant to
publish modified versions; keep CE source out of the public HA repository and
use the owner's local installation. Do not collapse these distributions into
one newly licensed source tree.

Setup should discover existing installations, prefill verified paths and
settings, show a concrete command/target before execution, and provide the
supported download or installation route for missing components. A failed
discovery remains a visible missing dependency rather than an invented success.

## Verification gates

1. Check exact official command syntax and downloaded artifact hashes.
2. Test command validation, address bounds, native-execution policy, target
   conflicts, dispatch recovery and structured output handling.
3. Run the existing architecture/broker and applicable application checks, then
   the repository's combined checks; retain failures or environment limits.
4. Independently review source, tests, provenance and integration boundaries.
5. On Windows x64, exercise the patched exoproc path and the actual installed
   tools against a controlled target; verify attach/detach, TTD stop/replay,
   evidence correlation, cancellation and target survival.

This document defines integration and acceptance boundaries. It is not a claim
that all native capabilities or the Windows acceptance gate are complete.

## Primary references

- https://frida.re/docs/javascript-api/
- https://help.x64dbg.com/en/latest/introduction/Commandline.html
- https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/windbg-command-line-preview
- https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/time-travel-debugging-ttd-exe-command-line-util
- https://github.com/microsoft/WinDbg-Samples/tree/master/TTD
- https://cheatengine.org/faq.php
- https://github.com/cheat-engine/cheat-engine
- https://github.com/w0ldan/exoproc
