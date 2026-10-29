# Scoped runtime documentation and acquisition review

**Final result: PASS for the exact three documentation files identified below.** An initial metadata omission was corrected by the integration owner and the corrected manifest was rechecked. No unresolved finding remains in this scope. This result does not approve runtime implementation, a release, execution of acquired tools, or Windows acceptance.

Review date: 2026-10-29 15:20:07 UTC.

Reviewer: independent review worker `/root/scope_review`; same provider, separate worker context. The reviewer made no repository edits, commits, pushes, installations or runtime invocations. The only written output is this review draft outside the repository.

## Scope and exact reviewed content

The scoped request was to review the new **Setup UX preference** section of `AGENTS.md`, `dev/RUNTIME_ANALYSIS.md`, and `dev/runtime-tool-sources.json`. The comparison base observed in this local worktree is `733473c39f34713768e54755deb0a58d99cc54b1`. At final inspection, this worktree still has that HEAD, with only these three files changed or added. The integration owner reports that the final timestamp correction was published at `e3f651c3571974d690c67d58629141733dd7aa73`; that publication was not independently inspected by this reviewer. Content hashes, rather than that reported commit, identify the reviewed result.

| File | Bytes | Reviewed SHA-256 |
| --- | ---: | --- |
| `AGENTS.md` | 8,059 | `30b4c875a67faebc96ab58a66edd23c3a0fab1ff28fcb97f7e872769da985f02` |
| `dev/RUNTIME_ANALYSIS.md` | 8,335 | `4df02cfe0d3c0dce1acfa6224356739084c4fc25d141a3f5e486e02a88a2ffaf` |
| `dev/runtime-tool-sources.json` | 15,326 | `3b82c04e6a2a565d1d064b24125322afc42536559bb574d022d6a7b24b3870b9` |

The HEAD version of `AGENTS.md` has SHA-256 `57cd885bbc7302b4b12b0d728c6435bdcc75b94ef2d744aeb46b6f912daf5611`. Removing only the inserted Setup UX preference block from the reviewed file reproduces that HEAD file byte for byte. The inserted block, including its leading newline, has SHA-256 `e58d5bd1ba0728221eb899b5b28dc6edab6676b005a40f2f3020a422a8b883f8`.

Architecture evidence: `dev/ARCHITECTURE.md`, SHA-256 `4d170f8acf19ab9d9c347ef697308febd75ea9a756ce2832361d32afd4381a66`, including modular-monolith responsibility boundaries, complete Ghidra/REA, optional MCP, deterministic broker state, native-execution permissions, source restrictions and measured acceptance. Relevant README and release-status passages were inspected for existing native-execution and live-validation boundaries; historical claims were not retested or adopted as new evidence.

## Results

