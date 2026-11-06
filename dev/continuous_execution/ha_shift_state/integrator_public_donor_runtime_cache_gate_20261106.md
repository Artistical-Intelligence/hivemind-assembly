# HA integrator — public donor runtime/cache engineering checkpoint (2026-11-06)

**CHECKS PENDING / AWAITING CI / independently qualified license and runtime review.** Owner's temporary emulator-runtime-reuse priority supersedes this team's earlier intake priorities, not its HA-only ownership or ongoing native-event/MCP obligations. No RE-Wizard repository or private code was opened.

## Actual HA source and scope

- Initial read: HA `main` commit `fa120d2df91bc28ba0eba0257cad93aedaa69dad`. New foreground-owned `_app/hivemind_assembly/integrations/github_public_source_inventory.py` blob `4849c4c35945b1d6904719642b81dc9cec178eaa` provides pinned, read-only public Git-tree traversal. This integrator neither duplicated nor modified it.
- Source policies read inline: `AGENTS.md` blob `4f68602fcce1b605a527f9521844143f1bbf4645`, `CHATGPT.md` `ef463012a2089f77896bbe97e96f9cd2101d44b0`, the authorized HA team instructions, and workflow definitions. Broad `.github/workflows/test.yml` blob `094ac74c77d5b6f7a08664ae45ecc6392cc78ac2` retains an unrestricted push trigger; each newly written evidence/utility commit used `[skip ci]`. The browser-fixture runner stays pinned to Ubuntu 24.04. No workflow was dispatched or changed.
- Only inline `mcp__GitHub__fetch_file`/`fetch` source/metadata reads, standard-library local Python, and HA-only allowed evidence/status writes. No source archives, opaque binaries, ZIP reads, private user files, paid model APIs, new automation, cross-project edits, or hosted approval bypass.

## Pinned public donors — reusable interfaces, not imported code

