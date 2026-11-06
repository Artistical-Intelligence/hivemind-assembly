# HA integrator: portable public-donor tree and cache identity hardening — 2026-11-06

**CHECKS PENDING / AWAITING CI / independent source and license review.** Temporary emulator/runtime-reuse priority; HA-only evidence lane. Public donor metadata only. No RE-Wizard or private project access, no game/firmware/archive execution, no GitHub Actions dispatch or paid API.

## Source and changes

- Initial inspected HA `main` commit: `2f7d63dbf472ee591fe3bd9cc6a5249b8c5cfbea`; exact upstream source documents/AGENTS/ChatGPT policy and existing donor cache/paginated inventory implementations read through inline `mcp__GitHub__fetch_file/fetch`. New published state through `b6ab5a37f025e583f0d415fa90c686ddcba26cf8` (verify fresh HEAD before relying on this as latest).
- In integrator-owned `dev/continuous_execution/ha_shift_state/donor_cache_gate.py`, blob `2a6fa42022a777bd8bc402079b2efdd8f00e436c`, reject Win32 device components such as `CON`, `NUL.txt`, `COM1`, `LPT9.dat`, superscript-digit device aliases, and trailing dot/space in every source/license/inventory path. These can otherwise collide on Windows while Git paths remain distinct on Linux. Continue to reject traversal, absolute paths, backslashes and ADS colons.
- The full-inventory gate now requires exactly Boolean `submodule` and `symlink` metadata (no integer/string stand-ins), a proper `tree/040000` entry for **every** ancestor of every nested path, and no blob `size` attached to a tree. Contradictions fail closed. This is source-identity hygiene, **not** a proof that untrusted JSON is a genuine GitHub response.
- In integrator-owned `dev/continuous_execution/ha_shift_state/test_donor_cache_gate.py`, blob `a6d03dec87218d52c01a142dd9f42d96b0ba50dd`, extend reserved-name/Unicode/trailing-name, missing ancestor, file-as-parent, type-confused flags, and bogus tree-size negatives. Add a positive **two-page cursor-stitch to final cache-gate** contract and negative missing-parent case. Existing candidate manifests and the separately owned `donor_inventory_pages.py` (blob `497e709ff6ec47169edfc755ddfb2c56cb19e698`) were not modified.
- Ordered five `[skip ci]` commits: `14c861f4d290af878810d9601ebcf0e5bc9e9f1f`, `23b28c623eb1e97bda92a18eca931613713ec088`, `81263059be728b2cd6482e28d9228fc66284e4c8`, `84a245b98b8e632be172ff5f11d08ca1bbb5cbd4`, `b6ab5a37f025e583f0d415fa90c686ddcba26cf8`. GitHub blob readbacks matched the exact submitted text. Comparison against `2f7d63dbf472ee591fe3bd9cc6a5249b8c5cfbea` showed only the two authorized code/test paths (22 additions, 2 deletions code; 49 additions, 2 deletions tests).
- Read-only GitHub Actions latest 12 run metadata as of this checkpoint contained **no new matching source SHAs**; historical runs remain historical evidence, and this bounded metadata read is not definitive trigger/account billing assurance. The broad `.github/workflows/test.yml` push trigger remains intact; no workflow or approval rules changed.

## Bounded local execution / explicit limits

The accessible local Python sandbox ran `python /tmp/ha_donor_portable_predicates.py` and `python -m py_compile /tmp/ha_donor_portable_predicates.py` against copied, source-matched path and ancestor-checking predicates. **3 unittest functions passed**, with 6 acceptable portable paths, 15 invalid/reserved-path cases and 4 missing-parent/flag-type structure variants; **0 isolated check failures**. These are **extracted-predicate synthetic checks**, not execution of the imported full GitHub source module. The new integration regression is authored and remotely verified, **not executed**.

**Unexecuted (0 run):** full `test_donor_cache_gate.py` (9 authored unittest methods), `test_donor_inventory_pages.py` (5), repo-wide HA pytest, donor builds/CTest, Windows/Ubuntu paths, actual GitHub API cursor traversal, real cache performance, live ChatGPT browser, external MCP, qualified independent license/security review. Source-independent metrics must not be inferred. No opaque donor artifacts were downloaded.

Reproduction when a permitted local source checkout is available (never GitHub Actions until owner reinstates):
```sh
cd dev/continuous_execution/ha_shift_state
python -m py_compile donor_cache_gate.py donor_inventory_pages.py test_donor_cache_gate.py test_donor_inventory_pages.py
python -m unittest -v test_donor_cache_gate.py test_donor_inventory_pages.py
# For trusted first-party public synthetic captures only:
python donor_inventory_pages.py CANDIDATE.json PAGE_ENVELOPES.json
```

## Negative review / handoff for District Manager

- Require actual pinned GitHub `root_tree_sha` read evidence and unaltered continuation envelopes before trusting any purported complete manifest; a self-asserted `complete=true` remains insufficient against forged data. For each source path, real Git-tree ancestor entries must now be present.
- The portable-name check addresses known Win32 device/trailing-name hazards, **not** an independent cross-platform filesystem proof (NTFS normalization, case folding, extended path or nested submodules need qualified checks).
- Foreground MZ/NX cache work and qualified license notices must be reconciled separately; this gate can identify unsafe source metadata but does not import a working runtime/backend or measure speed. Maintain CPU fallback, graphics/service/IO/audio compatibility, and first-party synthetic runtime/parity checks as separate adoption gates.
- Native ChatGPT browser/provider, full Linux/Windows suite, Windows Unicorn/Speakeasy crashes, strict core receipt authorization and final lease-fencing remain unresolved under original owner scopes.
- **Next ready milestone:** authorized local full-module Python 9+5 tests, independent source review, real page() first-party public synthetic source inventory, and then source/toolchain/cache performance comparison. Do not falsely promote any cached donor build as reproducible without these gates.

**Artifact persistence:** both intended source/test files created by GitHub update and SHA read-back verified. No FILE_FAILURE_EVENT or owner ZIP is applicable. Documentation and status will be separately committed/read back. No private task IDs, donor binaries, credentials or license approval exported.
