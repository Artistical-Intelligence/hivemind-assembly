# Hivemind Assembly roadmap

Current version: 0.36.0. This roadmap lists only work that is still open; what is
already implemented is described in [README](../README.md) and
[ARCHITECTURE](ARCHITECTURE.md). Implementation, automated verification and live
account acceptance are separate. Successful fixtures do not establish unattended
reconstruction or measured native-model learning gains.

## Completion plan: eight delivery stops

These stops close against runnable outcomes. Checkpoint commits and successful
fixtures do not close a live-account requirement. Stops 1–6 complete implementation,
Stop 7 audits the integrated product, and Stop 8 repairs findings and releases it.
They are delivery milestones, not a promise that every milestone fits one chat turn.

| Stop | Work and required outcome | Weight in remaining plan | Status |
| --- | --- | --- | --- |
| 1. First usable autonomous workflow | Trace requirements, establish the host and native sessions, connect category selection, separate worker/adviser, Ghidra/REA analysis, source editing, compilation and independent verification. Close on a real unattended reconstruction with retained artifacts and continuation through checkpoints. | 20% | In progress |
| 2. Resilient agent team | Validate all five actual routes; handle allowance, preferred-route promotion, adviser continuity, review, renewal, cancellation, uncertain sends and application/browser restarts without duplicate operations. Retain useful raw model/tool logs. | 15% | Open |
| 3. Project-level reconstruction | Complete inventories/dependency plans, cumulative builds and real region replacement/fallback with rollback. Exercise the fixed three-target suite below and reject incorrect mutants. | 20% | Implemented; source-known suite passes; live-team run open |
| 4. General coding and integrations | Complete a general programming task through bidirectional MCP with durable disconnect recovery and verified GitHub publication. Exercise optional repository creation, browser-assisted setup, Codespaces/hosted execution and conflict-safe import; retain a local-only path. | 15% | Open |
| 5. Demonstrated long-term learning | Complete category-first scoping, existing-tag/no-tag selection, fresh conversations, persistent knowledge and knowledge/procedure/executable improvement. Demonstrate correctness and measured speed gains on independent cross-project holdouts, with promotion, invalidation and rollback. Preserve optional Chat-only experiments and unlimited HA budgets. | 15% | Open |
| 6. Integrated installation and product | Complete onboarding, settings, status, evidence, recovery and documentation. Verify clean Windows prerequisites, credential persistence, restart, backup/restore and drop-in update. No hidden mandatory implementation TODOs. | 5% | Open |
| 7. Full audit | Audit requirements, correctness, privacy, protected evaluators, credentials, publication, recovery, upstream preservation, maintainability and claims. Produce reproducible findings with severity and repairs. | 5% | Open |
| 8. Revision and release | Resolve audit/acceptance defects, rerun affected workflows and installation/regression gates, package and publish exact source/evidence. No mandatory open requirement or blocking defect. | 5% | Open |

Progress is estimated against this fixed remaining-work plan, not lines of code or
test counts. Current estimate: **about 5% of the plan**, with **Stop 1 about 25%**
and **0/8 stops closed**. Existing implemented capabilities are described in README
and ARCHITECTURE; this is not a claim that only 5% of the repository has been built. Any change to
scope or weighting must be stated rather than silently changing the denominator.

### Still open in Stops 1, 3 and 5

- Stop 1: establish actual signed-in sessions on an execution host; run the
  dashboard's autonomous reconstruction trial through real Ghidra/REA and model
  calls; verify retained live evidence and publication. No live route or
  autonomous-reconstruction completion is claimed.
- Stop 3: run the fixed suite through a live native team with actual Ghidra
  callgraph plans. Stripped originals rely on owner/Ghidra-supplied addresses;
  inlined original copies of a recovered function are not redirected.
- Stop 5: measured native learning gains on independent holdouts (the pinned
  HumanEval-Decompile C subset can be imported as one); this needs live routes.

The fixed Stop 3 suite is a multi-function native utility, an ARM64-to-x64
reconstruction, and a small game-related state/frame/audio target. At least one
complete target must run with both recovered regions and fallback regions, and
incorrect alternatives must fail. Arbitrary Windows API/GUI/CRT support or a
commercial game is not an added prerequisite for this completion plan.