| Donor | Source-pinned evidence | Useful interface and blocker |
| --- | --- | --- |
| [Eglantine](https://github.com/Djihads80/Eglantine/tree/0857e8b4a792ac99b87af6bb6f329127aa7df683) | commit `0857e8b4a792ac99b87af6bb6f329127aa7df683`, tree `c5c4c575c76f011f2255c7b8436b1ad0014c0000`; `src/video_core/gpu_split.h` blob `836c46c79592693d2123d2699c10939a18d37612`; `.cpp` `07ac984222808937a0eb1516a2515a322151c86f`; `NX2_GPU_THREAD_SPLIT.md` `75fd0e4105ffaba8dcf3242e562f2c4699e9307e` | Ordered SPSC method queue, CPU/front macro register mirror, GPU/back renderer ownership and explicit drain synchronization. `EDEN_NX2_SPLIT=0` gives serial correctness fallback. Upstream-reported 1.46× throughput is NOT independently benchmarked here. GPL-3.0-or-later source header; root GPL v3 `LICENSE.txt` blob `f288702d2fa16d3cdf0035b15a9fcbc552cd88e7`. |
| [AnyPS5](https://github.com/boykopovar/AnyPS5/tree/c643163045dc52f1feb00d1cb303a148ce5058f7) | commit `c643163045dc52f1feb00d1cb303a148ce5058f7`, tree `0556a600aa3ab2c42931bd14b86b09bbee04ed33`; `core/relinker/CMakeLists.txt` blob `161798ae5131ee384ad4a9c0fd1d96a892b059cd`; `docs/dev/BUILD.md` blob `0ab14034884662d1314d5bf738892e04f181489e` | Isolated native x86-64 relinker: `cmake -S . -B build-relinker -G Ninja -DCMAKE_BUILD_TYPE=Release -DANYPS5_RELINKER_ONLY=ON -DBUILD_TESTING=ON`; `cmake --build build-relinker --parallel`; `ctest --test-dir build-relinker --output-on-failure`. **Commands NOT RUN.** Does not build target OS libraries. GPL-2.0-only per README; root LICENSE blob `a66a55f9806c0500ee810a8b13c024f34a6b2e16`. |
| [KytyPS5](https://github.com/KytyPS5/KytyPS5/tree/182161eb3e31439d97433607a8aa95463c56a9cc) | commit `182161eb3e31439d97433607a8aa95463c56a9cc`, tree `80598506283b8088a75c009d9979fc60deefad0e`; `src/graphics/shader/recompiler/ShaderRecompiler.cpp` blob `843894a79323b17fa46f1b195ca442db6fa245fc`; CMake blob `78d4963f128b061c0a92c8d75fd3119f38cb3336` | Decode/CFG/IR transformations to SPIR-V emitter; requires Vulkan 1.3 and Windows clang-cl/Qt/glslang per README blob `f32bc85307dfcae64df380024c1ae4cc4081861a`. CPU fallback/Windows integration unproven. Root GPL-2.0 license blob `ecbc0593737be657aef92e3adcf3bcbd6fdb812e`. |

All three source manifests have `license.review=PENDING`, `integration_status=SOURCE_ONLY_NOT_BUILT`. Root LICENSE detection is not per-file/dependency license clearance. Mixed GPL-2-only and GPL-3-or-later code cannot simply be merged into one binary without analysis. Source-level inspection is not runnable donor completeness, game compatibility, provider acceptance, or a claim of legal approval.

## Actual implementation and bounded local execution

The following exact files are committed under this integrator's authorized `dev/continuous_execution/ha_shift_state/` evidence lane, not other workers' code paths:

- `donor_cache_gate.py` — **source and build cache input gate** (Git blob `1e9331a4fb203132b0bed6e3ca1942f5157354ea`, local SHA-256 `6fcf74d6c08532bb11c3e46ff4092b2745c0b529fccd599910d5ed7e36b7c126`). Python stdlib only; no network or binary execution. Validates immutable repository/commit/tree, tracked source object and license hashes, unsafe paths/Windows case-fold collisions, host/target/toolchain/version/fingerprint, CMake options, dependency pins and patchset; emits domain-separated canonical SHA-256 cache identity. Local `verify_artifact()` hashes user-selected bytes and explicitly returns `runtime_tested=false`, `license_approved=false`, `independently_accepted=false`.
- `test_donor_cache_gate.py` — seven unittest functions with multiple negative subcases (blob `e37fd8ebd6e2f21ba8b6073ae049b54fe0701b62`): stable-order key, sensitivity to source/build/compiler/patch/dependency/license changes, unsafe/unpinned content, false approval, corrupted/cross-key/symlink artifacts, strict type validation.
- `candidate_anyps5.json` blob `59605163450dc0d80eeb41f03ed934199fe52c31`, `candidate_eglantine.json` blob `b8af78c6bf80926a59b03b7eebfe0dd4a82e0a03`, `candidate_kytyps5.json` blob `70e894037fcae9a8c97ca796c57e585dbb472588`: three independent exact-file public donor source snapshots.

**ACTUALLY EXECUTED in a permitted local Python 3.13.5 sandbox**, on byte-for-byte source code subsequently verified by GitHub blob SHA:

```text
python -m unittest -v test_donor_cache_gate.py  -> 7 passed, 0 failed (0.006 seconds)
python -m py_compile donor_cache_gate.py test_donor_cache_gate.py -> passed
python donor_cache_gate.py validate candidate_anyps5.json   -> PINNED_METADATA_VALID; NOT_BUILT; LICENSE_REVIEW_PENDING
python donor_cache_gate.py validate candidate_eglantine.json -> same
python donor_cache_gate.py validate candidate_kytyps5.json  -> same
```

No actual HA checkout/module pytest, donor compilation, CTest, Windows native runtime, GPU benchmark, opaque game/firmware binary, ChatGPT browser/provider, external MCP, independent qualified source review or release occurred. Self-asserted input fields such as `source_tree_complete` and compiler SHA-256 still need verification against actual Git-tree completion and a real local toolchain before a real build cache is trustworthy. This is a usable **cache identity/receipt gate**, not an emulation backend.

## Handoff and next acceptance

**District Manager/foreground:** consume the public donor pins, reconcile with the foreground's MZ output-cache and acquisition inventory without reading/copying private RE-Wizard material into HA. Complete per-file/submodule/license provenance, source-tree completeness, compiler/dependency fingerprints. **Backend owner:** choose a licensed, isolated, synthetic Windows relinker-only build first; retain a serial/fallback path for GPU split and explicit host graphics dependency checks; measure actual cold/warm cache timing and build/reconstruction behavior. **Independent verifier:** test real relinker-only CTest with synthetic fixtures on permitted Windows/Linux hosts; benchmark ordered GPU operations vs serial correctness before speed claims; verify negative cache corruption/changed input and license gating. Existing core durable-receipt authorization, lease fencing, Windows Unicorn/Speakeasy, MCP and real native-browser acceptance remain separately pending, and no Actions may run until owner lifts the stop.

All remote evidence/code writes are `[skip ci]`; their git blob SHAs were read back. Read-only GitHub Actions inspection after five code/candidate commits found **zero matching new runs** in the last 25 records, which is not a passing CI result.
