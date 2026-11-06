# HA integrator — inventory-bound public-donor artifact verification, 2026-11-06

**CHECKS PENDING / AWAITING CI / INDEPENDENT REVIEW.** HA-only public-source identity contract. This does **not** compile or validate emulator donor code, approve reuse licenses, attest a real remote GitHub tree, perform Windows runtime tests, accept a live ChatGPT browser/provider, or authorize private RE-Wizard access. No GitHub Actions, paid model API, private binaries, firmware, games or credentials were used.

## Source-pinned implementation and readback

- Before-work `main`: `dfeef2ca87ad8b548f8e9fe26ff1e33099fcc926` (2026-11-06 23:31 UTC); source blob `34cbc9c3ca5f63c8cb2ab1e3f431e412a78a8272`; cache test blob `1a30f9bf4078a7271b9acf2d2a4ed6beca77d7e9`.
- Implemented `verify_artifact_with_inventory(candidate, build, inventory, receipt, artifact_path)` in `donor_cache_gate.py` and new `verified-verify CANDIDATE.json BUILD.json INVENTORY.json RECEIPT.json ARTIFACT` CLI. The new path *first* validates a complete, pinned, structurally consistent Git-tree inventory (and rejects missing ancestors, unresolved symlinks/gitlinks, case collisions and mismatched required blobs) and *then* checks exact artifact size, SHA-256 and cache key. A source gate failure prevents proceeding to the artifact identity check. The old `verify` command deliberately remains **metadata-only** for compatibility.
- To make downstream claims unambiguous, the new verification result explicitly includes `source_inventory_structurally_verified: true` and `remote_source_authenticated: false`; inherited flags retain `license_approved: false`, `runtime_tested: false`, `independently_accepted: false`. Structural checks on supplied JSON do **not** authenticate the JSON's remote origin.
- Source commits: `e4f2d6fd2a0d7de2abf34fe6339513ec0cb57040` and `30bd77b5a678c023570346b8685067686a0c75d3`. Final read-back source blob: `02f4596356b9d38afe61f2fb476d307c9d6c7661`.
- Regression methods: added `test_verified_artifact_requires_complete_inventory_and_exact_bytes` to `test_donor_cache_gate.py`, including successful function and CLI invocation and rejection of incomplete/drifted inventory, missing required tree, mismatched source SHA, changed cache receipt, tampered output and invalid CLI inventory. Source test commits `b9674355877c480a62422a1929878468d82cc4df` and `69935118ea1903a584cdec32401da0f1b07ac17d`; final read-back test blob `3d12ddda66a0ee139843b416cfc1790e3d484d89`. The suite now contains **12 authored cache test methods** plus **5 pagination methods**, still requiring actual-module execution.

## Actual verification this shift

- Read exact current GitHub source/test via INLINE `mcp__GitHub__fetch_file`, checked new function, CLI argument mapping, test source and return flags against final blob identities. No attachment, GitHub MCP materialization, Files.materialize or binary fetch.
- Executed **one isolated, copied-source Python wrapper contract test** in an available non-Actions local Python 3.13 environment; 1 test passed, covering 1 positive and 10 negative variants (7 inventory failures and 3 artifact failures). `python -m py_compile` of that isolated probe passed. Simplified validator stubs were used in the probe, so it **does not prove the imported HA module or full inventory validator**.
- **NOT EXECUTED:** 12 actual `test_donor_cache_gate.py` methods, 5 `test_donor_inventory_pages.py` methods, any full HA pytest, real donor builds, native runtime, performance baseline, Windows/Linux compatibility, independent source/license review or native ChatGPT browser acceptance. No current-source CI green claim.
- Read 22 checked-in workflow trigger headers. The broad `.github/workflows/test.yml` has `push` on all branches; `release.yml` has a `workflow_run` trigger downstream of completed contracts. All four implementation/test commits use `[skip ci]`; no Actions were dispatched. Do **not** interpret the skip token as a universal guarantee against every possible trigger; Actions remain owner-prohibited.

## Deterministic reproduction and handoff

When an explicitly permitted HA checkout is available, from `dev/continuous_execution/ha_shift_state` run:

```sh
python -m py_compile donor_cache_gate.py test_donor_cache_gate.py donor_inventory_pages.py test_donor_inventory_pages.py
python -m unittest -v test_donor_cache_gate.py test_donor_inventory_pages.py
python donor_cache_gate.py verified-verify candidate.json build.json pinned_complete_inventory.json receipt.json local_synthetic_artifact.bin
```

Require immutable, separately verified public GitHub metadata and provenance before trusting the inventory; JSON alone is not origin attestation. Run a synthetic known-good cache and negative identity/path/tamper cases first; perform independent cache/security/license review before any reusable donor build-cache promotion. Keep game tests paused and no Actions. The District Manager can coordinate ownership of public upstream capture and reviewed build interface adoption, without private RE-Wizard data entering HA.

## Non-delivery / missing optional path receipt

An optional read-only attempt to inspect `dev/continuous_execution/ha_shift_state/README.md` returned GitHub REST 404 Not Found. This path was **not** a requested deliverable, source checkout, patch output or destination write; no README bytes were produced, and no uploader or recovery ZIP is needed. Any file-failure ledger should classify this as an optional missing lookup, not a lost artifact. All four intended source/test commits and their final blobs were read-back verified.

**Next ready milestone:** owner-authorized, non-Actions execution of all 17 current full-module test methods, independent reviewer examination of complete-inventory trust boundaries, and source-bound public-donor cache hit/miss measurement with immutable build output provenance. Keep CHECKS PENDING until genuinely executed and reviewed.