Login, 2FA, unavailable exact model targets or a missing execution host may block
live acceptance. They do not close the stop; independent implementation continues.
Native credentials, profiles and protected target data remain outside GitHub.

## Remaining implementation

- Run a live folder backup on Windows, through both the GitHub connection and the
  github.com New repository fallback with Git Credential Manager sign-in, including
  a file over 100 MiB as release assets (and once with Git LFS), a restore with both
  scripts, and a visibility change made on GitHub (all checked only against
  stand-ins and local Git remotes so far).

- Extend bounded x86-64/AArch64 function and static/dynamic Linux application lanes
  to broader Windows/game/graphics effects and target-level equivalence.
- Resolve any provider-specific adapter gaps identified by signed-in account
  validation; current ambiguous controls remain blocked.
- Extend MCP onboarding where a provider requires additional integration; standard
  HTTP OAuth setup is implemented, with live account consent and tunnel
  authorization still acceptance gates.
- Game play-testing beyond the current lanes: Windows and macOS native adapters,
  exported Godot binaries, other engines, pointer, touch and controller input,
  native audio capture, dynamic ELF stepping and measured learned navigation skills.

## Reference material: still open

HA now imports the owner's collection itself (Word files split at headings with
their tables and pictures, whole folders and GitHub repositories, ranked search and
the assistants' reference tools); no manual conversion is needed. Still open:

- Use the reference tools, and the adviser's picture descriptions, in a live run
  with signed-in assistants (both are checked only with stand-ins so far).
- Meaning search: measured on the owner's imported repository (prose only, 25,597
  vectors). On 20 task steps like the owner's (decomp, recomp, mods, HD art, Godot or
  Rust rewrites, a feature for another program), an expected section came first for 11
  (word search alone: 9) and in the top 10 for 20 (18); on 20 plain questions, first for
  12 (11), top 10 for 19 (16). Still open: measure it with the live assistants' own
  searches, and the index build time on a typical Windows PC (about 20 pieces a second
  per processor thread here).
- Old Office formats (.doc, .xls, .ppt) and slides are not imported; they are listed
  as skipped. Excel workbooks and scanned PDF pages are (0.35.0). Still open: OCR of
  pictures inside Word files, and languages other than English for scans.
- Push early, check later (0.36.0): tested with stand-ins for GitHub and the assistants.
  Still open: a live check by a signed-in ChatGPT of a Claude-written file, and the push of
  drafts to a real GitHub repository.

## Verification

### Current evidence

<!-- status:begin -->
<!-- Generated by dev/status_docs.py from _app/release_status.json; edit that file. -->

**Version 0.37.0.** Live native routes accepted: 0 of 5. Unattended worker/adviser/Ghidra loop with live models: not established. Clean Windows desktop installation: not verified.

