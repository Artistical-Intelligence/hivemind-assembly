# Foundation and dependency provenance

The workbench preserves separate complete foundations rather than copying selected proprietary functionality into replacement implementations.

- Hermes Agent — https://github.com/NousResearch/hermes-agent — pinned `c0015464f0f40d52c5702a84cf58e70361f4a04c`. Complete checkout installed separately. MIT notice remains with upstream. The native host uses its SessionDB; the optional plugin registers an additive CLI command.
- REA — https://github.com/morluto/rea — pinned `ca71e91d23672646af917ede8ae82c7fea395341`; complete npm package `rea-agents@6.7.0`. Upstream license and third-party notices remain intact. Broker adapters invoke managed CLI processes.
- Ghidra — https://github.com/NationalSecurityAgency/ghidra — release `Ghidra_12.1.4_build`. Complete release archive SHA-256 `ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db`. Ghidra's license and bundled notices remain in the distribution. WorkbenchBridge.java is an additive script.
- CPython 3.12.10 Windows embedded distribution — https://www.python.org/ftp/python/3.12.10/ — bundled unmodified with its license. Archive SHA-256 `4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3`.
- pip 25.0.1 — bundled unmodified wheel with its license metadata. SHA-256 `c46efd13b6aa8279f33f2864459c8ce587ea6a1a59ee20de055868d8f7688f7f`.

Python dependencies are installed from the pinned versions in requirements.txt, retaining their installed distribution notices. They include Playwright, pypcode (Ghidra SLEIGH binding), Unicorn, Z3, pypdf and the dependency subset required to import Hermes session persistence. Ghidra instruction semantics are reused through pypcode; Unicorn is the independent execution path. Original workbench code is not represented as an upstream contribution or an upstream-certified integration.

Runtime browser authentication, user documents, original target binaries, controller data, private local paths and accounts are not included in this release or source package.

- musl memory routines — https://git.musl-libc.org/cgit/musl — v1.2.6,
  commit `9fa28ece75d8a2191de7c5bb53bed224c5947417`, retrieved from the
  https://github.com/ifduyue/musl mirror. `memcpy.c`, `memmove.c`, `memset.c`,
  `memcmp.c` and the complete MIT `COPYRIGHT` are retained unmodified under
  `hivemind_assembly/vendor/musl`. Source hashes are checked before each program
  build. Integration adds compiler-defined ABI types and weak definition wrappers
  in temporary build files. The copyright notice is also embedded in generated
  PE/ELF images and checked after linking. No musl syscall or host-OS layer is
  linked by this integration.