| Check | Result | Evidence and conclusion |
| --- | --- | --- |
| Setup preference change is limited to its requested section | PASS | The new section is the only change relative to the observed base AGENTS.md. Existing architecture, access, recovery and check rules remain byte-identical. |
| Prefilled setup and authorized continuation | PASS | Known names, endpoints, callbacks, settings and task-required permissions are prefilled; confirmed values are reused and provider acceptance is verified. Credentials stay in provider or secure local flows. Manual fallback covers unverifiable automation. |
| No added user-consent gate | PASS | The section explicitly continues already authorized setup. User action is reserved for steps that actually need it. Existing native-execution permission and genuine provider-only input are preserved. Showing a concrete command/target is visibility, not an added approval requirement. |
| Six requested runtime tools and guard are represented | PASS | Frida, x64dbg, TTD, WinDbg, Cheat Engine and exoproc each have an intended-operation row. The exoproc requirement checks fresh RIP against target ntdll with owned suspension, fail-closed errors and balanced lifecycle paths. |
| Abandoned whole-application merger stays abandoned | PASS | The earlier Ghidra/Hopper/Binary Ninja combination is explicitly not a current requirement. The missing abandonment discussion is acknowledged without inventing reasons. Historical documentation does not authorize restarting that idea. |
| Full foundations and architecture retained | PASS | HA remains the application owner; Ghidra, REA and Hermes remain complete foundations. Runtime naming is provisional. Direct specialist calls remain primary, MCP optional, and reusable core boundaries remain intact. |
| Honest implementation and acceptance status | PASS | The design labels operations as intended, explicitly pauses broader runtime implementation, and distinguishes acquisitions and the exoproc patch. The manifest is expressly an acquisition list, with execution and live-Windows validation false. No live behavior, debugger synchronization or reconstruction equivalence is inferred from acquisition or launch. |
| Exact acquisition data and bytes | PASS | All 24 entries match their corresponding source records for every retained field. All 24 actual files match both manifests by SHA-256 and byte size. Total acquired bytes checked: 1,901,330,887, including the bundle and its extracted x64 member. |
| Exact revisions and source URLs | PASS | Release assets have pinned versions, source archives encode complete commit IDs in their codeload URLs, and the Microsoft SDK commit and NuGet version are retained. The mutable appinstaller acquisition URLs are distinguished by captured file hashes and retrieval times; actual runtime bundles have versioned URLs. |
| Acquisition timestamps | PASS after repair | The initially omitted x64 MSIX extraction time is now copied exactly from source. All 24 entries contain their original download, retrieval or extraction timestamp. |
| License and distribution boundary | PASS | The document preserves separate licenses/notices, keeps complete downloads outside HA, keeps CE private-use source outside public artifacts, and does not treat SDK MIT licensing as permission to redistribute Microsoft runtimes. |
| Credential and signed-URL exposure | PASS within stated scan | Manual inspection and bounded pattern scans found no credentials or private keys. All 44 HTTPS references across the three files have no query strings, embedded username/password or signed-token parameters. Hashes and public revision identifiers are ordinary provenance. |

### Corrected finding

Initial `dev/runtime-tool-sources.json` SHA-256: `a84bdb9f00e8238e4cb2c5067c8e8648e18df13d482739dd9ca1ad407e1d55af`.

The entry for `windbg-1.2610.1001.0-x64.msix` lacked a retrieval or extraction timestamp, despite the acquisition documentation requiring a timestamp per artifact. Its Microsoft source record had `extracted_at: 2026-10-29T15:12:34.480824+00:00`. The integration owner inserted that unchanged value. Final manifest SHA-256 is `3b82c04e6a2a565d1d064b24125322afc42536559bb574d022d6a7b24b3870b9`. A fresh comparison found no differing retained field and no missing artifact timestamp. This was a provenance-completeness issue; no acquired file hash or size changed.

## Source evidence

| Source | SHA-256 |
| --- | --- |
| `traceweave/downloads/open-source/provenance.json` | `5366b5a8a71cdc558cff1466d736be7c3c3d5035d9bba29b0b8a8b32f619eeb7` |
| `traceweave/downloads/microsoft/provenance.json` | `f95b5b8f22d7667024c3e5fe29cc936ebb5123f6c28bd262b258c881af5cfbb2` |
| `traceweave/downloads/microsoft/WinDbg-EULA.txt` | `002a00e12733b526ccec64d87bb8b270b9b2d507605089c383349e086e61f3e4` |
| `traceweave/downloads/microsoft/TTD-EULA.txt` | `bbc8ef5ef5e52e6c3150ece17ca821495609e27e45d0139354ec0e44b9f13a49` |
| `traceweave/downloads/microsoft/WinDbg-Samples-LICENSE.txt` | `27ebda9d51f0a56b7e281ccd8230a27236dcb51c05f64b07869ecf6e965d68b0` |
| `traceweave/engines/exoproc/LICENSE` | `19a7be2cfe9ab64e9c8d55b9d203e4bb8a55575027920c523a0d13520acb1fe7` |

