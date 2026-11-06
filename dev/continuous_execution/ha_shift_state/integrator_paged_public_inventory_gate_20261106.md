# HA integrator: paginated public-donor source inventory gate — 2026-11-06

**CHECKS PENDING / AWAITING CI / independent review required.** Scoped to public GitHub donor metadata in HA. Owner's temporary emulator/runtime reuse priority remains active; existing native-browser, MCP and core acceptance obligations are not closed. No private RE-Wizard access.

## Source-pinned engineering milestone

- Initial HA `main` source SHA: `1bc3ac1f318f9665bd8d11960b71e3b85eb4b6bf`.
- Existing foreground-owned `_app/hivemind_assembly/integrations/github_public_source_inventory.py` blob `4849c4c35945b1d6904719642b81dc9cec178eaa`: `page(pin, cursor=...)` returns bounded, SHA-pinned Git-tree entries and a continuation cursor. A truncated recursive `fast_manifest` is not an authoritative completed source inventory.
- Existing integrator-owned `donor_cache_gate.py` blob `8d5f03ff0e9e3de9e857e57e33ef8df78a985971`: `verify_complete_inventory(candidate, manifest)` requires exact donor commit/root tree/license/source object identities and a genuinely completed manifest. It previously accepted only a single complete manifest, not independently collected continuation pages.
- Added `donor_inventory_pages.py`, Git blob `497e709ff6ec47169edfc755ddfb2c56cb19e698`, committed `b055b8d1d85ac13d9a034cd4b6fefd2f8ab30752`. This is a fail-closed offline stitcher for ordered `page()` responses with an explicit recorded `request_cursor`. It validates the pinned repo/commit/root tree, cursor chaining and depth, strict response schema, complete final page, request and entry bounds, Git object kind/mode, Gitlink/symlink denial, text/path safety and Windows case-fold path collision. The resulting full inventory has exactly the field contract consumed by the existing cache gate. The CLI calls the existing final source/LICENSE validation; it does **not** grant license, runtime or independent acceptance.
- Added `test_donor_inventory_pages.py`, Git blob `3b8edb74ff3be269300125ec66c408b5a9de79d1`, committed `3b38981f02eb2d0e56d166abfaa12dac257d453f`. No other contributor's source, verifier test, workflows or tasks were edited.
- The page response itself does **not** include the input cursor: a trusted acquisition caller must preserve envelopes `{"request_cursor": <passed cursor or null>, "response": <unmodified page(...) return>}`. A JSON envelope cannot cryptographically authenticate an untrusted GitHub result, and cursor checking alone cannot establish actual Git-tree completeness.

## Tests actually executed locally (stdlib-only Python)

```text
python -m unittest -v test_donor_inventory_pages.py
  Ran 5 tests in 0.003s: OK (5 passed, 0 failed)
  Positive two-page stitched source inventory.
  26 negative variants: missing/reordered/duplicate/unfinished pages,
  source revision drift, inconsistent completion/cursor metadata,
  Boolean-as-integer requests/indices, extra fields, unsafe/colliding
  paths, unsupported symlink/gitlink object modes, oversized page and
  missing completed source entries.
python -m py_compile donor_inventory_pages.py test_donor_inventory_pages.py
  passed
```

Verified local code SHA-256: `donor_inventory_pages.py` `090defa9139039a211d238f43abcf58eb71e4439b40223ae3cb603e5c94dc596`; `test_donor_inventory_pages.py` `babda21896b6ca1ef9fca8be6606cc714a4a8c94099369f86141099b8ad80156`. GitHub readback blob hashes matched the local canonical Git blob hashes exactly after separate `[skip ci]` source/test commits.

**Not executed:** integrated CLI with a real downloaded public donor page sequence, end-to-end real `GitHubPublicSourceInventory.page` against remote GitHub, actual donor build/toolchain or MZ/NX cache hit, whole HA pytest, Windows/Linux runtime, native ChatGPT browser, external MCP, qualified security/source/license review. No GitHub Actions initiated. Read-only latest-30-run metadata showed no Actions for either new commit; this is not CI acceptance. Review of 20 other workflow trigger headers found only path-filtered push or explicit dispatch for these evidence paths; `test.yml` has a broad push trigger suppressed by `[skip ci]` for eligible push workflows, and `release.yml` is separately conditioned on a successful run/tag/dispatch. Do not infer general suppression for all possible triggers.

## Reproduction and District Manager handoff

1. In the authorized first-party **public-source metadata** collection lane, for each `GitHubPublicSourceInventory.page(pin, cursor=cursor)` call save the **input** `cursor` alongside its returned `response`. Obtain the subsequent cursor from `response["next_cursor"]` until the actual terminal result is `complete=true` and `next_cursor=null`. Keep the exact root commit and tree pin fixed.
2. Run `python dev/continuous_execution/ha_shift_state/donor_inventory_pages.py CANDIDATE.json PAGE_ENVELOPES.json`. This uses the existing `donor_cache_gate.verify_complete_inventory` for exact source and LICENSE blobs; expected response contains `complete_inventory=true, license_approved=false, runtime_tested=false` for eligible completed inventories.
3. The District Manager should reconcile this manifest with the separate foreground MZ build-output-cache candidate, source/dependency/toolchain fingerprints and qualified license notices. A source manifest does not verify compiler identity, license compatibility, GPU correctness, native PE execution or cache performance.
4. Independent verifier: exercise actual `GitHubPublicSourceInventory.page()` and CLI with a small **public first-party synthetic** Git tree, including a last empty terminal page, nontrivial nested traversal, inconsistent continuation, skipped/duplicated segments and a changed root SHA. Preserve separate Windows portable-path checks and qualify any donor code reuse before integration. No Actions until explicit owner release.

**Status:** source files saved online and exact Git blob readbacks confirmed; no FILE_FAILURE_EVENT or owner-operated upload required. Existing Actions quota pause and project/source boundaries remain unchanged.
