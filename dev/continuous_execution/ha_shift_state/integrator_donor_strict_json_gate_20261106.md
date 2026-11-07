# HA integrator — strict public donor cache JSON intake (2026-11-06 local)

**CHECKS PENDING / AWAITING CI / INDEPENDENT REVIEW.** HA-only, public-source cache reproducibility work, not donor execution, license approval, live ChatGPT browser/provider acceptance, artifact delivery or remote source attestation. Do not release with pending markers.

## Exact sources / commits

- Before-work `main`: `ba63e5df1917aff715498db9d0f3f74920136129` (read 2026-11-07 00:30Z; concurrent producer touched unrelated public submodule verifier).
- `dev/continuous_execution/ha_shift_state/donor_cache_gate.py` old blob `02f4596356b9d38afe61f2fb476d307c9d6c7661` → `a526b8fc92e4f4f7b9c7770e008c248c6940b5fc` at commit `1d12748e1ba45908ff8ecfd29dc7b3a6e954046e` (`[skip ci]`).
- `dev/continuous_execution/ha_shift_state/test_donor_cache_gate.py` old blob `3d12ddda66a0ee139843b416cfc1790e3d484d89` → `6b1907a25ed1c9ad70202380a446e33927beea27` at commit `d0be9b823495ecd4ff93d240f4723566b8625841` (`[skip ci]`).
- Both new content blobs were independently read back using *inline* `mcp__GitHub__fetch_file`; no materialization or binary fetch. Writes were sequential and restricted to this integration worker's existing `ha_shift_state` lease.
- All user-facing metadata in this document concerns public HA paths only.

## Implemented behavior

The donor cache CLI previously used permissive `json.load` for all candidate/build/inventory/receipt paths. JSON object duplicate keys (including nested licensing fields) silently overwrote the earlier value; Python also accepted nonstandard NaN/Infinity constants. Either can make source/build provenance receipts ambiguous or nonportable across parsers.

- Introduced `_strict_object_pairs` to reject duplicate keys recursively, `_reject_nonfinite` to reject NaN/±Infinity, and `_load_json` for UTF-8 strict parse errors.
- Routed **all six CLI commands** (`validate`, `inventory`, `key`, `verified-key`, `verify`, `verified-verify`) through the strict loader for every JSON input, while preserving the old cache-key schema and byte hashing.
- Added **two actual-module regression methods**, one for candidate/build duplicate and nonfinite JSON and another for structurally valid inventory/receipt verification followed by duplicate/nonfinite rejection. This is regression source, **not an executed full-module test**. Existing functionality, source acquisition, license status, and the legacy `verify` semantic remain unchanged.

## Executed and unexecuted checks

- **Executed:** 11/11 isolated standard-library Python JSON-predicate cases matched expected classification: 5 valid documents and 6 rejected ambiguous/nonfinite/malformed documents. The predicate logic was manually copied from the committed functions; this did not import HA files and does not prove the CLI, full test fixture, remote GitHub source, Windows paths, or runtime behavior.
- **Source readback/static audit:** source and test blobs above; visible six-command argument dispatch uses `_load_json` for all candidate/build/inventory/receipt JSON. The two new test methods are present. This is not a Python compile verdict.
- **NOT EXECUTED:** 14 cache-gate full-module unittest methods, 5 companion inventory pagination methods; no donor binaries/builds, Windows/Linux native execution, real cache hit/miss timing, live provider/browser/MCP, or whole-project pytest.
- **Actions prohibited:** no workflow dispatch or rerun. Read-only workflow trigger inspection shows the broad `.github/workflows/test.yml` uses `push` on all branches, while most other workflow push triggers are path-filtered; both commits include `[skip ci]`. The skip token is not a guarantee against all event triggers; do not dispatch Actions.

Runnable reproduction in an explicitly authorized **non-Actions local checkout**:
```sh
cd dev/continuous_execution/ha_shift_state
python -m py_compile donor_cache_gate.py test_donor_cache_gate.py donor_inventory_pages.py test_donor_inventory_pages.py
python -m unittest -v test_donor_cache_gate.py test_donor_inventory_pages.py
```
Then independently audit the same exact GitHub blobs and test genuine pinned public Git-tree bytes, build receipts, and Windows/Linux portability in the reviewed synthetic lane. These tests are pending; never claim acceptance from local predicate copies alone.

## Recovered pre-write guard event

Initial in-memory source-patch preparation intentionally stopped *before* a GitHub write: a replacement expected one inventory loader occurrence, but the file correctly contained two CLI inventory branches. No destination was modified. The corrected source update was subsequently saved at `1d12748e...` and source/test content readback succeeded. Sanitized `FILE_FAILURE_EVENT`:
```json
{"incident_id":"HA-INTEGRATOR-JSON-PATCH-GUARD-20261106","project":"HA","filename":"donor_cache_gate.py","path":"dev/continuous_execution/ha_shift_state/donor_cache_gate.py","repo":"Artistical-Intelligence/hivemind-assembly","branch":"main","operation":"source_patch_prewrite_verification","error":"Source guard expected one inventory JSON loader occurrence; two valid CLI branches exist; no write attempted on failed guard.","artifact_status":"CORRECTED_SOURCE_EXISTS_ONLINE","upload_status":"READBACK_VERIFIED"}
```
No owner-operated ZIP/.cmd/report download is needed because exact intended source/test files are present on GitHub. **Next milestone:** independent actual-module 19-test execution, negative JSON-wire review, public donor license/source authentication and cache evidence, and prior HA browser/security/whole-suite gates remain CHECKS PENDING.
