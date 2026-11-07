# HA integrator — Git-tree-bound artifact verification (2026-11-06)

**CHECKS PENDING / AWAITING CI / INDEPENDENT SOURCE REVIEW.** Public-donor metadata only; no private RE-Wizard files, source, user secrets, opaque donor binaries, games, firmware, paid model APIs or GitHub Actions were accessed/executed.

## Exact source, ownership, and online readbacks

- Initial HA `main`: `fc8ff98709a9e8412924e8c7e407e3d71a68b0e6` (inline GitHub branch metadata).
- Existing cache gate: `dev/continuous_execution/ha_shift_state/donor_cache_gate.py`, blob `dfca0bd45f310f7b2babe7377be958b877f27189`. No edit to this prerequisite.
- Tree-digest implementation: `dev/continuous_execution/ha_shift_state/donor_tree_digest.py`, commit `f4d11a3ae5ac75ffb8229ab1d6c3402754adc879`, blob `f4bc13cab6ba6d6c1aceca08cb8410741277bebc`, inline readback matched intended entire body.
- Tree-digest regressions: `dev/continuous_execution/ha_shift_state/test_donor_tree_digest.py`, commit `7789c979037d940fb8145647de22cbbe5fe0fddd`, blob `87c645feb40fe2987ad97d12012cf97ee22caac6`, inline readback matched intended entire body.
- Compare initial HEAD to `7789c979037d940fb8145647de22cbbe5fe0fddd`: exactly **2 commits, 2 owned source/test files**, no production A/B, other project or workflow change. Each commit contains `[skip ci]`.
- Read-only workflow header review: 22 YAML workflows, including `test.yml` on every push and `release.yml` on completed workflows/tags. Eligible push/PR workflows should be skipped by `[skip ci]`, but skip is not an approval bypass or universal guarantee. Do not dispatch or re-enable Actions.

## Engineering result

The existing cache gate’s `verified-verify` path validates a structurally complete claimed Git tree and cached artifact SHA-256 separately, without reconstructing the declared tree digest. A previously introduced opt-in `verified_tree_cache_key` reconstructed the tree but did not check artifact bytes. New `verified_tree_artifact(candidate, build, inventory, receipt, artifact_path)` composes **real cache-key + complete inventory validation + raw Git tree reconstruction + pinned root SHA equality + actual regular-file length/SHA-256 verification**. New opt-in CLI:

```shell
python dev/continuous_execution/ha_shift_state/donor_tree_digest.py verify-artifact CANDIDATE.json BUILD.json INVENTORY.json RECEIPT.json SYNTHETIC_ARTIFACT
```

The existing positional 3-document tree-digest CLI and `donor_cache_gate.py` commands are unchanged. The new return value distinguishes tree/object integrity and actual artifact bytes from remote upstream authenticity, license approval, donor runtime execution or independent acceptance; those last claims remain explicitly false. No cache artifact is executed.

The standalone `reconstruct_tree_digest` now also rejects contradictory submodule/symlink flags, Boolean/floating/negative blob sizes, non-null directory sizes, control characters and lone Unicode surrogates before hashing. The opt-in wrapper still invokes the authoritative cache inventory gate first.

## Checks executed vs not executed

- Executed a disposable **copied-predicate** Python harness against the newly introduced entry-validation condition: **16 expected classifications matched** (11 rejection cases and 5 permitted, including blob size=None and directory size=None). Not an imported HA module execution; do not use as module acceptance.
- Added two actual-module regression methods in `test_donor_tree_digest.py`: direct metadata negative/boundary cases; end-to-end **real `donor_cache_gate`** with a first-party synthetic tree, matching synthetic artifact bytes, CLI JSON output, forged sibling hash, incomplete inventory, stale receipt key and altered artifact. These are **authored but 0 executed in this shift**. The file now has 8 test methods (6 prior, 2 new); prior 6/6 success is historical source evidence, not current-source acceptance.
- Reproduction in a permitted local Python checkout (no GitHub Actions, donors, or games): `cd dev/continuous_execution/ha_shift_state && python -m unittest -v test_donor_tree_digest.py test_donor_cache_gate.py test_donor_inventory_pages.py` and `python -m py_compile donor_tree_digest.py test_donor_tree_digest.py`. The full cache, pagination and cross-platform suites remain unexecuted in this shift.
- Historical whole-HA Linux/Windows runs are not accepted for this HEAD. Live ChatGPT native browser/provider, independent review, Windows native Unicorn/Speakeasy diagnosis, public-donor builds and performance/cache hit-rate measurements all remain pending.

## Source-level handoff to District Manager / verifier

1. Independent checker should run the 8 current tree-digest methods plus the actual cache/pagination suites, not merely copied predicates, and scrutinize failures involving platform filename portability, Unicode and ambiguous metadata.
2. Review upstream commit-tree provenance, complete dependency/version pins, root LICENSE versus nested licenses and any non-GPL-compatible reuse before a real donor build or integration. An internally coherent Git SHA-1 tree is *not* remote source authentication.
3. Future integration should use the opt-in verification path for a **cache-hit artifact**. Measure reused build outputs on supported Windows synthetic workloads; do not execute unreviewed donor code or game/firmware binaries.
4. Keep separate HA-native browser transport receipt/lease checks, source-pinned Linux/Windows acceptance and qualified independent review outstanding. Do not mark any release green.

## Recovered source-preparation failure receipt

```json
{
  "incident_id": "HA-INTEGRATOR-TREE-ARTIFACT-PREWRITE-JS-20261106",
  "project": "HA",
  "filename": "donor_tree_digest.py",
  "path": "dev/continuous_execution/ha_shift_state/donor_tree_digest.py",
  "repo": "Artistical-Intelligence/hivemind-assembly",
  "branch": "main",
  "operation": "source_patch_prewrite_composition",
  "error": "Initial tool script had invalid JavaScript triple-quote syntax and did not execute a GitHub write; corrected script subsequently committed and read back.",
  "artifact_status": "RECOVERED_SOURCE_EXISTS_ONLINE",
  "upload_status": "READBACK_VERIFIED"
}
```

No owner-operated file package was generated or needed: source/test bytes exist online at verified commit refs. No OWNER_ARTIFACT_READY event applies. The District Manager may register the sanitized recovered FILE_FAILURE_EVENT without accessing private RE-Wizard from HA.
