# HA integrator: public donor cache verified-key and Windows-safe source paths — 2026-11-06

**CHECKS PENDING / AWAITING CI / independent source and license review.** This is HA-only source-identity engineering, not a compiled emulator, completed MZ/NX runtime reuse or proven Windows integration. No private source, donor binaries, archived games/firmware, GitHub Actions, paid model API, alternate mode or credential material were accessed.

## Exact source scope and implementation

- Before-work HA main: `e16bc65e621d3309c016bf61c96ec9ed812a8949` (2026-11-06 22:32:43 UTC); original donor-cache blob `2a6fa42022a777bd8bc402079b2efdd8f00e436c` and test blob `a6d03dec87218d52c01a142dd9f42d96b0ba50dd`.
- Source commit `7b336525e5506c592dea76d03a53e69ba1994fe4`; `donor_cache_gate.py` blob `34cbc9c3ca5f63c8cb2ab1e3f431e412a78a8272`. Adds `cache_key_with_inventory(candidate,build,inventory)` and `verified-key CANDIDATE.json BUILD.json INVENTORY.json` CLI. The new path *first* applies the existing complete pinned Git-tree structural gate, then computes the stable source/toolchain/build key. The old `key` and `verify` commands remain metadata-only for backward compatibility; do not promote them to evidence of complete source provenance.
- The same source update rejects Windows-forbidden filename punctuation, CONIN$/CONOUT$ devices, .git path components, and individual components exceeding 255 UTF-16 code units, in addition to existing device names, trailing dot/space, traversal, symlink/submodule and ancestor checks. Portability checks reduce cache-key/output mismatch risk on Windows; they are not a Windows-runtime test.
- Test commits `f9def7d5e7e0f36f0a47d30dd0d04c2c11a4def0` and corrective `c5ac26e500bcb584d9df73232542560caa67c393`; final test blob `1a30f9bf4078a7271b9acf2d2a4ed6beca77d7e9`. Two new unittest methods check Win32 negative/positive source identities, structural complete-inventory success/failure and the `verified-key` command's JSON I/O.

## Deterministic checks and evidence levels

- **Executed locally:** 26 source-matched extracted-Python `_path` predicate probes: 19/19 malicious/nonportable negative cases rejected and 7/7 portable positives accepted. No failures. This is an isolated subset, **not an imported-module test**.
- **Read-only verified:** exact GitHub source/test blob readbacks; 22 workflow trigger headers checked. `.github/workflows/test.yml` retains broad push trigger and browser fixture Ubuntu 24.04 pin. All changes used `[skip ci]`, which suppresses eligible push/PR workflows but does not guarantee all other triggers. No workflow was dispatched.
- **Unexecuted:** all 11 authored `test_donor_cache_gate.py` methods plus five `test_donor_inventory_pages.py` methods; full HA pytest; real GitHub inventory traversal/credential-free origin attestation; MZ/NX donor compiles, Windows/Linux smoke/parity/performance checks, live ChatGPT browser, external MCP, independent security/license qualification. No current-source CI green claim.
- **Local reproduction, when an actually authorized checkout is available (no Actions):**
  `cd dev/continuous_execution/ha_shift_state && python -m py_compile donor_cache_gate.py test_donor_cache_gate.py donor_inventory_pages.py test_donor_inventory_pages.py && python -m unittest -v test_donor_cache_gate.py test_donor_inventory_pages.py`
  Example cache key gate: `python donor_cache_gate.py verified-key candidate.json build.json pinned_complete_inventory.json`. An untrusted JSON file asserting `complete: true` does not prove actual GitHub content was fetched.

## Foreground integration and next ready milestone

- Foreground-owned `_app/hivemind_assembly/integrations/github_public_source_inventory.py` blob `4849c4c35945b1d6904719642b81dc9cec178eaa` provides public pinned Git-tree capture. Newly foreground-owned `github_public_submodule_verify.py` blob `91ca055981685092fd45d7204a838d31280e9e84` separately checks pinned public gitlink identities; **this conservative cache gate intentionally still rejects unresolved submodule source entries** rather than treating remote commit verification as full dependency bytes, nested-submodule or license clearance. Do not edit these other-worker sources without reallocation.
- District Manager next: assign independent full-module Python 11+5 test execution and review of the cache API, then a first-party public source/tree capture with immutable root tree identity, dependency license review and an explicit cache hit/miss performance baseline; only then stage a Windows build/runtime experiment. Keep core native-event/browser and whole-HA acceptance markers unresolved.

## Transient failure / corrected receipt

An initial test-source commit accidentally produced malformed test-fixture text `bad = ('CONIN, 'conout$.txt'` due a local string-replacement expansion of a dollar-quote sequence. **It was detected during exact GitHub source readback, corrected in `c5ac26e...` and the exact literal `'CONIN$'` was independently re-read from the final GitHub blob.** The earlier malformed revision must never be treated as a passing test or used as a build pin. No intended HA destination remains missing; source bytes are saved online. A sanitized FILE_FAILURE_EVENT will be included in the run result for the transient verification failure.

All writes stayed within the assigned HA integrator evidence/test paths. No additional automation, CI invocation, release promotion or external uploader/ZIP was needed.