| Evidence | Commit | Runs | Host | Model inference |
| --- | --- | --- | --- | --- |
| native-recovery-local-2026-10-29 (2026-10-29) | `cb37d73` | local | local Linux; Chromium 153 fixtures | no |
| workflow-context-0.37.0 (2026-10-29) | `512802e` | local | local Linux | no |
| hosted-ci-a9813a0 (2026-10-28) | `a9813a0` | [40780070811](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/40780070811) | GitHub Linux and Windows | no |
| local-suite-85974a3 (2026-10-28) | `a9813a0` | local | Linux x86-64 local (Python 3.12, Playwright Chromium, Tesseract 5.3.4) | no |
| checks-workflow-reviews-2026-10-28 (2026-10-28) | `a9813a0` | local | Linux x86-64 local | no |
| hosted-ci-0a1a5e4 (2026-10-28) | `0a1a5e4` | [40760091331](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/40760091331) | GitHub Linux and Windows | no |
| local-suite-0a1a5e4 (2026-10-28) | `0a1a5e4` | local | Linux x86-64 local (Python 3.12, Playwright Chromium, Tesseract 5.3.4) | no |
| reference-import-live-2026-10-28 (2026-10-28) | `0a1a5e4` | local | Linux x86-64 local; GitHub over this session's Git sign-in | no |
| hosted-ci-93c1c22 (2026-10-28) | `93c1c22` | [40736659843](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/40736659843) | GitHub Linux and Windows | no |
| local-suite-93c1c22 (2026-10-28) | `93c1c22` | local | Linux x86-64 local (Python 3.12, Playwright Chromium) | no |
| meaning-search-measured-2026-10-28 (2026-10-28) | `676f627` | local | Linux x86-64 local (2 processor threads), owner's imported reference repository | no |
| hosted-ci-676f627 (2026-10-28) | `676f627` | [40729696600](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/40729696600) | GitHub Linux and Windows | no |
| local-suite-676f627 (2026-10-28) | `676f627` | local | Linux x86-64 local (Python 3.12, Playwright Chromium) | no |
| reference-import-live-2026-10-27 (2026-10-27) | `d762a7f` | local | Linux x86-64 local; GitHub over this session's Git sign-in, not HA's GitHub connection | no |
| hosted-ci-9e2cc54 (2026-10-27) | `9e2cc54` | [40593247172](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/40593247172) | GitHub Linux and Windows | no |
| local-suite-9e2cc54 (2026-10-27) | `9e2cc54` | local | Linux x86-64 local (Python 3.12, Playwright Chromium) | no |
| hosted-ci-7c35caa (2026-10-22) | `7c35caa` | [39808320013](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39808320013), [39811968290](https://github.com/Artistical-Intelligence/hivemind-assembly/actions/runs/39811968290) | GitHub Linux and Windows | no |
| hosted-ci-game-play-testing (2026-10-22) | `3e741b3` | 39771716493 (log removed) | GitHub Linux and Windows | no |
| real-games-native (2026-10-22) | `3e741b3` | local | Linux x86-64 local (Ubuntu 24.04, Xvfb, Mesa llvmpipe, Godot 4.7.1) | no |
| game-play-testing-local (2026-10-22) | `96fb326` | local | Linux x86-64 local (Python 3.12, Clang 18, Godot 4.7.1) | no |
| hosted-ci-second-audit (2026-10-21) | `62b3101` | 39688769075 (log removed) | GitHub Linux and Windows | no |
| windows-project-acceptance (2026-10-21) | `62b3101` | 39688769075 (log removed) | Linux local and hosted Windows | no |
| audit-second-pass (2026-10-21) | `62b3101` | 39688769075 (log removed) | Linux x86-64 local and hosted CI | no |
| hosted-ci-improvements (2026-10-21) | `179524f` | 39674657186 (log removed), 39674657324 (log removed) | GitHub Linux and Windows | no |
| audit-2026-10-21 (2026-10-21) | `179524f` | 39674657186 (log removed) | Linux x86-64 local and hosted CI | no |
| windows-pe-composition (2026-10-21) | `179524f` | 39674657186 (log removed) | Linux local and hosted Windows | no |
| public-holdout-import (2026-10-21) | `179524f` | local | Linux x86-64 local | no |
| hosted-ci-0.25 (2026-10-21) | `0c475a2` | 39650550445 (log removed) | GitHub Linux and Windows | no |
| project-reconstruction-suite (2026-10-21) | `0c475a2` | 39650550445 (log removed) | Linux x86-64 local and hosted CI | no |
| ghidra-project-plan (2026-10-21) | `5a35215` | 39650087898 (log removed) | Fresh Linux x86-64 install and hosted Windows | no |
| baseline-suite-cc17bf1 (2026-10-21) | `cc17bf1` | 39632598272 (log removed) | GitHub Linux and Windows | no |

- **native-recovery-local-2026-10-29** (`cb37d73`): Native recovery recognizes nested user/assistant DOM elements as one message, preserves separate-message duplicate rejection and full-envelope verification, reconciles send exceptions without resending, bounds unconfirmed setup delivery checks, and caches recovered drafts only after identity discovery. Independent source review and 48 focused tests passed, including actual Chromium 153 local DOM fixtures. The non-browser non-slow suite passed 694 tests (103 skipped, 374 deselected). A broader browser-enabled run stopped after three failures: two extension serviceworker timeouts and a dashboard retained-result assertion. All three tests also failed on the unchanged base (the dashboard case was intermittent), so no full browser-suite pass is claimed. No signed-in provider acceptance, hosted CI, installer or release verification is claimed.
- **workflow-context-0.37.0** (`512802e`): Version 0.37.0: evidence-based local resume, checks-first scheduling, focused briefs and model-requested fresh chats passed the complete local suite: 826 passed, 333 skipped. Focused native workflow/session tests passed 66 cases; independent review passed, including crash replay, changed files after reset and owner setting changes during renewal. Source permissions, exact native identity, existing writer/operation recovery, learning and independent/root acceptance remain required. Clear requests fall back to new chats; no service clearing action or signed-in native reset was verified. No new operational performance log. Hosted Windows/Linux/browser/package and release checks remain separate gates.
- **hosted-ci-a9813a0** (`a9813a0`): All four jobs passed at a9813a0: Linux 1075 passed/43 skipped (871.71s); Windows 1044 passed/74 skipped (1805.48s); the Chromium browser fixture; Windows package install, update and restore. Push early, check later was tested with stand-ins for GitHub and the assistants only.
- **local-suite-85974a3** (`a9813a0`): Full local suite at 85974a3 (a9813a0 changes only test encodings and the gate script's decoding): 1106 passed/12 skipped (1127 s) with WORKBENCH_TEST_CHROME and the real meaning-search model.
- **checks-workflow-reviews-2026-10-28** (`a9813a0`): Push early, check later was checked by nine independent reviews, each a separate Claude session with a fresh context that saw only the request, the code and earlier reports (checks/2026-10-28-push-early-review-1.md to -9.md). Reviews 1-7 failed and their findings were fixed with tests; review 8 passed with minor fail-safe findings, whose follow-ups review 9 passed. Not established: a live check by a signed-in ChatGPT of a Claude-written file, or draft pushes to a real GitHub repository.
- **hosted-ci-0a1a5e4** (`0a1a5e4`): All four jobs passed at 0a1a5e4: Linux 1030 passed/43 skipped (751.91s); Windows 999 passed/74 skipped (1547.10s); the Chromium browser fixture; Windows package install, update and restore. Excel workbooks were tested with generated .xlsx/.xlsm files; scanned-page reading with Tesseract stood in for on Windows (its install by winget wasn't run there).
- **local-suite-0a1a5e4** (`0a1a5e4`): Full local suite: 1061 passed/12 skipped (1269 s) with WORKBENCH_TEST_CHROME and the real meaning-search model, including a real Tesseract read of a generated scanned PDF page.
- **reference-import-live-2026-10-28** (`0a1a5e4`): HA's GitHub import of the owner's private reference repository (its commit 0da1a55): 3,163 documents imported, 0 failed, in 103.9 s; 483 skipped with reasons, none of them spreadsheets now. Its one Excel workbook became 34 sections with 33 tables and no gaps; its 6 PDFs have text on every page (0 scanned pages). Counts only.
- **hosted-ci-93c1c22** (`93c1c22`): All four jobs passed at 93c1c22 (imports update daily by default; an edited document reuses the meaning vectors of its unchanged text): Linux 1026 passed/42 skipped (682.92s); Windows 995 passed/73 skipped (1498.93s); the Chromium browser fixture; Windows package build, install and restore.
- **local-suite-93c1c22** (`93c1c22`): Full local suite: 1056 passed/12 skipped (1199 s) with WORKBENCH_TEST_CHROME and HA_TEST_MEANING_MODEL set, including the real meaning-search model and a test that an edited chapter is the only text read again.
- **meaning-search-measured-2026-10-28** (`676f627`): Meaning search (all-MiniLM-L6-v2, 8-bit, pinned and SHA-256 checked) indexed the imported repository's prose: 423 documents, 25,597 vectors in 1,289 s on one thread. On 20 task steps like the owner's (decomp, recomp, mods, HD art, Godot or Rust rewrites, a feature for another program), an expected section came first for 11 (word search alone 9) and in the top 10 for 20 (18); on 20 plain questions, first for 12 (11), top 3 for 14 (15), top 10 for 19 (16). A combined search took 138-198 ms here against 107-136 ms for word search alone. Expected sections were chosen from the book's headings before these runs; counts only.
- **hosted-ci-676f627** (`676f627`): All four jobs passed at 676f627: Linux 1024 passed/42 skipped (970.72s); Windows 993 passed/73 skipped (1400.57s); the Chromium browser fixture; Windows package build, install and restore with ONNX Runtime in the hash-locked dependencies. Meaning search ran with a stand-in model there.
- **local-suite-676f627** (`676f627`): Full local suite: 1054 passed/12 skipped (1185 s) with WORKBENCH_TEST_CHROME and HA_TEST_MEANING_MODEL set, including 20 Chromium dashboard tests and the test of the real meaning-search model.
- **reference-import-live-2026-10-27** (`d762a7f`): HA's GitHub import of the owner's private reference repository (its commit bf3e723): 2,367 documents imported and 0 failed in 46.2 s, 422 skipped with their reasons (7 archives, 328 binary files, 85 pictures no document shows, 1 spreadsheet, Git's records); 73,301 sections, 1,289 tables, 104 pictures. The Word textbook became 3,270 sections with 487 tables and 7,874 links (4,349 inside the book resolved) and no gaps; it has no embedded pictures. Lookup by a heading found it; importing again said Already up to date with GitHub in 1.5 s. On 20 plain-language questions an expected section came first for 11 and in the top 3 for 15; a second search with the material's own terms found 4 of the 5 misses. Counts only: none of the repository's content is recorded here.
- **hosted-ci-9e2cc54** (`9e2cc54`): All four jobs passed at 9e2cc54: Linux 1017 passed/41 skipped (875.02s); Windows 986 passed/72 skipped (1382.46s), including both PowerShell restore tests in Windows PowerShell, Git LFS with a local remote, restore path checks with links, and the reference-material permission test that deletes the imported folder; fifteen native Windows checks; the Chromium browser fixture; Windows package install, update and restore. Large files, visibility changes and GitHub imports ran against stand-ins and local Git remotes only.
- **local-suite-9e2cc54** (`9e2cc54`): Full local suite: 1046 passed/12 skipped (1087 s) with WORKBENCH_TEST_CHROME set, including 20 Chromium dashboard tests, and the DOM fixture. Large files as release assets, both restore scripts, Git LFS, visibility following and GitHub imports ran against a stand-in release API and local Git remotes only. The PowerShell restore tests skip here (no PowerShell); they ran in Windows PowerShell in the hosted run.
- **hosted-ci-7c35caa** (`7c35caa`): All four contract jobs passed at 7c35caa (only documentation changed since v0.26.0 at 3e741b3): Linux 915 passed/20 skipped (620.13s), including the native SDL2 and Godot 4.7.1 play tests; Windows 887 passed/48 skipped (1241.11s); fifteen native Windows checks; twelve Chromium checks; Windows package install, update and restore. The release workflow it started (run 39811968290) found v0.26.0 already published and built nothing.
- **hosted-ci-game-play-testing** (`3e741b3`): All contract jobs passed at 3e741b3: Linux 915 passed/20 skipped (749.06s), including the native SDL2 and Godot 4.7.1 play tests; Windows 887 passed/48 skipped (1429.01s); native Windows checks; Chromium checks; Windows package install, update and restore.
- **real-games-native** (`3e741b3`): dev/check_real_games.py at 3e741b3. Dodge the Creeps (Godot demo, GDScript): replays identical; exploration 30 steps/1920 ticks pass. GDScript vs godot-rust port: replays identical with seeded OS randomness; exploration 30 steps/1370 ticks found divergence state:mobs at tick 295, shrunk 300->286 ticks and confirmed (the port uses Rust's generator for mob paths). Chromium B.S.U. 0.9.16.1-3 Ubuntu binary vs rebuild: replays identical; exploration 30 steps/1296 ticks pass. Rebuild vs planted bound defect: exploration 30 steps/1376 ticks found divergence state:y at tick 156, shrunk 160->22 ticks and confirmed; single build 30 steps/1376 ticks found invariant hero_inside_y at tick 156. sokoban-rs vs planted push defect: scripted up,right,right found divergence frame at tick 4; exploration 30 steps/292 ticks found divergence frame at tick 32, shrunk 34->17 ticks and confirmed; upstream alone 30 steps/336 ticks pass. Scripted, seeded play by HA's harness; no model inference.
- **game-play-testing-local** (`96fb326`): Full local suite at 96fb326: 925 passed/9 skipped (971.07s), with HA_TEST_GODOT set, including the game play-testing modules (contract, engine parity on x86-64 and AArch64, the Coin cavern fix loop, broker/team/dashboard/acceptance/CLI), the native lane tests (SDL2 and event-driven SDL2 programs, seeded randomness, headless Godot) and the real Chromium game panel test. Scripted and seeded checks only; no model inference.
- **hosted-ci-second-audit** (`62b3101`): All four contract jobs passed: Linux 842 passed/18 skipped, including the pinned HumanEval-Decompile fetch and scoring test; Windows 819 passed/41 skipped in 30 minutes under the new 40-minute limit; fifteen native Windows checks; ten Chromium checks; Windows package install, update and restore.
- **windows-project-acceptance** (`62b3101`): windows_project acceptance seals the Windows game target with pinned addresses, rejects the physics mutant at program level and moved region addresses, and accepts the repaired candidate with four recovered regions.
- **audit-second-pass** (`62b3101`): Fixes for the browser automation, backup, Codespaces and dashboard findings in dev/AUDIT.md, each with a regression test.
- **hosted-ci-improvements** (`179524f`): All four contract jobs passed: Linux 828 passed/19 skipped; Windows 807 passed/40 skipped; fifteen native Windows checks; ten Chromium checks; Windows package install, update and restore of the 0.25.0 package. Hosted Windows foundations passed, including the Ghidra project plan.
- **audit-2026-10-21** (`179524f`): Fixes for the findings in dev/AUDIT.md, including the high-severity leak of sealed function cases to workers; each has a regression test that fails on the earlier code where applicable.
- **windows-pe-composition** (`179524f`): The game target built as an x64 Windows console PE composes four recovered regions with original rendering, passes frame/audio cases and rejects the right-wall physics mutant at program level. A static glibc tool composes and runs natively with identical output; a wrong region changes it.
- **public-holdout-import** (`179524f`): HumanEval-Decompile C subset fetched at the pinned commit and SHA-256 (656 rows); problem-level families keep every optimization level of a problem in one split; the benchmark's reference function passes its sealed test natively. The fetch test runs only with HA_BENCHMARK_FETCH=1.
- **hosted-ci-0.25** (`0c475a2`): All four jobs passed: Linux 807 passed/18 skipped; Windows 788 passed/37 skipped after one rerun of an unrelated native compile timeout; fifteen native Windows checks; ten Chromium checks; Windows package install, update and restore. The package was built before the 0.25.0 version label.
- **project-reconstruction-suite** (`0c475a2`): Fixed source-known Stop 3 suite: x86-64 utility with original-code fallback, AArch64 original rebuilt as x86-64, game state/frame/audio target. Thirteen planted incorrect variants rejected, eight only by whole-program checks. The composed utility ran natively with output identical to the original.
- **ghidra-project-plan** (`5a35215`): Fresh Ghidra 12.1.4, REA 6.7.0 and Hermes c0015464f0f4 installations passed every foundation check, including composition over an actual Ghidra callgraph plan (30 functions, four regions recovered).
- **baseline-suite-cc17bf1** (`cc17bf1`): Handoff baseline: all four jobs passed; local Linux full suite 795 passed/18 skipped.

Still required:

- Live GitHub browser registration/device authorization and all five exact native routes.
- Unattended real worker/adviser/reviewer/Ghidra/REA artifact, recovery and acceptance loops.
- Native cross-project learning gains, provider account-wide memory isolation and repeated timing evidence.
- Desktop prerequisite installation through WinGet; hosted Windows package install/update/restore and full foundation installation/basic native adapters have passed.
- Run the managed native workflow through HA using a live authorized account with a configured spending boundary; review representative Linux/Windows target recipes and retained artifacts.
- Run the Stop 3 suite through a live native team with Ghidra-produced plans; broader application targets beyond the fixed suite remain separate scope.
- Measure native learning gains on the HumanEval-Decompile holdout once live routes exist.
- Play-test the Coin cavern example and a real game through a live native worker route (describe_game, play_game, test_game) with frame attachments, and retain the evidence.
- Back up a real folder with a file over 100 MiB to GitHub as release assets (and once with Git LFS), restore it with both scripts, and follow a visibility change made on GitHub; so far only stand-ins and local Git remotes.
- Use the reference tools and the adviser's picture descriptions with signed-in assistants; so far only fixture responses.
<!-- status:end -->

Detailed current and historical evidence is retained in
[`release_status.json`](../_app/release_status.json). Runtime boundaries and setup
instructions are in [README](../README.md); architectural decisions and external
approaches are in [ARCHITECTURE](ARCHITECTURE.md) and
[RELATED_WORK](RELATED_WORK.md).