The source manifests comprise 17 open-source-directory acquisitions and seven Microsoft-directory acquisitions. The collection name is a source-folder label; it does not override Cheat Engine's stated license boundary. The final HA manifest has no missing or extra acquisition relative to those two sources.

The upstream exoproc commit `949b6f7117271daffa70efbd4b7140c764f831d0` exists in the local repository. Its retained history has five reachable commits and the repository is not shallow; its upstream remote is `https://github.com/w0ldan/exoproc.git`. The retained license is MIT. These checks support the stated pinned upstream/history/license facts; the exoproc implementation and tests are outside this documentation review.

The WinDbg bundle was opened as a ZIP and its `windbg_win-x64.msix` member was streamed through SHA-256 without extraction or execution. That member is exactly 404,832,537 bytes with SHA-256 `959c4ec033e2d00f7ed75646e4d352cc7cff6de33f494fd5dccb83819fe64e7a`, matching the separately acquired x64 file. The TTD API package's `.nuspec` was read as XML and declares MIT; that metadata does not license the TTD runtime. The separately retained Microsoft runtime terms contain distribution restrictions, and the TTD terms also contain use restrictions; the scoped documents do not assert broader rights.

Two current primary pages were opened during review on 2026-10-29:

- [Cheat Engine FAQ](https://cheatengine.org/faq.php), source lines 59–64: supports the document's private-source-use and no-public-modified-source-grant distinction.
- [Microsoft TTD command-line documentation](https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/time-travel-debugging-ttd-exe-command-line-util), source lines 46–51: supports the distinction between ending a recording and removing recorder instrumentation from a process. The scoped text does not promise complete detachment after stopping.

## Independently rehashed acquired artifacts

The listed SHA-256 and size were computed from actual local bytes using Python's standard-library hashing, with no import or execution of downloaded code.

| Artifact | Bytes | Actual SHA-256 | Result |
| --- | ---: | --- | --- |
| `frida-gadget-17.24.3-windows-x86_64.dll.xz` | 9,254,948 | `e59f5719ea42d9d7d71ca49734d57c60469881c6b96a34cdaff473d10e53d117` | PASS |
| `frida-inject-17.24.3-windows-x86_64.exe.xz` | 26,612,228 | `20e6f32ae69fa68d44fbdfcdf49c44219350e60447082b3389a29ec61a6dd996` | PASS |
| `frida-server-17.24.3-windows-x86_64.exe.xz` | 26,623,300 | `940e2d806f9c83daa378eefc476cf9fd2be2718a7916e9abbf6e33426657b759` | PASS |
| `x64dbg-pluginsdk-cmake.zip` | 104,642 | `b669d6364816cbaed5257adad0df34a98a1791810a81941191d6f4aea74eb04e` | PASS |
| `x64dbg-pluginsdk.zip` | 108,710 | `52cbb9652dcae9a386d8ca94b46c3a291c3e791b36d1407fb1e1f0d36515e10f` | PASS |
| `frida-adf8be5f5b7f.zip` | 50,301 | `e431b39749c2aed3eb5026020238d082ee0197b7ce99ec28017b3df63fb2ee95` | PASS |
| `snapshot_2026-05-27_12-11.zip` | 31,526,833 | `d41966dfc5b435a372798245300ca0ab7bb8e48bdbf48512c6fb20fcca427697` | PASS |
| `symbols-snapshot_2026-05-27_12-11.zip` | 8,775,777 | `37e37f2f9312d8c3bc75610508c191ac3404d8d4f21c8409b3961945b772847c` | PASS |
| `frida-core-57161b0ddd23.zip` | 4,937,900 | `6c15973832364e1bd97545a43ce151860ca6599062f98d89138cba79b08e22d8` | PASS |
| `frida-python-b43e681df376.zip` | 389,255 | `e14c305b21b20878f545105cb1e0b06ece8ed55dac9e9eed45bc9739291d4bf4` | PASS |
| `frida-tools-330ed423f71b.zip` | 228,772 | `f4a7804e2f12afd6684dcadcda1461dd3e30d5068951c89f77f293f28375eaa2` | PASS |
| `x64dbg-9c8ca1cae0b6.zip` | 5,140,299 | `62173b2dcd5fdb1177468ac66f4a51793893d05d82e104ecb98a051640577429` | PASS |
| `frida-gum-3f82ef6a5b24.zip` | 14,746,764 | `19f3231ce1e455fb3cf72ff305df4e5fdd3ea22c840c646f94e0ce08f4fd2dd7` | PASS |
| `cheat-engine-ec45d5f47f92.zip` | 15,650,458 | `798588da392b53de1111772b88befe260a89d4ad7e3209fb5daef8e4bb141f24` | PASS |
| `frida_tools-14.11.0.tar.gz` | 4,690,429 | `b8c772e59502be43b76df9feccadd5d342b5ca325066dd0c2384e63fa88da921` | PASS |
| `frida-core-devkit-17.24.3-windows-x86_64.tar.xz` | 71,938,148 | `42af54ded8be200b461d6e75066bc2c781878a6afd249c940dd8888158a9bf3a` | PASS |
| `frida-17.24.3-cp37-abi3-win_amd64.whl` | 58,039,965 | `61f5a53b146e0e7755d6c2bfa5405e14fe2373818ae5d98105c4eeca3face7d1` | PASS |
| `windbg.appinstaller` | 685 | `230a7455d4f527ff588fa0ba6b7d3d7f735e0b57a0e65689ee855ddc4e7252a6` | PASS |
| `windbg-1.2610.1001.0.msixbundle` | 1,203,512,387 | `4662ae17bc0dc77db987b89cccea32c30058baa06268f861d09e0ab4e4f45c20` | PASS |
| `windbg-1.2610.1001.0-x64.msix` | 404,832,537 | `959c4ec033e2d00f7ed75646e4d352cc7cff6de33f494fd5dccb83819fe64e7a` | PASS |
| `ttd.appinstaller` | 664 | `bdbc65f468e7a3d90dd61154d0b02444096f118c42dd47554d012afa40d03731` | PASS |
| `ttd-1.11.611.0.msixbundle` | 7,203,028 | `b0b9f7f9a9ff526f81f491311af931eb69e2a8b0affdca49e864195eca6f89ce` | PASS |
| `WinDbg-Samples-e987a6667b96.zip` | 6,887,296 | `98d76caf88c312918d0cd06ee1c9e88794add39ab8b62558862459b27c24e53d` | PASS |
| `Microsoft.TimeTravelDebugging.Apis.0.9.5.nupkg` | 75,561 | `c906b99c02926ce089e1ed1bd54f1a0abf83458ddce4cf9bbc62403d7aa240bd` | PASS |

## Limits and handoff

- This is a documentation, scope and acquisition-provenance review. No runtime source was edited or integrated by this reviewer, and broader runtime code remains paused according to the scoped design.
- This reviewer ran no downloaded executable, installer, package build, Frida binding, debugger, TTD recorder, CE code or exoproc runtime. Source-manifest non-execution declarations were compared for consistency; activity in unrelated sessions was not independently audited.
- No Windows process behavior, thread suspension, attach/detach, replay, cancellation, target survival, Authenticode signature, provider form submission or live-agent acceptance was validated. The design correctly reserves those as later evidence.
- The hashes establish equality to the observed files and provenance records. Upstream digest verification flags were faithfully retained, but upstream service responses and every publisher digest were not independently fetched again.
- The integration owner reported `python dev/status_docs.py --check` passed. This reviewer did not rerun that check or the full test suite, and does not count that report as an independently executed test.
- Bounded secret-pattern and URL scans are not a general data-loss-prevention proof. All scoped text was read and no secret or signed URL was observed.
- This draft is for the single integration owner to place in the repository's normal check-report workflow and reconcile pending markers. It is not a release or publication authorization. Any change to the three reviewed files invalidates the corresponding content hash and requires checking the changed material.
