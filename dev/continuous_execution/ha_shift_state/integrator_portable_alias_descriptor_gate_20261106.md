# HA integrator — portable source aliases and descriptor-bound donor cache verification (2026-11-06 local)

**CHECKS PENDING / AWAITING CI / INDEPENDENT REVIEW.** Source-only public-donor build/cache verification improvement. This does not run donor code, approve licenses, authenticate the source server, demonstrate Windows parity, accept the HA native ChatGPT browser, or clear release checks.

## Scope, writer lease and immutable pins

- Repository: `Artistical-Intelligence/hivemind-assembly`, branch `main`. Beginning HEAD `e4c9490b1d272d531df29b8993cf6d2f8195b63c`; both edits restricted to this integrator's existing `dev/continuous_execution/ha_shift_state/` lease. No other employee's source/tests changed.
- Source: `donor_cache_gate.py` prior Git blob `a526b8fc92e4f4f7b9c7770e008c248c6940b5fc` → `dfca0bd45f310f7b2babe7377be958b877f27189` in commit `47ca61e17051765832e58bf9669943d23ad0e33f` (`[skip ci]`).
- Tests: `test_donor_cache_gate.py` prior Git blob `6b1907a25ed1c9ad70202380a446e33927beea27` → `35e6e0e09ba39328ed2b2c74eca57b577525fcb8` in commit `b68fa88c54d618b4684799b5285541cd66239f3c` (`[skip ci]`).
- Both full updated UTF-8 source files were fetched by `mcp__GitHub__fetch_file` and compared byte-for-byte with the submitted text. No GitHub MCP attachment or file materialization.

## Implemented engineering changes

1. Donor source-tree collision screening now applies Unicode NFC normalization and case-folding when detecting aliases among candidate source entries and the complete inventory. Previously, composed `café.cpp` and decomposed `cafe + combining acute.cpp` could be accepted as two distinct source paths even though a normalization-insensitive filesystem can alias them. **Rejecting aliases is conservative portability screening, not proof of Git tree authenticity.**
2. Windows reserved device basename screening now trims spaces from the stem preceding the extension before testing Win32 device patterns. It rejects ambiguous names such as `CON .txt`, `aux .bin`, `conout$ .log` and `lpt² .txt`, while allowing ordinary names such as `con file.txt`.
3. The artifact SHA-256 verifier now opens one OS file descriptor and checks that it refers to a regular file; on platforms supporting them it requests `O_NOFOLLOW` and `O_NONBLOCK` to avoid a swapped final-component symlink or FIFO stall. It checks the descriptor's size before hashing and device/inode/size/mtime/ctime after hashing, in addition to the actual byte digest and declared receipt size.
4. Added two actual-module unittest methods for the aliases/reserved names and artifact verifier's positive/negative cases (FIFO where supported; deterministic mocked mid-hash stat drift). Historical metadata-only `verify` and inventory-bound `verified-verify` interfaces remain present and unchanged.

**Limitations:** `O_NOFOLLOW` is platform-dependent (not portable to native Windows CRT); the preliminary symlink check on Windows is not an atomic anti-race guarantee. Parent symlink/junction handling is not proven secure. Stat comparison does not replace byte hashing or an independent provenance chain. Do not describe this as full race-free remote attestation.

## Executed checks / source-bound results

- A permitted non-Actions isolated Python diagnostic ran seven expected outcomes using a local transcription of the amended descriptor/path predicates: valid regular synthetic bytes, wrong declared size rejection, wrong SHA-256 rejection, direct symlink rejection, FIFO/nonregular rejection (POSIX), simulated post-hash metadata change rejection, and NFC-composed/decomposed Unicode equivalence. All seven behaved as expected. A separate earlier local diagnostic confirmed `O_NOFOLLOW` symlink rejection and `O_NONBLOCK` nonblocking FIFO open. **Neither invocation imported the committed HA modules.**
- Source/readback inspections: exact new Git blobs above, 16 authored cache-gate unittest methods and 5 authored inventory-page unittest methods; **zero of the 21 actual-module methods executed in this shift**. Python syntax, real CLI invocation and Windows-native execution are therefore not accepted.
- Reviewed `.github/workflows/` trigger headers for all 22 workflows. The broad `test.yml` push trigger is the relevant eligible trigger for this HA path; all source/test commits used `[skip ci]`. Read-only Actions query returned **zero associated runs for both source/test commits**. This does not prove other future event types cannot trigger workflows.
- Reproduction in a permitted checkout, using no external game/compiler or donor binary: `cd dev/continuous_execution/ha_shift_state && python -m unittest -v test_donor_cache_gate test_donor_inventory_pages`. Full HA checks remain `AWAITING CI` under the owner-wide private/public Actions pause.

## Pending handoff for the District Manager and independent verifier

- Independently run and review the 21 actual-module tests, including valid and adversarial Unicode/path/file-descriptor behavior on Windows and Linux; check installed Python versions and symlink/junction semantics.
- Connect this source/cache receipt gate to the foreground MZ/NX first-party public-source cache work only after confirming full dependency, build-flag, platform and actual source-tree identities, license notices and root/subdependency provenance. No private RE-Wizard source/material is included.
- Obtain qualified independent review before calling the cache verified for use; perform actual public-donor build/synthetic runtime measurements separately. No donor game/firmware, opaque binary or provider/API execution was attempted.
- Earlier HA native-browser, MCP receipt, Windows Unicorn/Speakeasy, full-project CI and security acceptance gates remain **CHECKS PENDING**. No scheduled tasks, providers, workflows, other worker files or release settings were modified.

**Owner artifact / recovery:** Nothing requires owner-operated download. Both intended source writes were saved to GitHub and read-back verified; no `OWNER_ARTIFACT_READY` or write-failure recovery ZIP is necessary.
