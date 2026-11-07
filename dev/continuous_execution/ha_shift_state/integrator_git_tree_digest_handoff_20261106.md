# HA integrator: public-donor Git tree digest reconstruction (November 6, 2026, Kentucky time)

**CHECKS PENDING / AWAITING CI / INDEPENDENT REVIEW.** This is an HA-owned, public-source-only, offline, opt-in build-cache integrity enhancement. It is not acceptance of donor licenses, executed donor code, real recompiler integration, provider/browser runtime, or upstream GitHub source authenticity. No private RE-Wizard access, game binary, firmware, credential, GitHub Actions or paid API was used.

## Source authority, leases and readback

- Initial main HEAD \`1a305182e9846751336ab0516b902aa0c7d7ec2e\` (inline GitHub branch read); the existing cache contract \`donor_cache_gate.py\` blob was \`dfca0bd45f310f7b2babe7377be958b877f27189\`. It already checked source inventory structure and pinned object names, but did not reconstruct Git's tree object SHA-1 to ensure the entries collectively match the declared root. Existing source was left untouched.
- New \`dev/continuous_execution/ha_shift_state/donor_tree_digest.py\`: blob \`4df4c9ab4ed008d309b8c43c659a2b6373aabd17\`, creation commit \`5e428f292c0b12c91976db74b3300d287b84bf6c\`.
- New \`dev/continuous_execution/ha_shift_state/test_donor_tree_digest.py\`: final blob \`c9fb8495ea7b947882fcc6290d39367f8ee79b5f\`, initial commit \`6930aec938755504368b7c314042f00a62e9d74b\`, follow-up tests commit \`363ecf85208e6ecce54b8feceaf5e2a8107be4bc\`.
- STATUS marker \`bdd0c08f2bee9a2204af6beb41a1cab64df5b5e8\`; root CHECKS_STATUS marker \`f7a1bbfa3f75fa6200b17f3e245a57ddf0a04e05\`. All five commits include \`[skip ci]\`. Exact inline GitHub fetch_file readback matched each intended source/test/status body. Compare \`1a305182...\` through \`f7a1bbfa...\` found **5 commits / 4 authorized paths**, no unrelated edits.
- GitHub Actions triggers were inspected read-only across all 22 workflow files. \`.github/workflows/test.yml\` still matches all pushes; eligible push tests are suppressed by \`[skip ci]\`, but this is not a guarantee against other trigger families. Read-only inspection of 30 latest Actions records found **no associated runs** for these five commits. No workflow dispatch, rerun or enabling occurred.

## Actual engineering change

New \`reconstruct_tree_digest\` deterministically reconstructs raw Git tree objects from a *complete* source inventory, using canonical Git wire modes (\`040000\` metadata -> \`40000\` raw), raw 20-byte object SHA-1 IDs, UTF-8 names, Git's bytewise ordering with \`/\` suffix for directories, and \`SHA1("tree <length>\\0" + entries)\`. It recomputes and compares every non-root directory's declared tree SHA before deriving the root. It rejects malformed entries, unexpected modes, path traversal, duplicate paths, absent parents, forged subtree SHA and unsupported objects.

\`verified_tree_cache_key\` is opt-in: first invokes the existing \`cache_key_with_inventory\` validator, then rejects a reconstructed root that differs from the candidate's pinned root. Standalone CLI reads three JSON documents through the existing strict loader and emits a key plus explicitly false authentication/license/runtime statuses. The original cache commands and contracts were **not altered**. No attempt was made to execute source, download donors or claim a trusted upstream commit: callers must independently authenticate a pinned commit/tree and license notices. Git SHA-1 identity by itself is not cryptographic supply-chain attestation.

## Executed tests and measured scope

An actually available, non-Actions Python environment was used to author and execute the **exact new Python module** and its regression test source locally before GitHub write, followed by byte-identical GitHub readbacks.

- \`python -m py_compile donor_tree_digest.py test_donor_tree_digest.py\`: **passed**.
- \`python -m unittest -v test_donor_tree_digest.py\`: **6 passed / 0 failed**, including a positive known Git-wire fixture, permutation invariance, forged child hash, missing tree/parent, unsupported mode, duplicate/path traversal, changed root blob and opt-in wrapper root mismatch. The wrapper test mocks the pre-existing cache gate; it does **not** prove imported real \`donor_cache_gate.py\` integration.
- An independent disposable \`git init\` / \`git add\` / \`git update-index --chmod=+x src/z.c\` / \`git write-tree\` synthetic fixture matched the Python-computed SHA exactly: \`de9dc83a985e0dff59e9d80a4277a4d7fe078054\`. No archive, compiler, game, emulator or donor bytes were involved.
- Locally measured Python-only digest on **1,000 / 10,000 / 50,000 synthetic root entries** took **0.003 / 0.084 / 0.157 seconds**, respectively, in this container. These are non-comparable sample timings, **not** real donor build/cache or Windows runtime benchmarks.

**Post-write exact-source replay:** an initial local test-file spacing difference was found by comparing Git blob hashes after GitHub readback. The ephemeral local test text was normalized to the *committed* blob (no repo correction required), and the six test methods were rerun: **6 passed, 0 failed**. Local `git hash-object donor_tree_digest.py` = `4df4c9ab4ed008d309b8c43c659a2b6373aabd17`; local `git hash-object test_donor_tree_digest.py` = `c9fb8495ea7b947882fcc6290d39367f8ee79b5f`, exactly matching GitHub's inline source blob IDs. Thus the final local replay tested byte-identical committed new-module/test source, with a mocked legacy cache dependency in one method.

**Unexecuted**: the imported actual \`donor_cache_gate.py\` full integration (current suite of 16 cache + 5 inventory methods), large nested donor tree, Windows POSIX parity, source authenticity / signed commit verification, license qualification, donor compilation, throughput improvements from reuse, whole-HA CI and live ChatGPT provider/browser/MCP acceptance. These remain **CHECKS PENDING** and cannot be called accepted.

## Reproduction and next scoped milestone

In a separately authorized, offline non-Actions local checkout of the exact source blobs:

\`\`\`sh
cd dev/continuous_execution/ha_shift_state
python -m py_compile donor_tree_digest.py test_donor_tree_digest.py donor_cache_gate.py
python -m unittest -v test_donor_tree_digest.py test_donor_cache_gate.py test_donor_inventory_pages.py
python donor_tree_digest.py CANDIDATE.json BUILD.json INVENTORY.json
\`\`\`

The CLI requires a genuine, complete, owner-pinned public Git inventory with valid blob/tree SHA identities. It will **reject** the older synthetic cache fixture whose intentionally dummy tree SHAs do not correspond to its entries; that is expected and should not be weakened. Independent verifier should test authentic Git-derived synthetic nested trees, source/license name collisions, symlink/gitlinks, and variable Unicode names; benchmark against a real public-source Git tree only after separate provenance and license review. District Manager can hand off these exact blobs for independent scrutiny and consider optional build-cache integration after test completion. Do not clear release/acceptance markers.

No owner-operated ZIP, launcher, download or recovery action is required; files are already saved in HA and read-back verified. No intended file creation/write/readback failed; no FILE_FAILURE_EVENT or OWNER_ARTIFACT_READY was generated in this checkpoint.

## Source-byte verification reconciliation receipt

A local mirror of the new test source differed from the GitHub-committed bytes by one blank newline; the **GitHub destination itself was correct**, and its exact readback was already verified. The local mirror was corrected and its six unit tests rerun successfully against the exact committed blob. No online file was missing and no owner uploader is required.

```json
{
  "incident_id": "HA-INTEGRATOR-TREE-DIGEST-LOCAL-BLOB-REPLAY-20261106",
  "project": "HA",
  "filename": "test_donor_tree_digest.py",
  "path": "dev/continuous_execution/ha_shift_state/test_donor_tree_digest.py",
  "repo": "Artistical-Intelligence/hivemind-assembly",
  "branch": "main",
  "operation": "local_source_blob_parity_verification",
  "error": "Initial local test mirror had one extra blank newline; local SHA-1 differed from committed blob c9fb8495ea7b947882fcc6290d39367f8ee79b5f. Corrected only local mirror, reran 6/6 synthetic tests, and verified exact blob parity.",
  "artifact_status": "EXACT_COMMITTED_SOURCE_EXISTS_ONLINE",
  "upload_status": "READBACK_VERIFIED"
}
```
